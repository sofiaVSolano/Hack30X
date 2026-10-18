"""Motor plantillas-v1: tres propuestas distintas, deterministas y sin cifras inventadas."""

import pytest

from app.modules.crear.catalog import BATCH_APPROACHES, Approach, Platform
from app.modules.crear.generation.base import PreviousProposal
from app.modules.crear.generation.templates import TemplateEngine
from app.modules.crear.generation.verification import unsupported_figures
from app.modules.detectar.storage.models import DataMode

from .contexts import GAP_FACT, gap_context, manual_context, params, plain_context

engine = TemplateEngine()


def test_batch_has_one_distinct_proposal_per_approach() -> None:
    batch = engine.generate_batch(gap_context(), params())

    assert list(batch) == list(BATCH_APPROACHES)
    assert len({c.titulo for c in batch.values()}) == 3
    assert len({c.gancho for c in batch.values()}) == 3
    for content in batch.values():
        assert [step.split(" · ")[0] for step in content.estructura] == ["0–3 s", "3–15 s", "15–35 s", "35–50 s", "50–60 s"]
        assert content.formato.startswith("Video vertical de 45 a 60 segundos para TikTok.")


def test_same_request_same_result() -> None:
    assert engine.generate_batch(gap_context(), params()) == engine.generate_batch(gap_context(), params())


def test_cites_only_facts_from_the_context() -> None:
    context = gap_context()
    batch = engine.generate_batch(context, params())

    for content in batch.values():
        assert unsupported_figures(content, context) == []
        assert any(GAP_FACT in step for step in content.estructura)


@pytest.mark.parametrize(
    ("platform", "first_slot"),
    [
        (Platform.CARRUSEL, "Diapositiva 1"),
        (Platform.YOUTUBE, "0:00"),
        (Platform.HILO_X, "1/7"),
        (Platform.LINKEDIN, "Primera línea"),
        (Platform.PODCAST, "Intro (1 min)"),
        (Platform.BLOG, "Introducción"),
    ],
)
def test_structure_follows_the_platform_format(platform: Platform, first_slot: str) -> None:
    content = engine.generate_batch(gap_context(), params(platform))[Approach.EDUCATIVO]

    assert content.estructura[0].startswith(f"{first_slot} · ")


def test_claims_only_appear_when_the_context_supports_them() -> None:
    claims = ("mucho menos", "tan poco", "se hablaba poco", "según DETECTAR", "en inglés")
    context = plain_context()
    for version in range(1, 40):
        for approach in BATCH_APPROACHES:
            previous = PreviousProposal(approach, params(), engine.generate_batch(context, params())[approach], 1)
            content = engine.regenerate(context, previous, approach, params(), None, version)
            text = f"{content.titulo} {content.gancho} {content.idea_central}"
            assert not any(claim in text for claim in claims), text


def test_regeneration_adapts_audience_platform_and_approach() -> None:
    context = gap_context()
    original = engine.generate_batch(context, params())[Approach.EDUCATIVO]
    previous = PreviousProposal(Approach.EDUCATIVO, params(), original, 1)

    new = engine.regenerate(
        context, previous, Approach.NARRATIVO, params(Platform.CARRUSEL, audience="jovenes_genz", detail="estudiantes de Monterrey"), None, 2
    )

    assert new != original
    assert new.estructura[0].startswith("Diapositiva 1 · La escena inicial")
    assert any("jóvenes de la Gen Z" in item for item in new.adaptacion_latam)
    assert "Piensa en esta audiencia concreta: estudiantes de Monterrey." in new.adaptacion_latam
    assert "Si la historia es ficticia o una recreación, acláralo." in new.precauciones


def test_manual_topics_cite_nothing_and_warn() -> None:
    context = manual_context()
    content = engine.generate_batch(context, params(country=None))[Approach.EDUCATIVO]

    assert context.hechos == []
    assert any("Usa solo datos que puedas verificar." in step for step in content.estructura)
    assert "Este tema no tiene datos de DETECTAR: no afirmes que es tendencia sin comprobarlo." in content.precauciones
    assert "Usa un español neutro y evita expresiones que solo se entiendan en un país." in content.adaptacion_latam
    assert "Latinoamérica" in content.palabras_clave


def test_simulated_data_is_flagged_in_the_cautions() -> None:
    content = engine.generate_batch(gap_context(mode=DataMode.SIMULATED), params())[Approach.CONTROVERSIAL]

    assert "Datos de demostración: no presentes estas cifras ni el tema como reales." in content.precauciones
    assert "Debate ideas: no ataques a personas ni a grupos." in content.precauciones
