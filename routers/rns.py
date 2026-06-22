"""
routers/rns.py — Motor RNS (Módulos 1 y 4)

Endpoints:
  POST /rns/search                  → Módulo 1: buscar equivalentes
  POST /rns/equivalences/confirm    → Almacén confirma equivalencia
  POST /rns/equivalences/reject     → Almacén rechaza equivalencia
  GET  /rns/equivalences            → Listar equivalencias confirmadas
  POST /rns/consolidate             → Módulo 4: agrupar solicitudes similares
  GET  /rns/training-pairs          → Pares de entrenamiento
  POST /rns/training-pairs          → Agregar par
  GET  /rns/model-versions          → Versiones del modelo
"""
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user, require_roles, CurrentUser
from database import get_conn
from services.rns_service import rns_service
from schemas.rns import (
    RNSSearchRequest, RNSSearchResponse, PartCandidateOut,
    EquivalenceConfirm, TrainingPairCreate,
)

router = APIRouter()


# ── Módulo 1: Búsqueda Inteligente ───────────────────────────────

@router.post("/search", response_model=RNSSearchResponse)
async def search_equivalents(
    body: RNSSearchRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Recibe una descripción textual y retorna los repuestos más similares
    del inventario y catálogo de proveedores con score ≥ umbral.
    """
    result = await rns_service.search(
        query_description=body.description,
        branch_id=str(body.branch_id) if body.branch_id else None,
        top_k=body.top_k,
    )

    # Persistir consulta en rns_query_log
    log_id = await rns_service.log_query(
        result=result,
        supply_request_id=str(body.supply_request_id) if body.supply_request_id else None,
        reviewed_by=user.id,
    )

    return RNSSearchResponse(
        input_description=result.input_description,
        candidates=[
            PartCandidateOut(
                part_id=c.part_id,
                part_name=c.part_name,
                description=c.description,
                brand=c.brand,
                similarity_score=c.similarity_score,
                available_quantity=c.available_quantity,
                branch_name=c.branch_name,
                source=c.source,
            )
            for c in result.candidates
        ],
        found_above_threshold=result.found_above_threshold,
        threshold_used=result.threshold_used,
        response_ms=result.response_ms,
        log_id=log_id,
    )


# ── Equivalencias ────────────────────────────────────────────────

@router.post("/equivalences/confirm")
async def confirm_equivalence(
    body: EquivalenceConfirm,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    """
    Almacén confirma que dos repuestos son equivalentes.
    Si ya existe la fila, actualiza su status a 'confirmed'.
    Adicionalmente marca la solicitud como resuelta por equivalencia.
    """
    async with get_conn() as conn:
        # Upsert en part_equivalences
        row = await conn.fetchrow(
            """
            INSERT INTO part_equivalences
                (part_a_id, part_b_id, similarity_score, status,
                 confirmed_by, confirmed_at, confirmed_at_request_id)
            VALUES ($1,$2,$3,'confirmed',$4,NOW(),$5)
            ON CONFLICT ON CONSTRAINT uq_equivalence_pair DO UPDATE
                SET status='confirmed', confirmed_by=$4,
                    confirmed_at=NOW(), confirmed_at_request_id=$5
            RETURNING id
            """,
            body.part_a_id, body.part_b_id, body.similarity_score,
            user.id, body.supply_request_id,
        )

        # Marcar la solicitud como resuelta si viene relacionada
        if body.supply_request_id:
            await conn.execute(
                """
                UPDATE supply_requests
                SET resolved_by_equivalence=TRUE,
                    resolved_equivalent_part_id=$2,
                    status='ready_for_advisor'
                WHERE id=$1
                """,
                body.supply_request_id, body.part_b_id,
            )

        # Agregar par de entrenamiento automáticamente
        await conn.execute(
            """
            INSERT INTO rns_training_pairs
                (description_a, description_b, part_a_id, part_b_id,
                 label, source, validated_by, validated_at)
            SELECT pa.description, pb.description, pa.id, pb.id,
                   TRUE, 'almacen_confirmed', $3, NOW()
            FROM parts pa, parts pb
            WHERE pa.id=$1 AND pb.id=$2
            ON CONFLICT DO NOTHING
            """,
            body.part_a_id, body.part_b_id, user.id,
        )

    return {"equivalence_id": str(row["id"]), "status": "confirmed"}


@router.post("/equivalences/{equivalence_id}/reject")
async def reject_equivalence(
    equivalence_id: UUID,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE part_equivalences SET status='rejected' WHERE id=$1 RETURNING id, part_a_id, part_b_id",
            equivalence_id,
        )
        if not row:
            raise HTTPException(404, "Equivalencia no encontrada")

        # Agregar par negativo al entrenamiento
        await conn.execute(
            """
            INSERT INTO rns_training_pairs
                (description_a, description_b, part_a_id, part_b_id,
                 label, source, validated_by, validated_at)
            SELECT pa.description, pb.description, pa.id, pb.id,
                   FALSE, 'almacen_confirmed', $3, NOW()
            FROM parts pa, parts pb
            WHERE pa.id=$1 AND pb.id=$2
            ON CONFLICT DO NOTHING
            """,
            row["part_a_id"], row["part_b_id"], user.id,
        )
    return {"status": "rejected"}


@router.get("/equivalences")
async def list_equivalences(
    status: str = Query("confirmed", description="suggested|confirmed|rejected"),
    limit:  int = Query(50, le=200),
    offset: int = 0,
    _user: CurrentUser = Depends(get_current_user),
):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT pe.*, pa.name AS part_a_name, pb.name AS part_b_name
            FROM part_equivalences pe
            JOIN parts pa ON pa.id = pe.part_a_id
            JOIN parts pb ON pb.id = pe.part_b_id
            WHERE pe.status = $1
            ORDER BY pe.similarity_score DESC
            LIMIT $2 OFFSET $3
            """,
            status, limit, offset,
        )
    return [dict(r) for r in rows]


# ── Módulo 4: Consolidador ────────────────────────────────────────

@router.post("/consolidate")
async def consolidate_requests(
    branch_id: UUID | None = None,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    """
    Detecta solicitudes activas con descripciones similares (score ≥ umbral)
    y las agrupa en request_consolidation_groups.
    Retorna los grupos creados con sus solicitudes agrupadas.
    """
    async with get_conn() as conn:
        # Traer solicitudes pendientes de partes
        pending = await conn.fetch(
            """
            SELECT sr.id, sr.part_description, wo.branch_id
            FROM supply_requests sr
            JOIN work_orders wo ON wo.id = sr.work_order_id
            WHERE sr.status IN ('requested','parts_pending')
            AND ($1::uuid IS NULL OR wo.branch_id = $1)
            """,
            branch_id,
        )

    if len(pending) < 2:
        return {"groups_created": 0, "message": "No hay suficientes solicitudes para consolidar"}

    # Agrupar por similitud RNS
    descriptions = [r["part_description"] for r in pending]
    groups: list[list[int]] = []
    assigned = set()

    for i, req_i in enumerate(pending):
        if i in assigned:
            continue
        group = [i]
        scores = rns_service._model.similarity(req_i["part_description"], descriptions)
        for j in range(i + 1, len(pending)):
            if j not in assigned and scores[j] >= rns_service._s.rns_similarity_threshold:
                group.append(j)
                assigned.add(j)
        if len(group) > 1:
            assigned.add(i)
            groups.append(group)

    # Persistir grupos
    groups_created = 0
    async with get_conn() as conn:
        for group_indices in groups:
            grp_row = await conn.fetchrow(
                "INSERT INTO request_consolidation_groups (managed_by) VALUES ($1) RETURNING id",
                user.id,
            )
            grp_id = grp_row["id"]
            for idx in group_indices:
                await conn.execute(
                    "INSERT INTO request_consolidation_items (group_id, request_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    grp_id, pending[idx]["id"],
                )
            groups_created += 1

    return {"groups_created": groups_created, "total_requests_grouped": sum(len(g) for g in groups)}


# ── Pares de entrenamiento ────────────────────────────────────────

@router.get("/training-pairs")
async def list_training_pairs(
    label:  bool | None = None,
    limit:  int = Query(100, le=500),
    offset: int = 0,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    async with get_conn() as conn:
        filters, params = [], []
        i = 1
        if label is not None:
            filters.append(f"label = ${i}"); params.append(label); i += 1
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = await conn.fetch(
            f"SELECT * FROM rns_training_pairs {where} ORDER BY created_at DESC LIMIT ${i} OFFSET ${i+1}",
            *params, limit, offset,
        )
    return [dict(r) for r in rows]


@router.post("/training-pairs", status_code=201)
async def add_training_pair(
    body: TrainingPairCreate,
    user: CurrentUser = Depends(require_roles("almacen", "admin")),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO rns_training_pairs
                (description_a, description_b, part_a_id, part_b_id,
                 label, source, validated_by, validated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
            RETURNING id
            """,
            body.description_a, body.description_b,
            body.part_a_id, body.part_b_id,
            body.label, body.source, user.id,
        )
    return {"id": str(row["id"])}


# ── Versiones del modelo ──────────────────────────────────────────

@router.get("/model-versions")
async def list_model_versions(_user: CurrentUser = Depends(get_current_user)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT * FROM rns_model_versions ORDER BY created_at DESC"
        )
    return [dict(r) for r in rows]
