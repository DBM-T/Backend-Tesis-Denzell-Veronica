"""schemas/supply_request.py — Solicitudes de abastecimiento"""
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Literal


class SupplyRequestCreate(BaseModel):
    work_order_id:   UUID
    part_description: str
    quantity:        float = 1.0
    priority:        Literal["low","normal","high","urgent"] = "normal"
    notes:           str | None = None


class SupplyRequestStatusUpdate(BaseModel):
    status: Literal[
        "requested","quotations_work","parts_pending","ready_for_advisor","cancelled"
    ]
    notes: str | None = None


class SupplyRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:                         UUID
    work_order_id:              UUID
    part_description:           str
    quantity:                   float
    status:                     str
    priority:                   str
    parts_pending_since:        datetime | None
    resolved_by_equivalence:    bool
    resolved_equivalent_part_id: UUID | None
    purchase_order_id:          UUID | None
    notes:                      str | None
    created_at:                 datetime
