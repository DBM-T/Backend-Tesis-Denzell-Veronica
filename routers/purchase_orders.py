"""Proceso de compra."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
from services.postgrest_utils import relation_one

router = APIRouter()


class PurchaseOrderLineCreate(BaseModel):
    producto_id: UUID
    qty_pedida: Decimal
    precio_unitario: Decimal


class PurchaseOrderCreate(BaseModel):
    requisicion_id: UUID | None = None
    proveedor_id: UUID
    sede_id: UUID
    canal: str = "local"
    canal_sugerido_ml: str | None = None
    prioridad: str = "baja"
    fecha_entrega_estimada: str | None = None
    observaciones: str | None = None
    lineas: list[PurchaseOrderLineCreate] = []


@router.get("")
async def list_purchase_orders(
    estado: str | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    query = supabase_admin().table("ordenes_compra").select("*, proveedores(razon_social)")
    if estado:
        query = query.eq("estado", estado)
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    rows = []
    for row in result.data or []:
        proveedor = relation_one(row.pop("proveedores", None))
        row["proveedor"] = proveedor.get("razon_social")
        rows.append(row)
    return rows


@router.post("", status_code=201)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    admin = supabase_admin()
    delivery_date = (
        date.fromisoformat(body.fecha_entrega_estimada) if body.fecha_entrega_estimada else None
    )
    header = (
        admin.table("ordenes_compra")
        .insert(
            {
                "requisicion_id": str(body.requisicion_id) if body.requisicion_id else None,
                "proveedor_id": str(body.proveedor_id),
                "sede_id": str(body.sede_id),
                "canal": body.canal,
                "canal_sugerido_ml": body.canal_sugerido_ml,
                "prioridad": body.prioridad,
                "fecha_entrega_estimada": delivery_date.isoformat() if delivery_date else None,
                "observaciones": body.observaciones,
                "creado_por": user.id,
            }
        )
        .execute()
    )
    if not header.data:
        raise HTTPException(500, "No se pudo crear la orden de compra")

    po = header.data[0]
    if body.lineas:
        admin.table("oc_lineas").insert(
            [
                {
                    "oc_id": po["id"],
                    "producto_id": str(line.producto_id),
                    "qty_pedida": line.qty_pedida,
                    "precio_unitario": line.precio_unitario,
                }
                for line in body.lineas
            ]
        ).execute()
    return po


@router.patch("/{po_id}/approve")
async def approve_order(
    po_id: UUID,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    result = (
        supabase_admin()
        .table("ordenes_compra")
        .update(
            {
                "estado": "enviada",
                "aprobado_por": user.id,
                "aprobado_at": datetime.utcnow().isoformat(),
            }
        )
        .eq("id", str(po_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Orden de compra no encontrada")
    row = result.data[0]
    return {"id": row["id"], "po_codigo": row["po_codigo"], "estado": row["estado"]}


@router.patch("/{po_id}/status")
async def update_order_status(
    po_id: UUID,
    estado: str,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen", "almacen_senior")),
):
    result = (
        supabase_admin()
        .table("ordenes_compra")
        .update({"estado": estado})
        .eq("id", str(po_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "OC no encontrada")
    row = result.data[0]
    return {"id": row["id"], "po_codigo": row["po_codigo"], "estado": row["estado"]}


@router.get("/{po_id}/lines")
async def get_order_lines(po_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    result = (
        supabase_admin()
        .table("oc_lineas")
        .select("*, productos(sku_padre, nombre)")
        .eq("oc_id", str(po_id))
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
