from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.schemas.auth import CurrentUser
from app.schemas.enums import PurchaseChannel, UserRole, UserStatus
from app.schemas.maestros import (
    CategoriaCreate,
    CategoriaRead,
    CategoriaTreeNode,
    CategoriaUpdate,
    InventarioCriticoRead,
    InventarioRead,
    PaginatedResponse,
    ParametroInventarioCreate,
    ParametroInventarioRead,
    ParametroInventarioUpdate,
    ProveedorCreate,
    ProveedorPerformanceSummary,
    ProveedorRead,
    ProveedorUpdate,
    RepuestoCreate,
    RepuestoRead,
    RepuestoUpdate,
)
from app.schemas.operaciones import InventoryWorkspaceRead
from app.services.maestros_service import (
    create_categoria,
    create_parametro_inventario,
    create_proveedor,
    create_repuesto,
    delete_categoria,
    delete_parametro_inventario,
    delete_proveedor,
    delete_repuesto,
    list_categorias,
    list_categorias_tree,
    list_categorias_public,
    list_categorias_tree_public,
    list_inventario,
    list_inventario_critico,
    list_parametros_inventario,
    list_proveedores,
    list_repuestos,
    proveedor_desempeno,
    update_categoria,
    update_parametro_inventario,
    update_proveedor,
    update_repuesto,
)
from app.services.operaciones_service import get_inventory_workspace


router = APIRouter()


def write_guard():
    return require_role(UserRole.administrador, UserRole.logistica)


def part_write_guard():
    return require_role(UserRole.administrador, UserRole.logistica, UserRole.almacenero)


@router.get(
    "/categorias",
    response_model=PaginatedResponse[CategoriaRead],
    summary="Listar categorias",
    description="Lista categorias con paginacion y filtro opcional por categoria padre.",
)
async def get_categorias(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    parent_id: UUID | None = Query(default=None, alias="categoria_padre_id"),
    q: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_categorias_public(
        page=page,
        page_size=page_size,
        parent_id=parent_id,
        q=q,
    )


@router.get(
    "/categorias/tree",
    response_model=list[CategoriaTreeNode],
    summary="Categorias en arbol",
    description="Devuelve el arbol completo de categorias con sus hijos anidados.",
)
async def get_categorias_tree(current_user: CurrentUser = Depends(get_current_user)):
    return await list_categorias_tree_public()


@router.post(
    "/categorias",
    response_model=CategoriaRead,
    summary="Crear categoria",
    description="Crea una categoria o subcategoria. Solo administrador o logistica.",
)
async def post_categoria(
    payload: CategoriaCreate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await create_categoria(current_user.supabase, payload)


@router.put(
    "/categorias/{categoria_id}",
    response_model=CategoriaRead,
    summary="Actualizar categoria",
    description="Actualiza una categoria existente. Solo administrador o logistica.",
)
async def put_categoria(
    categoria_id: UUID,
    payload: CategoriaUpdate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await update_categoria(current_user.supabase, str(categoria_id), payload)


@router.delete(
    "/categorias/{categoria_id}",
    summary="Eliminar categoria",
    description="Elimina una categoria. Solo administrador o logistica.",
)
async def delete_categoria_endpoint(
    categoria_id: UUID,
    current_user: CurrentUser = Depends(write_guard()),
):
    await delete_categoria(current_user.supabase, str(categoria_id))
    return {"message": "Categoria eliminada correctamente."}


@router.get(
    "/proveedores",
    response_model=PaginatedResponse[ProveedorRead],
    summary="Listar proveedores",
    description="Lista proveedores con filtros basicos y paginacion.",
)
async def get_proveedores(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    estado: UserStatus | None = Query(default=None),
    canal_preferido: PurchaseChannel | None = Query(default=None),
    q: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_proveedores(
        current_user.supabase,
        page=page,
        page_size=page_size,
        estado=estado,
        canal_preferido=canal_preferido.value if canal_preferido else None,
        q=q,
    )


@router.post(
    "/proveedores",
    response_model=ProveedorRead,
    summary="Crear proveedor",
    description="Crea un proveedor con sus campos de score ML. Solo administrador o logistica.",
)
async def post_proveedor(
    payload: ProveedorCreate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await create_proveedor(current_user.supabase, payload)


@router.get(
    "/proveedores/{proveedor_id}/desempeno",
    response_model=ProveedorPerformanceSummary,
    summary="Desempeno de proveedor",
    description="Devuelve un resumen historico derivado del comportamiento del proveedor.",
)
async def get_proveedor_desempeno(
    proveedor_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await proveedor_desempeno(current_user.supabase, str(proveedor_id))


@router.put(
    "/proveedores/{proveedor_id}",
    response_model=ProveedorRead,
    summary="Actualizar proveedor",
    description="Actualiza un proveedor. Solo administrador o logistica.",
)
async def put_proveedor(
    proveedor_id: UUID,
    payload: ProveedorUpdate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await update_proveedor(current_user.supabase, str(proveedor_id), payload)


@router.delete(
    "/proveedores/{proveedor_id}",
    response_model=ProveedorRead,
    summary="Desactivar proveedor",
    description="Marca el proveedor como inactivo. Solo administrador o logistica.",
)
async def delete_proveedor_endpoint(
    proveedor_id: UUID,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await delete_proveedor(current_user.supabase, str(proveedor_id))


@router.get(
    "/repuestos",
    response_model=PaginatedResponse[RepuestoRead],
    summary="Listar repuestos",
    description="Lista repuestos con filtros por sede, categoria, estado y busqueda simple.",
)
async def get_repuestos(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sede_id: UUID | None = Query(default=None),
    categoria_id: UUID | None = Query(default=None),
    estado: UserStatus | None = Query(default=None),
    q: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_repuestos(
        current_user.supabase,
        page=page,
        page_size=page_size,
        sede_id=sede_id,
        categoria_id=categoria_id,
        estado=estado,
        q=q,
    )


@router.post(
    "/repuestos",
    response_model=RepuestoRead,
    summary="Crear repuesto",
    description="Crea un repuesto/SKU. Solo administrador o logistica.",
)
async def post_repuesto(
    payload: RepuestoCreate,
    current_user: CurrentUser = Depends(part_write_guard()),
):
    return await create_repuesto(current_user.supabase, payload)


@router.put(
    "/repuestos/{repuesto_id}",
    response_model=RepuestoRead,
    summary="Actualizar repuesto",
    description="Actualiza un repuesto existente. Solo administrador o logistica.",
)
async def put_repuesto(
    repuesto_id: UUID,
    payload: RepuestoUpdate,
    current_user: CurrentUser = Depends(part_write_guard()),
):
    return await update_repuesto(current_user.supabase, str(repuesto_id), payload)


@router.delete(
    "/repuestos/{repuesto_id}",
    response_model=RepuestoRead,
    summary="Desactivar repuesto",
    description="Marca el repuesto como inactivo. Solo administrador o logistica.",
)
async def delete_repuesto_endpoint(
    repuesto_id: UUID,
    current_user: CurrentUser = Depends(part_write_guard()),
):
    return await delete_repuesto(current_user.supabase, str(repuesto_id))


@router.get(
    "/inventario/workspace",
    response_model=InventoryWorkspaceRead,
    summary="Workspace inventario",
    description="Carga repuestos, stock actual, criticos, movimientos recientes, sedes y OTs activas para el modulo de inventario.",
)
async def get_inventario_workspace(
    inventory_page: int = Query(default=1, ge=1),
    inventory_page_size: int = Query(default=20, ge=1, le=100),
    critical_page: int = Query(default=1, ge=1),
    critical_page_size: int = Query(default=12, ge=1, le=100),
    movement_page: int = Query(default=1, ge=1),
    movement_page_size: int = Query(default=20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await get_inventory_workspace(
        current_user.supabase,
        inventory_page=inventory_page,
        inventory_page_size=inventory_page_size,
        critical_page=critical_page,
        critical_page_size=critical_page_size,
        movement_page=movement_page,
        movement_page_size=movement_page_size,
    )


@router.get(
    "/parametros-inventario",
    response_model=PaginatedResponse[ParametroInventarioRead],
    summary="Listar parametros de inventario",
    description="Lista parametros por SKU y sede con filtros basicos.",
)
async def get_parametros_inventario(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sede_id: UUID | None = Query(default=None),
    repuesto_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_parametros_inventario(
        current_user.supabase,
        page=page,
        page_size=page_size,
        sede_id=sede_id,
        repuesto_id=repuesto_id,
    )


@router.post(
    "/parametros-inventario",
    response_model=ParametroInventarioRead,
    summary="Crear parametro de inventario",
    description="Crea el parametro por SKU+sede. Solo administrador o logistica.",
)
async def post_parametro_inventario(
    payload: ParametroInventarioCreate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await create_parametro_inventario(current_user.supabase, payload)


@router.put(
    "/parametros-inventario/{parametro_id}",
    response_model=ParametroInventarioRead,
    summary="Actualizar parametro de inventario",
    description="Actualiza el parametro de inventario. Solo administrador o logistica.",
)
async def put_parametro_inventario(
    parametro_id: UUID,
    payload: ParametroInventarioUpdate,
    current_user: CurrentUser = Depends(write_guard()),
):
    return await update_parametro_inventario(current_user.supabase, str(parametro_id), payload)


@router.delete(
    "/parametros-inventario/{parametro_id}",
    summary="Eliminar parametro de inventario",
    description="Elimina el parametro de inventario. Solo administrador o logistica.",
)
async def delete_parametro_inventario_endpoint(
    parametro_id: UUID,
    current_user: CurrentUser = Depends(write_guard()),
):
    await delete_parametro_inventario(current_user.supabase, str(parametro_id))
    return {"message": "Parametro de inventario eliminado correctamente."}


@router.get(
    "/inventario",
    response_model=PaginatedResponse[InventarioRead],
    summary="Consultar inventario",
    description="Consulta el stock actual con referencia a parametros de inventario.",
)
async def get_inventario(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sede_id: UUID | None = Query(default=None),
    repuesto_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_inventario(
        current_user.supabase,
        page=page,
        page_size=page_size,
        sede_id=sede_id,
        repuesto_id=repuesto_id,
    )


@router.get(
    "/inventario/criticos",
    response_model=PaginatedResponse[InventarioCriticoRead],
    summary="Inventario critico",
    description="Devuelve repuestos por debajo de stock minimo o punto de reorden.",
)
async def get_inventario_criticos(
    sede_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_inventario_critico(
        current_user.supabase,
        sede_id=sede_id,
        page=page,
        page_size=page_size,
    )
