"""Constants for Access Guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

DOMAIN: Final = "access_guard"
VERSION: Final = "1.0.0"

# Options
CONF_USERS: Final = "users"
CONF_BLOCKED_AREAS: Final = "blocked_areas"
CONF_BLOCKED_DASHBOARDS: Final = "blocked_dashboards"
CONF_HIDDEN_PANELS: Final = "hidden_panels"
CONF_HIDDEN_ENTITIES: Final = "hidden_entities"
CONF_LOG_SESSIONS: Final = "log_sessions"
CONF_LOG_LOGINS: Final = "log_logins"
CONF_LOG_DENIED: Final = "log_denied"
CONF_RETENTION_DAYS: Final = "retention_days"

DEFAULT_RETENTION_DAYS: Final = 30
DEFAULT_OPTIONS: Final[dict] = {
    CONF_USERS: {},
    CONF_LOG_SESSIONS: True,
    CONF_LOG_LOGINS: True,
    CONF_LOG_DENIED: True,
    CONF_RETENTION_DAYS: DEFAULT_RETENTION_DAYS,
}

# Admin panel
PANEL_URL_PATH: Final = "access-guard"
PANEL_COMPONENT: Final = "access-guard-panel"
STATIC_URL: Final = "/access_guard_static"

# Log
STORAGE_KEY: Final = f"{DOMAIN}.log"
STORAGE_VERSION: Final = 1
MAX_LOG_ENTRIES: Final = 5000
DENIED_DEDUP_SECONDS: Final = 300

MEDIA_SOURCE_PREFIX: Final = "media-source://"

# Panels that are never offered for hiding
UNHIDEABLE_PANELS: Final = frozenset({"profile", "notfound", "my", PANEL_URL_PATH})


@dataclass(frozen=True, slots=True)
class AreaDef:
    """A restrictable area of Home Assistant."""

    key: str
    panels: tuple[str, ...] = ()
    dashboards: tuple[str, ...] = ()
    ws_prefixes: tuple[str, ...] = ()
    ws_commands: tuple[str, ...] = ()
    http_prefixes: tuple[str, ...] = ()
    entity_domains: tuple[str, ...] = ()
    media_sources: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict, hash=False, compare=False)


AREAS: Final[dict[str, AreaDef]] = {
    area.key: area
    for area in (
        AreaDef(
            key="media",
            panels=("media-browser",),
            ws_prefixes=("media_source/",),
            ws_commands=("media_player/browse_media", "media_player/search_media"),
            http_prefixes=("/media/",),
            labels={"de": "Medien", "en": "Media"},
        ),
        AreaDef(
            key="cameras",
            ws_prefixes=("camera/",),
            http_prefixes=(
                "/api/camera_proxy/",
                "/api/camera_proxy_stream/",
                "/api/unifiprotect/",
            ),
            entity_domains=("camera",),
            media_sources=("camera", "unifiprotect"),
            labels={"de": "Kameras", "en": "Cameras"},
        ),
        AreaDef(
            key="energy",
            panels=("energy",),
            ws_prefixes=("energy/",),
            labels={"de": "Energie", "en": "Energy"},
        ),
        AreaDef(
            key="history",
            panels=("history",),
            ws_prefixes=("history/",),
            http_prefixes=("/api/history/",),
            labels={"de": "Verlauf", "en": "History"},
        ),
        AreaDef(
            key="logbook",
            panels=("logbook",),
            ws_prefixes=("logbook/",),
            http_prefixes=("/api/logbook",),
            labels={"de": "Logbuch", "en": "Logbook"},
        ),
        AreaDef(
            key="map",
            panels=("map",),
            dashboards=("map",),
            entity_domains=("person", "device_tracker"),
            labels={"de": "Karte & Standorte", "en": "Map & locations"},
        ),
        AreaDef(
            key="todo",
            panels=("todo",),
            ws_prefixes=("todo/",),
            entity_domains=("todo",),
            labels={"de": "To-do-Listen", "en": "To-do lists"},
        ),
        AreaDef(
            key="calendar",
            panels=("calendar",),
            ws_prefixes=("calendar/",),
            http_prefixes=("/api/calendars",),
            entity_domains=("calendar",),
            labels={"de": "Kalender", "en": "Calendar"},
        ),
    )
}

# Areas whose blocked websocket calls are not logged: dashboards and dialogs call
# them automatically, so they would only add noise (direct HTTP access is still logged)
QUIET_AREAS: Final = frozenset(
    {"energy", "history", "logbook", "map", "todo", "calendar"}
)

# Websocket commands that need inspection even without a matching prefix
WS_PANELS: Final = "get_panels"
WS_LOVELACE_CONFIG: Final = "lovelace/config"
WS_MEDIA_COMMANDS: Final = frozenset(
    {
        "media_source/browse_media",
        "media_source/search_media",
        "media_source/resolve_media",
        "media_player/browse_media",
        "media_player/search_media",
    }
)

GUARDED_WS_PREFIXES: Final = tuple(
    sorted({prefix for area in AREAS.values() for prefix in area.ws_prefixes})
)
GUARDED_WS_COMMANDS: Final = frozenset(
    {WS_PANELS, WS_LOVELACE_CONFIG, *WS_MEDIA_COMMANDS}
    | {cmd for area in AREAS.values() for cmd in area.ws_commands}
)
GUARDED_HTTP_PREFIXES: Final = tuple(
    sorted({prefix for area in AREAS.values() for prefix in area.http_prefixes})
)
LOGIN_FLOW_PATH: Final = "/auth/login_flow/"

# Sidebar names of built-in panels (frontend translates them, the backend has no title)
PANEL_TITLES: Final[dict[str, dict[str, str]]] = {
    "lovelace": {"de": "Übersicht", "en": "Overview"},
    "home": {"de": "Zuhause", "en": "Home"},
    "light": {"de": "Licht", "en": "Lights"},
    "security": {"de": "Sicherheit", "en": "Security"},
    "climate": {"de": "Klima", "en": "Climate"},
    "maintenance": {"de": "Wartung", "en": "Maintenance"},
    "energy": {"de": "Energie", "en": "Energy"},
    "map": {"de": "Karte", "en": "Map"},
    "logbook": {"de": "Logbuch", "en": "Logbook"},
    "history": {"de": "Verlauf", "en": "History"},
    "media-browser": {"de": "Medien", "en": "Media"},
    "todo": {"de": "To-do-Listen", "en": "To-do lists"},
    "calendar": {"de": "Kalender", "en": "Calendar"},
    "config": {"de": "Einstellungen", "en": "Settings"},
    "developer-tools": {"de": "Entwicklerwerkzeuge", "en": "Developer tools"},
}


def lang_of(language: str | None) -> str:
    """Return de or en."""
    return "de" if (language or "").lower().startswith("de") else "en"
