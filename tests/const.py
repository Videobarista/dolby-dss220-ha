"""Shared test data: a DSS220 playing a show, as the client returns it."""

from __future__ import annotations

from custom_components.dolby_dss220.soap import (
    ClipInfo,
    DeviceAlarm,
    DeviceComponent,
    PlaybackState,
    ShowInfo,
)

# Documentation address (RFC 5737) and made-up identifiers.
HOST = "192.0.2.10"
PORT = 8080
SERVER_ID = "urn:uuid:0F8C6A5E-1C2D-4E3F-8A9B-0C1D2E3F4A5B"
UNIQUE_ID = "0f8c6a5e-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
OTHER_SERVER_ID = "urn:uuid:99999999-8888-7777-6666-555555555555"
SHOW_ID = "urn:uuid:11111111-2222-3333-4444-555555555555"
SHOW2_ID = "urn:uuid:66666666-7777-8888-9999-000000000000"
SHOW3_ID = "urn:uuid:12121212-3434-5656-7878-909090909090"
CLIP_ID = "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIP_NAME = "Demo_TLR_F_EN-XX_51_2K_20260101_SMPTE_OV"
SW_VERSION = "4.9.5.2"

PLAYBACK = PlaybackState(
    transport_state="PLAYING",
    playback_mode="TWO_D",
    content_id=SHOW_ID,
    content_type="SHOW",
    current_clip_id=CLIP_ID,
    current_clip_index=3,
    clip_position=65.5,
    clip_duration=153.25,
    show_position=605.5,
    show_duration=1116.423,
)

SHOWS = [
    ShowInfo(
        show_id=SHOW_ID,
        name="Demo Show",
        duration=1116.423,
        playable=True,
        encrypted=False,
        licensed="NOT_NEEDED",
    ),
    ShowInfo(
        show_id=SHOW2_ID,
        name="Trailer Reel",
        duration=720.0,
        playable=False,
        encrypted=True,
        licensed="MISSING",
    ),
]

CLIP = ClipInfo(
    clip_id=CLIP_ID,
    name=CLIP_NAME,
    clip_type="TRAILER",
    duration=153.25,
    playable=True,
)

ALARM = DeviceAlarm(
    component="DSS220", alarm_type="FAN", severity="WARNING", name="Fan 5 not detected"
)

SERVER = DeviceComponent(
    component_id=SERVER_ID,
    component_type="SERVER",
    model="DSS220",
    location="1",
    version=SW_VERSION,
    properties={"Software Version": SW_VERSION},
    alarms=(ALARM,),
)

MEDIA_BLOCK = DeviceComponent(
    component_id="urn:uuid:12345678-1234-1234-1234-123456789abc",
    component_type="IMB",
    model="CAT745",
    location="1",
    version=None,
    properties={},
    alarms=(),
)
