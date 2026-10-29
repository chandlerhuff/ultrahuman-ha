"""The Ultrahuman integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UltrahumanApiClient
from .const import (
    CONF_API_KEY,
    CONF_DEVICE_TYPE,
    CONF_EMAIL,
    CONF_MAC_ADDRESS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HOME_UPDATE_INTERVAL,
    DEVICE_TYPE_DAILY,
    DEVICE_TYPE_HOME,
    DOMAIN,
)
from .coordinator import UltrahumanDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CARD_JS_URL = "/ultrahuman/ultrahuman-ring-card.js"
CARD_JS_PATH = Path(__file__).parent / "www" / "ultrahuman-ring-card.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the static path for the custom card."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_JS_URL, str(CARD_JS_PATH), False)]
    )

    # Register the card as a Lovelace resource
    await _async_register_card_resource(hass)

    return True


async def _async_register_card_resource(hass: HomeAssistant) -> None:
    """Register the card JS as a Lovelace resource if not already present."""
    # We use the lovelace resources collection if available
    try:
        resources = hass.data.get("lovelace", {})
        if hasattr(resources, "resources"):
            # Managed mode: check if our resource is already registered
            collection = resources.resources
            existing = [
                r
                for r in collection.async_items()
                if r.get("url", "").endswith("ultrahuman-ring-card.js")
            ]
            if not existing:
                await collection.async_create_item(
                    {"res_type": "module", "url": CARD_JS_URL}
                )
                _LOGGER.debug("Registered Ultrahuman card as Lovelace resource")
    except Exception:  # noqa: BLE001 - optional card registration must not block setup
        _LOGGER.debug(
            "Could not auto-register Lovelace resource. "
            "You may need to add it manually: %s",
            CARD_JS_URL,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ultrahuman from a config entry."""
    session = async_get_clientsession(hass)
    client = UltrahumanApiClient(
        session=session,
        api_key=entry.data[CONF_API_KEY],
        email=entry.data.get(CONF_EMAIL),
    )

    coordinator = UltrahumanDataUpdateCoordinator(
        hass,
        client,
        device_type=entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_DAILY),
        mac_address=entry.data.get(CONF_MAC_ADDRESS),
        update_interval_minutes=entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_HOME_UPDATE_INTERVAL
        ),
        config_entry=entry,
    )
    coordinator.configured_data = dict(entry.data)

    # Perform an initial data fetch so sensors have data
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply interval changes live, or reload after credential replacement."""
    coordinator: UltrahumanDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if dict(entry.data) != coordinator.configured_data:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    if coordinator.device_type == DEVICE_TYPE_HOME:
        coordinator.update_interval = timedelta(
            minutes=entry.options.get(
                CONF_UPDATE_INTERVAL, DEFAULT_HOME_UPDATE_INTERVAL
            )
        )
        await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
