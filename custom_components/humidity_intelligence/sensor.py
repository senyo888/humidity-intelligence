"""Sensor platform for Humidity Intelligence."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import partial
from math import ceil
from typing import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .helpers.drift_repairs import async_update_humidity_drift_repair_issue
from .helpers.level_labels import resolve_level_label_details
from .helpers.zone_validation import (
    detect_zone_mapping_duplicates,
    summarize_zone_mapping_duplicate_count_warning,
)
from .services import _build_diagnostics_summary
from .sensors.core import build_entities
from .sensors.slope import build_slope_entities
from homeassistant.helpers.device_registry import DeviceInfo

_LOGGER = logging.getLogger(__name__)


TIMER_KEYS = [
    "air_aq_upstairs_run",
    "air_aq_downstairs_run",
    "air_bathroom_min_run",
    "air_cooking_min_run",
    "air_control_pause",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    alert_only_mode = bool(_entry_section(entry, "alert_only_mode", False))
    sensors, binary_sensors, sources = build_entities(hass, entry)
    slope_sensors, slope_sources, slope_map = build_slope_entities(hass, entry)
    diagnostics = HIDiagnosticsSensor(hass, entry.entry_id)
    timer_sensors = [] if alert_only_mode else [HITimerSensor(entry.entry_id, key) for key in TIMER_KEYS]
    if alert_only_mode:
        _LOGGER.info(
            "HI entry %s sensor platform running in alert-only mode; timer control entities are suppressed.",
            entry.entry_id,
        )
    async_add_entities(sensors + slope_sensors + timer_sensors + [diagnostics], update_before_add=True)
    await async_update_humidity_drift_repair_issue(hass)

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["core_sensors"] = sensors
    hass.data[DOMAIN][entry.entry_id]["core_binary_sensors"] = binary_sensors
    hass.data[DOMAIN][entry.entry_id]["slope_map"] = slope_map
    hass.data[DOMAIN][entry.entry_id]["hi_timers"] = {t._key: t for t in timer_sensors}

    async def _handle_change(event) -> None:
        for sensor in sensors:
            sensor.update_from_hass()
            sensor.async_write_ha_state()
        for sensor in binary_sensors:
            sensor.update_from_hass()
            sensor.async_write_ha_state()
        await async_update_humidity_drift_repair_issue(hass)

    all_sources = list(set(sources + slope_sources))
    unsub = async_track_state_change_event(hass, all_sources, _handle_change)
    hass.data[DOMAIN][entry.entry_id]["core_unsub"] = unsub


class HIDiagnosticsSensor(SensorEntity):
    """Expose configuration and entity mapping diagnostics."""
    _attr_should_poll = True
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._attr_name = "HI Diagnostics"
        self._attr_unique_id = f"hi_{entry_id}_diagnostics"
        self._attr_icon = "mdi:clipboard-text"
        self._attr_native_value = "ok"

    def update(self) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry_id, {})
        config = data.get("config", {})
        options = data.get("options", {}) if isinstance(data.get("options", {}), dict) else {}
        telemetry = config.get("telemetry", []) if isinstance(config, dict) else []
        zones = config.get("zones", {}) if isinstance(config, dict) else {}
        cards = data.get("cards") or {}
        entity_map = data.get("entity_map") or {}
        alert_telemetry = data.get("alert_telemetry") or []
        unresolved = data.get("unresolved_placeholders") or []
        unresolved_by_card = data.get("unresolved_placeholders_by_card") or {}
        duplicates = detect_zone_mapping_duplicates(telemetry, zones if isinstance(zones, dict) else {})
        duplicate_summary = summarize_zone_mapping_duplicate_count_warning(duplicates)
        self._attr_native_value = "warning" if duplicates else "ok"
        summary = _build_diagnostics_summary(
            self.hass,
            config if isinstance(config, dict) else {},
            options,
            entity_map,
            data,
        )
        self._attr_extra_state_attributes = {
            "diagnostics_summary": _sanitize_json(_compact_diagnostics_summary(summary)),
            "config": _sanitize_json(_compact_ui_config(config, options)),
            "slope_map": _sanitize_json(data.get("slope_map") or {}),
            "cards": list(cards.keys()),
            "unresolved_placeholders_count": len(unresolved),
            "unresolved_placeholders": _sanitize_json(unresolved[:20]),
            "unresolved_placeholders_by_card_count": len(unresolved_by_card),
            "zone_mapping_duplicate_summary": duplicate_summary,
            "zone_mapping_duplicate_count": len(duplicates),
            "counts": {
                "telemetry": len(telemetry),
                "mapped_entities": len([v for v in entity_map.values() if v]),
                "card_templates": len(cards.keys()),
                "unresolved_placeholders": len(unresolved),
                "active_alerts": len(alert_telemetry),
            },
            "full_diagnostics": "Use service humidity_intelligence.dump_diagnostics for full config, options, entity map, and state export.",
        }


class HITimerSensor(SensorEntity):
    """Lightweight timer sensor with remaining attribute."""

    def __init__(self, entry_id: str, key: str) -> None:
        self._entry_id = entry_id
        self._key = key
        self._end: datetime | None = None
        self._cancel_scheduled_update: Callable[[], None] | None = None
        self._generation = 0
        self._removed = False
        self._attr_name = f"HI {key.replace('_', ' ').title()}"
        self._attr_unique_id = f"hi_{entry_id}_timer_{key}"
        self._attr_icon = "mdi:timer-outline"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hi")},
            name="Humidity Intelligence",
            manufacturer="Humidity Intelligence",
        )

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def native_value(self) -> str:
        return "active" if self._end and dt_util.utcnow() < self._end else "idle"

    @property
    def extra_state_attributes(self) -> dict:
        return {"remaining": self._remaining_str()}

    def _remaining_str(self) -> str:
        if not self._end:
            return "00:00:00"
        remaining = max(self._end - dt_util.utcnow(), timedelta(0))
        total = ceil(remaining.total_seconds())
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    async def async_start(self, duration: timedelta) -> None:
        self._invalidate_schedule()
        if self._removed:
            return
        now = dt_util.utcnow()
        self._end = now + max(duration, timedelta(0))
        if self._end <= now:
            self._end = None
        self.async_write_ha_state()
        if self._end:
            self._schedule_update(now, self._generation)

    async def async_cancel(self) -> None:
        self._invalidate_schedule()
        self._end = None
        if not self._removed:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._handle_remove()

    def _handle_remove(self) -> None:
        self._removed = True
        self._invalidate_schedule()
        self._end = None

    def _invalidate_schedule(self) -> None:
        self._generation += 1
        if self._cancel_scheduled_update:
            self._cancel_scheduled_update()
            self._cancel_scheduled_update = None

    def _schedule_update(self, now: datetime, generation: int) -> None:
        if self._removed or self._end is None or generation != self._generation:
            return
        next_update = min(self._end, now + timedelta(seconds=60))
        self._cancel_scheduled_update = async_track_point_in_utc_time(
            self.hass,
            partial(self._handle_scheduled_update, generation=generation),
            next_update,
        )

    @callback
    def _handle_scheduled_update(
        self, _scheduled_now: datetime, generation: int
    ) -> None:
        if self._removed or self._end is None or generation != self._generation:
            return
        self._cancel_scheduled_update = None
        now = dt_util.utcnow()
        if now >= self._end:
            self._end = None
            self._generation += 1
            self.async_write_ha_state()
            return
        self.async_write_ha_state()
        self._schedule_update(now, generation)


def _sanitize_json(value):
    if isinstance(value, dict):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    if isinstance(value, set):
        return list(value)
    # mappingproxy or other mapping types
    try:
        if hasattr(value, "keys") and hasattr(value, "__getitem__"):
            return {k: _sanitize_json(value[k]) for k in value.keys()}
    except (KeyError, TypeError, ValueError):
        pass
    return value


def _compact_diagnostics_summary(summary: dict) -> dict:
    """Keep recorder-safe diagnostics attributes under Home Assistant's limit."""
    unavailable = list(summary.get("unavailable_or_unknown_entities") or [])
    active_alerts = [
        _compact_alert_detail(item)
        for item in list(summary.get("active_alert_resolution") or [])[:5]
        if isinstance(item, dict)
    ]
    return {
        "runtime_control": summary.get("runtime_control", {}),
        "target_profile": summary.get("target_profile", {}),
        "temperature_comfort": summary.get("temperature_comfort", {}),
        "level_labels": summary.get("level_labels", {}),
        "zone_mappings": _compact_zone_mappings(summary.get("zone_mappings", {})),
        "alert_mappings": _compact_alert_mappings(summary.get("alert_mappings", [])),
        "visual_alerts": _compact_visual_alerts(summary.get("visual_alerts", [])),
        "active_alert_resolution": active_alerts,
        "humidity_drift_7d": summary.get("humidity_drift_7d", {}),
        "humidifier_reconciliation": _compact_humidifier_reconciliation(
            summary.get("humidifier_reconciliation", {})
        ),
        "pm25_entity_id_normalization": summary.get("pm25_entity_id_normalization", {}),
        "local_version_preservation": summary.get("local_version_preservation", {}),
        "unavailable_or_unknown_entities_count": len(unavailable),
        "unavailable_or_unknown_entities_sample": unavailable[:20],
        "warnings": list(summary.get("warnings") or [])[:10],
    }


def _compact_humidifier_reconciliation(value: dict) -> dict:
    """Keep only recorder-useful aggregate humidifier reconciliation truth."""
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    return {
        "schema": value.get("schema", 1),
        "status": value.get("status", "not_available"),
        "summary": {
            key: summary.get(key, 0)
            for key in (
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
        },
        "truth_boundary": value.get("truth_boundary"),
    }


def _compact_ui_config(config: dict, options: dict) -> dict:
    """Expose only the UI mapping context generated cards need."""
    effective = dict(config or {}) if isinstance(config, dict) else {}
    if isinstance(options, dict):
        effective.update(options)
    telemetry = []
    for item in effective.get("telemetry", []) or []:
        if not isinstance(item, dict):
            continue
        telemetry.append({
            "entity_id": item.get("entity_id"),
            "sensor_type": item.get("sensor_type"),
            "room": item.get("room"),
            "level": item.get("level"),
            "friendly_name": item.get("friendly_name"),
        })

    zones = {}
    for key, zone in (effective.get("zones", {}) or {}).items():
        if not isinstance(zone, dict):
            continue
        zones[key] = {
            "enabled": bool(zone.get("enabled", False)),
            "level": zone.get("level"),
            "rooms": list(zone.get("rooms") or []),
        }

    slope = effective.get("slope", {}) if isinstance(effective.get("slope", {}), dict) else {}
    return {
        "telemetry": telemetry,
        "level_labels": resolve_level_label_details(effective),
        "zones": zones,
        "slope": {
            "mode": slope.get("mode"),
            "source_entities": list(slope.get("source_entities") or []),
            "provided_sensors": list(slope.get("provided_sensors") or []),
            "show_temperature_chips": bool(slope.get("show_temperature_chips")),
        },
    }


def _compact_zone_mappings(zones: dict) -> dict:
    compact = {}
    if not isinstance(zones, dict):
        return compact
    for key, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        compact[key] = {
            "enabled": zone.get("enabled"),
            "level": zone.get("level"),
            "rooms": list(zone.get("rooms") or []),
            "output_count": len(zone.get("outputs") or []),
            "output_level": zone.get("output_level"),
            "boost_output_level": zone.get("boost_output_level"),
            "triggers": list(zone.get("triggers") or []),
            "thresholds": zone.get("thresholds") or {},
        }
    return compact


def _compact_alert_mappings(alerts: list) -> list:
    compact = []
    for alert in list(alerts or [])[:20]:
        if not isinstance(alert, dict):
            continue
        compact.append({
            "index": alert.get("index"),
            "enabled": alert.get("enabled"),
            "trigger_type": alert.get("trigger_type"),
            "room": alert.get("room"),
            "threshold": alert.get("threshold"),
            "visual_light_count": len(alert.get("visual_lights") or []),
            "has_power_entity": bool(alert.get("power_entity")),
            "flash_mode": alert.get("flash_mode"),
            "duration": alert.get("duration"),
        })
    return compact


def _compact_visual_alerts(alerts: list) -> list:
    compact = []
    for alert in list(alerts or [])[:20]:
        if not isinstance(alert, dict):
            continue
        compact.append({
            "index": alert.get("index"),
            "trigger_type": alert.get("trigger_type"),
            "room": alert.get("room"),
            "light_count": len(alert.get("lights") or []),
            "has_power_entity": bool(alert.get("power_entity")),
            "flash_mode": alert.get("flash_mode"),
            "flash_count": alert.get("flash_count"),
            "repeat_minutes": alert.get("repeat_minutes"),
            "restore_state": alert.get("restore_state"),
        })
    return compact


def _compact_alert_detail(detail: dict) -> dict:
    visual = detail.get("visual_alert") if isinstance(detail.get("visual_alert"), dict) else {}
    return {
        "source_summary": detail.get("source_summary"),
        "trigger_type": detail.get("trigger_type"),
        "source": detail.get("source"),
        "sensor": detail.get("sensor"),
        "room": detail.get("room"),
        "zone": detail.get("zone"),
        "measured": detail.get("measured"),
        "threshold": detail.get("threshold"),
        "threshold_source": detail.get("threshold_source"),
        "boost_level": detail.get("boost_level"),
        "output_count": len(detail.get("outputs") or []),
        "visual_configured": bool(visual.get("configured")),
        "visual_light_count": len(visual.get("lights") or []),
        "degraded": bool(detail.get("degraded")),
        "degraded_reasons": list(detail.get("degraded_reasons") or [])[:5],
    }


def _entry_section(entry: ConfigEntry, key: str, default):
    options = getattr(entry, "options", None) or {}
    if key in options:
        return options.get(key, default)
    data = getattr(entry, "data", None) or {}
    return data.get(key, default)
