"""Independent daily-health and Home-device update coordinators."""

from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    UltrahumanApiClient,
    UltrahumanApiError,
    UltrahumanAuthError,
    UltrahumanRateLimitError,
)
from .const import (
    DEFAULT_HOME_UPDATE_INTERVAL,
    DEVICE_TYPE_DAILY,
    DEVICE_TYPE_HOME,
    DOMAIN,
    HOME_METRICS,
)
from .models import MetricsSnapshot
from .parser import parse_daily_metrics, parse_home_metrics

_LOGGER = logging.getLogger(__name__)


class UltrahumanDataUpdateCoordinator(DataUpdateCoordinator[MetricsSnapshot]):
    """Fetch a single source so failures never affect sibling entries."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: UltrahumanApiClient,
        device_type: str = DEVICE_TYPE_DAILY,
        mac_address: str | None = None,
        update_interval_minutes: int = DEFAULT_HOME_UPDATE_INTERVAL,
        *,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_type}",
            config_entry=config_entry,
            update_interval=timedelta(
                minutes=update_interval_minutes
                if device_type == DEVICE_TYPE_HOME
                else 60
            ),
        )
        self.client = client
        self.device_type = device_type
        self.mac_address = mac_address
        self._account_timezone: ZoneInfo | None = None
        self._rate_limit_until = None

    async def _async_update_data(self) -> MetricsSnapshot:
        """Read the configured source, respecting server rate-limit delays."""
        now = dt_util.utcnow()
        if self._rate_limit_until is not None and now < self._rate_limit_until:
            raise UpdateFailed("Ultrahuman API is rate limited; retry later")
        try:
            if self.device_type == DEVICE_TYPE_HOME:
                if self.mac_address is None:
                    raise UltrahumanApiError("Home MAC address is required")
                end_epoch = int(now.timestamp())
                start_epoch = end_epoch - 24 * 60 * 60
                response = await self.client.async_get_home_metrics(
                    self.mac_address, HOME_METRICS, start_epoch, end_epoch
                )
                snapshot = parse_home_metrics(
                    response, self.mac_address, start_epoch, end_epoch
                )
            else:
                query_date = (
                    dt_util.now()
                    .astimezone(self._account_timezone or dt_util.DEFAULT_TIME_ZONE)
                    .date()
                )
                response = await self.client.async_get_daily_metrics(query_date)
                snapshot = parse_daily_metrics(response, query_date)
                if snapshot.timezone:
                    try:
                        self._account_timezone = ZoneInfo(snapshot.timezone)
                    except (ValueError, ZoneInfoNotFoundError):
                        _LOGGER.debug("API returned an unrecognized account timezone")
                    else:
                        corrected_date = (
                            dt_util.now().astimezone(self._account_timezone).date()
                        )
                        if corrected_date != query_date:
                            response = await self.client.async_get_daily_metrics(
                                corrected_date
                            )
                            snapshot = parse_daily_metrics(response, corrected_date)
        except UltrahumanAuthError as err:
            raise ConfigEntryAuthFailed("Ultrahuman authentication failed") from err
        except UltrahumanRateLimitError as err:
            delay = max(1, err.retry_after if err.retry_after is not None else 60)
            self._rate_limit_until = dt_util.utcnow() + timedelta(seconds=delay)
            raise UpdateFailed("Ultrahuman API rate limit reached") from err
        except UltrahumanApiError as err:
            raise UpdateFailed(str(err)) from err
        self._rate_limit_until = None
        return snapshot
