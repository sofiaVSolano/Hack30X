"""Verificación de cifras: las que parecen datos deben estar en los hechos o en el catálogo."""

from app.modules.crear.context import Fact
from app.modules.crear.generation.base import ProposalContent
from app.modules.crear.generation.verification import unsupported_figures

from .contexts import gap_context


def content(text: str) -> ProposalContent:
    return ProposalContent(
        titulo="Título",
        gancho=text,
        idea_central="Idea.",
        estructura=["0–3 s · Gancho", "1/7 · Paso", "Diapositivas 4–5 · Claves"],
        formato="Artículo de 800 a 1200 palabras",
        llamado_a_la_accion="Comenta.",
        adaptacion_latam=["Ejemplos locales."],
        palabras_clave=["tema"],
        precauciones=["Verifica los datos."],
    )


def test_invented_figures_are_reported() -> None:
    found = unsupported_figures(content("El 45 % lo busca, 3 veces más que antes, con 1,5 millones de vistas."), gap_context())

    assert found == ["45 %", "3 veces", "1,5 millones"]


def test_figures_from_the_facts_are_accepted_in_any_spelling() -> None:
    text = "Hubo 9800 visitas (9.800, 9 800) y 25 veces más lecturas: 25,0×."

    assert unsupported_figures(content(text), gap_context()) == []


def test_scaled_spellings_match_the_fact() -> None:
    context = gap_context().model_copy(update={"hechos": [Fact(clave="x", texto="24.500 visitas en 7 días.", fuente="DETECTAR")]})

    assert unsupported_figures(content("Casi 24,5 mil visitas"), context) == []
    assert unsupported_figures(content("Casi 25 mil visitas"), context) == ["25 mil"]


def test_structure_numbers_catalog_and_topic_name_are_not_data() -> None:
    context = gap_context(name="Copa 2026")

    assert unsupported_figures(content("La Copa 2026 explicada en 7 diapositivas y 60 segundos."), context) == []
