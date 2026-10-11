"""Tests of translation files."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

from custom_components.prezero_bielsko.const import FRACTIONS

COMPONENT = Path(__file__).parents[1] / "custom_components" / "prezero_bielsko"


def _load(name: str) -> dict[str, Any]:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, path))
        else:
            result[path] = value
    return result


STRINGS = _flatten(_load("strings.json"))


@pytest.mark.parametrize("language", ["en", "pl"])
def test_translation_keys_match(language: str) -> None:
    """Every translation has exactly the keys of strings.json."""
    translation = _flatten(_load(f"translations/{language}.json"))
    assert set(translation) == set(STRINGS)


@pytest.mark.parametrize("language", ["en", "pl"])
def test_placeholders_match(language: str) -> None:
    """Placeholders are the same in every language."""
    translation = _flatten(_load(f"translations/{language}.json"))
    for key, value in STRINGS.items():
        assert set(re.findall(r"{(\w+)}", translation[key])) == set(
            re.findall(r"{(\w+)}", value)
        ), key


def test_english_matches_strings() -> None:
    """The English translation is generated from strings.json."""
    assert _load("translations/en.json") == _load("strings.json")


def test_all_fractions_translated() -> None:
    """Every known fraction has entity names, icons and option labels."""
    icons = _load("icons.json")["entity"]
    for key in [*FRACTIONS, "other"]:
        assert f"entity.sensor.{key}.name" in STRINGS
        assert f"entity.binary_sensor.reminder_{key}.name" in STRINGS
        assert key in icons["sensor"]
        assert f"reminder_{key}" in icons["binary_sensor"]
    for key in FRACTIONS:
        assert f"options.step.init.sections.reminders.data.days_{key}" in STRINGS
        assert f"options.step.init.sections.appearance.data.color_{key}" in STRINGS


def test_polish_fraction_names() -> None:
    """Polish entity names match the default fraction names."""
    polish = _load("translations/pl.json")["entity"]["sensor"]
    for key, info in FRACTIONS.items():
        assert polish[key]["name"] == info.name
