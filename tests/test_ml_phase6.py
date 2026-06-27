from app.ml.inference.runtime import (
    DemandaFeatures,
    PrioridadOTFeatures,
    RankingProveedorCandidate,
    predecir_demanda,
    predecir_prioridad_ot,
    predecir_ranking_proveedores,
)
from app.schemas.enums import PriorityML


def test_predecir_prioridad_ot_fallback_is_stable():
    result = predecir_prioridad_ot(
        PrioridadOTFeatures(
            ot_id="ot-1",
            servicio_solicitado="Servicio de motor",
            historial_vehiculo=4,
            tiempo_estimado_horas=8,
            disponibilidad_tecnico=0.2,
        )
    )

    assert result.prioridad_ml in {PriorityML.ALTA, PriorityML.BAJA}
    assert 0 <= result.confianza_ml <= 1


def test_predecir_ranking_proveedores_orders_by_score():
    items = predecir_ranking_proveedores(
        [
            RankingProveedorCandidate(
                proveedor_id="p1",
                repuesto_id="r1",
                tasa_entrega_a_tiempo=95,
                tasa_defectos=1,
                precio_promedio=100,
                volumen_compras_previas=10,
                lead_time_estimado_dias=2,
                canal_preferido="local",
            ),
            RankingProveedorCandidate(
                proveedor_id="p2",
                repuesto_id="r1",
                tasa_entrega_a_tiempo=80,
                tasa_defectos=5,
                precio_promedio=150,
                volumen_compras_previas=2,
                lead_time_estimado_dias=8,
                canal_preferido="distribuidor",
            ),
        ]
    )

    assert items[0].proveedor_id == "p1"
    assert items[0].ranking_posicion == 1


def test_predecir_demanda_fallback_returns_positive_forecast():
    result = predecir_demanda(
        DemandaFeatures(
            repuesto_id="r1",
            sede_id="s1",
            promedio_consumo=3,
            consumo_90d=12,
            tendencia=1,
            stock_actual=5,
            stock_minimo=4,
            lead_time_base_dias=7,
        )
    )

    assert result.demanda_proyectada > 0
    assert result.punto_reorden_sugerido >= 1
