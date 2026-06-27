from supabase import acreate_client
from supabase._async.client import AsyncClient
from supabase.lib.client_options import AsyncClientOptions

from app.core.config import get_settings


def _build_options(access_token: str | None = None) -> AsyncClientOptions:
    headers: dict[str, str] = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return AsyncClientOptions(
        headers=headers,
        auto_refresh_token=False,
        persist_session=False,
    )


async def create_anon_client() -> AsyncClient:
    settings = get_settings()
    return await acreate_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=_build_options(),
    )


async def create_service_role_client() -> AsyncClient:
    settings = get_settings()
    return await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=_build_options(),
    )


async def create_request_client(access_token: str) -> AsyncClient:
    settings = get_settings()
    return await acreate_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=_build_options(access_token),
    )


async def verify_supabase_connection() -> None:
    client = await create_service_role_client()
    await client.table("sedes").select("id").limit(1).execute()
