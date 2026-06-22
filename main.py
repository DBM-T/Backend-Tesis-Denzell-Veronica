"""
main.py — Punto de entrada FastAPI
Sistema Web RNS — Gestión de Abastecimiento PYMES Automotriz
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config import get_settings
from database import init_db_pool, close_db_pool
from routers import parts, work_orders, supply_requests, purchase_orders, rns, dashboard, auth

_s = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("▶  Iniciando BD pool...")
    await init_db_pool()
    logger.info("▶  Cargando modelo RNS...")
    # from services.rns_service import rns_service
    # await rns_service.load_model()
    logger.info("✔  Sistema listo")
    yield
    await close_db_pool()
    logger.info("■  BD pool cerrado")


app = FastAPI(
    title="RNS — Gestión de Abastecimiento",
    description=(
        "Sistema web basado en Redes Neuronales Siamesas para la gestión "
        "de abastecimiento de repuestos — CALEAND S.A.C. / UPC Tesis 2026"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────
app.include_router(auth.router,             prefix="/auth",             tags=["Auth"])
app.include_router(parts.router,            prefix="/parts",            tags=["Repuestos"])
app.include_router(work_orders.router,      prefix="/work-orders",      tags=["Órdenes de trabajo"])
app.include_router(supply_requests.router,  prefix="/supply-requests",  tags=["Solicitudes"])
app.include_router(purchase_orders.router,  prefix="/purchase-orders",  tags=["Compras"])
app.include_router(rns.router,              prefix="/rns",              tags=["RNS — Motor IA"])
app.include_router(dashboard.router,        prefix="/dashboard",        tags=["Dashboard"])


@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "version": "1.0.0"}
