"""Deterministic identity pairing for user-provided slope observations."""

from collections import Counter
import re
from typing import Any


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def match_provided_slopes(hass, sources, sensors, room_map, bindings=None, *, allow_singleton=True):
    """Return a source-to-slope mapping, omitting ambiguous or unmatched pairs.

    When ``bindings`` is supplied, retain only selected saved pairs with a
    unique sensor; invalid bindings return an empty mapping without inference.
    Otherwise match room labels against sensor IDs or friendly names, requiring
    one candidate per source and no shared candidates. ``allow_singleton``
    also permits pairing one source and one sensor without label evidence."""
    sources = list(dict.fromkeys(value for value in sources if isinstance(value, str) and value))
    sensors = list(dict.fromkeys(value for value in sensors if isinstance(value, str) and value))
    if bindings is not None:
        if not isinstance(bindings, dict):
            return {}
        candidates = {source: sensor for source, sensor in bindings.items()
                      if source in sources and isinstance(sensor, str) and sensor in sensors}
        counts = Counter(candidates.values())
        return {source: sensor for source, sensor in candidates.items() if counts[sensor] == 1}
    if allow_singleton and len(sources) == len(sensors) == 1:
        return {sources[0]: sensors[0]}
    candidates = {}
    for source in sources:
        room = _key(room_map.get(source, source))
        candidates[source] = []
        if not room:
            continue
        for sensor in sensors:
            state = hass.states.get(sensor)
            name = state.attributes.get("friendly_name", "") if state else ""
            if any(f"_{room}_" in f"_{_key(label)}_" for label in (sensor, name)):
                candidates[source].append(sensor)
    counts = Counter(sensor for matches in candidates.values() for sensor in matches)
    return {source: matches[0] for source, matches in candidates.items()
            if len(matches) == 1 and counts[matches[0]] == 1}


def bindings_for_save(hass, sources, sensors, telemetry, previous=None):
    """Capture pairs only during an explicit setup/Options save, never at startup.

    Retain valid saved pairs and infer unmatched pairs from temperature room
    labels. Pair without label evidence only when the entire selection has
    one unique source and one unique sensor. Return the mapping for the caller
    to validate and save; this function does not persist it."""
    room_map = {item.get("entity_id"): item.get("room") or item.get("friendly_name") or item.get("entity_id")
                for item in telemetry if item.get("sensor_type") == "temperature"}
    saved = match_provided_slopes(hass, sources, sensors, room_map, previous or {})
    remaining_sources = [source for source in sources if source not in saved]
    remaining_sensors = [sensor for sensor in sensors if sensor not in saved.values()]
    return saved | match_provided_slopes(
        hass, remaining_sources, remaining_sensors, room_map,
        allow_singleton=len(set(sources)) == len(set(sensors)) == 1,
    )
