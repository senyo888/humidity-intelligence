"""Reusable runtime simulation fixtures for HI air-control mode validation."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import pathlib
import re
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from types import MethodType, SimpleNamespace
from typing import Any, Dict, List, Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "humidity_intelligence"
ENTRY_ID = "entry123"
PKG = "hi_air_control_mode_testpkg"
DOMAIN = "humidity_intelligence"

AIR_CONTROL_MODE_ENTITY_ID = "sensor.humidity_intelligence_hi_air_control_mode"
AIR_CONTROL_REASON_ENTITY_ID = "sensor.humidity_intelligence_hi_air_control_reason"


BASELINE_TELEMETRY: Dict[str, Any] = {
    "sensor.hi_fixture_kitchen_humidity": 50,
    "sensor.hi_fixture_kitchen_temperature": 21,
    "sensor.hi_fixture_hallway_humidity": 50,
    "sensor.hi_fixture_hallway_temperature": 21,
    "sensor.hi_fixture_bedroom_humidity": 50,
    "sensor.hi_fixture_bedroom_temperature": 20,
    "sensor.hi_fixture_level1_iaq": 90,
    "sensor.hi_fixture_level1_pm25": 5,
    "sensor.hi_fixture_co_ppm": 0,
}


@dataclass
class SimulationResult:
    mode_entity_id: str
    reason_entity_id: str
    mode_sensor_state: str
    mode_sensor_attrs: Dict[str, Any]
    reason_sensor_state: str
    reason_sensor_attrs: Dict[str, Any]
    runtime_mode: Optional[str]
    runtime_display: Optional[str]
    runtime_reason: str
    lower_lane_trace: List[str]
    fan_service_calls: List[tuple]
    all_service_calls: List[tuple]
    telemetry: Dict[str, Any]
    co_pressure_opted_in: bool


def run_air_control_simulation(
    *,
    telemetry_overrides: Optional[Dict[str, Any]] = None,
    state_overrides: Optional[Dict[str, Any]] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    boolean_overrides: Optional[Dict[str, bool]] = None,
    timer_overrides: Optional[Dict[str, str]] = None,
    co_pressure: bool = False,
    display_presenter_failure: bool = False,
    display_fact_failure: bool = False,
) -> SimulationResult:
    """Run a backend-consumed fake telemetry scenario.

    The helper builds a fresh fake HA runtime for every call. Fake telemetry is
    test-owned data and never becomes a Home Assistant service, dashboard
    fixture, or runtime control path.
    """
    telemetry = dict(BASELINE_TELEMETRY)
    telemetry.update(dict(telemetry_overrides or {}))
    if _numeric(telemetry.get("sensor.hi_fixture_co_ppm")) >= 15 and not co_pressure:
        raise AssertionError("CO emergency pressure must be explicitly opted in.")

    engine_mod, core_mod = _load_runtime_modules()
    original_presenter = engine_mod.build_display_reason
    if display_presenter_failure:
        def _raise_presenter(_facts):
            raise RuntimeError("injected display presenter failure")

        engine_mod.build_display_reason = _raise_presenter
    config = _base_entry_data()
    _deep_update(config, dict(config_overrides or {}))
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=config, options={})

    states = {
        entity_id: _FakeState(value, _default_attrs(entity_id))
        for entity_id, value in telemetry.items()
    }
    for entity_id, value in dict(state_overrides or {}).items():
        states[entity_id] = value if isinstance(value, _FakeState) else _FakeState(value)

    hass = _FakeHass(entry, states)
    for key, value in dict(boolean_overrides or {}).items():
        hass.data[DOMAIN][ENTRY_ID]["hi_input_booleans"][key].is_on = bool(value)
    for key, value in dict(timer_overrides or {}).items():
        hass.data[DOMAIN][ENTRY_ID]["hi_timers"][key].native_value = str(value)

    sensors, binary_sensors, _sources = core_mod.build_entities(hass, entry)
    _attach_entity_ids(sensors)
    runtime_data = hass.data[DOMAIN][ENTRY_ID]
    runtime_data["core_sensors"] = sensors
    runtime_data["core_binary_sensors"] = binary_sensors

    engine = engine_mod.HIAutomationEngine(hass, entry)
    if display_fact_failure:
        def _raise_fact_collection(self, *_args, **_kwargs):
            raise RuntimeError("injected display fact-collection failure")

        for method_name in (
            "_co_display_facts",
            "_control_lock_display_facts",
            "_gate_display_facts",
            "_pause_display_facts",
            "_telemetry_display_facts",
            "_runtime_display_facts",
        ):
            setattr(
                engine,
                method_name,
                MethodType(_raise_fact_collection, engine),
            )
    lower_lane_trace: List[str] = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine, method, lower_lane_trace)

    try:
        asyncio.run(_evaluate_and_refresh(engine, sensors))
        mode_sensor = _find_sensor(sensors, "air_control_mode")
        reason_sensor = _find_sensor(sensors, "air_control_reason")
        runtime_data = hass.data[DOMAIN][ENTRY_ID]
        return SimulationResult(
            mode_entity_id=getattr(mode_sensor, "entity_id", ""),
            reason_entity_id=getattr(reason_sensor, "entity_id", ""),
            mode_sensor_state=str(getattr(mode_sensor, "_attr_native_value", "")),
            mode_sensor_attrs=dict(getattr(mode_sensor, "_attr_extra_state_attributes", {}) or {}),
            reason_sensor_state=str(getattr(reason_sensor, "_attr_native_value", "")),
            reason_sensor_attrs=dict(getattr(reason_sensor, "_attr_extra_state_attributes", {}) or {}),
            runtime_mode=runtime_data.get("runtime_mode"),
            runtime_display=runtime_data.get("runtime_mode_display"),
            runtime_reason=str(runtime_data.get("runtime_reason") or ""),
            lower_lane_trace=list(lower_lane_trace),
            fan_service_calls=[
                call for call in hass.services.calls if call[0] in {"fan", "switch"}
            ],
            all_service_calls=list(hass.services.calls),
            telemetry=dict(telemetry),
            co_pressure_opted_in=bool(co_pressure),
        )
    finally:
        asyncio.run(engine.async_stop())
        engine_mod.build_display_reason = original_presenter


def _install_homeassistant_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    sensor_mod = types.ModuleType("homeassistant.components.sensor")
    binary_sensor_mod = types.ModuleType("homeassistant.components.binary_sensor")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_helper = types.ModuleType("homeassistant.helpers.entity")
    util = types.ModuleType("homeassistant.util")
    util_dt = types.ModuleType("homeassistant.util.dt")
    const = types.ModuleType("homeassistant.const")

    class HomeAssistant:
        pass

    class ConfigEntry:
        pass

    class Entity:
        def async_write_ha_state(self):
            return None

    class SensorEntity(Entity):
        pass

    class BinarySensorEntity(Entity):
        pass

    class SensorDeviceClass:
        TEMPERATURE = "temperature"

    class SensorStateClass:
        MEASUREMENT = "measurement"

    class UnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    class UnitOfRatio(StrEnum):
        PERCENTAGE = "%"

    class DeviceInfo(dict):
        pass

    def async_track_state_change_event(*_args, **_kwargs):
        return lambda: None

    def async_track_time_interval(*_args, **_kwargs):
        return lambda: None

    def async_track_point_in_utc_time(*_args, **_kwargs):
        return lambda: None

    def slugify(value):
        return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()))

    core.HomeAssistant = HomeAssistant
    config_entries.ConfigEntry = ConfigEntry
    const.PERCENTAGE = "%"
    const.UnitOfRatio = UnitOfRatio
    const.UnitOfTemperature = UnitOfTemperature
    sensor_mod.SensorEntity = SensorEntity
    sensor_mod.SensorDeviceClass = SensorDeviceClass
    sensor_mod.SensorStateClass = SensorStateClass
    binary_sensor_mod.BinarySensorEntity = BinarySensorEntity
    event.async_track_state_change_event = async_track_state_change_event
    event.async_track_time_interval = async_track_time_interval
    event.async_track_point_in_utc_time = async_track_point_in_utc_time
    device_registry.DeviceInfo = DeviceInfo
    entity_helper.Entity = Entity
    util.slugify = slugify
    util_dt.now = lambda: datetime.now().astimezone()
    util_dt.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = util_dt

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.sensor"] = sensor_mod
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_mod
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.entity"] = entity_helper
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = util_dt
    sys.modules["homeassistant.const"] = const


def _install_package_scaffold() -> None:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    for sub in ("automations", "helpers", "sensors"):
        mod = types.ModuleType(f"{PKG}.{sub}")
        mod.__path__ = [str(INTEGRATION_ROOT / sub)]
        sys.modules[f"{PKG}.{sub}"] = mod

    services = types.ModuleType(f"{PKG}.services")

    async def async_flash_lights_for_alert(hass, **kwargs):
        hass.data.setdefault("_trusted_visual_alert_calls", []).append(dict(kwargs))

    services.async_flash_lights_for_alert = async_flash_lights_for_alert
    sys.modules[f"{PKG}.services"] = services


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_runtime_modules():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PKG}.helpers.level_labels", INTEGRATION_ROOT / "helpers" / "level_labels.py")
    _load_module(f"{PKG}.helpers.parsing", INTEGRATION_ROOT / "helpers" / "parsing.py")
    _load_module(f"{PKG}.helpers.seasonal", INTEGRATION_ROOT / "helpers" / "seasonal.py")
    _load_module(f"{PKG}.helpers.zone_validation", INTEGRATION_ROOT / "helpers" / "zone_validation.py")
    _load_module(f"{PKG}.helpers.drift", INTEGRATION_ROOT / "helpers" / "drift.py")
    engine_mod = _load_module(f"{PKG}.automations.engine", INTEGRATION_ROOT / "automations" / "engine.py")
    core_mod = _load_module(f"{PKG}.sensors.core", INTEGRATION_ROOT / "sensors" / "core.py")
    return engine_mod, core_mod


def _base_entry_data() -> Dict[str, Any]:
    return {
        "target_profile": "winter",
        "alert_handling_enabled": True,
        "telemetry": [
            {
                "entity_id": "sensor.hi_fixture_kitchen_humidity",
                "sensor_type": "humidity",
                "level": "level1",
                "room": "Kitchen",
                "friendly_name": "Kitchen humidity",
            },
            {
                "entity_id": "sensor.hi_fixture_kitchen_temperature",
                "sensor_type": "temperature",
                "level": "level1",
                "room": "Kitchen",
                "friendly_name": "Kitchen temperature",
            },
            {
                "entity_id": "sensor.hi_fixture_hallway_humidity",
                "sensor_type": "humidity",
                "level": "level1",
                "room": "Hallway",
                "friendly_name": "Hallway humidity",
            },
            {
                "entity_id": "sensor.hi_fixture_hallway_temperature",
                "sensor_type": "temperature",
                "level": "level1",
                "room": "Hallway",
                "friendly_name": "Hallway temperature",
            },
            {
                "entity_id": "sensor.hi_fixture_bedroom_humidity",
                "sensor_type": "humidity",
                "level": "level2",
                "room": "Bedroom",
                "friendly_name": "Bedroom humidity",
            },
            {
                "entity_id": "sensor.hi_fixture_bedroom_temperature",
                "sensor_type": "temperature",
                "level": "level2",
                "room": "Bedroom",
                "friendly_name": "Bedroom temperature",
            },
            {
                "entity_id": "sensor.hi_fixture_level1_iaq",
                "sensor_type": "iaq",
                "level": "level1",
                "room": "Hallway",
                "friendly_name": "Level 1 IAQ",
            },
            {
                "entity_id": "sensor.hi_fixture_level1_pm25",
                "sensor_type": "pm25",
                "level": "level1",
                "room": "Hallway",
                "friendly_name": "Level 1 PM2.5",
            },
            {
                "entity_id": "sensor.hi_fixture_co_ppm",
                "sensor_type": "co",
                "level": "level1",
                "room": "Kitchen",
                "friendly_name": "CO ppm",
            },
        ],
        "zones": {
            "zone1": {
                "enabled": True,
                "level": "level1",
                "rooms": ["Kitchen"],
                "outputs": ["fan.hi_fixture_zone1"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 5},
                "output_level": 66,
                "boost_output_level": 100,
                "ui_label": "Zone 1",
            },
            "zone2": {
                "enabled": True,
                "level": "level2",
                "rooms": ["Bedroom"],
                "outputs": ["fan.hi_fixture_zone2"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 5},
                "output_level": 66,
                "boost_output_level": 100,
                "ui_label": "Zone 2",
            },
        },
        "humidifiers": {},
        "aq": {
            "level1": {
                "enabled": True,
                "outputs": ["fan.hi_fixture_aq"],
                "triggers": ["iaq_bad"],
                "thresholds": {"iaq_bad": 75},
                "output_level": 66,
                "run_duration": 10,
            }
        },
        "alerts": [],
    }


class _FakeState:
    def __init__(self, state, attrs=None):
        self.state = str(state)
        self.attributes = dict(attrs or {})


class _FakeStates:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, entity_id):
        return self._values.get(entity_id)

    def is_state(self, entity_id, state):
        st = self._values.get(entity_id)
        return bool(st and st.state == state)


class _FakeServices:
    def __init__(self):
        self.calls: List[tuple] = []

    def has_service(self, _domain, _service):
        return True

    async def async_call(self, domain, service, data=None, blocking=False):
        self.calls.append((domain, service, dict(data or {}), bool(blocking)))


class _FakeBool:
    def __init__(self, initial=False):
        self.is_on = bool(initial)
        self.entity_id = None

    async def async_turn_on(self):
        self.is_on = True

    async def async_turn_off(self):
        self.is_on = False


class _FakeTimer:
    def __init__(self):
        self.native_value = "idle"
        self.entity_id = None

    async def async_start(self, _duration):
        self.native_value = "active"

    async def async_cancel(self):
        self.native_value = "idle"


class _FakeConfig:
    class units:
        temperature_unit = "°C"


class _FakeConfigEntries:
    def __init__(self, entry):
        self._entry = entry

    def async_get_entry(self, entry_id):
        return self._entry if entry_id == self._entry.entry_id else None

    def async_entries(self, _domain):
        return [self._entry]


class _FakeHass:
    def __init__(self, entry, states):
        self.config = _FakeConfig()
        self.config_entries = _FakeConfigEntries(entry)
        self.services = _FakeServices()
        self.states = _FakeStates(states)
        self.data = {
            DOMAIN: {
                entry.entry_id: {
                    "hi_input_booleans": {
                        "air_control_enabled": _FakeBool(True),
                        "air_control_manual_override": _FakeBool(False),
                        "air_isolate_fan_outputs": _FakeBool(True),
                        "air_isolate_humidifier_outputs": _FakeBool(True),
                        "air_co_emergency_active": _FakeBool(False),
                        "air_downstairs_humidifier_active": _FakeBool(False),
                        "air_upstairs_humidifier_active": _FakeBool(False),
                        "air_aq_downstairs_active": _FakeBool(False),
                        "air_aq_upstairs_active": _FakeBool(False),
                        "air_alert_1_active": _FakeBool(False),
                        "air_alert_2_active": _FakeBool(False),
                        "air_alert_3_active": _FakeBool(False),
                        "air_alert_4_active": _FakeBool(False),
                        "air_alert_5_active": _FakeBool(False),
                    },
                    "hi_timers": {
                        "air_control_pause": _FakeTimer(),
                        "air_aq_downstairs_run": _FakeTimer(),
                        "air_aq_upstairs_run": _FakeTimer(),
                    },
                }
            }
        }

    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def _evaluate_and_refresh(engine, sensors):
    await engine._evaluate()
    for sensor in sensors:
        sensor.update_from_hass()


def _wrap_async_method(obj, method_name: str, trace: List[str]) -> None:
    original = getattr(obj, method_name)

    async def wrapped(self, *args, **kwargs):
        if method_name == "_handle_zone_by_key" and args:
            trace.append(f"{method_name}:{args[0]}")
        else:
            trace.append(method_name)
        return await original(*args, **kwargs)

    setattr(obj, method_name, MethodType(wrapped, obj))


def _find_sensor(sensors, unique_suffix: str):
    for sensor in sensors:
        if getattr(sensor, "_attr_unique_id", "").endswith(unique_suffix):
            return sensor
    raise AssertionError(f"sensor ending {unique_suffix!r} was not built")


def _attach_entity_ids(sensors) -> None:
    for sensor in sensors:
        unique_id = getattr(sensor, "_attr_unique_id", "")
        if unique_id.endswith("air_control_mode"):
            sensor.entity_id = AIR_CONTROL_MODE_ENTITY_ID
        elif unique_id.endswith("air_control_reason"):
            sensor.entity_id = AIR_CONTROL_REASON_ENTITY_ID


def _default_attrs(entity_id: str) -> Dict[str, Any]:
    if entity_id.endswith("_temperature"):
        return {"unit_of_measurement": "°C"}
    if entity_id.endswith("_humidity"):
        return {"unit_of_measurement": "%"}
    if entity_id.endswith("_co_ppm"):
        return {"unit_of_measurement": "ppm"}
    return {}


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _deep_update(base: Dict[str, Any], overrides: Dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
