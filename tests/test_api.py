"""Tests for the documented Ultrahuman HTTP contracts."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ultrahuman.api import (
    UltrahumanApiClient,
    UltrahumanApiError,
    UltrahumanAuthError,
    UltrahumanRateLimitError,
)

DAILY_URL = "https://partner.ultrahuman.com/api/v1/partner/daily_metrics"
HOME_URL = "https://partner.ultrahuman.com/api/v1/partner/home_metrics"


def make_session(payload=None, *, status=200, headers=None):
    """Build the aiohttp async context-manager interface without a network."""
    response = MagicMock(status=status, headers=headers or {})
    response.json = AsyncMock(return_value=payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = context
    return session, response


@pytest.mark.asyncio
async def test_daily_request_uses_current_endpoint_and_raw_token():
    """Personal tokens use the documented Authorization value, not Bearer."""
    payload = {"data": {"metrics": {}}, "error": None, "status": "ok"}
    session, _ = make_session(payload)
    client = UltrahumanApiClient(session, "secret-token", "person@example.com")

    assert await client.async_get_daily_metrics(date(2026, 10, 29)) == payload

    call = session.get.call_args
    assert call.args == (DAILY_URL,)
    assert call.kwargs["params"] == {
        "date": "2026-10-29",
        "email": "person@example.com",
    }
    assert call.kwargs["headers"] == {"Authorization": "secret-token"}
    assert call.kwargs["timeout"].total == 30


@pytest.mark.asyncio
async def test_home_request_sends_epoch_window_and_omits_empty_email():
    """Home requests specify one date-range format and an explicit metric list."""
    payload = {"data": {"metrics": []}, "error": None, "status": 200}
    session, _ = make_session(payload)
    client = UltrahumanApiClient(session, "secret-token", "")

    assert (
        await client.async_get_home_metrics(
            "AA:BB:CC:DD:EE:FF", ("pm25", "noise", "co2"), 100, 200
        )
        == payload
    )

    call = session.get.call_args
    assert call.args == (HOME_URL,)
    assert call.kwargs["params"] == {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "metrics": "pm25,noise,co2",
        "start_epoch": 100,
        "end_epoch": 200,
    }


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_authentication_statuses_raise_auth_error(status):
    session, _ = make_session({}, status=status)
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanAuthError):
        await client.async_get_daily_metrics(date(2026, 10, 29))


@pytest.mark.asyncio
async def test_rate_limit_retains_server_retry_delay():
    session, _ = make_session({}, status=429, headers={"Retry-After": "90"})
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanRateLimitError) as raised:
        await client.async_get_daily_metrics(date(2026, 10, 29))

    assert raised.value.retry_after == 90


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}, "error": "permission denied", "status": "ok"},
        {"data": {}, "error": {"message": "failure"}, "status": 200},
        [],
        None,
        {"data": []},
    ],
)
@pytest.mark.asyncio
async def test_application_errors_and_malformed_envelopes_are_rejected(payload):
    session, _ = make_session(payload)
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanApiError):
        await client.async_get_daily_metrics(date(2026, 10, 29))


@pytest.mark.parametrize("status", [400, 404, 500])
@pytest.mark.asyncio
async def test_other_http_failures_raise_api_error(status):
    session, _ = make_session({}, status=status)
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanApiError):
        await client.async_get_daily_metrics(date(2026, 10, 29))


@pytest.mark.parametrize("failure", [aiohttp.ClientError("offline"), TimeoutError()])
@pytest.mark.asyncio
async def test_transport_failures_are_wrapped(failure):
    session, _ = make_session({})
    session.get.side_effect = failure
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanApiError):
        await client.async_get_daily_metrics(date(2026, 10, 29))


@pytest.mark.asyncio
async def test_invalid_json_is_wrapped():
    session, response = make_session({})
    response.json.side_effect = ValueError("invalid json")
    client = UltrahumanApiClient(session, "secret-token")

    with pytest.raises(UltrahumanApiError):
        await client.async_get_daily_metrics(date(2026, 10, 29))
