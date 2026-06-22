"""schemas/rns.py — RNS endpoints"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class RNSSearchRequest(BaseModel):
    description:       str   = Field(..., min_length=3, max_length=500)
    supply_request_id: UUID  | None = None
    branch_id:         UUID  | None = None
    top_k:             int         = Field(5, ge=1, le=20)


class PartCandidateOut(BaseModel):
    part_id:            str
    part_name:          str
    description:        str
    brand:              str | None
    similarity_score:   float
    available_quantity: float
    branch_name:        str | None
    source:             str


class RNSSearchResponse(BaseModel):
    input_description:     str
    candidates:            list[PartCandidateOut]
    found_above_threshold: bool
    threshold_used:        float
    response_ms:           int
    log_id:                str | None = None


class EquivalenceConfirm(BaseModel):
    part_a_id:         UUID
    part_b_id:         UUID
    similarity_score:  float
    supply_request_id: UUID | None = None


class TrainingPairCreate(BaseModel):
    description_a: str
    description_b: str
    part_a_id:     UUID | None = None
    part_b_id:     UUID | None = None
    label:         bool        # True = equivalentes
    source:        str         = "manual"
