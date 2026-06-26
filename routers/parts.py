"""Catalogo de productos/repuestos."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import supabase_admin
from schemas.part import PartCreate, PartOut, PartUpdate
from services.access_control import ensure_action
from services.postgrest_utils import relation_one, sum_decimal

router = APIRouter()


def _part_select() -> str:
    return (
        "id, sku_padre, nombre, descripcion, categoria_id, marca, codigo_fabricante, "
        "unidad_medida, vehiculos_compatibles, is_storable, is_active, precio_referencia, "
        "created_at, updated_at, categorias_producto(nombre), stock(qty_disponible)"
    )


def _serialize_part(row: dict) -> dict:
    category = relation_one(row.pop("categorias_producto", None))
    stock_items = row.pop("stock", None)
    row["categoria"] = category.get("nombre")
    row["total_stock"] = sum_decimal(stock_items, "qty_disponible")
    return row


@router.get("", response_model=list[PartOut])
async def list_parts(
    q: str | None = Query(None, description="Busqueda por SKU, nombre o descripcion"),
    category_id: UUID | None = None,
    active: bool = True,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    ensure_action(_user, "productos", "read")
    query = supabase_admin().table("productos").select(_part_select()).eq("is_active", active)
    if category_id:
        query = query.eq("categoria_id", str(category_id))
    if q:
        like = f"%{q}%"
        query = query.or_(f"sku_padre.ilike.{like},nombre.ilike.{like},descripcion.ilike.{like}")

    result = query.order("nombre").range(offset, offset + limit - 1).execute()
    return [_serialize_part(row) for row in result.data or []]


@router.get("/{part_id}", response_model=PartOut)
async def get_part(part_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    ensure_action(_user, "productos", "read")
    result = (
        supabase_admin()
        .table("productos")
        .select(_part_select())
        .eq("id", str(part_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Producto no encontrado")
    return _serialize_part(result.data[0])


@router.post("", response_model=PartOut, status_code=201)
async def create_part(
    body: PartCreate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen_senior")),
):
    result = (
        supabase_admin()
        .table("productos")
        .insert(
            {
                "sku_padre": body.sku_padre,
                "nombre": body.nombre,
                "descripcion": body.descripcion,
                "categoria_id": str(body.categoria_id) if body.categoria_id else None,
                "marca": body.marca,
                "codigo_fabricante": body.codigo_fabricante,
                "unidad_medida": body.unidad_medida,
                "vehiculos_compatibles": body.vehiculos_compatibles,
                "precio_referencia": body.precio_referencia,
            }
        )
        .execute()
    )
    if not result.data:
        raise HTTPException(500, "No se pudo crear el producto")
    row = dict(result.data[0])
    row["categoria"] = None
    row["total_stock"] = Decimal("0")
    return row


@router.patch("/{part_id}", response_model=PartOut)
async def update_part(
    part_id: UUID,
    body: PartUpdate,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen_senior")),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Sin campos para actualizar")
    if "categoria_id" in updates and updates["categoria_id"] is not None:
        updates["categoria_id"] = str(updates["categoria_id"])

    result = (
        supabase_admin()
        .table("productos")
        .update(updates)
        .eq("id", str(part_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Producto no encontrado")
    fresh = (
        supabase_admin()
        .table("productos")
        .select(_part_select())
        .eq("id", str(part_id))
        .limit(1)
        .execute()
    )
    return _serialize_part(fresh.data[0])


@router.delete("/{part_id}", status_code=200)
async def delete_part(
    part_id: UUID,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen_senior")),
):
    result = (
        supabase_admin()
        .table("productos")
        .update({"is_active": False})
        .eq("id", str(part_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Producto no encontrado")
    return {"detail": "Producto desactivado", "id": str(part_id)}
