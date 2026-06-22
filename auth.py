"""
auth.py — Dependencia de autenticación para FastAPI.
Verifica el JWT de Supabase y retorna el usuario con su rol.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel
from config import get_settings
from database import supabase_admin

bearer = HTTPBearer()
_s = get_settings()


class CurrentUser(BaseModel):
    id:       str
    email:    str
    role:     str   # nombre del rol: 'almacen'|'tecnico'|'asesor'|...
    role_id:  str
    branch_id: str | None = None
    permissions: dict = {}


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> CurrentUser:
    token = creds.credentials
    try:
        payload = jwt.decode(
            token,
            _s.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado")

    # Obtener datos del usuario + rol (una sola consulta con join)
    sb = supabase_admin()
    result = (
        sb.table("users")
        .select("id, email, branch_id, role_id, roles(name, permissions)")
        .eq("id", user_id)
        .eq("active", True)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado o inactivo")

    u = result.data
    role_data = u.get("roles") or {}
    return CurrentUser(
        id=u["id"],
        email=u["email"],
        role=role_data.get("name", ""),
        role_id=u["role_id"],
        branch_id=u.get("branch_id"),
        permissions=role_data.get("permissions", {}),
    )


def require_roles(*roles: str):
    """Dependencia de autorización por rol. Uso: Depends(require_roles('admin','almacen'))"""
    async def _check(user: CurrentUser = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Rol '{user.role}' no tiene permiso. Requerido: {list(roles)}",
            )
        return user
    return _check
