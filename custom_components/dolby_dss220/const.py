"""Constants for the Dolby DSS220 integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "dolby_dss220"
MANUFACTURER: Final = "Dolby"
DEFAULT_MODEL: Final = "DSS220"
DEFAULT_NAME: Final = "Dolby DSS220"
DEFAULT_PORT: Final = 8080

CONF_ALLOW_CONTROL: Final = "allow_control"
CONF_MODEL: Final = "model"
CONF_SW_VERSION: Final = "sw_version"
DEFAULT_ALLOW_CONTROL: Final = False

# Transport state and selected input are polled every cycle; the rest less often.
SCAN_INTERVAL: Final = timedelta(seconds=5)
MEDIUM_INTERVAL: Final = timedelta(seconds=30)
SLOW_INTERVAL: Final = timedelta(minutes=5)

# Upper bound for the clip-name cache.
CLIP_CACHE_SIZE: Final = 500

# Inputs offered in the input select. HD-SDI is only added when the server reports it.
INPUT_OPTIONS: Final = ("SERVER", "HDMI_1", "HDMI_2")
