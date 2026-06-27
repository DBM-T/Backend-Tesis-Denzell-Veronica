# CALEAND SAC Backend

Backend en FastAPI para el sistema de abastecimiento de CALEAND S.A.C., integrado con Supabase y la capa de ML del proyecto.

## Arquitectura

```text
app/
  core/          config, seguridad, rate limit, scheduler, logging
  routers/       auth, usuarios, maestros, OT, compras, ML, alertas, reportes
  services/      lógica de negocio por módulo
  ml/            inferencia online y scripts de training offline
tests/          pruebas unitarias e integración simulada
supabase/       migraciones RLS nuevas por fase
```

## Variables de entorno

Necesarias:

```bash
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
SUPABASE_JWKS_URL=
PORT=8000
ENVIRONMENT=development
OC_LIMITE_APROBACION_GERENCIA=1500.00
ML_MODELS_DIR=app/ml/models
REPORTS_BUCKET=reports
AUTH_RATE_LIMIT_PER_MINUTE=5
CORS_ORIGINS=http://localhost:3000
```

## Levantamiento local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Rutas útiles:

- `GET /health`
- `GET /docs`
- `GET /redoc`

## Fases implementadas

- Fase 0: setup FastAPI, autenticación request-scoped, logging, health.
- Fase 1: auth y usuarios.
- Fase 2: maestros de datos.
- Fase 3: OT, PR e inventario operativo.
- Fase 4: RFQ, OC y recepciones.
- Fase 5: CSV históricos e inferencia de demanda.
- Fase 6: capa ML online y catálogo de modelos.
- Fase 7: alertas, recomendaciones y dashboard.
- Fase 8: reportes, indicadores de validación y continuidad.
- Fase 9: rate limiting, observabilidad, CI/CD y pruebas de integración.

## CI/CD

El repositorio incluye un workflow básico que ejecuta:

1. Lint con `ruff`
2. Tests con `pytest`
3. Build de verificación con `python -m compileall`

## Despliegue en Render

El servicio puede levantarse con:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Nota de auditoría

Si el cliente pide trazabilidad adicional para cambios sensibles, conviene agregar una migración nueva para una tabla de auditoría separada. No se improvisa sobre las tablas existentes.
