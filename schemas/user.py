"""Schemas de usuarios."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

VALID_ROLES = {
    "superadmin",
    "admin",
    "gerencia",
    "logistica",
    "almacen",
    "almacen_senior",
    "cotizador",
    "asesor",
    "tecnico",
    "informes",
}


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    nombre_completo: str = Field(min_length=1, max_length=200)
    rol: str
    sede_id: UUID | None = None
    activo: bool = True


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr | None = None
    nombre_completo: str
    rol: str
    role_id: UUID | None = None
    sede_id: UUID | None = None
    activo: bool
    is_superuser: bool = False
    telefono: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime
