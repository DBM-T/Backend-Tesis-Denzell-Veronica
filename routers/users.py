"""Gestion de usuarios con Supabase Auth + usuarios/roles."""
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from auth import CurrentUser, require_roles
from database import supabase_admin
from schemas.user import VALID_ROLES, UserCreate, UserOut, UserUpdate
from services.user_store import get_role_record, get_user_context, list_user_contexts, sync_usuario_from_auth

router = APIRouter()


def _serialize_user_out(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user.get("email"),
        "nombre_completo": user["nombre_completo"],
        "rol": user.get("rol", ""),
        "role_id": user.get("role_id"),
        "sede_id": user.get("sede_id"),
        "activo": user.get("activo", True),
        "is_superuser": user.get("is_superuser", False),
        "telefono": user.get("telefono"),
        "avatar_url": user.get("avatar_url"),
        "created_at": user["created_at"],
        "updated_at": user["updated_at"],
    }


def _as_uuid_str(value):
    return str(value) if value is not None else None


def _validate_role(role_name: str) -> dict:
    if role_name not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Rol invalido: '{role_name}'. Roles validos: {sorted(VALID_ROLES)}",
        )

    role = get_role_record(role_name)
    if role is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El rol '{role_name}' no existe o no esta activo en la base de datos",
        )
    return role


def _validate_sede(sede_id, admin) -> None:
    if sede_id is None:
        return

    sede_res = (
        admin.table("sedes")
        .select("id")
        .eq("id", str(sede_id))
        .eq("activa", True)
        .limit(1)
        .execute()
    )
    if not sede_res.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"La sede con id '{sede_id}' no existe o esta inactiva",
        )


@router.get("", response_model=list[UserOut])
async def list_users(
    include_inactive: bool = False,
    current_user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "almacen", "almacen_senior", "asesor", "tecnico")),
):
    users = list_user_contexts(include_inactive=include_inactive)
    if current_user.role in {"almacen", "almacen_senior", "asesor", "tecnico"}:
        users = [user for user in users if str(user["id"]) == current_user.id]
    return [_serialize_user_out(user) for user in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "almacen", "almacen_senior", "asesor", "tecnico")),
):
    user = get_user_context(user_id, require_active=False)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    if current_user.role in {"almacen", "almacen_senior", "asesor", "tecnico"} and user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes ver tu propio usuario")
    return _serialize_user_out(user)


@router.post("/register", response_model=UserOut, status_code=201)
async def register_user(
    body: UserCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    if body.rol not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Rol invalido: '{body.rol}'. Roles validos: {sorted(VALID_ROLES)}",
        )
    if body.rol == "superadmin" and _user.role != "superadmin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo un superadmin puede registrar otro usuario superadmin",
        )

    admin = supabase_admin()
    role = _validate_role(body.rol)
    _validate_sede(body.sede_id, admin)

    try:
        auth_res = admin.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "user_metadata": {
                    "nombre_completo": body.nombre_completo,
                    "rol": body.rol,
                    "sede_id": str(body.sede_id) if body.sede_id else None,
                },
            }
        )
    except Exception as e:
        err_msg = str(e).lower()
        if any(token in err_msg for token in ["already", "exists", "registered", "taken"]):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Ya existe un usuario con el email '{body.email}'",
            )
        logger.error(f"Error al crear usuario en Auth: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al crear usuario")

    auth_user_id = auth_res.user.id

    try:
        user = sync_usuario_from_auth(
            user_id=auth_user_id,
            email=body.email,
            nombre_completo=body.nombre_completo,
            role_name=role["nombre"],
            sede_id=str(body.sede_id) if body.sede_id else None,
            activo=body.activo,
        )
    except Exception as e:
        logger.error(f"Error al insertar usuario; rollback Auth: {e}")
        try:
            admin.auth.admin.delete_user(auth_user_id)
        except Exception as del_err:
            logger.error(f"No se pudo eliminar usuario huerfano {auth_user_id}: {del_err}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al registrar usuario")

    return _serialize_user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    admin = supabase_admin()
    current = get_user_context(user_id, require_active=False)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    if current.get("rol") == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo un superadmin puede modificar a otro superadmin",
        )

    changes = body.model_dump(exclude_unset=True)
    next_role = changes.get("rol", current.get("rol", ""))
    role = _validate_role(next_role)
    if next_role == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo un superadmin puede asignar el rol superadmin",
        )
    if "sede_id" in changes:
        _validate_sede(changes.get("sede_id"), admin)

    auth_payload: dict[str, object] = {
        "user_metadata": {
            "nombre_completo": changes.get("nombre_completo", current["nombre_completo"]),
            "rol": next_role,
            "sede_id": _as_uuid_str(changes["sede_id"]) if "sede_id" in changes else _as_uuid_str(current.get("sede_id")),
        },
        "app_metadata": {"role": next_role},
    }
    if "email" in changes:
        auth_payload["email"] = changes["email"]
        auth_payload["email_confirm"] = True
    if "password" in changes:
        auth_payload["password"] = changes["password"]

    try:
        admin.auth.admin.update_user_by_id(user_id, auth_payload)
    except Exception as exc:
        logger.error(f"Error al actualizar Auth para {user_id}: {exc}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al actualizar usuario")

    updated = sync_usuario_from_auth(
        user_id=user_id,
        email=changes.get("email", current.get("email")),
        nombre_completo=changes.get("nombre_completo", current["nombre_completo"]),
        role_name=role["nombre"],
        sede_id=_as_uuid_str(changes["sede_id"]) if "sede_id" in changes else _as_uuid_str(current.get("sede_id")),
        activo=changes.get("activo", current.get("activo", True)),
        telefono=changes.get("telefono", current.get("telefono")),
        avatar_url=changes.get("avatar_url", current.get("avatar_url")),
    )
    return _serialize_user_out(updated)


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_roles("superadmin", "admin")),
):
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes eliminar tu propia cuenta")

    admin = supabase_admin()
    current = get_user_context(user_id, require_active=False)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    if current.get("rol") == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo un superadmin puede eliminar a otro superadmin",
        )

    if current.get("rol") == "superadmin":
        active_superadmins = [
            user
            for user in list_user_contexts(include_inactive=False)
            if user.get("rol") == "superadmin"
        ]
        if len(active_superadmins) <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No se puede eliminar el ultimo superadmin activo",
            )

    try:
        admin.auth.admin.delete_user(user_id)
    except Exception as exc:
        logger.error(f"Error al eliminar usuario de Auth {user_id}: {exc}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al eliminar usuario")

    admin.table("usuarios").update({"activo": False}).eq("id", user_id).execute()
    return {"detail": "Usuario eliminado correctamente", "user_id": user_id}
