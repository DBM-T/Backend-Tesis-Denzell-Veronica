"""Punto de entrada FastAPI - Gestion de Abastecimiento con XGBoost y LightGBM."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config import get_settings
from database import close_db_pool, init_db_pool
from routers import auth, core_data, dashboard, ml, parts, purchase_orders, supply_requests, users, work_orders

_s = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando BD pool...")
    await init_db_pool()
    logger.info("Sistema listo")
    yield
    await close_db_pool()
    logger.info("BD pool cerrado")


app = FastAPI(
    title="ML - Gestion de Abastecimiento",
    description=(
        "Sistema web con XGBoost y LightGBM para la gestion de abastecimiento "
        "de repuestos - CALEAND S.A.C. / UPC Tesis 2026"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(core_data.router, tags=["Datos Base"])
app.include_router(users.router, prefix="/users", tags=["Usuarios"])
app.include_router(parts.router, prefix="/parts", tags=["Productos"])
app.include_router(work_orders.router, prefix="/work-orders", tags=["Ordenes de trabajo"])
app.include_router(supply_requests.router, prefix="/supply-requests", tags=["Requisiciones"])
app.include_router(purchase_orders.router, prefix="/purchase-orders", tags=["Compras"])
app.include_router(ml.router, prefix="/ml", tags=["ML - XGBoost y LightGBM"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])


@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "version": "2.0.0"}
