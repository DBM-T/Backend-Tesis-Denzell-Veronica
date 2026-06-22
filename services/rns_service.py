"""
services/rns_service.py
════════════════════════════════════════════════════════════
RNSService — Motor de búsqueda de equivalencias
Módulo 1 (Búsqueda Inteligente) + Módulo 4 (Consolidador)

Flujo principal:
  1. Técnico/asesor escribe descripción del repuesto buscado
  2. RNSService compara contra catálogo con similarity()
  3. Retorna candidatos con score ≥ umbral, priorizando stock
  4. Almacén confirma o rechaza → se registra en part_equivalences
════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import torch
from loguru import logger

from config import get_settings
from database import get_conn
from rns_module.model import SASNN

_s = get_settings()


@dataclass
class PartCandidate:
    part_id:            str
    part_name:          str
    description:        str
    brand:              str | None
    similarity_score:   float
    available_quantity: float
    branch_id:          str | None
    branch_name:        str | None
    source:             str          # 'stock'|'supplier_catalog'|'cross_branch'


@dataclass
class RNSSearchResult:
    input_description:    str
    candidates:           list[PartCandidate] = field(default_factory=list)
    found_above_threshold: bool = False
    threshold_used:       float = _s.rns_similarity_threshold
    response_ms:          int   = 0
    model_version_id:     str | None = None


class RNSService:
    """
    Singleton que mantiene el modelo SASNN cargado en memoria.
    Se inicializa una vez en el startup de FastAPI (main.py).
    """
    _model: SASNN | None = None
    _model_version_id: str | None = None

    async def load_model(self):
        """Carga el modelo activo desde la BD o el archivo local."""
        async with get_conn() as conn:
            row = await conn.fetchrow(
                "SELECT id, model_path, similarity_threshold FROM rns_model_versions "
                "WHERE is_active = TRUE LIMIT 1"
            )

        if row and row["model_path"] and Path(row["model_path"]).exists():
            model_path = row["model_path"]
            threshold  = float(row["similarity_threshold"])
            self._model_version_id = str(row["id"])
            logger.info(f"Cargando SASNN desde {model_path} (threshold={threshold})")
            self._model = SASNN(encoder_name=_s.rns_encoder_name)
            state = torch.load(model_path, map_location="cpu")
            self._model.load_state_dict(state)
            self._model.eval()
        else:
            logger.warning(
                "No hay modelo activo en BD o archivo no encontrado. "
                "Usando encoder base sin fine-tuning (Sprint 0)."
            )
            self._model = SASNN(encoder_name=_s.rns_encoder_name)
            self._model.eval()

    # ── Búsqueda principal ────────────────────────────────────

    async def search(
        self,
        query_description: str,
        branch_id: str | None = None,
        top_k: int | None = None,
    ) -> RNSSearchResult:
        """
        Busca repuestos equivalentes al query_description.
        Primero revisa stock disponible, luego catálogo de proveedores.
        """
        k = top_k or _s.rns_top_k
        t0 = time.time()

        if self._model is None:
            await self.load_model()

        # 1. Candidatos desde inventario (stock disponible)
        stock_candidates = await self._fetch_stock_candidates(branch_id)
        # 2. Candidatos desde catálogo de proveedores
        supplier_candidates = await self._fetch_supplier_candidates()

        all_candidates = stock_candidates + supplier_candidates
        if not all_candidates:
            return RNSSearchResult(
                input_description=query_description,
                response_ms=int((time.time() - t0) * 1000),
            )

        # 3. Calcular similitud con el modelo SASNN
        descriptions = [c["description"] for c in all_candidates]
        scores = self._model.similarity(query_description, descriptions)

        # 4. Construir resultado filtrado y ordenado
        result_candidates: list[PartCandidate] = []
        for cand, score in zip(all_candidates, scores):
            if score >= _s.rns_similarity_threshold:
                result_candidates.append(PartCandidate(
                    part_id=cand["part_id"],
                    part_name=cand["part_name"],
                    description=cand["description"],
                    brand=cand.get("brand"),
                    similarity_score=round(score, 4),
                    available_quantity=cand.get("quantity", 0),
                    branch_id=cand.get("branch_id"),
                    branch_name=cand.get("branch_name"),
                    source=cand["source"],
                ))

        result_candidates.sort(key=lambda x: x.similarity_score, reverse=True)

        ms = int((time.time() - t0) * 1000)
        logger.info(
            f"RNS search '{query_description[:50]}' → "
            f"{len(result_candidates)} resultados en {ms}ms"
        )
        return RNSSearchResult(
            input_description=query_description,
            candidates=result_candidates[:k],
            found_above_threshold=len(result_candidates) > 0,
            threshold_used=_s.rns_similarity_threshold,
            response_ms=ms,
            model_version_id=self._model_version_id,
        )

    # ── Helpers BD ────────────────────────────────────────────

    async def _fetch_stock_candidates(self, branch_id: str | None) -> list[dict]:
        """Trae repuestos con stock > 0."""
        async with get_conn() as conn:
            query = """
                SELECT
                    p.id          AS part_id,
                    p.name        AS part_name,
                    p.description,
                    p.brand,
                    i.quantity,
                    i.branch_id,
                    b.name        AS branch_name,
                    'stock'       AS source
                FROM inventory i
                JOIN parts    p ON p.id = i.part_id
                JOIN branches b ON b.id = i.branch_id
                WHERE i.quantity > 0 AND p.active = TRUE
            """
            params = []
            if branch_id:
                query += " AND i.branch_id = $1"
                params.append(branch_id)
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def _fetch_supplier_candidates(self) -> list[dict]:
        """Trae ítems activos del catálogo de proveedores."""
        async with get_conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    COALESCE(sc.part_id::TEXT, sc.id::TEXT) AS part_id,
                    COALESCE(p.name, sc.description)        AS part_name,
                    sc.description,
                    p.brand,
                    0                                       AS quantity,
                    NULL                                    AS branch_id,
                    NULL                                    AS branch_name,
                    'supplier_catalog'                      AS source
                FROM supplier_catalog sc
                LEFT JOIN parts p ON p.id = sc.part_id
                WHERE sc.active = TRUE
                """
            )
        return [dict(r) for r in rows]

    # ── Log de consultas ──────────────────────────────────────

    async def log_query(
        self,
        result: RNSSearchResult,
        supply_request_id: str | None,
        reviewed_by: str | None,
    ) -> str:
        """Persiste la consulta RNS en rns_query_log. Retorna el id del log."""
        top_results = [
            {
                "part_id": c.part_id,
                "score":   c.similarity_score,
                "source":  c.source,
            }
            for c in result.candidates
        ]
        import json
        async with get_conn() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rns_query_log
                    (supply_request_id, query_type, model_version_id,
                     input_description, top_results, threshold_used,
                     found_above_threshold, response_ms, reviewed_by)
                VALUES ($1,'stock_search',$2,$3,$4::jsonb,$5,$6,$7,$8)
                RETURNING id
                """,
                supply_request_id,
                result.model_version_id,
                result.input_description,
                json.dumps(top_results),
                result.threshold_used,
                result.found_above_threshold,
                result.response_ms,
                reviewed_by,
            )
        return str(row["id"])


# Instancia global (singleton)
rns_service = RNSService()
