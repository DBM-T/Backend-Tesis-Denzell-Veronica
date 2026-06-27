from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.reportes import (
    IndicadorValidacionCreate,
    IndicadorValidacionRead,
    IndicadorValidacionUpdate,
    PlanContinuidadCreate,
    PlanContinuidadRead,
    PlanContinuidadUpdate,
    ReporteCreate,
    ReporteRead,
)
from app.services.reportes_service import (
    create_indicador_validacion,
    create_plan_continuidad,
    create_reporte,
    delete_indicador_validacion,
    delete_plan_continuidad,
    list_indicadores_validacion,
    list_plan_continuidad,
    list_reportes,
    update_indicador_validacion,
    update_plan_continuidad,
)


router = APIRouter()


@router.post(
    "",
    response_model=ReporteRead,
    summary="Generar reporte",
    description="Genera un reporte exportable, lo sube a Storage y registra la fila en reportes_generados.",
)
async def post_reportes(payload: ReporteCreate, current_user: CurrentUser = Depends(get_current_user)):
    return await create_reporte(current_user.supabase, current_user, payload)


@router.get(
    "",
    response_model=list[ReporteRead],
    summary="Listar reportes",
    description="Devuelve el historial de reportes generados con filtros por tipo y fechas.",
)
async def get_reportes(
    tipo_reporte: str | None = Query(default=None),
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_reportes(
        current_user.supabase,
        tipo_reporte=tipo_reporte,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )


@router.get(
    "/indicadores-validacion",
    response_model=list[IndicadorValidacionRead],
    summary="Listar indicadores de validacion",
    description="Devuelve el historico de indicadores AS-IS vs TO-BE.",
)
async def get_indicadores_validacion(current_user: CurrentUser = Depends(get_current_user)):
    return await list_indicadores_validacion(current_user.supabase, current_user)


@router.post(
    "/indicadores-validacion",
    response_model=IndicadorValidacionRead,
    summary="Crear indicador de validacion",
    description="Registra un comparativo AS-IS vs TO-BE. Solo administrador.",
)
async def post_indicadores_validacion(
    payload: IndicadorValidacionCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_indicador_validacion(current_user.supabase, current_user, payload)


@router.put(
    "/indicadores-validacion/{indicador_id}",
    response_model=IndicadorValidacionRead,
    summary="Actualizar indicador de validacion",
    description="Actualiza un indicador existente. Solo administrador.",
)
async def put_indicadores_validacion(
    indicador_id: UUID,
    payload: IndicadorValidacionUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_indicador_validacion(current_user.supabase, current_user, str(indicador_id), payload)


@router.delete(
    "/indicadores-validacion/{indicador_id}",
    summary="Eliminar indicador de validacion",
    description="Elimina un indicador de validacion. Solo administrador.",
)
async def delete_indicadores_validacion(indicador_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    await delete_indicador_validacion(current_user.supabase, current_user, str(indicador_id))
    return {"message": "Indicador eliminado correctamente."}


@router.get(
    "/plan-continuidad",
    response_model=list[PlanContinuidadRead],
    summary="Listar plan de continuidad",
    description="Devuelve el plan de continuidad completo.",
)
async def get_plan_continuidad(current_user: CurrentUser = Depends(get_current_user)):
    return await list_plan_continuidad(current_user.supabase, current_user)


@router.post(
    "/plan-continuidad",
    response_model=PlanContinuidadRead,
    summary="Crear plan de continuidad",
    description="Registra una nueva tarea de continuidad. Solo administrador.",
)
async def post_plan_continuidad(
    payload: PlanContinuidadCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_plan_continuidad(current_user.supabase, current_user, payload)


@router.put(
    "/plan-continuidad/{plan_id}",
    response_model=PlanContinuidadRead,
    summary="Actualizar plan de continuidad",
    description="Actualiza una tarea del plan de continuidad. Solo administrador.",
)
async def put_plan_continuidad(
    plan_id: UUID,
    payload: PlanContinuidadUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_plan_continuidad(current_user.supabase, current_user, str(plan_id), payload)


@router.delete(
    "/plan-continuidad/{plan_id}",
    summary="Eliminar plan de continuidad",
    description="Elimina una tarea del plan de continuidad. Solo administrador.",
)
async def delete_plan_continuidad_endpoint(plan_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    await delete_plan_continuidad(current_user.supabase, current_user, str(plan_id))
    return {"message": "Plan eliminado correctamente."}
