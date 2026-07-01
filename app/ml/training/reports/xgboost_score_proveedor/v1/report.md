# Reporte xgboost_score_proveedor v1

## Auditoria obligatoria del dataset

- Dataset: `DATASETSmejorados\dataset_score_proveedores_sintetico.csv`
- Filas totales: 8000
- proveedor_id unicos: 8000
- Filas por proveedor: min 1, max 1, proveedores con una sola fila 8000
- score_objetivo: min -37.8125, max 39.2422, promedio 21.0800, mediana 24.8507, desviacion estandar 12.7843
- Filas con score_objetivo negativo: 1205 (15.06%)
- % tasa_defectos_es_inferida = True: 100.00%
- % tasa_entrega_es_inferida = True: 45.29%
- % lead_time_es_inferido = True: 34.90%
- Valores unicos de tasa_defectos: [5.0]

## Contrato de features de entrada

Orden posicional exacto usado para entrenar y para el backend:

1. tasa_entrega_a_tiempo
2. tasa_defectos
3. precio_promedio
4. volumen_compras_previas
5. lead_time_estimado_dias

Target continuo: `score_objetivo`
Columnas excluidas: proveedor_id, proveedor_nombre, tasa_entrega_es_inferida, tasa_defectos_es_inferida, lead_time_es_inferido

## Estrategia elegida

- Caso aplicado: A
- Motivo: Mas de 150 filas: corresponde split 80/20 estratificado por terciles y tuning con CV 5-fold. Dataset con mas de 150 filas. Se uso split 80/20 estratificado por terciles y tuning con CV 5-fold en train.
- Algoritmo final: XGBoost
- Clase serializada con joblib: `XGBRegressor`

## Metricas

### CV

```json
{
  "mae": 0.156158,
  "rmse": 0.40576,
  "mape": 3.252997,
  "r2": 0.998996
}
```

### Finales

```json
{
  "mae": 0.163311,
  "rmse": 0.494537,
  "mape": 2.292934,
  "r2": 0.998485
}
```

### Hiperparametros / seleccion final

```json
{
  "max_depth": 4,
  "learning_rate": 0.049226872559432824,
  "n_estimators": 521,
  "subsample": 0.6193804709218084,
  "colsample_bytree": 0.8307028371124743,
  "min_child_weight": 1.1807627506519358,
  "reg_alpha": 0.02211150426242656,
  "reg_lambda": 3.440974767325467
}
```

## Feature importance

| Feature | Importance |
| --- | ---: |
| tasa_entrega_a_tiempo | 0.80607921 |
| lead_time_estimado_dias | 0.16951330 |
| precio_promedio | 0.01988744 |
| volumen_compras_previas | 0.00452003 |
| tasa_defectos | 0.00000000 |

## Scatter plot

- Archivo: `ml\training\reports\xgboost_score_proveedor\v1\real_vs_pred.png`

## Limitaciones conocidas

- Cada proveedor aparece una sola vez en el dataset. El modelo aprende una fotografia transversal, no una trayectoria historica por proveedor.
- La columna tasa_defectos es constante en el dataset y no aporta variacion real. Se mantuvo por contrato de inferencia, pero su importance debe interpretarse como limitacion conocida. Importance observada: 0.0.
- tasa_defectos_es_inferida es True en 100% de las filas, asi que esa variable proviene enteramente de inferencia/regla previa y no de observacion directa.
- El MAPE aqui se calculo usando `abs(score_objetivo)` en el denominador porque el target puede ser negativo. Sirve como referencia visual, pero MAE, RMSE y R² siguen siendo las metricas principales.

## JSON para modelos_ml

```json
{
  "nombre_modelo": "xgboost_score_proveedor",
  "version": "v1",
  "algoritmo_final": "XGBoost",
  "model_class": "XGBRegressor",
  "dataset": "DATASETSmejorados\\dataset_score_proveedores_sintetico.csv",
  "strategy_case": "A",
  "features_order": [
    "tasa_entrega_a_tiempo",
    "tasa_defectos",
    "precio_promedio",
    "volumen_compras_previas",
    "lead_time_estimado_dias"
  ],
  "target": "score_objetivo",
  "metrics": {
    "mae": 0.163311,
    "rmse": 0.494537,
    "mape": 2.292934,
    "r2": 0.998485
  },
  "cv_metrics": {
    "mae": 0.156158,
    "rmse": 0.40576,
    "mape": 3.252997,
    "r2": 0.998996
  },
  "hyperparameters": {
    "max_depth": 4,
    "learning_rate": 0.049226872559432824,
    "n_estimators": 521,
    "subsample": 0.6193804709218084,
    "colsample_bytree": 0.8307028371124743,
    "min_child_weight": 1.1807627506519358,
    "reg_alpha": 0.02211150426242656,
    "reg_lambda": 3.440974767325467
  }
}
```

## Contrato de inferencia para el backend

- Features en orden posicional:
  - 1. tasa_entrega_a_tiempo
  - 2. tasa_defectos
  - 3. precio_promedio
  - 4. volumen_compras_previas
  - 5. lead_time_estimado_dias
- Output esperado: `float` continuo sin clipping. El target observado en entrenamiento estuvo entre -37.8125 y 39.2422. El modelo puede devolver negativos.
- Referencia de rango predicho en evaluacion (held_out_test): -36.1106 a 38.9050.
- Tipo de objeto que cargara backend con `joblib.load()`: `XGBRegressor`.

Nota final: El artefacto final es el XGBRegressor ajustado con los mejores hiperparametros encontrados en train.
