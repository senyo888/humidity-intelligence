"""Automation engine for Humidity Intelligence."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .engine import HIAutomationEngine
from ..const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    engine = HIAutomationEngine(hass, entry)
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["automation_engine"] = engine
    # The integration's failed-setup path must retain and drain partial startup.
    await engine.async_start()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Stop the engine; the integration retains it until unload succeeds."""
    engine = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("automation_engine")
    if engine:
        await engine.async_stop()
