from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.schemas.auth import CurrentUser
from app.schemas.enums import UserRole, UserStatus
from app.schemas.sedes import SedeCreate, SedeRead, SedeUpdate
from app.schemas.usuarios import UsuarioCreate, UsuarioRead, UsuarioUpdate
from app.services.users_service import (
    create_sede,
    create_user,
    deactivate_user,
    delete_sede,
    list_sedes,
    list_users,
    update_sede,
    update_user,
)


router = APIRouter()


@router.get(
    "",
    response_model=list[UsuarioRead],
    summary="Listar usuarios",
    description="Lista usuarios con filtros por rol, sede y estado. Solo administrador.",
)
async def get_users(
    rol: UserRole | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    estado: UserStatus | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(UserRole.administrador)),
):
    return await list_users(current_user.supabase, rol=rol, sede_id=sede_id, estado=estado)


@router.post(
    "",
    response_model=UsuarioRead,
    summary="Crear usuario",
    description="Crea auth.users y perfiles. Solo administrador.",
)
async def post_user(
    payload: UsuarioCreate,
    current_user: CurrentUser = Depends(require_role(UserRole.administrador)),
):
    return await create_user(payload)


@router.get(
    "/sedes",
    response_model=list[SedeRead],
    summary="Listar sedes",
    description="Lista todas las sedes activas e inactivas. Solo administrador.",
)
async def get_sedes(current_user: CurrentUser = Depends(require_role(UserRole.administrador))):
    return await list_sedes(current_user.supabase)


@router.post(
    "/sedes",
    response_model=SedeRead,
    summary="Crear sede",
    description="Crea una nueva sede. Solo administrador.",
)
async def post_sede(payload: SedeCreate, current_user: CurrentUser = Depends(require_role(UserRole.administrador))):
    return await create_sede(current_user.supabase, payload)


@router.put(
    "/sedes/{sede_id}",
    response_model=SedeRead,
    summary="Actualizar sede",
    description="Actualiza una sede existente. Solo administrador.",
)
async def put_sede(
    sede_id: UUID,
    payload: SedeUpdate,
    current_user: CurrentUser = Depends(require_role(UserRole.administrador)),
):
    return await update_sede(current_user.supabase, str(sede_id), payload)


@router.delete(
    "/sedes/{sede_id}",
    response_model=SedeRead,
    summary="Desactivar sede",
    description="Marca la sede como inactiva. Solo administrador.",
)
async def delete_sede_endpoint(
    sede_id: UUID,
    current_user: CurrentUser = Depends(require_role(UserRole.administrador)),
):
    return await delete_sede(current_user.supabase, str(sede_id))


@router.put(
    "/{user_id}",
    response_model=UsuarioRead,
    summary="Actualizar usuario",
    description="Permite editar el perfil propio en campos no sensibles o, si es admin, cualquier usuario.",
)
async def put_user(
    user_id: UUID,
    payload: UsuarioUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await update_user(
        current_user.supabase,
        current_user_id=str(current_user.id),
        target_user_id=str(user_id),
        payload=payload,
        is_admin=current_user.role == UserRole.administrador,
    )


@router.delete(
    "/{user_id}",
    response_model=UsuarioRead,
    summary="Desactivar usuario",
    description="Marca el usuario como inactivo. Solo administrador.",
)
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_role(UserRole.administrador)),
):
    return await deactivate_user(current_user.supabase, str(user_id))
