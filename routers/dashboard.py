"""routers/dashboard.py — KPIs gerenciales (Módulo 5)"""
from fastapi import APIRouter, Depends, Query
from uuid import UUID
from auth import require_roles, CurrentUser
from database import get_conn

router = APIRouter()


@router.get("/kpis")
async def get_kpis(
    branch_id: UUID | None = None,
    _user: CurrentUser = Depends(require_roles("gerente", "admin")),
):
    """KPIs en tiempo real — usa la vista v_dashboard_kpis."""
    async with get_conn() as conn:
        if branch_id:
            rows = await conn.fetch(
                "SELECT * FROM v_dashboard_kpis WHERE branch_id = $1", branch_id
            )
        else:
            rows = await conn.fetch("SELECT * FROM v_dashboard_kpis")
    return [dict(r) for r in rows]


@router.get("/kpis/history")
async def kpi_history(
    branch_id: UUID | None = None,
    days:      int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_roles("gerente", "admin")),
):
    """Histórico de snapshots KPI."""
    async with get_conn() as conn:
        filters, params = ["snapshot_date >= NOW() - make_interval(days => $1)"], [days]
        i = 2
        if branch_id:
            filters.append(f"branch_id = ${i}"); params.append(branch_id); i += 1
        where = " AND ".join(filters)
        rows = await conn.fetch(
            f"SELECT * FROM kpi_snapshots WHERE {where} ORDER BY snapshot_date DESC",
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/catalog")
async def catalog_stats(_user: CurrentUser = Depends(require_roles("gerente", "almacen", "admin"))):
    """Vista de equivalencias del catálogo — usa v_catalog_equivalences."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT category,
                   COUNT(*) AS total_skus,
                   COUNT(canonical_part_id) AS linked_to_canonical,
                   COUNT(equivalence_status) FILTER (WHERE equivalence_status='confirmed') AS confirmed_equivalences,
                   SUM(total_stock) AS total_stock_units
            FROM v_catalog_equivalences
            GROUP BY category
            ORDER BY total_skus DESC
            """
        )
    return [dict(r) for r in rows]


@router.post("/kpis/snapshot")
async def take_kpi_snapshot(
    branch_id: UUID | None = None,
    user: CurrentUser = Depends(require_roles("admin")),
):
    """Guarda un snapshot diario de KPIs en kpi_snapshots."""
    async with get_conn() as conn:
        # Leer valores actuales desde las vistas
        kpi_rows = await conn.fetch(
            "SELECT * FROM v_dashboard_kpis" + (" WHERE branch_id=$1" if branch_id else ""),
            *([branch_id] if branch_id else []),
        )
        inserted = 0
        for k in kpi_rows:
            await conn.execute(
                """
                INSERT INTO kpi_snapshots
                    (snapshot_date, branch_id,
                     requests_total, requests_resolved_by_rns,
                     avg_parts_pending_hours, pending_equivalences_count)
                VALUES (CURRENT_DATE, $1, $2, $3, $4, $5)
                ON CONFLICT (snapshot_date, branch_id) DO UPDATE
                    SET requests_total=$2, requests_resolved_by_rns=$3,
                        avg_parts_pending_hours=$4
                """,
                k["branch_id"],
                k["total_requests_30d"] or 0,
                k["resolved_by_rns_30d"] or 0,
                k["avg_hours_in_parts_pending"] or 0,
                k["pending_equivalences"] or 0,
            )
            inserted += 1
    return {"snapshots_saved": inserted}
