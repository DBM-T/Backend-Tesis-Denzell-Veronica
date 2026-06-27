from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.core.config import get_settings
from app.core.supabase_client import create_service_role_client
from app.schemas.auth import CurrentUser
from app.schemas.enums import UserRole
from app.schemas.reportes import (
    IndicadorValidacionCreate,
    IndicadorValidacionRead,
    IndicadorValidacionUpdate,
    PlanContinuidadCreate,
    PlanContinuidadRead,
    PlanContinuidadUpdate,
    ReporteCreate,
    ReporteRead,
)


REPORT_HEADERS: dict[str, list[str]] = {
    "consumo": ["id", "repuesto_id", "sede_id", "ot_id", "cantidad_consumida", "fecha_consumo"],
    "compras": ["id", "codigo_oc", "pr_id", "ot_id", "proveedor_id", "monto_total", "estado", "created_at"],
    "alertas": ["id", "tipo", "severidad", "estado", "sede_id", "mensaje", "created_at"],
    "lead_time": ["id", "proveedor_id", "repuesto_id", "fecha_entrega_comprometida", "fecha_recepcion", "diferencia_dias"],
    "desempeno_proveedores": ["id", "proveedor_id", "razon_social", "tasa_entrega_a_tiempo", "tasa_defectos", "precio_promedio", "lead_time_estimado_dias"],
}

REPORT_MIME: dict[str, str] = {
    "csv": "text/csv",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _require_admin(current_user: CurrentUser) -> None:
    if current_user.role != UserRole.administrador:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administrador puede realizar esta accion.")


def _sanitize_filename(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").replace(" ", "_")


def _serialize_rows(rows: list[dict], *, tipo_reporte: str, formato: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=REPORT_HEADERS[tipo_reporte], extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    payload = buffer.getvalue()
    if formato == "csv":
        return payload.encode("utf-8")
    if formato == "xlsx":
        return ("\t".join(REPORT_HEADERS[tipo_reporte]) + "\n" + payload).encode("utf-8")
    pdf_body = f"Reporte {tipo_reporte}\n\n{payload}"
    return ("%PDF-1.4\n" + pdf_body).encode("utf-8")


async def _read_dataset(client: AsyncClient, tipo_reporte: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    if tipo_reporte == "consumo":
        response = await client.table("historial_consumo").select(
            "id,repuesto_id,sede_id,ot_id,cantidad_consumida,fecha_consumo"
        ).gte("fecha_consumo", fecha_inicio.isoformat()).lte("fecha_consumo", fecha_fin.isoformat()).execute()
        return response.data or []
    if tipo_reporte == "compras":
        response = await client.table("ordenes_compra").select(
            "id,codigo_oc,pr_id,ot_id,proveedor_id,monto_total,estado,created_at"
        ).gte("created_at", fecha_inicio.isoformat()).lte("created_at", fecha_fin.isoformat()).execute()
        return response.data or []
    if tipo_reporte == "alertas":
        response = await client.table("alertas").select(
            "id,tipo,severidad,estado,sede_id,mensaje,created_at"
        ).gte("created_at", fecha_inicio.isoformat()).lte("created_at", fecha_fin.isoformat()).execute()
        return response.data or []
    if tipo_reporte == "lead_time":
        recepciones = await client.table("recepciones_oc").select(
            "id,oc_id,fecha_recepcion"
        ).gte("fecha_recepcion", fecha_inicio.isoformat()).lte("fecha_recepcion", fecha_fin.isoformat()).execute()
        oc_map = {}
        oc_ids = [row["oc_id"] for row in recepciones.data or []]
        if oc_ids:
            oc_response = await client.table("ordenes_compra").select(
                "id,proveedor_id,fecha_entrega_comprometida"
            ).in_("id", oc_ids).execute()
            oc_map = {row["id"]: row for row in oc_response.data or []}
        rows: list[dict] = []
        for recepcion in recepciones.data or []:
            oc = oc_map.get(recepcion["oc_id"], {})
            rows.append(
                {
                    "id": recepcion["id"],
                    "proveedor_id": oc.get("proveedor_id"),
                    "repuesto_id": None,
                    "fecha_entrega_comprometida": oc.get("fecha_entrega_comprometida"),
                    "fecha_recepcion": recepcion.get("fecha_recepcion"),
                    "diferencia_dias": None,
                }
            )
        return rows
    if tipo_reporte == "desempeno_proveedores":
        response = await client.table("proveedores").select(
            "id,razon_social,tasa_entrega_a_tiempo,tasa_defectos,precio_promedio,lead_time_estimado_dias"
        ).execute()
        return response.data or []
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tipo de reporte no soportado.")


async def _upload_report_artifact(formato: str, tipo_reporte: str, fecha_inicio: date, fecha_fin: date, content: bytes) -> str:
    settings = get_settings()
    bucket = settings.reports_bucket
    client = await create_service_role_client()
    storage = client.storage.from_(bucket)
    object_path = (
        f"{tipo_reporte}/{fecha_inicio.isoformat()}_{fecha_fin.isoformat()}/"
        f"{uuid4().hex}.{formato}"
    )
    await storage.upload(object_path, content, file_options={"content-type": REPORT_MIME[formato]})
    return f"{settings.supabase_url}/storage/v1/object/public/{bucket}/{object_path}"


async def create_reporte(client: AsyncClient, current_user: CurrentUser, payload: ReporteCreate) -> ReporteRead:
    rows = await _read_dataset(client, payload.tipo_reporte, payload.fecha_inicio, payload.fecha_fin)
    content = _serialize_rows(rows, tipo_reporte=payload.tipo_reporte, formato=payload.formato)
    url_archivo = await _upload_report_artifact(
        payload.formato,
        payload.tipo_reporte,
        payload.fecha_inicio,
        payload.fecha_fin,
        content,
    )
    response = await client.table("reportes_generados").insert(
        {
            "tipo_reporte": payload.tipo_reporte,
            "fecha_inicio": payload.fecha_inicio.isoformat(),
            "fecha_fin": payload.fecha_fin.isoformat(),
            "formato": payload.formato,
            "generado_por": str(current_user.id),
            "url_archivo": url_archivo,
        }
    ).execute()
    return ReporteRead.model_validate(response.data[0])


async def list_reportes(
    client: AsyncClient,
    *,
    tipo_reporte: str | None = None,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
) -> list[ReporteRead]:
    query = client.table("reportes_generados").select(
        "id,tipo_reporte,fecha_inicio,fecha_fin,formato,generado_por,url_archivo,created_at"
    ).order("created_at", desc=True)
    if tipo_reporte is not None:
        query = query.eq("tipo_reporte", tipo_reporte)
    if fecha_inicio is not None:
        query = query.gte("fecha_inicio", fecha_inicio.isoformat())
    if fecha_fin is not None:
        query = query.lte("fecha_fin", fecha_fin.isoformat())
    response = await query.execute()
    return [ReporteRead.model_validate(row) for row in response.data or []]


async def list_indicadores_validacion(client: AsyncClient, current_user: CurrentUser) -> list[IndicadorValidacionRead]:
    _require_admin(current_user)
    response = await client.table("indicadores_validacion").select(
        "id,nombre_indicador,valor_as_is,valor_to_be,unidad,observaciones,created_at"
    ).order("created_at", desc=True).execute()
    return [IndicadorValidacionRead.model_validate(row) for row in response.data or []]


async def create_indicador_validacion(client: AsyncClient, current_user: CurrentUser, payload: IndicadorValidacionCreate) -> IndicadorValidacionRead:
    _require_admin(current_user)
    response = await client.table("indicadores_validacion").insert(payload.model_dump(mode="json")).execute()
    return IndicadorValidacionRead.model_validate(response.data[0])


async def update_indicador_validacion(
    client: AsyncClient, current_user: CurrentUser, indicador_id: str, payload: IndicadorValidacionUpdate
) -> IndicadorValidacionRead:
    _require_admin(current_user)
    data = payload.model_dump(exclude_unset=True, mode="json")
    response = await client.table("indicadores_validacion").update(data).eq("id", indicador_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indicador no encontrado.")
    return IndicadorValidacionRead.model_validate(response.data[0])


async def delete_indicador_validacion(client: AsyncClient, current_user: CurrentUser, indicador_id: str) -> None:
    _require_admin(current_user)
    await client.table("indicadores_validacion").delete().eq("id", indicador_id).execute()


async def list_plan_continuidad(client: AsyncClient, current_user: CurrentUser) -> list[PlanContinuidadRead]:
    _require_admin(current_user)
    response = await client.table("plan_continuidad").select(
        "id,tipo,descripcion,frecuencia,responsable_id,created_at"
    ).order("created_at", desc=True).execute()
    return [PlanContinuidadRead.model_validate(row) for row in response.data or []]


async def create_plan_continuidad(client: AsyncClient, current_user: CurrentUser, payload: PlanContinuidadCreate) -> PlanContinuidadRead:
    _require_admin(current_user)
    response = await client.table("plan_continuidad").insert(payload.model_dump(mode="json")).execute()
    return PlanContinuidadRead.model_validate(response.data[0])


async def update_plan_continuidad(
    client: AsyncClient, current_user: CurrentUser, plan_id: str, payload: PlanContinuidadUpdate
) -> PlanContinuidadRead:
    _require_admin(current_user)
    data = payload.model_dump(exclude_unset=True, mode="json")
    response = await client.table("plan_continuidad").update(data).eq("id", plan_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado.")
    return PlanContinuidadRead.model_validate(response.data[0])


async def delete_plan_continuidad(client: AsyncClient, current_user: CurrentUser, plan_id: str) -> None:
    _require_admin(current_user)
    await client.table("plan_continuidad").delete().eq("id", plan_id).execute()
