"""Async client for the Dolby DSS SMI web services."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import logging
from typing import TYPE_CHECKING

import aiohttp

from .soap import (
    INPUT_SELECT_MODES,
    MAX_RESPONSE_BYTES,
    OP_GET_CLIP_INFOS,
    OP_GET_DEVICE_COMPONENT_INFOS,
    OP_GET_DOUSER,
    OP_GET_INPUT_SELECT,
    OP_GET_LAMP,
    OP_GET_MUTE,
    OP_GET_PLAYBACK_STATE,
    OP_GET_SCHEDULE_MODE,
    OP_GET_SHOW_INFOS,
    OP_GET_SYSTEM_TIME,
    OP_GET_VOLUME,
    OP_GO_TO_POSITION,
    OP_INPUT_SELECT,
    OP_NEXT,
    OP_PAUSE,
    OP_PLAY,
    OP_PREVIOUS,
    OP_SELECT_CONTENT,
    OP_SET_DOUSER,
    OP_SET_LAMP,
    OP_SET_MUTE,
    OP_SET_SCHEDULE_MODE,
    OP_SET_VOLUME,
    OP_STOP,
    PLAYABLE_CONTENT_TYPES,
    SCHEDULE_MODES,
    VOLUME_MAX,
    VOLUME_MIN,
    ClipInfo,
    DeviceComponent,
    DSSConnectionError,
    DSSFaultError,
    DSSProtocolError,
    Operation,
    PlaybackState,
    ShowInfo,
    SystemTime,
    build_base_url,
    build_envelope,
    format_duration,
    parse_bool,
    parse_clip_infos,
    parse_device_components,
    parse_playback_state,
    parse_response,
    parse_show_infos,
    parse_single_text,
    parse_system_time,
    validate_uuid,
)

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element  # noqa: S405 - type hints only

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


async def _read_limited(resp: aiohttp.ClientResponse) -> bytes:
    """Read the response body, stopping just past the size limit.

    A single read returns only what has arrived so far, so the body is read in
    chunks until the end or until it is known to be too large.
    """
    payload = bytearray()
    async for chunk in resp.content.iter_chunked(64 * 1024):
        payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            break
    return bytes(payload)


class DSSClient:
    """Client for one Dolby DSS server.

    Requests are serialized: the server is an older JBoss installation and
    does not need to handle parallel calls from Home Assistant.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = build_base_url(host, port)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Return the base URL of the web services."""
        return self._base_url

    async def _call(self, operation: Operation, params: Sequence[tuple[str, str]] = ()) -> Element:
        """Perform one SOAP call and return the response element."""
        url = f"{self._base_url}/{operation.service}"
        body = build_envelope(operation, params)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": operation.soap_action,
        }
        async with self._lock:
            try:
                async with self._session.post(
                    url,
                    data=body,
                    headers=headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                ) as resp:
                    status = resp.status
                    payload = await _read_limited(resp)
            except (TimeoutError, aiohttp.ClientError, OSError) as err:
                raise DSSConnectionError(
                    f"Cannot reach {operation.service}: {err or type(err).__name__}"
                ) from err

        _LOGGER.debug("%s returned HTTP %s (%d bytes)", operation.name, status, len(payload))
        if status not in (200, 500):
            raise DSSProtocolError(f"{operation.name} returned HTTP {status}")
        # SOAP faults are delivered with HTTP 500; parse_response raises them.
        return parse_response(operation, payload)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    async def get_playback_state(self) -> PlaybackState:
        """Return the current transport and content state."""
        return parse_playback_state(await self._call(OP_GET_PLAYBACK_STATE))

    async def play(self) -> None:
        """Start or resume playback."""
        await self._call(OP_PLAY)

    async def pause(self) -> None:
        """Pause playback."""
        await self._call(OP_PAUSE)

    async def stop(self) -> None:
        """Stop playback."""
        await self._call(OP_STOP)

    async def next(self) -> None:
        """Jump to the next clip."""
        await self._call(OP_NEXT)

    async def previous(self) -> None:
        """Jump to the previous clip."""
        await self._call(OP_PREVIOUS)

    async def select_content(self, content_id: str, content_type: str = "SHOW") -> None:
        """Select a show or clip for playback."""
        if content_type not in PLAYABLE_CONTENT_TYPES:
            raise ValueError(f"Invalid content type: {content_type!r}")
        await self._call(
            OP_SELECT_CONTENT,
            (("contentId", validate_uuid(content_id)), ("playableContentType", content_type)),
        )

    async def go_to_position(self, seconds: float) -> None:
        """Move playback to a position (in seconds) within the selected content."""
        await self._call(OP_GO_TO_POSITION, (("position", format_duration(seconds)),))

    async def get_schedule_mode(self) -> str | None:
        """Return the schedule mode."""
        return parse_single_text(await self._call(OP_GET_SCHEDULE_MODE), "scheduleMode")

    async def set_schedule_mode(self, mode: str) -> None:
        """Set the schedule mode."""
        if mode not in SCHEDULE_MODES:
            raise ValueError(f"Invalid schedule mode: {mode!r}")
        await self._call(OP_SET_SCHEDULE_MODE, (("scheduleMode", mode),))

    async def get_input_select(self) -> str | None:
        """Return the selected input of the media block."""
        return parse_single_text(await self._call(OP_GET_INPUT_SELECT), "inputSelectMode")

    async def set_input_select(self, mode: str) -> None:
        """Select an input of the media block."""
        if mode not in INPUT_SELECT_MODES:
            raise ValueError(f"Invalid input: {mode!r}")
        await self._call(OP_INPUT_SELECT, (("inputSelectMode", mode),))

    async def get_volume(self) -> float | None:
        """Return the cinema processor fader (0.0 - 10.0)."""
        text = parse_single_text(await self._call(OP_GET_VOLUME), "volume")
        if text is None:
            return None
        try:
            return float(text)
        except ValueError as err:
            raise DSSProtocolError(f"Invalid volume value: {text!r}") from err

    async def set_volume(self, volume: float) -> None:
        """Set the cinema processor fader (0.0 - 10.0)."""
        if not VOLUME_MIN <= volume <= VOLUME_MAX:
            raise ValueError(f"Invalid volume: {volume!r}")
        await self._call(OP_SET_VOLUME, (("volume", f"{volume:.1f}"),))

    async def get_mute(self) -> bool | None:
        """Return whether audio is muted."""
        return parse_bool(parse_single_text(await self._call(OP_GET_MUTE), "muted"))

    async def set_mute(self, muted: bool) -> None:
        """Mute or unmute audio."""
        await self._call(OP_SET_MUTE, (("muted", "true" if muted else "false"),))

    async def get_douser(self) -> bool | None:
        """Return whether the projector douser is closed."""
        return parse_bool(parse_single_text(await self._call(OP_GET_DOUSER), "doused"))

    async def set_douser(self, doused: bool) -> None:
        """Close (True) or open (False) the projector douser."""
        await self._call(OP_SET_DOUSER, (("doused", "true" if doused else "false"),))

    async def get_lamp(self) -> bool | None:
        """Return whether the projector lamp is on."""
        return parse_bool(parse_single_text(await self._call(OP_GET_LAMP), "struck"))

    async def set_lamp(self, on: bool) -> None:
        """Switch the projector lamp on or off."""
        await self._call(OP_SET_LAMP, (("struck", "true" if on else "false"),))

    # ------------------------------------------------------------------
    # Shows, clips and system
    # ------------------------------------------------------------------

    async def get_show_infos(self) -> list[ShowInfo]:
        """Return all shows known to the server."""
        return parse_show_infos(await self._call(OP_GET_SHOW_INFOS))

    async def get_clip_info(self, clip_id: str) -> ClipInfo | None:
        """Return information about a single clip."""
        clips = parse_clip_infos(
            await self._call(OP_GET_CLIP_INFOS, (("clipId", validate_uuid(clip_id)),))
        )
        for clip in clips:
            if clip.clip_id.lower() == clip_id.lower():
                return clip
        return clips[0] if clips else None

    async def get_system_time(self) -> SystemTime:
        """Return the server time and time zone."""
        return parse_system_time(await self._call(OP_GET_SYSTEM_TIME))

    async def get_device_components(self) -> list[DeviceComponent]:
        """Return the device components (server, player, projector, ...)."""
        return parse_device_components(await self._call(OP_GET_DEVICE_COMPONENT_INFOS))


__all__ = [
    "DSSClient",
    "DSSConnectionError",
    "DSSFaultError",
    "DSSProtocolError",
]
