"""Fully synthetic sparse responses and conflicting sleep representations."""

import json
from datetime import date
from pathlib import Path

import pytest

from custom_components.ultrahuman.parser import parse_daily_metrics

DAY = date(2024, 2, 12)
FIXTURE = Path(__file__).parent / "fixtures" / "daily_metrics_partial.json"


def sample():
    return json.loads(FIXTURE.read_text())


def metric_list(payload):
    return payload["data"]["metrics"][DAY.isoformat()]


def sleep_object(payload):
    return next(
        item["object"] for item in metric_list(payload) if item["type"] == "sleep"
    )


def test_synthetic_sleep_values_have_distinct_semantics():
    readings = parse_daily_metrics(sample(), DAY).metrics
    assert readings["sleep_score"].value == 87
    assert readings["total_sleep"].value == 420
    assert readings["time_in_bed"].value == 450
    assert readings["sleep_efficiency"].value == 93
    assert readings["deep_sleep"].value == 90
    assert readings["rem_sleep"].value == 110
    assert readings["light_sleep"].value == 220
    assert readings["light_sleep"].attributes["percentage"] == 52
    assert readings["light_sleep"].attributes["stage_percentage"] == 49
    assert readings["light_sleep"].attributes["stage_minutes"] == 210
    assert readings["restorative_sleep_percentage"].value == 64
    assert readings["restorative_sleep_percentage"].unit == "%"
    assert "restorative_sleep" not in readings
    assert readings["hr_drop_time"].value == "5:20 AM"
    assert readings["hr_drop_time"].unit is None
    assert "hr_drop" not in readings
    assert readings["movements"].value == 3
    assert readings["sleep_movements"].value == 11
    assert readings["morning_alertness_minutes"].value is None
    assert readings["morning_alertness_minutes"].unit == "min"
    assert readings["morning_alertness_minutes"].attributes["status"] == "pending"
    assert "morning_alertness" not in readings
    assert readings["inactive_time"].value == pytest.approx(83.25)
    assert readings["inactive_time"].unit is None
    assert readings["weekly_active_minutes"].value == 210
    assert readings["spo2"].value is None
    assert "glucose" not in readings
    assert readings["skin_temperature"].value == 31.25  # Explicit API value wins.
    assert all("last_synced_at" in reading.attributes for reading in readings.values())
    assert all(
        "insulin_insights" not in reading.attributes for reading in readings.values()
    )


def test_standalone_zero_null_and_pending_values_win_without_hiding_other_units():
    payload = sample()
    metric_list(payload).extend(
        {"type": kind, "object": obj}
        for kind, obj in (
            ("sleep_score", {"value": 0}),
            ("total_sleep", {"value": None, "unit": "seconds"}),
            ("sleep_efficiency", {"value": None}),
            ("temperature_deviation", {"value": 0}),
            ("full_sleep_cycles", {"value": None}),
            ("restorative_sleep", {"value": 78, "unit": "score"}),
            ("hr_drop", {"value": 12, "unit": "BPM"}),
        )
    )
    sleep = sleep_object(payload)
    sleep["morning_alertness"]["minutes"] = 10
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["sleep_score"].value == 0
    assert readings["total_sleep"].value is None
    assert readings["sleep_efficiency"].value is None
    assert readings["temperature_deviation"].value == 0
    assert readings["full_sleep_cycles"].value is None
    assert readings["morning_alertness_minutes"].value is None
    assert readings["morning_alertness_minutes"].attributes["status"] == "pending"
    assert readings["restorative_sleep"].value == 78
    assert readings["restorative_sleep_percentage"].value == 64
    assert readings["hr_drop"].value == 12
    assert readings["hr_drop_time"].value == "5:20 AM"


def test_details_container_accepts_the_same_structured_sleep_values():
    payload = sample()
    entry = next(item for item in metric_list(payload) if item["type"] == "sleep")
    entry["object"] = {"details": entry["object"]}
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["sleep_score"].value == 87
    assert readings["total_sleep"].value == 420
    assert readings["sleep_efficiency"].value == 93
    assert readings["sleep_score"].attributes["index_valid"] is True
    assert (
        readings["sleep_score"].attributes["bedtime_start"]
        == "2024-02-12T01:00:00+00:00"
    )
    assert readings["sleep_score"].attributes["awake_minutes"] == 30


def test_explicit_null_structured_sleep_fields_are_not_filled_from_quick_metrics():
    payload = sample()
    sleep = sleep_object(payload)
    sleep["total_sleep"] = {"minutes": None, "seconds": 25200}
    sleep["time_in_bed"] = None
    sleep["sleep_efficiency"] = {"percentage": None}
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["total_sleep"].value is None
    assert readings["time_in_bed"].value is None
    assert readings["sleep_efficiency"].value is None


def test_quick_metrics_and_stages_only_fill_absent_values_with_known_units():
    payload = sample()
    sleep = sleep_object(payload)
    for key in ("total_sleep", "time_in_bed", "sleep_efficiency", "light_sleep"):
        del sleep[key]
    payload["data"]["metrics"][DAY.isoformat()] = [
        item
        for item in metric_list(payload)
        if item["type"] not in ("avg_sleep_hrv", "sleep_rhr", "night_rhr")
    ]
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["total_sleep"].value == 420  # Quick value is 25200 seconds.
    assert readings["time_in_bed"].value == 450  # Quick value is 27000 seconds.
    assert readings["sleep_efficiency"].value == 93
    assert readings["light_sleep"].value == 210  # Stage value is 12600 seconds.
    assert readings["avg_sleep_hrv"].value == 63
    # The quick avg_hr metric is an average, not a resting heart rate.
    assert "sleep_rhr" not in readings
    assert "resting_heart_rate" not in readings
    sleep["quick_metrics"].append({"type": "sleep_rhr", "value": 0, "unit": "bpm"})
    assert parse_daily_metrics(payload, DAY).metrics["sleep_rhr"].value == 0


@pytest.mark.parametrize("invalid_sync", [None, True, "not-an-epoch", 1e100])
def test_invalid_last_sync_is_ignored_without_affecting_readings(invalid_sync):
    payload = sample()
    payload["data"]["last_synced_at"] = invalid_sync
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["heart_rate"].value == 72
    assert all(
        "last_synced_at" not in reading.attributes for reading in readings.values()
    )


@pytest.mark.parametrize("invalid_time", [None, 401, {}, "", " " * 4, "x" * 256])
def test_only_a_short_explicit_string_can_be_a_heart_rate_drop_time(invalid_time):
    payload = sample()
    sleep_object(payload)["hr_drop"] = {"time": invalid_time}
    assert parse_daily_metrics(payload, DAY).metrics["hr_drop_time"].value is None


def test_time_text_support_does_not_make_other_numeric_metrics_accept_strings():
    payload = sample()
    next(item["object"] for item in metric_list(payload) if item["type"] == "hr")[
        "last_reading"
    ] = "72"
    sleep = sleep_object(payload)
    sleep["hr_drop"]["time"] = " 5:20 AM "
    sleep["temperature_deviation"]["celsius"] = "-0.35"
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["heart_rate"].value is None
    assert readings["temperature_deviation"].value is None
    assert readings["hr_drop_time"].value == "5:20 AM"


def test_morning_alertness_with_an_unrelated_unit_is_not_a_score():
    payload = sample()
    entry = next(
        item for item in metric_list(payload) if item["type"] == "morning_alertness"
    )
    entry["object"] = {"value": 5, "unit": "hours"}
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["morning_alertness"].value is None


@pytest.mark.parametrize("value", [60, None])
def test_standalone_restorative_percentage_wins_even_when_pending(value):
    payload = sample()
    metric_list(payload).append(
        {
            "type": "restorative_sleep",
            "object": {"value": value, "unit": "%", "status": "pending"},
        }
    )
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["restorative_sleep_percentage"].value == value
    assert readings["restorative_sleep_percentage"].unit == "%"
    assert readings["restorative_sleep_percentage"].attributes["status"] == "pending"
    assert "restorative_sleep" not in readings


@pytest.mark.parametrize("source_unit", ["minutes", "time", "%"])
def test_numeric_drop_with_an_incompatible_unit_is_not_bpm(source_unit):
    payload = sample()
    metric_list(payload).append(
        {"type": "hr_drop", "object": {"value": 5, "unit": source_unit}}
    )
    readings = parse_daily_metrics(payload, DAY).metrics
    assert readings["hr_drop"].value is None
    assert readings["hr_drop_time"].value == "5:20 AM"
