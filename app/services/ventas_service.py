from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.schemas.auth import CurrentUser
from app.schemas.enums import OrdenVentaStatus, PriorityML, UserRole
from app.schemas.operaciones import OrdenVentaDetalleRead, OrdenVentaRead, WorkOrderListRead


def _sale_row(row: dict[str, Any], detail: list[OrdenVentaDetalleRead] | None = None) -> OrdenVentaRead:
    payload = dict(row)
    payload["detalle"] = detail or []
    return OrdenVentaRead.model_validate(payload)


async def _fetch_sale_detail(client: AsyncClient, orden_venta_id: str) -> list[OrdenVentaDetalleRead]:
    response = await (
        client.table("ordenes_venta_detalle")
        .select(
            "id,orden_venta_id,repuesto_id,codigo_sku,nombre_repuesto,cantidad,precio_unitario,subtotal,created_at"
        )
        .eq("orden_venta_id", orden_venta_id)
        .order("created_at", desc=False)
        .execute()
    )
    return [OrdenVentaDetalleRead.model_validate(row) for row in response.data or []]


async def _fetch_sale(client: AsyncClient, sale_id: str) -> OrdenVentaRead:
    response = await (
        client.table("ordenes_venta")
        .select(
            "id,codigo_ov,ot_id,sede_id,tecnico_id,costo_repuestos,costo_servicio,costo_total,estado,creado_por,created_at,updated_at"
        )
        .eq("id", sale_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden de venta no encontrada.")
    detail = await _fetch_sale_detail(client, sale_id)
    return _sale_row(response.data, detail)


async def get_sale_by_ot(client: AsyncClient, ot_id: str) -> OrdenVentaRead | None:
    response = await (
        client.table("ordenes_venta")
        .select(
            "id,codigo_ov,ot_id,sede_id,tecnico_id,costo_repuestos,costo_servicio,costo_total,estado,creado_por,created_at,updated_at"
        )
        .eq("ot_id", ot_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    sale_id = response.data[0]["id"]
    return await _fetch_sale(client, sale_id)


async def list_sales(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    estado: OrdenVentaStatus | None = None,
) -> list[OrdenVentaRead]:
    query = client.table("ordenes_venta").select(
        "id,codigo_ov,ot_id,sede_id,tecnico_id,costo_repuestos,costo_servicio,costo_total,estado,creado_por,created_at,updated_at"
    )
    if estado:
        query = query.eq("estado", estado.value)
    start = max(page - 1, 0) * page_size
    response = await query.order("created_at", desc=True).range(start, start + page_size - 1).execute()
    result: list[OrdenVentaRead] = []
    for row in response.data or []:
        detail = await _fetch_sale_detail(client, row["id"])
        result.append(_sale_row(row, detail))
    return result


def _require_sale_role(current_user: CurrentUser, allowed: set[UserRole]) -> None:
    if current_user.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar la orden de venta.",
        )


async def update_sale_service_cost(
    client: AsyncClient,
    current_user: CurrentUser,
    ov_id: str,
    costo_servicio: float | int | str,
) -> OrdenVentaRead:
    _require_sale_role(
        current_user,
        {UserRole.administrador, UserRole.tecnico, UserRole.asesor_servicio, UserRole.gerencia},
    )
    current_sale = await _fetch_sale(client, ov_id)
    if current_sale.estado == OrdenVentaStatus.cancelada:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede modificar una orden de venta cancelada.",
        )
    costo_servicio_value = str(costo_servicio)
    response = await client.rpc(
        "fn_actualizar_orden_venta_costo_servicio",
        {
            "p_ov_id": ov_id,
            "p_costo_servicio": costo_servicio_value,
        },
    ).execute()
    if response.data is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo actualizar la orden de venta.")
    return await _fetch_sale(client, ov_id)


async def cancel_sale(client: AsyncClient, current_user: CurrentUser, ov_id: str) -> OrdenVentaRead:
    _require_sale_role(
        current_user,
        {UserRole.administrador, UserRole.asesor_servicio, UserRole.gerencia},
    )
    current_sale = await _fetch_sale(client, ov_id)
    if current_sale.estado != OrdenVentaStatus.con_costo_servicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede cancelar una orden de venta con costo de servicio.",
        )
    response = await client.rpc(
        "fn_cancelar_orden_venta",
        {"p_ov_id": ov_id},
    ).execute()
    if response.data is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo cancelar la orden de venta.")
    return await _fetch_sale(client, ov_id)


async def list_work_orders(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    sede_id: str | None = None,
) -> list[WorkOrderListRead]:
    start = max(page - 1, 0) * page_size
    query = client.table("ordenes_trabajo").select(
        "id,codigo_ot,cliente_nombre,cliente_documento,cliente_telefono,vehiculo_placa,"
        "vehiculo_marca,vehiculo_modelo,vehiculo_anio,servicio_solicitado,asesor_id,tecnico_id,"
        "sede_id,estado,prioridad_ml,confianza_ml,fecha_diagnostico,fecha_completado,created_at,updated_at"
    )
    if sede_id is not None:
        query = query.eq("sede_id", sede_id)
    response = await query.order("created_at", desc=True).range(start, start + page_size - 1).execute()
    sales_by_ot: dict[str, OrdenVentaRead] = {}
    work_order_ids = [row["id"] for row in response.data or []]
    technician_names: dict[str, str] = {}
    if work_order_ids:
        sales_response = await (
            client.table("ordenes_venta")
            .select(
                "id,codigo_ov,ot_id,sede_id,tecnico_id,costo_repuestos,costo_servicio,costo_total,estado,creado_por,created_at,updated_at"
            )
            .in_("ot_id", work_order_ids)
            .execute()
        )
        for row in sales_response.data or []:
            detail = await _fetch_sale_detail(client, row["id"])
            sale = _sale_row(row, detail)
            sales_by_ot[str(sale.ot_id)] = sale

        technician_ids = sorted({str(row["tecnico_id"]) for row in response.data or [] if row.get("tecnico_id")})
        if technician_ids:
            try:
                technicians_response = await (
                    client.table("perfiles")
                    .select("id,nombres,apellidos,email")
                    .in_("id", technician_ids)
                    .execute()
                )
                for technician in technicians_response.data or []:
                    full_name = f"{technician.get('nombres') or ''} {technician.get('apellidos') or ''}".strip()
                    technician_names[str(technician["id"])] = full_name or str(technician.get("email") or "")
            except Exception:
                technician_names = {}
    result: list[WorkOrderListRead] = []
    for row in response.data or []:
        payload = dict(row)
        sale = sales_by_ot.get(str(row["id"]))
        payload["orden_venta"] = sale.model_dump(mode="json") if sale else None
        if row.get("tecnico_id"):
            payload["tecnico_nombre"] = technician_names.get(str(row["tecnico_id"]))
        if payload.get("prioridad_ml") is None and payload.get("confianza_ml") is not None:
            payload["prioridad_ml"] = PriorityML.REVISAR.value
        result.append(WorkOrderListRead.model_validate(payload))
    return result
