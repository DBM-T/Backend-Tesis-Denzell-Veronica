from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.enums import InventoryMoveType, PurchaseRequestStatus
from app.schemas.operaciones import (
    AssignTechnicianRequest,
    ChangeWorkOrderStatusRequest,
    CompleteServiceResponse,
    CloseWorkOrderRequest,
    CloseWorkOrderResponse,
    DiagnosticRequest,
    InventoryMovementCreate,
    InventoryMovementRead,
    OTWorkspaceRead,
    PaginatedInventoryMovementResponse,
    PaginatedPurchaseRequestResponse,
    PriorityClassificationRequest,
    PriorityClassificationResponse,
    PurchaseRequestCreate,
    PurchaseRequestRead,
    PurchaseRequestStateUpdate,
    StockAvailabilityResponse,
    WorkOrderCreate,
    WorkOrderDiagnosticResponse,
    WorkOrderListRead,
    WorkOrderRead,
)
from app.services.operaciones_service import (
    assign_technician,
    change_work_order_status,
    classify_priority,
    close_work_order,
    complete_service,
    create_inventory_movement,
    create_manual_pr,
    create_work_order,
    get_ot_workspace,
    list_inventory_movements,
    list_prs,
    list_work_orders,
    register_diagnostic,
    stock_available,
    update_pr_status,
    _fetch_purchase_request,
)


router = APIRouter()


@router.post("/ot", response_model=WorkOrderRead, summary="Crear OT")
async def post_ot(payload: WorkOrderCreate, current_user: CurrentUser = Depends(get_current_user)):
    return await create_work_order(current_user.supabase, current_user, payload)


@router.get("/ot", response_model=list[WorkOrderListRead], summary="Listar OT")
async def get_ot(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_work_orders(current_user.supabase, page=page, page_size=page_size)


@router.get("/ot/workspace", response_model=OTWorkspaceRead, summary="Workspace OT")
async def get_ot_workspace_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await get_ot_workspace(current_user.supabase, current_user, page=page, page_size=page_size)


@router.put("/ot/{ot_id}/asignar-tecnico", response_model=WorkOrderRead, summary="Asignar tecnico")
async def put_ot_assign_technician(
    ot_id: UUID,
    payload: AssignTechnicianRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await assign_technician(current_user.supabase, current_user, str(ot_id), payload)


@router.put("/ot/{ot_id}/diagnostico", response_model=WorkOrderDiagnosticResponse, summary="Registrar diagnostico")
async def put_ot_diagnostic(
    ot_id: UUID,
    payload: DiagnosticRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await register_diagnostic(current_user.supabase, current_user, str(ot_id), payload)


@router.post(
    "/ot/{ot_id}/clasificar-prioridad",
    response_model=PriorityClassificationResponse,
    summary="Clasificar prioridad OT",
)
async def post_ot_priority(
    ot_id: UUID,
    payload: PriorityClassificationRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await classify_priority(current_user.supabase, current_user, str(ot_id), payload)


@router.get("/ot/{ot_id}/stock-disponible", response_model=StockAvailabilityResponse, summary="Validar stock OT")
async def get_ot_stock(ot_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await stock_available(current_user.supabase, str(ot_id))


@router.put("/ot/{ot_id}/estado", summary="Cambiar estado OT")
async def put_ot_status(
    ot_id: UUID,
    payload: ChangeWorkOrderStatusRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await change_work_order_status(current_user.supabase, current_user, str(ot_id), payload)


@router.put("/ot/{ot_id}/completar-servicio", response_model=CompleteServiceResponse, summary="Completar servicio OT")
async def put_ot_complete_service(ot_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await complete_service(current_user.supabase, current_user, str(ot_id))


@router.put("/ot/{ot_id}/cerrar", response_model=CloseWorkOrderResponse, summary="Cerrar OT y generar orden de venta")
async def put_ot_close(
    ot_id: UUID,
    payload: CloseWorkOrderRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await close_work_order(current_user.supabase, current_user, str(ot_id), payload)


@router.post("/requisiciones", response_model=PurchaseRequestRead, summary="Crear requisicion manual")
async def post_requisition(
    payload: PurchaseRequestCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_manual_pr(current_user.supabase, current_user, payload)


@router.get("/requisiciones", response_model=PaginatedPurchaseRequestResponse, summary="Listar requisiciones")
async def get_requisitions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    estado: PurchaseRequestStatus | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_prs(
        current_user.supabase,
        page=page,
        page_size=page_size,
        estado=estado,
        sede_id=str(sede_id) if sede_id else None,
    )


@router.get("/requisiciones/{pr_id}", response_model=PurchaseRequestRead, summary="Detalle requisicion")
async def get_requisition_detail(pr_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return await _fetch_purchase_request(current_user.supabase, str(pr_id))


@router.put("/requisiciones/{pr_id}/estado", response_model=PurchaseRequestRead, summary="Cambiar estado requisicion")
async def put_requisition_status(
    pr_id: UUID,
    payload: PurchaseRequestStateUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_pr_status(current_user.supabase, current_user, str(pr_id), payload)


@router.post("/inventario/movimientos", response_model=InventoryMovementRead, summary="Registrar movimiento inventario")
async def post_inventory_movement(
    payload: InventoryMovementCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await create_inventory_movement(current_user.supabase, current_user, payload)


@router.get(
    "/inventario/movimientos",
    response_model=PaginatedInventoryMovementResponse,
    summary="Historial movimientos inventario",
)
async def get_inventory_movements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repuesto_id: UUID | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    tipo: InventoryMoveType | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_inventory_movements(
        current_user.supabase,
        page=page,
        page_size=page_size,
        repuesto_id=str(repuesto_id) if repuesto_id else None,
        sede_id=str(sede_id) if sede_id else None,
        tipo=tipo,
        desde=desde,
        hasta=hasta,
    )
