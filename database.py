"""
database.py — Dos clientes de base de datos:
  1. supabase_client()  → cliente supabase-py  (auth + CRUD simple)
  2. get_db_pool()      → pool asyncpg         (SQL complejo / RNS)
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio

import asyncpg
from supabase import create_client, Client
from loguru import logger
from config import get_settings

_settings = get_settings()

# ── 1. Supabase client (singleton) ─────────────────────────────
def supabase_client() -> Client:
    """Cliente PostgREST + Auth de Supabase."""
    return create_client(_settings.supabase_url, _settings.supabase_anon_key)


def supabase_admin() -> Client:
    """Cliente con service_key — omite RLS. Usar solo en endpoints internos."""
    return create_client(_settings.supabase_url, _settings.supabase_service_key)


# ── 2. asyncpg pool (inicializado en startup) ──────────────────
_pool: asyncpg.Pool | None = None


async def init_db_pool():
    global _pool
    # ⚠️ TEMPORAL: Deshabilitado debido a problema de DNS con asyncpg
    # El cliente Supabase-py funciona vía REST API (sin DNS directo)
    logger.warning("⚠️  Pool de asyncpg deshabilitado (problema DNS)")
    _pool = None
    logger.info("✓ BD inicializada (modo REST via Supabase)")


async def close_db_pool():
    if _pool:
        await _pool.close()


@asynccontextmanager
async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """Contexto para obtener una conexión del pool."""
    async with _pool.acquire() as conn:
        yield conn
