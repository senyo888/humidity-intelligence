"""Sensor platform for Humidity Intelligence."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
import asyncio
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .sensors.core import build_entities
from .sensors.slope import build_slope_entities
from homeassistant.helpers.device_registry import DeviceInfo


TIMER_KEYS = [
    "air_aq_upstairs_run",
    "air_aq_downstairs_run",
    "air_bathroom_min_run",
    "air_cooking_min_run",
    "air_control_pause",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    sensors, binary_sensors, sources = build_entities(hass, entry)
    slope_sensors, slope_sources, slope_map = build_slope_entities(hass, entry)
    diagnostics = HIDiagnosticsSensor(hass, entry.entry_id)
    timer_sensors = [HITimerSensor(entry.entry_id, key) for key in TIMER_KEYS]
    async_add_entities(sensors + slope_sensors + timer_sensors + [diagnostics], update_before_add=True)

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
        telemetry = config.get("telemetry", []) if isinstance(config, dict) else []
        cards = data.get("cards") or {}
        entity_map = data.get("entity_map") or {}
        unresolved = data.get("unresolved_placeholders") or []
        unresolved_by_card = data.get("unresolved_placeholders_by_card") or {}
        self._attr_extra_state_attributes = {
            "config": _sanitize_json(config),
            "options": _sanitize_json(data.get("options", {})),
            "entity_map": _sanitize_json(entity_map),
            "cards": list(cards.keys()),
            "unresolved_placeholders": _sanitize_json(unresolved),
            "unresolved_placeholders_by_card": _sanitize_json(unresolved_by_card),
            "counts": {
                "telemetry": len(telemetry),
                "mapped_entities": len([v for v in entity_map.values() if v]),
                "card_templates": len(cards.keys()),
                "unresolved_placeholders": len(unresolved),
            },
        }


class HITimerSensor(SensorEntity):
    """Lightweight timer sensor with remaining attribute."""

    def __init__(self, entry_id: str, key: str) -> None:
        self._entry_id = entry_id
        self._key = key
        self._end: datetime | None = None
        self._task: asyncio.Task | None = None
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
        return "active" if self._end and datetime.now() < self._end else "idle"

    @property
    def extra_state_attributes(self) -> dict:
        return {"remaining": self._remaining_str()}

    def _remaining_str(self) -> str:
        if not self._end:
            return "00:00:00"
        remaining = max(self._end - datetime.now(), timedelta(0))
        total = int(remaining.total_seconds())
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    async def async_start(self, duration: timedelta) -> None:
        if self._task:
            self._task.cancel()
        self._end = datetime.now() + duration
        self.async_write_ha_state()

        async def _finish() -> None:
            await asyncio.sleep(duration.total_seconds())
            self._end = None
            self.async_write_ha_state()

        self._task = asyncio.create_task(_finish())

    async def async_cancel(self) -> None:
        if self._task:
            self._task.cancel()
        self._end = None
        self.async_write_ha_state()


def _sanitize_json(value):
    if isinstance(value, dict):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, set):
        return list(value)
    # mappingproxy or other mapping types
    try:
        if hasattr(value, "keys") and hasattr(value, "__getitem__"):
            return {k: _sanitize_json(value[k]) for k in value.keys()}
    except Exception:
        pass
    return value
