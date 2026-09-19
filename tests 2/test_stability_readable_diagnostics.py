"""Tablet more-info exposes the same backend Stability explanations as the badge."""

from copy import deepcopy
from types import SimpleNamespace

from test_runtime_card_sanity import _load_sensor_platform_module


def test_sensor_publishes_backend_explanation_without_reclassifying_score():
    mod = _load_sensor_platform_module()
    for detail, movement in (
        ("Stability Score 54 — Poor. Underlying 72-hour score 97.00; capped because current mould Danger is active.",
         "Score moved lower; the arc is at -155 degrees."),
        ("Collecting baseline: fewer than 303 valid HI-owned snapshots.",
         "Directional movement unavailable because the current Stability Score is unavailable."),
        ("Live data unavailable; the historical score is suppressed.",
         "Directional movement unavailable because the current Stability Score is unavailable."),
    ):
        payload = {
            "presentation": {"detail_text": detail},
            "movement": {"detail_text": movement},
            "window": {"valid_samples": 303, "expected_samples": 432, "duration_hours": 72},
            "score": {"display_score": 54},
        }
        original = deepcopy(payload)
        mod._build_diagnostics_summary = lambda *_a: {"stability_score": payload}
        hass = SimpleNamespace(data={"humidity_intelligence": {"entry_test": {}}})
        sensor = mod.HIDiagnosticsSensor(hass, "entry_test")
        sensor.update()
        assert sensor._attr_extra_state_attributes["Stability Score"] == (
            detail + "\n\nWindow: 303/432 valid snapshots over 72 hours.\n\nCollection failure history unavailable.\n\n" + movement
        )
        assert sensor._attr_extra_state_attributes["diagnostics_summary"]["stability_score"]["presentation"]["detail_text"] == detail
        assert payload == original
        assert sensor._attr_native_value == "ok"


def test_missing_or_malformed_stability_explanation_degrades_safely():
    mod = _load_sensor_platform_module()
    for payload in (None, [], {}, {"presentation": [], "movement": [], "window": []},
                    {"presentation": {"detail_text": 42}, "window": {"valid_samples": "303", "expected_samples": 432, "duration_hours": 72}}):
        assert mod._readable_stability_score(payload) == (
            "Stability Score unavailable.\n\nWindow coverage unavailable.\n\nCollection failure history unavailable."
        )
    assert mod._readable_stability_score({"message": "Backend evidence is incomplete."}) == (
        "Backend evidence is incomplete.\n\nWindow coverage unavailable.\n\nCollection failure history unavailable."
    )


def test_native_details_show_baseline_minimum_and_observed_failures():
    mod = _load_sensor_platform_module()
    payload = {
        "presentation": {"state_code": "collecting", "detail_text": "Collecting baseline."},
        "window": {"valid_samples": 7, "minimum_valid_samples": 303, "expected_samples": 432, "duration_hours": 72},
        "sampling": {"failure_history": {"status": "available", "failed_bucket_count": 2}},
    }
    text = mod._readable_stability_score(payload)
    assert "Baseline progress: 7 of 303 valid samples." in text
    assert "Unsuccessful collections: 2 scheduled buckets in the current 72-hour window." in text
    assert "Window: 7/432" in text
    for bad in (False, [], "2", -1, 433, None):
        payload["sampling"]["failure_history"]["failed_bucket_count"] = bad
        assert "Collection failure history unavailable." in mod._readable_stability_score(payload)
    payload["sampling"]["failure_history"] = {"status": "unavailable", "failed_bucket_count": 0}
    assert "Collection failure history unavailable." in mod._readable_stability_score(payload)
    payload["window"]["minimum_valid_samples"] = False
    assert "Baseline progress unavailable." in mod._readable_stability_score(payload)
