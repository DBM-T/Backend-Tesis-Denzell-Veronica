"""Schemas para endpoints de XGBoost y LightGBM."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ModelType = Literal["xgboost", "lightgbm"]
ModelPurpose = Literal["demanda", "prioridad", "lead_time", "score_proveedor"]


class MLModelCreate(BaseModel):
    nombre: str
    tipo: ModelType
    proposito: ModelPurpose
    version: str
    metricas: dict[str, Any] | None = None
    hiperparametros: dict[str, Any] | None = None
    activo: bool = False


class MLModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nombre: str
    tipo: str
    proposito: str
    version: str
    fecha_entrenamiento: datetime
    metricas: dict[str, Any] | None = None
    hiperparametros: dict[str, Any] | None = None
    activo: bool
    created_at: datetime


class PriorityPredictionRequest(BaseModel):
    ot_id: UUID
    diagnostico_inicial: str | None = None
    tiempo_estimado_horas: Decimal | None = None
    km_ingreso: int | None = None


class PriorityPredictionResponse(BaseModel):
    ot_id: UUID
    prioridad_ml: Literal["alta", "baja"]
    prioridad_confianza: Decimal
    modelo_version: str | None = None


class DemandForecastCreate(BaseModel):
    producto_id: UUID
    sede_id: UUID
    periodo_inicio: date
    periodo_fin: date
    horizonte_dias: int = Field(..., ge=1)
    qty_predicha: Decimal
    intervalo_inf: Decimal | None = None
    intervalo_sup: Decimal | None = None
    rop_calculado: Decimal | None = None
    stock_seguridad_sugerido: Decimal | None = None
    modelo_id: UUID | None = None


class DemandForecastOut(DemandForecastCreate):
    id: UUID
    aprobado_por_gerencia: bool
    aprobado_at: datetime | None = None
    created_at: datetime


class ProviderScoreRequest(BaseModel):
    proveedor_id: UUID
    periodo: str
    entregas_a_tiempo_pct: Decimal | None = None
    tasa_defectos_pct: Decimal | None = None
    componentes_ml: dict[str, Any] | None = None


class ProviderScoreOut(BaseModel):
    id: UUID
    proveedor_id: UUID
    periodo: str
    entregas_a_tiempo_pct: Decimal | None = None
    tasa_defectos_pct: Decimal | None = None
    score_total_ml: Decimal | None = None
    ranking: int | None = None
    modelo_version: str | None = None
    componentes_ml: dict[str, Any] | None = None
    calculado_at: datetime
