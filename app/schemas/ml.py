from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import CSVDataType, CSVLoadStatus, MLModelType


class CargaCSVRead(BaseModel):
    id: UUID
    tipo_dato: CSVDataType
    nombre_archivo: str
    estado: CSVLoadStatus
    filas_totales: int | None = None
    filas_validas: int | None = None
    filas_con_error: int | None = None
    cargado_por: UUID
    created_at: datetime


class ValidacionCSVRead(BaseModel):
    id: UUID
    carga_id: UUID
    tipo_incidencia: str
    fila_referencia: int | None = None
    detalle: str | None = None
    created_at: datetime


class CSVLoadResult(BaseModel):
    carga: CargaCSVRead
    filas_insertadas: int
    filas_validas: int
    filas_con_error: int
    incidencias: list[ValidacionCSVRead] = Field(default_factory=list)


class ModeloMLRead(BaseModel):
    id: UUID
    tipo_modelo: MLModelType
    version: str
    descripcion: str | None = None
    activo: bool
    entrenado_en: datetime | None = None
    aprobado_por: UUID | None = None
    created_at: datetime


class PronosticoDemandaRead(BaseModel):
    id: UUID
    repuesto_id: UUID
    sede_id: UUID
    modelo_id: UUID | None = None
    demanda_proyectada: Decimal
    lead_time_estimado_dias: Decimal | None = None
    punto_reorden_sugerido: int | None = None
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    codigo_sku: str | None = None
    repuesto_nombre: str | None = None
    sede_nombre: str | None = None
    modelo_utilizado: str | None = None
    estado_alerta: Literal["SALUDABLE", "PREVENTIVA", "URGENTE", "CRITICA"] | None = None
    periodo_label: str | None = None
    created_at: datetime


class RiesgoAbastecimientoRead(BaseModel):
    id: UUID
    repuesto_id: UUID
    sede_id: UUID
    modelo_id: UUID | None = None
    nivel_riesgo: Literal["bajo", "medio", "alto"]
    confianza_ml: Decimal | None = None
    codigo_sku: str | None = None
    repuesto_nombre: str | None = None
    sede_nombre: str | None = None
    modelo_utilizado: str | None = None
    estado_alerta: Literal["SALUDABLE", "PREVENTIVA", "URGENTE", "CRITICA"] | None = None
    created_at: datetime


class RecalcularDemandaResponse(BaseModel):
    procesados: int
    pronosticos_creados: int
    pronosticos_insertados: int = 0
    pronosticos_actualizados: int = 0
    riesgo_actualizado: int
    demanda_proyectada: Decimal | None = None
    punto_reorden_sugerido: int | None = None
    nivel_riesgo: Literal["bajo", "medio", "alto"] | None = None
    confianza_ml: Decimal | None = None
    repuesto_id: UUID | None = None
    sede_id: UUID | None = None
    estado_alerta: Literal["SALUDABLE", "PREVENTIVA", "URGENTE", "CRITICA"] | None = None
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    source: str | None = None


class ModeloMetricasMLRead(BaseModel):
    id: UUID
    tipo_modelo: MLModelType
    version: str
    activo: bool
    problem_type: Literal["regression", "classification"]
    source: str
    description: str | None = None
    mape: float | None = None
    rmse: float | None = None
    r2: float | None = None
    mae: float | None = None
    accuracy: float | None = None
    f1_macro: float | None = None
    f1_alta: float | None = None
    f1_baja: float | None = None
    note: str | None = None
    metricas_originales: dict[str, object] = Field(default_factory=dict)
