from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status
from postgrest.exceptions import APIError
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_service_role_client
from app.schemas.enums import UserRole, UserStatus
from app.schemas.sedes import SedeCreate, SedeRead, SedeUpdate
from app.schemas.usuarios import UsuarioCreate, UsuarioRead, UsuarioUpdate


def _user_row_to_schema(row: dict[str, Any]) -> UsuarioRead:
    return UsuarioRead.model_validate(row)


def _sede_row_to_schema(row: dict[str, Any]) -> SedeRead:
    return SedeRead.model_validate(row)


async def _email_exists(client: AsyncClient, email: str, exclude_id: str | None = None) -> bool:
    query = client.table("perfiles").select("id").ilike("email", email)
    if exclude_id:
        query = query.neq("id", exclude_id)
    response = await query.limit(1).execute()
    return bool(response.data)


async def _get_user_profile_or_404(client: AsyncClient, user_id: str) -> dict[str, Any]:
    response = await (
        client.table("perfiles")
        .select("id,nombres,apellidos,email,rol,sede_id,estado,telefono,created_at,updated_at")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return response.data


async def list_users(
    client: AsyncClient,
    *,
    rol: UserRole | None = None,
    sede_id: UUID | None = None,
    estado: UserStatus | None = None,
) -> list[UsuarioRead]:
    query = client.table("perfiles").select(
        "id,nombres,apellidos,email,rol,sede_id,estado,telefono,created_at,updated_at"
    )
    if rol is not None:
        query = query.eq("rol", rol.value)
    if sede_id is not None:
        query = query.eq("sede_id", str(sede_id))
    if estado is not None:
        query = query.eq("estado", estado.value)
    response = await query.order("created_at", desc=True).execute()
    return [_user_row_to_schema(row) for row in response.data or []]


async def create_user(payload: UsuarioCreate) -> UsuarioRead:
    service_client = await create_service_role_client()

    if await _email_exists(service_client, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya existe.")

    auth_user = None
    try:
        auth_user = await service_client.auth.admin.create_user(
            {
                "email": str(payload.email).lower(),
                "password": payload.password,
                "email_confirm": True,
                "user_metadata": {
                    "nombres": payload.nombres,
                    "apellidos": payload.apellidos,
                },
            }
        )
        profile_response = await service_client.table("perfiles").insert(
            {
                "id": auth_user.user.id,
                "nombres": payload.nombres,
                "apellidos": payload.apellidos,
                "email": str(payload.email).lower(),
                "rol": payload.rol.value,
                "sede_id": str(payload.sede_id) if payload.sede_id else None,
                "estado": UserStatus.activo.value,
                "telefono": payload.telefono,
            }
        ).execute()
        return _user_row_to_schema(profile_response.data[0])
    except APIError:
        if auth_user is not None:
            await service_client.auth.admin.delete_user(auth_user.user.id, should_soft_delete=True)
        raise


async def update_user(
    client: AsyncClient,
    *,
    current_user_id: str,
    target_user_id: str,
    payload: UsuarioUpdate,
    is_admin: bool,
) -> UsuarioRead:
    existing = await _get_user_profile_or_404(client, target_user_id)
    data: dict[str, Any] = {}

    sensitive_fields = {"rol", "sede_id", "estado"}
    if not is_admin and any(getattr(payload, field) is not None for field in sensitive_fields):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede modificar rol, sede o estado.",
        )

    if not is_admin and current_user_id != target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes editar tu propio perfil o ser administrador.",
        )

    if payload.email is not None:
        normalized_email = str(payload.email).lower()
        if await _email_exists(client, normalized_email, exclude_id=target_user_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya existe.")
        data["email"] = normalized_email
    if payload.nombres is not None:
        data["nombres"] = payload.nombres
    if payload.apellidos is not None:
        data["apellidos"] = payload.apellidos
    if payload.telefono is not None:
        data["telefono"] = payload.telefono
    if payload.sede_id is not None:
        data["sede_id"] = str(payload.sede_id)
    if payload.rol is not None:
        data["rol"] = payload.rol.value
    if payload.estado is not None:
        data["estado"] = payload.estado.value

    if not data:
        return _user_row_to_schema(existing)

    response = await client.table("perfiles").update(data).eq("id", target_user_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return _user_row_to_schema(response.data[0])


async def deactivate_user(client: AsyncClient, target_user_id: str) -> UsuarioRead:
    response = await client.table("perfiles").update({"estado": UserStatus.inactivo.value}).eq(
        "id", target_user_id
    ).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return _user_row_to_schema(response.data[0])


async def log_session(
    client: AsyncClient,
    *,
    usuario_id: str,
    accion: str,
    request: Request | None = None,
) -> None:
    ip = None
    if request is not None:
        ip = request.client.host if request.client else None
    await client.table("sesiones_log").insert(
        {"usuario_id": usuario_id, "accion": accion, "ip": ip}
    ).execute()


async def list_sedes(client: AsyncClient) -> list[SedeRead]:
    response = await client.table("sedes").select("id,nombre,direccion,telefono,estado,created_at").order(
        "created_at", desc=True
    ).execute()
    return [_sede_row_to_schema(row) for row in response.data or []]


async def create_sede(client: AsyncClient, payload: SedeCreate) -> SedeRead:
    response = await client.table("sedes").insert(payload.model_dump()).execute()
    return _sede_row_to_schema(response.data[0])


async def update_sede(client: AsyncClient, sede_id: str, payload: SedeUpdate) -> SedeRead:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        current = await client.table("sedes").select("id,nombre,direccion,telefono,estado,created_at").eq(
            "id", sede_id
        ).single().execute()
        if not current.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada.")
        return _sede_row_to_schema(current.data)
    response = await client.table("sedes").update(data).eq("id", sede_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada.")
    return _sede_row_to_schema(response.data[0])


async def delete_sede(client: AsyncClient, sede_id: str) -> SedeRead:
    response = await client.table("sedes").update({"estado": "inactivo"}).eq("id", sede_id).execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada.")
    return _sede_row_to_schema(response.data[0])
