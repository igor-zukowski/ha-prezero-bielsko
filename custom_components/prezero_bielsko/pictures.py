"""Colored fraction pictures rendered as SVG.

Glyphs come from Material Design Icons (https://pictogrammers.com),
licensed under the Apache License 2.0.
"""

from __future__ import annotations

from functools import lru_cache
import re

from .const import FRACTIONS, UNKNOWN_FRACTION_COLOR

_HEX_COLOR_RE = re.compile(r"#?([0-9a-fA-F]{6})")
_DARK_GLYPH = "#212121"
_DARK_GLYPH_LUMINANCE = 0.0152

_GLYPHS: dict[str, str] = {
    "resztkowe": (
        "M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6"
        "M9,8V17H11V8H9M13,8V17H15V8H13Z"
    ),
    "kuchenne": (
        "M20,10C18.58,7.57 15.5,6.69 13,8V3H11V8C8.5,6.69 5.42,7.57 4,10C2,13 7,22 9,22"
        "C11,22 11,21 12,21C13,21 13,22 15,22C17,22 22,13 20,10M18.25,13.38C17.63,15.85 "
        "16.41,18.12 14.7,20C14.5,20 14.27,19.9 14.1,19.75C12.87,18.76 11.13,18.76 9.9,"
        "19.75C9.73,19.9 9.5,20 9.3,20C7.59,18.13 6.36,15.85 5.75,13.39C5.5,12.66 5.45,"
        "11.87 5.66,11.12C6.24,10.09 7.32,9.43 8.5,9.4C9.06,9.41 9.61,9.54 10.11,9.79L11,"
        "10.24H13L13.89,9.79C14.39,9.54 14.94,9.41 15.5,9.4C16.68,9.43 17.76,10.08 18.34,"
        "11.11C18.55,11.86 18.5,12.65 18.25,13.38M11,5C5.38,8.07 4.11,3.78 4.11,3.78C4.11,"
        "3.78 6.77,0.19 11,5Z"
    ),
    "mix": (
        "M10 2V4H10.91C10.65 5.79 9 7.5 8 9V13.77C9.32 14.96 9.32 17.04 8 18.23V20C8 21.11"
        " 8.9 22 10 22H14C15.11 22 16 21.11 16 20V18.23C14.68 17.04 14.68 14.96 16 13.77V9"
        "C15 7.5 13.35 5.79 13.09 4H14V2M12 6.5C12.24 7 13.54 8.5 13.9 8.91L14 9V13C13.35 "
        "13.87 13 14.92 13 16C13 17.08 13.35 18.13 14 19V20H10V19C10.65 18.13 11 17.08 11 "
        "16C11 14.92 10.65 13.87 10 13V9L10.1 8.91C10.46 8.5 11.76 7 12 6.5Z"
    ),
    "makulatura": (
        "M20 5L20 19L4 19L4 5H20M20 3H4C2.89 3 2 3.89 2 5V19C2 20.11 2.89 21 4 21H20C21.11"
        " 21 22 20.11 22 19V5C22 3.89 21.11 3 20 3M18 15H6V17H18V15M10 7H6V13H10V7M12 9H18"
        "V7H12V9M18 11H12V13H18V11Z"
    ),
    "szklo": (
        "M11.5 2C11.22 2 11 2.22 11 2.5V7C10.93 7 10.85 7 10.78 7.03C9.82 7.27 9.21 8 8.76"
        " 8.89C8.3 9.76 8 10.84 8 12C8.05 15 8 18.03 8 21C8 21.55 8.45 22 9 22C11 22 13 22"
        " 15 22C15.55 22 16 21.55 16 21C16.04 18 16 15 16 12C16 10.84 15.74 9.76 15.28 8.88"
        "C14.83 8 14.22 7.27 13.26 7.04C13.18 7 13.05 7 13 7V2.5C13 2.22 12.78 2 12.5 2M12"
        " 8.85C12.32 8.85 12.63 8.9 12.78 9C12.85 9.03 13.2 9.26 13.5 9.81C13.78 10.37 14 "
        "11.17 14 12V20H10V12C10 11.17 10.22 10.37 10.5 9.81C10.8 9.26 11.15 9.03 11.22 9"
        "C11.36 8.9 11.68 8.85 12 8.85Z"
    ),
    "zielone": (
        "M17,8C8,10 5.9,16.17 3.82,21.34L5.71,22L6.66,19.7C7.14,19.87 7.64,20 8,20C19,20 "
        "22,3 22,3C21,5 14,5.25 9,6.25C4,7.25 2,11.5 2,13.5C2,15.5 3.75,17.25 3.75,17.25C7,"
        "8 17,8 17,8Z"
    ),
    "popiol": (
        "M22,22H2V20H22V22M22,6H2V3H22V6M20,7V19H17V11C17,11 14.5,10 12,10C9.5,10 7,11 7,"
        "11V19H4V7H20M14.5,14.67H14.47L14.81,15.22L14.87,15.34C15.29,16.35 15,17.5 14.21,"
        "18.24C13.5,18.9 12.5,19.07 11.58,18.95C10.71,18.84 9.9,18.29 9.45,17.53C9.3,17.3 "
        "9.19,17.03 9.13,16.77L9,16.11C8.96,15.15 9.34,14.14 10.06,13.54C9.73,14.26 9.81,"
        "15.16 10.3,15.79L10.36,15.87C10.44,15.94 10.55,15.97 10.64,15.92C10.73,15.89 10.8,"
        "15.8 10.8,15.7L10.76,15.56C10.23,14.17 10.68,12.55 11.79,11.63C12.1,11.38 12.5,"
        "11.15 12.87,11.05C12.46,11.87 12.61,12.93 13.25,13.57L14.14,14.3L14.5,14.67M13.11,"
        "17.44V17.44C13.37,17.2 13.53,16.8 13.5,16.44V16.25C13.38,15.65 12.85,15.46 12.5,15"
        "L12.26,14.55C12.13,14.85 12.12,15.13 12.17,15.46C12.23,15.8 12.37,16.09 12.29,16.44"
        "C12.2,16.83 11.9,17.22 11.37,17.35C11.67,17.64 12.15,17.87 12.64,17.71L13.11,17.44Z"
    ),
    "gabaryty": (
        "M21 9V7C21 5.35 19.65 4 18 4H14C13.23 4 12.53 4.3 12 4.78C11.47 4.3 10.77 4 10 4"
        "H6C4.35 4 3 5.35 3 7V9C1.35 9 0 10.35 0 12V17C0 18.65 1.35 20 3 20V22H5V20H19V22"
        "H21V20C22.65 20 24 18.65 24 17V12C24 10.35 22.65 9 21 9M14 6H18C18.55 6 19 6.45 "
        "19 7V9.78C18.39 10.33 18 11.12 18 12V14H13V7C13 6.45 13.45 6 14 6M5 7C5 6.45 5.45"
        " 6 6 6H10C10.55 6 11 6.45 11 7V14H6V12C6 11.12 5.61 10.33 5 9.78V7M22 17C22 17.55"
        " 21.55 18 21 18H3C2.45 18 2 17.55 2 17V12C2 11.45 2.45 11 3 11S4 11.45 4 12V16H20"
        "V12C20 11.45 20.45 11 21 11S22 11.45 22 12V17Z"
    ),
}
_FALLBACK_GLYPH = (
    "M21.82,15.42L19.32,19.75C18.83,20.61 17.92,21.06 17,21H15V23L12.5,18.5L15,14V16H17.82"
    "L15.6,12.15L19.93,9.65L21.73,12.77C22.25,13.54 22.32,14.57 21.82,15.42M9.21,3.06H14.21"
    "C15.19,3.06 16.04,3.63 16.45,4.45L17.45,6.19L19.18,5.19L16.54,9.6L11.39,9.69L13.12,"
    "8.69L11.71,6.24L9.5,10.09L5.16,7.59L6.96,4.47C7.37,3.64 8.22,3.06 9.21,3.06M5.05,19.76"
    "L2.55,15.43C2.06,14.58 2.13,13.56 2.64,12.79L3.64,11.06L1.91,10.06L7.05,10.14L9.7,"
    "14.56L7.97,13.56L6.56,16H11V21H7.4C6.47,21.07 5.55,20.61 5.05,19.76Z"
)


def normalize_color(value: object, default: str) -> str:
    """Return a color as ``#RRGGBB`` from a hex string or an RGB list."""
    if isinstance(value, str) and (match := _HEX_COLOR_RE.fullmatch(value.strip())):
        return f"#{match.group(1).upper()}"
    if (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(isinstance(part, int) and 0 <= part <= 255 for part in value)
    ):
        return "#{:02X}{:02X}{:02X}".format(*value)
    return default


def hex_to_rgb(color: str) -> list[int]:
    """Convert ``#RRGGBB`` to an RGB list."""
    value = color.lstrip("#")
    return [int(value[i : i + 2], 16) for i in (0, 2, 4)]


def default_color(fraction: str) -> str:
    """Return the default color of a fraction."""
    info = FRACTIONS.get(fraction)
    return info.color if info else UNKNOWN_FRACTION_COLOR


def _glyph_color(background: str) -> str:
    """Return a glyph color readable on the given background."""
    red, green, blue = (
        channel / 255
        if channel / 255 <= 0.03928
        else ((channel / 255 + 0.055) / 1.055) ** 2.4
        for channel in hex_to_rgb(background)
    )
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    # Pick the glyph color with the higher WCAG contrast ratio.
    white_contrast = 1.05 / (luminance + 0.05)
    dark_contrast = (luminance + 0.05) / (_DARK_GLYPH_LUMINANCE + 0.05)
    return _DARK_GLYPH if dark_contrast > white_contrast else "#FFFFFF"


@lru_cache(maxsize=64)
def render_svg(fraction: str, color: str) -> str:
    """Render a round colored picture of a fraction."""
    background = normalize_color(color, default_color(fraction))
    glyph = _GLYPHS.get(fraction, _FALLBACK_GLYPH)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
        f'<circle cx="24" cy="24" r="24" fill="{background}"/>'
        f'<path transform="translate(10 10) scale(1.1667)" fill="{_glyph_color(background)}"'
        f' d="{glyph}"/></svg>'
    )
