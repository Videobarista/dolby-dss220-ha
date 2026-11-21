"""Switch entities for the Dolby DSS220 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DSSConfigEntry
from .api import DSSClient
from .coordinator import DSSCoordinator, DSSData
from .entity import DSSEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DSSSwitchDescription(SwitchEntityDescription):
    """Describes a DSS switch entity."""

    value_fn: Callable[[DSSData], bool | None]
    set_fn: Callable[[DSSClient], Callable[[bool], Awaitable[None]]]


SWITCHES: tuple[DSSSwitchDescription, ...] = (
    # On means the douser is closed (picture blocked), as reported by the server.
    DSSSwitchDescription(
        key="douser",
        translation_key="douser",
        value_fn=lambda data: data.doused,
        set_fn=lambda client: client.set_douser,
    ),
    DSSSwitchDescription(
        key="lamp",
        translation_key="lamp",
        value_fn=lambda data: data.lamp_on,
        set_fn=lambda client: client.set_lamp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch entities."""
    coordinator = entry.runtime_data
    async_add_entities(DSSSwitch(coordinator, description) for description in SWITCHES)


class DSSSwitch(DSSEntity, SwitchEntity):
    """A projector function controlled through the DSS server."""

    entity_description: DSSSwitchDescription

    def __init__(self, coordinator: DSSCoordinator, description: DSSSwitchDescription) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return whether the value is known."""
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._async_command(self.entity_description.set_fn(self.coordinator.client), True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._async_command(self.entity_description.set_fn(self.coordinator.client), False)
