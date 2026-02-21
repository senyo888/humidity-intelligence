"""Sensor platform for Humidity Intelligence."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from . import core, slope, aq


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up HI sensors."""
    await core.async_setup_entry(hass, entry)
    await slope.async_setup_entry(hass, entry)
    await aq.async_setup_entry(hass, entry)
