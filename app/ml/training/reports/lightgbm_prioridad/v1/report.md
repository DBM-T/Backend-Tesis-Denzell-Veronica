# Reporte LightGBM Prioridad OT v1

## Dataset y setup

- Dataset: `DATASETSmejorados\dataset_prioridad_ot_sintetico.csv`
- Filas: 3500
- Features usadas en orden posicional: `historial_vehiculo`, `tiempo_estimado_horas`, `disponibilidad_tecnico`
- Columnas excluidas del entrenamiento: `id_orden`, `ot_numero`, `es_etiqueta_inferida`
- Mapping de target usado para compatibilidad con `predict_proba()`: `BAJA=0`, `ALTA=1`
- Split: 80/20 estratificado
- Validacion cruzada: 5-fold estratificada sobre train
- Tuning: Optuna
- Trials de Optuna: 120
- Modelo: `LGBMClassifier(class_weight='balanced')`

## Hiperparametros finales

```json
{
  "num_leaves": 39,
  "max_depth": 4,
  "learning_rate": 0.030808870190585605,
  "n_estimators": 404,
  "min_child_samples": 25,
  "subsample": 0.9460792437281672,
  "colsample_bytree": 0.8556159871417726,
  "reg_alpha": 1.1582479985249268,
  "reg_lambda": 2.860067437681606
}
```

## Metricas finales en test con threshold 0.50

```json
{
  "accuracy": 0.9371,
  "f1_macro": 0.9348,
  "f1_baja": 0.9471,
  "f1_alta": 0.9225,
  "precision_baja": 0.9381,
  "precision_alta": 0.9357,
  "recall_baja": 0.9563,
  "recall_alta": 0.9097,
  "support_baja": 412,
  "support_alta": 288,
  "predicted_positive_mean": 0.4228
}
```

## Matriz de confusion en test con threshold 0.50

Filas = reales, Columnas = predichas

| Real \ Pred | BAJA | ALTA |
| --- | ---: | ---: |
| BAJA | 394 | 18 |
| ALTA | 26 | 262 |

## Threshold afinado para precision de ALTA

- Threshold por defecto del backend actual: `0.5`
- Threshold seleccionado con CV sobre train: `0.56`
- Regla de seleccion: `max cv_precision_alta with cv_recall_alta >= 0.90; tie-break by cv_f1_macro`

```json
{
  "threshold": 0.56,
  "cv_precision_alta": 0.9484,
  "cv_recall_alta": 0.922,
  "cv_f1_macro": 0.9452
}
```

## Metricas finales en test con threshold afinado

```json
{
  "accuracy": 0.9343,
  "f1_macro": 0.9316,
  "f1_baja": 0.9451,
  "f1_alta": 0.9181,
  "precision_baja": 0.9296,
  "precision_alta": 0.9416,
  "recall_baja": 0.9612,
  "recall_alta": 0.8958,
  "support_baja": 412,
  "support_alta": 288,
  "predicted_positive_mean": 0.4228
}
```

## Matriz de confusion en test con threshold afinado

Filas = reales, Columnas = predichas

| Real \ Pred | BAJA | ALTA |
| --- | ---: | ---: |
| BAJA | 396 | 16 |
| ALTA | 30 | 258 |

## Feature Importance

| Feature | Gain | Splits |
| --- | ---: | ---: |
| historial_vehiculo | 18717.4375 | 899 |
| disponibilidad_tecnico | 15405.1783 | 1035 |
| tiempo_estimado_horas | 14229.0210 | 2437 |

## Observacion sobre `disponibilidad_tecnico`

disponibilidad_tecnico no quedo ultima en importance por gain, aunque su baja variabilidad sigue limitando su aporte potencial.

## Artefactos

- Modelo: `ml/models/lightgbm_prioridad/v1/model.joblib`
- Metricas JSON: `ml/training/reports/lightgbm_prioridad/v1/metrics.json`
