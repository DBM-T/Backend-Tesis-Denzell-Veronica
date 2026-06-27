from __future__ import annotations

from dataclasses import asdict
from statistics import mean

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.ml.inference.runtime import DemandaFeatures, PrioridadOTFeatures, RankingProveedorCandidate


async def recolectar_features_prioridad_ot(
    client: AsyncClient,
    ot_id: str,
    *,
    historial_vehiculo: float | None = None,
    tiempo_estimado_horas: float | None = None,
    disponibilidad_tecnico: float | None = None,
) -> tuple[PrioridadOTFeatures, dict]:
    ot_response = await client.table("ordenes_trabajo").select(
        "id,servicio_solicitado,vehiculo_placa,vehiculo_marca,vehiculo_modelo,vehiculo_anio,tecnico_id,sede_id"
    ).eq("id", ot_id).single().execute()
    if not ot_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OT no encontrada.")

    ot = ot_response.data
    if historial_vehiculo is None:
        if ot.get("vehiculo_placa"):
            history = await client.table("ordenes_trabajo").select("id").eq(
                "vehiculo_placa", ot["vehiculo_placa"]
            ).in_("estado", ["completed", "tech_completed"]).execute()
            historial_vehiculo = float(len(history.data or []))
        else:
            historial_vehiculo = 0.0

    if tiempo_estimado_horas is None:
        diagnostics = await client.table("diagnosticos_ot").select("id").eq("ot_id", ot_id).execute()
        required_parts = await client.table("ot_repuestos_requeridos").select("cantidad").eq("ot_id", ot_id).execute()
        tiempo_estimado_horas = max(1.0, (len(diagnostics.data or []) * 1.5) + sum(int(row["cantidad"]) for row in required_parts.data or []) * 0.5)

    if disponibilidad_tecnico is None:
        disponibilidad_tecnico = 0.5 if ot.get("tecnico_id") else 0.2

    features = PrioridadOTFeatures(
        ot_id=ot_id,
        servicio_solicitado=ot.get("servicio_solicitado") or "",
        historial_vehiculo=float(historial_vehiculo),
        tiempo_estimado_horas=float(tiempo_estimado_horas),
        disponibilidad_tecnico=float(disponibilidad_tecnico),
    )
    return features, asdict(features)


async def recolectar_features_ranking_proveedor(
    client: AsyncClient,
    rfq_id: str,
) -> tuple[list[RankingProveedorCandidate], dict]:
    rfq_response = await client.table("rfq").select("id").eq("id", rfq_id).single().execute()
    if not rfq_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFQ no encontrada.")

    detalle_response = await client.table("rfq_detalle").select("repuesto_id").eq("rfq_id", rfq_id).execute()
    proveedores_response = await client.table("proveedores").select(
        "id,tasa_entrega_a_tiempo,tasa_defectos,precio_promedio,volumen_compras_previas,lead_time_estimado_dias,canal_preferido,estado"
    ).eq("estado", "activo").execute()
    respuestas_response = await client.table("rfq_respuestas").select(
        "repuesto_id,precio_unitario,disponibilidad,lead_time_ofrecido_dias"
    ).eq("rfq_id", rfq_id).execute()

    response_map: dict[str, dict] = {row["repuesto_id"]: row for row in responses_or_empty(respuestas_response)}
    candidates: list[RankingProveedorCandidate] = []
    for detalle in detalle_response.data or []:
        for proveedor in proveedores_response.data or []:
            respuesta = response_map.get(detalle["repuesto_id"])
            candidates.append(
                RankingProveedorCandidate(
                    proveedor_id=str(proveedor["id"]),
                    repuesto_id=str(detalle["repuesto_id"]),
                    tasa_entrega_a_tiempo=float(proveedor.get("tasa_entrega_a_tiempo") or 0),
                    tasa_defectos=float(proveedor.get("tasa_defectos") or 0),
                    precio_promedio=float(proveedor.get("precio_promedio") or 0),
                    volumen_compras_previas=float(proveedor.get("volumen_compras_previas") or 0),
                    lead_time_estimado_dias=float(proveedor.get("lead_time_estimado_dias") or 0),
                    canal_preferido=proveedor.get("canal_preferido"),
                    precio_ofrecido=float(respuesta["precio_unitario"]) if respuesta else None,
                    disponibilidad=respuesta["disponibilidad"] if respuesta else None,
                    lead_time_ofrecido_dias=float(respuesta["lead_time_ofrecido_dias"]) if respuesta and respuesta.get("lead_time_ofrecido_dias") is not None else None,
                )
            )
    return candidates, {"rfq_id": rfq_id, "candidates": [asdict(candidate) for candidate in candidates]}


def responses_or_empty(response) -> list[dict]:
    return list(response.data or [])


async def recolectar_features_demanda(
    client: AsyncClient,
    repuesto_id: str,
    sede_id: str,
) -> tuple[DemandaFeatures, dict]:
    history = await client.table("historial_consumo").select(
        "cantidad_consumida,fecha_consumo"
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).order("fecha_consumo", desc=True).execute()
    params_response = await client.table("parametros_inventario").select(
        "stock_minimo,lead_time_base_dias,punto_reorden_sugerido_ml"
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).limit(1).execute()
    inventory_response = await client.table("inventario").select(
        "stock_actual"
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).limit(1).execute()

    cantidades = [float(row["cantidad_consumida"]) for row in history.data or []]
    promedio = mean(cantidades) if cantidades else 0.0
    consumo_90d = float(sum(cantidades[-10:])) if cantidades else 0.0
    tendencia = (cantidades[-1] - cantidades[0]) if len(cantidades) >= 2 else promedio

    params = params_response.data[0] if params_response.data else {}
    inventory = inventory_response.data[0] if inventory_response.data else {}
    features = DemandaFeatures(
        repuesto_id=repuesto_id,
        sede_id=sede_id,
        promedio_consumo=promedio,
        consumo_90d=consumo_90d,
        tendencia=tendencia,
        stock_actual=float(inventory.get("stock_actual") or 0),
        stock_minimo=float(params.get("stock_minimo") or 0),
        lead_time_base_dias=float(params.get("lead_time_base_dias") or 0),
    )
    return features, {
        "repuesto_id": repuesto_id,
        "sede_id": sede_id,
        "promedio_consumo": promedio,
        "consumo_90d": consumo_90d,
        "tendencia": tendencia,
        "stock_actual": features.stock_actual,
        "stock_minimo": features.stock_minimo,
        "lead_time_base_dias": features.lead_time_base_dias,
    }
