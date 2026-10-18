"""Errores de CREAR en el mismo formato RFC 9457 que DETECTAR (``application/problem+json``).

El manejador de validación se ENCADENA con el que ya tenga la app: responde en formato
problem+json bajo ``/api/crear`` y delega cualquier otra ruta en el manejador anterior (el de
DETECTAR o el de FastAPI). Por eso se instala después de DETECTAR (ver ``app/main.py``).
"""

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from app.modules.detectar.api.errors import FieldError, Problem, problem_response

ERROR_TYPE_PREFIX = "urn:hack30x:crear:error:"


class CrearError(Exception):
    """Error de dominio de CREAR que se responde como problem+json."""

    def __init__(
        self,
        *,
        code: str,
        status: int,
        title: str,
        detail: str | None = None,
        errors: list[FieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.errors = errors
        self.headers = headers


def not_found(what: str) -> CrearError:
    return CrearError(code="not_found", status=404, title="No encontrado", detail=f"{what} no existe.")


def invalid(detail: str, field: str) -> CrearError:
    return CrearError(
        code="invalid_operation",
        status=422,
        title="Operación no válida",
        detail=detail,
        errors=[FieldError(campo=field, mensaje=detail)],
    )


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def install_exception_handlers(app: FastAPI, *, prefix: str) -> None:
    previous = app.exception_handlers.get(RequestValidationError, request_validation_exception_handler)

    async def handle_crear_error(request: Request, exc: CrearError) -> Response:
        return problem_response(
            Problem(
                type=ERROR_TYPE_PREFIX + exc.code,
                title=exc.title,
                status=exc.status,
                code=exc.code,
                detail=exc.detail,
                instance=request.url.path,
                errors=exc.errors,
            ),
            headers=exc.headers,
        )

    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not _under(request.url.path, prefix):
            return await previous(request, exc)
        # Solo la ubicación y el mensaje; nunca el valor recibido.
        errors = [
            FieldError(campo=".".join(str(part) for part in err["loc"]), mensaje=err["msg"])
            for err in exc.errors()
        ]
        return problem_response(
            Problem(
                type=ERROR_TYPE_PREFIX + "validation_error",
                title="Parámetros inválidos",
                status=422,
                code="validation_error",
                detail="La solicitud contiene parámetros inválidos.",
                instance=request.url.path,
                errors=errors,
            )
        )

    app.add_exception_handler(CrearError, handle_crear_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
