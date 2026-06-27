from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.schemas.alertas import AlertaRead, DashboardIndicadorRead, DashboardRefreshResult, RecomendacionCompraRead
from app.schemas.auth import CurrentUser
from app.schemas.enums import AlertSeverity, AlertStatus, AlertType
from app.services.alertas_service import (
    attend_alert,
    attend_recommendation,
    build_dashboard_snapshot,
    list_alertas,
    list_recomendaciones,
    refresh_alerts_and_dashboard,
)


router = APIRouter()


@router.get(
    "",
    response_model=list[AlertaRead],
    summary="Listar alertas",
    description="Devuelve alertas filtrables por estado, severidad, tipo y sede.",
)
async def get_alertas(
    estado: AlertStatus | None = Query(default=None),
    severidad: AlertSeverity | None = Query(default=None),
    tipo: AlertType | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_alertas(current_user.supabase, estado=estado, severidad=severidad, tipo=tipo, sede_id=str(sede_id) if sede_id else None)


@router.put(
    "/{alerta_id}/atender",
    response_model=AlertaRead,
    summary="Atender alerta",
    description="Marca una alerta como atendida por el usuario autenticado.",
)
async def put_alerta_atender(alerta_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await attend_alert(current_user.supabase, current_user, str(alerta_id))


@router.put(
    "/{alerta_id}/descartar",
    response_model=AlertaRead,
    summary="Descartar alerta",
    description="Marca una alerta como descartada por el usuario autenticado.",
)
async def put_alerta_descartar(alerta_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await attend_alert(current_user.supabase, current_user, str(alerta_id), discard=True)


@router.get(
    "/recomendaciones-compra",
    response_model=list[RecomendacionCompraRead],
    summary="Listar recomendaciones de compra",
    description="Devuelve recomendaciones filtrables por sede y estado de atencion.",
)
async def get_recomendaciones_compra(
    sede_id: UUID | None = Query(default=None),
    atendida: bool | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_recomendaciones(current_user.supabase, sede_id=str(sede_id) if sede_id else None, atendida=atendida)


@router.put(
    "/recomendaciones-compra/{recommendation_id}/atender",
    response_model=RecomendacionCompraRead,
    summary="Atender recomendacion de compra",
    description="Marca una recomendacion como atendida.",
)
async def put_recomendacion_atender(
    recommendation_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await attend_recommendation(current_user.supabase, current_user, str(recommendation_id))


@router.get(
    "/dashboard",
    response_model=DashboardIndicadorRead,
    summary="Dashboard gerencial",
    description="Calcula en tiempo real un snapshot agregado de stock, OC, alertas y demanda.",
)
async def get_dashboard(
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role not in {"administrador", "logistica", "gerencia"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar el dashboard.")
    snapshot = await build_dashboard_snapshot(current_user.supabase, sede_id=str(sede_id) if sede_id else None)
    return snapshot


@router.post(
    "/refresh",
    response_model=DashboardRefreshResult,
    include_in_schema=False,
)
async def post_refresh_alerts(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role not in {"administrador", "logistica"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para ejecutar el refresco.")
    return await refresh_alerts_and_dashboard()
