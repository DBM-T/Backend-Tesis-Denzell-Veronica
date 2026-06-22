"""routers/work_orders.py — Órdenes de trabajo"""
from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from pydantic import BaseModel
from auth import get_current_user, require_roles, CurrentUser
from database import get_conn

router = APIRouter()


class WorkOrderCreate(BaseModel):
    ot_number:    str
    vehicle_id:   UUID | None = None
    branch_id:    UUID
    priority:     str = "normal"
    scheduled_at: str | None = None
    notes:        str | None = None


@router.get("")
async def list_work_orders(
    status:    str | None = None,
    branch_id: UUID | None = None,
    limit:     int = Query(50, le=200),
    offset:    int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if status:
            filters.append(f"status = ${i}"); params.append(status); i += 1
        if branch_id:
            filters.append(f"branch_id = ${i}"); params.append(branch_id); i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"SELECT * FROM work_orders {where} ORDER BY created_at DESC LIMIT ${i} OFFSET ${i+1}",
            *params, limit, offset,
        )
    return [dict(r) for r in rows]


@router.get("/trace")
async def ot_trace(_user: CurrentUser = Depends(get_current_user)):
    """Vista completa del estado de OTs — usa v_ot_trace."""
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_ot_trace ORDER BY created_at DESC LIMIT 100")
    return [dict(r) for r in rows]


@router.get("/{ot_id}")
async def get_work_order(ot_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM work_orders WHERE id = $1", ot_id)
    if not row:
        raise HTTPException(404, "Orden de trabajo no encontrada")
    return dict(row)


@router.post("", status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    user: CurrentUser = Depends(require_roles("asesor", "cotizador", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO work_orders
                (ot_number, vehicle_id, branch_id, advisor_id, priority, scheduled_at, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
            """,
            body.ot_number, body.vehicle_id, body.branch_id,
            user.id, body.priority, body.scheduled_at, body.notes,
        )
    return dict(row)


@router.patch("/{ot_id}/status")
async def update_ot_status(
    ot_id: UUID,
    status: str,
    user: CurrentUser = Depends(require_roles("asesor", "almacen", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE work_orders SET status=$2 WHERE id=$1 RETURNING id, status",
            ot_id, status,
        )
    if not row:
        raise HTTPException(404, "OT no encontrada")
    return dict(row)
