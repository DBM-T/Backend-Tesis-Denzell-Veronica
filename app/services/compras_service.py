from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.ml.inference.ranking_service import generate_ranking_for_rfq
from app.services.alertas_service import create_alerta_from_recepcion
from app.schemas.auth import CurrentUser
from app.schemas.compras import (
    AprobacionProveedorCreate,
    AprobacionProveedorRead,
    OrdenCompraCreate,
    OrdenCompraDetalleRead,
    OrdenCompraEstadoUpdate,
    OrdenCompraRead,
    OrdenCompraRecepcionCreate,
    RecepcionOCDetalleRead,
    RecepcionOCRead,
    RFQCreate,
    RFQDetalleRead,
    RFQRead,
    RFQRespuestaCreate,
    RFQRespuestaRead,
    RFQStatusUpdate,
    RankingProveedorRead,
)
from app.schemas.enums import AlertSeverity, AlertType, PurchaseOrderStatus, PurchaseRequestStatus, RFQStatus, UserRole


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _code(prefix: str) -> str:
    return f"{prefix}-{_utcnow().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


def _require_roles(current_user: CurrentUser, *roles: UserRole) -> None:
    if current_user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para esta accion.")


def _rfq_read(row: dict, detalle: list[RFQDetalleRead] | None = None) -> RFQRead:
    payload = dict(row)
    payload["detalle"] = detalle or []
    return RFQRead.model_validate(payload)


def _oc_read(row: dict, detalle: list[OrdenCompraDetalleRead] | None = None) -> OrdenCompraRead:
    payload = dict(row)
    payload["detalle"] = detalle or []
    return OrdenCompraRead.model_validate(payload)


async def _fetch_pr(client: AsyncClient, pr_id: str) -> dict:
    response = await client.table("requisiciones_compra").select(
        "id,codigo_pr,ot_id,sede_id,prioridad_heredada,estado,generado_automaticamente,creado_por,created_at,updated_at"
    ).eq("id", pr_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PR no encontrada.")
    return response.data


async def _fetch_rfq(client: AsyncClient, rfq_id: str) -> RFQRead:
    response = await client.table("rfq").select(
        "id,codigo_rfq,pr_id,proveedor_id,fecha_limite_respuesta,condiciones_comerciales,estado,"
        "enviado_automaticamente,creado_por,created_at"
    ).eq("id", rfq_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFQ no encontrada.")
    details = await client.table("rfq_detalle").select("id,rfq_id,repuesto_id,cantidad").eq("rfq_id", rfq_id).execute()
    return _rfq_read(response.data, [RFQDetalleRead.model_validate(row) for row in details.data or []])


async def _fetch_oc(client: AsyncClient, oc_id: str) -> OrdenCompraRead:
    response = await client.table("ordenes_compra").select(
        "id,codigo_oc,pr_id,ot_id,proveedor_id,rfq_id,monto_total,condiciones_pago,fecha_entrega_comprometida,"
        "canal_compra,estado,requiere_aprobacion_gerencia,aprobado_por_gerencia_id,fecha_aprobacion_gerencia,"
        "creado_por,created_at,updated_at"
    ).eq("id", oc_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OC no encontrada.")
    details = await client.table("oc_detalle").select("id,oc_id,repuesto_id,cantidad,precio_unitario").eq("oc_id", oc_id).execute()
    return _oc_read(response.data, [OrdenCompraDetalleRead.model_validate(row) for row in details.data or []])


async def _get_rfq_detail_map(client: AsyncClient, rfq_id: str) -> dict[str, dict]:
    response = await client.table("rfq_detalle").select("repuesto_id,cantidad").eq("rfq_id", rfq_id).execute()
    return {row["repuesto_id"]: row for row in response.data or []}


async def _get_selected_provider_responses(client: AsyncClient, rfq_id: str, provider_id: str) -> dict[str, dict]:
    response = await client.table("rfq_respuestas").select(
        "repuesto_id,precio_unitario,disponibilidad,lead_time_ofrecido_dias"
    ).eq("rfq_id", rfq_id).execute()
    return {row["repuesto_id"]: row for row in response.data or []}


async def create_rfq(client: AsyncClient, current_user: CurrentUser, payload: RFQCreate) -> RFQRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    pr = await _fetch_pr(client, str(payload.pr_id))
    if pr["estado"] != PurchaseRequestStatus.aprobada.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La PR debe estar aprobada para generar RFQ.")

    rfq_response = await client.table("rfq").insert(
        {
            "codigo_rfq": _code("RFQ"),
            "pr_id": str(payload.pr_id),
            "proveedor_id": str(payload.proveedor_id),
            "fecha_limite_respuesta": payload.fecha_limite_respuesta.isoformat() if payload.fecha_limite_respuesta else None,
            "condiciones_comerciales": payload.condiciones_comerciales,
            "estado": RFQStatus.enviada.value,
            "enviado_automaticamente": payload.enviado_automaticamente,
            "creado_por": str(current_user.id),
        }
    ).execute()
    rfq_id = rfq_response.data[0]["id"]

    pr_details = await client.table("pr_detalle").select("repuesto_id,cantidad").eq("pr_id", str(payload.pr_id)).execute()
    if pr_details.data:
        await client.table("rfq_detalle").insert(
            [{"rfq_id": rfq_id, "repuesto_id": row["repuesto_id"], "cantidad": row["cantidad"]} for row in pr_details.data]
        ).execute()
    return await _fetch_rfq(client, rfq_id)


async def send_rfq(client: AsyncClient, current_user: CurrentUser, rfq_id: str) -> RFQRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    current = await _fetch_rfq(client, rfq_id)
    if current.estado == RFQStatus.cancelada:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se puede enviar una RFQ cancelada.")
    await client.table("rfq").update({"enviado_automaticamente": True, "estado": RFQStatus.enviada.value}).eq("id", rfq_id).execute()
    return await _fetch_rfq(client, rfq_id)


async def add_rfq_responses(client: AsyncClient, current_user: CurrentUser, rfq_id: str, payload: RFQRespuestaCreate) -> list[RFQRespuestaRead]:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    current = await _fetch_rfq(client, rfq_id)
    if current.estado not in {RFQStatus.enviada, RFQStatus.respondida}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La RFQ debe estar enviada para registrar respuestas.")

    inserted: list[RFQRespuestaRead] = []
    for item in payload.respuestas:
        row = {
            "rfq_id": rfq_id,
            "repuesto_id": str(item.repuesto_id),
            "precio_unitario": str(item.precio_unitario),
            "disponibilidad": item.disponibilidad,
            "lead_time_ofrecido_dias": item.lead_time_ofrecido_dias,
            "registrado_por": str(current_user.id),
        }
        response = await client.table("rfq_respuestas").insert(row).execute()
        inserted.append(RFQRespuestaRead.model_validate(response.data[0]))

    await client.table("rfq").update({"estado": RFQStatus.respondida.value}).eq("id", rfq_id).execute()
    return inserted


async def update_rfq_status(client: AsyncClient, current_user: CurrentUser, rfq_id: str, payload: RFQStatusUpdate) -> RFQRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    current = await _fetch_rfq(client, rfq_id)
    valid = {
        RFQStatus.enviada: {RFQStatus.respondida, RFQStatus.vencida, RFQStatus.cancelada},
        RFQStatus.respondida: {RFQStatus.vencida, RFQStatus.cancelada},
        RFQStatus.vencida: {RFQStatus.cancelada},
    }
    if payload.estado != current.estado and payload.estado not in valid.get(current.estado, set()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transicion de RFQ invalida.")
    await client.table("rfq").update({"estado": payload.estado.value}).eq("id", rfq_id).execute()
    return await _fetch_rfq(client, rfq_id)


async def get_rfq_ranking(client: AsyncClient, rfq_id: str) -> list[RankingProveedorRead]:
    rows = await client.table("ranking_proveedores_ml").select(
        "id,rfq_id,proveedor_id,repuesto_id,score_total_ml,ranking_posicion,canal_sugerido_ml,version_modelo,created_at"
    ).eq("rfq_id", rfq_id).order("ranking_posicion", desc=False).execute()
    if not rows.data:
        generated = await generate_ranking_for_rfq(client, rfq_id)
        if generated:
            rows = await client.table("ranking_proveedores_ml").select(
                "id,rfq_id,proveedor_id,repuesto_id,score_total_ml,ranking_posicion,canal_sugerido_ml,version_modelo,created_at"
            ).eq("rfq_id", rfq_id).order("ranking_posicion", desc=False).execute()
    enriched: list[RankingProveedorRead] = []
    if rows.data:
        provider_rows = await client.table("proveedores").select("id,razon_social").execute()
        provider_map = {row["id"]: row for row in provider_rows.data or []}
        repuestos_rows = await client.table("repuestos").select("id,codigo_sku").execute()
        repuesto_map = {row["id"]: row for row in repuestos_rows.data or []}
        for row in rows.data:
            enriched.append(
                RankingProveedorRead(
                    **row,
                    proveedor_razon_social=provider_map.get(row["proveedor_id"], {}).get("razon_social"),
                    repuesto_codigo_sku=repuesto_map.get(row["repuesto_id"], {}).get("codigo_sku"),
                )
            )
    return enriched


async def create_aprobacion_proveedor(
    client: AsyncClient, current_user: CurrentUser, payload: AprobacionProveedorCreate
) -> AprobacionProveedorRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    ranking = await get_rfq_ranking(client, str(payload.rfq_id))
    recommended_provider_id = ranking[0].proveedor_id if ranking else None
    coincide = recommended_provider_id == payload.proveedor_seleccionado_id
    if not coincide and not payload.justificacion:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La justificacion es obligatoria si el proveedor no coincide con el ranking.")
    response = await client.table("aprobaciones_proveedor").insert(
        {
            "rfq_id": str(payload.rfq_id),
            "proveedor_seleccionado_id": str(payload.proveedor_seleccionado_id),
            "coincide_con_recomendacion_ml": coincide,
            "justificacion": payload.justificacion,
            "aprobado_por": str(current_user.id),
        }
    ).execute()
    return AprobacionProveedorRead.model_validate(response.data[0])


async def create_orden_compra(client: AsyncClient, current_user: CurrentUser, payload: OrdenCompraCreate) -> OrdenCompraRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    approval = await client.table("aprobaciones_proveedor").select(
        "id,rfq_id,proveedor_seleccionado_id,coincide_con_recomendacion_ml,justificacion,aprobado_por,created_at"
    ).eq("id", str(payload.aprobacion_id)).single().execute()
    if not approval.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aprobacion no encontrada.")
    rfq_id = approval.data["rfq_id"]
    rfq = await _fetch_rfq(client, rfq_id)
    pr = await _fetch_pr(client, str(rfq.pr_id))
    if pr["estado"] != PurchaseRequestStatus.aprobada.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La PR asociada debe estar aprobada.")

    rfq_detail_map = await _get_rfq_detail_map(client, rfq_id)
    response_map = await _get_selected_provider_responses(client, rfq_id, approval.data["proveedor_seleccionado_id"])
    if not rfq_detail_map:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La RFQ no tiene detalle.")

    oc_details = []
    total = Decimal("0")
    for repuesto_id, detail in rfq_detail_map.items():
        resp = response_map.get(repuesto_id)
        if not resp:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Faltan respuestas del proveedor para generar la OC.")
        cantidad = int(detail["cantidad"])
        precio = Decimal(str(resp["precio_unitario"]))
        total += Decimal(cantidad) * precio
        oc_details.append(
            {
                "repuesto_id": repuesto_id,
                "cantidad": cantidad,
                "precio_unitario": str(precio),
            }
        )

    from app.core.config import get_settings
    limite = Decimal(str(get_settings().oc_limite_aprobacion_gerencia))
    requiere = total > limite
    estado = PurchaseOrderStatus.pendiente_aprobacion if requiere else PurchaseOrderStatus.pendiente

    oc_response = await client.table("ordenes_compra").insert(
        {
            "codigo_oc": _code("PO"),
            "pr_id": str(rfq.pr_id),
            "ot_id": str(pr["ot_id"]) if pr.get("ot_id") else None,
            "proveedor_id": str(approval.data["proveedor_seleccionado_id"]),
            "rfq_id": rfq_id,
            "monto_total": str(total),
            "condiciones_pago": payload.condiciones_pago,
            "fecha_entrega_comprometida": payload.fecha_entrega_comprometida.isoformat() if payload.fecha_entrega_comprometida else None,
            "canal_compra": payload.canal_compra.value if payload.canal_compra else None,
            "estado": estado.value,
            "requiere_aprobacion_gerencia": requiere,
            "creado_por": str(current_user.id),
        }
    ).execute()
    oc_id = oc_response.data[0]["id"]
    await client.table("oc_detalle").insert([{**row, "oc_id": oc_id} for row in oc_details]).execute()
    return await _fetch_oc(client, oc_id)


async def approve_orden_gerencia(client: AsyncClient, current_user: CurrentUser, oc_id: str) -> OrdenCompraRead:
    _require_roles(current_user, UserRole.gerencia)
    current = await _fetch_oc(client, oc_id)
    if current.estado != PurchaseOrderStatus.pendiente_aprobacion:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La OC debe estar pendiente_aprobacion.")
    response = await client.table("ordenes_compra").update(
        {
            "estado": PurchaseOrderStatus.aprobada.value,
            "aprobado_por_gerencia_id": str(current_user.id),
            "fecha_aprobacion_gerencia": _utcnow().isoformat(),
        }
    ).eq("id", oc_id).execute()
    return _oc_read(response.data[0], current.detalle)


async def update_orden_status(client: AsyncClient, current_user: CurrentUser, oc_id: str, payload: OrdenCompraEstadoUpdate) -> OrdenCompraRead:
    _require_roles(current_user, UserRole.logistica, UserRole.administrador)
    current = await _fetch_oc(client, oc_id)
    valid = {
        PurchaseOrderStatus.pendiente: {PurchaseOrderStatus.enviada, PurchaseOrderStatus.rechazada},
        PurchaseOrderStatus.aprobada: {PurchaseOrderStatus.enviada, PurchaseOrderStatus.rechazada},
        PurchaseOrderStatus.enviada: {
            PurchaseOrderStatus.recibida_parcial,
            PurchaseOrderStatus.recibida,
            PurchaseOrderStatus.cerrada,
            PurchaseOrderStatus.rechazada,
        },
        PurchaseOrderStatus.recibida_parcial: {PurchaseOrderStatus.recibida, PurchaseOrderStatus.cerrada},
        PurchaseOrderStatus.recibida: {PurchaseOrderStatus.cerrada},
    }
    if payload.estado != current.estado and payload.estado not in valid.get(current.estado, set()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transicion de OC invalida.")
    response = await client.table("ordenes_compra").update({"estado": payload.estado.value}).eq("id", oc_id).execute()
    return _oc_read(response.data[0], current.detalle)


async def create_recepcion_oc(
    client: AsyncClient, current_user: CurrentUser, oc_id: str, payload: OrdenCompraRecepcionCreate
) -> RecepcionOCRead:
    _require_roles(current_user, UserRole.almacenero, UserRole.administrador)
    current = await _fetch_oc(client, oc_id)
    if current.estado not in {PurchaseOrderStatus.aprobada, PurchaseOrderStatus.enviada, PurchaseOrderStatus.pendiente, PurchaseOrderStatus.recibida_parcial}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La OC no permite recepciones en este estado.")
    pr_response = await client.table("requisiciones_compra").select("sede_id").eq("id", str(current.pr_id)).single().execute()
    recepcion_response = await client.table("recepciones_oc").insert(
        {"oc_id": oc_id, "recibido_por": str(current_user.id)}
    ).execute()
    recepcion_id = recepcion_response.data[0]["id"]
    detalle_rows = []
    any_no_conforme = False
    for item in payload.detalles:
        if item.conformidad == "no_conforme":
            any_no_conforme = True
        detalle_rows.append(
            {
                "recepcion_id": recepcion_id,
                "repuesto_id": str(item.repuesto_id),
                "cantidad_recibida": item.cantidad_recibida,
                "conformidad": item.conformidad,
                "evidencia_url": item.evidencia_url,
                "observaciones": item.observaciones,
            }
        )
    await client.table("recepciones_oc_detalle").insert(detalle_rows).execute()
    if any_no_conforme:
        for item in payload.detalles:
            if item.conformidad == "no_conforme":
                await create_alerta_from_recepcion(
                    client,
                    tipo=AlertType.no_conformidad_proveedor,
                    severidad=AlertSeverity.alta,
                    mensaje="Se registró una no conformidad en la recepción de OC.",
                    repuesto_id=str(item.repuesto_id),
                    sede_id=str(pr_response.data["sede_id"]) if pr_response.data else None,
                )

    response = await client.table("recepciones_oc").select("id,oc_id,fecha_recepcion,recibido_por,created_at").eq("id", recepcion_id).single().execute()
    detalle_resp = await client.table("recepciones_oc_detalle").select(
        "id,recepcion_id,repuesto_id,cantidad_recibida,conformidad,evidencia_url,observaciones"
    ).eq("recepcion_id", recepcion_id).execute()
    if current.estado == PurchaseOrderStatus.enviada:
        new_status = PurchaseOrderStatus.recibida_parcial if any_no_conforme else PurchaseOrderStatus.recibida
        await client.table("ordenes_compra").update({"estado": new_status.value}).eq("id", oc_id).execute()
    elif current.estado == PurchaseOrderStatus.aprobada:
        await client.table("ordenes_compra").update({"estado": PurchaseOrderStatus.recibida_parcial.value}).eq("id", oc_id).execute()
    return RecepcionOCRead(
        **response.data,
        detalle=[RecepcionOCDetalleRead.model_validate(row) for row in detalle_resp.data or []],
    )


async def list_recepciones_oc(client: AsyncClient, oc_id: str) -> list[RecepcionOCRead]:
    response = await client.table("recepciones_oc").select("id,oc_id,fecha_recepcion,recibido_por,created_at").eq("oc_id", oc_id).order("created_at", desc=True).execute()
    recepciones = []
    for row in response.data or []:
        detalle = await client.table("recepciones_oc_detalle").select(
            "id,recepcion_id,repuesto_id,cantidad_recibida,conformidad,evidencia_url,observaciones"
        ).eq("recepcion_id", row["id"]).execute()
        recepciones.append(
            RecepcionOCRead(
                **row,
                detalle=[RecepcionOCDetalleRead.model_validate(item) for item in detalle.data or []],
            )
        )
    return recepciones
