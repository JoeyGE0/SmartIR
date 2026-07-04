"""Config flow for SmartIR."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_CONTROLLER_DATA,
    CONF_CONTROLLER_ENTITY,
    CONF_CONTROLLER_TYPE,
    CONF_DELAY,
    CONF_DEVICE_CLASS,
    CONF_DEVICE_CODE,
    CONF_HUMIDITY_SENSOR,
    CONF_PLATFORM,
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_RESTORE_STATE,
    CONF_SOURCE_NAMES,
    CONF_TEMPERATURE_SENSOR,
    CONTROLLER_ESPHOME,
    CONTROLLER_LOOKIN,
    CONTROLLER_MQTT,
    CONTROLLER_OTHER,
    CONTROLLER_REMOTE,
    DEFAULT_DELAY,
    DEFAULT_DEVICE_CLASS,
    DOMAIN,
    PLATFORM_CLIMATE,
    PLATFORM_DEFAULT_NAMES,
    PLATFORM_FAN,
    PLATFORM_LIGHT,
    PLATFORM_MEDIA_PLAYER,
)
from .helpers import async_load_device_data, build_unique_id

_LOGGER = logging.getLogger(__name__)

CONTROLLER_TYPES = [
    SelectOptionDict(value=CONTROLLER_REMOTE, label="Remote entity (Broadlink, Xiaomi, etc.)"),
    SelectOptionDict(value=CONTROLLER_MQTT, label="MQTT topic"),
    SelectOptionDict(value=CONTROLLER_LOOKIN, label="LOOK.in IP address"),
    SelectOptionDict(value=CONTROLLER_ESPHOME, label="ESPHome service name"),
    SelectOptionDict(value=CONTROLLER_OTHER, label="Other controller data"),
]

PLATFORM_OPTIONS = [
    SelectOptionDict(value=PLATFORM_CLIMATE, label="Climate"),
    SelectOptionDict(value=PLATFORM_FAN, label="Fan"),
    SelectOptionDict(value=PLATFORM_LIGHT, label="Light"),
    SelectOptionDict(value=PLATFORM_MEDIA_PLAYER, label="Media player"),
]


def _optional_entity(
    key: str, config: EntitySelectorConfig, defaults: dict[str, Any]
) -> dict:
    """Return optional entity selector without invalid None default."""
    value = defaults.get(key)
    if value:
        return {vol.Optional(key, default=value): EntitySelector(config)}
    return {vol.Optional(key): EntitySelector(config)}


def _required_entity(
    key: str, config: EntitySelectorConfig, default: str | None
) -> dict:
    """Return required entity selector without invalid None default."""
    if default:
        return {vol.Required(key, default=default): EntitySelector(config)}
    return {vol.Required(key): EntitySelector(config)}


def _controller_fields(defaults: dict[str, Any]) -> dict:
    """Return shared controller configuration fields."""
    controller_type = defaults.get(CONF_CONTROLLER_TYPE, CONTROLLER_REMOTE)
    fields: dict = {
        vol.Required(
            CONF_CONTROLLER_TYPE, default=controller_type
        ): SelectSelector(
            SelectSelectorConfig(options=CONTROLLER_TYPES, mode=SelectSelectorMode.DROPDOWN)
        ),
    }

    if controller_type == CONTROLLER_REMOTE:
        controller_default = (
            defaults.get(CONF_CONTROLLER_ENTITY) or defaults.get(CONF_CONTROLLER_DATA)
        )
        fields.update(
            _required_entity(
                CONF_CONTROLLER_ENTITY,
                EntitySelectorConfig(domain="remote"),
                controller_default,
            )
        )
    else:
        controller_data = defaults.get(CONF_CONTROLLER_DATA)
        if controller_data:
            fields[vol.Required(CONF_CONTROLLER_DATA, default=controller_data)] = (
                TextSelector(TextSelectorConfig(type=selector.TextSelectorType.TEXT))
            )
        else:
            fields[vol.Required(CONF_CONTROLLER_DATA)] = TextSelector(
                TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )

    return fields


def _base_schema(platform: str, defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return base fields shared by all platforms."""
    defaults = defaults or {}
    default_name = defaults.get(CONF_NAME, PLATFORM_DEFAULT_NAMES[platform])

    device_code = defaults.get(CONF_DEVICE_CODE)
    if device_code is not None:
        device_code_field = vol.Required(CONF_DEVICE_CODE, default=str(device_code))
    else:
        device_code_field = vol.Required(CONF_DEVICE_CODE)

    fields = {
        vol.Required(CONF_NAME, default=default_name): str,
        device_code_field: TextSelector(
            TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_DELAY, default=defaults.get(CONF_DELAY, DEFAULT_DELAY)): NumberSelector(
            NumberSelectorConfig(min=0, max=10, step=0.1, mode=NumberSelectorMode.BOX)
        ),
    }
    fields.update(
        _optional_entity(
            CONF_POWER_SENSOR,
            EntitySelectorConfig(domain=["binary_sensor", "sensor"]),
            defaults,
        )
    )
    fields.update(_controller_fields(defaults))
    return vol.Schema(fields)


def _climate_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    fields = _base_schema(PLATFORM_CLIMATE, defaults).schema.copy()
    fields.update(
        _optional_entity(
            CONF_TEMPERATURE_SENSOR,
            EntitySelectorConfig(domain="sensor", device_class="temperature"),
            defaults,
        )
    )
    fields.update(
        _optional_entity(
            CONF_HUMIDITY_SENSOR,
            EntitySelectorConfig(domain="sensor", device_class="humidity"),
            defaults,
        )
    )
    fields[vol.Optional(
        CONF_POWER_SENSOR_RESTORE_STATE,
        default=defaults.get(CONF_POWER_SENSOR_RESTORE_STATE, False),
    )] = bool
    return vol.Schema(fields)


def _media_player_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    fields = _base_schema(PLATFORM_MEDIA_PLAYER, defaults).schema.copy()
    fields.update(
        {
            vol.Optional(
                CONF_DEVICE_CLASS,
                default=defaults.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS),
            ): str,
            vol.Optional(
                CONF_SOURCE_NAMES,
                default=json.dumps(defaults.get(CONF_SOURCE_NAMES, {}))
                if defaults.get(CONF_SOURCE_NAMES)
                else "{}",
            ): TextSelector(
                TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                )
            ),
        }
    )
    return vol.Schema(fields)


def _schema_for_platform(platform: str, defaults: dict[str, Any] | None = None) -> vol.Schema:
    if platform == PLATFORM_CLIMATE:
        return _climate_schema(defaults)
    if platform == PLATFORM_MEDIA_PLAYER:
        return _media_player_schema(defaults)
    return _base_schema(platform, defaults)


def _resolve_controller_from_input(user_input: dict[str, Any]) -> str:
    controller_type = user_input[CONF_CONTROLLER_TYPE]
    if controller_type == CONTROLLER_REMOTE:
        return user_input[CONF_CONTROLLER_ENTITY]
    return user_input[CONF_CONTROLLER_DATA]


def _clean_optional_entities(data: dict[str, Any]) -> dict[str, Any]:
    """Remove empty optional entity fields."""
    entity_keys = (
        CONF_POWER_SENSOR,
        CONF_TEMPERATURE_SENSOR,
        CONF_HUMIDITY_SENSOR,
        CONF_CONTROLLER_ENTITY,
    )
    for key in entity_keys:
        if not data.get(key):
            data.pop(key, None)
    return data


def _entry_data(platform: str, user_input: dict[str, Any], device_code: int) -> dict[str, Any]:
    controller = _resolve_controller_from_input(user_input)
    data: dict[str, Any] = {
        CONF_PLATFORM: platform,
        CONF_NAME: user_input[CONF_NAME],
        CONF_DEVICE_CODE: device_code,
        CONF_CONTROLLER_TYPE: user_input[CONF_CONTROLLER_TYPE],
        CONF_CONTROLLER_DATA: controller,
        CONF_DELAY: float(user_input.get(CONF_DELAY, DEFAULT_DELAY)),
    }

    if user_input.get(CONF_POWER_SENSOR):
        data[CONF_POWER_SENSOR] = user_input[CONF_POWER_SENSOR]

    if user_input[CONF_CONTROLLER_TYPE] == CONTROLLER_REMOTE:
        data[CONF_CONTROLLER_ENTITY] = user_input[CONF_CONTROLLER_ENTITY]

    if platform == PLATFORM_CLIMATE:
        if user_input.get(CONF_TEMPERATURE_SENSOR):
            data[CONF_TEMPERATURE_SENSOR] = user_input[CONF_TEMPERATURE_SENSOR]
        if user_input.get(CONF_HUMIDITY_SENSOR):
            data[CONF_HUMIDITY_SENSOR] = user_input[CONF_HUMIDITY_SENSOR]
        data[CONF_POWER_SENSOR_RESTORE_STATE] = user_input.get(
            CONF_POWER_SENSOR_RESTORE_STATE, False
        )
    elif platform == PLATFORM_MEDIA_PLAYER:
        data[CONF_DEVICE_CLASS] = user_input.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS)
        source_names_raw = user_input.get(CONF_SOURCE_NAMES, "{}")
        try:
            data[CONF_SOURCE_NAMES] = json.loads(source_names_raw or "{}")
        except json.JSONDecodeError:
            data[CONF_SOURCE_NAMES] = {}

    return _clean_optional_entities(data)


class SmartIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a SmartIR config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._platform: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose the device platform."""
        if user_input is not None:
            self._platform = user_input[CONF_PLATFORM]
            return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLATFORM): SelectSelector(
                        SelectSelectorConfig(
                            options=PLATFORM_OPTIONS,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the selected platform."""
        errors: dict[str, str] = {}
        platform = self._platform
        assert platform is not None

        if user_input is not None:
            try:
                device_code = int(str(user_input[CONF_DEVICE_CODE]).strip())
                if device_code < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors["base"] = "invalid_device_code"
                device_code = None

            if device_code is not None:
                controller = _resolve_controller_from_input(user_input)

                device_data = await async_load_device_data(platform, device_code)
                if device_data is None:
                    errors["base"] = "invalid_device_code"
                else:
                    unique_id = build_unique_id(platform, device_code, controller)
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data=_entry_data(platform, user_input, device_code),
                    )

        return self.async_show_form(
            step_id="device",
            data_schema=_schema_for_platform(platform),
            errors=errors,
            description_placeholders={"platform": platform.replace("_", " ")},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SmartIROptionsFlowHandler:
        """Get the options flow."""
        return SmartIROptionsFlowHandler()


class SmartIROptionsFlowHandler(config_entries.OptionsFlow):
    """Handle SmartIR options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage SmartIR options."""
        platform = self._config_entry.data[CONF_PLATFORM]
        defaults = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            try:
                device_code = int(str(user_input[CONF_DEVICE_CODE]).strip())
                if device_code < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return self.async_show_form(
                    step_id="init",
                    data_schema=_schema_for_platform(platform, defaults),
                    errors={"base": "invalid_device_code"},
                )

            return self.async_create_entry(
                title="",
                data=_entry_data(platform, user_input, device_code),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_schema_for_platform(platform, defaults),
        )
