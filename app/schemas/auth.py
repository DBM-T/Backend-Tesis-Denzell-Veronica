from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from supabase._async.client import AsyncClient

from app.schemas.enums import UserRole, UserStatus


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserProfile(BaseModel):
    id: UUID
    nombres: str
    apellidos: str
    email: EmailStr
    rol: UserRole
    sede_id: UUID | None = None
    estado: UserStatus
    telefono: str | None = None
    created_at: datetime
    updated_at: datetime


class AuthenticatedUser(BaseModel):
    id: UUID
    email: EmailStr
    role: UserRole
    profile: UserProfile


class CurrentUser(AuthenticatedUser):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    access_token: str = Field(exclude=True)
    supabase: AsyncClient = Field(exclude=True)


class SessionTokens(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None


class LoginResponse(BaseModel):
    user: AuthenticatedUser
    session: SessionTokens
