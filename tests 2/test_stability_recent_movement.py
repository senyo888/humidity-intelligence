"""Recent movement uses real bounded publications without changing score/history."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from test_stability_score import _load_stability_module


@pytest.fixture
def publisher(monkeypatch):
    mod = _load_stability_module()
    runtime = {}
    now = datetime(2026, 10, 7, 12, 3, 17, tzinfo=timezone.utc)
    value = {"score": 40}

    def payload(*_a, **_kw):
        return {"score": {"display_score": value["score"],
            "score_status": "available" if value["score"] is not None else "unavailable"}}

    monkeypatch.setattr(mod, "_calculate_stability_payload", payload)

    def publish(seconds, score, **kwargs):
        value["score"] = score
        return mod.publish_stability_score(runtime, observed_at=now + timedelta(seconds=seconds), **kwargs)

    return mod, runtime, now, publish


def test_plus_five_minus_two_is_three_with_distinct_latest_fall(publisher):
    _, runtime, now, publish = publisher
    first = publish(0, 40)
    assert first["movement"]["status"] == "baseline"
    publish(1, 45)
    last = publish(2, 43)
    movement = last["movement"]
    assert last["score"]["display_score"] == 43
    assert movement["reference_display_score"] == 40
    assert movement["reference_at"] == now.isoformat()
    assert movement["recent_delta_points"] == 3
    assert movement["end_position_degrees"] == 11
    assert movement["delta_points"] == -2
    assert movement["color_token"] == "fall_gentle"
    assert movement["observed_span_seconds"] == 2
    assert "decreased by 2 points" in movement["detail_text"]
    assert "Recent score change: +3 points" in movement["detail_text"]
    assert last["score_history"]["points"] == []
    assert len(runtime["stability_movement_observations"]) == 1


@pytest.mark.parametrize("scores", [
    [50, 51, 52, 53, 54, 55, 50], [50, 55, 53, 50],
    [50, 49, 48, 47, 46, 45, 50], [50, 0, 100, 50],
])
def test_closed_score_paths_leave_no_geometric_residue(publisher, scores):
    _, _, _, publish = publisher
    for seconds, score in enumerate(scores):
        last = publish(seconds, score)
    assert last["movement"]["recent_delta_points"] == 0
    assert last["movement"]["end_position_degrees"] == 0


def test_steady_publications_expire_reference_without_a_fake_fall(publisher):
    _, runtime, now, publish = publisher
    publish(0, 40)
    publish(1, 45)
    for seconds in range(600, 3601, 600):
        last = publish(seconds, 45)
    assert last["movement"]["recent_delta_points"] == 5
    assert last["movement"]["observed_span_seconds"] == 3600
    assert len(runtime["stability_movement_observations"]) == 7
    expired = publish(3601, 45)["movement"]
    assert expired["reference_at"] == (now + timedelta(seconds=600)).isoformat()
    assert expired["recent_delta_points"] == 0
    assert expired["delta_points"] == 0
    assert expired["end_position_degrees"] == 0
    assert expired["color_token"] == "neutral"
    assert expired["reference_advanced"] is True
    assert expired["saturated"] is False
    assert "reference advanced" in expired["detail_text"]
    assert "unchanged since the previous update" in expired["detail_text"]


def test_reference_storage_is_bounded_even_with_frequent_updates(publisher):
    _, runtime, now, publish = publisher
    for seconds in range(0, 7201, 13):
        last = publish(seconds, 40 + seconds % 7)
        observations = runtime["stability_movement_observations"]
        assert len(observations) <= 7
        assert all(0 <= ((now + timedelta(seconds=seconds)) - at).total_seconds() <= 3600 for at in observations)
    assert last["movement"]["reference_at"] in {at.isoformat() for at in observations}
    assert last["score_history"]["points"] == []


def test_unknown_then_recovery_cannot_reuse_old_optimistic_reference(publisher):
    _, runtime, _, publish = publisher
    publish(0, 40)
    publish(1, 45)
    missing = publish(2, None)
    assert missing["movement"]["status"] == "unavailable"
    assert runtime["stability_movement_observations"] == {}
    recovered = publish(3, 46)["movement"]
    assert recovered["status"] == "baseline"
    assert recovered["recent_delta_points"] is None
    assert recovered["end_position_degrees"] == 0
    assert publish(4, 47)["movement"]["recent_delta_points"] == 1


@pytest.mark.parametrize("gap,expected", [(660, "available"), (661, "baseline"), (86400, "baseline")])
def test_long_publication_gap_starts_new_comparison(publisher, gap, expected):
    _, _, _, publish = publisher
    publish(0, 40)
    movement = publish(gap, 45)["movement"]
    assert movement["status"] == expected
    assert movement["end_position_degrees"] == (18 if expected == "available" else 0)
    assert movement["delta_points"] == (5 if expected == "available" else None)


def test_reads_repeated_and_reversed_publications_do_not_advance_reference(publisher):
    mod, runtime, now, publish = publisher
    publish(0, 40)
    actual = publish(1, 45)
    before = deepcopy(runtime)
    assert publish(1, 10) == actual
    assert publish(0, 10) == actual
    assert mod.stability_diagnostics_payload(runtime, observed_at=now + timedelta(days=1)) == actual
    assert runtime == before


def test_graph_gap_does_not_invalidate_genuine_live_publications(publisher):
    _, _, _, publish = publisher
    publish(0, 40, sample_history=True)
    publish(120, 43)
    gap = publish(600, 45, sample_history=True, history_available=False)
    assert gap["score_history"]["points"][-1]["score"] is None
    assert gap["movement"]["recent_delta_points"] == 5
    assert gap["movement"]["reference_window_minutes"] == 60


def test_expiry_concurrent_with_real_change_keeps_latest_delta(publisher):
    _, _, _, publish = publisher
    publish(0, 40)
    for seconds in range(600, 3601, 600):
        publish(seconds, 45)
    movement = publish(3601, 43)["movement"]
    assert movement["recent_delta_points"] == -2
    assert movement["delta_points"] == -2
    assert movement["color_token"] == "fall_gentle"
    assert movement["reference_advanced"] is True


def test_reset_runtime_establishes_baseline(publisher):
    _, runtime, _, publish = publisher
    publish(0, 40)
    publish(1, 45)
    runtime.clear()
    assert publish(2, 46)["movement"]["status"] == "baseline"
