"""KPIs gerenciales para la base consolidada."""
from uuid import UUID

from fastapi import APIRouter, Depends

from auth import CurrentUser, require_roles
from database import supabase_admin

router = APIRouter()


def _count_rows(table_name: str, sede_id: UUID | None = None) -> int:
    query = supabase_admin().table(table_name).select("id")
    if sede_id:
        query = query.eq("sede_id", str(sede_id))
    result = query.execute()
    return len(result.data or [])


@router.get("/kpis")
async def get_kpis(
    sede_id: UUID | None = None,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia")),
):
    stock_query = supabase_admin().table("stock").select("id, qty_disponible, stock_min")
    if sede_id:
        stock_query = stock_query.eq("sede_id", str(sede_id))
    stock_rows = stock_query.execute().data or []

    return {
        "ordenes_trabajo": _count_rows("ordenes_trabajo", sede_id),
        "requisiciones": _count_rows("requisiciones_compra", sede_id),
        "ordenes_compra": _count_rows("ordenes_compra", sede_id),
        "productos_bajo_minimo": sum(
            1 for row in stock_rows if float(row["qty_disponible"]) < float(row["stock_min"])
        ),
        "predicciones_demanda": _count_rows("ml_predicciones_demanda", sede_id),
        "proveedores_con_score": _count_rows("proveedor_metricas"),
    }


@router.get("/stock")
async def stock_status(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica", "almacen", "almacen_senior")),
):
    result = supabase_admin().table("v_stock_estado").select("*").execute()
    return result.data or []


@router.get("/forecast")
async def active_forecast(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    result = supabase_admin().table("v_forecast_vigente").select("*").execute()
    return result.data or []


@router.get("/suppliers/ranking")
async def supplier_ranking(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    result = supabase_admin().table("v_ranking_proveedores").select("*").execute()
    return result.data or []


@router.get("/trace")
async def traceability(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    result = supabase_admin().table("v_trazabilidad").select("*").order("ot_creada", desc=True).range(0, 99).execute()
    return result.data or []
