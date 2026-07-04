"""Helper functions for SmartIR."""

import json
import logging
import os.path

import aiofiles

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from . import COMPONENT_ABS_DIR, Helper
from .const import CONF_CONTROLLER_DATA, CONF_CONTROLLER_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)

CODES_SOURCE = (
    "https://raw.githubusercontent.com/smartHomeHub/SmartIR/master/codes/{}/{}.json"
)


def resolve_controller_data(config: dict) -> str:
    """Resolve controller target from config entry or YAML data."""
    if config.get(CONF_CONTROLLER_ENTITY):
        return config[CONF_CONTROLLER_ENTITY]
    return config[CONF_CONTROLLER_DATA]


def get_controller_device_info(
    hass: HomeAssistant, controller_entity_id: str
) -> DeviceInfo | None:
    """Return DeviceInfo for the physical device behind a controller entity.

    Re-using identifiers and connections attaches SmartIR entities to the
    same device card as integrations like Broadlink or UniFi Network.
    """
    if not controller_entity_id or "." not in controller_entity_id:
        return None

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    entity_entry = entity_reg.async_get(controller_entity_id)
    if entity_entry is None or entity_entry.device_id is None:
        return None

    device = device_reg.async_get(entity_entry.device_id)
    if device is None:
        return None

    return DeviceInfo(
        identifiers=device.identifiers,
        connections=device.connections,
        manufacturer=device.manufacturer,
        model=device.model,
        name=device.name_by_user or device.name,
        sw_version=device.sw_version,
        hw_version=device.hw_version,
    )


def get_device_info(
    hass: HomeAssistant,
    config: dict,
    unique_id: str | None,
    fallback_name: str,
) -> DeviceInfo | None:
    """Return linked controller device info or a SmartIR fallback device."""
    controller = resolve_controller_data(config)
    device_info = get_controller_device_info(hass, controller)
    if device_info is not None:
        return device_info

    if not unique_id:
        return None

    return DeviceInfo(
        identifiers={(DOMAIN, unique_id)},
        name=fallback_name,
        manufacturer="SmartIR",
    )


async def async_load_device_data(platform: str, device_code: int) -> dict | None:
    """Load device JSON from local codes or download from GitHub."""
    device_files_subdir = os.path.join("codes", platform)
    device_files_absdir = os.path.join(COMPONENT_ABS_DIR, device_files_subdir)

    if not os.path.isdir(device_files_absdir):
        os.makedirs(device_files_absdir)

    device_json_path = os.path.join(device_files_absdir, f"{device_code}.json")

    if not os.path.exists(device_json_path):
        _LOGGER.debug(
            "Device JSON %s not found locally, downloading", device_json_path
        )
        try:
            await Helper.downloader(
                CODES_SOURCE.format(platform, device_code), device_json_path
            )
        except Exception:
            _LOGGER.error(
                "Failed to download device code %s for platform %s",
                device_code,
                platform,
            )
            return None

    try:
        async with aiofiles.open(device_json_path, mode="r") as json_file:
            return json.loads(await json_file.read())
    except Exception:
        _LOGGER.error("Device JSON file is invalid: %s", device_json_path)
        return None


def build_unique_id(
    platform: str, device_code: int, controller_data: str
) -> str:
    """Build a stable unique id for a SmartIR config entry."""
    controller_key = controller_data.replace(".", "_").replace("/", "_")
    return f"{DOMAIN}_{platform}_{device_code}_{controller_key}"
