from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


ReporteTipo = Literal["consumo", "compras", "alertas", "lead_time", "desempeno_proveedores", "kpis_abastecimiento"]
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


class ReporteKpiResumenRead(BaseModel):
    tasa_quiebres_stock_pct: Decimal
    rotacion_inventario: Decimal
    tiempo_promedio_reposicion_dias: Decimal
    tasa_cumplimiento_proveedores_pct: Decimal


class ReporteKpiTendenciaRead(BaseModel):
    period: str
    label: str
    tasa_quiebres_stock_pct: Decimal
    rotacion_inventario: Decimal
    tiempo_promedio_reposicion_dias: Decimal
    tasa_cumplimiento_proveedores_pct: Decimal


class ReporteKpiWorkspaceRead(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    resumen: ReporteKpiResumenRead
    tendencia: list[ReporteKpiTendenciaRead]
    reportes_generados: list[ReporteRead] = Field(default_factory=list)


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
