"""Native Home Assistant diagnostics for Humidity Intelligence."""

from __future__ import annotations

import json
import os
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALERT_HANDLING_ENABLED,
    CONF_AUTO_REFRESH_UI_ON_STARTUP,
    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
    CONF_SHOW_TEMPERATURE_CHIPS,
    DEFAULT_ALERT_HANDLING_ENABLED,
    DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
    DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS,
    DEFAULT_SHOW_TEMPERATURE_CHIPS,
    DOMAIN,
    SLOPE_MODE_NONE,
)
from .helpers.drift import humidity_drift_dependency_status, humidity_drift_warning
from .helpers.diagnostics_redaction import TO_REDACT, redact_diagnostics_payload
from .helpers.frontend_dependencies import (
    async_frontend_dependency_status,
    frontend_dependency_not_inspectable,
)
from .helpers.level_labels import resolve_level_label_details
from .helpers.local_versions import async_local_version_status, cached_local_version_status
from .helpers.reason_presentation import display_reason_metadata
from .helpers.runtime_control import runtime_control_summary
from .helpers.seasonal import resolve_target_profile, resolve_temperature_comfort_profile
from .helpers.setup_assist import (
    diagnostics_setup_assist_summary,
    diagnostics_setup_assist_warnings,
)
from .helpers.zone_validation import (
    detect_zone_mapping_duplicates,
    summarize_zone_mapping_duplicate_count_warning,
    summarize_zone_mapping_duplicate_counts,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a Humidity Intelligence config entry."""

    runtime_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    effective = _effective_entry_config(entry)
    entity_map = runtime_data.get("entity_map") or {}
    frontend_dependencies = await _safe_frontend_dependency_status(hass)
    local_version_status = await async_local_version_status(hass)
    manifest_version = await _async_read_manifest_version(hass)
    diagnostics_summary = _diagnostics_summary(
        hass,
        effective,
        entity_map,
        runtime_data,
        frontend_dependencies=frontend_dependencies,
        local_version_status=local_version_status,
    )

    payload = {
        "integration": {
            "domain": DOMAIN,
            "integration_version": manifest_version,
            "home_assistant_version": HA_VERSION,
            "diagnostics_schema": 1,
            "native_home_assistant_diagnostics": True,
            "runtime_control_changed_by_diagnostics": False,
        },
        "config_entry": {
            "entry_id_present": bool(getattr(entry, "entry_id", None)),
            "title_present": bool(getattr(entry, "title", None)),
            "data_keys": sorted(str(key) for key in (getattr(entry, "data", {}) or {})),
            "option_keys": sorted(str(key) for key in (getattr(entry, "options", {}) or {})),
        },
        "configuration": {
            "summary": _configuration_summary(effective),
            "options_summary": _options_summary(effective),
            "enabled_feature_areas": _enabled_feature_areas(effective),
            "selected_entity_summary": _selected_entity_summary(effective),
        },
        "runtime": _runtime_summary(
            hass,
            effective,
            runtime_data,
            entity_map,
            diagnostics_summary,
        ),
        "frontend": {
            "dependency_status": frontend_dependencies,
            "status_source": "shared Lovelace resource inspection when available",
            "optional_backend_dependency": False,
        },
        "generated_ui": _generated_ui_summary(effective, runtime_data),
        "diagnostics_summary": diagnostics_summary,
        "privacy": {
            "redaction": "Home Assistant async_redact_data plus HI URL/token/key sanitising.",
            "review_reminder": (
                "The bundle is designed to redact sensitive values, but users should review it before "
                "attaching it to a public GitHub issue."
            ),
        },
    }

    return redact_diagnostics_payload(payload)


async def _safe_frontend_dependency_status(hass: HomeAssistant) -> dict[str, Any]:
    try:
        return await async_frontend_dependency_status(hass)
    except Exception as err:
        return frontend_dependency_not_inspectable(
            f"Frontend dependency status could not be inspected: {err}"
        )


async def _async_read_manifest_version(hass: HomeAssistant) -> str | None:
    def _read_version() -> str | None:
        path = os.path.join(os.path.dirname(__file__), "manifest.json")
        with open(path, "r", encoding="utf-8") as manifest:
            version = json.load(manifest).get("version")
        return str(version) if version is not None else None

    try:
        return await hass.async_add_executor_job(_read_version)
    except Exception:
        return None


def _effective_entry_config(entry: ConfigEntry) -> dict[str, Any]:
    effective = dict(getattr(entry, "data", None) or {})
    effective.update(dict(getattr(entry, "options", None) or {}))
    return effective


def _configuration_summary(config: dict[str, Any]) -> dict[str, Any]:
    telemetry = _list(config.get("telemetry"))
    zones = _dict(config.get("zones"))
    aq = _dict(config.get("aq"))
    humidifiers = _dict(config.get("humidifiers"))
    alerts = _list(config.get("alerts"))
    return {
        "telemetry_count": len(telemetry),
        "zone_count": len([zone for zone in zones.values() if isinstance(zone, dict) and zone.get("enabled")]),
        "aq_lane_count": len([row for row in aq.values() if isinstance(row, dict) and row.get("enabled", True)]),
        "humidifier_lane_count": len(
            [row for row in humidifiers.values() if isinstance(row, dict) and row.get("enabled", True)]
        ),
        "alert_rule_count": len([row for row in alerts if isinstance(row, dict) and row.get("enabled", True)]),
        "alert_only_mode": bool(config.get("alert_only_mode", False)),
    }


def _options_summary(config: dict[str, Any]) -> dict[str, Any]:
    slope = _dict(config.get("slope"))
    return {
        CONF_AUTO_REFRESH_UI_ON_STARTUP: bool(
            config.get(CONF_AUTO_REFRESH_UI_ON_STARTUP, DEFAULT_AUTO_REFRESH_UI_ON_STARTUP)
        ),
        CONF_ALERT_HANDLING_ENABLED: bool(
            config.get(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED)
        ),
        CONF_SHOW_OUTPUT_ENTITY_DETAILS: bool(
            config.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS, DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS)
        ),
        CONF_SHOW_TEMPERATURE_CHIPS: bool(
            config.get(CONF_SHOW_TEMPERATURE_CHIPS, slope.get(CONF_SHOW_TEMPERATURE_CHIPS, DEFAULT_SHOW_TEMPERATURE_CHIPS))
        ),
        "engine_interval_minutes": config.get("engine_interval_minutes"),
        "target_profile": config.get("target_profile", config.get("target_profile_mode", "auto")),
        "temperature_comfort_mode": config.get("temperature_comfort_mode", "auto"),
        "slope_mode": slope.get("mode"),
        "level_labels": resolve_level_label_details(config),
    }


def _enabled_feature_areas(config: dict[str, Any]) -> dict[str, bool]:
    zones = _dict(config.get("zones"))
    aq = _dict(config.get("aq"))
    humidifiers = _dict(config.get("humidifiers"))
    alerts = _list(config.get("alerts"))
    slope = _dict(config.get("slope"))
    alert_only_mode = bool(config.get("alert_only_mode", False))
    return {
        "telemetry": bool(_list(config.get("telemetry"))),
        "zone_control": not alert_only_mode and any(
            isinstance(zone, dict) and zone.get("enabled") for zone in zones.values()
        ),
        "air_quality": not alert_only_mode and any(
            isinstance(row, dict) and row.get("enabled", True) for row in aq.values()
        ),
        "humidifiers": not alert_only_mode and any(
            isinstance(row, dict) and row.get("enabled", True) for row in humidifiers.values()
        ),
        "alert_handling": bool(config.get(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED)),
        "visual_alerts": any(
            isinstance(alert, dict) and (alert.get("lights") or alert.get("power_entity"))
            for alert in alerts
        ),
        "temperature_slope": bool(slope and slope.get("mode") != SLOPE_MODE_NONE),
        "generated_ui": bool(config.get("ui_layouts")),
        "alert_only_mode": alert_only_mode,
    }


def _selected_entity_summary(config: dict[str, Any]) -> dict[str, Any]:
    telemetry = [item for item in _list(config.get("telemetry")) if isinstance(item, dict)]
    alerts = [item for item in _list(config.get("alerts")) if isinstance(item, dict)]
    return {
        "telemetry": {
            "count": len(telemetry),
            "by_sensor_type": _count_by(telemetry, "sensor_type"),
            "by_level": _count_by(telemetry, "level"),
        },
        "presence_gate": {
            "enabled": bool(_dict(config.get("presence_gate")).get("enabled")),
            "entity_count": len(_dict(config.get("presence_gate")).get("entities") or []),
        },
        "zones": _zone_mapping_summary(_dict(config.get("zones"))),
        "air_quality": _lane_output_summary(config.get("aq")),
        "humidifiers": _lane_output_summary(config.get("humidifiers")),
        "alerts": [
            {
                "index": idx,
                "enabled": bool(alert.get("enabled", True)),
                "trigger_type": alert.get("trigger_type"),
                "room_configured": bool(alert.get("room")),
                "visual_light_count": len(alert.get("lights") or []),
                "has_power_entity": bool(alert.get("power_entity")),
            }
            for idx, alert in enumerate(alerts, start=1)
        ],
        "slope": {
            "mode": _dict(config.get("slope")).get("mode"),
            "source_entity_count": len(_dict(config.get("slope")).get("source_entities") or []),
            "provided_sensor_count": len(_dict(config.get("slope")).get("provided_sensors") or []),
        },
    }


def _runtime_summary(
    hass: HomeAssistant,
    config: dict[str, Any],
    runtime_data: dict[str, Any],
    entity_map: dict[str, Any],
    diagnostics_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "current_state": {
            "runtime_mode": runtime_data.get("runtime_mode"),
            "runtime_mode_display": runtime_data.get("runtime_mode_display"),
            "reason_available": bool(runtime_data.get("runtime_reason_full") or runtime_data.get("runtime_reason")),
            "reason_truncated": bool(runtime_data.get("runtime_reason_truncated")),
            "display_reason": display_reason_metadata(
                runtime_data.get("runtime_display_reason")
            ),
        },
        "active_lane": runtime_data.get("runtime_mode"),
        "active_mode": runtime_data.get("runtime_mode_display"),
        "active_alert_resolution": _alert_resolution_summary(runtime_data.get("alert_telemetry", [])),
        "humidifier_reconciliation": _humidifier_reconciliation_summary(runtime_data),
        "gate_states": _gate_states(hass, config, runtime_data),
        "output_states": _output_states(hass, config),
        "mapped_runtime_entities": _mapped_entity_states(hass, entity_map),
        "unavailable_or_unknown_entities": diagnostics_summary.get(
            "unavailable_or_unknown_entities",
            _unavailable_entity_summary([]),
        ),
        "warnings": diagnostics_summary.get("warnings", []),
        "recent_hi_warnings_errors": {
            "status": "not_available",
            "reason": "Home Assistant log history is not exposed through native config-entry diagnostics.",
            "diagnostic_warnings": diagnostics_summary.get("warnings", []),
        },
    }


def _gate_states(
    hass: HomeAssistant,
    config: dict[str, Any],
    runtime_data: dict[str, Any],
) -> dict[str, Any]:
    presence_gate = _dict(config.get("presence_gate"))
    time_gate = _dict(config.get("time_gate"))
    booleans = _dict(runtime_data.get("hi_input_booleans"))
    timers = _dict(runtime_data.get("hi_timers"))
    return {
        "time_gate": {
            "enabled": bool(time_gate.get("enabled")),
            "start": time_gate.get("start"),
            "end": time_gate.get("end"),
            "outside_action": time_gate.get("outside_action"),
        },
        "presence_gate": {
            "enabled": bool(presence_gate.get("enabled")),
            "entity_status": _entity_status_summary(hass, presence_gate.get("entities") or []),
            "present_state_count": len(presence_gate.get("present_states") or []),
            "away_state_count": len(presence_gate.get("away_states") or []),
        },
        "control_switches": {
            key: {
                "entity_present": bool(getattr(entity, "entity_id", None)),
                "is_on": bool(getattr(entity, "is_on", False)),
            }
            for key, entity in booleans.items()
        },
        "pause_timers": {
            key: {
                "entity_present": bool(getattr(timer, "entity_id", None)),
                "state": _timer_state(timer),
            }
            for key, timer in timers.items()
        },
    }


def _output_states(hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
    fan_outputs = set()
    for section_name in ("zones", "aq"):
        for row in _dict(config.get(section_name)).values():
            if isinstance(row, dict):
                fan_outputs.update(row.get("outputs") or [])

    humidifier_outputs = set()
    for row in _dict(config.get("humidifiers")).values():
        if isinstance(row, dict):
            humidifier_outputs.update(row.get("outputs") or [])

    visual_alert_outputs = set()
    for alert in _list(config.get("alerts")):
        if not isinstance(alert, dict):
            continue
        visual_alert_outputs.update(alert.get("lights") or [])
        if alert.get("power_entity"):
            visual_alert_outputs.add(alert["power_entity"])

    return {
        "fan_outputs": _entity_status_summary(hass, sorted(fan_outputs)),
        "humidifier_outputs": _entity_status_summary(hass, sorted(humidifier_outputs)),
        "visual_alert_outputs": _entity_status_summary(hass, sorted(visual_alert_outputs)),
    }


def _mapped_entity_states(hass: HomeAssistant, entity_map: dict[str, Any]) -> dict[str, Any]:
    """Summarize mapped states without exposing mapping keys or entity IDs."""
    entity_ids = [entity_id for entity_id in (entity_map or {}).values() if entity_id]
    return _entity_status_summary(hass, entity_ids)


def _entity_status(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    if state is None:
        return {"configured": True, "status": "missing"}
    return {
        "configured": True,
        "status": _entity_status_bucket(getattr(state, "state", "unknown")),
    }


def _entity_status_bucket(state: Any) -> str:
    state_text = str(state or "").strip().lower()
    if state_text in {"unknown", "unavailable"}:
        return state_text
    if not state_text:
        return "unknown"
    return "available"


def _generated_ui_summary(config: dict[str, Any], runtime_data: dict[str, Any]) -> dict[str, Any]:
    cards = _dict(runtime_data.get("cards"))
    unresolved = runtime_data.get("unresolved_placeholders") or []
    unresolved_by_card = runtime_data.get("unresolved_placeholders_by_card") or {}
    return {
        "configured_layouts": list(config.get("ui_layouts") or []),
        "cached_layouts": sorted(cards.keys()),
        "cached_layout_sizes": {str(name): len(str(card)) for name, card in cards.items()},
        "unresolved_placeholders_count": len(unresolved),
        "unresolved_placeholders_by_card_count": len(unresolved_by_card),
        "show_output_entity_details": bool(
            config.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS, DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS)
        ),
    }


def _diagnostics_summary(
    hass: HomeAssistant,
    config: dict[str, Any],
    entity_map: dict[str, Any],
    runtime_data: dict[str, Any],
    *,
    frontend_dependencies: dict[str, Any],
    local_version_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    telemetry = _list(config.get("telemetry"))
    zones = _dict(config.get("zones"))
    alerts = _list(config.get("alerts"))
    target_profile = resolve_target_profile(config)
    comfort_profile = resolve_temperature_comfort_profile(config)
    duplicates = detect_zone_mapping_duplicates(telemetry, zones)
    duplicate_summary = summarize_zone_mapping_duplicate_count_warning(duplicates)
    unavailable = _unavailable_configured_entities(hass, config, entity_map)
    drift_dependency = humidity_drift_dependency_status(hass)
    drift_dependency_warning = humidity_drift_warning(drift_dependency)
    setup_assist = diagnostics_setup_assist_summary(hass, telemetry)
    warnings = []
    if duplicate_summary:
        warnings.append(duplicate_summary)
    if unavailable:
        warnings.append(f"{len(unavailable)} configured/mapped entity references are missing, unknown, or unavailable.")
    if drift_dependency_warning:
        warnings.append(drift_dependency_warning)
    warnings.extend(diagnostics_setup_assist_warnings(setup_assist))
    pm25_normalization = _pm25_normalization_status(runtime_data)
    if pm25_normalization.get("blocked_count"):
        warnings.append("PM25 aggregate entity ID normalization is blocked by an existing target entity.")
    if not telemetry:
        warnings.append("No telemetry sensors are configured.")
    if not zones and not config.get("alert_only_mode"):
        warnings.append("No control zones are configured.")
    humidifier_reconciliation = _humidifier_reconciliation_summary(runtime_data)
    humidifier_summary = _dict(humidifier_reconciliation.get("summary"))
    humidifier_truth_missing = (
        _configuration_summary(config).get("humidifier_lane_count", 0) > 0
        and humidifier_reconciliation.get("status") != "reported"
    )
    if humidifier_truth_missing:
        warnings.append(
            "Humidifier lanes are enabled, but runtime demand/output reconciliation truth is not available yet."
        )
    if humidifier_summary.get("faulted_outputs"):
        warnings.append("One or more humidifier outputs have a latched reconciliation fault.")
    if humidifier_summary.get("degraded_outputs") or humidifier_summary.get("unknown_outputs"):
        warnings.append("One or more humidifier outputs have degraded or unknown reconciliation truth.")
    if humidifier_summary.get("degraded_lanes") or humidifier_summary.get("unknown_lanes"):
        warnings.append("One or more humidifier lanes have degraded or unknown demand truth.")
    if humidifier_summary.get("ownership_conflicts"):
        warnings.append("One or more humidifier outputs have a conflicting configured output owner.")

    return {
        "runtime_control": runtime_control_summary(runtime_data),
        "target_profile": {
            "mode": config.get("target_profile", config.get("target_profile_mode", "auto")),
            "active_profile": target_profile.key,
            "active_season": target_profile.label,
            "target_low": target_profile.low,
            "target_high": target_profile.high,
            "high_risk": target_profile.high_risk,
            "custom_target_low": config.get("custom_target_low"),
            "custom_target_high": config.get("custom_target_high"),
        },
        "temperature_comfort": {
            "mode": config.get("temperature_comfort_mode", "auto"),
            "active_profile": comfort_profile.key,
            "active_label": comfort_profile.label,
            "target_low": comfort_profile.low,
            "target_high": comfort_profile.high,
            "warm_high": comfort_profile.warm_high,
            "watch_high": comfort_profile.warm_high,
            "custom_low": config.get("temperature_comfort_custom_low"),
            "custom_high": config.get("temperature_comfort_custom_high"),
        },
        "level_labels": resolve_level_label_details(config),
        "zone_mappings": _zone_mapping_summary(zones),
        "zone_mapping_duplicates": summarize_zone_mapping_duplicate_counts(duplicates),
        "alert_mappings": _alert_mapping_summary(alerts),
        "active_alert_resolution": _alert_resolution_summary(runtime_data.get("alert_telemetry", [])),
        "visual_alerts": _visual_alert_summary(alerts),
        "humidity_drift_7d": drift_dependency,
        "setup_assist": setup_assist,
        "pm25_entity_id_normalization": pm25_normalization,
        "humidifier_reconciliation": humidifier_reconciliation,
        "frontend_dependency_resources": frontend_dependencies,
        "local_version_preservation": local_version_status or cached_local_version_status(hass),
        "unavailable_or_unknown_entities": _unavailable_entity_summary(unavailable),
        "warnings": warnings,
    }


def _humidifier_reconciliation_summary(runtime_data: dict[str, Any]) -> dict[str, Any]:
    """Return bounded humidifier truth without configured entity identifiers."""
    raw = _dict(runtime_data.get("humidifier_reconciliation"))
    status = (
        "reported"
        if any(key in raw for key in ("schema", "summary", "outputs"))
        else "not_available"
    )
    raw_summary = _dict(raw.get("summary"))
    summary_keys = (
        "requested_lanes",
        "degraded_lanes",
        "unknown_lanes",
        "matched_outputs",
        "retrying_outputs",
        "faulted_outputs",
        "degraded_outputs",
        "unknown_outputs",
        "isolated_outputs",
        "manual_hold_outputs",
        "ownership_conflicts",
    )
    summary = {
        key: _nonnegative_int(raw_summary.get(key, 0))
        for key in summary_keys
    }
    outputs = {}
    for slot, value in sorted(_dict(raw.get("outputs")).items()):
        if not str(slot).startswith("output_") or not isinstance(value, dict):
            continue
        history = []
        for item in _list(value.get("history"))[-8:]:
            if not isinstance(item, dict):
                continue
            history.append(
                {
                    "event": str(item.get("event") or "unknown"),
                    "desired": str(item.get("desired") or "unknown"),
                    "observed": str(item.get("observed") or "unknown"),
                    "attempts": _nonnegative_int(item.get("attempts", 0)),
                }
            )
        outputs[str(slot)] = {
            "domain": value.get("domain"),
            "owners": [
                str(owner)
                for owner in _list(value.get("owners"))
                if str(owner) in {"level1", "level2"}
            ],
            "configured_owners": [
                str(owner)
                for owner in _list(value.get("configured_owners"))
                if str(owner) in {"level1", "level2"}
            ],
            "desired": value.get("desired"),
            "observed": value.get("observed"),
            "platform_action": value.get("platform_action"),
            "reconciliation": value.get("reconciliation"),
            "dispatch_result": value.get("dispatch_result"),
            "last_command_intent": value.get("last_command_intent"),
            "last_dispatch_utc": value.get("last_dispatch_utc"),
            "attempts": _nonnegative_int(value.get("attempts", 0)),
            "maximum_attempts": _nonnegative_int(value.get("maximum_attempts", 0)),
            "mismatch_age_seconds": (
                _nonnegative_int(value["mismatch_age_seconds"])
                if isinstance(value.get("mismatch_age_seconds"), (int, float))
                else None
            ),
            "failure_category": value.get("failure_category"),
            "fault_latched": bool(value.get("fault_latched")),
            "ownership_conflict": value.get("ownership_conflict"),
            "history": history,
        }
    return {
        "schema": 1,
        "status": status,
        "summary": summary,
        "outputs": outputs,
        "truth_boundary": (
            "Observed output state and optional platform action are Home Assistant evidence only; "
            "they do not prove physical moisture production."
        ),
    }


def _pm25_normalization_status(runtime_data: dict[str, Any]) -> dict[str, Any]:
    details = runtime_data.get("pm25_entity_id_normalization")
    if not isinstance(details, dict):
        return {"status": "not_run", "changed_count": 0, "blocked_count": 0, "blocked_reasons": []}
    changed = details.get("changed") if isinstance(details.get("changed"), dict) else {}
    blocked = details.get("blocked") if isinstance(details.get("blocked"), list) else []
    if blocked:
        status = "blocked"
    elif changed:
        status = "changed"
    else:
        status = "ok"
    return {
        "status": status,
        "changed_count": len(changed),
        "blocked_count": len(blocked),
        "blocked_reasons": sorted(
            {str(item.get("reason")) for item in blocked if isinstance(item, dict) and item.get("reason")}
        ),
    }


def _zone_mapping_summary(zones: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for key, zone in (zones or {}).items():
        if not isinstance(zone, dict):
            continue
        summary[str(key)] = {
            "enabled": bool(zone.get("enabled")),
            "level": zone.get("level"),
            "room_count": len(zone.get("rooms") or []),
            "output_count": len(zone.get("outputs") or []),
            "output_level": zone.get("output_level"),
            "boost_output_level": zone.get("boost_output_level"),
            "trigger_count": len(zone.get("triggers") or []),
            "threshold_count": len(_dict(zone.get("thresholds"))),
        }
    return summary


def _alert_mapping_summary(alerts: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for idx, alert in enumerate(alerts or [], start=1):
        if not isinstance(alert, dict):
            continue
        rows.append(
            {
                "index": idx,
                "enabled": bool(alert.get("enabled", True)),
                "trigger_type": alert.get("trigger_type"),
                "room_configured": bool(alert.get("room")),
                "threshold": alert.get("threshold"),
                "visual_light_count": len(alert.get("lights") or []),
                "has_power_entity": bool(alert.get("power_entity")),
                "flash_mode": alert.get("flash_mode", "red"),
                "duration": alert.get("duration", 10),
            }
        )
    return rows


def _visual_alert_summary(alerts: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for alert in _alert_mapping_summary(alerts):
        if not alert.get("visual_light_count"):
            continue
        rows.append(
            {
                "index": alert["index"],
                "trigger_type": alert["trigger_type"],
                "room_configured": alert["room_configured"],
                "visual_light_count": alert["visual_light_count"],
                "has_power_entity": alert["has_power_entity"],
                "flash_mode": alert["flash_mode"],
                "flash_count": 10,
                "repeat_minutes": 30,
                "restore_state": True,
            }
        )
    return rows


def _unavailable_configured_entities(
    hass: HomeAssistant,
    config: dict[str, Any],
    entity_map: dict[str, Any],
) -> list[dict[str, Any]]:
    entity_ids = set()
    for item in _list(config.get("telemetry")):
        if isinstance(item, dict) and item.get("entity_id"):
            entity_ids.add(str(item["entity_id"]))
    entity_ids.update(str(entity_id) for entity_id in _dict(config.get("presence_gate")).get("entities") or [])
    for section_name in ("zones", "aq", "humidifiers"):
        for row in _dict(config.get(section_name)).values():
            if isinstance(row, dict):
                entity_ids.update(str(entity_id) for entity_id in row.get("outputs") or [])
    for alert in _list(config.get("alerts")):
        if not isinstance(alert, dict):
            continue
        entity_ids.update(str(entity_id) for entity_id in alert.get("lights") or [])
        if alert.get("power_entity"):
            entity_ids.add(str(alert["power_entity"]))
    entity_ids.update(str(entity_id) for entity_id in (entity_map or {}).values() if entity_id)

    unavailable = []
    for entity_id in sorted(entity_ids):
        state = hass.states.get(entity_id)
        if state is None:
            unavailable.append({"entity_id": entity_id, "status": "missing"})
            continue
        if str(getattr(state, "state", "")).lower() in {"unknown", "unavailable"}:
            unavailable.append({"entity_id": entity_id, "status": str(state.state).lower()})
    return unavailable


def _lane_outputs(value: Any) -> dict[str, list[str]]:
    rows = {}
    for key, row in _dict(value).items():
        if isinstance(row, dict):
            rows[str(key)] = list(row.get("outputs") or [])
    return rows


def _lane_output_summary(value: Any) -> dict[str, dict[str, Any]]:
    rows = {}
    for key, row in _dict(value).items():
        if isinstance(row, dict):
            rows[str(key)] = {
                "enabled": bool(row.get("enabled", True)),
                "output_count": len(row.get("outputs") or []),
            }
    return rows


def _entity_status_summary(hass: HomeAssistant, entity_ids: list[Any]) -> dict[str, Any]:
    counts = {"available": 0, "missing": 0, "unknown": 0, "unavailable": 0}
    for entity_id in entity_ids:
        state = hass.states.get(str(entity_id))
        if state is None:
            counts["missing"] += 1
            continue
        state_text = str(getattr(state, "state", "unknown") or "").strip().lower()
        if not state_text:
            state_text = "unknown"
        if state_text in {"unknown", "unavailable"}:
            counts[state_text] += 1
        else:
            counts["available"] += 1
    return {"count": len(entity_ids), "by_status": counts}


def _unavailable_entity_summary(unavailable: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"missing": 0, "unknown": 0, "unavailable": 0}
    for item in unavailable:
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {"count": len(unavailable), "by_status": counts}


def _alert_resolution_summary(value: Any) -> dict[str, Any]:
    rows = [item for item in _list(value) if isinstance(item, dict)]
    return {
        "count": len(rows),
        "degraded_count": len([item for item in rows if item.get("degraded") is True]),
        "trigger_types": sorted(
            {str(item.get("trigger_type")) for item in rows if item.get("trigger_type")}
        ),
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _timer_state(timer: Any) -> Any:
    native_value = getattr(timer, "native_value", None)
    if native_value is not None:
        return native_value
    return getattr(timer, "state", None)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
