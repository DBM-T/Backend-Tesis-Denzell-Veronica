"""Gestion de usuarios con Supabase Auth + usuarios/roles."""
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from auth import CurrentUser, require_roles
from database import supabase_admin
from schemas.user import VALID_ROLES, UserCreate, UserOut
from services.user_store import get_role_record, sync_usuario_from_auth

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
    role = get_role_record(body.rol)
    if role is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El rol '{body.rol}' no existe o no esta activo en la base de datos",
        )

    if body.sede_id:
        sede_res = (
            admin.table("sedes")
            .select("id")
            .eq("id", str(body.sede_id))
            .eq("activa", True)
            .single()
            .execute()
        )
        if not sede_res.data:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"La sede con id '{body.sede_id}' no existe o esta inactiva",
            )

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
