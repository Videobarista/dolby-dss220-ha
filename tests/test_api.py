"""Tests for the SOAP client, on an HTTP session that exists only in memory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from custom_components.dolby_dss220.api import DSSClient
from custom_components.dolby_dss220.soap import (
    MAX_RESPONSE_BYTES,
    DSSConnectionError,
    DSSFaultError,
    DSSProtocolError,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://192.0.2.10:8080/dcinema/ws/smi/v1"


def _fixture(name: str) -> bytes:
    """Return a stored server response."""
    return (FIXTURES / name).read_bytes()


def _response(operation: str, body: str = "", version: str = "v1_0") -> bytes:
    """Build a response element for an operation, wrapped in an envelope."""
    return (
        "<env:Envelope xmlns:env='http://schemas.xmlsoap.org/soap/envelope/'><env:Body>"
        f"<r:{operation}Response xmlns:r='http://www.dolby.com/dcinema/ws/smi/{version}'>"
        f"{body}</r:{operation}Response></env:Body></env:Envelope>"
    ).encode()


class _Content:
    """The body of a response, read in chunks like aiohttp's StreamReader."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        # Small chunks, so a body always arrives in several parts.
        step = min(size, 100)
        for start in range(0, len(self._body), step):
            yield self._body[start : start + step]


class _Response:
    """A response context manager; raises on enter when the request fails."""

    def __init__(self, status: int, body: bytes, error: BaseException | None) -> None:
        self.status = status
        self.content = _Content(body)
        self._error = error

    async def __aenter__(self) -> _Response:
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class FakeSession:
    """Records POST requests and answers them from a queue."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.replies: list[tuple[int, bytes] | BaseException] = []

    def reply(self, body: bytes, status: int = 200) -> None:
        self.replies.append((status, body))

    def fail(self, error: BaseException) -> None:
        self.replies.append(error)

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append((url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            return _Response(0, b"", reply)
        return _Response(reply[0], reply[1], None)


@pytest.fixture
def session() -> FakeSession:
    """Return the in-memory session."""
    return FakeSession()


@pytest.fixture
def client(session: FakeSession) -> DSSClient:
    """Return a client on the in-memory session."""
    return DSSClient(session, "192.0.2.10", 8080, timeout=5)  # type: ignore[arg-type]


async def test_request_format(client: DSSClient, session: FakeSession) -> None:
    """Requests go to the service URL with the SOAP headers and no redirects."""
    session.reply(_fixture("get_input_select.xml"))
    assert await client.get_input_select() == "SERVER"

    url, kwargs = session.requests[0]
    assert url == f"{BASE}/PlaybackControlService"
    assert kwargs["headers"] == {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"http://www.dolby.com/dcinema/ws/smi/v1/getInputSelect"',
    }
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 5
    assert b"<m:getInputSelectRequest" in kwargs["data"]
    assert client.base_url == BASE


async def test_playback_and_lists(client: DSSClient, session: FakeSession) -> None:
    """Playback state, shows, clips, time and components are parsed."""
    session.reply(_fixture("get_playback_state2.xml"))
    session.reply(_fixture("get_show_infos.xml"))
    session.reply(_fixture("get_clip_infos.xml"))
    session.reply(_fixture("get_system_time.xml"))
    session.reply(_fixture("get_device_component_infos.xml"))

    assert (await client.get_playback_state()).transport_state == "PLAYING"
    assert len(await client.get_show_infos()) == 2
    clip = await client.get_clip_info("urn:uuid:AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")
    assert clip is not None
    assert clip.clip_type == "TRAILER"
    assert (await client.get_system_time()).time_zone == "WET"
    assert len(await client.get_device_components()) == 2

    services = [url.rsplit("/", 1)[1] for url, _ in session.requests]
    assert services == [
        "PlaybackControlService",
        "ShowManagementService",
        "ContentManagementService",
        "SystemManagementService",
        "SystemManagementService",
    ]
    assert (
        b"<clipId>urn:uuid:AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE</clipId>"
        in session.requests[2][1]["data"]
    )


async def test_clip_info_fallbacks(client: DSSClient, session: FakeSession) -> None:
    """Another clip in the answer is used when the ID differs; none gives None."""
    other = "urn:uuid:12345678-1234-1234-1234-123456789abc"
    session.reply(
        _response(
            "getClipInfos",
            "<clipInfo><clipId>urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            "</clipId><name>Other</name></clipInfo>",
        )
    )
    session.reply(_response("getClipInfos"))
    clip = await client.get_clip_info(other)
    assert clip is not None
    assert clip.name == "Other"
    assert await client.get_clip_info(other) is None
    with pytest.raises(ValueError):
        await client.get_clip_info("not-a-uuid")


@pytest.mark.parametrize(
    ("method", "args", "operation", "element"),
    [
        ("play", (), "play", b"<m:playRequest"),
        ("pause", (), "pause", b"<m:pauseRequest"),
        ("stop", (), "stop", b"<m:stopRequest"),
        ("next", (), "next", b"<m:nextRequest"),
        ("previous", (), "previous", b"<m:previousRequest"),
        (
            "select_content",
            ("urn:uuid:11111111-2222-3333-4444-555555555555",),
            "selectContent",
            b"<playableContentType>SHOW</playableContentType>",
        ),
        ("go_to_position", (90.5,), "goToPosition", b"<position>PT0H1M30.500S</position>"),
        ("set_schedule_mode", ("MANUAL",), "setScheduleMode", b"<scheduleMode>MANUAL"),
        ("set_input_select", ("HDMI_2",), "inputSelect", b"<inputSelectMode>HDMI_2"),
        ("set_volume", (7.25,), "setVolume", b"<volume>7.2</volume>"),
        ("set_mute", (True,), "setMute", b"<muted>true</muted>"),
        ("set_douser", (False,), "setDouser", b"<doused>false</doused>"),
        ("set_lamp", (True,), "setLamp", b"<struck>true</struck>"),
    ],
)
async def test_commands(
    client: DSSClient,
    session: FakeSession,
    method: str,
    args: tuple[Any, ...],
    operation: str,
    element: bytes,
) -> None:
    """Commands send the right operation and values."""
    session.reply(_response(operation))
    await getattr(client, method)(*args)
    _, kwargs = session.requests[0]
    assert kwargs["headers"]["SOAPAction"].endswith(f'/{operation}"')
    assert element in kwargs["data"]


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("select_content", ("urn:uuid:11111111-2222-3333-4444-555555555555", "PLAYLIST")),
        ("select_content", ("<script>",)),
        ("go_to_position", (-1,)),
        ("set_schedule_mode", ("AUTO",)),
        ("set_input_select", ("HDMI_3",)),
        ("set_volume", (10.5,)),
        ("set_volume", (-0.1,)),
    ],
)
async def test_invalid_command_values(
    client: DSSClient, session: FakeSession, method: str, args: tuple[Any, ...]
) -> None:
    """Invalid values are refused before anything is sent."""
    with pytest.raises(ValueError):
        await getattr(client, method)(*args)
    assert session.requests == []


@pytest.mark.parametrize(
    ("method", "operation", "element", "value", "expected"),
    [
        ("get_schedule_mode", "getScheduleMode", "scheduleMode", "SELECT_AUTOMATIC", None),
        ("get_volume", "getVolume", "volume", "6.5", 6.5),
        ("get_mute", "getMute", "muted", "true", True),
        ("get_douser", "getDouser", "doused", "false", False),
        ("get_lamp", "getLamp", "struck", "true", True),
    ],
)
async def test_getters(
    client: DSSClient,
    session: FakeSession,
    method: str,
    operation: str,
    element: str,
    value: str,
    expected: Any,
) -> None:
    """Simple getters return typed values."""
    session.reply(_response(operation, f"<{element}>{value}</{element}>"))
    result = await getattr(client, method)()
    assert result == (value if expected is None else expected)


async def test_volume_missing_or_invalid(client: DSSClient, session: FakeSession) -> None:
    """A missing volume is unknown; text that is not a number is a protocol error."""
    session.reply(_response("getVolume"))
    session.reply(_response("getVolume", "<volume>loud</volume>"))
    assert await client.get_volume() is None
    with pytest.raises(DSSProtocolError):
        await client.get_volume()


@pytest.mark.parametrize(
    "error",
    [TimeoutError(), aiohttp.ClientError("connection refused"), OSError("no route to host")],
)
async def test_connection_errors(
    client: DSSClient, session: FakeSession, error: BaseException
) -> None:
    """Network errors and timeouts become connection errors."""
    session.fail(error)
    with pytest.raises(DSSConnectionError):
        await client.get_playback_state()


async def test_fault_with_http_500(client: DSSClient, session: FakeSession) -> None:
    """SOAP faults arrive with HTTP 500 and are raised as faults."""
    session.reply(_fixture("fault_not_connected.xml"), status=500)
    with pytest.raises(DSSFaultError, match="NotConnected"):
        await client.get_douser()


@pytest.mark.parametrize("status", [301, 404, 503])
async def test_unexpected_status(client: DSSClient, session: FakeSession, status: int) -> None:
    """Other HTTP status codes (a redirect, a missing service) are protocol errors."""
    session.reply(b"<html>Not Found</html>", status=status)
    with pytest.raises(DSSProtocolError, match=str(status)):
        await client.get_input_select()


async def test_oversized_response(client: DSSClient, session: FakeSession) -> None:
    """At most one byte more than the limit is read, and then refused."""
    session.reply(b"<" + b"x" * (MAX_RESPONSE_BYTES + 100))
    with pytest.raises(DSSProtocolError, match="too large"):
        await client.get_input_select()
