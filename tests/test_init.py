"""Tests for setting up, polling and unloading the Dolby DSS220 integration."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.dolby_dss220.const import CONF_ALLOW_CONTROL, DOMAIN
from custom_components.dolby_dss220.diagnostics import async_get_config_entry_diagnostics
from custom_components.dolby_dss220.soap import DSSConnectionError, DSSFaultError, PlaybackState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import CLIP_ID, SHOW3_ID, SW_VERSION, UNIQUE_ID


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look an entity up by its unique ID, independent of its name."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{UNIQUE_ID}_{key}")
    assert found is not None, f"{platform} {key} was not created"
    return found


def state(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return the state of an entity looked up by its unique ID."""
    current = hass.states.get(entity_id(hass, platform, key))
    assert current is not None
    return current.state


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up the entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant) -> None:
    """Let the next regular poll run."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads, creates the device and its entities, and unloads cleanly."""
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, UNIQUE_ID)})
    assert device is not None
    assert device.manufacturer == "Dolby"
    assert device.model == "DSS220"
    assert device.sw_version == SW_VERSION

    assert state(hass, "media_player", "media_player") == "playing"
    assert state(hass, "select", "input") == "server"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_while_offline(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A server that is switched off is set up anyway and shown as off."""
    mock_client.get_playback_state.side_effect = DSSConnectionError("timeout")
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert state(hass, "media_player", "media_player") == STATE_OFF
    assert state(hass, "select", "input") == STATE_UNAVAILABLE
    assert state(hass, "switch", "douser") == STATE_UNAVAILABLE
    assert state(hass, "sensor", "transport_state") == STATE_UNAVAILABLE
    assert state(hass, "sensor", "last_seen") == STATE_UNKNOWN

    # The server comes back.
    mock_client.get_playback_state.side_effect = None
    await poll(hass)
    assert state(hass, "media_player", "media_player") == "playing"
    assert state(hass, "switch", "douser") == STATE_OFF
    assert state(hass, "sensor", "last_seen") != STATE_UNKNOWN


async def test_goes_offline(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A server that stops answering turns off; last seen stays."""
    await setup_entry(hass, mock_config_entry)
    last_seen = state(hass, "sensor", "last_seen")

    mock_client.get_playback_state.side_effect = DSSConnectionError("connection refused")
    await poll(hass)
    assert state(hass, "media_player", "media_player") == STATE_OFF
    assert state(hass, "sensor", "current_clip") == STATE_UNAVAILABLE
    assert state(hass, "sensor", "last_seen") == last_seen

    # A connection error halfway through a poll counts as offline too.
    mock_client.get_playback_state.side_effect = None
    mock_client.get_input_select.side_effect = DSSConnectionError("connection reset")
    await poll(hass)
    assert state(hass, "media_player", "media_player") == STATE_OFF


async def test_missing_features(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A getter the server answers with a fault makes only that value unknown."""
    fault = DSSFaultError("NotConnected", "Projector not connected")
    mock_client.get_douser.side_effect = fault
    mock_client.get_lamp.side_effect = fault
    mock_client.get_volume.side_effect = fault
    mock_client.get_device_components.side_effect = fault
    await setup_entry(hass, mock_config_entry)

    assert state(hass, "switch", "douser") == STATE_UNAVAILABLE
    assert state(hass, "switch", "lamp") == STATE_UNAVAILABLE
    assert state(hass, "media_player", "media_player") == "playing"
    assert state(hass, "sensor", "alarms") == "0"

    # Once the projector answers again the values return.
    mock_client.get_douser.side_effect = None
    mock_client.get_lamp.side_effect = None
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "switch", "douser") == STATE_OFF
    assert state(hass, "switch", "lamp") == "on"


async def test_unknown_show_looked_up_once(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A newly selected show triggers one extra show list lookup, not one per poll."""
    await setup_entry(hass, mock_config_entry)
    assert mock_client.get_show_infos.await_count == 1

    mock_client.get_playback_state.return_value = PlaybackState(
        transport_state="STOPPED", content_id=SHOW3_ID, content_type="SHOW"
    )
    await poll(hass)
    assert mock_client.get_show_infos.await_count == 2
    await poll(hass)
    await poll(hass)
    assert mock_client.get_show_infos.await_count == 2


async def test_clip_name_cached(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The clip name is looked up once per clip."""
    await setup_entry(hass, mock_config_entry)
    await poll(hass)
    await poll(hass)
    mock_client.get_clip_info.assert_awaited_once_with(CLIP_ID)


async def test_clip_name_unknown(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Without a clip name the clip ID is shown; an invalid ID is never sent."""
    mock_client.get_clip_info.side_effect = DSSFaultError("NotFound", None)
    await setup_entry(hass, mock_config_entry)
    assert state(hass, "sensor", "current_clip") == CLIP_ID

    mock_client.get_playback_state.return_value = PlaybackState(
        transport_state="PLAYING",
        content_id="not-a-uuid",
        content_type="SHOW",
        current_clip_id="also-not-a-uuid",
    )
    await poll(hass)
    assert state(hass, "sensor", "current_clip") == "also-not-a-uuid"
    assert state(hass, "sensor", "current_show") == "not-a-uuid"
    assert mock_client.get_clip_info.await_count == 1


async def test_position_timestamp_kept_while_stopped(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """While nothing moves the position timestamp does not change on every poll."""
    mock_client.get_playback_state.return_value = PlaybackState(
        transport_state="PAUSED",
        content_id="urn:uuid:11111111-2222-3333-4444-555555555555",
        content_type="SHOW",
        clip_position=10.0,
        clip_duration=20.0,
    )
    await setup_entry(hass, mock_config_entry)
    player = entity_id(hass, "media_player", "media_player")
    first = hass.states.get(player).attributes["media_position_updated_at"]
    await poll(hass)
    assert hass.states.get(player).attributes["media_position_updated_at"] == first


async def test_options_update_applies_without_reload(
    hass: HomeAssistant, mock_client: MagicMock, read_only_config_entry: MockConfigEntry
) -> None:
    """Switching control on in the options shows the controls at the next poll."""
    await setup_entry(hass, read_only_config_entry)
    player = entity_id(hass, "media_player", "media_player")
    assert hass.states.get(player).attributes.get("supported_features", 0) == 0

    hass.config_entries.async_update_entry(
        read_only_config_entry, options={CONF_ALLOW_CONTROL: True}
    )
    await poll(hass)
    assert hass.states.get(player).attributes["supported_features"] != 0
    assert read_only_config_entry.state is ConfigEntryState.LOADED


async def test_diagnostics(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Diagnostics show the state and leave out the address and identifiers."""
    mock_client.get_lamp.side_effect = DSSFaultError("NotConnected", None)
    await setup_entry(hass, mock_config_entry)

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["config"]["host"] == "**REDACTED**"
    assert result["unique_id"] == "**REDACTED**"
    assert result["allow_control"] is True
    assert result["unavailable_features"] == ["lamp"]
    assert result["current_show"]["name"] == "Demo Show"
    assert result["components"][0]["component_id"] == "**REDACTED**"
    assert result["components"][0]["model"] == "DSS220"
    assert result["state"]["online"] is True
    assert result["state"]["shows"] == 2
    assert result["state"]["playback"]["transport_state"] == "PLAYING"
    assert isinstance(result["state"]["last_seen"], str)
