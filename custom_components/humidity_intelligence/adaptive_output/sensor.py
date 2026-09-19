"""Optional output observations; failure never blocks HI's control entities."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_observation(hass, entry, async_add_entities):
    """Set up the optional observer in a separate failure boundary."""
    settings = entry.options.get("output_observation", entry.data.get("output_observation", {}))
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        return
    observer = None
    try:
        from .coordinator import OutputObserver

        observer = OutputObserver(hass, entry)
        await observer.async_start()
        hass.data[DOMAIN][entry.entry_id]["output_observer"] = observer
        async_add_entities([HIOutputStatusSensor(entry.entry_id, observer)])
    except Exception:
        _LOGGER.exception("Optional HI output observation could not start; control remains available")
        if observer is not None:
            try:
                await observer.async_stop()
            except Exception:
                _LOGGER.exception("Optional output observation cleanup failed")
        hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).pop("output_observer", None)


class HIOutputStatusSensor(SensorEntity):
    """Backend-owned observation, separate from command or physical-device proof."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "output_status"
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"payload", "error"})

    def __init__(self, entry_id, observer):
        self.observer = observer
        self._attr_unique_id = f"hi_{entry_id}_output_status"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "hi")}, name="Humidity Intelligence")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.observer.subscribe(self.async_write_ha_state))

    async def async_will_remove_from_hass(self):
        if self.observer.active:
            try:
                await self.observer.async_stop()
            except Exception:
                _LOGGER.exception("Optional output observation cleanup failed")
        await super().async_will_remove_from_hass()

    @property
    def available(self):
        return self.observer.payload is not None

    @property
    def native_value(self):
        return self.observer.payload["state"] if self.observer.payload else None

    @property
    def extra_state_attributes(self):
        payload = self.observer.payload
        return {
            "schema_version": payload["schema_version"] if payload else 2,
            "source": "home_assistant",
            "summary": payload["summary"] if payload else "Output observation unavailable",
            "counts": payload["counts"] if payload else {},
            "payload": payload,
            "error": self.observer.failure,
        }
