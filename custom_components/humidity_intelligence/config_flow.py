"""Config flow for the Humidity Intelligence integration."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from uuid import uuid4
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
try:
    from homeassistant.data_entry_flow import Optional as _FlowOptional
except ImportError:
    _FlowOptional = None
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from .adaptive_output.options import OutputObservationOptionsMixin
from .helpers.air_quality import AQ_CANONICAL_UNITS, AQ_TRIGGER_SPECS, _finite_float
from .helpers.voc_index import provider_identity, same_provider
from .helpers.slope_mapping import bindings_for_save
from .helpers.frontend_dependencies import async_render_dependency_status
from .helpers.level_labels import (
    level_label as resolve_level_label,
    level_label_config_from_form,
    level_label_field_values,
    resolve_level_label_details,
    resolve_level_labels,
)
from .helpers.setup_assist import advisory_text as setup_assist_advisory_text
from .helpers.setup_assist import setup_assist_suggestion
from .helpers.zone_validation import detect_zone_mapping_duplicates, summarize_zone_mapping_duplicates
from .const import (
    DOMAIN,
    DEFAULT_TIME_END,
    DEFAULT_TIME_START,
    ENGINE_INTERVAL_MAX,
    ENGINE_INTERVAL_MIN,
    ENGINE_INTERVAL_MINUTES_DEFAULT,
    ENGINE_INTERVAL_STEP,
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
    ROOM_SCOPED_ALERT_TRIGGERS,
    ALERT_THRESHOLD_BOUNDS,
    CONF_AUTO_REFRESH_UI_ON_STARTUP,
    DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
    CONF_ALERT_HANDLING_ENABLED,
    DEFAULT_ALERT_HANDLING_ENABLED,
    CONF_SHOW_TEMPERATURE_CHIPS,
    DEFAULT_SHOW_TEMPERATURE_CHIPS,
    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
    DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS,
    CONF_LEVEL_LABELS,
    CONF_LEVEL1_LABEL,
    CONF_LEVEL2_LABEL,
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
    TARGET_PROFILE_OPTIONS,
    TARGET_CUSTOM_LOW_MIN,
    TARGET_CUSTOM_LOW_MAX,
    TARGET_CUSTOM_HIGH_MIN,
    TARGET_CUSTOM_HIGH_MAX,
    TARGET_CUSTOM_STEP,
    TEMPERATURE_COMFORT_PROFILE_OPTIONS,
    TEMPERATURE_COMFORT_CUSTOM_LOW_MIN,
    TEMPERATURE_COMFORT_CUSTOM_LOW_MAX,
    TEMPERATURE_COMFORT_CUSTOM_HIGH_MIN,
    TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX,
    TEMPERATURE_COMFORT_CUSTOM_STEP,
    DEFAULT_TEMPERATURE_COMFORT_MODE,
    DEFAULT_TEMPERATURE_COMFORT_CUSTOM_LOW,
    DEFAULT_TEMPERATURE_COMFORT_CUSTOM_HIGH,
)

_LOGGER = logging.getLogger(__name__)

ADVANCED_OPTIONS_FIELD = "show_advanced_options"
ADVANCED_DEFAULTS_NOTE = (
    "Humidity Intelligence applies recommended defaults unless you customise these settings."
)
FORM_ACTION_SAVE = "save"
FORM_ACTION_PREVIEW = "preview"
FORM_ACTION_CANCEL = "cancel"
FORM_ACTION_RETURN = "return"
FORM_ACTION_CLOSE = "close"
CONFIGURATION_WALKTHROUGH_URL = (
    "https://github.com/senyo888/humidity-intelligence/wiki/Configuration-Walkthrough"
)


def _advanced_section(fields: Dict[Any, Any]) -> Any:
    return section(vol.Schema(fields), {"collapsed": True})


def _gate_optional(field: str, *, default: Any) -> Any:
    """Use conditional markers only with their matching schema implementation."""
    if _FlowOptional is not None and issubclass(_FlowOptional, vol.Optional):
        gate = "enable_presence_gate" if field == "presence_entities" else "enable_time_gate"
        return _FlowOptional(field, default=default, visible={"field": gate, "value": True})
    return vol.Optional(field, default=default)


def _dependency_schema(default_skip: bool = False) -> vol.Schema:
    return vol.Schema({
        vol.Optional("skip", default=default_skip): selector.BooleanSelector()
    })


def _presence_gate_for_entities(previous: Dict[str, Any], entities: Any, enabled: bool) -> Dict[str, Any]:
    """Stage selected entities without transferring another identity's mapping."""
    entities = _sanitize_entity_ids(entities)
    gate = {**previous, "enabled": enabled, "entities": entities}
    if set(entities) != set(_sanitize_entity_ids(previous.get("entities", []))):
        gate.pop("present_states", None)
        gate.pop("away_states", None)
    return gate


def _presence_states_schema(
    options: List[str], values: Optional[Dict[str, Any]] = None, *, require_review: bool = False,
) -> vol.Schema:
    """Build presence selectors with staged or submitted ``values`` as defaults.

    A new entity selection requires an explicit mapping; observed states are
    choices, not evidence that those states mean present. Explicit empty
    selections and submitted error-form values are kept."""
    select_options = [SelectOptionDict(value=o, label=o) for o in options] if options else []
    present = (
        vol.Required("present_states") if require_review and "present_states" not in (values or {})
        else vol.Required("present_states", default=_form_input_default(values, "present_states", options or ["home"]))
    )
    return vol.Schema({
        present: selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=select_options,
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional("away_states", default=_form_input_default(values, "away_states", [])): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=select_options,
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    })


def _flatten_advanced_section_input(user_input: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(user_input, dict):
        return user_input
    advanced_values = user_input.get(ADVANCED_OPTIONS_FIELD)
    if not isinstance(advanced_values, dict):
        return user_input
    flattened = dict(user_input)
    flattened.pop(ADVANCED_OPTIONS_FIELD, None)
    flattened.update(advanced_values)
    return flattened


def _form_input_default(user_input: Optional[Dict[str, Any]], field: str, default: Any) -> Any:
    if isinstance(user_input, dict):
        return user_input.get(field, default)
    return default


def _value_label_options(items: List[Dict[str, Any]]) -> List[SelectOptionDict]:
    return [SelectOptionDict(value=item["value"], label=item["label"]) for item in items]


def _save_cancel_options(save_label: str) -> List[SelectOptionDict]:
    return [
        SelectOptionDict(value=FORM_ACTION_SAVE, label=save_label),
        SelectOptionDict(value=FORM_ACTION_CANCEL, label="Cancel"),
    ]


def _save_preview_cancel_options(save_label: str) -> List[SelectOptionDict]:
    return [
        SelectOptionDict(value=FORM_ACTION_SAVE, label=save_label),
        SelectOptionDict(value=FORM_ACTION_PREVIEW, label="Preview HA suggestion"),
        SelectOptionDict(value=FORM_ACTION_CANCEL, label="Cancel"),
    ]


def _cancel_confirm_options(return_label: str) -> List[SelectOptionDict]:
    return [
        SelectOptionDict(value=FORM_ACTION_RETURN, label=return_label),
        SelectOptionDict(value=FORM_ACTION_CLOSE, label="Close without saving"),
    ]


def _level_label_schema(config: Optional[Dict[str, Any]] = None) -> vol.Schema:
    defaults = level_label_field_values(config or {})
    return vol.Schema({
        vol.Optional(
            CONF_LEVEL1_LABEL,
            default=defaults["level1"],
        ): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Optional(
            CONF_LEVEL2_LABEL,
            default=defaults["level2"],
        ): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
    })


def _configured_zone_items(zones: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    configured: List[Tuple[str, Dict[str, Any]]] = []
    for zone_key in ("zone1", "zone2"):
        zone = zones.get(zone_key)
        if not isinstance(zone, dict) or not zone:
            continue
        if not any(key in zone for key in ("enabled", "level", "rooms", "triggers", "outputs", "ui_label")):
            continue
        configured.append((zone_key, dict(zone)))
    return configured


ADD_SENSOR_TYPES = []
for sensor_type in SENSOR_TYPES:
    ADD_SENSOR_TYPES.append(sensor_type)
    if sensor_type["value"] == "voc":
        ADD_SENSOR_TYPES.append({"value": "voc_index", "label": "VOC index (display only)"})


class VocIndexEditor:
    """Manage opt-in display sources independently of control telemetry."""

    _index_key: str | None = None
    _index_defaults: dict | None = None

    def _index_context(self):
        raise NotImplementedError

    def _uses_index_provider(self, entity_id: str) -> bool:
        """Exclude the same provider from control telemetry, including a verified rename."""
        rows = self._index_context()[0].get("voc_index_sources", [])
        if any(row.get("entity_id") == entity_id for row in rows):
            return True
        if not any("provider_identity" in row for row in rows):
            return False
        from homeassistant.helpers import entity_registry as er

        provider = er.async_get(self.hass).async_get(entity_id)
        return any(same_provider(row, provider) for row in rows)

    async def async_step_voc_index(self, user_input=None):
        config, _, back = self._index_context()
        rows = config.get("voc_index_sources", [])
        if user_input:
            choice = user_input["source"]
            if choice == "done":
                return await back()
            if choice == "add" or any(row["source_key"] == choice for row in rows):
                self._index_key = None if choice == "add" else choice
                self._index_defaults = None
                return await self.async_step_voc_index_edit()
        choices = [{"value": row["source_key"], "label": row["label"]} for row in rows]
        choices.extend([{"value": "add", "label": "Add a source"}, {"value": "done", "label": "Back to sensors"}])
        return self.async_show_form(step_id="voc_index", data_schema=vol.Schema({
            vol.Required("source"): selector.SelectSelector(selector.SelectSelectorConfig(options=choices)),
        }))

    async def async_step_voc_index_edit(self, user_input=None):
        config, target, _ = self._index_context()
        rows = list(config.get("voc_index_sources", []))
        current = next((row for row in rows if row["source_key"] == self._index_key), None)
        if self._index_key and current is None:
            return await self.async_step_voc_index()
        errors = {}
        if user_input:
            action = user_input.get("action", "save")
            if action == "cancel":
                return await self.async_step_voc_index()
            others = [row for row in rows if row is not current]
            if action == "delete" and current:
                target["voc_index_sources"] = others
                return await self.async_step_voc_index()
            entity_id = _sanitize_optional_entity_id(user_input.get("entity_id"))
            label = str(user_input.get("label") or "").strip()
            if not entity_id or not re.fullmatch(r"sensor\.[a-z0-9_]+", entity_id):
                errors["entity_id"] = "required"
            elif any(row.get("entity_id") == entity_id for row in [*config.get("telemetry", []), *others]):
                errors["entity_id"] = "duplicate_entity"
            else:
                from homeassistant.helpers import entity_registry as er
                provider = er.async_get(self.hass).async_get(entity_id)
                if provider and provider.platform == DOMAIN:
                    errors["entity_id"] = "voc_index_provider"
                elif any(same_provider(row, provider) for row in others):
                    errors["entity_id"] = "duplicate_entity"
            if not label or len(label) > 80 or not label.isprintable():
                errors["label"] = "voc_index_label"
            elif any(row["label"].casefold() == label.casefold() for row in others):
                errors["label"] = "voc_index_label"
            if not errors:
                if current and (current["entity_id"] == entity_id or same_provider(current, provider)):
                    # A label-only edit never adopts another provider reusing the old ID.
                    record = {**current, "entity_id": entity_id, "label": label}
                else:
                    key = str(uuid4())
                    record = {"source_key": key, "entity_id": entity_id, "label": label}
                    if proof := provider_identity(key, provider):
                        record["provider_identity"] = proof
                if current:
                    rows[rows.index(current)] = record
                else:
                    rows.append(record)
                target["voc_index_sources"] = rows
                return await self.async_step_voc_index()

        defaults = user_input or current or self._index_defaults or {}
        actions = ["save", "delete", "cancel"] if current else ["save", "cancel"]
        return self.async_show_form(step_id="voc_index_edit", errors=errors, data_schema=vol.Schema({
            _optional_entity_selector_key("entity_id", defaults.get("entity_id")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)),
            vol.Optional("label", default=defaults.get("label", "")): str,
            vol.Required("action", default="save"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[{"value": a, "label": a.title()} for a in actions])),
        }))


class HumidityIntelligenceConfigFlow(VocIndexEditor, config_entries.ConfigFlow, domain=DOMAIN):
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
        self._cancel_return_step = "telemetry"

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Entry point for the flow. Present the first-run welcome guidance."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_welcome()

    async def async_step_welcome(self, user_input: Optional[Dict[str, Any]] = None):
        """Introduce the first-run configuration flow."""
        if user_input is not None:
            return await self.async_step_gates()

        return self.async_show_form(
            step_id="welcome",
            data_schema=vol.Schema({}),
            description_placeholders={
                "walkthrough_url": CONFIGURATION_WALKTHROUGH_URL,
            },
        )

    async def async_step_gates(self, user_input: Optional[Dict[str, Any]] = None):
        """Collect global time and presence gate settings.

        Reuse staged defaults on revisits and preserve omitted Advanced settings.
        Stage submissions, then open presence-state selection when enabled with
        entities, or continue to telemetry otherwise."""
        if user_input is not None:
            user_input = dict(_flatten_advanced_section_input(user_input))

            # A collapsed Advanced section can be absent from a native submission.
            # Keep previously staged values while allowing explicit replacements.
            for field in (
                "engine_interval_minutes", CONF_AUTO_REFRESH_UI_ON_STARTUP,
                CONF_SHOW_OUTPUT_ENTITY_DETAILS, "custom_target_low", "custom_target_high",
                "temperature_comfort_custom_low", "temperature_comfort_custom_high",
            ):
                if field not in user_input and field in self._data:
                    user_input[field] = self._data[field]

            target_profile = _normalize_target_profile(user_input.get("target_profile", "auto"))
            custom_low = _bounded_float(
                user_input.get("custom_target_low"),
                TARGET_CUSTOM_LOW_MIN,
                TARGET_CUSTOM_LOW_MAX,
                45.0,
            )
            custom_high = _bounded_float(
                user_input.get("custom_target_high"),
                TARGET_CUSTOM_HIGH_MIN,
                TARGET_CUSTOM_HIGH_MAX,
                55.0,
            )
            if custom_high <= custom_low:
                custom_high = min(float(TARGET_CUSTOM_HIGH_MAX), custom_low + 1.0)
            temp_comfort_low = _bounded_float(
                user_input.get("temperature_comfort_custom_low"),
                TEMPERATURE_COMFORT_CUSTOM_LOW_MIN,
                TEMPERATURE_COMFORT_CUSTOM_LOW_MAX,
                DEFAULT_TEMPERATURE_COMFORT_CUSTOM_LOW,
            )
            temp_comfort_high = _bounded_float(
                user_input.get("temperature_comfort_custom_high"),
                TEMPERATURE_COMFORT_CUSTOM_HIGH_MIN,
                TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX,
                DEFAULT_TEMPERATURE_COMFORT_CUSTOM_HIGH,
            )
            if temp_comfort_high <= temp_comfort_low:
                temp_comfort_high = min(float(TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX), temp_comfort_low + 0.5)

            self._data["time_gate"] = {
                "enabled": user_input.get("enable_time_gate", False),
                "start": user_input.get("start_time", self._data.get("time_gate", {}).get("start", DEFAULT_TIME_START)),
                "end": user_input.get("end_time", self._data.get("time_gate", {}).get("end", DEFAULT_TIME_END)),
                "outside_action": user_input.get("outside_action", self._data.get("time_gate", {}).get("outside_action", OUTSIDE_WINDOW_ACTIONS[0]["value"])),
            }
            self._data["engine_interval_minutes"] = user_input.get(
                "engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT
            )
            self._data["alert_only_mode"] = user_input.get("alert_only_mode", False)
            self._data[CONF_AUTO_REFRESH_UI_ON_STARTUP] = user_input.get(
                CONF_AUTO_REFRESH_UI_ON_STARTUP,
                DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
            )
            self._data[CONF_SHOW_OUTPUT_ENTITY_DETAILS] = bool(
                user_input.get(
                    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                    DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS,
                )
            )
            self._data["target_profile"] = target_profile
            self._data["custom_target_low"] = custom_low
            self._data["custom_target_high"] = custom_high
            self._data["temperature_comfort_mode"] = _normalize_temperature_comfort_mode(
                user_input.get("temperature_comfort_mode", DEFAULT_TEMPERATURE_COMFORT_MODE)
            )
            self._data["temperature_comfort_custom_low"] = temp_comfort_low
            self._data["temperature_comfort_custom_high"] = temp_comfort_high
            presence_enabled = user_input.get("enable_presence_gate", False)
            previous_presence = self._data.get("presence_gate", {})
            entities = user_input.get("presence_entities", previous_presence.get("entities", []))
            self._data["presence_gate"] = _presence_gate_for_entities(previous_presence, entities, presence_enabled)
            if presence_enabled and entities:
                return await self.async_step_presence_states()
            return await self.async_step_telemetry()

        time_gate = self._data.get("time_gate", {})
        presence_gate = self._data.get("presence_gate", {})
        gates_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enable_time_gate", default=gates_default("enable_time_gate", time_gate.get("enabled", False))): selector.BooleanSelector(),
            _gate_optional("start_time", default=gates_default("start_time", time_gate.get("start", DEFAULT_TIME_START))): selector.TimeSelector(),
            _gate_optional("end_time", default=gates_default("end_time", time_gate.get("end", DEFAULT_TIME_END))): selector.TimeSelector(),
            _gate_optional("outside_action", default=gates_default("outside_action", time_gate.get("outside_action", OUTSIDE_WINDOW_ACTIONS[0]["value"]))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(OUTSIDE_WINDOW_ACTIONS),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("alert_only_mode", default=gates_default("alert_only_mode", self._data.get("alert_only_mode", False))): selector.BooleanSelector(),
            vol.Optional("target_profile", default=gates_default("target_profile", self._data.get("target_profile", "auto"))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(TARGET_PROFILE_OPTIONS),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "temperature_comfort_mode",
                default=gates_default(
                    "temperature_comfort_mode",
                    self._data.get("temperature_comfort_mode", DEFAULT_TEMPERATURE_COMFORT_MODE),
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(TEMPERATURE_COMFORT_PROFILE_OPTIONS),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("enable_presence_gate", default=gates_default("enable_presence_gate", presence_gate.get("enabled", False))): selector.BooleanSelector(),
            _gate_optional("presence_entities", default=gates_default("presence_entities", presence_gate.get("entities", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("engine_interval_minutes", default=self._data.get("engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ENGINE_INTERVAL_MIN,
                    max=ENGINE_INTERVAL_MAX,
                    step=ENGINE_INTERVAL_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional(
                CONF_AUTO_REFRESH_UI_ON_STARTUP,
                default=self._data.get(
                    CONF_AUTO_REFRESH_UI_ON_STARTUP,
                    DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                default=self._data.get(
                    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                    DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS,
                ),
            ): selector.BooleanSelector(),
            vol.Optional("custom_target_low", default=self._data.get("custom_target_low", 45.0)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=TARGET_CUSTOM_LOW_MIN,
                    max=TARGET_CUSTOM_LOW_MAX,
                    step=TARGET_CUSTOM_STEP,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Optional("custom_target_high", default=self._data.get("custom_target_high", 55.0)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=TARGET_CUSTOM_HIGH_MIN,
                    max=TARGET_CUSTOM_HIGH_MAX,
                    step=TARGET_CUSTOM_STEP,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Optional(
                "temperature_comfort_custom_low",
                default=self._data.get("temperature_comfort_custom_low", DEFAULT_TEMPERATURE_COMFORT_CUSTOM_LOW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=TEMPERATURE_COMFORT_CUSTOM_LOW_MIN,
                    max=TEMPERATURE_COMFORT_CUSTOM_LOW_MAX,
                    step=TEMPERATURE_COMFORT_CUSTOM_STEP,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
            vol.Optional(
                "temperature_comfort_custom_high",
                default=self._data.get("temperature_comfort_custom_high", DEFAULT_TEMPERATURE_COMFORT_CUSTOM_HIGH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=TEMPERATURE_COMFORT_CUSTOM_HIGH_MIN,
                    max=TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX,
                    step=TEMPERATURE_COMFORT_CUSTOM_STEP,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
        })
        gates_schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="gates",
            data_schema=gates_schema,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_presence_states(self, user_input: Optional[Dict[str, Any]] = None):
        """Collect disjoint present and away states, retaining staged defaults.

        Redisplay overlapping selections with a field error without saving them;
        otherwise stage both selections and continue to telemetry."""
        options = _presence_state_options(self.hass, self._data.get("presence_gate", {}).get("entities", []))
        if user_input is not None:
            states = user_input.get("present_states", [])
            away_states = user_input.get("away_states", [])
            overlap = set(states).intersection(set(away_states))
            if overlap or "present_states" not in user_input:
                return self.async_show_form(
                    step_id="presence_states",
                    data_schema=_presence_states_schema(options, user_input, require_review=True),
                    errors={"away_states": "overlap"} if overlap else {"present_states": "required"},
                )
            self._data.setdefault("presence_gate", {})["present_states"] = states
            self._data.setdefault("presence_gate", {})["away_states"] = away_states
            return await self.async_step_telemetry()

        schema = _presence_states_schema(options, self._data.get("presence_gate", {}), require_review=True)
        return self.async_show_form(step_id="presence_states", data_schema=schema)

    def _index_context(self):
        return self._data, self._data, self.async_step_telemetry

    async def async_step_telemetry(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for telemetry sensors."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "voc_index":
                return await self.async_step_voc_index()
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
        options.append(SelectOptionDict(value="voc_index", label="VOC index (display only)"))
        if self._telemetry:
            options.append(SelectOptionDict(value="manage", label="Manage sensors"))
            options.append(SelectOptionDict(value="done", label="Continue to temperature change settings"))
        options.append(SelectOptionDict(value="back", label="Back to operating schedule and limits"))

        schema = vol.Schema({
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry",
            data_schema=schema,
            description_placeholders={
                "existing": _render_existing_telemetry(self._telemetry, self._data),
            },
        )

    async def async_step_telemetry_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a telemetry sensor entry."""
        errors: Dict[str, str] = {}
        preview_entity_id = _sanitize_optional_entity_id(user_input.get("entity_id")) if user_input else None
        preview_only = _is_setup_assist_preview_input(user_input)
        if user_input is not None:
            action = user_input.get("action", FORM_ACTION_SAVE)
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_cancel_confirm("telemetry_add", user_input)

            entity_id = _sanitize_optional_entity_id(user_input.get("entity_id"))
            if preview_only:
                pass
            elif user_input.get("sensor_type") == "voc_index":
                self._index_key = None
                self._index_defaults = {"entity_id": entity_id, "label": user_input.get("room", "")}
                return await self.async_step_voc_index_edit()
            elif not entity_id:
                errors["entity_id"] = "required"
            elif self._uses_index_provider(entity_id):
                errors["entity_id"] = "duplicate_entity"
            elif any(t.get("entity_id") == entity_id for t in self._telemetry):
                errors["entity_id"] = "duplicate_entity"
            else:
                area_name = _telemetry_display_value(user_input.get("room"), entity_id)
                entry = {
                    "entity_id": entity_id,
                    "sensor_type": user_input.get("sensor_type", SENSOR_TYPES[0]["value"]),
                    "friendly_name": area_name,
                    "level": user_input.get("level", LEVELS[0]["value"]),
                    "room": area_name,
                }
                self._telemetry.append(entry)
                self._data["telemetry"] = self._telemetry
                return await self.async_step_telemetry()

        default_room, default_level, assist_text = _setup_assist_defaults(
            self.hass,
            preview_entity_id,
        )
        room_options = _room_select_options(default_room)
        level_default = default_level or LEVELS[0]["value"]
        schema = vol.Schema({
            vol.Optional("action", default=FORM_ACTION_SAVE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_save_preview_cancel_options("Keep sensor changes"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            _optional_entity_selector_key("entity_id", preview_entity_id): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Optional("sensor_type", default=SENSOR_TYPES[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(ADD_SENSOR_TYPES),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("level", default=level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_level_value_label_options(self._data),
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
                "existing": _render_existing_telemetry(self._telemetry, self._data),
                "setup_assist": assist_text,
            },
        )

    async def async_step_telemetry_done(self, user_input: Optional[Dict[str, Any]] = None):
        """Finish telemetry selection and move to slope configuration."""
        if not self._telemetry:
            return await self.async_step_telemetry_add()
        return await self.async_step_slope()

    async def async_step_telemetry_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_gates()

    async def _async_show_cancel_confirm(
        self, return_step: str = "telemetry", user_input: Optional[Dict[str, Any]] = None
    ):
        self._cancel_return_step = return_step
        self._cancel_return_input = deepcopy(user_input or {})
        self._cancel_return_input.pop("action", None)
        return await self.async_step_cancel_confirm()

    async def async_step_cancel_confirm(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm closing a setup flow that has unsaved progress."""
        if user_input is not None:
            action = user_input.get("action", FORM_ACTION_RETURN)
            if action == FORM_ACTION_CLOSE:
                return self.async_abort(reason="user_cancelled")
            # Only redisplay known forms; never dispatch to a saving step.
            destinations = {
                "telemetry": self.async_step_telemetry,
                "telemetry_add": self.async_step_telemetry_add,
                "telemetry_manage": self.async_step_telemetry_manage,
                "telemetry_edit": self.async_step_telemetry_edit,
            }
            handler = destinations.get(self._cancel_return_step, self.async_step_telemetry)
            result = await handler()
            draft = getattr(self, "_cancel_return_input", {})
            if draft and result.get("step_id") == self._cancel_return_step:
                result["data_schema"] = self.add_suggested_values_to_schema(
                    result["data_schema"], draft
                )
            return result

        schema = vol.Schema({
            vol.Required("action", default=FORM_ACTION_RETURN): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_cancel_confirm_options("Keep editing"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(step_id="cancel_confirm", data_schema=schema)

    async def async_step_telemetry_manage(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit or delete an existing telemetry entry."""
        if not self._telemetry:
            return await self.async_step_telemetry_add()

        errors: Dict[str, str] = {}
        if user_input is not None:
            selection = user_input.get("selection")
            action = user_input.get("action")
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_cancel_confirm("telemetry_manage", user_input)
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
                        SelectOptionDict(value=FORM_ACTION_CANCEL, label="Cancel"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(
            step_id="telemetry_manage",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "existing": _render_existing_telemetry(self._telemetry, self._data),
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
            action = user_input.get("action", FORM_ACTION_SAVE)
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_cancel_confirm("telemetry_edit", user_input)

            entity_id = _sanitize_optional_entity_id(user_input.get("entity_id"))
            if not entity_id:
                errors["entity_id"] = "required"
            elif self._uses_index_provider(entity_id) or any(
                i != index and t.get("entity_id") == entity_id for i, t in enumerate(self._telemetry)
            ):
                errors["entity_id"] = "duplicate_entity"
            else:
                area_name = _telemetry_display_value(
                    user_input.get("room", current.get("room", "")),
                    entity_id,
                )
                current.update({
                    "entity_id": entity_id,
                    "sensor_type": user_input.get("sensor_type", current.get("sensor_type", SENSOR_TYPES[0]["value"])),
                    "friendly_name": area_name,
                    "level": user_input.get("level", current.get("level", LEVELS[0]["value"])),
                    "room": area_name,
                })
                self._telemetry[index] = current
                self._data["telemetry"] = self._telemetry
                return await self.async_step_telemetry()

        _room, _level, assist_text = _setup_assist_defaults(
            self.hass,
            _sanitize_optional_entity_id(current.get("entity_id")),
        )
        room_options = _room_select_options(current.get("room") or _room)
        schema = vol.Schema({
            vol.Optional("action", default=FORM_ACTION_SAVE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_save_cancel_options("Keep sensor changes"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional("entity_id", default=current.get("entity_id")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Optional("sensor_type", default=current.get("sensor_type")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(SENSOR_TYPES),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("level", default=current.get("level")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_level_value_label_options(self._data),
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
            description_placeholders={
                "setup_assist": assist_text,
            },
        )

    async def async_step_slope(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure temperature slope sensors."""
        temp_entities = [t["entity_id"] for t in self._telemetry if t["sensor_type"] == "temperature"]
        if not temp_entities:
            self._data["slope"] = {
                "mode": SLOPE_MODE_NONE,
                "source_entities": [],
                CONF_SHOW_TEMPERATURE_CHIPS: DEFAULT_SHOW_TEMPERATURE_CHIPS,
            }
            return await self.async_step_zones()

        errors: Dict[str, str] = {}
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            mode = user_input["slope_mode"]
            slope_sources = _sanitize_entity_ids(user_input.get("slope_sources") or temp_entities)
            provided_sensors = user_input.get("slope_sensors", [])
            show_temperature_chips = bool(
                user_input.get(
                    CONF_SHOW_TEMPERATURE_CHIPS,
                    DEFAULT_SHOW_TEMPERATURE_CHIPS,
                )
            )
            if mode == SLOPE_MODE_CALCULATED and not slope_sources:
                errors["slope_sources"] = "required"
            if mode == SLOPE_MODE_PROVIDED and not provided_sensors:
                errors["slope_sensors"] = "required"
            bindings = {}
            if mode == SLOPE_MODE_PROVIDED and provided_sensors:
                bindings = bindings_for_save(self.hass, slope_sources or temp_entities, provided_sensors,
                                             self._telemetry, self._data.get("slope", {}).get("bindings"))
                if len(bindings) != len(set(slope_sources or temp_entities)):
                    errors["slope_sensors"] = "ambiguous_slope_mapping"
            if not errors:
                slope_data: Dict[str, Any] = {
                    "mode": mode,
                    "source_entities": [],
                    CONF_SHOW_TEMPERATURE_CHIPS: show_temperature_chips,
                }
                if mode == SLOPE_MODE_CALCULATED:
                    slope_data["source_entities"] = slope_sources
                elif mode == SLOPE_MODE_PROVIDED:
                    slope_data["source_entities"] = slope_sources or temp_entities
                    slope_data["provided_sensors"] = provided_sensors
                    slope_data["bindings"] = bindings
                self._data["slope"] = slope_data
                return await self.async_step_zones()

        slope_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Required("slope_mode", default=slope_default("slope_mode", SLOPE_MODE_CALCULATED)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=SLOPE_MODE_CALCULATED, label="HI calculates slope"),
                        SelectOptionDict(value=SLOPE_MODE_PROVIDED, label="Provide my own slope sensors"),
                        SelectOptionDict(value=SLOPE_MODE_NONE, label="Skip slope"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("slope_sources", default=slope_default("slope_sources", temp_entities)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional("slope_sensors", default=slope_default("slope_sensors", [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(
                CONF_SHOW_TEMPERATURE_CHIPS,
                default=slope_default(CONF_SHOW_TEMPERATURE_CHIPS, DEFAULT_SHOW_TEMPERATURE_CHIPS),
            ): selector.BooleanSelector(),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="slope",
            data_schema=schema,
            errors=errors,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_zones(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for zone configuration."""
        zone_summary = _render_zones_summary(self._zones, self._data)
        return self.async_show_menu(
            step_id="zones",
            menu_options=[
                "level_labels",
                "zone1",
                "zone2",
                "zones_done",
                "zones_back",
            ],
            description_placeholders={"configured_zones": zone_summary},
        )

    async def async_step_level_labels(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit display-only Level 1 / Level 2 labels before zone mapping."""
        if user_input is not None:
            self._data[CONF_LEVEL_LABELS] = level_label_config_from_form(
                user_input,
                self._data,
            )
            return await self.async_step_zones()

        return self.async_show_form(
            step_id="level_labels",
            data_schema=_level_label_schema(self._data),
        )

    async def async_step_zone1(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_zone_config("zone1", user_input)

    async def async_step_zone2(self, user_input: Optional[Dict[str, Any]] = None):
        return await self._async_step_zone_config("zone2", user_input)

    async def _async_step_zone_config(self, zone_key: str, user_input: Optional[Dict[str, Any]] = None):
        """Configure a single zone."""
        existing = self._zones.get(zone_key, {})
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            enabled = user_input.get("enabled", False)
            zone = {
                "enabled": enabled,
                "level": user_input.get("level") or existing.get("level") or _default_zone_level(zone_key),
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
            boost_warning = _boost_level_warning(zone.get("output_level"), zone.get("boost_output_level"))
            if boost_warning:
                _LOGGER.warning("HI %s boost guidance: %s", zone_key, boost_warning)
            duplicates = detect_zone_mapping_duplicates(self._telemetry, self._zones)
            if duplicates:
                _LOGGER.warning(
                    "Zone mapping duplicates detected during setup for %s: %s",
                    zone_key,
                    summarize_zone_mapping_duplicates(duplicates),
                )
            if enabled and zone["triggers"]:
                self._pending_zone_key = zone_key
                return await self.async_step_zone_thresholds()
            return await self.async_step_zones()

        rooms_all = _rooms_all(self._telemetry)
        level_default = existing.get("level") or _default_zone_level(zone_key)
        room_options = [SelectOptionDict(value=r, label=r) for r in rooms_all]
        zone_default = lambda field, default: _form_input_default(user_input, field, default)
        selected_level_default = zone_default("level", level_default)
        trigger_options = _zone_trigger_options(selected_level_default, zone_key, self._data)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=zone_default("enabled", existing.get("enabled", False))): selector.BooleanSelector(),
            vol.Optional("level", default=selected_level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_level_value_label_options(self._data),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("rooms", default=zone_default("rooms", existing.get("rooms", []))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("triggers", default=zone_default("triggers", existing.get("triggers", []))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=zone_default("outputs", existing.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional(
                "output_level",
                default=_normalize_fan_level_choice(
                    zone_default("output_level", existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT)),
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
                    zone_default("boost_output_level", existing.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT)),
                    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("ui_label", default=zone_default("ui_label", existing.get("ui_label", _default_zone_ui_label(zone_key)))): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id=zone_key,
            data_schema=schema,
            description_placeholders={
                "boost_guidance": _boost_guidance_for_zone(existing),
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
            },
        )

    async def async_step_zone_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure zone thresholds for the selected triggers."""
        zone_key = self._pending_zone_key
        if not zone_key:
            return await self.async_step_zones()

        zone = self._zones.get(zone_key, {})
        triggers = zone.get("triggers", [])
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            thresholds = {}
            for trig in triggers:
                trig_def = TRIGGER_DEFS.get(trig)
                if not trig_def:
                    continue
                thresholds[trig] = user_input.get(
                    trig,
                    zone.get("thresholds", {}).get(trig, trig_def["default"]),
                )
            zone["thresholds"] = thresholds
            self._zones[zone_key] = zone
            self._data["zones"] = self._zones
            self._pending_zone_key = None
            return await self.async_step_zones()

        advanced_fields: Dict[Any, Any] = {}
        for trig in triggers:
            trig_def = TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            default = zone.get("thresholds", {}).get(trig, trig_def["default"])
            advanced_fields[vol.Optional(trig, default=default)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=trig_def["min"],
                    max=trig_def["max"],
                    step=trig_def.get("step", 1),
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement=trig_def.get("unit", "%"),
                )
            )
        schema = vol.Schema({
            vol.Optional(ADVANCED_OPTIONS_FIELD): _advanced_section(advanced_fields),
        })
        return self.async_show_form(
            step_id="zone_thresholds",
            data_schema=schema,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

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
            user_input = _flatten_advanced_section_input(user_input)

            self._humidifiers[level] = {
                "enabled": user_input.get("enabled", False),
                "band_adjust": user_input.get("band_adjust", 0),
                "outputs": user_input.get("outputs", []),
            }
            self._data["humidifiers"] = self._humidifiers
            return await self.async_step_humidifiers()

        target_low = f"sensor.hi_{level}_humidity_target_low"
        target_high = f"sensor.hi_{level}_humidity_target_high"
        humidifier_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=humidifier_default("enabled", existing.get("enabled", False))): selector.BooleanSelector(),
            vol.Optional("outputs", default=humidifier_default("outputs", existing.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["humidifier", "fan", "switch"], multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("band_adjust", default=humidifier_default("band_adjust", existing.get("band_adjust", 0))): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=HUMIDIFIER_BAND_MIN,
                    max=HUMIDIFIER_BAND_MAX,
                    step=HUMIDIFIER_BAND_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="%",
                )
            ),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id=f"humidifier_{level}",
            data_schema=schema,
            description_placeholders={
                "target_low": target_low,
                "target_high": target_high,
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
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
            user_input = _flatten_advanced_section_input(user_input)

            self._aq[level] = {
                "enabled": user_input.get("enabled", False),
                "triggers": user_input.get("triggers", []),
                "outputs": user_input.get("outputs", []),
                "run_duration": user_input.get("run_duration", existing.get("run_duration", 30)),
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

        trigger_options = _aq_trigger_options(level, self._data)
        step_key = f"aq_{level}"
        aq_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=aq_default("enabled", existing.get("enabled", False))): selector.BooleanSelector(),
            vol.Optional("triggers", default=aq_default("triggers", existing.get("triggers", []))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=trigger_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=aq_default("outputs", existing.get("outputs", []))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "air_purifier", "switch"], multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("run_duration", default=aq_default("run_duration", existing.get("run_duration", 30))):
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
                    aq_default("output_level", existing.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT)),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            ),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id=f"aq_{level}",
            data_schema=schema,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_aq_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        level = self._pending_aq_level
        if not level:
            return await self.async_step_aq()

        aq = self._aq.get(level, {})
        triggers = aq.get("triggers", [])
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            thresholds = {}
            for trig in triggers:
                trig_def = AQ_TRIGGER_DEFS.get(trig)
                if not trig_def:
                    continue
                thresholds[trig] = user_input.get(
                    trig,
                    aq.get("thresholds", {}).get(trig, trig_def["default"]),
                )
            aq["thresholds"] = thresholds
            self._aq[level] = aq
            self._data["aq"] = self._aq
            self._pending_aq_level = None
            return await self.async_step_aq()

        advanced_fields: Dict[Any, Any] = {}
        for trig in triggers:
            trig_def = AQ_TRIGGER_DEFS.get(trig)
            if not trig_def:
                continue
            default = aq.get("thresholds", {}).get(trig, trig_def["default"])
            advanced_fields[vol.Optional(trig, default=default)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=trig_def["min"],
                    max=trig_def["max"],
                    step=trig_def.get("step", 1),
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement=trig_def.get("unit"),
                )
            )
        schema = vol.Schema({
            vol.Optional(ADVANCED_OPTIONS_FIELD): _advanced_section(advanced_fields),
        })
        return self.async_show_form(
            step_id="aq_thresholds",
            data_schema=schema,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_aq_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_alerts()

    async def async_step_aq_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_humidifiers()

    async def async_step_alerts(self, user_input: Optional[Dict[str, Any]] = None):
        """Menu for alert/emergency automations."""
        alert_summary = _render_alerts_summary(self._alerts)
        menu_options = ["alert_settings"]
        if len(self._alerts) < MAX_ALERTS:
            menu_options.append("alert_add")
        if self._alerts:
            menu_options.append("alert_remove")
        menu_options.extend([
            "alerts_done",
            "alerts_back",
        ])
        return self.async_show_menu(
            step_id="alerts",
            menu_options=menu_options,
            description_placeholders={"configured_alerts": alert_summary},
        )

    async def async_step_alert_settings(self, user_input: Optional[Dict[str, Any]] = None):
        """Configure internal alert handling behavior."""
        if user_input is not None:
            self._data[CONF_ALERT_HANDLING_ENABLED] = bool(
                user_input.get(
                    CONF_ALERT_HANDLING_ENABLED,
                    self._data.get(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED),
                )
            )
            return await self.async_step_alerts()

        schema = vol.Schema({
            vol.Optional(
                CONF_ALERT_HANDLING_ENABLED,
                default=self._data.get(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED),
            ): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="alert_settings", data_schema=schema)

    async def async_step_alert_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a visual indicator rule for an internally calculated alert."""
        errors: Dict[str, str] = {}
        telemetry = list(self._telemetry)

        trigger_default = _default_alert_trigger_type()
        enabled_default = True
        room_default = ""
        lights_default: List[str] = []
        power_entity_default: Optional[str] = None
        flash_mode_default = _default_alert_flash_mode()
        duration_default = 10
        threshold_default_value: Any = _alert_threshold_value(
            trigger_default,
            None,
            self._data,
        )

        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            enabled_default = bool(user_input.get("enabled", True))
            trigger_default = _normalize_alert_trigger_type(user_input.get("trigger_type"))
            room_default = _sanitize_optional_room_scope(user_input.get("room")) or ""
            lights_default = _sanitize_entity_ids(user_input.get("lights", []))
            power_entity_default = _sanitize_optional_entity_id(user_input.get("power_entity"))
            flash_mode_default = _normalize_alert_flash_mode(user_input.get("flash_mode"))
            duration_default = _safe_alert_duration(user_input.get("duration", 10))
            threshold_default_value = _alert_threshold_value(
                trigger_default,
                user_input.get("threshold"),
                self._data,
            )

            try:
                alert, room_error = _alert_rule_payload_from_form_input(
                    telemetry=telemetry,
                    user_input=user_input,
                    config=self._data,
                )
                if room_error:
                    errors["room"] = room_error

                if not errors and alert is not None:
                    self._alerts.append(alert)
                    self._data["alerts"] = self._alerts
                    return await self.async_step_alerts()
            except Exception:
                _LOGGER.exception("Failed to add alert during initial config flow")
                errors["base"] = "alert_save_failed"

        alert_default = lambda field, default: _form_input_default(user_input, field, default)
        trigger_default = _normalize_alert_trigger_type(alert_default("trigger_type", trigger_default))
        enabled_default = bool(alert_default("enabled", enabled_default))
        room_default = _sanitize_optional_room_scope(alert_default("room", room_default)) or ""
        lights_default = _sanitize_entity_ids(alert_default("lights", lights_default))
        power_entity_default = _sanitize_optional_entity_id(alert_default("power_entity", power_entity_default))
        flash_mode_default = _normalize_alert_flash_mode(alert_default("flash_mode", flash_mode_default))
        duration_default = _safe_alert_duration(alert_default("duration", duration_default))
        threshold_default_value = _alert_threshold_value(
            trigger_default,
            alert_default("threshold", threshold_default_value),
            self._data,
        )
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=enabled_default): selector.BooleanSelector(),
            vol.Required("trigger_type", default=trigger_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_trigger_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=room_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_room_options(telemetry),
                    multiple=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("lights", default=lights_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
        }
        advanced_fields: Dict[Any, Any] = {}
        if _alert_uses_static_threshold(trigger_default):
            threshold_min, threshold_max, _, threshold_unit = _alert_threshold_bounds(trigger_default)
            advanced_fields[vol.Optional("threshold", default=threshold_default_value)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=threshold_min,
                    max=threshold_max,
                    step=1,
                    unit_of_measurement=threshold_unit,
                )
            )
        advanced_fields.update({
            _optional_entity_selector_key("power_entity", power_entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=False)
            ),
            vol.Optional("flash_mode", default=flash_mode_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_value_label_options(ALERT_FLASH_MODES),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("duration", default=duration_default): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ALERT_DURATION_MIN,
                    max=ALERT_DURATION_MAX,
                    step=ALERT_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
        })
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section(advanced_fields)
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="alert_add",
            data_schema=schema,
            errors=errors,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_alert_remove(self, user_input: Optional[Dict[str, Any]] = None):
        """Remove a visual indicator rule during initial setup."""
        if not self._alerts:
            return await self.async_step_alerts()

        if user_input is not None:
            remove_alert = str(user_input.get("remove_alert", "cancel"))
            if remove_alert != "cancel":
                try:
                    idx = int(remove_alert)
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(self._alerts):
                    self._alerts.pop(idx)
                    self._data["alerts"] = self._alerts
            return await self.async_step_alerts()

        options = [
            SelectOptionDict(value=str(idx), label=_alert_option_label(idx, alert))
            for idx, alert in enumerate(self._alerts)
        ]
        options.append(SelectOptionDict(value="cancel", label="Cancel"))
        schema = vol.Schema({
            vol.Required("remove_alert", default="0"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="alert_remove",
            data_schema=schema,
            description_placeholders={"configured_alerts": _render_alerts_summary(self._alerts)},
        )

    async def async_step_alerts_done(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_ui_install()

    async def async_step_alerts_back(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_aq()

    async def _async_create_entry(self):
        """Create the final config entry."""
        self._data["alerts"] = _sanitize_alert_rules(self._data.get("alerts", []))
        return super().async_create_entry(title="Humidity Intelligence", data=self._data)

    async def async_step_ui_install(self, user_input: Optional[Dict[str, Any]] = None):
        """Final step: choose UI layouts to export."""
        if user_input is not None:
            self._data["skip_dependencies"] = user_input.get("skip", False)
            self._data["ui_layouts"] = user_input.get("ui_layouts", [])
            return await self._async_create_entry()

        options = [
            SelectOptionDict(value="v2_mobile", label="V2 Mobile"),
            SelectOptionDict(value="v2_tablet", label="V2 Tablet"),
            SelectOptionDict(value="v1_mobile", label="V1 Mobile (deprecated - use V2 Mobile)"),
            SelectOptionDict(value="view_cards_button", label="View Cards Button"),
        ]
        schema = vol.Schema({
            vol.Optional("ui_layouts", default=["v2_tablet"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("skip", default=False): selector.BooleanSelector(),
        })
        return self.async_show_form(
            step_id="ui_install",
            data_schema=schema,
            description_placeholders={
                "dependencies": await async_render_dependency_status(self.hass, include_links=False),
                "configured_alerts": _render_alerts_summary(self._alerts),
                "walkthrough_url": CONFIGURATION_WALKTHROUGH_URL,
            },
        )


class _ProfileLimit(NamedTuple):
    key: str
    label: str
    minimum: float
    maximum: float
    default: float


class _OptionsProfile(NamedTuple):
    group: str
    mode_key: str
    modes: list
    unit: str
    step: float
    limits: tuple[_ProfileLimit, _ProfileLimit]
    range_error: str


_OPTIONS_PROFILES = (
    _OptionsProfile(
        "humidity_targets", "target_profile", TARGET_PROFILE_OPTIONS, "%", TARGET_CUSTOM_STEP,
        (_ProfileLimit("custom_target_low", "Humidity lower limit", TARGET_CUSTOM_LOW_MIN, TARGET_CUSTOM_LOW_MAX, 45),
         _ProfileLimit("custom_target_high", "Humidity upper limit", TARGET_CUSTOM_HIGH_MIN, TARGET_CUSTOM_HIGH_MAX, 55)),
        "humidity_range_invalid",
    ),
    _OptionsProfile(
        "temperature_comfort", "temperature_comfort_mode", TEMPERATURE_COMFORT_PROFILE_OPTIONS,
        "°C", TEMPERATURE_COMFORT_CUSTOM_STEP,
        (_ProfileLimit("temperature_comfort_custom_low", "Temperature lower limit", TEMPERATURE_COMFORT_CUSTOM_LOW_MIN,
                       TEMPERATURE_COMFORT_CUSTOM_LOW_MAX, DEFAULT_TEMPERATURE_COMFORT_CUSTOM_LOW),
         _ProfileLimit("temperature_comfort_custom_high", "Temperature upper limit", TEMPERATURE_COMFORT_CUSTOM_HIGH_MIN,
                       TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX, DEFAULT_TEMPERATURE_COMFORT_CUSTOM_HIGH)),
        "temperature_range_invalid",
    ),
)


class _AQThresholdReview(NamedTuple):
    level: str
    previous_lane: dict | None
    lane: dict
    triggers: list[str]


class HumidityIntelligenceOptionsFlow(VocIndexEditor, OutputObservationOptionsMixin, config_entries.OptionsFlow):
    """Options flow for Humidity Intelligence."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._options = dict(entry.options) if entry.options else {}
        self._pending_telemetry_index: Optional[int] = None
        self._pending_zone_key: Optional[str] = None
        self._pending_humidifier_level: Optional[str] = None
        self._pending_aq_level: Optional[str] = None
        self._aq_review: _AQThresholdReview | None = None
        self._pending_alert_index: Optional[int] = None
        self._pending_presence_gate: Optional[Dict[str, Any]] = None
        self._cancel_return_step = "options_telemetry"

    def _section(self, key: str, default: Any) -> Any:
        if key in self._options:
            return self._options.get(key, default)
        return _entry_section(self._entry, key, default)

    def _effective_config(self) -> Dict[str, Any]:
        config = dict(getattr(self._entry, "data", None) or {})
        config.update(dict(getattr(self._entry, "options", None) or {}))
        config.update(dict(self._options))
        return config

    async def _async_show_options_cancel_confirm(
        self, return_step: str = "options_telemetry", user_input: Optional[Dict[str, Any]] = None
    ):
        self._cancel_return_step = return_step
        self._cancel_return_input = deepcopy(user_input or {})
        self._cancel_return_input.pop("action", None)
        return await self.async_step_options_cancel_confirm()

    async def async_step_options_cancel_confirm(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm closing an options flow with unsaved changes."""
        if user_input is not None:
            action = user_input.get("action", FORM_ACTION_RETURN)
            if action == FORM_ACTION_CLOSE:
                return self.async_abort(reason="user_cancelled")
            # Only redisplay known forms; never dispatch to a saving step.
            destinations = {
                "options_telemetry": self.async_step_options_telemetry,
                "options_telemetry_add": self.async_step_options_telemetry_add,
                "options_telemetry_manage": self.async_step_options_telemetry_manage,
                "options_telemetry_edit": self.async_step_options_telemetry_edit,
            }
            handler = destinations.get(self._cancel_return_step, self.async_step_options_telemetry)
            result = await handler()
            draft = getattr(self, "_cancel_return_input", {})
            if draft and result.get("step_id") == self._cancel_return_step:
                result["data_schema"] = self.add_suggested_values_to_schema(
                    result["data_schema"], draft
                )
            return result

        schema = vol.Schema({
            vol.Required("action", default=FORM_ACTION_RETURN): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_cancel_confirm_options("Keep editing"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(step_id="options_cancel_confirm", data_schema=schema)

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
            slope = {
                "mode": SLOPE_MODE_NONE,
                "source_entities": [],
                CONF_SHOW_TEMPERATURE_CHIPS: bool(
                    slope.get(CONF_SHOW_TEMPERATURE_CHIPS, DEFAULT_SHOW_TEMPERATURE_CHIPS)
                ),
            }
        elif mode == SLOPE_MODE_PROVIDED and not provided_sensors:
            slope = {
                "mode": SLOPE_MODE_NONE,
                "source_entities": [],
                CONF_SHOW_TEMPERATURE_CHIPS: bool(
                    slope.get(CONF_SHOW_TEMPERATURE_CHIPS, DEFAULT_SHOW_TEMPERATURE_CHIPS)
                ),
            }
        else:
            slope["source_entities"] = source_entities
            if "bindings" in slope:
                bindings = slope["bindings"] if isinstance(slope["bindings"], dict) else {}
                slope["bindings"] = {source: sensor for source, sensor in bindings.items()
                                     if source in source_entities and sensor in provided_sensors}
            if mode == SLOPE_MODE_PROVIDED:
                slope["provided_sensors"] = provided_sensors
            elif "provided_sensors" in slope:
                slope.pop("provided_sensors", None)

        self._options["slope"] = slope

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        self._pending_aq_level = None
        self._aq_review = None
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "options_sensors",
                "options_gates",
                "options_thresholds",
                "options_zones",
                "options_humidifiers",
                "options_aq",
                "options_alerts",
                "options_slope",
                "options_output_observation",
                "options_dependencies",
                "options_done",
            ],
        )

    async def async_step_options_dependencies(self, user_input: Optional[Dict[str, Any]] = None):
        """Review optional frontend dependency status from post-configuration options."""
        if user_input is not None:
            self._options["skip_dependencies"] = user_input.get(
                "skip", self._section("skip_dependencies", False)
            )
            return await self.async_step_init()

        dep_lines = await _render_dependency_status(self.hass)
        return self.async_show_form(
            step_id="options_dependencies",
            data_schema=_dependency_schema(
                default_skip=bool(self._section("skip_dependencies", False))
            ),
            description_placeholders={
                "dependencies": dep_lines,
                "walkthrough_url": CONFIGURATION_WALKTHROUGH_URL,
            },
        )

    async def async_step_options_gates(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit global time/presence gates from post-configuration options."""
        time_gate = dict(self._section("time_gate", {}))
        presence_gate = dict(self._section("presence_gate", {}))

        default_presence_entities = _sanitize_entity_ids(presence_gate.get("entities", []))

        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            self._options["time_gate"] = {
                "enabled": user_input.get("enable_time_gate", False),
                "start": user_input.get("start_time", time_gate.get("start", DEFAULT_TIME_START)),
                "end": user_input.get("end_time", time_gate.get("end", DEFAULT_TIME_END)),
                "outside_action": user_input.get("outside_action", time_gate.get("outside_action", OUTSIDE_WINDOW_ACTIONS[0]["value"])),
            }
            self._options["alert_only_mode"] = user_input.get("alert_only_mode", self._section("alert_only_mode", False))
            self._options[CONF_AUTO_REFRESH_UI_ON_STARTUP] = user_input.get(
                CONF_AUTO_REFRESH_UI_ON_STARTUP,
                self._section(
                    CONF_AUTO_REFRESH_UI_ON_STARTUP,
                    DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
                ),
            )
            self._options[CONF_SHOW_OUTPUT_ENTITY_DETAILS] = bool(
                user_input.get(
                    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                    _entry_show_output_entity_details_default(self._entry),
                )
            )
            self._options["engine_interval_minutes"] = user_input.get(
                "engine_interval_minutes",
                self._section("engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT),
            )
            presence_enabled = user_input.get("enable_presence_gate", False)
            entities = _sanitize_entity_ids(user_input.get("presence_entities", default_presence_entities))
            pending_presence = _presence_gate_for_entities(presence_gate, entities, presence_enabled)

            if presence_enabled and entities:
                self._pending_presence_gate = pending_presence
                return await self.async_step_options_presence_states()

            self._options["presence_gate"] = pending_presence
            self._pending_presence_gate = None
            return await self.async_step_init()

        gates_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enable_time_gate", default=gates_default("enable_time_gate", time_gate.get("enabled", False))): selector.BooleanSelector(),
            _gate_optional("start_time", default=gates_default("start_time", time_gate.get("start") or DEFAULT_TIME_START)): selector.TimeSelector(),
            _gate_optional("end_time", default=gates_default("end_time", time_gate.get("end") or DEFAULT_TIME_END)): selector.TimeSelector(),
            _gate_optional(
                "outside_action",
                default=gates_default(
                    "outside_action",
                    time_gate.get("outside_action") or OUTSIDE_WINDOW_ACTIONS[0]["value"],
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in OUTSIDE_WINDOW_ACTIONS],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("alert_only_mode", default=gates_default("alert_only_mode", self._section("alert_only_mode", False))): selector.BooleanSelector(),
            vol.Optional("enable_presence_gate", default=gates_default("enable_presence_gate", presence_gate.get("enabled", False))): selector.BooleanSelector(),
            _gate_optional("presence_entities", default=gates_default("presence_entities", default_presence_entities)): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional(
                "engine_interval_minutes",
                default=gates_default(
                    "engine_interval_minutes",
                    self._section("engine_interval_minutes", ENGINE_INTERVAL_MINUTES_DEFAULT),
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ENGINE_INTERVAL_MIN,
                    max=ENGINE_INTERVAL_MAX,
                    step=ENGINE_INTERVAL_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional(
                CONF_AUTO_REFRESH_UI_ON_STARTUP,
                default=gates_default(
                    CONF_AUTO_REFRESH_UI_ON_STARTUP,
                    self._section(
                        CONF_AUTO_REFRESH_UI_ON_STARTUP,
                        DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
                    ),
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                default=gates_default(
                    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
                    _entry_show_output_entity_details_default(self._entry),
                ),
            ): selector.BooleanSelector(),
        })
        gates_schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="options_gates",
            data_schema=gates_schema,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

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
            if overlap or "present_states" not in user_input:
                errors = {"away_states": "overlap"} if overlap else {"present_states": "required"}
                present_defaults, away_defaults = present_states, away_states
                options = _merge_unique_values(options, present_states, away_states)
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
            (present_defaults if "present_states" in (user_input if user_input is not None else presence_gate) else None),
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
        present_defaults: Optional[List[str]],
        away_defaults: List[str],
    ) -> vol.Schema:
        select_options = [SelectOptionDict(value=o, label=o) for o in options] if options else []
        return vol.Schema({
            (vol.Required("present_states") if present_defaults is None else vol.Required("present_states", default=present_defaults)): selector.SelectSelector(
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

    async def async_step_options_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        """Stage edits to the two independent profile groups in one transaction."""
        config = self._effective_config()
        # Match the backend's legacy humidity lookup order without migrating an entry on visit.
        legacy_range = config.get("target_custom") or {}
        if not isinstance(legacy_range, dict):
            legacy_range = {}
        config["target_profile"] = config.get("target_profile") or config.get("target_profile_mode")
        for end in ("low", "high"):
            key = f"custom_target_{end}"
            config[key] = config.get(key) or config.get(f"target_custom_{end}") or legacy_range.get(end)

        fields = {}
        changes = {}
        errors = {}
        notes = []
        for profile in _OPTIONS_PROFILES:
            submitted = (user_input or {}).get(profile.group, {})
            mode = str(config.get(profile.mode_key) or "auto").strip().lower()
            choices = [item["value"] for item in profile.modes]
            if mode not in choices:
                mode = "auto"
            selected = submitted.get(profile.mode_key, mode)
            if selected != mode:
                changes[profile.mode_key] = selected
            group_fields = {
                vol.Optional(profile.mode_key, default=selected): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_value_label_options(profile.modes),
                                                  mode=selector.SelectSelectorMode.DROPDOWN)
                )
            }
            limits = []
            range_changed = False
            activating_custom = selected == "custom" and mode != "custom"
            for limit in profile.limits:
                raw = config.get(limit.key)
                saved = _finite_float(raw)
                effective = saved
                shown = saved
                if raw is None and mode != "custom":
                    shown = limit.default
                elif raw is not None and (saved is None or not limit.minimum <= saved <= limit.maximum):
                    shown = None
                    prior = f"{saved} {profile.unit}" if saved is not None else "unreadable"
                    notes.append(f"{limit.label} is {prior}. Leave it blank to keep the stored value.")

                default = shown
                value = submitted.get(limit.key)
                if value is not None:
                    number = _finite_float(value)
                    if number is None or not limit.minimum <= number <= limit.maximum:
                        errors["base"] = "profile_value_invalid"
                    else:
                        default = effective = number
                        if number != shown or (activating_custom and saved is None):
                            changes[limit.key] = number
                            range_changed = True
                limits.append(effective)
                marker = vol.Optional(limit.key) if default is None else vol.Optional(limit.key, default=default)
                group_fields[marker] = selector.NumberSelector(selector.NumberSelectorConfig(
                    min=limit.minimum, max=limit.maximum, step=profile.step,
                    mode=selector.NumberSelectorMode.BOX, unit_of_measurement=profile.unit,
                ))
            low, high = limits
            if activating_custom or range_changed:
                valid_custom = all(
                    value is not None and limit.minimum <= value <= limit.maximum
                    for value, limit in zip(limits, profile.limits)
                )
                if (selected == "custom" and not valid_custom) or (
                    low is not None and high is not None and low >= high
                ):
                    errors.setdefault("base", profile.range_error)
            fields[vol.Optional(profile.group)] = section(vol.Schema(group_fields), {"collapsed": False})

        if user_input is not None and not errors:
            self._options.update(changes)
            return await self.async_step_init()
        return self.async_show_form(
            step_id="options_thresholds", data_schema=vol.Schema(fields), errors=errors,
            description_placeholders={"range_notes": "\n\n".join(notes)},
        )

    async def async_step_options_sensors(self, user_input: Optional[Dict[str, Any]] = None):
        """Alias step for clearer top-level label in Options menu."""
        return await self.async_step_options_telemetry(user_input)

    def _index_context(self):
        return self._effective_config(), self._options, self.async_step_options_telemetry

    async def async_step_options_telemetry(self, user_input: Optional[Dict[str, Any]] = None):
        """Manage telemetry sensors in post-configuration options."""
        telemetry = list(self._section("telemetry", []))
        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action == "voc_index":
                return await self.async_step_voc_index()
            if action == "add":
                return await self.async_step_options_telemetry_add()
            if action == "manage":
                return await self.async_step_options_telemetry_manage()

        options = [SelectOptionDict(value="add", label="Add sensor")]
        options.append(SelectOptionDict(value="voc_index", label="VOC index (display only)"))
        if telemetry:
            options.append(SelectOptionDict(value="manage", label="Edit or delete sensor"))
        options.append(SelectOptionDict(value="done", label="Back to settings"))
        schema = vol.Schema({
            vol.Required("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        })
        return self.async_show_form(
            step_id="options_telemetry",
            data_schema=schema,
            description_placeholders={"telemetry_summary": _render_existing_telemetry(telemetry, self._effective_config())},
        )

    async def async_step_options_telemetry_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a telemetry sensor from post-configuration options."""
        telemetry = list(self._section("telemetry", []))
        errors: Dict[str, str] = {}
        preview_entity_id = _sanitize_optional_entity_id(user_input.get("entity_id")) if user_input else None
        preview_only = _is_setup_assist_preview_input(user_input)

        if user_input is not None:
            action = user_input.get("action", FORM_ACTION_SAVE)
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_options_cancel_confirm("options_telemetry_add", user_input)

            entity_id = _sanitize_optional_entity_id(user_input.get("entity_id"))
            if preview_only:
                pass
            elif user_input.get("sensor_type") == "voc_index":
                self._index_key = None
                self._index_defaults = {"entity_id": entity_id, "label": user_input.get("room", "")}
                return await self.async_step_voc_index_edit()
            elif not entity_id:
                errors["entity_id"] = "required"
            elif self._uses_index_provider(entity_id):
                errors["entity_id"] = "duplicate_entity"
            elif any(item.get("entity_id") == entity_id for item in telemetry):
                errors["entity_id"] = "duplicate_entity"
            else:
                area_name = _telemetry_display_value(user_input.get("room"), entity_id)
                entry = {
                    "entity_id": entity_id,
                    "sensor_type": user_input.get("sensor_type", SENSOR_TYPES[0]["value"]),
                    "friendly_name": area_name,
                    "level": user_input.get("level", LEVELS[0]["value"]),
                    "room": area_name,
                }
                telemetry.append(entry)
                self._options["telemetry"] = telemetry
                self._sync_slope_after_telemetry_add(entry)
                _LOGGER.info(
                    "Added telemetry sensor via options flow: %s (%s)",
                    entry.get("entity_id"),
                    entry.get("sensor_type"),
                )
                return await self.async_step_options_telemetry()

        default_room, default_level, assist_text = _setup_assist_defaults(
            self.hass,
            preview_entity_id,
        )
        room_options = _room_select_options(default_room)
        level_default = default_level or LEVELS[0]["value"]
        schema = vol.Schema({
            vol.Optional("action", default=FORM_ACTION_SAVE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_save_preview_cancel_options("Keep sensor changes"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            _optional_entity_selector_key("entity_id", preview_entity_id): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Optional("sensor_type", default=SENSOR_TYPES[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in ADD_SENSOR_TYPES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("level", default=level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_level_value_label_options(self._effective_config()),
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
            description_placeholders={
                "telemetry_summary": _render_existing_telemetry(telemetry, self._effective_config()),
                "setup_assist": assist_text,
            },
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
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_options_cancel_confirm("options_telemetry_manage", user_input)
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
                    _LOGGER.info("Removed telemetry sensor via options flow: %s", removed_entity_id)
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
                        SelectOptionDict(value=FORM_ACTION_CANCEL, label="Cancel"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(
            step_id="options_telemetry_manage",
            data_schema=schema,
            errors=errors,
            description_placeholders={"telemetry_summary": _render_existing_telemetry(telemetry, self._effective_config())},
        )

    async def async_step_options_telemetry_edit(self, user_input: Optional[Dict[str, Any]] = None):
        telemetry = list(self._section("telemetry", []))
        if not telemetry:
            return await self.async_step_options_telemetry()

        idx = self._pending_telemetry_index if self._pending_telemetry_index is not None else 0
        idx = max(0, min(idx, len(telemetry) - 1))
        current = telemetry[idx]
        errors: Dict[str, str] = {}

        if user_input is not None:
            action = user_input.get("action", FORM_ACTION_SAVE)
            if action == FORM_ACTION_CANCEL:
                return await self._async_show_options_cancel_confirm("options_telemetry_edit", user_input)

            selected_entity = _sanitize_optional_entity_id(user_input.get("entity_id"))
            if selected_entity and (
                self._uses_index_provider(selected_entity)
                or any(i != idx and item.get("entity_id") == selected_entity for i, item in enumerate(telemetry))
            ):
                errors["entity_id"] = "duplicate_entity"
            else:
                saved_entity_id = selected_entity or _sanitize_optional_entity_id(current.get("entity_id"))
                area_name = _telemetry_display_value(
                    user_input.get("room", current.get("room", "")),
                    saved_entity_id,
                )
                telemetry[idx] = {
                    **current,
                    "entity_id": saved_entity_id,
                    "sensor_type": user_input.get("sensor_type", current.get("sensor_type", SENSOR_TYPES[0]["value"])),
                    "friendly_name": area_name,
                    "level": user_input.get("level", current.get("level")),
                    "room": area_name,
                }
                self._options["telemetry"] = telemetry
                _LOGGER.info(
                    "Updated telemetry sensor via options flow: %s (%s)",
                    telemetry[idx].get("entity_id"),
                    telemetry[idx].get("sensor_type"),
                )
                return await self.async_step_options_telemetry()

        level_options = _level_value_label_options(self._effective_config())
        sensor_type_options = [SelectOptionDict(value=o["value"], label=o["label"]) for o in SENSOR_TYPES]
        entity_default = _sanitize_optional_entity_id(current.get("entity_id"))
        _room, _level, assist_text = _setup_assist_defaults(self.hass, entity_default)
        room_options = _room_select_options(current.get("room") or _room)
        schema = vol.Schema({
            vol.Optional("action", default=FORM_ACTION_SAVE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_save_cancel_options("Keep sensor changes"),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional("entity_id", default=entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=False)
            ),
            vol.Optional("sensor_type", default=current.get("sensor_type", SENSOR_TYPES[0]["value"])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=sensor_type_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("level", default=current.get("level")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=level_options,
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
            step_id="options_telemetry_edit",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "sensor_position": str(idx + 1),
                "sensor_total": str(len(telemetry)),
                "selected_sensor": _telemetry_label(current),
                "setup_assist": assist_text,
            },
        )

    async def async_step_options_zones(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose a zone to edit."""
        self._pending_zone_key = None
        zones = self._section("zones", {})
        readable = isinstance(zones, dict)
        configured = dict(_configured_zone_items(zones)) if readable else {}
        errors = {}
        slots = ("zone1", "zone2")
        editable = [key for key in slots if readable and isinstance(zones.get(key, {}), dict)]

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action == "level_labels":
                return await self.async_step_options_level_labels()
            if action in slots:
                if action in editable:
                    self._pending_zone_key = action
                    return await self.async_step_options_zone_edit()
                errors["base"] = "unrecognised_zone_settings"

        options = [
            SelectOptionDict(value=key, label=_zone_choice_label(key, zone, self._effective_config()))
            for key, zone in configured.items()
        ]
        options.extend(
            SelectOptionDict(value=key, label=f"Configure {_zone_title(key)}")
            for key in editable if key not in configured
        )
        options.extend([
            SelectOptionDict(value="level_labels", label="Edit level names"),
            SelectOptionDict(value="done", label="Back to settings"),
        ])
        schema = vol.Schema({
            vol.Required("action", default=options[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
            )
        })
        unavailable = [f"{_zone_title(key)}: saved settings unavailable." for key in slots if key not in editable]
        summary = [_render_zones_summary(configured, self._effective_config())] if configured or not unavailable else []
        return self.async_show_form(
            step_id="options_zones",
            errors=errors,
            data_schema=schema,
            description_placeholders={"configured_zones": "\n".join(summary + unavailable)},
        )

    async def async_step_options_level_labels(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit display-only Level 1 / Level 2 labels from Zone Options."""
        if user_input is not None:
            self._options[CONF_LEVEL_LABELS] = level_label_config_from_form(
                user_input,
                self._effective_config(),
            )
            return await self.async_step_options_zones()

        return self.async_show_form(
            step_id="options_level_labels",
            data_schema=_level_label_schema(self._effective_config()),
        )

    async def async_step_options_zone_edit(self, user_input: Optional[Dict[str, Any]] = None):
        zone_key = self._pending_zone_key
        if zone_key not in ("zone1", "zone2"):
            return await self.async_step_options_zones()
        zones = self._section("zones", {})
        zone = zones.get(zone_key, {}) if isinstance(zones, dict) else None
        if not isinstance(zone, dict):
            return await self.async_step_options_zones()
        if user_input is not None and user_input.get("action") == "back":
            return await self.async_step_options_zones()

        stored_triggers = zone.get("triggers", [])
        selected_triggers = [
            trig for trig in stored_triggers if isinstance(trig, str) and trig in TRIGGER_DEFS
        ] if isinstance(stored_triggers, list) else []
        defaults = {
            "enabled": bool(zone.get("enabled")),
            "level": zone.get("level") or _default_zone_level(zone_key),
            "rooms": zone.get("rooms") or [],
            "triggers": selected_triggers,
            "outputs": _sanitize_entity_ids(zone.get("outputs", [])),
            "output_level": _normalize_fan_level_choice(zone.get("output_level"), ZONE_OUTPUT_LEVEL_DEFAULT),
            "boost_output_level": _normalize_fan_level_choice(zone.get("boost_output_level"), ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
            "ui_label": _sanitize_ui_label(zone.get("ui_label"), _default_zone_ui_label(zone_key)),
        }
        stored_thresholds = zone.get("thresholds", {})
        thresholds = stored_thresholds if isinstance(stored_thresholds, dict) else {}
        errors = {}
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)
            changes = {
                key: user_input[key] for key, default in defaults.items()
                if key in user_input and user_input[key] != default
            }
            requested = changes.pop("triggers", selected_triggers)
            additions = [trig for trig in requested if trig in TRIGGER_DEFS and trig not in selected_triggers]
            if requested != selected_triggers and not isinstance(stored_triggers, list):
                errors["base"] = "unrecognised_zone_settings"
            elif requested != selected_triggers:
                changes["triggers"] = [
                    trig for trig in stored_triggers
                    if trig not in selected_triggers or trig in requested
                ] + additions
            if "outputs" in changes:
                changes["outputs"] = _sanitize_entity_ids(changes["outputs"])
            if "ui_label" in changes:
                changes["ui_label"] = _sanitize_ui_label(changes["ui_label"], defaults["ui_label"])

            updated = dict(thresholds)
            for trig, bounds in TRIGGER_DEFS.items():
                field = f"threshold_{trig}"
                raw = user_input.get(field)
                if raw is None or raw == "":
                    if trig in additions and trig not in thresholds:
                        updated[trig] = bounds["default"]
                    continue
                value = _finite_float(raw)
                if value is not None and value == _finite_float(thresholds.get(trig)):
                    continue
                if value is None or not bounds["min"] <= value <= bounds["max"]:
                    errors[field] = "invalid_zone_threshold"
                else:
                    updated[trig] = value
            if updated != thresholds:
                if isinstance(stored_thresholds, dict):
                    changes["thresholds"] = updated
                else:
                    errors["base"] = "unrecognised_zone_thresholds"
            # The controller reads triggers and thresholds once a zone has all three inputs.
            existing = zone if zone else {**defaults, "triggers": [], "thresholds": {}}
            edited = {**existing, **changes}
            enable_fields = ("enabled", "outputs", "triggers")
            if all(edited.get(key) for key in enable_fields) and not all(zone.get(key) for key in enable_fields):
                if not isinstance(edited.get("thresholds", {}), dict):
                    errors["base"] = "unrecognised_zone_thresholds"
                elif not isinstance(edited["triggers"], list) or not all(
                    isinstance(trigger, str) for trigger in edited["triggers"]
                ):
                    errors["base"] = "unrecognised_zone_settings"
            if not errors:
                if changes:
                    # Preserve raw representations and sparse legacy zones on unrelated edits.
                    zones = {**zones, zone_key: edited}
                    self._options["zones"] = zones
                    boost_warning = _boost_level_warning(
                        edited.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                        edited.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                    )
                    if boost_warning:
                        _LOGGER.warning("HI %s boost guidance: %s", zone_key, boost_warning)
                    duplicates = detect_zone_mapping_duplicates(self._section("telemetry", []), zones)
                    if duplicates:
                        _LOGGER.warning(
                            "Zone mapping duplicates detected in options for %s: %s",
                            zone_key, summarize_zone_mapping_duplicates(duplicates),
                        )
                return await self.async_step_options_zones()

        room_options = [SelectOptionDict(value=room, label=room) for room in _rooms_all(self._section("telemetry", []))]
        level_options = _level_value_label_options(self._effective_config())
        zone_default = lambda field, default: _form_input_default(user_input, field, default)
        selected_level_default = zone_default("level", defaults["level"])
        if defaults["level"] not in {option["value"] for option in level_options}:
            level_options.append(SelectOptionDict(value=defaults["level"], label=defaults["level"]))
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=zone_default("enabled", defaults["enabled"])): selector.BooleanSelector(),
            vol.Optional("level", default=selected_level_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=level_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("rooms", default=zone_default("rooms", defaults["rooms"])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("triggers", default=zone_default("triggers", selected_triggers)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_zone_trigger_options(
                        selected_level_default,
                        zone_key,
                        self._effective_config(),
                    ),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=zone_default("outputs", defaults["outputs"])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "switch"], multiple=True)
            ),
        }
        advanced_fields = {
            vol.Optional(
                "output_level",
                default=zone_default("output_level", defaults["output_level"]),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                "boost_output_level",
                default=zone_default("boost_output_level", defaults["boost_output_level"]),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("ui_label", default=zone_default("ui_label", defaults["ui_label"])): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        }
        for trig in TRIGGER_DEFS:
            field = f"threshold_{trig}"
            saved = _finite_float(thresholds.get(trig))
            suggested = zone_default(field, "" if saved is None else str(saved))
            key = vol.Optional(field, default=suggested)
            advanced_fields[key] = selector.TextSelector(selector.TextSelectorConfig(type="number"))
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section(advanced_fields)
        schema_fields[vol.Required("action", default="apply")] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["apply", "back"], translation_key="zone_edit_action", mode=selector.SelectSelectorMode.LIST
            )
        )
        return self.async_show_form(
            step_id="options_zone_edit",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={
                "zone_label": "Zone 1" if zone_key == "zone1" else "Zone 2",
                "boost_guidance": _boost_guidance_for_zone(zone),
            },
        )

    async def async_step_options_humidifiers(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose a humidifier lane to edit."""
        humidifiers = dict(self._section("humidifiers", {}))
        configured_levels = set(_configured_levels(self._section("telemetry", [])))
        known_levels = {item["value"] for item in LEVELS}
        levels = sorted(set(humidifiers.keys()).union(configured_levels).union(known_levels))
        if not levels:
            levels = [LEVELS[0]["value"]]

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action in levels:
                self._pending_humidifier_level = action
                return await self.async_step_options_humidifier_edit()

        options = [
            SelectOptionDict(
                value=level,
                label=(
                    f"{_level_choice_label(level, self._effective_config())}"
                    if level in humidifiers
                    else f"{_level_choice_label(level, self._effective_config())} (not configured - select to add)"
                ),
            )
            for level in levels
        ]
        options.append(SelectOptionDict(value="done", label="Back to settings"))
        schema = vol.Schema({
            vol.Required("action", default=levels[0]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        })
        return self.async_show_form(
            step_id="options_humidifiers",
            data_schema=schema,
            description_placeholders={
                "configured_humidifiers": _render_humidifiers_summary(
                    humidifiers,
                    self._effective_config(),
                )
            },
        )

    async def async_step_options_humidifier_edit(self, user_input: Optional[Dict[str, Any]] = None):
        humidifiers = dict(self._section("humidifiers", {}))
        level = self._pending_humidifier_level or (sorted(humidifiers.keys())[0] if humidifiers else None)
        if not level:
            return await self.async_step_options_humidifiers()
        cfg = humidifiers.get(level, {"enabled": False, "band_adjust": 0, "outputs": []})
        lane_existed = level in humidifiers

        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            if user_input.get("remove_lane", False):
                humidifiers.pop(level, None)
                self._options["humidifiers"] = humidifiers
                _LOGGER.info("Removed humidifier lane for %s via options flow", level)
                return await self.async_step_options_humidifiers()
            humidifiers[level] = {
                **cfg,
                "enabled": user_input.get("enabled", cfg.get("enabled", True)),
                "band_adjust": user_input.get("band_adjust", cfg.get("band_adjust", 0)),
                "outputs": _sanitize_entity_ids(user_input.get("outputs", cfg.get("outputs", []))),
            }
            self._options["humidifiers"] = humidifiers
            if lane_existed:
                _LOGGER.info("Updated humidifier lane for %s via options flow", level)
            else:
                _LOGGER.info("Added humidifier lane for %s via options flow", level)
            return await self.async_step_options_humidifiers()

        humidifier_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=humidifier_default("enabled", cfg.get("enabled", True))): selector.BooleanSelector(),
            vol.Optional("outputs", default=humidifier_default("outputs", _sanitize_entity_ids(cfg.get("outputs", [])))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["humidifier", "fan", "switch"], multiple=True)
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("remove_lane", default=humidifier_default("remove_lane", False)): selector.BooleanSelector(),
            vol.Optional("band_adjust", default=humidifier_default("band_adjust", cfg.get("band_adjust", 0))): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=HUMIDIFIER_BAND_MIN,
                    max=HUMIDIFIER_BAND_MAX,
                    step=HUMIDIFIER_BAND_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="%",
                )
            ),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="options_humidifier_edit",
            data_schema=schema,
            description_placeholders={
                "level_label": _level_choice_label(level, self._effective_config()),
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
            },
        )

    async def async_step_options_aq(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose an AQ lane to edit."""
        self._pending_aq_level = None
        self._aq_review = None
        aq = dict(self._section("aq", {}))
        known_levels = {item["value"] for item in LEVELS}
        levels = sorted(known_levels.union(key for key in aq if isinstance(key, str) and key))

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action in levels:
                self._pending_aq_level = action
                return await self.async_step_options_aq_edit()

        options = [
            SelectOptionDict(
                value=level,
                label=(
                    f"{_level_choice_label(level, self._effective_config())}"
                    if level in aq
                    else f"{_level_choice_label(level, self._effective_config())} (not configured - select to add)"
                ),
            )
            for level in levels
        ]
        options.append(SelectOptionDict(value="done", label="Back to settings"))
        schema = vol.Schema({
            vol.Required("action", default=levels[0]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        })
        return self.async_show_form(
            step_id="options_aq",
            data_schema=schema,
            description_placeholders={
                "configured_aq": _render_aq_summary(
                    aq,
                    self._effective_config(),
                )
            },
        )

    async def async_step_options_aq_edit(self, user_input: Optional[Dict[str, Any]] = None):
        aq = dict(self._section("aq", {}))
        level = self._pending_aq_level
        if not level or (level not in aq and level not in {item["value"] for item in LEVELS}):
            return await self.async_step_options_aq()
        cfg = aq.get(level, {
            "enabled": False,
            "triggers": [],
            "outputs": [],
            "run_duration": 30,
            "output_level": ZONE_OUTPUT_LEVEL_DEFAULT,
            "thresholds": {},
        })
        selected_triggers = cfg.get("triggers", []) or []
        known_triggers = [trig for trig in selected_triggers if trig in AQ_TRIGGER_DEFS]
        stored_thresholds = cfg.get("thresholds")
        saved_thresholds = stored_thresholds if isinstance(stored_thresholds, dict) else {}
        repairable = [
            trig for trig in known_triggers if _aq_editable_threshold(trig, saved_thresholds.get(trig)) is None
        ]

        errors = {}
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            if user_input.get("remove_lane", False):
                aq.pop(level, None)
                self._options["aq"] = aq
                _LOGGER.info("Removed AQ lane for %s via options flow", level)
                return await self.async_step_options_aq()
            requested = user_input.get("triggers", selected_triggers) or []
            # The selector only knows current trigger types. Retain legacy entries.
            triggers = [trig for trig in selected_triggers if trig in requested or trig not in AQ_TRIGGER_DEFS]
            additions = [
                trig for trig in dict.fromkeys(requested) if trig in AQ_TRIGGER_DEFS and trig not in triggers
            ]
            triggers.extend(additions)
            thresholds = dict(saved_thresholds)
            for trig in requested:
                field = f"threshold_{trig}"
                if trig not in known_triggers or field not in user_input:
                    continue
                prior = _aq_editable_threshold(trig, saved_thresholds.get(trig))
                if prior is None:
                    continue
                value = _aq_editable_threshold(trig, user_input[field])
                if value is None:
                    errors[field] = "invalid_aq_threshold"
                elif value != prior:
                    thresholds[trig] = value
            if not errors:
                lane = {
                    **cfg,
                    "enabled": user_input.get("enabled", cfg.get("enabled", False)),
                    "triggers": triggers,
                    "outputs": _sanitize_entity_ids(user_input.get("outputs", cfg.get("outputs", []))),
                    "run_duration": user_input.get("run_duration", cfg.get("run_duration", 30)),
                    "output_level": _normalize_fan_level_choice(
                        user_input.get("output_level"),
                        cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                    ),
                }
                if thresholds != saved_thresholds or level not in aq:
                    lane["thresholds"] = thresholds
                repairs = user_input.get("set_thresholds", [])
                review = additions + [trig for trig in repairable if trig in repairs and trig in triggers]
                if review:
                    self._aq_review = _AQThresholdReview(level, deepcopy(aq.get(level)), lane, review)
                    return await self.async_step_options_aq_thresholds()
                aq[level] = lane
                self._options["aq"] = aq
                return await self.async_step_options_aq()

        aq_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=aq_default("enabled", cfg.get("enabled", False))): selector.BooleanSelector(),
            vol.Optional("triggers", default=aq_default("triggers", known_triggers)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_aq_trigger_options(level, self._effective_config()),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("outputs", default=aq_default("outputs", _sanitize_entity_ids(cfg.get("outputs", [])))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["fan", "air_purifier", "switch"], multiple=True)
            ),
        }
        advanced_fields: Dict[Any, Any] = {
            vol.Optional("remove_lane", default=aq_default("remove_lane", False)): selector.BooleanSelector(),
            vol.Optional("run_duration", default=aq_default("run_duration", cfg.get("run_duration", 30))): selector.NumberSelector(
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
                    aq_default("output_level", cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT)),
                    ZONE_OUTPUT_LEVEL_DEFAULT,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_fan_output_level_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        if repairable:
            repair_key = vol.Optional("set_thresholds", default=aq_default("set_thresholds", []))
            advanced_fields[repair_key] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    SelectOptionDict(value=trig, label=_aq_threshold_note(trig, saved_thresholds.get(trig)))
                    for trig in repairable
                ], multiple=True)
            )
        for trig in known_triggers:
            if trig not in repairable:
                field = f"threshold_{trig}"
                current = _aq_editable_threshold(trig, saved_thresholds[trig])
                default = current if field in errors else aq_default(field, current)
                key = vol.Optional(field, default=default)
                advanced_fields[key] = _aq_threshold_selector(trig)
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section(advanced_fields)
        return self.async_show_form(
            step_id="options_aq_edit",
            errors=errors,
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "level_label": _level_choice_label(level, self._effective_config()),
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
            },
        )

    async def async_step_options_aq_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        """Confirm new or explicitly requested thresholds before staging the lane."""
        review = self._aq_review
        if review is None or review.level != self._pending_aq_level:
            return await self.async_step_options_aq()
        level = review.level
        lane = review.lane
        aq = dict(self._section("aq", {}))
        if aq.get(level) != review.previous_lane:
            return await self.async_step_options_aq()
        if user_input is not None and user_input.get("action") == "back":
            self._aq_review = None
            return await self.async_step_options_aq_edit()

        stored = lane.get("thresholds")
        if stored is not None and not isinstance(stored, dict):
            return await self.async_step_options_aq_thresholds_unavailable()
        thresholds = stored or {}
        fields = {}
        sources = []
        values = {}
        errors = {}
        for trig in review.triggers:
            key = f"threshold_{trig}"
            saved = _aq_editable_threshold(trig, thresholds.get(trig))
            default = saved if saved is not None else AQ_TRIGGER_DEFS[trig]["default"]
            bounds = AQ_TRIGGER_DEFS[trig]
            unit = AQ_CANONICAL_UNITS[AQ_TRIGGER_SPECS[trig]["sensor_type"]]
            note = _aq_threshold_note(trig, thresholds.get(trig))
            sources.append(f"- {note} Range {bounds['min']}–{bounds['max']} {unit}.")
            if user_input is not None:
                value = _aq_editable_threshold(trig, user_input.get(key))
                if value is None:
                    errors[key] = "invalid_aq_threshold"
                else:
                    values[trig] = thresholds[trig] if value == saved else value
            # Validate limits only on confirmation, so Back also works with unfinished input.
            suggested = str(default) if user_input is None else user_input.get(key, "")
            marker = vol.Optional(key, description={"suggested_value": suggested})
            fields[marker] = selector.TextSelector(selector.TextSelectorConfig(
                type=selector.TextSelectorType.NUMBER, suffix=unit,
            ))
        if user_input is not None and user_input.get("action") == "confirm" and not errors:
            aq[level] = {**lane, "thresholds": {**thresholds, **values}}
            self._options["aq"] = aq
            return await self.async_step_options_aq()
        fields[vol.Required("action", default="confirm")] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=[
                SelectOptionDict(value="confirm", label="Keep these thresholds"),
                SelectOptionDict(value="back", label="Back to lane without these changes"),
            ], mode=selector.SelectSelectorMode.LIST)
        )
        return self.async_show_form(
            step_id="options_aq_thresholds", data_schema=vol.Schema(fields), errors=errors,
            description_placeholders={
                "level_label": _level_choice_label(level, self._effective_config()),
                "threshold_sources": "\n".join(sources),
            },
        )

    async def async_step_options_aq_thresholds_unavailable(self, user_input=None):
        """Return without replacing an unrecognised threshold collection."""
        if user_input is not None:
            return await self.async_step_options_aq()
        return self.async_show_form(step_id="options_aq_thresholds_unavailable", data_schema=vol.Schema({}))

    async def async_step_options_alerts(self, user_input: Optional[Dict[str, Any]] = None):
        """Choose an alert to edit."""
        alerts = _sanitize_alert_rules(list(self._section("alerts", [])))
        self._options["alerts"] = alerts

        if user_input is not None:
            action = user_input.get("action", "done")
            if action == "done":
                return await self.async_step_init()
            if action == "settings":
                return await self.async_step_options_alert_settings()
            if action == "add":
                return await self.async_step_options_alert_add()
            if action == "remove":
                return await self.async_step_options_alert_remove()
            try:
                idx = int(action)
            except (TypeError, ValueError):
                idx = 0
            if 0 <= idx < len(alerts):
                self._pending_alert_index = idx
                return await self.async_step_options_alert_edit()

        options = [SelectOptionDict(value="settings", label="Alert handling settings")]
        options.append(SelectOptionDict(value="add", label="Add alert visual rule"))
        if alerts:
            options.append(SelectOptionDict(value="remove", label="Remove alert visual rule"))
        options.extend([
            SelectOptionDict(value=str(idx), label=_alert_option_label(idx, alert))
            for idx, alert in enumerate(alerts)
        ])
        options.append(SelectOptionDict(value="done", label="Back to settings"))
        default_action = "0" if alerts else "settings"
        schema = vol.Schema({
            vol.Required("action", default=default_action): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        })
        return self.async_show_form(
            step_id="options_alerts",
            data_schema=schema,
            description_placeholders={"configured_alerts": _render_alerts_summary(alerts)},
        )

    async def async_step_options_alert_settings(self, user_input: Optional[Dict[str, Any]] = None):
        """Edit internal alert handling settings from options."""
        if user_input is not None:
            self._options[CONF_ALERT_HANDLING_ENABLED] = bool(
                user_input.get(
                    CONF_ALERT_HANDLING_ENABLED,
                    self._section(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED),
                )
            )
            return await self.async_step_options_alerts()

        schema = vol.Schema({
            vol.Optional(
                CONF_ALERT_HANDLING_ENABLED,
                default=self._section(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED),
            ): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="options_alert_settings", data_schema=schema)

    async def async_step_options_alert_add(self, user_input: Optional[Dict[str, Any]] = None):
        """Add a new visual indicator rule from options."""
        alerts = list(self._section("alerts", []))
        if len(alerts) >= MAX_ALERTS:
            return await self.async_step_options_alerts()
        errors: Dict[str, str] = {}
        telemetry = list(self._section("telemetry", []))
        config = self._effective_config()

        trigger_default = _default_alert_trigger_type()
        enabled_default = True
        room_default = ""
        lights_default: List[str] = []
        power_entity_default: Optional[str] = None
        flash_mode_default = _default_alert_flash_mode()
        duration_default = 10
        threshold_default_value: Any = _alert_threshold_value(
            trigger_default,
            None,
            config,
        )

        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            enabled_default = bool(user_input.get("enabled", True))
            trigger_default = _normalize_alert_trigger_type(user_input.get("trigger_type"))
            room_default = _sanitize_optional_room_scope(user_input.get("room")) or ""
            lights_default = _sanitize_entity_ids(user_input.get("lights", []))
            power_entity_default = _sanitize_optional_entity_id(user_input.get("power_entity"))
            flash_mode_default = _normalize_alert_flash_mode(user_input.get("flash_mode"))
            duration_default = _safe_alert_duration(user_input.get("duration", 10))
            threshold_default_value = _alert_threshold_value(
                trigger_default,
                user_input.get("threshold"),
                config,
            )

            try:
                alert, room_error = _alert_rule_payload_from_form_input(
                    telemetry=telemetry,
                    user_input=user_input,
                    config=config,
                )
                if room_error:
                    errors["room"] = room_error

                if not errors and alert is not None:
                    alerts.append(alert)
                    self._options["alerts"] = alerts
                    return await self.async_step_options_alerts()
            except Exception:
                _LOGGER.exception("Failed to add alert in options flow")
                errors["base"] = "alert_save_failed"

        alert_default = lambda field, default: _form_input_default(user_input, field, default)
        trigger_default = _normalize_alert_trigger_type(alert_default("trigger_type", trigger_default))
        enabled_default = bool(alert_default("enabled", enabled_default))
        room_default = _sanitize_optional_room_scope(alert_default("room", room_default)) or ""
        lights_default = _sanitize_entity_ids(alert_default("lights", lights_default))
        power_entity_default = _sanitize_optional_entity_id(alert_default("power_entity", power_entity_default))
        flash_mode_default = _normalize_alert_flash_mode(alert_default("flash_mode", flash_mode_default))
        duration_default = _safe_alert_duration(alert_default("duration", duration_default))
        threshold_default_value = _alert_threshold_value(
            trigger_default,
            alert_default("threshold", threshold_default_value),
            config,
        )
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=enabled_default): selector.BooleanSelector(),
            vol.Required("trigger_type", default=trigger_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_trigger_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=room_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_room_options(telemetry),
                    multiple=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("lights", default=lights_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
        }
        advanced_fields: Dict[Any, Any] = {}
        if _alert_uses_static_threshold(trigger_default):
            threshold_min, threshold_max, _, threshold_unit = _alert_threshold_bounds(trigger_default)
            advanced_fields[vol.Optional("threshold", default=threshold_default_value)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=threshold_min,
                    max=threshold_max,
                    step=1,
                    unit_of_measurement=threshold_unit,
                )
            )
        advanced_fields.update({
            _optional_entity_selector_key("power_entity", power_entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=False)
            ),
            vol.Optional("flash_mode", default=flash_mode_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in ALERT_FLASH_MODES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("duration", default=duration_default): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ALERT_DURATION_MIN,
                    max=ALERT_DURATION_MAX,
                    step=ALERT_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
        })
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section(advanced_fields)
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="options_alert_add",
            data_schema=schema,
            errors=errors,
            description_placeholders={"advanced_note": ADVANCED_DEFAULTS_NOTE},
        )

    async def async_step_options_alert_remove(self, user_input: Optional[Dict[str, Any]] = None):
        """Remove a visual indicator rule from options."""
        alerts = _sanitize_alert_rules(list(self._section("alerts", [])))
        self._options["alerts"] = alerts
        if not alerts:
            return await self.async_step_options_alerts()

        if user_input is not None:
            remove_alert = str(user_input.get("remove_alert", "cancel"))
            if remove_alert != "cancel":
                try:
                    idx = int(remove_alert)
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(alerts):
                    alerts.pop(idx)
                    self._options["alerts"] = alerts
            return await self.async_step_options_alerts()

        options = [
            SelectOptionDict(value=str(idx), label=_alert_option_label(idx, alert))
            for idx, alert in enumerate(alerts)
        ]
        options.append(SelectOptionDict(value="cancel", label="Cancel"))
        schema = vol.Schema({
            vol.Required("remove_alert", default="0"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })
        return self.async_show_form(
            step_id="options_alert_remove",
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
        telemetry = list(self._section("telemetry", []))
        config = self._effective_config()
        errors: Dict[str, str] = {}

        trigger_default = _normalize_alert_trigger_type(alert.get("trigger_type"))
        enabled_default = bool(alert.get("enabled", True))
        room_default = _sanitize_optional_room_scope(alert.get("room")) or ""
        lights_default = _sanitize_entity_ids(alert.get("lights", []))
        power_entity_default = _sanitize_optional_entity_id(alert.get("power_entity"))
        flash_mode_default = _normalize_alert_flash_mode(alert.get("flash_mode"))
        duration_default = _safe_alert_duration(alert.get("duration", 10))
        threshold_default = _alert_threshold_value(
            trigger_default,
            alert.get("threshold"),
            config,
        )

        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            trigger_default = _normalize_alert_trigger_type(user_input.get("trigger_type", trigger_default))
            enabled_default = bool(user_input.get("enabled", enabled_default))
            room_default = _sanitize_optional_room_scope(user_input.get("room", room_default)) or ""
            lights_default = _sanitize_entity_ids(user_input.get("lights", lights_default))
            power_entity_default = _sanitize_optional_entity_id(
                user_input.get("power_entity", power_entity_default)
            )
            flash_mode_default = _normalize_alert_flash_mode(
                user_input.get("flash_mode", flash_mode_default)
            )
            duration_default = _safe_alert_duration(user_input.get("duration", duration_default))
            threshold_default = _alert_threshold_value(
                trigger_default,
                user_input.get("threshold", threshold_default),
                config,
            )

            try:
                updated_alert, room_error = _alert_rule_payload_from_form_input(
                    telemetry=telemetry,
                    user_input=user_input,
                    config=config,
                    existing_alert=alert,
                )
                if room_error:
                    errors["room"] = room_error

                if not errors and updated_alert is not None:
                    alerts[idx] = updated_alert
                    self._options["alerts"] = alerts
                    return await self.async_step_options_alerts()
            except Exception:
                _LOGGER.exception("Failed to edit alert %s in options flow", idx + 1)
                errors["base"] = "alert_save_failed"

        alert_default = lambda field, default: _form_input_default(user_input, field, default)
        trigger_default = _normalize_alert_trigger_type(alert_default("trigger_type", trigger_default))
        enabled_default = bool(alert_default("enabled", enabled_default))
        room_default = _sanitize_optional_room_scope(alert_default("room", room_default)) or ""
        lights_default = _sanitize_entity_ids(alert_default("lights", lights_default))
        power_entity_default = _sanitize_optional_entity_id(alert_default("power_entity", power_entity_default))
        flash_mode_default = _normalize_alert_flash_mode(alert_default("flash_mode", flash_mode_default))
        duration_default = _safe_alert_duration(alert_default("duration", duration_default))
        threshold_default = _alert_threshold_value(
            trigger_default,
            alert_default("threshold", threshold_default),
            config,
        )
        schema_fields: Dict[Any, Any] = {
            vol.Optional("enabled", default=enabled_default): selector.BooleanSelector(),
            vol.Optional("trigger_type", default=trigger_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_trigger_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("room", default=room_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_alert_room_options(telemetry),
                    multiple=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("lights", default=lights_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
        }
        advanced_fields: Dict[Any, Any] = {}
        if _alert_uses_static_threshold(trigger_default):
            threshold_min, threshold_max, _, threshold_unit = _alert_threshold_bounds(trigger_default)
            advanced_fields[vol.Optional("threshold", default=threshold_default)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=threshold_min,
                    max=threshold_max,
                    step=1,
                    unit_of_measurement=threshold_unit,
                )
            )
        advanced_fields.update({
            _optional_entity_selector_key("power_entity", power_entity_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=False)
            ),
            vol.Optional("flash_mode", default=flash_mode_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SelectOptionDict(value=o["value"], label=o["label"]) for o in ALERT_FLASH_MODES],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("duration", default=duration_default): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=ALERT_DURATION_MIN,
                    max=ALERT_DURATION_MAX,
                    step=ALERT_DURATION_STEP,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="s",
                )
            ),
        })
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section(advanced_fields)
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="options_alert_edit",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "alert_label": _alert_option_label(idx, alert),
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
            },
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
        default_show_temperature_chips = bool(
            slope.get(CONF_SHOW_TEMPERATURE_CHIPS, DEFAULT_SHOW_TEMPERATURE_CHIPS)
        )

        errors: Dict[str, str] = {}
        if user_input is not None:
            user_input = _flatten_advanced_section_input(user_input)

            mode = user_input.get("slope_mode", default_mode)
            slope_sources = _sanitize_entity_ids(user_input.get("slope_sources") or default_sources)
            provided_sensors = _sanitize_entity_ids(user_input.get("slope_sensors", []))
            show_temperature_chips = bool(
                user_input.get(CONF_SHOW_TEMPERATURE_CHIPS, default_show_temperature_chips)
            )

            if mode == SLOPE_MODE_CALCULATED and not slope_sources:
                errors["slope_sources"] = "required"
            if mode == SLOPE_MODE_PROVIDED and not provided_sensors:
                errors["slope_sensors"] = "required"
            bindings = {}
            if mode == SLOPE_MODE_PROVIDED and provided_sensors:
                bindings = bindings_for_save(self.hass, slope_sources or temp_entities, provided_sensors,
                                             telemetry, slope.get("bindings"))
                if len(bindings) != len(set(slope_sources or temp_entities)):
                    errors["slope_sensors"] = "ambiguous_slope_mapping"
            if not errors:
                slope_data: Dict[str, Any] = {
                    "mode": mode,
                    "source_entities": [],
                    CONF_SHOW_TEMPERATURE_CHIPS: show_temperature_chips,
                }
                if mode == SLOPE_MODE_CALCULATED:
                    slope_data["source_entities"] = slope_sources
                elif mode == SLOPE_MODE_PROVIDED:
                    slope_data["source_entities"] = slope_sources or temp_entities
                    slope_data["provided_sensors"] = provided_sensors
                    slope_data["bindings"] = bindings
                self._options["slope"] = slope_data
                return await self.async_step_init()

        slope_default = lambda field, default: _form_input_default(user_input, field, default)
        schema_fields: Dict[Any, Any] = {
            vol.Required("slope_mode", default=slope_default("slope_mode", default_mode)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=SLOPE_MODE_CALCULATED, label="HI calculates slope"),
                        SelectOptionDict(value=SLOPE_MODE_PROVIDED, label="Provide my own slope sensors"),
                        SelectOptionDict(value=SLOPE_MODE_NONE, label="Skip slope"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        schema_fields[vol.Optional(ADVANCED_OPTIONS_FIELD)] = _advanced_section({
            vol.Optional("slope_sources", default=slope_default("slope_sources", default_sources)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional("slope_sensors", default=slope_default("slope_sensors", default_provided)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(
                CONF_SHOW_TEMPERATURE_CHIPS,
                default=slope_default(CONF_SHOW_TEMPERATURE_CHIPS, default_show_temperature_chips),
            ): selector.BooleanSelector(),
        })
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="options_slope",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "configured_slope": _render_slope_summary(slope),
                "advanced_note": ADVANCED_DEFAULTS_NOTE,
            },
        )

    async def async_step_options_done(self, user_input: Optional[Dict[str, Any]] = None):
        self._options["alerts"] = _sanitize_alert_rules(self._section("alerts", []))
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
    return await async_render_dependency_status(hass)


def _entry_section(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Resolve a config section from options first, then entry data."""
    if entry.options and key in entry.options:
        return entry.options.get(key, default)
    return entry.data.get(key, default)


def _entry_show_output_entity_details_default(entry: config_entries.ConfigEntry) -> bool:
    """Preserve existing generated-card detail panels unless a config value exists."""
    if entry.options and CONF_SHOW_OUTPUT_ENTITY_DETAILS in entry.options:
        return bool(entry.options.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS))
    if entry.data and CONF_SHOW_OUTPUT_ENTITY_DETAILS in entry.data:
        return bool(entry.data.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS))
    return True


def _sanitize_optional_entity_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def _telemetry_display_value(value: Any, entity_id: Optional[str]) -> str:
    """Return a saved display value, falling back to the sensor id."""
    text = str(value or "").strip()
    if text:
        return text
    return entity_id or ""


def _sanitize_entity_ids(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, (list, tuple, set)):
        raw = list(values)
    else:
        raw = [values]
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


def _alert_uses_static_threshold(trigger_type: Any) -> bool:
    """Return True for alert triggers that store their own numeric threshold."""
    return str(trigger_type or "") in ALERT_THRESHOLD_BOUNDS


def _alert_threshold_value(trigger_type: Any, value: Any, _config: Dict[str, Any]) -> Any:
    """Normalize static thresholds while leaving profile-driven alerts unsaved."""
    if not _alert_uses_static_threshold(trigger_type):
        return None
    return _safe_alert_threshold(trigger_type, value, None)


def _alert_rule_payload(
    *,
    telemetry: List[Dict[str, Any]],
    enabled: bool,
    trigger_type: str,
    threshold: Any,
    room: Any,
    lights: List[str],
    power_entity: Optional[str],
    flash_mode: str,
    duration: int,
    existing_alert: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    room_scope, room_error = _resolve_alert_room_scope(telemetry, trigger_type, room)
    if room_error:
        return None, room_error

    payload: Dict[str, Any] = {
        "enabled": enabled,
        "trigger_type": trigger_type,
        "threshold": threshold,
        "room": room_scope,
        "lights": lights,
        "power_entity": power_entity,
        "flash_mode": flash_mode,
        "duration": duration,
    }
    if existing_alert is not None:
        return {**existing_alert, **payload}, None
    return payload, None


def _alert_rule_payload_from_form_input(
    *,
    telemetry: List[Dict[str, Any]],
    user_input: Dict[str, Any],
    config: Dict[str, Any],
    existing_alert: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    defaults = existing_alert or {}
    flattened = _flatten_advanced_section_input(user_input) or {}
    trigger_type = _normalize_alert_trigger_type(
        flattened.get("trigger_type", defaults.get("trigger_type"))
    )
    return _alert_rule_payload(
        telemetry=telemetry,
        enabled=bool(flattened.get("enabled", defaults.get("enabled", True))),
        trigger_type=trigger_type,
        threshold=_alert_threshold_value(
            trigger_type,
            flattened.get("threshold", defaults.get("threshold")),
            config,
        ),
        room=_sanitize_optional_room_scope(flattened.get("room", defaults.get("room"))) or "",
        lights=_sanitize_entity_ids(flattened.get("lights", defaults.get("lights", []))),
        power_entity=_sanitize_optional_entity_id(
            flattened.get("power_entity", defaults.get("power_entity"))
        ),
        flash_mode=_normalize_alert_flash_mode(
            flattened.get("flash_mode", defaults.get("flash_mode"))
        ),
        duration=_safe_alert_duration(flattened.get("duration", defaults.get("duration", 10))),
        existing_alert=existing_alert,
    )


def _safe_alert_threshold(trigger_type: Any, value: Any, fallback: Optional[float] = None) -> Any:
    min_value, max_value, default_value, _ = _alert_threshold_bounds(trigger_type)
    parsed = None
    if value not in (None, ""):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
    if parsed is None:
        try:
            parsed = float(fallback) if fallback is not None else None
        except (TypeError, ValueError):
            parsed = None
    if parsed is None:
        parsed = default_value
    parsed = max(min_value, min(max_value, parsed))
    if abs(parsed - round(parsed)) < 1e-9:
        return int(round(parsed))
    return round(parsed, 2)


def _default_alert_trigger_type() -> str:
    if ALERT_TRIGGER_DEFS:
        return next(iter(ALERT_TRIGGER_DEFS.keys()))
    return "humidity_danger"


def _normalize_alert_trigger_type(value: Any) -> str:
    text = str(value or "").strip()
    if text in ALERT_TRIGGER_DEFS:
        return text
    return _default_alert_trigger_type()


def _alert_trigger_options() -> List[SelectOptionDict]:
    return [SelectOptionDict(value=k, label=v["label"]) for k, v in ALERT_TRIGGER_DEFS.items()]


def _default_alert_flash_mode() -> str:
    if ALERT_FLASH_MODES:
        return str(ALERT_FLASH_MODES[0]["value"])
    return "red"


def _normalize_alert_flash_mode(value: Any) -> str:
    text = str(value or "").strip()
    valid = {str(item["value"]) for item in ALERT_FLASH_MODES}
    if text in valid:
        return text
    return _default_alert_flash_mode()


def _safe_alert_duration(value: Any, default: int = 10) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(ALERT_DURATION_MIN, min(ALERT_DURATION_MAX, parsed))


def _sanitize_optional_room_scope(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _alert_room_options(telemetry: List[Dict[str, Any]]) -> List[SelectOptionDict]:
    options = [SelectOptionDict(value="", label="Auto-resolve affected room")]
    options.extend(SelectOptionDict(value=room, label=room) for room in _rooms_all(telemetry))
    return options


def _resolve_alert_room_scope(
    telemetry: List[Dict[str, Any]],
    trigger_type: str,
    room_value: Any,
) -> Tuple[Optional[str], Optional[str]]:
    room_scope = _sanitize_optional_room_scope(room_value)
    if not room_scope:
        return None, None

    if trigger_type not in ROOM_SCOPED_ALERT_TRIGGERS:
        return None, None

    room_lookup = {}
    for room in _rooms_all(telemetry):
        key = room.lower().strip()
        if key and key not in room_lookup:
            room_lookup[key] = room
    resolved_room = room_lookup.get(room_scope.lower().strip())
    if not resolved_room:
        return None, "room_unknown"

    if trigger_type == "humidity_danger":
        if not _telemetry_room_has_sensor_type(telemetry, resolved_room, "humidity"):
            return None, "room_missing_humidity"
    elif trigger_type in {"condensation_danger", "condensation_risk", "mould_danger", "mould_risk"}:
        has_humidity = _telemetry_room_has_sensor_type(telemetry, resolved_room, "humidity")
        has_temperature = _telemetry_room_has_sensor_type(telemetry, resolved_room, "temperature")
        if not has_humidity or not has_temperature:
            return None, "room_missing_temp_humidity"

    return resolved_room, None


def _telemetry_room_has_sensor_type(
    telemetry: List[Dict[str, Any]],
    room: str,
    sensor_type: str,
) -> bool:
    room_key = room.lower().strip()
    for item in telemetry:
        item_room = str(item.get("room") or "").strip().lower()
        if not item_room or item_room != room_key:
            continue
        if item.get("sensor_type") == sensor_type and _sanitize_optional_entity_id(item.get("entity_id")):
            return True
    return False


def _optional_entity_selector_key(field_name: str, default_value: Any) -> Any:
    entity_id = _sanitize_optional_entity_id(default_value)
    if entity_id is None:
        return vol.Optional(field_name)
    return vol.Optional(field_name, default=entity_id)


def _render_alerts_summary(alerts: List[Dict[str, Any]]) -> str:
    """Human-readable summary of configured visual alert indicator rules."""
    alerts = _sanitize_alert_rules(alerts)
    if not alerts:
        return "No visual indicator rules configured yet."
    lines: List[str] = []
    for idx, alert in enumerate(alerts, start=1):
        trigger = alert.get("trigger_type", "unknown")
        trigger_def = ALERT_TRIGGER_DEFS.get(trigger, {})
        trigger_label = trigger_def.get("label", trigger.replace("_", " ").title())
        threshold = alert.get("threshold")
        suffix = ""
        if trigger == "humidity_danger":
            suffix = " @ active profile high-risk"
        elif _alert_uses_static_threshold(trigger) and threshold not in (None, ""):
            suffix = f" @ {_safe_alert_threshold(trigger, threshold, None)}"
        room_scope = _sanitize_optional_room_scope(alert.get("room"))
        room_suffix = f" in {room_scope}" if room_scope else ""
        lines.append(f"- Indicator {idx}: {trigger_label}{suffix}{room_suffix}")
    return "\n".join(lines)


def _sanitize_alert_rules(alerts: Any) -> List[Dict[str, Any]]:
    """Strip deprecated generic-trigger alert config and keep indicator rules portable."""
    sanitized: List[Dict[str, Any]] = []
    for alert in alerts or []:
        if not isinstance(alert, dict):
            continue
        raw_trigger = str(alert.get("trigger_type") or "").strip()
        if raw_trigger not in ALERT_TRIGGER_DEFS:
            continue
        trigger = _normalize_alert_trigger_type(raw_trigger)
        sanitized.append({
            "enabled": bool(alert.get("enabled", True)),
            "trigger_type": trigger,
            "threshold": _alert_threshold_value(trigger, alert.get("threshold"), alert),
            "room": _sanitize_optional_room_scope(alert.get("room")),
            "lights": _sanitize_entity_ids(alert.get("lights", [])),
            "power_entity": _sanitize_optional_entity_id(alert.get("power_entity")),
            "flash_mode": _normalize_alert_flash_mode(alert.get("flash_mode")),
            "duration": _safe_alert_duration(alert.get("duration", 10)),
        })
        if len(sanitized) >= MAX_ALERTS:
            break
    return sanitized


def _render_slope_summary(slope: Dict[str, Any]) -> str:
    """Human-readable summary of slope configuration for options flow pages."""
    if not slope:
        return "No slope configuration set."
    mode = slope.get("mode", SLOPE_MODE_NONE)
    if mode == SLOPE_MODE_CALCULATED:
        sources = _sanitize_entity_ids(slope.get("source_entities", []))
        chips = "enabled" if slope.get(CONF_SHOW_TEMPERATURE_CHIPS) else "disabled"
        return f"Mode: HI calculates slope. Source sensors: {len(sources)}. Temperature chip row: {chips}."
    if mode == SLOPE_MODE_PROVIDED:
        provided = _sanitize_entity_ids(slope.get("provided_sensors", []))
        sources = _sanitize_entity_ids(slope.get("source_entities", []))
        chips = "enabled" if slope.get(CONF_SHOW_TEMPERATURE_CHIPS) else "disabled"
        return (
            f"Mode: Provided slope sensors. "
            f"Provided sensors: {len(provided)}. Source temperature sensors: {len(sources)}. "
            f"Temperature chip row: {chips}."
        )
    chips = "enabled" if slope.get(CONF_SHOW_TEMPERATURE_CHIPS) else "disabled"
    return f"Mode: Slope disabled. Temperature chip row: {chips}."


def _render_zones_summary(
    zones: Dict[str, Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Human-readable summary of zone output levels for config flow pages."""
    if not zones:
        return "No zones configured yet."
    lines: List[str] = []
    for zone_key in ("zone1", "zone2"):
        zone = zones.get(zone_key)
        if not zone:
            continue
        enabled = "on" if zone.get("enabled") else "off"
        level = _level_choice_label(zone.get("level"), config) if zone.get("level") else "unset"
        normal_level = _fan_level_label(zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT))
        boost_level = _fan_level_label(zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT))
        ui_label = _sanitize_ui_label(zone.get("ui_label"), _default_zone_ui_label(zone_key))
        boost_warning = _boost_level_warning(zone.get("output_level"), zone.get("boost_output_level"))
        warning_suffix = f" Warning: {boost_warning}" if boost_warning else ""
        lines.append(
            f"- {zone_key.upper()}: {enabled}, {level}, label '{ui_label}', normal {normal_level}, boost {boost_level}.{warning_suffix}"
        )
    return "\n".join(lines) if lines else "No zones configured yet."


def _render_humidifiers_summary(
    humidifiers: Dict[str, Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> str:
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
            f"- {_level_choice_label(level, config)}: {enabled}, band adjust {band_adjust}%, outputs: {output_summary}"
        )
    return "\n".join(lines)


def _render_aq_summary(
    aq: Dict[str, Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> str:
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
            f"- {_level_choice_label(level, config)}: {enabled}, triggers [{trigger_summary}], outputs [{output_summary}], level {level_txt}, run {run_duration} min"
        )
    return "\n".join(lines)


def _render_existing_telemetry(
    telemetry: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    if not telemetry:
        return "None yet."
    lines = []
    for item in telemetry:
        ent = item.get("entity_id") or "unknown"
        room = item.get("room") or ent
        display = room
        level = _level_choice_label(item.get("level"), config or {})
        stype = item.get("sensor_type")
        lines.append(f"- {display} ({level}): {stype} ({ent})")
    return "\n".join(lines)


def _telemetry_options(telemetry: List[Dict[str, Any]]) -> List[SelectOptionDict]:
    options: List[SelectOptionDict] = []
    for idx, item in enumerate(telemetry):
        options.append(SelectOptionDict(value=str(idx), label=_telemetry_label(item)))
    return options


def _telemetry_label(item: Dict[str, Any]) -> str:
    ent = item.get("entity_id") or "unknown"
    room = item.get("room") or ent
    display = room
    stype = str(item.get("sensor_type") or "sensor").replace("_", " ").title()
    return f"{display} ({stype}) - {ent}"


def _zone_choice_label(
    zone_key: str,
    zone: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    title = _zone_title(zone_key)
    level = _level_choice_label(zone.get("level"), config)
    enabled = "Enabled" if zone.get("enabled") else "Disabled"
    ui_label = _sanitize_ui_label(zone.get("ui_label"), _default_zone_ui_label(zone_key))
    return f"{title} - {enabled} ({level}, UI label: {ui_label})"


def _zone_title(zone_key: str) -> str:
    if zone_key == "zone1":
        return "Zone 1"
    if zone_key == "zone2":
        return "Zone 2"
    return str(zone_key or "Zone")


def _default_zone_level(zone_key: str) -> str:
    if zone_key == "zone2":
        return "level2"
    return "level1"


def _level_value_label_options(
    config: Optional[Dict[str, Any]] = None,
) -> List[SelectOptionDict]:
    labels = resolve_level_labels(config or {})
    return [
        SelectOptionDict(
            value=item["value"],
            label=labels.get(item["value"], item["label"]),
        )
        for item in LEVELS
    ]


def _level_choice_label(
    level: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    return resolve_level_label(level, config or {})


def _alert_option_label(idx: int, alert: Dict[str, Any]) -> str:
    trigger = str(alert.get("trigger_type") or "unknown")
    trigger_label = ALERT_TRIGGER_DEFS.get(trigger, {}).get("label", trigger.replace("_", " ").title())
    enabled = "Enabled" if alert.get("enabled", True) else "Disabled"
    room_scope = _sanitize_optional_room_scope(alert.get("room"))
    room_suffix = f" in {room_scope}" if room_scope else ""
    return f"Indicator {idx + 1} - {trigger_label}{room_suffix} ({enabled})"


def _setup_assist_defaults(
    hass: HomeAssistant,
    entity_id: str | None = None,
) -> tuple[str, str, str]:
    suggestion = setup_assist_suggestion(hass, entity_id)
    return suggestion.room, suggestion.level, setup_assist_advisory_text(suggestion)


def _is_setup_assist_preview_input(user_input: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(user_input, dict):
        return False
    if not _sanitize_optional_entity_id(user_input.get("entity_id")):
        return False
    if user_input.get("action") == FORM_ACTION_PREVIEW:
        return True
    explicit_fields = {
        "sensor_type",
        "friendly_name",
        "level",
        "room",
    }
    return not any(field in user_input for field in explicit_fields)


def _room_select_options(*extra_rooms: Any) -> List[SelectOptionDict]:
    rooms: List[str] = []
    seen = set()
    for room in [*COMMON_ROOMS, *extra_rooms]:
        text = str(room or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        rooms.append(text)
    return [
        SelectOptionDict(value=room, label=room)
        for room in sorted(rooms, key=str.casefold)
    ]


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
    return [item["value"] for item in LEVELS if any(
        entry.get("sensor_type") in aq_types and entry.get("level") == item["value"]
        for entry in telemetry
    )]


def _aq_editable_threshold(trig: str, value: Any) -> float | None:
    """Present a saved threshold only when the native number control can edit it."""
    number = _finite_float(value)
    bounds = AQ_TRIGGER_DEFS[trig]
    return number if number is not None and bounds["min"] <= number <= bounds["max"] else None


def _aq_threshold_note(trig: str, value: Any) -> str:
    """Describe a numeric legacy value without interpolating arbitrary stored text."""
    label = AQ_TRIGGER_DEFS[trig]["label"]
    number = _finite_float(value)
    if number is None:
        return f"{label}: no usable saved value. The editor suggests a default."
    unit = AQ_CANONICAL_UNITS[AQ_TRIGGER_SPECS[trig]["sensor_type"]]
    if _aq_editable_threshold(trig, number) is None:
        return f"{label}: saved {number} {unit} is outside the editable range. Confirm to replace it."
    return f"{label}: saved value {number} {unit}."


def _aq_threshold_selector(trig: str) -> selector.NumberSelector:
    bounds = AQ_TRIGGER_DEFS[trig]
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=bounds["min"], max=bounds["max"], step=bounds.get("step", 1),
        mode=selector.NumberSelectorMode.SLIDER,
        unit_of_measurement=AQ_CANONICAL_UNITS[AQ_TRIGGER_SPECS[trig]["sensor_type"]],
    ))


def _zone_trigger_context_label(
    level: str,
    zone_key: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    level_label = _level_choice_label(level, config)
    if zone_key:
        return f"{_zone_title(zone_key)} / {level_label}"
    return level_label


def _zone_trigger_options(
    level: str,
    zone_key: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[SelectOptionDict]:
    opts = []
    for key, trig in TRIGGER_DEFS.items():
        label = f"{trig['label']} ({_zone_trigger_context_label(level, zone_key, config)})"
        opts.append(SelectOptionDict(value=key, label=label))
    return opts


def _aq_trigger_options(
    level: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[SelectOptionDict]:
    opts = []
    for key, trig in AQ_TRIGGER_DEFS.items():
        label = f"{trig['label']} ({_level_choice_label(level, config)})"
        opts.append(SelectOptionDict(value=key, label=label))
    return opts


def _normalize_target_profile(value: Any) -> str:
    raw = str(value or "auto").strip().lower()
    allowed = {item["value"] for item in TARGET_PROFILE_OPTIONS}
    if raw in allowed:
        return raw
    return "auto"


def _normalize_temperature_comfort_mode(value: Any) -> str:
    raw = str(value or DEFAULT_TEMPERATURE_COMFORT_MODE).strip().lower()
    allowed = {item["value"] for item in TEMPERATURE_COMFORT_PROFILE_OPTIONS}
    if raw in allowed:
        return raw
    return DEFAULT_TEMPERATURE_COMFORT_MODE


def _bounded_float(value: Any, min_value: float, max_value: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(float(min_value), min(float(max_value), parsed))


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


def _config_fan_level_rank(value: Any) -> int:
    normalized = _normalize_fan_level_choice(value, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        return 0
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return 0


def _boost_level_warning(normal_level: Any, boost_level: Any) -> str:
    if _config_fan_level_rank(boost_level) <= _config_fan_level_rank(normal_level):
        return (
            "Boost settings should normally be higher than the standard zone fan level. "
            "Zone control handles normal correction; boost is reserved for danger escalation "
            "such as condensation, mould risk, or humidity danger."
        )
    return ""


def _boost_guidance_for_zone(zone: Dict[str, Any]) -> str:
    normal_level = zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT)
    boost_level = zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT)
    warning = _boost_level_warning(normal_level, boost_level)
    guidance = (
        "Boost settings should normally be higher than the standard zone fan level. "
        "Zone control handles normal correction; boost is reserved for danger escalation "
        "such as condensation, mould risk, or humidity danger."
    )
    if warning:
        return f"{guidance}\n\nWarning: current boost is not higher than the normal zone fan level."
    return guidance


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
