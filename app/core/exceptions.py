import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.schemas.common import ErrorBody, ErrorResponse


logger = logging.getLogger("caleand")

POSTGRES_STATUS_MAP: dict[str, tuple[int, str]] = {
    "23505": (status.HTTP_409_CONFLICT, "Conflicto por valor duplicado."),
    "23503": (status.HTTP_409_CONFLICT, "La referencia relacionada no existe."),
    "23514": (status.HTTP_400_BAD_REQUEST, "La operacion viola una restriccion de validacion."),
    "22P02": (status.HTTP_400_BAD_REQUEST, "Uno de los valores enviados no tiene el formato esperado."),
    "PGRST116": (status.HTTP_404_NOT_FOUND, "No se encontro el recurso solicitado."),
}


def _error_response(
    *,
    status_code: int,
    error_type: str,
    message: str,
    code: str | None = None,
    details: str | list[dict] | None = None,
    hint: str | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            type=error_type,
            message=message,
            code=code,
            details=details,
            hint=hint,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_postgrest_error(_: Request, exc: APIError) -> JSONResponse:
        status_code, message = POSTGRES_STATUS_MAP.get(
            exc.code or "",
            (
                status.HTTP_400_BAD_REQUEST,
                exc.message or "Error al procesar la solicitud contra la base de datos.",
            ),
        )
        return _error_response(
            status_code=status_code,
            error_type="database_error",
            message=message,
            code=exc.code,
            details=exc.details,
            hint=exc.hint,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_type="validation_error",
            message="La solicitud contiene datos invalidos.",
            details=exc.errors(),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_type="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_type="internal_error",
            message="Ocurrio un error interno no esperado.",
        )
