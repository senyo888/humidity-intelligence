"""Switch helpers for Humidity Intelligence (replaces input_boolean helpers)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.switch import SwitchEntity

from .const import ALERT_TRIGGER_DEFS, DOMAIN, MAX_ALERTS, UI_DROPDOWN_AUTO_CLOSE_SECONDS


BASE_SWITCH_KEYS = [
    "air_aq_downstairs_active",
    "air_aq_upstairs_active",
    "air_co_emergency_active",
    "air_control_enabled",
    "air_control_manual_override",
    "air_control_output_expanded",
    "air_isolate_fan_outputs",
    "air_isolate_humidifier_outputs",
    "air_downstairs_humidifier_active",
    "air_upstairs_humidifier_active",
    "humidity_constellation_expanded",
    "toggle",
]

DEFAULT_ON = {"air_control_enabled"}


class HIInputSwitch(SwitchEntity, RestoreEntity):
    """Simple switch-like helper for HI UI compatibility."""

    def __init__(
        self,
        entry_id: str,
        key: str,
        *,
        name: str | None = None,
        attrs: Dict[str, Any] | None = None,
    ) -> None:
        self._entry_id = entry_id
        self._key = key
        self._state = key in DEFAULT_ON
        self._attr_name = name or f"HI {key.replace('_', ' ').title()}"
        self._attr_unique_id = f"hi_{entry_id}_input_{key}"
        self._attr_extra_state_attributes = attrs or {}
        self._auto_close_task: asyncio.Task | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hi")},
            name="Humidity Intelligence",
            manufacturer="Humidity Intelligence",
        )

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> bool:
        return self._state

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._state = last_state.state == "on"
            if self._state and self._supports_auto_close():
                self._schedule_auto_close()

    async def async_will_remove_from_hass(self) -> None:
        if self._auto_close_task:
            self._auto_close_task.cancel()
            self._auto_close_task = None

    async def async_turn_on(self, **kwargs) -> None:
        self._state = True
        self.async_write_ha_state()
        if self._supports_auto_close():
            self._schedule_auto_close()

    async def async_turn_off(self, **kwargs) -> None:
        self._state = False
        if self._auto_close_task:
            self._auto_close_task.cancel()
            self._auto_close_task = None
        self.async_write_ha_state()

    def _supports_auto_close(self) -> bool:
        return self._key.endswith("_expanded") or self._key == "toggle"

    def _schedule_auto_close(self) -> None:
        if self._auto_close_task:
            self._auto_close_task.cancel()

        async def _auto_close() -> None:
            try:
                await asyncio.sleep(UI_DROPDOWN_AUTO_CLOSE_SECONDS)
                if self._state:
                    self._state = False
                    self.async_write_ha_state()
            except asyncio.CancelledError:
                return

        self._auto_close_task = asyncio.create_task(_auto_close())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    entities: List[HIInputSwitch] = []
    for key in BASE_SWITCH_KEYS:
        entities.append(HIInputSwitch(entry.entry_id, key))
    alert_switches: Dict[int, HIInputSwitch] = {}
    for idx, key, name, attrs in _alert_switch_definitions(entry):
        entity = HIInputSwitch(entry.entry_id, key, name=name, attrs=attrs)
        entities.append(entity)
        alert_switches[idx] = entity
    async_add_entities(entities)

    data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    switches = {e._key: e for e in entities}
    # Keep legacy key name so automation engine stays compatible.
    data["hi_input_booleans"] = switches
    data["hi_switches"] = switches
    data["hi_alert_switches"] = alert_switches


def _resolved_alerts(entry: ConfigEntry) -> List[Dict[str, Any]]:
    if entry.options and "alerts" in entry.options:
        return list(entry.options.get("alerts", []))
    return list(entry.data.get("alerts", []))


def _alert_switch_definitions(entry: ConfigEntry) -> List[Tuple[int, str, str, Dict[str, Any]]]:
    defs: List[Tuple[int, str, str, Dict[str, Any]]] = []
    alerts = _resolved_alerts(entry)
    for idx, alert in enumerate(alerts[:MAX_ALERTS], start=1):
        trigger_type = str(alert.get("trigger_type") or "unknown")
        trigger_label = ALERT_TRIGGER_DEFS.get(trigger_type, {}).get(
            "label",
            trigger_type.replace("_", " ").title(),
        )
        threshold = alert.get("threshold")
        threshold_suffix = f" @ {threshold}" if threshold not in (None, "") else ""
        name = f"HI Alert {idx} {trigger_label}{threshold_suffix} Active"
        key = f"air_alert_{idx}_active"
        attrs = {
            "alert_index": idx,
            "trigger_type": trigger_type,
            "trigger_label": trigger_label,
            "threshold": threshold,
        }
        defs.append((idx, key, name, attrs))
    return defs
