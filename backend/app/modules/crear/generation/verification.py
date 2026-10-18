"""Verificación de cifras de una propuesta: CREAR no inventa números.

Busca en el texto de la propuesta las cifras que suelen presentarse como datos —porcentajes,
multiplicadores («3×», «5 veces»), cantidades de cuatro o más cifras y cantidades con «mil» o
«millones»— y comprueba que cada una aparezca en los hechos del contexto, en el nombre del tema
o en las pautas del catálogo. Las que no aparecen se devuelven como «cifras sin respaldo» para
mostrarlas junto a la propuesta: no se borran ni se corrigen, porque decidir qué hacer con ellas
le corresponde a la persona.

Las cifras pequeñas sin unidad (pasos, segundos, diapositivas) no se revisan: son estructura.
"""

import re
from collections.abc import Iterable

from app.modules.crear.catalog import catalog_texts
from app.modules.crear.context import CreativeContext
from app.modules.crear.generation.base import ProposalContent

# Miles con separador (24.500, 24,500, 24 500) o número simple con decimales (19,5 o 1295).
_NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d)"
    r"(\s*(?:%|por\s?ciento\b|×|veces\b|x(?!\w)|millones\b|millón\b|mil\b|k\b))?",
    re.IGNORECASE,
)
_SCALE = {"mil": 1_000.0, "k": 1_000.0, "millones": 1_000_000.0, "millón": 1_000_000.0}
_LARGE = 1_000


def _candidates(raw: str, suffix: str) -> set[float]:
    """Valores posibles de una cifra: «24.500» puede ser 24500 (es) o 24,5 (en)."""
    text = raw.replace("\u00a0", " ").replace("\u202f", " ")
    scale = _SCALE.get(suffix.strip().lower(), 1.0)
    values: set[float] = set()
    for thousands, decimal in ((".", ","), (",", "."), (" ", ",")):
        candidate = text.replace(thousands, "").replace(" ", "").replace(decimal, ".")
        try:
            values.add(round(float(candidate) * scale, 3))
        except ValueError:
            continue
    return values


def _kind(suffix: str) -> str:
    """Un «45 %» no se respalda con un «45 segundos»: cada tipo de cifra se compara aparte."""
    word = suffix.strip().lower()
    if word == "%" or word.startswith("por"):
        return "porcentaje"
    if word in ("×", "x", "veces"):
        return "multiplicador"
    return "cantidad"


def _tokens(text: str) -> Iterable[tuple[str, str, set[float], bool]]:
    """(texto de la cifra, tipo, valores posibles, ¿se presenta como dato?)."""
    for match in _NUMBER.finditer(text):
        raw, suffix = match.group(1), match.group(2) or ""
        values = _candidates(raw, suffix)
        if not values:
            continue
        looks_like_data = bool(suffix.strip()) or max(values) >= _LARGE
        yield (raw + suffix).strip(), _kind(suffix), values, looks_like_data


def allowed_numbers(context: CreativeContext) -> set[tuple[str, float]]:
    texts = [fact.texto for fact in context.hechos]
    texts.extend((context.tema_nombre, *catalog_texts()))
    allowed: set[tuple[str, float]] = set()
    for text in texts:
        for _label, kind, values, _data in _tokens(text):
            allowed |= {(kind, value) for value in values}
    return allowed


def _content_texts(content: ProposalContent) -> list[str]:
    return [
        content.titulo,
        content.gancho,
        content.idea_central,
        content.formato,
        content.llamado_a_la_accion,
        *content.estructura,
        *content.adaptacion_latam,
        *content.palabras_clave,
        *content.precauciones,
    ]


def unsupported_figures(content: ProposalContent, context: CreativeContext, *, limit: int = 20) -> list[str]:
    """Cifras con aspecto de dato que no aparecen en los hechos ni en el catálogo."""
    allowed = allowed_numbers(context)
    found: list[str] = []
    for text in _content_texts(content):
        for label, kind, values, looks_like_data in _tokens(text):
            supported = any((kind, value) in allowed for value in values)
            if looks_like_data and not supported and label not in found:
                found.append(label)
    return found[:limit]
