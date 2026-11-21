"""Data update coordinator for the Dolby DSS220 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
import logging
import time
from typing import TYPE_CHECKING, TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import DSSClient
from .const import (
    CLIP_CACHE_SIZE,
    CONF_ALLOW_CONTROL,
    DEFAULT_ALLOW_CONTROL,
    DOMAIN,
    MEDIUM_INTERVAL,
    SCAN_INTERVAL,
    SLOW_INTERVAL,
)
from .soap import (
    UUID_RE,
    DeviceAlarm,
    DeviceComponent,
    DSSConnectionError,
    DSSError,
    PlaybackState,
    ShowInfo,
    find_server_component,
)

if TYPE_CHECKING:
    from . import DSSConfigEntry

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(slots=True)
class DSSData:
    """Snapshot of the server state."""

    online: bool
    playback: PlaybackState | None = None
    input_select: str | None = None
    schedule_mode: str | None = None
    volume: float | None = None
    muted: bool | None = None
    doused: bool | None = None
    lamp_on: bool | None = None
    shows: dict[str, ShowInfo] = field(default_factory=dict)
    current_clip_name: str | None = None
    clock_offset: float | None = None
    time_zone: str | None = None
    alarms: tuple[DeviceAlarm, ...] = ()
    last_seen: datetime | None = None
    response_time: float | None = None
    position_updated_at: datetime | None = None

    @property
    def current_show(self) -> ShowInfo | None:
        """Return the selected show, if any."""
        if self.playback is None or not self.playback.content_id:
            return None
        return self.shows.get(self.playback.content_id)


class DSSCoordinator(DataUpdateCoordinator[DSSData]):
    """Poll the DSS server.

    An unreachable server is not an error: the server is regularly switched
    off, so it is reported as offline (media player "off") instead of making
    the config entry fail.
    """

    config_entry: DSSConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DSSConfigEntry, client: DSSClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._online = True
        self._force_full = True
        self._next_medium = 0.0
        self._next_slow = 0.0
        self._last_seen: datetime | None = None
        self._unavailable: set[str] = set()
        self._shows: dict[str, ShowInfo] = {}
        self._show_lookups: set[str] = set()
        self._clip_names: dict[str, str | None] = {}
        self._schedule_mode: str | None = None
        self._volume: float | None = None
        self._muted: bool | None = None
        self._doused: bool | None = None
        self._lamp_on: bool | None = None
        self._clock_offset: float | None = None
        self._time_zone: str | None = None
        self._alarms: tuple[DeviceAlarm, ...] = ()
        self._components: tuple[DeviceComponent, ...] = ()
        self._sw_version: str | None = None
        self._position_key: tuple[object, ...] | None = None
        self._position_updated_at: datetime | None = None

    @property
    def allow_control(self) -> bool:
        """Return whether control commands are allowed for this entry."""
        return bool(self.config_entry.options.get(CONF_ALLOW_CONTROL, DEFAULT_ALLOW_CONTROL))

    @property
    def device_identifier(self) -> str:
        """Return the identifier used for the device registry."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    @property
    def components(self) -> tuple[DeviceComponent, ...]:
        """Return the device components reported by the server."""
        return self._components

    @property
    def unavailable_features(self) -> list[str]:
        """Return the getters the server currently answers with a fault."""
        return sorted(self._unavailable)

    async def async_request_full_refresh(self) -> None:
        """Refresh everything (used after a command)."""
        self._force_full = True
        await self.async_request_refresh()

    async def _optional(self, key: str, func: Callable[[], Awaitable[_T]]) -> _T | None:
        """Call a getter whose feature may not exist on every system.

        A SOAP fault (for example no cinema processor or projector connected)
        makes the value unknown instead of failing the whole update. The first
        occurrence is logged; connection errors are passed on.
        """
        try:
            value = await func()
        except DSSConnectionError:
            raise
        except DSSError as err:
            if key not in self._unavailable:
                self._unavailable.add(key)
                _LOGGER.info("%s is not available on this system: %s", key, err)
            return None
        if key in self._unavailable:
            self._unavailable.discard(key)
            _LOGGER.debug("%s is available again", key)
        return value

    def _offline_data(self) -> DSSData:
        """Return the data shown while the server is unreachable."""
        return DSSData(online=False, shows=dict(self._shows), last_seen=self._last_seen)

    async def _async_update_data(self) -> DSSData:
        """Fetch data from the server."""
        try:
            return await self._async_fetch()
        except DSSConnectionError as err:
            if self._online:
                _LOGGER.info("Dolby DSS at %s is offline: %s", self.client.base_url, err)
            self._online = False
            self._force_full = True
            return self._offline_data()

    async def _async_fetch(self) -> DSSData:
        """Fetch all values; raises DSSConnectionError when unreachable."""
        started = time.monotonic()
        playback = await self._optional("playback_state", self.client.get_playback_state)
        response_time = round((time.monotonic() - started) * 1000, 1)

        if not self._online:
            _LOGGER.info("Dolby DSS at %s is back online", self.client.base_url)
        self._online = True
        now = dt_util.utcnow()
        self._last_seen = now

        input_select = await self._optional("input_select", self.client.get_input_select)

        mono = time.monotonic()
        if self._force_full or mono >= self._next_medium:
            self._schedule_mode = await self._optional(
                "schedule_mode", self.client.get_schedule_mode
            )
            self._volume = await self._optional("volume", self.client.get_volume)
            self._muted = await self._optional("mute", self.client.get_mute)
            self._doused = await self._optional("douser", self.client.get_douser)
            self._lamp_on = await self._optional("lamp", self.client.get_lamp)
            self._next_medium = mono + MEDIUM_INTERVAL.total_seconds()

        periodic = self._force_full or mono >= self._next_slow
        if periodic:
            # A show that was still unknown after a lookup is tried again now.
            self._show_lookups.clear()
        unknown_show = (
            playback.content_id
            if playback is not None
            and playback.content_type == "SHOW"
            and playback.content_id
            and playback.content_id not in self._shows
            and playback.content_id not in self._show_lookups
            else None
        )
        if periodic or unknown_show:
            if unknown_show:
                # A newly selected show: look it up once, not on every poll.
                self._show_lookups.add(unknown_show)
            await self._async_fetch_slow()
            self._next_slow = mono + SLOW_INTERVAL.total_seconds()

        self._force_full = False

        return DSSData(
            online=True,
            playback=playback,
            input_select=input_select,
            schedule_mode=self._schedule_mode,
            volume=self._volume,
            muted=self._muted,
            doused=self._doused,
            lamp_on=self._lamp_on,
            shows=dict(self._shows),
            current_clip_name=await self._async_clip_name(playback),
            clock_offset=self._clock_offset,
            time_zone=self._time_zone,
            alarms=self._alarms,
            last_seen=now,
            response_time=response_time,
            position_updated_at=self._position_timestamp(playback, now),
        )

    def _position_timestamp(self, playback: PlaybackState | None, now: datetime) -> datetime | None:
        """Return when the reported position last changed.

        Keeping the timestamp while nothing moves avoids a state change (and a
        recorder write) on every poll of a stopped or paused server.
        """
        if playback is None:
            self._position_key = None
            self._position_updated_at = None
            return None
        key = (
            playback.transport_state,
            playback.current_clip_id,
            playback.clip_position,
            playback.show_position,
        )
        if key != self._position_key or self._position_updated_at is None:
            self._position_key = key
            self._position_updated_at = now
        return self._position_updated_at

    async def _async_fetch_slow(self) -> None:
        """Fetch values that rarely change: shows, clock and alarms."""
        shows = await self._optional("shows", self.client.get_show_infos)
        if shows is not None:
            self._shows = {show.show_id: show for show in shows}
            # Retry clips whose name could not be looked up earlier.
            self._clip_names = {
                key: value for key, value in self._clip_names.items() if value is not None
            }

        system_time = await self._optional("system_time", self.client.get_system_time)
        if system_time is not None and system_time.time is not None:
            self._clock_offset = round((system_time.time - dt_util.utcnow()).total_seconds(), 1)
            self._time_zone = system_time.time_zone
        else:
            self._clock_offset = None
            self._time_zone = None

        components = await self._optional("device_components", self.client.get_device_components)
        if components is None:
            self._alarms = ()
            return
        self._components = tuple(components)
        self._alarms = tuple(alarm for component in components for alarm in component.alarms)
        server = find_server_component(components)
        if (
            server is not None
            and server.version
            and server.version != self._sw_version
            and self._update_device_version(server.version)
        ):
            self._sw_version = server.version

    def _update_device_version(self, version: str) -> bool:
        """Store the reported software version in the device registry.

        Returns False while the device is not registered yet (the first poll runs
        before the entities create it), so the next slow poll tries again.
        """
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self.device_identifier)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if identifier in device.identifiers:
                if device.sw_version != version:
                    registry.async_update_device(device.id, sw_version=version)
                return True
        return False

    async def _async_clip_name(self, playback: PlaybackState | None) -> str | None:
        """Return the name of the clip that is currently playing."""
        if playback is None or not playback.current_clip_id:
            return None
        clip_id = playback.current_clip_id
        if clip_id in self._clip_names:
            return self._clip_names[clip_id]
        clip = None
        if UUID_RE.match(clip_id):
            clip = await self._optional("clip_info", partial(self.client.get_clip_info, clip_id))
        name = clip.name if clip is not None else None
        if len(self._clip_names) >= CLIP_CACHE_SIZE:
            self._clip_names.pop(next(iter(self._clip_names)))
        self._clip_names[clip_id] = name
        return name
