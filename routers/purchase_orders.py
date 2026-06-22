"""routers/purchase_orders.py — Proceso de compra"""
from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from pydantic import BaseModel
from auth import get_current_user, require_roles, CurrentUser
from database import get_conn

router = APIRouter()


class PurchaseOrderCreate(BaseModel):
    supply_request_id: UUID
    supplier_id:       UUID
    branch_id:         UUID
    part_description:  str
    quantity:          float
    unit_price:        float | None = None
    currency:          str = "PEN"
    priority:          str = "normal"
    notes:             str | None = None


@router.get("")
async def list_purchase_orders(
    status:    str | None = None,
    branch_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if status:
            filters.append(f"po.status = ${i}"); params.append(status); i += 1
        if branch_id:
            filters.append(f"po.branch_id = ${i}"); params.append(branch_id); i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"""
            SELECT po.*, s.name AS supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON s.id = po.supplier_id
            {where}
            ORDER BY po.created_at DESC
            LIMIT ${i} OFFSET ${i+1}
            """,
            *params, limit, offset,
        )
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    total = (body.unit_price or 0) * body.quantity if body.unit_price else None
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO purchase_orders
                (supply_request_id, supplier_id, branch_id, managed_by,
                 part_description, quantity, unit_price, total_amount,
                 currency, priority, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING *
            """,
            body.supply_request_id, body.supplier_id, body.branch_id, user.id,
            body.part_description, body.quantity, body.unit_price, total,
            body.currency, body.priority, body.notes,
        )
    return dict(row)


@router.patch("/{po_id}/treasury-approve")
async def treasury_approve(
    po_id: UUID,
    payment_proof: str | None = None,
    user: CurrentUser = Depends(require_roles("admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            UPDATE purchase_orders
            SET treasury_status='approved', treasury_approved_by=$2,
                treasury_approved_at=NOW(), treasury_payment_proof=$3,
                status='treasury_approved'
            WHERE id=$1
            RETURNING id, status, treasury_status
            """,
            po_id, user.id, payment_proof,
        )
    if not row:
        raise HTTPException(404, "Orden de compra no encontrada")
    return dict(row)


@router.patch("/{po_id}/receive")
async def receive_order(
    po_id: UUID,
    corresponds: bool,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    """Almacén verifica la recepción del repuesto."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            UPDATE purchase_orders
            SET status=$2, corresponds=$3, verified_by=$4, verified_at=NOW()
            WHERE id=$1
            RETURNING id, status
            """,
            po_id, "received" if corresponds else "returned", corresponds, user.id,
        )
    if not row:
        raise HTTPException(404, "OC no encontrada")
    return dict(row)
