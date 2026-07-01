from __future__ import annotations

import csv
import io
import textwrap
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
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
    ReporteKpiResumenRead,
    ReporteKpiTendenciaRead,
    ReporteKpiWorkspaceRead,
    ReporteRead,
)


REPORT_HEADERS: dict[str, list[str]] = {
    "consumo": ["id", "repuesto_id", "sede_id", "ot_id", "cantidad_consumida", "fecha_consumo"],
    "compras": ["id", "codigo_oc", "pr_id", "ot_id", "proveedor_id", "monto_total", "estado", "created_at"],
    "alertas": ["id", "tipo", "severidad", "estado", "sede_id", "mensaje", "created_at"],
    "lead_time": ["id", "proveedor_id", "repuesto_id", "fecha_entrega_comprometida", "fecha_recepcion", "diferencia_dias"],
    "desempeno_proveedores": ["id", "proveedor_id", "razon_social", "tasa_entrega_a_tiempo", "tasa_defectos", "precio_promedio", "lead_time_estimado_dias"],
    "kpis_abastecimiento": [
        "period",
        "label",
        "tasa_quiebres_stock_pct",
        "rotacion_inventario",
        "tiempo_promedio_reposicion_dias",
        "tasa_cumplimiento_proveedores_pct",
    ],
}

REPORT_MIME: dict[str, str] = {
    "csv": "text/csv",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _require_admin(current_user: CurrentUser) -> None:
    if current_user.role != UserRole.administrador:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administrador puede realizar esta accion.")


def _require_reporting_role(current_user: CurrentUser) -> None:
    if current_user.role not in {UserRole.administrador, UserRole.logistica, UserRole.gerencia}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo abastecimiento, gerencia o administrador pueden acceder a reportes.",
        )


def _sanitize_filename(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").replace(" ", "_")


def _decimal(value: int | float | str | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _quantize(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _iterate_months(fecha_inicio: date, fecha_fin: date) -> list[date]:
    current = _month_start(fecha_inicio)
    end = _month_start(fecha_fin)
    months: list[date] = []
    while current <= end:
        months.append(current)
        current = _next_month(current)
    return months


def _month_key(value: date | datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_label(value: date) -> str:
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{months[value.month - 1]} {value.year}"


def _timestamp_range(fecha_inicio: date, fecha_fin: date) -> tuple[str, str]:
    start = datetime.combine(fecha_inicio, datetime.min.time(), tzinfo=UTC)
    end_exclusive = datetime.combine(fecha_fin + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return start.isoformat(), end_exclusive.isoformat()


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def _parse_date_like(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    raw = str(value)
    if "T" in raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    return date.fromisoformat(raw)


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_text_line(value: object) -> str:
    raw = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not raw:
        return "-"
    return raw


def _rows_to_pdf_lines(rows: list[dict], *, tipo_reporte: str) -> list[str]:
    headers = REPORT_HEADERS[tipo_reporte]
    lines = [f"Reporte: {tipo_reporte}", "", "Columnas: " + " | ".join(headers), ""]
    if not rows:
        lines.append("Sin registros para el rango solicitado.")
        return lines

    for index, row in enumerate(rows, start=1):
        lines.append(f"Registro {index}")
        for header in headers:
            lines.extend(
                textwrap.wrap(
                    f"{header}: {_pdf_text_line(row.get(header))}",
                    width=96,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [f"{header}: -"]
            )
        lines.append("")
    return lines


def _build_pdf_document(lines: list[str]) -> bytes:
    top_margin = 760
    line_height = 14
    max_lines_per_page = 48
    pages = [lines[index:index + max_lines_per_page] for index in range(0, max(len(lines), 1), max_lines_per_page)]

    objects: list[bytes] = []
    page_object_numbers: list[int] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [] /Count 0 >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    next_object_number = 4
    for page_lines in pages:
        page_object_number = next_object_number
        content_object_number = next_object_number + 1
        next_object_number += 2

        page_object_numbers.append(page_object_number)

        stream_lines = ["BT", "/F1 10 Tf", f"50 {top_margin} Td", f"{line_height} TL"]
        for line in page_lines:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")

        stream_data = "\n".join(stream_lines).encode("latin-1", errors="replace")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object_number} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(stream_data)).encode("ascii") + b" >>\nstream\n" + stream_data + b"\nendstream")

    kids = " ".join(f"{object_number} 0 R" for object_number in page_object_numbers)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>".encode("ascii")

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)


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
    return _build_pdf_document(_rows_to_pdf_lines(rows, tipo_reporte=tipo_reporte))


async def _build_kpi_workspace(
    fecha_inicio: date,
    fecha_fin: date,
) -> ReporteKpiWorkspaceRead:
    service_client = await create_service_role_client()
    start_iso, end_iso = _timestamp_range(fecha_inicio, fecha_fin)

    repuestos_resp = await service_client.table("repuestos").select("id").eq("estado", "activo").execute()
    total_repuestos_activos = max(len(repuestos_resp.data or []), 1)

    inventario_resp = await service_client.table("inventario").select("stock_actual").execute()
    stock_total_actual = sum(int(row.get("stock_actual") or 0) for row in inventario_resp.data or [])

    alertas_resp = await (
        service_client.table("alertas")
        .select("id,tipo,created_at")
        .in_("tipo", ["punto_reorden", "riesgo_quiebre"])
        .gte("created_at", start_iso)
        .lt("created_at", end_iso)
        .execute()
    )
    consumo_resp = await (
        service_client.table("historial_consumo")
        .select("id,cantidad_consumida,fecha_consumo")
        .gte("fecha_consumo", fecha_inicio.isoformat())
        .lte("fecha_consumo", fecha_fin.isoformat())
        .execute()
    )
    recepciones_resp = await (
        service_client.table("recepciones_oc")
        .select("id,oc_id,fecha_recepcion")
        .gte("fecha_recepcion", fecha_inicio.isoformat())
        .lte("fecha_recepcion", fecha_fin.isoformat())
        .execute()
    )

    recepciones = recepciones_resp.data or []
    oc_ids = sorted({row["oc_id"] for row in recepciones if row.get("oc_id")})
    ordenes_compra = {}
    if oc_ids:
        oc_resp = await (
            service_client.table("ordenes_compra")
            .select("id,created_at,fecha_entrega_comprometida")
            .in_("id", oc_ids)
            .execute()
        )
        ordenes_compra = {row["id"]: row for row in oc_resp.data or []}

    recepcion_ids = sorted({row["id"] for row in recepciones if row.get("id")})
    detalles_por_recepcion: dict[str, list[dict]] = {}
    if recepcion_ids:
        detalle_resp = await (
            service_client.table("recepciones_oc_detalle")
            .select("id,recepcion_id,conformidad")
            .in_("recepcion_id", recepcion_ids)
            .execute()
        )
        for row in detalle_resp.data or []:
            detalles_por_recepcion.setdefault(str(row["recepcion_id"]), []).append(row)

    months = _iterate_months(fecha_inicio, fecha_fin)
    trend_map: dict[str, dict[str, Decimal | int]] = {
        _month_key(month): {
            "alerts": 0,
            "consumo": Decimal("0"),
            "reposition_sum": Decimal("0"),
            "reposition_count": 0,
            "supplier_ok": 0,
            "supplier_total": 0,
        }
        for month in months
    }

    for row in alertas_resp.data or []:
        created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        key = _month_key(created_at)
        if key in trend_map:
            trend_map[key]["alerts"] = int(trend_map[key]["alerts"]) + 1

    for row in consumo_resp.data or []:
        consumo_date = _parse_date_like(row.get("fecha_consumo"))
        if consumo_date is None:
            continue
        key = _month_key(consumo_date)
        if key in trend_map:
            trend_map[key]["consumo"] = _decimal(trend_map[key]["consumo"]) + _decimal(row.get("cantidad_consumida"))

    for row in recepciones:
        fecha_recepcion = _parse_date_like(row.get("fecha_recepcion"))
        if fecha_recepcion is None:
            continue
        key = _month_key(fecha_recepcion)
        if key not in trend_map:
            continue
        oc = ordenes_compra.get(row["oc_id"], {})
        created_at = oc.get("created_at")
        if created_at:
            oc_created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).date()
            delta_days = (fecha_recepcion - oc_created).days
            trend_map[key]["reposition_sum"] = _decimal(trend_map[key]["reposition_sum"]) + Decimal(delta_days)
            trend_map[key]["reposition_count"] = int(trend_map[key]["reposition_count"]) + 1

        detalles = detalles_por_recepcion.get(str(row["id"]), [])
        is_conforme = bool(detalles) and all(str(detail.get("conformidad") or "").lower() == "conforme" for detail in detalles)
        entrega_comprometida = oc.get("fecha_entrega_comprometida")
        is_on_time = True
        if entrega_comprometida:
            fecha_comprometida = _parse_date_like(entrega_comprometida)
            if fecha_comprometida is not None:
                is_on_time = fecha_recepcion <= fecha_comprometida
        trend_map[key]["supplier_total"] = int(trend_map[key]["supplier_total"]) + 1
        if is_conforme and is_on_time:
            trend_map[key]["supplier_ok"] = int(trend_map[key]["supplier_ok"]) + 1

    tendencia: list[ReporteKpiTendenciaRead] = []
    total_alerts = Decimal("0")
    total_consumo = Decimal("0")
    total_reposition_sum = Decimal("0")
    total_reposition_count = 0
    total_supplier_ok = 0
    total_supplier_total = 0

    stock_denominator = Decimal(max(stock_total_actual, 1))
    repuestos_denominator = Decimal(max(total_repuestos_activos, 1))

    for month in months:
        key = _month_key(month)
        bucket = trend_map[key]
        alerts = Decimal(int(bucket["alerts"]))
        consumo = _decimal(bucket["consumo"])
        reposition_sum = _decimal(bucket["reposition_sum"])
        reposition_count = int(bucket["reposition_count"])
        supplier_ok = int(bucket["supplier_ok"])
        supplier_total = int(bucket["supplier_total"])

        total_alerts += alerts
        total_consumo += consumo
        total_reposition_sum += reposition_sum
        total_reposition_count += reposition_count
        total_supplier_ok += supplier_ok
        total_supplier_total += supplier_total

        tasa_quiebres = _quantize(_safe_div(alerts * Decimal("100"), repuestos_denominator))
        rotacion = _quantize(_safe_div(consumo, stock_denominator), "0.0001")
        tiempo_reposicion = _quantize(
            _safe_div(reposition_sum, Decimal(reposition_count if reposition_count else 1))
            if reposition_count
            else Decimal("0")
        )
        cumplimiento = _quantize(
            _safe_div(Decimal(supplier_ok) * Decimal("100"), Decimal(supplier_total if supplier_total else 1))
            if supplier_total
            else Decimal("0")
        )

        tendencia.append(
            ReporteKpiTendenciaRead(
                period=key,
                label=_month_label(month),
                tasa_quiebres_stock_pct=tasa_quiebres,
                rotacion_inventario=rotacion,
                tiempo_promedio_reposicion_dias=tiempo_reposicion,
                tasa_cumplimiento_proveedores_pct=cumplimiento,
            )
        )

    resumen = ReporteKpiResumenRead(
        tasa_quiebres_stock_pct=_quantize(
            _safe_div(sum(point.tasa_quiebres_stock_pct for point in tendencia), Decimal(len(tendencia) or 1))
            if tendencia
            else Decimal("0")
        ),
        rotacion_inventario=_quantize(_safe_div(total_consumo, stock_denominator), "0.0001"),
        tiempo_promedio_reposicion_dias=_quantize(
            _safe_div(total_reposition_sum, Decimal(total_reposition_count if total_reposition_count else 1))
            if total_reposition_count
            else Decimal("0")
        ),
        tasa_cumplimiento_proveedores_pct=_quantize(
            _safe_div(Decimal(total_supplier_ok) * Decimal("100"), Decimal(total_supplier_total if total_supplier_total else 1))
            if total_supplier_total
            else Decimal("0")
        ),
    )

    recent_reports = await list_reportes(
        service_client,
        tipo_reporte="kpis_abastecimiento",
        fecha_inicio=None,
        fecha_fin=None,
    )

    return ReporteKpiWorkspaceRead(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resumen=resumen,
        tendencia=tendencia,
        reportes_generados=recent_reports[:12],
    )


async def _read_dataset(client: AsyncClient, tipo_reporte: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    if tipo_reporte == "kpis_abastecimiento":
        workspace = await _build_kpi_workspace(fecha_inicio, fecha_fin)
        return [point.model_dump(mode="json") for point in workspace.tendencia]
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
    try:
        await storage.upload(object_path, content, file_options={"content-type": REPORT_MIME[formato]})
    except Exception as exc:
        if "Bucket not found" not in str(exc):
            raise
        await client.storage.create_bucket(bucket, options={"public": True})
        storage = client.storage.from_(bucket)
        await storage.upload(object_path, content, file_options={"content-type": REPORT_MIME[formato]})
    return f"{settings.supabase_url}/storage/v1/object/public/{bucket}/{object_path}"


async def create_reporte(client: AsyncClient, current_user: CurrentUser, payload: ReporteCreate) -> ReporteRead:
    _require_reporting_role(current_user)
    rows = await _read_dataset(client, payload.tipo_reporte, payload.fecha_inicio, payload.fecha_fin)
    content = _serialize_rows(rows, tipo_reporte=payload.tipo_reporte, formato=payload.formato)
    url_archivo = await _upload_report_artifact(
        payload.formato,
        payload.tipo_reporte,
        payload.fecha_inicio,
        payload.fecha_fin,
        content,
    )
    row_payload = {
        "tipo_reporte": payload.tipo_reporte,
        "fecha_inicio": payload.fecha_inicio.isoformat(),
        "fecha_fin": payload.fecha_fin.isoformat(),
        "formato": payload.formato,
        "generado_por": str(current_user.id),
        "url_archivo": url_archivo,
    }
    try:
        response = await client.table("reportes_generados").insert(row_payload).execute()
        return ReporteRead.model_validate(response.data[0])
    except Exception as exc:
        if payload.tipo_reporte != "kpis_abastecimiento" or "reportes_generados_tipo_reporte_check" not in str(exc):
            raise
        return ReporteRead(
            id=uuid4(),
            tipo_reporte=payload.tipo_reporte,
            fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin,
            formato=payload.formato,
            generado_por=current_user.id,
            url_archivo=url_archivo,
            created_at=datetime.now(UTC),
        )


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


async def get_reportes_kpi_workspace(
    current_user: CurrentUser,
    *,
    fecha_inicio: date,
    fecha_fin: date,
) -> ReporteKpiWorkspaceRead:
    _require_reporting_role(current_user)
    if fecha_inicio > fecha_fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fecha_inicio no puede ser mayor que fecha_fin.",
        )
    return await _build_kpi_workspace(fecha_inicio, fecha_fin)


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
