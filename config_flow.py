"""Config flow for the Humidity Intelligence integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from .const import (
    DOMAIN,
    DEFAULT_TIME_END,
    DEFAULT_TIME_START,
    ENGINE_INTERVAL_MAX,
    ENGINE_INTERVAL_MIN,
    ENGINE_INTERVAL_MINUTES_DEFAULT,
    ENGINE_INTERVAL_STEP,
    DEPENDENCIES,
    LEVELS,
    MAX_ALERTS,
    OUTSIDE_WINDOW_ACTIONS,
    SENSOR_TYPES,
    SLOPE_MODE_CALCULATED,
    SLOPE_MODE_NONE,
    SLOPE_MODE_PROVIDED,
    TRIGGER_DEFS,
    AQ_TRIGGER_DEFS,
    ALERT_TRIGGER_DEFS,
    ALERT_THRESHOLD_BOUNDS,
    HUMIDIFIER_BAND_MIN,
    HUMIDIFIER_BAND_MAX,
    HUMIDIFIER_BAND_STEP,
    ALERT_DURATION_MIN,
    ALERT_DURATION_MAX,
    ALERT_DURATION_STEP,
    ALERT_FLASH_MODES,
    AQ_DURATION_MIN,
    AQ_DURATION_MAX,
    AQ_DURATION_STEP,
    ZONE_OUTPUT_LEVEL_DEFAULT,
    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
    COMMON_ROOMS,
    FAN_OUTPUT_LEVEL_AUTO,
    FAN_OUTPUT_LEVEL_STEPS,
)

_LOGGER = logging.getLogger(__name__)


class HumidityIntelligenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Humidity Intelligence."""

    VERSION = 1
    MINOR_VERSION = 0
    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HumidityIntelligenceOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._telemetry: List[Dict[str, Any]] = []
        self._zones: Dict[str, Dict[str, Any]] = {}
        self._humidifiers: Dict[str, Dict[str, Any]] = {}
        self._aq: Dict[str, Dict[str, Any]] = {}
        self._alerts: List[Dict[str, Any]] = []
        self._pending_zone_key: Optional[str] = None
        self._pending_aq_level: Optional[str] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Entry point for the flow. Present the dependencies page first."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_dependencies()

    async def async_step_dependencies(self, user_input: Optional[Dict[str, Any]] = None):
        """Collect optional dependency information and allow skipping."""
        if user_input is not None:
            self._data["skip_dependencies"] = user_input.get("skip", False)
            return await self.async_step_gates()

        dep_lines = await _render_dependency_status(self.hass)
        schema = vol.Schema({
            vol.Optional("skip", default=False): selector.BooleanSelector()
        })
        return self.async_show_form(
            step_id="dependencies",
            data_schema=schema,
            description_placeholders={"dependencies": dep_lines},
        )

    async def async_step_gates(self, user_input: Optional[Dict[str, Any]] = None):
        """Collect global time and presence gate settings."""
        if user_input is not None:
            self._data["time_gate"] = {
                "enabled": user_input.get("enable_time_gate", False),
                "start": user_input.get("start_time"),
                "end": user_input.get("end_time"),
                "outside_action": user_input.get("outside_action"),
            }
            self._data["engine_interval_minutes"] = user_input.get(
                "engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT
            )
            presence_enabled = user_input.get("enable_presence_gate", False)
            entities = user_input.get("presence_entities", [])
            self._data["presence_gate"] = {
                "enabled": presence_enabled,
                "entities": entities,
                "present_states": [],
                "away_states": [],
            }
            if presence_enabled and entities:
                return await self.async_step_presence_states()
            return await self.async_step_telemetry()

        gates_schema = vol.Schema({
            vol.Optional("enable_time_gate", default=False): selector.BooleanSelector(),
            vol.Optional("start_time", default=DEFAULT_TIME_START): selector.TimeSelector(),
            vol.Optional("end_time", default=DEFAULT_TIME_END): selector.TimeSelector(),
            vol.Optional("outside_action", default=OUTSIDE_WINDOW_ACTIONS[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in OUTSIDE_WINDOW_ACTIONS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("engine_interval_minutes", default=ENGINE_INTERVAL_MINUTES_DEFAULT): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ENGINE_INTERVAL_MIN,
                    max=ENGINE_INTERVAL_MAX,
                    step=ENGINE_INTERVAL_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional("enable_presence_gate", default=False): selector.BooleanSelector(),
            vol.Optional("presence_entities", default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        })
        return self.async_show_form(step_id="gates", data_schema=gates_schema)

    async def async_step_presence_states(self, user_input: Optional[Dict[str, Any]] = None):
        """Collect presence state values that indicate someone is home."""
        options = _presence_state_options(self.hass, self._data.get("presence_gate", {}).get("entities", []))
        if user_input is not None:
            states = user_input.get("present_states", [])
            away_states = user_input.get("away_states", [])
            overlap = set(states).intersection(set(away_states))
            if overlap:
                return self.async_show_form(
                    step_id="presence_states",
                    data_schema=self._presence_states_schema(options),
                    errors={"away_states": "overlap"},
                )
            self._data.setdefault("presence_gate", {})["present_states"] = states
            self._data.setdefault("presence_gate", {})["away_states"] = away_states
            return await self.async_step_telemetry()

        schema = self._presence_states_schema(options)
        return self.async_show_form(step_id="presence_states", data_schema=schema)

    def _presence_states_schema(self, options: List[str]) -> vol.Schema:
        select_options = [SelectOptionDict(value=o, label=o) for o in options] if options else []
        return vol.Schema({
            vol.Required("present_states", default=options or ["home"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("away_states", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

    async def async_step_telemetry(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for telemetry sensors."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_telemetry_add()
            if action == "manage":
                return await self.async_step_telemetry_manage()
            if action == "done":
                return await self.async_step_telemetry_done()
            if action == "back":
                return await self.async_step_gates()

        options = [
            SelectOptionDict(value="add", label="Add sensor"),
        ]
        if self._telemetry:
            options.append(SelectOptionDict(value="manage", label="Manage sensors"))
            options.append(SelectOptionDict(value="done", label="Continue"))
        options.append(SelectOptionDict(value="back", label="Back"))

        schema = vol.Schema({
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry",
            data_schema=schema,
            description_placeholders={
                "existing": _render_existing_telemetry(self._telemetry),
            },
        )

    async def async_step_telemetry_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a telemetry sensor entry."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input["entity_id"]
            if any(t.get("entity_id") == entity_id for t in self._telemetry):
                errors["entity_id"] = "duplicate_entity"
            else:
                entry = {
                    "entity_id": entity_id,
                    "sensor_type": user_input["sensor_type"],
                    "friendly_name": user_input.get("friendly_name", ""),
                    "level": user_input["level"],
                    "room": user_input.get("room", ""),
                }
                self._telemetry.append(entry)
                self._data["telemetry"] = self._telemetry
                return await self.async_step_telemetry()

        default_room, default_level = _suggest_room_and_level(self.hass, user_input["entity_id"] if user_input else None)
        room_options = [SelectOptionDict(value=o, label=o) for o in COMMON_ROOMS]
        level_default = default_level or LEVELS[0]["value"]
        schema = vol.Schema({
            vol.Required("entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Required("sensor_type", default=SENSOR_TYPES[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in SENSOR_TYPES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("friendly_name", default=""): selector.TextSelector(),
            vol.Required("level", default=level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=default_room): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=False,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry_add",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "existing": _render_existing_telemetry(self._telemetry),
            },
        )

    async def async_step_telemetry_done(self, user_input: Optional[Dict[str, Any]] = None):
        """Finish telemetry selection and move to slope configuration."""
        if not self._telemetry:
            return await self.async_step_telemetry_add()
        return await self.async_step_slope()

    async def async_step_telemetry_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_gates()

    async def async_step_telemetry_manage(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit or delete an existing telemetry entry."""
        if not self._telemetry:
            return await self.async_step_telemetry_add()

        errors: Dict[str, str] = {}
        if user_input is not None:
            selection = user_input.get("selection")
            action = user_input.get("action")
            if selection is None:
                errors["selection"] = "required"
            else:
                index = int(selection)
                if action == "delete":
                    if 0 <= index < len(self._telemetry):
                        self._telemetry.pop(index)
                        self._data["telemetry"] = self._telemetry
                    return await self.async_step_telemetry()
                if action == "edit":
                    self._data["telemetry_edit_index"] = index
                    return await self.async_step_telemetry_edit()

        options = _telemetry_options(self._telemetry)
        schema = vol.Schema({
            vol.Required("selection"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("action", default="edit"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="edit", label="Edit"),
                        SelectOptionDict(value="delete", label="Delete"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry_manage",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "existing": _render_existing_telemetry(self._telemetry),
            },
        )

    async def async_step_telemetry_edit(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit an existing telemetry sensor entry."""
        index = self._data.get("telemetry_edit_index")
        if index is None or index >= len(self._telemetry):
            return await self.async_step_telemetry()

        current = self._telemetry[index]
        errors: Dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input["entity_id"]
            if any(i != index and t.get("entity_id") == entity_id for i, t in enumerate(self._telemetry)):
                errors["entity_id"] = "duplicate_entity"
            else:
                current.update({
                    "entity_id": entity_id,
                    "sensor_type": user_input["sensor_type"],
                    "friendly_name": user_input.get("friendly_name", ""),
                    "level": user_input["level"],
                    "room": user_input.get("room", ""),
                })
                self._telemetry[index] = current
                self._data["telemetry"] = self._telemetry
                return await self.async_step_telemetry()

        room_options = [SelectOptionDict(value=o, label=o) for o in COMMON_ROOMS]
        schema = vol.Schema({
            vol.Required("entity_id", default=current.get("entity_id")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Required("sensor_type", default=current.get("sensor_type")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in SENSOR_TYPES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("friendly_name", default=current.get("friendly_name", "")): selector.TextSelector(),
            vol.Required("level", default=current.get("level")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=current.get("room", "")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=False,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry_edit",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_slope(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure temperature slope sensors."""
        temp_entities = [t["entity_id"] for t in self._telemetry if t["sensor_type"] == "temperature"]
        if not temp_entities:
            self._data["slope"] = {"mode": SLOPE_MODE_NONE, "source_entities": []}
            return await self.async_step_zones()

        errors: Dict[str, str] = {}
        if user_input is not None:
            mode = user_input["slope_mode"]
            slope_sources = user_input.get("slope_sources", [])
            provided_sensors = user_input.get("slope_sensors", [])
            if mode == SLOPE_MODE_CALCULATED and not slope_sources:
                errors["slope_sources"] = "required"
            if mode == SLOPE_MODE_PROVIDED and not provided_sensors:
                errors["slope_sensors"] = "required"
            if not errors:
                slope_data: Dict[str, Any] = {"mode": mode, "source_entities": []}
                if mode == SLOPE_MODE_CALCULATED:
                    slope_data["source_entities"] = slope_sources
                elif mode == SLOPE_MODE_PROVIDED:
                    slope_data["source_entities"] = slope_sources or temp_entities
                    slope_data["provided_sensors"] = provided_sensors
                self._data["slope"] = slope_data
                return await self.async_step_zones()

        schema = vol.Schema({
            vol.Required("slope_mode", default=SLOPE_MODE_CALCULATED): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=SLOPE_MODE_CALCULATED, label="HI calculates slope"),
                        SelectOptionDict(value=SLOPE_MODE_PROVIDED, label="Provide my own slope sensors"),
                        SelectOptionDict(value=SLOPE_MODE_NONE, label="Skip slope"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("slope_sources", default=temp_entities): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional("slope_sensors", default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
        })
        return self.async_show_form(step_id="slope", data_schema=schema, errors=errors)

    async def async_step_zones(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for zone configuration."""
        zone_summary = _render_zones_summary(self._zones)
        return self.async_show_menu(
            step_id="zones",
            menu_options=[
                "zone1",
                "zone2",
                "zones_done",
                "zones_back",
            ],
            description_placeholders={"configured_zones": zone_summary},
        )

    async def async_step_zone1(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_zone_config("zone1", user_input)

    async def async_step_zone2(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_zone_config("zone2", user_input)

    async def _async_step_zone_config(self, zone_key: str, user_input: Optional[Dict[str, Any]] = None):
        """Configure a single zone."""
        existing = self._zones.get(zone_key, {})
        if user_input is not None:
            enabled = user_input.get("enabled", False)
            zone = {
                "enabled": enabled,
                "level": user_input.get("level"),
                "rooms": user_input.get("rooms", []),
                "triggers": user_input.get("triggers", []),
                "outputs": user_input.get("outputs", []),
                "output_level": _normalize_fan_level_choice(
                    user_input.get("output_level"),
                    existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                ),
                "boost_output_level": _normalize_fan_level_choice(
                    user_input.get("boost_output_level"),
                    existing.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                ),
                "ui_label": _sanitize_ui_label(
                    user_input.get("ui_label"),
                    existing.get("ui_label") or _default_zone_ui_label(zone_key),
                ),
                "thresholds": existing.get("thresholds", {}),
            }
            self._zones[zone_key] = zone
            self._data["zones"] = self._zones
            if enabled and zone["triggers"]:
                self._pending_zone_key = zone_key
                return await self.async_step_zone_thresholds()
            return await self.async_step_zones()

        rooms_all = _rooms_all(self._telemetry)
        level_default = existing.get("level") or LEVELS[0]["value"]
        room_options = [SelectOptionDict(value=r, label=r) for r in rooms_all]
        trigger_options = _zone_trigger_options(level_default)
        schema = vol.Schema({
            vol.Optional("enabled", default=existing.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("level", default=level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("rooms", default=existing.get("rooms", [])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("triggers", default=existing.get("triggers", [])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=existing.get("outputs", [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            vol.Optional(
                "output_level",
                default=_normalize_fan_level_choice(
                    existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "boost_output_level",
                default=_normalize_fan_level_choice(
                    existing.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("ui_label", default=existing.get("ui_label", _default_zone_ui_label(zone_key))): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        })
        return self.async_show_form(step_id=zone_key, data_schema=schema)

    async def async_step_zone_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure zone thresholds for the selected triggers."""
        zone_key = self._pending_zone_key
        if not zone_key:
            return await self.async_step_zones()

        zone = self._zones.get(zone_key, {})
        triggers = zone.get("triggers", [])
        if user_input is not None:
            thresholds = {k: v for k, v in user_input.items()}
            zone["thresholds"] = thresholds
            self._zones[zone_key] = zone
            self._data["zones"] = self._zones
            self._pending_zone_key = None
            return await self.async_step_zones()

        fields: Dict[Any, Any] = {}
        for trig in triggers:
            trig_def = TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            default = zone.get("thresholds", {}).get(trig, trig_def["default"])
            fields[vol.Optional(trig, default=default)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=trig_def["min"],
                    max=trig_def["max"],
                    step=trig_def.get("step", 1),
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement=trig_def.get("unit", "%"),
                )
            )
        schema = vol.Schema(fields)
        return self.async_show_form(step_id="zone_thresholds", data_schema=schema)

    async def async_step_zones_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_humidifiers()

    async def async_step_zones_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_slope()

    async def async_step_humidifiers(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for humidifier automations per level."""
        levels = _configured_levels(self._telemetry)
        if not levels:
            levels = [LEVELS[0]["value"]]
        self._data.setdefault("levels", levels)
        options = [f"humidifier_{lvl}" for lvl in levels] + ["humidifiers_done", "humidifiers_back"]
        return self.async_show_menu(step_id="humidifiers", menu_options=options)

    async def async_step_humidifier_level1(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_humidifier("level1", user_input)

    async def async_step_humidifier_level2(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_humidifier("level2", user_input)

    async def _async_step_humidifier(self, level: str, user_input: Optional[Dict[str, Any]] = None):
        existing = self._humidifiers.get(level, {})
        if user_input is not None:
            self._humidifiers[level] = {
                "enabled": user_input.get("enabled", False),
                "band_adjust": user_input.get("band_adjust", 0),
                "outputs": user_input.get("outputs", []),
            }
            self._data["humidifiers"] = self._humidifiers
            return await self.async_step_humidifiers()

        target_low = f"sensor.hi_{level}_humidity_target_low"
        target_high = f"sensor.hi_{level}_humidity_target_high"
        schema = vol.Schema({
            vol.Optional("enabled", default=existing.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("band_adjust", default=existing.get("band_adjust", 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=HUMIDIFIER_BAND_MIN,
                    max=HUMIDIFIER_BAND_MAX,
                    step=HUMIDIFIER_BAND_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="%",
                )
            ),
            vol.Optional("outputs", default=existing.get("outputs", [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["humidifier", "fan", "switch"], multiple=True)
            ),
        })
        return self.async_show_form(
            step_id=f"humidifier_{level}",
            data_schema=schema,
            description_placeholders={
                "target_low": target_low,
                "target_high": target_high,
            },
        )

    async def async_step_humidifiers_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_aq()

    async def async_step_humidifiers_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_zones()

    async def async_step_aq(self, user_input: Optional[Dict[str, Any]] = None):
        """Air quality automation menu."""
        levels = _levels_with_aq(self._telemetry)
        if not levels:
            return await self.async_step_aq_skip()
        options = [f"aq_{lvl}" for lvl in levels] + ["aq_done", "aq_back"]
        return self.async_show_menu(step_id="aq", menu_options=options)

    async def async_step_aq_skip(self, user_input: Optional[Dict[str, Any]] = None):
        if user_input is not None:
            return await self.async_step_alerts()
        schema = vol.Schema({
            vol.Optional("skip", default=True): selector.BooleanSelector()
        })
        return self.async_show_form(step_id="aq_skip", data_schema=schema)

    async def async_step_aq_level1(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_aq("level1", user_input)

    async def async_step_aq_level2(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_aq("level2", user_input)

    async def _async_step_aq(self, level: str, user_input: Optional[Dict[str, Any]] = None):
        existing = self._aq.get(level, {})
        if user_input is not None:
            self._aq[level] = {
                "enabled": user_input.get("enabled", False),
                "triggers": user_input.get("triggers", []),
                "outputs": user_input.get("outputs", []),
                "run_duration": user_input.get("run_duration"),
                "output_level": _normalize_fan_level_choice(
                    user_input.get("output_level"),
                    existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                ),
                "thresholds": existing.get("thresholds", {}),
            }
            self._data["aq"] = self._aq
            if self._aq[level]["enabled"] and self._aq[level]["triggers"]:
                self._pending_aq_level = level
                return await self.async_step_aq_thresholds()
            return await self.async_step_aq()

        trigger_options = _aq_trigger_options(level)
        schema = vol.Schema({
            vol.Optional("enabled", default=existing.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("triggers", default=existing.get("triggers", [])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=existing.get("outputs", [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "air_purifier", "switch"], multiple=True)
            ),
            vol.Optional("run_duration", default=existing.get("run_duration", 30)):
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=AQ_DURATION_MIN,
                        max=AQ_DURATION_MAX,
                        step=AQ_DURATION_STEP,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
            vol.Optional(
                "output_level",
                default=_normalize_fan_level_choice(
                    existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            ),
        })
        return self.async_show_form(step_id=f"aq_{level}", data_schema=schema)

    async def async_step_aq_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        level = self._pending_aq_level
        if not level:
            return await self.async_step_aq()

        aq = self._aq.get(level, {})
        triggers = aq.get("triggers", [])
        if user_input is not None:
            thresholds = {k: v for k, v in user_input.items()}
            aq["thresholds"] = thresholds
            self._aq[level] = aq
            self._data["aq"] = self._aq
            self._pending_aq_level = None
            return await self.async_step_aq()

        fields: Dict[Any, Any] = {}
        for trig in triggers:
            trig_def = AQ_TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            default = aq.get("thresholds", {}).get(trig, trig_def["default"])
            fields[vol.Optional(trig, default=default)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=trig_def["min"],
                    max=trig_def["max"],
                    step=trig_def.get("step", 1),
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement=trig_def.get("unit"),
                )
            )
        schema = vol.Schema(fields)
        return self.async_show_form(step_id="aq_thresholds", data_schema=schema)

    async def async_step_aq_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_alerts()

    async def async_step_aq_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_humidifiers()

    async def async_step_alerts(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for alert/emergency automations."""
        if len(self._alerts) >= MAX_ALERTS:
            return await self.async_step_alerts_done()
        alert_summary = _render_alerts_summary(self._alerts)
        return self.async_show_menu(
            step_id="alerts",
            menu_options=[
                "alert_add",
                "alerts_done",
                "alerts_back",
            ],
            description_placeholders={"configured_alerts": alert_summary},
        )

    async def async_step_alert_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a high-priority alert automation."""
        if user_input is not None:
            trigger_type = user_input.get("trigger_type")
            alert: Dict[str, Any] = {
                "enabled": user_input.get("enabled", False),
                "trigger_type": trigger_type,
                "custom_trigger": _sanitize_optional_entity_id(user_input.get("custom_trigger")),
                "threshold": _safe_alert_threshold(trigger_type, user_input.get("threshold")),
                "lights": _sanitize_entity_ids(user_input.get("lights", [])),
                "outputs": _sanitize_entity_ids(user_input.get("outputs", [])),
                "power_entity": _sanitize_optional_entity_id(user_input.get("power_entity")),
                "flash_mode": user_input.get("flash_mode"),
                "duration": user_input.get("duration"),
            }
            self._alerts.append(alert)
            self._data["alerts"] = self._alerts
            return await self.async_step_alerts()

        trigger_options = [SelectOptionDict(value=k, label=v["label"]) for k, v in ALERT_TRIGGER_DEFS.items()]
        default_trigger = trigger_options[0]["value"] if trigger_options else "humidity_danger"
        threshold_min, threshold_max, threshold_default, threshold_unit = _alert_threshold_bounds(default_trigger)
        schema = vol.Schema({
            vol.Optional("enabled", default=True): selector.BooleanSelector(),
            vol.Required("trigger_type", default=default_trigger): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("custom_trigger"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=False)
            ),
            vol.Optional("threshold", default=threshold_default): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=threshold_min,
                    max=threshold_max,
                    step=1,
                    unit_of_measurement=threshold_unit,
                )
            ),
            vol.Optional("lights", default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional("outputs", default=[]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            vol.Optional("power_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=False)
            ),
            vol.Optional("flash_mode", default=ALERT_FLASH_MODES[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in ALERT_FLASH_MODES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("duration", default=10): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ALERT_DURATION_MIN,
                    max=ALERT_DURATION_MAX,
                    step=ALERT_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
        })
        return self.async_show_form(step_id="alert_add", data_schema=schema)

    async def async_step_alerts_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_ui_install()

    async def async_step_alerts_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_aq()

    async def _async_create_entry(self):
        """Create the final config entry."""
        return super().async_create_entry(title="Humidity Intelligence", data=self._data)

    async def async_step_ui_install(self, user_input: Optional[Dict[str, Any]] = None):
        """Final step: choose UI layouts to export."""
        if user_input is not None:
            self._data["ui_layouts"] = user_input.get("ui_layouts", [])
            return await self._async_create_entry()

        options = [
            SelectOptionDict(value="v2_mobile", label="V2 Mobile"),
            SelectOptionDict(value="v2_tablet", label="V2 Tablet"),
            SelectOptionDict(value="v1_mobile", label="V1 Mobile"),
            SelectOptionDict(value="view_cards_button", label="View Cards Button"),
            SelectOptionDict(value="create_dashboard", label="Create Dashboard Automatically"),
        ]
        schema = vol.Schema({
            vol.Optional("ui_layouts", default=["v2_mobile"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="ui_install",
            data_schema=schema,
            description_placeholders={"configured_alerts": _render_alerts_summary(self._alerts)},
        )


class HumidityIntelligenceOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Humidity Intelligence."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._options = dict(entry.options) if entry.options else {}
        self._pending_telemetry_index: Optional[int] = None
        self._pending_zone_key: Optional[str] = None
        self._pending_humidifier_level: Optional[str] = None
        self._pending_aq_level: Optional[str] = None
        self._pending_alert_index: Optional[int] = None
        self._pending_presence_gate: Optional[Dict[str, Any]] = None

    def _section(self, key: str, default: Any) -> Any:
        if key in self._options:
            return self._options.get(key, default)
        return _entry_section(self._entry, key, default)

    def _sync_slope_after_telemetry_add(self, telemetry_entry: Dict[str, Any]) -> None:
        """Keep slope source associations in sync when adding temperature telemetry."""
        if telemetry_entry.get("sensor_type") != "temperature":
            return
        entity_id = _sanitize_optional_entity_id(telemetry_entry.get("entity_id"))
        if not entity_id:
            return

        slope = dict(self._section("slope", {}))
        if not slope:
            return

        mode = slope.get("mode")
        if mode not in {SLOPE_MODE_CALCULATED, SLOPE_MODE_PROVIDED}:
            return

        source_entities = _sanitize_entity_ids(slope.get("source_entities", []))
        if entity_id in source_entities:
            return

        source_entities.append(entity_id)
        slope["source_entities"] = source_entities
        self._options["slope"] = slope

    def _purge_deleted_telemetry_associations(
        self, removed_entity_id: str, telemetry: List[Dict[str, Any]]
    ) -> None:
        """Purge deleted telemetry from related config sections."""
        slope = dict(self._section("slope", {}))
        if not slope:
            return

        mode = slope.get("mode", SLOPE_MODE_NONE)
        source_entities = [
            entity_id
            for entity_id in _sanitize_entity_ids(slope.get("source_entities", []))
            if entity_id != removed_entity_id
        ]
        provided_sensors = [
            entity_id
            for entity_id in _sanitize_entity_ids(slope.get("provided_sensors", []))
            if entity_id != removed_entity_id
        ]

        if not source_entities and mode in {SLOPE_MODE_CALCULATED, SLOPE_MODE_PROVIDED}:
            remaining_temp_sources = [
                item.get("entity_id")
                for item in telemetry
                if item.get("sensor_type") == "temperature" and item.get("entity_id")
            ]
            source_entities = _sanitize_entity_ids(remaining_temp_sources)

        if mode == SLOPE_MODE_CALCULATED and not source_entities:
            slope = {"mode": SLOPE_MODE_NONE, "source_entities": []}
        elif mode == SLOPE_MODE_PROVIDED and not provided_sensors:
            slope = {"mode": SLOPE_MODE_NONE, "source_entities": []}
        else:
            slope["source_entities"] = source_entities
            if mode == SLOPE_MODE_PROVIDED:
                slope["provided_sensors"] = provided_sensors
            elif "provided_sensors" in slope:
                slope.pop("provided_sensors", None)

        self._options["slope"] = slope

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "options_sensors",
                "options_gates",
                "options_zones",
                "options_humidifiers",
                "options_aq",
                "options_alerts",
                "options_slope",
                "options_done",
            ],
        )

    async def async_step_options_gates(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit global time/presence gates from post-configuration options."""
        time_gate = dict(self._section("time_gate", {}))
        presence_gate = dict(self._section("presence_gate", {}))

        default_presence_entities = _sanitize_entity_ids(presence_gate.get("entities", []))
        default_present_states = _sanitize_state_values(presence_gate.get("present_states", []))
        default_away_states = _sanitize_state_values(presence_gate.get("away_states", []))

        if user_input is not None:
            self._options["time_gate"] = {
                "enabled": user_input.get("enable_time_gate", False),
                "start": user_input.get("start_time"),
                "end": user_input.get("end_time"),
                "outside_action": user_input.get("outside_action", OUTSIDE_WINDOW_ACTIONS[0]["value"]),
            }
            self._options["engine_interval_minutes"] = user_input.get(
                "engine_interval_minutes",
                self._section("engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT),
            )

            presence_enabled = user_input.get("enable_presence_gate", False)
            entities = _sanitize_entity_ids(user_input.get("presence_entities", []))
            pending_presence = {
                "enabled": presence_enabled,
                "entities": entities,
                "present_states": default_present_states,
                "away_states": default_away_states,
            }

            if presence_enabled and entities:
                self._pending_presence_gate = pending_presence
                return await self.async_step_options_presence_states()

            self._options["presence_gate"] = pending_presence
            self._pending_presence_gate = None
            return await self.async_step_init()

        gates_schema = vol.Schema({
            vol.Optional("enable_time_gate", default=time_gate.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("start_time", default=time_gate.get("start") or DEFAULT_TIME_START): selector.TimeSelector(),
            vol.Optional("end_time", default=time_gate.get("end") or DEFAULT_TIME_END): selector.TimeSelector(),
            vol.Optional(
                "outside_action",
                default=time_gate.get("outside_action") or OUTSIDE_WINDOW_ACTIONS[0]["value"],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in OUTSIDE_WINDOW_ACTIONS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "engine_interval_minutes",
                default=self._section("engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ENGINE_INTERVAL_MIN,
                    max=ENGINE_INTERVAL_MAX,
                    step=ENGINE_INTERVAL_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional("enable_presence_gate", default=presence_gate.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("presence_entities", default=default_presence_entities): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        })
        return self.async_show_form(step_id="options_gates", data_schema=gates_schema)

    async def async_step_options_presence_states(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit presence and away state mapping for configured presence entities."""
        presence_gate = dict(self._pending_presence_gate or self._section("presence_gate", {}))
        entities = _sanitize_entity_ids(presence_gate.get("entities", []))
        live_states = _presence_state_options(self.hass, entities)
        present_defaults = _sanitize_state_values(presence_gate.get("present_states", []))
        away_defaults = _sanitize_state_values(presence_gate.get("away_states", []))
        options = _merge_unique_values(live_states, present_defaults, away_defaults)

        errors: Dict[str, str] = {}
        if user_input is not None:
            present_states = _sanitize_state_values(user_input.get("present_states", []))
            away_states = _sanitize_state_values(user_input.get("away_states", []))
            overlap = set(present_states).intersection(set(away_states))
            if overlap:
                errors["away_states"] = "overlap"
            else:
                self._options["presence_gate"] = {
                    "enabled": bool(presence_gate.get("enabled")),
                    "entities": entities,
                    "present_states": present_states,
                    "away_states": away_states,
                }
                self._pending_presence_gate = None
                return await self.async_step_init()

        schema = self._options_presence_states_schema(
            options,
            present_defaults or (options or ["home"]),
            away_defaults,
        )
        return self.async_show_form(
            step_id="options_presence_states",
            data_schema=schema,
            errors=errors,
        )

    def _options_presence_states_schema(
        self,
        options: List[str],
        present_defaults: List[str],
        away_defaults: List[str],
    ) -> vol.Schema:
        select_options = [SelectOptionDict(value=o, label=o) for o in options] if options else []
        return vol.Schema({
            vol.Required("present_states", default=present_defaults): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("away_states", default=away_defaults): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

    async def async_step_options_sensors(self, user_input: Optional[Dict[str, Any]] = None):
        """Alias step for clearer top-level label in Options menu."""
        return await self.async_step_options_telemetry(user_input)

    async def async_step_options_telemetry(self, user_input: Optional[Dict[str, Any]] = None):
        """Manage telemetry sensors in post-configuration options."""
        telemetry = list(self._section("telemetry", []))
        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action == "add":
                return await self.async_step_options_telemetry_add()
            if action == "manage":
                return await self.async_step_options_telemetry_manage()

        options = [SelectOptionDict(value="add", label="Add sensor")]
        if telemetry:
            options.append(SelectOptionDict(value="manage", label="Edit or delete sensor"))
        options.append(SelectOptionDict(value="done", label="Done"))
        schema = vol.Schema({
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_telemetry",
            data_schema=schema,
            description_placeholders={"telemetry_summary": _render_existing_telemetry(telemetry)},
        )

    async def async_step_options_telemetry_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a telemetry sensor from post-configuration options."""
        telemetry = list(self._section("telemetry", []))
        errors: Dict[str, str] = {}

        if user_input is not None:
            entity_id = _sanitize_optional_entity_id(user_input.get("entity_id"))
            if not entity_id:
                errors["entity_id"] = "required"
            elif any(item.get("entity_id") == entity_id for item in telemetry):
                errors["entity_id"] = "duplicate_entity"
            else:
                entry = {
                    "entity_id": entity_id,
                    "sensor_type": user_input.get("sensor_type", SENSOR_TYPES[0]["value"]),
                    "friendly_name": user_input.get("friendly_name", ""),
                    "level": user_input.get("level", LEVELS[0]["value"]),
                    "room": user_input.get("room", ""),
                }
                telemetry.append(entry)
                self._options["telemetry"] = telemetry
                self._sync_slope_after_telemetry_add(entry)
                return await self.async_step_options_telemetry()

        default_room, default_level = _suggest_room_and_level(
            self.hass,
            _sanitize_optional_entity_id(user_input.get("entity_id")) if user_input else None,
        )
        room_options = [SelectOptionDict(value=o, label=o) for o in COMMON_ROOMS]
        level_default = default_level or LEVELS[0]["value"]
        schema = vol.Schema({
            vol.Required("entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Required("sensor_type", default=SENSOR_TYPES[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in SENSOR_TYPES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("friendly_name", default=""): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required("level", default=level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=default_room): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=False,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="options_telemetry_add",
            data_schema=schema,
            errors=errors,
            description_placeholders={"telemetry_summary": _render_existing_telemetry(telemetry)},
        )

    async def async_step_options_telemetry_manage(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose a telemetry sensor to edit or delete."""
        telemetry = list(self._section("telemetry", []))
        if not telemetry:
            return await self.async_step_options_telemetry()

        errors: Dict[str, str] = {}
        if user_input is not None:
            selection = user_input.get("selection")
            action = user_input.get("action")
            try:
                idx = int(selection)
            except (TypeError, ValueError):
                idx = -1
            if not (0 <= idx < len(telemetry)):
                errors["selection"] = "required"
            elif action == "delete":
                removed = telemetry.pop(idx)
                self._options["telemetry"] = telemetry
                removed_entity_id = _sanitize_optional_entity_id(removed.get("entity_id"))
                if removed_entity_id:
                    self._purge_deleted_telemetry_associations(removed_entity_id, telemetry)
                return await self.async_step_options_telemetry()
            elif action == "edit":
                self._pending_telemetry_index = idx
                return await self.async_step_options_telemetry_edit()
            else:
                errors["action"] = "required"

        options = _telemetry_options(telemetry)
        schema = vol.Schema({
            vol.Required("selection", default=str(self._pending_telemetry_index or 0)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("action", default="edit"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="edit", label="Edit"),
                        SelectOptionDict(value="delete", label="Delete"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        return self.async_show_form(
            step_id="options_telemetry_manage",
            data_schema=schema,
            errors=errors,
            description_placeholders={"telemetry_summary": _render_existing_telemetry(telemetry)},
        )

    async def async_step_options_telemetry_edit(self, user_input: Optional[Dict[str, Any]] = None):
        telemetry = list(self._section("telemetry", []))
        if not telemetry:
            return await self.async_step_options_telemetry()

        idx = self._pending_telemetry_index if self._pending_telemetry_index is not None else 0
        idx = max(0, min(idx, len(telemetry) - 1))
        current = telemetry[idx]

        if user_input is not None:
            telemetry[idx] = {
                **current,
                "entity_id": _sanitize_optional_entity_id(user_input.get("entity_id")) or _sanitize_optional_entity_id(current.get("entity_id")),
                "friendly_name": user_input.get("friendly_name", current.get("friendly_name", "")),
                "level": user_input.get("level", current.get("level")),
                "room": user_input.get("room", current.get("room")),
            }
            self._options["telemetry"] = telemetry
            return await self.async_step_options_telemetry()

        level_options = [SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS]
        entity_default = _sanitize_optional_entity_id(current.get("entity_id"))
        schema = vol.Schema({
            vol.Optional("entity_id", default=entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Optional("friendly_name", default=current.get("friendly_name", "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional("level", default=current.get("level")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=level_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=current.get("room", "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        })
        return self.async_show_form(
            step_id="options_telemetry_edit",
            data_schema=schema,
            description_placeholders={
                "sensor_position": str(idx + 1),
                "sensor_total": str(len(telemetry)),
                "selected_sensor": _telemetry_label(current),
            },
        )

    async def async_step_options_zones(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose a zone to edit."""
        zones = dict(self._section("zones", {}))
        zone_keys = [key for key in ("zone1", "zone2") if key in zones]

        if not zone_keys:
            schema = vol.Schema({vol.Optional("noop", default=True): selector.BooleanSelector()})
            return self.async_show_form(step_id="options_zones", data_schema=schema)

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action in zone_keys:
                self._pending_zone_key = action
                return await self.async_step_options_zone_edit()

        options = [SelectOptionDict(value=key, label=_zone_choice_label(key, zones.get(key, {}))) for key in zone_keys]
        options.append(SelectOptionDict(value="done", label="Done"))
        schema = vol.Schema({
            vol.Required("action", default=zone_keys[0]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_zones",
            data_schema=schema,
            description_placeholders={"configured_zones": _render_zones_summary(zones)},
        )

    async def async_step_options_zone_edit(self, user_input: Optional[Dict[str, Any]] = None):
        zones = dict(self._section("zones", {}))
        zone_key = self._pending_zone_key or ("zone1" if "zone1" in zones else "zone2")
        zone = zones.get(zone_key)
        if not zone:
            return await self.async_step_options_zones()

        selected_triggers = [
            trig for trig in (zone.get("triggers", []) or []) if trig in TRIGGER_DEFS
        ]

        if user_input is not None:
            selected_triggers = [
                trig for trig in (user_input.get("triggers", selected_triggers) or []) if trig in TRIGGER_DEFS
            ]
            previous_thresholds = dict(zone.get("thresholds", {}))
            thresholds: Dict[str, Any] = {}
            for trig in selected_triggers:
                field = f"threshold_{trig}"
                if field in user_input:
                    thresholds[trig] = user_input[field]
                elif trig in previous_thresholds:
                    thresholds[trig] = previous_thresholds[trig]
                else:
                    thresholds[trig] = TRIGGER_DEFS[trig]["default"]
            zones[zone_key] = {
                **zone,
                "enabled": user_input.get("enabled", zone.get("enabled", True)),
                "level": user_input.get("level", zone.get("level")),
                "rooms": user_input.get("rooms", zone.get("rooms", [])),
                "triggers": selected_triggers,
                "outputs": _sanitize_entity_ids(user_input.get("outputs", zone.get("outputs", []))),
                "output_level": _normalize_fan_level_choice(
                    user_input.get("output_level"),
                    zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                ),
                "boost_output_level": _normalize_fan_level_choice(
                    user_input.get("boost_output_level"),
                    zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                ),
                "ui_label": _sanitize_ui_label(
                    user_input.get("ui_label"),
                    zone.get("ui_label") or _default_zone_ui_label(zone_key),
                ),
                "thresholds": thresholds,
            }
            self._options["zones"] = zones
            return await self.async_step_options_zones()

        room_options = [SelectOptionDict(value=room, label=room) for room in _rooms_all(self._section("telemetry", []))]
        level_options = [SelectOptionDict(value=o["value"], label=o["label"]) for o in LEVELS]
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=zone.get("enabled", True)): selector.BooleanSelector(),
            vol.Optional("level", default=zone.get("level")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=level_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("rooms", default=zone.get("rooms", [])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("triggers", default=selected_triggers): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_zone_trigger_options(zone.get("level")),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=_sanitize_entity_ids(zone.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            vol.Optional(
                "output_level",
                default=_normalize_fan_level_choice(
                    zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "boost_output_level",
                default=_normalize_fan_level_choice(
                    zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("ui_label", default=zone.get("ui_label", _default_zone_ui_label(zone_key))): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        }
        for trig in selected_triggers:
            trig_def = TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            schema_fields[vol.Optional(f"threshold_{trig}", default=zone.get("thresholds", {}).get(trig, trig_def["default"]))] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=trig_def["min"],
                        max=trig_def["max"],
                        step=trig_def.get("step", 1),
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement=trig_def.get("unit", "%"),
                    )
                )
            )

        return self.async_show_form(
            step_id="options_zone_edit",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={"zone_label": "Zone 1" if zone_key == "zone1" else "Zone 2"},
        )

    async def async_step_options_humidifiers(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose a humidifier lane to edit."""
        humidifiers = dict(self._section("humidifiers", {}))
        levels = sorted(humidifiers.keys())
        if not levels:
            schema = vol.Schema({vol.Optional("noop", default=True): selector.BooleanSelector()})
            return self.async_show_form(
                step_id="options_humidifiers",
                data_schema=schema,
                description_placeholders={"configured_humidifiers": "No humidifier lanes are configured yet."},
            )

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action in levels:
                self._pending_humidifier_level = action
                return await self.async_step_options_humidifier_edit()

        options = [SelectOptionDict(value=level, label=_level_choice_label(level)) for level in levels]
        options.append(SelectOptionDict(value="done", label="Done"))
        schema = vol.Schema({
            vol.Required("action", default=levels[0]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_humidifiers",
            data_schema=schema,
            description_placeholders={"configured_humidifiers": _render_humidifiers_summary(humidifiers)},
        )

    async def async_step_options_humidifier_edit(self, user_input: Optional[Dict[str, Any]] = None):
        humidifiers = dict(self._section("humidifiers", {}))
        level = self._pending_humidifier_level or (sorted(humidifiers.keys())[0] if humidifiers else None)
        if not level or level not in humidifiers:
            return await self.async_step_options_humidifiers()
        cfg = humidifiers[level]

        if user_input is not None:
            humidifiers[level] = {
                **cfg,
                "enabled": user_input.get("enabled", cfg.get("enabled", True)),
                "band_adjust": user_input.get("band_adjust", cfg.get("band_adjust", 0)),
                "outputs": _sanitize_entity_ids(user_input.get("outputs", cfg.get("outputs", []))),
            }
            self._options["humidifiers"] = humidifiers
            return await self.async_step_options_humidifiers()

        schema = vol.Schema({
            vol.Optional("enabled", default=cfg.get("enabled", True)): selector.BooleanSelector(),
            vol.Optional("band_adjust", default=cfg.get("band_adjust", 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=HUMIDIFIER_BAND_MIN,
                    max=HUMIDIFIER_BAND_MAX,
                    step=HUMIDIFIER_BAND_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="%",
                )
            ),
            vol.Optional("outputs", default=_sanitize_entity_ids(cfg.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["humidifier", "fan", "switch"], multiple=True)
            ),
        })
        return self.async_show_form(
            step_id="options_humidifier_edit",
            data_schema=schema,
            description_placeholders={"level_label": _level_choice_label(level)},
        )

    async def async_step_options_aq(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose an AQ lane to edit."""
        aq = dict(self._section("aq", {}))
        levels = sorted(aq.keys())
        if not levels:
            schema = vol.Schema({vol.Optional("noop", default=True): selector.BooleanSelector()})
            return self.async_show_form(
                step_id="options_aq",
                data_schema=schema,
                description_placeholders={"configured_aq": "No AQ lanes are configured yet."},
            )

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action in levels:
                self._pending_aq_level = action
                return await self.async_step_options_aq_edit()

        options = [SelectOptionDict(value=level, label=_level_choice_label(level)) for level in levels]
        options.append(SelectOptionDict(value="done", label="Done"))
        schema = vol.Schema({
            vol.Required("action", default=levels[0]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_aq",
            data_schema=schema,
            description_placeholders={"configured_aq": _render_aq_summary(aq)},
        )

    async def async_step_options_aq_edit(self, user_input: Optional[Dict[str, Any]] = None):
        aq = dict(self._section("aq", {}))
        level = self._pending_aq_level or (sorted(aq.keys())[0] if aq else None)
        if not level or level not in aq:
            return await self.async_step_options_aq()
        cfg = aq[level]

        if user_input is not None:
            selected_triggers = user_input.get("triggers", cfg.get("triggers", [])) or []
            thresholds = dict(cfg.get("thresholds", {}))
            for trig in selected_triggers:
                field = f"threshold_{trig}"
                if field in user_input:
                    thresholds[trig] = user_input[field]
            aq[level] = {
                **cfg,
                "enabled": user_input.get("enabled", cfg.get("enabled", False)),
                "triggers": selected_triggers,
                "outputs": _sanitize_entity_ids(user_input.get("outputs", cfg.get("outputs", []))),
                "run_duration": user_input.get("run_duration", cfg.get("run_duration", 30)),
                "output_level": _normalize_fan_level_choice(
                    user_input.get("output_level"),
                    cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                ),
                "thresholds": thresholds,
            }
            self._options["aq"] = aq
            return await self.async_step_options_aq()

        selected_triggers = cfg.get("triggers", []) or []
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=cfg.get("enabled", False)): selector.BooleanSelector(),
            vol.Optional("triggers", default=selected_triggers): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_aq_trigger_options(level),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=_sanitize_entity_ids(cfg.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "air_purifier", "switch"], multiple=True)
            ),
            vol.Optional("run_duration", default=cfg.get("run_duration", 30)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=AQ_DURATION_MIN,
                    max=AQ_DURATION_MAX,
                    step=AQ_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional(
                "output_level",
                default=_normalize_fan_level_choice(
                    cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        for trig in selected_triggers:
            trig_def = AQ_TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            schema_fields[vol.Optional(f"threshold_{trig}", default=cfg.get("thresholds", {}).get(trig, trig_def["default"]))] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=trig_def["min"],
                        max=trig_def["max"],
                        step=trig_def.get("step", 1),
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement=trig_def.get("unit"),
                    )
                )
            )
        return self.async_show_form(
            step_id="options_aq_edit",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={"level_label": _level_choice_label(level)},
        )

    async def async_step_options_alerts(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose an alert to edit."""
        alerts = list(self._section("alerts", []))
        if not alerts:
            schema = vol.Schema({vol.Optional("noop", default=True): selector.BooleanSelector()})
            return self.async_show_form(step_id="options_alerts", data_schema=schema)

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            try:
                idx = int(action)
            except (TypeError, ValueError):
                idx = 0
            if 0 <= idx < len(alerts):
                self._pending_alert_index = idx
                return await self.async_step_options_alert_edit()

        options = [
            SelectOptionDict(value=str(idx), label=_alert_option_label(idx, alert))
            for idx, alert in enumerate(alerts)
        ]
        options.append(SelectOptionDict(value="done", label="Done"))
        schema = vol.Schema({
            vol.Required("action", default="0"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_alerts",
            data_schema=schema,
            description_placeholders={"configured_alerts": _render_alerts_summary(alerts)},
        )

    async def async_step_options_alert_edit(self, user_input: Optional[Dict[str, Any]] = None):
        alerts = list(self._section("alerts", []))
        if not alerts:
            return await self.async_step_options_alerts()

        idx = self._pending_alert_index if self._pending_alert_index is not None else 0
        idx = max(0, min(idx, len(alerts) - 1))
        alert = alerts[idx]
        trigger_type = alert.get("trigger_type")
        threshold_min, threshold_max, threshold_default, threshold_unit = _alert_threshold_bounds(trigger_type)
        default_threshold = _safe_alert_threshold(
            trigger_type,
            alert.get("threshold", threshold_default),
        )

        if user_input is not None:
            selected_trigger_type = user_input.get("trigger_type", alert.get("trigger_type"))
            alerts[idx] = {
                **alert,
                "enabled": user_input.get("enabled", alert.get("enabled", True)),
                "trigger_type": selected_trigger_type,
                "custom_trigger": _sanitize_optional_entity_id(
                    user_input.get("custom_trigger", alert.get("custom_trigger"))
                ),
                "threshold": _safe_alert_threshold(
                    selected_trigger_type,
                    user_input.get("threshold", alert.get("threshold")),
                ),
                "lights": _sanitize_entity_ids(user_input.get("lights", alert.get("lights", []))),
                "outputs": _sanitize_entity_ids(user_input.get("outputs", alert.get("outputs", []))),
                "power_entity": _sanitize_optional_entity_id(
                    user_input.get("power_entity", alert.get("power_entity"))
                ),
                "flash_mode": user_input.get("flash_mode", alert.get("flash_mode")),
                "duration": user_input.get("duration", alert.get("duration", 10)),
            }
            self._options["alerts"] = alerts
            return await self.async_step_options_alerts()

        custom_trigger_default = _sanitize_optional_entity_id(alert.get("custom_trigger"))
        power_entity_default = _sanitize_optional_entity_id(alert.get("power_entity"))
        schema = vol.Schema({
            vol.Optional("enabled", default=alert.get("enabled", True)): selector.BooleanSelector(),
            vol.Optional("trigger_type", default=alert.get("trigger_type")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=k, label=v["label"]) for k, v in ALERT_TRIGGER_DEFS.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            _optional_entity_selector_key("custom_trigger", custom_trigger_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=False)
            ),
            vol.Optional("threshold", default=default_threshold): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=threshold_min,
                    max=threshold_max,
                    step=1,
                    unit_of_measurement=threshold_unit,
                )
            ),
            vol.Optional("lights", default=_sanitize_entity_ids(alert.get("lights", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional("outputs", default=_sanitize_entity_ids(alert.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
            _optional_entity_selector_key("power_entity", power_entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=False)
            ),
            vol.Optional("flash_mode", default=alert.get("flash_mode")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in ALERT_FLASH_MODES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("duration", default=alert.get("duration", 10)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ALERT_DURATION_MIN,
                    max=ALERT_DURATION_MAX,
                    step=ALERT_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
        })
        return self.async_show_form(
            step_id="options_alert_edit",
            data_schema=schema,
            description_placeholders={"alert_label": _alert_option_label(idx, alert)},
        )

    async def async_step_options_slope(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit temperature slope configuration from post-setup options."""
        telemetry = list(self._section("telemetry", []))
        temp_entities = [
            item.get("entity_id")
            for item in telemetry
            if item.get("sensor_type") == "temperature" and item.get("entity_id")
        ]
        slope = dict(self._section("slope", {}))
        default_mode = slope.get("mode", SLOPE_MODE_CALCULATED if temp_entities else SLOPE_MODE_NONE)
        default_sources = _sanitize_entity_ids(slope.get("source_entities", temp_entities))
        default_provided = _sanitize_entity_ids(slope.get("provided_sensors", []))

        errors: Dict[str, str] = {}
        if user_input is not None:
            mode = user_input.get("slope_mode", default_mode)
            slope_sources = _sanitize_entity_ids(user_input.get("slope_sources", []))
            provided_sensors = _sanitize_entity_ids(user_input.get("slope_sensors", []))

            if mode == SLOPE_MODE_CALCULATED and not slope_sources:
                errors["slope_sources"] = "required"
            if mode == SLOPE_MODE_PROVIDED and not provided_sensors:
                errors["slope_sensors"] = "required"

            if not errors:
                slope_data: Dict[str, Any] = {"mode": mode, "source_entities": []}
                if mode == SLOPE_MODE_CALCULATED:
                    slope_data["source_entities"] = slope_sources
                elif mode == SLOPE_MODE_PROVIDED:
                    slope_data["source_entities"] = slope_sources or temp_entities
                    slope_data["provided_sensors"] = provided_sensors
                self._options["slope"] = slope_data
                return await self.async_step_init()

        schema = vol.Schema({
            vol.Required("slope_mode", default=default_mode): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=SLOPE_MODE_CALCULATED, label="HI calculates slope"),
                        SelectOptionDict(value=SLOPE_MODE_PROVIDED, label="Provide my own slope sensors"),
                        SelectOptionDict(value=SLOPE_MODE_NONE, label="Skip slope"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("slope_sources", default=default_sources): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional("slope_sensors", default=default_provided): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
        })
        return self.async_show_form(
            step_id="options_slope",
            data_schema=schema,
            errors=errors,
            description_placeholders={"configured_slope": _render_slope_summary(slope)},
        )

    async def async_step_options_done(self, user_input: Optional[Dict[str, Any]] = None):
        return self.async_create_entry(title="", data=self._options)


def _presence_state_options(hass: HomeAssistant, entities: List[str]) -> List[str]:
    values = set()
    for entity_id in entities or []:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        values.add(state.state)
    return sorted(values)


async def _render_dependency_status(hass: HomeAssistant) -> str:
    lines: List[str] = []
    resources = hass.data.get("lovelace_resources") or {}
    custom_components_path = Path(hass.config.path("custom_components"))

    for dep in DEPENDENCIES:
        status = "Unknown (verify manually)"
        url = dep["url"]
        resource = dep.get("resource")
        if resource and any(resource in str(v) for v in resources.values()):
            status = "Installed"
        else:
            path = custom_components_path / dep["domain"]
            if path.exists():
                status = "Detected"
        lines.append(f"- {dep['name']} ({status}) - {url}")

    return "\n".join(lines)


def _entry_section(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Resolve a config section from options first, then entry data."""
    if entry.options and key in entry.options:
        return entry.options.get(key, default)
    return entry.data.get(key, default)


def _sanitize_optional_entity_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def _sanitize_entity_ids(values: Any) -> List[str]:
    if not values:
        return []
    raw = values if isinstance(values, list) else [values]
    result: List[str] = []
    seen = set()
    for item in raw:
        entity_id = _sanitize_optional_entity_id(item)
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        result.append(entity_id)
    return result


def _sanitize_state_values(values: Any) -> List[str]:
    if not values:
        return []
    raw = values if isinstance(values, list) else [values]
    out: List[str] = []
    seen = set()
    for item in raw:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _merge_unique_values(*groups: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged


def _alert_threshold_bounds(trigger_type: Any) -> Tuple[float, float, float, Optional[str]]:
    key = str(trigger_type or "")
    bounds = ALERT_THRESHOLD_BOUNDS.get(key)
    if not bounds:
        return 0.0, 100.0, 0.0, None
    return (
        float(bounds.get("min", 0.0)),
        float(bounds.get("max", 100.0)),
        float(bounds.get("default", 0.0)),
        bounds.get("unit"),
    )


def _safe_alert_threshold(trigger_type: Any, value: Any) -> Any:
    min_value, max_value, default_value, _ = _alert_threshold_bounds(trigger_type)
    parsed = None
    if value not in (None, ""):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
    if parsed is None:
        parsed = default_value
    parsed = max(min_value, min(max_value, parsed))
    if abs(parsed - round(parsed)) < 1e-9:
        return int(round(parsed))
    return round(parsed, 2)


def _optional_entity_selector_key(field_name: str, default_value: Any) -> Any:
    entity_id = _sanitize_optional_entity_id(default_value)
    if entity_id is None:
        return vol.Optional(field_name)
    return vol.Optional(field_name, default=entity_id)


def _render_alerts_summary(alerts: List[Dict[str, Any]]) -> str:
    """Human-readable summary of configured alerts for config flow pages."""
    if not alerts:
        return "None configured yet."
    lines: List[str] = []
    for idx, alert in enumerate(alerts, start=1):
        trigger = alert.get("trigger_type", "unknown")
        trigger_def = ALERT_TRIGGER_DEFS.get(trigger, {})
        trigger_label = trigger_def.get("label", trigger.replace("_", " ").title())
        threshold = alert.get("threshold")
        suffix = ""
        if threshold not in (None, ""):
            suffix = f" @ {threshold}"
        lines.append(f"- Alert {idx}: {trigger_label}{suffix}")
    return "\n".join(lines)


def _render_slope_summary(slope: Dict[str, Any]) -> str:
    """Human-readable summary of slope configuration for options flow pages."""
    if not slope:
        return "No slope configuration set."
    mode = slope.get("mode", SLOPE_MODE_NONE)
    if mode == SLOPE_MODE_CALCULATED:
        sources = _sanitize_entity_ids(slope.get("source_entities", []))
        return f"Mode: HI calculates slope. Source sensors: {len(sources)}."
    if mode == SLOPE_MODE_PROVIDED:
        provided = _sanitize_entity_ids(slope.get("provided_sensors", []))
        sources = _sanitize_entity_ids(slope.get("source_entities", []))
        return (
            f"Mode: Provided slope sensors. "
            f"Provided sensors: {len(provided)}. Source temperature sensors: {len(sources)}."
        )
    return "Mode: Slope disabled."


def _render_zones_summary(zones: Dict[str, Dict[str, Any]]) -> str:
    """Human-readable summary of zone output levels for config flow pages."""
    if not zones:
        return "No zones configured yet."
    lines: List[str] = []
    for zone_key in ("zone1", "zone2"):
        zone = zones.get(zone_key)
        if not zone:
            continue
        enabled = "on" if zone.get("enabled") else "off"
        level = zone.get("level") or "unset"
        normal_level = _fan_level_label(zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT))
        boost_level = _fan_level_label(zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT))
        ui_label = _sanitize_ui_label(zone.get("ui_label"), _default_zone_ui_label(zone_key))
        lines.append(
            f"- {zone_key.upper()}: {enabled}, {level}, label '{ui_label}', normal {normal_level}, boost {boost_level}"
        )
    return "\n".join(lines) if lines else "No zones configured yet."


def _render_humidifiers_summary(humidifiers: Dict[str, Dict[str, Any]]) -> str:
    if not humidifiers:
        return "No humidifier lanes are configured yet."
    lines: List[str] = []
    for level in sorted(humidifiers.keys()):
        cfg = humidifiers.get(level, {})
        enabled = "on" if cfg.get("enabled") else "off"
        outputs = _sanitize_entity_ids(cfg.get("outputs", []))
        output_summary = ", ".join(outputs) if outputs else "no outputs"
        band_adjust = cfg.get("band_adjust", 0)
        lines.append(
            f"- {_level_choice_label(level)}: {enabled}, band adjust {band_adjust}%, outputs: {output_summary}"
        )
    return "\n".join(lines)


def _render_aq_summary(aq: Dict[str, Dict[str, Any]]) -> str:
    if not aq:
        return "No AQ lanes are configured yet."
    lines: List[str] = []
    for level in sorted(aq.keys()):
        cfg = aq.get(level, {})
        enabled = "on" if cfg.get("enabled") else "off"
        triggers = cfg.get("triggers", []) or []
        trigger_summary = ", ".join(triggers) if triggers else "no triggers"
        outputs = _sanitize_entity_ids(cfg.get("outputs", []))
        output_summary = ", ".join(outputs) if outputs else "no outputs"
        level_txt = _fan_level_label(cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT))
        run_duration = cfg.get("run_duration", 30)
        lines.append(
            f"- {_level_choice_label(level)}: {enabled}, triggers [{trigger_summary}], outputs [{output_summary}], level {level_txt}, run {run_duration} min"
        )
    return "\n".join(lines)


def _render_existing_telemetry(telemetry: List[Dict[str, Any]]) -> str:
    if not telemetry:
        return "None yet."
    lines = []
    for item in telemetry:
        room = item.get("room") or "Unknown room"
        display = item.get("friendly_name") or room
        stype = item.get("sensor_type")
        ent = item.get("entity_id")
        lines.append(f"- {display}: {stype} ({ent})")
    return "\n".join(lines)


def _telemetry_options(telemetry: List[Dict[str, Any]]) -> List[SelectOptionDict]:
    options: List[SelectOptionDict] = []
    for idx, item in enumerate(telemetry):
        options.append(SelectOptionDict(value=str(idx), label=_telemetry_label(item)))
    return options


def _telemetry_label(item: Dict[str, Any]) -> str:
    room = item.get("room") or "Unknown room"
    display = item.get("friendly_name") or room
    stype = str(item.get("sensor_type") or "sensor").replace("_", " ").title()
    ent = item.get("entity_id") or "unknown"
    return f"{display} ({stype}) - {ent}"


def _zone_choice_label(zone_key: str, zone: Dict[str, Any]) -> str:
    title = "Zone 1" if zone_key == "zone1" else "Zone 2"
    level = _level_choice_label(zone.get("level"))
    enabled = "Enabled" if zone.get("enabled") else "Disabled"
    ui_label = _sanitize_ui_label(zone.get("ui_label"), _default_zone_ui_label(zone_key))
    return f"{title} - {enabled} ({level}, UI label: {ui_label})"


def _level_choice_label(level: Optional[str]) -> str:
    if level == "level1":
        return "Level 1 (Downstairs)"
    if level == "level2":
        return "Level 2 (Upstairs)"
    if level:
        return str(level)
    return "Unassigned level"


def _alert_option_label(idx: int, alert: Dict[str, Any]) -> str:
    trigger = str(alert.get("trigger_type") or "unknown")
    trigger_label = ALERT_TRIGGER_DEFS.get(trigger, {}).get("label", trigger.replace("_", " ").title())
    enabled = "Enabled" if alert.get("enabled", True) else "Disabled"
    return f"Alert {idx + 1} - {trigger_label} ({enabled})"


def _suggest_room_and_level(hass: HomeAssistant, entity_id: str | None = None) -> tuple[str, str]:
    if not entity_id:
        return "", ""
    entity_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    entry = entity_reg.async_get(entity_id)
    if not entry or not entry.area_id:
        return "", ""
    area = area_reg.async_get(entry.area_id)
    if not area:
        return "", ""
    room = area.name
    level = ""
    name_lower = room.lower()
    if "upstairs" in name_lower or "level 2" in name_lower or "second" in name_lower:
        level = "level2"
    elif "downstairs" in name_lower or "level 1" in name_lower or "ground" in name_lower:
        level = "level1"
    return room, level


def _rooms_by_level(telemetry: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    rooms: Dict[str, List[str]] = {lvl["value"]: [] for lvl in LEVELS}
    for entry in telemetry:
        level = entry.get("level")
        room = entry.get("room")
        if level and room:
            if room not in rooms.setdefault(level, []):
                rooms[level].append(room)
    return rooms


def _rooms_all(telemetry: List[Dict[str, Any]]) -> List[str]:
    rooms: List[str] = []
    seen = set()
    for entry in telemetry:
        room = entry.get("room")
        if not room:
            continue
        key = room.lower()
        if key in seen:
            continue
        seen.add(key)
        rooms.append(room)
    return rooms


def _configured_levels(telemetry: List[Dict[str, Any]]) -> List[str]:
    levels = sorted({entry.get("level") for entry in telemetry if entry.get("level")})
    return levels


def _levels_with_aq(telemetry: List[Dict[str, Any]]) -> List[str]:
    aq_types = {"co2", "voc", "iaq", "pm25", "co"}
    levels = set()
    for entry in telemetry:
        if entry.get("sensor_type") in aq_types:
            levels.add(entry.get("level"))
    return sorted(levels)


def _zone_trigger_options(level: str) -> List[SelectOptionDict]:
    opts = []
    for key, trig in TRIGGER_DEFS.items():
        label = f"{trig['label']} ({level})"
        opts.append(SelectOptionDict(value=key, label=label))
    return opts


def _aq_trigger_options(level: str) -> List[SelectOptionDict]:
    opts = []
    for key, trig in AQ_TRIGGER_DEFS.items():
        label = f"{trig['label']} ({level})"
        opts.append(SelectOptionDict(value=key, label=label))
    return opts


def _fan_output_level_options() -> List[SelectOptionDict]:
    options = [SelectOptionDict(value=FAN_OUTPUT_LEVEL_AUTO, label="Auto")]
    for step in FAN_OUTPUT_LEVEL_STEPS:
        options.append(SelectOptionDict(value=str(step), label=f"{step}%"))
    return options


def _normalize_fan_level_choice(value: Any, fallback: Any) -> str:
    raw = value if value is not None else fallback
    if raw is None:
        return str(ZONE_OUTPUT_LEVEL_DEFAULT)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text == FAN_OUTPUT_LEVEL_AUTO:
            return FAN_OUTPUT_LEVEL_AUTO
        if text.endswith("%"):
            text = text[:-1]
        try:
            raw = int(float(text))
        except (TypeError, ValueError):
            raw = None
    if raw is None:
        return str(ZONE_OUTPUT_LEVEL_DEFAULT)
    try:
        numeric = int(raw)
    except (TypeError, ValueError):
        return str(ZONE_OUTPUT_LEVEL_DEFAULT)
    nearest = min(FAN_OUTPUT_LEVEL_STEPS, key=lambda step: abs(step - numeric))
    return str(nearest)


def _fan_level_label(value: Any) -> str:
    normalized = _normalize_fan_level_choice(value, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        return "Auto"
    return f"{normalized}%"


def _default_zone_ui_label(zone_key: str) -> str:
    if zone_key == "zone1":
        return "Cooking"
    if zone_key == "zone2":
        return "Bathroom"
    return "Zone"


def _sanitize_ui_label(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return fallback
    return text[:40]


def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return HumidityIntelligenceOptionsFlow(config_entry)
