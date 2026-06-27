from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


ReporteTipo = Literal["consumo", "compras", "alertas", "lead_time", "desempeno_proveedores"]
ReporteFormato = Literal["csv", "pdf", "xlsx"]
PlanContinuidadTipo = Literal["respaldo", "mantenimiento", "actualizacion_modelo"]


class ReporteCreate(BaseModel):
    tipo_reporte: ReporteTipo
    fecha_inicio: date
    fecha_fin: date
    formato: ReporteFormato = "csv"


class ReporteRead(BaseModel):
    id: UUID
    tipo_reporte: ReporteTipo
    fecha_inicio: date
    fecha_fin: date
    formato: ReporteFormato
    generado_por: UUID
    url_archivo: str | None = None
    created_at: datetime


class IndicadorValidacionCreate(BaseModel):
    nombre_indicador: str = Field(min_length=1)
    valor_as_is: Decimal | None = None
    valor_to_be: Decimal | None = None
    unidad: str | None = None
    observaciones: str | None = None


class IndicadorValidacionRead(IndicadorValidacionCreate):
    id: UUID
    created_at: datetime


class IndicadorValidacionUpdate(BaseModel):
    nombre_indicador: str | None = Field(default=None, min_length=1)
    valor_as_is: Decimal | None = None
    valor_to_be: Decimal | None = None
    unidad: str | None = None
    observaciones: str | None = None


class PlanContinuidadCreate(BaseModel):
    tipo: PlanContinuidadTipo
    descripcion: str = Field(min_length=1)
    frecuencia: str | None = None
    responsable_id: UUID | None = None


class PlanContinuidadRead(PlanContinuidadCreate):
    id: UUID
    created_at: datetime


class PlanContinuidadUpdate(BaseModel):
    tipo: PlanContinuidadTipo | None = None
    descripcion: str | None = Field(default=None, min_length=1)
    frecuencia: str | None = None
    responsable_id: UUID | None = None

