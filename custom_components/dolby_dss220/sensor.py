"""Sensor entities for the Dolby DSS220 integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import DSSConfigEntry
from .coordinator import DSSCoordinator, DSSData
from .entity import DSSEntity
from .soap import TRANSPORT_STATES

PARALLEL_UPDATES = 0


def timecode(position: float | None, duration: float | None) -> str | None:
    """Return 'HH:MM:SS / HH:MM:SS' for a position and duration."""
    if position is None or duration is None:
        return None
    return f"{_hms(position)} / {_hms(duration)}"


def _hms(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def remaining(position: float | None, duration: float | None) -> float | None:
    """Return the remaining time in seconds."""
    if position is None or duration is None:
        return None
    return round(max(0.0, duration - position), 1)


def _transport_state(data: DSSData) -> str | None:
    if data.playback is None:
        return None
    state = data.playback.transport_state.lower()
    return state if state.upper() in TRANSPORT_STATES else None


def _current_show(data: DSSData) -> str | None:
    show = data.current_show
    if show is not None:
        return show.name
    return data.playback.content_id if data.playback else None


def _current_clip(data: DSSData) -> str | None:
    if data.playback is None or not data.playback.current_clip_id:
        return None
    return data.current_clip_name or data.playback.current_clip_id


def _clip_timecode(data: DSSData) -> str | None:
    playback = data.playback
    return timecode(playback.clip_position, playback.clip_duration) if playback else None


def _clip_remaining(data: DSSData) -> float | None:
    playback = data.playback
    return remaining(playback.clip_position, playback.clip_duration) if playback else None


def _show_timecode(data: DSSData) -> str | None:
    playback = data.playback
    return timecode(playback.show_position, playback.show_duration) if playback else None


def _show_remaining(data: DSSData) -> float | None:
    playback = data.playback
    return remaining(playback.show_position, playback.show_duration) if playback else None


def _alarm_attributes(data: DSSData) -> dict[str, Any]:
    return {
        "alarms": [
            f"{alarm.component}: {alarm.name or alarm.alarm_type.lower()} "
            f"({alarm.severity.lower()})"
            for alarm in data.alarms
        ]
    }


def _clock_attributes(data: DSSData) -> dict[str, Any]:
    return {"time_zone": data.time_zone}


def _show_attributes(data: DSSData) -> dict[str, Any]:
    return {"show_id": data.playback.content_id if data.playback else None}


def _clip_attributes(data: DSSData) -> dict[str, Any]:
    playback = data.playback
    return {
        "clip_id": playback.current_clip_id if playback else None,
        "clip_index": playback.current_clip_index if playback else None,
    }


@dataclass(frozen=True, kw_only=True)
class DSSSensorDescription(SensorEntityDescription):
    """Describes a DSS sensor entity."""

    value_fn: Callable[[DSSData], StateType | datetime]
    attributes_fn: Callable[[DSSData], dict[str, Any]] | None = None
    available_when_offline: bool = False


SENSORS: tuple[DSSSensorDescription, ...] = (
    DSSSensorDescription(
        key="transport_state",
        translation_key="transport_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.lower() for state in TRANSPORT_STATES],
        value_fn=_transport_state,
    ),
    DSSSensorDescription(
        key="current_show",
        translation_key="current_show",
        value_fn=_current_show,
        attributes_fn=_show_attributes,
    ),
    DSSSensorDescription(
        key="current_clip",
        translation_key="current_clip",
        value_fn=_current_clip,
        attributes_fn=_clip_attributes,
    ),
    DSSSensorDescription(
        key="clip_timecode",
        translation_key="clip_timecode",
        value_fn=_clip_timecode,
    ),
    DSSSensorDescription(
        key="clip_remaining",
        translation_key="clip_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=_clip_remaining,
    ),
    DSSSensorDescription(
        key="show_timecode",
        translation_key="show_timecode",
        value_fn=_show_timecode,
    ),
    DSSSensorDescription(
        key="show_remaining",
        translation_key="show_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=_show_remaining,
    ),
    DSSSensorDescription(
        key="alarms",
        translation_key="alarms",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.alarms),
        attributes_fn=_alarm_attributes,
    ),
    DSSSensorDescription(
        key="clock_offset",
        translation_key="clock_offset",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda data: data.clock_offset,
        attributes_fn=_clock_attributes,
    ),
    DSSSensorDescription(
        key="response_time",
        translation_key="response_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda data: data.response_time,
    ),
    DSSSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_seen,
        available_when_offline=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities(DSSSensor(coordinator, description) for description in SENSORS)


class DSSSensor(DSSEntity, SensorEntity):
    """A value read from the DSS server."""

    entity_description: DSSSensorDescription

    def __init__(self, coordinator: DSSCoordinator, description: DSSSensorDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._available_when_offline = description.available_when_offline

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
