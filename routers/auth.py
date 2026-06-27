"""Login, token refresh y perfil."""
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel
from supabase import create_client
from supabase_auth.errors import AuthApiError

from auth import CurrentUser, _decode_supabase_jwt, create_local_app_token, get_current_user
from config import get_settings
from services.user_store import get_user_context, get_user_context_by_email, sync_usuario_from_auth

router = APIRouter()
_s = get_settings()


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_role: str
    permissions: dict


def _get_value(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    try:
        sb = create_client(_s.supabase_url, _s.supabase_publishable_key)
        res = sb.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except AuthApiError as exc:
        detail = str(exc)
        logger.error(f"Error de Auth al iniciar sesion para {body.email}: {detail}")
        if "Database error" in detail:
            if _s.app_env == "development":
                data = get_user_context_by_email(body.email, require_active=True)
                if not data:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales invalidas")
                local_token = create_local_app_token(data)
                logger.warning(
                    f"Usando fallback de login local en development para {body.email} por falla de Supabase Auth"
                )
                return TokenResponse(
                    access_token=local_token,
                    refresh_token=local_token,
                    user_role=data.get("rol") or "tecnico",
                    permissions=data.get("permisos") or {},
                )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Supabase Auth reporto un error interno al validar este usuario",
            )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales invalidas")
    except Exception as exc:
        logger.error(f"Error inesperado en login para {body.email}: {exc}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales invalidas")

    user_id = _get_value(res.user, "id")
    user_metadata = _get_value(res.user, "user_metadata", None) or {}
    app_metadata = _get_value(res.user, "app_metadata", None) or {}
    data = get_user_context(user_id, require_active=False)

    fallback_role = user_metadata.get("rol") or app_metadata.get("role") or "tecnico"
    if not data:
        try:
            data = sync_usuario_from_auth(
                user_id=user_id,
                email=_get_value(res.user, "email", body.email),
                nombre_completo=user_metadata.get("nombre_completo", body.email),
                role_name=fallback_role,
                sede_id=user_metadata.get("sede_id"),
                activo=True,
            )
        except Exception as exc:
            logger.warning(f"No se pudo crear/actualizar usuarios para {body.email}: {exc}")
            data = {}

    user_role = data.get("rol", "") or fallback_role

    return TokenResponse(
        access_token=_get_value(res.session, "access_token"),
        refresh_token=_get_value(res.session, "refresh_token"),
        user_role=user_role,
        permissions=data.get("permisos") or {},
    )


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    sb = create_client(_s.supabase_url, _s.supabase_publishable_key)
    try:
        res = sb.auth.refresh_session(refresh_token)
        return {"access_token": res.session.access_token}
    except Exception:
        if _s.app_env == "development":
            try:
                payload = _decode_supabase_jwt(refresh_token)
                user_id = payload.get("sub")
                if user_id:
                    user = get_user_context(user_id, require_active=True)
                    if user:
                        return {"access_token": create_local_app_token(user)}
            except Exception:
                pass
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de refresco invalido")


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return user
