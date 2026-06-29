from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import unicodedata
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
    ("perfiles", "perfiles.csv"),
    ("proveedores", "proveedores.csv"),
    ("repuestos", "repuestos.csv"),
    ("parametros_inventario", "parametros_inventario.csv"),
    ("inventario", "inventario.csv"),
    ("ordenes_trabajo", "ordenes_trabajo.csv"),
    ("diagnosticos_ot", "diagnosticos_ot.csv"),
    ("ot_repuestos_requeridos", "ot_repuestos_requeridos.csv"),
    ("requisiciones_compra", "requisiciones_compra.csv"),
    ("pr_detalle", "pr_detalle.csv"),
    ("ordenes_compra", "ordenes_compra.csv"),
    ("oc_detalle", "oc_detalle.csv"),
    ("recepciones_oc", "recepciones_oc.csv"),
    ("recepciones_oc_detalle", "recepciones_oc_detalle.csv"),
    ("ordenes_venta", "ordenes_venta.csv"),
    ("ordenes_venta_detalle", "ordenes_venta_detalle.csv"),
    ("movimientos_inventario", "movimientos_inventario.csv"),
    ("historial_consumo", "historial_consumo.csv"),
]

BOOL_COLUMNS = {
    "generado_automaticamente",
    "requiere_aprobacion_gerencia",
    "atendida",
}

TABLE_DECIMAL_OVERRIDES = {
    "ordenes_venta_detalle": {"cantidad"},
    "movimientos_inventario": {"cantidad"},
}

PROFILE_REFERENCE_COLUMNS = {
    "asesor_id",
    "tecnico_id",
    "creado_por",
    "registrado_por",
    "recibido_por",
    "atendido_por",
    "aprobado_por_gerencia_id",
}

PROVIDER_REFERENCE_COLUMNS = {
    "proveedor_id",
    "proveedor_seleccionado_id",
    "proveedor_sugerido_id",
}

REPUESTO_REFERENCE_COLUMNS = {
    "repuesto_id",
}

ORDER_SALE_REFERENCE_COLUMNS = {
    "orden_venta_id",
}

INT_COLUMNS = {
    "lead_time_estimado_dias",
    "volumen_compras_previas",
    "stock_actual",
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

INT_CEIL_COLUMNS = {
    "lead_time_estimado_dias",
}

DECIMAL_COLUMNS = {
    "tasa_entrega_a_tiempo",
    "tasa_defectos",
    "precio_promedio",
    "monto_total",
    "precio_unitario",
    "costo_repuestos",
    "costo_servicio",
    "costo_total",
    "subtotal",
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


def normalize_value(table: str, column: str, value: str | None) -> Any:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None

    lower = cleaned.lower()
    decimal_override = column in TABLE_DECIMAL_OVERRIDES.get(table, set())
    if column in BOOL_COLUMNS:
        if lower in {"true", "t", "1", "yes", "y"}:
            return True
        if lower in {"false", "f", "0", "no", "n"}:
            return False
    if column in INT_COLUMNS and not decimal_override:
        try:
            return int(cleaned)
        except ValueError:
            try:
                numeric_value = float(cleaned)
            except ValueError:
                return cleaned
            if column in INT_CEIL_COLUMNS:
                return math.ceil(numeric_value)
            return int(round(numeric_value))
    if column in DECIMAL_COLUMNS or decimal_override:
        return cleaned
    return cleaned


def read_csv_rows(table: str, path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            row = {column: normalize_value(table, column, value) for column, value in raw_row.items()}
            rows.append(row)
        return rows


def normalize_table_rows(table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if table == "ordenes_venta":
        for row in rows:
            estado = str(row.get("estado") or "").strip().lower()
            if estado == "emitida":
                row["estado"] = "con_costo_servicio"
    return rows


def order_categories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = [row for row in rows if not row.get("categoria_padre_id")]
    children = [row for row in rows if row.get("categoria_padre_id")]
    return parents + children


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def is_valid_email(value: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip()
    if any(ord(ch) > 127 for ch in cleaned):
        return False
    if "@" not in cleaned:
        return False
    local, _, domain = cleaned.partition("@")
    return bool(local and domain and "." in domain)


def auth_email_for_profile(row: dict[str, Any]) -> str:
    email = str(row.get("email") or "").strip()
    if is_valid_email(email):
        return email.lower()
    if "@" in email:
        normalized = unicodedata.normalize("NFKD", email).encode("ascii", "ignore").decode("ascii").strip()
        if is_valid_email(normalized):
            return normalized.lower()
    return f"import-{str(row['id'])[:8].lower()}@example.com"


def build_inventory_buffer_map(movement_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    buffer_map: dict[tuple[str, str], int] = defaultdict(int)
    for row in movement_rows:
        repuesto_id = row.get("repuesto_id")
        sede_id = row.get("sede_id")
        cantidad = row.get("cantidad")
        if not repuesto_id or not sede_id or cantidad in {None, ""}:
            continue
        try:
            qty = math.ceil(abs(float(cantidad)))
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
            qty = math.ceil(abs(float(cantidad)))
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
        final_row = dict(row)
        try:
            final_stock = int(final_row.get("stock_actual") or 0)
            final_row["stock_actual"] = max(final_stock, 0)
        except (TypeError, ValueError):
            pass
        final_rows.append(final_row)
        key = (str(row.get("repuesto_id")), str(row.get("sede_id")))
        buffer_amount = buffer_map.get(key, 0)
        buffered_row = dict(final_row)
        try:
            buffered_row["stock_actual"] = int(buffered_row.get("stock_actual") or 0) + buffer_amount
            buffered_row["stock_actual"] = max(int(buffered_row["stock_actual"]), 0)
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


def validate_referenced_profiles(
    client,
    rows_by_table: dict[str, list[dict[str, Any]]],
    imported_profile_ids: set[str] | None = None,
) -> None:
    candidate_ids: set[str] = set()
    for table in (
        "ordenes_trabajo",
        "diagnosticos_ot",
        "requisiciones_compra",
        "ordenes_compra",
        "recepciones_oc",
        "movimientos_inventario",
        "ordenes_venta",
    ):
        for row in rows_by_table.get(table, []):
            for key in PROFILE_REFERENCE_COLUMNS:
                if row.get(key):
                    candidate_ids.add(str(row[key]))

    if not candidate_ids:
        return

    existing = set()
    for batch in chunked([{"id": value} for value in sorted(candidate_ids)], 100):
        ids = [item["id"] for item in batch]
        response = client.table("perfiles").select("id").in_("id", ids).execute()
        existing.update(row["id"] for row in response.data or [])

    imported_profile_ids = imported_profile_ids or set()
    missing = sorted(candidate_ids - existing - imported_profile_ids)
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


def list_auth_users(client, per_page: int = 200) -> list[Any]:
    users: list[Any] = []
    page = 1
    while True:
        batch = client.auth.admin.list_users(page=page, per_page=per_page)
        current = batch if isinstance(batch, list) else getattr(batch, "users", [])
        if not current:
            break
        users.extend(current)
        if len(current) < per_page:
            break
        page += 1
    return users


def build_profile_id_map(client, profile_rows: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, int]]:
    profile_id_map: dict[str, str] = {}
    stats = {"created_auth_users": 0, "reused_auth_users": 0}

    auth_users = list_auth_users(client)
    auth_by_email = {
        str(getattr(user, "email", "")).strip().lower(): user
        for user in auth_users
        if getattr(user, "email", None)
    }

    for row in profile_rows:
        original_id = str(row["id"])
        auth_email = auth_email_for_profile(row)
        existing_user = auth_by_email.get(auth_email)
        if existing_user:
            profile_id_map[original_id] = str(existing_user.id)
            stats["reused_auth_users"] += 1
            continue

        random_password = f"Tmp#{uuid5(NAMESPACE_URL, original_id).hex[:20]}"
        try:
            user_response = client.auth.admin.create_user(
                {
                    "email": auth_email,
                    "password": random_password,
                    "email_confirm": True,
                    "user_metadata": {
                        "nombres": row.get("nombres"),
                        "apellidos": row.get("apellidos"),
                        "rol": row.get("rol"),
                        "legacy_profile_id": original_id,
                        "legacy_profile_email": row.get("email"),
                    },
                }
            )
        except Exception as exc:
            raise SystemExit(
                f"No se pudo crear auth user para el perfil legacy {original_id} "
                f"con email {auth_email!r}: {exc}"
            ) from exc
        created_user = getattr(user_response, "user", None)
        if not created_user:
            raise SystemExit(f"No se pudo crear auth user para el perfil legacy {original_id}.")
        auth_by_email[auth_email] = created_user
        profile_id_map[original_id] = str(created_user.id)
        stats["created_auth_users"] += 1

    return profile_id_map, stats


def remap_profile_ids(rows_by_table: dict[str, list[dict[str, Any]]], profile_id_map: dict[str, str]) -> int:
    if not profile_id_map:
        return 0

    remapped = 0
    for row in rows_by_table.get("perfiles", []):
        original_id = str(row.get("id"))
        mapped_id = profile_id_map.get(original_id)
        if mapped_id and mapped_id != original_id:
            row["id"] = mapped_id
            remapped += 1

    for table, rows in rows_by_table.items():
        if table == "perfiles":
            continue
        for row in rows:
            for column in PROFILE_REFERENCE_COLUMNS:
                value = row.get(column)
                if not value:
                    continue
                mapped_id = profile_id_map.get(str(value))
                if mapped_id and mapped_id != str(value):
                    row[column] = mapped_id
                    remapped += 1

    return remapped


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


def row_completeness_score(row: dict[str, Any]) -> tuple[int, int]:
    populated = sum(1 for value in row.values() if value not in {None, ""})
    descriptive_length = len(str(row.get("razon_social") or "")) + len(str(row.get("email") or ""))
    return populated, descriptive_length


def merge_prefer_populated(base_row: dict[str, Any], other_row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base_row)
    for key, value in other_row.items():
        if merged.get(key) in {None, ""} and value not in {None, ""}:
            merged[key] = value
    return merged


def safe_float(value: Any) -> float:
    if value in {None, ""}:
        return 0.0
    return float(value)


def compact_number(value: float) -> Any:
    if float(value).is_integer():
        return int(value)
    return str(value)


def remap_provider_references(rows_by_table: dict[str, list[dict[str, Any]]], provider_id_map: dict[str, str]) -> int:
    if not provider_id_map:
        return 0

    remapped = 0
    for table, rows in rows_by_table.items():
        if table == "proveedores":
            continue
        for row in rows:
            for column in PROVIDER_REFERENCE_COLUMNS:
                value = row.get(column)
                if not value:
                    continue
                mapped_id = provider_id_map.get(str(value))
                if mapped_id and mapped_id != str(value):
                    row[column] = mapped_id
                    remapped += 1
    return remapped


def remap_repuesto_references(rows_by_table: dict[str, list[dict[str, Any]]], repuesto_id_map: dict[str, str]) -> int:
    if not repuesto_id_map:
        return 0

    remapped = 0
    for table, rows in rows_by_table.items():
        if table == "repuestos":
            continue
        for row in rows:
            for column in REPUESTO_REFERENCE_COLUMNS:
                value = row.get(column)
                if not value:
                    continue
                mapped_id = repuesto_id_map.get(str(value))
                if mapped_id and mapped_id != str(value):
                    row[column] = mapped_id
                    remapped += 1
    return remapped


def remap_order_sale_references(rows_by_table: dict[str, list[dict[str, Any]]], order_sale_id_map: dict[str, str]) -> int:
    if not order_sale_id_map:
        return 0

    remapped = 0
    for table, rows in rows_by_table.items():
        if table == "ordenes_venta":
            continue
        for row in rows:
            for column in ORDER_SALE_REFERENCE_COLUMNS:
                value = row.get(column)
                if not value:
                    continue
                mapped_id = order_sale_id_map.get(str(value))
                if mapped_id and mapped_id != str(value):
                    row[column] = mapped_id
                    remapped += 1
    return remapped


def reconcile_proveedores(client, rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    provider_rows = rows_by_table.get("proveedores", [])
    if not provider_rows:
        return {"deduplicated": 0, "reused_existing": 0, "reference_remaps": 0}

    canonical_by_ruc: dict[str, dict[str, Any]] = {}
    provider_id_map: dict[str, str] = {}
    deduplicated = 0

    for row in provider_rows:
        ruc = str(row.get("ruc") or "").strip()
        if not ruc:
            continue
        current = canonical_by_ruc.get(ruc)
        if not current:
            canonical_by_ruc[ruc] = dict(row)
            continue

        preferred = current
        duplicate = row
        if row_completeness_score(row) > row_completeness_score(current):
            preferred = dict(row)
            duplicate = current
        canonical_by_ruc[ruc] = merge_prefer_populated(preferred, duplicate)
        provider_id_map[str(row["id"])] = str(canonical_by_ruc[ruc]["id"])
        if str(current["id"]) != str(canonical_by_ruc[ruc]["id"]):
            provider_id_map[str(current["id"])] = str(canonical_by_ruc[ruc]["id"])
        deduplicated += 1

    rucs = sorted(canonical_by_ruc.keys())
    existing_by_ruc: dict[str, dict[str, Any]] = {}
    if rucs:
        for batch in chunked([{"ruc": value} for value in rucs], 100):
            batch_rucs = [row["ruc"] for row in batch]
            response = client.table("proveedores").select("id,ruc,razon_social,email").in_("ruc", batch_rucs).execute()
            for row in response.data or []:
                if row.get("ruc"):
                    existing_by_ruc[str(row["ruc"])] = row

    reused_existing = 0
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: dict[str, dict[str, Any]] = {}

    for row in provider_rows:
        original_id = str(row["id"])
        ruc = str(row.get("ruc") or "").strip()
        canonical_id = provider_id_map.get(original_id, original_id)
        working_row = dict(row)

        if ruc and ruc in existing_by_ruc:
            existing_id = str(existing_by_ruc[ruc]["id"])
            provider_id_map[original_id] = existing_id
            canonical_id = existing_id
            reused_existing += 1

        working_row["id"] = canonical_id
        if canonical_id in seen_ids:
            seen_ids[canonical_id] = merge_prefer_populated(seen_ids[canonical_id], working_row)
            continue
        seen_ids[canonical_id] = working_row
        normalized_rows.append(working_row)

    rows_by_table["proveedores"] = normalized_rows
    reference_remaps = remap_provider_references(rows_by_table, provider_id_map)
    return {
        "deduplicated": deduplicated,
        "reused_existing": reused_existing,
        "reference_remaps": reference_remaps,
    }


def reconcile_repuestos(client, rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    repuesto_rows = rows_by_table.get("repuestos", [])
    if not repuesto_rows:
        return {"deduplicated": 0, "reused_existing": 0, "reference_remaps": 0}

    canonical_by_sku: dict[str, dict[str, Any]] = {}
    repuesto_id_map: dict[str, str] = {}
    deduplicated = 0

    for row in repuesto_rows:
        sku = str(row.get("codigo_sku") or "").strip()
        if not sku:
            continue
        current = canonical_by_sku.get(sku)
        if not current:
            canonical_by_sku[sku] = dict(row)
            continue

        preferred = current
        duplicate = row
        if row_completeness_score(row) > row_completeness_score(current):
            preferred = dict(row)
            duplicate = current
        canonical_by_sku[sku] = merge_prefer_populated(preferred, duplicate)
        repuesto_id_map[str(row["id"])] = str(canonical_by_sku[sku]["id"])
        if str(current["id"]) != str(canonical_by_sku[sku]["id"]):
            repuesto_id_map[str(current["id"])] = str(canonical_by_sku[sku]["id"])
        deduplicated += 1

    skus = sorted(canonical_by_sku.keys())
    existing_by_sku: dict[str, dict[str, Any]] = {}
    if skus:
        for batch in chunked([{"sku": value} for value in skus], 100):
            batch_skus = [row["sku"] for row in batch]
            response = client.table("repuestos").select("id,codigo_sku,nombre").in_("codigo_sku", batch_skus).execute()
            for row in response.data or []:
                if row.get("codigo_sku"):
                    existing_by_sku[str(row["codigo_sku"])] = row

    reused_existing = 0
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: dict[str, dict[str, Any]] = {}

    for row in repuesto_rows:
        original_id = str(row["id"])
        sku = str(row.get("codigo_sku") or "").strip()
        canonical_id = repuesto_id_map.get(original_id, original_id)
        working_row = dict(row)

        if sku and sku in existing_by_sku:
            existing_id = str(existing_by_sku[sku]["id"])
            repuesto_id_map[original_id] = existing_id
            canonical_id = existing_id
            reused_existing += 1

        working_row["id"] = canonical_id
        if canonical_id in seen_ids:
            seen_ids[canonical_id] = merge_prefer_populated(seen_ids[canonical_id], working_row)
            continue
        seen_ids[canonical_id] = working_row
        normalized_rows.append(working_row)

    rows_by_table["repuestos"] = normalized_rows
    reference_remaps = remap_repuesto_references(rows_by_table, repuesto_id_map)
    return {
        "deduplicated": deduplicated,
        "reused_existing": reused_existing,
        "reference_remaps": reference_remaps,
    }


def consolidate_detail_rows(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    summary = {
        "oc_detalle": 0,
        "recepciones_oc_detalle": 0,
        "ordenes_venta_detalle": 0,
    }

    oc_rows = rows_by_table.get("oc_detalle", [])
    if oc_rows:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        removed = 0
        for row in oc_rows:
            key = (str(row.get("oc_id") or ""), str(row.get("repuesto_id") or ""))
            if not all(key):
                grouped[(str(row.get("id") or ""), "")] = dict(row)
                continue
            current = grouped.get(key)
            if not current:
                grouped[key] = dict(row)
                continue
            removed += 1
            total_qty = safe_float(current.get("cantidad")) + safe_float(row.get("cantidad"))
            total_cost = (
                safe_float(current.get("cantidad")) * safe_float(current.get("precio_unitario"))
                + safe_float(row.get("cantidad")) * safe_float(row.get("precio_unitario"))
            )
            current["cantidad"] = compact_number(total_qty)
            current["precio_unitario"] = "0" if total_qty == 0 else str(total_cost / total_qty)
            grouped[key] = merge_prefer_populated(current, row)
        rows_by_table["oc_detalle"] = list(grouped.values())
        summary["oc_detalle"] = removed

    recepcion_rows = rows_by_table.get("recepciones_oc_detalle", [])
    if recepcion_rows:
        grouped = {}
        removed = 0
        for row in recepcion_rows:
            key = (str(row.get("recepcion_id") or ""), str(row.get("repuesto_id") or ""))
            if not all(key):
                grouped[(str(row.get("id") or ""), "")] = dict(row)
                continue
            current = grouped.get(key)
            if not current:
                grouped[key] = dict(row)
                continue
            removed += 1
            current["cantidad_recibida"] = compact_number(
                safe_float(current.get("cantidad_recibida")) + safe_float(row.get("cantidad_recibida"))
            )
            if str(current.get("conformidad") or "").strip() != "no_conforme":
                current["conformidad"] = row.get("conformidad") or current.get("conformidad")
            grouped[key] = merge_prefer_populated(current, row)
        rows_by_table["recepciones_oc_detalle"] = list(grouped.values())
        summary["recepciones_oc_detalle"] = removed

    ov_rows = rows_by_table.get("ordenes_venta_detalle", [])
    if ov_rows:
        grouped = {}
        removed = 0
        for row in ov_rows:
            key = (str(row.get("orden_venta_id") or ""), str(row.get("repuesto_id") or ""))
            if not all(key):
                grouped[(str(row.get("id") or ""), "")] = dict(row)
                continue
            current = grouped.get(key)
            if not current:
                grouped[key] = dict(row)
                continue
            removed += 1
            current["cantidad"] = compact_number(
                safe_float(current.get("cantidad")) + safe_float(row.get("cantidad"))
            )
            current["subtotal"] = str(safe_float(current.get("subtotal")) + safe_float(row.get("subtotal")))
            total_qty = safe_float(current.get("cantidad"))
            if total_qty > 0:
                current["precio_unitario"] = str(safe_float(current.get("subtotal")) / total_qty)
            grouped[key] = merge_prefer_populated(current, row)
        rows_by_table["ordenes_venta_detalle"] = list(grouped.values())
        summary["ordenes_venta_detalle"] = removed

    return summary


def reconcile_ordenes_venta(client, rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    sale_rows = rows_by_table.get("ordenes_venta", [])
    if not sale_rows:
        return {"deduplicated": 0, "reused_existing": 0, "reference_remaps": 0}

    canonical_by_ot: dict[str, dict[str, Any]] = {}
    order_sale_id_map: dict[str, str] = {}
    deduplicated = 0

    for row in sale_rows:
        ot_id = str(row.get("ot_id") or "").strip()
        if not ot_id:
            continue
        current = canonical_by_ot.get(ot_id)
        if not current:
            canonical_by_ot[ot_id] = dict(row)
            continue

        preferred = current
        duplicate = row
        if row_completeness_score(row) > row_completeness_score(current):
            preferred = dict(row)
            duplicate = current
        canonical_by_ot[ot_id] = merge_prefer_populated(preferred, duplicate)
        order_sale_id_map[str(row["id"])] = str(canonical_by_ot[ot_id]["id"])
        if str(current["id"]) != str(canonical_by_ot[ot_id]["id"]):
            order_sale_id_map[str(current["id"])] = str(canonical_by_ot[ot_id]["id"])
        deduplicated += 1

    ot_ids = sorted(canonical_by_ot.keys())
    existing_by_ot: dict[str, dict[str, Any]] = {}
    if ot_ids:
        for batch in chunked([{"ot_id": value} for value in ot_ids], 100):
            batch_ot_ids = [row["ot_id"] for row in batch]
            response = client.table("ordenes_venta").select("id,ot_id,codigo_ov").in_("ot_id", batch_ot_ids).execute()
            for row in response.data or []:
                if row.get("ot_id"):
                    existing_by_ot[str(row["ot_id"])] = row

    reused_existing = 0
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: dict[str, dict[str, Any]] = {}

    for row in sale_rows:
        original_id = str(row["id"])
        ot_id = str(row.get("ot_id") or "").strip()
        canonical_id = order_sale_id_map.get(original_id, original_id)
        working_row = dict(row)

        if ot_id and ot_id in existing_by_ot:
            existing_id = str(existing_by_ot[ot_id]["id"])
            order_sale_id_map[original_id] = existing_id
            canonical_id = existing_id
            reused_existing += 1

        working_row["id"] = canonical_id
        if canonical_id in seen_ids:
            seen_ids[canonical_id] = merge_prefer_populated(seen_ids[canonical_id], working_row)
            continue
        seen_ids[canonical_id] = working_row
        normalized_rows.append(working_row)

    rows_by_table["ordenes_venta"] = normalized_rows
    reference_remaps = remap_order_sale_references(rows_by_table, order_sale_id_map)
    return {
        "deduplicated": deduplicated,
        "reused_existing": reused_existing,
        "reference_remaps": reference_remaps,
    }


TABLE_CONFLICT_KEYS = {
    "parametros_inventario": "repuesto_id,sede_id",
    "inventario": "repuesto_id,sede_id",
    "oc_detalle": "oc_id,repuesto_id",
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
        try:
            response = client.table(table).upsert(batch, on_conflict=on_conflict).execute()
        except Exception as exc:
            sample_row = batch[0] if batch else {}
            raise SystemExit(
                f"Fallo el upsert de la tabla {table} con lote de {len(batch)} filas. "
                f"Primera fila del lote: {sample_row}. Error: {exc}"
            ) from exc
        total += len(response.data or batch)
    return total


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def collect_csv_id_map(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    return {
        table: {str(row["id"]) for row in rows if row.get("id")}
        for table, rows in rows_by_table.items()
    }


def delete_by_ids(client, table: str, ids: set[str], batch_size: int = 200) -> int:
    if not ids:
        return 0
    deleted = 0
    id_rows = [{"id": value} for value in sorted(ids)]
    for batch in chunked(id_rows, batch_size):
        batch_ids = [row["id"] for row in batch]
        client.table(table).delete().in_("id", batch_ids).execute()
        deleted += len(batch_ids)
    return deleted


def collect_recent_ids(client, table: str, started_at: datetime) -> set[str]:
    response = client.table(table).select("id,created_at").execute()
    collected: set[str] = set()
    for row in response.data or []:
        created_at = _parse_iso_datetime(row.get("created_at"))
        if created_at and created_at >= started_at and row.get("id"):
            collected.add(str(row["id"]))
    return collected


def cleanup_trigger_side_effects(
    client,
    rows_by_table: dict[str, list[dict[str, Any]]],
    import_started_at: datetime,
) -> dict[str, int]:
    csv_id_map = collect_csv_id_map(rows_by_table)
    summary: dict[str, int] = {}

    recent_alert_ids = collect_recent_ids(client, "alertas", import_started_at)
    deleted_alerts = delete_by_ids(client, "alertas", recent_alert_ids)
    if deleted_alerts:
        summary["alertas_auto"] = deleted_alerts

    recent_pr_ids = collect_recent_ids(client, "requisiciones_compra", import_started_at)
    expected_pr_ids = csv_id_map.get("requisiciones_compra", set())
    extra_pr_ids = recent_pr_ids - expected_pr_ids
    if extra_pr_ids:
        pr_detail_response = client.table("pr_detalle").select("id,pr_id").in_("pr_id", sorted(extra_pr_ids)).execute()
        pr_detail_ids = {str(row["id"]) for row in pr_detail_response.data or [] if row.get("id")}
        deleted_pr_detail = delete_by_ids(client, "pr_detalle", pr_detail_ids)
        deleted_prs = delete_by_ids(client, "requisiciones_compra", extra_pr_ids)
        if deleted_pr_detail:
            summary["pr_detalle_auto"] = deleted_pr_detail
        if deleted_prs:
            summary["requisiciones_auto"] = deleted_prs

    recent_movement_ids = collect_recent_ids(client, "movimientos_inventario", import_started_at)
    expected_movement_ids = csv_id_map.get("movimientos_inventario", set())
    extra_movement_ids = recent_movement_ids - expected_movement_ids
    deleted_movements = delete_by_ids(client, "movimientos_inventario", extra_movement_ids)
    if deleted_movements:
        summary["movimientos_auto"] = deleted_movements

    return summary


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
        rows = read_csv_rows(table, csv_path)
        if table == "categorias":
            rows = order_categories(rows)
        rows = normalize_table_rows(table, rows)
        rows_by_table[table] = rows
        print(f"[OK] {table}: {len(rows)} filas leidas.")

    if rows_by_table.get("perfiles"):
        profile_id_map, auth_stats = build_profile_id_map(client, rows_by_table["perfiles"])
        remapped_profiles = remap_profile_ids(rows_by_table, profile_id_map)
        print(
            "[OK] Auth users sincronizados para perfiles: "
            f"{auth_stats['created_auth_users']} creados, {auth_stats['reused_auth_users']} reutilizados."
        )
        if remapped_profiles:
            print(f"[WARN] Se remapearon {remapped_profiles} referencias de perfiles al UUID real de auth.users.")

    provider_stats = reconcile_proveedores(client, rows_by_table)
    if provider_stats["deduplicated"] or provider_stats["reused_existing"] or provider_stats["reference_remaps"]:
        print(
            "[OK] Proveedores reconciliados: "
            f"{provider_stats['deduplicated']} duplicados internos, "
            f"{provider_stats['reused_existing']} reutilizados desde Supabase, "
            f"{provider_stats['reference_remaps']} referencias remapeadas."
        )

    repuesto_stats = reconcile_repuestos(client, rows_by_table)
    if repuesto_stats["deduplicated"] or repuesto_stats["reused_existing"] or repuesto_stats["reference_remaps"]:
        print(
            "[OK] Repuestos reconciliados: "
            f"{repuesto_stats['deduplicated']} duplicados internos, "
            f"{repuesto_stats['reused_existing']} reutilizados desde Supabase, "
            f"{repuesto_stats['reference_remaps']} referencias remapeadas."
        )

    sale_stats = reconcile_ordenes_venta(client, rows_by_table)
    if sale_stats["deduplicated"] or sale_stats["reused_existing"] or sale_stats["reference_remaps"]:
        print(
            "[OK] Ordenes de venta reconciliadas: "
            f"{sale_stats['deduplicated']} duplicados internos, "
            f"{sale_stats['reused_existing']} reutilizadas desde Supabase, "
            f"{sale_stats['reference_remaps']} referencias remapeadas."
        )

    detail_stats = consolidate_detail_rows(rows_by_table)
    if any(detail_stats.values()):
        print(
            "[OK] Detalles consolidados: "
            f"oc_detalle={detail_stats['oc_detalle']}, "
            f"recepciones_oc_detalle={detail_stats['recepciones_oc_detalle']}, "
            f"ordenes_venta_detalle={detail_stats['ordenes_venta_detalle']}."
        )

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

    imported_profile_ids = {str(row["id"]) for row in rows_by_table.get("perfiles", []) if row.get("id")}

    candidate_ids: set[str] = set()
    for table in (
        "ordenes_trabajo",
        "diagnosticos_ot",
        "requisiciones_compra",
        "ordenes_compra",
        "recepciones_oc",
        "movimientos_inventario",
        "ordenes_venta",
    ):
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

    missing_profile_ids = candidate_ids - existing_profile_ids - imported_profile_ids
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

    validate_referenced_profiles(client, rows_by_table, imported_profile_ids=imported_profile_ids)

    if args.dry_run:
        print("Dry run completado. No se insertaron datos.")
        return 0

    import_started_at = datetime.now(timezone.utc)
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

    cleanup_summary = cleanup_trigger_side_effects(client, rows_by_table, import_started_at)
    for key, count in cleanup_summary.items():
        summary[key] = count
        print(f"[CLEANUP] {key}: {count} filas eliminadas.")

    print("\nImportacion completada.")
    for table, count in summary.items():
        print(f" - {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
