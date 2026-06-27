from __future__ import annotations

from dataclasses import asdict

from supabase._async.client import AsyncClient

from app.ml.inference.features import recolectar_features_ranking_proveedor
from app.ml.inference.runtime import predecir_ranking_proveedores


async def generate_ranking_for_rfq(client: AsyncClient, rfq_id: str) -> list[dict]:
    candidates, parametros = await recolectar_features_ranking_proveedor(client, rfq_id)
    ranking_items = predecir_ranking_proveedores(candidates)
    if not ranking_items:
        return []

    model = None
    model_row = await client.table("modelos_ml").select("id,version").eq("tipo_modelo", "xgboost_proveedor").eq("activo", True).limit(1).execute()
    if model_row.data:
        model = model_row.data[0]

    await client.table("inferencias_ml").insert(
        {
            "modelo_id": model["id"] if model else None,
            "parametros_entrada": parametros,
            "resultado": [asdict(item) for item in ranking_items],
        }
    ).execute()

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
                "version_modelo": model["version"] if model else "heuristic_fallback",
            }
        )

    await client.table("ranking_proveedores_ml").insert(ranking_rows).execute()
    return ranking_rows
