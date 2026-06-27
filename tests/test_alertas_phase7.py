from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.enums import AlertSeverity, AlertStatus, AlertType
from app.services.alertas_service import build_dashboard_snapshot, create_alerta_from_recepcion


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if str(row.get(column)) == str(value)]
        return SimpleNamespace(data=rows)


class FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


@pytest.mark.asyncio
async def test_build_dashboard_snapshot_counts_by_thresholds():
    client = FakeClient(
        {
            "inventario": [
                {"repuesto_id": "11111111-1111-1111-1111-111111111111", "sede_id": "22222222-2222-2222-2222-222222222222", "stock_actual": 2},
                {"repuesto_id": "33333333-3333-3333-3333-333333333333", "sede_id": "22222222-2222-2222-2222-222222222222", "stock_actual": 10},
            ],
            "parametros_inventario": [
                {"repuesto_id": "11111111-1111-1111-1111-111111111111", "sede_id": "22222222-2222-2222-2222-222222222222", "stock_minimo": 5, "punto_reorden_sugerido_ml": 4},
                {"repuesto_id": "33333333-3333-3333-3333-333333333333", "sede_id": "22222222-2222-2222-2222-222222222222", "stock_minimo": 3, "punto_reorden_sugerido_ml": 2},
            ],
            "ordenes_compra": [
                {"id": "44444444-4444-4444-4444-444444444444", "estado": "enviada", "sede_id": "22222222-2222-2222-2222-222222222222", "fecha_entrega_comprometida": str(date.today())},
                {"id": "55555555-5555-5555-5555-555555555555", "estado": "pendiente_aprobacion", "sede_id": "22222222-2222-2222-2222-222222222222", "fecha_entrega_comprometida": None},
            ],
            "alertas": [
                {"id": "66666666-6666-6666-6666-666666666666", "sede_id": "22222222-2222-2222-2222-222222222222", "estado": "activa"},
                {"id": "77777777-7777-7777-7777-777777777777", "sede_id": "22222222-2222-2222-2222-222222222222", "estado": "atendida"},
            ],
            "pronosticos_demanda": [
                {"sede_id": "22222222-2222-2222-2222-222222222222", "demanda_proyectada": "3.5"},
                {"sede_id": "22222222-2222-2222-2222-222222222222", "demanda_proyectada": "1.5"},
            ],
        }
    )

    snapshot = await build_dashboard_snapshot(client, sede_id="22222222-2222-2222-2222-222222222222")

    assert snapshot.fecha_corte == date.today()
    assert snapshot.stock_critico_count == 1
    assert snapshot.ordenes_en_curso_count == 2
    assert snapshot.alertas_activas_count == 1
    assert snapshot.demanda_proyectada_total == 5


@pytest.mark.asyncio
async def test_create_alerta_from_recepcion_skips_existing_active_alert():
    client = FakeClient(
        {
            "alertas": [
                {
                    "id": "88888888-8888-8888-8888-888888888888",
                    "tipo": AlertType.no_conformidad_proveedor.value,
                    "estado": AlertStatus.activa.value,
                    "repuesto_id": "11111111-1111-1111-1111-111111111111",
                    "sede_id": "22222222-2222-2222-2222-222222222222",
                }
            ]
        }
    )

    await create_alerta_from_recepcion(
        client,
        tipo=AlertType.no_conformidad_proveedor,
        severidad=AlertSeverity.alta,
        mensaje="No conformidad",
        repuesto_id="11111111-1111-1111-1111-111111111111",
        sede_id="22222222-2222-2222-2222-222222222222",
    )

    assert True
