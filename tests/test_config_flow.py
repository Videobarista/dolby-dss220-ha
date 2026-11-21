"""Tests for the Dolby DSS220 config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_dss220.const import (
    CONF_ALLOW_CONTROL,
    CONF_MODEL,
    CONF_SW_VERSION,
    DOMAIN,
)
from custom_components.dolby_dss220.soap import (
    DeviceComponent,
    DSSConnectionError,
    DSSFaultError,
    DSSProtocolError,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ENTRY_DATA
from .const import HOST, MEDIA_BLOCK, OTHER_SERVER_ID, PORT, SERVER, SW_VERSION, UNIQUE_ID

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

USER_INPUT: dict[str, Any] = {CONF_HOST: HOST, CONF_PORT: PORT, CONF_ALLOW_CONTROL: False}
NEW_HOST = "192.0.2.20"


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    """Open the user step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    """Open the reconfigure step of an existing entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


async def test_user_flow(hass: HomeAssistant, mock_flow_client: MagicMock) -> None:
    """A server that reports its components gets an entry keyed by its UUID."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: f" {HOST} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dolby DSS220"
    assert result["data"] == ENTRY_DATA
    assert result["options"] == {CONF_ALLOW_CONTROL: False}
    assert result["result"].unique_id == UNIQUE_ID
    mock_flow_client.get_system_time.assert_not_called()


async def test_user_flow_allow_control(hass: HomeAssistant, mock_flow_client: MagicMock) -> None:
    """Control can be switched on while adding the server."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_ALLOW_CONTROL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_ALLOW_CONTROL: True}


@pytest.mark.parametrize(
    "components",
    [
        pytest.param(DSSFaultError("OperationNotImplemented", None), id="fault"),
        pytest.param([MEDIA_BLOCK], id="no-server-component"),
    ],
)
async def test_user_flow_without_identity(
    hass: HomeAssistant, mock_flow_client: MagicMock, components: Any
) -> None:
    """Without a server component the system time proves it is a DSS; no unique ID."""
    if isinstance(components, Exception):
        mock_flow_client.get_device_components.side_effect = components
    else:
        mock_flow_client.get_device_components.return_value = components
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id is None
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: PORT,
        CONF_MODEL: None,
        CONF_SW_VERSION: None,
    }
    mock_flow_client.get_system_time.assert_awaited_once()


async def test_user_flow_player_component(hass: HomeAssistant, mock_flow_client: MagicMock) -> None:
    """A system that only reports a player is keyed by the player."""
    player = DeviceComponent(
        component_id=OTHER_SERVER_ID,
        component_type="PLAYER",
        model="DSS200",
        location="1",
        version="4.9.5.2",
        properties={},
        alarms=(),
    )
    mock_flow_client.get_device_components.return_value = [MEDIA_BLOCK, player]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "99999999-8888-7777-6666-555555555555"
    assert result["data"][CONF_MODEL] == "DSS200"


@pytest.mark.parametrize(
    ("method", "side_effect", "error"),
    [
        ("get_device_components", DSSConnectionError("timeout"), "cannot_connect"),
        ("get_device_components", RuntimeError("boom"), "unknown"),
        ("get_system_time", DSSProtocolError("not a SOAP envelope"), "invalid_response"),
        ("get_system_time", DSSConnectionError("connection reset"), "cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    method: str,
    side_effect: Exception,
    error: str,
) -> None:
    """Errors are shown on the form, and the flow recovers once they are gone."""
    if method == "get_system_time":
        # The system time is only asked for when the components do not identify the server.
        mock_flow_client.get_device_components.return_value = []
    getattr(mock_flow_client, method).side_effect = side_effect

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    getattr(mock_flow_client, method).side_effect = None
    mock_flow_client.get_device_components.return_value = [SERVER]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("host", ["http://192.0.2.10/", "192.0.2.10/path", "bad host", "-a-"])
async def test_user_flow_invalid_host(
    hass: HomeAssistant, mock_flow_client: MagicMock, host: str
) -> None:
    """Something that is not a host name or IP address is refused before connecting."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: host}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    mock_flow_client.get_device_components.assert_not_called()


async def test_user_flow_ipv6(hass: HomeAssistant, mock_flow_client: MagicMock) -> None:
    """An IPv6 address is accepted and stored without brackets."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "[2001:DB8::10]"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "2001:db8::10"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The same server is not added twice; a changed address is taken over."""
    mock_config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: NEW_HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == NEW_HOST


async def test_user_flow_already_configured_by_address(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """Without a unique ID the address decides whether the server is known."""
    MockConfigEntry(domain=DOMAIN, unique_id=None, data=dict(ENTRY_DATA)).add_to_hass(hass)
    mock_flow_client.get_device_components.return_value = []
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The address of a server can be changed."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_reconfigure(hass, mock_config_entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: 8081}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        CONF_HOST: NEW_HOST,
        CONF_PORT: 8081,
        CONF_MODEL: "DSS220",
        CONF_SW_VERSION: SW_VERSION,
    }
    assert mock_config_entry.options == {CONF_ALLOW_CONTROL: True}


async def test_reconfigure_wrong_device(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """An address that belongs to another server is refused."""
    mock_config_entry.add_to_hass(hass)
    other = DeviceComponent(
        component_id=OTHER_SERVER_ID,
        component_type="SERVER",
        model="DSS220",
        location="2",
        version=SW_VERSION,
        properties={},
        alarms=(),
    )
    mock_flow_client.get_device_components.return_value = [other]
    result = await _start_reconfigure(hass, mock_config_entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert mock_config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_error(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A connection error keeps the form open with the error."""
    mock_config_entry.add_to_hass(hass)
    mock_flow_client.get_device_components.side_effect = DSSConnectionError("timeout")
    result = await _start_reconfigure(hass, mock_config_entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: PORT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_flow_client.get_device_components.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_without_unique_id(
    hass: HomeAssistant, mock_flow_client: MagicMock
) -> None:
    """An entry without a unique ID is updated without the identity check."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=None, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == NEW_HOST
    assert entry.unique_id is None


async def test_options_flow(hass: HomeAssistant, read_only_config_entry: MockConfigEntry) -> None:
    """Control can be switched on in the options."""
    read_only_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(read_only_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_CONTROL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert read_only_config_entry.options == {CONF_ALLOW_CONTROL: True}
