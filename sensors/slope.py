"""Slope sensor implementation for Humidity Intelligence."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple
import re

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.util import slugify

from ..const import DOMAIN, SLOPE_MODE_CALCULATED, SLOPE_MODE_PROVIDED


WINDOW = timedelta(hours=1)
SAMPLE_INTERVAL = timedelta(minutes=5)


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
        series = self._series.setdefault(entity_id, deque())
        if not series:
            # Seed a baseline point so slopes begin at 0.0 instead of "unknown".
            series.append(_Point(ts=ts - SAMPLE_INTERVAL, value=value))
        series.append(_Point(ts=ts, value=value))
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
    source_to_slope: Dict[str, str] = {}

    for entity_id in sources:
        room_name = room_map.get(entity_id, entity_id)
        object_id = room_name.lower().replace(" ", "_")
        unique_id = f"hi_{entry.entry_id}_slope_{object_id}"
        name = f"HI {room_name} Temperature Slope"
        sensor = HISlopeSensor(hass, name, unique_id, entity_id, tracker)
        sensors.append(sensor)
        source_to_slope[entity_id] = (
            sensor.entity_id if sensor.entity_id else f"sensor.hi_{object_id}_temperature_slope"
        )

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["slope_tracker"] = tracker
    hass.data[DOMAIN][entry.entry_id]["slope_sources"] = sources

    def _record_state(entity_id: str) -> bool:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        try:
            value = float(state.state)
        except ValueError:
            return False
        tracker.record(entity_id, value)
        return True

    def _refresh_sensors() -> None:
        for sensor in sensors:
            sensor.update_from_hass()
            sensor.async_write_ha_state()

    for source in sources:
        _record_state(source)

    async def _handle_change(event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id not in sources:
            return
        if _record_state(entity_id):
            _refresh_sensors()

    async def _periodic_sample(now) -> None:
        updated = False
        for source in sources:
            if _record_state(source):
                updated = True
        if updated:
            _refresh_sensors()

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


def _entry_section(entry: ConfigEntry, key: str, default: Any) -> Any:
    options = getattr(entry, "options", None) or {}
    if key in options:
        return options.get(key, default)
    data = getattr(entry, "data", None) or {}
    return data.get(key, default)
