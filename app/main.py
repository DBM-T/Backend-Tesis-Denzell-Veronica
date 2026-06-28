from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestContextLoggingMiddleware, setup_logging
from app.core.scheduler import start_scheduler, stop_scheduler
from app.ml.inference.runtime import preload_active_models
from app.routers import alertas, auth, compras, maestros, ml, ordenes_trabajo, reportes, usuarios, ventas
from app.schemas.health import HealthResponse
from app.services.health_service import build_health_response


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    await preload_active_models()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="CALEAND SAC Backend",
    description=(
        "API del sistema de gestion de abastecimiento para CALEAND S.A.C. "
        "integrada con Supabase, FastAPI y modelos ML."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextLoggingMiddleware)

register_exception_handlers(app)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(usuarios.router, prefix="/usuarios", tags=["Usuarios"])
app.include_router(maestros.router, tags=["Maestros"])
app.include_router(ordenes_trabajo.router, tags=["Ordenes de Trabajo"])
app.include_router(compras.router, tags=["Compras"])
app.include_router(ml.router, prefix="/ml", tags=["ML"])
app.include_router(alertas.router, prefix="/alertas", tags=["Alertas"])
app.include_router(reportes.router, prefix="/reportes", tags=["Reportes"])
app.include_router(ventas.router, tags=["Ventas"])


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Verificar salud del backend",
    description="Comprueba que la API este activa y pueda conectarse a Supabase.",
)
async def health_check() -> HealthResponse:
    return await build_health_response()
