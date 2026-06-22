"""schemas/part.py — Repuestos"""
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime


class PartCreate(BaseModel):
    name:                 str
    description:          str
    brand:                str | None  = None
    part_number:          str | None  = None
    internal_code:        str | None  = None
    vehicle_compatibility: str | None = None
    category:             str | None  = None
    unit_of_measure:      str         = "und"


class PartUpdate(BaseModel):
    name:                 str | None  = None
    description:          str | None  = None
    brand:                str | None  = None
    part_number:          str | None  = None
    vehicle_compatibility: str | None = None
    category:             str | None  = None
    active:               bool | None = None


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:                   UUID
    internal_code:        str | None
    name:                 str
    description:          str
    brand:                str | None
    part_number:          str | None
    vehicle_compatibility: str | None
    category:             str | None
    unit_of_measure:      str
    canonical_part_id:    UUID | None
    active:               bool
    created_at:           datetime
