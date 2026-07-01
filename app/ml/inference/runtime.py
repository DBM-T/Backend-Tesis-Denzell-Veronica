from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil, expm1
from pathlib import Path
from typing import Any

import joblib
from starlette.concurrency import run_in_threadpool

try:
    from xgboost import XGBRegressor
except Exception:  # pragma: no cover - compatibilidad cuando xgboost no esta disponible
    XGBRegressor = None

from app.core.config import get_settings
from app.core.supabase_client import create_service_role_client
from app.schemas.enums import MLModelType, PriorityML, PurchaseChannel


@dataclass(slots=True)
class ActiveModel:
    model_id: str
    tipo_modelo: MLModelType
    version: str
    artifact_path: Path | None
    artifact: Any | None = None


@dataclass(slots=True)
class PrioridadOTFeatures:
    ot_id: str
    servicio_solicitado: str
    historial_vehiculo: float
    tiempo_estimado_horas: float
    disponibilidad_tecnico: float


@dataclass(slots=True)
class PrioridadOTResult:
    prioridad_ml: PriorityML
    confianza_ml: float
    modelo_id: str | None
    version_modelo: str | None
    source: str


@dataclass(slots=True)
class RankingProveedorCandidate:
    proveedor_id: str
    repuesto_id: str
    tasa_entrega_a_tiempo: float | None
    tasa_defectos: float | None
    precio_promedio: float | None
    volumen_compras_previas: float | None
    lead_time_estimado_dias: float | None
    canal_preferido: str | None
    precio_ofrecido: float | None = None
    disponibilidad: bool | None = None
    lead_time_ofrecido_dias: float | None = None


@dataclass(slots=True)
class RankingProveedorItem:
    proveedor_id: str
    repuesto_id: str
    score_total_ml: float
    ranking_posicion: int
    canal_sugerido_ml: PurchaseChannel | None


@dataclass(slots=True)
class DemandaFeatures:
    repuesto_id: str
    sede_id: str
    promedio_consumo: float
    consumo_90d: float
    tendencia: float
    stock_actual: float | None
    stock_minimo: float | None
    lead_time_base_dias: float | None


@dataclass(slots=True)
class DemandaResult:
    demanda_proyectada: float
    lead_time_estimado_dias: float
    punto_reorden_sugerido: int
    nivel_riesgo: str
    confianza_ml: float
    modelo_id: str | None
    version_modelo: str | None
    source: str


@dataclass(slots=True)
class LeadTimeFeatures:
    compra_id: str
    proveedor_id: str | None
    lead_time_estimado_dias: float
    monto_total: float
    cantidad_lineas: float
    cantidad_total_unidades: float
    mes_pedido: float


@dataclass(slots=True)
class LeadTimeResult:
    lead_time_predicho_dias: float
    lead_time_predicho_redondeado_dias: int
    confianza_ml: float
    modelo_id: str | None
    version_modelo: str | None
    source: str


MODEL_CACHE: dict[MLModelType, ActiveModel] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _model_path(tipo_modelo: MLModelType, version: str) -> Path:
    return get_settings().ml_models_dir / tipo_modelo.value / version / "model.joblib"


def _fallback_xgboost_path(tipo_modelo: MLModelType, version: str) -> Path:
    return get_settings().ml_models_dir / tipo_modelo.value / version / "model.json"


async def _load_artifact(tipo: MLModelType, version: str) -> tuple[Any | None, Path | None]:
    artifact = None
    loaded_from: Path | None = None
    artifact_path = _model_path(tipo, version)
    if tipo.value.startswith("xgboost_") and XGBRegressor is not None:
        fallback_path = _fallback_xgboost_path(tipo, version)
        if fallback_path.exists():
            try:
                booster = XGBRegressor()
                booster.load_model(fallback_path)
                artifact = booster
                loaded_from = fallback_path
            except Exception:
                artifact = None
    if artifact is None and artifact_path.exists():
        try:
            artifact = await run_in_threadpool(joblib.load, artifact_path)
            loaded_from = artifact_path
        except Exception:
            artifact = None
    return artifact, loaded_from


async def _preload_local_models() -> None:
    models_dir = get_settings().ml_models_dir
    for tipo in MLModelType:
        if tipo in MODEL_CACHE and MODEL_CACHE[tipo].artifact is not None:
            continue
        model_root = models_dir / tipo.value
        if not model_root.exists():
            continue
        versions = sorted((path.name for path in model_root.iterdir() if path.is_dir()), reverse=True)
        for version in versions:
            artifact, loaded_from = await _load_artifact(tipo, version)
            if artifact is None:
                continue
            MODEL_CACHE[tipo] = ActiveModel(
                model_id=f"local-{tipo.value}-{version}",
                tipo_modelo=tipo,
                version=version,
                artifact_path=loaded_from,
                artifact=artifact,
            )
            break


async def preload_active_models() -> None:
    MODEL_CACHE.clear()
    try:
        client = await create_service_role_client()
        response = await client.table("modelos_ml").select(
            "id,tipo_modelo,version,activo"
        ).eq("activo", True).execute()
    except Exception:
        await _preload_local_models()
        return

    for row in response.data or []:
        tipo = MLModelType(row["tipo_modelo"])
        artifact, loaded_from = await _load_artifact(tipo, row["version"])
        MODEL_CACHE[tipo] = ActiveModel(
            model_id=str(row["id"]),
            tipo_modelo=tipo,
            version=row["version"],
            artifact_path=loaded_from,
            artifact=artifact,
        )
    await _preload_local_models()


def get_active_model(tipo_modelo: MLModelType) -> ActiveModel | None:
    return MODEL_CACHE.get(tipo_modelo)


def _priority_thresholds() -> tuple[float, float]:
    settings = get_settings()
    low = float(settings.ml_priority_low_threshold)
    high = float(settings.ml_priority_high_threshold)
    if low >= high:
        low, high = 0.10, 0.90
    return low, high


def _score_to_priority(score: float) -> tuple[PriorityML, float]:
    score = max(0.0, min(score, 0.999))
    low_threshold, high_threshold = _priority_thresholds()
    if score >= high_threshold:
        return PriorityML.ALTA, round(score, 4)
    if score <= low_threshold:
        return PriorityML.BAJA, round(1 - score, 4)

    abstention_confidence = max(high_threshold - score, score - low_threshold) / max(high_threshold - low_threshold, 1e-9)
    return PriorityML.REVISAR, round(1 - abstention_confidence, 4)


def predecir_prioridad_ot(features: PrioridadOTFeatures) -> PrioridadOTResult:
    model = get_active_model(MLModelType.lightgbm_prioridad)
    if model and model.artifact is not None:
        try:
            payload = [[
                features.historial_vehiculo,
                features.tiempo_estimado_horas,
                features.disponibilidad_tecnico,
            ]]
            if hasattr(model.artifact, "predict_proba"):
                probabilities = model.artifact.predict_proba(payload)[0]
                positive = float(probabilities[1]) if len(probabilities) > 1 else float(probabilities[0])
                priority, confidence = _score_to_priority(positive)
                return PrioridadOTResult(priority, confidence, model.model_id, model.version, "lightgbm_selective")
            if hasattr(model.artifact, "predict"):
                prediction = model.artifact.predict(payload)[0]
                priority = PriorityML.ALTA if str(prediction).upper() in {"1", "ALTA", "TRUE"} else PriorityML.BAJA
                return PrioridadOTResult(priority, 0.75, model.model_id, model.version, "lightgbm_binary")
        except Exception:
            pass

    score = 0.05
    if features.tiempo_estimado_horas >= 6:
        score += 0.35
    if features.historial_vehiculo >= 3:
        score += 0.25
    if features.disponibilidad_tecnico <= 0.3:
        score += 0.25
    if "motor" in features.servicio_solicitado.lower():
        score += 0.15
    priority, confidence = _score_to_priority(score)
    return PrioridadOTResult(priority, confidence, model.model_id if model else None, model.version if model else None, "heuristic_selective")


def _score_provider(candidate: RankingProveedorCandidate) -> float:
    score = 0.0
    score += (candidate.tasa_entrega_a_tiempo or 0) * 0.40
    score -= (candidate.tasa_defectos or 0) * 0.20
    score -= (candidate.lead_time_estimado_dias or 0) * 1.5
    score += (candidate.volumen_compras_previas or 0) * 0.02
    if candidate.precio_promedio:
        score -= candidate.precio_promedio / 1000
    if candidate.precio_ofrecido:
        score -= candidate.precio_ofrecido / 1000
    if candidate.disponibilidad is False:
        score -= 1.0
    return round(score, 4)


def _provider_payload(candidate: RankingProveedorCandidate) -> list[float]:
    return [
        float(candidate.tasa_entrega_a_tiempo or 0),
        float(candidate.tasa_defectos or 0),
        float(candidate.precio_promedio or 0),
        float(candidate.volumen_compras_previas or 0),
        float(candidate.lead_time_estimado_dias or 0),
    ]


def predecir_ranking_proveedores(candidates: list[RankingProveedorCandidate]) -> list[RankingProveedorItem]:
    model = get_active_model(MLModelType.xgboost_proveedor)
    scored: list[tuple[float, RankingProveedorCandidate]] = []
    for candidate in candidates:
        score: float | None = None
        if model and model.artifact is not None:
            try:
                prediction = model.artifact.predict([_provider_payload(candidate)])
                score = float(prediction[0])
            except Exception:
                score = None
        if score is None:
            score = _score_provider(candidate)
        scored.append((round(score, 6), candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    items: list[RankingProveedorItem] = []
    for position, (score, candidate) in enumerate(scored, start=1):
        items.append(
            RankingProveedorItem(
                proveedor_id=candidate.proveedor_id,
                repuesto_id=candidate.repuesto_id,
                score_total_ml=score,
                ranking_posicion=position,
                canal_sugerido_ml=PurchaseChannel(candidate.canal_preferido) if candidate.canal_preferido else None,
            )
        )
    return items


def predecir_demanda(features: DemandaFeatures) -> DemandaResult:
    model = get_active_model(MLModelType.xgboost_demanda)
    if model and model.artifact is not None:
        try:
            payload = [[
                features.promedio_consumo,
                features.consumo_90d,
                features.tendencia,
                features.stock_actual or 0,
                features.stock_minimo or 0,
                features.lead_time_base_dias or 0,
            ]]
            if hasattr(model.artifact, "predict"):
                prediction = max(float(model.artifact.predict(payload)[0]), 0.0)
                lead = max(1.0, features.lead_time_base_dias or 7.0)
                stock_actual = max(features.stock_actual or 0, 0)
                stock_minimo = max(features.stock_minimo or 0, 0)
                demanda_diaria = max(prediction, 0.0) / 30.0
                rondon = max(1, int(ceil((demanda_diaria * lead) + stock_minimo)))
                if stock_actual <= stock_minimo or stock_actual < rondon:
                    riesgo = "alto"
                elif stock_actual < (rondon * 1.25):
                    riesgo = "medio"
                else:
                    riesgo = "bajo"
                confidence = 0.8 if riesgo != "medio" else 0.72
                return DemandaResult(
                    round(prediction, 2),
                    round(lead, 2),
                    rondon,
                    riesgo,
                    confidence,
                    model.model_id,
                    model.version,
                    "xgboost_tweedie_raw",
                )
        except Exception:
            pass

    projected = max(features.promedio_consumo, features.consumo_90d / 3.0, 1.0)
    projected += max(features.tendencia, 0) * 0.4
    lead = max(1.0, features.lead_time_base_dias or 7.0)
    rondon = max(1, int(round(projected * max(lead, 1.0) / 7.0)))
    current_stock = features.stock_actual or 0
    if current_stock <= (features.stock_minimo or 0):
        risk = "alto"
    elif current_stock <= rondon:
        risk = "medio"
    else:
        risk = "bajo"
    confidence = 0.65 if risk == "medio" else 0.75
    return DemandaResult(round(projected, 2), round(lead, 2), rondon, risk, confidence, model.model_id if model else None, model.version if model else None, "heuristic_fallback")


def predecir_lead_time_compra(features: LeadTimeFeatures) -> LeadTimeResult:
    model = get_active_model(MLModelType.xgboost_lead_time)
    if model and model.artifact is not None:
        try:
            payload = [[
                features.lead_time_estimado_dias,
                features.monto_total,
                features.cantidad_lineas,
                features.cantidad_total_unidades,
                features.mes_pedido,
            ]]
            if hasattr(model.artifact, "predict"):
                raw_prediction = float(model.artifact.predict(payload)[0])
                prediction = max(expm1(raw_prediction), 0.0)
                rounded = max(0, int(round(prediction)))
                return LeadTimeResult(
                    lead_time_predicho_dias=round(prediction, 2),
                    lead_time_predicho_redondeado_dias=rounded,
                    confianza_ml=0.74,
                    modelo_id=model.model_id,
                    version_modelo=model.version,
                    source="xgboost_log1p",
                )
        except Exception:
            pass

    baseline = max(features.lead_time_estimado_dias or 0.0, 0.0)
    if baseline == 0:
        baseline = 1.0 if features.cantidad_lineas <= 2 else 2.0
    return LeadTimeResult(
        lead_time_predicho_dias=round(baseline, 2),
        lead_time_predicho_redondeado_dias=max(0, int(round(baseline))),
        confianza_ml=0.6,
        modelo_id=model.model_id if model else None,
        version_modelo=model.version if model else None,
        source="heuristic_fallback",
    )
