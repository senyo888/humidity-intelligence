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
            detail + "\n\nWindow: 303/432 valid snapshots over 72 hours.\n\n" + movement
        )
        assert sensor._attr_extra_state_attributes["diagnostics_summary"]["stability_score"]["presentation"]["detail_text"] == detail
        assert payload == original
        assert sensor._attr_native_value == "ok"


def test_missing_or_malformed_stability_explanation_degrades_safely():
    mod = _load_sensor_platform_module()
    for payload in (None, [], {}, {"presentation": [], "movement": [], "window": []},
                    {"presentation": {"detail_text": 42}, "window": {"valid_samples": "303", "expected_samples": 432, "duration_hours": 72}}):
        assert mod._readable_stability_score(payload) == (
            "Stability Score unavailable.\n\nWindow coverage unavailable."
        )
    assert mod._readable_stability_score({"message": "Backend evidence is incomplete."}) == (
        "Backend evidence is incomplete.\n\nWindow coverage unavailable."
    )
