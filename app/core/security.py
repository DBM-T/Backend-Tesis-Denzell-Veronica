from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest.exceptions import APIError
from supabase._async.client import AsyncClient
from supabase_auth.errors import AuthApiError

from app.core.supabase_client import create_request_client
from app.schemas.auth import CurrentUser
from app.schemas.enums import UserRole
from app.services.auth_service import get_profile_by_user_id


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un token Bearer valido.",
        )

    access_token = credentials.credentials
    client = await create_request_client(access_token)
    try:
        auth_response = await client.auth.get_user(access_token)
    except AuthApiError as exc:
        message = "La sesion ha expirado. Inicia sesion nuevamente."
        if "expired" not in str(exc).lower():
            message = "No se pudo validar el token de acceso."
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
        ) from exc

    if auth_response is None or auth_response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar el usuario autenticado.",
        )

    try:
        profile = await get_profile_by_user_id(client, auth_response.user.id)
    except APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se pudo cargar el perfil del usuario autenticado.",
        ) from exc

    current_user = CurrentUser(
        id=profile.id,
        email=profile.email,
        role=profile.rol,
        profile=profile,
        access_token=access_token,
        supabase=client,
    )
    request.state.user_id = str(profile.id)
    request.state.user_role = profile.rol.value
    return current_user


async def get_supabase_client(current_user: CurrentUser = Depends(get_current_user)) -> AsyncClient:
    return current_user.supabase


def require_role(*allowed_roles: UserRole | str) -> Callable:
    normalized_roles = {
        role if isinstance(role, UserRole) else UserRole(role) for role in allowed_roles
    }

    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in normalized_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para realizar esta accion.",
            )
        return current_user

    return dependency
