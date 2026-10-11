"""Constants for the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Final

DOMAIN: Final = "prezero_bielsko"

CITY: Final = "Bielsko-Biała"
API_URL: Final = "https://prezero-bielsko.pl/harmonogramy/index.php"
SCHEDULE_URL: Final = "https://prezero-bielsko.pl/harmonogram-odbioru-odpadow/"

CONF_STREET: Final = "street"
CONF_NUMBER: Final = "number"
CONF_SYMBOL: Final = "symbol"

CONF_LANGUAGE: Final = "language"
CONF_REFRESH_INTERVAL: Final = "refresh_interval"
CONF_REMINDER_START: Final = "reminder_start"
CONF_REMINDER_END: Final = "reminder_end"
CONF_COLORED_PICTURES: Final = "colored_pictures"
CONF_DAYS_PREFIX: Final = "days_"
CONF_COLOR_PREFIX: Final = "color_"

SECTION_REFRESH: Final = "refresh"
SECTION_REMINDERS: Final = "reminders"
SECTION_APPEARANCE: Final = "appearance"

REFRESH_DAILY: Final = "daily"
REFRESH_WEEKLY: Final = "weekly"
REFRESH_MONTHLY: Final = "monthly"
REFRESH_INTERVALS: Final[dict[str, timedelta]] = {
    REFRESH_DAILY: timedelta(days=1),
    REFRESH_WEEKLY: timedelta(days=7),
    REFRESH_MONTHLY: timedelta(days=30),
}

LANGUAGE_AUTO: Final = "auto"
LANGUAGES: Final = ("pl", "en", LANGUAGE_AUTO)
DEFAULT_LANGUAGE: Final = "pl"
DEVICE_MODELS: Final = {
    "pl": "Harmonogram odbioru odpadów",
    "en": "Waste collection schedule",
}

DEFAULT_REFRESH_INTERVAL: Final = REFRESH_DAILY
DEFAULT_REMINDER_DAYS: Final = 1
DEFAULT_REMINDER_START: Final = time(18, 0)
DEFAULT_REMINDER_END: Final = time(10, 0)
DEFAULT_COLORED_PICTURES: Final = True
MAX_REMINDER_DAYS: Final = 14

# Retry delays after failed downloads, capped by the configured refresh interval.
RETRY_DELAYS: Final = (
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=4),
    timedelta(hours=6),
)
# A repair issue is raised when downloads keep failing for this long.
FETCH_FAILED_ISSUE_AFTER: Final = timedelta(days=1)
FETCH_FAILED_ISSUE_MIN_FAILURES: Final = 3

STORAGE_VERSION: Final = 1

ISSUE_FETCH_FAILED: Final = "fetch_failed"
ISSUE_SCHEDULE_MISSING: Final = "schedule_missing"
ISSUE_ADDRESS_NOT_FOUND: Final = "address_not_found"
ISSUES: Final = (ISSUE_FETCH_FAILED, ISSUE_SCHEDULE_MISSING, ISSUE_ADDRESS_NOT_FOUND)

EVENT_SCHEDULE_UPDATED: Final = f"{DOMAIN}_schedule_updated"

SERVICE_GET_SCHEDULE: Final = "get_schedule"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_DAYS: Final = "days"

ICON_URL: Final = f"/api/{DOMAIN}/icon"

UNKNOWN_FRACTION_ICON: Final = "mdi:recycle"
UNKNOWN_FRACTION_COLOR: Final = "#607D8B"


@dataclass(frozen=True, slots=True)
class FractionInfo:
    """Static metadata of a waste fraction."""

    key: str
    name: str
    icon: str
    color: str


# Order defines the order of entities and option fields.
FRACTIONS: Final[dict[str, FractionInfo]] = {
    info.key: info
    for info in (
        FractionInfo("resztkowe", "Zmieszane", "mdi:trash-can-outline", "#37474F"),
        FractionInfo("kuchenne", "Bio", "mdi:food-apple-outline", "#795548"),
        FractionInfo(
            "mix",
            "Metale i tworzywa sztuczne",
            "mdi:bottle-soda-classic-outline",
            "#FBC02D",
        ),
        FractionInfo(
            "makulatura", "Papier", "mdi:newspaper-variant-outline", "#1565C0"
        ),
        FractionInfo("szklo", "Szkło", "mdi:bottle-wine-outline", "#2E7D32"),
        FractionInfo("zielone", "Zielone", "mdi:leaf", "#7CB342"),
        FractionInfo("popiol", "Popiół", "mdi:fireplace", "#9E9E9E"),
        FractionInfo("gabaryty", "Gabaryty", "mdi:sofa-outline", "#8E24AA"),
    )
}
