from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from typing import Any

from supabase import create_client


DEFAULT_CSV_DIR = Path(
    r"D:\Tareas UPC\9veno ciclo\TP1\TODO PARA EL PROGRAMA\NUEVA BASE DE DATOS\NUEVA BASE DE DATOS"
)

TABLE_FILES: list[tuple[str, str]] = [
    ("sedes", "sedes.csv"),
    ("categorias", "categorias.csv"),
    ("proveedores", "proveedores.csv"),
    ("repuestos", "repuestos.csv"),
    ("parametros_inventario", "parametros_inventario.csv"),
    ("inventario", "inventario.csv"),
    ("ordenes_trabajo", "ordenes_trabajo.csv"),
    ("ot_repuestos_requeridos", "ot_repuestos_requeridos.csv"),
    ("requisiciones_compra", "requisiciones_compra.csv"),
    ("pr_detalle", "pr_detalle.csv"),
    ("ordenes_compra", "ordenes_compra.csv"),
    ("oc_detalle", "oc_detalle.csv"),
    ("recepciones_oc", "recepciones_oc.csv"),
    ("movimientos_inventario", "movimientos_inventario.csv"),
    ("historial_consumo", "historial_consumo.csv"),
]

BOOL_COLUMNS = {
    "generado_automaticamente",
    "requiere_aprobacion_gerencia",
    "atendida",
}

PROFILE_REFERENCE_COLUMNS = {
    "asesor_id",
    "tecnico_id",
    "creado_por",
    "registrado_por",
    "recibido_por",
    "atendido_por",
    "aprobado_por_gerencia",
}

INT_COLUMNS = {
    "lead_time_estimado_dias",
    "volumen_compras_previas",
    "stock_minimo",
    "stock_maximo",
    "lead_time_base_dias",
    "punto_reorden_inicial",
    "cantidad",
    "vehiculo_anio",
    "cantidad_recibida",
    "cantidad_consumida",
    "cantidad_sugerida",
}

DECIMAL_COLUMNS = {
    "tasa_entrega_a_tiempo",
    "tasa_defectos",
    "precio_promedio",
    "monto_total",
    "precio_unitario",
    "confianza_ml",
    "demanda_proyectada",
    "lead_time_estimado_dias",
}


def env_value(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise SystemExit(f"Falta la variable de entorno {name}.")
    return value


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def normalize_value(column: str, value: str | None) -> Any:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None

    lower = cleaned.lower()
    if column in BOOL_COLUMNS:
        if lower in {"true", "t", "1", "yes", "y"}:
            return True
        if lower in {"false", "f", "0", "no", "n"}:
            return False
    if column in INT_COLUMNS:
        try:
            return int(cleaned)
        except ValueError:
            return cleaned
    if column in DECIMAL_COLUMNS:
        return cleaned
    return cleaned


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            row = {column: normalize_value(column, value) for column, value in raw_row.items()}
            rows.append(row)
        return rows


def order_categories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = [row for row in rows if not row.get("categoria_padre_id")]
    children = [row for row in rows if row.get("categoria_padre_id")]
    return parents + children


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_inventory_buffer_map(movement_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    buffer_map: dict[tuple[str, str], int] = defaultdict(int)
    for row in movement_rows:
        repuesto_id = row.get("repuesto_id")
        sede_id = row.get("sede_id")
        cantidad = row.get("cantidad")
        if not repuesto_id or not sede_id or cantidad in {None, ""}:
            continue
        try:
            qty = abs(int(cantidad))
        except (TypeError, ValueError):
            continue
        buffer_map[(str(repuesto_id), str(sede_id))] += qty
    return buffer_map


def build_movement_balance_map(movement_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    balance_map: dict[tuple[str, str], int] = defaultdict(int)
    sign_map = {
        "ajuste_positivo": 1,
        "entrada_compra": 1,
        "transferencia": 1,
        "salida_consumo": -1,
        "ajuste_negativo": -1,
    }
    for row in movement_rows:
        repuesto_id = row.get("repuesto_id")
        sede_id = row.get("sede_id")
        cantidad = row.get("cantidad")
        if not repuesto_id or not sede_id or cantidad in {None, ""}:
            continue
        try:
            qty = int(cantidad)
        except (TypeError, ValueError):
            continue
        sign = sign_map.get(str(row.get("tipo") or ""), 0)
        balance_map[(str(repuesto_id), str(sede_id))] += qty * sign
    return balance_map


def apply_inventory_buffer(
    inventory_rows: list[dict[str, Any]],
    buffer_map: dict[tuple[str, str], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    buffered_rows: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []
    for row in inventory_rows:
        final_rows.append(dict(row))
        key = (str(row.get("repuesto_id")), str(row.get("sede_id")))
        buffer_amount = buffer_map.get(key, 0)
        buffered_row = dict(row)
        try:
            buffered_row["stock_actual"] = int(buffered_row.get("stock_actual") or 0) + buffer_amount
        except (TypeError, ValueError):
            pass
        buffered_rows.append(buffered_row)
    return buffered_rows, final_rows


def create_synthetic_inventory_rows(
    movement_rows: list[dict[str, Any]],
    existing_pairs: set[tuple[str, str]],
    buffer_map: dict[tuple[str, str], int],
    balance_map: dict[tuple[str, str], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now_iso = datetime.now(timezone.utc).isoformat()
    buffered_rows: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []
    for pair, buffer_amount in buffer_map.items():
        if pair in existing_pairs:
            continue
        repuesto_id, sede_id = pair
        synthetic_id = str(uuid5(NAMESPACE_URL, f"inventario:{repuesto_id}:{sede_id}"))
        final_stock = balance_map.get(pair, 0)
        if final_stock < 0:
            print(
                f"[WARN] El saldo historico calculado para {repuesto_id} / {sede_id} es negativo ({final_stock}); "
                "se ajustara a 0 para respetar la constraint."
            )
            final_stock = 0
        buffered_rows.append(
            {
                "id": synthetic_id,
                "repuesto_id": repuesto_id,
                "sede_id": sede_id,
                "stock_actual": max(final_stock + buffer_amount, buffer_amount),
                "updated_at": now_iso,
            }
        )
        final_rows.append(
            {
                "id": synthetic_id,
                "repuesto_id": repuesto_id,
                "sede_id": sede_id,
                "stock_actual": final_stock,
                "updated_at": now_iso,
            }
        )
    return buffered_rows, final_rows


def collect_foreign_key_ids(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    referenced: dict[str, set[str]] = defaultdict(set)

    for row in rows_by_table.get("categorias", []):
        if row.get("categoria_padre_id"):
            referenced["categorias"].add(str(row["categoria_padre_id"]))

    for table in ("proveedores", "repuestos", "parametros_inventario", "inventario", "ordenes_trabajo", "ot_repuestos_requeridos",
                  "requisiciones_compra", "pr_detalle", "ordenes_compra", "oc_detalle", "recepciones_oc", "movimientos_inventario",
                  "historial_consumo"):
        for row in rows_by_table.get(table, []):
            for key in row:
                if key.endswith("_id") and row.get(key) not in {None, ""} and key not in {"id"}:
                    # Only collect simple UUID refs; skip monetary/numeric columns like model ids not used here.
                    referenced_key = key.replace("_id", "")
                    if referenced_key in {
                        "categoria",
                        "sede",
                        "repuesto",
                        "ot",
                        "pr",
                        "oc",
                        "rfq",
                        "proveedor",
                        "asesor",
                        "tecnico",
                        "creado_por",
                        "registrado_por",
                        "recibido_por",
                        "aprobado_por_gerencia",
                        "atendido_por",
                    }:
                        referenced[referenced_key].add(str(row[key]))

    return referenced


def validate_referenced_profiles(client, rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
    candidate_ids: set[str] = set()
    for table in ("ordenes_trabajo", "requisiciones_compra", "movimientos_inventario", "recepciones_oc"):
        for row in rows_by_table.get(table, []):
            for key in ("asesor_id", "tecnico_id", "creado_por", "registrado_por", "recibido_por"):
                if row.get(key):
                    candidate_ids.add(str(row[key]))

    if not candidate_ids:
        return

    existing = set()
    for batch in chunked([{"id": value} for value in sorted(candidate_ids)], 100):
        ids = [item["id"] for item in batch]
        response = client.table("perfiles").select("id").in_("id", ids).execute()
        existing.update(row["id"] for row in response.data or [])

    missing = sorted(candidate_ids - existing)
    if missing:
        raise SystemExit(
            "Faltan perfiles en Supabase para estos IDs referenciados por los CSV:\n"
            + "\n".join(f" - {value}" for value in missing)
            + "\nCarga o crea esos perfiles antes de ejecutar el importador."
        )


def pick_fallback_profile(client) -> tuple[str, Any]:
    response = client.auth.admin.list_users(page=1, per_page=200)
    users = response if isinstance(response, list) else getattr(response, "users", [])
    if not users:
        raise SystemExit("No se encontraron usuarios en auth.users para usar como fallback de perfiles.")

    preferred_emails = {"superadmin@calead.pe"}
    for user in users:
        if getattr(user, "email", None) in preferred_emails:
            return str(user.id), user

    return str(users[0].id), users[0]


def remap_missing_profile_references(
    rows_by_table: dict[str, list[dict[str, Any]]],
    missing_profile_ids: set[str],
    fallback_profile_id: str,
) -> int:
    if not missing_profile_ids:
        return 0

    remapped = 0
    for rows in rows_by_table.values():
        for row in rows:
            for column in PROFILE_REFERENCE_COLUMNS:
                if row.get(column) and str(row[column]) in missing_profile_ids:
                    row[column] = fallback_profile_id
                    remapped += 1
    return remapped


TABLE_CONFLICT_KEYS = {
    "parametros_inventario": "repuesto_id,sede_id",
    "inventario": "repuesto_id,sede_id",
}


def upsert_rows(
    client,
    table: str,
    rows: list[dict[str, Any]],
    batch_size: int = 500,
    on_conflict: str = "id",
) -> int:
    total = 0
    for batch in chunked(rows, batch_size):
        response = client.table(table).upsert(batch, on_conflict=on_conflict).execute()
        total += len(response.data or batch)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa los CSV reales de la nueva base de datos a Supabase.")
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR, help="Ruta a la carpeta que contiene los CSV.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Archivo .env con credenciales de Supabase.")
    parser.add_argument("--batch-size", type=int, default=500, help="Tamano de lote para upserts.")
    parser.add_argument("--dry-run", action="store_true", help="Solo valida y muestra resumen sin insertar.")
    args = parser.parse_args()

    load_env_file(args.env_file)
    supabase_url = env_value("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    if not supabase_key:
        raise SystemExit("Falta SUPABASE_SERVICE_ROLE_KEY o SUPABASE_SECRET_KEY en el entorno.")

    csv_dir: Path = args.csv_dir
    if not csv_dir.exists():
        raise SystemExit(f"No existe la carpeta de CSV: {csv_dir}")

    client = create_client(supabase_url, supabase_key)

    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for table, filename in TABLE_FILES:
        csv_path = csv_dir / filename
        if not csv_path.exists():
            print(f"[WARN] No existe {filename}, se omite.")
            continue
        rows = read_csv_rows(csv_path)
        if table == "categorias":
            rows = order_categories(rows)
        rows_by_table[table] = rows
        print(f"[OK] {table}: {len(rows)} filas leidas.")

    final_inventory_rows: list[dict[str, Any]] | None = None
    if "inventario" in rows_by_table and "movimientos_inventario" in rows_by_table:
        inventory_pairs = {
            (str(row.get("repuesto_id")), str(row.get("sede_id")))
            for row in rows_by_table["inventario"]
            if row.get("repuesto_id") and row.get("sede_id")
        }
        buffer_map = build_inventory_buffer_map(rows_by_table["movimientos_inventario"])
        balance_map = build_movement_balance_map(rows_by_table["movimientos_inventario"])
        rows_by_table["inventario"], final_inventory_rows = apply_inventory_buffer(
            rows_by_table["inventario"],
            buffer_map,
        )
        synthetic_buffer_rows, synthetic_final_rows = create_synthetic_inventory_rows(
            rows_by_table["movimientos_inventario"],
            inventory_pairs,
            buffer_map,
            balance_map,
        )
        if synthetic_buffer_rows:
            rows_by_table["inventario"].extend(synthetic_buffer_rows)
            if final_inventory_rows is not None:
                final_inventory_rows.extend(synthetic_final_rows)
            print(
                f"[WARN] Se agregaron {len(synthetic_buffer_rows)} filas temporales de inventario faltantes "
                "para soportar movimientos historicos."
            )
        print(f"[WARN] Se aplico un colchon temporal al inventario para importar movimientos historicos.")

    candidate_ids: set[str] = set()
    for table in ("ordenes_trabajo", "requisiciones_compra", "movimientos_inventario", "recepciones_oc"):
        for row in rows_by_table.get(table, []):
            for key in PROFILE_REFERENCE_COLUMNS:
                if row.get(key):
                    candidate_ids.add(str(row[key]))

    existing_profile_ids: set[str] = set()
    if candidate_ids:
        for batch in chunked([{"id": value} for value in sorted(candidate_ids)], 100):
            ids = [item["id"] for item in batch]
            response = client.table("perfiles").select("id").in_("id", ids).execute()
            existing_profile_ids.update(row["id"] for row in response.data or [])

    missing_profile_ids = candidate_ids - existing_profile_ids
    if missing_profile_ids:
        fallback_profile_id, fallback_user = pick_fallback_profile(client)
        remapped = remap_missing_profile_references(rows_by_table, missing_profile_ids, fallback_profile_id)
        print(
            "[WARN] Se remapearon referencias de perfiles faltantes al usuario "
            f"{fallback_profile_id}. Celdas actualizadas: {remapped}."
        )
        if fallback_profile_id not in existing_profile_ids:
            email = getattr(fallback_user, "email", None) or f"{fallback_profile_id[:8]}@import.local"
            metadata = getattr(fallback_user, "user_metadata", {}) or {}
            nombres = metadata.get("nombres") or "Importado"
            apellidos = metadata.get("apellidos") or "CSV"
            rol = metadata.get("rol") or "administrador"
            client.table("perfiles").upsert(
                {
                    "id": fallback_profile_id,
                    "nombres": nombres,
                    "apellidos": apellidos,
                    "email": email,
                    "rol": rol,
                    "sede_id": None,
                    "estado": "activo",
                    "telefono": None,
                },
                on_conflict="id",
            ).execute()
            print(f"[WARN] Se aseguró el perfil fallback {fallback_profile_id} en Supabase.")
    else:
        print("[OK] Todas las referencias a perfiles ya existen en Supabase.")

    validate_referenced_profiles(client, rows_by_table)

    if args.dry_run:
        print("Dry run completado. No se insertaron datos.")
        return 0

    summary: dict[str, int] = {}
    for table, _filename in TABLE_FILES:
        rows = rows_by_table.get(table, [])
        if not rows:
            continue
        inserted = upsert_rows(
            client,
            table,
            rows,
            batch_size=args.batch_size,
            on_conflict=TABLE_CONFLICT_KEYS.get(table, "id"),
        )
        summary[table] = inserted
        print(f"[DONE] {table}: {inserted} filas procesadas.")

    if final_inventory_rows:
        restored = upsert_rows(
            client,
            "inventario",
            final_inventory_rows,
            batch_size=args.batch_size,
            on_conflict=TABLE_CONFLICT_KEYS["inventario"],
        )
        summary["inventario"] = restored
        print(f"[DONE] inventario restaurado al stock final: {restored} filas procesadas.")

    print("\nImportacion completada.")
    for table, count in summary.items():
        print(f" - {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
