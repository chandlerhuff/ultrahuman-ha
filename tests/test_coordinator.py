"""Polling windows, timezone correction, and update failure isolation."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.ultrahuman.api import (
    UltrahumanApiError,
    UltrahumanAuthError,
    UltrahumanRateLimitError,
)
from custom_components.ultrahuman.const import HOME_METRICS
from custom_components.ultrahuman.coordinator import UltrahumanDataUpdateCoordinator

MAC = "AA:BB:CC:DD:EE:FF"


def daily_payload(*, timezone="UTC", metrics=None):
    return {
        "data": {"metrics": metrics or {}, "latest_time_zone": timezone},
        "error": None,
    }


def home_payload():
    return {
        "data": {
            "home": {"mac_address": MAC, "name": "Bedroom"},
            "date_range": {"start_epoch": 100, "end_epoch": 200, "timezone": "UTC"},
            "metrics": [],
        },
        "error": None,
    }


def make_client():
    client = MagicMock()
    client.async_get_daily_metrics = AsyncMock(return_value=daily_payload())
    client.async_get_home_metrics = AsyncMock(return_value=home_payload())
    return client


async def test_polling_defaults_are_hourly_daily_and_five_minute_home(hass):
    client = make_client()
    daily = UltrahumanDataUpdateCoordinator(hass, client)
    home = UltrahumanDataUpdateCoordinator(
        hass, client, device_type="home", mac_address=MAC
    )

    assert daily.update_interval == timedelta(hours=1)
    assert home.update_interval == timedelta(minutes=5)


async def test_home_requests_rolling_24_hours_and_all_metrics(hass, freezer):
    freezer.move_to("2026-10-29 12:00:00+00:00")
    client = make_client()
    coordinator = UltrahumanDataUpdateCoordinator(
        hass, client, device_type="home", mac_address=MAC
    )

    snapshot = await coordinator._async_update_data()

    call = client.async_get_home_metrics.call_args
    arguments = call.kwargs
    if call.args:
        arguments = (
            dict(zip(("mac_address", "metrics", "start_epoch", "end_epoch"), call.args))
            | arguments
        )
    assert arguments["mac_address"] == MAC
    assert set(arguments["metrics"]) == set(HOME_METRICS)
    assert arguments["end_epoch"] - arguments["start_epoch"] == 24 * 60 * 60
    assert arguments["end_epoch"] == 1793275200
    assert snapshot.device_name == "Bedroom"
    client.async_get_daily_metrics.assert_not_awaited()


async def test_account_timezone_corrects_initial_date_and_rolls_forward(hass, freezer):
    """At UTC midnight, the account can still be on the previous calendar day."""
    freezer.move_to("2026-10-29 01:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    client = make_client()
    client.async_get_daily_metrics.return_value = daily_payload(
        timezone="America/New_York"
    )
    coordinator = UltrahumanDataUpdateCoordinator(hass, client)

    await coordinator._async_update_data()

    assert client.async_get_daily_metrics.await_args_list[0].args == (
        date(2026, 10, 29),
    )
    assert client.async_get_daily_metrics.await_args_list[1].args == (
        date(2026, 10, 28),
    )

    freezer.move_to("2026-10-29 05:00:00+00:00")
    await coordinator._async_update_data()
    assert client.async_get_daily_metrics.await_args.args == (date(2026, 10, 29),)
    assert client.async_get_daily_metrics.await_count == 3


async def test_empty_day_replaces_previous_day_instead_of_retaining_readings(
    hass, freezer
):
    freezer.move_to("2026-10-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    client = make_client()
    client.async_get_daily_metrics.return_value = daily_payload(
        metrics={"2026-10-28": [{"type": "steps", "object": {"total": 1234}}]}
    )
    coordinator = UltrahumanDataUpdateCoordinator(hass, client)
    first = await coordinator._async_update_data()
    assert first.metrics["steps"].value == 1234

    freezer.move_to("2026-10-29 00:01:00+00:00")
    client.async_get_daily_metrics.return_value = daily_payload()
    second = await coordinator._async_update_data()
    assert "steps" not in second.metrics or second.metrics["steps"].value is None


async def test_authentication_failure_requests_reauthentication(hass):
    client = make_client()
    client.async_get_daily_metrics.side_effect = UltrahumanAuthError("expired")
    coordinator = UltrahumanDataUpdateCoordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_home_failure_does_not_prevent_daily_updates(hass):
    daily_client = make_client()
    home_client = make_client()
    home_client.async_get_home_metrics.side_effect = UltrahumanApiError("offline")
    daily = UltrahumanDataUpdateCoordinator(hass, daily_client)
    home = UltrahumanDataUpdateCoordinator(
        hass, home_client, device_type="home", mac_address=MAC
    )

    with pytest.raises(UpdateFailed):
        await home._async_update_data()
    assert await daily._async_update_data() is not None
    daily_client.async_get_daily_metrics.assert_awaited_once()


async def test_rate_limit_suppresses_requests_until_retry_delay(hass, freezer):
    freezer.move_to("2026-10-29 12:00:00+00:00")
    client = make_client()
    client.async_get_daily_metrics.side_effect = [
        UltrahumanRateLimitError(retry_after=90),
        daily_payload(),
    ]
    coordinator = UltrahumanDataUpdateCoordinator(hass, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert client.async_get_daily_metrics.await_count == 1

    freezer.tick(timedelta(seconds=91))
    assert await coordinator._async_update_data() is not None
    assert client.async_get_daily_metrics.await_count == 2
