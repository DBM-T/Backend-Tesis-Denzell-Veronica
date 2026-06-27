from datetime import datetime, date
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import InventoryMoveType, PriorityML, PurchaseRequestStatus, WorkOrderStatus
from app.schemas.maestros import PaginatedResponse


class WorkOrderCreate(BaseModel):
    cliente_nombre: str = Field(min_length=1, max_length=255)
    cliente_documento: str | None = None
    cliente_telefono: str | None = None
    vehiculo_placa: str | None = None
    vehiculo_marca: str | None = None
    vehiculo_modelo: str | None = None
    vehiculo_anio: int | None = None
    servicio_solicitado: str = Field(min_length=1)
    sede_id: UUID


class WorkOrderRead(WorkOrderCreate):
    id: UUID
    codigo_ot: str
    asesor_id: UUID
    tecnico_id: UUID | None = None
    estado: WorkOrderStatus
    prioridad_ml: PriorityML | None = None
    confianza_ml: float | None = Field(default=None, ge=0, le=1)
    fecha_diagnostico: datetime | None = None
    fecha_completado: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AssignTechnicianRequest(BaseModel):
    tecnico_id: UUID


class RequiredPartInput(BaseModel):
    repuesto_id: UUID
    cantidad: int = Field(gt=0)


class DiagnosticRequest(BaseModel):
    descripcion: str = Field(min_length=1)
    repuestos: list[RequiredPartInput] = Field(min_length=1)


class DiagnosticRead(BaseModel):
    id: UUID
    ot_id: UUID
    tecnico_id: UUID
    descripcion: str
    created_at: datetime


class WorkOrderDiagnosticResponse(BaseModel):
    diagnostico: DiagnosticRead
    repuestos: list[RequiredPartInput]
    orden_trabajo: WorkOrderRead


class PriorityClassificationRequest(BaseModel):
    historial_vehiculo: float = Field(default=0, ge=0)
    tiempo_estimado_horas: float = Field(gt=0)
    disponibilidad_tecnico: float = Field(ge=0, le=1)


class PriorityClassificationResponse(BaseModel):
    prioridad_ml: PriorityML
    confianza_ml: float = Field(ge=0, le=1)
    source: str
    orden_trabajo: WorkOrderRead


class StockAvailabilityItem(BaseModel):
    repuesto_id: UUID
    codigo_sku: str
    nombre: str
    cantidad_requerida: int
    stock_actual: int
    disponible: bool


class StockAvailabilityResponse(BaseModel):
    ot_id: UUID
    estado_sugerido: WorkOrderStatus
    lineas: list[StockAvailabilityItem]


class ChangeWorkOrderStatusRequest(BaseModel):
    estado: WorkOrderStatus


class PurchaseRequestDetailInput(BaseModel):
    repuesto_id: UUID
    cantidad: int = Field(gt=0)


class PurchaseRequestCreate(BaseModel):
    sede_id: UUID
    ot_id: UUID | None = None
    prioridad_heredada: PriorityML | None = None
    detalles: list[PurchaseRequestDetailInput] = Field(min_length=1)


class PurchaseRequestStateUpdate(BaseModel):
    estado: PurchaseRequestStatus


class PurchaseRequestDetailRead(BaseModel):
    id: UUID
    pr_id: UUID
    repuesto_id: UUID
    cantidad: int


class PurchaseRequestRead(BaseModel):
    id: UUID
    codigo_pr: str
    ot_id: UUID | None = None
    sede_id: UUID
    prioridad_heredada: PriorityML | None = None
    estado: PurchaseRequestStatus
    generado_automaticamente: bool
    creado_por: UUID | None = None
    created_at: datetime
    updated_at: datetime
    detalle: list[PurchaseRequestDetailRead] = Field(default_factory=list)


class InventoryMovementCreate(BaseModel):
    repuesto_id: UUID
    sede_id: UUID
    tipo: InventoryMoveType
    cantidad: int = Field(gt=0)
    ot_id: UUID | None = None
    motivo: str | None = None


class InventoryMovementRead(BaseModel):
    id: UUID
    repuesto_id: UUID
    sede_id: UUID
    tipo: InventoryMoveType
    cantidad: int
    ot_id: UUID | None = None
    orden_compra_id: UUID | None = None
    motivo: str | None = None
    registrado_por: UUID
    created_at: datetime


class InventoryMovementFilters(BaseModel):
    repuesto_id: UUID | None = None
    sede_id: UUID | None = None
    tipo: InventoryMoveType | None = None
    desde: date | None = None
    hasta: date | None = None


class CompleteServiceResponse(BaseModel):
    orden_trabajo: WorkOrderRead
    historial_registrado: int


PaginatedPurchaseRequestResponse = PaginatedResponse[PurchaseRequestRead]
PaginatedInventoryMovementResponse = PaginatedResponse[InventoryMovementRead]
