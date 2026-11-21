"""Base entity for the Dolby DSS220 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, CONF_SW_VERSION, DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import DSSCoordinator
from .soap import DSSError


class DSSEntity(CoordinatorEntity[DSSCoordinator]):
    """Common base for all Dolby DSS220 entities."""

    _attr_has_entity_name = True
    # Entities that keep reporting (e.g. "off") while the server is unreachable.
    _available_when_offline = False

    def __init__(self, coordinator: DSSCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{coordinator.device_identifier}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_identifier)},
            manufacturer=MANUFACTURER,
            model=entry.data.get(CONF_MODEL) or DEFAULT_MODEL,
            name=entry.title,
            sw_version=entry.data.get(CONF_SW_VERSION),
        )

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        if not super().available:
            return False
        return self._available_when_offline or self.coordinator.data.online

    async def _async_command(self, func: Callable[..., Awaitable[None]], *args: Any) -> None:
        """Run a control command, then refresh the state."""
        if not self.coordinator.allow_control:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="control_disabled"
            )
        try:
            await func(*args)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        except DSSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_full_refresh()
