from fastapi import APIRouter, Depends, Request

from app.core.security import get_current_user
from app.core.rate_limit import auth_rate_limit
from app.core.supabase_client import create_request_client
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse
from app.services.auth_service import authenticate_user, logout_user
from app.services.users_service import log_session


router = APIRouter()


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesion con Supabase Auth",
    description="Autentica por email y password y devuelve el access token junto al perfil del usuario.",
    dependencies=[Depends(auth_rate_limit)],
)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    result = await authenticate_user(payload)
    request_client = await create_request_client(result.session.access_token)
    await log_session(
        request_client,
        usuario_id=str(result.user.id),
        accion="login",
        request=request,
    )
    return result


@router.get(
    "/me",
    response_model=CurrentUser,
    summary="Obtener usuario autenticado",
    description="Devuelve el perfil y rol del usuario actual a partir del JWT enviado.",
)
async def get_me(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return current_user


@router.post(
    "/logout",
    summary="Cerrar sesion",
    description="Cierra la sesion activa en Supabase Auth y registra el evento en sesiones_log.",
    dependencies=[Depends(auth_rate_limit)],
)
async def logout(request: Request, current_user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    await log_session(current_user.supabase, usuario_id=str(current_user.id), accion="logout", request=request)
    await logout_user(current_user.supabase)
    return {"message": "Sesion cerrada correctamente."}
