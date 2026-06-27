from app.core.config import get_settings
from app.core.supabase_client import verify_supabase_connection
from app.schemas.health import HealthResponse


async def build_health_response() -> HealthResponse:
    await verify_supabase_connection()
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        supabase="connected",
    )
