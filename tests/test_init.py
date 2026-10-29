"""Entry setup, independent devices, and live options updates."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import Platform
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ultrahuman import async_setup_entry, async_unload_entry
from custom_components.ultrahuman.const import DOMAIN

MAC = "AA:BB:CC:DD:EE:FF"


async def test_home_setup_and_options_update_only_its_coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.update_interval = timedelta(minutes=5)
    coordinator.device_type = "home"
    unrelated_coordinator = MagicMock()
    unrelated_coordinator.async_request_refresh = AsyncMock()
    hass.data[DOMAIN] = {"other-device": unrelated_coordinator}

    with (
        patch(
            "custom_components.ultrahuman.UltrahumanDataUpdateCoordinator",
            return_value=coordinator,
        ) as factory,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", return_value=None
        ) as forward,
    ):
        assert await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN][entry.entry_id] is coordinator
    assert factory.call_args.kwargs["device_type"] == "home"
    assert factory.call_args.kwargs["mac_address"] == MAC
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    forward.assert_awaited_once_with(entry, [Platform.SENSOR])

    hass.config_entries.async_update_entry(entry, options={"update_interval": 9})
    await hass.async_block_till_done()

    assert coordinator.update_interval == timedelta(minutes=9)
    coordinator.async_request_refresh.assert_awaited_once()
    unrelated_coordinator.async_request_refresh.assert_not_awaited()


async def test_unload_removes_only_selected_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    other = MagicMock()
    hass.data[DOMAIN] = {entry.entry_id: MagicMock(), "other-device": other}

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry)

    assert entry.entry_id not in hass.data[DOMAIN]
    assert hass.data[DOMAIN]["other-device"] is other


async def test_real_setup_registers_daily_and_home_sensors_on_separate_devices(hass):
    """Run real entry/platform setup, not just the forwarding callback."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util

    from custom_components.ultrahuman.sensor import (
        DAILY_SENSOR_DESCRIPTIONS,
        HOME_SENSOR_DESCRIPTIONS,
    )

    today = dt_util.now().date().isoformat()
    timestamp = int(dt_util.utcnow().timestamp()) - 1
    client = MagicMock()
    client.async_get_daily_metrics = AsyncMock(
        return_value={
            "data": {
                "latest_time_zone": "UTC",
                "metrics": {
                    today: [
                        {"type": "sleep_score", "object": {"value": 84}},
                        {"type": "steps", "object": {"total": 1234}},
                        {"type": "total_sleep", "object": {"value": 21600}},
                    ]
                },
            },
            "error": None,
        }
    )
    client.async_get_home_metrics = AsyncMock(
        return_value={
            "data": {
                "home": {"mac_address": MAC, "name": "Bedroom"},
                "date_range": {"timezone": "UTC"},
                "metrics": [
                    {
                        "type": "co2",
                        "unit": "ppm",
                        "data": [{"timestamp": timestamp, "value": 650}],
                    },
                    {
                        "type": "temp",
                        "unit": "°C",
                        "data": [{"timestamp": timestamp, "value": 22}],
                    },
                ],
            },
            "error": None,
        }
    )
    daily = MockConfigEntry(
        domain=DOMAIN,
        unique_id="daily:person@example.com",
        data={
            "device_type": "daily",
            "api_key": "token",
            "email": "person@example.com",
        },
    )
    home = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    daily.add_to_hass(hass)

    # Static HTTP path registration is outside the entry/sensor behavior under test.
    with (
        patch("custom_components.ultrahuman.async_setup", return_value=True),
        patch("custom_components.ultrahuman.UltrahumanApiClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(daily.entry_id)
        home.add_to_hass(hass)
        assert await hass.config_entries.async_setup(home.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        daily_entities = er.async_entries_for_config_entry(registry, daily.entry_id)
        home_entities = er.async_entries_for_config_entry(registry, home.entry_id)
        assert len(daily_entities) == 39
        assert len(home_entities) == 19
        assert {entity.disabled_by is not None for entity in daily_entities} == {False}
        disabled_home = {
            entity.unique_id.rsplit("_", 1)[-1]
            for entity in home_entities
            if entity.disabled_by is not None
        }
        assert disabled_home == {
            "mic",
            "uva",
            "uvb",
            "uvc",
            "red",
            "green",
            "blue",
            "ir",
        }

        daily_by_key = {
            description.key: next(
                entity
                for entity in daily_entities
                if entity.unique_id == f"{daily.entry_id}_{description.key}"
            )
            for description in DAILY_SENSOR_DESCRIPTIONS
        }
        home_by_key = {
            description.key: next(
                entity
                for entity in home_entities
                if entity.unique_id == f"home_aabbccddeeff_{description.key}"
            )
            for description in HOME_SENSOR_DESCRIPTIONS
        }
        for key, entity in {**daily_by_key, **home_by_key}.items():
            assert entity.entity_id.endswith(f"_{key}")
        assert hass.states.get(daily_by_key["sleep_score"].entity_id).state == "84"
        total_sleep = hass.states.get(daily_by_key["total_sleep"].entity_id)
        assert total_sleep.state == "360.0"
        assert total_sleep.attributes["unit_of_measurement"] == "min"
        assert hass.states.get(home_by_key["co2"].entity_id).state == "650"
        assert hass.states.get(home_by_key["mic"].entity_id) is None

        devices = dr.async_get(hass)
        daily_device = devices.async_get(daily_by_key["steps"].device_id)
        home_device = devices.async_get(home_by_key["co2"].device_id)
        assert daily_device is not None and home_device is not None
        assert daily_device.id != home_device.id
        assert home_device.name == "Ultrahuman Home Bedroom"

        client.async_get_daily_metrics.reset_mock()
        client.async_get_home_metrics.reset_mock()
        hass.config_entries.async_update_entry(home, options={"update_interval": 8})
        await hass.async_block_till_done()
        assert hass.data[DOMAIN][home.entry_id].update_interval == timedelta(minutes=8)
        client.async_get_home_metrics.assert_awaited_once()
        client.async_get_daily_metrics.assert_not_awaited()

        assert await hass.config_entries.async_unload(home.entry_id)
        assert await hass.config_entries.async_unload(daily.entry_id)


async def test_home_empty_window_accepts_later_readings_without_wrong_units(hass):
    """Units and device classes can arrive after an initially empty setup."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util

    response = {
        "data": {
            "home": {"mac_address": MAC, "name": "Bedroom"},
            "date_range": {"timezone": "UTC"},
            "metrics": [],
        },
        "error": None,
    }
    client = MagicMock()
    client.async_get_home_metrics = AsyncMock(return_value=response)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"home:{MAC}",
        data={"device_type": "home", "api_key": "token", "mac_address": MAC},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.ultrahuman.async_setup", return_value=True),
        patch("custom_components.ultrahuman.UltrahumanApiClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "home_aabbccddeeff_temp"
        )
        assert hass.states.get(entity_id).state == "unknown"
        assert "unit_of_measurement" not in hass.states.get(entity_id).attributes

        response["data"]["metrics"] = [
            {
                "type": "temp",
                "unit": "°C",
                "data": [
                    {"timestamp": int(dt_util.utcnow().timestamp()) - 1, "value": 22}
                ],
            }
        ]
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state.state == "22"
        assert state.attributes["unit_of_measurement"] == "°C"
        assert state.attributes["device_class"] == "temperature"

        # Equivalent API units are converted into the existing native unit.
        response["data"]["metrics"][0]["unit"] = "°F"
        response["data"]["metrics"][0]["data"][0]["value"] = 71.6
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert float(state.state) == 22
        assert state.attributes["unit_of_measurement"] == "°C"
        assert "unexpected_source_unit" not in state.attributes

        # An incompatible unit still cannot silently relabel existing statistics.
        response["data"]["metrics"][0]["unit"] = "device units"
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state.state == "unknown"
        assert state.attributes["unit_of_measurement"] == "°C"
        assert state.attributes["unexpected_source_unit"] == "device units"
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_same_name_home_devices_have_distinct_common_card_prefixes(hass):
    """MAC discrimination belongs before the metric suffix, never after it."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.ultrahuman.sensor import HOME_SENSOR_DESCRIPTIONS

    async def response(mac_address, metrics, start_epoch, end_epoch):
        return {
            "data": {
                "home": {"mac_address": mac_address, "name": "Bedroom"},
                "date_range": {"timezone": "UTC"},
                "metrics": [],
            },
            "error": None,
        }

    client = MagicMock()
    client.async_get_home_metrics = AsyncMock(side_effect=response)
    entries = [
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"home:{mac}",
            data={"device_type": "home", "api_key": "token", "mac_address": mac},
        )
        for mac in (MAC, "11:22:33:44:55:66")
    ]
    with (
        patch("custom_components.ultrahuman.async_setup", return_value=True),
        patch("custom_components.ultrahuman.UltrahumanApiClient", return_value=client),
    ):
        prefixes = []
        registry = er.async_get(hass)
        for entry in entries:
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            entities = er.async_entries_for_config_entry(registry, entry.entry_id)
            assert len(entities) == 19
            compact_mac = entry.data["mac_address"].replace(":", "").lower()
            metric_prefixes = set()
            for description in HOME_SENSOR_DESCRIPTIONS:
                entity = next(
                    entity
                    for entity in entities
                    if entity.unique_id == f"home_{compact_mac}_{description.key}"
                )
                suffix = f"_{description.key}"
                assert entity.entity_id.endswith(suffix)
                metric_prefixes.add(entity.entity_id[: -len(suffix)])
            assert len(metric_prefixes) == 1
            prefix = metric_prefixes.pop()
            assert compact_mac in prefix
            prefixes.append(prefix)
        assert prefixes[0] != prefixes[1]
        for entry in entries:
            assert await hass.config_entries.async_unload(entry.entry_id)
