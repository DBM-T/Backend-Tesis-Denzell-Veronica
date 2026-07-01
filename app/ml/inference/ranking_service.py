from __future__ import annotations

from dataclasses import asdict

from supabase._async.client import AsyncClient

from app.ml.inference.features import recolectar_features_ranking_proveedor
from app.ml.inference.runtime import get_active_model, predecir_ranking_proveedores
from app.schemas.enums import MLModelType


async def generate_ranking_for_rfq(client: AsyncClient, rfq_id: str, *, force: bool = False) -> list[dict]:
    candidates, parametros = await recolectar_features_ranking_proveedor(client, rfq_id)
    ranking_items = predecir_ranking_proveedores(candidates)
    if not ranking_items:
        return []

    model = get_active_model(MLModelType.xgboost_proveedor)
    modelo_id = None
    version_modelo = "heuristic_fallback"
    if model:
        version_modelo = model.version
        if not str(model.model_id).startswith("local-"):
            modelo_id = model.model_id

    if modelo_id:
        await client.table("inferencias_ml").insert(
            {
                "modelo_id": modelo_id,
                "parametros_entrada": parametros,
                "resultado": [asdict(item) for item in ranking_items],
            }
        ).execute()

    if force:
        await client.table("ranking_proveedores_ml").delete().eq("rfq_id", rfq_id).execute()

    ranking_rows: list[dict] = []
    for item in ranking_items:
        ranking_rows.append(
            {
                "rfq_id": rfq_id,
                "proveedor_id": item.proveedor_id,
                "repuesto_id": item.repuesto_id,
                "score_total_ml": str(item.score_total_ml),
                "ranking_posicion": item.ranking_posicion,
                "canal_sugerido_ml": item.canal_sugerido_ml.value if item.canal_sugerido_ml else None,
                "version_modelo": version_modelo,
            }
        )

    await client.table("ranking_proveedores_ml").insert(ranking_rows).execute()
    return ranking_rows
