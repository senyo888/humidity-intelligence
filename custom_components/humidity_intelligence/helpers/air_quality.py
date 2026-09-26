"""Pure configured air-quality threshold evaluation helpers."""

from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Optional


AQ_TRIGGER_SPECS = {
    "iaq_bad": {"sensor_type": "iaq", "direction": "low"},
    "pm25_high": {"sensor_type": "pm25", "direction": "high"},
    "voc_bad": {"sensor_type": "voc", "direction": "high"},
    "co2_high": {"sensor_type": "co2", "direction": "high"},
    "co_warning": {"sensor_type": "co", "direction": "high"},
}
AQ_EXPECTED_UNITS = {
    "iaq": {"", "iaq", "index"},
    "pm25": {"ug/m3"},
    "voc": {"ppb"},
    "co2": {"ppm"},
    "co": {"ppm"},
}


def evaluate_configured_aq_triggers(
    config: dict[str, Any],
    value_for_sensor_type: Callable[[str], Optional[float]],
) -> list[dict[str, Any]]:
    """Evaluate configured trigger thresholds without changing runtime state."""
    thresholds = config.get("thresholds")
    thresholds = thresholds if isinstance(thresholds, dict) else {}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_trigger in config.get("triggers", []) or []:
        trigger = str(raw_trigger)
        if trigger in seen or trigger not in AQ_TRIGGER_SPECS:
            continue
        seen.add(trigger)
        spec = AQ_TRIGGER_SPECS[trigger]
        threshold = _finite_float(thresholds.get(trigger))
        value = value_for_sensor_type(str(spec["sensor_type"]))
        value = _finite_float(value)
        crossed: Optional[bool] = None
        if threshold is not None and value is not None:
            crossed = (
                value <= threshold
                if spec["direction"] == "low"
                else value >= threshold
            )
        results.append(
            {
                "trigger": trigger,
                "sensor_type": spec["sensor_type"],
                "direction": spec["direction"],
                "threshold": threshold,
                "value": value,
                "crossed": crossed,
                "status": "available"
                if crossed is not None
                else "invalid_threshold"
                if threshold is None
                else "unavailable",
            }
        )
    return results


def format_aq_trigger_detail(evaluation: dict[str, Any]) -> Optional[str]:
    """Render the established engine wording for one crossed AQ trigger."""
    if evaluation.get("crossed") is not True:
        return None
    value = float(evaluation["value"])
    threshold = float(evaluation["threshold"])
    label = {
        "iaq_bad": "IAQ",
        "pm25_high": "PM2.5",
        "voc_bad": "VOC",
        "co2_high": "CO2",
        "co_warning": "CO",
    }.get(str(evaluation.get("trigger")))
    if label is None:
        return None
    operator = "<=" if evaluation.get("direction") == "low" else ">="
    return f"{label} {value:.1f} {operator} threshold {threshold:g}"


def capture_configured_aq_evidence(
    hass: Any,
    config: dict[str, Any],
    *,
    stability_selection: bool = False,
) -> dict[str, Any]:
    """Capture bounded unit-validated AQ evidence for Stability truth."""
    telemetry_by_level_type: dict[tuple[str, str], list[str]] = {}
    seen_entities: set[str] = set()
    telemetry_source_count = 0
    supported_types = {
        str(spec["sensor_type"])
        for spec in AQ_TRIGGER_SPECS.values()
    }
    for item in config.get("telemetry", []) or []:
        if not isinstance(item, dict):
            continue
        sensor_type = str(item.get("sensor_type") or "")
        if sensor_type not in supported_types:
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if not entity_id or entity_id in seen_entities:
            continue
        seen_entities.add(entity_id)
        telemetry_source_count += 1
        level = str(item.get("level") or "").strip()
        telemetry_by_level_type.setdefault((level, sensor_type), []).append(entity_id)

    configured_trigger_count = 0
    evaluated_trigger_count = 0
    bad_trigger_count = 0
    expected_source_count = 0
    available_source_count = 0
    unit_invalid_source_count = 0
    invalid_threshold_count = 0
    bad_trigger_codes: list[str] = []
    level_clearances: list[float] = []
    selection_levels: list[dict[str, Any]] = []
    co_warning_active = False
    co_evidence_complete = True
    aq_config = config.get("aq")
    aq_config = aq_config if isinstance(aq_config, dict) else {}
    for raw_level in sorted(aq_config, key=str):
        level = str(raw_level)
        level_config = aq_config.get(raw_level)
        if not isinstance(level_config, dict) or not level_config.get("enabled"):
            continue
        evidence_by_type: dict[str, Optional[float]] = {}

        def _value_for_type(sensor_type: str) -> Optional[float]:
            nonlocal expected_source_count
            nonlocal available_source_count
            nonlocal unit_invalid_source_count
            if sensor_type in evidence_by_type:
                return evidence_by_type[sensor_type]
            entity_ids = telemetry_by_level_type.get((level, sensor_type), [])
            expected_source_count += len(entity_ids)
            values: list[float] = []
            invalid_units = 0
            for entity_id in entity_ids:
                state = (
                    getattr(hass, "states", None).get(entity_id)
                    if getattr(hass, "states", None)
                    else None
                )
                if state is None:
                    continue
                attributes = getattr(state, "attributes", {})
                unit = (
                    attributes.get("unit_of_measurement")
                    if isinstance(attributes, dict)
                    else None
                )
                if not aq_unit_supported(sensor_type, unit):
                    invalid_units += 1
                    continue
                value = _finite_float(getattr(state, "state", None))
                if value is not None:
                    values.append(value)
            available_source_count += len(values)
            unit_invalid_source_count += invalid_units
            evidence_by_type[sensor_type] = (
                sum(values) / len(values) if values else None
            )
            return evidence_by_type[sensor_type]

        selected_config = level_config
        selected_triggers = []
        if stability_selection:
            configured = list(dict.fromkeys(str(item) for item in level_config.get("triggers", []) or []))
            raw = [item for item in configured if item in {"pm25_high", "voc_bad", "co2_high"}]
            selected_triggers = raw or (["iaq_bad"] if "iaq_bad" in configured else [])
            selected_config = {**level_config, "triggers": selected_triggers}
            # CO evidence remains independent of the routine AQ score selection.
            before_co = (expected_source_count, available_source_count, unit_invalid_source_count)
            if "co_warning" in configured:
                co = evaluate_configured_aq_triggers({**level_config, "triggers": ["co_warning"]}, _value_for_type)[0]
                co_warning_active = co_warning_active or co["crossed"] is True
                co_evidence_complete = co_evidence_complete and co["status"] == "available" and expected_source_count > before_co[0] and available_source_count - before_co[1] == expected_source_count - before_co[0]
            expected_source_count, available_source_count, unit_invalid_source_count = before_co
        before_sources = (expected_source_count, available_source_count)
        evaluations = evaluate_configured_aq_triggers(selected_config, _value_for_type)
        if stability_selection:
            expected = expected_source_count - before_sources[0]
            available = available_source_count - before_sources[1]
            selection_levels.append({
                "level": level,
                "basis": "raw" if raw else "iaq_fallback" if selected_triggers else "unconfigured",
                "selected_triggers": selected_triggers,
                "excluded_iaq": bool(raw and "iaq_bad" in configured),
                "complete": bool(evaluations) and all(item["status"] == "available" for item in evaluations) and expected > 0 and available == expected,
            })
        configured_trigger_count += len(evaluations)
        level_values: list[float] = []
        for evaluation in evaluations:
            status = str(evaluation.get("status"))
            if status == "invalid_threshold":
                invalid_threshold_count += 1
                continue
            if status != "available":
                continue
            evaluated_trigger_count += 1
            crossed = evaluation.get("crossed") is True
            level_values.append(0.0 if crossed else 1.0)
            if crossed:
                bad_trigger_count += 1
                trigger = str(evaluation.get("trigger"))
                if trigger not in bad_trigger_codes:
                    bad_trigger_codes.append(trigger)
        if level_values:
            level_clearances.append(sum(level_values) / len(level_values))

    result = {
        "clearance": sum(level_clearances) / len(level_clearances)
        if level_clearances
        else None,
        "configured_trigger_count": configured_trigger_count,
        "evaluated_trigger_count": evaluated_trigger_count,
        "bad_trigger_count": bad_trigger_count,
        "telemetry_source_count": telemetry_source_count,
        "expected_source_count": expected_source_count,
        "available_source_count": available_source_count,
        "unit_invalid_source_count": unit_invalid_source_count,
        "invalid_threshold_count": invalid_threshold_count,
        "bad_trigger_codes": bad_trigger_codes[:10],
    }
    if stability_selection:
        result.update({
            "selection": {"policy": "raw_first_per_level_v1", "levels": selection_levels},
            "complete": configured_trigger_count > 0 and all(item["complete"] for item in selection_levels if item["selected_triggers"]),
            "co_warning_active": co_warning_active,
            "co_evidence_complete": co_evidence_complete,
        })
    return result


def aq_unit_supported(sensor_type: str, unit: Any) -> bool:
    """Return whether a source unit matches the configured AQ threshold scale."""
    normalized = str(unit or "").strip().lower().replace(" ", "")
    normalized = normalized.replace("³", "3")
    normalized = normalized.replace("μ", "u").replace("µ", "u")
    normalized = normalized.replace("ug/m^3", "ug/m3")
    return normalized in AQ_EXPECTED_UNITS.get(sensor_type, set())


def _finite_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
