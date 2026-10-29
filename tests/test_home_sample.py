"""Run synthetic unit-response regressions through real Home Assistant entities."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import UnitOfDensity
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import METRIC_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultrahuman.const import DOMAIN

MAC = "AA:BB:CC:DD:EE:FF"
FIXTURE = Path(__file__).parent / "fixtures" / "home_metrics_units.json"


def _entity_id(registry, key):
    return registry.async_get_entity_id("sensor", DOMAIN, f"home_aabbccddeeff_{key}")


def _metric(payload, key):
    return next(
        metric for metric in payload["data"]["metrics"] if metric["type"] == key
    )


@pytest.fixture
async def sample_entry(hass, freezer):
    """Use the real parser, coordinator, registry and sensor platform offline."""
    payload = json.loads(FIXTURE.read_text())
    latest_epoch = max(
        point["timestamp"]
        for metric in payload["data"]["metrics"]
        for point in metric["data"]
    )
    freezer.move_to(datetime.fromtimestamp(latest_epoch + 60, UTC))
    hass.config.units = METRIC_SYSTEM
    client = MagicMock()
    client.async_get_home_metrics = AsyncMock(return_value=payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "test-token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.ultrahuman.async_setup", return_value=True),
        patch("custom_components.ultrahuman.UltrahumanApiClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, payload, er.async_get(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_synthetic_home_response_uses_supported_units_and_handles_omitted_mic(
    hass, sample_entry, caplog
):
    """Fahrenheit, mg/m³, unitless AQI and missing mic are accepted together."""
    _, payload, registry = sample_entry
    assert len(payload["data"]["metrics"]) == 18

    temperature = hass.states.get(_entity_id(registry, "temp"))
    assert float(temperature.state) == pytest.approx(25)
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["device_class"] == "temperature"
    assert temperature.attributes["source_unit"] == "°F"
    assert temperature.attributes["summary_unit"] == "°F"
    assert temperature.attributes["average"] == pytest.approx(75.2)
    assert temperature.attributes["timezone"] == "Etc/UTC"

    hcho = hass.states.get(_entity_id(registry, "hcho"))
    assert float(hcho.state) == pytest.approx(0.025)
    assert hcho.attributes["unit_of_measurement"] == "mg/m³"
    assert hcho.attributes["state_class"] == "measurement"
    assert "device_class" not in hcho.attributes

    voc = hass.states.get(_entity_id(registry, "voc"))
    assert float(voc.state) == pytest.approx(0.35)
    assert voc.attributes["unit_of_measurement"] == "mg/m³"
    assert voc.attributes["device_class"] == "volatile_organic_compounds"
    assert voc.attributes["state_class"] == "measurement"
    assert hass.states.get(_entity_id(registry, "co2")).state == "720"
    for key in ("pm1", "pm10", "pm25"):
        state = hass.states.get(_entity_id(registry, key))
        assert (
            state.attributes["unit_of_measurement"]
            == UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
        )
        assert state.attributes["device_class"] == key
        assert state.attributes["state_class"] == "measurement"
    aqi = hass.states.get(_entity_id(registry, "aqi"))
    assert float(aqi.state) == 17
    assert aqi.attributes["device_class"] == "aqi"
    assert "unit_of_measurement" not in aqi.attributes

    mic = registry.async_get(_entity_id(registry, "mic"))
    assert mic.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(mic.entity_id) is None
    assert "mic" not in hass.data[DOMAIN][sample_entry[0].entry_id].data.metrics
    assert not any(
        "is not a valid unit" in record.getMessage()
        for record in caplog.get_records("setup") + caplog.records
    )


async def test_source_unit_changes_keep_device_readings_and_summaries_valid(
    hass, sample_entry
):
    """An app unit preference change cannot strand otherwise compatible sensors."""
    entry, payload, registry = sample_entry
    temperature = _metric(payload, "temp")
    temperature["unit"] = "°C"
    for point in temperature["data"]:
        point["value"] = (point["value"] - 32) * 5 / 9
    for key in ("average", "min", "max"):
        temperature["summary"][key] = (temperature["summary"][key] - 32) * 5 / 9

    hcho = _metric(payload, "hcho")
    hcho["unit"] = "µg/m³"
    for point in hcho["data"]:
        point["value"] *= 1000
    for key in ("average", "min", "max"):
        hcho["summary"][key] *= 1000

    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(registry, "temp"))
    assert float(state.state) == pytest.approx(25)
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["source_unit"] == "°C"
    # Summary attributes have the entity's stable native unit; HA separately
    # converts its displayed temperature state to the user's chosen unit.
    assert state.attributes["summary_unit"] == "°F"
    assert state.attributes["average"] == pytest.approx(75.2)
    assert state.attributes["count"] == 12
    assert "unexpected_source_unit" not in state.attributes

    state = hass.states.get(_entity_id(registry, "hcho"))
    assert float(state.state) == pytest.approx(0.025)
    assert state.attributes["unit_of_measurement"] == "mg/m³"
    assert state.attributes["source_unit"] == "µg/m³"
    assert state.attributes["summary_unit"] == "mg/m³"
    assert state.attributes["average"] == pytest.approx(0.025)
    assert state.attributes["count"] == 12
    assert "unexpected_source_unit" not in state.attributes


async def test_enabled_optical_and_uv_sensors_use_supported_ha_units(
    hass, sample_entry
):
    """Optional channels retain zeros and gain matching classes/statistics."""
    entry, _, registry = sample_entry
    channels = ("uva", "uvb", "uvc", "red", "green", "blue", "ir")
    assert await hass.config_entries.async_unload(entry.entry_id)
    for key in channels:
        entity_id = _entity_id(registry, key)
        assert registry.async_get(entity_id).disabled_by is not None
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for key in channels:
        state = hass.states.get(_entity_id(registry, key))
        assert float(state.state) == 0
        assert state.attributes["state_class"] == "measurement"
        if key.startswith("uv"):
            assert state.attributes["unit_of_measurement"] == "W/m²"
            assert state.attributes["device_class"] == "irradiance"
            assert state.attributes["source_unit"] == "mw/cm²"
            assert state.attributes["summary_unit"] == "W/m²"
        else:
            assert state.attributes["unit_of_measurement"] == "lux"
            assert state.attributes["device_class"] == "illuminance"
