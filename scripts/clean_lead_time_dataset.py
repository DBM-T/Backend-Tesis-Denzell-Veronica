"""Limpia y perfila el dataset de lead time para entrenamiento."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from services.lead_time_model_service import build_lead_time_feature_frame

TARGET_COLUMN = "lead_time_days"


def clean_lead_time_dataset(input_path: Path, output_path: Path) -> dict:
    df = pd.read_csv(input_path)
    rows_in = len(df)

    for column in ["date_order", "date_approve", "date_planned", "effective_date"]:
        df[column] = pd.to_datetime(df[column], errors="coerce")

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
        "lead_time_days",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["category"] = df["category"].fillna("SIN_CATEGORIA")
    df["is_storable"] = df["is_storable"].fillna("f")
    df["is_child_sku"] = df["is_child_sku"].fillna("f")

    invalid_target_mask = df[TARGET_COLUMN].isna() | (df[TARGET_COLUMN] < 0)
    invalid_date_mask = df["date_order"].isna() | df["date_approve"].isna()
    rows_dropped = int((invalid_target_mask | invalid_date_mask).sum())
    df = df.loc[~(invalid_target_mask | invalid_date_mask)].copy()

    features = build_lead_time_feature_frame(df)
    df["approve_hour"] = features["approve_hour"]
    df["approval_lag_hours"] = features["approval_lag_hours"]
    df["planned_gap_days"] = features["planned_gap_days"]
    df["is_storable_num"] = features["is_storable_num"]
    df["is_child_sku_num"] = features["is_child_sku_num"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    report = {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "rows_in": rows_in,
        "rows_out": int(len(df)),
        "rows_dropped": rows_dropped,
        "columns_in": list(df.columns),
        "target": TARGET_COLUMN,
        "target_summary": {
            "min": float(df[TARGET_COLUMN].min()),
            "max": float(df[TARGET_COLUMN].max()),
            "mean": float(df[TARGET_COLUMN].mean()),
            "median": float(df[TARGET_COLUMN].median()),
            "std": float(df[TARGET_COLUMN].std()),
        },
        "target_distribution": {
            "0_days": int((df[TARGET_COLUMN] == 0).sum()),
            "1_day": int((df[TARGET_COLUMN] == 1).sum()),
            "2_days": int((df[TARGET_COLUMN] == 2).sum()),
            "3_days": int((df[TARGET_COLUMN] == 3).sum()),
            "4_plus_days": int((df[TARGET_COLUMN] >= 4).sum()),
        },
        "missing_after_cleaning": {
            column: int(value)
            for column, value in df.isna().sum().items()
            if int(value) > 0
        },
    }
    report_path = output_path.with_name(f"{output_path.stem}_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Ruta al CSV crudo")
    parser.add_argument("--output", required=True, help="Ruta del CSV limpio")
    args = parser.parse_args()

    report = clean_lead_time_dataset(Path(args.input), Path(args.output))
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
