"""Proceso de compra."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, require_roles
from database import get_conn

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
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if estado:
            filters.append(f"oc.estado = ${i}")
            params.append(estado)
            i += 1
        if sede_id:
            filters.append(f"oc.sede_id = ${i}")
            params.append(sede_id)
            i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"""
            SELECT oc.*, p.razon_social AS proveedor
            FROM ordenes_compra oc
            JOIN proveedores p ON p.id = oc.proveedor_id
            {where}
            ORDER BY oc.created_at DESC
            LIMIT ${i} OFFSET ${i + 1}
            """,
            *params,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica")),
):
    async with get_conn() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO ordenes_compra (
                  requisicion_id, proveedor_id, sede_id, canal, canal_sugerido_ml,
                  prioridad, fecha_entrega_estimada, observaciones, creado_por
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                RETURNING *
                """,
                body.requisicion_id,
                body.proveedor_id,
                body.sede_id,
                body.canal,
                body.canal_sugerido_ml,
                body.prioridad,
                body.fecha_entrega_estimada,
                body.observaciones,
                user.id,
            )
            for line in body.lineas:
                await conn.execute(
                    """
                    INSERT INTO oc_lineas (oc_id, producto_id, qty_pedida, precio_unitario)
                    VALUES ($1,$2,$3,$4)
                    """,
                    row["id"],
                    line.producto_id,
                    line.qty_pedida,
                    line.precio_unitario,
                )
    return dict(row)


@router.patch("/{po_id}/approve")
async def approve_order(
    po_id: UUID,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ordenes_compra
            SET estado='enviada', aprobado_por=$2, aprobado_at=NOW()
            WHERE id=$1
            RETURNING id, po_codigo, estado
            """,
            po_id,
            user.id,
        )
    if not row:
        raise HTTPException(404, "Orden de compra no encontrada")
    return dict(row)


@router.patch("/{po_id}/status")
async def update_order_status(
    po_id: UUID,
    estado: str,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen", "almacen_senior")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE ordenes_compra SET estado=$2 WHERE id=$1 RETURNING id, po_codigo, estado",
            po_id,
            estado,
        )
    if not row:
        raise HTTPException(404, "OC no encontrada")
    return dict(row)


@router.get("/{po_id}/lines")
async def get_order_lines(po_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT ol.*, p.sku_padre, p.nombre AS producto
            FROM oc_lineas ol
            JOIN productos p ON p.id = ol.producto_id
            WHERE ol.oc_id = $1
            ORDER BY ol.created_at
            """,
            po_id,
        )
    return [dict(r) for r in rows]
