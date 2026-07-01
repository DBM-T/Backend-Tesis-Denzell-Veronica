from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_service_role_client
from app.schemas.enums import UserRole, UserStatus
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


MAESTROS_SELECT = {
    "categorias": "id,nombre,categoria_padre_id,created_at",
    "proveedores": (
        "id,razon_social,ruc,contacto_nombre,telefono,email,direccion,condiciones_pago,"
        "lead_time_estimado_dias,canal_preferido,estado,tasa_entrega_a_tiempo,tasa_defectos,"
        "precio_promedio,volumen_compras_previas,created_at,updated_at"
    ),
    "repuestos": "id,codigo_sku,nombre,descripcion,unidad_medida,categoria_id,marca_compatible,sede_id,estado,created_at,updated_at",
    "parametros_inventario": "id,repuesto_id,sede_id,stock_minimo,stock_maximo,lead_time_base_dias,punto_reorden_inicial,punto_reorden_sugerido_ml,created_at,updated_at",
    "inventario": "id,repuesto_id,sede_id,stock_actual,updated_at",
}


def _offset(page: int, page_size: int) -> int:
    return max(page - 1, 0) * page_size


def _page_end(page: int, page_size: int) -> int:
    return _offset(page, page_size) + page_size - 1


def _parse_rows(response) -> list[dict[str, Any]]:
    return list(response.data or [])


def _response_total(response, fallback: int) -> int:
    count = getattr(response, "count", None)
    return int(count) if count is not None else fallback


def _chunked_values(values: set[str], size: int = 200) -> list[list[str]]:
    ordered = sorted(values)
    return [ordered[index : index + size] for index in range(0, len(ordered), size)]


def _check_write_role(role: UserRole) -> None:
    if role not in {UserRole.administrador, UserRole.logistica}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administrador o logistica pueden modificar maestros.",
        )


def _to_category(row: dict[str, Any]) -> CategoriaRead:
    return CategoriaRead.model_validate(row)


def _to_provider(row: dict[str, Any]) -> ProveedorRead:
    return ProveedorRead.model_validate(row)


def _to_repuesto(row: dict[str, Any]) -> RepuestoRead:
    return RepuestoRead.model_validate(row)


def _to_parametro(row: dict[str, Any]) -> ParametroInventarioRead:
    return ParametroInventarioRead.model_validate(row)


def _to_inventario(row: dict[str, Any]) -> InventarioRead:
    return InventarioRead.model_validate(row)


def _inventory_status(*, stock_actual: int, stock_minimo: int | None, punto_reorden: int | None) -> str:
    if stock_minimo is not None and stock_actual <= int(stock_minimo):
        return "CRITICO"
    if punto_reorden is not None and stock_actual <= int(punto_reorden):
        return "BAJO"
    return "OK"


async def _paginate(query, *, page: int, page_size: int):
    return await query.range(_offset(page, page_size), _page_end(page, page_size)).execute()


async def _fetch_total(client: AsyncClient, table: str, filters: list[tuple[str, str, Any]]) -> int:
    query = client.table(table).select("id")
    for column, operator, value in filters:
        if operator == "eq":
            query = query.eq(column, value)
        elif operator == "ilike":
            query = query.ilike(column, value)
    response = await query.execute()
    return len(response.data or [])


async def list_categorias(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    parent_id: UUID | None = None,
    q: str | None = None,
) -> PaginatedResponse[CategoriaRead]:
    query = client.table("categorias").select(MAESTROS_SELECT["categorias"], count="exact")
    if parent_id is not None:
        query = query.eq("categoria_padre_id", str(parent_id))
    if q:
        query = query.ilike("nombre", f"%{q}%")
    response = await _paginate(query.order("created_at", desc=True), page=page, page_size=page_size)
    items = [_to_category(row) for row in _parse_rows(response)]
    total = await _fetch_total(
        client,
        "categorias",
        [("categoria_padre_id", "eq", str(parent_id))] if parent_id is not None else [],
    )
    return PaginatedResponse[CategoriaRead](items=items, page=page, page_size=page_size, total=total)


async def list_categorias_tree(client: AsyncClient) -> list[CategoriaTreeNode]:
    response = await client.table("categorias").select(MAESTROS_SELECT["categorias"]).order(
        "created_at", desc=False
    ).execute()
    rows = [_to_category(row) for row in _parse_rows(response)]
    nodes = {row.id: CategoriaTreeNode(**row.model_dump(), children=[]) for row in rows}
    roots: list[CategoriaTreeNode] = []
    for row in rows:
        node = nodes[row.id]
        if row.categoria_padre_id and row.categoria_padre_id in nodes:
            nodes[row.categoria_padre_id].children.append(node)
        else:
            roots.append(node)
    return roots


async def list_categorias_public(
    *,
    page: int,
    page_size: int,
    parent_id: UUID | None = None,
    q: str | None = None,
) -> PaginatedResponse[CategoriaRead]:
    service_client = await create_service_role_client()
    return await list_categorias(
        service_client,
        page=page,
        page_size=page_size,
        parent_id=parent_id,
        q=q,
    )


async def list_all_categorias_public() -> list[CategoriaRead]:
    service_client = await create_service_role_client()
    response = await service_client.table("categorias").select(MAESTROS_SELECT["categorias"]).order(
        "nombre"
    ).execute()
    return [_to_category(row) for row in _parse_rows(response)]


async def list_categorias_tree_public() -> list[CategoriaTreeNode]:
    service_client = await create_service_role_client()
    return await list_categorias_tree(service_client)


async def create_categoria(client: AsyncClient, payload: CategoriaCreate) -> CategoriaRead:
    response = await client.table("categorias").insert(payload.model_dump()).execute()
    return _to_category(response.data[0])


async def update_categoria(client: AsyncClient, categoria_id: str, payload: CategoriaUpdate) -> CategoriaRead:
    response = await client.table("categorias").update(
        payload.model_dump(exclude_unset=True)
    ).eq("id", categoria_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria no encontrada.")
    return _to_category(response.data[0])


async def delete_categoria(client: AsyncClient, categoria_id: str) -> None:
    await client.table("categorias").delete().eq("id", categoria_id).execute()


async def list_proveedores(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    estado: UserStatus | None = None,
    canal_preferido: str | None = None,
    q: str | None = None,
) -> PaginatedResponse[ProveedorRead]:
    query = client.table("proveedores").select(MAESTROS_SELECT["proveedores"], count="exact")
    if estado is not None:
        query = query.eq("estado", estado.value)
    if canal_preferido:
        query = query.eq("canal_preferido", canal_preferido)
    if q:
        query = query.ilike("razon_social", f"%{q}%")
    response = await _paginate(query.order("created_at", desc=True), page=page, page_size=page_size)
    items = [_to_provider(row) for row in _parse_rows(response)]
    total = _response_total(response, len(items))
    return PaginatedResponse[ProveedorRead](items=items, page=page, page_size=page_size, total=total)


async def create_proveedor(client: AsyncClient, payload: ProveedorCreate) -> ProveedorRead:
    response = await client.table("proveedores").insert(payload.model_dump(mode="json")).execute()
    return _to_provider(response.data[0])


async def update_proveedor(client: AsyncClient, proveedor_id: str, payload: ProveedorUpdate) -> ProveedorRead:
    response = await client.table("proveedores").update(
        payload.model_dump(exclude_unset=True, mode="json")
    ).eq("id", proveedor_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proveedor no encontrado.")
    return _to_provider(response.data[0])


async def delete_proveedor(client: AsyncClient, proveedor_id: str) -> ProveedorRead:
    response = await client.table("proveedores").update({"estado": UserStatus.inactivo.value}).eq(
        "id", proveedor_id
    ).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proveedor no encontrado.")
    return _to_provider(response.data[0])


async def proveedor_desempeno(client: AsyncClient, proveedor_id: str) -> ProveedorPerformanceSummary:
    provider_response = await (
        client.table("proveedores")
        .select(MAESTROS_SELECT["proveedores"])
        .eq("id", proveedor_id)
        .single()
        .execute()
    )
    if not provider_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proveedor no encontrado.")

    oc_response = await client.table("ordenes_compra").select("id,created_at").eq(
        "proveedor_id", proveedor_id
    ).execute()
    oc_ids = [row["id"] for row in _parse_rows(oc_response)]
    recepciones = 0
    no_conformes = 0
    cantidades: list[int] = []
    if oc_ids:
        recepciones_response = await client.table("recepciones_oc").select("id,oc_id").in_(
            "oc_id", oc_ids
        ).execute()
        recepcion_ids = [row["id"] for row in _parse_rows(recepciones_response)]
        recepciones = len(recepcion_ids)
        if recepcion_ids:
            detalle_response = await client.table("recepciones_oc_detalle").select(
                "id,cantidad_recibida,conformidad"
            ).in_("recepcion_id", recepcion_ids).execute()
            for row in _parse_rows(detalle_response):
                cantidades.append(int(row["cantidad_recibida"]))
                if row["conformidad"] != "conforme":
                    no_conformes += 1

    promedio = None
    if cantidades:
        promedio = Decimal(sum(cantidades)) / Decimal(len(cantidades))

    provider = _to_provider(provider_response.data)
    return ProveedorPerformanceSummary(
        proveedor_id=provider.id,
        razon_social=provider.razon_social,
        total_ordenes_compra=len(oc_ids),
        total_recepciones=recepciones,
        total_no_conformidades=no_conformes,
        promedio_cantidad_recibida=promedio,
        metrics=provider,
    )


async def list_repuestos(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    sede_id: UUID | None = None,
    categoria_id: UUID | None = None,
    estado: UserStatus | None = None,
    q: str | None = None,
) -> PaginatedResponse[RepuestoRead]:
    query = client.table("repuestos").select(MAESTROS_SELECT["repuestos"], count="exact")
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    if categoria_id is not None:
        query = query.eq("categoria_id", str(categoria_id))
    if estado is not None:
        query = query.eq("estado", estado.value)
    if q:
        query = query.or_(f"codigo_sku.ilike.%{q}%,nombre.ilike.%{q}%")
    response = await _paginate(
        query.order("created_at", desc=True).order("id", desc=True),
        page=page,
        page_size=page_size,
    )
    items = [_to_repuesto(row) for row in _parse_rows(response)]
    total = _response_total(response, len(items))
    return PaginatedResponse[RepuestoRead](items=items, page=page, page_size=page_size, total=total)


async def create_repuesto(client: AsyncClient, payload: RepuestoCreate) -> RepuestoRead:
    response = await client.table("repuestos").insert(payload.model_dump(mode="json")).execute()
    return _to_repuesto(response.data[0])


async def update_repuesto(client: AsyncClient, repuesto_id: str, payload: RepuestoUpdate) -> RepuestoRead:
    response = await client.table("repuestos").update(
        payload.model_dump(exclude_unset=True, mode="json")
    ).eq("id", repuesto_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repuesto no encontrado.")
    return _to_repuesto(response.data[0])


async def delete_repuesto(client: AsyncClient, repuesto_id: str) -> RepuestoRead:
    response = await client.table("repuestos").update({"estado": UserStatus.inactivo.value}).eq(
        "id", repuesto_id
    ).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repuesto no encontrado.")
    return _to_repuesto(response.data[0])


async def list_parametros_inventario(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    sede_id: UUID | None = None,
    repuesto_id: UUID | None = None,
) -> PaginatedResponse[ParametroInventarioRead]:
    query = client.table("parametros_inventario").select(
        MAESTROS_SELECT["parametros_inventario"], count="exact"
    )
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    if repuesto_id is not None:
        query = query.eq("repuesto_id", str(repuesto_id))
    response = await _paginate(query.order("created_at", desc=True), page=page, page_size=page_size)
    items = [_to_parametro(row) for row in _parse_rows(response)]
    total = _response_total(response, len(items))
    return PaginatedResponse[ParametroInventarioRead](items=items, page=page, page_size=page_size, total=total)


async def create_parametro_inventario(
    client: AsyncClient, payload: ParametroInventarioCreate
) -> ParametroInventarioRead:
    response = await client.table("parametros_inventario").insert(payload.model_dump(mode="json")).execute()
    return _to_parametro(response.data[0])


async def update_parametro_inventario(
    client: AsyncClient, parametro_id: str, payload: ParametroInventarioUpdate
) -> ParametroInventarioRead:
    response = await client.table("parametros_inventario").update(
        payload.model_dump(exclude_unset=True, mode="json")
    ).eq("id", parametro_id).execute()
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parametro de inventario no encontrado."
        )
    return _to_parametro(response.data[0])


async def delete_parametro_inventario(client: AsyncClient, parametro_id: str) -> None:
    await client.table("parametros_inventario").delete().eq("id", parametro_id).execute()


async def _load_related_maps(client: AsyncClient, rows: list[dict[str, Any]]):
    repuesto_ids = {row["repuesto_id"] for row in rows}
    sede_ids = {row["sede_id"] for row in rows}
    repuestos_map: dict[str, dict[str, Any]] = {}
    if repuesto_ids:
        for chunk in _chunked_values(repuesto_ids):
            repuestos_response = await client.table("repuestos").select(
                "id,codigo_sku,nombre,categoria_id,sede_id"
            ).in_("id", chunk).execute()
            repuestos_map.update({row["id"]: row for row in _parse_rows(repuestos_response)})

    sedes_map: dict[str, dict[str, Any]] = {}
    if sede_ids:
        for chunk in _chunked_values(sede_ids):
            sedes_response = await client.table("sedes").select("id,nombre").in_("id", chunk).execute()
            sedes_map.update({row["id"]: row for row in _parse_rows(sedes_response)})

    params_map: dict[tuple[str, str], dict[str, Any]] = {}
    if repuesto_ids and sede_ids:
        for repuesto_chunk in _chunked_values(repuesto_ids, size=100):
            params_response = await client.table("parametros_inventario").select(
                "repuesto_id,sede_id,stock_minimo,stock_maximo,punto_reorden_sugerido_ml"
            ).in_("repuesto_id", repuesto_chunk).in_("sede_id", list(sede_ids)).execute()
            params_map.update(
                {(row["repuesto_id"], row["sede_id"]): row for row in _parse_rows(params_response)}
            )

    return repuestos_map, sedes_map, params_map


async def list_inventario(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    sede_id: UUID | None = None,
    repuesto_id: UUID | None = None,
) -> PaginatedResponse[InventarioRead]:
    query = client.table("inventario").select(MAESTROS_SELECT["inventario"], count="exact")
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    if repuesto_id is not None:
        query = query.eq("repuesto_id", str(repuesto_id))
    response = await _paginate(query.order("updated_at", desc=True), page=page, page_size=page_size)
    rows = _parse_rows(response)
    repuestos_map, sedes_map, params_map = await _load_related_maps(client, rows)
    items: list[InventarioRead] = []
    for row in rows:
        repuesto = repuestos_map.get(row["repuesto_id"], {})
        sede = sedes_map.get(row["sede_id"], {})
        param = params_map.get((row["repuesto_id"], row["sede_id"]), {})
        stock_minimo = param.get("stock_minimo")
        punto_reorden = param.get("punto_reorden_sugerido_ml")
        stock_actual = int(row["stock_actual"])
        estado_stock = _inventory_status(
            stock_actual=stock_actual,
            stock_minimo=int(stock_minimo) if stock_minimo is not None else None,
            punto_reorden=int(punto_reorden) if punto_reorden is not None else None,
        )
        critico = estado_stock in {"BAJO", "CRITICO"}
        items.append(
            InventarioRead(
                id=row["id"],
                repuesto_id=row["repuesto_id"],
                sede_id=row["sede_id"],
                codigo_sku=repuesto.get("codigo_sku", ""),
                repuesto_nombre=repuesto.get("nombre", ""),
                sede_nombre=sede.get("nombre"),
                stock_actual=stock_actual,
                stock_minimo=stock_minimo,
                stock_maximo=param.get("stock_maximo"),
                punto_reorden_sugerido_ml=punto_reorden,
                updated_at=row["updated_at"],
                critico=critico,
                estado_stock=estado_stock,
            )
        )
    total = _response_total(response, len(items))
    return PaginatedResponse[InventarioRead](items=items, page=page, page_size=page_size, total=total)


async def list_inventario_critico(
    client: AsyncClient,
    *,
    sede_id: UUID | None,
    page: int,
    page_size: int,
) -> PaginatedResponse[InventarioCriticoRead]:
    items = await list_inventario_critico_full(client, sede_id=sede_id)
    total = len(items)
    paged_items = items[_offset(page, page_size) : _offset(page, page_size) + page_size]
    return PaginatedResponse[InventarioCriticoRead](
        items=paged_items,
        page=page,
        page_size=page_size,
        total=total,
    )


async def list_inventario_critico_full(
    client: AsyncClient,
    *,
    sede_id: UUID | None,
) -> list[InventarioCriticoRead]:
    query = client.table("inventario").select(MAESTROS_SELECT["inventario"])
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    response = await query.order("updated_at", desc=True).execute()
    rows = _parse_rows(response)
    repuestos_map, sedes_map, params_map = await _load_related_maps(client, rows)
    items: list[InventarioCriticoRead] = []
    for row in rows:
        repuesto = repuestos_map.get(row["repuesto_id"], {})
        sede = sedes_map.get(row["sede_id"], {})
        param = params_map.get((row["repuesto_id"], row["sede_id"]), {})
        stock_minimo = param.get("stock_minimo")
        punto_reorden = param.get("punto_reorden_sugerido_ml")
        stock_actual = int(row["stock_actual"])
        estado_stock = _inventory_status(
            stock_actual=stock_actual,
            stock_minimo=int(stock_minimo) if stock_minimo is not None else None,
            punto_reorden=int(punto_reorden) if punto_reorden is not None else None,
        )
        critico = estado_stock in {"BAJO", "CRITICO"}
        if not critico:
            continue
        motivo_parts = []
        if stock_minimo is not None and stock_actual <= int(stock_minimo):
            motivo_parts.append("stock bajo minimo")
        if punto_reorden is not None and stock_actual <= int(punto_reorden):
            motivo_parts.append("debajo de punto de reorden")
        items.append(
            InventarioCriticoRead(
                id=row["id"],
                repuesto_id=row["repuesto_id"],
                sede_id=row["sede_id"],
                codigo_sku=repuesto.get("codigo_sku", ""),
                repuesto_nombre=repuesto.get("nombre", ""),
                sede_nombre=sede.get("nombre"),
                stock_actual=stock_actual,
                stock_minimo=stock_minimo,
                stock_maximo=param.get("stock_maximo"),
                punto_reorden_sugerido_ml=punto_reorden,
                updated_at=row["updated_at"],
                critico=critico,
                estado_stock=estado_stock,
                motivo=" y ".join(motivo_parts) if motivo_parts else "stock critico",
            )
        )
    return items
