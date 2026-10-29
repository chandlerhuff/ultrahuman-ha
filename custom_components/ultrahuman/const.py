"""Constants and device identifiers for the Ultrahuman integration."""

import re

DOMAIN = "ultrahuman"

CONF_API_KEY = "api_key"
CONF_EMAIL = "email"
CONF_DEVICE_TYPE = "device_type"
CONF_MAC_ADDRESS = "mac_address"
CONF_UPDATE_INTERVAL = "update_interval"

DEVICE_TYPE_DAILY = "daily"
DEVICE_TYPE_HOME = "home"

DEFAULT_HOME_UPDATE_INTERVAL = 5
MIN_HOME_UPDATE_INTERVAL = 1
MAX_HOME_UPDATE_INTERVAL = 60

HOME_METRICS = (
    "hcho",
    "co",
    "co2",
    "pm1",
    "pm10",
    "pm25",
    "voc",
    "temp",
    "humidity",
    "noise",
    "mic",
    "uva",
    "uvb",
    "uvc",
    "red",
    "green",
    "blue",
    "ir",
    "aqi",
)

API_BASE_URL = "https://partner.ultrahuman.com/api/v1/partner"
API_DAILY_METRICS_ENDPOINT = f"{API_BASE_URL}/daily_metrics"
API_HOME_METRICS_ENDPOINT = f"{API_BASE_URL}/home_metrics"


def normalize_mac_address(value: str) -> str:
    """Return a canonical MAC address, accepting colon, hyphen or plain hex."""
    value = value.strip()
    if not re.fullmatch(
        r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|"
        r"(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})",
        value,
    ):
        raise ValueError("Invalid MAC address")
    compact = value.replace(":", "").replace("-", "").upper()
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))
