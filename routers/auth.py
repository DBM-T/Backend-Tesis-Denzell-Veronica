"""Login, token refresh y perfil."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import create_client

from auth import CurrentUser, get_current_user
from config import get_settings
from database import supabase_admin

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


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    sb = create_client(_s.supabase_url, _s.supabase_publishable_key)
    try:
        res = sb.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales invalidas")

    profile = (
        supabase_admin()
        .table("profiles")
        .select("rol, is_superuser")
        .eq("id", res.user.id)
        .single()
        .execute()
    )
    data = profile.data or {}
    user_role = "superadmin" if data.get("is_superuser") else data.get("rol", "")

    return TokenResponse(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
        user_role=user_role,
        permissions={},
    )


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    sb = create_client(_s.supabase_url, _s.supabase_publishable_key)
    try:
        res = sb.auth.refresh_session(refresh_token)
        return {"access_token": res.session.access_token}
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de refresco invalido")


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return user
