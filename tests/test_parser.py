"""Contract tests against published examples and synthetic unit responses."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from custom_components.ultrahuman.api import UltrahumanApiError
from custom_components.ultrahuman.parser import parse_daily_metrics, parse_home_metrics

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2025, 5, 1)
MAC = "AA:BB:CC:DD:EE:FF"
HOME_START = 1755023400
HOME_END = 1755109799


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_daily_documented_example():
    """Scalar sleep data wins over inconsistent overlapping aggregate values."""
    snapshot = parse_daily_metrics(fixture("daily_metrics.json"), DAY)
    metrics = snapshot.metrics
    assert len(metrics) == 33
    assert snapshot.timezone == "America/New_York"
    assert metrics["sleep_score"].value == 85
    assert metrics["sleep_score"].attributes["is_processing_new_data"] is False
    assert metrics["sleep_score"].attributes["bedtime_start"].endswith("+00:00")
    assert metrics["total_sleep"].value == 425
    assert metrics["time_in_bed"].value == 480
    assert metrics["deep_sleep"].value == 56
    assert metrics["rem_sleep"].value == 85
    assert metrics["light_sleep"].value == 308.25
    assert metrics["deep_sleep"].attributes["percentage"] == 13.19
    assert metrics["restorative_sleep"].value == 78
    assert metrics["restorative_sleep"].unit == "score"
    assert metrics["spo2"].value == 97.5
    assert metrics["heart_rate"].value == 63
    assert metrics["resting_heart_rate"].value == 48
    assert metrics["sleep_rhr"].value == 50
    assert metrics["hrv"].value == 45
    assert metrics["avg_sleep_hrv"].value == 55
    assert metrics["temperature_deviation"].value == -0.2
    assert metrics["active_minutes"].value == 45
    assert all("values" not in reading.attributes for reading in metrics.values())


def test_daily_missing_date_does_not_use_previous_day():
    snapshot = parse_daily_metrics(fixture("daily_metrics.json"), date(2025, 5, 2))
    assert snapshot.metrics == {}
    assert (
        parse_daily_metrics({"data": {"metrics": {}}, "error": None}, DAY).metrics == {}
    )


def test_daily_null_zero_and_sleep_fallbacks():
    payload = {
        "data": {
            "metrics": {
                DAY.isoformat(): [
                    {"type": "steps", "object": {"total": 0}},
                    {"type": "hr", "object": None},
                    {"type": "temperature_deviation", "object": {"value": 0}},
                    {
                        "type": "sleep",
                        "object": {
                            "score": 0,
                            "details": {
                                "quick_metrics": [
                                    {"type": "total_sleep", "value": 3600},
                                    {"type": "sleep_efic", "value": 0},
                                    {"type": [], "value": 12},
                                ]
                            },
                        },
                    },
                ]
            }
        }
    }
    metrics = parse_daily_metrics(payload, DAY).metrics
    assert metrics["steps"].value == 0
    assert "heart_rate" not in metrics
    assert metrics["temperature_deviation"].value == 0
    assert metrics["sleep_score"].value == 0
    assert metrics["total_sleep"].value == 60
    assert metrics["sleep_efficiency"].value == 0


def test_latest_glucose_requires_valid_timestamp_and_finite_number():
    payload = {
        "data": {
            "metrics": {
                DAY.isoformat(): [
                    {
                        "type": "glucose",
                        "object": {
                            "values": [
                                {"timestamp": 1746064800, "value": 0},
                                {"timestamp": 1746061200, "value": 90},
                                {"timestamp": 1746065000, "value": float("nan")},
                                {"timestamp": 1746066000, "value": True},
                                {"timestamp": "later", "value": 200},
                                {"timestamp": 1e100, "value": 250},
                            ]
                        },
                    }
                ]
            }
        }
    }
    reading = parse_daily_metrics(payload, DAY).metrics["glucose"]
    assert reading.value == 0
    assert reading.unit == "mg/dL"
    assert reading.attributes["reading_timestamp"] == "2025-05-01T02:00:00+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {"metric_data": []}},
        {"data": {"metrics": []}},
        {"data": {"metrics": {DAY.isoformat(): {}}}},
        {"data": {"metrics": {DAY.isoformat(): [None]}}},
        {"data": {"metrics": {DAY.isoformat(): [{"type": "hr", "object": []}]}}},
        {"data": {"metrics": {}}, "error": "denied"},
    ],
)
def test_daily_malformed_envelopes_fail(payload):
    with pytest.raises(UltrahumanApiError):
        parse_daily_metrics(payload, DAY)


def test_home_documented_example():
    snapshot = parse_home_metrics(
        fixture("home_metrics.json"), MAC, HOME_START, HOME_END
    )
    assert snapshot.device_name == "Living"
    assert snapshot.timezone == "Asia/Calcutta"
    assert snapshot.metrics["pm25"].value == 4
    assert snapshot.metrics["pm25"].unit == "μg/m³"
    assert snapshot.metrics["noise"].value == 35
    attrs = snapshot.metrics["pm25"].attributes
    assert attrs["average"] == 9.91
    assert attrs["count"] == 208
    assert attrs["min"] == 1
    assert attrs["max"] == 56
    assert attrs["room_type"] == "bedroom"
    assert attrs["start_epoch"] == HOME_START
    assert attrs["end_epoch"] == HOME_END
    assert "data" not in attrs


def test_home_latest_sample_not_average_or_array_order():
    payload = fixture("home_metrics.json")
    payload["data"]["home"]["mac_address"] = "aa-bb-cc-dd-ee-ff"
    payload["data"]["metrics"] = [
        {
            "type": "co2",
            "unit": "ppm",
            "data": [
                {"timestamp": HOME_START + 10, "value": 500},
                {"timestamp": HOME_END - 1, "value": 0},
                {"timestamp": HOME_START + 1, "value": 400},
                {"timestamp": HOME_END, "value": float("inf")},
                {"timestamp": HOME_END, "value": False},
                {"timestamp": HOME_END + 1, "value": 999},
                {"timestamp": HOME_START - 1, "value": 999},
            ],
            "summary": {"average": 425},
        }
    ]
    reading = parse_home_metrics(payload, MAC, HOME_START, HOME_END).metrics["co2"]
    assert reading.value == 0
    assert reading.attributes["average"] == 425


def test_home_sparse_data_and_undocumented_units():
    payload = fixture("home_metrics.json")
    payload["data"]["metrics"] = [
        {
            "type": "red",
            "unit": "device units",
            "data": [{"timestamp": HOME_START, "value": 3}],
        },
        {
            "type": "mic",
            "data": [{"timestamp": HOME_START, "value": {"audio": "blob"}}],
        },
        {"type": "temp", "unit": "°C", "data": None},
    ]
    metrics = parse_home_metrics(payload, MAC, HOME_START, HOME_END).metrics
    assert metrics["red"].value == 3
    assert metrics["red"].unit == "device units"
    assert metrics["mic"].value is None
    assert metrics["mic"].unit is None
    assert metrics["temp"].value is None
    payload["data"]["metrics"] = []
    assert parse_home_metrics(payload, MAC, HOME_START, HOME_END).metrics == {}


def test_synthetic_home_response_preserves_units_and_all_available_readings():
    """Exercise unit variants, missing mic and zero light/UV with fabricated data."""
    payload = fixture("home_metrics_units.json")
    window = payload["data"]["date_range"]
    snapshot = parse_home_metrics(
        payload, MAC, window["start_epoch"], window["end_epoch"]
    )
    expected = {
        "hcho": (0.025, "mg/m³"),
        "co": (0.4, "ppm"),
        "co2": (720, "ppm"),
        "pm1": (5, "μg/m³"),
        "pm10": (12, "μg/m³"),
        "pm25": (8, "μg/m³"),
        "voc": (0.35, "mg/m³"),
        "temp": (77, "°F"),
        "humidity": (45, "%"),
        "noise": (39, "dB"),
        "uva": (0, "W/m²"),
        "uvb": (0, "W/m²"),
        "uvc": (0, "W/m²"),
        "red": (0, "lux"),
        "green": (0, "lux"),
        "blue": (0, "lux"),
        "ir": (0, "lux"),
        "aqi": (17, None),
    }
    assert snapshot.device_name == "Test Room"
    assert snapshot.timezone == "Etc/UTC"
    assert set(snapshot.metrics) == set(expected)
    for key, (value, unit) in expected.items():
        reading = snapshot.metrics[key]
        assert reading.value == pytest.approx(value)
        assert reading.unit == unit
        assert reading.attributes["reading_timestamp"] == "2024-02-12T02:00:00+00:00"
        assert reading.attributes["summary_unit"] == unit
        assert reading.attributes["count"] == 12
        assert "data" not in reading.attributes
    assert snapshot.metrics["temp"].attributes["average"] == 75.2
    assert snapshot.metrics["temp"].attributes["source_unit"] == "°F"
    assert snapshot.metrics["hcho"].attributes["source_unit"] == "mg/m³"
    assert snapshot.metrics["uva"].attributes["source_unit"] == "mw/cm²"
    assert snapshot.metrics["aqi"].attributes["source_unit"] == ""


@pytest.mark.parametrize(
    ("key", "source_unit"),
    [("uva", "mw/cm²"), ("uvb", "mW/cm²"), ("uvc", "mW/cm2")],
)
def test_home_uv_converts_nonzero_values_and_summary_but_not_count(key, source_unit):
    payload = fixture("home_metrics.json")
    payload["data"]["metrics"] = [
        {
            "type": key,
            "unit": source_unit,
            "data": [{"timestamp": HOME_START, "value": 0.25}],
            "summary": {"count": 5, "average": 0.1, "min": 0, "max": 0.5},
        }
    ]
    reading = parse_home_metrics(payload, MAC, HOME_START, HOME_END).metrics[key]
    assert reading.value == pytest.approx(2.5)
    assert reading.unit == "W/m²"
    assert reading.attributes["source_unit"] == source_unit
    assert reading.attributes["summary_unit"] == "W/m²"
    assert reading.attributes["average"] == pytest.approx(1)
    assert reading.attributes["min"] == 0
    assert reading.attributes["max"] == pytest.approx(5)
    assert reading.attributes["count"] == 5


def test_home_unknown_uv_units_are_not_reinterpreted():
    payload = fixture("home_metrics.json")
    payload["data"]["metrics"] = [
        {
            "type": "uva",
            "unit": "device units",
            "data": [{"timestamp": HOME_START, "value": 0.25}],
            "summary": {"count": 5, "average": 0.1},
        }
    ]
    reading = parse_home_metrics(payload, MAC, HOME_START, HOME_END).metrics["uva"]
    assert reading.value == 0.25
    assert reading.unit == "device units"
    assert reading.attributes["average"] == 0.1
    assert reading.attributes["summary_unit"] == "device units"


@pytest.mark.parametrize(
    "change",
    [
        {"home": None},
        {"home": {"mac_address": "00:00:00:00:00:00"}},
        {"metrics": {}},
        {"metrics": [None]},
        {"metrics": [{"type": "co2", "data": {}}]},
        {"date_range": []},
    ],
)
def test_home_rejects_wrong_device_or_malformed_data(change):
    payload = fixture("home_metrics.json")
    payload["data"].update(deepcopy(change))
    with pytest.raises(UltrahumanApiError):
        parse_home_metrics(payload, MAC, HOME_START, HOME_END)
