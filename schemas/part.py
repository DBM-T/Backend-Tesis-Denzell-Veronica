"""Schemas para productos/repuestos."""
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PartCreate(BaseModel):
    sku_padre: str
    nombre: str
    descripcion: str | None = None
    categoria_id: UUID | None = None
    marca: str | None = None
    codigo_fabricante: str | None = None
    unidad_medida: str = "UND"
    vehiculos_compatibles: list[dict[str, Any]] | None = None
    precio_referencia: Decimal | None = None


class PartUpdate(BaseModel):
    sku_padre: str | None = None
    nombre: str | None = None
    descripcion: str | None = None
    categoria_id: UUID | None = None
    marca: str | None = None
    codigo_fabricante: str | None = None
    unidad_medida: str | None = None
    vehiculos_compatibles: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    precio_referencia: Decimal | None = None


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_padre: str
    nombre: str
    descripcion: str | None = None
    categoria_id: UUID | None = None
    categoria: str | None = None
    marca: str | None = None
    codigo_fabricante: str | None = None
    unidad_medida: str
    vehiculos_compatibles: list[dict[str, Any]] | None = None
    is_storable: bool
    is_active: bool
    precio_referencia: Decimal | None = None
    total_stock: Decimal | None = None
    created_at: datetime
