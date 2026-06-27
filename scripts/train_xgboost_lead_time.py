"""Entrena el modelo XGBoost de lead time usando dataset_lead_time.csv y datos reales."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.lead_time_training_service import train_lead_time_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        nargs="+",
        help="Una o varias rutas CSV para entrenar el modelo",
    )
    parser.add_argument(
        "--model-output",
        required=True,
        help="Ruta donde se guardara el modelo .joblib",
    )
    parser.add_argument(
        "--dataset-output",
        help="Ruta donde se guardara el dataset enriquecido usado por el modelo",
    )
    parser.add_argument(
        "--skip-supabase-register",
        action="store_true",
        help="No registra la nueva version en la tabla ml_modelos",
    )
    args = parser.parse_args()

    metrics = train_lead_time_model(
        input_path=[Path(path) for path in args.input],
        model_output=Path(args.model_output),
        dataset_output=Path(args.dataset_output) if args.dataset_output else None,
        register_in_supabase=not args.skip_supabase_register,
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
