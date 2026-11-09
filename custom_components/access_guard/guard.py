"""Enforce per-user restrictions on panels, websocket commands, HTTP and entities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from homeassistant.auth.permissions import AbstractPermissions
from homeassistant.components import websocket_api
from homeassistant.components.http import KEY_HASS_USER
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.http import current_request

from .const import (
    AREAS,
    CONF_BLOCKED_AREAS,
    CONF_BLOCKED_DASHBOARDS,
    CONF_HIDDEN_ENTITIES,
    CONF_HIDDEN_PANELS,
    CONF_USERS,
    GUARDED_HTTP_PREFIXES,
    GUARDED_WS_COMMANDS,
    GUARDED_WS_PREFIXES,
    LOGIN_FLOW_PATH,
    MEDIA_SOURCE_PREFIX,
    QUIET_AREAS,
    WS_LOVELACE_CONFIG,
    WS_MEDIA_COMMANDS,
    WS_PANELS,
)

if TYPE_CHECKING:
    from aiohttp.web_urldispatcher import AbstractRoute

    from homeassistant.auth.models import User
    from homeassistant.components.websocket_api import ActiveConnection

    from .access_log import AccessLog

_LOGGER = logging.getLogger(__name__)

WRAPPED_MARKER = "__access_guard_original__"
DENIED_MESSAGE = "Zugriff für diesen Benutzer gesperrt (Access Guard)"

type WsHandler = Callable[[HomeAssistant, Any, dict[str, Any]], None]
type HttpHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def media_source_domain(content_id: str | None) -> str | None:
    """Return the media source domain of a media-source:// content id."""
    if not content_id or not content_id.startswith(MEDIA_SOURCE_PREFIX):
        return None
    return content_id[len(MEDIA_SOURCE_PREFIX) :].split("/", 1)[0] or None


@dataclass(slots=True)
class UserRules:
    """Compiled restrictions of one user."""

    blocked_areas: frozenset[str] = frozenset()
    blocked_dashboards: frozenset[str] = frozenset()
    hidden_panels: frozenset[str] = frozenset()
    hidden_entities: frozenset[str] = frozenset()
    hidden_domains: frozenset[str] = frozenset()
    blocked_media_sources: frozenset[str] = frozenset()
    ws_prefixes: dict[str, str] = field(default_factory=dict)
    ws_commands: dict[str, str] = field(default_factory=dict)
    http_prefixes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_options(cls, data: dict[str, Any]) -> UserRules:
        """Compile the rules from the stored options of one user."""
        areas = frozenset(a for a in data.get(CONF_BLOCKED_AREAS, []) if a in AREAS)
        dashboards = set(data.get(CONF_BLOCKED_DASHBOARDS, []))
        panels = set(data.get(CONF_HIDDEN_PANELS, [])) | dashboards
        domains: set[str] = set()
        sources: set[str] = set()
        ws_prefixes: dict[str, str] = {}
        ws_commands: dict[str, str] = {}
        http_prefixes: dict[str, str] = {}
        for key in areas:
            area = AREAS[key]
            panels.update(area.panels)
            dashboards.update(area.dashboards)
            domains.update(area.entity_domains)
            sources.update(area.media_sources)
            ws_prefixes.update(dict.fromkeys(area.ws_prefixes, key))
            ws_commands.update(dict.fromkeys(area.ws_commands, key))
            http_prefixes.update(dict.fromkeys(area.http_prefixes, key))
        return cls(
            blocked_areas=areas,
            blocked_dashboards=frozenset(dashboards),
            hidden_panels=frozenset(panels),
            hidden_entities=frozenset(data.get(CONF_HIDDEN_ENTITIES, [])),
            hidden_domains=frozenset(domains),
            blocked_media_sources=frozenset(sources),
            ws_prefixes=ws_prefixes,
            ws_commands=ws_commands,
            http_prefixes=http_prefixes,
        )

    @property
    def hides_entities(self) -> bool:
        """Return True if entities are hidden for this user."""
        return bool(self.hidden_entities or self.hidden_domains)

    @property
    def is_empty(self) -> bool:
        """Return True if nothing is restricted."""
        return not (
            self.blocked_areas
            or self.blocked_dashboards
            or self.hidden_panels
            or self.hides_entities
        )

    def entity_hidden(self, entity_id: str) -> bool:
        """Return True if the entity must not be visible."""
        return (
            entity_id in self.hidden_entities
            or entity_id.partition(".")[0] in self.hidden_domains
        )

    def ws_denied_area(self, command: str, msg: dict[str, Any]) -> str | None:
        """Return the area that blocks a websocket command, if any."""
        if (area := self.ws_commands.get(command)) is not None:
            return area
        for prefix, area in self.ws_prefixes.items():
            if command.startswith(prefix):
                return area
        if command == WS_LOVELACE_CONFIG:
            url_path = msg.get("url_path") or "lovelace"
            if url_path in self.blocked_dashboards:
                return f"dashboard:{url_path}"
        if (
            command in WS_MEDIA_COMMANDS
            and self.blocked_media_sources
            and media_source_domain(msg.get("media_content_id"))
            in self.blocked_media_sources
        ):
            return "cameras"
        return None

    def http_denied_area(self, path: str) -> str | None:
        """Return the area that blocks an HTTP path, if any."""
        for prefix, area in self.http_prefixes.items():
            if path.startswith(prefix):
                return area
        return None

    def filter_panels(self, panels: Any) -> Any:
        """Remove hidden panels from a get_panels result."""
        if not isinstance(panels, dict) or not self.hidden_panels:
            return panels
        return {
            key: value for key, value in panels.items() if key not in self.hidden_panels
        }

    def filter_media(self, result: Any) -> Any:
        """Remove blocked media sources from a browse result (recursively)."""
        if not isinstance(result, dict) or not self.blocked_media_sources:
            return result
        children = result.get("children")
        if not isinstance(children, list):
            return result
        kept = [
            self.filter_media(child)
            for child in children
            if not (
                isinstance(child, dict)
                and media_source_domain(child.get("media_content_id"))
                in self.blocked_media_sources
            )
        ]
        return {**result, "children": kept}


class GuardedPermissions(AbstractPermissions):
    """Permissions that additionally hide entities of a restricted user."""

    def __init__(
        self, base: AbstractPermissions, guard: AccessGuard, user_id: str
    ) -> None:
        """Wrap the regular permissions of a user."""
        self.base = base
        self._guard = guard
        self._user_id = user_id

    def access_all_entities(self, key: str) -> bool:
        """Check if we have a certain access to all entities."""
        rules = self._guard.rules_by_user_id(self._user_id)
        if rules is not None and rules.hides_entities:
            return False
        return self.base.access_all_entities(key)

    def check_entity(self, entity_id: str, key: str) -> bool:
        """Check if we can access entity."""
        rules = self._guard.rules_by_user_id(self._user_id)
        if rules is not None and rules.entity_hidden(entity_id):
            return False
        return self.base.check_entity(entity_id, key)

    def _entity_func(self) -> Callable[[str, str], bool]:
        return self.check_entity

    def __eq__(self, other: object) -> bool:
        """Equals check."""
        return (
            isinstance(other, GuardedPermissions)
            and other.base == self.base
            and other._user_id == self._user_id
        )

    __hash__ = None  # type: ignore[assignment]


class _FilteringConnection:
    """Proxy for an ActiveConnection that filters successful results."""

    __slots__ = ("_conn", "_filter")

    def __init__(
        self, conn: ActiveConnection, result_filter: Callable[[Any], Any]
    ) -> None:
        self._conn = conn
        self._filter = result_filter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def send_result(self, msg_id: int, result: Any | None = None) -> None:
        self._conn.send_result(msg_id, self._filter(result))

    def send_message(self, message: Any) -> None:
        if (
            isinstance(message, dict)
            and message.get("type") == "result"
            and message.get("success")
        ):
            message = {**message, "result": self._filter(message.get("result"))}
        self._conn.send_message(message)


class AccessGuard:
    """Hold the rules and hook them into Home Assistant."""

    def __init__(
        self, hass: HomeAssistant, options: dict[str, Any], access_log: AccessLog
    ) -> None:
        """Initialize the guard."""
        self.hass = hass
        self.access_log = access_log
        self._rules: dict[str, UserRules] = {}
        self._ws_wrappers: dict[str, WsHandler] = {}
        self._route_originals: list[tuple[AbstractRoute, HttpHandler]] = []
        self._login_names: dict[str, str] = {}
        self._warned_permissions = False
        self.update_options(options)

    # -------------------------------------------------------------------- rules

    @callback
    def update_options(self, options: dict[str, Any]) -> None:
        """Compile rules from options."""
        rules: dict[str, UserRules] = {}
        for user_id, data in (options.get(CONF_USERS) or {}).items():
            compiled = UserRules.from_options(data or {})
            if not compiled.is_empty:
                rules[user_id] = compiled
        self._rules = rules

    @callback
    def rules_by_user_id(self, user_id: str) -> UserRules | None:
        """Return the rules of a user id."""
        return self._rules.get(user_id)

    @callback
    def rules_for(self, user: User | None) -> UserRules | None:
        """Return the rules of a user, None if the user is unrestricted."""
        if user is None or user.system_generated:
            return None
        return self._rules.get(user.id)

    @property
    def restricted_user_ids(self) -> set[str]:
        """Return ids of users with restrictions."""
        return set(self._rules)

    # ---------------------------------------------------------- start / stop

    async def async_start(self) -> None:
        """Hook into Home Assistant."""
        self.async_wrap_commands()
        self.async_wrap_routes()
        await self.async_apply_permissions()

    async def async_stop(self) -> None:
        """Remove every hook."""
        handlers = self.hass.data.get(websocket_api.DOMAIN, {})
        for command, wrapper in self._ws_wrappers.items():
            current = handlers.get(command)
            if current is not None and current[0] is wrapper:
                handlers[command] = (getattr(wrapper, WRAPPED_MARKER), current[1])
        self._ws_wrappers.clear()

        for route, original in self._route_originals:
            route._handler = original  # noqa: SLF001
        self._route_originals.clear()

        self._rules = {}
        for user in await self.hass.auth.async_get_users():
            self._remove_permissions(user)

    # -------------------------------------------------------------- websocket

    @staticmethod
    def _is_guarded_command(command: str) -> bool:
        return command in GUARDED_WS_COMMANDS or command.startswith(GUARDED_WS_PREFIXES)

    @callback
    def async_wrap_commands(self) -> None:
        """Wrap all relevant websocket commands (idempotent)."""
        handlers: dict[str, tuple[WsHandler, Any]] | None = self.hass.data.get(
            websocket_api.DOMAIN
        )
        if not handlers:
            return
        for command, (handler, schema) in list(handlers.items()):
            if not self._is_guarded_command(command):
                continue
            if self._ws_wrappers.get(command) is handler:
                continue
            wrapper = self._make_ws_wrapper(command, handler)
            handlers[command] = (wrapper, schema)
            self._ws_wrappers[command] = wrapper

    def _make_ws_wrapper(self, command: str, handler: WsHandler) -> WsHandler:
        guard = self

        @callback
        def _guarded(
            hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
        ) -> None:
            rules = guard.rules_for(connection.user)
            if rules is None:
                handler(hass, connection, msg)
                return

            if (area := rules.ws_denied_area(command, msg)) is not None:
                if area not in QUIET_AREAS:
                    guard._log_ws_denied(connection, area, command)
                connection.send_error(
                    msg["id"], websocket_api.ERR_UNAUTHORIZED, DENIED_MESSAGE
                )
                return

            if command == WS_PANELS and rules.hidden_panels:
                handler(
                    hass, _FilteringConnection(connection, rules.filter_panels), msg
                )
                return

            if command in WS_MEDIA_COMMANDS and rules.blocked_media_sources:
                handler(hass, _FilteringConnection(connection, rules.filter_media), msg)
                return

            handler(hass, connection, msg)

        setattr(_guarded, WRAPPED_MARKER, handler)
        return _guarded

    @callback
    def _log_ws_denied(
        self, connection: ActiveConnection, area: str, detail: str
    ) -> None:
        request = current_request.get()
        token = (
            self.hass.auth.async_get_refresh_token(connection.refresh_token_id)
            if connection.refresh_token_id
            else None
        )
        self.access_log.async_denied(
            connection.user,
            area=area,
            detail=detail,
            ip=connection.remote,
            user_agent=request.headers.get("User-Agent") if request else None,
            token=token,
        )

    # ------------------------------------------------------------------- http

    @callback
    def async_wrap_routes(self) -> None:
        """Wrap HTTP routes of guarded areas and the login flow (idempotent)."""
        http = getattr(self.hass, "http", None)
        if http is None:
            return
        for resource in list(http.app.router.resources()):
            path = getattr(resource, "canonical", "")
            is_login = path.startswith(LOGIN_FLOW_PATH)
            if not (is_login or path.startswith(GUARDED_HTTP_PREFIXES)):
                continue
            for route in resource:
                handler = route.handler
                if hasattr(handler, WRAPPED_MARKER):
                    continue
                if is_login:
                    if route.method != "POST":
                        continue
                    wrapper = self._make_login_wrapper(handler)
                else:
                    wrapper = self._make_http_wrapper(handler)
                route._handler = wrapper  # noqa: SLF001
                self._route_originals.append((route, handler))

    def _make_http_wrapper(self, handler: HttpHandler) -> HttpHandler:
        guard = self

        async def _guarded(request: web.Request) -> web.StreamResponse:
            user: User | None = request.get(KEY_HASS_USER)
            rules = guard.rules_for(user)
            if (
                rules is not None
                and user is not None
                and (area := rules.http_denied_area(request.path)) is not None
            ):
                guard.access_log.async_denied(
                    user,
                    area=area,
                    detail=request.path,
                    ip=request.remote,
                    user_agent=request.headers.get("User-Agent"),
                )
                return web.json_response({"message": DENIED_MESSAGE}, status=403)
            return await handler(request)

        setattr(_guarded, WRAPPED_MARKER, handler)
        return _guarded

    def _make_login_wrapper(self, handler: HttpHandler) -> HttpHandler:
        guard = self

        async def _logged(request: web.Request) -> web.StreamResponse:
            username: str | None = None
            flow_id = request.match_info.get("flow_id", "")
            try:
                body = await request.json()
            except (ValueError, UnicodeDecodeError):
                body = None
            if isinstance(body, dict):
                username = body.get("username") or body.get("user")
            if username:
                # Remember the name for later steps (e.g. two-factor code)
                guard._login_names[flow_id] = username
                while len(guard._login_names) > 200:
                    guard._login_names.pop(next(iter(guard._login_names)))
            else:
                username = guard._login_names.get(flow_id)
            response = await handler(request)
            try:
                await guard._async_log_login(request, response, username)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Could not log login attempt")
            return response

        setattr(_logged, WRAPPED_MARKER, handler)
        return _logged

    async def _async_log_login(
        self,
        request: web.Request,
        response: web.StreamResponse,
        username: str | None,
    ) -> None:
        if not isinstance(response, web.Response) or not response.body:
            return
        try:
            data = json.loads(bytes(response.body))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("type") == "create_entry":
            success = True
        elif data.get("type") == "form" and (data.get("errors") or {}).get("base") in (
            "invalid_auth",
            "invalid_login",
            "invalid_code",
        ):
            success = False
        else:
            return  # intermediate step (e.g. MFA) – nothing to log yet
        user = await self._async_find_user(username)
        self.access_log.async_login_attempt(
            success=success,
            username=username,
            user=user,
            ip=request.remote,
            user_agent=request.headers.get("User-Agent"),
        )

    async def _async_find_user(self, username: str | None) -> User | None:
        if not username:
            return None
        wanted = username.strip().casefold()
        for user in await self.hass.auth.async_get_users():
            if user.id == username:
                return user
            for credential in user.credentials:
                cred_name = str(credential.data.get("username", "")).strip().casefold()
                if cred_name and cred_name == wanted:
                    return user
        return None

    # ------------------------------------------------------------ permissions

    async def async_apply_permissions(self) -> None:
        """Install or remove the entity filter on all users."""
        for user in await self.hass.auth.async_get_users():
            self.async_ensure_permissions(user)

    @callback
    def async_ensure_permissions(self, user: User) -> None:
        """Install the entity filter for one user if needed."""
        rules = self.rules_for(user)
        if rules is None or not rules.hides_entities:
            self._remove_permissions(user)
            return
        current = user.__dict__.get("permissions")
        if isinstance(current, GuardedPermissions):
            return
        user.__dict__.pop("permissions", None)
        wrapper = GuardedPermissions(user.permissions, self, user.id)
        user.__dict__["permissions"] = wrapper
        if user.permissions is not wrapper and not self._warned_permissions:
            self._warned_permissions = True
            _LOGGER.warning(
                "Entities cannot be hidden in this Home Assistant version; "
                "panels and data access are still restricted"
            )

    @staticmethod
    def _remove_permissions(user: User) -> None:
        if isinstance(user.__dict__.get("permissions"), GuardedPermissions):
            user.__dict__.pop("permissions", None)
