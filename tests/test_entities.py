"""Tests for the Dolby DSS220 select, switch and sensor entities."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_dss220.sensor import remaining, timecode
from custom_components.dolby_dss220.soap import DSSFaultError, PlaybackState
from homeassistant.components.select.const import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import CLIP_ID, CLIP_NAME, SHOW_ID
from .test_init import entity_id, setup_entry, state


async def test_input_select(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The input select shows the media block input and switches it."""
    await setup_entry(hass, mock_config_entry)
    select = entity_id(hass, "select", "input")
    current = hass.states.get(select)
    assert current.state == "server"
    assert current.attributes["options"] == ["server", "hdmi_1", "hdmi_2"]

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select, ATTR_OPTION: "hdmi_1"},
        blocking=True,
    )
    mock_client.set_input_select.assert_awaited_once_with("HDMI_1")


async def test_input_select_extra_option(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """An input outside the default list (HD-SDI) is added to the options."""
    mock_client.get_input_select.return_value = "HD_SDI"
    await setup_entry(hass, mock_config_entry)
    current = hass.states.get(entity_id(hass, "select", "input"))
    assert current.state == "hd_sdi"
    assert current.attributes["options"] == ["server", "hdmi_1", "hdmi_2", "hd_sdi"]


async def test_input_select_unknown(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A server that cannot report the input makes the select unavailable."""
    mock_client.get_input_select.side_effect = DSSFaultError("OperationNotImplemented", None)
    await setup_entry(hass, mock_config_entry)
    assert state(hass, "select", "input") == STATE_UNAVAILABLE


async def test_schedule_mode_select(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The schedule mode can be read and changed."""
    await setup_entry(hass, mock_config_entry)
    select = entity_id(hass, "select", "schedule_mode")
    assert hass.states.get(select).state == "manual"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select, ATTR_OPTION: "full_automatic"},
        blocking=True,
    )
    mock_client.set_schedule_mode.assert_awaited_once_with("FULL_AUTOMATIC")


@pytest.mark.parametrize(
    ("key", "method", "initial"),
    [("douser", "set_douser", STATE_OFF), ("lamp", "set_lamp", STATE_ON)],
)
async def test_switches(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    key: str,
    method: str,
    initial: str,
) -> None:
    """Douser and lamp switches show the state and send commands."""
    await setup_entry(hass, mock_config_entry)
    switch = entity_id(hass, "switch", key)
    assert hass.states.get(switch).state == initial

    await hass.services.async_call(
        Platform.SWITCH, SERVICE_TURN_ON, {ATTR_ENTITY_ID: switch}, blocking=True
    )
    await hass.services.async_call(
        Platform.SWITCH, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch}, blocking=True
    )
    assert [call.args for call in getattr(mock_client, method).await_args_list] == [
        (True,),
        (False,),
    ]


async def test_switch_read_only(
    hass: HomeAssistant, mock_client: MagicMock, read_only_config_entry: MockConfigEntry
) -> None:
    """With control off a switch refuses to act."""
    await setup_entry(hass, read_only_config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            Platform.SWITCH,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id(hass, "switch", "douser")},
            blocking=True,
        )
    assert err.value.translation_key == "control_disabled"
    mock_client.set_douser.assert_not_called()


async def test_select_read_only(
    hass: HomeAssistant, mock_client: MagicMock, read_only_config_entry: MockConfigEntry
) -> None:
    """With control off the input cannot be changed."""
    await setup_entry(hass, read_only_config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity_id(hass, "select", "input"), ATTR_OPTION: "hdmi_2"},
            blocking=True,
        )
    mock_client.set_input_select.assert_not_called()


async def test_switch_refused(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A lamp command the projector refuses is reported as failed."""
    mock_client.set_lamp.side_effect = DSSFaultError("NotReady", "Lamp is cooling down")
    await setup_entry(hass, mock_config_entry)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            Platform.SWITCH,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id(hass, "switch", "lamp")},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"


async def test_sensors(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The sensors show what is playing and where it is."""
    await setup_entry(hass, mock_config_entry)

    assert state(hass, "sensor", "transport_state") == "playing"
    assert state(hass, "sensor", "current_show") == "Demo Show"
    assert state(hass, "sensor", "current_clip") == CLIP_NAME
    assert state(hass, "sensor", "clip_timecode") == "00:01:05 / 00:02:33"
    assert float(state(hass, "sensor", "clip_remaining")) == pytest.approx(87.75, abs=0.1)
    assert state(hass, "sensor", "show_timecode") == "00:10:05 / 00:18:36"
    assert float(state(hass, "sensor", "show_remaining")) == pytest.approx(510.9, abs=0.1)
    assert state(hass, "sensor", "alarms") == "1"
    assert float(state(hass, "sensor", "clock_offset")) == pytest.approx(14400, abs=5)
    assert float(state(hass, "sensor", "response_time")) >= 0
    assert state(hass, "sensor", "last_seen") not in (STATE_UNKNOWN, STATE_UNAVAILABLE)

    show = hass.states.get(entity_id(hass, "sensor", "current_show"))
    assert show.attributes["show_id"] == SHOW_ID
    clip = hass.states.get(entity_id(hass, "sensor", "current_clip"))
    assert clip.attributes["clip_id"] == CLIP_ID
    assert clip.attributes["clip_index"] == 3
    alarms = hass.states.get(entity_id(hass, "sensor", "alarms"))
    assert alarms.attributes["alarms"] == ["DSS220: Fan 5 not detected (warning)"]
    clock = hass.states.get(entity_id(hass, "sensor", "clock_offset"))
    assert clock.attributes["time_zone"] == "WET"


async def test_sensors_without_playback(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Without a playback state the playback sensors are unknown."""
    mock_client.get_playback_state.side_effect = DSSFaultError("NotReady", None)
    mock_client.get_system_time.side_effect = DSSFaultError("NotReady", None)
    await setup_entry(hass, mock_config_entry)

    for key in (
        "transport_state",
        "current_show",
        "current_clip",
        "clip_timecode",
        "clip_remaining",
        "show_timecode",
        "show_remaining",
        "clock_offset",
    ):
        assert state(hass, "sensor", key) == STATE_UNKNOWN, key


async def test_unlisted_transport_state(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A transport state outside the published list is unknown, not an error."""
    mock_client.get_playback_state.return_value = PlaybackState(transport_state="WARMING_UP")
    await setup_entry(hass, mock_config_entry)
    assert state(hass, "sensor", "transport_state") == STATE_UNKNOWN


def test_formatting() -> None:
    """Timecodes and remaining time are formatted and clamped."""
    assert timecode(3725.9, 7200) == "01:02:05 / 02:00:00"
    assert timecode(None, 10) is None
    assert timecode(-3, 10) == "00:00:00 / 00:00:10"
    assert remaining(10, 25.04) == 15.0
    assert remaining(30, 25) == 0.0
    assert remaining(10, None) is None
