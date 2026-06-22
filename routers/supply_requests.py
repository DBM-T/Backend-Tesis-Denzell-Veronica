"""
routers/supply_requests.py — Panel de solicitudes (Módulo 2)
Flujo: requested → quotations_work → parts_pending → ready_for_advisor
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from auth import get_current_user, require_roles, CurrentUser
from database import get_conn
from schemas.supply_request import (
    SupplyRequestCreate, SupplyRequestStatusUpdate, SupplyRequestOut,
)

router = APIRouter()


@router.get("", response_model=list[SupplyRequestOut])
async def list_requests(
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
            filters.append(f"sr.status = ${i}"); params.append(status); i += 1
        if branch_id:
            filters.append(f"wo.branch_id = ${i}"); params.append(branch_id); i += 1

        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"""
            SELECT sr.*
            FROM supply_requests sr
            JOIN work_orders wo ON wo.id = sr.work_order_id
            {where}
            ORDER BY sr.created_at DESC
            LIMIT ${i} OFFSET ${i+1}
            """,
            *params, limit, offset,
        )
    return [dict(r) for r in rows]


@router.get("/active")
async def active_panel(_user: CurrentUser = Depends(get_current_user)):
    """Panel en tiempo real — usa la vista v_active_requests."""
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_active_requests ORDER BY ot_priority DESC, hours_in_parts_pending DESC NULLS LAST")
    return [dict(r) for r in rows]


@router.post("", response_model=SupplyRequestOut, status_code=201)
async def create_request(
    body: SupplyRequestCreate,
    user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        # Verificar que la OT existe
        ot = await conn.fetchrow("SELECT id FROM work_orders WHERE id=$1", body.work_order_id)
        if not ot:
            raise HTTPException(404, "Orden de trabajo no encontrada")

        row = await conn.fetchrow(
            """
            INSERT INTO supply_requests
                (work_order_id, requested_by, part_description, quantity, priority, notes)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING *
            """,
            body.work_order_id, user.id, body.part_description,
            body.quantity, body.priority, body.notes,
        )
    return dict(row)


@router.patch("/{request_id}/status", response_model=SupplyRequestOut)
async def update_status(
    request_id: UUID,
    body: SupplyRequestStatusUpdate,
    user: CurrentUser = Depends(require_roles("almacen", "asesor", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE supply_requests SET status=$2 WHERE id=$1 RETURNING *",
            request_id, body.status,
        )
    if not row:
        raise HTTPException(404, "Solicitud no encontrada")
    return dict(row)


@router.get("/{request_id}", response_model=SupplyRequestOut)
async def get_request(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM supply_requests WHERE id=$1", request_id)
    if not row:
        raise HTTPException(404, "Solicitud no encontrada")
    return dict(row)
