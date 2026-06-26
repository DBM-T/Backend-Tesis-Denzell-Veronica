"""Panel de requisiciones de compra."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
from schemas.supply_request import SupplyRequestCreate, SupplyRequestOut, SupplyRequestStatusUpdate
from services.postgrest_utils import relation_one

router = APIRouter()


@router.get("", response_model=list[SupplyRequestOut])
async def list_requests(
    estado: str | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    query = supabase_admin().table("requisiciones_compra").select("*")
    if estado:
        query = query.eq("estado", estado)
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return result.data or []


@router.get("/active")
async def active_panel(_user: CurrentUser = Depends(get_current_user)):
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
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen", "almacen_senior")),
):
    admin = supabase_admin()
    header = (
        admin.table("requisiciones_compra")
        .insert(
            {
                "sede_id": str(body.sede_id),
                "ot_id": str(body.ot_id) if body.ot_id else None,
                "origen": body.origen,
                "prioridad": body.prioridad,
                "observaciones": body.observaciones,
                "solicitado_por": user.id,
            }
        )
        .execute()
    )
    if not header.data:
        raise HTTPException(500, "No se pudo crear la requisicion")

    request_row = header.data[0]
    if body.lineas:
        admin.table("requisicion_lineas").insert(
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
        ).execute()
    return request_row


@router.patch("/{request_id}/status", response_model=SupplyRequestOut)
async def update_status(
    request_id: UUID,
    body: SupplyRequestStatusUpdate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "gerencia")),
):
    payload = {"estado": body.estado}
    if body.observaciones is not None:
        payload["observaciones"] = body.observaciones
    if body.estado == "aprobada":
        payload["aprobado_por"] = user.id
        payload["aprobado_at"] = datetime.utcnow().isoformat()

    result = (
        supabase_admin()
        .table("requisiciones_compra")
        .update(payload)
        .eq("id", str(request_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Requisicion no encontrada")
    return result.data[0]


@router.get("/{request_id}", response_model=SupplyRequestOut)
async def get_request(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    result = (
        supabase_admin()
        .table("requisiciones_compra")
        .select("*")
        .eq("id", str(request_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Requisicion no encontrada")
    return result.data[0]


@router.get("/{request_id}/lines")
async def get_request_lines(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
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
    return rows
