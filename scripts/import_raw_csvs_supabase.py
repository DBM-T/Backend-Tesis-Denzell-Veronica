"""Importa los CSV de data/raw a Supabase REST, excluyendo dataset_lead_time.csv."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_settings

RAW_DIR = BASE_DIR / "data" / "raw"

IMPORT_ORDER = [
    ("sedes", "sedes.csv"),
    ("clientes", "clientes.csv"),
    ("categorias_producto", "categorias_producto.csv"),
    ("productos", "productos.csv"),
    ("proveedores", "proveedores.csv"),
    ("vehiculos", "vehiculos.csv"),
    ("citas", "citas.csv"),
    ("ordenes_trabajo", "ordenes_trabajo.csv"),
    ("requisiciones_compra", "requisiciones_compra.csv"),
    ("ordenes_compra", "ordenes_compra.csv"),
    ("oc_lineas", "oc_lineas.csv"),
    ("recepciones", "recepciones.csv"),
    ("ot_lineas", "ot_lineas.csv"),
    ("stock", "stock.csv"),
    ("stock_movimientos", "stock_movimientos.csv"),
    ("requisicion_lineas", "requisicion_lineas.csv"),
    ("catalogo_precios", "catalogo_precios.csv"),
    ("historial_consumo", "historial_consumo.csv"),
]

BOOL_COLUMNS = {
    "activo",
    "activa",
    "adelanto_20pct",
    "es_adicional",
    "is_storable",
    "is_active",
    "homologado",
    "params_ml",
}

INT_COLUMNS = {
    "anio",
    "kilometraje",
    "tiempo_entrega_promedio_dias",
}

DECIMAL_COLUMNS = {
    "precio_costo",
    "monto_adelanto",
    "precio_referencia",
    "qty_consumida",
    "qty_pedida",
    "qty_recibida",
    "precio_unitario",
    "subtotal_linea",
    "qty",
    "qty_disponible",
    "qty_reservada",
    "qty_en_transito",
    "stock_min",
    "stock_max",
    "stock_seguridad",
    "rop",
    "qty_antes",
    "qty_despues",
    "qty_solicitada",
    "qty_aprobada",
    "precio_estimado",
    "subtotal",
}

USER_REF_COLUMNS = {
    "asesor_id",
    "created_by",
    "tecnico_id",
    "solicitado_por",
    "aprobado_por",
    "creado_por",
    "revisado_por",
}

BATCH_SIZE = 250

TABLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "stock": {
        "qty_disponible": 0.0,
        "qty_reservada": 0.0,
        "qty_en_transito": 0.0,
        "stock_min": 0.0,
        "stock_seguridad": 0.0,
        "params_ml": False,
    }
}


class SupabaseRestClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/") + "/rest/v1"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
            }
        )

    def fetch(self, table: str, select: str, limit: int = 1000) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}/{table}",
            params={"select": select, "limit": limit},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def upsert_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        response = self.session.post(
            f"{self.base_url}/{table}",
            params={"on_conflict": "id"},
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
                "Content-Type": "application/json",
            },
            json=rows,
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Error importando {table}: HTTP {response.status_code} - {response.text}"
            )


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"t", "true", "1", "yes", "y"}:
        return True
    if normalized in {"f", "false", "0", "no", "n"}:
        return False
    raise ValueError(f"Valor booleano no reconocido: {value!r}")


def parse_decimal(value: str) -> float:
    decimal_value = Decimal(value)
    if decimal_value.is_nan():
        return None  # type: ignore[return-value]
    return float(decimal_value)


def normalize_value(column: str, value: str) -> Any:
    value = value.strip()
    if value == "":
        return None

    if column in BOOL_COLUMNS:
        return parse_bool(value)

    if column in INT_COLUMNS:
        return int(value)

    if column in DECIMAL_COLUMNS:
        try:
            return parse_decimal(value)
        except InvalidOperation:
            return value

    return value


def read_csv_rows(file_path: Path) -> list[dict[str, Any]]:
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {column: normalize_value(column, value or "") for column, value in row.items()}
            for row in reader
        ]


def apply_table_defaults(table: str, rows: list[dict[str, Any]]) -> None:
    defaults = TABLE_DEFAULTS.get(table, {})
    if not defaults:
        return

    for row in rows:
        for column, default_value in defaults.items():
            if row.get(column) is None:
                row[column] = default_value


def find_existing_user_mapping(client: SupabaseRestClient) -> tuple[set[str], str | None]:
    users = client.fetch("usuarios", "id,nombre_completo,email", limit=1000)
    existing_ids = {user["id"] for user in users}
    fallback_user_id = users[0]["id"] if len(users) == 1 else None
    return existing_ids, fallback_user_id


def remap_user_refs(
    table: str,
    rows: list[dict[str, Any]],
    existing_user_ids: set[str],
    fallback_user_id: str | None,
) -> int:
    remapped = 0
    for row in rows:
        for column in USER_REF_COLUMNS:
            if column not in row:
                continue
            value = row[column]
            if value is None or value in existing_user_ids:
                continue
            if fallback_user_id is None:
                raise RuntimeError(
                    f"La tabla {table} referencia usuarios inexistentes y no hay un usuario "
                    "unico disponible para remapear automaticamente."
                )
            row[column] = fallback_user_id
            remapped += 1
    return remapped


def chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def import_rows_with_retry(
    client: SupabaseRestClient, table: str, rows: list[dict[str, Any]]
) -> None:
    failures: list[tuple[str | None, str]] = []
    for batch in chunked(rows, BATCH_SIZE):
        try:
            client.upsert_batch(table, batch)
            continue
        except Exception:
            pass

        for mini_batch in chunked(batch, 25):
            try:
                client.upsert_batch(table, mini_batch)
                continue
            except Exception:
                pass

            for row in mini_batch:
                try:
                    client.upsert_batch(table, [row])
                except Exception as exc:
                    failures.append((row.get("id"), str(exc)))

    if failures:
        details = "\n".join(
            f"- {row_id or 'sin id'}: {message}" for row_id, message in failures[:10]
        )
        raise RuntimeError(
            f"Fallaron {len(failures)} filas al importar {table}.\n{details}"
        )


def main() -> None:
    settings = get_settings()
    client = SupabaseRestClient(settings.supabase_url, settings.supabase_secret_key)
    existing_user_ids, fallback_user_id = find_existing_user_mapping(client)

    imported_counts: dict[str, int] = {}
    remap_counts: defaultdict[str, int] = defaultdict(int)

    for table, filename in IMPORT_ORDER:
        csv_path = RAW_DIR / filename
        rows = read_csv_rows(csv_path)
        apply_table_defaults(table, rows)

        remap_counts[table] = remap_user_refs(
            table, rows, existing_user_ids, fallback_user_id
        )

        import_rows_with_retry(client, table, rows)

        imported_counts[table] = len(rows)
        print(
            f"{table}: {len(rows)} filas importadas"
            + (
                f" ({remap_counts[table]} referencias de usuario remapeadas)"
                if remap_counts[table]
                else ""
            )
        )

    print("\nResumen:")
    for table, _filename in IMPORT_ORDER:
        print(f"- {table}: {imported_counts[table]} filas")

    print("\nNo se importo: dataset_lead_time.csv")


if __name__ == "__main__":
    main()
