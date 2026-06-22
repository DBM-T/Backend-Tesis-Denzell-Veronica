"""routers/parts.py — Catálogo de repuestos (Módulo 3)"""
from fastapi import APIRouter, Depends, Query, HTTPException
from uuid import UUID
from auth import get_current_user, require_roles, CurrentUser
from database import get_conn
from schemas.part import PartCreate, PartUpdate, PartOut

router = APIRouter()


@router.get("", response_model=list[PartOut])
async def list_parts(
    q:        str | None = Query(None, description="Búsqueda por nombre/descripción (trigrama)"),
    category: str | None = None,
    active:   bool       = True,
    limit:    int        = Query(50, le=200),
    offset:   int        = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = ["p.active = $1"], [active]
        i = 2
        if category:
            filters.append(f"p.category = ${i}"); params.append(category); i += 1
        if q:
            filters.append(
                f"(p.name ILIKE ${i} OR p.description % ${i} "
                f"OR p.description ILIKE ${i})"
            )
            params.append(f"%{q}%"); i += 1

        where = " AND ".join(filters)
        rows = await conn.fetch(
            f"""
            SELECT p.*, i.total_stock
            FROM parts p
            LEFT JOIN (
                SELECT part_id, SUM(quantity) AS total_stock
                FROM inventory WHERE quantity>0 GROUP BY part_id
            ) i ON i.part_id = p.id
            WHERE {where}
            ORDER BY p.name
            LIMIT ${i} OFFSET ${i+1}
            """,
            *params, limit, offset,
        )
    return [dict(r) for r in rows]


@router.get("/{part_id}", response_model=PartOut)
async def get_part(part_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM parts WHERE id = $1", part_id)
    if not row:
        raise HTTPException(404, "Repuesto no encontrado")
    return dict(row)


@router.post("", response_model=PartOut, status_code=201)
async def create_part(
    body: PartCreate,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO parts (name, description, brand, part_number,
                internal_code, vehicle_compatibility, category, unit_of_measure)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            RETURNING *
            """,
            body.name, body.description, body.brand, body.part_number,
            body.internal_code, body.vehicle_compatibility,
            body.category, body.unit_of_measure,
        )
    return dict(row)


@router.patch("/{part_id}", response_model=PartOut)
async def update_part(
    part_id: UUID,
    body: PartUpdate,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Sin campos para actualizar")
    set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    async with get_conn() as conn:
        row = await conn.fetchrow(
            f"UPDATE parts SET {set_clause} WHERE id=$1 RETURNING *",
            part_id, *updates.values(),
        )
    if not row:
        raise HTTPException(404, "Repuesto no encontrado")
    return dict(row)
