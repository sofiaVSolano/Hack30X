import pytest

from app.modules.detectar.topics.normalize import (
    disambiguation_base,
    is_usable_key,
    normalize_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("México", "mexico"),
        ("MÉXICO", "mexico"),
        ("  Copa   América  2026 ", "copa america 2026"),
        ("Copa_América_2026", "copa america 2026"),
        ("AC/DC", "ac dc"),
        ("covid-19", "covid 19"),
        ("¿Qué pasó?", "que paso"),
        ("Straße", "strasse"),
        ("ＣＯＶＩＤ", "covid"),  # NFKC: caracteres de ancho completo
        ("São Paulo", "sao paulo"),
        ("Inteligencia Artificial", "inteligencia artificial"),
        # Siglas con puntos
        ("I.A.", "ia"),
        ("I.A", "ia"),
        ("U.S.A.", "usa"),
        ("la I.A. hoy", "la ia hoy"),
        ("Dr. House", "dr house"),
        ("versión 1.5", "version 1 5"),
        ("Sr.A", "sr a"),
    ],
)
def test_normalization_variants(text: str, expected: str) -> None:
    assert normalize_text(text) == expected


def test_enye_is_kept_so_different_words_do_not_collide() -> None:
    assert normalize_text("Año Nuevo") == "año nuevo"
    assert normalize_text("año") != normalize_text("ano")
    assert normalize_text("PEÑA") == "peña"


def test_no_stemming_stopwords_or_synonyms() -> None:
    # Normalizar no relaciona conceptos: solo iguala variantes de escritura.
    assert normalize_text("IA") != normalize_text("Inteligencia artificial")
    assert normalize_text("tendencias") != normalize_text("tendencia")
    assert normalize_text("la copa") != normalize_text("copa")


@pytest.mark.parametrize(("text", "usable"), [("x", False), ("!!", False), ("ia", True), ("5g", True)])
def test_minimum_key_length(text: str, usable: bool) -> None:
    assert is_usable_key(normalize_text(text)) is usable


@pytest.mark.parametrize(
    ("title", "base"),
    [
        ("Mercurio (planeta)", "Mercurio"),
        ("Jaguar (automóvil)", "Jaguar"),
        ("Mercurio", None),
        ("(algo)", None),
        ("A (b) (c)", "A (b)"),
    ],
)
def test_disambiguation_base(title: str, base: str | None) -> None:
    assert disambiguation_base(title) == base
