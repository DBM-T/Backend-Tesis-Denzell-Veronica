from app.core.config import get_settings
from app.core.supabase_client import verify_supabase_connection
from app.schemas.health import HealthResponse


async def build_health_response(*, verify_connection: bool = True) -> HealthResponse:
    if verify_connection:
        await verify_supabase_connection()
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        supabase="connected",
    )
