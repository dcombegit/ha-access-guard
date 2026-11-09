"""Turn user agents and refresh tokens into readable device names."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.auth.models import RefreshToken

APP_CLIENT_IDS = {
    "https://home-assistant.io/iOS": "iOS/macOS",
    "https://home-assistant.io/android": "Android",
}

_OS_RULES: tuple[tuple[str, str], ...] = (
    ("iPad", "iPad"),
    ("iPhone", "iPhone"),
    ("Windows NT", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Macintosh", "macOS"),
    ("Linux", "Linux"),
)

_BROWSER_RULES: tuple[tuple[str, str], ...] = (
    ("Fully Kiosk", "Fully Kiosk"),
    ("FKB/", "Fully Kiosk"),
    ("Edg/", "Edge"),
    ("EdgA/", "Edge"),
    ("EdgiOS/", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)

_APP_UA = re.compile(r"Home ?Assistant/", re.IGNORECASE)


def client_kind(token: RefreshToken | None, user_agent: str | None) -> str:
    """Return the kind of client: app, browser, token or unknown."""
    if token is not None:
        if token.token_type == "long_lived_access_token":
            return "token"
        if token.client_id in APP_CLIENT_IDS:
            return "app"
    if user_agent and _APP_UA.search(user_agent):
        return "app"
    if user_agent and user_agent.startswith("Mozilla/"):
        return "browser"
    return "unknown"


def describe_device(token: RefreshToken | None, user_agent: str | None) -> str:
    """Return a short human readable description of the client device."""
    ua = user_agent or ""
    kind = client_kind(token, ua)

    if kind == "token":
        name = token.client_name if token is not None else None
        return f"API-Token „{name}“" if name else "API-Token"

    os_name = next((name for needle, name in _OS_RULES if needle in ua), None)
    if "Shelly" in ua:
        os_name = "Shelly"

    if kind == "app":
        platform = os_name
        if platform is None and token is not None:
            platform = APP_CLIENT_IDS.get(token.client_id or "")
        return f"Companion-App · {platform}" if platform else "Companion-App"

    browser = next((name for needle, name in _BROWSER_RULES if needle in ua), None)
    if browser == "Chrome" and "; wv)" in ua:
        browser = "WebView"

    parts = [part for part in (browser, os_name) if part]
    if parts:
        return " · ".join(parts)
    if ua:
        return ua[:60]
    return "Unbekannt"
