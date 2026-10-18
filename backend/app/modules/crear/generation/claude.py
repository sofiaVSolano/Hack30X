"""Motor ``claude``: propuestas con Claude mediante el SDK oficial de Anthropic.

- Una llamada por lote (las tres propuestas a la vez, para que sean distintas entre sí) y una
  por regeneración.
- Salida estructurada: ``messages.parse`` valida la respuesta con los mismos modelos Pydantic
  que usa el resto de CREAR.
- ``fallbacks="default"``: si los clasificadores de seguridad declinan, la API reintenta con el
  modelo de respaldo recomendado para ese caso.
- Cualquier fallo se convierte en ``GenerationError`` con un motivo seguro de mostrar; el
  generador usa entonces las plantillas y lo indica en la propuesta.

El SDK se importa al crear el motor, no al importar CREAR: sin el paquete ``anthropic``, el
backend arranca igual y usa plantillas.
"""

import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.crear.catalog import Approach
from app.modules.crear.config import CrearSettings
from app.modules.crear.context import CreativeContext
from app.modules.crear.generation.base import (
    CreativeParams,
    GenerationError,
    PreviousProposal,
    ProposalContent,
)
from app.modules.crear.generation.prompts import (
    SYSTEM_PROMPT,
    batch_prompt,
    regeneration_prompt,
)

logger = logging.getLogger(__name__)

ENGINE_ID = "claude"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000

T = TypeVar("T", bound=BaseModel)


class BatchOutput(BaseModel):
    """Salida de un lote: una propuesta por enfoque, con nombre fijo (ninguna puede faltar)."""

    model_config = ConfigDict(extra="forbid")

    educativo: ProposalContent
    controversial: ProposalContent
    narrativo: ProposalContent


class ClaudeEngine:
    id = ENGINE_ID

    def __init__(self, settings: CrearSettings, client: Any | None = None) -> None:
        if client is None:
            import anthropic  # importación diferida: ver el docstring del módulo

            client = anthropic.Anthropic(
                timeout=settings.claude_timeout_seconds, max_retries=settings.claude_max_retries
            )
        self._client = client
        self.model: str | None = settings.modelo
        self._effort = settings.esfuerzo

    def generate_batch(self, context: CreativeContext, params: CreativeParams) -> dict[Approach, ProposalContent]:
        output = self._call(batch_prompt(context, params), BatchOutput)
        return {
            Approach.EDUCATIVO: output.educativo,
            Approach.CONTROVERSIAL: output.controversial,
            Approach.NARRATIVO: output.narrativo,
        }

    def regenerate(
        self,
        context: CreativeContext,
        previous: PreviousProposal,
        approach: Approach,
        params: CreativeParams,
        instruction: str | None,
        version: int,
    ) -> ProposalContent:
        return self._call(regeneration_prompt(context, previous, approach, params, instruction), ProposalContent)

    def _call(self, user_text: str, schema: type[T]) -> T:
        import anthropic

        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_text}],
                output_format=schema,
                output_config={"effort": self._effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise self._fail("credencial", "Anthropic rechazó la credencial configurada.") from None
        except anthropic.PermissionDeniedError:
            raise self._fail("permiso", "La credencial de Anthropic no tiene permiso para usar este modelo.") from None
        except anthropic.NotFoundError:
            raise self._fail("modelo", f"El modelo {self.model} no existe o no está disponible.") from None
        except anthropic.RateLimitError:
            raise self._fail("limite", "Claude alcanzó su límite de solicitudes; inténtalo más tarde.") from None
        except anthropic.BadRequestError:
            raise self._fail("solicitud", "Claude rechazó la solicitud por parámetros no válidos.") from None
        except anthropic.APIStatusError as exc:
            raise self._fail("estado", f"La API de Anthropic devolvió un error ({exc.status_code}).") from None
        except anthropic.APITimeoutError:
            raise self._fail("tiempo", "Claude no respondió a tiempo.") from None
        except anthropic.APIConnectionError:
            raise self._fail("conexion", "No se pudo conectar con la API de Anthropic.") from None
        except ValidationError:
            raise self._fail("formato", "La respuesta de Claude no tenía el formato esperado.") from None
        except anthropic.AnthropicError:
            raise self._fail("sdk", "No se pudo usar Claude: revise la credencial de Anthropic.") from None
        except TypeError as exc:
            # El SDK lanza TypeError cuando no encuentra ninguna credencial en el entorno.
            if "authentication" not in str(exc).lower():
                raise
            raise self._fail(
                "sin_credencial", "No hay credencial de Anthropic (ANTHROPIC_API_KEY o «ant auth login»)."
            ) from None
        if response.stop_reason == "refusal":
            raise self._fail("rechazo", "Claude declinó generar esta propuesta.")
        if response.stop_reason == "max_tokens":
            raise self._fail("incompleta", "La respuesta de Claude quedó incompleta.")
        parsed = response.parsed_output
        if not isinstance(parsed, schema):
            raise self._fail("vacia", "Claude no devolvió una propuesta.")
        return parsed

    @staticmethod
    def _fail(code: str, message: str) -> GenerationError:
        # Solo el código del motivo: nunca el texto de la solicitud ni de la respuesta.
        logger.warning("CREAR: Claude no generó la propuesta (%s)", code)
        return GenerationError(message)
