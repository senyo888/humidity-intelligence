"""Migration helpers for Humidity Intelligence v1 -> v2."""

from __future__ import annotations

from typing import Dict, List

from homeassistant.core import HomeAssistant

V1_PREFIXES = [
    "sensor.house_",
    "sensor.worst_room_",
    "binary_sensor.condensation_",
    "binary_sensor.mould_",
]


def suggest_v2_entity(entity_id: str) -> str:
    """Suggest a v2 entity ID by prefixing with hi_."""
    if entity_id.startswith("sensor."):
        return entity_id.replace("sensor.", "sensor.hi_", 1)
    if entity_id.startswith("binary_sensor."):
        return entity_id.replace("binary_sensor.", "binary_sensor.hi_", 1)
    return entity_id


async def async_scan_v1_entities(hass: HomeAssistant) -> List[Dict[str, str]]:
    """Scan current states for known v1 entities and suggest v2 replacements."""
    results: List[Dict[str, str]] = []
    for state in hass.states.async_all():
        if any(state.entity_id.startswith(prefix) for prefix in V1_PREFIXES):
            results.append({
                "v1": state.entity_id,
                "v2": suggest_v2_entity(state.entity_id),
            })
    return results
