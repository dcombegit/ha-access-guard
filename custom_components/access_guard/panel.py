"""Admin panel and websocket API of Access Guard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import (
    AREAS,
    CONF_BLOCKED_AREAS,
    CONF_BLOCKED_DASHBOARDS,
    CONF_HIDDEN_ENTITIES,
    CONF_HIDDEN_PANELS,
    CONF_LOG_DENIED,
    CONF_LOG_LOGINS,
    CONF_LOG_SESSIONS,
    CONF_RETENTION_DAYS,
    CONF_USERS,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
    lang_of,
)
from .devices import client_kind, describe_device
from .helpers import panel_title

if TYPE_CHECKING:
    from homeassistant.auth.models import RefreshToken
    from homeassistant.components.websocket_api import ActiveConnection

    from . import AccessGuardRuntime

FRONTEND_DIR = Path(__file__).parent / "frontend"
DATA_STATIC_REGISTERED = f"{DOMAIN}_static_registered"
DATA_WS_REGISTERED = f"{DOMAIN}_ws_registered"


def _iso(value: Any) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the admin panel and its websocket commands."""
    if not hass.data.get(DATA_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[DATA_STATIC_REGISTERED] = True

    if not hass.data.get(DATA_WS_REGISTERED):
        websocket_api.async_register_command(hass, ws_overview)
        websocket_api.async_register_command(hass, ws_revoke_token)
        websocket_api.async_register_command(hass, ws_set_label)
        websocket_api.async_register_command(hass, ws_clear_log)
        hass.data[DATA_WS_REGISTERED] = True

    title = "Zugriffe" if lang_of(hass.config.language) == "de" else "Access"
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=title,
        sidebar_icon="mdi:shield-account",
        module_url=f"{STATIC_URL}/access-guard-panel.js?v={VERSION}",
        require_admin=True,
        config={},
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the admin panel."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


@callback
def _runtime(hass: HomeAssistant) -> AccessGuardRuntime | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _token_info(
    token: RefreshToken,
    labels: dict[str, str],
    current_id: str | None,
    seen_devices: dict[str, str],
) -> dict[str, Any]:
    kind = client_kind(token, None)
    device = describe_device(token, None)
    if kind != "token" and token.id in seen_devices:
        # The user agent of the last session tells more than the token
        device = seen_devices[token.id]
    return {
        "id": token.id,
        "type": token.token_type,
        "client_id": token.client_id,
        "client_name": token.client_name,
        "kind": kind,
        "device": device,
        "label": labels.get(token.id),
        "created_at": _iso(token.created_at),
        "last_used_at": _iso(token.last_used_at),
        "last_used_ip": token.last_used_ip,
        "current": token.id == current_id,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/overview",
        vol.Optional("limit", default=1000): vol.All(int, vol.Range(min=1, max=5000)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_overview(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return users, devices, restrictions and the access log."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Access Guard is not loaded")
        return

    options = runtime.entry.options
    user_options: dict[str, Any] = options.get(CONF_USERS) or {}
    access_log = runtime.access_log
    seen_devices: dict[str, str] = {}
    for entry in access_log.entries:
        if entry.get("type") == "session" and entry.get("token_id"):
            seen_devices[entry["token_id"]] = entry["device"]
    users = []
    for user in await hass.auth.async_get_users():
        if user.system_generated:
            continue
        restrictions = user_options.get(user.id) or {}
        users.append(
            {
                "id": user.id,
                "name": user.name,
                "is_admin": user.is_admin,
                "is_owner": user.is_owner,
                "is_active": user.is_active,
                "local_only": user.local_only,
                "restrictions": {
                    "areas": restrictions.get(CONF_BLOCKED_AREAS, []),
                    "dashboards": restrictions.get(CONF_BLOCKED_DASHBOARDS, []),
                    "panels": restrictions.get(CONF_HIDDEN_PANELS, []),
                    "entities": restrictions.get(CONF_HIDDEN_ENTITIES, []),
                },
                "tokens": sorted(
                    (
                        _token_info(
                            token,
                            access_log.labels,
                            connection.refresh_token_id,
                            seen_devices,
                        )
                        for token in user.refresh_tokens.values()
                        if token.token_type != "system"
                    ),
                    key=lambda item: item["last_used_at"] or item["created_at"] or "",
                    reverse=True,
                ),
            }
        )

    lang = lang_of(hass.config.language)
    panel_ids = {
        value
        for item in users
        for value in item["restrictions"]["panels"] + item["restrictions"]["dashboards"]
    }
    open_ids = access_log.open_session_ids
    entries = [
        {**entry, "open": entry["id"] in open_ids}
        for entry in reversed(access_log.entries[-msg["limit"] :])
    ]
    connection.send_result(
        msg["id"],
        {
            "version": runtime.version,
            "entry_id": runtime.entry.entry_id,
            "users": users,
            "entries": entries,
            "labels": access_log.labels,
            "areas": {key: area.labels.get(lang, key) for key, area in AREAS.items()},
            "panels": {url_path: panel_title(hass, url_path) for url_path in panel_ids},
            "settings": {
                "log_sessions": options.get(CONF_LOG_SESSIONS, True),
                "log_logins": options.get(CONF_LOG_LOGINS, True),
                "log_denied": options.get(CONF_LOG_DENIED, True),
                "retention_days": options.get(
                    CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                ),
            },
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/revoke_token", vol.Required("token_id"): str}
)
@websocket_api.require_admin
@callback
def ws_revoke_token(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Log a device out by deleting its refresh token."""
    token = hass.auth.async_get_refresh_token(msg["token_id"])
    if token is None or token.token_type == "system":
        connection.send_error(msg["id"], "not_found", "Token not found")
        return
    hass.auth.async_remove_refresh_token(token)
    if (runtime := _runtime(hass)) is not None:
        runtime.access_log.async_set_label(msg["token_id"], None)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_label",
        vol.Required("token_id"): str,
        vol.Optional("label"): vol.Any(None, vol.All(str, vol.Length(max=60))),
    }
)
@websocket_api.require_admin
@callback
def ws_set_label(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Give a device a readable name."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "Access Guard is not loaded")
        return
    runtime.access_log.async_set_label(msg["token_id"], msg.get("label"))
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/clear_log"})
@websocket_api.require_admin
@callback
def ws_clear_log(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete the access log."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "Access Guard is not loaded")
        return
    runtime.access_log.async_clear()
    connection.send_result(msg["id"])
