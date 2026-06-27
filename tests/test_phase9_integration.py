from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import app.services.compras_service as compras_service
import app.services.operaciones_service as operaciones_service
from app.core.config import get_settings
from app.schemas.compras import (
    AprobacionProveedorCreate,
    OrdenCompraCreate,
    OrdenCompraEstadoUpdate,
    OrdenCompraRecepcionCreate,
    OrdenCompraRecepcionDetalleCreateItem,
    RFQCreate,
    RFQRespuestaCreate,
    RFQRespuestaCreateItem,
)
from app.schemas.auth import CurrentUser, UserProfile
from app.schemas.compras import RankingProveedorRead
from app.schemas.enums import PurchaseChannel, PurchaseOrderStatus, PurchaseRequestStatus, UserRole, UserStatus, WorkOrderStatus
from app.schemas.operaciones import (
    ChangeWorkOrderStatusRequest,
    DiagnosticRequest,
    PurchaseRequestStateUpdate,
    WorkOrderCreate,
)


def _now():
    return datetime.now(UTC).isoformat()


REPUESTO_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SEDE_ID = "22222222-2222-2222-2222-222222222222"


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str):
        self.client = client
        self.table = table
        self.op = "select"
        self.payload = None
        self.filters = []
        self.order_field = None
        self.order_desc = False
        self.limit_count = None
        self._single = False

    def select(self, *_args, **_kwargs):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = deepcopy(payload)
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = deepcopy(payload)
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, set(values)))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    def ilike(self, column, value):
        self.filters.append(("ilike", column, value.lower().replace("%", "")))
        return self

    def order(self, field, desc=False):
        self.order_field = field
        self.order_desc = desc
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def single(self):
        self._single = True
        return self

    def _match(self, row):
        for op, column, value in self.filters:
            cell = row.get(column)
            if op == "eq" and str(cell) != str(value):
                return False
            if op == "neq" and str(cell) == str(value):
                return False
            if op == "in" and str(cell) not in {str(item) for item in value}:
                return False
            if op == "gte" and str(cell) < str(value):
                return False
            if op == "lte" and str(cell) > str(value):
                return False
            if op == "ilike" and value not in str(cell).lower():
                return False
        return True

    async def execute(self):
        if self.op == "select":
            rows = [deepcopy(row) for row in self.client.tables[self.table] if self._match(row)]
            if self.order_field:
                rows.sort(key=lambda row: str(row.get(self.order_field)), reverse=self.order_desc)
            if self.limit_count is not None:
                rows = rows[: self.limit_count]
            if self._single:
                return FakeResponse(rows[0] if rows else None)
            return FakeResponse(rows)

        if self.op == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for item in payloads:
                row = deepcopy(item)
                row.setdefault("id", str(uuid4()))
                row.setdefault("created_at", _now())
                row.setdefault("updated_at", row.get("created_at"))
                if self.table == "recepciones_oc":
                    row.setdefault("fecha_recepcion", row["created_at"])
                self.client.tables[self.table].append(row)
                inserted.append(deepcopy(row))
                self.client._after_insert(self.table, row)
            return FakeResponse(inserted)

        if self.op == "update":
            updated = []
            for row in self.client.tables[self.table]:
                if self._match(row):
                    before = deepcopy(row)
                    row.update(self.payload)
                    row.setdefault("updated_at", _now())
                    row["updated_at"] = _now()
                    updated.append(deepcopy(row))
                    self.client._after_update(self.table, before, row)
            return FakeResponse(updated)

        if self.op == "delete":
            remaining = []
            deleted = []
            for row in self.client.tables[self.table]:
                if self._match(row):
                    deleted.append(deepcopy(row))
                else:
                    remaining.append(row)
            self.client.tables[self.table] = remaining
            return FakeResponse(deleted)

        return FakeResponse([])


class FakeStorage:
    def from_(self, *_args, **_kwargs):
        return self

    async def upload(self, *_args, **_kwargs):
        return {"path": "fake"}


class FakeAuth:
    async def get_user(self, *_args, **_kwargs):
        return SimpleNamespace(user=SimpleNamespace(id="user-1"))

    async def sign_out(self):
        return None


class FakeClient:
    def __init__(self):
        self.tables = defaultdict(list)
        self.storage = FakeStorage()
        self.auth = FakeAuth()
        self.tables["sedes"].append({"id": SEDE_ID, "nombre": "Sede 1", "created_at": _now()})
        self.tables["perfiles"].append(
            {
                "id": "user-1",
                "nombres": "Admin",
                "apellidos": "Test",
                "email": "admin@calead.pe",
                "rol": UserRole.administrador.value,
                "sede_id": SEDE_ID,
                "estado": UserStatus.activo.value,
                "telefono": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        self.tables["proveedores"].append(
            {
                "id": "prov-1",
                "razon_social": "Proveedor Uno",
                "ruc": "12345678901",
                "email": "prov@example.com",
                "estado": UserStatus.activo.value,
                "tasa_entrega_a_tiempo": Decimal("95"),
                "tasa_defectos": Decimal("1"),
                "precio_promedio": Decimal("100"),
                "volumen_compras_previas": 10,
                "lead_time_estimado_dias": 3,
                "canal_preferido": PurchaseChannel.local.value,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        self.tables["repuestos"].append(
            {
                "id": REPUESTO_ID,
                "codigo_sku": "SKU-1",
                "nombre": "Filtro",
                "estado": UserStatus.activo.value,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        self.tables["inventario"].append(
            {"id": "inv-1", "repuesto_id": REPUESTO_ID, "sede_id": SEDE_ID, "stock_actual": 2, "updated_at": _now()}
        )
        self.tables["parametros_inventario"].append(
            {
                "id": "par-1",
                "repuesto_id": REPUESTO_ID,
                "sede_id": SEDE_ID,
                "stock_minimo": 5,
                "stock_maximo": 20,
                "lead_time_base_dias": 7,
                "punto_reorden_inicial": 4,
                "punto_reorden_sugerido_ml": 4,
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
        self.tables["movimientos_inventario"].append(
            {
                "id": "mov-1",
                "repuesto_id": REPUESTO_ID,
                "sede_id": SEDE_ID,
                "tipo": "salida_consumo",
                "cantidad": 1,
                "ot_id": "ot-1",
                "registrado_por": "user-1",
                "created_at": _now(),
            }
        )
    def table(self, name):
        return FakeQuery(self, name)

    def _after_insert(self, table, row):
        if table == "recepciones_oc_detalle" and row.get("conformidad") == "conforme":
            recepcion = next(
                (item for item in self.tables["recepciones_oc"] if str(item["id"]) == str(row["recepcion_id"])),
                None,
            )
            if recepcion:
                oc = next(
                    (
                        item
                        for item in self.tables["ordenes_compra"]
                        if str(item["id"]) == str(recepcion["oc_id"])
                    ),
                    None,
                )
                if oc:
                    pr = next(
                        (
                            item
                            for item in self.tables["requisiciones_compra"]
                            if str(item["id"]) == str(oc["pr_id"])
                        ),
                        None,
                    )
                    sede_id = pr["sede_id"] if pr else None
                    inv = next(
                        (
                            item
                            for item in self.tables["inventario"]
                            if str(item["repuesto_id"]) == str(row["repuesto_id"])
                        ),
                        None,
                    )
                    if inv:
                        inv["stock_actual"] += int(row["cantidad_recibida"])
                    self.tables["movimientos_inventario"].append(
                        {
                            "id": str(uuid4()),
                            "repuesto_id": row["repuesto_id"],
                            "sede_id": sede_id,
                            "tipo": "entrada_compra",
                            "cantidad": row["cantidad_recibida"],
                            "orden_compra_id": oc["id"],
                            "registrado_por": recepcion["recibido_por"],
                            "created_at": _now(),
                        }
                    )

    def _after_update(self, table, before, after):
        if table == "ordenes_trabajo" and before.get("estado") != "waiting_parts" and after.get("estado") == "waiting_parts":
            pr_id = str(uuid4())
            codigo_pr = f"PR-{datetime.now(UTC).strftime('%Y%m%d')}-ABC123"
            required_parts = [
                item for item in self.tables["ot_repuestos_requeridos"] if item["ot_id"] == after["id"]
            ]
            self.tables["requisiciones_compra"].append(
                {
                    "id": pr_id,
                    "codigo_pr": codigo_pr,
                    "ot_id": after["id"],
                    "sede_id": after["sede_id"],
                    "prioridad_heredada": after.get("prioridad_ml"),
                    "estado": PurchaseRequestStatus.generada.value,
                    "generado_automaticamente": True,
                    "creado_por": after.get("asesor_id"),
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            )
            for item in required_parts:
                self.tables["pr_detalle"].append(
                    {
                        "id": str(uuid4()),
                        "pr_id": pr_id,
                        "repuesto_id": item["repuesto_id"],
                        "cantidad": item["cantidad"],
                    }
                )


def make_user(client: FakeClient, role: UserRole):
    profile = UserProfile(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        nombres="Admin",
        apellidos="Test",
        email="admin@calead.pe",
        rol=role,
        sede_id=UUID("22222222-2222-2222-2222-222222222222"),
        estado=UserStatus.activo,
        telefono=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return CurrentUser.model_construct(
        id=profile.id,
        email=profile.email,
        role=profile.rol,
        profile=profile,
        access_token="token",
        supabase=client,
    )


@pytest.mark.asyncio
async def test_full_flow_otto_oc_recepcion(monkeypatch):
    client = FakeClient()
    current_user = make_user(client, UserRole.administrador)
    settings = get_settings()
    monkeypatch.setattr(settings, "oc_limite_aprobacion_gerencia", Decimal("1"), raising=False)
    async def fake_get_rfq_ranking(*_args, **_kwargs):
        return [
            RankingProveedorRead(
                id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                rfq_id=None,
                proveedor_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                repuesto_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                score_total_ml=Decimal("0.99"),
                ranking_posicion=1,
                canal_sugerido_ml=PurchaseChannel.local,
                version_modelo="heuristic_fallback",
                created_at=datetime.now(UTC),
                proveedor_razon_social="Proveedor Uno",
                repuesto_codigo_sku="SKU-1",
            )
        ]

    monkeypatch.setattr(compras_service, "get_rfq_ranking", fake_get_rfq_ranking)
    monkeypatch.setattr(compras_service, "create_alerta_from_recepcion", lambda *args, **kwargs: None)
    monkeypatch.setattr(operaciones_service, "predict_priority", lambda features: SimpleNamespace(prioridad_ml=SimpleNamespace(value="ALTA"), confianza_ml=0.9, source="heuristic",))

    ot = await operaciones_service.create_work_order(
        client,
        current_user,
        WorkOrderCreate(
            cliente_nombre="Juan Perez",
            cliente_documento="12345678",
            vehiculo_placa="ABC-123",
            vehiculo_marca="Toyota",
            vehiculo_modelo="Corolla",
            vehiculo_anio=2020,
            servicio_solicitado="Servicio de motor",
            sede_id=UUID("22222222-2222-2222-2222-222222222222"),
        ),
    )
    diag = await operaciones_service.register_diagnostic(
        client,
        current_user,
        str(ot.id),
        DiagnosticRequest(
            descripcion="Falla motor",
            repuestos=[{"repuesto_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"), "cantidad": 3}],
        ),
    )
    assert diag.orden_trabajo.estado == WorkOrderStatus.diagnostico

    waiting = await operaciones_service.change_work_order_status(
        client,
        current_user,
        str(ot.id),
        ChangeWorkOrderStatusRequest(estado=WorkOrderStatus.waiting_parts),
    )
    assert waiting["orden_trabajo"].estado == WorkOrderStatus.waiting_parts
    pr = waiting["pr_generada"]
    assert pr is not None
    assert pr.estado == PurchaseRequestStatus.generada

    pr = await operaciones_service.update_pr_status(
        client,
        current_user,
        str(pr.id),
        PurchaseRequestStateUpdate(estado=PurchaseRequestStatus.en_cotizacion),
    )
    pr = await operaciones_service.update_pr_status(
        client,
        current_user,
        str(pr.id),
        PurchaseRequestStateUpdate(estado=PurchaseRequestStatus.aprobada),
    )
    assert pr.estado == PurchaseRequestStatus.aprobada

    rfq = await compras_service.create_rfq(
        client,
        current_user,
        RFQCreate(pr_id=pr.id, proveedor_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")),
    )
    assert rfq.pr_id == pr.id

    await compras_service.add_rfq_responses(
        client,
        current_user,
        str(rfq.id),
        RFQRespuestaCreate(
            respuestas=[
                RFQRespuestaCreateItem(
                    repuesto_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                    precio_unitario=Decimal("10"),
                    disponibilidad=True,
                    lead_time_ofrecido_dias=2,
                )
            ]
        ),
    )

    aprobacion = await compras_service.create_aprobacion_proveedor(
        client,
        current_user,
        AprobacionProveedorCreate(
            rfq_id=rfq.id,
            proveedor_seleccionado_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        ),
    )
    assert aprobacion.coincide_con_recomendacion_ml is True

    oc = await compras_service.create_orden_compra(
        client,
        current_user,
        OrdenCompraCreate(aprobacion_id=aprobacion.id),
    )
    assert oc.estado == PurchaseOrderStatus.pendiente_aprobacion

    current_gerencia = make_user(client, UserRole.gerencia)
    oc = await compras_service.approve_orden_gerencia(client, current_gerencia, str(oc.id))
    assert oc.estado == PurchaseOrderStatus.aprobada

    oc = await compras_service.update_orden_status(
        client,
        current_user,
        str(oc.id),
        OrdenCompraEstadoUpdate(estado=PurchaseOrderStatus.enviada),
    )
    assert oc.estado == PurchaseOrderStatus.enviada

    stock_before = next(row for row in client.tables["inventario"] if row["repuesto_id"] == REPUESTO_ID)["stock_actual"]
    recepcion = await compras_service.create_recepcion_oc(
        client,
        current_user,
        str(oc.id),
        OrdenCompraRecepcionCreate(
            detalles=[
                OrdenCompraRecepcionDetalleCreateItem(
                    repuesto_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                    cantidad_recibida=3,
                    conformidad="conforme",
                )
            ]
        ),
    )
    stock_after = next(row for row in client.tables["inventario"] if row["repuesto_id"] == REPUESTO_ID)["stock_actual"]
    assert stock_after == stock_before + 3
    assert recepcion.detalle[0].conformidad == "conforme"

    waiting_again = await operaciones_service.change_work_order_status(
        client,
        current_user,
        str(ot.id),
        ChangeWorkOrderStatusRequest(estado=WorkOrderStatus.in_progress),
    )
    assert waiting_again["orden_trabajo"].estado == WorkOrderStatus.in_progress

    closed = await operaciones_service.complete_service(client, current_user, str(ot.id))
    assert closed.orden_trabajo.estado == WorkOrderStatus.tech_completed
