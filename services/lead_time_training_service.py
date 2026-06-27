"""Preparacion y entrenamiento del modelo XGBoost de lead time con datos reales."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

from config import get_settings
from database import supabase_admin
from services.lead_time_model_service import (
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    build_lead_time_feature_frame,
    clear_lead_time_caches,
)
from services.postgrest_utils import encode_postgrest_payload

TARGET_COLUMN = "lead_time_days"
MIN_CORE_MATCH_RATIO = 0.6
MIN_CORE_MATCH_ROWS = 200
PREFERRED_LEAD_TIME_INPUT = Path("data/raw/dataset_lead_time_sintetico.csv")
DEFINITIVE_LEAD_TIME_DATASET = Path("data/processed/dataset_lead_time_definitivo.csv")
REAL_TABLE_EXPORTS = {
    "ordenes_compra": Path("data/raw/ordenes_compra.csv"),
    "oc_lineas": Path("data/raw/oc_lineas.csv"),
    "proveedores": Path("data/raw/proveedores.csv"),
    "productos": Path("data/raw/productos.csv"),
    "sedes": Path("data/raw/sedes.csv"),
}
DATE_COLUMNS = ["date_order", "date_approve", "date_planned", "effective_date"]


def _preferred_lead_time_inputs() -> list[Path]:
    if PREFERRED_LEAD_TIME_INPUT.exists():
        return [PREFERRED_LEAD_TIME_INPUT]
    settings = get_settings()
    return [Path(settings.lead_time_raw_dataset_path)]


def _normalize_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text.casefold() if text else None


def _should_force_full_dataset(source_path: Path) -> bool:
    name = source_path.name.casefold()
    return "synthetic" in name or "sintetico" in name


def _load_table_from_supabase(table_name: str, page_size: int = 1000) -> pd.DataFrame:
    client = supabase_admin()
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        result = client.table(table_name).select("*").range(start, start + page_size - 1).execute()
        batch = result.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return pd.DataFrame(rows)


def _load_table_from_csv(table_name: str) -> pd.DataFrame:
    csv_path = REAL_TABLE_EXPORTS[table_name]
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No se encontro el respaldo real para '{table_name}' en '{csv_path.as_posix()}'."
        )
    return pd.read_csv(csv_path)


def _load_real_table(table_name: str) -> tuple[pd.DataFrame, str]:
    try:
        table = _load_table_from_supabase(table_name)
        if not table.empty:
            return table, "supabase"
    except Exception:
        pass
    return _load_table_from_csv(table_name), "csv_export"


def build_supabase_related_lead_time_dataset(dataset_path: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    settings = get_settings()
    source_path = dataset_path or Path(settings.lead_time_raw_dataset_path)
    if not source_path.exists():
        raise FileNotFoundError(
            f"No se encontro el dataset base en '{source_path.as_posix()}'."
        )

    df = pd.read_csv(source_path)
    rows_input = int(len(df))
    for column in DATE_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")

    for column in ["po_name", "supplier_name", "sede_name", "product_name"]:
        df[f"{column}_norm"] = df[column].map(_normalize_text)

    orders, orders_source = _load_real_table("ordenes_compra")
    providers, providers_source = _load_real_table("proveedores")
    products, products_source = _load_real_table("productos")
    sites, sites_source = _load_real_table("sedes")
    order_lines, lines_source = _load_real_table("oc_lineas")

    if not orders.empty:
        orders = orders.copy()
        orders["po_codigo_norm"] = orders["po_codigo"].map(_normalize_text)
        orders = orders.rename(
            columns={
                "id": "supabase_oc_id",
                "proveedor_id": "supabase_order_proveedor_id",
                "sede_id": "supabase_order_sede_id",
            }
        )
        orders = orders.drop_duplicates(subset=["po_codigo_norm"], keep="first")
    else:
        orders = pd.DataFrame(
            columns=[
                "po_codigo_norm",
                "supabase_oc_id",
                "supabase_order_proveedor_id",
                "supabase_order_sede_id",
                "fecha_entrega_estimada",
                "fecha_entrega_real",
                "aprobado_at",
                "created_at",
            ]
        )
    if not providers.empty:
        providers = providers.copy()
        providers["supplier_name_norm"] = providers["razon_social"].map(_normalize_text)
        providers = providers.rename(columns={"id": "supabase_proveedor_id"})
        providers = providers.drop_duplicates(subset=["supplier_name_norm"], keep="first")
    else:
        providers = pd.DataFrame(columns=["supplier_name_norm", "supabase_proveedor_id", "ruc"])
    if not products.empty:
        products = products.copy()
        products["product_name_norm"] = products["nombre"].map(_normalize_text)
        products = products.rename(columns={"id": "supabase_producto_id"})
        products = products.drop_duplicates(subset=["product_name_norm"], keep="first")
    else:
        products = pd.DataFrame(columns=["product_name_norm", "supabase_producto_id", "sku_padre"])
    if not sites.empty:
        sites = sites.copy()
        sites["sede_name_norm"] = sites["nombre"].map(_normalize_text)
        sites = sites.rename(columns={"id": "supabase_sede_id"})
        sites = sites.drop_duplicates(subset=["sede_name_norm"], keep="first")
    else:
        sites = pd.DataFrame(columns=["sede_name_norm", "supabase_sede_id"])
    if not order_lines.empty:
        order_lines = order_lines.copy()
        order_lines = order_lines.rename(columns={"id": "supabase_oc_linea_id"})
        order_lines = order_lines.drop_duplicates(subset=["oc_id", "producto_id"], keep="first")
    else:
        order_lines = pd.DataFrame(
            columns=["supabase_oc_linea_id", "oc_id", "producto_id", "qty_pedida", "qty_recibida"]
        )

    merged = df.merge(
        orders[
            [
                "po_codigo_norm",
                "supabase_oc_id",
                "supabase_order_proveedor_id",
                "supabase_order_sede_id",
                "fecha_entrega_estimada",
                "fecha_entrega_real",
                "aprobado_at",
                "created_at",
            ]
        ],
        left_on="po_name_norm",
        right_on="po_codigo_norm",
        how="left",
    )
    merged = merged.merge(
        providers[["supplier_name_norm", "supabase_proveedor_id", "ruc"]],
        on="supplier_name_norm",
        how="left",
    )
    merged = merged.merge(
        sites[["sede_name_norm", "supabase_sede_id"]],
        on="sede_name_norm",
        how="left",
    )
    merged = merged.merge(
        products[["product_name_norm", "supabase_producto_id", "sku_padre"]],
        on="product_name_norm",
        how="left",
    )

    merged["supabase_proveedor_id"] = merged["supabase_order_proveedor_id"].combine_first(
        merged["supabase_proveedor_id"]
    )
    merged["supabase_sede_id"] = merged["supabase_order_sede_id"].combine_first(
        merged["supabase_sede_id"]
    )

    if not order_lines.empty:
        merged = merged.merge(
            order_lines[["supabase_oc_linea_id", "oc_id", "producto_id", "qty_pedida", "qty_recibida"]],
            left_on=["supabase_oc_id", "supabase_producto_id"],
            right_on=["oc_id", "producto_id"],
            how="left",
        )

    merged["matched_order"] = merged["supabase_oc_id"].notna()
    merged["matched_supplier"] = merged["supabase_proveedor_id"].notna()
    merged["matched_sede"] = merged["supabase_sede_id"].notna()
    merged["matched_product"] = merged["supabase_producto_id"].notna()
    merged["matched_order_line"] = merged.get(
        "supabase_oc_linea_id", pd.Series(index=merged.index, dtype="object")
    ).notna()
    merged["matched_core"] = (
        merged["matched_order"] & merged["matched_supplier"] & merged["matched_sede"]
    )

    matched = merged.loc[merged["matched_core"]].copy()
    core_match_rows = int(merged["matched_core"].sum())
    core_match_ratio = (core_match_rows / rows_input) if rows_input else 0.0
    use_full_dataset_fallback = (
        matched.empty
        or core_match_rows < MIN_CORE_MATCH_ROWS
        or core_match_ratio < MIN_CORE_MATCH_RATIO
        or _should_force_full_dataset(source_path)
    )
    training_df = merged.copy() if use_full_dataset_fallback else matched

    report = {
        "dataset_source": str(source_path),
        "rows_input": rows_input,
        "rows_training": int(len(training_df)),
        "rows_matched_core": core_match_rows,
        "rows_matched_order": int(merged["matched_order"].sum()),
        "rows_matched_supplier": int(merged["matched_supplier"].sum()),
        "rows_matched_sede": int(merged["matched_sede"].sum()),
        "rows_matched_product": int(merged["matched_product"].sum()),
        "rows_matched_order_line": int(merged["matched_order_line"].sum()),
        "core_match_ratio": round(core_match_ratio, 6),
        "min_core_match_ratio": MIN_CORE_MATCH_RATIO,
        "min_core_match_rows": MIN_CORE_MATCH_ROWS,
        "used_full_dataset_fallback": use_full_dataset_fallback,
        "table_sources": {
            "ordenes_compra": orders_source,
            "oc_lineas": lines_source,
            "proveedores": providers_source,
            "productos": products_source,
            "sedes": sites_source,
        },
    }
    return training_df.drop(columns=[c for c in training_df.columns if c.endswith("_norm")]), report


def clean_lead_time_training_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    cleaned = df.copy()
    for column in DATE_COLUMNS:
        if column in cleaned.columns:
            cleaned[column] = pd.to_datetime(cleaned[column], errors="coerce")

    numeric_columns = [
        "product_qty",
        "qty_received",
        "price_unit",
        "supplier_lead_time_decl",
        "supplier_min_qty",
        "supplier_price",
        "approve_dow",
        "approve_month",
        "planned_lead_time_days",
        TARGET_COLUMN,
    ]
    for column in numeric_columns:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned["category"] = cleaned["category"].fillna("SIN_CATEGORIA")
    cleaned["is_storable"] = cleaned["is_storable"].fillna("f")
    cleaned["is_child_sku"] = cleaned["is_child_sku"].fillna("f")

    invalid_target_mask = cleaned[TARGET_COLUMN].isna() | (cleaned[TARGET_COLUMN] < 0)
    invalid_date_mask = cleaned["date_order"].isna() | cleaned["date_approve"].isna()
    rows_dropped = int((invalid_target_mask | invalid_date_mask).sum())
    cleaned = cleaned.loc[~(invalid_target_mask | invalid_date_mask)].copy()

    features = build_lead_time_feature_frame(cleaned)
    cleaned["approve_hour"] = features["approve_hour"]
    cleaned["approval_lag_hours"] = features["approval_lag_hours"]
    cleaned["planned_gap_days"] = features["planned_gap_days"]
    cleaned["is_storable_num"] = features["is_storable_num"]
    cleaned["is_child_sku_num"] = features["is_child_sku_num"]

    report = {
        "rows_out": int(len(cleaned)),
        "rows_dropped": rows_dropped,
        "missing_after_cleaning": {
            column: int(value)
            for column, value in cleaned.isna().sum().items()
            if int(value) > 0
        },
    }
    return cleaned, report


def _make_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
            (
                "numeric",
                Pipeline(steps=[("imputer", SimpleImputer(strategy="median"))]),
                NUMERIC_FEATURES,
            ),
        ]
    )
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.8,
        min_child_weight=2,
        reg_alpha=0.0,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=4,
        tree_method="hist",
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _normalize_input_paths(input_path: Path | list[Path] | tuple[Path, ...]) -> list[Path]:
    if isinstance(input_path, (list, tuple)):
        return [Path(path) for path in input_path]
    return [Path(input_path)]


def _build_training_dataset_for_inputs(
    input_path: Path | list[Path] | tuple[Path, ...],
) -> tuple[pd.DataFrame, dict[str, Any], str]:
    input_paths = _normalize_input_paths(input_path)
    prepared_frames: list[pd.DataFrame] = []
    source_reports: list[dict[str, Any]] = []

    for path in input_paths:
        prepared_df, dataset_report = build_supabase_related_lead_time_dataset(path)
        prepared_df = prepared_df.copy()
        prepared_df["training_source_file"] = path.name
        prepared_frames.append(prepared_df)
        source_reports.append(dataset_report)

    combined_df = pd.concat(prepared_frames, ignore_index=True)
    combined_report = {
        "dataset_sources": [str(path) for path in input_paths],
        "source_count": len(input_paths),
        "rows_input": int(sum(item["rows_input"] for item in source_reports)),
        "rows_training": int(len(combined_df)),
        "rows_matched_core": int(sum(item["rows_matched_core"] for item in source_reports)),
        "rows_matched_order": int(sum(item["rows_matched_order"] for item in source_reports)),
        "rows_matched_supplier": int(sum(item["rows_matched_supplier"] for item in source_reports)),
        "rows_matched_sede": int(sum(item["rows_matched_sede"] for item in source_reports)),
        "rows_matched_product": int(sum(item["rows_matched_product"] for item in source_reports)),
        "rows_matched_order_line": int(sum(item["rows_matched_order_line"] for item in source_reports)),
        "used_full_dataset_fallback": any(item["used_full_dataset_fallback"] for item in source_reports),
        "source_reports": source_reports,
    }
    source_label = " + ".join(path.name for path in input_paths)
    return combined_df, combined_report, source_label


def _register_model_in_supabase(bundle: dict[str, Any], metrics_report: dict[str, Any]) -> str | None:
    try:
        admin = supabase_admin()
        admin.table("ml_modelos").update({"activo": False}).eq("tipo", "xgboost").eq(
            "proposito", "lead_time"
        ).execute()
        payload = {
            "nombre": "XGBoost Lead Time",
            "tipo": "xgboost",
            "proposito": "lead_time",
            "version": bundle["model_version"],
            "metricas": {
                "mae": metrics_report["mae"],
                "rmse": metrics_report["rmse"],
                "r2": metrics_report["r2"],
                "rows_total": metrics_report["rows_total"],
                "rows_matched_core": metrics_report["dataset_report"]["rows_matched_core"],
            },
            "hiperparametros": {
                **bundle["hyperparameters"],
                "feature_columns": MODEL_FEATURES,
                "dataset": metrics_report["dataset_report"],
            },
            "activo": True,
        }
        result = admin.table("ml_modelos").insert(encode_postgrest_payload(payload)).execute()
        if result.data:
            return result.data[0].get("id")
    except Exception:
        return None
    return None


def train_lead_time_model(
    input_path: Path | list[Path] | tuple[Path, ...],
    model_output: Path,
    dataset_output: Path | None = None,
    register_in_supabase: bool = True,
) -> dict[str, Any]:
    prepared_df, dataset_report, source_label = _build_training_dataset_for_inputs(input_path)
    cleaned_df, cleaning_report = clean_lead_time_training_dataframe(prepared_df)
    if cleaned_df.empty:
        raise RuntimeError("No quedaron filas validas para entrenar el modelo de lead time")

    X = build_lead_time_feature_frame(cleaned_df)
    y = pd.to_numeric(cleaned_df[TARGET_COLUMN], errors="coerce").fillna(0.0)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = _make_pipeline()
    pipeline.fit(X_train, y_train)

    raw_predictions = pipeline.predict(X_test)
    predictions = np.clip(raw_predictions, a_min=0.0, a_max=None)
    mae = mean_absolute_error(y_test, predictions)
    rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
    r2 = r2_score(y_test, predictions)

    final_pipeline = _make_pipeline()
    final_pipeline.fit(X, y)

    model_version = f"lead-time-xgb-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    trained_at = datetime.now(timezone.utc).isoformat()
    reference_output = dataset_output or Path(get_settings().lead_time_dataset_path)
    metrics = {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
    }
    bundle = {
        "pipeline": final_pipeline,
        "model_version": model_version,
        "target": TARGET_COLUMN,
        "metrics": metrics,
        "feature_columns": MODEL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "trained_at": trained_at,
        "training_rows": int(len(cleaned_df)),
        "source_input": source_label,
        "source_inputs": dataset_report["dataset_sources"],
        "reference_dataset_output": str(reference_output),
        "hyperparameters": final_pipeline.named_steps["model"].get_xgb_params(),
        "dataset_report": dataset_report,
        "cleaning_report": cleaning_report,
    }

    model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_output)

    reference_output.parent.mkdir(parents=True, exist_ok=True)
    cleaned_df.to_csv(reference_output, index=False)

    metrics_report = {
        **metrics,
        "model_version": model_version,
        "target": TARGET_COLUMN,
        "trained_at": trained_at,
        "rows_total": int(len(cleaned_df)),
        "rows_train": int(len(X_train)),
        "rows_test": int(len(X_test)),
        "feature_columns": MODEL_FEATURES,
        "hyperparameters": bundle["hyperparameters"],
        "dataset_report": dataset_report,
        "cleaning_report": cleaning_report,
        "source_input": source_label,
        "source_inputs": dataset_report["dataset_sources"],
        "reference_dataset_output": str(reference_output),
    }

    metrics_path = model_output.with_name(f"{model_output.stem}_metrics.json")
    _write_json(metrics_path, metrics_report)
    report_path = reference_output.with_name(f"{reference_output.stem}_report.json")
    _write_json(report_path, {**dataset_report, **cleaning_report, "output_path": str(reference_output)})
    clear_lead_time_caches()

    model_registry_id = None
    if register_in_supabase:
        model_registry_id = _register_model_in_supabase(bundle, metrics_report)
    metrics_report["ml_modelos_id"] = model_registry_id
    return metrics_report


def retrain_lead_time_model() -> dict[str, Any]:
    settings = get_settings()
    return train_lead_time_model(
        input_path=_preferred_lead_time_inputs(),
        model_output=Path(settings.xgboost_lead_time_model_path),
        dataset_output=DEFINITIVE_LEAD_TIME_DATASET,
        register_in_supabase=True,
    )


def retrain_lead_time_model_best_known() -> dict[str, Any]:
    return retrain_lead_time_model()
