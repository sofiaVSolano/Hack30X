"""Extracción de candidatos a tema desde observaciones ya guardadas.

Qué campo representa el tema en cada fuente (el resto son metadatos de la observación):

- Google Trends RSS (``search_term``): ``subject_ref`` = título de la tendencia tal como
  llegó. País, captura, tráfico y noticias son metadatos; el tráfico no es un volumen.
- Wikimedia (``wiki_article``): ``subject_ref`` = ``<proyecto>:<Artículo>``; el tema es el
  título del artículo (guiones bajos como espacios). Proyecto, día y visitas son metadatos;
  la edición no indica el país de los lectores.
- GDELT (``news_query``): ``raw_excerpt["term"]`` = término consultado. ``subject_ref`` es la
  consulta completa con filtros (``sourcelang:``, ``sourcecountry:``), que son metadatos.
  Es una consulta periodística, no un artículo concreto.

Si falta el campo temático, se devuelve una limitación en lugar de inventar un tema.
Nunca se modifica la observación.
"""

from dataclasses import dataclass

from app.modules.detectar.storage.models import RawObservation, Source, SubjectType
from app.modules.detectar.topics.normalize import disambiguation_base


@dataclass(frozen=True)
class Candidate:
    text: str | None
    # Solo Wikipedia: base de un título con calificador, p. ej. "Mercurio (planeta)".
    disambiguation_base: str | None = None
    limitation: str | None = None


def candidate_for(observation: RawObservation) -> Candidate:
    source, subject_type = observation.source, observation.subject_type

    if source is Source.GOOGLE_TRENDS_RSS and subject_type is SubjectType.SEARCH_TERM:
        text = observation.subject_ref.strip()
        return Candidate(text) if text else Candidate(None, limitation="gtr_empty_title")

    if source is Source.WIKIMEDIA and subject_type is SubjectType.WIKI_ARTICLE:
        project, separator, article = observation.subject_ref.partition(":")
        if not separator or not project or not article:
            return Candidate(None, limitation="wikimedia_subject_without_article")
        title = article.replace("_", " ").strip()
        return Candidate(title, disambiguation_base=disambiguation_base(title))

    if source is Source.GDELT and subject_type is SubjectType.NEWS_QUERY:
        excerpt = observation.raw_excerpt or {}
        term = excerpt.get("term")
        if not isinstance(term, str) or not term.strip():
            return Candidate(None, limitation="gdelt_term_missing")
        return Candidate(term.strip())

    return Candidate(
        None, limitation=f"unsupported_subject:{source.value}:{subject_type.value}"
    )
