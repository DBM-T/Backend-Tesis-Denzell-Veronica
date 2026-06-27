from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_service_role_client
from app.schemas.auth import CurrentUser
from app.schemas.enums import CSVDataType, CSVLoadStatus, MLModelType, UserRole
from app.schemas.ml import (
    CargaCSVRead,
    CSVLoadResult,
    ModeloMLRead,
    PronosticoDemandaRead,
    RecalcularDemandaResponse,
    RiesgoAbastecimientoRead,
    ValidacionCSVRead,
)
from app.ml.inference.features import recolectar_features_demanda
from app.ml.inference.runtime import predecir_demanda


REQUIRED_COLUMNS = {"repuesto_id", "sede_id", "cantidad_consumida", "fecha_consumo"}


@dataclass(slots=True)
class CsvValidationIssue:
    tipo_incidencia: str
    fila_referencia: int | None
    detalle: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_roles(current_user: CurrentUser, *roles: UserRole) -> None:
    if current_user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para esta accion.")


def _normalize_value(value: str | None) -> str:
    return (value or "").strip()


def _parse_uuid(value: str | None, field: str, row_number: int, issues: list[CsvValidationIssue]) -> UUID | None:
    raw = _normalize_value(value)
    if not raw:
        issues.append(CsvValidationIssue("nulo", row_number, f"El campo {field} es obligatorio."))
        return None
    try:
        return UUID(raw)
    except ValueError:
        issues.append(CsvValidationIssue("formato_invalido", row_number, f"El campo {field} no es un UUID valido."))
        return None


def _parse_int(
    value: str | None,
    field: str,
    row_number: int,
    issues: list[CsvValidationIssue],
    *,
    min_value: int | None = None,
) -> int | None:
    raw = _normalize_value(value)
    if not raw:
        issues.append(CsvValidationIssue("nulo", row_number, f"El campo {field} es obligatorio."))
        return None
    try:
        parsed = int(raw)
    except ValueError:
        issues.append(CsvValidationIssue("formato_invalido", row_number, f"El campo {field} debe ser entero."))
        return None
    if min_value is not None and parsed < min_value:
        issues.append(CsvValidationIssue("rango_inconsistente", row_number, f"El campo {field} debe ser >= {min_value}."))
        return None
    return parsed


def _parse_decimal(
    value: str | None,
    field: str,
    row_number: int,
    issues: list[CsvValidationIssue],
    *,
    min_value: Decimal | None = None,
) -> Decimal | None:
    raw = _normalize_value(value)
    if not raw:
        issues.append(CsvValidationIssue("nulo", row_number, f"El campo {field} es obligatorio."))
        return None
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        issues.append(CsvValidationIssue("formato_invalido", row_number, f"El campo {field} debe ser numerico."))
        return None
    if min_value is not None and parsed < min_value:
        issues.append(CsvValidationIssue("rango_inconsistente", row_number, f"El campo {field} debe ser >= {min_value}."))
        return None
    return parsed


def _parse_fecha_consumo(
    value: str | None, row_number: int, issues: list[CsvValidationIssue]
) -> datetime | None:
    raw = _normalize_value(value)
    if not raw:
        issues.append(CsvValidationIssue("nulo", row_number, "El campo fecha_consumo es obligatorio."))
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(raw)
        except ValueError:
            issues.append(CsvValidationIssue("formato_invalido", row_number, "El campo fecha_consumo no tiene formato valido."))
            return None
        return datetime.combine(parsed_date, time.min, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row_signature(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(_normalize_value(row.get(column)) for column in sorted(row.keys()))


def _validate_csv_rows(rows: list[dict[str, str]]) -> tuple[list[dict], list[CsvValidationIssue]]:
    issues: list[CsvValidationIssue] = []
    clean_rows: list[dict] = []
    signatures: Counter[tuple[str, ...]] = Counter()

    for index, row in enumerate(rows, start=2):
        missing_columns = [column for column in REQUIRED_COLUMNS if not _normalize_value(row.get(column))]
        for column in missing_columns:
            issues.append(CsvValidationIssue("nulo", index, f"El campo {column} es obligatorio."))

        signature = _row_signature(row)
        signatures[signature] += 1
        if signatures[signature] > 1:
            issues.append(CsvValidationIssue("duplicado", index, "La fila esta duplicada en el archivo."))
            continue

        repuesto_id = _parse_uuid(row.get("repuesto_id"), "repuesto_id", index, issues)
        sede_id = _parse_uuid(row.get("sede_id"), "sede_id", index, issues)
        cantidad_consumida = _parse_int(
            row.get("cantidad_consumida"), "cantidad_consumida", index, issues, min_value=1
        )
        fecha_consumo = _parse_fecha_consumo(row.get("fecha_consumo"), index, issues)
        vehiculo_anio_raw = _normalize_value(row.get("vehiculo_anio"))
        vehiculo_anio = None
        if vehiculo_anio_raw:
            vehiculo_anio = _parse_int(row.get("vehiculo_anio"), "vehiculo_anio", index, issues, min_value=1900)

        if repuesto_id is None or sede_id is None or cantidad_consumida is None or fecha_consumo is None:
            continue

        clean_rows.append(
            {
                "repuesto_id": str(repuesto_id),
                "sede_id": str(sede_id),
                "ot_id": _normalize_value(row.get("ot_id")) or None,
                "vehiculo_marca": _normalize_value(row.get("vehiculo_marca")) or None,
                "vehiculo_modelo": _normalize_value(row.get("vehiculo_modelo")) or None,
                "vehiculo_anio": vehiculo_anio,
                "cantidad_consumida": cantidad_consumida,
                "fecha_consumo": fecha_consumo.isoformat(),
            }
        )

    return clean_rows, issues


def _to_carga(row: dict) -> CargaCSVRead:
    return CargaCSVRead.model_validate(row)


def _to_validacion(row: dict) -> ValidacionCSVRead:
    return ValidacionCSVRead.model_validate(row)


async def load_csv(
    client: AsyncClient,
    current_user: CurrentUser,
    archivo: UploadFile,
    tipo_dato: CSVDataType,
    *,
    confirmar_continuar: bool = False,
) -> CSVLoadResult:
    _require_roles(current_user, UserRole.administrador, UserRole.logistica)

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo CSV esta vacio.")

    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo CSV debe estar en UTF-8.") from exc

    reader = csv.DictReader(io.StringIO(texto))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo CSV no contiene encabezados.")

    rows = list(reader)
    carga_resp = await client.table("cargas_csv").insert(
        {
            "tipo_dato": tipo_dato.value,
            "nombre_archivo": archivo.filename or "carga.csv",
            "estado": CSVLoadStatus.cargado.value,
            "filas_totales": len(rows),
            "filas_validas": 0,
            "filas_con_error": 0,
            "cargado_por": str(current_user.id),
        }
    ).execute()
    carga_id = carga_resp.data[0]["id"]

    clean_rows, issues = _validate_csv_rows(rows)
    if len(rows) == 0:
        issues.append(CsvValidationIssue("nulo", None, "El archivo no contiene filas de datos."))

    validation_payload = [
        {
            "carga_id": carga_id,
            "tipo_incidencia": issue.tipo_incidencia,
            "fila_referencia": issue.fila_referencia,
            "detalle": issue.detalle,
        }
        for issue in issues
    ]
    inserted_validation_rows: list[dict] = []
    if validation_payload:
        validation_response = await client.table("validaciones_csv").insert(validation_payload).execute()
        inserted_validation_rows = list(validation_response.data or [])

    filas_validas = len(clean_rows)
    filas_con_error = len(issues)
    should_process = filas_validas > 0 and (confirmar_continuar or filas_con_error == 0)
    estado = CSVLoadStatus.procesado if should_process else (CSVLoadStatus.con_errores if filas_con_error else CSVLoadStatus.validado)

    if should_process:
        await client.table("historial_consumo").insert(
            [{**row, "origen_carga_id": carga_id} for row in clean_rows]
        ).execute()

    carga_update = await client.table("cargas_csv").update(
        {
            "estado": estado.value,
            "filas_validas": filas_validas,
            "filas_con_error": filas_con_error,
        }
    ).eq("id", carga_id).execute()

    if not carga_update.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo actualizar la carga CSV.")

    carga = _to_carga(carga_update.data[0])
    return CSVLoadResult(
        carga=carga,
        filas_insertadas=filas_validas if should_process else 0,
        filas_validas=filas_validas,
        filas_con_error=filas_con_error,
        incidencias=[_to_validacion(row) for row in inserted_validation_rows],
    )


async def get_csv_validations(client: AsyncClient, carga_id: str) -> list[ValidacionCSVRead]:
    response = await (
        client.table("validaciones_csv")
        .select("id,carga_id,tipo_incidencia,fila_referencia,detalle,created_at")
        .eq("carga_id", carga_id)
        .order("created_at", desc=False)
        .execute()
    )
    return [_to_validacion(row) for row in response.data or []]


async def list_modelos_ml(
    client: AsyncClient,
    *,
    tipo_modelo: MLModelType | None = None,
    activo: bool | None = None,
) -> list[ModeloMLRead]:
    query = client.table("modelos_ml").select(
        "id,tipo_modelo,version,descripcion,activo,entrenado_en,aprobado_por,created_at"
    ).order("created_at", desc=True)
    if tipo_modelo is not None:
        query = query.eq("tipo_modelo", tipo_modelo.value)
    if activo is not None:
        query = query.eq("activo", activo)
    response = await query.execute()
    return [ModeloMLRead.model_validate(row) for row in response.data or []]


async def list_pronosticos_demanda(
    client: AsyncClient,
    *,
    repuesto_id: UUID | None = None,
    sede_id: UUID | None = None,
) -> list[PronosticoDemandaRead]:
    query = client.table("pronosticos_demanda").select(
        "id,repuesto_id,sede_id,modelo_id,demanda_proyectada,lead_time_estimado_dias,punto_reorden_sugerido,periodo_inicio,periodo_fin,created_at"
    ).order("created_at", desc=True)
    if repuesto_id is not None:
        query = query.eq("repuesto_id", str(repuesto_id))
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    response = await query.execute()
    return [PronosticoDemandaRead.model_validate(row) for row in response.data or []]


async def list_riesgo_abastecimiento(
    client: AsyncClient,
    *,
    repuesto_id: UUID | None = None,
    sede_id: UUID | None = None,
) -> list[RiesgoAbastecimientoRead]:
    query = client.table("riesgo_abastecimiento_ml").select(
        "id,repuesto_id,sede_id,modelo_id,nivel_riesgo,confianza_ml,created_at"
    ).order("created_at", desc=True)
    if repuesto_id is not None:
        query = query.eq("repuesto_id", str(repuesto_id))
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    response = await query.execute()
    return [RiesgoAbastecimientoRead.model_validate(row) for row in response.data or []]


async def recalculate_demand(
    current_user: CurrentUser,
    *,
    repuesto_id: UUID | None = None,
    sede_id: UUID | None = None,
) -> RecalcularDemandaResponse:
    _require_roles(current_user, UserRole.administrador, UserRole.logistica)
    client = await create_service_role_client()

    params_query = client.table("parametros_inventario").select(
        "repuesto_id,sede_id,stock_minimo,lead_time_base_dias,punto_reorden_sugerido_ml"
    )
    if repuesto_id is not None:
        params_query = params_query.eq("repuesto_id", str(repuesto_id))
    if sede_id is not None:
        params_query = params_query.eq("sede_id", str(sede_id))
    params_response = await params_query.execute()

    processed = 0
    pronosticos_creados = 0
    riesgo_actualizado = 0
    for row in params_response.data or []:
        processed += 1
        features, parametros_entrada = await recolectar_features_demanda(
            client, str(row["repuesto_id"]), str(row["sede_id"])
        )
        result = predecir_demanda(features)
        model_row = await client.table("modelos_ml").select("id,version").eq("tipo_modelo", "xgboost_demanda").eq("activo", True).limit(1).execute()
        model_id = model_row.data[0]["id"] if model_row.data else result.modelo_id
        await client.table("inferencias_ml").insert(
            {
                "modelo_id": model_id,
                "ejecutado_por": str(current_user.id),
                "parametros_entrada": parametros_entrada,
                "resultado": {
                    "demanda_proyectada": result.demanda_proyectada,
                    "lead_time_estimado_dias": result.lead_time_estimado_dias,
                    "punto_reorden_sugerido": result.punto_reorden_sugerido,
                    "nivel_riesgo": result.nivel_riesgo,
                    "confianza_ml": result.confianza_ml,
                    "source": result.source,
                },
            }
        ).execute()
        existing = await client.table("pronosticos_demanda").select("id").eq(
            "repuesto_id", str(row["repuesto_id"])
        ).eq("sede_id", str(row["sede_id"])).limit(1).execute()
        payload = {
            "repuesto_id": str(row["repuesto_id"]),
            "sede_id": str(row["sede_id"]),
            "modelo_id": model_id,
            "demanda_proyectada": str(result.demanda_proyectada),
            "lead_time_estimado_dias": str(result.lead_time_estimado_dias),
            "punto_reorden_sugerido": result.punto_reorden_sugerido,
        }
        if existing.data:
            await client.table("pronosticos_demanda").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            payload.update(
                {
                    "periodo_inicio": None,
                    "periodo_fin": None,
                }
            )
            await client.table("pronosticos_demanda").insert(payload).execute()
        pronosticos_creados += 1

        await client.table("riesgo_abastecimiento_ml").insert(
            {
                "repuesto_id": str(row["repuesto_id"]),
                "sede_id": str(row["sede_id"]),
                "modelo_id": model_id,
                "nivel_riesgo": result.nivel_riesgo,
                "confianza_ml": result.confianza_ml,
            }
        ).execute()
        riesgo_actualizado += 1

        await client.table("parametros_inventario").update(
            {"punto_reorden_sugerido_ml": result.punto_reorden_sugerido}
        ).eq("repuesto_id", str(row["repuesto_id"])).eq("sede_id", str(row["sede_id"])).execute()

    return RecalcularDemandaResponse(
        procesados=processed,
        pronosticos_creados=pronosticos_creados,
        riesgo_actualizado=riesgo_actualizado,
    )
