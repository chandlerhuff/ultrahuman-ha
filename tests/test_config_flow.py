"""Exercise user-visible setup and options through Home Assistant's flow manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultrahuman.api import (
    UltrahumanApiError,
    UltrahumanAuthError,
    UltrahumanRateLimitError,
)
from custom_components.ultrahuman.const import DOMAIN

MAC = "AA:BB:CC:DD:EE:FF"
DAILY_PAYLOAD = {"data": {"metrics": {}, "latest_time_zone": "UTC"}, "error": None}
HOME_PAYLOAD = {
    "data": {
        "home": {"mac_address": MAC, "name": "Bedroom", "room_type": "bedroom"},
        "date_range": {"start_epoch": 100, "end_epoch": 200, "timezone": "UTC"},
        "metrics": [],
    },
    "error": None,
}


@pytest.fixture
async def client():
    """Keep flow validation local while still testing the real response parser."""
    client = MagicMock()
    client.async_get_daily_metrics = AsyncMock(return_value=DAILY_PAYLOAD)
    client.async_get_home_metrics = AsyncMock(return_value=HOME_PAYLOAD)
    with (
        patch(
            "custom_components.ultrahuman.config_flow.UltrahumanApiClient",
            return_value=client,
        ),
        patch("custom_components.ultrahuman.async_setup_entry", return_value=True),
    ):
        yield client


async def start_step(hass, step):
    menu = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert menu["type"] is FlowResultType.MENU
    assert set(menu["menu_options"]) == {"daily", "home"}
    result = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": step}
    )
    assert result["step_id"] == step
    return result


async def test_daily_setup_accepts_valid_empty_day(hass, client):
    result = await start_step(hass, "daily")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "email": " Person@Example.com "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "device_type": "daily",
        "api_key": "token",
        "email": "person@example.com",
    }
    assert result["result"].unique_id == "daily:person@example.com"
    client.async_get_daily_metrics.assert_awaited_once()
    client.async_get_home_metrics.assert_not_awaited()


async def test_home_only_setup_normalizes_mac_and_accepts_empty_readings(hass, client):
    result = await start_step(hass, "home")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "mac_address": "aa-bb-cc-dd-ee-ff"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_type"] == "home"
    assert result["data"]["mac_address"] == MAC
    assert result["result"].unique_id == f"home:{MAC}"
    assert not result["data"].get("email")
    client.async_get_home_metrics.assert_awaited_once()
    client.async_get_daily_metrics.assert_not_awaited()


async def test_duplicate_home_rejected_across_mac_formatting(hass, client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "old", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    result = await start_step(hass, "home")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "other-token", "mac_address": "aabbccddeeff"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client.async_get_home_metrics.assert_not_awaited()


async def test_multiple_home_devices_can_be_configured(hass, client):
    for mac in (MAC, "11:22:33:44:55:66"):
        client.async_get_home_metrics.return_value = {
            **HOME_PAYLOAD,
            "data": {**HOME_PAYLOAD["data"], "home": {"mac_address": mac}},
        }
        result = await start_step(hass, "home")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "token", "mac_address": mac}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


@pytest.mark.parametrize("step", ["daily", "home"])
async def test_setup_authentication_failure(hass, client, step):
    getattr(client, f"async_get_{step}_metrics").side_effect = UltrahumanAuthError(
        "expired"
    )
    fields = {"api_key": "token", "email": "person@example.com"}
    if step == "home":
        fields["mac_address"] = MAC
    result = await start_step(hass, step)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], fields)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_malformed_response_does_not_create_an_empty_integration(hass, client):
    client.async_get_daily_metrics.return_value = {"data": {"metrics": []}}
    result = await start_step(hass, "daily")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "email": "person@example.com"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_network_failure_is_reported(hass, client):
    client.async_get_home_metrics.side_effect = UltrahumanApiError("offline")
    result = await start_step(hass, "home")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "mac_address": MAC}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_mac_is_rejected_before_request(hass, client):
    result = await start_step(hass, "home")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "mac_address": "not-a-mac"}
    )
    assert result["errors"] == {"mac_address": "invalid_mac"}
    client.async_get_home_metrics.assert_not_awaited()


async def test_home_options_accept_custom_refresh_interval(hass, client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 12}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"update_interval": 12}


async def test_reauthentication_updates_existing_entry(hass, client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="daily:person@example.com",
        data={
            "device_type": "daily",
            "api_key": "expired",
            "email": "person@example.com",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "replacement"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "replacement"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.parametrize("interval", [0, 61])
async def test_home_options_reject_out_of_range_interval(hass, client, interval):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"update_interval": interval}
        )
    assert not entry.options


async def test_rate_limit_is_reported_without_repeating_validation(hass, client):
    client.async_get_home_metrics.side_effect = UltrahumanRateLimitError(retry_after=90)
    result = await start_step(hass, "home")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "token", "mac_address": MAC}
    )
    assert result["errors"] == {"base": "rate_limited"}
    client.async_get_home_metrics.assert_awaited_once()
