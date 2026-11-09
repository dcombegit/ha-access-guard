"""Access Guard: per-user restrictions and an access log for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.auth import EVENT_USER_ADDED, EVENT_USER_UPDATED
from homeassistant.components.websocket_api.connection import current_connection
from homeassistant.components.websocket_api.const import SIGNAL_WEBSOCKET_CONNECTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_COMPONENT_LOADED,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.http import current_request

from .access_log import AccessLog
from .const import DEFAULT_OPTIONS, VERSION
from .guard import AccessGuard
from .panel import async_remove_panel, async_setup_panel

_LOGGER = logging.getLogger(__name__)

RESCAN_INTERVAL = timedelta(minutes=5)


@dataclass
class AccessGuardRuntime:
    """Runtime data of the config entry."""

    entry: ConfigEntry
    guard: AccessGuard
    access_log: AccessLog
    version: str = VERSION


type AccessGuardConfigEntry = ConfigEntry[AccessGuardRuntime]


def _options(entry: ConfigEntry) -> dict:
    return {**DEFAULT_OPTIONS, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: AccessGuardConfigEntry) -> bool:
    """Set up Access Guard from a config entry."""
    access_log = AccessLog(hass, _options(entry))
    await access_log.async_load()
    guard = AccessGuard(hass, _options(entry), access_log)
    await guard.async_start()
    entry.runtime_data = AccessGuardRuntime(entry, guard, access_log)

    @callback
    def _rescan(*_: object) -> None:
        guard.async_wrap_commands()
        guard.async_wrap_routes()

    @callback
    def _websocket_connected() -> None:
        """Called inside the websocket task right after authentication."""
        connection = current_connection.get()
        if connection is None or connection.user is None:
            return
        if connection.user.system_generated:
            return
        _rescan()
        guard.async_ensure_permissions(connection.user)
        access_log.async_session_started(connection, current_request.get())

    async def _user_changed(event: Event) -> None:
        if (user := await hass.auth.async_get_user(event.data["user_id"])) is not None:
            guard.async_ensure_permissions(user)

    async def _stop(_: Event) -> None:
        await access_log.async_shutdown()

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_WEBSOCKET_CONNECTED, _websocket_connected)
    )
    entry.async_on_unload(hass.bus.async_listen(EVENT_COMPONENT_LOADED, _rescan))
    entry.async_on_unload(hass.bus.async_listen(EVENT_HOMEASSISTANT_STARTED, _rescan))
    entry.async_on_unload(hass.bus.async_listen(EVENT_USER_ADDED, _user_changed))
    entry.async_on_unload(hass.bus.async_listen(EVENT_USER_UPDATED, _user_changed))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    entry.async_on_unload(async_track_time_interval(hass, _rescan, RESCAN_INTERVAL))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await async_setup_panel(hass)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: AccessGuardConfigEntry
) -> None:
    """Apply changed options without a reload."""
    runtime = entry.runtime_data
    options = _options(entry)
    runtime.guard.update_options(options)
    runtime.access_log.update_options(options)
    await runtime.guard.async_apply_permissions()
    # Make open frontends fetch the (filtered) sidebar again
    hass.bus.async_fire("panels_updated")


async def async_unload_entry(
    hass: HomeAssistant, entry: AccessGuardConfigEntry
) -> bool:
    """Unload a config entry."""
    async_remove_panel(hass)
    await entry.runtime_data.guard.async_stop()
    await entry.runtime_data.access_log.async_shutdown()
    hass.bus.async_fire("panels_updated")
    return True
