"""Utilidades para respuestas de PostgREST/Supabase."""
from decimal import Decimal
from typing import Any


def relation_one(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value else {}
    if isinstance(value, dict):
        return value
    return {}


def sum_decimal(items: list[dict[str, Any]] | None, key: str) -> Decimal:
    total = Decimal("0")
    for item in items or []:
        value = item.get(key)
        if value is not None:
            total += Decimal(str(value))
    return total

