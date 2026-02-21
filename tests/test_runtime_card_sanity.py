"""Regression sanity checks for HI runtime lane ordering and card rendering."""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from types import MethodType, SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRY_ID = "entry123"
PKG = "hi_testpkg"


def _install_homeassistant_stubs() -> None:
    """Install lightweight Home Assistant stubs into sys.modules."""
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    config_entries = types.ModuleType("homeassistant.config_entries")
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class HomeAssistant:
        pass

    class ConfigEntry:
        pass

    def async_track_state_change_event(*args, **kwargs):
        return lambda: None

    def async_track_time_interval(*args, **kwargs):
        return lambda: None

    core.HomeAssistant = HomeAssistant
    config_entries.ConfigEntry = ConfigEntry
    event.async_track_state_change_event = async_track_state_change_event
    event.async_track_time_interval = async_track_time_interval
    entity_registry.async_get = lambda hass: None

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry


def _install_package_scaffold() -> None:
    """Create importable package namespace used for file-based module loading."""
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    for sub in ("automations", "ui"):
        mod = types.ModuleType(f"{PKG}.{sub}")
        mod.__path__ = [str(ROOT / sub)]
        sys.modules[f"{PKG}.{sub}"] = mod

    services = types.ModuleType(f"{PKG}.services")
    services.SERVICE_FLASH_LIGHTS = "flash_lights"
    sys.modules[f"{PKG}.services"] = services


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_target_modules():
    _install_homeassistant_stubs()
    _install_package_scaffold()

    _load_module(f"{PKG}.const", ROOT / "const.py")
    engine_mod = _load_module(f"{PKG}.automations.engine", ROOT / "automations" / "engine.py")
    register_mod = _load_module(f"{PKG}.ui.register", ROOT / "ui" / "register.py")
    return engine_mod, register_mod


class _FakeState:
    def __init__(self, state, attrs=None):
        self.state = str(state)
        self.attributes = attrs or {}


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
        self.calls = []

    def has_service(self, domain, service):
        return True

    async def async_call(self, domain, service, data=None, blocking=False):
        self.calls.append((domain, service, dict(data or {}), bool(blocking)))


class _FakeBool:
    def __init__(self, initial=False):
        self.is_on = bool(initial)

    async def async_turn_on(self):
        self.is_on = True

    async def async_turn_off(self):
        self.is_on = False


class _FakeTimer:
    def __init__(self):
        self.native_value = "idle"

    async def async_start(self, duration):
        self.native_value = "active"

    async def async_cancel(self):
        self.native_value = "idle"


class _FakeConfigEntries:
    def __init__(self, entry):
        self._entry = entry

    def async_get_entry(self, entry_id):
        return self._entry if entry_id == self._entry.entry_id else None


class _FakeRegistry:
    def async_get_entity_id(self, domain, _integration, unique_id):
        suffix = unique_id.split("_", 2)[-1]
        return f"{domain}.hi_{suffix}"


class _FakeHass:
    def __init__(self, entry, states):
        self.services = _FakeServices()
        self.states = _FakeStates(states)
        self.config_entries = _FakeConfigEntries(entry)
        self.data = {
            "humidity_intelligence": {
                entry.entry_id: {
                    "hi_input_booleans": {
                        "air_control_enabled": _FakeBool(True),
                        "air_control_manual_override": _FakeBool(False),
                        "air_isolate_fan_outputs": _FakeBool(False),
                        "air_isolate_humidifier_outputs": _FakeBool(False),
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


def _wrap_async_method(obj, method_name: str, trace: list[str]) -> None:
    original = getattr(obj, method_name)

    async def wrapped(self, *args, **kwargs):
        if method_name == "_handle_zone_by_key" and args:
            trace.append(f"{method_name}:{args[0]}")
        else:
            trace.append(method_name)
        return await original(*args, **kwargs)

    setattr(obj, method_name, MethodType(wrapped, obj))


def _base_entry_data():
    return {
        "telemetry": [
            {"entity_id": "sensor.kitchen_h", "sensor_type": "humidity", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.hall_h", "sensor_type": "humidity", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.bed_h", "sensor_type": "humidity", "level": "level2", "room": "Bedroom"},
            {"entity_id": "sensor.kitchen_t", "sensor_type": "temperature", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.hall_t", "sensor_type": "temperature", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.bed_t", "sensor_type": "temperature", "level": "level2", "room": "Bedroom"},
            {"entity_id": "sensor.l1_iaq", "sensor_type": "iaq", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.co_val", "sensor_type": "co", "level": "level1", "room": "Kitchen"},
        ],
        "zones": {
            "zone1": {
                "enabled": True,
                "level": "level1",
                "rooms": ["Kitchen"],
                "outputs": ["fan.zone1"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 5},
                "ui_label": "Cooking",
            },
            "zone2": {
                "enabled": True,
                "level": "level2",
                "rooms": ["Bedroom"],
                "outputs": ["fan.zone2"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 2},
                "ui_label": "Bathroom",
            },
        },
        "humidifiers": {
            "level1": {"enabled": True, "outputs": ["humidifier.l1"], "band_adjust": 0},
        },
        "aq": {
            "level1": {
                "enabled": True,
                "outputs": ["fan.aq1"],
                "triggers": ["iaq_bad"],
                "thresholds": {"iaq_bad": 75},
                "output_level": 66,
                "run_duration": 10,
            }
        },
        "alerts": [
            {
                "enabled": True,
                "trigger_type": "custom_binary",
                "custom_trigger": "binary_sensor.test_alert",
                "power_entity": "switch.alert_power",
                "lights": ["light.alert"],
                "flash_mode": "red",
                "duration": 10,
            }
        ],
    }


async def _run_runtime_assertions(engine_mod) -> None:
    HIAutomationEngine = engine_mod.HIAutomationEngine

    # CO emergency preemption: must short-circuit lower lanes.
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass_co = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(75),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(68),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(16),
            "binary_sensor.test_alert": _FakeState("on"),
        },
    )
    engine_co = HIAutomationEngine(hass_co, entry)
    co_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_co, method, co_trace)
    await engine_co._evaluate()

    assert co_trace == []
    assert hass_co.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "co_emergency"

    # CO emergency should respect configured threshold/output entities (from alert config)
    # and stand down non-selected outputs.
    entry_co_cfg_data = _base_entry_data()
    entry_co_cfg_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "co_emergency",
            "threshold": 20,
            "outputs": ["fan.zone1"],
            "lights": ["light.alert"],
            "power_entity": "switch.alert_power",
            "flash_mode": "red",
            "duration": 10,
        }
    ]
    entry_co_cfg = SimpleNamespace(entry_id=ENTRY_ID, data=entry_co_cfg_data, options={})
    hass_co_cfg = _FakeHass(
        entry_co_cfg,
        {
            "sensor.kitchen_h": _FakeState(60),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(60),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(21),  # above configured CO threshold (20)
        },
    )
    engine_co_cfg = HIAutomationEngine(hass_co_cfg, entry_co_cfg)
    await engine_co_cfg._evaluate()
    assert hass_co_cfg.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "co_emergency"
    assert any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.zone1"
        for domain, service, data, _ in hass_co_cfg.services.calls
    )
    # Non-selected outputs should be returned to auto while CO lane is active.
    assert any(
        domain == "fan" and service == "set_preset_mode" and data.get("entity_id") in {"fan.zone2", "fan.aq1"}
        for domain, service, data, _ in hass_co_cfg.services.calls
    )

    # Safe-threshold enforcement: CO emergency threshold is clamped to minimum safe value.
    # With threshold configured as 1 and CO at 8, emergency should not trigger.
    entry_co_guard_data = _base_entry_data()
    entry_co_guard_data["zones"]["zone1"]["enabled"] = False
    entry_co_guard_data["zones"]["zone2"]["enabled"] = False
    entry_co_guard_data["aq"] = {}
    entry_co_guard_data["humidifiers"] = {}
    entry_co_guard_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "co_emergency",
            "threshold": 1,  # below safe floor, should clamp up.
            "outputs": ["fan.zone1"],
            "lights": ["light.alert"],
            "power_entity": "switch.alert_power",
            "flash_mode": "red",
            "duration": 10,
        }
    ]
    entry_co_guard = SimpleNamespace(entry_id=ENTRY_ID, data=entry_co_guard_data, options={})
    hass_co_guard = _FakeHass(
        entry_co_guard,
        {
            "sensor.kitchen_h": _FakeState(60),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(60),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(8),
        },
    )
    engine_co_guard = HIAutomationEngine(hass_co_guard, entry_co_guard)
    await engine_co_guard._evaluate()
    assert hass_co_guard.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") != "co_emergency"

    # Alert lane is now exclusive: no humidifier/zone/AQ handling should run.
    entry2 = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry2,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(90),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("on"),
        },
    )
    engine = HIAutomationEngine(hass, entry2)
    trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine, method, trace)
    await engine._evaluate()

    assert trace == ["_handle_alerts"]
    assert "_handle_aq" not in trace

    calls = hass.services.calls
    assert any(domain == "humidity_intelligence" and service == "flash_lights" for domain, service, *_ in calls)
    assert not hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert not any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") in {"fan.zone1", "fan.zone2"}
        for domain, service, data, _ in calls
    )
    assert not any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.aq1"
        for domain, service, data, _ in calls
    )

    # Runtime mode priority should prefer alert while alert lane is active.
    assert hass.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    assert hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_alert_1_active"].is_on
    alert_reason = hass.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "Alert response is active" in alert_reason
    assert "All other lanes are paused" in alert_reason

    # Zone label and fan-step enforcement: custom UI label should be surfaced,
    # and unsupported percentages should snap to the nearest supported level.
    entry_label_data = _base_entry_data()
    entry_label_data["alerts"][0]["enabled"] = False
    entry_label_data["zones"]["zone1"]["ui_label"] = "Kitchen Extract"
    entry_label_data["zones"]["zone1"]["output_level"] = 64
    entry_label_data["zones"]["zone2"]["enabled"] = False
    entry_label_data["aq"] = {}
    entry_label = SimpleNamespace(entry_id=ENTRY_ID, data=entry_label_data, options={})
    hass_label = _FakeHass(
        entry_label,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_label = HIAutomationEngine(hass_label, entry_label)
    await engine_label._evaluate()

    assert hass_label.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "cooking"
    assert hass_label.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode_display") == "Kitchen Extract"
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 66
        for domain, service, data, _ in hass_label.services.calls
    )

    # AQ-only scenario: no alert and no zone should allow AQ lane execution.
    entry3_data = _base_entry_data()
    entry3_data["zones"]["zone1"]["enabled"] = False
    entry3_data["zones"]["zone2"]["enabled"] = False
    entry3_data["alerts"][0]["enabled"] = False
    # Overlap AQ output with a zone output to ensure AQ is not immediately reset to auto.
    entry3_data["aq"]["level1"]["outputs"] = ["fan.zone1"]
    entry3 = SimpleNamespace(entry_id=ENTRY_ID, data=entry3_data, options={})
    hass_aq = _FakeHass(
        entry3,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_aq = HIAutomationEngine(hass_aq, entry3)
    aq_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_aq, method, aq_trace)
    await engine_aq._evaluate()

    assert "_handle_aq" in aq_trace
    assert any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.zone1"
        for domain, service, data, _ in hass_aq.services.calls
    )
    assert not any(
        domain == "fan" and service == "set_preset_mode" and data.get("entity_id") == "fan.zone1"
        for domain, service, data, _ in hass_aq.services.calls
    )
    assert hass_aq.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "air_quality"
    aq_reason = hass_aq.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "AQ is active" in aq_reason or "Air-quality assist is active" in aq_reason
    assert "Trigger detail:" in aq_reason

    # AQ auto level should use fan preset mode instead of percentage service.
    entry_aq_auto_data = _base_entry_data()
    entry_aq_auto_data["zones"]["zone1"]["enabled"] = False
    entry_aq_auto_data["zones"]["zone2"]["enabled"] = False
    entry_aq_auto_data["alerts"][0]["enabled"] = False
    entry_aq_auto_data["aq"]["level1"]["output_level"] = "auto"
    entry_aq_auto = SimpleNamespace(entry_id=ENTRY_ID, data=entry_aq_auto_data, options={})
    hass_aq_auto = _FakeHass(
        entry_aq_auto,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_aq_auto = HIAutomationEngine(hass_aq_auto, entry_aq_auto)
    await engine_aq_auto._evaluate()
    assert any(
        domain == "fan" and service == "set_preset_mode" and data.get("entity_id") == "fan.aq1"
        for domain, service, data, _ in hass_aq_auto.services.calls
    )
    assert not any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.aq1"
        for domain, service, data, _ in hass_aq_auto.services.calls
    )

    # Independent AQ lanes sharing one output: both can run; newest trigger wins output level.
    entry_shared_aq_data = _base_entry_data()
    entry_shared_aq_data["zones"]["zone1"]["enabled"] = False
    entry_shared_aq_data["zones"]["zone2"]["enabled"] = False
    entry_shared_aq_data["alerts"][0]["enabled"] = False
    entry_shared_aq_data["telemetry"].append(
        {"entity_id": "sensor.l2_iaq", "sensor_type": "iaq", "level": "level2", "room": "Bedroom"}
    )
    entry_shared_aq_data["aq"] = {
        "level1": {
            "enabled": True,
            "outputs": ["fan.shared"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 33,
            "run_duration": 10,
        },
        "level2": {
            "enabled": True,
            "outputs": ["fan.shared"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 100,
            "run_duration": 10,
        },
    }
    entry_shared_aq = SimpleNamespace(entry_id=ENTRY_ID, data=entry_shared_aq_data, options={})
    hass_shared_aq = _FakeHass(
        entry_shared_aq,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),   # level1 triggers first
            "sensor.l2_iaq": _FakeState(90),   # level2 idle initially
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_shared_aq = HIAutomationEngine(hass_shared_aq, entry_shared_aq)
    await engine_shared_aq._evaluate()
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.shared"
        and data.get("percentage") == 33
        for domain, service, data, _ in hass_shared_aq.services.calls
    )
    # New level2 trigger arrives later: shared output should move to level2 setting.
    hass_shared_aq.states._values["sensor.l2_iaq"] = _FakeState(70)
    await engine_shared_aq._evaluate()
    assert hass_shared_aq.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_downstairs_active"].is_on
    assert hass_shared_aq.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.shared"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_shared_aq.services.calls
    )

    # Shared humidifier output follows last trigger transition while lanes remain independent.
    entry_shared_humid_data = _base_entry_data()
    entry_shared_humid_data["zones"]["zone1"]["enabled"] = False
    entry_shared_humid_data["zones"]["zone2"]["enabled"] = False
    entry_shared_humid_data["alerts"][0]["enabled"] = False
    entry_shared_humid_data["aq"] = {}
    entry_shared_humid_data["humidifiers"] = {
        "level1": {"enabled": True, "outputs": ["humidifier.shared"], "band_adjust": 0},
        "level2": {"enabled": True, "outputs": ["humidifier.shared"], "band_adjust": 0},
    }
    entry_shared_humid = SimpleNamespace(entry_id=ENTRY_ID, data=entry_shared_humid_data, options={})
    hass_shared_humid = _FakeHass(
        entry_shared_humid,
        {
            "sensor.kitchen_h": _FakeState(40),  # level1 below low -> on
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),      # level2 below low -> on
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(90),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_shared_humid = HIAutomationEngine(hass_shared_humid, entry_shared_humid)
    await engine_shared_humid._evaluate()
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_upstairs_humidifier_active"].is_on
    # Level1 recovers: its off transition becomes the newest command on shared output.
    hass_shared_humid.states._values["sensor.kitchen_h"] = _FakeState(55)
    hass_shared_humid.states._values["sensor.hall_h"] = _FakeState(55)
    await engine_shared_humid._evaluate()
    assert any(
        domain == "humidifier"
        and service == "turn_off"
        and data.get("entity_id") == "humidifier.shared"
        for domain, service, data, _ in hass_shared_humid.services.calls
    )
    assert not hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_upstairs_humidifier_active"].is_on

    # Testing isolation toggles suppress output service calls while logic state still updates.
    entry_isolated_data = _base_entry_data()
    entry_isolated_data["alerts"][0]["enabled"] = False
    entry_isolated_data["zones"]["zone2"]["enabled"] = False
    entry_isolated_data["aq"] = {}
    entry_isolated = SimpleNamespace(entry_id=ENTRY_ID, data=entry_isolated_data, options={})
    hass_isolated = _FakeHass(
        entry_isolated,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(90),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    hass_isolated.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_isolate_fan_outputs"].is_on = True
    hass_isolated.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_isolate_humidifier_outputs"].is_on = True
    engine_isolated = HIAutomationEngine(hass_isolated, entry_isolated)
    await engine_isolated._evaluate()
    assert hass_isolated.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "cooking"
    isolated_reason = hass_isolated.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "isolated for testing" in isolated_reason
    assert not any(
        domain in {"fan", "switch", "humidifier"} and service in {"set_percentage", "set_preset_mode", "turn_on", "turn_off"}
        for domain, service, data, _ in hass_isolated.services.calls
    )

    # Stale AQ state from an old level config must be cleared (prevents AQ badge/mode drift).
    entry4_data = _base_entry_data()
    entry4_data["zones"]["zone1"]["enabled"] = False
    entry4_data["zones"]["zone2"]["enabled"] = False
    entry4_data["alerts"][0]["enabled"] = False
    entry4_data["aq"] = {
        "level1": {
            "enabled": False,
            "outputs": ["fan.aq1"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 66,
            "run_duration": 10,
        }
    }
    entry4 = SimpleNamespace(entry_id=ENTRY_ID, data=entry4_data, options={})
    hass_stale = _FakeHass(
        entry4,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    hass_stale.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on = True
    engine_stale = HIAutomationEngine(hass_stale, entry4)
    engine_stale._aq_tasks["level2"] = asyncio.create_task(asyncio.sleep(3600))
    await engine_stale._evaluate()

    assert not hass_stale.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on
    assert "level2" not in engine_stale._aq_tasks
    assert hass_stale.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "normal"

    # Global gate should publish dedicated runtime mode for UI chip/border sync.
    entry_gate_data = _base_entry_data()
    entry_gate_data["alerts"][0]["enabled"] = False
    entry_gate_data["zones"]["zone1"]["enabled"] = False
    entry_gate_data["zones"]["zone2"]["enabled"] = False
    entry_gate_data["aq"] = {}
    entry_gate_data["humidifiers"] = {}
    entry_gate_data["presence_gate"] = {
        "enabled": True,
        "entities": ["binary_sensor.home_presence"],
        "present_states": ["on"],
        "away_states": ["off"],
    }
    entry_gate = SimpleNamespace(entry_id=ENTRY_ID, data=entry_gate_data, options={})
    hass_gate = _FakeHass(
        entry_gate,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.home_presence": _FakeState("off"),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    engine_gate = HIAutomationEngine(hass_gate, entry_gate)
    await engine_gate._evaluate()
    assert hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "global_gate"
    assert hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode_display") == "GLOBAL GATE"
    gate_reason = hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "Presence gate is active" in gate_reason

    # Disabled humidifier lanes should clear stale active state and turn outputs off.
    entry5_data = _base_entry_data()
    entry5_data["zones"]["zone1"]["enabled"] = False
    entry5_data["zones"]["zone2"]["enabled"] = False
    entry5_data["alerts"][0]["enabled"] = False
    entry5_data["aq"] = {}
    entry5_data["humidifiers"]["level1"]["enabled"] = False
    entry5 = SimpleNamespace(entry_id=ENTRY_ID, data=entry5_data, options={})
    hass_humid = _FakeHass(
        entry5,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    hass_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on = True
    engine_humid = HIAutomationEngine(hass_humid, entry5)
    await engine_humid._evaluate()

    assert not hass_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert any(
        domain == "humidifier" and service == "turn_off" and data.get("entity_id") == "humidifier.l1"
        for domain, service, data, _ in hass_humid.services.calls
    )

    # Humidifier off threshold should recover inside target band (low + 4%), not only at high target.
    entry6_data = _base_entry_data()
    entry6_data["zones"]["zone1"]["enabled"] = False
    entry6_data["zones"]["zone2"]["enabled"] = False
    entry6_data["alerts"][0]["enabled"] = False
    entry6_data["aq"] = {}
    entry6 = SimpleNamespace(entry_id=ENTRY_ID, data=entry6_data, options={})
    hass_humid_band = _FakeHass(
        entry6,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.test_alert": _FakeState("off"),
        },
    )
    # Simulate humidifier already running; at 50% in winter, it should now shut off at low+4.
    hass_humid_band.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on = True
    engine_humid_band = HIAutomationEngine(hass_humid_band, entry6)
    await engine_humid_band._evaluate()
    assert not hass_humid_band.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert any(
        domain == "humidifier" and service == "turn_off" and data.get("entity_id") == "humidifier.l1"
        for domain, service, data, _ in hass_humid_band.services.calls
    )

    # Cleanup background AQ tasks.
    for task in list(engine._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_aq._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_stale._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_aq_auto._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_shared_aq._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _contains_v2_border_pill_sync_logic(yaml_text: str) -> bool:
    chip_tokens = [
        "const red =",
        "const gateActive =",
        "const zone1 =",
        "const zone2 =",
        "const aqActive =",
        "if (red) return '#ef4444'",
        "if (gateActive) return '#f59e0b'",
        "if (zone1) return '#38bdf8'",
        "if (zone2) return '#4ade80'",
        "if (aqActive) return '#a855f7'",
    ]
    border_tokens = [
        "if (red) return '1px solid rgba(239,68,68",
        "if (gateActive) return '1px solid rgba(245,158,11",
        "if (zone1) return '1px solid rgba(56,189,248",
        "if (zone2) return '1px solid rgba(74,222,128",
        "if (aqActive) return '1px solid rgba(168,85,247",
    ]
    return all(token in yaml_text for token in chip_tokens) and all(
        token in yaml_text for token in border_tokens
    )


async def _run_card_assertions(register_mod) -> None:
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistry()

    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "telemetry": [
                {"entity_id": "sensor.kitchen_h", "sensor_type": "humidity", "level": "level1", "room": "Kitchen"},
                {"entity_id": "sensor.hall_h", "sensor_type": "humidity", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.bed_h", "sensor_type": "humidity", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.willow_h", "sensor_type": "humidity", "level": "level2", "room": "Willow Room"},
                {"entity_id": "sensor.bath_h", "sensor_type": "humidity", "level": "level1", "room": "Bathroom"},
                {"entity_id": "sensor.l1_iaq", "sensor_type": "iaq", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_iaq", "sensor_type": "iaq", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_pm25", "sensor_type": "pm25", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_pm25", "sensor_type": "pm25", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_voc", "sensor_type": "voc", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_voc", "sensor_type": "voc", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_co", "sensor_type": "co", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_co", "sensor_type": "co", "level": "level2", "room": "Bedroom"},
            ],
            "zones": {
                "zone1": {"level": "level1", "outputs": ["fan.zone1"]},
                "zone2": {"level": "level2", "outputs": ["fan.zone2"]},
            },
            "humidifiers": {
                "level1": {"outputs": ["humidifier.l1"]},
                "level2": {"outputs": ["humidifier.l2"]},
            },
            "alerts": [{"lights": ["light.alert1"]}],
        },
        options={},
    )
    hass = _FakeHass(entry, {})
    hass.config_entries = _FakeConfigEntries(entry)

    mapping = await register_mod.async_build_entity_mapping(hass, ENTRY_ID)
    cards = await register_mod.async_register_cards(hass, ENTRY_ID, mapping)

    assert hass.data["humidity_intelligence"][ENTRY_ID].get("unresolved_placeholders_by_card", {}) == {}

    room_placeholders = [
        "sensor.bedroom_humidity",
        "sensor.hallway_humidity",
        "sensor.kids_room_humidity",
        "sensor.living_room_humidity",
        "sensor.toilet_humidity",
        "sensor.bathroom_humidity",
    ]
    for placeholder in room_placeholders:
        assert mapping.get(placeholder)
        assert placeholder not in cards.get("v1_mobile", "")

    assert _contains_v2_border_pill_sync_logic(cards.get("v2_mobile", ""))
    assert _contains_v2_border_pill_sync_logic(cards.get("v2_tablet", ""))
    # Outputs should only include configured alert placeholders.
    assert "input_boolean.air_alert_2_active" not in cards.get("v2_mobile", "")
    assert "light.alert_2" not in cards.get("v2_mobile", "")
    assert "name: Alert 2 Active" not in cards.get("v2_mobile", "")
    assert "name: Alert light 2" not in cards.get("v2_mobile", "")
    assert "air_bathroom_alert_77" not in cards.get("v2_mobile", "")
    assert "air_bathroom_alert_81" not in cards.get("v2_mobile", "")
    assert "air_bathroom_alert_77" not in cards.get("v2_tablet", "")
    assert "air_bathroom_alert_81" not in cards.get("v2_tablet", "")
    assert "input_boolean.air_isolate_fan_outputs" not in cards.get("v2_mobile", "")
    assert "input_boolean.air_isolate_humidifier_outputs" not in cards.get("v2_mobile", "")
    assert "input_boolean.air_isolate_fan_outputs" not in cards.get("v2_tablet", "")
    assert "input_boolean.air_isolate_humidifier_outputs" not in cards.get("v2_tablet", "")


def test_runtime_lane_order_and_service_simulation():
    engine_mod, _ = _load_target_modules()
    asyncio.run(_run_runtime_assertions(engine_mod))


def test_card_render_sanity_and_placeholder_resolution():
    _, register_mod = _load_target_modules()
    asyncio.run(_run_card_assertions(register_mod))
