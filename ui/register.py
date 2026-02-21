"""UI registration helpers for Humidity Intelligence.

This module provides functions to register prebuilt dashboard cards with
Home Assistant.  It uses Lovelace APIs to create or suggest cards.
The functions defined here are placeholders; the real implementation
will need to interact with the frontend when the API becomes stable.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


from pathlib import Path


async def async_build_entity_mapping(hass: HomeAssistant, entry_id: str) -> Dict[str, str]:
    """Build mapping from v1 placeholder entity IDs to v2 entity IDs."""
    registry = er.async_get(hass)
    mapping: Dict[str, str] = {}

    entry = hass.config_entries.async_get_entry(entry_id)
    telemetry = _entry_section(entry, "telemetry", []) if entry else []
    zones = _entry_section(entry, "zones", {}) if entry else {}
    humidifiers = _entry_section(entry, "humidifiers", {}) if entry else {}
    alerts = _entry_section(entry, "alerts", []) if entry else []

    def _find_telemetry(room_hint: str, sensor_type: str, level: str | None = None) -> str | None:
        room_hint = room_hint.lower()
        for item in telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            if level and item.get("level") != level:
                continue
            room = (item.get("room") or "").lower()
            if room_hint in room:
                return item.get("entity_id")
        return None

    def _first_telemetry(sensor_type: str, level: str | None = None) -> str | None:
        for item in telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            if level and item.get("level") != level:
                continue
            entity_id = item.get("entity_id")
            if entity_id:
                return entity_id
        return None

    def _entity_id(domain: str, unique_suffix: str) -> str | None:
        unique_id = f"hi_{entry_id}_{unique_suffix}"
        return registry.async_get_entity_id(domain, DOMAIN, unique_id)

    def _pick(values: list[str], idx: int = 0) -> str | None:
        if len(values) > idx:
            return values[idx]
        if values:
            return values[0]
        return None

    def _zone_outputs(level: str) -> list[str]:
        out: list[str] = []
        for zone in (zones or {}).values():
            if not isinstance(zone, dict):
                continue
            if zone.get("level") != level:
                continue
            for entity_id in zone.get("outputs", []) or []:
                if isinstance(entity_id, str) and entity_id not in out:
                    out.append(entity_id)
        return out

    def _humidifier_output(level: str) -> str | None:
        cfg = (humidifiers or {}).get(level, {})
        outputs = cfg.get("outputs", []) if isinstance(cfg, dict) else []
        return _pick([e for e in outputs if isinstance(e, str)], 0)

    def _alert_lights() -> list[str]:
        out: list[str] = []
        for alert in alerts or []:
            if not isinstance(alert, dict):
                continue
            lights = alert.get("lights", []) or []
            for light in lights:
                if isinstance(light, str) and light not in out:
                    out.append(light)
        return out

    def _alert_light_at(index: int) -> str | None:
        lights = _alert_lights()
        if len(lights) > index:
            return lights[index]
        return None

    def _bool_entity_id(key: str) -> str:
        unique_id = f"hi_{entry_id}_input_{key}"
        return registry.async_get_entity_id("switch", DOMAIN, unique_id) or f"switch.hi_{key}"

    def _alert_active_entity(index: int) -> str | None:
        if index >= len(alerts or []):
            return None
        key = f"air_alert_{index + 1}_active"
        unique_id = f"hi_{entry_id}_input_{key}"
        found = registry.async_get_entity_id("switch", DOMAIN, unique_id)
        if found:
            return found
        return f"switch.hi_{key}"

    def _timer_entity_id(key: str) -> str:
        unique_id = f"hi_{entry_id}_timer_{key}"
        return registry.async_get_entity_id("sensor", DOMAIN, unique_id) or f"sensor.hi_{key}"

    placeholders = {
        "sensor.house_average_humidity": _entity_id("sensor", "house_avg_humidity"),
        "sensor.house_average_temperature": _entity_id("sensor", "house_avg_temperature"),
        "sensor.house_humidity_target_low": _entity_id("sensor", "house_target_low"),
        "sensor.house_humidity_target_high": _entity_id("sensor", "house_target_high"),
        "sensor.house_humidity_drift_7d": _entity_id("sensor", "house_drift_7d"),
        "sensor.worst_room_condensation": _entity_id("sensor", "worst_condensation"),
        "sensor.worst_room_condensation_risk": _entity_id("sensor", "worst_condensation_risk"),
        "sensor.worst_room_mould": _entity_id("sensor", "worst_mould"),
        "sensor.worst_room_mould_risk": _entity_id("sensor", "worst_mould_risk"),
        "sensor.air_control_downstairs_average_humidity": _entity_id("sensor", "level1_avg_humidity"),
        "sensor.air_control_upstairs_average_humidity": _entity_id("sensor", "level2_avg_humidity"),
        "sensor.air_control_house_iaq_average": _entity_id("sensor", "house_iaq_average"),
        "sensor.air_control_downstairs_iaq_average": _entity_id("sensor", "level1_iaq_average"),
        "sensor.air_control_upstairs_iaq_average": _entity_id("sensor", "level2_iaq_average"),
        "sensor.air_control_house_pm25_average": _entity_id("sensor", "house_pm25_average"),
        "sensor.air_control_downstairs_pm25_average": _entity_id("sensor", "level1_pm25_average"),
        "sensor.air_control_upstairs_pm25_average": _entity_id("sensor", "level2_pm25_average"),
        "sensor.air_control_house_voc_average": _entity_id("sensor", "house_voc_average"),
        "sensor.air_control_downstairs_voc_average": _entity_id("sensor", "level1_voc_average"),
        "sensor.air_control_upstairs_voc_average": _entity_id("sensor", "level2_voc_average"),
        "sensor.air_control_house_co_average": _entity_id("sensor", "house_co_average"),
        "sensor.air_control_downstairs_co_average": _entity_id("sensor", "level1_co_average"),
        "sensor.air_control_upstairs_co_average": _entity_id("sensor", "level2_co_average"),
        "sensor.air_control_mode": _entity_id("sensor", "air_control_mode"),
        "sensor.air_control_reason": _entity_id("sensor", "air_control_reason"),
        "sensor.air_control_kitchen_humidity_delta": _entity_id("sensor", "air_control_kitchen_humidity_delta"),
        "sensor.air_control_bathroom_humidity_delta": _entity_id("sensor", "air_control_bathroom_humidity_delta"),
        "sensor.air_control_kitchen_slope_delta": _entity_id("sensor", "air_control_kitchen_slope_delta"),
        "sensor.condensation_danger": _entity_id("binary_sensor", "condensation_danger"),
        "sensor.mould_danger": _entity_id("binary_sensor", "mould_danger"),
        "sensor.humidity_danger": _entity_id("binary_sensor", "humidity_danger"),
        "binary_sensor.condensation_danger": _entity_id("binary_sensor", "condensation_danger"),
        "binary_sensor.humidity_danger": _entity_id("binary_sensor", "humidity_danger"),
        "binary_sensor.mould_danger": _entity_id("binary_sensor", "mould_danger"),
        "input_boolean.air_aq_downstairs_active": _bool_entity_id("air_aq_downstairs_active"),
        "input_boolean.air_aq_upstairs_active": _bool_entity_id("air_aq_upstairs_active"),
        "input_boolean.air_alert_1_active": _alert_active_entity(0),
        "input_boolean.air_alert_2_active": _alert_active_entity(1),
        "input_boolean.air_alert_3_active": _alert_active_entity(2),
        "input_boolean.air_alert_4_active": _alert_active_entity(3),
        "input_boolean.air_alert_5_active": _alert_active_entity(4),
        "input_boolean.air_co_emergency_active": _bool_entity_id("air_co_emergency_active"),
        "input_boolean.air_control_enabled": _bool_entity_id("air_control_enabled"),
        "input_boolean.air_control_manual_override": _bool_entity_id("air_control_manual_override"),
        "input_boolean.air_control_output_expanded": _bool_entity_id("air_control_output_expanded"),
        "input_boolean.air_isolate_fan_outputs": _bool_entity_id("air_isolate_fan_outputs"),
        "input_boolean.air_isolate_humidifier_outputs": _bool_entity_id("air_isolate_humidifier_outputs"),
        "input_boolean.air_downstairs_humidifier_active": _bool_entity_id("air_downstairs_humidifier_active"),
        "input_boolean.air_upstairs_humidifier_active": _bool_entity_id("air_upstairs_humidifier_active"),
        "input_boolean.humidity_constellation_expanded": _bool_entity_id("humidity_constellation_expanded"),
        "input_boolean.toggle": _bool_entity_id("toggle"),
        "timer.air_aq_upstairs_run": _timer_entity_id("air_aq_upstairs_run"),
        "timer.air_aq_downstairs_run": _timer_entity_id("air_aq_downstairs_run"),
        "timer.air_bathroom_min_run": _timer_entity_id("air_bathroom_min_run"),
        "timer.air_cooking_min_run": _timer_entity_id("air_cooking_min_run"),
        "timer.air_control_pause": _timer_entity_id("air_control_pause"),
        "fan.kitchen_air": _pick(_zone_outputs("level1"), 0),
        "fan.living_room_air": _pick(_zone_outputs("level1"), 1),
        "fan.upstairs_air": _pick(_zone_outputs("level2"), 0),
        "humidifier.downstairs_humidifier": _humidifier_output("level1"),
        "humidifier.upstairs_humidifier": _humidifier_output("level2"),
        "light.bathroom": _alert_light_at(0),
        "light.alert_1": _alert_light_at(0),
        "light.alert_2": _alert_light_at(1),
        "light.alert_3": _alert_light_at(2),
        "light.alert_4": _alert_light_at(3),
        "light.alert_5": _alert_light_at(4),
    }

    # Room-based sensor placeholders
    fallback_house_humidity = _entity_id("sensor", "house_avg_humidity")
    fallback_humidity_any = _first_telemetry("humidity")
    fallback_humidity_l1 = _first_telemetry("humidity", "level1") or fallback_humidity_any
    fallback_humidity_l2 = _first_telemetry("humidity", "level2") or fallback_humidity_any
    room_placeholders = {
        "sensor.kitchen_humidity": (
            _find_telemetry("kitchen", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.living_room_humidity": (
            _find_telemetry("living", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.hallway_humidity": (
            _find_telemetry("hallway", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.bathroom_humidity": (
            _find_telemetry("bathroom", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.toilet_humidity": (
            _find_telemetry("toilet", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.bedroom_humidity": (
            _find_telemetry("bedroom", "humidity")
            or fallback_humidity_l2
            or fallback_house_humidity
        ),
        "sensor.kids_room_humidity": (
            _find_telemetry("kid", "humidity")
            or _find_telemetry("willow", "humidity")
            or fallback_humidity_l2
            or fallback_house_humidity
        ),
        "sensor.wirelesstag_kitchen_humidity": (
            _find_telemetry("kitchen", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
        "sensor.wirelesstag_bathroom_humidity": (
            _find_telemetry("bathroom", "humidity")
            or fallback_humidity_l1
            or fallback_house_humidity
        ),
    }
    placeholders.update(room_placeholders)

    # AQ monitor placeholders
    aq_placeholders = {
        # Common monitor entity ids with and without the trailing "_2"
        "sensor.bedroom_air_quality_monitor_indoor_air_quality": _find_telemetry("bedroom", "iaq") or _find_telemetry("", "iaq", "level2"),
        "sensor.bedroom_air_quality_monitor_particulate_matter": _find_telemetry("bedroom", "pm25") or _find_telemetry("", "pm25", "level2"),
        "sensor.bedroom_air_quality_monitor_volatile_organic_compounds": _find_telemetry("bedroom", "voc") or _find_telemetry("", "voc", "level2"),
        "sensor.bedroom_air_quality_monitor_carbon_monoxide": _find_telemetry("bedroom", "co") or _find_telemetry("", "co", "level2"),
        "sensor.bedroom_air_quality_monitor_indoor_air_quality_2": _find_telemetry("bedroom", "iaq") or _find_telemetry("", "iaq", "level2"),
        "sensor.bedroom_air_quality_monitor_particulate_matter_2": _find_telemetry("bedroom", "pm25") or _find_telemetry("", "pm25", "level2"),
        "sensor.bedroom_air_quality_monitor_volatile_organic_compounds_2": _find_telemetry("bedroom", "voc") or _find_telemetry("", "voc", "level2"),
        "sensor.bedroom_air_quality_monitor_carbon_monoxide_2": _find_telemetry("bedroom", "co") or _find_telemetry("", "co", "level2"),
        "sensor.downstairs_air_quality_monitor_indoor_air_quality": _find_telemetry("hallway", "iaq") or _find_telemetry("", "iaq", "level1"),
        "sensor.downstairs_air_quality_monitor_particulate_matter": _find_telemetry("hallway", "pm25") or _find_telemetry("", "pm25", "level1"),
        "sensor.downstairs_air_quality_monitor_volatile_organic_compounds": _find_telemetry("hallway", "voc") or _find_telemetry("", "voc", "level1"),
        "sensor.downstairs_air_quality_monitor_carbon_monoxide": _find_telemetry("hallway", "co") or _find_telemetry("", "co", "level1"),
        "sensor.downstairs_air_quality_monitor_indoor_air_quality_2": _find_telemetry("hallway", "iaq") or _find_telemetry("", "iaq", "level1"),
        "sensor.downstairs_air_quality_monitor_particulate_matter_2": _find_telemetry("hallway", "pm25") or _find_telemetry("", "pm25", "level1"),
        "sensor.downstairs_air_quality_monitor_volatile_organic_compounds_2": _find_telemetry("hallway", "voc") or _find_telemetry("", "voc", "level1"),
        "sensor.downstairs_air_quality_monitor_carbon_monoxide_2": _find_telemetry("hallway", "co") or _find_telemetry("", "co", "level1"),
    }
    placeholders.update(aq_placeholders)

    unresolved: List[str] = []
    for placeholder, entity_id in placeholders.items():
        if entity_id:
            mapping[placeholder] = entity_id
        else:
            unresolved.append(placeholder)

    hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {})
    hass.data[DOMAIN][entry_id]["unresolved_placeholders"] = sorted(unresolved)

    return mapping

async def async_register_cards(hass: HomeAssistant, entry_id: str, mapping: Dict[str, str]) -> Dict[str, str]:
    """Prepare dashboard YAML snippets for the given config entry.

    This helper loads the canonical V2 mobile and tablet YAML templates from
    the integration's UI directory and substitutes placeholder entity IDs with
    the actual entity IDs generated for a particular config entry.  It returns
    a dictionary containing the substituted YAML strings.  The caller is
    responsible for presenting these to the user or creating Lovelace cards.

    :param hass: Home Assistant instance
    :param entry_id: The ID of the config entry
    :param mapping: Placeholder to actual entity_id mapping for substitution
    :return: A mapping of card names to YAML strings
    """
    base_path = Path(__file__).parents[1] / "ui" / "cards"
    card_files = {
        "v2_mobile": base_path / "v2_mobile.yaml",
        "v2_tablet": base_path / "v2_tablet.yaml",
        "v1_mobile": base_path / "v1_mobile.yaml",
        "view_cards_button": base_path / "view_cards_button.yaml",
    }
    cards: Dict[str, str] = {}
    unresolved = list(
        (hass.data.get(DOMAIN, {}).get(entry_id, {}) or {}).get("unresolved_placeholders", [])
    )
    unresolved_by_card: Dict[str, List[str]] = {}
    for name, path in card_files.items():
        try:
            content = await hass.async_add_executor_job(path.read_text, "utf-8")
        except Exception as exc:
            _LOGGER.error("Unable to read template %s: %s", path, exc)
            continue
        # Replace placeholders safely (avoid partial matches like binary_sensor.*)
        for placeholder, entity_id in mapping.items():
            if not entity_id:
                continue
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(placeholder)}(?![A-Za-z0-9_])"
            content = re.sub(pattern, entity_id, content)

        content = _prune_unresolved_entity_items(content, unresolved)

        unresolved_in_card: List[str] = []
        for placeholder in unresolved:
            if _is_optional_placeholder(placeholder):
                continue
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(placeholder)}(?![A-Za-z0-9_])"
            if re.search(pattern, content):
                unresolved_in_card.append(placeholder)
        if unresolved_in_card:
            unresolved_by_card[name] = sorted(unresolved_in_card)
            _LOGGER.error(
                "Card %s has unresolved placeholders for entry %s: %s",
                name,
                entry_id,
                ", ".join(sorted(unresolved_in_card)),
            )
            warning = (
                "# HI WARNING: unresolved placeholders detected and kept as-is:\n"
                "# "
                + ", ".join(sorted(unresolved_in_card))
                + "\n"
            )
            content = warning + content
        cards[name] = content

    hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {})
    hass.data[DOMAIN][entry_id]["unresolved_placeholders_by_card"] = unresolved_by_card
    return cards


def _is_optional_placeholder(placeholder: str) -> bool:
    """Placeholders that are expected to be user-provided outputs are optional."""
    return placeholder.startswith(
        (
            "fan.",
            "humidifier.",
            "light.",
            "input_boolean.air_alert_",
        )
    )


def _should_prune_unresolved_entity_line(placeholder: str) -> bool:
    return placeholder.startswith(
        (
            "light.alert_",
            "input_boolean.air_alert_",
        )
    )


def _prune_unresolved_entity_items(content: str, unresolved: List[str]) -> str:
    prune_set = {p for p in unresolved if _should_prune_unresolved_entity_line(p)}
    if not prune_set:
        return content

    lines = content.splitlines()
    out: List[str] = []
    i = 0
    entity_pattern = re.compile(r"^([ \t]*)-[ \t]*entity:[ \t]*([^#\s]+)[ \t]*(?:#.*)?$")

    while i < len(lines):
        line = lines[i]
        match = entity_pattern.match(line)
        if not match:
            out.append(line)
            i += 1
            continue

        entity_id = match.group(2)
        if entity_id not in prune_set:
            out.append(line)
            i += 1
            continue

        # Drop this list item and its child mapping lines.
        base_indent = len(match.group(1))
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                i += 1
                continue
            indent = len(nxt) - len(nxt.lstrip(" \t"))
            if indent <= base_indent:
                break
            i += 1

    result = "\n".join(out)
    if content.endswith("\n"):
        result += "\n"
    return result


def _entry_section(entry: Any, key: str, default: Any) -> Any:
    if entry is None:
        return default
    options = getattr(entry, "options", None) or {}
    if key in options:
        return options.get(key, default)
    data = getattr(entry, "data", None) or {}
    return data.get(key, default)
