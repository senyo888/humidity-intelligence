"""Focused wiring tests for the diagnostics-only Stability snapshot scheduler."""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "humidity_intelligence"
PKG = "hi_stability_scheduler_testpkg"
DOMAIN = "humidity_intelligence"


def _load_sensor_module(registrations, captures, repair_updates):
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    for subpackage in ("helpers", "sensors"):
        module = types.ModuleType(f"{PKG}.{subpackage}")
        module.__path__ = [str(ROOT / subpackage)]
        sys.modules[f"{PKG}.{subpackage}"] = module

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    sensor_component = types.ModuleType("homeassistant.components.sensor")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class SensorEntity:
        pass

    class ConfigEntry:
        pass

    class HomeAssistant:
        pass

    class DeviceInfo(dict):
        pass

    def async_track_state_change_event(hass, sources, callback):
        registrations["state"] = {
            "hass": hass,
            "sources": list(sources),
            "callback": callback,
        }
        return lambda: registrations.setdefault("state_unsubscribed", True)

    def async_track_point_in_utc_time(hass, callback, point_in_time):
        registration = {
            "hass": hass,
            "callback": callback,
            "point_in_time": point_in_time,
            "cancelled": False,
        }
        registrations.setdefault("points", []).append(registration)

        def cancel():
            registration["cancelled"] = True

        return cancel

    sensor_component.SensorEntity = SensorEntity
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    util = types.ModuleType("homeassistant.util")
    dt_util = types.ModuleType("homeassistant.util.dt")
    dt_util.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = dt_util
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt_util
    event.async_track_state_change_event = async_track_state_change_event
    event.async_track_point_in_utc_time = async_track_point_in_utc_time
    device_registry.DeviceInfo = DeviceInfo

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.sensor"] = sensor_component
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    const = types.ModuleType(f"{PKG}.const")
    const.DOMAIN = DOMAIN
    sys.modules[f"{PKG}.const"] = const

    drift_repairs = types.ModuleType(f"{PKG}.helpers.drift_repairs")

    async def async_update_humidity_drift_repair_issue(_hass):
        repair_updates.append("updated")

    drift_repairs.async_update_humidity_drift_repair_issue = (
        async_update_humidity_drift_repair_issue
    )
    sys.modules[f"{PKG}.helpers.drift_repairs"] = drift_repairs

    level_labels = types.ModuleType(f"{PKG}.helpers.level_labels")
    level_labels.resolve_level_label_details = lambda *_args, **_kwargs: {}
    sys.modules[f"{PKG}.helpers.level_labels"] = level_labels

    class StabilitySnapshotRing:
        def __init__(self):
            self.items = []
            self.pruned_at = []

        def add(self, snapshot):
            self.items.append(snapshot)
            return True

        def samples(self):
            return list(self.items)

        def prune(self, observed_at):
            self.pruned_at.append(observed_at)

    stability = types.ModuleType(f"{PKG}.helpers.stability")
    from test_stability_score import _load_stability_module
    stability.record_stability_bucket_outcome = _load_stability_module().record_stability_bucket_outcome
    stability.SNAPSHOT_LATE_GRACE_SECONDS = 60
    stability.StabilitySnapshotRing = StabilitySnapshotRing
    stability.bucket_start_for = lambda observed_at: observed_at.replace(
        minute=observed_at.minute - (observed_at.minute % 10),
        second=0,
        microsecond=0,
    )
    stability.next_bucket_boundary_after = lambda observed_at: (
        stability.bucket_start_for(observed_at)
        + __import__("datetime").timedelta(minutes=10)
    )
    stability.crossed_bucket_count = lambda scheduled_at, observed_at: (
        int((observed_at - scheduled_at).total_seconds() // (10 * 60)) + 1
    )
    stability.stability_snapshot_invalid_reasons = lambda _snapshot: []

    def capture_stability_snapshot(
        hass,
        entry,
        runtime_data,
        *,
        observed_at=None,
    ):
        capture = SimpleNamespace(
            hass=hass,
            entry=entry,
            runtime_data=runtime_data,
            observed_at=observed_at,
        )
        captures.append(capture)
        return capture

    stability.capture_stability_snapshot = capture_stability_snapshot
    stability.record_stability_score_movement = (
        lambda runtime_data, *, observed_at: runtime_data.setdefault(
            "movement_recorded_at",
            [],
        ).append(observed_at)
    )
    stability.stability_diagnostics_payload = lambda _runtime_data: {}
    sys.modules[f"{PKG}.helpers.stability"] = stability

    zone_validation = types.ModuleType(f"{PKG}.helpers.zone_validation")
    zone_validation.detect_zone_mapping_duplicates = lambda *_args, **_kwargs: []
    zone_validation.summarize_zone_mapping_duplicate_count_warning = (
        lambda *_args, **_kwargs: {}
    )
    sys.modules[f"{PKG}.helpers.zone_validation"] = zone_validation

    services = types.ModuleType(f"{PKG}.services")
    services._build_diagnostics_summary = lambda *_args, **_kwargs: {}
    sys.modules[f"{PKG}.services"] = services

    class CoreSensor:
        _attr_unique_id = "hi_test_house_avg_humidity"
        _attr_native_value = 50.0

        def __init__(self):
            self.update_calls = 0
            self.write_calls = 0

        def update_from_hass(self):
            self.update_calls += 1

        def async_write_ha_state(self):
            self.write_calls += 1

    class BinarySensor(CoreSensor):
        pass

    core_sensor = CoreSensor()
    binary_sensor = BinarySensor()
    sensors_core = types.ModuleType(f"{PKG}.sensors.core")
    sensors_core.build_entities = lambda _hass, _entry: (
        [core_sensor],
        [binary_sensor],
        ["sensor.primary"],
    )
    sys.modules[f"{PKG}.sensors.core"] = sensors_core

    sensors_slope = types.ModuleType(f"{PKG}.sensors.slope")
    sensors_slope.build_slope_entities = lambda _hass, _entry: (
        [],
        ["sensor.slope"],
        {},
    )
    sys.modules[f"{PKG}.sensors.slope"] = sensors_slope

    module_name = f"{PKG}.sensor"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "sensor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, core_sensor, binary_sensor


def test_setup_registers_fixed_utc_bucket_capture_separate_from_state_updates():
    registrations = {}
    captures = []
    repair_updates = []
    sensor_mod, core_sensor, binary_sensor = _load_sensor_module(
        registrations,
        captures,
        repair_updates,
    )
    setup_at = datetime(2026, 7, 30, 10, 14, 0, tzinfo=timezone.utc)
    sensor_mod._utc_now = lambda: setup_at
    entry = SimpleNamespace(
        entry_id="entry_test",
        data={"alert_only_mode": True},
        options={},
        async_on_unload=lambda callback: registrations.setdefault(
            "entry_unload",
            callback,
        ),
    )
    hass = SimpleNamespace(data={})
    added_entities = []

    asyncio.run(
        sensor_mod.async_setup_entry(
            hass,
            entry,
            lambda entities, **_kwargs: added_entities.extend(entities),
        )
    )

    assert set(registrations) == {"entry_unload", "points", "state"}
    assert set(registrations["state"]["sources"]) == {
        "sensor.primary",
        "sensor.slope",
    }
    assert len(registrations["points"]) == 1
    assert registrations["points"][0]["point_in_time"] == datetime(
        2026,
        7,
        30,
        10,
        20,
        tzinfo=timezone.utc,
    )
    assert captures == []
    assert len(added_entities) == 2
    assert repair_updates == ["updated"]

    asyncio.run(registrations["state"]["callback"](SimpleNamespace()))

    assert captures == []
    assert core_sensor.update_calls == 1
    assert core_sensor.write_calls == 1
    assert binary_sensor.update_calls == 1
    assert binary_sensor.write_calls == 1
    assert repair_updates == ["updated", "updated"]

    observed_at = datetime(2026, 7, 30, 10, 20, tzinfo=timezone.utc)
    sensor_mod._utc_now = lambda: observed_at
    registrations["points"][0]["callback"](
        registrations["points"][0]["point_in_time"]
    )

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    assert len(captures) == 1
    assert captures[0].observed_at == observed_at
    assert runtime_data["stability_snapshot_ring"].samples() == captures
    assert runtime_data["stability_snapshot_unsub"] is not None
    assert runtime_data["stability_sampling"] == {
        "scheduler_active": True,
        "last_capture_status": "captured",
        "last_bucket_start_utc": observed_at.isoformat(),
        "missed_buckets_since_setup": 0,
        "last_invalid_reasons": [],
    }
    assert runtime_data["movement_recorded_at"] == [observed_at]
    assert len(registrations["points"]) == 2
    assert registrations["points"][1]["point_in_time"] == datetime(
        2026,
        7,
        30,
        10,
        30,
        tzinfo=timezone.utc,
    )

    registrations["entry_unload"]()
    assert registrations["points"][0]["cancelled"] is False
    assert registrations["points"][1]["cancelled"] is True
    assert runtime_data["stability_sampling"]["scheduler_active"] is False

    registrations["points"][1]["callback"](
        registrations["points"][1]["point_in_time"]
    )
    assert len(captures) == 1
    assert len(registrations["points"]) == 2


def test_setup_on_ten_minute_boundary_schedules_strictly_future_bucket():
    registrations = {}
    captures = []
    repair_updates = []
    sensor_mod, _, _ = _load_sensor_module(
        registrations,
        captures,
        repair_updates,
    )
    sensor_mod._utc_now = lambda: datetime(
        2026,
        7,
        30,
        10,
        20,
        0,
        200000,
        tzinfo=timezone.utc,
    )
    entry = SimpleNamespace(
        entry_id="entry_boundary",
        data={"alert_only_mode": True},
        options={},
        async_on_unload=lambda callback: registrations.setdefault(
            "entry_unload",
            callback,
        ),
    )
    hass = SimpleNamespace(data={})

    asyncio.run(
        sensor_mod.async_setup_entry(
            hass,
            entry,
            lambda _entities, **_kwargs: None,
        )
    )

    assert captures == []
    assert registrations["points"][0]["point_in_time"] == datetime(
        2026,
        7,
        30,
        10,
        30,
        tzinfo=timezone.utc,
    )


def test_late_scheduler_callback_is_missing_without_backfill():
    registrations = {}
    captures = []
    repair_updates = []
    sensor_mod, _, _ = _load_sensor_module(
        registrations,
        captures,
        repair_updates,
    )
    sensor_mod._utc_now = lambda: datetime(
        2026,
        7,
        30,
        10,
        14,
        tzinfo=timezone.utc,
    )
    entry = SimpleNamespace(
        entry_id="entry_late",
        data={"alert_only_mode": True},
        options={},
        async_on_unload=lambda callback: registrations.setdefault(
            "entry_unload",
            callback,
        ),
    )
    hass = SimpleNamespace(data={})

    asyncio.run(
        sensor_mod.async_setup_entry(
            hass,
            entry,
            lambda _entities, **_kwargs: None,
        )
    )
    sensor_mod._utc_now = lambda: datetime(
        2026,
        7,
        30,
        10,
        30,
        30,
        tzinfo=timezone.utc,
    )
    registrations["points"][0]["callback"](
        registrations["points"][0]["point_in_time"]
    )

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    assert captures == []
    assert len(runtime_data["stability_failed_buckets"]) == 2
    assert runtime_data["stability_snapshot_ring"].samples() == []
    assert runtime_data["stability_sampling"] == {
        "scheduler_active": True,
        "last_capture_status": "late_skipped",
        "last_bucket_start_utc": "2026-07-30T10:20:00+00:00",
        "missed_buckets_since_setup": 2,
        "last_invalid_reasons": [],
    }
    assert runtime_data["stability_snapshot_ring"].pruned_at == [
        datetime(2026, 7, 30, 10, 30, 30, tzinfo=timezone.utc)
    ]
    assert "movement_recorded_at" not in runtime_data
    assert len(registrations["points"]) == 2
    assert registrations["points"][1]["point_in_time"] == datetime(
        2026,
        7,
        30,
        10,
        40,
        tzinfo=timezone.utc,
    )


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print(f"{len(tests)} stability scheduler checks passed.")
