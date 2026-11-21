"""The Dolby DSS220 integration.

Uses the official Dolby SMI web services (SOAP over HTTP, TCP port 8080) of the
Dolby DSS200/DSS220 Show Store. No web interface is used.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DSSClient
from .coordinator import DSSCoordinator

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type DSSConfigEntry = ConfigEntry[DSSCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DSSConfigEntry) -> bool:
    """Set up a Dolby DSS220 from a config entry."""
    client = DSSClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
    )
    coordinator = DSSCoordinator(hass, entry, client)
    # An unreachable server does not fail the setup: it is shown as offline.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DSSConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
