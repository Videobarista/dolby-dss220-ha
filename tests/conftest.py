"""Shared fixtures for the Dolby DSS220 tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dolby_dss220.const import (
    CONF_ALLOW_CONTROL,
    CONF_MODEL,
    CONF_SW_VERSION,
    DOMAIN,
)
from custom_components.dolby_dss220.soap import SystemTime, build_base_url
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.util import dt as dt_util

from .const import CLIP, HOST, MEDIA_BLOCK, PLAYBACK, PORT, SERVER, SHOWS, SW_VERSION, UNIQUE_ID

ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_PORT: PORT,
    CONF_MODEL: "DSS220",
    CONF_SW_VERSION: SW_VERSION,
}


def _system_time() -> SystemTime:
    """The server clock runs four hours ahead, in the WET time zone."""
    return SystemTime(time=dt_util.utcnow() + timedelta(hours=4), time_zone="WET")


def make_client() -> MagicMock:
    """Build a stand-in for DSSClient that answers like a playing DSS220."""
    client = MagicMock()
    client.base_url = build_base_url(HOST, PORT)
    client.get_playback_state = AsyncMock(return_value=PLAYBACK)
    client.get_input_select = AsyncMock(return_value="SERVER")
    client.get_schedule_mode = AsyncMock(return_value="MANUAL")
    client.get_volume = AsyncMock(return_value=7.0)
    client.get_mute = AsyncMock(return_value=False)
    client.get_douser = AsyncMock(return_value=False)
    client.get_lamp = AsyncMock(return_value=True)
    client.get_show_infos = AsyncMock(return_value=list(SHOWS))
    client.get_clip_info = AsyncMock(return_value=CLIP)
    client.get_system_time = AsyncMock(side_effect=_system_time)
    client.get_device_components = AsyncMock(return_value=[SERVER, MEDIA_BLOCK])
    for command in (
        "play",
        "pause",
        "stop",
        "next",
        "previous",
        "select_content",
        "go_to_position",
        "set_schedule_mode",
        "set_input_select",
        "set_volume",
        "set_mute",
        "set_douser",
        "set_lamp",
    ):
        setattr(client, command, AsyncMock(return_value=None))
    return client


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured server with control allowed."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Dolby DSS220",
        unique_id=UNIQUE_ID,
        data=dict(ENTRY_DATA),
        options={CONF_ALLOW_CONTROL: True},
    )


@pytest.fixture
def read_only_config_entry() -> MockConfigEntry:
    """A configured server with control switched off (the default)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Dolby DSS220",
        unique_id=UNIQUE_ID,
        data=dict(ENTRY_DATA),
        options={CONF_ALLOW_CONTROL: False},
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry itself while testing the config flow."""
    with patch("custom_components.dolby_dss220.async_setup_entry", return_value=True) as setup:
        yield setup


@pytest.fixture
def mock_flow_client() -> Generator[MagicMock]:
    """The client the config flow uses to probe a server."""
    client = make_client()
    with patch("custom_components.dolby_dss220.config_flow.DSSClient", return_value=client):
        yield client


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """The client a loaded config entry polls."""
    client = make_client()
    with patch("custom_components.dolby_dss220.DSSClient", return_value=client):
        yield client
