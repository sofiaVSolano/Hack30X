"""Selección del motor según CREAR_MOTOR y la credencial de Anthropic."""

import importlib.util
import sys

import pytest

from app.modules.crear.config import CrearSettings
from app.modules.crear.generation.factory import (
    build_generator,
    has_anthropic_credentials,
)


def test_templates_when_configured() -> None:
    info = build_generator(CrearSettings(motor="plantillas"), env={"ANTHROPIC_API_KEY": "sk-x"}).info

    assert (info.id, info.model) == ("plantillas-v1", None)
    assert "CREAR_MOTOR=plantillas" in info.detail


def test_auto_without_credentials_uses_templates_and_explains_how_to_enable_claude() -> None:
    info = build_generator(CrearSettings(), env={}).info

    assert info.id == "plantillas-v1"
    assert "ANTHROPIC_API_KEY" in info.detail


@pytest.mark.skipif(importlib.util.find_spec("anthropic") is None, reason="extra crear no instalado")
def test_auto_with_credentials_uses_claude_without_calling_it() -> None:
    info = build_generator(CrearSettings(), env={"ANTHROPIC_API_KEY": "sk-ant-prueba"}).info

    assert (info.id, info.name, info.model) == ("claude", "Claude", "claude-opus-5-5")


def test_missing_sdk_falls_back_to_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import anthropic -> ImportError

    info = build_generator(CrearSettings(motor="claude"), env={}).info

    assert info.id == "plantillas-v1"
    assert "anthropic no está instalado" in info.detail


def test_blank_credentials_do_not_count() -> None:
    assert not has_anthropic_credentials({"ANTHROPIC_API_KEY": "  ", "ANTHROPIC_AUTH_TOKEN": ""})
    assert has_anthropic_credentials({"ANTHROPIC_AUTH_TOKEN": "tok"})
