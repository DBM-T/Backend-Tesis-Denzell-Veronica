"""Ordenes de trabajo."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, require_roles
from database import get_conn

router = APIRouter()


class WorkOrderCreate(BaseModel):
    sede_id: UUID
    vehiculo_id: UUID
    cita_id: UUID | None = None
    tecnico_id: UUID | None = None
    prioridad: str | None = None
    diagnostico_inicial: str | None = None
    km_ingreso: int | None = None
    tiempo_estimado_horas: Decimal | None = None


@router.get("")
async def list_work_orders(
    status: str | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if status:
            filters.append(f"estado = ${i}")
            params.append(status)
            i += 1
        if sede_id:
            filters.append(f"sede_id = ${i}")
            params.append(sede_id)
            i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"SELECT * FROM ordenes_trabajo {where} ORDER BY created_at DESC LIMIT ${i} OFFSET ${i + 1}",
            *params,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


@router.get("/trace")
async def ot_trace(_user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_trazabilidad ORDER BY ot_creada DESC LIMIT 100")
    return [dict(r) for r in rows]


@router.get("/{ot_id}")
async def get_work_order(ot_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM ordenes_trabajo WHERE id = $1", ot_id)
    if not row:
        raise HTTPException(404, "Orden de trabajo no encontrada")
    return dict(row)


@router.post("", status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "asesor", "gerencia")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ordenes_trabajo (
              cita_id, sede_id, vehiculo_id, tecnico_id, prioridad, diagnostico_inicial,
              km_ingreso, tiempo_estimado_horas, created_by
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            body.cita_id,
            body.sede_id,
            body.vehiculo_id,
            body.tecnico_id,
            body.prioridad,
            body.diagnostico_inicial,
            body.km_ingreso,
            body.tiempo_estimado_horas,
            user.id,
        )
    return dict(row)


@router.patch("/{ot_id}/status")
async def update_ot_status(
    ot_id: UUID,
    estado: str,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "asesor", "almacen", "almacen_senior", "logistica")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE ordenes_trabajo SET estado=$2 WHERE id=$1 RETURNING id, estado",
            ot_id,
            estado,
        )
    if not row:
        raise HTTPException(404, "OT no encontrada")
    return dict(row)
