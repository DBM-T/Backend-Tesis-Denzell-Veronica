from __future__ import annotations

from app.ml.inference.runtime import PrioridadOTFeatures, PrioridadOTResult, predecir_prioridad_ot


def predict_priority(features: PrioridadOTFeatures) -> PrioridadOTResult:
    return predecir_prioridad_ot(features)
