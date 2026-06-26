"""KPIs gerenciales para la base consolidada."""
from uuid import UUID

from fastapi import APIRouter, Depends

from auth import CurrentUser, require_roles
from database import get_conn

router = APIRouter()


@router.get("/kpis")
async def get_kpis(
    sede_id: UUID | None = None,
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM ordenes_trabajo WHERE ($1::uuid IS NULL OR sede_id=$1)) AS ordenes_trabajo,
              (SELECT COUNT(*) FROM requisiciones_compra WHERE ($1::uuid IS NULL OR sede_id=$1)) AS requisiciones,
              (SELECT COUNT(*) FROM ordenes_compra WHERE ($1::uuid IS NULL OR sede_id=$1)) AS ordenes_compra,
              (SELECT COUNT(*) FROM stock WHERE ($1::uuid IS NULL OR sede_id=$1) AND qty_disponible < stock_min) AS productos_bajo_minimo,
              (SELECT COUNT(*) FROM ml_predicciones_demanda WHERE ($1::uuid IS NULL OR sede_id=$1)) AS predicciones_demanda,
              (SELECT COUNT(*) FROM proveedor_metricas) AS proveedores_con_score
            """,
            sede_id,
        )
    return dict(row)


@router.get("/stock")
async def stock_status(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica", "almacen", "almacen_senior")),
):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_stock_estado")
    return [dict(r) for r in rows]


@router.get("/forecast")
async def active_forecast(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_forecast_vigente")
    return [dict(r) for r in rows]


@router.get("/suppliers/ranking")
async def supplier_ranking(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_ranking_proveedores")
    return [dict(r) for r in rows]


@router.get("/trace")
async def traceability(
    _user: CurrentUser = Depends(require_roles("superadmin", "admin", "gerencia", "logistica")),
):
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT * FROM v_trazabilidad ORDER BY ot_creada DESC LIMIT 100")
    return [dict(r) for r in rows]
