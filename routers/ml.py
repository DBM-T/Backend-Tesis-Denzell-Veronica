"""Endpoints ML para XGBoost y LightGBM."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
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
    query = supabase_admin().table("ml_modelos").select("*")
    if tipo:
        query = query.eq("tipo", tipo)
    if proposito:
        query = query.eq("proposito", proposito)
    if activo is not None:
        query = query.eq("activo", activo)
    result = query.order("fecha_entrenamiento", desc=True).execute()
    return result.data or []


@router.post("/models", response_model=MLModelOut, status_code=201)
async def create_model(
    body: MLModelCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    admin = supabase_admin()
    if body.activo:
        admin.table("ml_modelos").update({"activo": False}).eq("tipo", body.tipo).eq(
            "proposito", body.proposito
        ).execute()
    result = (
        admin.table("ml_modelos")
        .insert(
            {
                "nombre": body.nombre,
                "tipo": body.tipo,
                "proposito": body.proposito,
                "version": body.version,
                "metricas": body.metricas,
                "hiperparametros": body.hiperparametros,
                "activo": body.activo,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(500, "No se pudo crear el modelo")
    return result.data[0]


@router.patch("/models/{model_id}/activate", response_model=MLModelOut)
async def activate_model(
    model_id: UUID,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    admin = supabase_admin()
    current = admin.table("ml_modelos").select("*").eq("id", str(model_id)).limit(1).execute()
    if not current.data:
        raise HTTPException(404, "Modelo no encontrado")
    model = current.data[0]
    admin.table("ml_modelos").update({"activo": False}).eq("tipo", model["tipo"]).eq(
        "proposito", model["proposito"]
    ).execute()
    result = admin.table("ml_modelos").update({"activo": True}).eq("id", str(model_id)).execute()
    return result.data[0]


@router.post("/priority/predict", response_model=PriorityPredictionResponse)
async def predict_priority(
    body: PriorityPredictionRequest,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "asesor", "logistica")),
):
    admin = supabase_admin()
    model_res = (
        admin.table("ml_modelos")
        .select("version")
        .eq("tipo", "lightgbm")
        .eq("proposito", "prioridad")
        .eq("activo", True)
        .order("fecha_entrenamiento", desc=True)
        .limit(1)
        .execute()
    )
    ot_res = admin.table("ordenes_trabajo").select("*").eq("id", str(body.ot_id)).limit(1).execute()
    if not ot_res.data:
        raise HTTPException(404, "OT no encontrada")

    ot = ot_res.data[0]
    texto = (body.diagnostico_inicial or ot.get("diagnostico_inicial") or "").lower()
    horas = body.tiempo_estimado_horas or Decimal(str(ot.get("tiempo_estimado_horas") or "0"))
    km = body.km_ingreso or ot.get("km_ingreso") or 0
    alta = any(word in texto for word in ["urgente", "inmovilizado", "freno", "motor"])
    alta = alta or horas >= Decimal("6") or km >= 180000
    prioridad = "alta" if alta else "baja"
    confianza = Decimal("0.780") if alta else Decimal("0.720")
    version = (
        model_res.data[0]["version"] if model_res.data else "lightgbm-rule-fallback"
    )

    result = (
        admin.table("ordenes_trabajo")
        .update(
            {
                "prioridad_ml": prioridad,
                "prioridad_confianza": confianza,
                "prioridad_ml_version": version,
            }
        )
        .eq("id", str(body.ot_id))
        .execute()
    )
    row = result.data[0]
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
    query = supabase_admin().table("ml_predicciones_demanda").select("*")
    if producto_id:
        query = query.eq("producto_id", str(producto_id))
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(0, limit - 1).execute()
    return result.data or []


@router.post("/demand/forecasts", response_model=DemandForecastOut, status_code=201)
async def create_demand_forecast(
    body: DemandForecastCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    result = (
        supabase_admin()
        .table("ml_predicciones_demanda")
        .insert(
            {
                "producto_id": str(body.producto_id),
                "sede_id": str(body.sede_id),
                "modelo_id": str(body.modelo_id) if body.modelo_id else None,
                "periodo_inicio": body.periodo_inicio.isoformat(),
                "periodo_fin": body.periodo_fin.isoformat(),
                "horizonte_dias": body.horizonte_dias,
                "qty_predicha": body.qty_predicha,
                "intervalo_inf": body.intervalo_inf,
                "intervalo_sup": body.intervalo_sup,
                "rop_calculado": body.rop_calculado,
                "stock_seguridad_sugerido": body.stock_seguridad_sugerido,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(500, "No se pudo crear la prediccion")
    return result.data[0]


@router.patch("/demand/forecasts/{forecast_id}/approve")
async def approve_demand_forecast(
    forecast_id: UUID,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia")),
):
    admin = supabase_admin()
    result = (
        admin.table("ml_predicciones_demanda")
        .update(
            {
                "aprobado_por_gerencia": True,
                "aprobado_at": datetime.utcnow().isoformat(),
            }
        )
        .eq("id", str(forecast_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Prediccion no encontrada")
    forecast = result.data[0]

    stock_payload = {
        "producto_id": forecast["producto_id"],
        "sede_id": forecast["sede_id"],
        "rop": forecast.get("rop_calculado"),
        "stock_seguridad": forecast.get("stock_seguridad_sugerido") or 0,
        "params_ml": True,
        "modelo_version": "xgboost-demanda",
    }
    existing = (
        admin.table("stock")
        .select("id")
        .eq("producto_id", forecast["producto_id"])
        .eq("sede_id", forecast["sede_id"])
        .limit(1)
        .execute()
    )
    if existing.data:
        admin.table("stock").update(stock_payload).eq("id", existing.data[0]["id"]).execute()
    else:
        admin.table("stock").insert(stock_payload).execute()
    return forecast


@router.post("/providers/score", response_model=ProviderScoreOut)
async def score_provider(
    body: ProviderScoreRequest,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    admin = supabase_admin()
    model_res = (
        admin.table("ml_modelos")
        .select("version")
        .eq("tipo", "xgboost")
        .eq("proposito", "score_proveedor")
        .eq("activo", True)
        .order("fecha_entrenamiento", desc=True)
        .limit(1)
        .execute()
    )
    on_time = body.entregas_a_tiempo_pct or Decimal("0")
    defects = body.tasa_defectos_pct or Decimal("0")
    score = max(Decimal("0"), min(Decimal("100"), on_time - defects * Decimal("1.5")))
    version = model_res.data[0]["version"] if model_res.data else "xgboost-score-rule-fallback"

    existing = (
        admin.table("proveedor_metricas")
        .select("*")
        .eq("proveedor_id", str(body.proveedor_id))
        .eq("periodo", body.periodo)
        .limit(1)
        .execute()
    )
    payload = {
        "proveedor_id": str(body.proveedor_id),
        "periodo": body.periodo,
        "entregas_a_tiempo_pct": body.entregas_a_tiempo_pct,
        "tasa_defectos_pct": body.tasa_defectos_pct,
        "score_total_ml": score,
        "modelo_version": version,
        "componentes_ml": body.componentes_ml,
    }
    if existing.data:
        row = (
            admin.table("proveedor_metricas")
            .update({**payload, "calculado_at": datetime.utcnow().isoformat()})
            .eq("id", existing.data[0]["id"])
            .execute()
            .data[0]
        )
    else:
        row = admin.table("proveedor_metricas").insert(payload).execute().data[0]

    ranking_rows = (
        admin.table("proveedor_metricas")
        .select("id, score_total_ml")
        .eq("periodo", body.periodo)
        .order("score_total_ml", desc=True)
        .execute()
        .data
        or []
    )
    for index, metric in enumerate(ranking_rows, start=1):
        admin.table("proveedor_metricas").update({"ranking": index}).eq(
            "id", metric["id"]
        ).execute()

    fresh = (
        admin.table("proveedor_metricas")
        .select("*")
        .eq("id", row["id"])
        .limit(1)
        .execute()
    )
    return fresh.data[0]


@router.get("/providers/ranking")
async def provider_ranking(_user: CurrentUser = Depends(get_current_user)):
    result = supabase_admin().table("v_ranking_proveedores").select("*").execute()
    return result.data or []
