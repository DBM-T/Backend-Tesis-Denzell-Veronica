from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.enums import PurchaseChannel, UserStatus


T = TypeVar("T")


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int | None = None


class CategoriaBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    categoria_padre_id: UUID | None = None


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    categoria_padre_id: UUID | None = None


class CategoriaRead(CategoriaBase):
    id: UUID
    created_at: datetime


class CategoriaTreeNode(CategoriaRead):
    children: list["CategoriaTreeNode"] = Field(default_factory=list)


class ProveedorBase(BaseModel):
    razon_social: str = Field(min_length=1, max_length=255)
    ruc: str | None = Field(default=None, min_length=8, max_length=20)
    contacto_nombre: str | None = None
    telefono: str | None = None
    email: EmailStr | None = None
    direccion: str | None = None
    condiciones_pago: str | None = None
    lead_time_estimado_dias: int | None = Field(default=None, ge=0)
    canal_preferido: PurchaseChannel | None = None
    tasa_entrega_a_tiempo: Decimal | None = Field(default=None, ge=0, le=100)
    tasa_defectos: Decimal | None = Field(default=None, ge=0, le=100)
    precio_promedio: Decimal | None = Field(default=None, ge=0)
    volumen_compras_previas: int | None = Field(default=None, ge=0)


class ProveedorCreate(ProveedorBase):
    pass


class ProveedorUpdate(BaseModel):
    razon_social: str | None = Field(default=None, min_length=1, max_length=255)
    ruc: str | None = Field(default=None, min_length=8, max_length=20)
    contacto_nombre: str | None = None
    telefono: str | None = None
    email: EmailStr | None = None
    direccion: str | None = None
    condiciones_pago: str | None = None
    lead_time_estimado_dias: int | None = Field(default=None, ge=0)
    canal_preferido: PurchaseChannel | None = None
    estado: UserStatus | None = None
    tasa_entrega_a_tiempo: Decimal | None = Field(default=None, ge=0, le=100)
    tasa_defectos: Decimal | None = Field(default=None, ge=0, le=100)
    precio_promedio: Decimal | None = Field(default=None, ge=0)
    volumen_compras_previas: int | None = Field(default=None, ge=0)


class ProveedorRead(ProveedorBase):
    id: UUID
    estado: UserStatus
    created_at: datetime
    updated_at: datetime


class ProveedorPerformanceSummary(BaseModel):
    proveedor_id: UUID
    razon_social: str
    total_ordenes_compra: int
    total_recepciones: int
    total_no_conformidades: int
    promedio_cantidad_recibida: Decimal | None = None
    metrics: ProveedorRead


class RepuestoBase(BaseModel):
    codigo_sku: str = Field(min_length=1, max_length=100)
    nombre: str = Field(min_length=1, max_length=255)
    descripcion: str | None = None
    unidad_medida: str = Field(default="unidad", min_length=1, max_length=50)
    categoria_id: UUID | None = None
    marca_compatible: str | None = None
    sede_id: UUID | None = None


class RepuestoCreate(RepuestoBase):
    pass


class RepuestoUpdate(BaseModel):
    codigo_sku: str | None = Field(default=None, min_length=1, max_length=100)
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    descripcion: str | None = None
    unidad_medida: str | None = Field(default=None, min_length=1, max_length=50)
    categoria_id: UUID | None = None
    marca_compatible: str | None = None
    sede_id: UUID | None = None
    estado: UserStatus | None = None


class RepuestoRead(RepuestoBase):
    id: UUID
    estado: UserStatus
    created_at: datetime
    updated_at: datetime


class ParametroInventarioBase(BaseModel):
    repuesto_id: UUID
    sede_id: UUID
    stock_minimo: int = Field(ge=0)
    stock_maximo: int | None = Field(default=None, ge=0)
    lead_time_base_dias: int = Field(default=0, ge=0)
    punto_reorden_inicial: int = Field(default=0, ge=0)
    punto_reorden_sugerido_ml: int | None = Field(default=None, ge=0)


class ParametroInventarioCreate(ParametroInventarioBase):
    pass


class ParametroInventarioUpdate(BaseModel):
    stock_minimo: int | None = Field(default=None, ge=0)
    stock_maximo: int | None = Field(default=None, ge=0)
    lead_time_base_dias: int | None = Field(default=None, ge=0)
    punto_reorden_inicial: int | None = Field(default=None, ge=0)
    punto_reorden_sugerido_ml: int | None = Field(default=None, ge=0)


class ParametroInventarioRead(ParametroInventarioBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class InventarioRead(BaseModel):
    id: UUID
    repuesto_id: UUID
    sede_id: UUID
    codigo_sku: str
    repuesto_nombre: str
    sede_nombre: str | None = None
    stock_actual: int
    stock_minimo: int | None = None
    stock_maximo: int | None = None
    punto_reorden_sugerido_ml: int | None = None
    updated_at: datetime
    critico: bool = False
    estado_stock: Literal["OK", "BAJO", "CRITICO"] = "OK"


class InventarioCriticoRead(InventarioRead):
    motivo: str


CategoriaTreeNode.model_rebuild()
