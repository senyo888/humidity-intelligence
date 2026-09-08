"""Core computed sensors for Humidity Intelligence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
try:
    from homeassistant.const import UnitOfRatio
except ImportError:
    from homeassistant.const import PERCENTAGE as _LEGACY_PERCENTAGE

    # UnitOfRatio was added in Home Assistant 2026.7; keep the 2026.5 floor importable.
    class UnitOfRatio(StrEnum):
        PERCENTAGE = _LEGACY_PERCENTAGE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.util import slugify

from ..const import DOMAIN
from ..helpers.drift import (
    HOUSE_HUMIDITY_MEAN_7D_ENTITY,
    house_drift_unavailable_attributes,
    humidity_drift_dependency_status,
)
from ..helpers.parsing import format_temperature, hass_temperature_unit, parse_numeric, parse_temperature
from ..helpers.reason_presentation import (
    ReasonPresentationError,
    validate_display_reason,
)
from ..helpers.seasonal import (
    condensation_risk as seasonal_condensation_risk,
    humidity_state as seasonal_humidity_state,
    mould_risk as seasonal_mould_risk,
    resolve_target_profile,
    resolve_temperature_comfort_profile,
    temperature_comfort_state,
)
from ..helpers.zone_validation import detect_zone_mapping_duplicates, summarize_zone_mapping_duplicates

_LOGGER = logging.getLogger(__name__)


@dataclass
class _RoomMetrics:
    name: str
    humidity: Optional[float]
    temperature: Optional[float]
    dew_point: Optional[float]
    spread: Optional[float]
    condensation_risk: str
    mould_risk: str


_RISK_ORDER = {"OK": 0, "Watch": 1, "Risk": 2, "Danger": 3, "Unknown": -1}


class HIComputedSensor(SensorEntity):
    """Sensor whose state is computed from other entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        compute: Callable[[], Tuple[Any, Dict[str, Any]]],
        unit: Optional[str] = None,
        device_class: Optional[SensorDeviceClass] = None,
        state_class: Optional[SensorStateClass] = None,
        icon: Optional[str] = None,
    ) -> None:
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._compute = compute
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hi")},
            name="Humidity Intelligence",
            manufacturer="Humidity Intelligence",
        )

    def update_from_hass(self) -> None:
        state, attrs = self._compute()
        self._attr_native_value = state
        self._attr_extra_state_attributes = attrs


class HIComputedBinarySensor(BinarySensorEntity):
    """Binary sensor computed from other entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        compute: Callable[[], Tuple[bool, Dict[str, Any]]],
        icon: Optional[str] = None,
    ) -> None:
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._compute = compute
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hi")},
            name="Humidity Intelligence",
            manufacturer="Humidity Intelligence",
        )

    def update_from_hass(self) -> None:
        state, attrs = self._compute()
        self._attr_is_on = state
        self._attr_extra_state_attributes = attrs


def build_entities(hass: HomeAssistant, entry: ConfigEntry) -> Tuple[List[SensorEntity], List[BinarySensorEntity], List[str]]:
    """Build computed sensors and the list of source entity IDs."""
    telemetry: List[Dict[str, Any]] = _entry_section(entry, "telemetry", [])
    sources = [t["entity_id"] for t in telemetry if t.get("entity_id")]
    if HOUSE_HUMIDITY_MEAN_7D_ENTITY not in sources:
        sources.append(HOUSE_HUMIDITY_MEAN_7D_ENTITY)
    core = _CoreComputations(hass, entry, telemetry)
    sensors = core.build_sensors()
    binary_sensors = core.build_binary_sensors()
    for sensor in sensors:
        sensor.update_from_hass()
    for sensor in binary_sensors:
        sensor.update_from_hass()
    return sensors, binary_sensors, sources


class _CoreComputations:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, telemetry: List[Dict[str, Any]]) -> None:
        self.hass = hass
        self.entry = entry
        self.telemetry = telemetry
        self.zones: Dict[str, Dict[str, Any]] = _entry_section(entry, "zones", {})
        self.rooms: Dict[str, Dict[str, str]] = {}
        self.room_labels: Dict[str, str] = {}
        self.levels: Dict[str, Dict[str, List[str]]] = {}
        self._zone_duplicate_signature: Tuple[str, ...] = tuple()
        self._index()

    def _index(self) -> None:
        for item in self.telemetry:
            entity_id = item.get("entity_id")
            room = item.get("room") or ""
            friendly_name = item.get("friendly_name") or ""
            level = item.get("level")
            stype = item.get("sensor_type")
            if room:
                self.rooms.setdefault(room, {})[stype] = entity_id
                if room not in self.room_labels:
                    if friendly_name:
                        self.room_labels[room] = friendly_name
                    else:
                        self.room_labels[room] = room
            if level:
                self.levels.setdefault(level, {}).setdefault(stype, []).append(entity_id)

    def build_sensors(self) -> List[SensorEntity]:
        entry_id = self.entry.entry_id
        sensors: List[SensorEntity] = []

        def make(name: str, key: str, compute: Callable[[], Tuple[Any, Dict[str, Any]]], unit: Optional[str] = None,
                 device_class: Optional[SensorDeviceClass] = None, state_class: Optional[SensorStateClass] = None,
                 icon: Optional[str] = None) -> SensorEntity:
            return HIComputedSensor(
                self.hass,
                name=name,
                unique_id=f"hi_{entry_id}_{key}",
                compute=compute,
                unit=unit,
                device_class=device_class,
                state_class=state_class,
                icon=icon,
            )

        sensors.append(make(
            "HI House Average Humidity",
            "house_avg_humidity",
            self._compute_house_avg_humidity,
            unit=UnitOfRatio.PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:water-percent",
        ))
        sensors.append(make(
            "HI House Average Temperature",
            "house_avg_temperature",
            self._compute_house_avg_temperature,
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:thermometer",
        ))
        sensors.append(make(
            "HI House Humidity Target Low",
            "house_target_low",
            self._compute_target_low,
            unit=UnitOfRatio.PERCENTAGE,
            icon="mdi:target",
        ))
        sensors.append(make(
            "HI House Humidity Target High",
            "house_target_high",
            self._compute_target_high,
            unit=UnitOfRatio.PERCENTAGE,
            icon="mdi:target",
        ))
        sensors.append(make(
            "HI Active Target Season",
            "target_season",
            self._compute_target_season,
            icon="mdi:calendar",
        ))
        sensors.append(make(
            "HI House Temperature Comfort Low",
            "house_temperature_comfort_low",
            self._compute_temperature_comfort_low,
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            icon="mdi:thermometer-low",
        ))
        sensors.append(make(
            "HI House Temperature Comfort High",
            "house_temperature_comfort_high",
            self._compute_temperature_comfort_high,
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            icon="mdi:thermometer-high",
        ))
        sensors.append(make(
            "HI House Temperature Comfort State",
            "house_temperature_comfort_state",
            self._compute_house_temperature_comfort_state,
            icon="mdi:home-thermometer",
        ))
        sensors.append(make(
            "HI House Humidity State",
            "house_humidity_state",
            self._compute_house_humidity_state,
            icon="mdi:water-sync",
        ))
        sensors.append(make(
            "HI Worst Room Condensation",
            "worst_condensation",
            self._compute_worst_condensation,
            icon="mdi:water-alert",
        ))
        sensors.append(make(
            "HI Worst Room Mould",
            "worst_mould",
            self._compute_worst_mould,
            icon="mdi:biohazard",
        ))
        sensors.append(make(
            "HI House IAQ Average",
            "house_iaq_average",
            self._compute_house_iaq_avg,
            icon="mdi:air-filter",
        ))
        sensors.append(make(
            "HI House PM25 Average",
            "house_pm25_average",
            self._compute_house_pm25_avg,
            icon="mdi:chart-bubble",
        ))
        sensors.append(make(
            "HI House VOC Average",
            "house_voc_average",
            self._compute_house_voc_avg,
            icon="mdi:chemical-weapon",
        ))
        sensors.append(make(
            "HI House CO Average",
            "house_co_average",
            self._compute_house_co_avg,
            icon="mdi:molecule-co",
        ))
        sensors.append(make(
            "HI House Humidity Drift 7d",
            "house_drift_7d",
            self._compute_house_drift_7d,
            unit=UnitOfRatio.PERCENTAGE,
            icon="mdi:chart-line",
        ))
        sensors.append(make(
            "HI Air Control Mode",
            "air_control_mode",
            self._compute_mode,
            icon="mdi:fan",
        ))
        sensors.append(make(
            "HI Air Control Reason",
            "air_control_reason",
            self._compute_reason,
            icon="mdi:comment-text",
        ))
        sensors.append(make(
            "HI Active Alert Context",
            "active_alert_context",
            self._compute_active_alert_context,
            icon="mdi:alert-decagram",
        ))
        sensors.append(make(
            "HI Air Control Kitchen Humidity Delta",
            "air_control_kitchen_humidity_delta",
            self._compute_kitchen_humidity_delta,
            unit=UnitOfRatio.PERCENTAGE,
        ))
        sensors.append(make(
            "HI Air Control Bathroom Humidity Delta",
            "air_control_bathroom_humidity_delta",
            self._compute_bathroom_humidity_delta,
            unit=UnitOfRatio.PERCENTAGE,
        ))
        sensors.append(make(
            "HI Air Control Kitchen Slope Delta",
            "air_control_kitchen_slope_delta",
            self._compute_kitchen_slope_delta,
            unit="degC/h",
        ))
        sensors.append(make(
            "HI Worst Room Condensation Risk",
            "worst_condensation_risk",
            self._compute_worst_condensation_risk,
            icon="mdi:water-alert",
        ))
        sensors.append(make(
            "HI Worst Room Mould Risk",
            "worst_mould_risk",
            self._compute_worst_mould_risk,
            icon="mdi:biohazard",
        ))
        sensors.append(make(
            "HI Zone Mapping Duplicates",
            "zone_mapping_duplicates",
            self._compute_zone_mapping_duplicates,
            icon="mdi:alert-outline",
        ))

        for room in sorted(self.rooms.keys(), key=lambda r: r.lower()):
            if "humidity" not in self.rooms.get(room, {}):
                continue
            room_key = _slugify_room(room)
            display_name = self.room_labels.get(room, room)
            sensors.append(make(
                f"HI {display_name} Humidity Delta",
                f"room_{room_key}_humidity_delta",
                lambda r=room: self._compute_room_humidity_delta(r),
                unit=UnitOfRatio.PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:water-percent",
            ))

        for level in sorted(self.levels.keys()):
            sensors.append(make(
                f"HI {level.capitalize()} Average Humidity",
                f"{level}_avg_humidity",
                lambda lvl=level: self._compute_level_avg_humidity(lvl),
                unit=UnitOfRatio.PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:water-percent",
            ))
            sensors.append(make(
                f"HI {level.capitalize()} Average Temperature",
                f"{level}_avg_temperature",
                lambda lvl=level: self._compute_level_avg_temperature(lvl),
                unit=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:thermometer",
            ))
            sensors.append(make(
                f"HI {level.capitalize()} Humidity Target Low",
                f"{level}_target_low",
                self._compute_target_low,
                unit=UnitOfRatio.PERCENTAGE,
                icon="mdi:target",
            ))
            sensors.append(make(
                f"HI {level.capitalize()} Humidity Target High",
                f"{level}_target_high",
                self._compute_target_high,
                unit=UnitOfRatio.PERCENTAGE,
                icon="mdi:target",
            ))
            sensors.append(make(
                f"HI {level.capitalize()} Temperature Comfort State",
                f"{level}_temperature_comfort_state",
                lambda lvl=level: self._compute_level_temperature_comfort_state(lvl),
                icon="mdi:home-thermometer",
            ))

            if self.levels.get(level, {}).get("iaq"):
                sensors.append(make(
                    f"HI {level.capitalize()} IAQ Average",
                    f"{level}_iaq_average",
                    lambda lvl=level: self._compute_level_iaq_avg(lvl),
                    icon="mdi:air-filter",
                ))
            if self.levels.get(level, {}).get("pm25"):
                sensors.append(make(
                    f"HI {level.capitalize()} PM25 Average",
                    f"{level}_pm25_average",
                    lambda lvl=level: self._compute_level_pm25_avg(lvl),
                    icon="mdi:chart-bubble",
                ))
            if self.levels.get(level, {}).get("voc"):
                sensors.append(make(
                    f"HI {level.capitalize()} VOC Average",
                    f"{level}_voc_average",
                    lambda lvl=level: self._compute_level_voc_avg(lvl),
                    icon="mdi:chemical-weapon",
                ))
            if self.levels.get(level, {}).get("co"):
                sensors.append(make(
                    f"HI {level.capitalize()} CO Average",
                    f"{level}_co_average",
                    lambda lvl=level: self._compute_level_co_avg(lvl),
                    icon="mdi:molecule-co",
                ))

        return sensors

    def build_binary_sensors(self) -> List[BinarySensorEntity]:
        entry_id = self.entry.entry_id
        sensors: List[BinarySensorEntity] = []

        def make(name: str, key: str, compute: Callable[[], Tuple[bool, Dict[str, Any]]], icon: Optional[str] = None):
            return HIComputedBinarySensor(
                self.hass,
                name=name,
                unique_id=f"hi_{entry_id}_{key}",
                compute=compute,
                icon=icon,
            )

        sensors.append(make(
            "HI Condensation Danger",
            "condensation_danger",
            self._compute_condensation_danger,
            icon="mdi:water-alert",
        ))
        sensors.append(make(
            "HI Mould Danger",
            "mould_danger",
            self._compute_mould_danger,
            icon="mdi:biohazard",
        ))
        sensors.append(make(
            "HI Humidity Danger",
            "humidity_danger",
            self._compute_humidity_danger,
            icon="mdi:water-alert",
        ))
        return sensors

    def _compute_house_avg_humidity(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("humidity")
        return _avg(values), {}

    def _compute_house_avg_temperature(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("temperature")
        avg_c = _avg(values)
        display_unit = hass_temperature_unit(self.hass)
        return avg_c, {
            "display_value": format_temperature(avg_c, display_unit),
            "display_unit": display_unit,
        }

    def _compute_level_avg_humidity(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("humidity", level)
        return _avg(values), {}

    def _compute_level_avg_temperature(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("temperature", level)
        avg_c = _avg(values)
        display_unit = hass_temperature_unit(self.hass)
        return avg_c, {
            "display_value": format_temperature(avg_c, display_unit),
            "display_unit": display_unit,
        }

    def _compute_target_low(self) -> Tuple[float, Dict[str, Any]]:
        profile = self._active_target_profile()
        return profile.low, {
            "season": profile.label,
            "profile": profile.key,
            "high_risk": profile.high_risk,
        }

    def _compute_target_high(self) -> Tuple[float, Dict[str, Any]]:
        profile = self._active_target_profile()
        return profile.high, {
            "season": profile.label,
            "profile": profile.key,
            "high_risk": profile.high_risk,
        }

    def _compute_target_season(self) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_target_profile()
        return profile.label, {
            "profile": profile.key,
            "target_low": profile.low,
            "target_high": profile.high,
            "high_risk": profile.high_risk,
        }

    def _compute_temperature_comfort_low(self) -> Tuple[float, Dict[str, Any]]:
        profile = self._active_temperature_comfort_profile()
        return profile.low, {
            "season": profile.label,
            "profile": profile.key,
            "comfort_high": profile.high,
            "warm_high": profile.warm_high,
            "watch_high": profile.warm_high,
        }

    def _compute_temperature_comfort_high(self) -> Tuple[float, Dict[str, Any]]:
        profile = self._active_temperature_comfort_profile()
        return profile.high, {
            "season": profile.label,
            "profile": profile.key,
            "comfort_low": profile.low,
            "warm_high": profile.warm_high,
            "watch_high": profile.warm_high,
        }

    def _compute_house_temperature_comfort_state(self) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_temperature_comfort_profile()
        temperature = self._compute_house_avg_temperature()[0]
        state = temperature_comfort_state(temperature, profile)
        return state, {
            "temperature": temperature,
            "comfort_low": profile.low,
            "comfort_high": profile.high,
            "warm_high": profile.warm_high,
            "watch_high": profile.warm_high,
            "season": profile.label,
            "profile": profile.key,
        }

    def _compute_level_temperature_comfort_state(self, level: str) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_temperature_comfort_profile()
        temperature = self._compute_level_avg_temperature(level)[0]
        state = temperature_comfort_state(temperature, profile)
        return state, {
            "temperature": temperature,
            "comfort_low": profile.low,
            "comfort_high": profile.high,
            "warm_high": profile.warm_high,
            "watch_high": profile.warm_high,
            "season": profile.label,
            "profile": profile.key,
        }

    def _compute_house_humidity_state(self) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_target_profile()
        humidity = self._compute_house_avg_humidity()[0]
        state = seasonal_humidity_state(humidity, profile)
        if humidity is not None:
            _LOGGER.debug(
                "HI entry %s humidity badge classification: %s (humidity=%.1f, low=%.1f, high=%.1f, high_risk=%.1f, profile=%s)",
                self.entry.entry_id,
                state,
                humidity,
                profile.low,
                profile.high,
                profile.high_risk,
                profile.label,
            )
        return state, {
            "humidity": humidity,
            "target_low": profile.low,
            "target_high": profile.high,
            "high_risk": profile.high_risk,
            "season": profile.label,
            "profile": profile.key,
        }

    def _compute_worst_condensation(self) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_target_profile()
        rooms = self._room_metrics()
        worst = max(rooms, key=lambda r: _RISK_ORDER.get(r.condensation_risk, -1), default=None)
        if not worst:
            return "Unknown", {
                "risk": "Unknown",
                "season": profile.label,
                "profile": profile.key,
            }
        return worst.name, {
            "risk": worst.condensation_risk,
            "season": profile.label,
            "profile": profile.key,
            "danger_spread_threshold": profile.condensation_danger_spread,
            "risk_spread_threshold": profile.condensation_risk_spread,
            "watch_spread_threshold": profile.condensation_watch_spread,
        }

    def _compute_worst_mould(self) -> Tuple[str, Dict[str, Any]]:
        profile = self._active_target_profile()
        rooms = self._room_metrics()
        worst = max(rooms, key=lambda r: _RISK_ORDER.get(r.mould_risk, -1), default=None)
        if not worst:
            return "Unknown", {
                "risk": "Unknown",
                "season": profile.label,
                "profile": profile.key,
            }
        return worst.name, {
            "risk": worst.mould_risk,
            "season": profile.label,
            "profile": profile.key,
            "humidity_target_high": profile.high,
            "humidity_high_risk": profile.high_risk,
            "spread_danger_threshold": profile.mould_spread_danger,
            "spread_risk_threshold": profile.mould_spread_risk,
        }

    def _compute_house_iaq_avg(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("iaq")
        return _avg(values), {}

    def _compute_house_pm25_avg(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("pm25")
        return _avg(values), {}

    def _compute_house_voc_avg(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("voc")
        return _avg(values), {}

    def _compute_house_co_avg(self) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("co")
        return _avg(values), {}

    def _compute_level_iaq_avg(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("iaq", level)
        return _avg(values), {}

    def _compute_level_pm25_avg(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("pm25", level)
        return _avg(values), {}

    def _compute_level_voc_avg(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("voc", level)
        return _avg(values), {}

    def _compute_level_co_avg(self, level: str) -> Tuple[Optional[float], Dict[str, Any]]:
        values = self._collect_values("co", level)
        return _avg(values), {}

    def _compute_house_drift_7d(self) -> Tuple[Optional[float], Dict[str, Any]]:
        current = self._compute_house_avg_humidity()[0]
        dependency = humidity_drift_dependency_status(self.hass)
        mean = dependency.get("mean_7d")
        if current is None or mean is None:
            return None, house_drift_unavailable_attributes(current, dependency)
        return round(current - mean, 1), {}

    def _compute_humidity_danger(self) -> Tuple[bool, Dict[str, Any]]:
        profile = self._active_target_profile()
        values = self._collect_values("humidity")
        return any(val >= profile.high_risk for val in values), {
            "threshold": profile.high_risk,
            "season": profile.label,
            "profile": profile.key,
        }

    def _compute_mode(self) -> Tuple[str, Dict[str, Any]]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        timers = data.get("hi_timers", {})
        runtime_display = str(data.get("runtime_mode_display") or "").strip()
        runtime_mode = data.get("runtime_mode")
        if (
            runtime_mode == "co_emergency"
            or (
                booleans.get("air_co_emergency_active")
                and booleans["air_co_emergency_active"].is_on
            )
        ):
            return "co_emergency", {"display": "CO EMERGENCY"}
        if (
            runtime_mode == "manual_override"
            or (
                booleans.get("air_control_manual_override")
                and booleans["air_control_manual_override"].is_on
            )
        ):
            return "manual_override", {"display": "MANUAL OVERRIDE"}
        pause_timer = timers.get("air_control_pause")
        if pause_timer and pause_timer.native_value == "active":
            return "paused", {"display": "PAUSED"}
        if booleans.get("air_control_enabled") and not booleans["air_control_enabled"].is_on:
            return "disabled", {"display": "DISABLED"}
        if isinstance(runtime_mode, str) and runtime_mode:
            display = runtime_display or runtime_mode.replace("_", " ").upper()
            return runtime_mode, {"display": display}
        if booleans.get("air_aq_upstairs_active") and booleans["air_aq_upstairs_active"].is_on:
            return "air_quality", {"display": "AIR QUALITY"}
        if booleans.get("air_aq_downstairs_active") and booleans["air_aq_downstairs_active"].is_on:
            return "air_quality", {"display": "AIR QUALITY"}
        return "normal", {"display": "NORMAL"}

    def _compute_reason(self) -> Tuple[str, Dict[str, Any]]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        reason = data.get("runtime_reason")
        full_reason = data.get("runtime_reason_full")
        truncated = bool(data.get("runtime_reason_truncated"))
        humidifier_status = data.get("humidifier_status")
        display_reason = data.get("runtime_display_reason")
        if isinstance(reason, str) and reason.strip():
            attrs: Dict[str, Any] = {"truncated": truncated}
            if isinstance(full_reason, str) and full_reason.strip():
                attrs["full_reason"] = full_reason.strip()
            if isinstance(humidifier_status, dict):
                attrs["humidifier_status"] = _sanitize_json(humidifier_status)
            try:
                attrs["display_reason"] = validate_display_reason(display_reason)
            except ReasonPresentationError:
                pass
            return reason.strip(), attrs
        attrs = {}
        if isinstance(humidifier_status, dict):
            attrs["humidifier_status"] = _sanitize_json(humidifier_status)
        try:
            attrs["display_reason"] = validate_display_reason(display_reason)
        except ReasonPresentationError:
            pass
        return "System is armed and monitoring sensors. No action is needed right now.", attrs

    def _compute_active_alert_context(self) -> Tuple[str, Dict[str, Any]]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        context = str(data.get("active_alert_context") or "None").strip() or "None"
        telemetry = data.get("alert_telemetry") or []
        return context, {"alert_telemetry": _sanitize_json(telemetry)}

    def _compute_kitchen_humidity_delta(self) -> Tuple[Optional[float], Dict[str, Any]]:
        kitchen = self._find_room_value("kitchen", "humidity")
        house = self._compute_house_avg_humidity()[0]
        if kitchen is None or house is None:
            return None, {}
        return round(kitchen - house, 1), {}

    def _compute_bathroom_humidity_delta(self) -> Tuple[Optional[float], Dict[str, Any]]:
        bathroom = self._find_room_value("bathroom", "humidity")
        house = self._compute_house_avg_humidity()[0]
        if bathroom is None or house is None:
            return None, {}
        return round(bathroom - house, 1), {}

    def _compute_kitchen_slope_delta(self) -> Tuple[Optional[float], Dict[str, Any]]:
        slope_entity = self._slope_entity_for_room("kitchen")
        if not slope_entity:
            return None, {}
        slope = _get_float(self.hass, slope_entity)
        if slope is None:
            return None, {"slope_entity": slope_entity}
        return slope, {"slope_entity": slope_entity}

    def _compute_worst_condensation_risk(self) -> Tuple[str, Dict[str, Any]]:
        _, attrs = self._compute_worst_condensation()
        return attrs.get("risk", "Unknown"), {
            "season": attrs.get("season"),
            "profile": attrs.get("profile"),
        }

    def _compute_worst_mould_risk(self) -> Tuple[str, Dict[str, Any]]:
        _, attrs = self._compute_worst_mould()
        return attrs.get("risk", "Unknown"), {
            "season": attrs.get("season"),
            "profile": attrs.get("profile"),
        }

    def _compute_zone_mapping_duplicates(self) -> Tuple[str, Dict[str, Any]]:
        duplicates = detect_zone_mapping_duplicates(
            self.telemetry,
            self.zones if isinstance(self.zones, dict) else {},
        )
        duplicate_entities = sorted({entity for values in duplicates.values() for entity in values})
        signature = tuple(duplicate_entities)
        if duplicate_entities and signature != self._zone_duplicate_signature:
            _LOGGER.warning(
                "Zone mapping duplicates detected for entry %s: %s",
                self.entry.entry_id,
                summarize_zone_mapping_duplicates(duplicates),
            )
        self._zone_duplicate_signature = signature
        if duplicate_entities:
            return "detected", {
                "message": "Zone mapping duplicates detected",
                "duplicates": duplicates,
                "duplicate_entities": duplicate_entities,
            }
        return "clear", {
            "message": "No zone mapping duplicates detected",
            "duplicates": {},
            "duplicate_entities": [],
        }

    def _compute_condensation_danger(self) -> Tuple[bool, Dict[str, Any]]:
        state, attrs = self._compute_worst_condensation()
        return attrs.get("risk") == "Danger", {
            "worst_room": state,
            "season": attrs.get("season"),
            "profile": attrs.get("profile"),
        }

    def _compute_mould_danger(self) -> Tuple[bool, Dict[str, Any]]:
        state, attrs = self._compute_worst_mould()
        return attrs.get("risk") == "Danger", {
            "worst_room": state,
            "season": attrs.get("season"),
            "profile": attrs.get("profile"),
        }

    def _compute_room_humidity_delta(self, room: str) -> Tuple[Optional[float], Dict[str, Any]]:
        sensor_id = self.rooms.get(room, {}).get("humidity")
        room_val = _get_float(self.hass, sensor_id)
        house_avg = self._compute_house_avg_humidity()[0]
        display_name = self.room_labels.get(room, room)
        if room_val is None or house_avg is None:
            return None, {"room": display_name}
        return round(room_val - house_avg, 1), {
            "room": display_name,
            "room_humidity": room_val,
            "house_average": house_avg,
        }

    def _collect_values(self, sensor_type: str, level: Optional[str] = None) -> List[float]:
        entity_ids: List[str] = []
        if level:
            entity_ids = self.levels.get(level, {}).get(sensor_type, [])
        else:
            for lvl in self.levels.values():
                entity_ids.extend(lvl.get(sensor_type, []))
        values: List[float] = []
        exclusions: List[Tuple[str, str]] = []
        expected_unit: Optional[str] = None
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None:
                exclusions.append((entity_id, "missing"))
                continue

            raw_state = str(state.state).strip()
            lowered = raw_state.lower()
            if lowered == "unknown":
                exclusions.append((entity_id, "unknown"))
                continue
            if lowered == "unavailable":
                exclusions.append((entity_id, "unavailable"))
                continue

            if sensor_type == "temperature":
                temp_c, reason = parse_temperature(
                    state.state,
                    state.attributes.get("unit_of_measurement"),
                    hass_temperature_unit(self.hass),
                )
                if temp_c is None:
                    exclusions.append((entity_id, reason or "non_numeric"))
                    continue
                values.append(temp_c)
                continue

            val = parse_numeric(state.state)
            if val is None:
                exclusions.append((entity_id, "non_numeric"))
                continue

            normalized_unit = _normalize_sensor_unit(sensor_type, state.attributes.get("unit_of_measurement"))
            if normalized_unit is not None:
                if expected_unit is None:
                    expected_unit = normalized_unit
                elif normalized_unit != expected_unit:
                    exclusions.append((entity_id, "unit_mismatch"))
                    continue

            values.append(val)

        if exclusions:
            scope = f"level={level}" if level else "house"
            excluded_summary = ", ".join(f"{entity}:{reason}" for entity, reason in exclusions)
            _LOGGER.debug(
                "Excluded %s telemetry values for %s (%s): %s",
                sensor_type,
                self.entry.entry_id,
                scope,
                excluded_summary,
            )
        return values

    def _room_metrics(self) -> List[_RoomMetrics]:
        profile = self._active_target_profile()
        metrics: List[_RoomMetrics] = []
        for room, sensors in self.rooms.items():
            rh = _get_float(self.hass, sensors.get("humidity"))
            temp = _get_temperature_c(self.hass, sensors.get("temperature"))
            if rh is None or temp is None:
                cond = "Unknown"
                mould = "Unknown"
                dp = None
                spread = None
            else:
                dp = _dew_point(temp, rh)
                spread = temp - dp if dp is not None else None
                cond = seasonal_condensation_risk(spread, profile)
                mould = seasonal_mould_risk(rh, spread, profile)
            metrics.append(_RoomMetrics(
                name=self.room_labels.get(room, room),
                humidity=rh,
                temperature=temp,
                dew_point=dp,
                spread=spread,
                condensation_risk=cond,
                mould_risk=mould,
            ))
        return metrics

    def _slope_entity_for_room(self, room_hint: str) -> Optional[str]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        slope_map: Dict[str, str] = data.get("slope_map", {})
        temp_entity = self._find_room_entity_id(room_hint, "temperature")
        if temp_entity and slope_map.get(temp_entity):
            return slope_map[temp_entity]

        room_hint_lower = room_hint.lower()
        for source_entity, slope_entity in slope_map.items():
            source_room = ""
            for room, sensors in self.rooms.items():
                if sensors.get("temperature") == source_entity:
                    source_room = room
                    break
            if source_room and room_hint_lower in source_room.lower():
                return slope_entity
            if room_hint_lower in source_entity.lower():
                return slope_entity
            if room_hint_lower in slope_entity.lower():
                return slope_entity
        return None

    def _find_room_entity_id(self, room_hint: str, sensor_type: str) -> Optional[str]:
        room_hint = room_hint.lower()
        for room, sensors in self.rooms.items():
            if room_hint in room.lower():
                return sensors.get(sensor_type)
        return None

    def _find_room_value(self, room_hint: str, sensor_type: str) -> Optional[float]:
        entity_id = self._find_room_entity_id(room_hint, sensor_type)
        return _get_float(self.hass, entity_id)

    def _active_target_profile(self):
        return resolve_target_profile(self._effective_config())

    def _active_temperature_comfort_profile(self):
        return resolve_temperature_comfort_profile(self._effective_config())

    def _effective_config(self) -> Dict[str, Any]:
        data = dict(getattr(self.entry, "data", None) or {})
        data.update(dict(getattr(self.entry, "options", None) or {}))
        return data


def _get_float(hass: HomeAssistant, entity_id: Optional[str]) -> Optional[float]:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    raw_state = str(state.state).strip()
    if raw_state.lower() in ("unknown", "unavailable"):
        return None
    return parse_numeric(raw_state)


def _get_temperature_c(hass: HomeAssistant, entity_id: Optional[str]) -> Optional[float]:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    raw_state = str(state.state).strip()
    if raw_state.lower() in ("unknown", "unavailable"):
        return None
    value_c, _reason = parse_temperature(
        state.state,
        state.attributes.get("unit_of_measurement"),
        hass_temperature_unit(hass),
    )
    return value_c


def _avg(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _sanitize_json(value):
    if isinstance(value, dict):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(v) for v in value]
    if isinstance(value, set):
        return list(value)
    return value


def _dew_point(temp_c: float, rh: float) -> Optional[float]:
    if rh <= 0:
        return None
    a = 17.62
    b = 243.12
    import math
    gamma = (a * temp_c / (b + temp_c)) + math.log(rh / 100.0)
    return round((b * gamma) / (a - gamma), 1)


def _slugify_room(room: str) -> str:
    return slugify(room) if room else "room"


_UNIT_ALIASES: Dict[str, Dict[str, str]] = {
    "humidity": {"%": "%", "percent": "%", "rh": "%", "%rh": "%"},
    "pm25": {"ug/m3": "ug/m3", "ug/m^3": "ug/m3", "μg/m3": "ug/m3", "µg/m3": "ug/m3"},
    "voc": {"ppb": "ppb", "ppm": "ppm"},
    "co2": {"ppm": "ppm"},
    "co": {"ppm": "ppm"},
}


def _normalize_sensor_unit(sensor_type: str, unit: Any) -> Optional[str]:
    if unit in (None, ""):
        return None
    aliases = _UNIT_ALIASES.get(sensor_type)
    if aliases is None:
        return None
    normalized = str(unit).strip().lower().replace(" ", "")
    normalized = normalized.replace("³", "3")
    normalized = normalized.replace("μ", "u").replace("µ", "u")
    return aliases.get(normalized, normalized)


def _entry_section(entry: ConfigEntry, key: str, default: Any) -> Any:
    options = getattr(entry, "options", None) or {}
    if key in options:
        return options.get(key, default)
    data = getattr(entry, "data", None) or {}
    return data.get(key, default)
