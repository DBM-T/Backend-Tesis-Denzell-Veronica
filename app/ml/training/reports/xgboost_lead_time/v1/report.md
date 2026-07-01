# Reporte XGBoost Lead Time v1

## Auditoria del target

- Dataset: `DATASETSmejorados\dataset_lead_time_compras_sintetico.csv`
- Filas: `6000`
- Minimo: `1.2`
- Maximo: `26.44`
- Promedio: `7.2268`
- Mediana: `6.79`
- Desviacion estandar: `3.3041`
- Valores unicos de proveedor_id: `150`
- Porcentaje con `lead_time_estimado_es_inferido = True`: `15.4667%`
- Participacion del valor mas frecuente: `0.25%`
- Distribucion casi constante (>80% en un mismo valor): `False`

### Frecuencia por valor entero del target

| lead_time_real_dias | filas |
| --- | ---: |
| 1 | 51 |
| 2 | 255 |
| 3 | 582 |
| 4 | 760 |
| 5 | 770 |
| 6 | 744 |
| 7 | 782 |
| 8 | 644 |
| 9 | 402 |
| 10 | 304 |
| 11 | 193 |
| 12 | 155 |
| 13 | 102 |
| 14 | 90 |
| 15 | 49 |
| 16 | 39 |
| 17 | 17 |
| 18 | 13 |
| 19 | 21 |
| 20 | 9 |
| 21 | 7 |
| 22 | 5 |
| 23 | 4 |
| 24 | 1 |
| 26 | 1 |

## Setup de entrenamiento

- Features en orden: `lead_time_estimado_dias`, `monto_total`, `cantidad_lineas`, `cantidad_total_unidades`, `mes_pedido`
- Target: `lead_time_real_dias`
- Split: temporal por `compra_id`, ultimo 20% mas reciente como test
- Train rows: `4800`
- Test rows: `1200`
- Rango `compra_id` train: `1` a `4800`
- Rango `compra_id` test: `4801` a `6000`
- TimeSeriesSplit para validacion cruzada
- Tuning: Optuna con `60` trials por variante
- Variante final seleccionada: `regresion_log1p`
- Variante de clasificacion: no probada porque la desviacion estandar del target fue `>= 2.0`

## Variantes de regresion

## Variante: regresion_raw

- Transformacion del target: `none`
- CV MAE: `0.372`

### Hiperparametros

```json
{
  "max_depth": 3,
  "learning_rate": 0.02926900119346936,
  "n_estimators": 396,
  "subsample": 0.7687509758147958,
  "colsample_bytree": 0.9298528902087922,
  "min_child_weight": 2.8122725883059463
}
```

### Metricas en test

```json
{
  "mae": 0.32,
  "rmse": 0.4658,
  "mape": 4.765,
  "r2": 0.9793,
  "mae_inferido_false_only": 0.285,
  "test_rows_inferido_false_only": 1021
}
```

### Feature importance

| Feature | Importance |
| --- | ---: |
| lead_time_estimado_dias | 0.865275 |
| cantidad_lineas | 0.043907 |
| cantidad_total_unidades | 0.037462 |
| monto_total | 0.036102 |
| mes_pedido | 0.017253 |

## Variante: regresion_log1p

- Transformacion del target: `log1p`
- CV MAE: `0.3638`

### Hiperparametros

```json
{
  "max_depth": 2,
  "learning_rate": 0.058357037277661894,
  "n_estimators": 280,
  "subsample": 0.6369286526334413,
  "colsample_bytree": 0.7990676174866341,
  "min_child_weight": 8.101389011542805
}
```

### Metricas en test

```json
{
  "mae": 0.3095,
  "rmse": 0.4641,
  "mape": 4.489,
  "r2": 0.9795,
  "mae_inferido_false_only": 0.2752,
  "test_rows_inferido_false_only": 1021
}
```

### Feature importance

| Feature | Importance |
| --- | ---: |
| lead_time_estimado_dias | 0.876775 |
| cantidad_total_unidades | 0.042962 |
| cantidad_lineas | 0.035738 |
| monto_total | 0.029256 |
| mes_pedido | 0.015269 |


## Contrato de inferencia para el backend

- Lista de features en orden posicional: `lead_time_estimado_dias`, `monto_total`, `cantidad_lineas`, `cantidad_total_unidades`, `mes_pedido`
- Tipo de salida del modelo: `float continuo`
- Si terminaste usando log1p u otra transformacion, aclararlo aqui para que el backend aplique la inversa antes de guardar el resultado:
  - La variante final `regresion_log1p` usa `log1p` sobre el target y requiere aplicar `expm1` a la salida del modelo.
