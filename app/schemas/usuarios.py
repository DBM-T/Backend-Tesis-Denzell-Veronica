from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.enums import UserRole, UserStatus


class UsuarioFilter(BaseModel):
    rol: UserRole | None = None
    sede_id: UUID | None = None
    estado: UserStatus | None = None


class UsuarioBase(BaseModel):
    nombres: str = Field(min_length=1, max_length=255)
    apellidos: str = Field(min_length=1, max_length=255)
    email: EmailStr
    telefono: str | None = None
    sede_id: UUID | None = None


class UsuarioCreate(UsuarioBase):
    password: str = Field(min_length=6)
    rol: UserRole


class UsuarioUpdate(BaseModel):
    nombres: str | None = Field(default=None, min_length=1, max_length=255)
    apellidos: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    telefono: str | None = None
    sede_id: UUID | None = None
    rol: UserRole | None = None
    estado: UserStatus | None = None


class UsuarioRead(UsuarioBase):
    id: UUID
    rol: UserRole
    estado: UserStatus
    created_at: datetime
    updated_at: datetime
