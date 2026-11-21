"""The integration only talks to the configured server.

The runtime half of the "local only" badge: the real client runs against an
in-memory HTTP session, and every request made during setup, polling and a
command must go to the server's SMI web services. Real network access is
blocked in the tests anyway, so anything else would fail. The static half is
scripts/check_local_only.py, which is tested here as well.
"""

from __future__ import annotations

from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CLIP_NAME, HOST, PORT
from .test_init import entity_id

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SERVICES = (
    "PlaybackControlService",
    "ShowManagementService",
    "ContentManagementService",
    "SystemManagementService",
)
PLAY_RESPONSE = (
    b"<env:Envelope xmlns:env='http://schemas.xmlsoap.org/soap/envelope/'><env:Body>"
    b"<r:playResponse xmlns:r='http://www.dolby.com/dcinema/ws/smi/v1_0'/>"
    b"</env:Body></env:Envelope>"
)


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_local_only", ROOT / "scripts" / "check_local_only.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _answers() -> dict[str, bytes]:
    """Answers per operation; anything else gets a fault, as on a server without it."""
    return {
        "getPlaybackState2": (FIXTURES / "get_playback_state2.xml").read_bytes(),
        "getInputSelect": (FIXTURES / "get_input_select.xml").read_bytes(),
        "getShowInfos": (FIXTURES / "get_show_infos.xml").read_bytes(),
        "getClipInfos": (FIXTURES / "get_clip_infos.xml").read_bytes(),
        "getSystemTime": (FIXTURES / "get_system_time.xml").read_bytes(),
        "getDeviceComponentInfos": (FIXTURES / "get_device_component_infos.xml").read_bytes(),
        "play": PLAY_RESPONSE,
    }


async def test_all_traffic_goes_to_the_server(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Setup, polling and a command only reach the server, and parse end to end."""
    urls: list[URL] = []
    operations: list[str] = []
    answers = _answers()
    fault = (FIXTURES / "fault_not_connected.xml").read_bytes()
    match_request = aioclient_mock.match_request

    async def _record(method: str, url: Any, **kwargs: Any) -> Any:
        urls.append(URL(str(url)))
        return await match_request(method, url, **kwargs)

    async def _answer(method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        body = data if isinstance(data, bytes) else str(data).encode()
        for operation, answer in answers.items():
            if f"<m:{operation}Request ".encode() in body:
                operations.append(operation)
                return AiohttpClientMockResponse(method, url, response=answer)
        return AiohttpClientMockResponse(method, url, status=500, response=fault)

    for service in SERVICES:
        aioclient_mock.post(
            f"http://{HOST}:{PORT}/dcinema/ws/smi/v1/{service}", side_effect=_answer
        )

    mock_config_entry.add_to_hass(hass)
    with patch.object(aioclient_mock, "match_request", _record):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        player = entity_id(hass, "media_player", "media_player")
        state = hass.states.get(player)
        assert state is not None
        assert state.state == "playing"
        assert state.attributes["media_title"] == CLIP_NAME
        assert state.attributes["media_playlist"] == "Demo Show"

        for seconds in (6, 12):
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
            await hass.async_block_till_done()
        await hass.services.async_call(
            "media_player", "media_play", {"entity_id": player}, blocking=True
        )
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert urls, "the test made no requests"
    assert {(url.scheme, url.host, url.port) for url in urls} == {("http", HOST, PORT)}
    assert {url.path for url in urls} <= {f"/dcinema/ws/smi/v1/{s}" for s in SERVICES}
    assert "play" in operations


def test_static_check_passes() -> None:
    """The integration passes scripts/check_local_only.py."""
    checker = _load_checker()
    assert checker.main(["check_local_only.py"]) == 0


def test_static_check_catches_leaks(tmp_path: Path) -> None:
    """The check fails on an integration that could send data elsewhere."""
    checker = _load_checker()
    leaky = tmp_path / "leaky"
    shutil.copytree(ROOT / "custom_components" / "dolby_dss220", leaky)
    manifest = json.loads((leaky / "manifest.json").read_text())
    manifest.update(iot_class="cloud_polling", requirements=["phonehome==1.0"])
    (leaky / "manifest.json").write_text(json.dumps(manifest))
    (leaky / "telemetry.py").write_text(
        "import asyncio\n"
        "import requests\n"
        "from homeassistant.helpers.aiohttp_client import async_get_clientsession\n\n\n"
        "async def leak(hass):\n"
        "    session = async_get_clientsession(hass)\n"
        "    await session.post('https://telemetry.example.com/collect')\n"
        "    await asyncio.start_server(None, '0.0.0.0', 8080)\n"
        "    await asyncio.open_connection('8.8.8.8', 53)\n"
        "    return 'analytics.vendor.io'\n"
    )

    problems = checker.check_manifest(leaky)
    problems += checker.check_source(leaky / "telemetry.py", "leaky/telemetry.py")
    text = "\n".join(problems)
    for expected in (
        "iot_class",
        "phonehome",
        "imports requests",
        "async_get_clientsession() outside",
        "session.post() outside",
        "start_server() listens",
        "open_connection() outside",
        "https://telemetry.example.com",
        "8.8.8.8",
        "analytics.vendor.io",
    ):
        assert expected in text, expected
    assert checker.main(["check_local_only.py", str(leaky)]) == 1
