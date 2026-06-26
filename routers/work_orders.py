"""Ordenes de trabajo."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
from services.access_control import ensure_action, ensure_payload_scope, ensure_row_access, fetch_row, filter_rows
from services.postgrest_utils import encode_postgrest_payload

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
    ensure_action(_user, "ordenes_trabajo", "read")
    query = supabase_admin().table("ordenes_trabajo").select("*")
    if status:
        query = query.eq("estado", status)
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return filter_rows(_user, "ordenes_trabajo", result.data or [])


@router.get("/trace")
async def ot_trace(_user: CurrentUser = Depends(get_current_user)):
    result = supabase_admin().table("v_trazabilidad").select("*").order("ot_creada", desc=True).range(0, 99).execute()
    return result.data or []


@router.get("/{ot_id}")
async def get_work_order(ot_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    ensure_action(_user, "ordenes_trabajo", "read")
    row = fetch_row("ordenes_trabajo", str(ot_id))
    return ensure_row_access(_user, "ordenes_trabajo", row)


@router.post("", status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "ordenes_trabajo", "create")
    ensure_payload_scope(user, "ordenes_trabajo", body.model_dump())
    result = (
        supabase_admin()
        .table("ordenes_trabajo")
        .insert(
            encode_postgrest_payload(
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
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(500, "No se pudo crear la orden de trabajo")
    return result.data[0]


@router.patch("/{ot_id}")
async def update_work_order(
    ot_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "ordenes_trabajo", "update")
    current = ensure_row_access(user, "ordenes_trabajo", fetch_row("ordenes_trabajo", str(ot_id)))
    ensure_payload_scope(user, "ordenes_trabajo", {**current, **payload})
    result = (
        supabase_admin()
        .table("ordenes_trabajo")
        .update(encode_postgrest_payload(payload))
        .eq("id", str(ot_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Orden de trabajo no encontrada")
    return result.data[0]


@router.delete("/{ot_id}")
async def delete_work_order(
    ot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "ordenes_trabajo", "delete")
    ensure_row_access(user, "ordenes_trabajo", fetch_row("ordenes_trabajo", str(ot_id)))
    result = supabase_admin().table("ordenes_trabajo").delete().eq("id", str(ot_id)).execute()
    if not result.data:
        raise HTTPException(404, "Orden de trabajo no encontrada")
    return {"detail": "Orden de trabajo eliminada", "id": str(ot_id)}


@router.patch("/{ot_id}/status")
async def update_ot_status(
    ot_id: UUID,
    estado: str,
    _user: CurrentUser = Depends(get_current_user),
):
    ensure_action(_user, "ordenes_trabajo", "update")
    ensure_row_access(_user, "ordenes_trabajo", fetch_row("ordenes_trabajo", str(ot_id)))
    result = (
        supabase_admin()
        .table("ordenes_trabajo")
        .update(encode_postgrest_payload({"estado": estado}))
        .eq("id", str(ot_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "OT no encontrada")
    row = result.data[0]
    return {"id": row["id"], "estado": row["estado"]}


@router.get("/{ot_id}/lines")
async def list_ot_lines(ot_id: UUID, user: CurrentUser = Depends(get_current_user)):
    ensure_action(user, "ot_lineas", "read")
    ensure_row_access(user, "ordenes_trabajo", fetch_row("ordenes_trabajo", str(ot_id)))
    result = (
        supabase_admin()
        .table("ot_lineas")
        .select("*")
        .eq("ot_id", str(ot_id))
        .order("created_at")
        .execute()
    )
    return filter_rows(user, "ot_lineas", result.data or [])


@router.post("/{ot_id}/lines", status_code=201)
async def create_ot_line(
    ot_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "ot_lineas", "create")
    ensure_row_access(user, "ordenes_trabajo", fetch_row("ordenes_trabajo", str(ot_id)))
    payload["ot_id"] = str(ot_id)
    result = supabase_admin().table("ot_lineas").insert(encode_postgrest_payload(payload)).execute()
    if not result.data:
        raise HTTPException(500, "No se pudo crear la linea de OT")
    return ensure_row_access(user, "ot_lineas", result.data[0])


@router.patch("/lines/{line_id}")
async def update_ot_line(
    line_id: UUID,
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
):
    ensure_action(user, "ot_lineas", "update")
    current = ensure_row_access(user, "ot_lineas", fetch_row("ot_lineas", str(line_id)))
    result = supabase_admin().table("ot_lineas").update(encode_postgrest_payload(payload)).eq("id", str(line_id)).execute()
    if not result.data:
        raise HTTPException(404, "Linea de OT no encontrada")
    return ensure_row_access(user, "ot_lineas", result.data[0])


@router.delete("/lines/{line_id}")
async def delete_ot_line(line_id: UUID, user: CurrentUser = Depends(get_current_user)):
    ensure_action(user, "ot_lineas", "delete")
    ensure_row_access(user, "ot_lineas", fetch_row("ot_lineas", str(line_id)))
    result = supabase_admin().table("ot_lineas").delete().eq("id", str(line_id)).execute()
    if not result.data:
        raise HTTPException(404, "Linea de OT no encontrada")
    return {"detail": "Linea de OT eliminada", "id": str(line_id)}
