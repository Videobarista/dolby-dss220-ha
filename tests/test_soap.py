"""Tests for the SOAP layer: envelopes, parsing and hostile responses."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.dolby_dss220 import soap

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    """Return a stored server response."""
    return (FIXTURES / name).read_bytes()


def _envelope(body: str) -> bytes:
    """Wrap a body in a SOAP envelope the way JBossWS does."""
    return (
        "<env:Envelope xmlns:env='http://schemas.xmlsoap.org/soap/envelope/'>"
        f"<env:Header></env:Header><env:Body>{body}</env:Body></env:Envelope>"
    ).encode()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def test_operation_namespace_and_action() -> None:
    """Each operation lives in the namespace of the API version that added it."""
    assert soap.OP_GET_PLAYBACK_STATE.namespace == "http://www.dolby.com/dcinema/ws/smi/v1_3"
    assert soap.OP_GET_INPUT_SELECT.namespace == "http://www.dolby.com/dcinema/ws/smi/v1_4"
    assert soap.OP_SET_VOLUME.namespace == "http://www.dolby.com/dcinema/ws/smi/v1_5"
    assert soap.OP_PLAY.soap_action == '"http://www.dolby.com/dcinema/ws/smi/v1/play"'


def test_build_envelope() -> None:
    """The request element is qualified, its children are not, values are escaped."""
    body = soap.build_envelope(
        soap.OP_SELECT_CONTENT, (("contentId", "a<b&c"), ("playableContentType", "SHOW"))
    ).decode()
    assert body.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert (
        '<m:selectContentRequest xmlns:m="http://www.dolby.com/dcinema/ws/smi/v1_0">'
        "<contentId>a&lt;b&amp;c</contentId>"
        "<playableContentType>SHOW</playableContentType>"
        "</m:selectContentRequest>"
    ) in body


def test_build_envelope_without_parameters() -> None:
    """An operation without parameters sends an empty request element."""
    body = soap.build_envelope(soap.OP_GET_INPUT_SELECT).decode()
    assert (
        '<m:getInputSelectRequest xmlns:m="http://www.dolby.com/dcinema/ws/smi/v1_4">'
        "</m:getInputSelectRequest>"
    ) in body


@pytest.mark.parametrize("name", ["", "1abc", "a b", "a>b", "x:y"])
def test_build_envelope_rejects_bad_names(name: str) -> None:
    """Parameter names are never taken from outside input, but are checked anyway."""
    with pytest.raises(ValueError):
        soap.build_envelope(soap.OP_PLAY, ((name, "value"),))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.1.129", "192.168.1.129"),
        (" 192.168.1.129 ", "192.168.1.129"),
        ("DSS220.Local.", "dss220.local"),
        ("[fe80::1]", "fe80::1"),
        ("2001:DB8::1", "2001:db8::1"),
    ],
)
def test_validate_host(host: str, expected: str) -> None:
    """Host names and IP addresses are normalized."""
    assert soap.validate_host(host) == expected


@pytest.mark.parametrize(
    "host", ["", "http://dss", "dss/path", "dss:8080", "-dss", "a..b", "a b", "x" * 254]
)
def test_validate_host_invalid(host: str) -> None:
    """Anything that is not a plain host name or address is refused."""
    with pytest.raises(ValueError):
        soap.validate_host(host)


def test_build_base_url() -> None:
    """The base URL points at the SMI services; IPv6 gets brackets."""
    assert soap.build_base_url("192.0.2.10", 8080) == "http://192.0.2.10:8080/dcinema/ws/smi/v1"
    assert soap.build_base_url("2001:db8::1", 80) == "http://[2001:db8::1]:80/dcinema/ws/smi/v1"
    for port in (0, 65536):
        with pytest.raises(ValueError):
            soap.build_base_url("192.0.2.10", port)


def test_validate_uuid() -> None:
    """Only urn:uuid identifiers are sent to the server."""
    value = "urn:uuid:11111111-2222-3333-4444-555555555555"
    assert soap.validate_uuid(value) == value
    for bad in ("11111111-2222-3333-4444-555555555555", "urn:uuid:<x/>", ""):
        with pytest.raises(ValueError):
            soap.validate_uuid(bad)


def test_durations() -> None:
    """xs:duration values are converted both ways."""
    assert soap.format_duration(3725.5) == "PT1H2M5.500S"
    assert soap.format_duration(0) == "PT0H0M0.000S"
    for bad in (-1.0, float("nan")):
        with pytest.raises(ValueError):
            soap.format_duration(bad)

    assert soap.parse_duration("PT1H2M5.5S") == pytest.approx(3725.5)
    assert soap.parse_duration("P0Y0M0DT0H2M33.250S") == pytest.approx(153.25)
    assert soap.parse_duration("P1DT1S") == pytest.approx(86401)
    assert soap.parse_duration("-PT10S") == pytest.approx(-10)
    for bad in (None, "", "P", "PT", "10 seconds", "PT1H2X"):
        assert soap.parse_duration(bad) is None


def test_parse_bool_and_datetime() -> None:
    """xs:boolean and xs:dateTime values are parsed leniently."""
    assert soap.parse_bool("true") is True
    assert soap.parse_bool(" 1 ") is True
    assert soap.parse_bool("FALSE") is False
    assert soap.parse_bool("0") is False
    assert soap.parse_bool("maybe") is None
    assert soap.parse_bool(None) is None

    assert soap.parse_datetime("2026-11-21T22:48:27Z") == datetime(
        2026, 11, 21, 22, 48, 27, tzinfo=UTC
    )
    assert soap.parse_datetime("2026-11-21T22:48:27").tzinfo is UTC
    assert soap.parse_datetime("2026-11-21T23:48:27+01:00").utcoffset().total_seconds() == 3600
    assert soap.parse_datetime("yesterday") is None
    assert soap.parse_datetime(None) is None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


def test_real_get_input_select() -> None:
    """A response captured from a DSS220 with a CAT745."""
    response = soap.parse_response(soap.OP_GET_INPUT_SELECT, _fixture("get_input_select.xml"))
    assert soap.parse_single_text(response, "inputSelectMode") == "SERVER"


def test_playback_state() -> None:
    """A playing show with its clip and positions."""
    response = soap.parse_response(soap.OP_GET_PLAYBACK_STATE, _fixture("get_playback_state2.xml"))
    state = soap.parse_playback_state(response)
    assert state.transport_state == "PLAYING"
    assert state.unavailable_reasons == ()
    assert state.playback_mode == "TWO_D"
    assert state.content_id == "urn:uuid:11111111-2222-3333-4444-555555555555"
    assert state.content_type == "SHOW"
    assert state.current_clip_id == "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert state.current_clip_index == 3
    assert state.clip_position == pytest.approx(65.5)
    assert state.clip_duration == pytest.approx(153.25)
    assert state.show_position == pytest.approx(605.5)
    assert state.show_duration == pytest.approx(1116.423)


def test_playback_state_unavailable() -> None:
    """An unavailable media block, with an extension reason."""
    response = soap.parse_response(
        soap.OP_GET_PLAYBACK_STATE, _fixture("get_playback_state2_unavailable.xml")
    )
    state = soap.parse_playback_state(response)
    assert state.transport_state == "UNAVAILABLE"
    assert state.unavailable_reasons == ("CONNECTION_ERROR", "IMB_BOOTING")
    assert state.content_id is None
    assert state.current_clip_index is None


def test_playback_state_odd_values() -> None:
    """A clip index that is not a number is ignored; no transport state is an error."""
    response = soap.parse_response(
        soap.OP_GET_PLAYBACK_STATE,
        _envelope(
            "<r:getPlaybackState2Response xmlns:r='http://www.dolby.com/dcinema/ws/smi/v1_3'>"
            "<transportState><transportStateType>STOPPED</transportStateType></transportState>"
            "<contentPlaybackState><currentClipIndex>x</currentClipIndex></contentPlaybackState>"
            "</r:getPlaybackState2Response>"
        ),
    )
    assert soap.parse_playback_state(response).current_clip_index is None

    empty = soap.parse_response(
        soap.OP_GET_PLAYBACK_STATE,
        _envelope(
            "<r:getPlaybackState2Response xmlns:r='http://www.dolby.com/dcinema/ws/smi/v1_3'>"
            "<transportState/></r:getPlaybackState2Response>"
        ),
    )
    with pytest.raises(soap.DSSProtocolError):
        soap.parse_playback_state(empty)


def test_show_infos() -> None:
    """Shows with their playability and license state."""
    response = soap.parse_response(soap.OP_GET_SHOW_INFOS, _fixture("get_show_infos.xml"))
    shows = soap.parse_show_infos(response)
    assert [show.name for show in shows] == ["Demo Show", "Trailer Reel"]
    assert shows[0].playable is True
    assert shows[0].duration == pytest.approx(1116.423)
    assert shows[1].playable is False
    assert shows[1].encrypted is True
    assert shows[1].licensed == "MISSING"


def test_show_infos_incomplete() -> None:
    """A show without an ID is skipped; one without a name is named by its ID."""
    response = soap.parse_response(
        soap.OP_GET_SHOW_INFOS,
        _envelope(
            "<r:getShowInfosResponse xmlns:r='http://www.dolby.com/dcinema/ws/smi/v1_0'>"
            "<showInfo><name>No id</name></showInfo>"
            "<showInfo><showId>urn:uuid:11111111-2222-3333-4444-555555555555</showId></showInfo>"
            "</r:getShowInfosResponse>"
        ),
    )
    shows = soap.parse_show_infos(response)
    assert len(shows) == 1
    assert shows[0].name == shows[0].show_id
    assert shows[0].playable is True


def test_clip_infos() -> None:
    """Clip details from the content management service."""
    response = soap.parse_response(soap.OP_GET_CLIP_INFOS, _fixture("get_clip_infos.xml"))
    clips = soap.parse_clip_infos(response)
    assert len(clips) == 1
    assert clips[0].name == "Demo_TLR_F_EN-XX_51_2K_20260101_SMPTE_OV"
    assert clips[0].clip_type == "TRAILER"
    assert clips[0].duration == pytest.approx(153.25)
    assert clips[0].playable is True


def test_system_time() -> None:
    """The server clock and its time zone."""
    response = soap.parse_response(soap.OP_GET_SYSTEM_TIME, _fixture("get_system_time.xml"))
    result = soap.parse_system_time(response)
    assert result.time == datetime(2026, 11, 21, 22, 48, 27, 123000, tzinfo=UTC)
    assert result.time_zone == "WET"


def test_device_components() -> None:
    """The server component carries the software version and alarms."""
    response = soap.parse_response(
        soap.OP_GET_DEVICE_COMPONENT_INFOS, _fixture("get_device_component_infos.xml")
    )
    components = soap.parse_device_components(response)
    assert [component.component_type for component in components] == ["SERVER", "IMB"]
    server = soap.find_server_component(components)
    assert server is components[0]
    assert server.model == "DSS220"
    assert server.version == "4.9.5.2"
    assert server.properties == {"BIOS Version": "1.0c_Dolby", "Software Version": "4.9.5.2"}
    assert server.alarms == (
        soap.DeviceAlarm(
            component="DSS220", alarm_type="FAN", severity="WARNING", name="Fan 5 not detected"
        ),
    )
    assert soap.unique_id_from_component(server) == "0f8c6a5e-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
    assert components[1].model == "CAT745"
    assert components[1].version is None


def test_device_components_fallbacks() -> None:
    """Without a software property the first version is used; incomplete items are skipped."""
    response = soap.parse_response(
        soap.OP_GET_DEVICE_COMPONENT_INFOS,
        _envelope(
            "<r:getDeviceComponentInfosResponse"
            " xmlns:r='http://www.dolby.com/dcinema/ws/smi/v1_0'>"
            "<deviceComponentInfo><deviceComponentType>SERVER</deviceComponentType>"
            "</deviceComponentInfo>"
            "<deviceComponentInfo>"
            "<deviceComponentId>urn:uuid:11111111-2222-3333-4444-555555555555</deviceComponentId>"
            "<deviceComponentType>PLAYER</deviceComponentType>"
            "<deviceComponentProperty><type>VERSION</type><name>Firmware</name>"
            "<value>2.1</value></deviceComponentProperty>"
            "<deviceComponentProperty><type>OTHER</type><name>Serial</name></deviceComponentProperty>"
            "<deviceComponentAlarm/>"
            "</deviceComponentInfo>"
            "</r:getDeviceComponentInfosResponse>"
        ),
    )
    components = soap.parse_device_components(response)
    assert len(components) == 1
    player = components[0]
    assert player.version == "2.1"
    assert player.properties == {"Firmware": "2.1"}
    assert player.alarms[0].component == "PLAYER"
    assert player.alarms[0].alarm_type == "UNKNOWN"
    assert soap.find_server_component(components) is player
    assert soap.find_server_component([]) is None


def test_fault() -> None:
    """A SOAP fault is raised with its type and reason."""
    with pytest.raises(soap.DSSFaultError) as err:
        soap.parse_response(soap.OP_GET_DOUSER, _fixture("fault_not_connected.xml"))
    assert err.value.fault_type == "NotConnected"
    assert err.value.reason == "CAT745 is not connected"
    assert str(err.value) == "NotConnected: CAT745 is not connected"


def test_fault_without_detail() -> None:
    """A fault without detail falls back to the fault string."""
    with pytest.raises(soap.DSSFaultError) as err:
        soap.parse_response(
            soap.OP_PLAY,
            _envelope(
                "<env:Fault><faultcode>env:Server</faultcode>"
                "<faultstring>Internal error</faultstring></env:Fault>"
            ),
        )
    assert err.value.fault_type is None
    assert str(err.value) == "Fault: Internal error"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"<html><body>Not Found</body></html>", id="html"),
        pytest.param(b"<env:Envelope xmlns:env='x'/>", id="no-body"),
        pytest.param(b"not xml at all", id="garbage"),
        pytest.param(_envelope("<other/>"), id="wrong-response"),
    ],
)
def test_invalid_responses(payload: bytes) -> None:
    """Anything that is not the expected SOAP response is a protocol error."""
    with pytest.raises(soap.DSSProtocolError):
        soap.parse_response(soap.OP_PLAY, payload)


def test_entity_expansion_refused() -> None:
    """Entity declarations (billion laughs, external entities) are refused."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        b"<env:Envelope xmlns:env='http://schemas.xmlsoap.org/soap/envelope/'>"
        b"<env:Body>&lol2;</env:Body></env:Envelope>"
    )
    external = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]>'
        b"<env:Envelope xmlns:env='http://schemas.xmlsoap.org/soap/envelope/'>"
        b"<env:Body>&ext;</env:Body></env:Envelope>"
    )
    for payload in (bomb, external):
        with pytest.raises(soap.DSSProtocolError):
            soap.parse_response(soap.OP_PLAY, payload)


def test_oversized_response_refused() -> None:
    """A response above the size limit is not parsed at all."""
    payload = b" " * (soap.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(soap.DSSProtocolError, match="too large"):
        soap.parse_response(soap.OP_PLAY, payload)
