"""Tests for the Dolby DSS220 media player."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_dss220.media_player import source_map
from custom_components.dolby_dss220.soap import (
    DSSConnectionError,
    DSSFaultError,
    PlaybackState,
    ShowInfo,
)
from homeassistant.components.media_player.const import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_SEEK_POSITION,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MP_DOMAIN,
    SERVICE_SELECT_SOURCE,
    MediaPlayerEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_SEEK,
    SERVICE_MEDIA_STOP,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import CLIP_NAME, SHOW2_ID, SHOW3_ID, SHOW_ID
from .test_init import entity_id, poll, setup_entry


async def _player(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Set up the entry and return the media player entity ID."""
    await setup_entry(hass, entry)
    return entity_id(hass, "media_player", "media_player")


async def _call(hass: HomeAssistant, service: str, player: str, **data: Any) -> None:
    """Call a media player service and wait for it."""
    await hass.services.async_call(
        MP_DOMAIN, service, {ATTR_ENTITY_ID: player, **data}, blocking=True
    )


async def test_playing_state(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A playing show shows the clip as title and the show as playlist."""
    player = await _player(hass, mock_config_entry)
    current = hass.states.get(player)

    assert current.state == "playing"
    attributes = current.attributes
    assert attributes["media_title"] == CLIP_NAME
    assert attributes["media_playlist"] == "Demo Show"
    assert attributes["media_content_id"] == SHOW_ID
    assert attributes["media_duration"] == 153
    assert attributes["media_position"] == 65
    assert attributes["source"] == "Demo Show"
    # The trailer reel misses its KDM and is not offered.
    assert attributes["source_list"] == ["Demo Show"]
    assert attributes["volume_level"] == pytest.approx(0.7)
    assert attributes["is_volume_muted"] is False
    assert attributes["transport_state"] == "playing"
    assert attributes["clip_index"] == 3
    features = MediaPlayerEntityFeature(attributes["supported_features"])
    assert MediaPlayerEntityFeature.PLAY in features
    assert MediaPlayerEntityFeature.SELECT_SOURCE in features
    assert MediaPlayerEntityFeature.VOLUME_SET in features
    assert MediaPlayerEntityFeature.VOLUME_MUTE in features


@pytest.mark.parametrize(
    ("transport_state", "expected"),
    [
        ("PAUSED", "paused"),
        ("SELECTING", "buffering"),
        ("STOPPED", "idle"),
        ("UNSELECTED", "idle"),
        ("UNAVAILABLE", "standby"),
        ("SOMETHING_NEW", "on"),
    ],
)
async def test_states(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    transport_state: str,
    expected: str,
) -> None:
    """Every transport state maps to a media player state."""
    mock_client.get_playback_state.return_value = PlaybackState(transport_state=transport_state)
    player = await _player(hass, mock_config_entry)
    current = hass.states.get(player)
    assert current.state == expected
    assert current.attributes.get("media_title") is None


async def test_no_playback_state(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A server that answers but gives no playback state is simply on."""
    mock_client.get_playback_state.side_effect = DSSFaultError("NotReady", None)
    mock_client.get_volume.side_effect = DSSFaultError("NotConnected", None)
    mock_client.get_mute.side_effect = DSSFaultError("NotConnected", None)
    player = await _player(hass, mock_config_entry)
    current = hass.states.get(player)
    assert current.state == "on"
    features = MediaPlayerEntityFeature(current.attributes["supported_features"])
    assert MediaPlayerEntityFeature.PLAY in features
    assert MediaPlayerEntityFeature.VOLUME_SET not in features
    assert MediaPlayerEntityFeature.VOLUME_MUTE not in features


async def test_unknown_show_shows_id(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A show that is not in the show list is shown by its ID."""
    mock_client.get_playback_state.return_value = PlaybackState(
        transport_state="STOPPED", content_id=SHOW3_ID, content_type="SHOW"
    )
    player = await _player(hass, mock_config_entry)
    attributes = hass.states.get(player).attributes
    assert attributes["media_playlist"] == SHOW3_ID
    assert attributes.get("source") is None


@pytest.mark.parametrize(
    ("service", "method"),
    [
        (SERVICE_MEDIA_PLAY, "play"),
        (SERVICE_MEDIA_PAUSE, "pause"),
        (SERVICE_MEDIA_STOP, "stop"),
        (SERVICE_MEDIA_NEXT_TRACK, "next"),
        (SERVICE_MEDIA_PREVIOUS_TRACK, "previous"),
    ],
)
async def test_transport_commands(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    method: str,
) -> None:
    """Transport commands reach the server and refresh the state."""
    player = await _player(hass, mock_config_entry)
    calls = mock_client.get_playback_state.await_count
    await _call(hass, service, player)
    await hass.async_block_till_done()
    getattr(mock_client, method).assert_awaited_once_with()
    assert mock_client.get_playback_state.await_count > calls


async def test_seek(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A position in the clip is turned into a position in the show."""
    player = await _player(hass, mock_config_entry)
    await _call(hass, SERVICE_MEDIA_SEEK, player, **{ATTR_MEDIA_SEEK_POSITION: 30})
    # The clip started at 605.5 - 65.5 = 540 seconds into the show.
    mock_client.go_to_position.assert_awaited_once_with(570.0)


async def test_seek_without_positions(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Without show and clip positions the requested position is used as it is."""
    mock_client.get_playback_state.return_value = PlaybackState(
        transport_state="PAUSED", content_id=SHOW_ID, content_type="SHOW"
    )
    player = await _player(hass, mock_config_entry)
    await _call(hass, SERVICE_MEDIA_SEEK, player, **{ATTR_MEDIA_SEEK_POSITION: 12})
    mock_client.go_to_position.assert_awaited_once_with(12.0)


async def test_select_source(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Selecting a source selects that show on the server."""
    player = await _player(hass, mock_config_entry)
    await _call(hass, SERVICE_SELECT_SOURCE, player, **{ATTR_INPUT_SOURCE: "Demo Show"})
    mock_client.select_content.assert_awaited_once_with(SHOW_ID, "SHOW")

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_SELECT_SOURCE, player, **{ATTR_INPUT_SOURCE: "Trailer Reel"})
    assert err.value.translation_key == "unknown_source"


async def test_volume(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Volume and mute map to the cinema processor fader (0-10) and mute."""
    player = await _player(hass, mock_config_entry)
    await _call(hass, SERVICE_VOLUME_SET, player, **{ATTR_MEDIA_VOLUME_LEVEL: 0.55})
    mock_client.set_volume.assert_awaited_once_with(5.5)
    await _call(hass, SERVICE_VOLUME_MUTE, player, **{ATTR_MEDIA_VOLUME_MUTED: True})
    mock_client.set_mute.assert_awaited_once_with(True)


async def test_command_refused(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A fault from the server is reported as a failed command."""
    mock_client.play.side_effect = DSSFaultError("NotReady", "Show is not ready")
    player = await _player(hass, mock_config_entry)
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, SERVICE_MEDIA_PLAY, player)
    assert err.value.translation_key == "command_failed"
    assert not isinstance(err.value, ServiceValidationError)


async def test_invalid_value(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A value the client refuses is reported as invalid input."""
    mock_client.set_volume.side_effect = ValueError("Invalid volume: 11")
    player = await _player(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_VOLUME_SET, player, **{ATTR_MEDIA_VOLUME_LEVEL: 1.0})
    assert err.value.translation_key == "invalid_value"


async def test_read_only(
    hass: HomeAssistant, mock_client: MagicMock, read_only_config_entry: MockConfigEntry
) -> None:
    """With control off the player offers no controls and refuses commands."""
    player = await _player(hass, read_only_config_entry)
    assert hass.states.get(player).attributes.get("supported_features", 0) == 0
    with pytest.raises(HomeAssistantError):
        await _call(hass, SERVICE_MEDIA_PLAY, player)
    mock_client.play.assert_not_called()


async def test_offline_offers_no_controls(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """An unreachable server is off and offers no controls."""
    player = await _player(hass, mock_config_entry)
    mock_client.get_playback_state.side_effect = DSSConnectionError("timeout")
    await poll(hass)
    current = hass.states.get(player)
    assert current.state == "off"
    assert current.attributes.get("supported_features", 0) == 0


def test_source_map_duplicates() -> None:
    """Shows with the same name get the start of their ID added."""
    shows = {
        SHOW_ID: ShowInfo(SHOW_ID, "Matinee", None, True, False, None),
        SHOW2_ID: ShowInfo(SHOW2_ID, "Matinee", None, True, False, None),
        SHOW3_ID: ShowInfo(SHOW3_ID, "evening", None, True, False, None),
    }
    assert source_map(shows) == {
        "evening": SHOW3_ID,
        "Matinee (11111111)": SHOW_ID,
        "Matinee (66666666)": SHOW2_ID,
    }
