"""Servicio y utilidades para el modelo XGBoost de lead time."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from config import get_settings

CATEGORICAL_FEATURES = [
    "supplier_id",
    "sede_id",
    "warehouse_id",
    "product_tmpl_id",
    "category",
]
NUMERIC_FEATURES = [
    "product_qty",
    "price_unit",
    "supplier_lead_time_decl",
    "supplier_min_qty",
    "supplier_price",
    "planned_lead_time_days",
    "approve_dow",
    "approve_month",
    "approve_hour",
    "approval_lag_hours",
    "planned_gap_days",
    "is_storable_num",
    "is_child_sku_num",
]
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
_LEAD_TIME_BUNDLE_CACHE: dict[str, Any] | None = None
_LEAD_TIME_BUNDLE_MTIME: float | None = None
_LEAD_TIME_DATASET_CACHE: pd.DataFrame | None = None
_LEAD_TIME_DATASET_KEY: tuple[str, float] | None = None


def _normalize_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"t", "true", "1", "y", "yes", "si", "s"}:
        return True
    if text in {"f", "false", "0", "n", "no"}:
        return False
    return None


def _to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def build_lead_time_feature_frame(rows: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)

    for column in ["date_order", "date_approve", "date_planned"]:
        if column in df.columns:
            df[column] = _to_datetime(df[column])
        else:
            df[column] = pd.NaT

    for column in [
        "product_qty",
        "price_unit",
        "supplier_lead_time_decl",
        "supplier_min_qty",
        "supplier_price",
        "planned_lead_time_days",
        "approve_dow",
        "approve_month",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = pd.NA

    approve_dow = pd.to_numeric(df["approve_dow"], errors="coerce")
    approve_month = pd.to_numeric(df["approve_month"], errors="coerce")
    df["approve_dow"] = approve_dow.where(
        approve_dow.notna(), df["date_approve"].dt.dayofweek.astype("float64")
    )
    df["approve_month"] = approve_month.where(
        approve_month.notna(), df["date_approve"].dt.month.astype("float64")
    )
    df["approve_hour"] = df["date_approve"].dt.hour.astype("float64")
    df["approval_lag_hours"] = (
        (df["date_approve"] - df["date_order"]).dt.total_seconds() / 3600.0
    )
    df["planned_gap_days"] = (
        (df["date_planned"] - df["date_approve"]).dt.total_seconds() / 86400.0
    )

    if "category" not in df.columns:
        df["category"] = "SIN_CATEGORIA"
    else:
        df["category"] = df["category"].fillna("SIN_CATEGORIA")
    for column in ["supplier_id", "sede_id", "warehouse_id", "product_tmpl_id"]:
        if column not in df.columns:
            df[column] = "missing"
        else:
            df[column] = df[column].astype("string").fillna("missing")

    if "is_storable" not in df.columns:
        df["is_storable_num"] = 0
    else:
        df["is_storable_num"] = df["is_storable"].map(_normalize_bool).fillna(False).astype(int)
    if "is_child_sku" not in df.columns:
        df["is_child_sku_num"] = 0
    else:
        df["is_child_sku_num"] = df["is_child_sku"].map(_normalize_bool).fillna(False).astype(int)

    features = df[MODEL_FEATURES].copy()
    return features


def _model_path() -> Path:
    settings = get_settings()
    return Path(settings.xgboost_lead_time_model_path)


def _dataset_path() -> Path:
    settings = get_settings()
    return Path(settings.lead_time_dataset_path)


def _raw_dataset_path() -> Path:
    settings = get_settings()
    return Path(settings.lead_time_raw_dataset_path)


def load_lead_time_bundle() -> dict[str, Any]:
    global _LEAD_TIME_BUNDLE_CACHE, _LEAD_TIME_BUNDLE_MTIME
    model_path = _model_path()
    if not model_path.exists():
        raise FileNotFoundError(
            f"No se encontro el modelo de lead time en '{model_path.as_posix()}'. "
            "Primero ejecuta el entrenamiento."
        )
    mtime = model_path.stat().st_mtime
    if _LEAD_TIME_BUNDLE_CACHE is not None and _LEAD_TIME_BUNDLE_MTIME == mtime:
        return _LEAD_TIME_BUNDLE_CACHE

    bundle = joblib.load(model_path)
    if not isinstance(bundle, dict) or "pipeline" not in bundle:
        raise RuntimeError("El archivo del modelo de lead time no tiene el formato esperado")
    _LEAD_TIME_BUNDLE_CACHE = bundle
    _LEAD_TIME_BUNDLE_MTIME = mtime
    return bundle


def load_lead_time_reference_dataset() -> pd.DataFrame:
    global _LEAD_TIME_DATASET_CACHE, _LEAD_TIME_DATASET_KEY
    bundle_dataset_path: Path | None = None
    try:
        bundle = load_lead_time_bundle()
        raw_bundle_dataset_path = bundle.get("reference_dataset_output")
        if raw_bundle_dataset_path:
            candidate = Path(str(raw_bundle_dataset_path))
            if candidate.exists():
                bundle_dataset_path = candidate
    except Exception:
        bundle_dataset_path = None

    dataset_path = bundle_dataset_path or _dataset_path()
    if dataset_path.exists():
        cache_key = (dataset_path.as_posix(), dataset_path.stat().st_mtime)
        if _LEAD_TIME_DATASET_CACHE is not None and _LEAD_TIME_DATASET_KEY == cache_key:
            return _LEAD_TIME_DATASET_CACHE
        df = pd.read_csv(
            dataset_path,
            parse_dates=["date_order", "date_approve", "date_planned", "effective_date"],
        )
        _LEAD_TIME_DATASET_CACHE = df
        _LEAD_TIME_DATASET_KEY = cache_key
        return df

    raw_dataset_path = _raw_dataset_path()
    if not raw_dataset_path.exists():
        raise FileNotFoundError(
            f"No se encontro el dataset de lead time ni en '{dataset_path.as_posix()}' "
            f"ni en '{raw_dataset_path.as_posix()}'."
        )

    from services.lead_time_training_service import build_supabase_related_lead_time_dataset

    df, _ = build_supabase_related_lead_time_dataset(raw_dataset_path)
    _LEAD_TIME_DATASET_CACHE = df
    _LEAD_TIME_DATASET_KEY = (raw_dataset_path.as_posix(), raw_dataset_path.stat().st_mtime)
    return df


def clear_lead_time_caches() -> None:
    global _LEAD_TIME_BUNDLE_CACHE, _LEAD_TIME_BUNDLE_MTIME
    global _LEAD_TIME_DATASET_CACHE, _LEAD_TIME_DATASET_KEY
    _LEAD_TIME_BUNDLE_CACHE = None
    _LEAD_TIME_BUNDLE_MTIME = None
    _LEAD_TIME_DATASET_CACHE = None
    _LEAD_TIME_DATASET_KEY = None


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _serialize_match(row: pd.Series) -> dict[str, Any]:
    return {
        "po_line_id": int(row["po_line_id"]),
        "po_id": int(row["po_id"]),
        "po_name": _safe_text(row.get("po_name")),
        "supplier_id": _safe_text(row.get("supplier_id")),
        "supplier_name": _safe_text(row.get("supplier_name")),
        "sede_id": _safe_text(row.get("sede_id")),
        "sede_name": _safe_text(row.get("sede_name")),
        "warehouse_id": _safe_text(row.get("warehouse_id")),
        "warehouse_name": _safe_text(row.get("warehouse_name")),
        "product_tmpl_id": _safe_text(row.get("product_tmpl_id")),
        "product_name": _safe_text(row.get("product_name")),
        "category": _safe_text(row.get("category")),
        "product_qty": _safe_float(row.get("product_qty")),
        "price_unit": _safe_float(row.get("price_unit")),
        "supplier_price": _safe_float(row.get("supplier_price")),
        "planned_lead_time_days": _safe_float(row.get("planned_lead_time_days")),
        "lead_time_days": _safe_float(row.get("lead_time_days")),
        "date_approve": row["date_approve"].isoformat() if pd.notna(row.get("date_approve")) else None,
        "effective_date": row["effective_date"].isoformat() if pd.notna(row.get("effective_date")) else None,
        "match_score": _safe_float(row.get("match_score")) or 0.0,
    }


def find_lead_time_matches(payload: dict[str, Any], limit: int = 10) -> tuple[int, list[dict[str, Any]]]:
    df = load_lead_time_reference_dataset().copy()
    request_supplier = str(payload.get("supplier_id")) if payload.get("supplier_id") is not None else None
    request_sede = str(payload.get("sede_id")) if payload.get("sede_id") is not None else None
    request_warehouse = (
        str(payload.get("warehouse_id")) if payload.get("warehouse_id") is not None else None
    )
    request_product = (
        str(payload.get("product_tmpl_id")) if payload.get("product_tmpl_id") is not None else None
    )
    request_category = payload.get("category")
    request_qty = payload.get("product_qty")

    df["supplier_id"] = df["supplier_id"].astype("Int64").astype("string")
    df["sede_id"] = df["sede_id"].astype("Int64").astype("string")
    df["warehouse_id"] = df["warehouse_id"].astype("Int64").astype("string")
    df["product_tmpl_id"] = df["product_tmpl_id"].astype("Int64").astype("string")

    mask = pd.Series(False, index=df.index)
    if request_product is not None:
        mask = mask | (df["product_tmpl_id"] == request_product)
    if request_supplier is not None:
        mask = mask | (df["supplier_id"] == request_supplier)
    if request_category:
        mask = mask | (df["category"].fillna("SIN_CATEGORIA") == str(request_category))
    if not mask.any():
        mask = pd.Series(True, index=df.index)

    candidates = df.loc[mask].copy()
    candidates["match_score"] = 0.0
    if request_product is not None:
        candidates.loc[candidates["product_tmpl_id"] == request_product, "match_score"] += 5
    if request_supplier is not None:
        candidates.loc[candidates["supplier_id"] == request_supplier, "match_score"] += 4
    if request_sede is not None:
        candidates.loc[candidates["sede_id"] == request_sede, "match_score"] += 3
    if request_warehouse is not None:
        candidates.loc[candidates["warehouse_id"] == request_warehouse, "match_score"] += 2
    if request_category:
        candidates.loc[
            candidates["category"].fillna("SIN_CATEGORIA") == str(request_category), "match_score"
        ] += 1
    if request_qty is not None:
        qty = float(request_qty)
        qty_distance = (pd.to_numeric(candidates["product_qty"], errors="coerce") - qty).abs().fillna(9999)
        candidates["match_score"] += (1 / (1 + qty_distance)).astype(float)

    candidates = candidates.sort_values(
        by=["match_score", "date_approve"], ascending=[False, False]
    )
    total = int(len(candidates))
    items = [_serialize_match(row) for _, row in candidates.head(limit).iterrows()]
    return total, items


def predict_lead_time_days(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = load_lead_time_bundle()
    features = build_lead_time_feature_frame([payload])
    prediction = float(bundle["pipeline"].predict(features)[0])
    prediction = max(0.0, prediction)
    total_matches, matches = find_lead_time_matches(payload, limit=10)
    metrics = bundle.get("metrics") or {}
    sanitized_metrics = {
        key: float(value) if value is not None else None for key, value in metrics.items()
    }
    historical_lead_times = [
        item["lead_time_days"] for item in matches if item.get("lead_time_days") is not None
    ]
    avg_historical = (
        round(sum(historical_lead_times) / len(historical_lead_times), 4)
        if historical_lead_times
        else None
    )
    return {
        "lead_time_days_pred": Decimal(str(round(prediction, 6))),
        "lead_time_days_pred_rounded": int(round(prediction)),
        "modelo_version": bundle.get("model_version"),
        "target": bundle.get("target", "lead_time_days"),
        "metrics": sanitized_metrics,
        "historical_matches_count": total_matches,
        "historical_matches_shown": len(matches),
        "historical_matches": matches,
        "insights": {
            "historical_average_lead_time": avg_historical,
            "historical_min_lead_time": min(historical_lead_times) if historical_lead_times else None,
            "historical_max_lead_time": max(historical_lead_times) if historical_lead_times else None,
        },
    }
