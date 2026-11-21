"""Diagnostics support for the Dolby DSS220 integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import DSSConfigEntry

# A diagnostics file is made to be attached to a public issue. The address and
# the identifiers of the server and its components identify the installation
# and are not needed to find a fault, so they never leave Home Assistant.
TO_REDACT = {CONF_HOST, "unique_id", "component_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DSSConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    state: dict[str, Any] = asdict(data) if data is not None else {}
    for key in ("last_seen", "position_updated_at"):
        if state.get(key) is not None:
            state[key] = state[key].isoformat()
    # The show list can be long; the number and the selected show are enough.
    state["shows"] = len(state.get("shows", {}))
    current_show = data.current_show if data is not None else None
    return async_redact_data(
        {
            "config": dict(entry.data),
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
            "allow_control": coordinator.allow_control,
            "unavailable_features": coordinator.unavailable_features,
            "current_show": asdict(current_show) if current_show is not None else None,
            "components": [asdict(component) for component in coordinator.components],
            "state": state,
        },
        TO_REDACT,
    )
