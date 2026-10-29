"""Parse the documented UltraSignal responses without retaining timeseries."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from typing import Any

from .api import UltrahumanApiError
from .const import HOME_METRICS
from .models import MetricReading, MetricsSnapshot

# API type -> entity key, numeric field, normalized unit.
_DAILY_FIELDS: dict[str, tuple[str, str, str | None]] = {
    "hr": ("heart_rate", "last_reading", "bpm"),
    "night_rhr": ("resting_heart_rate", "avg", "bpm"),
    "hrv": ("hrv", "avg", "ms"),
    "temp": ("skin_temperature", "last_reading", "°C"),
    "steps": ("steps", "total", "steps"),
    "spo2": ("spo2", "avg", "%"),
    "metabolic_score": ("metabolic_score", "value", "score"),
    "glucose_variability": ("glucose_variability", "value", "%"),
    "average_glucose": ("average_glucose", "value", "mg/dL"),
    "hba1c": ("hba1c", "value", "%"),
    "time_in_target": ("time_in_target", "value", "%"),
    "recovery_index": ("recovery_index", "value", "score"),
    "movement_index": ("movement_index", "value", "score"),
    "vo2_max": ("vo2_max", "value", "mL/kg/min"),
    "sleep_rhr": ("sleep_rhr", "value", "bpm"),
    "avg_sleep_hrv": ("avg_sleep_hrv", "value", "ms"),
    "active_minutes": ("active_minutes", "value", "min"),
    "weekly_active_minutes": ("weekly_active_minutes", "value", "min"),
    "sleep_score": ("sleep_score", "value", "score"),
    "sleep_efficiency": ("sleep_efficiency", "value", "%"),
    "temperature_deviation": ("temperature_deviation", "value", "°C"),
    "hr_drop": ("hr_drop", "value", "bpm"),
    "restorative_sleep": ("restorative_sleep", "value", "score"),
    "movements": ("movements", "value", "count"),
    "full_sleep_cycles": ("full_sleep_cycles", "value", "cycles"),
    "tosses_and_turns": ("tosses_and_turns", "value", "count"),
    "average_body_temperature": ("average_body_temperature", "value", "°C"),
}
_SLEEP_DURATIONS = (
    "total_sleep",
    "time_in_bed",
    "rem_sleep",
    "deep_sleep",
    "light_sleep",
)
_HOME_DEFAULT_UNITS = {
    "hcho": "μg/m³",
    "co": "ppm",
    "co2": "ppm",
    "pm25": "μg/m³",
    "temp": "°C",
    "humidity": "%",
    "noise": "dB",
}


def _number(value: Any) -> int | float | None:
    """Reject boolean, string, NaN and infinite values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _timestamp(value: Any) -> str | None:
    """Return a valid Unix-seconds timestamp in UTC."""
    if (numeric := _number(value)) is None:
        return None
    try:
        return datetime.fromtimestamp(numeric, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _latest(
    points: Any,
    *,
    start_epoch: int | None = None,
    end_epoch: int | None = None,
) -> tuple[int | float | None, str | None]:
    """Select a timestamped sample, independently of ordering or summary fields."""
    if not isinstance(points, list):
        return None, None
    latest: tuple[int | float, int | float, str] | None = None
    for point in points:
        if not isinstance(point, dict):
            continue
        value = _number(point.get("value"))
        epoch = _number(point.get("timestamp"))
        timestamp = _timestamp(epoch)
        if value is None or epoch is None or timestamp is None:
            continue
        if start_epoch is not None and epoch < start_epoch:
            continue
        if end_epoch is not None and epoch > end_epoch:
            continue
        if latest is None or epoch >= latest[0]:
            latest = (epoch, value, timestamp)
    return (latest[1], latest[2]) if latest else (None, None)


def _data(response: Any) -> dict[str, Any]:
    """Require an actual response envelope, while accepting empty metric sets."""
    if not isinstance(response, dict) or response.get("error") is not None:
        raise UltrahumanApiError("Invalid metrics response or API error")
    data = response.get("data")
    if not isinstance(data, dict):
        raise UltrahumanApiError("Metrics response is missing its data object")
    return data


def _unit(value: Any) -> str | None:
    """Normalize spelling variants of documented units, not their meaning."""
    if not isinstance(value, str) or not value.strip():
        return None
    # Home Assistant uses Greek mu (μ), rather than the visually identical micro sign (µ).
    unit = value.strip().replace("µ", "μ").replace("m3", "m³").replace("m2", "m²")
    return {"BPM": "bpm", "celsius": "°C", "C": "°C", "percent": "%"}.get(unit, unit)


def parse_daily_metrics(response: dict[str, Any], query_date: date) -> MetricsSnapshot:
    """Read sparse standalone metrics and both published/live sleep structures."""
    data = _data(response)
    dates = data.get("metrics")
    if not isinstance(dates, dict):
        raise UltrahumanApiError("Daily metrics response must be keyed by date")
    metric_list = dates.get(query_date.isoformat(), [])
    if not isinstance(metric_list, list):
        raise UltrahumanApiError("Daily metrics for the requested date must be a list")

    objects: dict[str, dict[str, Any]] = {}
    for item in metric_list:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise UltrahumanApiError("Invalid daily metric record")
        obj = item.get("object")
        if obj is None:
            continue
        if not isinstance(obj, dict):
            raise UltrahumanApiError("Invalid daily metric object")
        objects[item["type"]] = obj

    source_date = query_date.isoformat()
    last_synced_at = _timestamp(data.get("last_synced_at"))

    def attributes(obj: dict[str, Any] | None = None) -> dict[str, Any]:
        attrs: dict[str, Any] = {"source_date": source_date}
        if last_synced_at is not None:
            attrs["last_synced_at"] = last_synced_at
        if obj is not None:
            _, timestamp = _latest(obj.get("values"))
            if timestamp is not None:
                attrs["reading_timestamp"] = timestamp
            if isinstance(obj.get("status"), str):
                attrs["status"] = obj["status"]
        return attrs

    parsed: dict[str, MetricReading] = {}
    for api_type, (key, field, unit) in _DAILY_FIELDS.items():
        obj = objects.get(api_type)
        if obj is not None:
            value = _number(obj.get(field))
            source_unit = _unit(obj.get("unit"))
            if api_type == "restorative_sleep":
                if source_unit == "%":
                    key, unit = "restorative_sleep_percentage", "%"
                elif source_unit not in (None, "score"):
                    value = None
            elif api_type == "hr_drop" and source_unit not in (None, "bpm"):
                value = None
            parsed[key] = MetricReading(value, unit, attributes(obj))

    for key in _SLEEP_DURATIONS:
        obj = objects.get(key)
        if obj is None:
            continue
        value = _number(obj.get("value"))
        if value is not None and _unit(obj.get("unit")) not in ("min", "minutes"):
            value /= 60
        attrs = attributes(obj)
        if (percentage := _number(obj.get("percentage"))) is not None:
            attrs["percentage"] = percentage
        parsed[key] = MetricReading(value, "min", attrs)

    if (obj := objects.get("inactive_time")) is not None:
        # The live response does not specify a unit; its magnitude is not evidence.
        parsed["inactive_time"] = MetricReading(
            _number(obj.get("value")), _unit(obj.get("unit")), attributes(obj)
        )
    if (obj := objects.get("morning_alertness")) is not None:
        unit = _unit(obj.get("unit"))
        if unit in ("min", "minute", "minutes"):
            key, unit = "morning_alertness_minutes", "min"
        else:
            key = "morning_alertness"
        # A source with an unrelated explicit unit cannot be relabelled as a score.
        value = _number(obj.get("value")) if unit in (None, "score", "min") else None
        parsed[key] = MetricReading(
            value, "min" if unit == "min" else "score", attributes(obj)
        )
    if (obj := objects.get("glucose")) is not None:
        value, timestamp = _latest(obj.get("values"))
        attrs = attributes(obj)
        if timestamp is not None:
            attrs["reading_timestamp"] = timestamp
        parsed["glucose"] = MetricReading(value, "mg/dL", attrs)

    sleep = objects.get("sleep", {})
    details = sleep.get("details")
    if not isinstance(details, dict):
        details = {}

    def sleep_field(key: str) -> tuple[bool, Any]:
        # Explicit null in the live object is missing/pending data, not permission
        # to silently substitute a second, possibly older representation.
        for source in (sleep, details):
            if key in source:
                return True, source[key]
        return False, None

    def nested_reading(key: str, field: str, unit: str | None) -> None:
        if key in parsed:
            return
        present, obj = sleep_field(key)
        if present:
            parsed[key] = MetricReading(
                _number(obj.get(field)) if isinstance(obj, dict) else None,
                unit,
                attributes(obj if isinstance(obj, dict) else None),
            )

    nested_reading("sleep_score", "score", "score")
    if sleep and "sleep_score" not in parsed:
        _, score = sleep_field("score")
        parsed["sleep_score"] = MetricReading(_number(score), "score", attributes())
    nested_reading("sleep_efficiency", "percentage", "%")
    nested_reading("temperature_deviation", "celsius", "°C")
    nested_reading("full_sleep_cycles", "cycles", "cycles")
    nested_reading("tosses_and_turns", "count", "count")
    nested_reading("average_body_temperature", "celsius", "°C")
    if "spo2" not in parsed:
        present, obj = sleep_field("spo2")
        if present:
            # Preserve explicit value:null rather than substituting an average.
            field = "value" if isinstance(obj, dict) and "value" in obj else "avg"
            parsed["spo2"] = MetricReading(
                _number(obj.get(field)) if isinstance(obj, dict) else None,
                "%",
                attributes(),
            )

    for key in _SLEEP_DURATIONS:
        if key in parsed:
            continue
        present, obj = sleep_field(key)
        if not present:
            continue
        obj = obj if isinstance(obj, dict) else {}
        if "minutes" in obj:
            value = _number(obj["minutes"])
        else:
            seconds = _number(obj.get("seconds"))
            value = seconds / 60 if seconds is not None else None
        attrs = attributes(obj)
        if (percentage := _number(obj.get("percentage"))) is not None:
            attrs["percentage"] = percentage
        parsed[key] = MetricReading(value, "min", attrs)

    # These fields are distinct from standalone scores, BPM drops and movements.
    for source_key, key, field, unit in (
        ("movements", "sleep_movements", "count", "count"),
        ("restorative_sleep", "restorative_sleep_percentage", "percentage", "%"),
        ("morning_alertness", "morning_alertness_minutes", "minutes", "min"),
    ):
        present, obj = sleep_field(source_key)
        if key not in parsed and present:
            parsed[key] = MetricReading(
                _number(obj.get(field)) if isinstance(obj, dict) else None,
                unit,
                attributes(obj if isinstance(obj, dict) else None),
            )
    present, obj = sleep_field("hr_drop")
    if present:
        text = obj.get("time") if isinstance(obj, dict) else None
        text = text.strip() if isinstance(text, str) else None
        parsed["hr_drop_time"] = MetricReading(
            text if text and len(text) <= 255 else None, None, attributes()
        )

    # Typed quick metrics are a last fallback. Tiled/trend values intentionally
    # remain unused: their units differ even when their type names are identical.
    _, quick_metrics = sleep_field("quick_metrics")
    quick_fields = {
        "total_sleep": ("total_sleep", "min"),
        "time_in_bed": ("time_in_bed", "min"),
        "sleep_efic": ("sleep_efficiency", "%"),
        "avg_hrv": ("avg_sleep_hrv", "ms"),
        "sleep_rhr": ("sleep_rhr", "bpm"),
        "night_rhr": ("resting_heart_rate", "bpm"),
    }
    if isinstance(quick_metrics, list):
        for metric in quick_metrics:
            if not isinstance(metric, dict) or not isinstance(metric.get("type"), str):
                continue
            field = quick_fields.get(metric["type"])
            if field is None or field[0] in parsed:
                continue
            key, unit = field
            value = _number(metric.get("value"))
            if (
                key in ("total_sleep", "time_in_bed")
                and value is not None
                and _unit(metric.get("unit")) not in ("min", "minutes")
            ):
                value /= 60
            parsed[key] = MetricReading(value, unit, attributes(metric))

    # Percentages for the card are kept as a coherent set from sleep_stages.
    # Detailed per-stage percentages remain separately available as percentage.
    _, stages = sleep_field("sleep_stages")
    awake: dict[str, Any] = {}
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict) or not isinstance(stage.get("type"), str):
                continue
            key = stage["type"]
            percentage = _number(stage.get("percentage"))
            seconds = _number(stage.get("stage_time"))
            minutes = seconds / 60 if seconds is not None else None
            if key == "awake":
                if percentage is not None:
                    awake["awake_percentage"] = percentage
                if minutes is not None:
                    awake["awake_minutes"] = minutes
                continue
            if key not in _SLEEP_DURATIONS:
                continue
            reading = parsed.get(key)
            if reading is None and "stage_time" in stage:
                reading = MetricReading(minutes, "min", attributes())
            if reading is None:
                continue
            attrs = dict(reading.attributes)
            if percentage is not None:
                attrs["stage_percentage"] = percentage
                attrs.setdefault("percentage", percentage)
            if minutes is not None:
                attrs["stage_minutes"] = minutes
            parsed[key] = MetricReading(reading.value, reading.unit, attrs)

    if (score := parsed.get("sleep_score")) is not None:
        attrs = {**score.attributes, **awake}
        for key in ("index_valid", "is_processing_new_data"):
            _, value = sleep_field(key)
            if isinstance(value, bool):
                attrs[key] = value
        for key in ("bedtime_start", "bedtime_end"):
            _, value = sleep_field(key)
            if (timestamp := _timestamp(value)) is not None:
                attrs[key] = timestamp
        parsed["sleep_score"] = MetricReading(score.value, score.unit, attrs)

    timezone = data.get("latest_time_zone")
    return MetricsSnapshot(parsed, timezone if isinstance(timezone, str) else None)


def _mac(value: Any) -> str | None:
    """Compare valid hardware addresses regardless of delimiters or casing."""
    if not isinstance(value, str):
        return None
    compact = re.sub("[:-]", "", value).lower()
    return compact if re.fullmatch(r"[0-9a-f]{12}", compact) else None


def parse_home_metrics(
    response: dict[str, Any],
    mac_address: str,
    start_epoch: int,
    end_epoch: int,
) -> MetricsSnapshot:
    """Read the newest sample from each requested Home environmental metric."""
    data = _data(response)
    home = data.get("home")
    metrics = data.get("metrics")
    if not isinstance(home, dict) or not isinstance(metrics, list):
        raise UltrahumanApiError(
            "Home response must contain a home object and metric list"
        )
    requested_mac = _mac(mac_address)
    if requested_mac is None or _mac(home.get("mac_address")) != requested_mac:
        raise UltrahumanApiError("Home response belongs to a different device")
    date_range = data.get("date_range", {})
    if not isinstance(date_range, dict):
        raise UltrahumanApiError("Invalid Home date range")

    parsed: dict[str, MetricReading] = {}
    for item in metrics:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise UltrahumanApiError("Invalid Home metric record")
        key = item["type"]
        if key not in HOME_METRICS:
            continue
        points = item.get("data")
        if points is not None and not isinstance(points, list):
            raise UltrahumanApiError("Home metric samples must be a list")
        value, timestamp = _latest(points, start_epoch=start_epoch, end_epoch=end_epoch)
        attrs: dict[str, Any] = {"start_epoch": start_epoch, "end_epoch": end_epoch}
        if timestamp is not None:
            attrs["reading_timestamp"] = timestamp
        source_unit = item.get("unit")
        unit = _unit(source_unit) or _HOME_DEFAULT_UNITS.get(key)
        if isinstance(source_unit, str):
            attrs["source_unit"] = source_unit
        scale = 1
        if key in ("uva", "uvb", "uvc") and unit in ("mw/cm²", "mW/cm²"):
            # The Home API uses mW/cm²; HA irradiance sensors accept W/m².
            unit = "W/m²"
            scale = 10
            if value is not None:
                value = _number(value * scale)
        summary = item.get("summary")
        if isinstance(summary, dict):
            for summary_key in ("count", "average", "min", "max"):
                if (summary_value := _number(summary.get(summary_key))) is not None:
                    if summary_key != "count":
                        summary_value = _number(summary_value * scale)
                    if summary_value is not None:
                        attrs[summary_key] = summary_value
            if any(key in attrs for key in ("average", "min", "max")):
                # HA may convert the displayed state (e.g. °F to °C), but attributes
                # remain in the sensor's native unit and must identify that unit.
                attrs["summary_unit"] = unit
        room_type = home.get("room_type")
        if isinstance(room_type, str):
            attrs["room_type"] = room_type
        parsed[key] = MetricReading(value, unit, attrs)

    timezone = date_range.get("timezone")
    name = home.get("name")
    return MetricsSnapshot(
        parsed,
        timezone if isinstance(timezone, str) else None,
        name if isinstance(name, str) and name.strip() else None,
    )
