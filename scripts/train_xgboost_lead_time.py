"""Entrena un modelo XGBoost para predecir lead time en dias."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

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

from services.lead_time_model_service import (
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    build_lead_time_feature_frame,
)

TARGET_COLUMN = "lead_time_days"


def _make_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ),
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


def train_lead_time_model(input_path: Path, model_output: Path) -> dict:
    df = pd.read_csv(input_path, parse_dates=["date_order", "date_approve", "date_planned"])
    if TARGET_COLUMN not in df.columns:
        raise RuntimeError(f"El dataset no contiene la columna target '{TARGET_COLUMN}'")

    X = build_lead_time_feature_frame(df)
    y = pd.to_numeric(df[TARGET_COLUMN], errors="coerce").fillna(0.0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

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
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(df)),
        "source_input": str(input_path),
        "hyperparameters": final_pipeline.named_steps["model"].get_xgb_params(),
    }

    model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_output)

    metrics_report = {
        **metrics,
        "model_version": model_version,
        "target": TARGET_COLUMN,
        "rows_total": int(len(df)),
        "rows_train": int(len(X_train)),
        "rows_test": int(len(X_test)),
        "feature_columns": MODEL_FEATURES,
        "hyperparameters": bundle["hyperparameters"],
    }
    metrics_path = model_output.with_name(f"{model_output.stem}_metrics.json")
    metrics_path.write_text(
        json.dumps(metrics_report, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return metrics_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Ruta al CSV limpio")
    parser.add_argument(
        "--model-output",
        required=True,
        help="Ruta donde se guardara el modelo .joblib",
    )
    args = parser.parse_args()

    metrics = train_lead_time_model(Path(args.input), Path(args.model_output))
    print(json.dumps(metrics, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
