"""API client for the Ultrahuman personal-token Partner APIs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any

import aiohttp

from .const import API_DAILY_METRICS_ENDPOINT, API_HOME_METRICS_ENDPOINT


class UltrahumanApiError(Exception):
    """Exception for transport errors or invalid Ultrahuman responses."""


class UltrahumanAuthError(UltrahumanApiError):
    """Exception for authentication errors."""


class UltrahumanRateLimitError(UltrahumanApiError):
    """Exception for rate limiting, optionally including a retry delay."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Ultrahuman API rate limit reached")
        self.retry_after = retry_after


def _retry_delay(header: str | None) -> float | None:
    """Parse either form of Retry-After without trusting malformed headers."""
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        try:
            retry_date = parsedate_to_datetime(header)
            if retry_date.tzinfo is None:
                retry_date = retry_date.replace(tzinfo=UTC)
            seconds = (retry_date - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, seconds) if isfinite(seconds) else None


class UltrahumanApiClient:
    """Client using the raw personal token in the Authorization header."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        email: str | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._email = email.strip() if email else None

    async def async_get_daily_metrics(self, query_date: date) -> dict[str, Any]:
        """Fetch one day in the account's timezone."""
        return await self._request(
            API_DAILY_METRICS_ENDPOINT, {"date": query_date.isoformat()}
        )

    async def async_get_home_metrics(
        self,
        mac_address: str,
        metrics: Sequence[str],
        start_epoch: int,
        end_epoch: int,
    ) -> dict[str, Any]:
        """Fetch a Home device's metrics over an epoch window."""
        return await self._request(
            API_HOME_METRICS_ENDPOINT,
            {
                "mac_address": mac_address,
                "metrics": ",".join(metrics),
                "start_epoch": start_epoch,
                "end_epoch": end_epoch,
            },
        )

    async def _request(
        self, endpoint: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        if self._email:
            params["email"] = self._email
        try:
            async with self._session.get(
                endpoint,
                params=params,
                headers={"Authorization": self._api_key},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in (401, 403):
                    raise UltrahumanAuthError("Invalid API token or access denied")
                if response.status == 429:
                    raise UltrahumanRateLimitError(
                        _retry_delay(response.headers.get("Retry-After"))
                    )
                if response.status != 200:
                    raise UltrahumanApiError(
                        f"API request failed with status {response.status}"
                    )
                payload = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            # aiohttp errors may contain the email URL; keep their text out of logs.
            raise UltrahumanApiError(
                "Unable to read the Ultrahuman API response"
            ) from err

        if not isinstance(payload, dict):
            raise UltrahumanApiError("Invalid API response: expected an object")
        if payload.get("error") is not None:
            raise UltrahumanApiError("Ultrahuman API returned an error")
        if not isinstance(payload.get("data"), dict):
            raise UltrahumanApiError("Invalid API response: missing data object")
        return payload
