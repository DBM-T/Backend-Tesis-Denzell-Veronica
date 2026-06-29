from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from statistics import mean

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.ml.inference.runtime import DemandaFeatures, LeadTimeFeatures, PrioridadOTFeatures, RankingProveedorCandidate


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
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).order("fecha_consumo", desc=False).execute()
    params_response = await client.table("parametros_inventario").select(
        "stock_minimo,lead_time_base_dias,punto_reorden_sugerido_ml"
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).limit(1).execute()
    inventory_response = await client.table("inventario").select(
        "stock_actual"
    ).eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).limit(1).execute()

    history_rows = list(history.data or [])
    cantidades = [float(row["cantidad_consumida"]) for row in history_rows]
    promedio = mean(cantidades) if cantidades else 0.0

    recent_rows: list[dict] = []
    if history_rows:
        latest_date = datetime.fromisoformat(str(history_rows[-1]["fecha_consumo"]).replace("Z", "+00:00"))
        cutoff = latest_date - timedelta(days=90)
        recent_rows = [
            row
            for row in history_rows
            if datetime.fromisoformat(str(row["fecha_consumo"]).replace("Z", "+00:00")) >= cutoff
        ]
    recent_quantities = [float(row["cantidad_consumida"]) for row in recent_rows]
    consumo_90d = float(sum(recent_quantities)) if recent_quantities else 0.0
    if len(recent_quantities) >= 2:
        tendencia = recent_quantities[-1] - recent_quantities[0]
    elif len(cantidades) >= 2:
        tendencia = cantidades[-1] - cantidades[0]
    else:
        tendencia = promedio

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


async def recolectar_features_lead_time_compra(
    client: AsyncClient,
    oc_id: str,
) -> tuple[LeadTimeFeatures, dict]:
    oc_response = await client.table("ordenes_compra").select(
        "id,proveedor_id,monto_total,created_at,rfq_id"
    ).eq("id", oc_id).single().execute()
    if not oc_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OC no encontrada.")

    oc = oc_response.data
    detail_response = await client.table("oc_detalle").select("cantidad").eq("oc_id", oc_id).execute()
    detail_rows = list(detail_response.data or [])
    cantidad_lineas = float(len(detail_rows))
    cantidad_total_unidades = float(sum(int(row.get("cantidad") or 0) for row in detail_rows))

    provider_response = await client.table("proveedores").select(
        "lead_time_estimado_dias"
    ).eq("id", str(oc.get("proveedor_id"))).limit(1).execute()
    provider = provider_response.data[0] if provider_response.data else {}

    rfq_estimated_days: list[float] = []
    if oc.get("rfq_id"):
        rfq_responses = await client.table("rfq_respuestas").select(
            "lead_time_ofrecido_dias"
        ).eq("rfq_id", str(oc["rfq_id"])).execute()
        for row in rfq_responses.data or []:
            if row.get("lead_time_ofrecido_dias") is not None:
                rfq_estimated_days.append(float(row["lead_time_ofrecido_dias"]))

    if rfq_estimated_days:
        lead_time_estimado_dias = float(mean(rfq_estimated_days))
    else:
        lead_time_estimado_dias = float(provider.get("lead_time_estimado_dias") or 0)

    created_at = datetime.fromisoformat(str(oc["created_at"]).replace("Z", "+00:00"))
    mes_pedido = float(created_at.month)
    features = LeadTimeFeatures(
        compra_id=oc_id,
        proveedor_id=str(oc.get("proveedor_id")) if oc.get("proveedor_id") else None,
        lead_time_estimado_dias=float(lead_time_estimado_dias),
        monto_total=float(oc.get("monto_total") or 0),
        cantidad_lineas=cantidad_lineas,
        cantidad_total_unidades=cantidad_total_unidades,
        mes_pedido=mes_pedido,
    )
    return features, {
        "compra_id": oc_id,
        "proveedor_id": features.proveedor_id,
        "lead_time_estimado_dias": features.lead_time_estimado_dias,
        "monto_total": features.monto_total,
        "cantidad_lineas": features.cantidad_lineas,
        "cantidad_total_unidades": features.cantidad_total_unidades,
        "mes_pedido": features.mes_pedido,
    }
