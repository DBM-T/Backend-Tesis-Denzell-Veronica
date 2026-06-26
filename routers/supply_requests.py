"""Panel de requisiciones de compra."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_current_user, require_roles
from database import get_conn
from schemas.supply_request import SupplyRequestCreate, SupplyRequestOut, SupplyRequestStatusUpdate

router = APIRouter()


@router.get("", response_model=list[SupplyRequestOut])
async def list_requests(
    estado: str | None = None,
    sede_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if estado:
            filters.append(f"estado = ${i}")
            params.append(estado)
            i += 1
        if sede_id:
            filters.append(f"sede_id = ${i}")
            params.append(sede_id)
            i += 1

        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM requisiciones_compra
            {where}
            ORDER BY created_at DESC
            LIMIT ${i} OFFSET ${i + 1}
            """,
            *params,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


@router.get("/active")
async def active_panel(_user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT pr.*, sd.nombre AS sede, ot.ot_codigo, COUNT(rl.id) AS total_lineas
            FROM requisiciones_compra pr
            JOIN sedes sd ON sd.id = pr.sede_id
            LEFT JOIN ordenes_trabajo ot ON ot.id = pr.ot_id
            LEFT JOIN requisicion_lineas rl ON rl.requisicion_id = pr.id
            WHERE pr.estado IN ('borrador','pendiente_aprobacion','aprobada')
            GROUP BY pr.id, sd.nombre, ot.ot_codigo
            ORDER BY pr.created_at DESC
            LIMIT 100
            """
        )
    return [dict(r) for r in rows]


@router.post("", response_model=SupplyRequestOut, status_code=201)
async def create_request(
    body: SupplyRequestCreate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "almacen", "almacen_senior")),
):
    async with get_conn() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO requisiciones_compra
                    (sede_id, ot_id, origen, prioridad, observaciones, solicitado_por)
                VALUES ($1,$2,$3,$4,$5,$6)
                RETURNING *
                """,
                body.sede_id,
                body.ot_id,
                body.origen,
                body.prioridad,
                body.observaciones,
                user.id,
            )
            for line in body.lineas:
                await conn.execute(
                    """
                    INSERT INTO requisicion_lineas (
                      requisicion_id, producto_id, qty_solicitada, precio_estimado,
                      proveedor_sugerido_id, observaciones
                    )
                    VALUES ($1,$2,$3,$4,$5,$6)
                    """,
                    row["id"],
                    line.producto_id,
                    line.qty_solicitada,
                    line.precio_estimado,
                    line.proveedor_sugerido_id,
                    line.observaciones,
                )
    return dict(row)


@router.patch("/{request_id}/status", response_model=SupplyRequestOut)
async def update_status(
    request_id: UUID,
    body: SupplyRequestStatusUpdate,
    user: CurrentUser = Depends(require_roles("superadmin", "admin", "logistica", "gerencia")),
):
    approve_fields = ""
    params = [request_id, body.estado, body.observaciones]
    if body.estado == "aprobada":
        approve_fields = ", aprobado_por=$4, aprobado_at=NOW()"
        params.append(user.id)

    async with get_conn() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE requisiciones_compra
            SET estado=$2, observaciones=COALESCE($3, observaciones){approve_fields}
            WHERE id=$1
            RETURNING *
            """,
            *params,
        )
    if not row:
        raise HTTPException(404, "Requisicion no encontrada")
    return dict(row)


@router.get("/{request_id}", response_model=SupplyRequestOut)
async def get_request(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM requisiciones_compra WHERE id=$1", request_id)
    if not row:
        raise HTTPException(404, "Requisicion no encontrada")
    return dict(row)


@router.get("/{request_id}/lines")
async def get_request_lines(request_id: UUID, _user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT rl.*, p.sku_padre, p.nombre AS producto
            FROM requisicion_lineas rl
            JOIN productos p ON p.id = rl.producto_id
            WHERE rl.requisicion_id = $1
            ORDER BY rl.created_at
            """,
            request_id,
        )
    return [dict(r) for r in rows]
