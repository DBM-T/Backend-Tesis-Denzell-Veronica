from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.enums import OrdenVentaStatus
from app.schemas.operaciones import OrdenVentaRead, UpdateOrdenVentaCostoServicioRequest
from app.services.ventas_service import _fetch_sale, cancel_sale, list_sales, update_sale_service_cost


router = APIRouter()


@router.get("/ordenes-venta", response_model=list[OrdenVentaRead], summary="Listar ordenes de venta")
async def get_sales(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    estado: OrdenVentaStatus | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_sales(current_user.supabase, page=page, page_size=page_size, estado=estado)


@router.get("/ordenes-venta/{ov_id}", response_model=OrdenVentaRead, summary="Detalle orden de venta")
async def get_sale_detail(ov_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await _fetch_sale(current_user.supabase, str(ov_id))


@router.put("/ordenes-venta/{ov_id}/costo-servicio", response_model=OrdenVentaRead, summary="Actualizar costo de servicio de orden de venta")
async def put_sale_service_cost(
    ov_id: UUID,
    payload: UpdateOrdenVentaCostoServicioRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_sale_service_cost(current_user.supabase, current_user, str(ov_id), payload.costo_servicio)


@router.put("/ordenes-venta/{ov_id}/cancelar", response_model=OrdenVentaRead, summary="Cancelar orden de venta")
async def put_sale_cancel(
    ov_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await cancel_sale(current_user.supabase, current_user, str(ov_id))
