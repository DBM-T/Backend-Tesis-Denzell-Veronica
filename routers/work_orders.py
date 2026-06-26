"""Ordenes de trabajo."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin

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
    query = supabase_admin().table("ordenes_trabajo").select("*")
    if status:
        query = query.eq("estado", status)
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return result.data or []


@router.get("/trace")
async def ot_trace(_user: CurrentUser = Depends(get_current_user)):
    result = supabase_admin().table("v_trazabilidad").select("*").order("ot_creada", desc=True).range(0, 99).execute()
    return result.data or []


@router.get("/{ot_id}")
async def get_work_order(ot_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    result = supabase_admin().table("ordenes_trabajo").select("*").eq("id", str(ot_id)).limit(1).execute()
    if not result.data:
        raise HTTPException(404, "Orden de trabajo no encontrada")
    return result.data[0]


@router.post("", status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "asesor", "gerencia")),
):
    result = (
        supabase_admin()
        .table("ordenes_trabajo")
        .insert(
            {
                "cita_id": str(body.cita_id) if body.cita_id else None,
                "sede_id": str(body.sede_id),
                "vehiculo_id": str(body.vehiculo_id),
                "tecnico_id": str(body.tecnico_id) if body.tecnico_id else None,
                "prioridad": body.prioridad,
                "diagnostico_inicial": body.diagnostico_inicial,
                "km_ingreso": body.km_ingreso,
                "tiempo_estimado_horas": body.tiempo_estimado_horas,
                "created_by": user.id,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(500, "No se pudo crear la orden de trabajo")
    return result.data[0]


@router.patch("/{ot_id}/status")
async def update_ot_status(
    ot_id: UUID,
    estado: str,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "asesor", "almacen", "almacen_senior", "logistica")),
):
    result = (
        supabase_admin()
        .table("ordenes_trabajo")
        .update({"estado": estado})
        .eq("id", str(ot_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "OT no encontrada")
    row = result.data[0]
    return {"id": row["id"], "estado": row["estado"]}
