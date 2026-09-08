"""Focused v2.0.12 timer lifecycle tests."""

from __future__ import annotations

import asyncio
from functools import partial
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from test_runtime_card_sanity import (
    ENTRY_ID,
    INTEGRATION_ROOT,
    _FakeHass,
    _FakeState,
    _base_entry_data,
    _install_homeassistant_stubs,
    _load_module,
    _load_target_modules,
)

TIMER_PKG = "hi_timer_testpkg"


def _load_timer_sensor_module():
    _install_homeassistant_stubs()

    def mark_callback(func):
        func._hass_callback = True
        return func

    sys.modules["homeassistant.core"].callback = mark_callback
    package = types.ModuleType(TIMER_PKG)
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules[TIMER_PKG] = package
    for sub in ("helpers", "sensors"):
        module = types.ModuleType(f"{TIMER_PKG}.{sub}")
        module.__path__ = [str(INTEGRATION_ROOT / sub)]
        sys.modules[module.__name__] = module

    services = types.ModuleType(f"{TIMER_PKG}.services")
    services._build_diagnostics_summary = lambda *_args, **_kwargs: {}
    sys.modules[services.__name__] = services
    core = types.ModuleType(f"{TIMER_PKG}.sensors.core")
    core.build_entities = lambda *_args, **_kwargs: ([], [], [])
    sys.modules[core.__name__] = core
    slope = types.ModuleType(f"{TIMER_PKG}.sensors.slope")
    slope.build_slope_entities = lambda *_args, **_kwargs: ([], [], {})
    sys.modules[slope.__name__] = slope

    _load_module(f"{TIMER_PKG}.const", INTEGRATION_ROOT / "const.py")

    drift_repairs = types.ModuleType(f"{TIMER_PKG}.helpers.drift_repairs")

    async def async_update_humidity_drift_repair_issue(*_args, **_kwargs):
        return None

    drift_repairs.async_update_humidity_drift_repair_issue = (
        async_update_humidity_drift_repair_issue
    )
    sys.modules[drift_repairs.__name__] = drift_repairs

    level_labels = types.ModuleType(f"{TIMER_PKG}.helpers.level_labels")
    level_labels.resolve_level_label_details = lambda *_args, **_kwargs: {}
    sys.modules[level_labels.__name__] = level_labels

    zone_validation = types.ModuleType(f"{TIMER_PKG}.helpers.zone_validation")
    zone_validation.detect_zone_mapping_duplicates = lambda *_args, **_kwargs: []
    zone_validation.summarize_zone_mapping_duplicate_count_warning = (
        lambda *_args, **_kwargs: None
    )
    sys.modules[zone_validation.__name__] = zone_validation

    return _load_module(f"{TIMER_PKG}.sensor", INTEGRATION_ROOT / "sensor.py")


def _timer_fixture():
    sensor_mod = _load_timer_sensor_module()
    clock = SimpleNamespace(now=datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc))
    scheduled = []

    def async_track_point_in_utc_time(_hass, callback, when):
        record = SimpleNamespace(callback=callback, when=when, cancelled=False)
        scheduled.append(record)

        def cancel():
            record.cancelled = True

        return cancel

    sensor_mod.dt_util.utcnow = lambda: clock.now
    sensor_mod.async_track_point_in_utc_time = async_track_point_in_utc_time

    timer = sensor_mod.HITimerSensor(ENTRY_ID, "air_control_pause")
    timer.hass = object()
    writes = []
    timer.async_write_ha_state = lambda: writes.append(
        (timer.native_value, timer.extra_state_attributes["remaining"])
    )
    return timer, clock, scheduled, writes


def test_timer_publishes_at_bounded_cadence_and_exact_expiry():
    timer, clock, scheduled, writes = _timer_fixture()

    asyncio.run(timer.async_start(timedelta(seconds=125)))
    assert writes == [("active", "00:02:05")]
    assert scheduled[-1].when == clock.now + timedelta(seconds=60)

    clock.now += timedelta(seconds=60)
    scheduled[-1].callback(clock.now)
    assert writes[-1] == ("active", "00:01:05")
    assert scheduled[-1].when == clock.now + timedelta(seconds=60)

    clock.now += timedelta(seconds=60)
    scheduled[-1].callback(clock.now)
    assert writes[-1] == ("active", "00:00:05")
    assert scheduled[-1].when == clock.now + timedelta(seconds=5)

    clock.now += timedelta(seconds=5)
    scheduled[-1].callback(clock.now)
    assert writes[-1] == ("idle", "00:00:00")
    assert timer._cancel_scheduled_update is None
    assert len(writes) == 4


def test_timer_delayed_callback_reschedules_from_actual_utc_without_catch_up_burst():
    timer, clock, scheduled, writes = _timer_fixture()

    asyncio.run(timer.async_start(timedelta(minutes=5)))
    first = scheduled[-1]
    assert first.when == datetime(2026, 9, 4, 8, 1, tzinfo=timezone.utc)

    clock.now = datetime(2026, 9, 4, 8, 3, tzinfo=timezone.utc)
    first.callback(first.when)
    assert writes[-1] == ("active", "00:02:00")
    assert len(writes) == 2
    assert scheduled[-1].when == datetime(
        2026, 9, 4, 8, 4, tzinfo=timezone.utc
    )

    delayed_expiry = scheduled[-1]
    clock.now = datetime(2026, 9, 4, 8, 6, tzinfo=timezone.utc)
    delayed_expiry.callback(delayed_expiry.when)
    assert writes[-1] == ("idle", "00:00:00")
    assert len(writes) == 3
    assert timer._cancel_scheduled_update is None


def test_timer_scheduler_receives_home_assistant_callback_partial():
    timer, _clock, scheduled, _writes = _timer_fixture()

    asyncio.run(timer.async_start(timedelta(minutes=2)))
    scheduled_callback = scheduled[-1].callback

    assert isinstance(scheduled_callback, partial)
    assert scheduled_callback.func.__self__ is timer
    assert scheduled_callback.func.__func__ is type(timer)._handle_scheduled_update
    assert scheduled_callback.func.__func__._hass_callback is True
    assert scheduled_callback.keywords == {"generation": timer._generation}


def test_timer_replacement_and_cancel_invalidate_old_callbacks():
    timer, clock, scheduled, writes = _timer_fixture()

    asyncio.run(timer.async_start(timedelta(minutes=5)))
    first = scheduled[-1]
    clock.now += timedelta(seconds=10)
    asyncio.run(timer.async_start(timedelta(minutes=2)))
    assert first.cancelled is True
    replacement = scheduled[-1]
    write_count = len(writes)

    first.callback(clock.now + timedelta(minutes=5))
    assert len(writes) == write_count
    assert scheduled[-1] is replacement

    asyncio.run(timer.async_cancel())
    assert replacement.cancelled is True
    assert writes[-1] == ("idle", "00:00:00")


def test_timer_removal_cancels_schedule_and_blocks_late_write():
    timer, clock, scheduled, writes = _timer_fixture()

    asyncio.run(timer.async_start(timedelta(minutes=2)))
    active_callback = scheduled[-1]
    asyncio.run(timer.async_will_remove_from_hass())
    assert active_callback.cancelled is True
    write_count = len(writes)

    clock.now += timedelta(minutes=2)
    active_callback.callback(clock.now)
    asyncio.run(timer.async_cancel())
    asyncio.run(timer.async_start(timedelta(minutes=1)))
    assert len(writes) == write_count
    assert timer.native_value == "idle"

    fresh_timer = type(timer)(ENTRY_ID, "air_control_pause")
    assert fresh_timer.native_value == "idle"
    assert fresh_timer.extra_state_attributes["remaining"] == "00:00:00"


def _pause_timer_engine():
    engine_mod, _ = _load_target_modules()
    entry_data = _base_entry_data()
    entry_data["time_gate"] = {
        "enabled": True,
        "start": "00:00",
        "end": "23:59",
        "outside_action": "pause",
    }
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    return engine_mod, engine_mod.HIAutomationEngine(hass, entry)


def test_pause_countdown_attributes_do_not_trigger_engine_evaluation():
    engine_mod, engine = _pause_timer_engine()
    pause_timer = SimpleNamespace(entity_id="sensor.hi_air_control_pause")
    engine.hass.data["humidity_intelligence"][ENTRY_ID]["hi_timers"] = {
        "air_control_pause": pause_timer
    }
    evaluations = []

    async def record_evaluation():
        evaluations.append("evaluate")

    engine.async_request_evaluate = record_evaluation
    asyncio.run(
        engine._handle_change(
            SimpleNamespace(
                data={
                    "entity_id": pause_timer.entity_id,
                    "old_state": _FakeState("active"),
                    "new_state": _FakeState("active"),
                }
            )
        )
    )
    assert evaluations == []

    asyncio.run(
        engine._handle_change(
            SimpleNamespace(
                data={
                    "entity_id": pause_timer.entity_id,
                    "old_state": _FakeState("active"),
                    "new_state": _FakeState("idle"),
                }
            )
        )
    )
    assert evaluations == ["evaluate"]
