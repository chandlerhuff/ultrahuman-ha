"""Sensor metadata, source units and identity behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.ultrahuman.const import (
    DEVICE_TYPE_DAILY,
    DEVICE_TYPE_HOME,
    DOMAIN,
)
from custom_components.ultrahuman.models import MetricReading, MetricsSnapshot
from custom_components.ultrahuman.sensor import (
    DAILY_SENSOR_DESCRIPTIONS,
    HOME_SENSOR_DESCRIPTIONS,
    UltrahumanSensor,
)


def sensor(
    key,
    reading=None,
    *,
    device_type=DEVICE_TYPE_DAILY,
    mac="AA:BB:CC:DD:EE:FF",
    entry_id="daily-account",
    email="person@example.com",
):
    descriptions = (
        HOME_SENSOR_DESCRIPTIONS
        if device_type == DEVICE_TYPE_HOME
        else DAILY_SENSOR_DESCRIPTIONS
    )
    coordinator = SimpleNamespace(
        device_type=device_type,
        mac_address=mac,
        data=MetricsSnapshot(
            {key: reading} if reading is not None else {}, "America/New_York", "Living"
        ),
        last_update_success=True,
    )
    entry = SimpleNamespace(entry_id=entry_id, data={"email": email})
    return UltrahumanSensor(
        coordinator, next(d for d in descriptions if d.key == key), entry
    )


def test_daily_zero_units_and_attributes():
    entity = sensor(
        "temperature_deviation", MetricReading(0, "°C", {"source_date": "2025-05-01"})
    )
    assert entity.native_value == 0
    assert entity.native_unit_of_measurement == "°C"
    assert entity.device_class != SensorDeviceClass.TEMPERATURE
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert entity.extra_state_attributes == {
        "source_date": "2025-05-01",
        "timezone": "America/New_York",
    }
    assert entity.suggested_object_id == "daily-account_temperature_deviation"
    assert entity.unique_id == "daily-account_temperature_deviation"


def test_daily_unit_and_masked_device_name():
    entity = sensor("restorative_sleep", MetricReading(78, "score"))
    assert entity.native_unit_of_measurement == "score"
    assert entity.device_info["name"] == "Ultrahuman Ring (p*****@example.com)"
    assert entity.device_info["identifiers"] == {(DOMAIN, "daily-account")}
    assert (
        sensor("steps", MetricReading(0, "steps")).state_class
        == SensorStateClass.TOTAL_INCREASING
    )


def test_unknown_reading_and_coordinator_failure():
    entity = sensor("heart_rate")
    assert entity.native_value is None
    assert entity.extra_state_attributes is None
    entity.coordinator.last_update_success = False
    assert not entity.available


def test_home_identity_units_and_class():
    entity = sensor("pm25", MetricReading(0, "μg/m³"), device_type=DEVICE_TYPE_HOME)
    assert entity.native_value == 0
    assert entity.native_unit_of_measurement == "μg/m³"
    assert entity.device_class == SensorDeviceClass.PM25
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert entity.unique_id == "home_aabbccddeeff_pm25"
    assert entity.suggested_object_id == "aabbccddeeff_pm25"
    assert entity.device_info["name"] == "Ultrahuman Home Living"
    assert entity.device_info["identifiers"] == {(DOMAIN, "home_aabbccddeeff")}
    other = sensor(
        "pm25",
        MetricReading(1, "μg/m³"),
        device_type=DEVICE_TYPE_HOME,
        mac="00-11-22-33-44-55",
    )
    assert other.unique_id != entity.unique_id
    assert other.device_info["identifiers"] != entity.device_info["identifiers"]


def test_same_name_home_devices_have_distinct_shared_metric_prefixes():
    first = [
        sensor(description.key, device_type=DEVICE_TYPE_HOME)
        for description in HOME_SENSOR_DESCRIPTIONS
    ]
    second = [
        sensor(
            description.key,
            device_type=DEVICE_TYPE_HOME,
            mac="00:11:22:33:44:55",
        )
        for description in HOME_SENSOR_DESCRIPTIONS
    ]
    assert first[0].device_info["name"] == second[0].device_info["name"]
    for entity, description in zip(first, HOME_SENSOR_DESCRIPTIONS, strict=True):
        assert entity.suggested_object_id == f"aabbccddeeff_{description.key}"
    for entity, description in zip(second, HOME_SENSOR_DESCRIPTIONS, strict=True):
        assert entity.suggested_object_id == f"001122334455_{description.key}"
    assert {entity.suggested_object_id for entity in first}.isdisjoint(
        entity.suggested_object_id for entity in second
    )


def test_colliding_masked_email_names_have_distinct_metric_prefixes():
    first = sensor("hrv", entry_id="account-one", email="person@example.com")
    second = sensor("hrv", entry_id="account-two", email="paulxx@example.com")
    assert first.device_info["name"] == second.device_info["name"]
    assert first.suggested_object_id == "account-one_hrv"
    assert second.suggested_object_id == "account-two_hrv"
    assert first.suggested_object_id != second.suggested_object_id


def test_unknown_home_units_get_no_guessed_class_or_statistics():
    entity = sensor(
        "voc", MetricReading(9, "proprietary"), device_type=DEVICE_TYPE_HOME
    )
    assert entity.native_value == 9
    assert entity.native_unit_of_measurement == "proprietary"
    assert entity.device_class is None
    assert entity.state_class is None
    assert len(DAILY_SENSOR_DESCRIPTIONS) == 39
    assert len(HOME_SENSOR_DESCRIPTIONS) == 19
    assert {
        d.key for d in HOME_SENSOR_DESCRIPTIONS if not d.entity_registry_enabled_default
    } == {"mic", "uva", "uvb", "uvc", "red", "green", "blue", "ir"}


def test_home_temperature_unit_changes_preserve_statistics_unit():
    entity = sensor("temp", MetricReading(20, "°C"), device_type=DEVICE_TYPE_HOME)
    assert entity.native_value == 20
    assert entity.device_class == SensorDeviceClass.TEMPERATURE
    entity.coordinator.data = MetricsSnapshot({"temp": MetricReading(68, "°F")})
    assert entity.native_value == pytest.approx(20)
    assert entity.native_unit_of_measurement == "°C"
    assert "unexpected_source_unit" not in entity.extra_state_attributes


@pytest.mark.parametrize(
    "initial_unit,initial_value,source_unit,source_value",
    [("°F", 70.7, "°C", 21.5), ("°C", 21.5, "°F", 70.7), ("K", 294.65, "°C", 21.5)],
)
def test_home_temperature_converts_reading_and_summary(
    initial_unit, initial_value, source_unit, source_value
):
    entity = sensor(
        "temp", MetricReading(initial_value, initial_unit), device_type=DEVICE_TYPE_HOME
    )
    assert entity.native_value == pytest.approx(initial_value)
    assert entity.device_class == SensorDeviceClass.TEMPERATURE
    entity.coordinator.data = MetricsSnapshot(
        {
            "temp": MetricReading(
                source_value,
                source_unit,
                {
                    "source_unit": source_unit,
                    "summary_unit": source_unit,
                    "average": source_value,
                    "min": source_value,
                    "max": source_value,
                    "count": 87,
                },
            )
        }
    )
    assert entity.native_value == pytest.approx(initial_value)
    assert entity.native_unit_of_measurement == initial_unit
    attrs = entity.extra_state_attributes
    assert attrs["source_unit"] == source_unit
    assert attrs["summary_unit"] == initial_unit
    assert attrs["average"] == pytest.approx(initial_value)
    assert attrs["min"] == pytest.approx(initial_value)
    assert attrs["max"] == pytest.approx(initial_value)
    assert attrs["count"] == 87
    assert "unexpected_source_unit" not in attrs


@pytest.mark.parametrize("key", ["hcho", "voc", "pm1", "pm10", "pm25"])
def test_home_mass_concentration_converts_summary_and_keeps_count(key):
    entity = sensor(key, MetricReading(10, "μg/m³"), device_type=DEVICE_TYPE_HOME)
    entity.coordinator.data = MetricsSnapshot(
        {
            key: MetricReading(
                0.01,
                "mg/m³",
                {
                    "source_unit": "mg/m³",
                    "summary_unit": "mg/m³",
                    "average": 0.01,
                    "min": 0,
                    "max": 0.02,
                    "count": 87,
                },
            )
        }
    )
    assert entity.native_value == pytest.approx(10)
    assert entity.native_unit_of_measurement == "μg/m³"
    attrs = entity.extra_state_attributes
    assert attrs["source_unit"] == "mg/m³"
    assert attrs["summary_unit"] == "μg/m³"
    assert attrs["average"] == pytest.approx(10)
    assert attrs["min"] == 0
    assert attrs["max"] == pytest.approx(20)
    assert attrs["count"] == 87
    assert "unexpected_source_unit" not in attrs


def test_home_formaldehyde_milligram_unit_supports_statistics():
    entity = sensor("hcho", MetricReading(0.01, "mg/m³"), device_type=DEVICE_TYPE_HOME)
    assert entity.native_value == 0.01
    assert entity.native_unit_of_measurement == "mg/m³"
    assert entity.device_class is None
    assert entity.state_class == SensorStateClass.MEASUREMENT


@pytest.mark.parametrize(
    "key,initial_unit,new_unit",
    [("temp", "°F", "proprietary"), ("voc", "mg/m³", "ppm"), ("co2", "ppm", "mg/m³")],
)
def test_home_incompatible_source_unit_is_unknown(key, initial_unit, new_unit):
    entity = sensor(key, MetricReading(1, initial_unit), device_type=DEVICE_TYPE_HOME)
    entity.coordinator.data = MetricsSnapshot({key: MetricReading(2, new_unit)})
    assert entity.native_value is None
    assert entity.native_unit_of_measurement == initial_unit
    assert entity.extra_state_attributes["unexpected_source_unit"] == new_unit


@pytest.mark.parametrize(
    "key,unit,expected_class",
    [
        ("uva", "W/m²", SensorDeviceClass.IRRADIANCE),
        ("uvb", "W/m²", SensorDeviceClass.IRRADIANCE),
        ("uvc", "W/m²", SensorDeviceClass.IRRADIANCE),
        ("red", "lux", SensorDeviceClass.ILLUMINANCE),
        ("green", "lux", SensorDeviceClass.ILLUMINANCE),
        ("blue", "lux", SensorDeviceClass.ILLUMINANCE),
        ("ir", "lux", SensorDeviceClass.ILLUMINANCE),
    ],
)
def test_home_optical_measurements_have_compatible_class_and_statistics(
    key, unit, expected_class
):
    entity = sensor(key, MetricReading(0, unit), device_type=DEVICE_TYPE_HOME)
    assert entity.native_value == 0
    assert entity.device_class == expected_class
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert not entity.entity_description.entity_registry_enabled_default


@pytest.mark.parametrize("key", ["uva", "red", "mic"])
def test_home_optical_unknown_units_remain_generic(key):
    entity = sensor(key, MetricReading(0, "proprietary"), device_type=DEVICE_TYPE_HOME)
    assert entity.native_value == 0
    assert entity.device_class is None
    assert entity.state_class is None


def test_home_units_can_arrive_after_empty_initial_window(monkeypatch):
    entity = sensor("co2", device_type=DEVICE_TYPE_HOME)
    assert entity.native_value is None
    assert entity.state_class is None
    entity.coordinator.data = MetricsSnapshot({"co2": MetricReading(450, "ppm")})
    write_state = Mock()
    monkeypatch.setattr(entity, "async_write_ha_state", write_state)
    entity._handle_coordinator_update()
    assert entity.native_value == 450
    assert entity.native_unit_of_measurement == "ppm"
    assert entity.device_class == SensorDeviceClass.CO2
    assert entity.state_class == SensorStateClass.MEASUREMENT
    write_state.assert_called_once()


@pytest.mark.parametrize(
    "key,unit,expected_class",
    [
        ("voc", "ppb", SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS),
        ("voc", "μg/m³", SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS),
        ("noise", "dB", SensorDeviceClass.SOUND_PRESSURE),
        ("aqi", None, SensorDeviceClass.AQI),
    ],
)
def test_home_classes_match_returned_units(key, unit, expected_class):
    entity = sensor(key, MetricReading(12, unit), device_type=DEVICE_TYPE_HOME)
    assert entity.device_class == expected_class


@pytest.mark.parametrize("key", ["weekly_active_minutes", "morning_alertness_minutes"])
def test_daily_duration_variants_use_minutes_without_replacing_scores(key):
    entity = sensor(key, MetricReading(0, "min"))
    assert entity.native_value == 0
    assert entity.native_unit_of_measurement == "min"
    assert entity.device_class == SensorDeviceClass.DURATION
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert (
        sensor(
            "morning_alertness", MetricReading(82, "score")
        ).native_unit_of_measurement
        == "score"
    )


def test_daily_movement_and_restorative_quantities_remain_distinct():
    movements = sensor("movements", MetricReading(3, "count"))
    sleep_movements = sensor("sleep_movements", MetricReading(11, "count"))
    restorative_score = sensor("restorative_sleep", MetricReading(78, "score"))
    restorative_percentage = sensor(
        "restorative_sleep_percentage", MetricReading(64, "%")
    )
    assert movements.native_value == 3
    assert sleep_movements.native_value == 11
    assert movements.unique_id != sleep_movements.unique_id
    assert restorative_score.native_unit_of_measurement == "score"
    assert restorative_percentage.native_unit_of_measurement == "%"
    assert restorative_percentage.native_value == 64


def test_daily_hr_drop_time_is_text_without_numeric_statistics():
    entity = sensor("hr_drop_time", MetricReading("5:20 AM"))
    assert entity.native_value == "5:20 AM"
    assert entity.native_unit_of_measurement is None
    assert entity.device_class is None
    assert entity.state_class is None
    assert entity.suggested_display_precision is None
    assert (
        sensor("hr_drop", MetricReading(12, "bpm")).native_unit_of_measurement == "bpm"
    )


def test_daily_inactive_time_does_not_invent_a_unit_or_statistics():
    entity = sensor("inactive_time", MetricReading(83.25))
    assert entity.native_value == pytest.approx(83.25)
    assert entity.native_unit_of_measurement is None
    assert entity.device_class is None
    assert entity.state_class is None
    entity.coordinator.data = MetricsSnapshot(
        {"inactive_time": MetricReading(84, "min")}
    )
    assert entity.native_unit_of_measurement == "min"
    assert entity.state_class is None


def test_daily_pending_duration_preserves_status_without_publishing_zero():
    entity = sensor(
        "morning_alertness_minutes", MetricReading(None, "min", {"status": "pending"})
    )
    assert entity.native_value is None
    assert entity.extra_state_attributes["status"] == "pending"
