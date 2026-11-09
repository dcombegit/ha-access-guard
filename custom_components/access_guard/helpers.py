"""Small helpers shared by the options flow and the panel."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import PANEL_TITLES, lang_of

DATA_PANELS = "frontend_panels"
DATA_PANELS_CONFIG = "frontend_panels_config"


def panels(hass: HomeAssistant) -> dict[str, Any]:
    """Return the registered frontend panels."""
    return hass.data.get(DATA_PANELS, {}) or {}


def panel_override(hass: HomeAssistant, url_path: str) -> dict[str, Any]:
    """Return the sidebar overrides (title, admin only, …) of a panel."""
    return (hass.data.get(DATA_PANELS_CONFIG, {}) or {}).get(url_path) or {}


def panel_title(hass: HomeAssistant, url_path: str) -> str:
    """Return a readable title for a panel or dashboard."""
    panel = panels(hass).get(url_path)
    title = panel_override(hass, url_path).get("title") or getattr(
        panel, "sidebar_title", None
    )
    if not title and url_path in PANEL_TITLES:
        title = PANEL_TITLES[url_path][lang_of(hass.config.language)]
    return title or url_path
