"""Daily health and Home environmental sensors for Ultrahuman."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.unit_conversion import (
    MassVolumeConcentrationConverter,
    TemperatureConverter,
)

from .const import CONF_EMAIL, DEVICE_TYPE_HOME, DOMAIN
from .coordinator import UltrahumanDataUpdateCoordinator
from .models import MetricReading


@dataclass(frozen=True, kw_only=True)
class UltrahumanSensorEntityDescription(SensorEntityDescription):
    """A normalized metric, whose display name is supplied by translations."""


def _description(
    key: str,
    unit: str | None = None,
    device_class: SensorDeviceClass | None = None,
    *,
    icon: str | None = None,
    enabled: bool = True,
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    precision: int | None = 2,
) -> UltrahumanSensorEntityDescription:
    return UltrahumanSensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        suggested_display_precision=precision,
        icon=icon,
        entity_registry_enabled_default=enabled,
    )


DAILY_SENSOR_DESCRIPTIONS = (
    _description("sleep_score", "score", icon="mdi:sleep"),
    _description("total_sleep", "min", SensorDeviceClass.DURATION),
    _description("sleep_efficiency", "%", icon="mdi:sleep"),
    _description("deep_sleep", "min", SensorDeviceClass.DURATION),
    _description("rem_sleep", "min", SensorDeviceClass.DURATION),
    _description("light_sleep", "min", SensorDeviceClass.DURATION),
    _description("restorative_sleep", "score", icon="mdi:heart-pulse"),
    _description("spo2", "%", icon="mdi:water-percent"),
    _description("heart_rate", "bpm", icon="mdi:heart-pulse"),
    _description("resting_heart_rate", "bpm", icon="mdi:heart"),
    _description("hrv", "ms", icon="mdi:heart-flash"),
    _description("skin_temperature", "°C", SensorDeviceClass.TEMPERATURE),
    _description(
        "steps", "steps", icon="mdi:walk", state_class=SensorStateClass.TOTAL_INCREASING
    ),
    _description("metabolic_score", "score", icon="mdi:chart-arc"),
    _description("glucose_variability", "%", icon="mdi:chart-line-variant"),
    _description("average_glucose", "mg/dL", icon="mdi:diabetes"),
    _description("hba1c", "%", icon="mdi:blood-bag"),
    _description("time_in_target", "%", icon="mdi:target"),
    _description("recovery_index", "score", icon="mdi:meditation"),
    _description("movement_index", "score", icon="mdi:run"),
    _description("vo2_max", "mL/kg/min", icon="mdi:lungs"),
    _description("glucose", "mg/dL", icon="mdi:diabetes"),
    _description("sleep_rhr", "bpm", icon="mdi:heart"),
    _description("avg_sleep_hrv", "ms", icon="mdi:heart-flash"),
    _description("active_minutes", "min", SensorDeviceClass.DURATION),
    _description("time_in_bed", "min", SensorDeviceClass.DURATION),
    _description(
        "temperature_deviation",
        "°C",
        getattr(SensorDeviceClass, "TEMPERATURE_DELTA", None),
        icon="mdi:thermometer-lines",
    ),
    _description("hr_drop", "bpm", icon="mdi:heart-minus"),
    _description("movements", "count", icon="mdi:bed"),
    _description("morning_alertness", "score", icon="mdi:weather-sunset-up"),
    _description("full_sleep_cycles", "cycles", icon="mdi:sleep"),
    _description("tosses_and_turns", "count", icon="mdi:bed"),
    _description("average_body_temperature", "°C", SensorDeviceClass.TEMPERATURE),
    _description("weekly_active_minutes", "min", SensorDeviceClass.DURATION),
    _description("inactive_time", icon="mdi:seat", state_class=None),
    _description("sleep_movements", "count", icon="mdi:bed"),
    _description("restorative_sleep_percentage", "%", icon="mdi:heart-pulse"),
    _description(
        "hr_drop_time", icon="mdi:clock-outline", state_class=None, precision=None
    ),
    _description("morning_alertness_minutes", "min", SensorDeviceClass.DURATION),
)

HOME_SENSOR_DESCRIPTIONS = (
    _description("hcho", icon="mdi:air-filter"),
    _description("co", icon="mdi:molecule-co"),
    _description("co2", icon="mdi:molecule-co2"),
    _description("pm1", icon="mdi:blur"),
    _description("pm10", icon="mdi:blur"),
    _description("pm25", icon="mdi:blur"),
    _description("voc", icon="mdi:air-filter"),
    _description("temp", icon="mdi:thermometer"),
    _description("humidity", icon="mdi:water-percent"),
    _description("noise", icon="mdi:volume-high"),
    _description("aqi", icon="mdi:air-filter"),
    _description("mic", icon="mdi:microphone", enabled=False, state_class=None),
    _description("uva", icon="mdi:weather-sunny", enabled=False),
    _description("uvb", icon="mdi:weather-sunny", enabled=False),
    _description("uvc", icon="mdi:weather-sunny", enabled=False),
    _description("red", icon="mdi:palette", enabled=False),
    _description("green", icon="mdi:palette", enabled=False),
    _description("blue", icon="mdi:palette", enabled=False),
    _description("ir", icon="mdi:weather-sunny", enabled=False),
)

# Unrecognized units get no guessed class or statistics.
_HOME_DEVICE_CLASSES: dict[tuple[str, str | None], SensorDeviceClass] = {
    ("co", "ppm"): SensorDeviceClass.CO,
    ("co2", "ppm"): SensorDeviceClass.CO2,
    ("pm1", "μg/m³"): SensorDeviceClass.PM1,
    ("pm10", "μg/m³"): SensorDeviceClass.PM10,
    ("pm25", "μg/m³"): SensorDeviceClass.PM25,
    ("voc", "μg/m³"): SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
    ("voc", "mg/m³"): SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
    ("voc", "ppm"): SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
    ("voc", "ppb"): SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
    ("temp", "°C"): SensorDeviceClass.TEMPERATURE,
    ("temp", "°F"): SensorDeviceClass.TEMPERATURE,
    ("temp", "K"): SensorDeviceClass.TEMPERATURE,
    ("humidity", "%"): SensorDeviceClass.HUMIDITY,
    ("noise", "dB"): SensorDeviceClass.SOUND_PRESSURE,
    ("noise", "dBA"): SensorDeviceClass.SOUND_PRESSURE,
    ("aqi", None): SensorDeviceClass.AQI,
    ("uva", "W/m²"): SensorDeviceClass.IRRADIANCE,
    ("uvb", "W/m²"): SensorDeviceClass.IRRADIANCE,
    ("uvc", "W/m²"): SensorDeviceClass.IRRADIANCE,
    ("red", "lux"): SensorDeviceClass.ILLUMINANCE,
    ("green", "lux"): SensorDeviceClass.ILLUMINANCE,
    ("blue", "lux"): SensorDeviceClass.ILLUMINANCE,
    ("ir", "lux"): SensorDeviceClass.ILLUMINANCE,
}
_HOME_KNOWN_GENERIC_UNITS = {("hcho", "μg/m³"), ("hcho", "mg/m³")}
_HOME_MASS_CONCENTRATIONS = {"hcho", "voc", "pm1", "pm10", "pm25"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose a separate sensor set for each daily account or Home device."""
    coordinator: UltrahumanDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    descriptions = (
        HOME_SENSOR_DESCRIPTIONS
        if coordinator.device_type == DEVICE_TYPE_HOME
        else DAILY_SENSOR_DESCRIPTIONS
    )
    async_add_entities(
        UltrahumanSensor(coordinator, description, entry)
        for description in descriptions
    )


class UltrahumanSensor(
    CoordinatorEntity[UltrahumanDataUpdateCoordinator], SensorEntity
):
    """A normalized reading with an identity independent of its display name."""

    entity_description: UltrahumanSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UltrahumanDataUpdateCoordinator,
        description: UltrahumanSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._is_home = coordinator.device_type == DEVICE_TYPE_HOME
        self._unit: str | None = description.native_unit_of_measurement
        self._unit_initialized = not self._is_home
        self._home_device_class: SensorDeviceClass | None = None
        self._home_state_class: SensorStateClass | None = None

        if self._is_home:
            mac = (
                (coordinator.mac_address or "")
                .replace(":", "")
                .replace("-", "")
                .lower()
            )
            identity = f"home_{mac}"
            self._object_id_source = mac
            self._attr_unique_id = f"{identity}_{description.key}"
            name = (
                coordinator.data.device_name if coordinator.data is not None else None
            )
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, identity)},
                name=f"Ultrahuman Home {name or mac[-6:]}",
                manufacturer="Ultrahuman",
                model="Home",
            )
            self._initialize_home_unit()
        else:
            self._object_id_source = entry.entry_id
            self._attr_unique_id = f"{entry.entry_id}_{description.key}"
            email = entry.data.get(CONF_EMAIL, "")
            local, sep, domain = email.partition("@")
            masked = (
                f"{local[0]}{'*' * (len(local) - 1)}@{domain}"
                if sep and local
                else "***"
            )
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=f"Ultrahuman Ring ({masked})",
                manufacturer="Ultrahuman",
                model="Ring AIR",
                entry_type=DeviceEntryType.SERVICE,
            )

    @property
    def suggested_object_id(self) -> str:
        """Give same-name devices distinct prefixes while preserving metric suffixes."""
        return f"{self._object_id_source}_{self.entity_description.key}"

    def _reading(self) -> MetricReading | None:
        data = self.coordinator.data
        return (
            data.metrics.get(self.entity_description.key) if data is not None else None
        )

    def _initialize_home_unit(self) -> None:
        """Lock source units when first reported, before publishing statistics."""
        if self._unit_initialized or (reading := self._reading()) is None:
            return
        if reading.unit is None and self.entity_description.key != "aqi":
            return
        self._unit = reading.unit
        self._unit_initialized = True
        metric_unit = (self.entity_description.key, self._unit)
        self._home_device_class = _HOME_DEVICE_CLASSES.get(metric_unit)
        if self.entity_description.state_class is not None and (
            self._home_device_class is not None
            or metric_unit in _HOME_KNOWN_GENERIC_UNITS
        ):
            self._home_state_class = SensorStateClass.MEASUREMENT

    def _reading_in_native_unit(self) -> MetricReading | None:
        """Convert compatible source changes without changing the statistics unit."""
        reading = self._reading()
        if (
            reading is None
            or not self._is_home
            or not self._unit_initialized
            or reading.unit == self._unit
        ):
            return reading

        key = self.entity_description.key
        # HA's density converters use Greek mu; some API units use the micro sign.
        source_unit = reading.unit.replace("µ", "μ") if reading.unit else reading.unit
        target_unit = self._unit.replace("µ", "μ") if self._unit else self._unit
        if (
            key == "temp"
            and source_unit in TemperatureConverter.VALID_UNITS
            and target_unit in TemperatureConverter.VALID_UNITS
        ):
            converter = TemperatureConverter
        elif (
            key in _HOME_MASS_CONCENTRATIONS
            and source_unit in MassVolumeConcentrationConverter.VALID_UNITS
            and target_unit in MassVolumeConcentrationConverter.VALID_UNITS
        ):
            converter = MassVolumeConcentrationConverter
        else:
            return None

        attrs = dict(reading.attributes)
        attrs.setdefault("source_unit", reading.unit)
        for name in ("average", "min", "max"):
            if name in attrs:
                attrs[name] = converter.convert(attrs[name], source_unit, target_unit)
        if any(name in attrs for name in ("average", "min", "max")):
            attrs["summary_unit"] = self._unit
        value = (
            converter.convert(reading.value, source_unit, target_unit)
            if reading.value is not None
            else None
        )
        return MetricReading(value, self._unit, attrs)

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._is_home:
            self._initialize_home_unit()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | float | str | None:
        reading = self._reading_in_native_unit()
        return reading.value if reading is not None else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if not self._is_home and self.entity_description.key == "inactive_time":
            reading = self._reading()
            return reading.unit if reading is not None else None
        return self._unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return (
            self._home_device_class
            if self._is_home
            else self.entity_description.device_class
        )

    @property
    def state_class(self) -> SensorStateClass | None:
        return (
            self._home_state_class
            if self._is_home
            else self.entity_description.state_class
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reading = self._reading()
        if reading is None:
            return None
        converted = self._reading_in_native_unit()
        attrs = dict((converted or reading).attributes)
        if self.coordinator.data is not None and self.coordinator.data.timezone:
            attrs["timezone"] = self.coordinator.data.timezone
        if self._is_home and self._unit_initialized and converted is None:
            attrs["unexpected_source_unit"] = reading.unit
        return attrs
