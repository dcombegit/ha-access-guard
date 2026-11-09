"""Persistent log of logins, sessions and blocked access attempts."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LOG_DENIED,
    CONF_LOG_LOGINS,
    CONF_LOG_SESSIONS,
    CONF_RETENTION_DAYS,
    DEFAULT_RETENTION_DAYS,
    DENIED_DEDUP_SECONDS,
    DOMAIN,
    MAX_LOG_ENTRIES,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .devices import client_kind, describe_device

if TYPE_CHECKING:
    from aiohttp.web import Request

    from homeassistant.auth.models import RefreshToken, User
    from homeassistant.components.websocket_api import ActiveConnection

_LOGGER = logging.getLogger(__name__)

EVENT_LOGIN = f"{DOMAIN}_login"
EVENT_DENIED = f"{DOMAIN}_denied"

SAVE_DELAY = 15
NEW_LOGIN_WINDOW = timedelta(seconds=120)
UA_MAX_LEN = 300


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _now() -> str:
    return _iso(dt_util.utcnow())


class AccessLog:
    """Keep a rolling log of who used Home Assistant from which device."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        """Initialize the log."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, private=True, atomic_writes=True
        )
        self._options = options
        self.entries: list[dict[str, Any]] = []
        self.labels: dict[str, str] = {}
        self._open_sessions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ storage

    async def async_load(self) -> None:
        """Load the log from disk."""
        data = await self._store.async_load() or {}
        self.entries = list(data.get("entries", []))
        self.labels = dict(data.get("labels", {}))
        for entry in self.entries:
            if entry.get("type") == "session" and not entry.get("end"):
                # Home Assistant stopped without closing the session
                entry["end"] = entry["time"]
                entry["end_unknown"] = True
        self._prune()

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {"entries": self.entries, "labels": self.labels}

    @callback
    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_shutdown(self) -> None:
        """Close open sessions and write the log."""
        now = _now()
        for entry in self._open_sessions.values():
            entry["end"] = now
        self._open_sessions.clear()
        await self._store.async_save(self._data_to_save())

    @callback
    def update_options(self, options: dict[str, Any]) -> None:
        """Apply new options."""
        self._options = options
        self._prune()
        self._schedule_save()

    @callback
    def _prune(self) -> None:
        days = int(self._options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))
        cutoff = _iso(dt_util.utcnow() - timedelta(days=days))
        open_ids = set(self._open_sessions)
        self.entries = [
            entry
            for entry in self.entries
            if entry["id"] in open_ids
            or (entry.get("end") or entry.get("last") or entry["time"]) >= cutoff
        ]
        if len(self.entries) > MAX_LOG_ENTRIES:
            self.entries = self.entries[-MAX_LOG_ENTRIES:]

    @callback
    def _append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)
        if len(self.entries) > MAX_LOG_ENTRIES + 100:
            self._prune()
        self._schedule_save()

    @callback
    def async_clear(self) -> None:
        """Delete all entries (open sessions are kept)."""
        open_ids = set(self._open_sessions)
        self.entries = [entry for entry in self.entries if entry["id"] in open_ids]
        self._schedule_save()

    @callback
    def async_set_label(self, token_id: str, label: str | None) -> None:
        """Give a device (refresh token) a readable name."""
        if label:
            self.labels[token_id] = label.strip()[:60]
        else:
            self.labels.pop(token_id, None)
        self._schedule_save()

    # ----------------------------------------------------------------- sessions

    @callback
    def async_session_started(
        self, connection: ActiveConnection, request: Request | None
    ) -> None:
        """Record a new websocket session (= frontend or app opened)."""
        if not self._options.get(CONF_LOG_SESSIONS, True):
            return
        user: User = connection.user
        token = (
            self.hass.auth.async_get_refresh_token(connection.refresh_token_id)
            if connection.refresh_token_id
            else None
        )
        user_agent = request.headers.get("User-Agent") if request is not None else None
        now = dt_util.utcnow()
        entry = {
            "id": uuid4().hex,
            "type": "session",
            "time": _iso(now),
            "end": None,
            "user_id": user.id,
            "user": user.name,
            "ip": connection.remote
            or (request.remote if request is not None else None),
            "device": describe_device(token, user_agent),
            "client": client_kind(token, user_agent),
            "ua": (user_agent or "")[:UA_MAX_LEN],
            "token_id": token.id if token else None,
            "new_login": bool(
                token is not None
                and token.token_type == "normal"
                and now - token.created_at < NEW_LOGIN_WINDOW
                and not any(e.get("token_id") == token.id for e in self.entries[-200:])
            ),
        }
        self._open_sessions[entry["id"]] = entry
        self._append(entry)

        @callback
        def _closed() -> None:
            if self._open_sessions.pop(entry["id"], None) is not None:
                entry["end"] = _now()
                self._schedule_save()

        # Subscriptions are called when the connection closes
        connection.subscriptions[(DOMAIN, entry["id"])] = _closed

    @property
    def open_session_ids(self) -> set[str]:
        """Return ids of sessions that are currently open."""
        return set(self._open_sessions)

    # ------------------------------------------------------------------- logins

    @callback
    def async_login_attempt(
        self,
        *,
        success: bool,
        username: str | None,
        user: User | None,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        """Record a login through the login form."""
        if not self._options.get(CONF_LOG_LOGINS, True):
            return
        entry = {
            "id": uuid4().hex,
            "type": "login" if success else "login_failed",
            "time": _now(),
            "user_id": user.id if user else None,
            "user": user.name if user else None,
            "username": (username or "")[:100] or None,
            "ip": ip,
            "device": describe_device(None, user_agent),
            "ua": (user_agent or "")[:UA_MAX_LEN],
        }
        self._append(entry)
        self.hass.bus.async_fire(
            EVENT_LOGIN,
            {
                "success": success,
                "user_id": entry["user_id"],
                "user": entry["user"],
                "username": entry["username"],
                "ip": ip,
                "device": entry["device"],
            },
        )

    # ------------------------------------------------------------------- denied

    @callback
    def async_denied(
        self,
        user: User,
        *,
        area: str,
        detail: str,
        ip: str | None,
        user_agent: str | None,
        token: RefreshToken | None = None,
    ) -> None:
        """Record a blocked access attempt."""
        if not self._options.get(CONF_LOG_DENIED, True):
            return
        now = dt_util.utcnow()
        dedup_after = _iso(now - timedelta(seconds=DENIED_DEDUP_SECONDS))
        for entry in reversed(self.entries[-100:]):
            if (
                entry["type"] == "denied"
                and entry["user_id"] == user.id
                and entry["area"] == area
                and entry["last"] >= dedup_after
            ):
                entry["count"] += 1
                entry["last"] = _iso(now)
                if detail not in entry["details"] and len(entry["details"]) < 10:
                    entry["details"].append(detail)
                self._schedule_save()
                return

        entry = {
            "id": uuid4().hex,
            "type": "denied",
            "time": _iso(now),
            "last": _iso(now),
            "count": 1,
            "user_id": user.id,
            "user": user.name,
            "area": area,
            "details": [detail],
            "ip": ip,
            "device": describe_device(token, user_agent),
            "ua": (user_agent or "")[:UA_MAX_LEN],
        }
        self._append(entry)
        self.hass.bus.async_fire(
            EVENT_DENIED,
            {
                "user_id": user.id,
                "user": user.name,
                "area": area,
                "detail": detail,
                "ip": ip,
                "device": entry["device"],
            },
        )
