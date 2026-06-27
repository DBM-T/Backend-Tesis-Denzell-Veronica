from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.enums import CSVDataType, MLModelType
from app.schemas.ml import (
    CSVLoadResult,
    ModeloMLRead,
    PronosticoDemandaRead,
    RecalcularDemandaResponse,
    RiesgoAbastecimientoRead,
    ValidacionCSVRead,
)
from app.services.ml_service import (
    get_csv_validations,
    list_modelos_ml,
    list_pronosticos_demanda,
    list_riesgo_abastecimiento,
    recalculate_demand,
    load_csv,
)


router = APIRouter()


@router.post(
    "/cargas-csv",
    response_model=CSVLoadResult,
    summary="Cargar CSV historico",
    description="Recibe un CSV, lo valida, registra incidencias y opcionalmente inserta los datos limpios en historial_consumo.",
)
async def post_cargas_csv(
    archivo: UploadFile = File(...),
    tipo_dato: CSVDataType = Form(...),
    confirmar_continuar: bool = Form(False),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await load_csv(current_user.supabase, current_user, archivo, tipo_dato, confirmar_continuar=confirmar_continuar)


@router.get(
    "/cargas-csv/{carga_id}/validaciones",
    response_model=list[ValidacionCSVRead],
    summary="Ver validaciones de una carga CSV",
    description="Devuelve las incidencias registradas para una carga CSV concreta.",
)
async def get_cargas_csv_validaciones(
    carga_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await get_csv_validations(current_user.supabase, str(carga_id))


@router.get(
    "/modelos",
    response_model=list[ModeloMLRead],
    summary="Listar modelos ML",
    description="Devuelve el catalogo de modelos ML versionados, filtrable por tipo y estado activo.",
)
async def get_modelos(
    tipo_modelo: MLModelType | None = Query(default=None),
    activo: bool | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_modelos_ml(current_user.supabase, tipo_modelo=tipo_modelo, activo=activo)


@router.get(
    "/modelos-ml",
    response_model=list[ModeloMLRead],
    include_in_schema=False,
)
async def get_modelos_ml(
    tipo_modelo: MLModelType | None = Query(default=None),
    activo: bool | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_modelos_ml(current_user.supabase, tipo_modelo=tipo_modelo, activo=activo)


@router.get(
    "/pronosticos-demanda",
    response_model=list[PronosticoDemandaRead],
    summary="Listar pronosticos de demanda",
    description="Devuelve los pronosticos historicos o vigentes de demanda para repuesto y sede.",
)
async def get_pronosticos_demanda(
    repuesto_id: UUID | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_pronosticos_demanda(current_user.supabase, repuesto_id=repuesto_id, sede_id=sede_id)


@router.get(
    "/riesgo-abastecimiento",
    response_model=list[RiesgoAbastecimientoRead],
    summary="Listar riesgo de abastecimiento",
    description="Devuelve el nivel de riesgo vigente por repuesto y sede.",
)
async def get_riesgo_abastecimiento(
    repuesto_id: UUID | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await list_riesgo_abastecimiento(current_user.supabase, repuesto_id=repuesto_id, sede_id=sede_id)


@router.post(
    "/recalcular-demanda",
    response_model=RecalcularDemandaResponse,
    summary="Recalcular demanda",
    description="Recalcula pronosticos de demanda y riesgo de abastecimiento para los SKUs relevantes.",
)
async def post_recalcular_demanda(
    repuesto_id: UUID | None = Query(default=None),
    sede_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await recalculate_demand(current_user, repuesto_id=repuesto_id, sede_id=sede_id)
