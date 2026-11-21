"""SOAP envelope building and response parsing for the Dolby DSS SMI web services.

The Dolby DSS200/DSS220 Show Store exposes its official "SMI" (Show Management
Interface) web services through JBoss on TCP port 8080. This module turns
requests into SOAP envelopes and parses the responses into plain dataclasses.

It deliberately has no Home Assistant or aiohttp imports, so the protocol
handling can be tested in isolation.

Security notes:
- Responses are parsed with defusedxml (no DTDs, so no entity expansion and no
  external entities) and are size-capped before parsing.
- Every value that is sent to the server is validated and XML-escaped.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import ipaddress
import re
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element  # noqa: S405 - type hints only

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SMI_NAMESPACE_BASE = "http://www.dolby.com/dcinema/ws/smi"
SMI_ACTION_BASE = "http://www.dolby.com/dcinema/ws/smi/v1"
SMI_PATH = "/dcinema/ws/smi/v1"

# Largest response we are willing to parse. A full show list of a busy server
# stays far below this; anything larger is treated as a protocol error.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

UUID_RE = re.compile(
    r"^urn:uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PARAM_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)
_DURATION_RE = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

# Values accepted by the server, taken from the published XSD schemas.
INPUT_SELECT_MODES = ("SERVER", "HDMI_1", "HDMI_2", "HD_SDI")
SCHEDULE_MODES = ("FULL_AUTOMATIC", "SELECT_AUTOMATIC", "MANUAL")
TRANSPORT_STATES = (
    "READY",
    "SELECTING",
    "RECOVERING",
    "LATE",
    "PLAYING",
    "STOPPED",
    "PAUSED",
    "UNSELECTED",
    "SEEKING",
    "UNAVAILABLE",
)
PLAYABLE_CONTENT_TYPES = ("CLIP", "SHOW")
VOLUME_MIN = 0.0
VOLUME_MAX = 10.0


class DSSError(Exception):
    """Base class for all DSS errors."""


class DSSConnectionError(DSSError):
    """The server could not be reached."""


class DSSProtocolError(DSSError):
    """The server answered with something we do not understand."""


class DSSFaultError(DSSError):
    """The server answered with a SOAP fault."""

    def __init__(self, fault_type: str | None, reason: str | None) -> None:
        """Initialize the fault."""
        self.fault_type = fault_type
        self.reason = reason
        message = fault_type or "Fault"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Operation:
    """A single SMI web service operation."""

    service: str
    name: str
    version: str

    @property
    def namespace(self) -> str:
        """Return the namespace of the request element."""
        return f"{SMI_NAMESPACE_BASE}/{self.version}"

    @property
    def soap_action(self) -> str:
        """Return the SOAPAction header value."""
        return f'"{SMI_ACTION_BASE}/{self.name}"'


_PLAYBACK = "PlaybackControlService"
_SHOWS = "ShowManagementService"
_CONTENT = "ContentManagementService"
_SYSTEM = "SystemManagementService"

OP_GET_PLAYBACK_STATE = Operation(_PLAYBACK, "getPlaybackState2", "v1_3")
OP_SELECT_CONTENT = Operation(_PLAYBACK, "selectContent", "v1_0")
OP_PLAY = Operation(_PLAYBACK, "play", "v1_0")
OP_PAUSE = Operation(_PLAYBACK, "pause", "v1_0")
OP_STOP = Operation(_PLAYBACK, "stop", "v1_0")
OP_NEXT = Operation(_PLAYBACK, "next", "v1_0")
OP_PREVIOUS = Operation(_PLAYBACK, "previous", "v1_0")
OP_GO_TO_POSITION = Operation(_PLAYBACK, "goToPosition", "v1_0")
OP_GET_SCHEDULE_MODE = Operation(_PLAYBACK, "getScheduleMode", "v1_0")
OP_SET_SCHEDULE_MODE = Operation(_PLAYBACK, "setScheduleMode", "v1_0")
OP_GET_INPUT_SELECT = Operation(_PLAYBACK, "getInputSelect", "v1_4")
OP_INPUT_SELECT = Operation(_PLAYBACK, "inputSelect", "v1_4")
OP_GET_VOLUME = Operation(_PLAYBACK, "getVolume", "v1_5")
OP_SET_VOLUME = Operation(_PLAYBACK, "setVolume", "v1_5")
OP_GET_MUTE = Operation(_PLAYBACK, "getMute", "v1_5")
OP_SET_MUTE = Operation(_PLAYBACK, "setMute", "v1_5")
OP_GET_DOUSER = Operation(_PLAYBACK, "getDouser", "v1_5")
OP_SET_DOUSER = Operation(_PLAYBACK, "setDouser", "v1_5")
OP_GET_LAMP = Operation(_PLAYBACK, "getLamp", "v1_5")
OP_SET_LAMP = Operation(_PLAYBACK, "setLamp", "v1_5")
OP_GET_SHOW_INFOS = Operation(_SHOWS, "getShowInfos", "v1_0")
OP_GET_CLIP_INFOS = Operation(_CONTENT, "getClipInfos", "v1_0")
OP_GET_SYSTEM_TIME = Operation(_SYSTEM, "getSystemTime", "v1_0")
OP_GET_DEVICE_COMPONENT_INFOS = Operation(_SYSTEM, "getDeviceComponentInfos", "v1_0")


@dataclass(frozen=True, slots=True)
class PlaybackState:
    """Result of getPlaybackState2."""

    transport_state: str
    unavailable_reasons: tuple[str, ...] = ()
    playback_mode: str | None = None
    content_id: str | None = None
    content_type: str | None = None
    current_clip_id: str | None = None
    current_clip_index: int | None = None
    clip_position: float | None = None
    clip_duration: float | None = None
    show_position: float | None = None
    show_duration: float | None = None


@dataclass(frozen=True, slots=True)
class ShowInfo:
    """A show (SPL) known to the server."""

    show_id: str
    name: str
    duration: float | None
    playable: bool
    encrypted: bool | None
    licensed: str | None


@dataclass(frozen=True, slots=True)
class ClipInfo:
    """A clip (CPL) known to the server."""

    clip_id: str
    name: str
    clip_type: str | None
    duration: float | None
    playable: bool | None


@dataclass(frozen=True, slots=True)
class SystemTime:
    """Result of getSystemTime."""

    time: datetime | None
    time_zone: str | None


@dataclass(frozen=True, slots=True)
class DeviceAlarm:
    """An active alarm on a device component."""

    component: str
    alarm_type: str
    severity: str
    name: str


@dataclass(frozen=True, slots=True)
class DeviceComponent:
    """A device component (server, player, projector, ...) of the system."""

    component_id: str
    component_type: str
    model: str | None
    location: str | None
    version: str | None
    properties: dict[str, str]
    alarms: tuple[DeviceAlarm, ...]


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def validate_host(host: str) -> str:
    """Return a normalized host name or IP address, or raise ValueError."""
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if _HOSTNAME_RE.match(value):
        return value.rstrip(".").lower()
    raise ValueError(f"Invalid host: {host!r}")


def build_base_url(host: str, port: int) -> str:
    """Return the base URL of the SMI web services."""
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid port: {port}")
    clean = validate_host(host)
    if ":" in clean:  # IPv6 literal
        clean = f"[{clean}]"
    return f"http://{clean}:{port}{SMI_PATH}"


def validate_uuid(value: str) -> str:
    """Return the value if it is a urn:uuid identifier, or raise ValueError."""
    if not UUID_RE.match(value):
        raise ValueError(f"Invalid content id: {value!r}")
    return value


def format_duration(seconds: float) -> str:
    """Format a number of seconds as an xs:duration."""
    if seconds != seconds or seconds < 0:  # NaN or negative
        raise ValueError(f"Invalid position: {seconds!r}")
    total = float(seconds)
    hours = int(total // 3600)
    minutes = int((total - hours * 3600) // 60)
    rest = total - hours * 3600 - minutes * 60
    return f"PT{hours}H{minutes}M{rest:.3f}S"


def parse_duration(value: str | None) -> float | None:
    """Parse an xs:duration into seconds; return None when not parseable."""
    if not value:
        return None
    match = _DURATION_RE.match(value.strip())
    if not match or value.strip() in ("P", "-P", "PT", "-PT"):
        return None
    parts = match.groupdict()
    total = (
        int(parts["years"] or 0) * 365 * 86400
        + int(parts["months"] or 0) * 30 * 86400
        + int(parts["days"] or 0) * 86400
        + int(parts["hours"] or 0) * 3600
        + int(parts["minutes"] or 0) * 60
        + float(parts["seconds"] or 0)
    )
    return -total if parts["sign"] else total


def parse_bool(value: str | None) -> bool | None:
    """Parse an xs:boolean."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an xs:dateTime; naive values are assumed to be UTC."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# --------------------------------------------------------------------------
# Envelope building
# --------------------------------------------------------------------------


def build_envelope(operation: Operation, params: Sequence[tuple[str, str]] = ()) -> bytes:
    """Build a SOAP 1.1 request envelope.

    The request element is namespace-qualified with a prefix; its children are
    unqualified, as required by the schemas inlined in the server's WSDL.
    """
    children: list[str] = []
    for name, value in params:
        if not _PARAM_NAME_RE.match(name):
            raise ValueError(f"Invalid parameter name: {name!r}")
        children.append(f"<{name}>{escape(value)}</{name}>")
    element = f"{operation.name}Request"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENV_NS}"><s:Body>'
        f'<m:{element} xmlns:m="{operation.namespace}">{"".join(children)}</m:{element}>'
        "</s:Body></s:Envelope>"
    ).encode()


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def _local(tag: object) -> str:
    """Return the local name of an element tag."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _child(element: Element | None, name: str) -> Element | None:
    """Return the first direct child with the given local name."""
    if element is None:
        return None
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _children(element: Element | None, name: str) -> list[Element]:
    """Return all direct children with the given local name."""
    if element is None:
        return []
    return [child for child in element if _local(child.tag) == name]


def _enum_value(element: Element | None) -> str | None:
    """Return the text of an enum element, resolving the EXTENSION form."""
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    if text == "EXTENSION" and element.get("extension"):
        return element.get("extension")
    return text or None


def _text(element: Element | None, name: str) -> str | None:
    """Return the stripped text of a direct child, or None."""
    child = _child(element, name)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _descendants(element: Element) -> Iterable[Element]:
    """Iterate over all descendants of an element."""
    for child in element:
        yield child
        yield from _descendants(child)


def _parse_fault(fault: Element) -> DSSFaultError:
    """Turn a SOAP fault element into an exception."""
    fault_string = _text(fault, "faultstring")
    fault_type: str | None = None
    reason: str | None = None
    detail = _child(fault, "detail")
    if detail is not None:
        for item in _descendants(detail):
            xsi_type = item.get(f"{{{XSI_NS}}}type")
            if fault_type is None and (xsi_type or len(item)):
                fault_type = (xsi_type or _local(item.tag)).rsplit(":", 1)[-1]
            if _local(item.tag) == "reason" and item.text and item.text.strip():
                reason = item.text.strip()
                break
    return DSSFaultError(fault_type, reason or fault_string)


def parse_response(operation: Operation, payload: bytes) -> Element:
    """Parse a SOAP response and return the response element of the operation."""
    if len(payload) > MAX_RESPONSE_BYTES:
        raise DSSProtocolError("Response too large")
    try:
        root = SafeET.fromstring(payload, forbid_dtd=True)
    except (SafeET.ParseError, DefusedXmlException) as err:
        raise DSSProtocolError(f"Invalid XML in response: {err}") from err
    if _local(root.tag) != "Envelope":
        raise DSSProtocolError("Response is not a SOAP envelope")
    body = _child(root, "Body")
    if body is None:
        raise DSSProtocolError("SOAP envelope has no body")
    fault = _child(body, "Fault")
    if fault is not None:
        raise _parse_fault(fault)
    response = _child(body, f"{operation.name}Response")
    if response is None:
        raise DSSProtocolError(f"Missing {operation.name}Response in SOAP body")
    return response


def parse_playback_state(response: Element) -> PlaybackState:
    """Parse a getPlaybackState2Response."""
    transport = _child(response, "transportState")
    state = _enum_value(_child(transport, "transportStateType"))
    if state is None:
        raise DSSProtocolError("Playback state without transport state")
    reasons = tuple(
        value
        for value in (
            _enum_value(item) for item in _children(transport, "transportStateUnavailableReason")
        )
        if value
    )
    playback_mode = _enum_value(_child(response, "playbackMode")) or response.get("playbackMode")
    content = _child(response, "contentPlaybackState")
    clip_index_text = _text(content, "currentClipIndex")
    try:
        clip_index = int(clip_index_text) if clip_index_text is not None else None
    except ValueError:
        clip_index = None
    return PlaybackState(
        transport_state=state,
        unavailable_reasons=reasons,
        playback_mode=playback_mode,
        content_id=_text(content, "contentId"),
        content_type=_text(content, "contentType"),
        current_clip_id=_text(content, "currentClipId"),
        current_clip_index=clip_index,
        clip_position=parse_duration(_text(content, "clipPosition")),
        clip_duration=parse_duration(_text(content, "clipDuration")),
        show_position=parse_duration(_text(content, "showPosition")),
        show_duration=parse_duration(_text(content, "showDuration")),
    )


def parse_show_infos(response: Element) -> list[ShowInfo]:
    """Parse a getShowInfosResponse."""
    shows: list[ShowInfo] = []
    for item in _children(response, "showInfo"):
        show_id = _text(item, "showId")
        if not show_id:
            continue
        shows.append(
            ShowInfo(
                show_id=show_id,
                name=_text(item, "name") or show_id,
                duration=parse_duration(_text(item, "duration")),
                playable=parse_bool(_text(item, "playable")) is not False,
                encrypted=parse_bool(_text(item, "encrypted")),
                licensed=_enum_value(_child(item, "licensed")),
            )
        )
    return shows


def parse_clip_infos(response: Element) -> list[ClipInfo]:
    """Parse a getClipInfosResponse."""
    clips: list[ClipInfo] = []
    for item in _children(response, "clipInfo"):
        clip_id = _text(item, "clipId")
        if not clip_id:
            continue
        clips.append(
            ClipInfo(
                clip_id=clip_id,
                name=_text(item, "name") or clip_id,
                clip_type=_enum_value(_child(item, "clipType")),
                duration=parse_duration(_text(item, "duration")),
                playable=parse_bool(_text(item, "playable")),
            )
        )
    return clips


def parse_system_time(response: Element) -> SystemTime:
    """Parse a getSystemTimeResponse."""
    return SystemTime(
        time=parse_datetime(_text(response, "time")),
        time_zone=_text(response, "timeZoneId"),
    )


def parse_device_components(response: Element) -> list[DeviceComponent]:
    """Parse a getDeviceComponentInfosResponse."""
    components: list[DeviceComponent] = []
    for item in _children(response, "deviceComponentInfo"):
        component_id = _text(item, "deviceComponentId")
        component_type = _enum_value(_child(item, "deviceComponentType"))
        if not component_id or not component_type:
            continue
        model = _text(item, "deviceComponentModel")
        properties: dict[str, str] = {}
        versions: list[tuple[str, str]] = []
        for prop in _children(item, "deviceComponentProperty"):
            name = _text(prop, "name")
            value = _text(prop, "value")
            if not name or value is None:
                continue
            properties[name] = value
            if _enum_value(_child(prop, "type")) == "VERSION":
                versions.append((name, value))
        # Prefer a property that names the software version over e.g. firmware.
        version = next(
            (value for name, value in versions if "software" in name.lower()),
            versions[0][1] if versions else None,
        )
        label = model or component_type
        alarms = tuple(
            DeviceAlarm(
                component=label,
                alarm_type=_enum_value(_child(alarm, "type")) or "UNKNOWN",
                severity=_text(alarm, "severity") or "UNKNOWN",
                name=_text(alarm, "name") or "",
            )
            for alarm in _children(item, "deviceComponentAlarm")
        )
        components.append(
            DeviceComponent(
                component_id=component_id,
                component_type=component_type,
                model=model,
                location=_text(item, "location"),
                version=version,
                properties=properties,
                alarms=alarms,
            )
        )
    return components


def parse_single_text(response: Element, name: str) -> str | None:
    """Return the text (or resolved enum value) of a single child element."""
    return _enum_value(_child(response, name))


def find_server_component(components: Sequence[DeviceComponent]) -> DeviceComponent | None:
    """Return the server component (or the player as fallback)."""
    for wanted in ("SERVER", "PLAYER"):
        for component in components:
            if component.component_type == wanted:
                return component
    return None


def unique_id_from_component(component: DeviceComponent) -> str:
    """Return a stable unique id for a device component."""
    return component.component_id.removeprefix("urn:uuid:").lower()
