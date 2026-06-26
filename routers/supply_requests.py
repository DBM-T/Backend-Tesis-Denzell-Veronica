"""Panel de requisiciones de compra."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
from schemas.supply_request import SupplyRequestCreate, SupplyRequestOut, SupplyRequestStatusUpdate
from services.access_control import ensure_action, ensure_payload_scope, ensure_row_access, fetch_row, filter_rows
from services.postgrest_utils import encode_postgrest_payload, relation_one

router = APIRouter()


@router.get("", response_model=list[SupplyRequestOut])
async def list_requests(
    estado: str | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    ensure_action(_user, "requisiciones_compra", "read")
    query = supabase_admin().table("requisiciones_compra").select("*")
    if estado:
        query = query.eq("estado", estado)
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return filter_rows(_user, "requisiciones_compra", result.data or [])


@router.get("/active")
async def active_panel(_user: CurrentUser = Depends(get_current_user)):
    ensure_action(_user, "requisiciones_compra", "read")
    result = (
        supabase_admin()
        .table("requisiciones_compra")
        .select("*, sedes(nombre), ordenes_trabajo(ot_codigo), requisicion_lineas(id)")
        .in_("estado", ["borrador", "pendiente_aprobacion", "aprobada"])
        .order("created_at", desc=True)
        .range(0, 99)
        .execute()
    )
    panel = []
    for row in result.data or []:
        sede = relation_one(row.pop("sedes", None))
        ot = relation_one(row.pop("ordenes_trabajo", None))
        lineas = row.pop("requisicion_lineas", None) or []
        row["sede"] = sede.get("nombre")
        row["ot_codigo"] = ot.get("ot_codigo")
        row["total_lineas"] = len(lineas)
        panel.append(row)
    return panel


@router.post("", response_model=SupplyRequestOut, status_code=201)
async def create_request(
    body: SupplyRequestCreate,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "requisiciones_compra", "create")
    ensure_payload_scope(user, "requisiciones_compra", body.model_dump())
    admin = supabase_admin()
    header = (
        admin.table("requisiciones_compra")
        .insert(
            encode_postgrest_payload(
                {
                    "sede_id": str(body.sede_id),
                    "ot_id": str(body.ot_id) if body.ot_id else None,
                    "origen": body.origen,
                    "prioridad": body.prioridad,
                    "observaciones": body.observaciones,
                    "solicitado_por": user.id,
                }
            )
        )
        .execute()
    )
    if not header.data:
        raise HTTPException(500, "No se pudo crear la requisicion")

    request_row = header.data[0]
    if body.lineas:
        admin.table("requisicion_lineas").insert(
            encode_postgrest_payload(
                [
                    {
                        "requisicion_id": request_row["id"],
                        "producto_id": str(line.producto_id),
                        "qty_solicitada": line.qty_solicitada,
                        "precio_estimado": line.precio_estimado,
                        "proveedor_sugerido_id": (
                            str(line.proveedor_sugerido_id) if line.proveedor_sugerido_id else None
                        ),
                        "observaciones": line.observaciones,
                    }
                    for line in body.lineas
                ]
            )
        ).execute()
    return request_row


@router.patch("/{request_id}", response_model=SupplyRequestOut)
async def update_request(
    request_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "requisiciones_compra", "update")
    current = ensure_row_access(user, "requisiciones_compra", fetch_row("requisiciones_compra", str(request_id)))
    ensure_payload_scope(user, "requisiciones_compra", {**current, **payload})
    result = (
        supabase_admin()
        .table("requisiciones_compra")
        .update(encode_postgrest_payload(payload))
        .eq("id", str(request_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Requisicion no encontrada")
    return result.data[0]


@router.patch("/{request_id}/status", response_model=SupplyRequestOut)
async def update_status(
    request_id: UUID,
    body: SupplyRequestStatusUpdate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "gerencia")),
):
    ensure_action(user, "requisiciones_compra", "approve" if body.estado == "aprobada" else "update")
    payload = {"estado": body.estado}
    if body.observaciones is not None:
        payload["observaciones"] = body.observaciones
    if body.estado == "aprobada":
        payload["aprobado_por"] = user.id
        payload["aprobado_at"] = datetime.utcnow().isoformat()

    result = (
        supabase_admin()
        .table("requisiciones_compra")
        .update(encode_postgrest_payload(payload))
        .eq("id", str(request_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Requisicion no encontrada")
    return result.data[0]


@router.delete("/{request_id}")
async def delete_request(
    request_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "requisiciones_compra", "delete")
    ensure_row_access(user, "requisiciones_compra", fetch_row("requisiciones_compra", str(request_id)))
    result = (
        supabase_admin().table("requisiciones_compra").delete().eq("id", str(request_id)).execute()
    )
    if not result.data:
        raise HTTPException(404, "Requisicion no encontrada")
    return {"detail": "Requisicion eliminada", "id": str(request_id)}


@router.get("/{request_id}", response_model=SupplyRequestOut)
async def get_request(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    ensure_action(_user, "requisiciones_compra", "read")
    return ensure_row_access(_user, "requisiciones_compra", fetch_row("requisiciones_compra", str(request_id)))


@router.get("/{request_id}/lines")
async def get_request_lines(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    ensure_action(_user, "requisicion_lineas", "read")
    ensure_row_access(_user, "requisiciones_compra", fetch_row("requisiciones_compra", str(request_id)))
    result = (
        supabase_admin()
        .table("requisicion_lineas")
        .select("*, productos(sku_padre, nombre)")
        .eq("requisicion_id", str(request_id))
        .order("created_at")
        .execute()
    )
    rows = []
    for row in result.data or []:
        producto = relation_one(row.pop("productos", None))
        row["sku_padre"] = producto.get("sku_padre")
        row["producto"] = producto.get("nombre")
        rows.append(row)
    return filter_rows(_user, "requisicion_lineas", rows)


@router.post("/{request_id}/lines", status_code=201)
async def create_request_line(
    request_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "requisicion_lineas", "create")
    ensure_row_access(user, "requisiciones_compra", fetch_row("requisiciones_compra", str(request_id)))
    payload["requisicion_id"] = str(request_id)
    result = supabase_admin().table("requisicion_lineas").insert(encode_postgrest_payload(payload)).execute()
    if not result.data:
        raise HTTPException(500, "No se pudo crear la linea de requisicion")
    return result.data[0]


@router.patch("/lines/{line_id}")
async def update_request_line(
    line_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "requisicion_lineas", "update")
    ensure_row_access(user, "requisicion_lineas", fetch_row("requisicion_lineas", str(line_id)))
    result = supabase_admin().table("requisicion_lineas").update(encode_postgrest_payload(payload)).eq("id", str(line_id)).execute()
    if not result.data:
        raise HTTPException(404, "Linea no encontrada")
    return result.data[0]


@router.delete("/lines/{line_id}")
async def delete_request_line(line_id: UUID, user: CurrentUser = Depends(get_current_user)):
    ensure_action(user, "requisicion_lineas", "delete")
    ensure_row_access(user, "requisicion_lineas", fetch_row("requisicion_lineas", str(line_id)))
    result = supabase_admin().table("requisicion_lineas").delete().eq("id", str(line_id)).execute()
    if not result.data:
        raise HTTPException(404, "Linea no encontrada")
    return {"detail": "Linea eliminada", "id": str(line_id)}
