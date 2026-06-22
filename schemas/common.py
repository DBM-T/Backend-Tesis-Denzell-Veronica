"""schemas/common.py — Schemas Pydantic v2 compartidos"""
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime


class UUIDBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None
