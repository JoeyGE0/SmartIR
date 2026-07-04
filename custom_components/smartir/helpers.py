"""Helper functions for SmartIR."""

import json
import logging
import os.path
import asyncio
import shutil

import aiofiles

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from . import COMPONENT_ABS_DIR, Helper
from .const import CONF_CONTROLLER_DATA, CONF_CONTROLLER_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)

CODES_SOURCE_FORK = (
    "https://raw.githubusercontent.com/JoeyGE0/SmartIR/master/codes/{}/{}.json"
)
CODES_SOURCE_UPSTREAM = (
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
    """Return DeviceInfo for the physical device behind a controller entity."""
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


def _device_json_paths(platform: str, device_code: int) -> list[str]:
    """Return candidate local paths for a device JSON file."""
    filename = f"{device_code}.json"
    return [
        os.path.join(COMPONENT_ABS_DIR, "codes", platform, filename),
        os.path.join(COMPONENT_ABS_DIR, "bundled_codes", platform, filename),
    ]


async def _seed_device_json(platform: str, device_code: int) -> str | None:
    """Copy bundled code into the writable codes directory if available."""
    target_dir = os.path.join(COMPONENT_ABS_DIR, "codes", platform)
    target_path = os.path.join(target_dir, f"{device_code}.json")
    bundled_path = os.path.join(
        COMPONENT_ABS_DIR, "bundled_codes", platform, f"{device_code}.json"
    )

    if os.path.exists(target_path):
        return target_path

    if not os.path.exists(bundled_path):
        return None

    os.makedirs(target_dir, exist_ok=True)
    await asyncio.to_thread(shutil.copy2, bundled_path, target_path)
    return target_path


async def async_load_device_data(platform: str, device_code: int) -> dict | None:
    """Load device JSON from local codes or download from GitHub."""
    await _seed_device_json(platform, device_code)

    device_json_path = None
    for candidate in _device_json_paths(platform, device_code):
        if os.path.exists(candidate):
            device_json_path = candidate
            break

    if device_json_path is None:
        target_dir = os.path.join(COMPONENT_ABS_DIR, "codes", platform)
        os.makedirs(target_dir, exist_ok=True)
        device_json_path = os.path.join(target_dir, f"{device_code}.json")

        _LOGGER.debug(
            "Device JSON %s not found locally, downloading", device_json_path
        )
        for source in (CODES_SOURCE_FORK, CODES_SOURCE_UPSTREAM):
            try:
                await Helper.downloader(
                    source.format(platform, device_code), device_json_path
                )
                break
            except Exception:
                _LOGGER.debug(
                    "Device code %s not found at %s", device_code, source
                )
        else:
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
