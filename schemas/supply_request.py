"""Schemas para requisiciones de compra."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SupplyRequestLineCreate(BaseModel):
    producto_id: UUID
    qty_solicitada: Decimal
    precio_estimado: Decimal | None = None
    proveedor_sugerido_id: UUID | None = None
    observaciones: str | None = None


class SupplyRequestCreate(BaseModel):
    sede_id: UUID
    ot_id: UUID | None = None
    origen: str = "manual"
    prioridad: Literal["alta", "baja"] = "baja"
    observaciones: str | None = None
    lineas: list[SupplyRequestLineCreate] = []


class SupplyRequestStatusUpdate(BaseModel):
    estado: Literal[
        "borrador",
        "pendiente_aprobacion",
        "aprobada",
        "rechazada",
        "cancelada",
        "procesada",
    ]
    observaciones: str | None = None


class SupplyRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pr_codigo: str
    sede_id: UUID
    ot_id: UUID | None = None
    origen: str
    estado: str
    prioridad: str
    observaciones: str | None = None
    solicitado_por: UUID
    aprobado_por: UUID | None = None
    aprobado_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
