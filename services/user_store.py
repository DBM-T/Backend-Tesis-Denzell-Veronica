"""Helpers para usuarios/roles en la nueva estructura de Supabase."""
from typing import Any

from database import supabase_admin


def _normalize_relation(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value else {}
    if isinstance(value, dict):
        return value
    return {}


def get_role_record(role_name: str) -> dict[str, Any] | None:
    result = (
        supabase_admin()
        .table("roles")
        .select("id, nombre, permisos, activo")
        .eq("nombre", role_name)
        .eq("activo", True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def get_user_context(user_id: str, require_active: bool = True) -> dict[str, Any] | None:
    result = (
        supabase_admin()
        .table("usuarios")
        .select(
            "id, nombre_completo, email, role_id, sede_id, activo, is_superuser, "
            "telefono, avatar_url, roles(nombre, permisos)"
        )
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    row = result.data[0]
    if require_active and not row.get("activo", False):
        return None

    role_data = _normalize_relation(row.get("roles"))
    row["rol"] = "superadmin" if row.get("is_superuser") else role_data.get("nombre", "")
    row["permisos"] = role_data.get("permisos") or {}
    return row


def sync_usuario_from_auth(
    *,
    user_id: str,
    email: str | None,
    nombre_completo: str,
    role_name: str,
    sede_id: str | None = None,
    activo: bool = True,
    telefono: str | None = None,
    avatar_url: str | None = None,
) -> dict[str, Any]:
    role = get_role_record(role_name) or get_role_record("tecnico")
    if role is None:
        raise RuntimeError("No existe un rol activo para sincronizar usuarios")

    is_superuser = role["nombre"] == "superadmin"
    payload = {
        "id": user_id,
        "nombre_completo": nombre_completo,
        "email": email,
        "role_id": role["id"],
        "sede_id": sede_id,
        "activo": activo,
        "is_superuser": is_superuser,
        "telefono": telefono,
        "avatar_url": avatar_url,
    }

    admin = supabase_admin()
    updated = admin.table("usuarios").update(payload).eq("id", user_id).execute()
    if not updated.data:
        admin.table("usuarios").upsert(payload).execute()

    user = get_user_context(user_id, require_active=False)
    if user is None:
        raise RuntimeError("No se pudo sincronizar el usuario en la tabla usuarios")
    return user

