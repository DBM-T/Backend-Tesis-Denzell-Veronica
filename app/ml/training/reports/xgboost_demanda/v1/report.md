# Reporte XGBoost Demanda v1

## Setup

- Dataset: `DATASETSmejorados\dataset_demanda_repuestos_catalogo_sintetico.csv`
- Features en orden: `promedio_consumo`, `consumo_90d`, `tendencia`, `stock_actual`, `stock_minimo`, `lead_time_base_dias`
- Target: `demanda_real_futura`
- Split: temporal por `fecha_corte`, dejando el ultimo 20% de fechas para test
- CV: `TimeSeriesSplit`
- Tuning: Optuna con 60 trials por version
- Transformacion del target: `none`
- Objetivo del modelo: `reg:tweedie`
- Version final seleccionada: `completo`

## Tratamiento de MAPE

El MAPE se calculo excluyendo filas con demanda_real_futura = 0 en el set de test porque dividir por cero lo vuelve infinito o enganoso. Ademas, cuando el target real es 1 o muy pequeno, errores absolutos modestos pueden inflar mucho el porcentaje. El reporte incluye cuantas filas con target 0 hubo en test.

## Nota de interpretacion

Este dataset mezcla muchos targets en `0` o `1` con algunos outliers muy altos. Por eso el `MAPE` puede dispararse y no debe leerse como unica medida de usabilidad. Para operacion conviene mirar tambien `MAE`, `RMSE`, `R²`, `sMAPE` y `WAPE`.

## Comparacion de versiones

## Version: completo

- Filas totales usadas: 11900
- Train rows: 9350
- Test rows: 2550
- Fechas train: 2024-04-01, 2024-05-01, 2024-06-01, 2024-07-01, 2024-08-01, 2024-09-01, 2024-10-01, 2024-11-01, 2024-12-01, 2025-01-01, 2025-02-01
- Fechas test: 2025-03-01, 2025-04-01, 2025-05-01
- Filas con target 0 en test: 0

### Tasas de banderas en train

```json
{
  "stock_actual_es_aproximado": 10.65,
  "stock_minimo_es_inferido": 9.82,
  "lead_time_es_inferido": 14.55,
  "historial_insuficiente": 6.55
}
```

### Hiperparametros

```json
{
  "tweedie_variance_power": 1.2209245787909255,
  "max_depth": 5,
  "learning_rate": 0.03372905600896035,
  "n_estimators": 250,
  "subsample": 0.7921376273789545,
  "colsample_bytree": 0.8478794177489314,
  "min_child_weight": 3.63677984609597,
  "reg_alpha": 0.48284864646139225,
  "reg_lambda": 1.02783731240677
}
```

### Score de validacion cruzada

- CV WAPE (%): 6.5409

### Metricas en test

```json
{
  "mae": 1.7967,
  "rmse": 2.6846,
  "mape_pct_nonzero_only": 6.8186,
  "smape_pct": 6.7808,
  "wape_pct": 6.8132,
  "r2": 0.9738
}
```

### Feature importance

| Feature | Importance |
| --- | ---: |
| consumo_90d | 0.663824 |
| promedio_consumo | 0.320576 |
| tendencia | 0.008030 |
| lead_time_base_dias | 0.004225 |
| stock_minimo | 0.001823 |
| stock_actual | 0.001523 |

### Grafico real vs predicho

- Archivo: `ml\training\reports\xgboost_demanda\v1\real_vs_pred_completo.png`

## Version: solo_historial_suficiente

- Filas totales usadas: 11221
- Train rows: 8738
- Test rows: 2483
- Fechas train: 2024-04-01, 2024-05-01, 2024-06-01, 2024-07-01, 2024-08-01, 2024-09-01, 2024-10-01, 2024-11-01, 2024-12-01, 2025-01-01, 2025-02-01
- Fechas test: 2025-03-01, 2025-04-01, 2025-05-01
- Filas con target 0 en test: 0

### Tasas de banderas en train

```json
{
  "stock_actual_es_aproximado": 10.71,
  "stock_minimo_es_inferido": 9.82,
  "lead_time_es_inferido": 14.53,
  "historial_insuficiente": 0.0
}
```

### Hiperparametros

```json
{
  "tweedie_variance_power": 1.2369894380482673,
  "max_depth": 5,
  "learning_rate": 0.021842177671895398,
  "n_estimators": 374,
  "subsample": 0.7812958305066867,
  "colsample_bytree": 0.8824015445845159,
  "min_child_weight": 2.9126724140656393,
  "reg_alpha": 0.8872127425763265,
  "reg_lambda": 1.8388728353562886
}
```

### Score de validacion cruzada

- CV WAPE (%): 6.5947

### Metricas en test

```json
{
  "mae": 1.8054,
  "rmse": 2.7063,
  "mape_pct_nonzero_only": 6.8203,
  "smape_pct": 6.7835,
  "wape_pct": 6.8314,
  "r2": 0.9735
}
```

### Feature importance

| Feature | Importance |
| --- | ---: |
| consumo_90d | 0.709958 |
| promedio_consumo | 0.274447 |
| tendencia | 0.007674 |
| lead_time_base_dias | 0.003958 |
| stock_minimo | 0.002290 |
| stock_actual | 0.001673 |

### Grafico real vs predicho

- Archivo: `ml\training\reports\xgboost_demanda\v1\real_vs_pred_historial_suficiente.png`

