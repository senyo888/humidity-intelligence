"""Fault injection across passive Stability capture and canonical runtime."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    ENTRY_ID,
    _FakeHass,
    _FakeState,
    _base_entry_data,
    _load_target_modules,
)
from test_stability_scheduler import _load_sensor_module
from test_stability_score import _load_stability_module, _sample


def _healthy_history(mod):
    ring = mod.StabilitySnapshotRing()
    for index in range(432):
        ring.add(_sample(mod, index))
    return {
        "stability_snapshot_ring": ring,
        "runtime_mode": "normal",
        "config": {"target_profile": "winter"},
        "core_sensors": [
            SimpleNamespace(_attr_unique_id="hi_" + suffix, _attr_native_value=value)
            for suffix, value in (
                ("house_avg_humidity", 50.0),
                ("worst_condensation_risk", "OK"),
                ("worst_mould_risk", "OK"),
            )
        ],
    }


def test_aq_capture_failure_preserves_co_preemption_and_marks_evidence_unavailable():
    engine_mod, _ = _load_target_modules()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {
        "sensor.kitchen_h": _FakeState(50),
        "sensor.hall_h": _FakeState(50),
        "sensor.bed_h": _FakeState(50),
        "sensor.kitchen_t": _FakeState(23),
        "sensor.hall_t": _FakeState(22),
        "sensor.bed_t": _FakeState(21),
        "sensor.l1_iaq": _FakeState(90),
        "sensor.co_val": _FakeState(16),
    })
    engine = engine_mod.HIAutomationEngine(hass, entry)

    def fail_capture():
        raise RuntimeError("injected passive AQ capture failure")

    engine._record_stability_aq_truth = fail_capture
    runtime_data = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime_data["stability_current_air_quality"] = {
        "configured_trigger_count": 1,
        "evaluated_trigger_count": 1,
        "crossed_trigger_count": 0,
    }
    asyncio.run(engine._evaluate())
    assert runtime_data["runtime_mode"] == "co_emergency"
    assert runtime_data["stability_current_air_quality"] == {
        "configured_trigger_count": 0,
        "evaluated_trigger_count": 0,
        "crossed_trigger_count": 0,
    }

    mod = _load_stability_module()
    history = _healthy_history(mod)
    history["stability_current_air_quality"] = runtime_data["stability_current_air_quality"]
    payload = mod.stability_diagnostics_payload(
        history, observed_at=_sample(mod, 431).observed_at,
    )
    assert payload["score"]["display_score"] == 91
    assert payload["caps"]["headline_cap_reason"] == "air_quality_evidence_incomplete"
    history["runtime_mode"] = runtime_data["runtime_mode"]
    emergency = mod.stability_diagnostics_payload(
        history, observed_at=_sample(mod, 431).observed_at,
    )
    assert emergency["score"]["display_score"] == 0
    assert emergency["caps"]["headline_cap_reason"] == "current_co_emergency"


def test_scheduler_capture_exception_rearms_and_breaks_movement_chain():
    registrations = {}
    sensor_mod, _, _ = _load_sensor_module(registrations, [], [])
    mod = _load_stability_module()
    previous_at = _sample(mod, 431).observed_at
    sensor_mod._utc_now = lambda: previous_at
    entry = SimpleNamespace(
        entry_id="entry_fault",
        data={"alert_only_mode": True}, options={},
        async_on_unload=lambda callback: None,
    )
    hass = SimpleNamespace(data={})
    asyncio.run(sensor_mod.async_setup_entry(hass, entry, lambda *_a, **_k: None))
    runtime_data = hass.data["humidity_intelligence"][entry.entry_id]
    runtime_data.update(_healthy_history(mod))
    first = mod.record_stability_score_movement(runtime_data, observed_at=previous_at)
    assert first["status"] == "baseline"
    sensor_mod.record_stability_score_movement = mod.record_stability_score_movement

    def fail_capture(*_args, **_kwargs):
        raise RuntimeError("injected snapshot failure")

    sensor_mod.capture_stability_snapshot = fail_capture
    failed_at = previous_at + timedelta(minutes=10)
    sensor_mod._utc_now = lambda: failed_at
    with pytest.raises(RuntimeError, match="injected snapshot failure"):
        registrations["points"][0]["callback"](failed_at)
    sampling = runtime_data["stability_sampling"]
    assert sampling["last_capture_status"] == "incomplete"
    assert sampling["missed_buckets_since_setup"] == 1
    assert len(runtime_data["stability_snapshot_ring"].samples()) == 432
    failed = mod.stability_diagnostics_payload(runtime_data, observed_at=failed_at)
    assert failed["movement"]["status"] == "unavailable"
    assert failed["movement"]["active_led_steps"] == 0
    assert runtime_data["stability_movement_last_score"] is None
    assert len(registrations["points"]) == 2
    assert registrations["points"][1]["point_in_time"] == failed_at + timedelta(minutes=10)

    recovered_at = failed_at + timedelta(minutes=10)
    sensor_mod._utc_now = lambda: recovered_at
    sensor_mod.capture_stability_snapshot = lambda *_a, **_k: _sample(mod, 433)
    registrations["points"][1]["callback"](recovered_at)
    recovered = runtime_data["stability_score_movement"]
    assert recovered["status"] == "baseline"
    assert recovered["previous_display_score"] is None
    assert recovered["active_led_steps"] == 0
    assert sampling["last_capture_status"] == "captured"
    assert sampling["missed_buckets_since_setup"] == 1
