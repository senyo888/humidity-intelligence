"""Binary sensor platform for Humidity Intelligence."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .sensors.core import build_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    binary_sensors = data.get("core_binary_sensors")
    if binary_sensors is None:
        _, binary_sensors, _ = build_entities(hass, entry)
        data["core_binary_sensors"] = binary_sensors
    if binary_sensors:
        async_add_entities(binary_sensors)
