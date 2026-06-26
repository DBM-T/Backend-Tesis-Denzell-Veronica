"""Gestion de usuarios con Supabase Auth + profiles."""
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from auth import CurrentUser, require_roles
from database import supabase_admin
from schemas.user import VALID_ROLES, UserCreate, UserOut

router = APIRouter()


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

    admin = supabase_admin()

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
        profile_res = (
            admin.table("profiles")
            .upsert(
                {
                    "id": auth_user_id,
                    "nombre_completo": body.nombre_completo,
                    "rol": body.rol,
                    "sede_id": str(body.sede_id) if body.sede_id else None,
                    "activo": body.activo,
                }
            )
            .execute()
        )
    except Exception as e:
        logger.error(f"Error al insertar profile; rollback Auth: {e}")
        try:
            admin.auth.admin.delete_user(auth_user_id)
        except Exception as del_err:
            logger.error(f"No se pudo eliminar usuario huerfano {auth_user_id}: {del_err}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al registrar perfil")

    if not profile_res.data:
        try:
            admin.auth.admin.delete_user(auth_user_id)
        except Exception as del_err:
            logger.error(f"No se pudo eliminar usuario huerfano {auth_user_id}: {del_err}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo crear perfil")

    return profile_res.data[0]
