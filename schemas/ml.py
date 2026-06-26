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


class LeadTimePredictionRequest(BaseModel):
    supplier_id: int | str
    sede_id: int | str
    warehouse_id: int | str | None = None
    product_tmpl_id: int | str | None = None
    product_qty: Decimal = Field(..., ge=0)
    price_unit: Decimal | None = Field(None, ge=0)
    supplier_lead_time_decl: Decimal | None = Field(None, ge=0)
    supplier_min_qty: Decimal | None = Field(None, ge=0)
    supplier_price: Decimal | None = Field(None, ge=0)
    planned_lead_time_days: Decimal | None = None
    category: str | None = None
    is_storable: str | bool | None = None
    is_child_sku: str | bool | None = None
    date_order: datetime
    date_approve: datetime
    date_planned: datetime | None = None


class LeadTimePredictionResponse(BaseModel):
    lead_time_days_pred: Decimal
    lead_time_days_pred_rounded: int
    modelo_version: str | None = None
    target: str = "lead_time_days"
    metrics: dict[str, Any] | None = None
    historical_matches_count: int = 0
    historical_matches_shown: int = 0
    historical_matches: list[dict[str, Any]] = Field(default_factory=list)
    insights: dict[str, Any] | None = None


class LeadTimeMatchesResponse(BaseModel):
    total: int
    shown: int
    items: list[dict[str, Any]] = Field(default_factory=list)
