"""Normalized readings shared by the daily and Home sensor platforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetricReading:
    """One sensor reading and its small, recorder-friendly metadata."""

    value: int | float | str | None
    unit: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricsSnapshot:
    """A complete update, rather than a patch to the previous day's data."""

    metrics: dict[str, MetricReading]
    timezone: str | None = None
    device_name: str | None = None
