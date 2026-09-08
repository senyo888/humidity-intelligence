"""Failing-first and regression checks for humidifier output reconciliation."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import MethodType, SimpleNamespace

from test_runtime_card_sanity import (
    ENTRY_ID,
    _FakeHass,
    _FakeState,
    _base_entry_data,
    _load_services_module,
    _load_target_modules,
)

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "humidity_intelligence"


def _entry_with_humidifiers(humidifiers):
    data = _base_entry_data()
    data["alert_handling_enabled"] = False
    data["alerts"] = []
    data["zones"] = {}
    data["aq"] = {}
    data["humidifiers"] = humidifiers
    return SimpleNamespace(entry_id=ENTRY_ID, data=data, options={})


def _states(*, level1=40, level2=40, outputs=None):
    values = {
        "sensor.kitchen_h": _FakeState(level1),
        "sensor.hall_h": _FakeState(level1),
        "sensor.bed_h": _FakeState(level2),
        "sensor.kitchen_t": _FakeState(21),
        "sensor.hall_t": _FakeState(21),
        "sensor.bed_t": _FakeState(20),
        "sensor.l1_iaq": _FakeState(90),
        "sensor.co_val": _FakeState(0),
    }
    values.update(outputs or {})
    return values


def _humidifier_calls(hass, *, entity_id=None, service=None):
    calls = [
        call
        for call in hass.services.calls
        if call[0] in {"humidifier", "fan", "switch"}
        and (entity_id is None or call[2].get("entity_id") == entity_id)
        and (service is None or call[1] == service)
    ]
    return calls


def _set_humidifier_display_truth(
    hass,
    *,
    reconciliation,
    demand="requested",
    observed="off",
    platform_action="not_exposed",
    failure_category=None,
    dispatch_result=None,
    dispatch_intent=None,
    overall=None,
):
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime["humidifier_status"] = {
        "schema": 1,
        "overall": overall or reconciliation,
        "lanes": {
            "level1": {
                "demand": demand,
                "environmental_state": (
                    "start" if demand == "requested" else "inactive"
                ),
                "reconciliation": reconciliation,
                "observed": observed,
                "platform_action": platform_action,
                "output_count": 1,
                "failure_category": failure_category,
            }
        },
    }
    outputs = {}
    if dispatch_result is not None:
        outputs["output_1"] = {
            "owners": ["level1"],
            "configured_owners": ["level1"],
            "last_command_intent": dispatch_intent or "turn_on",
            "dispatch_result": dispatch_result,
        }
    runtime["humidifier_reconciliation"] = {"schema": 1, "outputs": outputs}


def _active_humidifier_detail():
    return {
        "level": "level1",
        "season": "Winter",
        "humidity": 51.4,
        "low": 54.0,
        "high": 58.0,
        "recovery_off": 55.0,
        "environmental_state": "start",
        "demand": True,
    }


def test_restored_demand_with_observed_output_off_dispatches_reconciliation():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(
                level1=47,
                outputs={"humidifier.level1": _FakeState("off")},
            ),
        )
        demand = hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"][
            "air_downstairs_humidifier_active"
        ]
        demand.is_on = True
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            assert demand.is_on
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="humidifier.level1",
                    service="turn_on",
                )
            ) == 1
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["humidifier_status"]["lanes"]["level1"]["demand"] == "requested"
            assert runtime["humidifier_status"]["lanes"]["level1"][
                "reconciliation"
            ] in {"requested", "retrying"}
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_shared_output_uses_aggregated_demand_and_one_write_per_cycle():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.shared"],
                    "band_adjust": 0,
                },
                "level2": {
                    "enabled": True,
                    "outputs": ["humidifier.shared"],
                    "band_adjust": 0,
                },
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"humidifier.shared": _FakeState("off")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="humidifier.shared",
                    service="turn_on",
                )
            ) == 1

            hass.states._values["humidifier.shared"] = _FakeState("on")
            await engine._evaluate()
            hass.states._values["sensor.kitchen_h"] = _FakeState(55)
            hass.states._values["sensor.hall_h"] = _FakeState(55)
            await engine._evaluate()

            assert not _humidifier_calls(
                hass,
                entity_id="humidifier.shared",
                service="turn_off",
            )
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["humidifier_status"]["lanes"]["level1"]["demand"] == "inactive"
            assert runtime["humidifier_status"]["lanes"]["level2"]["demand"] == "requested"
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_two_independent_lane_outputs_dispatch_once_each():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                },
                "level2": {
                    "enabled": True,
                    "outputs": ["humidifier.level2"],
                    "band_adjust": 0,
                },
            }
        )
        hass = _FakeHass(
            entry,
            _states(
                outputs={
                    "switch.level1": _FakeState("off"),
                    "humidifier.level2": _FakeState("off"),
                }
            ),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="switch.level1",
                    service="turn_on",
                )
            ) == 1
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="humidifier.level2",
                    service="turn_on",
                )
            ) == 1
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["humidifier_status"]["lanes"]["level1"]["demand"] == "requested"
            assert runtime["humidifier_status"]["lanes"]["level2"]["demand"] == "requested"
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_configured_output_is_an_evaluation_source_but_demand_helper_is_not():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers(
        {
            "level1": {
                "enabled": True,
                "outputs": ["switch.level1"],
                "band_adjust": 0,
            }
        }
    )
    hass = _FakeHass(entry, _states(outputs={"switch.level1": _FakeState("off")}))
    for key, entity in hass.data["humidity_intelligence"][ENTRY_ID][
        "hi_input_booleans"
    ].items():
        entity.entity_id = f"switch.hi_{key}"
    engine = engine_mod.HIAutomationEngine(hass, entry)

    sources = engine._evaluation_sources()

    assert "switch.level1" in sources
    assert "switch.hi_air_downstairs_humidifier_active" not in sources


def test_missing_unknown_and_unavailable_outputs_do_not_receive_turn_on():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        for entity_id, state in (
            ("switch.missing", None),
            ("switch.unknown", _FakeState("unknown")),
            ("switch.unavailable", _FakeState("unavailable")),
            ("light.unsupported", _FakeState("off")),
        ):
            entry = _entry_with_humidifiers(
                {
                    "level1": {
                        "enabled": True,
                        "outputs": [entity_id],
                        "band_adjust": 0,
                    }
                }
            )
            output_states = {} if state is None else {entity_id: state}
            hass = _FakeHass(entry, _states(outputs=output_states))
            engine = engine_mod.HIAutomationEngine(hass, entry)
            try:
                await engine._evaluate()
                assert not [
                    call
                    for call in hass.services.calls
                    if call[2].get("entity_id") == entity_id
                ]
                runtime = hass.data["humidity_intelligence"][ENTRY_ID]
                assert runtime["humidifier_status"]["lanes"]["level1"][
                    "reconciliation"
                ] in {"degraded", "unknown"}
            finally:
                await engine.async_stop()

    asyncio.run(run())


def test_level_telemetry_loss_remains_degraded_when_house_average_is_available():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(
                level1="unavailable",
                level2=45,
                outputs={"switch.level1": _FakeState("off")},
            ),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()

            assert not _humidifier_calls(
                hass,
                entity_id="switch.level1",
                service="turn_on",
            )
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            lane = runtime["humidifier_status"]["lanes"]["level1"]
            assert lane["demand"] == "inactive"
            assert lane["environmental_state"] == "unknown"
            assert lane["reconciliation"] == "degraded"
            assert lane["observed"] == "off"
            assert runtime["humidifier_status"]["overall"] == "degraded"
            summary = runtime["humidifier_reconciliation"]["summary"]
            assert summary["degraded_lanes"] == 1
            assert summary["unknown_lanes"] == 1
            assert runtime["humidifier_reconciliation"]["outputs"]["output_1"][
                "reconciliation"
            ] == "matched_off"
            display = runtime["runtime_display_reason"]
            display_text = " ".join(line["text"] for line in display["lines"])
            assert (
                "humidity data is unavailable, so HI cannot assess humidifier demand"
                in display_text
            )
            assert "Output reconciliation is degraded" not in display_text
            helper = runtime["hi_input_booleans"][
                "air_downstairs_humidifier_active"
            ]
            assert not helper.is_on
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_missing_humidifier_output_has_mapping_specific_display_truth():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": [],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(entry, _states())
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            lane = runtime["humidifier_status"]["lanes"]["level1"]
            assert lane["failure_category"] == "no_outputs"
            assert lane["reconciliation"] == "degraded"
            assert not _humidifier_calls(hass)
            display_text = " ".join(
                line["text"]
                for line in runtime["runtime_display_reason"]["lines"]
            )
            assert (
                "no humidifier output is configured, so no command was sent"
                in display_text
            )
            assert "Output reconciliation is degraded" not in display_text
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_normal_ventilation_mode_can_coexist_with_humidifier_demand():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                }
            }
        )
        entry.data["level_labels"] = {
            "level1": "Ground Floor",
            "level2": "Loft",
        }
        hass = _FakeHass(
            entry,
            _states(outputs={"humidifier.level1": _FakeState("on")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["runtime_mode"] == "normal"
            reason = runtime.get("runtime_reason_full") or runtime["runtime_reason"]
            assert "no ventilation lane currently needs to run" in reason
            assert "Home Assistant reports" in reason
            assert "physical moisture" in reason.lower()
            display = runtime["runtime_display_reason"]
            assert display["family"] == "normal"
            display_text = " ".join(
                [display["headline"]]
                + [line["text"] for line in display["lines"]]
            )
            assert "Home Assistant reports that the output is on" in display_text
            assert "physical moisture output is not measured" in display_text
            assert "Ground Floor" in display_text
            assert "Downstairs" not in display_text
            assert "humidifier.level1" not in display_text
            assert display_text.count("physical moisture output is not measured") == 1
            assert len(display["lines"]) <= 6
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_reason_line_truncation_retains_material_truth_in_original_order():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    secondary = [
        engine_mod.ReasonLine(
            "next",
            "system",
            f"normal.secondary_{index}",
            "selected",
            f"Secondary explanation {index}.",
        )
        for index in range(4)
    ]
    material = [
        engine_mod.ReasonLine(
            "why", "safety", "alert.safety_truth", "observed", "Safety truth."
        ),
        engine_mod.ReasonLine(
            "notice", "system", "alert.degraded_truth", "unmapped", "Degraded truth."
        ),
        engine_mod.ReasonLine(
            "notice", "ventilation", "isolation.fan_outputs", "blocked", "Isolation truth."
        ),
        engine_mod.ReasonLine(
            "action", "ventilation", "zone.output_selected", "selected", "Action truth."
        ),
        engine_mod.ReasonLine(
            "notice", "humidifier", "humidifier.output_on", "observed", "Observation truth."
        ),
        engine_mod.ReasonLine(
            "notice", "humidifier", "humidifier.retry_failed", "failed", "Failure truth."
        ),
    ]

    facts = engine._make_reason_facts(
        "normal",
        "monitoring",
        "neutral",
        "Monitoring",
        secondary + material,
    )
    codes = [line.code for line in facts.lines]

    assert facts.truncated is True
    assert len(facts.lines) == 8
    for line in material:
        assert line.code in codes
    assert codes == [
        line.code for line in secondary + material if line.code in set(codes)
    ]


def test_multibyte_contract_compaction_retains_material_truth_under_four_kib():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    lines = [
        engine_mod.ReasonLine(
            "why",
            "system",
            f"normal.multibyte_{index}",
            "selected",
            "🧪" * 200,
        )
        for index in range(5)
    ] + [
        engine_mod.ReasonLine(
            "action",
            "ventilation",
            "zone.output_selected",
            "selected",
            "Selected action remains visible.",
        ),
        engine_mod.ReasonLine(
            "notice",
            "safety",
            "alert.safety_truth",
            "observed",
            "Safety truth remains visible.",
        ),
        engine_mod.ReasonLine(
            "notice",
            "humidifier",
            "humidifier.retrying",
            "failed",
            "Failure truth remains visible.",
        ),
    ]

    facts = engine._make_reason_facts(
        "normal",
        "monitoring",
        "neutral",
        "Monitoring",
        lines,
    )
    display = engine_mod.build_display_reason(facts)
    encoded = json.dumps(
        display,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert facts.truncated is True
    assert len(encoded) <= engine_mod.DISPLAY_REASON_MAX_BYTES
    assert {
        "zone.output_selected",
        "alert.safety_truth",
        "humidifier.retrying",
    }.issubset({line.code for line in facts.lines})
    assert [line.code for line in facts.lines] == [
        line.code for line in lines if line.code in {item.code for item in facts.lines}
    ]


def test_humidifier_response_copy_covers_all_material_reconciliation_states():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    entry.data["level_labels"] = {"level1": "Ground Floor"}
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    cases = (
        (
            "output_on",
            "requested",
            "on",
            "humidifying",
            None,
            None,
            None,
            "observed",
            "Home Assistant reports its output on and its humidifier action as humidifying",
        ),
        (
            "platform_idle",
            "requested",
            "on",
            "idle",
            None,
            None,
            None,
            "observed",
            "its humidifier action is idle",
        ),
        (
            "requested",
            "requested",
            "off",
            "not_exposed",
            None,
            "dispatched_unconfirmed",
            "turn_on",
            "requested",
            "HI sent the output-on request to Home Assistant",
        ),
        (
            "retrying",
            "requested",
            "off",
            "not_exposed",
            None,
            "exception",
            "turn_on",
            "failed",
            "A Home Assistant output-on request failed",
        ),
        (
            "stopping",
            "inactive",
            "on",
            "not_exposed",
            None,
            "dispatched_unconfirmed",
            "turn_off",
            "requested",
            "HI sent the output-off request to Home Assistant",
        ),
        (
            "isolated",
            "requested",
            "off",
            "not_exposed",
            None,
            None,
            None,
            "blocked",
            "isolation is active, so HI is not sending humidifier commands to Home Assistant",
        ),
        (
            "unknown",
            "requested",
            "unavailable",
            "not_exposed",
            None,
            None,
            None,
            "unavailable",
            "Home Assistant is not reporting the output state",
        ),
        (
            "degraded",
            "inactive",
            "off",
            "not_exposed",
            "telemetry_unavailable",
            None,
            None,
            "unavailable",
            "Humidity data is unavailable, so HI cannot assess humidifier demand",
        ),
        (
            "degraded",
            "inactive",
            "not_configured",
            "not_exposed",
            "no_outputs",
            None,
            None,
            "blocked",
            "No humidifier output is configured, so no command was sent",
        ),
        (
            "degraded",
            "requested",
            "off",
            "not_exposed",
            "service_unavailable",
            "service_unavailable",
            "turn_on",
            "blocked",
            "A required Home Assistant output-on service is unavailable, so HI did not send that request",
        ),
        (
            "degraded",
            "inactive",
            "on",
            "not_exposed",
            "service_unavailable",
            "service_unavailable",
            "turn_off",
            "blocked",
            "A required Home Assistant output-off service is unavailable, so HI did not send that request",
        ),
        (
            "degraded",
            "requested",
            "off",
            "not_exposed",
            "unsupported_domain",
            "unsupported_domain",
            "turn_on",
            "blocked",
            "A configured humidifier output uses an unsupported entity type, so HI did not send that request",
        ),
        (
            "degraded",
            "requested",
            "missing",
            "not_exposed",
            "missing",
            "missing",
            "turn_on",
            "unavailable",
            "A configured humidifier output is not available in Home Assistant, so HI did not send that request",
        ),
        (
            "degraded",
            "requested",
            "unknown",
            "not_exposed",
            "unknown",
            "unknown",
            "turn_on",
            "unavailable",
            "A required humidifier output state is unavailable, so HI did not send that request",
        ),
        (
            "degraded",
            "requested",
            "unavailable",
            "not_exposed",
            "unavailable",
            "unavailable",
            "turn_on",
            "unavailable",
            "A required humidifier output state is unavailable, so HI did not send that request",
        ),
        (
            "fault_latched",
            "requested",
            "off",
            "not_exposed",
            "retry_exhausted",
            None,
            None,
            "failed",
            "HI has used all configured confirmation attempts",
        ),
        (
            "inactive_shared_output",
            "inactive",
            "on",
            "not_exposed",
            None,
            None,
            None,
            "selected",
            "another area still needs the shared output",
        ),
    )

    for (
        reconciliation,
        demand,
        observed,
        platform_action,
        failure_category,
        dispatch_result,
        dispatch_intent,
        expected_truth,
        expected_copy,
    ) in cases:
        _set_humidifier_display_truth(
            hass,
            reconciliation=reconciliation,
            demand=demand,
            observed=observed,
            platform_action=platform_action,
            failure_category=failure_category,
            dispatch_result=dispatch_result,
            dispatch_intent=dispatch_intent,
        )
        active_details = (
            [_active_humidifier_detail()] if demand == "requested" else []
        )
        lines = engine._humidifier_display_lines(active_details)
        response = next(
            line
            for line in lines
            if line.code == f"humidifier.{reconciliation}"
        )
        assert response.truth == expected_truth, reconciliation
        assert expected_copy.lower() in response.text.lower(), reconciliation
        if dispatch_result in {
            "service_unavailable",
            "unsupported_domain",
            "missing",
            "unknown",
            "unavailable",
        }:
            assert "HI sent" not in response.text
        assert all("Ground Floor" in line.text for line in lines), reconciliation
        assert all(
            len(line.text) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
            for line in lines
        ), reconciliation
        assert not any(
            line.code
            in {
                "humidifier.platform_action_caveat",
                "humidifier.physical_output_not_confirmed",
            }
            for line in lines
        ), reconciliation

    for reconciliation in ("inactive", "matched_off"):
        _set_humidifier_display_truth(
            hass,
            reconciliation=reconciliation,
            demand="inactive",
            observed="off",
        )
        assert engine._humidifier_display_lines([]) == []


def test_humidifier_requested_wording_requires_proved_home_assistant_dispatch():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)

    for reconciliation, dispatch_result, intent in (
        ("requested", None, "turn_on"),
        ("retrying", None, "turn_on"),
        ("retrying", "exception", "turn_on"),
        ("stopping", None, "turn_off"),
        ("stopping", "exception", "turn_off"),
    ):
        demand = "inactive" if reconciliation == "stopping" else "requested"
        _set_humidifier_display_truth(
            hass,
            reconciliation=reconciliation,
            demand=demand,
            dispatch_result=dispatch_result,
            dispatch_intent=intent,
        )
        active_details = (
            [_active_humidifier_detail()] if demand == "requested" else []
        )
        lines = engine._humidifier_display_lines(active_details)
        response = next(
            line
            for line in lines
            if line.code == f"humidifier.{reconciliation}"
        )
        assert "HI sent" not in response.text
        if dispatch_result == "exception":
            assert response.truth == "failed"
        else:
            assert response.truth == "not_confirmed"


def test_humidifier_response_long_label_splits_and_folds_physical_caveat():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    long_label = "L" * 64
    entry.data["level_labels"] = {"level1": long_label}
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    # Exercise the presentation contract's 64-character dynamic-label ceiling;
    # configured level labels currently have a stricter storage bound.
    engine._level_labels["level1"] = long_label
    _set_humidifier_display_truth(
        hass,
        reconciliation="platform_idle",
        demand="requested",
        observed="on",
        platform_action="idle",
    )

    maximum_detail = _active_humidifier_detail()
    maximum_detail.update(
        {
            "season": "S" * 32,
            "humidity": 100.0,
            "low": 100.0,
            "recovery_off": 100.0,
        }
    )
    lines = engine._humidifier_display_lines([maximum_detail])
    assert len(lines) == 2
    assert lines[0].text.startswith("Separately, L")
    assert "… needs humidification" in lines[0].text
    assert lines[1].text.startswith(f"For {long_label}, Home Assistant reports")
    assert all(
        len(line.text) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
        for line in lines
    )
    environment_line = next(
        line for line in lines if line.code == "humidifier.environment"
    )
    assert f"Under the {'S' * 32} profile" in environment_line.text
    assert "demand starts at 100.0%" in environment_line.text
    assert "clears at 100.0%" in environment_line.text
    assert (
        sum("physical moisture output is not measured" in line.text for line in lines)
        == 1
    )
    assert not any(
        "physical_output" in line.code or "caveat" in line.code for line in lines
    )

    missing_season_detail = _active_humidifier_detail()
    missing_season_detail["season"] = None
    missing_season_lines = engine._humidifier_display_lines([missing_season_detail])
    missing_season_environment = next(
        line
        for line in missing_season_lines
        if line.code == "humidifier.environment"
    )
    assert (
        "Under the current profile, demand starts" in missing_season_environment.text
    )
    assert "profile profile" not in missing_season_environment.text

    defensive_fallback = engine._bounded_humidifier_environment(
        long_label,
        f"Meanwhile, {long_label} needs humidification at {'9' * 240}%.",
    )
    assert defensive_fallback == (
        "Meanwhile, the configured humidifier level needs humidification."
    )
    assert "structured reason data" not in defensive_fallback

    facts = engine._make_reason_facts(
        "normal",
        "monitoring",
        "neutral",
        "Monitoring",
        [
            engine_mod.ReasonLine(
                "why",
                "system",
                "normal.no_higher_priority_lane",
                "selected",
                "HI is monitoring; no ventilation response is selected.",
            ),
            *lines,
        ],
    )
    display = engine_mod.build_display_reason(facts)
    assert display["schema"] == "hi.reason.v1"


def test_long_labels_keep_retry_and_aq_selection_lines_inside_contract_bounds():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    long_label = "Household Environmental Level " + ("L" * 40)
    hass = _FakeHass(
        entry,
        _states(
            outputs={
                "fan.one": _FakeState(
                    "off",
                    {"friendly_name": "A" * 64},
                ),
                "fan.two": _FakeState(
                    "off",
                    {"friendly_name": "B" * 64},
                ),
            }
        ),
    )
    engine = engine_mod.HIAutomationEngine(hass, entry)
    engine._level_labels["level1"] = long_label
    _set_humidifier_display_truth(
        hass,
        reconciliation="retrying",
        demand="requested",
        observed="off",
    )

    humidifier_lines = engine._humidifier_display_lines(
        [_active_humidifier_detail()]
    )
    assert len(humidifier_lines) == 2
    assert all(
        len(line.text) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
        for line in humidifier_lines
    )
    retry_line = next(
        line for line in humidifier_lines if line.code == "humidifier.retrying"
    )
    assert retry_line.text.startswith("For Household Environmental Level")
    assert "cannot confirm that Home Assistant received a request" in retry_line.text

    aq_lines = engine._aq_display_lines(
        [
            {
                "level": "level1",
                "trigger_facts": [
                    engine_mod._TriggerFact(
                        "iaq_bad",
                        34.0,
                        60.0,
                        "index",
                        "<=",
                    )
                ],
                "outputs": ["fan.one", "fan.two"],
                "output_level": "boost",
            }
        ]
    )
    assert len(aq_lines) == 2
    assert all(
        len(line.text) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
        for line in aq_lines
    )
    assert aq_lines[1].text.endswith(
        "66% for 2 configured air-quality ventilation outputs."
    )
    engine_mod.build_display_reason(
        engine._make_reason_facts(
            "air_quality",
            "trigger_active",
            "active",
            "Air quality response lane selected",
            [*aq_lines, *humidifier_lines],
        )
    )


def test_multibyte_labels_and_outputs_keep_dual_aq_humidifier_contract_available():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    emoji_label = "🌫️" * 32
    entry.data["level_labels"] = {
        "level1": emoji_label,
        "level2": emoji_label,
    }
    outputs = {
        f"fan.output_{index}": _FakeState(
            "off",
            {"friendly_name": "🧪" * 64},
        )
        for index in range(4)
    }
    hass = _FakeHass(entry, _states(outputs=outputs))
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime["humidifier_status"] = {
        "schema": 1,
        "overall": "output_on",
        "lanes": {
            level: {
                "demand": "requested",
                "environmental_state": "start",
                "reconciliation": "output_on",
                "observed": "on",
                "platform_action": "not_exposed",
                "failure_category": None,
            }
            for level in ("level1", "level2")
        },
    }
    runtime["humidifier_reconciliation"] = {"schema": 1, "outputs": {}}
    engine = engine_mod.HIAutomationEngine(hass, entry)
    facts = engine._runtime_display_facts(
        runtime_mode="air_quality",
        alert_details=[],
        zone_detail=None,
        aq_details=[
            {
                "level": "level1",
                "trigger_active": False,
                "outputs": ["fan.output_0", "fan.output_1"],
                "output_level": "boost",
            },
            {
                "level": "level2",
                "trigger_active": False,
                "outputs": ["fan.output_2", "fan.output_3"],
                "output_level": "boost",
            },
        ],
        humidifier_details=[
            {
                "level": level,
                "season": "Winter",
                "humidity": 51.4,
                "low": 54.0,
                "recovery_off": 55.0,
                "environmental_state": "start",
            }
            for level in ("level1", "level2")
        ],
    )
    display = engine_mod.build_display_reason(facts)
    encoded = json.dumps(
        display,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert len(encoded) <= engine_mod.DISPLAY_REASON_MAX_BYTES
    assert len(display["lines"]) <= engine_mod.DISPLAY_REASON_MAX_LINES
    assert all(
        len(line["text"]) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
        for line in display["lines"]
    )
    action_lines = [line for line in display["lines"] if line["role"] == "action"]
    assert len(action_lines) == 2
    assert all(
        "2 configured air-quality ventilation outputs" in line["text"]
        for line in action_lines
    )
    assert "🧪" not in " ".join(line["text"] for line in display["lines"])


def test_concurrent_aq_keeps_its_headline_and_self_contained_humidifier_response():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    entry.data["level_labels"] = {"level1": "Ground Floor"}
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    _set_humidifier_display_truth(
        hass,
        reconciliation="output_on",
        demand="requested",
        observed="on",
    )

    facts = engine._runtime_display_facts(
        runtime_mode="air_quality",
        alert_details=[],
        zone_detail=None,
        aq_details=[
            {
                "level": "level1",
                "trigger_active": True,
                "outputs": [],
                "output_level": "boost",
            }
        ],
        humidifier_details=[_active_humidifier_detail()],
    )
    assert facts.headline == "Air quality response lane selected"
    assert [line.text for line in facts.lines[:2]] == [
        "Ground Floor air-quality response remains selected while its run window is active.",
        (
            "For Ground Floor, HI keeps 66% selected for configured air-quality "
            "ventilation output while the run window remains active."
        ),
    ]
    humidifier_lines = [line for line in facts.lines if line.scope == "humidifier"]
    assert humidifier_lines
    assert humidifier_lines[0].text.startswith(
        "Separately, Ground Floor needs humidification"
    )
    assert sum(
        "physical moisture output is not measured" in line.text
        for line in facts.lines
    ) == 1
    assert len(facts.lines) <= engine_mod.DISPLAY_REASON_TARGET_LINES
    engine_mod.build_display_reason(facts)


def test_aq_presentation_order_is_canonical_when_details_arrive_reversed():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    entry.data["level_labels"] = {
        "level1": "Downstairs",
        "level2": "Upstairs",
    }
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    lines = engine._aq_display_lines(
        [
            {
                "level": "level2",
                "outputs": [],
                "output_level": "boost",
            },
            {
                "level": "level1",
                "outputs": [],
                "output_level": "boost",
            },
        ]
    )

    assert lines[0].text.startswith("Downstairs air-quality response")
    assert lines[1].text.startswith("For Downstairs, HI keeps")
    assert lines[2].text.startswith("Upstairs air-quality response")
    assert lines[3].text.startswith("For Upstairs, HI keeps")


def test_dual_aq_and_humidifier_copy_reads_as_one_ordered_household_explanation():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    entry.data["level_labels"] = {
        "level1": "Downstairs",
        "level2": "Upstairs",
    }
    hass = _FakeHass(
        entry,
        _states(
            outputs={
                "fan.kitchen": _FakeState(
                    "off",
                    {"friendly_name": "Kitchen air"},
                ),
                "fan.living": _FakeState(
                    "off",
                    {"friendly_name": "Living room Air"},
                ),
                "fan.upstairs": _FakeState(
                    "off",
                    {"friendly_name": "Upstairs air"},
                ),
            }
        ),
    )
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime["humidifier_status"] = {
        "schema": 1,
        "overall": "output_on",
        "lanes": {
            level: {
                "demand": "requested",
                "environmental_state": "recovering",
                "reconciliation": "output_on",
                "observed": "on",
                "platform_action": "not_exposed",
                "output_count": 1,
                "failure_category": None,
            }
            for level in ("level1", "level2")
        },
    }
    runtime["humidifier_reconciliation"] = {"schema": 1, "outputs": {}}
    engine = engine_mod.HIAutomationEngine(hass, entry)
    facts = engine._runtime_display_facts(
        runtime_mode="air_quality",
        alert_details=[],
        zone_detail=None,
        aq_details=[
            {
                "level": "level1",
                "trigger_active": True,
                "trigger_facts": [
                    engine_mod._TriggerFact(
                        "iaq_bad",
                        34.0,
                        60.0,
                        "index",
                        "<=",
                    )
                ],
                "outputs": ["fan.kitchen", "fan.living"],
                "output_level": "boost",
            },
            {
                "level": "level2",
                "trigger_active": True,
                "trigger_facts": [
                    engine_mod._TriggerFact(
                        "iaq_bad",
                        17.0,
                        60.0,
                        "index",
                        "<=",
                    )
                ],
                "outputs": ["fan.upstairs", "fan.living"],
                "output_level": "boost",
            },
        ],
        humidifier_details=[
            {
                "level": "level1",
                "season": "Summer",
                "humidity": 53.2,
                "low": 51.0,
                "recovery_off": 54.0,
                "environmental_state": "recovering",
            },
            {
                "level": "level2",
                "season": "Summer",
                "humidity": 52.2,
                "low": 51.0,
                "recovery_off": 54.0,
                "environmental_state": "recovering",
            },
        ],
    )

    assert facts.headline == "Air quality response lane selected"
    assert [line.text for line in facts.lines] == [
        "Downstairs IAQ is 34, at or below the response point of 60.",
        "So for Downstairs, HI selected 66% for Kitchen air and Living room Air.",
        "Upstairs IAQ is 17, at or below the response point of 60.",
        "So for Upstairs, HI selected 66% for Upstairs air and Living room Air.",
        (
            "Separately, Downstairs still needs humidification at 53.2%. Under the "
            "Summer profile, demand starts at 51.0% and clears at 54.0% to avoid "
            "short cycling."
        ),
        (
            "For Downstairs, Home Assistant reports that the output is on; physical "
            "moisture output is not measured."
        ),
        (
            "Meanwhile, Upstairs still needs humidification at 52.2%. Under the "
            "Summer profile, demand starts at 51.0% and clears at 54.0% to avoid "
            "short cycling."
        ),
        (
            "For Upstairs, Home Assistant reports that the output is on; physical "
            "moisture output is not measured."
        ),
    ]
    assert [line.truth for line in facts.lines] == [
        "observed",
        "selected",
        "observed",
        "selected",
        "selected",
        "observed",
        "selected",
        "observed",
    ]
    assert [line.role for line in facts.lines] == [
        "why",
        "action",
        "why",
        "action",
        "notice",
        "notice",
        "notice",
        "notice",
    ]
    assert [line.code for line in facts.lines] == [
        "air_quality.iaq_bad",
        "air_quality.output_level_selected",
        "air_quality.iaq_bad",
        "air_quality.output_level_selected",
        "humidifier.environment",
        "humidifier.output_on",
        "humidifier.environment",
        "humidifier.output_on",
    ]
    assert [dict(line.args) for line in facts.lines] == [
        {"measured": 34.0, "threshold": 60.0, "unit": "index"},
        {"output_count": 2, "output_level": "66%"},
        {"measured": 17.0, "threshold": 60.0, "unit": "index"},
        {"output_count": 2, "output_level": "66%"},
        {
            "demand_active": True,
            "dispatch_evidence": "not_confirmed",
            "environmental_state": "recovering",
            "lane": "level1",
            "observed": "on",
            "reconciliation": "output_on",
        },
        {
            "demand_active": True,
            "dispatch_evidence": "not_confirmed",
            "environmental_state": "recovering",
            "lane": "level1",
            "observed": "on",
            "reconciliation": "output_on",
        },
        {
            "demand_active": True,
            "dispatch_evidence": "not_confirmed",
            "environmental_state": "recovering",
            "lane": "level2",
            "observed": "on",
            "reconciliation": "output_on",
        },
        {
            "demand_active": True,
            "dispatch_evidence": "not_confirmed",
            "environmental_state": "recovering",
            "lane": "level2",
            "observed": "on",
            "reconciliation": "output_on",
        },
    ]
    assert len(facts.lines) == engine_mod.DISPLAY_REASON_MAX_LINES
    assert all(
        len(line.text) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
        for line in facts.lines
    )
    engine_mod.build_display_reason(facts)


def test_first_active_demand_does_not_say_also_after_inactive_shared_lane():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    entry.data["level_labels"] = {
        "level1": "Downstairs",
        "level2": "Upstairs",
    }
    hass = _FakeHass(entry, _states())
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime["humidifier_status"] = {
        "schema": 1,
        "overall": "output_on",
        "lanes": {
            "level1": {
                "demand": "inactive",
                "environmental_state": "inactive",
                "reconciliation": "inactive_shared_output",
                "observed": "on",
                "platform_action": "not_exposed",
                "failure_category": None,
            },
            "level2": {
                "demand": "requested",
                "environmental_state": "start",
                "reconciliation": "output_on",
                "observed": "on",
                "platform_action": "not_exposed",
                "failure_category": None,
            },
        },
    }
    runtime["humidifier_reconciliation"] = {"schema": 1, "outputs": {}}
    engine = engine_mod.HIAutomationEngine(hass, entry)
    lines = engine._humidifier_display_lines(
        [
            {
                "level": "level2",
                "season": "Winter",
                "humidity": 51.4,
                "low": 54.0,
                "recovery_off": 55.0,
                "environmental_state": "start",
            }
        ]
    )

    assert "Upstairs needs humidification" in lines[1].text
    assert "Upstairs also needs humidification" not in lines[1].text


def test_inactive_humidifier_isolation_keeps_one_existing_global_notice():
    engine_mod, _register_mod = _load_target_modules()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    engine = engine_mod.HIAutomationEngine(hass, entry)
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime["hi_input_booleans"]["air_isolate_humidifier_outputs"].is_on = True
    _set_humidifier_display_truth(
        hass,
        reconciliation="isolated",
        demand="inactive",
        observed="off",
        overall="inactive",
    )

    assert engine._humidifier_display_lines([]) == []
    isolation_lines = engine._isolation_display_lines()
    assert [line.text for line in isolation_lines] == [
        (
            "Humidifier-output isolation is active, so HI is not sending humidifier "
            "commands to Home Assistant."
        )
    ]


def test_inactive_humidifier_isolation_has_one_notice_on_gate_and_co_paths():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        expected_notice = (
            "Humidifier-output isolation is active, so HI is not sending humidifier "
            "commands to Home Assistant."
        )
        for scenario, expected_family in (
            ("gate_no_change", "gate"),
            ("gate_safe_state", "gate"),
            ("co_emergency", "co_emergency"),
        ):
            entry = _entry_with_humidifiers(
                {
                    "level1": {
                        "enabled": True,
                        "outputs": ["switch.level1"],
                        "band_adjust": 0,
                    }
                }
            )
            hass = _FakeHass(
                entry,
                _states(
                    level1=55,
                    outputs={"switch.level1": _FakeState("off")},
                ),
            )
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            runtime["hi_input_booleans"][
                "air_isolate_humidifier_outputs"
            ].is_on = True
            engine = engine_mod.HIAutomationEngine(hass, entry)

            if scenario.startswith("gate_"):
                outside_start = (datetime.now() + timedelta(hours=1)).time()
                outside_end = (datetime.now() + timedelta(hours=2)).time()
                engine.time_gate = {
                    "enabled": True,
                    "start": outside_start,
                    "end": outside_end,
                    "outside_action": (
                        "safe_state"
                        if scenario == "gate_safe_state"
                        else "no_change"
                    ),
                }
            else:
                engine._co_emergency_triggered = lambda: True

            try:
                await engine._evaluate()

                display = runtime["runtime_display_reason"]
                assert display["family"] == expected_family, scenario
                isolation_lines = [
                    line
                    for line in display["lines"]
                    if line["code"] == "isolation.humidifier_outputs"
                ]
                assert len(isolation_lines) == 1, scenario
                assert isolation_lines[0]["text"] == expected_notice, scenario
                assert not any(
                    line["code"].startswith("humidifier.")
                    for line in display["lines"]
                ), scenario

                if scenario == "gate_no_change":
                    assert "humidifier_status" not in runtime
                    assert "humidifier_reconciliation" not in runtime
                else:
                    lane = runtime["humidifier_status"]["lanes"]["level1"]
                    output = runtime["humidifier_reconciliation"]["outputs"][
                        "output_1"
                    ]
                    assert lane["demand"] == "inactive", scenario
                    assert lane["reconciliation"] == "isolated", scenario
                    assert output["reconciliation"] == "isolated", scenario
                assert not _humidifier_calls(
                    hass,
                    entity_id="switch.level1",
                ), scenario
            finally:
                await engine.async_stop()

    asyncio.run(run())


def test_full_cycle_presenter_failures_do_not_change_humidifier_reconciliation():
    async def execute(failure_stage=None):
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(level1=40, outputs={"switch.level1": _FakeState("off")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        engine._monotonic = lambda: 1000.0
        scheduled = []
        engine._schedule_humidifier_retry = (
            lambda entity_id, when: scheduled.append((entity_id, when))
        )
        original_presenter = engine_mod.build_display_reason

        if failure_stage == "fact_collection":
            def fail_facts(self, *_args, **_kwargs):
                raise RuntimeError("fixture fact-collection failure")

            engine._runtime_display_facts = MethodType(fail_facts, engine)
        elif failure_stage == "presenter":
            def fail_presenter(_facts):
                raise RuntimeError("fixture presenter failure")

            engine_mod.build_display_reason = fail_presenter

        try:
            await engine._evaluate()
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            output = next(
                iter(runtime["humidifier_reconciliation"]["outputs"].values())
            )
            helper = runtime["hi_input_booleans"][
                "air_downstairs_humidifier_active"
            ]
            return {
                "calls": copy.deepcopy(hass.services.calls),
                "scheduled": list(scheduled),
                "technical_reason": runtime.get("runtime_reason_full")
                or runtime.get("runtime_reason"),
                "humidifier_status": copy.deepcopy(runtime["humidifier_status"]),
                "output_truth": {
                    key: copy.deepcopy(output.get(key))
                    for key in (
                        "desired",
                        "observed",
                        "reconciliation",
                        "dispatch_result",
                        "last_command_intent",
                        "attempts",
                        "maximum_attempts",
                        "failure_category",
                        "fault_latched",
                    )
                },
                "helper_active": helper.is_on,
                "display_present": "runtime_display_reason" in runtime,
            }
        finally:
            engine_mod.build_display_reason = original_presenter
            await engine.async_stop()

    async def run():
        baseline = await execute()
        fact_failure = await execute("fact_collection")
        presenter_failure = await execute("presenter")

        assert baseline["display_present"] is True
        for failure in (fact_failure, presenter_failure):
            assert failure["display_present"] is False
            assert {
                key: value
                for key, value in failure.items()
                if key != "display_present"
            } == {
                key: value
                for key, value in baseline.items()
                if key != "display_present"
            }

    asyncio.run(run())


def test_failed_display_publication_clears_stale_contract_and_keeps_new_technical_reason():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers({})
        hass = _FakeHass(entry, _states())
        engine = engine_mod.HIAutomationEngine(hass, entry)
        facts = engine_mod.ReasonFacts(
            family="normal",
            variant="monitoring",
            attention="neutral",
            headline="Monitoring",
            lines=(
                engine_mod.ReasonLine(
                    "why",
                    "system",
                    "normal.no_higher_priority_lane",
                    "selected",
                    "No higher-priority ventilation lane is selected.",
                ),
            ),
        )
        try:
            await engine._set_runtime_reason(
                "First technical reason.",
                display_facts_factory=lambda: facts,
            )
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["runtime_display_reason"]["headline"] == "Monitoring"

            def fail_fact_collection():
                raise RuntimeError("fixture presenter failure")

            await engine._set_runtime_reason(
                "Second technical reason.",
                display_facts_factory=fail_fact_collection,
            )

            assert runtime["runtime_reason"] == "Second technical reason."
            assert runtime["runtime_reason_full"] is None
            assert "runtime_display_reason" not in runtime
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_global_gates_alert_and_co_move_active_output_to_desired_off_truth():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        for scenario in (
            "control_disabled",
            "pause",
            "presence_gate",
            "time_gate",
            "telemetry_unavailable",
            "alert",
            "co_emergency",
        ):
            entry = _entry_with_humidifiers(
                {
                    "level1": {
                        "enabled": True,
                        "outputs": ["humidifier.level1"],
                        "band_adjust": 0,
                    }
                }
            )
            hass = _FakeHass(
                entry,
                _states(
                    outputs={"humidifier.level1": _FakeState("on")},
                ),
            )
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            helper = runtime["hi_input_booleans"][
                "air_downstairs_humidifier_active"
            ]
            helper.is_on = True
            engine = engine_mod.HIAutomationEngine(hass, entry)

            if scenario == "control_disabled":
                runtime["hi_input_booleans"]["air_control_enabled"].is_on = False
            elif scenario == "pause":
                runtime["hi_timers"]["air_control_pause"].native_value = "active"
            elif scenario == "presence_gate":
                engine.presence_gate = {
                    "enabled": True,
                    "entities": ["binary_sensor.home_presence"],
                    "present_states": ["on"],
                    "away_states": ["off"],
                }
                hass.states._values["binary_sensor.home_presence"] = _FakeState(
                    "off"
                )
            elif scenario == "time_gate":
                outside_start = (datetime.now() + timedelta(hours=1)).time()
                outside_end = (datetime.now() + timedelta(hours=2)).time()
                engine.time_gate = {
                    "enabled": True,
                    "start": outside_start,
                    "end": outside_end,
                    "outside_action": "safe_state",
                }
            elif scenario == "telemetry_unavailable":
                for entity_id in (
                    "sensor.kitchen_h",
                    "sensor.hall_h",
                    "sensor.bed_h",
                ):
                    hass.states._values[entity_id] = _FakeState("unavailable")
            elif scenario == "alert":
                async def active_alert():
                    return True, [
                        {
                            "label": "Humidity Danger",
                            "trigger_type": "humidity_danger",
                            "outputs": [],
                        }
                    ]

                engine._handle_alerts = active_alert
            else:
                engine._co_emergency_triggered = lambda: True

            try:
                await engine._evaluate()

                output = runtime["humidifier_reconciliation"]["outputs"][
                    "output_1"
                ]
                assert output["desired"] == "off", scenario
                assert output["observed"] == "on", scenario
                assert output["reconciliation"] == "stopping", scenario
                assert not helper.is_on, scenario
                assert len(
                    _humidifier_calls(
                        hass,
                        entity_id="humidifier.level1",
                        service="turn_off",
                    )
                ) == 1, scenario
                display = runtime["runtime_display_reason"]
                display_text = " ".join(
                    [display["headline"]]
                    + [line["text"] for line in display["lines"]]
                )
                assert "HI sent the output-off request to Home Assistant" in display_text, scenario
                assert "humidifier.level1" not in display_text, scenario
            finally:
                await engine.async_stop()

    asyncio.run(run())


def test_manual_override_holds_observed_humidifier_truth_without_dispatch_and_auto_resumes():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                },
                "level2": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                },
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"humidifier.level1": _FakeState("on")}),
        )
        runtime = hass.data["humidity_intelligence"][ENTRY_ID]
        runtime["hi_input_booleans"][
            "air_isolate_humidifier_outputs"
        ].is_on = False
        manual = runtime["hi_input_booleans"]["air_control_manual_override"]
        manual.is_on = True
        manual.entity_id = "switch.hi_air_control_manual_override"
        engine = engine_mod.HIAutomationEngine(hass, entry)
        assert manual.entity_id in engine._evaluation_sources()

        record = engine._new_humidifier_output_record()
        engine._humidifier_output_records["humidifier.level1"] = record
        engine._schedule_humidifier_retry(
            "humidifier.level1",
            engine._monotonic() + 120,
        )
        pending_retry = engine._humidifier_retry_tasks["humidifier.level1"]

        try:
            await engine._evaluate()
            await engine._evaluate()
            await asyncio.sleep(0)

            assert pending_retry.cancelled()
            assert engine._humidifier_retry_tasks == {}
            assert _humidifier_calls(hass) == []
            assert runtime["runtime_mode"] == "manual_override"
            assert runtime["runtime_mode_display"] == "MANUAL OVERRIDE"
            output = runtime["humidifier_reconciliation"]["outputs"]["output_1"]
            assert output["desired"] == "manual"
            assert output["observed"] == "on"
            assert output["reconciliation"] == "manual_hold"
            assert output["configured_owners"] == ["level1", "level2"]
            assert output["last_command_intent"] == "none"
            assert output["dispatch_result"] == "not_requested"
            assert output["attempts"] == 0
            assert runtime["humidifier_reconciliation"]["summary"][
                "manual_hold_outputs"
            ] == 1
            assert runtime["humidifier_status"]["overall"] == "manual_hold"
            assert not runtime["hi_input_booleans"][
                "air_downstairs_humidifier_active"
            ].is_on
            display_text = " ".join(
                [runtime["runtime_display_reason"]["headline"]]
                + [
                    line["text"]
                    for line in runtime["runtime_display_reason"]["lines"]
                ]
            )
            assert "Manual control is active" in display_text
            assert (
                "HI leaves fans, switches, humidifiers, and alert lights as they are"
                in display_text
            )
            assert "Control stays with you or another automation" in display_text
            assert "until Manual is turned off" in display_text
            assert (
                "CO emergency protection can still run configured ventilation at full speed"
                in display_text
            )
            assert "released HI ownership" not in display_text
            assert "holding HI ownership" not in display_text
            assert "selected" not in display_text.lower()
            humidifier_text = " ".join(
                line.text for line in engine._humidifier_display_lines([])
            )
            assert (
                "while Manual is on, HI shows the humidifier state reported by Home Assistant without changing it"
                in humidifier_text
            )

            attempted, result = await engine._dispatch_humidifier_output(
                "humidifier.level1",
                False,
            )
            assert (attempted, result) == (False, "manual_override")
            assert _humidifier_calls(hass) == []

            manual.is_on = False
            hass.states._values["humidifier.level1"] = _FakeState("off")
            await engine.async_request_evaluate()
            assert runtime["runtime_mode"] == "normal"
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="humidifier.level1",
                    service="turn_on",
                )
            ) == 1
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_manual_plus_co_forces_ventilation_only_and_preserves_humidifier():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                }
            }
        )
        entry.data["zones"] = {
            "zone1": {
                "enabled": True,
                "outputs": ["fan.co_ventilation"],
            }
        }
        hass = _FakeHass(
            entry,
            _states(
                outputs={
                    "fan.co_ventilation": _FakeState(
                        "off",
                        {"percentage": 0, "preset_mode": "manual"},
                    ),
                    "humidifier.level1": _FakeState("on"),
                }
            ),
        )
        runtime = hass.data["humidity_intelligence"][ENTRY_ID]
        runtime["hi_input_booleans"]["air_isolate_fan_outputs"].is_on = False
        runtime["hi_input_booleans"][
            "air_isolate_humidifier_outputs"
        ].is_on = False
        runtime["hi_input_booleans"]["air_control_manual_override"].is_on = True
        engine = engine_mod.HIAutomationEngine(hass, entry)
        engine._co_emergency_triggered = lambda: True

        try:
            await engine._evaluate()
            assert runtime["runtime_mode"] == "co_emergency"
            fan_calls = [call for call in hass.services.calls if call[0] == "fan"]
            assert [call[1] for call in fan_calls] == ["turn_on", "set_percentage"]
            assert fan_calls[-1][2]["percentage"] == 100
            assert _humidifier_calls(
                hass,
                entity_id="humidifier.level1",
            ) == []
            output = runtime["humidifier_reconciliation"]["outputs"]["output_1"]
            assert output["desired"] == "manual"
            assert output["observed"] == "on"
            assert output["reconciliation"] == "manual_hold"
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_output_on_is_observed_without_duplicate_dispatch_and_idle_is_honest():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["humidifier.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(
                outputs={
                    "humidifier.level1": _FakeState(
                        "on",
                        {"action": "idle"},
                    )
                }
            ),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            await engine._evaluate()
            assert not _humidifier_calls(hass, entity_id="humidifier.level1")
            lane = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_status"
            ]["lanes"]["level1"]
            assert lane["demand"] == "requested"
            assert lane["observed"] == "on"
            assert lane["platform_action"] == "idle"
            assert lane["reconciliation"] == "platform_idle"
            display = hass.data["humidity_intelligence"][ENTRY_ID][
                "runtime_display_reason"
            ]
            display_text = " ".join(line["text"] for line in display["lines"])
            assert (
                "Home Assistant reports its output on, but its humidifier action is idle"
                in display_text
            )
            assert display_text.count("physical moisture output is not measured") == 1
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_long_demand_output_stop_requests_prompt_reconciliation():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("on")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        engine._schedule_humidifier_retry = lambda _entity_id, _when: None
        try:
            await engine._evaluate()
            assert not _humidifier_calls(hass, entity_id="switch.level1")
            hass.states._values["switch.level1"] = _FakeState("off")
            await engine._evaluate()
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="switch.level1",
                    service="turn_on",
                )
            ) == 1
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_retry_schedule_is_bounded_and_fault_latches_without_hammering():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("off")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        clock = [0.0]
        engine._monotonic = lambda: clock[0]
        engine._schedule_humidifier_retry = lambda _entity_id, _when: None
        try:
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 1

            clock[0] = 29.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 1

            clock[0] = 30.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 2

            clock[0] = 149.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 2

            clock[0] = 150.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 3

            clock[0] = 165.0
            await engine._evaluate()
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 3
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["fault_latched"] is True
            assert output["failure_category"] == "retry_exhausted"
            assert output["attempts"] == 3

            hass.states._values["switch.level1"] = _FakeState("on")
            clock[0] = 180.0
            await engine._evaluate()
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["reconciliation"] == "output_on"
            assert output["fault_latched"] is False
            assert output["attempts"] == 3

            hass.states._values["switch.level1"] = _FakeState("off")
            clock[0] = 200.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 3
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["fault_latched"] is True
            assert output["attempts"] == 3

            hass.states._values["sensor.kitchen_h"] = _FakeState(55)
            hass.states._values["sensor.hall_h"] = _FakeState(55)
            clock[0] = 210.0
            await engine._evaluate()
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["desired"] == "off"
            assert output["attempts"] == 0
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_observed_recovery_preserves_retry_budget_until_demand_clears():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("off")}),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        clock = [0.0]
        engine._monotonic = lambda: clock[0]
        engine._schedule_humidifier_retry = lambda _entity_id, _when: None
        try:
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 1

            hass.states._values["switch.level1"] = _FakeState("on")
            clock[0] = 5.0
            await engine._evaluate()
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["attempts"] == 1
            assert output["reconciliation"] == "output_on"

            hass.states._values["switch.level1"] = _FakeState("off")
            clock[0] = 300.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 2
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["attempts"] == 2
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_retry_cleanup_does_not_cancel_the_waking_evaluation_task():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers({})
        hass = _FakeHass(entry, _states())
        engine = engine_mod.HIAutomationEngine(hass, entry)
        current = asyncio.current_task()
        assert current is not None
        engine._humidifier_retry_tasks["switch.level1"] = current
        engine._cancel_humidifier_retry("switch.level1")
        await asyncio.sleep(0)
        assert "switch.level1" not in engine._humidifier_retry_tasks
        assert not current.cancelled()

    asyncio.run(run())


def test_service_unavailable_and_exception_degrade_without_false_confirmation():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        entry.data["level_labels"] = {"level1": "Plant Room"}

        unavailable_hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("off")}),
        )
        unavailable_hass.services.has_service = lambda _domain, _service: False
        unavailable_engine = engine_mod.HIAutomationEngine(unavailable_hass, entry)
        try:
            await unavailable_engine._evaluate()
            output = unavailable_hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert not _humidifier_calls(unavailable_hass)
            assert output["dispatch_result"] == "service_unavailable"
            assert output["last_dispatch_utc"] is None
            assert output["reconciliation"] == "degraded"
            assert output["attempts"] == 0
            lane = unavailable_hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_status"
            ]["lanes"]["level1"]
            assert lane["failure_category"] is None
            display = unavailable_hass.data["humidity_intelligence"][ENTRY_ID][
                "runtime_display_reason"
            ]
            response = next(
                line
                for line in display["lines"]
                if line["code"] == "humidifier.degraded"
            )
            environment = next(
                line
                for line in display["lines"]
                if line["code"] == "humidifier.environment"
            )
            assert response["truth"] == "blocked"
            assert environment["text"].startswith(
                "Separately, Plant Room needs humidification"
            )
            assert (
                "a required home assistant output-on service is unavailable, so hi did not send that request."
                in response["text"].lower()
            )
            assert "HI sent" not in response["text"]
            assert len(response["text"]) <= engine_mod.DISPLAY_REASON_MAX_LINE_TEXT
            assert len(display["lines"]) <= engine_mod.DISPLAY_REASON_MAX_LINES
        finally:
            await unavailable_engine.async_stop()

        unavailable_stop_hass = _FakeHass(
            entry,
            _states(
                level1=55,
                outputs={"switch.level1": _FakeState("on")},
            ),
        )
        unavailable_stop_hass.services.has_service = (
            lambda _domain, _service: False
        )
        unavailable_stop_engine = engine_mod.HIAutomationEngine(
            unavailable_stop_hass,
            entry,
        )
        try:
            await unavailable_stop_engine._evaluate()
            runtime = unavailable_stop_hass.data["humidity_intelligence"][ENTRY_ID]
            output = runtime["humidifier_reconciliation"]["outputs"]["output_1"]
            assert not _humidifier_calls(unavailable_stop_hass)
            assert output["dispatch_result"] == "service_unavailable"
            assert output["last_command_intent"] == "turn_off"
            assert output["last_dispatch_utc"] is None
            assert output["reconciliation"] == "degraded"
            assert output["attempts"] == 0
            assert runtime["humidifier_status"]["lanes"]["level1"][
                "demand"
            ] == "inactive"
            response = next(
                line
                for line in runtime["runtime_display_reason"]["lines"]
                if line["code"] == "humidifier.degraded"
            )
            assert response["truth"] == "blocked"
            assert (
                "a required home assistant output-off service is unavailable, so hi did not send that request."
                in response["text"].lower()
            )
            assert "HI sent" not in response["text"]
        finally:
            await unavailable_stop_engine.async_stop()

        exception_hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("off")}),
        )

        async def fail_dispatch(_domain, _service, data=None, blocking=False):
            assert blocking is False
            raise RuntimeError("fixture service failure")

        exception_hass.services.async_call = fail_dispatch
        exception_engine = engine_mod.HIAutomationEngine(exception_hass, entry)
        exception_engine._schedule_humidifier_retry = (
            lambda _entity_id, _when: None
        )
        try:
            await exception_engine._evaluate()
            output = exception_hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["dispatch_result"] == "exception"
            assert output["last_dispatch_utc"] is not None
            assert output["failure_category"] == "dispatch_exception"
            assert output["attempts"] == 1
            assert output["reconciliation"] == "retrying"
            display = exception_hass.data["humidity_intelligence"][ENTRY_ID][
                "runtime_display_reason"
            ]
            display_text = " ".join(line["text"] for line in display["lines"])
            assert "a Home Assistant output-on request failed" in display_text
            assert "sent" not in display_text.lower()
        finally:
            await exception_engine.async_stop()

    asyncio.run(run())


def test_other_not_attempted_dispatch_results_have_exact_presentation_truth():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        for (
            entity_id,
            entity_state,
            expected_result,
            expected_truth,
            expected_copy,
        ) in (
            (
                "light.level1",
                _FakeState("off"),
                "unsupported_domain",
                "blocked",
                "A configured humidifier output uses an unsupported entity type, so HI did not send that request.",
            ),
            (
                "switch.missing",
                None,
                "missing",
                "unavailable",
                "A configured humidifier output is not available in Home Assistant, so HI did not send that request.",
            ),
            (
                "switch.unknown",
                _FakeState("unknown"),
                "unknown",
                "unavailable",
                "A required humidifier output state is unavailable, so HI did not send that request.",
            ),
            (
                "switch.unavailable",
                _FakeState("unavailable"),
                "unavailable",
                "unavailable",
                "A required humidifier output state is unavailable, so HI did not send that request.",
            ),
        ):
            entry = _entry_with_humidifiers(
                {
                    "level1": {
                        "enabled": True,
                        "outputs": [entity_id],
                        "band_adjust": 0,
                    }
                }
            )
            entry.data["level_labels"] = {"level1": "Plant Room"}
            hass = _FakeHass(
                entry,
                _states(outputs={entity_id: _FakeState("off")}),
            )
            target_reads = [0]
            original_get = hass.states.get

            def changing_output_state(current_entity_id):
                if current_entity_id != entity_id:
                    return original_get(current_entity_id)
                target_reads[0] += 1
                if target_reads[0] == 1 or expected_result == "unsupported_domain":
                    return original_get(current_entity_id)
                return entity_state

            hass.states.get = changing_output_state
            engine = engine_mod.HIAutomationEngine(hass, entry)
            try:
                await engine._evaluate()

                runtime = hass.data["humidity_intelligence"][ENTRY_ID]
                output = runtime["humidifier_reconciliation"]["outputs"][
                    "output_1"
                ]
                assert output["dispatch_result"] == expected_result
                assert output["last_dispatch_utc"] is None
                assert output["attempts"] == 0
                assert output["reconciliation"] == "degraded"
                if expected_result != "unsupported_domain":
                    assert target_reads[0] >= 2
                assert runtime["humidifier_status"]["lanes"]["level1"][
                    "failure_category"
                ] is None
                response = next(
                    line
                    for line in runtime["runtime_display_reason"]["lines"]
                    if line["code"] == "humidifier.degraded"
                )
                assert response["truth"] == expected_truth
                assert "Plant Room" in response["text"]
                assert expected_copy.lower() in response["text"].lower()
                assert "HI sent" not in response["text"]
                assert not hass.services.calls
            finally:
                await engine.async_stop()

    asyncio.run(run())


def test_supported_output_domains_use_nonblocking_domain_safe_commands():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        for domain in ("humidifier", "fan", "switch"):
            entity_id = f"{domain}.level1"
            entry = _entry_with_humidifiers(
                {
                    "level1": {
                        "enabled": True,
                        "outputs": [entity_id],
                        "band_adjust": 0,
                    }
                }
            )
            hass = _FakeHass(
                entry,
                _states(outputs={entity_id: _FakeState("off")}),
            )
            engine = engine_mod.HIAutomationEngine(hass, entry)
            try:
                await engine._evaluate()
                assert _humidifier_calls(
                    hass,
                    entity_id=entity_id,
                    service="turn_on",
                ) == [(domain, "turn_on", {"entity_id": entity_id}, False)]
            finally:
                await engine.async_stop()

    asyncio.run(run())


def test_unknown_output_with_no_demand_gets_one_best_effort_off_only():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(
                level1=55,
                level2=55,
                outputs={"switch.level1": _FakeState("unknown")},
            ),
        )
        engine = engine_mod.HIAutomationEngine(hass, entry)
        clock = [0.0]
        engine._monotonic = lambda: clock[0]
        engine._schedule_humidifier_retry = lambda _entity_id, _when: None
        try:
            await engine._evaluate()
            await engine._evaluate()
            assert len(
                _humidifier_calls(
                    hass,
                    entity_id="switch.level1",
                    service="turn_off",
                )
            ) == 1
            clock[0] = 15.0
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 1
            output = hass.data["humidity_intelligence"][ENTRY_ID][
                "humidifier_reconciliation"
            ]["outputs"]["output_1"]
            assert output["reconciliation"] == "degraded"
            assert output["failure_category"] == "confirmation_timeout"
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_isolation_preserves_demand_and_defers_retry_budget_until_released():
    async def run():
        engine_mod, _register_mod = _load_target_modules()
        entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.level1"],
                    "band_adjust": 0,
                }
            }
        )
        hass = _FakeHass(
            entry,
            _states(outputs={"switch.level1": _FakeState("off")}),
        )
        isolation = hass.data["humidity_intelligence"][ENTRY_ID][
            "hi_input_booleans"
        ]["air_isolate_humidifier_outputs"]
        isolation.is_on = True
        engine = engine_mod.HIAutomationEngine(hass, entry)
        engine._schedule_humidifier_retry = lambda _entity_id, _when: None
        try:
            await engine._evaluate()
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["humidifier_status"]["lanes"]["level1"]["demand"] == "requested"
            assert runtime["humidifier_status"]["lanes"]["level1"][
                "reconciliation"
            ] == "isolated"
            assert not _humidifier_calls(hass)

            isolation.is_on = False
            await engine._evaluate()
            assert len(_humidifier_calls(hass, entity_id="switch.level1")) == 1
            output = runtime["humidifier_reconciliation"]["outputs"]["output_1"]
            assert output["attempts"] == 1
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_cross_family_and_cross_entry_ownership_suppress_writes():
    async def run():
        engine_mod, _register_mod = _load_target_modules()

        cross_family_entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["fan.shared"],
                    "band_adjust": 0,
                }
            }
        )
        cross_family_entry.data["zones"] = {
            "zone1": {
                "enabled": True,
                "outputs": ["fan.shared"],
            }
        }
        cross_family_hass = _FakeHass(
            cross_family_entry,
            _states(outputs={"fan.shared": _FakeState("off")}),
        )
        cross_family_engine = engine_mod.HIAutomationEngine(
            cross_family_hass,
            cross_family_entry,
        )
        try:
            result = await cross_family_engine._reconcile_humidifier_outputs(
                {"fan.shared": {"level1"}}
            )
            assert not _humidifier_calls(cross_family_hass)
            assert result["fan.shared"]["ownership_conflict"] == "cross_family_ownership"
            assert result["fan.shared"]["reconciliation"] == "degraded"
        finally:
            await cross_family_engine.async_stop()

        primary_entry = _entry_with_humidifiers(
            {
                "level1": {
                    "enabled": True,
                    "outputs": ["switch.shared"],
                    "band_adjust": 0,
                }
            }
        )
        primary_hass = _FakeHass(
            primary_entry,
            _states(outputs={"switch.shared": _FakeState("off")}),
        )
        primary_engine = engine_mod.HIAutomationEngine(primary_hass, primary_entry)
        other_entry = SimpleNamespace(
            entry_id="entry-other",
            data=dict(primary_entry.data),
            options={},
        )
        other_engine = engine_mod.HIAutomationEngine(primary_hass, other_entry)
        primary_hass.data["humidity_intelligence"]["entry-other"] = {
            "automation_engine": other_engine
        }
        try:
            result = await primary_engine._reconcile_humidifier_outputs(
                {"switch.shared": {"level1"}}
            )
            assert not _humidifier_calls(primary_hass)
            assert result["switch.shared"]["ownership_conflict"] == "cross_entry_ownership"
            assert result["switch.shared"]["reconciliation"] == "degraded"

            await other_engine.async_stop()
            result = await primary_engine._reconcile_humidifier_outputs(
                {"switch.shared": {"level1"}}
            )
            assert result["switch.shared"]["ownership_conflict"] is None
            assert result["switch.shared"]["reconciliation"] == "requested"
            assert len(
                _humidifier_calls(
                    primary_hass,
                    entity_id="switch.shared",
                    service="turn_on",
                )
            ) == 1
        finally:
            await primary_engine.async_stop()
            await other_engine.async_stop()

    asyncio.run(run())


def test_sanitized_support_truth_drops_entity_ids_and_preserves_categories():
    services_mod = _load_services_module()
    value = {
        "schema": 1,
        "summary": {
            "requested_lanes": 1,
            "degraded_lanes": 0,
            "unknown_lanes": 0,
            "faulted_outputs": 1,
            "degraded_outputs": 0,
            "unknown_outputs": 0,
            "manual_hold_outputs": 1,
        },
        "outputs": {
            "output_1": {
                "domain": "humidifier",
                "owners": ["level1"],
                "configured_owners": ["level1"],
                "desired": "on",
                "observed": "off",
                "reconciliation": "fault_latched",
                "failure_category": "retry_exhausted",
                "fault_latched": True,
            },
            "humidifier.private_bedroom": {
                "desired": "on",
                "observed": "off",
            },
        },
    }

    sanitized = services_mod._support_humidifier_reconciliation_summary(value)

    assert sanitized["summary"]["requested_lanes"] == 1
    assert sanitized["summary"]["manual_hold_outputs"] == 1
    assert sanitized["outputs"]["output_1"]["reconciliation"] == "fault_latched"
    assert "private_bedroom" not in str(sanitized)
    assert "physical moisture production" in sanitized["truth_boundary"]


def test_release_check_warns_on_degraded_humidifier_truth_without_physical_claim():
    services_mod = _load_services_module()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    runtime_data = {
        "cards": {},
        "entity_map": {},
        "humidifier_reconciliation": {
            "schema": 1,
            "summary": {
                "requested_lanes": 1,
                "degraded_lanes": 0,
                "unknown_lanes": 0,
                "matched_outputs": 0,
                "retrying_outputs": 0,
                "faulted_outputs": 0,
                "degraded_outputs": 1,
                "unknown_outputs": 0,
                "isolated_outputs": 0,
                "ownership_conflicts": 0,
            },
            "outputs": {
                "output_1": {
                    "domain": "switch",
                    "owners": ["level1"],
                    "configured_owners": ["level1"],
                    "desired": "on",
                    "observed": "off",
                    "reconciliation": "degraded",
                    "failure_category": "service_unavailable",
                }
            },
        },
    }

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.10-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    check = {
        item["id"]: item
        for item in report["checks"]
    }["humidifier_reconciliation_truth"]

    assert check["status"] == "warn"
    assert "Home Assistant evidence only" in check["message"]
    assert "entity_id" not in str(check["details"])


def test_release_check_warns_when_enabled_humidifier_truth_is_not_available():
    services_mod = _load_services_module()
    entry = _entry_with_humidifiers(
        {
            "level1": {
                "enabled": True,
                "outputs": ["switch.level1"],
                "band_adjust": 0,
            }
        }
    )
    hass = _FakeHass(entry, _states())

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {"cards": {}, "entity_map": {}},
        manifest_version="2.0.10-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    check = {
        item["id"]: item
        for item in report["checks"]
    }["humidifier_reconciliation_truth"]

    assert check["status"] == "warn"
    assert check["details"]["status"] == "not_available"
    assert "not available yet" in check["message"]


def test_release_check_reports_manual_runtime_control_as_backend_truth():
    services_mod = _load_services_module()
    entry = _entry_with_humidifiers({})
    hass = _FakeHass(entry, _states())
    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "cards": {},
            "entity_map": {},
            "runtime_mode": "manual_override",
            "runtime_mode_display": "MANUAL OVERRIDE",
            "runtime_reason": "Manual override is enabled.",
        },
        manifest_version="2.0.12-beta.3",
        frontend_dependencies={"status": "not_inspectable"},
    )
    check = {
        item["id"]: item
        for item in report["checks"]
    }["runtime_control_truth"]

    assert check["status"] == "pass"
    assert check["details"] == {
        "mode": "manual_override",
        "display": "MANUAL OVERRIDE",
        "reason_available": True,
    }


def test_v2_templates_and_gallery_use_backend_humidifier_and_reason_truth():
    paths = (
        INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
        INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
        ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
        ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    )
    for path in paths:
        source = path.read_text()
        assert "attributes?.humidifier_status" in source
        assert "${label} Humidifier · ${text}" in source
        assert "Humidifier ${label} · ${text}" not in source
        assert "output_on: 'On'" in source
        assert "output_on: 'Output on'" not in source
        assert "output_on: '#22d3ee'" in source
        assert "requested: '#22d3ee'" in source
        assert "const splitHumidifierRow" not in source
        assert "out.push(...humidifierOut);" in source
        assert "return scrollRow(out, 'Current Air Control status');" in source
        assert ".cv-chip-stack{" not in source
        assert "Humidifier assist running" not in source
        assert "reasonState?.attributes?.display_reason" in source
        assert "displayReason.schema !== 'hi.reason.v1'" in source
        assert "displayReason.lines.map((line) => escapeHtml(line.text))" in source
        assert "output confirmation pending" not in source
        assert "Home Assistant reports the configured output on" not in source


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
    print(f"{len(tests)} humidifier reconciliation checks passed.")
