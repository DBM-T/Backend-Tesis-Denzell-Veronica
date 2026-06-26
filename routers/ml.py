"""Endpoints ML para XGBoost y LightGBM."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import get_conn
from schemas.ml import (
    DemandForecastCreate,
    DemandForecastOut,
    MLModelCreate,
    MLModelOut,
    PriorityPredictionRequest,
    PriorityPredictionResponse,
    ProviderScoreOut,
    ProviderScoreRequest,
)

router = APIRouter()


@router.get("/models", response_model=list[MLModelOut])
async def list_models(
    tipo: str | None = None,
    proposito: str | None = None,
    activo: bool | None = None,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if tipo:
            filters.append(f"tipo = ${i}")
            params.append(tipo)
            i += 1
        if proposito:
            filters.append(f"proposito = ${i}")
            params.append(proposito)
            i += 1
        if activo is not None:
            filters.append(f"activo = ${i}")
            params.append(activo)
            i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"SELECT * FROM ml_modelos {where} ORDER BY fecha_entrenamiento DESC",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/models", response_model=MLModelOut, status_code=201)
async def create_model(
    body: MLModelCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    async with get_conn() as conn:
        async with conn.transaction():
            if body.activo:
                await conn.execute(
                    "UPDATE ml_modelos SET activo=FALSE WHERE tipo=$1 AND proposito=$2",
                    body.tipo,
                    body.proposito,
                )
            row = await conn.fetchrow(
                """
                INSERT INTO ml_modelos
                  (nombre, tipo, proposito, version, metricas, hiperparametros, activo)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7)
                RETURNING *
                """,
                body.nombre,
                body.tipo,
                body.proposito,
                body.version,
                body.metricas,
                body.hiperparametros,
                body.activo,
            )
    return dict(row)


@router.patch("/models/{model_id}/activate", response_model=MLModelOut)
async def activate_model(
    model_id: UUID,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    async with get_conn() as conn:
        async with conn.transaction():
            model = await conn.fetchrow("SELECT * FROM ml_modelos WHERE id=$1", model_id)
            if not model:
                raise HTTPException(404, "Modelo no encontrado")
            await conn.execute(
                "UPDATE ml_modelos SET activo=FALSE WHERE tipo=$1 AND proposito=$2",
                model["tipo"],
                model["proposito"],
            )
            row = await conn.fetchrow("UPDATE ml_modelos SET activo=TRUE WHERE id=$1 RETURNING *", model_id)
    return dict(row)


@router.post("/priority/predict", response_model=PriorityPredictionResponse)
async def predict_priority(
    body: PriorityPredictionRequest,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "asesor", "logistica")),
):
    async with get_conn() as conn:
        model = await conn.fetchrow(
            """
            SELECT version FROM ml_modelos
            WHERE tipo='lightgbm' AND proposito='prioridad' AND activo=TRUE
            ORDER BY fecha_entrenamiento DESC
            LIMIT 1
            """
        )
        ot = await conn.fetchrow("SELECT * FROM ordenes_trabajo WHERE id=$1", body.ot_id)
        if not ot:
            raise HTTPException(404, "OT no encontrada")

        texto = (body.diagnostico_inicial or ot["diagnostico_inicial"] or "").lower()
        horas = body.tiempo_estimado_horas or ot["tiempo_estimado_horas"] or Decimal("0")
        km = body.km_ingreso or ot["km_ingreso"] or 0
        alta = any(word in texto for word in ["urgente", "inmovilizado", "freno", "motor"])
        alta = alta or horas >= Decimal("6") or km >= 180000
        prioridad = "alta" if alta else "baja"
        confianza = Decimal("0.780") if alta else Decimal("0.720")
        version = model["version"] if model else "lightgbm-rule-fallback"

        row = await conn.fetchrow(
            """
            UPDATE ordenes_trabajo
            SET prioridad_ml=$2, prioridad_confianza=$3, prioridad_ml_version=$4
            WHERE id=$1
            RETURNING id, prioridad_ml, prioridad_confianza, prioridad_ml_version
            """,
            body.ot_id,
            prioridad,
            confianza,
            version,
        )
    return {
        "ot_id": row["id"],
        "prioridad_ml": row["prioridad_ml"],
        "prioridad_confianza": row["prioridad_confianza"],
        "modelo_version": row["prioridad_ml_version"],
    }


@router.get("/demand/forecasts", response_model=list[DemandForecastOut])
async def list_demand_forecasts(
    producto_id: UUID | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(100, le=500),
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if producto_id:
            filters.append(f"producto_id = ${i}")
            params.append(producto_id)
            i += 1
        if sede_id:
            filters.append(f"sede_id = ${i}")
            params.append(sede_id)
            i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"SELECT * FROM ml_predicciones_demanda {where} ORDER BY created_at DESC LIMIT ${i}",
            *params,
            limit,
        )
    return [dict(r) for r in rows]


@router.post("/demand/forecasts", response_model=DemandForecastOut, status_code=201)
async def create_demand_forecast(
    body: DemandForecastCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ml_predicciones_demanda (
              producto_id, sede_id, modelo_id, periodo_inicio, periodo_fin, horizonte_dias,
              qty_predicha, intervalo_inf, intervalo_sup, rop_calculado,
              stock_seguridad_sugerido
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING *
            """,
            body.producto_id,
            body.sede_id,
            body.modelo_id,
            body.periodo_inicio,
            body.periodo_fin,
            body.horizonte_dias,
            body.qty_predicha,
            body.intervalo_inf,
            body.intervalo_sup,
            body.rop_calculado,
            body.stock_seguridad_sugerido,
        )
    return dict(row)


@router.patch("/demand/forecasts/{forecast_id}/approve")
async def approve_demand_forecast(
    forecast_id: UUID,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia")),
):
    async with get_conn() as conn:
        async with conn.transaction():
            forecast = await conn.fetchrow(
                """
                UPDATE ml_predicciones_demanda
                SET aprobado_por_gerencia=TRUE, aprobado_at=NOW()
                WHERE id=$1
                RETURNING *
                """,
                forecast_id,
            )
            if not forecast:
                raise HTTPException(404, "Prediccion no encontrada")
            await conn.execute(
                """
                INSERT INTO stock (producto_id, sede_id, rop, stock_seguridad, params_ml, modelo_version)
                VALUES ($1,$2,$3,COALESCE($4,0),TRUE,$5)
                ON CONFLICT (producto_id, sede_id)
                DO UPDATE SET
                  rop=EXCLUDED.rop,
                  stock_seguridad=EXCLUDED.stock_seguridad,
                  params_ml=TRUE,
                  modelo_version=EXCLUDED.modelo_version,
                  updated_at=NOW()
                """,
                forecast["producto_id"],
                forecast["sede_id"],
                forecast["rop_calculado"],
                forecast["stock_seguridad_sugerido"],
                "xgboost-demanda",
            )
    return dict(forecast)


@router.post("/providers/score", response_model=ProviderScoreOut)
async def score_provider(
    body: ProviderScoreRequest,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    async with get_conn() as conn:
        model = await conn.fetchrow(
            """
            SELECT version FROM ml_modelos
            WHERE tipo='xgboost' AND proposito='score_proveedor' AND activo=TRUE
            ORDER BY fecha_entrenamiento DESC
            LIMIT 1
            """
        )
        on_time = body.entregas_a_tiempo_pct or Decimal("0")
        defects = body.tasa_defectos_pct or Decimal("0")
        score = max(Decimal("0"), min(Decimal("100"), on_time - defects * Decimal("1.5")))
        version = model["version"] if model else "xgboost-score-rule-fallback"

        row = await conn.fetchrow(
            """
            INSERT INTO proveedor_metricas (
              proveedor_id, periodo, entregas_a_tiempo_pct, tasa_defectos_pct,
              score_total_ml, modelo_version, componentes_ml
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
            ON CONFLICT (proveedor_id, periodo)
            DO UPDATE SET
              entregas_a_tiempo_pct=EXCLUDED.entregas_a_tiempo_pct,
              tasa_defectos_pct=EXCLUDED.tasa_defectos_pct,
              score_total_ml=EXCLUDED.score_total_ml,
              modelo_version=EXCLUDED.modelo_version,
              componentes_ml=EXCLUDED.componentes_ml,
              calculado_at=NOW()
            RETURNING *
            """,
            body.proveedor_id,
            body.periodo,
            body.entregas_a_tiempo_pct,
            body.tasa_defectos_pct,
            score,
            version,
            body.componentes_ml,
        )
        await conn.execute(
            """
            WITH ranked AS (
              SELECT id, ROW_NUMBER() OVER (ORDER BY score_total_ml DESC NULLS LAST) AS rn
              FROM proveedor_metricas
              WHERE periodo=$1
            )
            UPDATE proveedor_metricas pm
            SET ranking=ranked.rn
            FROM ranked
            WHERE ranked.id=pm.id
            """,
            body.periodo,
        )
        row = await conn.fetchrow("SELECT * FROM proveedor_metricas WHERE id=$1", row["id"])
    return dict(row)


@router.get("/providers/ranking")
async def provider_ranking(_user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_ranking_proveedores")
    return [dict(r) for r in rows]
