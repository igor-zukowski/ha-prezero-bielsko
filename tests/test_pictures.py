"""Tests of colored fraction pictures."""

from __future__ import annotations

import pytest

from custom_components.prezero_bielsko.const import FRACTIONS, UNKNOWN_FRACTION_COLOR
from custom_components.prezero_bielsko.pictures import (
    default_color,
    hex_to_rgb,
    normalize_color,
    render_svg,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#1565c0", "#1565C0"),
        ("1565C0", "#1565C0"),
        (" #ABCDEF ", "#ABCDEF"),
        ([21, 101, 192], "#1565C0"),
        ((0, 0, 0), "#000000"),
        ("#12345", "#DEFAUL"),
        ("red", "#DEFAUL"),
        ([256, 0, 0], "#DEFAUL"),
        ([1, 2], "#DEFAUL"),
        (["1", 2, 3], "#DEFAUL"),
        (None, "#DEFAUL"),
    ],
)
def test_normalize_color(value: object, expected: str) -> None:
    """Colors are normalized from hex strings and RGB lists."""
    assert normalize_color(value, "#DEFAUL") == expected


def test_hex_to_rgb() -> None:
    """Hex colors convert to RGB lists."""
    assert hex_to_rgb("#1565C0") == [21, 101, 192]


def test_default_color() -> None:
    """Known fractions have their colors, unknown ones a neutral color."""
    assert default_color("makulatura") == FRACTIONS["makulatura"].color
    assert default_color("elektro") == UNKNOWN_FRACTION_COLOR


@pytest.mark.parametrize("fraction", [*FRACTIONS, "unknown"])
def test_render_all(fraction: str) -> None:
    """Every fraction renders a valid SVG."""
    svg = render_svg(fraction, default_color(fraction))
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert f'fill="{default_color(fraction)}"' in svg


@pytest.mark.parametrize(
    ("color", "glyph"),
    [
        ("#FBC02D", "#212121"),  # yellow, dark glyph
        ("#9E9E9E", "#212121"),  # grey, dark glyph
        ("#1565C0", "#FFFFFF"),  # blue, white glyph
        ("#37474F", "#FFFFFF"),  # dark slate, white glyph
    ],
)
def test_glyph_contrast(color: str, glyph: str) -> None:
    """The glyph color is chosen for contrast."""
    assert (
        f'path transform="translate(10 10) scale(1.1667)" fill="{glyph}"'
        in render_svg("mix", color)
    )


def test_render_invalid_color_falls_back() -> None:
    """Invalid colors fall back to the default and cannot inject markup."""
    svg = render_svg("szklo", '"/><script>')
    assert "<script>" not in svg
    assert FRACTIONS["szklo"].color in svg
