"""Exercise the real Stability builder through live sensor and support export."""

import asyncio
from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    ENTRY_ID, PKG, _DumpCardsConfig, _FakeAuth, _FakeHass, _FakeState,
    _FlashServiceRegistry, _load_sensor_platform_module,
)
from test_stability_score import _sample


@pytest.mark.parametrize("sample_count", [1, 432])
@pytest.mark.parametrize("export_report", [False, True], ids=["live_sensor", "support_export"])
def test_real_builder_reaches_live_diagnostics_and_dump(sample_count, export_report, monkeypatch, tmp_path):
    sensor_module = _load_sensor_platform_module()
    services = sys.modules[f"{PKG}.services"]
    stability = sys.modules[f"{PKG}.helpers.stability"]
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(stability, "datetime", FixedDatetime)
    monkeypatch.setattr(sensor_module, "_utc_now", lambda: now)
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={"target_profile": "winter",
        "telemetry": [{"entity_id": "sensor.example_co2", "sensor_type": "co2", "level": "level1"}],
        "aq": {"level1": {"enabled": True, "triggers": ["co2_high"], "thresholds": {"co2_high": 1200}}},
    }, options={})
    hass = _FakeHass(entry, {"sensor.example_co2": _FakeState(800, {"unit_of_measurement": "ppm"})})
    hass.config = _DumpCardsConfig(str(tmp_path))
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    runtime = hass.data[services.DOMAIN][ENTRY_ID]
    runtime.update({
        "config": entry.data,
        "options": {},
        "runtime_mode": "normal",
        "core_sensors": [
            SimpleNamespace(_attr_unique_id=f"hi_{suffix}", _attr_native_value=value)
            for suffix, value in (
                ("house_avg_humidity", 50),
                ("worst_condensation_risk", "OK"),
                ("worst_mould_risk", "OK"),
            )
        ],
        "stability_current_air_quality": {
            "configured_trigger_count": 1,
            "evaluated_trigger_count": 1,
            "crossed_trigger_count": 0,
        },
        "stability_snapshot_ring": stability.StabilitySnapshotRing(),
    })
    for index in range(sample_count):
        runtime["stability_snapshot_ring"].add(_sample(
            stability, index,
            observed_at=now - timedelta(minutes=10 * (sample_count - 1 - index)),
        ))

    runtime["stability_failed_buckets"] = set()
    if sample_count == 1:
        # A real failed bucket reaches the sensor through the shared builder.
        failed_at = FixedDatetime(2026, 9, 19, 11, 50, tzinfo=timezone.utc)
        stability.record_stability_bucket_outcome(runtime, failed_at, now)

    sensor = sensor_module.HIDiagnosticsSensor(hass, ENTRY_ID)
    sensor.update()
    live = sensor._attr_extra_state_attributes["stability_score"]
    legacy = sensor._attr_extra_state_attributes["diagnostics_summary"]["stability_score"]
    assert "stability_score" in sensor._unrecorded_attributes
    assert "diagnostics_summary" not in sensor._unrecorded_attributes
    assert "score_history" in live
    assert not {"score_history", "published_at", "explanation", "aq_selection", "aq_adjustment"}.intersection(legacy)
    assert legacy["score"] == live["score"]
    assert live["schema"] == 3
    assert live["window"]["valid_samples"] == sample_count
    assert live["window"]["expected_samples"] == 432
    assert live["presentation"]["card_label"] == (
        "Collecting baseline" if sample_count == 1 else "Stability Score"
    )
    assert live["presentation"]["primary_text"] == ("1" if sample_count == 1 else "97")
    assert live["score"]["display_score"] == (None if sample_count == 1 else 97)
    assert live["presentation"]["detail_text"] in sensor._attr_extra_state_attributes["Stability Score"]
    assert f"Window: {sample_count}/432 valid snapshots over 72 hours." in sensor._attr_extra_state_attributes["Stability Score"]

    history = live["sampling"]["failure_history"]
    assert history["status"] == "available"
    assert history["failed_bucket_count"] == (1 if sample_count == 1 else 0)
    assert len(history["marker_angles_degrees"]) == history["failed_bucket_count"]
    readable = sensor._attr_extra_state_attributes["Stability Score"]
    assert f"Unsuccessful collections: {history['failed_bucket_count']} scheduled buckets" in readable
    if sample_count == 1:
        assert "Baseline progress: 1 of 303 valid samples." in readable

    if not export_report:
        return

    # Keep actual registration, authorization, shared builder, support sanitization,
    # and redaction; intercept only external local-version inspection and file IO.
    async def local_versions(_hass):
        return {"status": "not_configured"}

    written = {}
    monkeypatch.setattr(services, "async_local_version_status", local_versions)
    monkeypatch.setattr(services, "write_owned_report", lambda _root, _name, payload: written.update(payload))
    asyncio.run(services.async_register_services(hass))
    dump = hass.services.handlers[(services.DOMAIN, services.SERVICE_DUMP_DIAGNOSTICS)]
    asyncio.run(dump(SimpleNamespace(
        data={"entry_id": ENTRY_ID}, context=SimpleNamespace(user_id="admin"),
    )))
    # The accepted source exports Stability through native diagnostics and the
    # live sensor; its service support allowlist intentionally stays unchanged.
    assert "stability_score" not in written[ENTRY_ID]["diagnostics_summary"]
