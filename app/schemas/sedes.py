from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SedeBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    direccion: str | None = None
    telefono: str | None = None


class SedeCreate(SedeBase):
    pass


class SedeUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    direccion: str | None = None
    telefono: str | None = None


class SedeRead(SedeBase):
    id: UUID
    estado: str
    created_at: datetime
