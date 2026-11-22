"""One optional read-only sensor for an entry's configured VOC index providers."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_entity_registry_updated_event, async_track_state_change_event

from ..const import DOMAIN
from ..helpers.voc_index import configured_sources, source_readings


@callback
def async_setup_index_sensor(hass, entry, add_entities, section):
    """Register the optional entity, or retire its exact record on explicit removal."""
    unique_id = f"hi_{entry.entry_id}_voc_index_sources"
    if sources := configured_sources(section):
        add_entities([HIVocIndexSources(unique_id, sources)])
    elif section == []:
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        existing = registry.async_get(entity_id) if entity_id else None
        if existing and existing.config_entry_id == entry.entry_id and existing.unique_id == unique_id:
            registry.async_remove(entity_id)


class HIVocIndexSources(SensorEntity):
    """State counts reporting sources. Individual readings live only in attributes."""

    _attr_should_poll = False
    _attr_name = "HI VOC index sources available"
    _attr_native_unit_of_measurement = "sources"
    _attr_icon = "mdi:counter"
    _unrecorded_attributes = frozenset({"readings"})

    def __init__(self, unique_id, sources):
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "hi")}, name="Humidity Intelligence")
        self._sources = sources

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        ids = [row["entity_id"] for row in self._sources if row["entity_id"] != self.entity_id]
        if ids:
            self.async_on_remove(async_track_state_change_event(self.hass, ids, self._source_changed))
        verified = [row["entity_id"] for row in self._sources if "provider_identity" in row]
        if verified:
            self.async_on_remove(async_track_entity_registry_updated_event(self.hass, verified, self._source_changed))
        self._refresh()

    @callback
    def _source_changed(self, _event):
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _refresh(self):
        readings = source_readings(self.hass, self._sources)
        self._attr_native_value = sum(row["status"] == "available" for row in readings.values())
        self._attr_extra_state_attributes = {"schema": 1, "readings": readings}
