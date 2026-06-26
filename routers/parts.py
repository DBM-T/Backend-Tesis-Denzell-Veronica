"""Catalogo de productos/repuestos."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import get_conn
from schemas.part import PartCreate, PartOut, PartUpdate

router = APIRouter()


@router.get("", response_model=list[PartOut])
async def list_parts(
    q: str | None = Query(None, description="Busqueda por SKU, nombre o descripcion"),
    category_id: UUID | None = None,
    active: bool = True,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = ["p.is_active = $1"], [active]
        i = 2
        if category_id:
            filters.append(f"p.categoria_id = ${i}")
            params.append(category_id)
            i += 1
        if q:
            filters.append(
                f"(p.sku_padre ILIKE ${i} OR p.nombre ILIKE ${i} OR p.descripcion ILIKE ${i})"
            )
            params.append(f"%{q}%")
            i += 1

        rows = await conn.fetch(
            f"""
            SELECT
              p.*,
              c.nombre AS categoria,
              COALESCE(SUM(s.qty_disponible), 0) AS total_stock
            FROM productos p
            LEFT JOIN categorias_producto c ON c.id = p.categoria_id
            LEFT JOIN stock s ON s.producto_id = p.id
            WHERE {" AND ".join(filters)}
            GROUP BY p.id, c.nombre
            ORDER BY p.nombre
            LIMIT ${i} OFFSET ${i + 1}
            """,
            *params,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


@router.get("/{part_id}", response_model=PartOut)
async def get_part(part_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*, c.nombre AS categoria, COALESCE(SUM(s.qty_disponible), 0) AS total_stock
            FROM productos p
            LEFT JOIN categorias_producto c ON c.id = p.categoria_id
            LEFT JOIN stock s ON s.producto_id = p.id
            WHERE p.id = $1
            GROUP BY p.id, c.nombre
            """,
            part_id,
        )
    if not row:
        raise HTTPException(404, "Producto no encontrado")
    return dict(row)


@router.post("", response_model=PartOut, status_code=201)
async def create_part(
    body: PartCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen_senior")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO productos (
              sku_padre, nombre, descripcion, categoria_id, marca, codigo_fabricante,
              unidad_medida, vehiculos_compatibles, precio_referencia
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
            RETURNING *, NULL::text AS categoria, 0::numeric AS total_stock
            """,
            body.sku_padre,
            body.nombre,
            body.descripcion,
            body.categoria_id,
            body.marca,
            body.codigo_fabricante,
            body.unidad_medida,
            body.vehiculos_compatibles,
            body.precio_referencia,
        )
    return dict(row)


@router.patch("/{part_id}", response_model=PartOut)
async def update_part(
    part_id: UUID,
    body: PartUpdate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen_senior")),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Sin campos para actualizar")

    values = []
    assignments = []
    for key, value in updates.items():
        if key == "vehiculos_compatibles":
            assignments.append(f"{key} = ${len(values) + 2}::jsonb")
        else:
            assignments.append(f"{key} = ${len(values) + 2}")
        values.append(value)

    async with get_conn() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE productos
            SET {", ".join(assignments)}
            WHERE id = $1
            RETURNING *, NULL::text AS categoria, 0::numeric AS total_stock
            """,
            part_id,
            *values,
        )
    if not row:
        raise HTTPException(404, "Producto no encontrado")
    return dict(row)
