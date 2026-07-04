import asyncio
import logging

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerEntity, PLATFORM_SCHEMA)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature, MediaType)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME, STATE_OFF, STATE_ON, STATE_UNKNOWN)
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from .const import (
    CONF_CONTROLLER_DATA,
    CONF_DELAY,
    CONF_DEVICE_CLASS,
    CONF_DEVICE_CODE,
    CONF_PLATFORM,
    CONF_POWER_SENSOR,
    CONF_SOURCE_NAMES,
    CONF_UNIQUE_ID,
    DEFAULT_DELAY,
    DEFAULT_DEVICE_CLASS,
    DEFAULT_MEDIA_PLAYER_NAME,
    PLATFORM_MEDIA_PLAYER,
)
from .controller import get_controller
from .helpers import (
    async_load_device_data,
    get_device_info,
    normalize_delay,
    resolve_controller_data,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_UNIQUE_ID): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_MEDIA_PLAYER_NAME): cv.string,
    vol.Required(CONF_DEVICE_CODE): cv.positive_int,
    vol.Required(CONF_CONTROLLER_DATA): cv.string,
    vol.Optional(CONF_DELAY, default=DEFAULT_DELAY): cv.string,
    vol.Optional(CONF_POWER_SENSOR): cv.entity_id,
    vol.Optional(CONF_SOURCE_NAMES): dict,
    vol.Optional(CONF_DEVICE_CLASS, default=DEFAULT_DEVICE_CLASS): cv.string
})


async def _async_create_media_player_entity(
    hass: HomeAssistant, config: dict, unique_id: str | None = None
) -> SmartIRMediaPlayer | None:
    """Create a media player entity from configuration."""
    device_code = config[CONF_DEVICE_CODE]
    device_data = await async_load_device_data(PLATFORM_MEDIA_PLAYER, device_code)
    if device_data is None:
        return None

    entity_unique_id = unique_id or config.get(CONF_UNIQUE_ID)
    device_info = get_device_info(
        hass,
        config,
        entity_unique_id,
        config.get(CONF_NAME, DEFAULT_MEDIA_PLAYER_NAME),
    )

    return SmartIRMediaPlayer(
        hass=hass,
        config=config,
        device_data=device_data,
        unique_id=entity_unique_id,
        device_info=device_info,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SmartIR media player from a config entry."""
    if entry.data.get(CONF_PLATFORM) != PLATFORM_MEDIA_PLAYER:
        return

    config = {**entry.data, **entry.options}
    entity = await _async_create_media_player_entity(hass, config, entry.unique_id)
    if entity is None:
        return

    async_add_entities([entity])


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the IR Media Player platform from YAML."""
    entity = await _async_create_media_player_entity(hass, config)
    if entity is None:
        return

    async_add_entities([entity])


class SmartIRMediaPlayer(MediaPlayerEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        device_data: dict,
        unique_id: str | None = None,
        device_info: DeviceInfo | None = None,
    ):
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = config.get(CONF_NAME, DEFAULT_MEDIA_PLAYER_NAME)
        self._attr_device_info = device_info
        self._device_code = config.get(CONF_DEVICE_CODE)
        self._controller_data = resolve_controller_data(config)
        self._delay = normalize_delay(config.get(CONF_DELAY))
        self._power_sensor = config.get(CONF_POWER_SENSOR)

        self._manufacturer = device_data['manufacturer']
        self._supported_models = device_data['supportedModels']
        self._supported_controller = device_data['supportedController']
        self._commands_encoding = device_data['commandsEncoding']
        self._commands = device_data['commands']

        self._state = STATE_OFF
        self._sources_list = []
        self._source = None
        self._support_flags = 0

        self._device_class = config.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS)

        #Supported features
        if 'off' in self._commands and self._commands['off'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.TURN_OFF

        if 'on' in self._commands and self._commands['on'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.TURN_ON

        if 'previousChannel' in self._commands and self._commands['previousChannel'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.PREVIOUS_TRACK

        if 'nextChannel' in self._commands and self._commands['nextChannel'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.NEXT_TRACK

        if ('volumeDown' in self._commands and self._commands['volumeDown'] is not None) \
        or ('volumeUp' in self._commands and self._commands['volumeUp'] is not None):
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.VOLUME_STEP

        if 'mute' in self._commands and self._commands['mute'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.VOLUME_MUTE

        if 'sources' in self._commands and self._commands['sources'] is not None:
            self._support_flags = self._support_flags | MediaPlayerEntityFeature.SELECT_SOURCE | MediaPlayerEntityFeature.PLAY_MEDIA

            for source, new_name in config.get(CONF_SOURCE_NAMES, {}).items():
                if source in self._commands['sources']:
                    if new_name is not None:
                        self._commands['sources'][new_name] = self._commands['sources'][source]

                    del self._commands['sources'][source]

            #Sources list
            for key in self._commands['sources']:
                self._sources_list.append(key)

        self._temp_lock = asyncio.Lock()

        #Init the IR/RF controller
        self._controller = get_controller(
            self.hass,
            self._supported_controller, 
            self._commands_encoding,
            self._controller_data,
            self._delay)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None:
            self._state = last_state.state

    @property
    def should_poll(self):
        """Push an update after each command."""
        return True

    @property
    def device_class(self):
        """Return the device_class of the media player."""
        return self._device_class

    @property
    def state(self):
        """Return the state of the player."""
        return self._state

    @property
    def media_title(self):
        """Return the title of current playing media."""
        return None

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MediaType.CHANNEL

    @property
    def source_list(self):
        return self._sources_list
        
    @property
    def source(self):
        return self._source

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return self._support_flags

    @property
    def extra_state_attributes(self):
        """Platform specific attributes."""
        return {
            'device_code': self._device_code,
            'manufacturer': self._manufacturer,
            'supported_models': self._supported_models,
            'supported_controller': self._supported_controller,
            'commands_encoding': self._commands_encoding,
        }

    async def async_turn_off(self):
        """Turn the media player off."""
        await self.send_command(self._commands['off'])
        
        if self._power_sensor is None:
            self._state = STATE_OFF
            self._source = None
            self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn the media player off."""
        await self.send_command(self._commands['on'])

        if self._power_sensor is None:
            self._state = STATE_ON
            self.async_write_ha_state()

    async def async_media_previous_track(self):
        """Send previous track command."""
        await self.send_command(self._commands['previousChannel'])
        self.async_write_ha_state()

    async def async_media_next_track(self):
        """Send next track command."""
        await self.send_command(self._commands['nextChannel'])
        self.async_write_ha_state()

    async def async_volume_down(self):
        """Turn volume down for media player."""
        await self.send_command(self._commands['volumeDown'])
        self.async_write_ha_state()

    async def async_volume_up(self):
        """Turn volume up for media player."""
        await self.send_command(self._commands['volumeUp'])
        self.async_write_ha_state()
    
    async def async_mute_volume(self, mute):
        """Mute the volume."""
        await self.send_command(self._commands['mute'])
        self.async_write_ha_state()

    async def async_select_source(self, source):
        """Select channel from source."""
        self._source = source
        await self.send_command(self._commands['sources'][source])
        self.async_write_ha_state()

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Support channel change through play_media service."""
        if self._state == STATE_OFF:
            await self.async_turn_on()

        if media_type != MediaType.CHANNEL:
            _LOGGER.error("invalid media type")
            return
        if not media_id.isdigit():
            _LOGGER.error("media_id must be a channel number")
            return

        self._source = "Channel {}".format(media_id)
        for digit in media_id:
            await self.send_command(self._commands['sources']["Channel {}".format(digit)])
        self.async_write_ha_state()

    async def send_command(self, command):
        async with self._temp_lock:
            try:
                await self._controller.send(command)
            except Exception as e:
                _LOGGER.exception(e)
            
    async def async_update(self):
        if self._power_sensor is None:
            return

        power_state = self.hass.states.get(self._power_sensor)

        if power_state:
            if power_state.state == STATE_OFF:
                self._state = STATE_OFF
                self._source = None
            elif power_state.state == STATE_ON:
                self._state = STATE_ON
