"""Raw-first Stability evidence and atomic score publication regression tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


AQ_PATH = Path(__file__).resolve().parents[1] / "custom_components/humidity_intelligence/helpers/air_quality.py"


def _aq_module():
    spec = importlib.util.spec_from_file_location("hi_stability_refinement_aq", AQ_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(levels, readings, *, selection=True):
    """Readings are synthetic (level, sensor type, value, unit) tuples."""
    states = {}
    telemetry = []
    for index, (level, sensor_type, value, unit) in enumerate(readings):
        entity_id = f"sensor.example_aq_{index}"
        telemetry.append({"entity_id": entity_id, "sensor_type": sensor_type, "level": level})
        if value is not None:
            states[entity_id] = SimpleNamespace(state=value, attributes={"unit_of_measurement": unit})
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    config = {"telemetry": telemetry, "aq": levels}
    return _aq_module().capture_configured_aq_evidence(hass, config, stability_selection=selection)


def _level(triggers, **thresholds):
    return {"enabled": True, "triggers": triggers, "thresholds": thresholds}


def test_raw_first_ignores_crossed_iaq_without_changing_engine_evidence():
    levels = {"level1": _level(["co2_high", "iaq_bad"], co2_high=1200, iaq_bad=75)}
    readings = [("level1", "co2", 800, "ppm"), ("level1", "iaq", 50, "index")]
    selected = _capture(levels, readings)
    engine = _capture(levels, readings, selection=False)
    assert selected["configured_trigger_count"] == selected["evaluated_trigger_count"] == 1
    assert selected["clearance"] == 1.0
    assert selected["bad_trigger_codes"] == []
    assert selected["complete"] is True
    assert engine["configured_trigger_count"] == 2
    assert engine["bad_trigger_codes"] == ["iaq_bad"]
    assert engine["clearance"] == 0.5


def test_raw_first_selection_is_per_level_with_iaq_fallback():
    selected = _capture({
        "level1": _level(["pm25_high", "iaq_bad"], pm25_high=35, iaq_bad=75),
        "level2": _level(["iaq_bad"], iaq_bad=60),
    }, [
        ("level1", "pm25", 10, "µg/m³"), ("level1", "iaq", 10, "index"),
        ("level2", "iaq", 60, "index"),
    ])
    assert selected["configured_trigger_count"] == 2
    assert selected["evaluated_trigger_count"] == 2
    assert selected["bad_trigger_codes"] == ["iaq_bad"]
    assert selected["clearance"] == 0.5
    assert selected["complete"] is True
    assert len(selected["selection"]["levels"]) == 2


@pytest.mark.parametrize("value,unit,threshold,mapped", [
    (None, "ppm", 1200, True),
    ("unavailable", "ppm", 1200, True),
    ("unknown", "ppm", 1200, True),
    ("nan", "ppm", 1200, True),
    (800, "ppb", 1200, True),
    (800, "ppm", "invalid", True),
    (800, "ppm", None, True),
    (800, "ppm", 1200, False),
])
def test_invalid_or_missing_raw_does_not_fall_back_to_healthy_iaq(value, unit, threshold, mapped):
    readings = [("level1", "iaq", 100, "index")]
    if mapped:
        readings.append(("level1", "co2", value, unit))
    selected = _capture({"level1": _level(["co2_high", "iaq_bad"], co2_high=threshold, iaq_bad=75)}, readings)
    assert selected["configured_trigger_count"] == 1
    assert selected["evaluated_trigger_count"] == 0
    assert selected["clearance"] is None
    assert selected["complete"] is False
    assert selected["bad_trigger_codes"] == []


def test_partial_raw_source_outage_remains_incomplete_despite_available_average():
    selected = _capture({"level1": _level(["co2_high", "iaq_bad"], co2_high=1200, iaq_bad=75)}, [
        ("level1", "co2", 800, "ppm"), ("level1", "co2", None, "ppm"),
        ("level1", "iaq", 100, "index"),
    ])
    assert selected["expected_source_count"] == 2
    assert selected["available_source_count"] == 1
    assert selected["complete"] is False


def test_each_configured_raw_condition_contributes_without_iaq_duplication():
    selected = _capture({"level1": _level(
        ["co2_high", "voc_bad", "pm25_high", "iaq_bad"],
        co2_high=1200, voc_bad=600, pm25_high=35, iaq_bad=75,
    )}, [
        ("level1", "co2", 1200, "ppm"), ("level1", "voc", 100, "ppb"),
        ("level1", "pm25", 35, "ug/m3"), ("level1", "iaq", 0, "index"),
    ])
    assert selected["configured_trigger_count"] == 3
    assert selected["evaluated_trigger_count"] == 3
    assert set(selected["bad_trigger_codes"]) == {"co2_high", "pm25_high"}
    assert selected["clearance"] == pytest.approx(1 / 3)


def test_unconfigured_raw_telemetry_does_not_disable_iaq_fallback():
    selected = _capture({"level1": _level(["iaq_bad"], iaq_bad=75)}, [
        ("level1", "co2", 2000, "ppm"), ("level1", "iaq", 100, "index"),
    ])
    assert selected["configured_trigger_count"] == 1
    assert selected["expected_source_count"] == 1
    assert selected["clearance"] == 1.0
    assert selected["complete"] is True


def test_co_warning_is_separate_from_selected_non_co_aq():
    selected = _capture({"level1": _level(["co_warning", "iaq_bad"], co_warning=15, iaq_bad=75)}, [
        ("level1", "co", 15, "ppm"), ("level1", "iaq", 100, "index"),
    ])
    assert selected["configured_trigger_count"] == 1
    assert selected["clearance"] == 1.0
    assert selected["bad_trigger_codes"] == []
    assert selected["co_warning_active"] is True
    assert selected["co_evidence_complete"] is True


def test_missing_co_does_not_report_clear_co_evidence():
    selected = _capture({"level1": _level(["co_warning", "co2_high"], co_warning=15, co2_high=1200)}, [
        ("level1", "co", None, "ppm"), ("level1", "co2", 800, "ppm"),
    ])
    assert selected["co_evidence_complete"] is False
    assert selected["configured_trigger_count"] == 1
    assert selected["clearance"] == 1.0


def test_disabled_level_does_not_add_missing_raw_conditions():
    disabled = _level(["co2_high"], co2_high=1200)
    disabled["enabled"] = False
    selected = _capture({"level1": disabled, "level2": _level(["iaq_bad"], iaq_bad=75)}, [
        ("level2", "iaq", 100, "index"),
    ])
    assert selected["configured_trigger_count"] == 1
    assert selected["complete"] is True


@pytest.mark.parametrize("position", [-360, -180, 0, 180, 360])
@pytest.mark.parametrize("delta,token", [(1, "rise_gentle"), (5, "rise_strong"), (-1, "fall_gentle"), (-5, "fall_strong")])
def test_movement_color_follows_delta_on_both_sides_and_at_saturation(position, delta, token):
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    movement = mod._directional_movement(
        70, 70 + delta,
        previous_bucket_start_utc="2026-09-26T12:00:00+00:00",
        current_bucket_start_utc="2026-09-26T12:00:01+00:00",
        previous_position_degrees=position,
        previous_color_token="fall_strong" if delta > 0 else "rise_strong",
    )
    assert movement["color_token"] == token
    assert movement["direction"] == ("higher" if delta > 0 else "lower")
    assert movement["current_display_score"] == 70 + delta
    assert -360 <= movement["end_position_degrees"] <= 360
    if delta > 0:
        assert movement["end_position_degrees"] >= position
    else:
        assert movement["end_position_degrees"] <= position


def _controlled_score_payload(score):
    return {
        "score": {
            "display_score": score,
            "score_status": "available" if score is not None else "unavailable",
        },
        "presentation": {"state_code": "available" if score is not None else "unavailable"},
    }


def test_publication_updates_movement_for_every_change_inside_one_bucket(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    first = mod.publish_stability_score(runtime, observed_at=start)
    assert first["movement"]["status"] == "baseline"
    for seconds, score, token in [(1, 71, "rise_gentle"), (2, 69, "fall_gentle"), (3, 74, "rise_strong")]:
        current["score"] = score
        published = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=seconds))
        assert published["score"]["display_score"] == score
        assert published["movement"]["current_display_score"] == score
        assert published["movement"]["color_token"] == token


def test_diagnostic_reads_are_pure_and_return_published_score(monkeypatch):
    from copy import deepcopy
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    mod.publish_stability_score(runtime, observed_at=start)
    current["score"] = 72
    published = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=1))
    before = deepcopy(runtime)
    current["score"] = 50
    for seconds in range(2, 8):
        read = mod.stability_diagnostics_payload(runtime, observed_at=start + timedelta(seconds=seconds))
        assert read["score"] == published["score"]
        assert read["movement"] == published["movement"]
        assert runtime == before


def test_unchanged_publication_preserves_position_and_next_delta_baseline(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    mod.publish_stability_score(runtime, observed_at=start)
    current["score"] = 65
    falling = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=1))
    same = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=2))
    assert same["movement"]["end_position_degrees"] == falling["movement"]["end_position_degrees"]
    current["score"] = 66
    rising = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=3))
    assert rising["movement"]["delta_points"] == 1
    assert rising["movement"]["color_token"] == "rise_gentle"
    assert rising["movement"]["arc_side"] == "left"


def test_unavailable_publication_breaks_comparison_baseline(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    mod.publish_stability_score(runtime, observed_at=start)
    current["score"] = None
    gap = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=1))
    assert gap["movement"]["status"] == "unavailable"
    current["score"] = 90
    restored = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=2))
    assert restored["movement"]["status"] == "baseline"
    assert restored["movement"]["delta_points"] is None


def test_iaq_fallback_keeps_configured_low_is_bad_direction_and_unit_rules():
    levels = {"level1": _level(["iaq_bad"], iaq_bad=75)}
    crossed = _capture(levels, [("level1", "iaq", 75, "index")])
    unsupported = _capture(levels, [("level1", "iaq", 75, "ppm")])
    assert crossed["bad_trigger_codes"] == ["iaq_bad"]
    assert crossed["clearance"] == 0.0
    assert unsupported["complete"] is False
    assert unsupported["evaluated_trigger_count"] == 0
    assert unsupported["clearance"] is None


def test_multiple_sensors_of_one_raw_type_retain_existing_mean_aggregation():
    selected = _capture({"level1": _level(["co2_high"], co2_high=1200)}, [
        ("level1", "co2", 500, "ppm"), ("level1", "co2", 1500, "ppm"),
    ])
    assert selected["configured_trigger_count"] == 1
    assert selected["expected_source_count"] == 2
    assert selected["available_source_count"] == 2
    assert selected["complete"] is True
    assert selected["clearance"] == 1.0


def test_sampled_history_keeps_live_point_separate_and_preserves_gaps(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    mod.publish_stability_score(runtime, observed_at=start, sample_history=True)
    current["score"] = 72
    live = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=1))
    assert [point["score"] for point in live["score_history"]["points"]] == [70]
    assert live["score_history"]["current"]["score"] == 72
    later = mod.publish_stability_score(runtime, observed_at=start + timedelta(minutes=30), sample_history=True)
    assert [point["score"] for point in later["score_history"]["points"]] == [70, None, None, 72]


def test_history_same_bucket_replacement_capacity_and_restart(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    mod.publish_stability_score(runtime, observed_at=start, sample_history=True)
    current["score"] = 71
    replaced = mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=1), sample_history=True)
    assert len(replaced["score_history"]["points"]) == 1
    assert replaced["score_history"]["points"][0]["score"] == 71
    later = mod.publish_stability_score(runtime, observed_at=start + timedelta(hours=73), sample_history=True)
    assert len(later["score_history"]["points"]) == 432
    assert later["score_history"]["points"][0]["score"] is None
    reset = mod.publish_stability_score({}, observed_at=start + timedelta(hours=73), sample_history=True)
    assert len(reset["score_history"]["points"]) == 1
    assert reset["movement"]["status"] == "baseline"


def test_out_of_order_publication_cannot_rewind_score_or_history(monkeypatch):
    from copy import deepcopy
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    current = {"score": 70}
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *a, **kw: _controlled_score_payload(current["score"]))
    runtime = {}
    start = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    published = mod.publish_stability_score(runtime, observed_at=start, sample_history=True)
    before = deepcopy(runtime)
    current["score"] = 20
    for delta in [0, -1]:
        assert mod.publish_stability_score(runtime, observed_at=start + timedelta(seconds=delta), sample_history=True) == published
        assert runtime == before


def test_aq_adjustment_requires_six_hours_of_observed_clear_intervals():
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    start = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
    state = mod._advance_aq_adjustment({}, observed_at=start, crossed=True, complete=True)
    assert state["points"] == 12
    state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=10), crossed=False, complete=True)
    assert state["points"] == 12  # First clear observation cannot certify the preceding interval.
    for index in range(1, 37):
        state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=10 * (index + 1)), crossed=False, complete=True)
        if index == 18:
            assert state["points"] == 6
    assert state["points"] == 0
    assert state["event_active"] is False


def test_aq_adjustment_missing_evidence_and_long_gaps_earn_no_credit():
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    start = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
    state = mod._advance_aq_adjustment({}, observed_at=start, crossed=True, complete=True)
    for minutes, complete in [(10, True), (20, False), (380, True)]:
        state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=minutes), crossed=False, complete=complete)
        assert state["points"] == 12
    state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=740), crossed=False, complete=True)
    assert state["points"] == 12
    state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=750), crossed=False, complete=True)
    assert state["points"] == 11.67


def test_repeated_aq_crossing_resets_but_never_stacks_adjustment():
    from datetime import datetime, timedelta, timezone
    from test_stability_score import _load_stability_module

    mod = _load_stability_module()
    start = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
    state = mod._advance_aq_adjustment({}, observed_at=start, crossed=True, complete=True)
    for index in range(1, 10):
        state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=index * 10), crossed=False, complete=True)
    assert 0 < state["points"] < 12
    for index in range(10, 15):
        state = mod._advance_aq_adjustment(state, observed_at=start + timedelta(minutes=index * 10), crossed=True, complete=True)
        assert state["points"] == 12
        assert state["clear_seconds"] == 0


def test_old_formula_samples_do_not_contribute_to_new_baseline():
    from test_stability_score import _load_stability_module, _sample

    mod = _load_stability_module()
    samples = [_sample(mod, index, formula_version=mod.FORMULA_VERSION - 1) for index in range(432)]
    result = mod.evaluate_stability_window(samples, observed_at=samples[-1].observed_at)
    assert result["window"]["valid_samples"] == 0
    assert result["score"]["display_score"] is None
    mixed = samples[:300] + [_sample(mod, index) for index in range(300, 432)]
    result = mod.evaluate_stability_window(mixed, observed_at=mixed[-1].observed_at)
    assert result["window"]["valid_samples"] == 132
    assert result["score"]["display_score"] is None


def test_source_policy_change_resets_baseline_history_and_movement():
    from test_stability_scheduler import _load_sensor_module

    sensor, _, _ = _load_sensor_module({}, [], [])
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None))
    runtime = {"config": {"aq": {"level1": _level(["co2_high"], co2_high=1200)}}}
    sensor._refresh_stability_aq(hass, runtime)
    ring = sensor.StabilitySnapshotRing()
    runtime["stability_snapshot_ring"] = ring
    runtime["stability_failed_buckets"] = {"old"}
    for key in ["stability_published", "stability_aq_adjustment", "stability_score_movement", "stability_score_history"]:
        runtime[key] = {"old": True}
    sensor._refresh_stability_aq(hass, runtime)
    assert runtime["stability_snapshot_ring"] is ring
    assert runtime["stability_published"] == {"old": True}
    runtime["config"]["aq"]["level1"]["thresholds"]["co2_high"] = 1000
    sensor._refresh_stability_aq(hass, runtime)
    assert runtime["stability_snapshot_ring"] is not ring
    assert runtime["stability_snapshot_ring"].samples() == []
    assert runtime["stability_failed_buckets"] == set()
    for key in ["stability_published", "stability_aq_adjustment", "stability_score_movement", "stability_score_history"]:
        assert key not in runtime


@pytest.mark.parametrize("co_value,co_complete", [(0, True), (None, False)])
def test_co_only_level_does_not_poison_complete_routine_aq_evidence(co_value, co_complete):
    selected = _capture({
        "level1": _level(["co2_high"], co2_high=1200),
        "level2": _level(["co_warning"], co_warning=15),
    }, [("level1", "co2", 800, "ppm"), ("level2", "co", co_value, "ppm")])
    assert selected["configured_trigger_count"] == 1
    assert selected["complete"] is True
    assert selected["clearance"] == 1.0
    assert selected["co_evidence_complete"] is co_complete


def test_co_only_configuration_does_not_claim_routine_aq_coverage():
    selected = _capture({"level1": _level(["co_warning"], co_warning=15)}, [
        ("level1", "co", 0, "ppm"),
    ])
    assert selected["configured_trigger_count"] == 0
    assert selected["complete"] is False
    assert selected["clearance"] is None
    assert selected["co_evidence_complete"] is True


def test_displayed_equation_operands_reconcile_after_decimal_rounding():
    from test_stability_score import _load_stability_module, _sample
    mod = _load_stability_module()
    samples = [_sample(mod, index, house_humidity=56 if index % 17 == 0 else 50,
        air_quality_clearance=[.3, .6, 1][index % 3]) for index in range(305)]
    result = mod.evaluate_stability_window(samples, current_air_quality_bad=False,
        current_air_quality_evidence_available=True,
        aq_adjustment={"points": 1.1558, "status": "recovering", "remaining_clear_seconds": 1000})
    equation = result["explanation"]
    assert round(max(0, 100 - equation["component_shortfall_points"] - equation["evidence_deduction_points"] - equation["aq_adjustment_points"]), 2) == equation["pre_cap_score"]
    assert round(sum(row["points"] for row in equation["component_shortfalls"]), 2) == equation["component_shortfall_points"]
    assert all(row["points"] >= 0 for row in equation["component_shortfalls"])


def test_late_history_sample_does_not_suppress_valid_live_score(monkeypatch):
    from datetime import datetime, timezone
    from test_stability_score import _load_stability_module
    mod = _load_stability_module()
    monkeypatch.setattr(mod, "_calculate_stability_payload", lambda *_a, **_k:
        {"score": {"score_status": "available", "display_score": 87}})
    result = mod.publish_stability_score({}, observed_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        sample_history=True, history_available=False)
    assert result["score"]["display_score"] == 87
    assert result["movement"]["status"] == "baseline"
    assert result["score_history"]["points"][0]["score"] is None
    assert result["score_history"]["current"]["score"] == 87
