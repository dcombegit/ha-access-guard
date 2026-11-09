"""Tests for Access Guard."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    CLIENT_ID,
    CLIENT_REDIRECT_URI,
)

from homeassistant import config_entries
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.access_guard.const import (
    CONF_BLOCKED_AREAS,
    CONF_BLOCKED_DASHBOARDS,
    CONF_HIDDEN_ENTITIES,
    CONF_HIDDEN_PANELS,
    CONF_RETENTION_DAYS,
    CONF_USERS,
    DOMAIN,
)
from custom_components.access_guard.devices import describe_device
from custom_components.access_guard.guard import WRAPPED_MARKER

from .conftest import UA_IPAD_SAFARI, UA_WINDOWS_CHROME, Account

# ---------------------------------------------------------------- config flow


async def test_config_and_options_flow(
    hass: HomeAssistant, setup_components: None, employee: Account
) -> None:
    """Set up via the UI and restrict a user through the options flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "select_user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_user"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"user_id": employee.user.id}
    )
    assert result["step_id"] == "restrictions"
    assert result["description_placeholders"] == {"user": "Mitarbeiter"}
    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert CONF_BLOCKED_AREAS in schema_keys
    assert CONF_HIDDEN_PANELS in schema_keys

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_BLOCKED_AREAS: ["media", "cameras"],
            CONF_HIDDEN_PANELS: ["security"],
            CONF_HIDDEN_ENTITIES: ["light.office"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_USERS][employee.user.id] == {
        CONF_BLOCKED_AREAS: ["media", "cameras"],
        CONF_BLOCKED_DASHBOARDS: [],
        CONF_HIDDEN_PANELS: ["security"],
        CONF_HIDDEN_ENTITIES: ["light.office"],
    }
    # Options are applied live
    assert entry.runtime_data.guard.rules_for(employee.user) is not None

    # Removing all restrictions removes the user
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "select_user"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"user_id": employee.user.id}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_BLOCKED_AREAS: [], CONF_HIDDEN_PANELS: [], CONF_HIDDEN_ENTITIES: []},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert employee.user.id not in entry.options[CONF_USERS]
    assert entry.runtime_data.guard.rules_for(employee.user) is None

    # Log settings
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "logging"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "log_logins": True,
            "log_sessions": False,
            "log_denied": True,
            CONF_RETENTION_DAYS: 14,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RETENTION_DAYS] == 14
    assert entry.options["log_sessions"] is False


async def test_single_instance(hass: HomeAssistant, setup_guard: Any) -> None:
    """Only one instance is allowed."""
    await setup_guard()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT


# ------------------------------------------------------------ restrictions


async def test_media_and_cameras_blocked(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    admin: Account,
    connect_ws: Any,
) -> None:
    """A restricted user loses the media panel, media browsing and cameras."""
    entry = await setup_guard(
        {CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["media", "cameras"]}}}
    )
    hass.states.async_set("camera.eingang", "idle", {"access_token": "secret"})
    hass.states.async_set("light.studio", "on")

    staff = await connect_ws(employee.token)
    boss = await connect_ws(admin.token, UA_IPAD_SAFARI)

    # Sidebar
    staff_panels = (await staff.call("get_panels"))["result"]
    boss_panels = (await boss.call("get_panels"))["result"]
    assert "media-browser" in boss_panels
    assert "media-browser" not in staff_panels
    assert "access-guard" in boss_panels
    assert "access-guard" not in staff_panels

    # Media browser
    response = await staff.call("media_source/browse_media", media_content_id="")
    assert not response["success"]
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED
    response = await boss.call("media_source/browse_media", media_content_id="")
    assert response["success"]

    # Camera live stream
    response = await staff.call("camera/stream", entity_id="camera.eingang")
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED

    # Camera entities are invisible, the rest stays
    staff_states = {s["entity_id"] for s in (await staff.call("get_states"))["result"]}
    boss_states = {s["entity_id"] for s in (await boss.call("get_states"))["result"]}
    assert "camera.eingang" not in staff_states
    assert "light.studio" in staff_states
    assert {"camera.eingang", "light.studio"} <= boss_states

    # Camera services can't be called either
    response = await staff.call(
        "call_service",
        domain="camera",
        service="turn_off",
        target={"entity_id": "camera.eingang"},
    )
    assert not response["success"]

    # Blocked attempts are logged (and grouped)
    await staff.call("media_source/browse_media", media_content_id="")
    log = entry.runtime_data.access_log
    denied = [e for e in log.entries if e["type"] == "denied"]
    by_area = {e["area"]: e for e in denied}
    assert by_area["media"]["count"] == 2
    assert by_area["media"]["user"] == "Mitarbeiter"
    assert by_area["media"]["device"] == "Chrome · Windows"
    assert by_area["cameras"]["details"] == ["camera/stream"]


async def test_cameras_only_hides_camera_media_sources(
    hass: HomeAssistant, setup_guard: Any, employee: Account, connect_ws: Any
) -> None:
    """Blocking only cameras keeps the media browser but removes camera sources."""
    await setup_guard(
        {CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["cameras"]}}}
    )
    staff = await connect_ws(employee.token)

    panels = (await staff.call("get_panels"))["result"]
    assert "media-browser" in panels

    root = await staff.call("media_source/browse_media", media_content_id="")
    assert root["success"]
    ids = [child["media_content_id"] for child in root["result"]["children"]]
    assert ids, "expected at least one other media source"
    assert not [cid for cid in ids if cid.startswith("media-source://camera")]

    response = await staff.call(
        "media_source/browse_media", media_content_id="media-source://camera"
    )
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED
    response = await staff.call(
        "media_source/resolve_media",
        media_content_id="media-source://unifiprotect/abc/event/123",
    )
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED


async def test_quiet_areas_blocked_but_not_logged(
    hass: HomeAssistant, setup_guard: Any, employee: Account, connect_ws: Any
) -> None:
    """Automatic calls from dashboard cards are blocked silently."""
    for domain in ("todo", "calendar"):
        assert await async_setup_component(hass, domain, {})
    entry = await setup_guard(
        {CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["todo", "calendar"]}}}
    )
    staff = await connect_ws(employee.token)
    assert "todo" not in (await staff.call("get_panels"))["result"]
    response = await staff.call("todo/item/list", entity_id="todo.einkauf")
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED
    response = await staff.call(
        "calendar/event/subscribe",
        entity_id="calendar.team",
        start="2026-11-09T00:00:00+00:00",
        end="2026-11-10T00:00:00+00:00",
    )
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED
    denied = [e for e in entry.runtime_data.access_log.entries if e["type"] == "denied"]
    assert denied == []


async def test_hidden_panels_and_entities(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    connect_ws: Any,
) -> None:
    """Hidden panels disappear from the sidebar; hidden entities are invisible."""
    await setup_guard(
        {
            CONF_USERS: {
                employee.user.id: {
                    CONF_HIDDEN_PANELS: ["media-browser"],
                    CONF_HIDDEN_ENTITIES: ["switch.tor"],
                }
            }
        }
    )
    hass.states.async_set("switch.tor", "off")
    hass.states.async_set("switch.licht", "off")
    staff = await connect_ws(employee.token)

    assert "media-browser" not in (await staff.call("get_panels"))["result"]
    # Hidden only, not blocked
    assert (await staff.call("media_source/browse_media", media_content_id=""))[
        "success"
    ]

    states = {s["entity_id"] for s in (await staff.call("get_states"))["result"]}
    assert "switch.tor" not in states
    assert "switch.licht" in states


async def test_http_endpoints_blocked(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    admin: Account,
    hass_client: Any,
) -> None:
    """Camera HTTP endpoints return 403 for the restricted user only."""
    await setup_guard(
        {CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["cameras"]}}}
    )
    staff = await hass_client(employee.token)
    boss = await hass_client(admin.token)

    response = await staff.get("/api/camera_proxy/camera.eingang")
    assert response.status == HTTPStatus.FORBIDDEN
    response = await boss.get("/api/camera_proxy/camera.eingang")
    assert response.status != HTTPStatus.FORBIDDEN


async def test_live_option_change_and_unload(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    connect_ws: Any,
) -> None:
    """Options apply without reload, unloading restores everything."""
    entry = await setup_guard()
    hass.states.async_set("camera.eingang", "idle")
    staff = await connect_ws(employee.token)
    assert (await staff.call("media_source/browse_media", media_content_id=""))[
        "success"
    ]

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["media", "cameras"]}},
        },
    )
    await hass.async_block_till_done()
    response = await staff.call("media_source/browse_media", media_content_id="")
    assert not response["success"]
    states = {s["entity_id"] for s in (await staff.call("get_states"))["result"]}
    assert "camera.eingang" not in states

    # Permission filter survives a user update (cache invalidation)
    await hass.auth.async_update_user(employee.user, name="Mitarbeiterin")
    await hass.async_block_till_done()
    states = {s["entity_id"] for s in (await staff.call("get_states"))["result"]}
    assert "camera.eingang" not in states

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    handler = hass.data[websocket_api.DOMAIN]["media_source/browse_media"][0]
    assert not hasattr(handler, WRAPPED_MARKER)
    assert (await staff.call("media_source/browse_media", media_content_id=""))[
        "success"
    ]
    states = {s["entity_id"] for s in (await staff.call("get_states"))["result"]}
    assert "camera.eingang" in states


async def test_dashboard_blocked(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    admin: Account,
    connect_ws: Any,
) -> None:
    """A blocked dashboard can't be loaded."""
    await setup_guard(
        {CONF_USERS: {employee.user.id: {CONF_BLOCKED_DASHBOARDS: ["kameras"]}}}
    )
    staff = await connect_ws(employee.token)
    response = await staff.call("lovelace/config", url_path="kameras")
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED


# ---------------------------------------------------------------------- log


async def test_sessions_logged_with_device(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    admin: Account,
    connect_ws: Any,
) -> None:
    """Every frontend session is logged with user, device and duration."""
    entry = await setup_guard()
    log = entry.runtime_data.access_log
    staff = await connect_ws(employee.token, UA_WINDOWS_CHROME)
    await connect_ws(admin.token, UA_IPAD_SAFARI)
    await hass.async_block_till_done()

    sessions = [e for e in log.entries if e["type"] == "session"]
    assert {(e["user"], e["device"]) for e in sessions} == {
        ("Mitarbeiter", "Chrome · Windows"),
        ("Mock User", "Safari · iPad"),
    }
    staff_session = next(e for e in sessions if e["user"] == "Mitarbeiter")
    assert staff_session["end"] is None
    assert staff_session["new_login"] is True
    assert staff_session["id"] in log.open_session_ids

    await staff.ws.close()
    await hass.async_block_till_done()
    assert staff_session["end"] is not None
    assert staff_session["id"] not in log.open_session_ids


async def test_login_attempts_logged(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    local_auth: Any,
    hass_client_no_auth: Any,
) -> None:
    """Successful and failed logins through the login form are logged."""
    await local_auth.async_initialize()
    local_auth.data.add_auth("mitarbeiter", "richtig")
    credential = await local_auth.async_get_or_create_credentials(
        {"username": "mitarbeiter"}
    )
    await hass.auth.async_link_user(employee.user, credential)

    events = []
    hass.bus.async_listen("access_guard_login", events.append)
    entry = await setup_guard()
    client = await hass_client_no_auth()
    headers = {"User-Agent": UA_IPAD_SAFARI}

    async def login(password: str) -> dict:
        resp = await client.post(
            "/auth/login_flow",
            json={
                "client_id": CLIENT_ID,
                "handler": ["homeassistant", None],
                "redirect_uri": CLIENT_REDIRECT_URI,
            },
            headers=headers,
        )
        flow = await resp.json()
        resp = await client.post(
            f"/auth/login_flow/{flow['flow_id']}",
            json={
                "client_id": CLIENT_ID,
                "username": "Mitarbeiter",
                "password": password,
            },
            headers=headers,
        )
        return await resp.json()

    assert (await login("falsch"))["type"] == "form"
    assert (await login("richtig"))["type"] == "create_entry"
    await hass.async_block_till_done()

    log = entry.runtime_data.access_log
    logins = [e for e in log.entries if e["type"] in ("login", "login_failed")]
    assert [e["type"] for e in logins] == ["login_failed", "login"]
    assert all(e["user"] == "Mitarbeiter" for e in logins)
    assert logins[0]["username"] == "Mitarbeiter"
    assert logins[0]["device"] == "Safari · iPad"
    assert "richtig" not in str(log.entries)
    assert "falsch" not in str(log.entries)
    assert [e.data["success"] for e in events] == [False, True]


async def test_log_persists_and_prunes(
    hass: HomeAssistant, setup_guard: Any, employee: Account, connect_ws: Any
) -> None:
    """The log survives a reload and closes dangling sessions."""
    entry = await setup_guard()
    await connect_ws(employee.token)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    log = entry.runtime_data.access_log
    sessions = [e for e in log.entries if e["type"] == "session"]
    assert len(sessions) == 1
    assert sessions[0]["end"] is not None


# -------------------------------------------------------------------- panel


# Revoking a token cancels the websocket handler; aiohttp keeps its heartbeat timer
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_admin_panel_api(
    hass: HomeAssistant,
    setup_guard: Any,
    employee: Account,
    admin: Account,
    connect_ws: Any,
) -> None:
    """The panel API is admin-only and can rename and sign out devices."""
    await setup_guard({CONF_USERS: {employee.user.id: {CONF_BLOCKED_AREAS: ["media"]}}})
    staff = await connect_ws(employee.token)
    boss = await connect_ws(admin.token)

    response = await staff.call("access_guard/overview")
    assert response["error"]["code"] == websocket_api.ERR_UNAUTHORIZED

    overview = (await boss.call("access_guard/overview"))["result"]
    users = {u["name"]: u for u in overview["users"]}
    assert users["Mitarbeiter"]["restrictions"]["areas"] == ["media"]
    staff_tokens = users["Mitarbeiter"]["tokens"]
    assert [t["id"] for t in staff_tokens] == [employee.refresh_token_id]
    assert any(t["current"] for t in users["Mock User"]["tokens"])
    assert {e["type"] for e in overview["entries"]} >= {"session"}
    assert overview["areas"]["media"] in ("Medien", "Media")

    assert (
        await boss.call(
            "access_guard/set_label",
            token_id=employee.refresh_token_id,
            label="Studio-PC",
        )
    )["success"]
    overview = (await boss.call("access_guard/overview"))["result"]
    assert overview["labels"][employee.refresh_token_id] == "Studio-PC"

    assert (
        await boss.call("access_guard/revoke_token", token_id=employee.refresh_token_id)
    )["success"]
    assert hass.auth.async_get_refresh_token(employee.refresh_token_id) is None
    # The signed-out device gets disconnected
    assert (await staff.ws.receive()).type.name in ("CLOSE", "CLOSING", "CLOSED")
    await staff.ws.close()
    await hass.async_block_till_done()

    assert (await boss.call("access_guard/clear_log"))["success"]


# ------------------------------------------------------------------ devices


def test_describe_device() -> None:
    """User agents become readable device names."""
    assert describe_device(None, UA_WINDOWS_CHROME) == "Chrome · Windows"
    assert describe_device(None, UA_IPAD_SAFARI) == "Safari · iPad"
    assert (
        describe_device(
            None,
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
            "like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        )
        == "Edge · Windows"
    )
    assert (
        describe_device(
            None,
            "Mozilla/5.0 (Linux; Android 8.1.0; WallDisplay; wv) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Version/4.0 Chrome/120.0 Mobile Safari/537.36",
        )
        == "WebView · Android"
    )
    assert (
        describe_device(
            None,
            "Home Assistant/2026.10.3 (io.robbie.HomeAssistant; build:2026.3322; "
            "iOS 18.1.0) Mobile/HomeAssistant",
        )
        == "Companion-App"
    )
    assert describe_device(None, None) == "Unbekannt"
