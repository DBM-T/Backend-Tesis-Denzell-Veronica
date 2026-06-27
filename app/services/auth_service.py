from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_anon_client, create_request_client
from app.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    SessionTokens,
    UserProfile,
)


async def get_profile_by_user_id(client: AsyncClient, user_id: str) -> UserProfile:
    response = await (
        client.table("perfiles")
        .select("id,nombres,apellidos,email,rol,sede_id,estado,telefono,created_at,updated_at")
        .eq("id", user_id)
        .single()
        .execute()
    )
    return UserProfile.model_validate(response.data)


async def authenticate_user(payload: LoginRequest) -> LoginResponse:
    client = await create_anon_client()
    try:
        auth_response = await client.auth.sign_in_with_password(
            {"email": str(payload.email).lower(), "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales invalidas.",
        ) from exc

    if auth_response.user is None or auth_response.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase no devolvio una sesion valida.",
        )

    request_client = await create_request_client(auth_response.session.access_token)

    try:
        profile = await get_profile_by_user_id(request_client, auth_response.user.id)
    except APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario autenticado no tiene un perfil valido en el sistema.",
        ) from exc

    return LoginResponse(
        user=AuthenticatedUser(
            id=profile.id,
            email=profile.email,
            role=profile.rol,
            profile=profile,
        ),
        session=SessionTokens(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            expires_in=auth_response.session.expires_in,
            expires_at=auth_response.session.expires_at,
        ),
    )


async def logout_user(client: AsyncClient) -> None:
    await client.auth.sign_out()
