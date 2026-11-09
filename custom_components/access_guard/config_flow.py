"""Config and options flow for Access Guard."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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
    DEFAULT_OPTIONS,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    UNHIDEABLE_PANELS,
    lang_of,
)
from .helpers import panel_override, panel_title, panels

CONF_USER_ID = "user_id"


class AccessGuardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Access Guard."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the setup."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title="Access Guard", data={}, options=deepcopy(DEFAULT_OPTIONS)
            )
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AccessGuardOptionsFlow()


class AccessGuardOptionsFlow(OptionsFlow):
    """Edit restrictions and log settings."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._user_id: str | None = None
        self._user_name: str = ""

    @property
    def _lang(self) -> str:
        return lang_of(self.hass.config.language)

    def _current(self) -> dict[str, Any]:
        return {
            **deepcopy(DEFAULT_OPTIONS),
            **deepcopy(dict(self.config_entry.options)),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to edit."""
        return self.async_show_menu(
            step_id="init", menu_options=["select_user", "logging"]
        )

    # ------------------------------------------------------------------ users

    async def async_step_select_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the user to restrict."""
        users = [
            user
            for user in await self.hass.auth.async_get_users()
            if not user.system_generated and not user.is_owner
        ]
        if not users:
            return self.async_abort(reason="no_users")

        if user_input is not None:
            self._user_id = user_input[CONF_USER_ID]
            self._user_name = next(
                (u.name or u.id for u in users if u.id == self._user_id), self._user_id
            )
            return await self.async_step_restrictions()

        configured = self._current()[CONF_USERS]
        admin_label = " (Administrator)" if self._lang == "de" else " (administrator)"
        restricted_label = " – eingeschränkt" if self._lang == "de" else " – restricted"
        options = [
            SelectOptionDict(
                value=user.id,
                label=(user.name or user.id)
                + (admin_label if user.is_admin else "")
                + (restricted_label if configured.get(user.id) else ""),
            )
            for user in sorted(
                users, key=lambda u: (u.is_admin, (u.name or "").lower())
            )
        ]
        return self.async_show_form(
            step_id="select_user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    def _panel_options(self) -> list[SelectOptionDict]:
        result: list[SelectOptionDict] = []
        for url_path, panel in panels(self.hass).items():
            if panel_override(self.hass, url_path).get(
                "require_admin", panel.require_admin
            ):
                continue
            if url_path in UNHIDEABLE_PANELS:
                continue
            result.append(
                SelectOptionDict(value=url_path, label=panel_title(self.hass, url_path))
            )
        return sorted(result, key=lambda option: option["label"].lower())

    def _dashboard_options(self) -> list[SelectOptionDict]:
        return sorted(
            (
                SelectOptionDict(value=url_path, label=panel_title(self.hass, url_path))
                for url_path, panel in panels(self.hass).items()
                if getattr(panel, "component_name", None) == "lovelace"
                and url_path != "lovelace"
            ),
            key=lambda option: option["label"].lower(),
        )

    async def async_step_restrictions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the restrictions of the selected user."""
        assert self._user_id is not None
        options = self._current()
        current = options[CONF_USERS].get(self._user_id, {})

        if user_input is not None:
            restrictions = {
                CONF_BLOCKED_AREAS: list(user_input.get(CONF_BLOCKED_AREAS, [])),
                CONF_BLOCKED_DASHBOARDS: list(
                    user_input.get(CONF_BLOCKED_DASHBOARDS, [])
                ),
                CONF_HIDDEN_PANELS: list(user_input.get(CONF_HIDDEN_PANELS, [])),
                CONF_HIDDEN_ENTITIES: list(user_input.get(CONF_HIDDEN_ENTITIES, [])),
            }
            if any(restrictions.values()):
                options[CONF_USERS][self._user_id] = restrictions
            else:
                options[CONF_USERS].pop(self._user_id, None)
            return self.async_create_entry(data=options)

        dashboards = self._dashboard_options()
        known_panels = self._panel_options()
        known_values = {option["value"] for option in known_panels}
        # Keep previously hidden panels selectable even if they are gone now
        known_panels += [
            SelectOptionDict(value=value, label=value)
            for value in current.get(CONF_HIDDEN_PANELS, [])
            if value not in known_values
        ]

        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_BLOCKED_AREAS, default=current.get(CONF_BLOCKED_AREAS, [])
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(AREAS),
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                    translation_key="areas",
                )
            ),
        }
        if dashboards:
            dashboard_values = {option["value"] for option in dashboards}
            schema[
                vol.Optional(
                    CONF_BLOCKED_DASHBOARDS,
                    default=[
                        d
                        for d in current.get(CONF_BLOCKED_DASHBOARDS, [])
                        if d in dashboard_values
                    ],
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=dashboards, multiple=True, mode=SelectSelectorMode.LIST
                )
            )
        schema[
            vol.Optional(
                CONF_HIDDEN_PANELS, default=current.get(CONF_HIDDEN_PANELS, [])
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=known_panels, multiple=True, mode=SelectSelectorMode.LIST
            )
        )
        schema[
            vol.Optional(
                CONF_HIDDEN_ENTITIES, default=current.get(CONF_HIDDEN_ENTITIES, [])
            )
        ] = EntitySelector(EntitySelectorConfig(multiple=True))

        return self.async_show_form(
            step_id="restrictions",
            data_schema=vol.Schema(schema),
            description_placeholders={"user": self._user_name},
        )

    # ---------------------------------------------------------------- logging

    async def async_step_logging(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the log settings."""
        options = self._current()
        if user_input is not None:
            options.update(
                {
                    CONF_LOG_SESSIONS: user_input[CONF_LOG_SESSIONS],
                    CONF_LOG_LOGINS: user_input[CONF_LOG_LOGINS],
                    CONF_LOG_DENIED: user_input[CONF_LOG_DENIED],
                    CONF_RETENTION_DAYS: int(user_input[CONF_RETENTION_DAYS]),
                }
            )
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="logging",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOG_LOGINS, default=options[CONF_LOG_LOGINS]
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_LOG_SESSIONS, default=options[CONF_LOG_SESSIONS]
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_LOG_DENIED, default=options[CONF_LOG_DENIED]
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_RETENTION_DAYS,
                        default=options.get(
                            CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=365,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="d",
                        )
                    ),
                }
            ),
        )
