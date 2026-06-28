from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.compras import (
    AprobacionProveedorCreate,
    AprobacionProveedorRead,
    OrdenCompraCreate,
    OrdenCompraEstadoUpdate,
    OrdenCompraRead,
    OrdenCompraRecepcionCreate,
    RecepcionOCRead,
    RFQCreate,
    RFQRead,
    RFQRespuestaCreate,
    RFQRespuestaRead,
    RFQStatusUpdate,
    RankingProveedorRead,
)
from app.services.compras_service import (
    add_rfq_responses,
    approve_orden_gerencia,
    create_aprobacion_proveedor,
    create_orden_compra,
    create_rfq,
    create_recepcion_oc,
    get_rfq_ranking,
    list_aprobaciones_proveedor,
    list_ordenes_compra,
    list_recepciones_oc,
    list_rfqs,
    send_rfq,
    update_orden_status,
    update_rfq_status,
)


router = APIRouter()


@router.get("/rfq", response_model=list[RFQRead], summary="Listar RFQ")
async def get_rfqs(
    page: int = 1,
    page_size: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_rfqs(current_user.supabase, page=page, page_size=page_size)


@router.post(
    "/rfq",
    response_model=RFQRead,
    summary="Crear RFQ",
    description="Genera una RFQ a partir de una PR aprobada y copia el detalle de la PR.",
)
async def post_rfq(payload: RFQCreate, current_user: CurrentUser = Depends(get_current_user)):
    return await create_rfq(current_user.supabase, current_user, payload)


@router.post(
    "/rfq/{rfq_id}/enviar",
    response_model=RFQRead,
    summary="Enviar RFQ",
    description="Marca la RFQ como enviada y deja el punto de extension para email o notificaciones.",
)
async def post_rfq_send(rfq_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await send_rfq(current_user.supabase, current_user, str(rfq_id))


@router.post(
    "/rfq/{rfq_id}/respuestas",
    response_model=list[RFQRespuestaRead],
    summary="Registrar respuestas RFQ",
    description="Registra las respuestas de un proveedor para una RFQ.",
)
async def post_rfq_responses(
    rfq_id: UUID,
    payload: RFQRespuestaCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await add_rfq_responses(current_user.supabase, current_user, str(rfq_id), payload)


@router.put(
    "/rfq/{rfq_id}/estado",
    response_model=RFQRead,
    summary="Cambiar estado RFQ",
    description="Permite pasar una RFQ a respondida, vencida o cancelada segun el flujo.",
)
async def put_rfq_status(
    rfq_id: UUID,
    payload: RFQStatusUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_rfq_status(current_user.supabase, current_user, str(rfq_id), payload)


@router.get(
    "/rfq/{rfq_id}/ranking",
    response_model=list[RankingProveedorRead],
    summary="Obtener ranking de proveedores",
    description="Devuelve el ranking vigente y, si no existe, lo genera y lo persiste.",
)
async def get_rfq_ranking_endpoint(rfq_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await get_rfq_ranking(current_user.supabase, str(rfq_id))


@router.post(
    "/aprobaciones-proveedor",
    response_model=AprobacionProveedorRead,
    summary="Aprobar proveedor",
    description="Logistica confirma el proveedor recomendado o uno distinto con justificacion.",
)
async def post_aprobacion_proveedor(
    payload: AprobacionProveedorCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_aprobacion_proveedor(current_user.supabase, current_user, payload)


@router.get("/aprobaciones-proveedor", response_model=list[AprobacionProveedorRead], summary="Listar aprobaciones de proveedor")
async def get_aprobaciones_proveedor(
    page: int = 1,
    page_size: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_aprobaciones_proveedor(current_user.supabase, page=page, page_size=page_size)


@router.post(
    "/ordenes-compra",
    response_model=OrdenCompraRead,
    summary="Crear orden de compra",
    description="Genera la OC a partir de la aprobacion del proveedor y el detalle de la RFQ.",
)
async def post_orden_compra(
    payload: OrdenCompraCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_orden_compra(current_user.supabase, current_user, payload)


@router.get("/ordenes-compra", response_model=list[OrdenCompraRead], summary="Listar ordenes de compra")
async def get_ordenes_compra(
    page: int = 1,
    page_size: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_ordenes_compra(current_user.supabase, page=page, page_size=page_size)


@router.put(
    "/ordenes-compra/{oc_id}/aprobar-gerencia",
    response_model=OrdenCompraRead,
    summary="Aprobar OC por gerencia",
    description="Solo gerencia puede aprobar una OC pendiente_aprobacion.",
)
async def put_orden_compra_aprobar(
    oc_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await approve_orden_gerencia(current_user.supabase, current_user, str(oc_id))


@router.put(
    "/ordenes-compra/{oc_id}/estado",
    response_model=OrdenCompraRead,
    summary="Cambiar estado OC",
    description="Gestiona las transiciones de la orden de compra luego de creada.",
)
async def put_orden_compra_estado(
    oc_id: UUID,
    payload: OrdenCompraEstadoUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_orden_status(current_user.supabase, current_user, str(oc_id), payload)


@router.post(
    "/ordenes-compra/{oc_id}/recepciones",
    response_model=RecepcionOCRead,
    summary="Registrar recepcion de OC",
    description="Registra la recepcion y deja que el trigger actualice stock y movimientos.",
)
async def post_recepcion_oc(
    oc_id: UUID,
    payload: OrdenCompraRecepcionCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_recepcion_oc(current_user.supabase, current_user, str(oc_id), payload)


@router.get(
    "/ordenes-compra/{oc_id}/recepciones",
    response_model=list[RecepcionOCRead],
    summary="Historial de recepciones",
    description="Lista las recepciones asociadas a una OC.",
)
async def get_recepciones_oc(
    oc_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_recepciones_oc(current_user.supabase, str(oc_id))
