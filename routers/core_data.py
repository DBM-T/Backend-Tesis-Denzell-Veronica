"""CRUDs explicitos para tablas base y operativas que faltaban en la API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from auth import CurrentUser, get_current_user
from database import supabase_admin
from services.access_control import ensure_action, ensure_payload_scope, ensure_row_access, fetch_row, filter_rows

router = APIRouter()


def _rows(resource: str, request: Request, *, limit: int, offset: int, order_by: str = "created_at", desc: bool = True):
    query = supabase_admin().table(resource).select("*")
    for key, value in request.query_params.items():
        if key in {"limit", "offset"} or value == "":
            continue
        query = query.eq(key, value)
    result = query.order(order_by, desc=desc).range(offset, offset + limit - 1).execute()
    return result.data or []


def _list(resource: str, request: Request, user: CurrentUser, *, limit: int, offset: int, order_by: str = "created_at", desc: bool = True):
    ensure_action(user, resource, "read")
    return filter_rows(user, resource, _rows(resource, request, limit=limit, offset=offset, order_by=order_by, desc=desc))


def _get(resource: str, row_id: str, user: CurrentUser):
    ensure_action(user, resource, "read")
    return ensure_row_access(user, resource, fetch_row(resource, row_id))


def _create(resource: str, payload: dict[str, Any], user: CurrentUser):
    ensure_action(user, resource, "create")
    ensure_payload_scope(user, resource, payload)
    result = supabase_admin().table(resource).insert(payload).execute()
    if not result.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"No se pudo crear '{resource}'")
    return ensure_row_access(user, resource, result.data[0])


def _update(resource: str, row_id: str, payload: dict[str, Any], user: CurrentUser):
    ensure_action(user, resource, "update")
    current = ensure_row_access(user, resource, fetch_row(resource, row_id))
    merged = {**current, **payload}
    ensure_payload_scope(user, resource, merged)
    result = supabase_admin().table(resource).update(payload).eq("id", row_id).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registro no encontrado")
    return ensure_row_access(user, resource, result.data[0])


def _delete(resource: str, row_id: str, user: CurrentUser):
    ensure_action(user, resource, "delete")
    ensure_row_access(user, resource, fetch_row(resource, row_id))
    result = supabase_admin().table(resource).delete().eq("id", row_id).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registro no encontrado")
    return {"detail": "Registro eliminado", "id": row_id}


@router.get("/roles")
async def list_roles(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("roles", request, user, limit=limit, offset=offset)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("roles", role_id, user)


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("roles", payload, user)


@router.patch("/roles/{role_id}")
async def update_role(role_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("roles", role_id, payload, user)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("roles", role_id, user)


@router.get("/sedes")
async def list_sedes(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("sedes", request, user, limit=limit, offset=offset)


@router.get("/sedes/{sede_id}")
async def get_sede(sede_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("sedes", sede_id, user)


@router.post("/sedes", status_code=status.HTTP_201_CREATED)
async def create_sede(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("sedes", payload, user)


@router.patch("/sedes/{sede_id}")
async def update_sede(sede_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("sedes", sede_id, payload, user)


@router.delete("/sedes/{sede_id}")
async def delete_sede(sede_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("sedes", sede_id, user)


@router.get("/clientes")
async def list_clientes(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("clientes", request, user, limit=limit, offset=offset)


@router.get("/clientes/{cliente_id}")
async def get_cliente(cliente_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("clientes", cliente_id, user)


@router.post("/clientes", status_code=status.HTTP_201_CREATED)
async def create_cliente(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("clientes", payload, user)


@router.patch("/clientes/{cliente_id}")
async def update_cliente(cliente_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("clientes", cliente_id, payload, user)


@router.delete("/clientes/{cliente_id}")
async def delete_cliente(cliente_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("clientes", cliente_id, user)


@router.get("/vehiculos")
async def list_vehiculos(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("vehiculos", request, user, limit=limit, offset=offset)


@router.get("/vehiculos/{vehiculo_id}")
async def get_vehiculo(vehiculo_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("vehiculos", vehiculo_id, user)


@router.post("/vehiculos", status_code=status.HTTP_201_CREATED)
async def create_vehiculo(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("vehiculos", payload, user)


@router.patch("/vehiculos/{vehiculo_id}")
async def update_vehiculo(vehiculo_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("vehiculos", vehiculo_id, payload, user)


@router.delete("/vehiculos/{vehiculo_id}")
async def delete_vehiculo(vehiculo_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("vehiculos", vehiculo_id, user)


@router.get("/citas")
async def list_citas(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("citas", request, user, limit=limit, offset=offset)


@router.get("/citas/{cita_id}")
async def get_cita(cita_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("citas", cita_id, user)


@router.post("/citas", status_code=status.HTTP_201_CREATED)
async def create_cita(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    payload.setdefault("created_by", user.id)
    return _create("citas", payload, user)


@router.patch("/citas/{cita_id}")
async def update_cita(cita_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("citas", cita_id, payload, user)


@router.delete("/citas/{cita_id}")
async def delete_cita(cita_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("citas", cita_id, user)


@router.get("/categorias-producto")
async def list_categorias_producto(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("categorias_producto", request, user, limit=limit, offset=offset, order_by="nombre", desc=False)


@router.get("/categorias-producto/{categoria_id}")
async def get_categoria_producto(categoria_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("categorias_producto", categoria_id, user)


@router.post("/categorias-producto", status_code=status.HTTP_201_CREATED)
async def create_categoria_producto(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("categorias_producto", payload, user)


@router.patch("/categorias-producto/{categoria_id}")
async def update_categoria_producto(categoria_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("categorias_producto", categoria_id, payload, user)


@router.delete("/categorias-producto/{categoria_id}")
async def delete_categoria_producto(categoria_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("categorias_producto", categoria_id, user)


@router.get("/proveedores")
async def list_proveedores(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("proveedores", request, user, limit=limit, offset=offset)


@router.get("/proveedores/{proveedor_id}")
async def get_proveedor(proveedor_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("proveedores", proveedor_id, user)


@router.post("/proveedores", status_code=status.HTTP_201_CREATED)
async def create_proveedor(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("proveedores", payload, user)


@router.patch("/proveedores/{proveedor_id}")
async def update_proveedor(proveedor_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("proveedores", proveedor_id, payload, user)


@router.delete("/proveedores/{proveedor_id}")
async def delete_proveedor(proveedor_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("proveedores", proveedor_id, user)


@router.get("/catalogo-precios")
async def list_catalogo_precios(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("catalogo_precios", request, user, limit=limit, offset=offset)


@router.get("/catalogo-precios/{catalogo_id}")
async def get_catalogo_precio(catalogo_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("catalogo_precios", catalogo_id, user)


@router.post("/catalogo-precios", status_code=status.HTTP_201_CREATED)
async def create_catalogo_precio(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("catalogo_precios", payload, user)


@router.patch("/catalogo-precios/{catalogo_id}")
async def update_catalogo_precio(catalogo_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("catalogo_precios", catalogo_id, payload, user)


@router.delete("/catalogo-precios/{catalogo_id}")
async def delete_catalogo_precio(catalogo_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("catalogo_precios", catalogo_id, user)


@router.get("/proveedor-metricas")
async def list_proveedor_metricas(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("proveedor_metricas", request, user, limit=limit, offset=offset, order_by="calculado_at")


@router.get("/proveedor-metricas/{metrica_id}")
async def get_proveedor_metrica(metrica_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("proveedor_metricas", metrica_id, user)


@router.post("/proveedor-metricas", status_code=status.HTTP_201_CREATED)
async def create_proveedor_metrica(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("proveedor_metricas", payload, user)


@router.patch("/proveedor-metricas/{metrica_id}")
async def update_proveedor_metrica(metrica_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("proveedor_metricas", metrica_id, payload, user)


@router.delete("/proveedor-metricas/{metrica_id}")
async def delete_proveedor_metrica(metrica_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("proveedor_metricas", metrica_id, user)


@router.get("/cotizaciones-rfq")
async def list_cotizaciones_rfq(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("cotizaciones_rfq", request, user, limit=limit, offset=offset)


@router.get("/cotizaciones-rfq/{rfq_id}")
async def get_cotizacion_rfq(rfq_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("cotizaciones_rfq", rfq_id, user)


@router.post("/cotizaciones-rfq", status_code=status.HTTP_201_CREATED)
async def create_cotizacion_rfq(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    payload.setdefault("created_by", user.id)
    return _create("cotizaciones_rfq", payload, user)


@router.patch("/cotizaciones-rfq/{rfq_id}")
async def update_cotizacion_rfq(rfq_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("cotizaciones_rfq", rfq_id, payload, user)


@router.delete("/cotizaciones-rfq/{rfq_id}")
async def delete_cotizacion_rfq(rfq_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("cotizaciones_rfq", rfq_id, user)


@router.get("/stock")
async def list_stock(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("stock", request, user, limit=limit, offset=offset, order_by="updated_at")


@router.get("/stock/{stock_id}")
async def get_stock(stock_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("stock", stock_id, user)


@router.post("/stock", status_code=status.HTTP_201_CREATED)
async def create_stock(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("stock", payload, user)


@router.patch("/stock/{stock_id}")
async def update_stock(stock_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("stock", stock_id, payload, user)


@router.delete("/stock/{stock_id}")
async def delete_stock(stock_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("stock", stock_id, user)


@router.get("/stock-movimientos")
async def list_stock_movimientos(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("stock_movimientos", request, user, limit=limit, offset=offset)


@router.get("/stock-movimientos/{movimiento_id}")
async def get_stock_movimiento(movimiento_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("stock_movimientos", movimiento_id, user)


@router.post("/stock-movimientos", status_code=status.HTTP_201_CREATED)
async def create_stock_movimiento(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("stock_movimientos", payload, user)


@router.patch("/stock-movimientos/{movimiento_id}")
async def update_stock_movimiento(movimiento_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("stock_movimientos", movimiento_id, payload, user)


@router.delete("/stock-movimientos/{movimiento_id}")
async def delete_stock_movimiento(movimiento_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("stock_movimientos", movimiento_id, user)


@router.get("/recepciones")
async def list_recepciones(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("recepciones", request, user, limit=limit, offset=offset)


@router.get("/recepciones/{recepcion_id}")
async def get_recepcion(recepcion_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("recepciones", recepcion_id, user)


@router.post("/recepciones", status_code=status.HTTP_201_CREATED)
async def create_recepcion(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    payload.setdefault("created_by", user.id)
    return _create("recepciones", payload, user)


@router.patch("/recepciones/{recepcion_id}")
async def update_recepcion(recepcion_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("recepciones", recepcion_id, payload, user)


@router.delete("/recepciones/{recepcion_id}")
async def delete_recepcion(recepcion_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("recepciones", recepcion_id, user)


@router.get("/recepcion-lineas")
async def list_recepcion_lineas(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("recepcion_lineas", request, user, limit=limit, offset=offset)


@router.get("/recepcion-lineas/{linea_id}")
async def get_recepcion_linea(linea_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("recepcion_lineas", linea_id, user)


@router.post("/recepcion-lineas", status_code=status.HTTP_201_CREATED)
async def create_recepcion_linea(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("recepcion_lineas", payload, user)


@router.patch("/recepcion-lineas/{linea_id}")
async def update_recepcion_linea(linea_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("recepcion_lineas", linea_id, payload, user)


@router.delete("/recepcion-lineas/{linea_id}")
async def delete_recepcion_linea(linea_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("recepcion_lineas", linea_id, user)


@router.get("/no-conformidades")
async def list_no_conformidades(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("no_conformidades", request, user, limit=limit, offset=offset)


@router.get("/no-conformidades/{no_conformidad_id}")
async def get_no_conformidad(no_conformidad_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("no_conformidades", no_conformidad_id, user)


@router.post("/no-conformidades", status_code=status.HTTP_201_CREATED)
async def create_no_conformidad(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    payload.setdefault("created_by", user.id)
    return _create("no_conformidades", payload, user)


@router.patch("/no-conformidades/{no_conformidad_id}")
async def update_no_conformidad(no_conformidad_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("no_conformidades", no_conformidad_id, payload, user)


@router.delete("/no-conformidades/{no_conformidad_id}")
async def delete_no_conformidad(no_conformidad_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("no_conformidades", no_conformidad_id, user)


@router.get("/historial-consumo")
async def list_historial_consumo(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("historial_consumo", request, user, limit=limit, offset=offset, order_by="fecha")


@router.get("/historial-consumo/{historial_id}")
async def get_historial_consumo(historial_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("historial_consumo", historial_id, user)


@router.post("/historial-consumo", status_code=status.HTTP_201_CREATED)
async def create_historial_consumo(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _create("historial_consumo", payload, user)


@router.patch("/historial-consumo/{historial_id}")
async def update_historial_consumo(historial_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("historial_consumo", historial_id, payload, user)


@router.delete("/historial-consumo/{historial_id}")
async def delete_historial_consumo(historial_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("historial_consumo", historial_id, user)


@router.get("/notificaciones")
async def list_notificaciones(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    return _list("notificaciones", request, user, limit=limit, offset=offset)


@router.get("/notificaciones/{notificacion_id}")
async def get_notificacion(notificacion_id: str, user: CurrentUser = Depends(get_current_user)):
    return _get("notificaciones", notificacion_id, user)


@router.post("/notificaciones", status_code=status.HTTP_201_CREATED)
async def create_notificacion(payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    payload.setdefault("usuario_id", user.id)
    return _create("notificaciones", payload, user)


@router.patch("/notificaciones/{notificacion_id}")
async def update_notificacion(notificacion_id: str, payload: dict[str, Any], user: CurrentUser = Depends(get_current_user)):
    return _update("notificaciones", notificacion_id, payload, user)


@router.delete("/notificaciones/{notificacion_id}")
async def delete_notificacion(notificacion_id: str, user: CurrentUser = Depends(get_current_user)):
    return _delete("notificaciones", notificacion_id, user)
