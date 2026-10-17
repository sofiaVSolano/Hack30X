"""Errores estructurados compatibles con RFC 9457 (``application/problem+json``).

Los manejadores se instalan explícitamente con :func:`install_exception_handlers`, de modo
que la app compartida decide cuándo activarlos. El manejador de validación solo responde
en formato problem+json para rutas bajo el prefijo de DETECTAR; el resto de la app conserva
el formato por defecto de FastAPI y no se interfiere con otros módulos.
"""

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

PROBLEM_MEDIA_TYPE = "application/problem+json"
ERROR_TYPE_PREFIX = "urn:hack30x:detectar:error:"


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campo: str
    mensaje: str


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None


class DetectarError(Exception):
    """Error de dominio de DETECTAR que se responde como problem+json."""

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


def problem_response(problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def _is_detectar_path(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def install_exception_handlers(app: FastAPI, *, prefix: str) -> None:
    async def handle_detectar_error(request: Request, exc: DetectarError) -> Response:
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
        if not _is_detectar_path(request.url.path, prefix):
            return await request_validation_exception_handler(request, exc)
        # Solo se exponen la ubicación y el mensaje; nunca el valor recibido.
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

    app.add_exception_handler(DetectarError, handle_detectar_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
