"""Direct contract tests for Phase 2B windowed Stability Score."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone
from math import ceil


ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "humidity_intelligence"
PKG = "hi_stability_testpkg"


def _install_package_scaffold() -> None:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    helpers = types.ModuleType(f"{PKG}.helpers")
    helpers.__path__ = [str(ROOT / "helpers")]
    sys.modules[f"{PKG}.helpers"] = helpers


def _load_stability_module():
    _install_package_scaffold()
    module_name = f"{PKG}.helpers.stability"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "helpers" / "stability.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _sample(mod, idx: int, **overrides):
    base = {
        "observed_at": datetime(2026, 6, 14, tzinfo=timezone.utc)
        + timedelta(minutes=mod.BUCKET_MINUTES * idx),
        "house_humidity": 50.0,
        "target_low": 45.0,
        "target_high": 55.0,
        "worst_condensation_state": "OK",
        "worst_mould_state": "OK",
        "room_or_level_humidity_spread": 2.0,
        "house_humidity_drift_7d": 1.0,
        "runtime_mode": "normal",
        "required_telemetry_available": True,
        "balance_scope": "room",
        "balance_source_count": 2,
        "air_quality_clearance": 1.0,
        "air_quality_configured_condition_count": 1,
        "air_quality_evaluated_condition_count": 1,
        "air_quality_bad_condition_count": 0,
        "air_quality_telemetry_source_count": 1,
        "air_quality_source_count": 1,
        "air_quality_available_source_count": 1,
    }
    base.update(overrides)
    return mod.StabilitySnapshot(**base)


def test_insufficient_coverage_is_unavailable():
    mod = _load_stability_module()
    result = mod.evaluate_stability_window([_sample(mod, idx) for idx in range(300)])

    assert result["score"]["score_status"] == "unavailable"
    assert result["availability"] == "insufficient_coverage"
    assert result["score"]["display_score"] is None
    assert result["score"]["suppression_reason"] == "coverage_below_threshold"
    assert "fewer than 303 valid HI-owned 10-minute snapshots" in result["message"]
    assert result["presentation"] == {
        "state_code": "collecting",
        "card_label": "Collecting baseline",
        "primary_text": "300",
        "compact_text": "OF 303",
        "detail_text": result["message"],
        "tone": "collecting",
        "indicator_mode": "collection",
        "progress_ratio": 0.9901,
        "cap_applied": False,
    }


def test_valid_coverage_excellent_has_no_caps():
    mod = _load_stability_module()
    samples = [_sample(mod, idx, room_or_level_humidity_spread=1.5) for idx in range(432)]

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["score_status"] == "available"
    assert result["score"]["display_classification"] == "Excellent"
    assert result["caps"]["classification_cap_applied"] is False
    assert result["control_contract"]["lane_selection_input"] is False


def test_full_environmental_formula_includes_air_quality_at_fifteen_percent():
    mod = _load_stability_module()
    samples = [
        _sample(mod, idx, air_quality_clearance=0.5)
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["formula_version"] == 4
    assert result["score_basis"] == "full_environmental"
    assert result["subscores"]["air_quality_clearance_score"] == 0.5
    assert result["score"]["raw_score"] == 79.5
    assert result["penalties"]["air_quality_evidence_penalty_points"] == 0.0
    assert result["environmental_evidence"] == "complete"


def test_no_aq_hardware_renormalizes_once_and_caps_good():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            air_quality_clearance=None,
            air_quality_configured_condition_count=0,
            air_quality_evaluated_condition_count=0,
            air_quality_telemetry_source_count=0,
            air_quality_source_count=0,
            air_quality_available_source_count=0,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["score_basis"] == "non_aq_renormalized"
    assert result["environmental_evidence"] == "no_aq_hardware"
    assert result["penalties"]["air_quality_evidence_penalty_points"] == 3.0
    assert result["score"]["display_score"] == 91
    assert result["score"]["display_classification"] == "Good"
    assert result["caps"]["headline_cap_reason"] == "air_quality_evidence_incomplete"
    assert result["presentation"]["compact_text"] == "PARTIAL"
    assert result["presentation"]["tone"] == "incomplete"


def test_configured_but_unmapped_aq_is_distinct_from_no_hardware():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            air_quality_clearance=None,
            air_quality_configured_condition_count=0,
            air_quality_evaluated_condition_count=0,
            air_quality_telemetry_source_count=1,
            air_quality_source_count=0,
            air_quality_available_source_count=0,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["environmental_evidence"] == "configured_unmapped"
    assert result["score"]["display_score"] == 91
    assert "AQ evidence is incomplete" in result["message"]


def test_sufficient_partial_aq_coverage_is_scored_with_proportional_penalty():
    mod = _load_stability_module()
    samples = []
    for idx in range(432):
        if idx < 129:
            samples.append(
                _sample(
                    mod,
                    idx,
                    air_quality_clearance=None,
                    air_quality_evaluated_condition_count=0,
                    air_quality_available_source_count=0,
                )
            )
        else:
            samples.append(_sample(mod, idx))

    result = mod.evaluate_stability_window(samples)

    assert result["environmental_evidence"] == "partial"
    assert result["score_basis"] == "full_environmental"
    assert result["component_coverage"]["air_quality"]["coverage_ratio"] == 0.7014
    assert result["penalties"]["air_quality_evidence_penalty_points"] == 2.99
    assert result["presentation"]["compact_text"] == "PARTIAL"


def test_aq_coverage_below_seventy_percent_uses_fallback():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            air_quality_clearance=None if idx < 130 else 1.0,
            air_quality_evaluated_condition_count=0 if idx < 130 else 1,
            air_quality_available_source_count=0 if idx < 130 else 1,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["environmental_evidence"] == "insufficient_window_coverage"
    assert result["score_basis"] == "non_aq_renormalized"
    assert result["penalties"]["air_quality_evidence_penalty_points"] == 3.0
    assert result["score"]["display_score"] == 91


def test_current_and_recent_routine_aq_use_bounded_adjustment_without_hard_caps():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-2] = _sample(
        mod,
        430,
        air_quality_clearance=0.0,
        air_quality_bad_condition_count=1,
        air_quality_bad_trigger_codes=("pm25_high",),
    )

    current = mod.evaluate_stability_window(samples, current_air_quality_bad=True)
    recent = mod.evaluate_stability_window(samples, current_air_quality_bad=False)

    assert current["score"]["display_score"] == 85
    assert current["aq_adjustment"]["points"] == 12
    assert current["caps"]["headline_cap_reason"] is None
    assert recent["score"]["display_score"] == 85
    assert recent["aq_adjustment"]["points"] == 12
    assert recent["caps"]["headline_cap_reason"] is None


def test_recent_aq_cap_expires_against_current_evaluation_bucket():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-1] = _sample(
        mod,
        431,
        air_quality_clearance=0.0,
        air_quality_bad_condition_count=1,
    )
    observed_at = samples[-1].observed_at + timedelta(hours=13)

    result = mod.evaluate_stability_window(
        samples,
        current_air_quality_bad=False,
        observed_at=observed_at,
    )

    assert "recent_air_quality_bad_12h" not in result["caps"]["classification_cap_reasons"]


def test_current_co_emergency_is_strongest_zero_cap():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]

    result = mod.evaluate_stability_window(
        samples,
        current_air_quality_bad=True,
        current_co_emergency=True,
    )

    assert result["score"]["window_score"] > 80
    assert result["score"]["display_score"] == 0
    assert result["score"]["display_classification"] == "Poor"
    assert result["caps"]["headline_cap_reason"] == "current_co_emergency"
    assert result["caps"]["score_cap_ceiling"] == 0


def test_live_aq_truth_outranks_partial_evidence_even_below_score_cap():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            house_humidity=70.0,
            room_or_level_humidity_spread=20.0,
            house_humidity_drift_7d=10.0,
            air_quality_clearance=None if idx < 129 else 0.0,
            air_quality_evaluated_condition_count=0 if idx < 129 else 1,
            air_quality_available_source_count=0 if idx < 129 else 1,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(
        samples,
        current_air_quality_bad=True,
    )

    assert result["score"]["window_score"] < 54
    assert result["caps"]["score_cap_applied"] is False
    assert result["caps"]["headline_cap_reason"] is None
    assert result["aq_adjustment"]["points"] == 12
    assert "selected air-quality threshold is currently crossed" in result["message"]
    assert result["presentation"]["compact_text"] == "POOR"
    assert result["presentation"]["tone"] == "poor"
    assert result["presentation"]["evidence_status"] == "partial"


def test_live_co_truth_outranks_partial_evidence_even_at_zero_score():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            house_humidity=30.0 if idx % 2 else 70.0,
            worst_condensation_state="Danger",
            worst_mould_state="Danger",
            room_or_level_humidity_spread=30.0,
            house_humidity_drift_7d=10.0,
            air_quality_clearance=None if idx < 129 else 0.0,
            air_quality_evaluated_condition_count=0 if idx < 129 else 1,
            air_quality_available_source_count=0 if idx < 129 else 1,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(
        samples,
        current_air_quality_bad=True,
        current_co_emergency=True,
    )

    assert result["score"]["window_score"] == 0
    assert result["caps"]["score_cap_applied"] is False
    assert result["caps"]["headline_cap_reason"] == "current_co_emergency"
    assert "backend CO-emergency state is active" in result["message"]
    assert result["presentation"]["compact_text"] == "POOR"
    assert result["presentation"]["tone"] == "poor"
    assert result["presentation"]["evidence_status"] == "partial"


def test_aq_capture_matches_all_engine_directions_and_equality():
    mod = _load_stability_module()

    class States:
        def __init__(self, values):
            self.values = values

        def get(self, entity_id):
            value, unit = self.values[entity_id]
            return types.SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
            )

    telemetry = [
        {"entity_id": "sensor.iaq", "sensor_type": "iaq", "level": "level1"},
        {"entity_id": "sensor.pm25", "sensor_type": "pm25", "level": "level1"},
        {"entity_id": "sensor.voc", "sensor_type": "voc", "level": "level1"},
        {"entity_id": "sensor.co2", "sensor_type": "co2", "level": "level1"},
        {"entity_id": "sensor.co", "sensor_type": "co", "level": "level1"},
        {"entity_id": "sensor.pm25", "sensor_type": "pm25", "level": "level1"},
    ]
    config = {
        "telemetry": telemetry,
        "aq": {
            "level1": {
                "enabled": True,
                "triggers": ["iaq_bad", "pm25_high", "voc_bad", "co2_high", "co_warning"],
                "thresholds": {
                    "iaq_bad": 75,
                    "pm25_high": 35,
                    "voc_bad": 600,
                    "co2_high": 1200,
                    "co_warning": 15,
                },
            }
        },
    }
    hass = types.SimpleNamespace(
        states=States(
            {
                "sensor.iaq": (75, None),
                "sensor.pm25": (35, "µg/m³"),
                "sensor.voc": (600, "ppb"),
                "sensor.co2": (1200, "ppm"),
                "sensor.co": (15, "ppm"),
            }
        )
    )

    evidence = mod._air_quality_from_config(hass, config)

    assert evidence["configured_trigger_count"] == 5
    assert evidence["evaluated_trigger_count"] == 5
    assert evidence["bad_trigger_count"] == 5
    assert evidence["telemetry_source_count"] == 5
    assert evidence["expected_source_count"] == 5
    assert evidence["clearance"] == 0.0

    config["aq"]["level1"]["enabled"] = False
    disabled = mod._air_quality_from_config(hass, config)
    assert disabled["configured_trigger_count"] == 0
    assert disabled["telemetry_source_count"] == 5


def test_aq_capture_balances_levels_and_respects_distinct_thresholds():
    mod = _load_stability_module()
    states = {
        "sensor.l1_iaq": types.SimpleNamespace(
            state="70", attributes={"unit_of_measurement": None}
        ),
        "sensor.l1_pm25": types.SimpleNamespace(
            state="5", attributes={"unit_of_measurement": "ug/m3"}
        ),
        "sensor.l2_iaq": types.SimpleNamespace(
            state="70", attributes={"unit_of_measurement": None}
        ),
    }
    hass = types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda entity_id: states.get(entity_id))
    )
    config = {
        "telemetry": [
            {"entity_id": "sensor.l1_iaq", "sensor_type": "iaq", "level": "level1"},
            {"entity_id": "sensor.l1_pm25", "sensor_type": "pm25", "level": "level1"},
            {"entity_id": "sensor.l2_iaq", "sensor_type": "iaq", "level": "level2"},
        ],
        "aq": {
            "level1": {
                "enabled": True,
                "outputs": [],
                "triggers": ["iaq_bad", "pm25_high"],
                "thresholds": {"iaq_bad": 75, "pm25_high": 35},
            },
            "level2": {
                "enabled": True,
                "outputs": [],
                "triggers": ["iaq_bad"],
                "thresholds": {"iaq_bad": 60},
            },
        },
    }

    evidence = mod._air_quality_from_config(hass, config)

    assert evidence["configured_trigger_count"] == 3
    assert evidence["evaluated_trigger_count"] == 3
    assert evidence["bad_trigger_count"] == 1
    assert evidence["clearance"] == 0.75


def test_unsupported_voc_unit_is_incomplete_not_bad():
    mod = _load_stability_module()
    state = types.SimpleNamespace(
        state="0.6",
        attributes={"unit_of_measurement": "ppm"},
    )
    hass = types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda _entity_id: state)
    )
    config = {
        "telemetry": [
            {"entity_id": "sensor.voc", "sensor_type": "voc", "level": "level1"},
        ],
        "aq": {
            "level1": {
                "enabled": True,
                "triggers": ["voc_bad"],
                "thresholds": {"voc_bad": 600},
            }
        },
    }

    evidence = mod._air_quality_from_config(hass, config)

    assert evidence["configured_trigger_count"] == 1
    assert evidence["evaluated_trigger_count"] == 0
    assert evidence["bad_trigger_count"] == 0
    assert evidence["unit_invalid_source_count"] == 1
    assert evidence["clearance"] is None

    samples = [
        _sample(
            mod,
            idx,
            air_quality_clearance=None,
            air_quality_evaluated_condition_count=0,
            air_quality_available_source_count=0,
            air_quality_unit_invalid_source_count=1,
        )
        for idx in range(432)
    ]
    result = mod.evaluate_stability_window(samples)
    assert result["environmental_evidence"] == "unsupported_unit"
    assert result["score"]["display_score"] == 91
    assert result["caps"]["headline_cap_reason"] == "air_quality_evidence_incomplete"


def test_missing_data_above_threshold_applies_visible_penalty():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(360)]

    result = mod.evaluate_stability_window(samples)

    assert result["window"]["valid_samples"] == 360
    assert result["penalties"]["coverage_penalty_points"] == 1.67
    assert "1.67-point coverage penalty" in result["message"]


def test_recent_danger_12h_caps_score_and_classification_to_unstable():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-20] = _sample(mod, 412, worst_condensation_state="Danger")

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["raw_score"] is not None
    assert result["score"]["raw_classification"] == "Excellent"
    assert result["score"]["window_classification"] == "Excellent"
    assert result["score"]["display_score"] == 69
    assert result["score"]["display_classification"] == "Unstable"
    assert result["caps"]["score_cap_applied"] is True
    assert "recent_condensation_danger_12h" in result["caps"]["classification_cap_reasons"]


def test_current_danger_caps_score_and_classification_to_poor():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-1] = _sample(mod, 431, worst_mould_state="Danger")

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["raw_score"] is not None
    assert result["score"]["raw_classification"] == "Excellent"
    assert result["score"]["display_score"] == 54
    assert result["score"]["display_classification"] == "Poor"
    assert result["caps"]["headline_cap_reason"] == "current_mould_danger"
    assert result["presentation"]["cap_applied"] is True
    assert "Calculated score" in result["message"]


def test_mould_risk_duration_24h_caps_good_independently():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    for idx in range(417, 432):
        samples[idx] = _sample(mod, idx, worst_mould_state="Risk")

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["display_classification"] == "Good"
    assert result["score"]["display_score"] == 91
    assert result["caps"]["classification_cap_reasons"] == ["mould_risk_duration_24h"]


def test_condensation_risk_duration_24h_caps_good_independently():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    for idx in range(417, 432):
        samples[idx] = _sample(mod, idx, worst_condensation_state="Risk")

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["display_classification"] == "Good"
    assert result["score"]["display_score"] == 91
    assert result["caps"]["classification_cap_reasons"] == [
        "condensation_risk_duration_24h"
    ]


def test_drift_unavailable_above_threshold_is_penalized_not_suppressed():
    mod = _load_stability_module()
    samples = [_sample(mod, idx, house_humidity_drift_7d=None) for idx in range(432)]

    result = mod.evaluate_stability_window(samples)

    assert result["score"]["score_status"] == "available"
    assert result["penalties"]["drift_unavailable_penalty_points"] == 3.0
    assert result["drift_component_status"] == "unavailable_penalized"


def test_open_recovery_event_is_capped_at_12h():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    for idx in range(330, 432):
        samples[idx] = _sample(mod, idx, house_humidity=60.0)

    result = mod.evaluate_stability_window(samples)

    assert result["recovery"]["open_event_capped"] is True
    assert result["recovery"]["open_event_duration_used_hours"] == 12.0
    assert result["subscores"]["recovery_score"] == 0.0


def test_current_telemetry_unavailable_suppresses_historic_score():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]

    result = mod.evaluate_stability_window(
        samples,
        current_runtime_mode="telemetry_unavailable",
    )

    assert result["availability"] == "suppressed"
    assert result["score"]["score_status"] == "unavailable"
    assert result["score"]["suppression_reason"] == "current_telemetry_unavailable"
    assert result["score"]["display_score"] is None
    assert result["presentation"]["card_label"] == "Live data unavailable"
    assert result["message"] == (
        "Stability Score unavailable: required live telemetry is unavailable. "
        "Historic window coverage is not used while HI is standing down."
    )


def test_no_consecutive_samples_is_unavailable():
    mod = _load_stability_module()
    indices = list(range(0, 432, 2)) + list(range(1, 174, 2))
    samples = [_sample(mod, idx) for idx in sorted(indices)]

    result = mod.evaluate_stability_window(samples)

    assert result["availability"] == "suppressed"
    assert result["score"]["suppression_reason"] == "insufficient_consecutive_samples"
    assert result["presentation"]["compact_text"] == "GAPS"
    assert result["presentation"]["card_label"] == "Evidence gaps"
    assert result["presentation"]["tone"] == "incomplete"


def test_insufficient_balance_sources_is_unavailable():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            room_or_level_humidity_spread=2.0 if idx < 200 else None,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["availability"] == "suppressed"
    assert result["score"]["suppression_reason"] == "insufficient_balance_sources"
    assert result["presentation"]["compact_text"] == "BALANCE"
    assert result["presentation"]["card_label"] == "Balance evidence"
    assert result["presentation"]["tone"] == "incomplete"


def test_bucket_start_uses_fixed_10_minute_boundaries():
    mod = _load_stability_module()
    observed = datetime(2026, 6, 14, 10, 29, 59, tzinfo=timezone.utc)

    assert mod.bucket_start_for(observed) == datetime(
        2026, 6, 14, 10, 20, tzinfo=timezone.utc
    )


def test_next_bucket_boundary_is_strictly_after_exact_boundary():
    mod = _load_stability_module()
    observed = datetime(2026, 7, 30, 10, 20, tzinfo=timezone.utc)

    assert mod.next_bucket_boundary_after(observed) == datetime(
        2026,
        7,
        30,
        10,
        30,
        tzinfo=timezone.utc,
    )


def test_crossed_bucket_count_includes_scheduled_and_current_boundaries():
    mod = _load_stability_module()
    scheduled = datetime(2026, 7, 30, 10, 10, tzinfo=timezone.utc)

    assert mod.crossed_bucket_count(
        scheduled,
        datetime(2026, 7, 30, 10, 11, 1, tzinfo=timezone.utc),
    ) == 1
    assert mod.crossed_bucket_count(
        scheduled,
        datetime(2026, 7, 30, 10, 20, 30, tzinfo=timezone.utc),
    ) == 2


def test_ring_keeps_last_complete_observation_in_bucket():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    first = _sample(mod, 0, house_humidity=49.0)
    later = _sample(mod, 0, observed_at=first.observed_at + timedelta(minutes=5), house_humidity=51.0)

    ring.add(first)
    ring.add(later)

    assert ring.samples()[0].house_humidity == 51.0


def test_incomplete_observation_does_not_replace_complete_bucket():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    complete = _sample(mod, 0, house_humidity=49.0)
    incomplete = _sample(
        mod,
        0,
        observed_at=complete.observed_at + timedelta(minutes=5),
        house_humidity=None,
    )

    ring.add(complete)
    ring.add(incomplete)

    assert ring.samples()[0].house_humidity == 49.0


def test_incomplete_observation_leaves_empty_bucket_missing():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    incomplete = _sample(mod, 0, house_humidity=None)

    stored = ring.add(incomplete)

    assert stored is False
    assert ring.samples() == []


def test_invalid_observation_still_prunes_expired_buckets():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))

    stored = ring.add(_sample(mod, 450, house_humidity=None))

    assert stored is False
    assert ring.samples()[0].observed_at == _sample(mod, 19).observed_at


def test_ring_retains_only_72h_window():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(450):
        ring.add(_sample(mod, idx))

    assert len(ring.samples()) == 432
    assert ring.samples()[0].observed_at == _sample(mod, 18).observed_at


def test_capture_uses_fixed_scheduler_observation_time():
    mod = _load_stability_module()
    observed_at = datetime(2026, 7, 30, 10, 20, tzinfo=timezone.utc)
    runtime_data = {
        "core_sensors": [],
        "runtime_mode": "normal",
    }

    snapshot = mod.capture_stability_snapshot(
        types.SimpleNamespace(states=None),
        types.SimpleNamespace(data={}, options={}),
        runtime_data,
        observed_at=observed_at,
    )

    assert snapshot is not None
    assert snapshot.observed_at == observed_at


def test_diagnostics_declares_fixed_bucket_snapshot_provenance():
    mod = _load_stability_module()

    result = mod.stability_diagnostics_payload(
        {
            "stability_snapshot_ring": mod.StabilitySnapshotRing(),
            "runtime_mode": "normal",
        }
    )

    assert result["snapshot"] == {
        "source": "hi_owned_fixed_bucket",
        "schedule": "utc_ten_minute",
        "representative": "last_complete_scheduled_observation",
        "capture_minutes_utc": [0, 10, 20, 30, 40, 50],
    }
    failure_history = result["sampling"].pop("failure_history")
    assert failure_history["failed_bucket_count"] == 0
    assert failure_history["marker_angles_degrees"] == []
    assert result["sampling"] == {
        "source_schema_version": 2,
        "snapshot_source": "hi_owned_fixed_bucket",
        "alignment": "utc_ten_minute",
        "interval_minutes": 10,
        "late_grace_seconds": 60,
        "scheduler_active": False,
        "last_capture_status": "pending",
        "last_bucket_start_utc": None,
        "missed_buckets_since_setup": 0,
        "last_invalid_reasons": [],
    }


def test_classification_bands_start_excellent_at_92():
    mod = _load_stability_module()

    assert mod._classification(100) == "Excellent"
    assert mod._classification(92) == "Excellent"
    assert mod._classification(91) == "Good"
    assert mod._classification(70) == "Good"
    assert mod._classification(69) == "Unstable"
    assert mod._classification(55) == "Unstable"
    assert mod._classification(54) == "Poor"
    assert mod._classification(0) == "Poor"


def test_live_current_danger_caps_before_next_bucket():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]

    result = mod.evaluate_stability_window(
        samples,
        current_condensation_state="OK",
        current_mould_state="Danger",
    )

    assert result["score"]["window_classification"] == "Excellent"
    assert result["score"]["display_score"] == 54
    assert result["score"]["display_classification"] == "Poor"
    assert result["caps"]["headline_cap_reason"] == "current_mould_danger"


def test_live_clear_state_downgrades_latest_bucket_danger_to_recent_cap():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-1] = _sample(mod, 431, worst_mould_state="Danger")

    result = mod.evaluate_stability_window(
        samples,
        current_condensation_state="OK",
        current_mould_state="OK",
    )

    assert result["score"]["display_score"] == 69
    assert result["score"]["display_classification"] == "Unstable"
    assert result["caps"]["headline_cap_reason"] == "recent_mould_danger_12h"


def test_risk_clearance_weights_components_equally():
    mod = _load_stability_module()
    samples = [
        _sample(mod, idx, house_humidity_drift_7d=9.0)
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["subscores"]["risk_clearance_score"] == 0.6667
    assert result["subscores"]["risk_clearance_components"] == {
        "condensation": 1.0,
        "mould": 1.0,
        "drift": 0.0,
    }


def test_sparse_drift_is_unavailable_penalized_not_equal_weighted():
    mod = _load_stability_module()
    samples = [
        _sample(
            mod,
            idx,
            house_humidity_drift_7d=9.0 if idx == 431 else None,
        )
        for idx in range(432)
    ]

    result = mod.evaluate_stability_window(samples)

    assert result["drift_component_status"] == "unavailable_penalized"
    assert result["penalties"]["drift_unavailable_penalty_points"] == 3.0
    assert result["subscores"]["risk_clearance_score"] == 1.0
    assert result["subscores"]["risk_clearance_components"]["drift"] is None
    assert result["component_coverage"]["drift"]["status"] == "insufficient"


def test_non_finite_required_values_and_reversed_targets_are_invalid():
    mod = _load_stability_module()

    assert mod.stability_snapshot_invalid_reasons(
        _sample(mod, 0, house_humidity=float("nan"))
    ) == ["house_humidity_invalid"]
    assert mod.stability_snapshot_invalid_reasons(
        _sample(mod, 0, target_low=55.0, target_high=45.0)
    ) == ["target_bounds_invalid"]
    assert mod.stability_snapshot_invalid_reasons(
        _sample(mod, 0, target_low=float("inf"))
    ) == ["target_bounds_invalid"]


def test_explicit_prune_removes_expired_history_without_new_sample():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))

    ring.prune(_sample(mod, 450).observed_at)

    assert ring.samples()[0].observed_at == _sample(mod, 19).observed_at


def test_runtime_live_risk_states_feed_diagnostics_cap():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))
    sensors = [
        types.SimpleNamespace(
            _attr_unique_id="hi_house_avg_humidity",
            _attr_native_value=50.0,
        ),
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_condensation_risk",
            _attr_native_value="OK",
        ),
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_mould_risk",
            _attr_native_value="Danger",
        ),
    ]

    result = mod.stability_diagnostics_payload(
        {
            "stability_snapshot_ring": ring,
            "runtime_mode": "normal",
            "core_sensors": sensors,
            "config": {"target_profile": "winter"},
        },
        observed_at=_sample(mod, 431).observed_at,
    )

    assert result["score"]["display_score"] == 54
    assert result["caps"]["headline_cap_reason"] == "current_mould_danger"


def test_historic_danger_cap_expires_against_current_evaluation_time():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-1] = _sample(mod, 431, worst_mould_state="Danger")

    result = mod.evaluate_stability_window(
        samples,
        current_condensation_state="OK",
        current_mould_state="OK",
        observed_at=_sample(mod, 431).observed_at + timedelta(hours=21),
    )

    assert result["availability"] == "available"
    assert result["window"]["valid_samples"] == 306
    assert "recent_mould_danger_12h" not in result["caps"]["classification_cap_reasons"]
    assert result["score"]["display_classification"] == "Excellent"


def test_sparse_recent_risk_does_not_inflate_duration_cap():
    mod = _load_stability_module()
    samples = [_sample(mod, idx) for idx in range(432)]
    samples[-2] = _sample(mod, 430, worst_mould_state="Risk")
    samples[-1] = _sample(mod, 431, worst_mould_state="Risk")

    result = mod.evaluate_stability_window(
        samples,
        current_condensation_state="OK",
        current_mould_state="OK",
        observed_at=_sample(mod, 431).observed_at + timedelta(hours=21),
    )

    assert "mould_risk_duration_24h" not in result["caps"]["classification_cap_reasons"]


def test_invalid_or_missing_live_risk_truth_suppresses_historic_score():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))
    common = [
        types.SimpleNamespace(
            _attr_unique_id="hi_house_avg_humidity",
            _attr_native_value=50.0,
        ),
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_condensation_risk",
            _attr_native_value="OK",
        ),
    ]
    for mould_sensor in (
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_mould_risk",
            _attr_native_value="Unknown",
        ),
        None,
    ):
        sensors = common + ([mould_sensor] if mould_sensor is not None else [])
        result = mod.stability_diagnostics_payload(
            {
                "stability_snapshot_ring": ring,
                "runtime_mode": "normal",
                "core_sensors": sensors,
                "config": {"target_profile": "winter"},
            },
            observed_at=_sample(mod, 431).observed_at,
        )

        assert result["availability"] == "suppressed"
        assert result["score"]["suppression_reason"] == "current_telemetry_unavailable"
        assert "mould_state_invalid" in result["live_truth"]["invalid_reasons"]


def test_invalid_current_custom_targets_suppress_historic_score():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))
    sensors = [
        types.SimpleNamespace(
            _attr_unique_id="hi_house_avg_humidity",
            _attr_native_value=50.0,
        ),
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_condensation_risk",
            _attr_native_value="OK",
        ),
        types.SimpleNamespace(
            _attr_unique_id="hi_worst_mould_risk",
            _attr_native_value="OK",
        ),
    ]

    result = mod.stability_diagnostics_payload(
        {
            "stability_snapshot_ring": ring,
            "runtime_mode": "normal",
            "core_sensors": sensors,
            "config": {
                "target_profile": "custom",
                "custom_target_low": 60.0,
                "custom_target_high": 40.0,
            },
        },
        observed_at=_sample(mod, 431).observed_at,
    )

    assert result["availability"] == "suppressed"
    assert "target_bounds_invalid" in result["live_truth"]["invalid_reasons"]


def test_balance_requires_two_distinct_configured_scopes():
    mod = _load_stability_module()

    class States:
        def get(self, entity_id):
            return types.SimpleNamespace(state={
                "sensor.same": "50",
                "sensor.other": "54",
            }.get(entity_id))

    duplicate_config = {
        "telemetry": [
            {"sensor_type": "humidity", "entity_id": "sensor.same", "room": "One"},
            {"sensor_type": "humidity", "entity_id": "sensor.same", "room": "Two"},
        ]
    }
    distinct_config = {
        "telemetry": [
            {"sensor_type": "humidity", "entity_id": "sensor.same", "room": "One"},
            {"sensor_type": "humidity", "entity_id": "sensor.other", "room": "Two"},
        ]
    }

    assert mod._humidity_balance_from_config(
        types.SimpleNamespace(states=States()),
        duplicate_config,
    ) == (None, None, 1)
    assert mod._humidity_balance_from_config(
        types.SimpleNamespace(states=States()),
        distinct_config,
    ) == (4.0, "room", 2)


def test_directional_movement_uses_twelve_oclock_split_and_rounded_led_steps():
    mod = _load_stability_module()

    higher = mod._directional_movement(90, 91)
    lower = mod._directional_movement(91, 90)
    steady = mod._directional_movement(91, 91)
    saturated = mod._directional_movement(100, 0)
    baseline = mod._directional_movement(None, 92)

    assert higher["origin"] == "twelve_oclock"
    assert higher["led_steps_total"] == 360
    assert higher["led_steps_per_side"] == 360
    assert higher["led_steps_per_point"] == 3.6
    assert higher["direction"] == "higher"
    assert higher["active_led_steps"] == 4
    assert lower["direction"] == "lower"
    assert lower["active_led_steps"] == 4
    assert steady["direction"] == "steady"
    assert steady["active_led_steps"] == 0
    assert saturated["direction"] == "lower"
    assert saturated["active_led_steps"] == 360
    assert saturated["saturated"] is True
    assert baseline["status"] == "baseline"
    assert baseline["active_led_steps"] == 0


def test_live_unavailable_truth_hides_stored_directional_movement():
    mod = _load_stability_module()
    stored = mod._directional_movement(
        96,
        54,
        previous_bucket_start_utc="2026-08-02T11:50:00+00:00",
        current_bucket_start_utc="2026-08-02T12:00:00+00:00",
    )
    runtime_data = {"stability_score_movement": stored}

    visible = mod._movement_from_runtime(
        runtime_data,
        {
            "score": {
                "score_status": "unavailable",
                "display_score": None,
            }
        },
    )

    assert visible["status"] == "unavailable"
    assert visible["previous_display_score"] == 54
    assert visible["current_display_score"] is None
    assert visible["direction"] == "none"
    assert visible["active_led_steps"] == 0
    assert runtime_data["stability_score_movement"] == stored


def test_fixed_utc_runtime_records_score_movement_against_previous_runtime():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))
    house = types.SimpleNamespace(
        _attr_unique_id="hi_house_avg_humidity",
        _attr_native_value=50.0,
    )
    condensation = types.SimpleNamespace(
        _attr_unique_id="hi_worst_condensation_risk",
        _attr_native_value="OK",
    )
    mould = types.SimpleNamespace(
        _attr_unique_id="hi_worst_mould_risk",
        _attr_native_value="OK",
    )
    runtime_data = {
        "stability_snapshot_ring": ring,
        "runtime_mode": "normal",
        "core_sensors": [house, condensation, mould],
        "config": {"target_profile": "winter"},
    }

    first = mod.record_stability_score_movement(
        runtime_data,
        observed_at=_sample(mod, 431).observed_at,
    )
    assert first["status"] == "baseline"
    assert first["current_display_score"] == 97

    house._attr_native_value = 60.0
    mould._attr_native_value = "Danger"
    ring.add(
        _sample(
            mod,
            432,
            house_humidity=60.0,
            worst_mould_state="Danger",
        )
    )
    second = mod.record_stability_score_movement(
        runtime_data,
        observed_at=_sample(mod, 432).observed_at,
    )

    assert second["previous_display_score"] == 97
    assert second["current_display_score"] == 54
    assert second["delta_points"] == -43
    assert second["direction"] == "lower"
    assert second["active_led_steps"] == 155
    payload = mod.stability_diagnostics_payload(
        runtime_data,
        observed_at=_sample(mod, 432).observed_at,
    )
    assert payload["movement"] == second


def test_unavailable_runtime_breaks_directional_movement_chain():
    mod = _load_stability_module()
    ring = mod.StabilitySnapshotRing()
    for idx in range(432):
        ring.add(_sample(mod, idx))
    house = types.SimpleNamespace(
        _attr_unique_id="hi_house_avg_humidity",
        _attr_native_value=50.0,
    )
    runtime_data = {
        "stability_snapshot_ring": ring,
        "runtime_mode": "normal",
        "core_sensors": [
            house,
            types.SimpleNamespace(
                _attr_unique_id="hi_worst_condensation_risk",
                _attr_native_value="OK",
            ),
            types.SimpleNamespace(
                _attr_unique_id="hi_worst_mould_risk",
                _attr_native_value="OK",
            ),
        ],
        "config": {"target_profile": "winter"},
    }

    first = mod.record_stability_score_movement(
        runtime_data,
        observed_at=_sample(mod, 431).observed_at,
    )
    assert first["status"] == "baseline"

    house._attr_native_value = "unknown"
    unavailable = mod.record_stability_score_movement(
        runtime_data,
        observed_at=_sample(mod, 432).observed_at,
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["previous_display_score"] == first["current_display_score"]
    assert runtime_data["stability_movement_last_score"] is None

    house._attr_native_value = 50.0
    recovered = mod.record_stability_score_movement(
        runtime_data,
        observed_at=_sample(mod, 433).observed_at,
    )
    assert recovered["status"] == "baseline"
    assert recovered["previous_display_score"] is None
    assert recovered["active_led_steps"] == 0


def test_movement_color_intensity_uses_signed_score_rate_boundary():
    mod = _load_stability_module()
    for delta, token, intensity in (
        (1, "rise_gentle", "gentle"),
        (4, "rise_gentle", "gentle"),
        (5, "rise_strong", "strong"),
        (-1, "fall_gentle", "gentle"),
        (-4, "fall_gentle", "gentle"),
        (-5, "fall_strong", "strong"),
    ):
        result = mod._directional_movement(
            70, 70 + delta,
            previous_bucket_start_utc="2026-09-10T10:00:00+00:00",
            current_bucket_start_utc="2026-09-10T10:10:00+00:00",
        )
        assert result["color_token"] == token
        assert result["intensity"] == intensity
        assert result["rate_points_per_10_minutes"] == delta
        assert result["delta_points"] == delta
        assert result["active_led_steps"] == ceil(abs(delta) * 3.6)
        assert "since the previous update" in result["detail_text"]
        assert result["basis"] == "published_display_score"


def test_movement_color_uses_delta_while_rate_remains_observational():
    mod = _load_stability_module()
    for delta, token, rate in (
        (5, "rise_strong", 2.5),
        (-5, "fall_strong", -2.5),
        (10, "rise_strong", 5.0),
        (-10, "fall_strong", -5.0),
    ):
        result = mod._directional_movement(
            70, 70 + delta,
            previous_bucket_start_utc="2026-09-10T11:00:00+01:00",
            current_bucket_start_utc="2026-09-10T10:20:00Z",
        )
        assert result["color_token"] == token
        assert result["rate_points_per_10_minutes"] == rate
        assert result["delta_points"] == delta
        assert result["active_led_steps"] == ceil(abs(delta) * 3.6)


def test_movement_unknown_interval_keeps_delta_color_without_inventing_rate():
    mod = _load_stability_module()
    valid = "2026-09-10T10:00:00+00:00"
    for previous, current in (
        (None, valid), (valid, None), ("bad", valid), (valid, "bad"),
        ("2026-09-10T09:50:00", valid),
        (valid, "2026-09-10T10:10:00"),
        (valid, valid),
        (valid, "2026-09-10T09:50:00+00:00"),
    ):
        result = mod._directional_movement(
            70, 80,
            previous_bucket_start_utc=previous,
            current_bucket_start_utc=current,
        )
        assert result["color_token"] == "rise_strong"
        assert result["intensity"] == "strong"
        assert result["rate_points_per_10_minutes"] is None
        assert result["direction"] == "higher"
        assert result["active_led_steps"] == 36
        assert "increased by 10 points" in result["detail_text"]


def test_movement_baseline_steady_and_unavailable_have_neutral_color_without_arc():
    mod = _load_stability_module()
    for previous, current, expected_rate in ((None, 80, None), (80, 80, 0.0), (80, None, None)):
        result = mod._directional_movement(
            previous, current,
            previous_bucket_start_utc="2026-09-10T10:00:00+00:00",
            current_bucket_start_utc="2026-09-10T10:10:00+00:00",
        )
        assert result["color_token"] == "neutral"
        assert result["intensity"] == "neutral"
        assert result["rate_points_per_10_minutes"] == expected_rate
        assert result["active_led_steps"] == 0


def test_persistent_arc_retracts_crosses_origin_and_neutralizes_when_steady():
    mod = _load_stability_module()
    score, position, token = 80, 0, "neutral"
    origin = datetime(2026, 9, 10, tzinfo=timezone.utc)
    for index, (delta, endpoint, expected_token, side) in enumerate((
        (-10, -36, "fall_strong", "left"),
        (0, -36, "neutral", "left"),
        (-5, -54, "fall_strong", "left"),
        (5, -36, "rise_strong", "left"),
        (15, 18, "rise_strong", "right"),
        (-1, 14, "fall_gentle", "right"),
        (0, 14, "neutral", "right"),
    )):
        result = mod._directional_movement(
            score, score + delta,
            previous_position_degrees=position,
            previous_color_token=token,
            previous_bucket_start_utc=(origin + timedelta(minutes=index * 10)).isoformat(),
            current_bucket_start_utc=(origin + timedelta(minutes=(index + 1) * 10)).isoformat(),
        )
        assert result["start_position_degrees"] == position
        assert result["end_position_degrees"] == endpoint
        assert result["active_led_steps"] == abs(endpoint)
        assert result["arc_side"] == side
        assert result["color_token"] == expected_token
        assert result["intensity"] == expected_token.rsplit("_", 1)[-1]
        assert result["direction"] == ("higher" if delta > 0 else "lower" if delta < 0 else "steady")
        score, position, token = score + delta, endpoint, expected_token


def test_persistent_arc_saturates_each_step_and_retracts_from_edge():
    mod = _load_stability_module()
    for previous, current, start, endpoint in (
        (80, 90, 350, 360), (90, 89, 360, 356),
        (80, 70, -350, -360), (70, 71, -360, -356),
    ):
        result = mod._directional_movement(
            previous, current, previous_position_degrees=start,
        )
        assert result["end_position_degrees"] == endpoint
        assert result["active_led_steps"] == abs(endpoint)
        assert result["saturated"] is (abs(endpoint) == 360)
    for previous, current in ((None, 80), (80, None)):
        reset = mod._directional_movement(
            previous, current, previous_position_degrees=-176,
            previous_color_token="rise_strong",
        )
        assert reset["start_position_degrees"] == 0
        assert reset["end_position_degrees"] == 0
        assert reset["arc_side"] == "none"
        assert reset["active_led_steps"] == 0
        assert reset["color_token"] == "neutral"


def test_recorder_passes_persistent_endpoint_color_and_resets_after_capture_failure():
    mod = _load_stability_module()
    runtime = {}
    current = {"score": {"score_status": "available", "display_score": 80}}
    mod._calculate_stability_payload = lambda *_a, **_k: {"score": dict(current["score"])}
    origin = datetime(2026, 9, 10, tzinfo=timezone.utc)
    for index, (score, endpoint, token) in enumerate((
        (80, 0, "neutral"), (70, -36, "fall_strong"),
        (70, -36, "neutral"), (75, -18, "rise_strong"),
    )):
        current["score"]["display_score"] = score
        movement = mod.record_stability_score_movement(
            runtime, observed_at=origin + timedelta(minutes=index * 10),
        )
        assert movement["end_position_degrees"] == endpoint
        assert movement["color_token"] == token
    failed = mod.record_stability_score_movement(
        runtime, observed_at=origin + timedelta(minutes=40), capture_available=False,
    )
    assert failed["status"] == "unavailable"
    assert failed["end_position_degrees"] == 0
    recovered = mod.record_stability_score_movement(
        runtime, observed_at=origin + timedelta(minutes=50),
    )
    assert recovered["status"] == "baseline"
    assert recovered["end_position_degrees"] == 0
    assert recovered["color_token"] == "neutral"


def test_arc_continues_past_half_circle_and_returns_to_top_at_full_circle():
    mod = _load_stability_module()
    half = mod._directional_movement(100, 50)
    assert half["end_position_degrees"] == -180
    assert half["saturated"] is False
    full = mod._directional_movement(
        50, 0, previous_position_degrees=half["end_position_degrees"],
    )
    assert full["start_position_degrees"] == -180
    assert full["end_position_degrees"] == -360
    assert full["active_led_steps"] == 360
    assert full["saturated"] is True
    assert "decreased by 50 points" in full["detail_text"]
    assert full["basis"] == "published_display_score"
    reversed_arc = mod._directional_movement(
        0, 10, previous_position_degrees=full["end_position_degrees"],
    )
    assert reversed_arc["end_position_degrees"] == -324
    assert reversed_arc["active_led_steps"] == 324
    assert reversed_arc["arc_side"] == "left"
    assert reversed_arc["direction"] == "higher"
    assert reversed_arc["saturated"] is False


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
    print(f"{len(tests)} stability score sanity checks passed.")
