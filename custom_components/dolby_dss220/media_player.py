"""Media player for the Dolby DSS220 integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DSSConfigEntry
from .const import DOMAIN
from .coordinator import DSSCoordinator
from .entity import DSSEntity
from .soap import ShowInfo

PARALLEL_UPDATES = 1

STATE_MAP: dict[str, MediaPlayerState] = {
    "PLAYING": MediaPlayerState.PLAYING,
    "PAUSED": MediaPlayerState.PAUSED,
    "SELECTING": MediaPlayerState.BUFFERING,
    "SEEKING": MediaPlayerState.BUFFERING,
    "RECOVERING": MediaPlayerState.BUFFERING,
    "LATE": MediaPlayerState.BUFFERING,
    "READY": MediaPlayerState.IDLE,
    "STOPPED": MediaPlayerState.IDLE,
    "UNSELECTED": MediaPlayerState.IDLE,
    # The server is up, but the media block cannot play (e.g. switched off).
    # The transport state sensor and attribute tell the two idle cases apart.
    "UNAVAILABLE": MediaPlayerState.IDLE,
}

CONTROL_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


def source_map(shows: dict[str, ShowInfo]) -> dict[str, str]:
    """Map a unique, readable source name to the id of each playable show."""
    playable = sorted(
        (show for show in shows.values() if show.playable),
        key=lambda show: (show.name.casefold(), show.show_id),
    )
    counts: dict[str, int] = {}
    for show in playable:
        counts[show.name] = counts.get(show.name, 0) + 1
    result: dict[str, str] = {}
    for show in playable:
        name = show.name
        if counts[name] > 1:
            name = f"{name} ({show.show_id.removeprefix('urn:uuid:')[:8]})"
        result[name] = show.show_id
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    async_add_entities([DSSMediaPlayer(entry.runtime_data)])


class DSSMediaPlayer(DSSEntity, MediaPlayerEntity):
    """The playback side of the DSS server."""

    _attr_name = None
    _attr_media_content_type = MediaType.VIDEO
    _attr_volume_step = 0.05
    _available_when_offline = True

    def __init__(self, coordinator: DSSCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, "media_player")

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state."""
        data = self.coordinator.data
        if not data.online:
            return MediaPlayerState.OFF
        if data.playback is None:
            return MediaPlayerState.ON
        return STATE_MAP.get(data.playback.transport_state, MediaPlayerState.ON)

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the supported features; control is opt-in."""
        data = self.coordinator.data
        if not self.coordinator.allow_control or not data.online:
            return MediaPlayerEntityFeature(0)
        features = CONTROL_FEATURES
        if data.volume is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
        if data.muted is not None:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        return features

    @property
    def media_content_id(self) -> str | None:
        """Return the id of the selected show or clip."""
        playback = self.coordinator.data.playback
        return playback.content_id if playback else None

    @property
    def media_title(self) -> str | None:
        """Return the name of the clip (CPL) that is playing."""
        data = self.coordinator.data
        if data.playback is None or not data.playback.current_clip_id:
            return None
        return data.current_clip_name or data.playback.current_clip_id

    @property
    def media_playlist(self) -> str | None:
        """Return the name of the selected show (SPL)."""
        data = self.coordinator.data
        show = data.current_show
        if show is not None:
            return show.name
        return data.playback.content_id if data.playback else None

    @property
    def media_duration(self) -> int | None:
        """Return the duration of the current clip in seconds."""
        playback = self.coordinator.data.playback
        if playback is None or playback.clip_duration is None:
            return None
        return int(playback.clip_duration)

    @property
    def media_position(self) -> int | None:
        """Return the position within the current clip in seconds."""
        playback = self.coordinator.data.playback
        if playback is None or playback.clip_position is None:
            return None
        return int(playback.clip_position)

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Return when the position was last read."""
        return self.coordinator.data.position_updated_at

    @property
    def source(self) -> str | None:
        """Return the selected show."""
        show = self.coordinator.data.current_show
        if show is None:
            return None
        for name, show_id in source_map(self.coordinator.data.shows).items():
            if show_id == show.show_id:
                return name
        return show.name

    @property
    def source_list(self) -> list[str]:
        """Return all playable shows."""
        return list(source_map(self.coordinator.data.shows))

    @property
    def volume_level(self) -> float | None:
        """Return the cinema processor fader as 0..1."""
        volume = self.coordinator.data.volume
        return None if volume is None else max(0.0, min(1.0, volume / 10))

    @property
    def is_volume_muted(self) -> bool | None:
        """Return whether audio is muted."""
        return self.coordinator.data.muted

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra playback details."""
        playback = self.coordinator.data.playback
        if playback is None:
            return {}
        return {
            "transport_state": playback.transport_state.lower(),
            "unavailable_reasons": [reason.lower() for reason in playback.unavailable_reasons],
            "clip_index": playback.current_clip_index,
            "show_position": playback.show_position,
            "show_duration": playback.show_duration,
        }

    async def async_media_play(self) -> None:
        """Start or resume playback."""
        await self._async_command(self.coordinator.client.play)

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._async_command(self.coordinator.client.pause)

    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self._async_command(self.coordinator.client.stop)

    async def async_media_next_track(self) -> None:
        """Jump to the next clip."""
        await self._async_command(self.coordinator.client.next)

    async def async_media_previous_track(self) -> None:
        """Jump to the previous clip."""
        await self._async_command(self.coordinator.client.previous)

    async def async_media_seek(self, position: float) -> None:
        """Seek within the current clip.

        The server positions within the whole show, so the start of the current
        clip in the show is added to the requested clip position.
        """
        target = float(position)
        playback = self.coordinator.data.playback
        if (
            playback is not None
            and playback.show_position is not None
            and playback.clip_position is not None
        ):
            target += playback.show_position - playback.clip_position
        await self._async_command(self.coordinator.client.go_to_position, max(0.0, target))

    async def async_select_source(self, source: str) -> None:
        """Select a show for playback."""
        show_id = source_map(self.coordinator.data.shows).get(source)
        if show_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": source},
            )
        await self._async_command(self.coordinator.client.select_content, show_id, "SHOW")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the cinema processor fader."""
        await self._async_command(
            self.coordinator.client.set_volume, round(max(0.0, min(1.0, volume)) * 10, 1)
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute audio."""
        await self._async_command(self.coordinator.client.set_mute, mute)
