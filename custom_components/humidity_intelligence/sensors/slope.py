"""Slope sensor implementation for Humidity Intelligence."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Deque, Dict, List, Optional, Tuple
import re

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.util import slugify

from ..const import DOMAIN, SLOPE_MODE_CALCULATED, SLOPE_MODE_PROVIDED
from ..helpers.parsing import hass_temperature_unit, parse_temperature

_LOGGER = logging.getLogger(__name__)

WINDOW = timedelta(hours=1)
SAMPLE_INTERVAL = timedelta(minutes=5)
# An inclusive hour can intersect 61 minute buckets. Keep actual observation times.
MAX_SAMPLES = 61


@dataclass
class _Point:
    ts: datetime
    value: float


class HISlopeSensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, name: str, unique_id: str, source_entity: str, tracker: "SlopeTracker") -> None:
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = "degC/h"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._source = source_entity
        self._tracker = tracker
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hi")},
            name="Humidity Intelligence",
            manufacturer="Humidity Intelligence",
        )

    def update(self) -> None:
        """Populate seeded slope state during entity add/poll cycles."""
        self.update_from_hass()

    def update_from_hass(self) -> None:
        self._attr_native_value = self._tracker.get_slope(self._source)
        self._attr_extra_state_attributes = {
            "source_entity": self._source,
            "window_minutes": int(WINDOW.total_seconds() // 60),
            "sample_count": self._tracker.sample_count(self._source),
        }


class SlopeTracker:
    def __init__(self) -> None:
        self._series: Dict[str, Deque[_Point]] = {}

    def record(self, entity_id: str, value: float, ts: Optional[datetime] = None) -> None:
        ts = ts or datetime.now()
        series = self._series.setdefault(entity_id, deque(maxlen=MAX_SAMPLES))
        if not series:
            # Seed a baseline point so slopes begin at 0.0 instead of "unknown".
            series.append(_Point(ts=ts - SAMPLE_INTERVAL, value=value))
        point = _Point(ts=ts, value=value)
        # A noisy source contributes its latest reading per minute, not event-rate
        # weighting. Publication remains immediate; no pending timer or backfill.
        if series[-1].ts.replace(second=0, microsecond=0) == ts.replace(second=0, microsecond=0):
            series[-1] = point
        else:
            series.append(point)
        cutoff = ts - WINDOW
        while series and series[0].ts < cutoff:
            series.popleft()

    def get_slope(self, entity_id: str) -> Optional[float]:
        series = self._series.get(entity_id)
        if not series or len(series) < 2:
            return None
        first_ts = series[0].ts
        points: List[Tuple[float, float]] = [
            ((point.ts - first_ts).total_seconds(), point.value) for point in series
        ]
        count = len(points)
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_x2 = sum(p[0] * p[0] for p in points)
        denom = (count * sum_x2) - (sum_x * sum_x)
        if denom <= 0:
            return 0.0
        slope_per_second = ((count * sum_xy) - (sum_x * sum_y)) / denom
        return round(slope_per_second * 3600.0, 2)

    def sample_count(self, entity_id: str) -> int:
        return len(self._series.get(entity_id, []))


def build_slope_entities(hass: HomeAssistant, entry: ConfigEntry) -> Tuple[List[SensorEntity], List[str], Dict[str, str]]:
    slope_cfg = _entry_section(entry, "slope", {})
    mode = slope_cfg.get("mode")
    telemetry = _entry_section(entry, "telemetry", [])

    room_map: Dict[str, str] = {}
    for item in telemetry:
        if item.get("sensor_type") != "temperature":
            continue
        room = item.get("room") or item.get("friendly_name") or item.get("entity_id")
        room_map[item.get("entity_id")] = room

    if mode == SLOPE_MODE_PROVIDED:
        source_entities: List[str] = slope_cfg.get("source_entities", [])
        if not source_entities:
            source_entities = [item.get("entity_id") for item in telemetry if item.get("sensor_type") == "temperature"]
        provided_sensors: List[str] = slope_cfg.get("provided_sensors", [])
        source_to_slope = _match_provided_sensors_to_sources(
            hass,
            source_entities,
            provided_sensors,
            room_map,
        )
        return [], provided_sensors, source_to_slope

    if mode != SLOPE_MODE_CALCULATED:
        return [], [], {}

    sources: List[str] = slope_cfg.get("source_entities", [])
    tracker = SlopeTracker()

    sensors: List[SensorEntity] = []
    sensors_by_source: Dict[str, List[HISlopeSensor]] = {}
    source_to_slope: Dict[str, str] = {}

    for entity_id in sources:
        room_name = room_map.get(entity_id, entity_id)
        object_id = slugify(room_name) or slugify(entity_id) or "temperature"
        unique_id = f"hi_{entry.entry_id}_slope_{object_id}"
        name = f"HI {room_name} Temperature Slope"
        sensor = HISlopeSensor(hass, name, unique_id, entity_id, tracker)
        sensors.append(sensor)
        sensors_by_source.setdefault(entity_id, []).append(sensor)
        registered_entity_id = _registered_slope_entity_id(hass, unique_id)
        sensor_entity_id = getattr(sensor, "entity_id", None)
        source_to_slope[entity_id] = (
            registered_entity_id
            or sensor_entity_id
            or f"sensor.hi_{object_id}_temperature_slope"
        )

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["slope_tracker"] = tracker
    hass.data[DOMAIN][entry.entry_id]["slope_sources"] = sources

    def _record_state(entity_id: str) -> bool:
        state = hass.states.get(entity_id)
        if state is None:
            return False
        raw_state = str(state.state).strip().lower()
        if raw_state in ("unknown", "unavailable"):
            return False
        value, reason = parse_temperature(
            state.state,
            state.attributes.get("unit_of_measurement"),
            hass_temperature_unit(hass),
        )
        if value is None:
            _LOGGER.debug("Skipping slope sample for %s due to %s", entity_id, reason or "non_numeric")
            return False
        tracker.record(entity_id, value)
        return True

    def _refresh_sensors(entity_ids: List[str]) -> None:
        for entity_id in entity_ids:
            for sensor in sensors_by_source[entity_id]:
                sensor.update_from_hass()
                sensor.async_write_ha_state()

    for source in sources:
        _record_state(source)
    for sensor in sensors:
        sensor.update_from_hass()

    async def _handle_change(event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id not in sensors_by_source:
            return
        if _record_state(entity_id):
            _refresh_sensors([entity_id])

    async def _periodic_sample(now) -> None:
        updated = [source for source in sources if _record_state(source)]
        if updated:
            _refresh_sensors(updated)

    unsub_state = async_track_state_change_event(hass, sources, _handle_change)
    unsub_periodic = async_track_time_interval(hass, _periodic_sample, SAMPLE_INTERVAL)

    def _unsub_all() -> None:
        unsub_state()
        unsub_periodic()

    hass.data[DOMAIN][entry.entry_id]["slope_unsub"] = _unsub_all

    return sensors, sources, source_to_slope


def _match_provided_sensors_to_sources(
    hass: HomeAssistant,
    source_entities: List[str],
    provided_sensors: List[str],
    room_map: Dict[str, str],
) -> Dict[str, str]:
    """Best-effort pairing from temperature sources -> provided slope sensors."""
    if not source_entities or not provided_sensors:
        return {}

    unmatched = [sensor for sensor in provided_sensors if isinstance(sensor, str)]
    mapping: Dict[str, str] = {}

    for source in source_entities:
        room_name = room_map.get(source, source)
        room_key = slugify(room_name) or ""
        selected = None
        for sensor_entity in unmatched:
            if _matches_room(hass, sensor_entity, room_key):
                selected = sensor_entity
                break
        if not selected and unmatched:
            selected = unmatched[0]
        if selected:
            mapping[source] = selected
            unmatched.remove(selected)

    return mapping


def _matches_room(hass: HomeAssistant, entity_id: str, room_key: str) -> bool:
    if not room_key:
        return False
    state = hass.states.get(entity_id)
    friendly = ""
    if state:
        friendly = str(state.attributes.get("friendly_name", ""))
    token_source = " ".join([entity_id, friendly])
    token_key = slugify(re.sub(r"[^A-Za-z0-9]+", " ", token_source))
    return bool(token_key and (room_key in token_key or token_key in room_key))


def _registered_slope_entity_id(hass: HomeAssistant, unique_id: str) -> Optional[str]:
    """Return HA's actual entity id for an existing slope unique_id."""
    try:
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id) if registry else None
    except (AttributeError, TypeError, ValueError):
        return None
    return entity_id if isinstance(entity_id, str) and entity_id else None


def _entry_section(entry: ConfigEntry, key: str, default: Any) -> Any:
    options = getattr(entry, "options", None) or {}
    if key in options:
        return options.get(key, default)
    data = getattr(entry, "data", None) or {}
    return data.get(key, default)
