"""Dependencias de autenticacion y autorizacion para FastAPI."""
from functools import lru_cache

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from pydantic import BaseModel

from config import get_settings
from database import supabase_admin

bearer = HTTPBearer()
_s = get_settings()


class CurrentUser(BaseModel):
    id: str
    email: str
    role: str
    role_id: str | None = None
    branch_id: str | None = None
    sede_id: str | None = None
    permissions: dict = {}


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> CurrentUser:
    token = creds.credentials
    try:
        payload = _decode_supabase_jwt(token)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido o expirado")

    result = (
        supabase_admin()
        .table("profiles")
        .select("id, rol, sede_id, activo, is_superuser")
        .eq("id", user_id)
        .eq("activo", True)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado o inactivo")

    profile = result.data
    role = "superadmin" if profile.get("is_superuser") else profile.get("rol", "")
    sede_id = profile.get("sede_id")
    return CurrentUser(
        id=profile["id"],
        email=payload.get("email", ""),
        role=role,
        branch_id=sede_id,
        sede_id=sede_id,
        permissions={},
    )


def require_roles(*roles: str):
    """Dependencia de autorizacion por rol."""

    async def _check(user: CurrentUser = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Rol '{user.role}' no tiene permiso. Requerido: {list(roles)}",
            )
        return user

    return _check


@lru_cache(maxsize=1)
def _load_jwks() -> dict:
    if not _s.supabase_jwks_url:
        return {}
    response = requests.get(_s.supabase_jwks_url, timeout=10)
    response.raise_for_status()
    return response.json()


def _decode_supabase_jwt(token: str) -> dict:
    if _s.supabase_jwks_url:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        jwks = _load_jwks()
        keys = jwks.get("keys", [])
        jwk_data = next((key for key in keys if key.get("kid") == key_id), None)
        if not jwk_data:
            raise JWTError("JWKS key not found")
        public_key = jwk.construct(jwk_data, algorithm=header.get("alg", "RS256"))
        return jwt.decode(
            token,
            public_key.to_pem().decode("utf-8"),
            algorithms=[header.get("alg", "RS256")],
            audience="authenticated",
        )

    if _s.supabase_jwt_secret:
        return jwt.decode(
            token,
            _s.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    raise JWTError("No JWT verification material configured")
