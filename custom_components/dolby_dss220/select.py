"""Select entities for the Dolby DSS220 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DSSConfigEntry
from .api import DSSClient
from .const import INPUT_OPTIONS
from .coordinator import DSSCoordinator, DSSData
from .entity import DSSEntity
from .soap import SCHEDULE_MODES

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DSSSelectDescription(SelectEntityDescription):
    """Describes a DSS select entity."""

    base_options: tuple[str, ...]
    value_fn: Callable[[DSSData], str | None]
    set_fn: Callable[[DSSClient], Callable[[str], Awaitable[None]]]


SELECTS: tuple[DSSSelectDescription, ...] = (
    DSSSelectDescription(
        key="input",
        translation_key="input",
        base_options=INPUT_OPTIONS,
        value_fn=lambda data: data.input_select,
        set_fn=lambda client: client.set_input_select,
    ),
    DSSSelectDescription(
        key="schedule_mode",
        translation_key="schedule_mode",
        entity_category=EntityCategory.CONFIG,
        base_options=SCHEDULE_MODES,
        value_fn=lambda data: data.schedule_mode,
        set_fn=lambda client: client.set_schedule_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities."""
    coordinator = entry.runtime_data
    async_add_entities(DSSSelect(coordinator, description) for description in SELECTS)


class DSSSelect(DSSEntity, SelectEntity):
    """A DSS setting with a fixed set of values."""

    entity_description: DSSSelectDescription

    def __init__(self, coordinator: DSSCoordinator, description: DSSSelectDescription) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def _raw_value(self) -> str | None:
        """Return the value as reported by the server."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return whether the value is known."""
        return super().available and self._raw_value is not None

    @property
    def options(self) -> list[str]:
        """Return the selectable options."""
        options = [option.lower() for option in self.entity_description.base_options]
        current = self.current_option
        if current is not None and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        value = self._raw_value
        return value.lower() if value else None

    async def async_select_option(self, option: str) -> None:
        """Change the value on the server."""
        await self._async_command(
            self.entity_description.set_fn(self.coordinator.client), option.upper()
        )
