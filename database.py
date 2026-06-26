"""Clientes de base de datos para Supabase y PostgreSQL directo."""
from contextlib import asynccontextmanager
import json
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
from supabase import create_client, Client
from loguru import logger
from config import get_settings

_settings = get_settings()
_pool: asyncpg.Pool | None = None


def supabase_client() -> Client:
    """Cliente PostgREST + Auth de Supabase."""
    return create_client(_settings.supabase_url, _settings.supabase_publishable_key)


def supabase_admin() -> Client:
    """Cliente con service_key. Omite RLS; usar solo en endpoints internos."""
    return create_client(_settings.supabase_url, _settings.supabase_secret_key)


async def init_db_pool():
    global _pool
    if _pool:
        return

    database_url, ssl = _normalize_asyncpg_url(_settings.database_url)
    try:
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
            ssl=ssl,
            init=_setup_connection,
        )
        logger.info("BD inicializada con pool asyncpg")
    except Exception as exc:
        _pool = None
        logger.warning(
            f"No se pudo inicializar asyncpg; la API continuara con Supabase REST: {exc}"
        )


async def close_db_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """Contexto para obtener una conexion del pool."""
    if _pool is None:
        raise RuntimeError("El pool de base de datos no esta inicializado")
    async with _pool.acquire() as conn:
        yield conn


def _normalize_asyncpg_url(database_url: str) -> tuple[str, str | bool | None]:
    """asyncpg no entiende sslmode como libpq; lo convertimos a ssl."""
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    normalized_url = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
    ssl: str | bool | None = (
        "require" if sslmode in {"require", "verify-ca", "verify-full"} else None
    )
    return normalized_url, ssl


async def _setup_connection(conn: asyncpg.Connection):
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )
