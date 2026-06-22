"""routers/auth.py — Login, token refresh, perfil"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from supabase import create_client
from config import get_settings
from auth import get_current_user, CurrentUser
from fastapi import Depends

router = APIRouter()
_s = get_settings()


class LoginRequest(BaseModel):
    email:    str
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user_role:     str
    permissions:   dict


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    sb = create_client(_s.supabase_url, _s.supabase_anon_key)
    try:
        res = sb.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")

    # Obtener rol del usuario
    from database import supabase_admin
    admin = supabase_admin()
    u_data = (
        admin.table("users")
        .select("role_id, roles(name, permissions)")
        .eq("id", res.user.id)
        .single()
        .execute()
    )
    role_info = u_data.data.get("roles", {}) if u_data.data else {}

    return TokenResponse(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
        user_role=role_info.get("name",""),
        permissions=role_info.get("permissions",{}),
    )


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    sb = create_client(_s.supabase_url, _s.supabase_anon_key)
    try:
        res = sb.auth.refresh_session(refresh_token)
        return {"access_token": res.session.access_token}
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de refresco inválido")


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return user
