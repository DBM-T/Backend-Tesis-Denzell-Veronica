from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from supabase._async.client import AsyncClient

from app.core.supabase_client import create_service_role_client
from app.ml.inference.features import recolectar_features_prioridad_ot
from app.ml.inference.priority_service import predict_priority
from app.schemas.auth import CurrentUser
from app.schemas.enums import InventoryMoveType, PriorityML, PurchaseRequestStatus, UserRole, UserStatus, WorkOrderStatus
from app.schemas.maestros import InventarioCriticoRead, InventarioRead, PaginatedResponse, RepuestoRead
from app.schemas.operaciones import (
    AssignTechnicianRequest,
    ChangeWorkOrderStatusRequest,
    CompleteServiceResponse,
    CloseWorkOrderRequest,
    CloseWorkOrderResponse,
    DiagnosticRead,
    DiagnosticRequest,
    InventoryMovementCreate,
    InventoryMovementRead,
    InventoryWorkspaceRead,
    PriorityClassificationRequest,
    PriorityClassificationResponse,
    PurchaseRequestCreate,
    PurchaseRequestDetailRead,
    PurchaseRequestRead,
    PurchaseRequestStateUpdate,
    OTWorkspaceRead,
    StockAvailabilityItem,
    StockAvailabilityResponse,
    WorkOrderCreate,
    WorkOrderDiagnosticResponse,
    WorkOrderRead,
    WorkOrderListRead,
)
from app.schemas.sedes import SedeRead
from app.schemas.usuarios import UsuarioRead
from app.services.maestros_service import (
    _inventory_status,
    list_all_categorias_public,
)
from app.services.ventas_service import get_sale_by_ot
from app.services.users_service import list_sedes, list_users


OT_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.registrada: {WorkOrderStatus.diagnostico, WorkOrderStatus.cancelada},
    WorkOrderStatus.diagnostico: {
        WorkOrderStatus.waiting_parts,
        WorkOrderStatus.in_progress,
        WorkOrderStatus.cancelada,
    },
    WorkOrderStatus.waiting_parts: {
        WorkOrderStatus.in_progress,
        WorkOrderStatus.cancelada,
    },
    WorkOrderStatus.in_progress: {
        WorkOrderStatus.tech_completed,
        WorkOrderStatus.cancelada,
    },
    WorkOrderStatus.tech_completed: {WorkOrderStatus.completed},
    WorkOrderStatus.completed: set(),
    WorkOrderStatus.cancelada: set(),
}

PR_TRANSITIONS: dict[PurchaseRequestStatus, set[PurchaseRequestStatus]] = {
    PurchaseRequestStatus.generada: {
        PurchaseRequestStatus.en_cotizacion,
        PurchaseRequestStatus.cancelada,
    },
    PurchaseRequestStatus.en_cotizacion: {
        PurchaseRequestStatus.aprobada,
        PurchaseRequestStatus.cancelada,
    },
    PurchaseRequestStatus.aprobada: {
        PurchaseRequestStatus.convertida_oc,
        PurchaseRequestStatus.cancelada,
    },
    PurchaseRequestStatus.convertida_oc: set(),
    PurchaseRequestStatus.cancelada: set(),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _code(prefix: str) -> str:
    return f"{prefix}-{_utcnow().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


async def _sic_code(client: AsyncClient) -> str:
    year = _utcnow().strftime("%Y")
    response = await client.table("requisiciones_compra").select("codigo_pr").like("codigo_pr", f"SIC/{year}/%").execute()
    current_numbers: list[int] = []
    for row in response.data or []:
        code = str(row.get("codigo_pr") or "")
        parts = code.split("/")
        if len(parts) == 3 and parts[0] == "SIC" and parts[1] == year and parts[2].isdigit():
            current_numbers.append(int(parts[2]))
    return f"SIC/{year}/{max(current_numbers, default=0) + 1:05d}"


def _ot_row(row: dict) -> WorkOrderRead:
    payload = dict(row)
    if payload.get("prioridad_ml") is None and payload.get("confianza_ml") is not None:
        payload["prioridad_ml"] = PriorityML.REVISAR.value
    return WorkOrderRead.model_validate(payload)


def _pr_detail_row(row: dict) -> PurchaseRequestDetailRead:
    return PurchaseRequestDetailRead.model_validate(row)


def _pr_row(row: dict, detail: list[PurchaseRequestDetailRead] | None = None) -> PurchaseRequestRead:
    payload = dict(row)
    payload["detalle"] = detail or []
    return PurchaseRequestRead.model_validate(payload)


def _movement_row(row: dict) -> InventoryMovementRead:
    return InventoryMovementRead.model_validate(row)


def _part_row(row: dict) -> RepuestoRead:
    return RepuestoRead.model_validate(row)


def _page_range(page: int, page_size: int) -> tuple[int, int]:
    start = max(page - 1, 0) * page_size
    return start, start + page_size - 1


def _response_total(response, fallback: int) -> int:
    count = getattr(response, "count", None)
    return int(count) if count is not None else fallback


def _chunked(values: set[str], size: int = 200) -> list[list[str]]:
    ordered = sorted(values)
    return [ordered[index:index + size] for index in range(0, len(ordered), size)]


async def _fetch_id_map(client: AsyncClient, *, table: str, select_fields: str, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows: list[dict] = []
    for chunk in _chunked(ids):
        response = await client.table(table).select(select_fields).in_("id", chunk).execute()
        rows.extend(response.data or [])
    return {str(row["id"]): row for row in rows}


async def _upsert_inventory_stock(client: AsyncClient, *, repuesto_id: str, sede_id: str, stock_actual: int) -> int:
    existing = await client.table("inventario").select("id").eq("repuesto_id", repuesto_id).eq("sede_id", sede_id).limit(1).execute()
    payload = {
        "repuesto_id": repuesto_id,
        "sede_id": sede_id,
        "stock_actual": stock_actual,
    }
    if existing.data:
        await client.table("inventario").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        await client.table("inventario").insert(payload).execute()
    return stock_actual


async def _fetch_work_order(client: AsyncClient, ot_id: str) -> WorkOrderRead:
    response = await (
        client.table("ordenes_trabajo")
        .select(
            "id,codigo_ot,cliente_nombre,cliente_documento,cliente_telefono,vehiculo_placa,"
            "vehiculo_marca,vehiculo_modelo,vehiculo_anio,servicio_solicitado,asesor_id,"
            "tecnico_id,sede_id,estado,prioridad_ml,confianza_ml,fecha_diagnostico,"
            "fecha_completado,created_at,updated_at"
        )
        .eq("id", ot_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OT no encontrada.")
    return _ot_row(response.data)


async def _fetch_purchase_request(client: AsyncClient, pr_id: str) -> PurchaseRequestRead:
    response = await (
        client.table("requisiciones_compra")
        .select(
            "id,codigo_pr,ot_id,sede_id,prioridad_heredada,estado,generado_automaticamente,"
            "creado_por,created_at,updated_at"
        )
        .eq("id", pr_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisicion no encontrada.")
    details = await (
        client.table("pr_detalle").select("id,pr_id,repuesto_id,cantidad").eq("pr_id", pr_id).execute()
    )
    return _pr_row(response.data, [_pr_detail_row(row) for row in details.data or []])


async def _fetch_purchase_request_detail_map(
    client: AsyncClient,
    pr_ids: list[str],
) -> dict[str, list[PurchaseRequestDetailRead]]:
    if not pr_ids:
        return {}
    details = await client.table("pr_detalle").select("id,pr_id,repuesto_id,cantidad").in_("pr_id", pr_ids).execute()
    grouped: dict[str, list[PurchaseRequestDetailRead]] = defaultdict(list)
    for row in details.data or []:
        grouped[str(row["pr_id"])].append(_pr_detail_row(row))
    return grouped


def _require_roles(current_user: CurrentUser, *roles: UserRole) -> None:
    if current_user.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para realizar esta accion.",
        )


def _ensure_transition(current: WorkOrderStatus, target: WorkOrderStatus) -> None:
    if target == current:
        return
    if target not in OT_TRANSITIONS[current]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transicion invalida de {current.value} a {target.value}.",
        )


def _ensure_technician_can_operate(current_user: CurrentUser, ot: WorkOrderRead) -> None:
    if current_user.role != UserRole.tecnico:
        return

    if ot.tecnico_id:
        if str(ot.tecnico_id) != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La orden esta asignada a otro tecnico.")
        return

    if not current_user.profile.sede_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu usuario tecnico no tiene una sede asignada para tomar esta orden.",
        )
    if str(current_user.profile.sede_id) != str(ot.sede_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puedes operar ordenes de tu sede.")


def _ensure_pr_transition(current: PurchaseRequestStatus, target: PurchaseRequestStatus) -> None:
    if target == current:
        return
    if target not in PR_TRANSITIONS[current]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transicion invalida de {current.value} a {target.value}.",
        )


async def create_work_order(client: AsyncClient, current_user: CurrentUser, payload: WorkOrderCreate) -> WorkOrderRead:
    _require_roles(current_user, UserRole.asesor_servicio, UserRole.administrador)
    response = await client.table("ordenes_trabajo").insert(
        {
            **payload.model_dump(mode="json"),
            "codigo_ot": _code("OT"),
            "asesor_id": str(current_user.id),
            "estado": WorkOrderStatus.registrada.value,
        }
    ).execute()
    return _ot_row(response.data[0])


async def assign_technician(
    client: AsyncClient, current_user: CurrentUser, ot_id: str, payload: AssignTechnicianRequest
) -> WorkOrderRead:
    _require_roles(current_user, UserRole.asesor_servicio, UserRole.administrador, UserRole.tecnico)
    ot = await _fetch_work_order(client, ot_id)
    tecnico_id = str(payload.tecnico_id)

    if current_user.role == UserRole.tecnico:
        if tecnico_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puedes tomar la orden para ti mismo.")
        if ot.tecnico_id and str(ot.tecnico_id) != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La orden ya esta asignada a otro tecnico.")
        if current_user.profile.sede_id and str(current_user.profile.sede_id) != str(ot.sede_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puedes tomar ordenes de tu sede.")
    else:
        validation_client = await create_service_role_client()
        tecnico_response = await (
            validation_client.table("perfiles").select("id,rol,sede_id,estado").eq("id", tecnico_id).single().execute()
        )
        if not tecnico_response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tecnico no encontrado.")
        if tecnico_response.data.get("rol") != UserRole.tecnico.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El usuario seleccionado no tiene rol tecnico.")
        if tecnico_response.data.get("estado") != "activo":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El tecnico seleccionado no esta activo.")
        if tecnico_response.data.get("sede_id") and str(tecnico_response.data["sede_id"]) != str(ot.sede_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El tecnico debe pertenecer a la sede de la orden.")

    response = await client.table("ordenes_trabajo").update(
        {"tecnico_id": tecnico_id}
    ).eq("id", ot_id).execute()
    return _ot_row(response.data[0])


async def register_diagnostic(
    client: AsyncClient, current_user: CurrentUser, ot_id: str, payload: DiagnosticRequest
) -> WorkOrderDiagnosticResponse:
    _require_roles(current_user, UserRole.tecnico, UserRole.administrador)
    ot = await _fetch_work_order(client, ot_id)
    _ensure_technician_can_operate(current_user, ot)

    diagnostic_response = await client.table("diagnosticos_ot").insert(
        {
            "ot_id": ot_id,
            "tecnico_id": str(current_user.id),
            "descripcion": payload.descripcion,
        }
    ).execute()

    # Reemplazamos la lista requerida para reflejar el ultimo diagnostico confirmado.
    await client.table("ot_repuestos_requeridos").delete().eq("ot_id", ot_id).execute()
    for item in payload.repuestos:
        await client.table("ot_repuestos_requeridos").insert(
            {
                "ot_id": ot_id,
                "repuesto_id": str(item.repuesto_id),
                "cantidad": item.cantidad,
            }
        ).execute()

    updated_ot_response = await client.table("ordenes_trabajo").update(
        {
            "estado": WorkOrderStatus.diagnostico.value,
            "fecha_diagnostico": _utcnow().isoformat(),
        }
    ).eq("id", ot_id).execute()

    return WorkOrderDiagnosticResponse(
        diagnostico=DiagnosticRead.model_validate(diagnostic_response.data[0]),
        repuestos=payload.repuestos,
        orden_trabajo=_ot_row(updated_ot_response.data[0]),
    )


async def classify_priority(
    client: AsyncClient,
    current_user: CurrentUser,
    ot_id: str,
    payload: PriorityClassificationRequest,
) -> PriorityClassificationResponse:
    _require_roles(current_user, UserRole.tecnico, UserRole.asesor_servicio, UserRole.administrador)
    features, parametros_entrada = await recolectar_features_prioridad_ot(
        client,
        ot_id,
        historial_vehiculo=payload.historial_vehiculo,
        tiempo_estimado_horas=payload.tiempo_estimado_horas,
        disponibilidad_tecnico=payload.disponibilidad_tecnico,
    )
    resultado = predict_priority(features)
    prioridad_persistible = (
        resultado.prioridad_ml.value
        if resultado.prioridad_ml in {PriorityML.ALTA, PriorityML.BAJA}
        else None
    )
    response = await client.table("ordenes_trabajo").update(
        {
            "prioridad_ml": prioridad_persistible,
            "confianza_ml": resultado.confianza_ml,
        }
    ).eq("id", ot_id).execute()
    updated_ot = _ot_row(response.data[0])
    await client.table("inferencias_ml").insert(
        {
            "modelo_id": resultado.modelo_id,
            "ejecutado_por": str(current_user.id),
            "parametros_entrada": parametros_entrada,
            "resultado": {
                "prioridad_ml": resultado.prioridad_ml.value,
                "confianza_ml": resultado.confianza_ml,
                "source": resultado.source,
                "version_modelo": resultado.version_modelo,
            },
        }
    ).execute()
    return PriorityClassificationResponse(
        prioridad_ml=resultado.prioridad_ml,
        confianza_ml=resultado.confianza_ml,
        source=resultado.source,
        orden_trabajo=updated_ot,
    )


async def stock_available(client: AsyncClient, ot_id: str) -> StockAvailabilityResponse:
    ot = await _fetch_work_order(client, ot_id)
    required_response = await client.table("ot_repuestos_requeridos").select(
        "repuesto_id,cantidad"
    ).eq("ot_id", ot_id).execute()
    required = required_response.data or []

    lineas: list[StockAvailabilityItem] = []
    all_available = True
    for row in required:
        repuesto_id = row["repuesto_id"]
        repuesto_response = await (
            client.table("repuestos").select("codigo_sku,nombre").eq("id", repuesto_id).single().execute()
        )
        inventory_response = await (
            client.table("inventario")
            .select("stock_actual")
            .eq("repuesto_id", repuesto_id)
            .eq("sede_id", str(ot.sede_id))
            .execute()
        )
        stock_actual = int(inventory_response.data[0]["stock_actual"]) if inventory_response.data else 0
        disponible = stock_actual >= int(row["cantidad"])
        all_available = all_available and disponible
        lineas.append(
            StockAvailabilityItem(
                repuesto_id=repuesto_id,
                codigo_sku=repuesto_response.data["codigo_sku"],
                nombre=repuesto_response.data["nombre"],
                cantidad_requerida=int(row["cantidad"]),
                stock_actual=stock_actual,
                disponible=disponible,
            )
        )

    return StockAvailabilityResponse(
        ot_id=ot.id,
        estado_sugerido=WorkOrderStatus.in_progress if all_available else WorkOrderStatus.waiting_parts,
        lineas=lineas,
    )


async def change_work_order_status(
    client: AsyncClient, current_user: CurrentUser, ot_id: str, payload: ChangeWorkOrderStatusRequest
) -> dict:
    ot = await _fetch_work_order(client, ot_id)
    target = payload.estado

    if target in {WorkOrderStatus.completed, WorkOrderStatus.cancelada}:
        _require_roles(current_user, UserRole.asesor_servicio, UserRole.administrador)
    elif target in {WorkOrderStatus.waiting_parts, WorkOrderStatus.in_progress, WorkOrderStatus.tech_completed}:
        _require_roles(current_user, UserRole.tecnico, UserRole.asesor_servicio, UserRole.administrador)
        _ensure_technician_can_operate(current_user, ot)

    _ensure_transition(ot.estado, target)

    if target == WorkOrderStatus.in_progress:
        availability = await stock_available(client, ot_id)
        if availability.estado_sugerido != WorkOrderStatus.in_progress:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No hay stock suficiente para pasar la OT a in_progress.",
            )

    if target == WorkOrderStatus.waiting_parts and ot.estado == WorkOrderStatus.waiting_parts:
        latest_pr = await _latest_pr_for_ot(client, ot_id)
        return {"orden_trabajo": ot, "pr_generada": latest_pr}

    update_payload: dict[str, str] = {"estado": target.value}
    if target == WorkOrderStatus.completed:
        update_payload["fecha_completado"] = _utcnow().isoformat()
    response = await client.table("ordenes_trabajo").update(update_payload).eq("id", ot_id).execute()
    updated_ot = _ot_row(response.data[0])

    latest_pr = await _latest_pr_for_ot(client, ot_id) if target == WorkOrderStatus.waiting_parts else None
    return {"orden_trabajo": updated_ot, "pr_generada": latest_pr}


async def _latest_pr_for_ot(client: AsyncClient, ot_id: str) -> PurchaseRequestRead | None:
    response = await client.table("requisiciones_compra").select(
        "id,codigo_pr,ot_id,sede_id,prioridad_heredada,estado,generado_automaticamente,creado_por,created_at,updated_at"
    ).eq("ot_id", ot_id).order("created_at", desc=True).limit(1).execute()
    if not response.data:
        return None
    pr_id = response.data[0]["id"]
    return await _fetch_purchase_request(client, pr_id)


async def complete_service(client: AsyncClient, current_user: CurrentUser, ot_id: str) -> CompleteServiceResponse:
    _require_roles(current_user, UserRole.tecnico, UserRole.administrador)
    ot = await _fetch_work_order(client, ot_id)
    _ensure_technician_can_operate(current_user, ot)
    if ot.estado not in {WorkOrderStatus.in_progress, WorkOrderStatus.tech_completed}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La OT debe estar en in_progress o tech_completed para completar el servicio.",
        )

    history_exists = await client.table("historial_consumo").select("id").eq("ot_id", ot_id).limit(1).execute()
    inserted = 0
    if not history_exists.data:
        movements = await client.table("movimientos_inventario").select(
            "repuesto_id,sede_id,cantidad"
        ).eq("ot_id", ot_id).eq("tipo", InventoryMoveType.salida_consumo.value).execute()
        grouped: dict[tuple[str, str], int] = defaultdict(int)
        for row in movements.data or []:
            grouped[(row["repuesto_id"], row["sede_id"])] += int(row["cantidad"])
        for (repuesto_id, sede_id), quantity in grouped.items():
            await client.table("historial_consumo").insert(
                {
                    "repuesto_id": repuesto_id,
                    "sede_id": sede_id,
                    "ot_id": ot_id,
                    "vehiculo_marca": ot.vehiculo_marca,
                    "vehiculo_modelo": ot.vehiculo_modelo,
                    "vehiculo_anio": ot.vehiculo_anio,
                    "cantidad_consumida": quantity,
                    "fecha_consumo": _utcnow().isoformat(),
                }
            ).execute()
            inserted += 1

    response = await client.table("ordenes_trabajo").update(
        {"estado": WorkOrderStatus.tech_completed.value}
    ).eq("id", ot_id).execute()
    return CompleteServiceResponse(
        orden_trabajo=_ot_row(response.data[0]),
        historial_registrado=inserted,
    )


async def close_work_order(
    client: AsyncClient,
    current_user: CurrentUser,
    ot_id: str,
    payload: CloseWorkOrderRequest | None = None,
) -> CloseWorkOrderResponse:
    _require_roles(current_user, UserRole.asesor_servicio, UserRole.administrador)
    ot = await _fetch_work_order(client, ot_id)
    if ot.estado not in {WorkOrderStatus.tech_completed, WorkOrderStatus.completed}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La OT debe estar en tech_completed o completed para generar la orden de venta.",
        )

    rpc_response = await client.rpc(
        "fn_generar_orden_venta",
        {
            "p_ot_id": ot_id,
            "p_costo_servicio": "0",
        },
    ).execute()
    if rpc_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo generar la orden de venta.",
        )
    orden_venta = await get_sale_by_ot(client, ot_id)
    if orden_venta is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La orden de venta se genero pero no se pudo recuperar.",
        )

    return CloseWorkOrderResponse(
        orden_trabajo=await _fetch_work_order(client, ot_id),
        orden_venta=orden_venta,
    )


async def list_work_orders(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    sede_id: str | None = None,
) -> list[WorkOrderListRead]:
    from app.services.ventas_service import list_work_orders as list_work_orders_with_sales

    rows = await list_work_orders_with_sales(client, page=page, page_size=page_size, sede_id=sede_id)
    return [WorkOrderListRead.model_validate(row) for row in rows]


async def list_active_parts_catalog(client: AsyncClient) -> list[RepuestoRead]:
    response = await (
        client.table("repuestos")
        .select("id,codigo_sku,nombre,descripcion,unidad_medida,categoria_id,marca_compatible,sede_id,estado,created_at,updated_at")
        .eq("estado", "activo")
        .order("created_at", desc=True)
        .execute()
    )
    return [_part_row(row) for row in response.data or []]


async def list_active_work_orders_catalog(client: AsyncClient) -> list[WorkOrderListRead]:
    response = await (
        client.table("ordenes_trabajo")
        .select(
            "id,codigo_ot,cliente_nombre,cliente_documento,cliente_telefono,vehiculo_placa,"
            "vehiculo_marca,vehiculo_modelo,vehiculo_anio,servicio_solicitado,sede_id,asesor_id,"
            "tecnico_id,estado,prioridad_ml,confianza_ml,fecha_diagnostico,"
            "fecha_completado,created_at,updated_at"
        )
        .in_(
            "estado",
            [
                WorkOrderStatus.registrada.value,
                WorkOrderStatus.diagnostico.value,
                WorkOrderStatus.waiting_parts.value,
                WorkOrderStatus.in_progress.value,
                WorkOrderStatus.tech_completed.value,
            ],
        )
        .order("updated_at", desc=True)
        .execute()
    )
    rows = response.data or []
    technician_names: dict[str, str] = {}
    technician_ids = sorted({str(row["tecnico_id"]) for row in rows if row.get("tecnico_id")})
    if technician_ids:
        technicians_response = await (
            client.table("perfiles").select("id,nombres,apellidos,email").in_("id", technician_ids).execute()
        )
        for technician in technicians_response.data or []:
            full_name = f"{technician.get('nombres') or ''} {technician.get('apellidos') or ''}".strip()
            technician_names[str(technician["id"])] = full_name or str(technician.get("email") or "")
    result: list[WorkOrderListRead] = []
    for row in rows:
        payload = dict(row)
        if row.get("tecnico_id"):
            payload["tecnico_nombre"] = technician_names.get(str(row["tecnico_id"]))
        result.append(WorkOrderListRead.model_validate(payload))
    return result


async def get_ot_workspace(
    client: AsyncClient,
    current_user: CurrentUser,
    *,
    page: int = 1,
    page_size: int = 20,
) -> OTWorkspaceRead:
    catalog_client = await create_service_role_client()
    work_orders_task = list_work_orders(client, page=page, page_size=page_size)
    active_parts_task = list_active_parts_catalog(catalog_client)

    sedes_task: asyncio.Future[list[SedeRead]] | None = None
    technicians_task: asyncio.Future[list[UsuarioRead]] | None = None
    if current_user.role in {UserRole.administrador, UserRole.asesor_servicio}:
        sedes_task = asyncio.ensure_future(list_sedes(catalog_client))
        technicians_task = asyncio.ensure_future(
            list_users(catalog_client, rol=UserRole.tecnico, estado=UserStatus.activo)
        )

    work_orders, active_parts = await asyncio.gather(work_orders_task, active_parts_task)
    sedes = await sedes_task if sedes_task is not None else []
    technicians = await technicians_task if technicians_task is not None else []

    return OTWorkspaceRead(
        work_orders=work_orders,
        sedes=sedes,
        technicians=technicians,
        active_parts=active_parts,
    )


async def create_manual_pr(
    client: AsyncClient, current_user: CurrentUser, payload: PurchaseRequestCreate
) -> PurchaseRequestRead:
    _require_roles(current_user, UserRole.almacenero, UserRole.logistica, UserRole.administrador)
    codigo_pr = await _sic_code(client)
    pr_response = await client.table("requisiciones_compra").insert(
        {
            "codigo_pr": codigo_pr,
            "ot_id": str(payload.ot_id) if payload.ot_id else None,
            "sede_id": str(payload.sede_id),
            "prioridad_heredada": payload.prioridad_heredada.value if payload.prioridad_heredada else None,
            "estado": PurchaseRequestStatus.generada.value,
            "generado_automaticamente": False,
            "creado_por": str(current_user.id),
        }
    ).execute()
    pr_id = pr_response.data[0]["id"]
    for detail in payload.detalles:
        await client.table("pr_detalle").insert(
            {
                "pr_id": pr_id,
                "repuesto_id": str(detail.repuesto_id),
                "cantidad": detail.cantidad,
            }
        ).execute()
    return await _fetch_purchase_request(client, pr_id)


async def list_prs(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    estado: PurchaseRequestStatus | None = None,
    sede_id: str | None = None,
) -> PaginatedResponse[PurchaseRequestRead]:
    query = client.table("requisiciones_compra").select(
        "id,codigo_pr,ot_id,sede_id,prioridad_heredada,estado,generado_automaticamente,creado_por,created_at,updated_at"
    )
    if estado is not None:
        query = query.eq("estado", estado.value)
    if sede_id is not None:
        query = query.eq("sede_id", sede_id)
    start, end = _page_range(page, page_size)
    response = await query.order("created_at", desc=True).range(start, end).execute()
    pr_ids = [str(row["id"]) for row in response.data or []]
    detail_map = await _fetch_purchase_request_detail_map(client, pr_ids)
    items = [_pr_row(row, detail_map.get(str(row["id"]), [])) for row in response.data or []]
    return PaginatedResponse[PurchaseRequestRead](
        items=items,
        page=page,
        page_size=page_size,
        total=len(items),
    )


async def update_pr_status(
    client: AsyncClient, current_user: CurrentUser, pr_id: str, payload: PurchaseRequestStateUpdate
) -> PurchaseRequestRead:
    _require_roles(current_user, UserRole.almacenero, UserRole.logistica, UserRole.administrador)
    current = await _fetch_purchase_request(client, pr_id)
    _ensure_pr_transition(current.estado, payload.estado)
    await client.table("requisiciones_compra").update({"estado": payload.estado.value}).eq("id", pr_id).execute()
    return await _fetch_purchase_request(client, pr_id)


async def _current_stock(client: AsyncClient, repuesto_id: str, sede_id: str) -> int:
    response = await client.table("inventario").select("stock_actual").eq("repuesto_id", repuesto_id).eq(
        "sede_id", sede_id
    ).execute()
    if not response.data:
        return 0
    return int(response.data[0]["stock_actual"])


async def _enrich_movement_rows(client: AsyncClient, rows: list[dict], *, stock_result_map: dict[str, int] | None = None) -> list[InventoryMovementRead]:
    stock_result_map = stock_result_map or {}
    repuesto_ids = {str(row["repuesto_id"]) for row in rows if row.get("repuesto_id")}
    sede_ids = {str(row["sede_id"]) for row in rows if row.get("sede_id")}
    ot_ids = {str(row["ot_id"]) for row in rows if row.get("ot_id")}
    oc_ids = {str(row["orden_compra_id"]) for row in rows if row.get("orden_compra_id")}
    registrado_por_ids = {str(row["registrado_por"]) for row in rows if row.get("registrado_por")}

    repuestos_map, sedes_map, ot_map, oc_map, perfiles_map = await asyncio.gather(
        _fetch_id_map(client, table="repuestos", select_fields="id,codigo_sku,nombre", ids=repuesto_ids),
        _fetch_id_map(client, table="sedes", select_fields="id,nombre", ids=sede_ids),
        _fetch_id_map(client, table="ordenes_trabajo", select_fields="id,codigo_ot", ids=ot_ids),
        _fetch_id_map(client, table="ordenes_compra", select_fields="id,codigo_oc", ids=oc_ids),
        _fetch_id_map(client, table="perfiles", select_fields="id,nombres,apellidos", ids=registrado_por_ids),
    )

    enriched: list[InventoryMovementRead] = []
    for row in rows:
        repuesto = repuestos_map.get(str(row.get("repuesto_id")), {})
        sede = sedes_map.get(str(row.get("sede_id")), {})
        ot = ot_map.get(str(row.get("ot_id")), {})
        oc = oc_map.get(str(row.get("orden_compra_id")), {})
        perfil = perfiles_map.get(str(row.get("registrado_por")), {})
        payload = dict(row)
        payload["codigo_sku"] = repuesto.get("codigo_sku")
        payload["repuesto_nombre"] = repuesto.get("nombre")
        payload["sede_nombre"] = sede.get("nombre")
        payload["codigo_ot"] = ot.get("codigo_ot")
        payload["codigo_oc"] = oc.get("codigo_oc")
        payload["registrado_por_nombre"] = " ".join(
            part for part in [perfil.get("nombres"), perfil.get("apellidos")] if part
        ) or None
        payload["stock_resultante"] = stock_result_map.get(str(row.get("id")))
        enriched.append(_movement_row(payload))
    return enriched


async def create_inventory_movement(
    client: AsyncClient, current_user: CurrentUser, payload: InventoryMovementCreate
) -> InventoryMovementRead:
    _require_roles(current_user, UserRole.tecnico, UserRole.almacenero, UserRole.administrador, UserRole.logistica)
    if payload.tipo != InventoryMoveType.salida_consumo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Los movimientos manuales de este modulo solo permiten salida_consumo asociada a una OT. "
                "Las entradas por compra se generan desde recepciones de OC."
            ),
        )
    if payload.tipo == InventoryMoveType.salida_consumo and payload.ot_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ot_id es obligatorio para salida_consumo.",
        )
    if payload.tipo == InventoryMoveType.salida_consumo and payload.ot_id is not None:
        ot = await _fetch_work_order(client, str(payload.ot_id))
        if str(ot.sede_id) != str(payload.sede_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La sede del movimiento debe coincidir con la sede de la OT.",
            )

    current_stock = await _current_stock(client, str(payload.repuesto_id), str(payload.sede_id))
    if current_stock < payload.cantidad:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stock insuficiente para registrar el movimiento.",
        )
    delta = -payload.cantidad
    resulting_stock = current_stock + delta
    if resulting_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El movimiento dejaria stock negativo.",
        )

    response = await client.table("movimientos_inventario").insert(
        {
            "repuesto_id": str(payload.repuesto_id),
            "sede_id": str(payload.sede_id),
            "tipo": payload.tipo.value,
            "cantidad": payload.cantidad,
            "ot_id": str(payload.ot_id) if payload.ot_id else None,
            "motivo": payload.motivo,
            "registrado_por": str(current_user.id),
        }
    ).execute()
    movement_row = response.data[0]
    try:
        await _upsert_inventory_stock(
            client,
            repuesto_id=str(payload.repuesto_id),
            sede_id=str(payload.sede_id),
            stock_actual=resulting_stock,
        )
    except Exception:
        await client.table("movimientos_inventario").delete().eq("id", movement_row["id"]).execute()
        raise
    enriched = await _enrich_movement_rows(client, [movement_row], stock_result_map={str(movement_row["id"]): resulting_stock})
    return enriched[0]


async def list_inventory_movements(
    client: AsyncClient,
    *,
    page: int,
    page_size: int,
    repuesto_id: str | None = None,
    sede_id: str | None = None,
    tipo: InventoryMoveType | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> PaginatedResponse[InventoryMovementRead]:
    query = client.table("movimientos_inventario").select(
        "id,repuesto_id,sede_id,tipo,cantidad,ot_id,orden_compra_id,motivo,registrado_por,created_at",
        count="exact",
    )
    if repuesto_id:
        query = query.eq("repuesto_id", repuesto_id)
    if sede_id:
        query = query.eq("sede_id", sede_id)
    if tipo:
        query = query.eq("tipo", tipo.value)
    if desde:
        query = query.gte("created_at", desde.isoformat())
    if hasta:
        query = query.lte("created_at", hasta.isoformat())
    start, end = _page_range(page, page_size)
    response = await query.order("created_at", desc=True).range(start, end).execute()
    items = await _enrich_movement_rows(client, response.data or [])
    return PaginatedResponse[InventoryMovementRead](
        items=items,
        page=page,
        page_size=page_size,
        total=_response_total(response, len(items)),
    )


async def _fetch_all_inventory_params_map(client: AsyncClient) -> dict[tuple[str, str], dict]:
    response = await (
        client.table("parametros_inventario")
        .select("repuesto_id,sede_id,stock_minimo,stock_maximo,punto_reorden_sugerido_ml")
        .execute()
    )
    return {(row["repuesto_id"], row["sede_id"]): row for row in response.data or []}


def _inventory_read_from_maps(
    row: dict,
    *,
    repuestos_map: dict[str, dict],
    sedes_map: dict[str, dict],
    params_map: dict[tuple[str, str], dict],
) -> InventarioRead:
    repuesto_id = str(row["repuesto_id"])
    sede_id = str(row["sede_id"])
    repuesto = repuestos_map.get(repuesto_id, {})
    sede = sedes_map.get(sede_id, {})
    param = params_map.get((repuesto_id, sede_id), {})
    stock_minimo = param.get("stock_minimo")
    punto_reorden = param.get("punto_reorden_sugerido_ml")
    stock_actual = int(row["stock_actual"])
    estado_stock = _inventory_status(
        stock_actual=stock_actual,
        stock_minimo=int(stock_minimo) if stock_minimo is not None else None,
        punto_reorden=int(punto_reorden) if punto_reorden is not None else None,
    )

    return InventarioRead(
        id=row["id"],
        repuesto_id=repuesto_id,
        sede_id=sede_id,
        codigo_sku=repuesto.get("codigo_sku", ""),
        repuesto_nombre=repuesto.get("nombre", ""),
        sede_nombre=sede.get("nombre"),
        stock_actual=stock_actual,
        stock_minimo=stock_minimo,
        stock_maximo=param.get("stock_maximo"),
        punto_reorden_sugerido_ml=punto_reorden,
        updated_at=row["updated_at"],
        critico=estado_stock in {"BAJO", "CRITICO"},
        estado_stock=estado_stock,
    )


def _critical_inventory_read_from_item(item: InventarioRead) -> InventarioCriticoRead:
    motivo_parts: list[str] = []
    if item.stock_minimo is not None and item.stock_actual <= int(item.stock_minimo):
        motivo_parts.append("stock bajo minimo")
    if item.punto_reorden_sugerido_ml is not None and item.stock_actual <= int(item.punto_reorden_sugerido_ml):
        motivo_parts.append("debajo de punto de reorden")

    return InventarioCriticoRead(
        **item.model_dump(),
        motivo=" y ".join(motivo_parts) if motivo_parts else "stock critico",
    )


async def get_inventory_workspace(
    client: AsyncClient,
    *,
    inventory_page: int = 1,
    inventory_page_size: int = 20,
    critical_page: int = 1,
    critical_page_size: int = 12,
    movement_page: int = 1,
    movement_page_size: int = 20,
) -> InventoryWorkspaceRead:
    catalog_client = await create_service_role_client()
    categorias_task = list_all_categorias_public()
    repuestos_task = list_active_parts_catalog(catalog_client)
    sedes_task = list_sedes(client)
    ordenes_task = list_active_work_orders_catalog(client)

    movement_start, movement_end = _page_range(movement_page, movement_page_size)
    movimientos_query = (
        client.table("movimientos_inventario")
        .select(
            "id,repuesto_id,sede_id,tipo,cantidad,ot_id,orden_compra_id,motivo,registrado_por,created_at",
            count="planned",
        )
        .order("created_at", desc=True)
        .range(movement_start, movement_end)
    )

    inventory_response_task = (
        client.table("inventario")
        .select("id,repuesto_id,sede_id,stock_actual,updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    movimientos_response_task = movimientos_query.execute()

    categorias, repuestos, sedes, ordenes, inventory_response, movimientos_response = await asyncio.gather(
        categorias_task,
        repuestos_task,
        sedes_task,
        ordenes_task,
        inventory_response_task,
        movimientos_response_task,
    )

    inventory_rows = list(inventory_response.data or [])
    movement_rows = list(movimientos_response.data or [])
    inventory_repuesto_ids = {str(row["repuesto_id"]) for row in inventory_rows if row.get("repuesto_id")}
    inventory_sede_ids = {str(row["sede_id"]) for row in inventory_rows if row.get("sede_id")}
    movement_repuesto_ids = {str(row["repuesto_id"]) for row in movement_rows if row.get("repuesto_id")}
    movement_sede_ids = {str(row["sede_id"]) for row in movement_rows if row.get("sede_id")}
    ot_ids = {str(row["ot_id"]) for row in movement_rows if row.get("ot_id")}
    oc_ids = {str(row["orden_compra_id"]) for row in movement_rows if row.get("orden_compra_id")}
    registrado_por_ids = {str(row["registrado_por"]) for row in movement_rows if row.get("registrado_por")}

    repuestos_map = {
        str(item.id): {"id": str(item.id), "codigo_sku": item.codigo_sku, "nombre": item.nombre}
        for item in repuestos
    }
    sedes_map = {str(item.id): {"id": str(item.id), "nombre": item.nombre} for item in sedes}
    ot_map = {str(item.id): {"id": str(item.id), "codigo_ot": item.codigo_ot} for item in ordenes}

    missing_repuesto_ids = (inventory_repuesto_ids | movement_repuesto_ids) - set(repuestos_map)
    missing_sede_ids = (inventory_sede_ids | movement_sede_ids) - set(sedes_map)
    missing_ot_ids = ot_ids - set(ot_map)

    missing_repuestos_map, missing_sedes_map, params_map, missing_ot_map, oc_map, perfiles_map = await asyncio.gather(
        _fetch_id_map(client, table="repuestos", select_fields="id,codigo_sku,nombre", ids=missing_repuesto_ids),
        _fetch_id_map(client, table="sedes", select_fields="id,nombre", ids=missing_sede_ids),
        _fetch_all_inventory_params_map(client),
        _fetch_id_map(client, table="ordenes_trabajo", select_fields="id,codigo_ot", ids=missing_ot_ids),
        _fetch_id_map(client, table="ordenes_compra", select_fields="id,codigo_oc", ids=oc_ids),
        _fetch_id_map(client, table="perfiles", select_fields="id,nombres,apellidos", ids=registrado_por_ids),
    )
    repuestos_map.update(missing_repuestos_map)
    sedes_map.update(missing_sedes_map)
    ot_map.update(missing_ot_map)

    inventory_items = [
        _inventory_read_from_maps(
            row,
            repuestos_map=repuestos_map,
            sedes_map=sedes_map,
            params_map=params_map,
        )
        for row in inventory_rows
    ]
    inventory_start, inventory_end = _page_range(inventory_page, inventory_page_size)
    inventario = PaginatedResponse[InventarioRead](
        items=inventory_items[inventory_start : inventory_end + 1],
        page=inventory_page,
        page_size=inventory_page_size,
        total=_response_total(inventory_response, len(inventory_items)),
    )

    enriched_movements: list[InventoryMovementRead] = []
    for row in movement_rows:
        repuesto = repuestos_map.get(str(row.get("repuesto_id")), {})
        sede = sedes_map.get(str(row.get("sede_id")), {})
        ot = ot_map.get(str(row.get("ot_id")), {})
        oc = oc_map.get(str(row.get("orden_compra_id")), {})
        perfil = perfiles_map.get(str(row.get("registrado_por")), {})
        payload = dict(row)
        payload["codigo_sku"] = repuesto.get("codigo_sku")
        payload["repuesto_nombre"] = repuesto.get("nombre")
        payload["sede_nombre"] = sede.get("nombre")
        payload["codigo_ot"] = ot.get("codigo_ot")
        payload["codigo_oc"] = oc.get("codigo_oc")
        payload["registrado_por_nombre"] = " ".join(
            part for part in [perfil.get("nombres"), perfil.get("apellidos")] if part
        ) or None
        enriched_movements.append(_movement_row(payload))

    movimientos = PaginatedResponse[InventoryMovementRead](
        items=enriched_movements,
        page=movement_page,
        page_size=movement_page_size,
        total=_response_total(movimientos_response, len(enriched_movements)),
    )

    critical_items = [_critical_inventory_read_from_item(item) for item in inventory_items if item.critico]
    criticos_total = len(critical_items)
    bajos_total = sum(1 for item in critical_items if item.estado_stock == "BAJO")
    critical_start, critical_end = _page_range(critical_page, critical_page_size)
    criticos = PaginatedResponse[InventarioCriticoRead](
        items=critical_items[critical_start : critical_end + 1],
        page=critical_page,
        page_size=critical_page_size,
        total=criticos_total,
    )
    return InventoryWorkspaceRead(
        categorias=categorias,
        repuestos=repuestos,
        inventario=inventario,
        criticos=criticos,
        movimientos=movimientos,
        sedes=sedes,
        ordenes_trabajo=ordenes,
        repuestos_total=len(repuestos),
        inventario_total=inventario.total or len(inventario.items),
        criticos_total=criticos_total,
        bajos_total=bajos_total,
        movimientos_total=movimientos.total or len(movimientos.items),
    )
