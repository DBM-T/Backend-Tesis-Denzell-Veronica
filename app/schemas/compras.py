from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import PurchaseChannel, PurchaseOrderStatus, RFQStatus
from app.schemas.maestros import ProveedorRead
from app.schemas.operaciones import PurchaseRequestRead


class RFQCreate(BaseModel):
    pr_id: UUID
    proveedor_id: UUID
    enviado_automaticamente: bool = False
    fecha_limite_respuesta: date | None = None
    condiciones_comerciales: str | None = None


class RFQRead(BaseModel):
    id: UUID
    codigo_rfq: str
    pr_id: UUID
    proveedor_id: UUID
    fecha_limite_respuesta: date | None = None
    condiciones_comerciales: str | None = None
    estado: RFQStatus
    enviado_automaticamente: bool
    creado_por: UUID | None = None
    created_at: datetime
    detalle: list["RFQDetalleRead"] = Field(default_factory=list)


class RFQDetalleCreateItem(BaseModel):
    repuesto_id: UUID
    cantidad: int = Field(gt=0)


class RFQDetalleRead(BaseModel):
    id: UUID
    rfq_id: UUID
    repuesto_id: UUID
    cantidad: int
    codigo_sku: str | None = None
    nombre_repuesto: str | None = None


class RFQRespuestaCreateItem(BaseModel):
    repuesto_id: UUID
    precio_unitario: Decimal = Field(ge=0)
    disponibilidad: bool = True
    lead_time_ofrecido_dias: int | None = Field(default=None, ge=0)


class RFQRespuestaCreate(BaseModel):
    respuestas: list[RFQRespuestaCreateItem] = Field(min_length=1)


class RFQRespuestaRead(BaseModel):
    id: UUID
    rfq_id: UUID
    repuesto_id: UUID
    precio_unitario: Decimal
    disponibilidad: bool
    lead_time_ofrecido_dias: int | None = None
    registrado_por: UUID | None = None
    created_at: datetime


class RFQStatusUpdate(BaseModel):
    estado: RFQStatus


class RankingProveedorRead(BaseModel):
    id: UUID
    rfq_id: UUID | None = None
    proveedor_id: UUID
    repuesto_id: UUID | None = None
    score_total_ml: Decimal
    ranking_posicion: int
    canal_sugerido_ml: PurchaseChannel | None = None
    version_modelo: str | None = None
    created_at: datetime
    proveedor_razon_social: str | None = None
    repuesto_codigo_sku: str | None = None


class AprobacionProveedorCreate(BaseModel):
    rfq_id: UUID
    proveedor_seleccionado_id: UUID
    justificacion: str | None = None


class AprobacionProveedorRead(BaseModel):
    id: UUID
    rfq_id: UUID
    proveedor_seleccionado_id: UUID
    coincide_con_recomendacion_ml: bool
    justificacion: str | None = None
    aprobado_por: UUID
    created_at: datetime


class OrdenCompraDetalleCreateItem(BaseModel):
    repuesto_id: UUID
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0)


class OrdenCompraCreate(BaseModel):
    aprobacion_id: UUID
    condiciones_pago: str | None = None
    fecha_entrega_comprometida: date | None = None
    canal_compra: PurchaseChannel | None = None


class OrdenCompraRead(BaseModel):
    id: UUID
    codigo_oc: str
    pr_id: UUID | None = None
    ot_id: UUID | None = None
    proveedor_id: UUID
    rfq_id: UUID | None = None
    monto_total: Decimal
    condiciones_pago: str | None = None
    fecha_entrega_comprometida: date | None = None
    canal_compra: PurchaseChannel | None = None
    estado: PurchaseOrderStatus
    requiere_aprobacion_gerencia: bool
    aprobado_por_gerencia_id: UUID | None = None
    fecha_aprobacion_gerencia: datetime | None = None
    creado_por: UUID | None = None
    created_at: datetime
    updated_at: datetime
    detalle: list["OrdenCompraDetalleRead"] = Field(default_factory=list)


class OrdenCompraDetalleRead(BaseModel):
    id: UUID
    oc_id: UUID
    repuesto_id: UUID
    cantidad: int
    precio_unitario: Decimal
    codigo_sku: str | None = None
    nombre_repuesto: str | None = None


class OrdenCompraEstadoUpdate(BaseModel):
    estado: PurchaseOrderStatus


class OrdenCompraRecepcionDetalleCreateItem(BaseModel):
    repuesto_id: UUID
    cantidad_recibida: int = Field(ge=0)
    conformidad: str
    evidencia_url: str | None = None
    observaciones: str | None = None

    @model_validator(mode="after")
    def validate_no_conforme(self):
        if self.conformidad == "no_conforme" and (not self.evidencia_url or not self.observaciones):
            raise ValueError("evidencia_url y observaciones son obligatorios si la conformidad es no_conforme")
        return self


class OrdenCompraRecepcionCreate(BaseModel):
    detalles: list[OrdenCompraRecepcionDetalleCreateItem] = Field(min_length=1)


class RecepcionOCDetalleRead(BaseModel):
    id: UUID
    recepcion_id: UUID
    repuesto_id: UUID
    cantidad_recibida: int
    conformidad: str
    evidencia_url: str | None = None
    observaciones: str | None = None


class RecepcionOCRead(BaseModel):
    id: UUID
    oc_id: UUID
    fecha_recepcion: datetime
    recibido_por: UUID
    created_at: datetime
    detalle: list[RecepcionOCDetalleRead] = Field(default_factory=list)


class RecepcionOCCreateResponse(BaseModel):
    recepcion: RecepcionOCRead
    oc: OrdenCompraRead


class ComprasWorkspaceRead(BaseModel):
    requisiciones: list[PurchaseRequestRead] = Field(default_factory=list)
    proveedores: list[ProveedorRead] = Field(default_factory=list)
    rfqs: list[RFQRead] = Field(default_factory=list)
    aprobaciones: list[AprobacionProveedorRead] = Field(default_factory=list)
    ordenes_compra: list[OrdenCompraRead] = Field(default_factory=list)


RFQRead.model_rebuild()
OrdenCompraRead.model_rebuild()
RecepcionOCRead.model_rebuild()
