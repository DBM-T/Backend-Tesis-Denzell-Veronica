from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import AlertSeverity, AlertStatus, AlertType
from app.schemas.health import HealthResponse
from app.schemas.ml import ModeloMLRead
from app.schemas.operaciones import PurchaseRequestRead, WorkOrderListRead


class AlertaRead(BaseModel):
    id: UUID
    tipo: AlertType
    severidad: AlertSeverity
    estado: AlertStatus
    repuesto_id: UUID | None = None
    sede_id: UUID | None = None
    orden_compra_id: UUID | None = None
    proveedor_id: UUID | None = None
    mensaje: str
    atendido_por: UUID | None = None
    atendido_en: datetime | None = None
    created_at: datetime


class RecomendacionCompraRead(BaseModel):
    id: UUID
    repuesto_id: UUID
    sede_id: UUID
    cantidad_sugerida: int
    fecha_sugerida: date | None = None
    proveedor_sugerido_id: UUID | None = None
    modelo_id: UUID | None = None
    justificacion_ml: str | None = None
    atendida: bool
    created_at: datetime


class DashboardIndicadorRead(BaseModel):
    sede_id: UUID | None = None
    fecha_corte: date
    stock_critico_count: int
    ordenes_en_curso_count: int
    alertas_activas_count: int
    demanda_proyectada_total: Decimal
    source: str


class DashboardRefreshResult(BaseModel):
    procesados: int
    alertas_creadas: int
    recomendaciones_creadas: int
    dashboard_actualizado: int


class DashboardWorkspaceRead(BaseModel):
    snapshot: DashboardIndicadorRead
    alerts: list[AlertaRead]
    work_orders: list[WorkOrderListRead]
    requisitions: list[PurchaseRequestRead]
    models: list[ModeloMLRead]
    health: HealthResponse
