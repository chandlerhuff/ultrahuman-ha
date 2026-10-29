"""Exercise fully synthetic partial daily responses through Home Assistant."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import METRIC_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultrahuman.const import DOMAIN
from custom_components.ultrahuman.sensor import DAILY_SENSOR_DESCRIPTIONS

FIXTURE = Path(__file__).parent / "fixtures" / "daily_metrics_partial.json"
DAY = "2024-02-12"


def _entity_id(registry, entry, key):
    return registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


@pytest.fixture
async def daily_sample_entry(hass, freezer):
    """Use fabricated readings while exercising the real parser and platform."""
    payload = json.loads(FIXTURE.read_text())
    freezer.move_to(datetime.fromtimestamp(payload["data"]["last_synced_at"] + 60, UTC))
    hass.config.units = METRIC_SYSTEM
    client = MagicMock()
    client.async_get_daily_metrics = AsyncMock(return_value=payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="daily:person@example.com",
        data={
            "device_type": "daily",
            "api_key": "test-token",
            "email": "person@example.com",
        },
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.ultrahuman.async_setup", return_value=True),
        patch("custom_components.ultrahuman.UltrahumanApiClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, payload, client, er.async_get(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_partial_response_publishes_available_values_and_keeps_missing_unknown(
    hass, daily_sample_entry, caplog
):
    entry, payload, _, registry = daily_sample_entry
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(registered) == 39
    assert len(payload["data"]["metrics"][DAY]) == 16

    expected_values = {
        "heart_rate": 72,
        "skin_temperature": 31.25,
        "hrv": 48,
        "steps": 2468,
        "resting_heart_rate": 54,
        "avg_sleep_hrv": 63,
        "sleep_rhr": 57,
        "recovery_index": 81,
        "movement_index": 74,
        "active_minutes": 0,
        "weekly_active_minutes": 210,
        "inactive_time": 83.25,
        "movements": 3,
        "sleep_movements": 11,
        "vo2_max": 42,
        "sleep_score": 87,
        "total_sleep": 420,
        "time_in_bed": 450,
        "sleep_efficiency": 93,
        "deep_sleep": 90,
        "rem_sleep": 110,
        "light_sleep": 220,
        "temperature_deviation": -0.35,
        "full_sleep_cycles": 5,
        "tosses_and_turns": 6,
        "average_body_temperature": 34.75,
        "restorative_sleep_percentage": 64,
    }
    for key, value in expected_values.items():
        state = hass.states.get(_entity_id(registry, entry, key))
        assert state is not None
        assert float(state.state) == pytest.approx(value), key
        assert state.attributes["source_date"] == DAY
        assert state.attributes["timezone"] == "Etc/UTC"

    for key in (
        "glucose",
        "average_glucose",
        "metabolic_score",
        "spo2",
        "restorative_sleep",
        "hr_drop",
        "morning_alertness",
        "morning_alertness_minutes",
    ):
        assert hass.states.get(_entity_id(registry, entry, key)).state == "unknown", key

    pending = hass.states.get(_entity_id(registry, entry, "morning_alertness_minutes"))
    assert pending.attributes["status"] == "pending"
    assert pending.attributes["unit_of_measurement"] == "min"
    assert pending.attributes["device_class"] == "duration"
    inactive = hass.states.get(_entity_id(registry, entry, "inactive_time"))
    assert "unit_of_measurement" not in inactive.attributes
    assert "state_class" not in inactive.attributes
    assert "device_class" not in inactive.attributes
    drop_time = hass.states.get(_entity_id(registry, entry, "hr_drop_time"))
    assert drop_time.state == "5:20 AM"
    assert "unit_of_measurement" not in drop_time.attributes
    assert "state_class" not in drop_time.attributes
    restorative = hass.states.get(
        _entity_id(registry, entry, "restorative_sleep_percentage")
    )
    assert restorative.attributes["unit_of_measurement"] == "%"

    score = hass.states.get(_entity_id(registry, entry, "sleep_score"))
    assert score.attributes["index_valid"] is True
    assert score.attributes["awake_percentage"] == 7
    assert score.attributes["bedtime_start"] == "2024-02-12T01:00:00+00:00"
    assert score.attributes["bedtime_end"] == "2024-02-12T08:30:00+00:00"
    assert score.attributes["last_synced_at"] == "2024-02-12T09:00:00+00:00"
    light = hass.states.get(_entity_id(registry, entry, "light_sleep"))
    assert light.attributes["percentage"] == 52
    assert light.attributes["stage_percentage"] == 49
    assert not any(
        "is not a valid unit" in record.getMessage()
        for record in caplog.get_records("setup") + caplog.records
    )


async def test_pending_minutes_can_become_available_without_creating_a_score(
    hass, daily_sample_entry
):
    entry, payload, _, registry = daily_sample_entry
    morning = next(
        metric["object"]
        for metric in payload["data"]["metrics"][DAY]
        if metric["type"] == "morning_alertness"
    )
    assert morning["value"] is None
    morning["value"] = 12
    morning["status"] = "available"
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(registry, entry, "morning_alertness_minutes"))
    assert float(state.state) == 12
    assert state.attributes["unit_of_measurement"] == "min"
    assert state.attributes["status"] == "available"
    assert (
        hass.states.get(_entity_id(registry, entry, "morning_alertness")).state
        == "unknown"
    )


async def test_partial_values_clear_on_account_date_rollover(
    hass, daily_sample_entry, freezer
):
    entry, _, client, registry = daily_sample_entry
    # Keep yesterday's payload to prove that the requested account date is used.
    freezer.move_to("2024-02-13 01:00:00+00:00")
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    assert client.async_get_daily_metrics.await_args.args[0].isoformat() == "2024-02-13"
    for description in DAILY_SENSOR_DESCRIPTIONS:
        entity_id = _entity_id(registry, entry, description.key)
        assert hass.states.get(entity_id).state == "unknown", description.key
