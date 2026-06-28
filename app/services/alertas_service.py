from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_service_role_client
from app.schemas.alertas import AlertaRead, DashboardIndicadorRead, DashboardRefreshResult, RecomendacionCompraRead
from app.schemas.auth import CurrentUser
from app.schemas.enums import AlertSeverity, AlertStatus, AlertType, PurchaseOrderStatus, UserRole


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_roles(current_user: CurrentUser, *roles: UserRole) -> None:
    if current_user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para realizar esta accion.")


def _to_alert(row: dict) -> AlertaRead:
    return AlertaRead.model_validate(row)


def _to_recommendation(row: dict) -> RecomendacionCompraRead:
    return RecomendacionCompraRead.model_validate(row)


def _to_dashboard(row: dict) -> DashboardIndicadorRead:
    return DashboardIndicadorRead.model_validate(row)


async def list_alertas(
    client: AsyncClient,
    *,
    estado: AlertStatus | None = None,
    severidad: AlertSeverity | None = None,
    tipo: AlertType | None = None,
    sede_id: str | None = None,
) -> list[AlertaRead]:
    query = client.table("alertas").select(
        "id,tipo,severidad,estado,repuesto_id,sede_id,orden_compra_id,proveedor_id,mensaje,atendido_por,atendido_en,created_at"
    ).order("created_at", desc=True)
    if estado is not None:
        query = query.eq("estado", estado.value)
    if severidad is not None:
        query = query.eq("severidad", severidad.value)
    if tipo is not None:
        query = query.eq("tipo", tipo.value)
    if sede_id is not None:
        query = query.eq("sede_id", sede_id)
    response = await query.execute()
    return [_to_alert(row) for row in response.data or []]


async def attend_alert(client: AsyncClient, current_user: CurrentUser, alert_id: str, *, discard: bool = False) -> AlertaRead:
    _require_roles(
        current_user,
        UserRole.administrador,
        UserRole.almacenero,
        UserRole.logistica,
        UserRole.gerencia,
        UserRole.asesor_servicio,
        UserRole.tecnico,
    )
    current = await client.table("alertas").select("id,estado").eq("id", alert_id).single().execute()
    if not current.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada.")
    if current.data["estado"] != AlertStatus.activa.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La alerta ya no esta activa.")
    payload = {
        "estado": AlertStatus.descartada.value if discard else AlertStatus.atendida.value,
        "atendido_por": str(current_user.id),
        "atendido_en": _utcnow().isoformat(),
    }
    response = await client.table("alertas").update(payload).eq("id", alert_id).execute()
    return _to_alert(response.data[0])


async def create_alerta_from_recepcion(
    client: AsyncClient,
    *,
    tipo: AlertType,
    severidad: AlertSeverity,
    mensaje: str,
    repuesto_id: str | None = None,
    sede_id: str | None = None,
    orden_compra_id: str | None = None,
    proveedor_id: str | None = None,
) -> None:
    existing = client.table("alertas").select("id").eq("tipo", tipo.value).eq("estado", AlertStatus.activa.value)
    if repuesto_id is not None:
        existing = existing.eq("repuesto_id", repuesto_id)
    if sede_id is not None:
        existing = existing.eq("sede_id", sede_id)
    if orden_compra_id is not None:
        existing = existing.eq("orden_compra_id", orden_compra_id)
    if proveedor_id is not None:
        existing = existing.eq("proveedor_id", proveedor_id)
    result = await existing.limit(1).execute()
    if result.data:
        return
    await client.table("alertas").insert(
        {
            "tipo": tipo.value,
            "severidad": severidad.value,
            "repuesto_id": repuesto_id,
            "sede_id": sede_id,
            "orden_compra_id": orden_compra_id,
            "proveedor_id": proveedor_id,
            "mensaje": mensaje,
        }
    ).execute()


async def list_recomendaciones(
    client: AsyncClient,
    *,
    sede_id: str | None = None,
    atendida: bool | None = None,
) -> list[RecomendacionCompraRead]:
    query = client.table("recomendaciones_compra").select(
        "id,repuesto_id,sede_id,cantidad_sugerida,fecha_sugerida,proveedor_sugerido_id,modelo_id,justificacion_ml,atendida,created_at"
    ).order("created_at", desc=True)
    if sede_id is not None:
        query = query.eq("sede_id", sede_id)
    if atendida is not None:
        query = query.eq("atendida", atendida)
    response = await query.execute()
    return [_to_recommendation(row) for row in response.data or []]


async def attend_recommendation(client: AsyncClient, current_user: CurrentUser, recommendation_id: str) -> RecomendacionCompraRead:
    _require_roles(current_user, UserRole.administrador, UserRole.logistica)
    current = await client.table("recomendaciones_compra").select("id,atendida").eq("id", recommendation_id).single().execute()
    if not current.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recomendacion no encontrada.")
    if current.data["atendida"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La recomendacion ya fue atendida.")
    response = await client.table("recomendaciones_compra").update({"atendida": True}).eq("id", recommendation_id).execute()
    return _to_recommendation(response.data[0])


async def build_dashboard_snapshot(client: AsyncClient, *, sede_id: str | None = None) -> DashboardIndicadorRead:
    inventory_query = client.table("inventario").select("repuesto_id,sede_id,stock_actual")
    params_query = client.table("parametros_inventario").select(
        "repuesto_id,sede_id,stock_minimo,punto_reorden_sugerido_ml"
    )
    orders_query = client.table("ordenes_compra").select("id,estado,pr_id,fecha_entrega_comprometida")
    alerts_query = client.table("alertas").select("id,sede_id,estado")
    demand_query = client.table("pronosticos_demanda").select("sede_id,demanda_proyectada")
    if sede_id is not None:
        inventory_query = inventory_query.eq("sede_id", sede_id)
        params_query = params_query.eq("sede_id", sede_id)
        orders_query = orders_query.eq("sede_id", sede_id)
        alerts_query = alerts_query.eq("sede_id", sede_id)
        demand_query = demand_query.eq("sede_id", sede_id)

    inventory = (await inventory_query.execute()).data or []
    params = (await params_query.execute()).data or []
    orders = (await orders_query.execute()).data or []
    alerts = (await alerts_query.execute()).data or []
    demand = (await demand_query.execute()).data or []
    params_map = {(row["repuesto_id"], row["sede_id"]): row for row in params}
    pr_ids = [row["pr_id"] for row in orders if row.get("pr_id")]
    pr_map: dict[str, str] = {}
    if pr_ids:
        pr_response = await client.table("requisiciones_compra").select("id,sede_id").in_("id", pr_ids).execute()
        pr_map = {row["id"]: row["sede_id"] for row in pr_response.data or []}
    stock_critical = 0
    for row in inventory:
        param = params_map.get((row["repuesto_id"], row["sede_id"]))
        if not param:
            continue
        stock = int(row["stock_actual"])
        stock_minimo = int(param.get("stock_minimo") or 0)
        punto_ml = int(param.get("punto_reorden_sugerido_ml") or 0)
        if stock <= stock_minimo or (punto_ml and stock <= punto_ml):
            stock_critical += 1
    orders_in_course = sum(
        1
        for row in orders
        if row["estado"] in {
            PurchaseOrderStatus.aprobada.value,
            PurchaseOrderStatus.enviada.value,
            PurchaseOrderStatus.pendiente.value,
            PurchaseOrderStatus.pendiente_aprobacion.value,
            PurchaseOrderStatus.recibida_parcial.value,
        }
        and (
            sede_id is None
            or str(row.get("sede_id") or pr_map.get(row.get("pr_id")) or "") == sede_id
        )
    )
    active_alerts = sum(1 for row in alerts if row["estado"] == AlertStatus.activa.value)
    demand_total = sum(
        Decimal(str(row.get("demanda_proyectada") or 0))
        for row in demand
        if sede_id is None or str(row.get("sede_id")) == sede_id
    )
    return DashboardIndicadorRead(
        sede_id=UUID(sede_id) if sede_id else None,
        fecha_corte=date.today(),
        stock_critico_count=stock_critical,
        ordenes_en_curso_count=orders_in_course,
        alertas_activas_count=active_alerts,
        demanda_proyectada_total=demand_total,
        source="on_demand",
    )


async def refresh_alerts_and_dashboard() -> DashboardRefreshResult:
    client = await create_service_role_client()
    processed = 0
    alertas_creadas = 0
    recomendaciones_creadas = 0
    dashboard_actualizado = 0

    inventory_response = await client.table("inventario").select("repuesto_id,sede_id,stock_actual").execute()
    params_response = await client.table("parametros_inventario").select(
        "repuesto_id,sede_id,stock_minimo,punto_reorden_sugerido_ml"
    ).execute()
    params_map = {(row["repuesto_id"], row["sede_id"]): row for row in (params_response.data or [])}
    for row in inventory_response.data or []:
        processed += 1
        param = params_map.get((row["repuesto_id"], row["sede_id"]))
        if not param:
            continue
        stock = int(row["stock_actual"])
        stock_min = int(param.get("stock_minimo") or 0)
        punto_ml = int(param.get("punto_reorden_sugerido_ml") or 0)
        if stock <= stock_min or (punto_ml and stock <= punto_ml):
            before = await client.table("alertas").select("id").eq("tipo", AlertType.punto_reorden.value).eq("estado", AlertStatus.activa.value).eq("repuesto_id", row["repuesto_id"]).eq("sede_id", row["sede_id"]).limit(1).execute()
            if not before.data:
                await client.table("alertas").insert(
                    {
                        "tipo": AlertType.punto_reorden.value,
                        "severidad": AlertSeverity.alta.value if stock <= stock_min else AlertSeverity.media.value,
                        "repuesto_id": row["repuesto_id"],
                        "sede_id": row["sede_id"],
                        "mensaje": "Stock bajo umbral de reorden.",
                    }
                ).execute()
                alertas_creadas += 1
        if stock <= max(stock_min, punto_ml):
            before_rec = await client.table("recomendaciones_compra").select("id").eq("repuesto_id", row["repuesto_id"]).eq("sede_id", row["sede_id"]).eq("atendida", False).limit(1).execute()
            if not before_rec.data:
                qty = max(1, (punto_ml or stock_min or 1) - stock + 1)
                await client.table("recomendaciones_compra").insert(
                    {
                        "repuesto_id": row["repuesto_id"],
                        "sede_id": row["sede_id"],
                        "cantidad_sugerida": qty,
                        "justificacion_ml": "Generada por job de Fase 7 segun stock critico y ROP sugerido.",
                    }
                ).execute()
                recomendaciones_creadas += 1

    today = date.today()
    ocs = await client.table("ordenes_compra").select("id,estado,fecha_entrega_comprometida,pr_id").execute()
    oc_pr_ids = [row["pr_id"] for row in (ocs.data or []) if row.get("pr_id")]
    oc_pr_map: dict[str, str] = {}
    if oc_pr_ids:
        pr_response = await client.table("requisiciones_compra").select("id,sede_id").in_("id", oc_pr_ids).execute()
        oc_pr_map = {row["id"]: row["sede_id"] for row in pr_response.data or []}
    for oc in ocs.data or []:
        oc_sede_id = str(oc.get("sede_id") or oc_pr_map.get(oc.get("pr_id")) or "") or None
        if oc.get("fecha_entrega_comprometida") and oc["estado"] in {PurchaseOrderStatus.enviada.value, PurchaseOrderStatus.pendiente.value}:
            if str(oc["fecha_entrega_comprometida"]) < str(today):
                before = await client.table("alertas").select("id").eq("tipo", AlertType.oc_retrasada.value).eq("estado", AlertStatus.activa.value).eq("orden_compra_id", oc["id"]).limit(1).execute()
                if not before.data:
                    await client.table("alertas").insert(
                        {
                            "tipo": AlertType.oc_retrasada.value,
                            "severidad": AlertSeverity.alta.value,
                            "orden_compra_id": oc["id"],
                            "sede_id": oc_sede_id,
                            "mensaje": "Orden de compra con fecha comprometida vencida.",
                        }
                    ).execute()
                    alertas_creadas += 1
        if oc["estado"] == PurchaseOrderStatus.pendiente_aprobacion.value:
            before = await client.table("alertas").select("id").eq("tipo", AlertType.oc_pendiente_aprobacion.value).eq("estado", AlertStatus.activa.value).eq("orden_compra_id", oc["id"]).limit(1).execute()
            if not before.data:
                await client.table("alertas").insert(
                    {
                        "tipo": AlertType.oc_pendiente_aprobacion.value,
                        "severidad": AlertSeverity.media.value,
                        "orden_compra_id": oc["id"],
                        "sede_id": oc_sede_id,
                        "mensaje": "Orden de compra pendiente de aprobacion de gerencia.",
                    }
                ).execute()
                alertas_creadas += 1

    for sede in {row["sede_id"] for row in (inventory_response.data or [])}:
        snapshot = await build_dashboard_snapshot(client, sede_id=str(sede))
        existing = await client.table("dashboard_indicadores").select("id").eq("sede_id", str(sede)).eq("fecha_corte", str(snapshot.fecha_corte)).limit(1).execute()
        payload = snapshot.model_dump(mode="json", exclude={"source"})
        if existing.data:
            await client.table("dashboard_indicadores").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            await client.table("dashboard_indicadores").insert(payload).execute()
        dashboard_actualizado += 1

    return DashboardRefreshResult(
        procesados=processed,
        alertas_creadas=alertas_creadas,
        recomendaciones_creadas=recomendaciones_creadas,
        dashboard_actualizado=dashboard_actualizado,
    )
