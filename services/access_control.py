"""Helpers de permisos por rol y alcance usando el JWT actual."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from auth import CurrentUser
from database import supabase_admin

ROLE_MATRIX: dict[str, dict[str, str]] = {
    "roles": {"superadmin": "CRUD", "admin": "CRUD", "gerencia": "R", "informes": "R"},
    "sedes": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R",
        "almacen_senior": "R",
        "asesor": "R",
        "tecnico": "R",
        "informes": "R",
    },
    "usuarios": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "almacen": "R*",
        "almacen_senior": "R*",
        "asesor": "R*",
        "tecnico": "R*",
    },
    "clientes": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R",
        "almacen_senior": "R",
        "cotizador": "R",
        "asesor": "CRU",
        "tecnico": "R",
        "informes": "R",
    },
    "vehiculos": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R",
        "almacen_senior": "R",
        "asesor": "CRU",
        "tecnico": "R",
        "informes": "R",
    },
    "categorias_producto": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R",
        "almacen_senior": "R",
        "cotizador": "R",
        "asesor": "R",
        "tecnico": "R",
        "informes": "R",
    },
    "productos": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "R",
        "almacen_senior": "CRUD",
        "cotizador": "R",
        "asesor": "R",
        "tecnico": "R",
        "informes": "R",
    },
    "proveedores": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen_senior": "R",
        "cotizador": "R",
    },
    "catalogo_precios": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "logistica": "CRUD",
        "almacen": "R",
        "almacen_senior": "R",
        "cotizador": "R",
    },
    "proveedor_metricas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "informes": "R",
    },
    "citas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R*",
        "almacen_senior": "R*",
        "asesor": "CRU",
        "tecnico": "R*",
        "informes": "R",
    },
    "ordenes_trabajo": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "RU",
        "almacen": "RU*",
        "almacen_senior": "RU*",
        "asesor": "CRU",
        "tecnico": "RU*",
        "informes": "R",
    },
    "ot_lineas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "RU*",
        "almacen_senior": "RU*",
        "asesor": "CRU",
        "tecnico": "RU*",
        "informes": "R",
    },
    "stock": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "RU*",
        "almacen_senior": "RU*",
        "asesor": "R",
        "tecnico": "R",
        "informes": "R",
    },
    "stock_movimientos": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "R*",
        "almacen_senior": "R*",
        "tecnico": "R",
        "informes": "R",
    },
    "requisiciones_compra": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "RA",
        "logistica": "CRUA",
        "almacen": "CR",
        "almacen_senior": "CR*",
        "cotizador": "R",
        "tecnico": "CR",
    },
    "requisicion_lineas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "CR",
        "almacen_senior": "CR",
    },
    "cotizaciones_rfq": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen_senior": "R",
        "cotizador": "CRUD",
    },
    "ordenes_compra": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "RA",
        "logistica": "CRUA",
        "almacen": "R*",
        "almacen_senior": "R*",
        "cotizador": "R",
    },
    "oc_lineas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "R*",
        "almacen_senior": "R*",
    },
    "recepciones": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "CRU*",
        "almacen_senior": "CRU*",
    },
    "recepcion_lineas": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRUD",
        "almacen": "CRU*",
        "almacen_senior": "CRU*",
    },
    "no_conformidades": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "CRU",
        "almacen": "R",
        "almacen_senior": "R",
    },
    "ml_modelos": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
    },
    "ml_predicciones_demanda": {
        "superadmin": "CRUD",
        "admin": "CRU",
        "gerencia": "RA",
        "logistica": "R",
        "informes": "R",
    },
    "historial_consumo": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R",
        "logistica": "R",
        "almacen": "R*",
        "almacen_senior": "R*",
        "tecnico": "R",
        "informes": "R",
    },
    "notificaciones": {
        "superadmin": "CRUD",
        "admin": "CRUD",
        "gerencia": "R*",
        "logistica": "R*",
        "almacen": "R*",
        "almacen_senior": "R*",
        "cotizador": "R*",
        "asesor": "R*",
        "tecnico": "R*",
        "informes": "R*",
    },
}

ACTION_CODES = {"create": "C", "read": "R", "update": "U", "delete": "D", "approve": "A"}

SCOPES = {
    "usuarios": {"almacen": "self", "almacen_senior": "self", "asesor": "self", "tecnico": "self"},
    "citas": {"almacen": "sede", "almacen_senior": "sede", "tecnico": "sede"},
    "ordenes_trabajo": {"almacen": "sede", "almacen_senior": "sede", "tecnico": "tecnico"},
    "ot_lineas": {"almacen": "ot_sede", "almacen_senior": "ot_sede", "tecnico": "ot_tecnico"},
    "stock": {"almacen": "sede", "almacen_senior": "sede"},
    "stock_movimientos": {"almacen": "sede", "almacen_senior": "sede"},
    "requisiciones_compra": {"almacen_senior": "sede"},
    "ordenes_compra": {"almacen": "sede", "almacen_senior": "sede"},
    "oc_lineas": {"almacen": "oc_sede", "almacen_senior": "oc_sede"},
    "recepciones": {"almacen": "sede", "almacen_senior": "sede"},
    "recepcion_lineas": {"almacen": "recepcion_sede", "almacen_senior": "recepcion_sede"},
    "historial_consumo": {"almacen": "sede", "almacen_senior": "sede"},
    "notificaciones": {
        "gerencia": "own_user",
        "logistica": "own_user",
        "almacen": "own_user",
        "almacen_senior": "own_user",
        "cotizador": "own_user",
        "asesor": "own_user",
        "tecnico": "own_user",
        "informes": "own_user",
    },
}


def permission_string(user: CurrentUser, resource: str) -> str:
    if user.is_superuser:
        return "CRUDA"
    return ROLE_MATRIX.get(resource, {}).get(user.role, "")


def ensure_action(user: CurrentUser, resource: str, action: str) -> None:
    code = ACTION_CODES[action]
    perms = permission_string(user, resource).replace("*", "")
    if code not in perms:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"El rol '{user.role}' no tiene permiso '{action}' sobre '{resource}'",
        )


def resource_scope(user: CurrentUser, resource: str) -> str:
    perms = permission_string(user, resource)
    if not perms.endswith("*"):
        return "all"
    return SCOPES.get(resource, {}).get(user.role, "all")


def fetch_row(resource: str, row_id: str) -> dict[str, Any] | None:
    result = supabase_admin().table(resource).select("*").eq("id", row_id).limit(1).execute()
    if not result.data:
        return None
    return result.data[0]


def row_allowed(user: CurrentUser, resource: str, row: dict[str, Any]) -> bool:
    scope = resource_scope(user, resource)
    if scope == "all":
        return True
    if scope == "self":
        return str(row.get("id")) == user.id
    if scope == "own_user":
        return str(row.get("usuario_id")) == user.id
    if scope == "sede":
        return user.sede_id is not None and str(row.get("sede_id")) == str(user.sede_id)
    if scope == "tecnico":
        return str(row.get("tecnico_id")) == user.id
    if scope == "ot_sede":
        parent = fetch_row("ordenes_trabajo", str(row.get("ot_id")))
        return bool(parent) and str(parent.get("sede_id")) == str(user.sede_id)
    if scope == "ot_tecnico":
        parent = fetch_row("ordenes_trabajo", str(row.get("ot_id")))
        return bool(parent) and str(parent.get("tecnico_id")) == user.id
    if scope == "oc_sede":
        parent = fetch_row("ordenes_compra", str(row.get("oc_id")))
        return bool(parent) and str(parent.get("sede_id")) == str(user.sede_id)
    if scope == "recepcion_sede":
        parent = fetch_row("recepciones", str(row.get("recepcion_id")))
        return bool(parent) and str(parent.get("sede_id")) == str(user.sede_id)
    return False


def filter_rows(user: CurrentUser, resource: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row_allowed(user, resource, row)]


def ensure_row_access(user: CurrentUser, resource: str, row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registro no encontrado")
    if not row_allowed(user, resource, row):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a este registro")
    return row


def ensure_payload_scope(user: CurrentUser, resource: str, payload: dict[str, Any]) -> None:
    scope = resource_scope(user, resource)
    if scope == "all":
        return
    if scope == "self" and payload.get("id") not in (None, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes operar tu propio registro")
    if scope == "own_user" and payload.get("usuario_id") not in (None, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes operar tus notificaciones")
    if scope == "sede":
        if user.sede_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu usuario no tiene sede asignada")
        sede_id = payload.get("sede_id")
        if sede_id is not None and str(sede_id) != str(user.sede_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes operar registros de tu sede")
    if scope == "tecnico":
        tecnico_id = payload.get("tecnico_id")
        if tecnico_id is not None and str(tecnico_id) != user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Solo puedes operar ordenes asignadas a tu usuario tecnico",
            )
