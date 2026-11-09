"""Fixtures for Access Guard tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
import itertools
from typing import Any

from aiohttp import ClientWebSocketResponse
import pytest
from pytest_homeassistant_custom_component.common import (
    CLIENT_ID,
    MockConfigEntry,
    MockUser,
)

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.access_guard.const import DEFAULT_OPTIONS, DOMAIN

UA_WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_IPAD_SAFARI = (
    "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations."""


@dataclass
class Account:
    """A user with an access token."""

    user: MockUser
    token: str
    refresh_token_id: str


@pytest.fixture
async def employee(hass: HomeAssistant, local_auth: Any) -> Account:
    """A regular (non-admin) user like a staff member."""
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    user = MockUser(name="Mitarbeiter", groups=[group]).add_to_hass(hass)
    refresh_token = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return Account(
        user, hass.auth.async_create_access_token(refresh_token), refresh_token.id
    )


@pytest.fixture
async def admin(
    hass: HomeAssistant, hass_admin_user: MockUser, hass_access_token: str
) -> Account:
    """The admin user."""
    token_id = next(iter(hass_admin_user.refresh_tokens))
    return Account(hass_admin_user, hass_access_token, token_id)


@pytest.fixture
async def setup_components(hass: HomeAssistant) -> None:
    """Set up the core components the guard hooks into."""
    for domain in ("http", "media_source", "camera"):
        assert await async_setup_component(hass, domain, {})
    await hass.async_block_till_done()


SetupGuard = Callable[[dict[str, Any] | None], Awaitable[MockConfigEntry]]


@pytest.fixture
def setup_guard(hass: HomeAssistant, setup_components: None) -> SetupGuard:
    """Return a function that sets up Access Guard with options."""

    async def _setup(options: dict[str, Any] | None = None) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Access Guard",
            options={**DEFAULT_OPTIONS, **(options or {})},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


@dataclass
class WsSession:
    """A raw websocket session with a custom user agent."""

    ws: ClientWebSocketResponse
    ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    async def call(self, msg_type: str, **kwargs: Any) -> dict[str, Any]:
        """Send a command and return the response."""
        msg_id = next(self.ids)
        await self.ws.send_json({"id": msg_id, "type": msg_type, **kwargs})
        while True:
            response = await self.ws.receive_json()
            if response.get("id") == msg_id and response["type"] == "result":
                return response


ConnectWs = Callable[..., Awaitable[WsSession]]


@pytest.fixture
async def connect_ws(
    hass: HomeAssistant, hass_client_no_auth: Any
) -> AsyncGenerator[ConnectWs]:
    """Open authenticated websocket sessions with a given user agent."""
    sessions: list[WsSession] = []

    async def _connect(token: str, user_agent: str = UA_WINDOWS_CHROME) -> WsSession:
        client = await hass_client_no_auth()
        ws = await client.ws_connect(
            "/api/websocket", headers={"User-Agent": user_agent}
        )
        assert (await ws.receive_json())["type"] == "auth_required"
        await ws.send_json({"type": "auth", "access_token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        session = WsSession(ws)
        sessions.append(session)
        return session

    yield _connect
    for session in sessions:
        if not session.ws.closed:
            await session.ws.close()
    await hass.async_block_till_done()
