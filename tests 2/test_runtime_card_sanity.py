"""Regression sanity checks for HI runtime lane ordering and card rendering."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MethodType, SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "humidity_intelligence"
ENTRY_ID = "entry123"
PKG = "hi_testpkg"

PUBLIC_CARD_SURFACES = (
    INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
    INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
    ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
    ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    ROOT / "tmp_out" / "v2_mobile.yaml",
    ROOT / "tmp_out" / "v2_tablet.yaml",
    INTEGRATION_ROOT / "ui" / "_sensor_ids.txt",
    INTEGRATION_ROOT / "ui" / "register.py",
    ROOT / "tests 2" / "test_slope_sanity.py",
)

PRIVATE_CARD_IDENTIFIERS = (
    "alarm_control_panel.private_fixture_alarm_a",
    "person.private_fixture_person_a",
    "person.private_fixture_person_b",
    "device_tracker.private_fixture_phone_a",
    "sensor.private_fixture_room_humidity_a",
    "sensor.private_fixture_room_humidity_b",
    "sensor.private_fixture_room_temperature_a",
    "sensor.private_fixture_room_temperature_b",
    "sensor.private_fixture_zone_temperature_a",
    "Room Private Fixture A",
)

OUTPUT_DETAILS_SURFACES = (
    INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
    INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
    ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
    ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
)
V2_REASON_SURFACES = OUTPUT_DETAILS_SURFACES

OUTPUT_EXPANDER_TOGGLE_ACTION = """      tap_action:
        action: call-service
        service: switch.toggle
        service_data:
          entity_id: input_boolean.air_control_output_expanded"""
V207_CONTROL_TOGGLE_ACTION = """          tap_action:
            action: toggle"""
V207_CONTROL_TOGGLE_ENTITIES = (
    "input_boolean.air_control_enabled",
    "input_boolean.air_control_manual_override",
)


def _output_details_block(source: str) -> str:
    start = source.index("# hi:output-details:start")
    end = source.index("# hi:output-details:end", start)
    return source[start:end]


def _v2_reason_block(source: str) -> str:
    start = source.index("        reason: |\n")
    end = source.index("        aq: |\n", start)
    return source[start:end]


def _strip_allowed_output_expander_toggle(source: str) -> str:
    try:
        block = _output_details_block(source)
    except ValueError:
        return source
    stripped = block.replace(OUTPUT_EXPANDER_TOGGLE_ACTION, "")
    return source.replace(block, stripped)


def _button_card_block(source: str, entity_id: str) -> str:
    entity_marker = f"entity: {entity_id}"
    entity_index = source.index(entity_marker)
    start = source.rfind("        - type: custom:button-card", 0, entity_index)
    if start == -1:
        start = entity_index
    next_start = source.find("        - type: custom:button-card", entity_index + len(entity_marker))
    if next_start == -1:
        next_start = len(source)
    return source[start:next_start]


def _strip_allowed_v207_control_toggles(source: str) -> str:
    for entity_id in V207_CONTROL_TOGGLE_ENTITIES:
        try:
            block = _button_card_block(source, entity_id)
        except ValueError:
            continue
        stripped = block.replace(V207_CONTROL_TOGGLE_ACTION, "")
        source = source.replace(block, stripped)
    return source


def _install_homeassistant_stubs(*, include_unit_ratio: bool = True) -> None:
    """Install lightweight Home Assistant stubs into sys.modules."""
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    config_entries = types.ModuleType("homeassistant.config_entries")
    const = types.ModuleType("homeassistant.const")
    components = types.ModuleType("homeassistant.components")
    diagnostics_mod = types.ModuleType("homeassistant.components.diagnostics")
    sensor_mod = types.ModuleType("homeassistant.components.sensor")
    binary_sensor_mod = types.ModuleType("homeassistant.components.binary_sensor")
    lovelace = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    event = types.ModuleType("homeassistant.helpers.event")
    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_helper = types.ModuleType("homeassistant.helpers.entity")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    util = types.ModuleType("homeassistant.util")
    util_dt = types.ModuleType("homeassistant.util.dt")
    voluptuous = types.ModuleType("voluptuous")

    class HomeAssistant:
        pass

    class ServiceCall:
        def __init__(self, data=None):
            self.data = data or {}

    class ConfigEntry:
        pass

    class HomeAssistantError(Exception):
        pass

    class Entity:
        pass

    def async_generate_entity_id(_format_string, suggested_object_id, hass=None):
        return f"sensor.{suggested_object_id}"

    class SensorEntity(Entity):
        pass

    class BinarySensorEntity(Entity):
        pass

    class DeviceInfo(dict):
        pass

    class SensorDeviceClass:
        TEMPERATURE = "temperature"

    class SensorStateClass:
        MEASUREMENT = "measurement"

    class UnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    class UnitOfRatio(StrEnum):
        PERCENTAGE = "%"

    class Invalid(Exception):
        pass

    ALLOW_EXTRA = object()
    PREVENT_EXTRA = object()
    _NO_DEFAULT = object()

    class _SchemaKey:
        def __init__(self, key, default=_NO_DEFAULT):
            self.key = key
            self.default = default

        def __hash__(self):
            try:
                return hash((self.key, self.default))
            except TypeError:
                return hash((self.key, repr(self.default)))

    class Schema:
        def __init__(self, schema, extra=PREVENT_EXTRA):
            self.schema = schema
            self.extra = extra

        def __call__(self, value):
            if not isinstance(self.schema, dict):
                return value
            if not isinstance(value, dict):
                raise Invalid("schema value must be a mapping")

            declared_keys = {
                key_spec.key if isinstance(key_spec, _SchemaKey) else key_spec
                for key_spec in self.schema
            }
            unexpected_keys = set(value) - declared_keys
            if unexpected_keys and self.extra is not ALLOW_EXTRA:
                raise Invalid(
                    f"extra keys not allowed: {sorted(unexpected_keys)!r}"
                )

            validated = dict(value) if self.extra is ALLOW_EXTRA else {}
            for key_spec, validator in self.schema.items():
                key = key_spec.key if isinstance(key_spec, _SchemaKey) else key_spec
                if key in value:
                    item = value[key]
                elif isinstance(key_spec, _SchemaKey) and key_spec.default is not _NO_DEFAULT:
                    item = key_spec.default
                else:
                    continue
                validated[key] = validator(item) if callable(validator) else item
            return validated

    def _ensure_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [value]

    def _coerce(kind):
        return lambda value: kind(value)

    def _range(min=None, max=None):
        def validate(value):
            if min is not None and value < min:
                raise Invalid("value below range")
            if max is not None and value > max:
                raise Invalid("value above range")
            return value

        return validate

    def _all(*validators):
        def validate(value):
            for validator in validators:
                value = validator(value)
            return value

        return validate

    def _any(*validators):
        def validate(value):
            for validator in validators:
                if validator is None and value is None:
                    return value
                if callable(validator):
                    try:
                        return validator(value)
                    except Exception:
                        continue
            raise Invalid("no validator accepted value")

        return validate

    def async_track_state_change_event(*args, **kwargs):
        return lambda: None

    def async_track_time_interval(*args, **kwargs):
        return lambda: None

    def async_track_point_in_utc_time(*args, **kwargs):
        return lambda: None

    def async_redact_data(data, to_redact):
        redact = {str(item).lower() for item in to_redact}

        def redact_value(value):
            if isinstance(value, dict):
                return {
                    key: "[REDACTED]" if str(key).lower() in redact else redact_value(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact_value(item) for item in value]
            return value

        return redact_value(data)

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall
    core.callback = lambda func: func
    config_entries.ConfigEntry = ConfigEntry
    exceptions.HomeAssistantError = HomeAssistantError
    const.UnitOfTemperature = UnitOfTemperature
    const.PERCENTAGE = "%"
    const.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    if include_unit_ratio:
        const.UnitOfRatio = UnitOfRatio
    sensor_mod.SensorEntity = SensorEntity
    sensor_mod.SensorDeviceClass = SensorDeviceClass
    sensor_mod.SensorStateClass = SensorStateClass
    binary_sensor_mod.BinarySensorEntity = BinarySensorEntity
    lovelace_const.LOVELACE_DATA = "lovelace"
    diagnostics_mod.async_redact_data = async_redact_data
    config_validation.entity_id = str
    config_validation.entity_ids = _ensure_list
    config_validation.ensure_list = _ensure_list
    config_validation.string = str
    event.async_track_state_change_event = async_track_state_change_event
    event.async_track_time_interval = async_track_time_interval
    event.async_track_point_in_utc_time = async_track_point_in_utc_time
    device_registry.DeviceInfo = DeviceInfo
    entity_helper.Entity = Entity
    entity_helper.async_generate_entity_id = async_generate_entity_id
    entity_registry.async_get = lambda hass: None
    issue_registry.IssueSeverity = SimpleNamespace(WARNING="warning")
    issue_registry.async_create_issue = lambda *_args, **_kwargs: None
    issue_registry.async_delete_issue = lambda *_args, **_kwargs: None
    helpers.issue_registry = issue_registry
    util.slugify = lambda value: str(value).lower().replace(" ", "_")
    util_dt.now = lambda: datetime.now().astimezone()
    util_dt.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = util_dt
    voluptuous.Schema = Schema
    voluptuous.Optional = _SchemaKey
    voluptuous.Required = _SchemaKey
    voluptuous.Invalid = Invalid
    voluptuous.Coerce = _coerce
    voluptuous.Range = _range
    voluptuous.All = _all
    voluptuous.Any = _any
    voluptuous.ALLOW_EXTRA = ALLOW_EXTRA
    voluptuous.PREVENT_EXTRA = PREVENT_EXTRA

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.diagnostics"] = diagnostics_mod
    sys.modules["homeassistant.components.sensor"] = sensor_mod
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_mod
    sys.modules["homeassistant.components.lovelace"] = lovelace
    sys.modules["homeassistant.components.lovelace.const"] = lovelace_const
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.entity"] = entity_helper
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = util_dt
    sys.modules["voluptuous"] = voluptuous


def _install_package_scaffold() -> None:
    """Create importable package namespace used for file-based module loading."""
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    for sub in ("automations", "ui", "helpers", "sensors"):
        mod = types.ModuleType(f"{PKG}.{sub}")
        mod.__path__ = [str(INTEGRATION_ROOT / sub)]
        sys.modules[f"{PKG}.{sub}"] = mod

    services = types.ModuleType(f"{PKG}.services")

    async def async_flash_lights_for_alert(hass, **kwargs):
        hass.data.setdefault("_trusted_visual_alert_calls", []).append(dict(kwargs))

    services.async_flash_lights_for_alert = async_flash_lights_for_alert
    sys.modules[f"{PKG}.services"] = services


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_target_modules():
    _install_homeassistant_stubs()
    _install_package_scaffold()

    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    level_labels_path = INTEGRATION_ROOT / "helpers" / "level_labels.py"
    if level_labels_path.exists():
        _load_module(f"{PKG}.helpers.level_labels", level_labels_path)
    engine_mod = _load_module(f"{PKG}.automations.engine", INTEGRATION_ROOT / "automations" / "engine.py")
    register_mod = _load_module(f"{PKG}.ui.register", INTEGRATION_ROOT / "ui" / "register.py")
    return engine_mod, register_mod


def _load_services_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PKG}.helpers.cleanup", INTEGRATION_ROOT / "helpers" / "cleanup.py")
    _load_module(
        f"{PKG}.helpers.report_exports",
        INTEGRATION_ROOT / "helpers" / "report_exports.py",
    )
    level_labels_path = INTEGRATION_ROOT / "helpers" / "level_labels.py"
    if level_labels_path.exists():
        _load_module(f"{PKG}.helpers.level_labels", level_labels_path)
    return _load_module(f"{PKG}.services", INTEGRATION_ROOT / "services.py")


def _load_sensor_platform_module():
    services_mod = _load_services_module()

    drift_repairs_mod = types.ModuleType(f"{PKG}.helpers.drift_repairs")

    async def async_noop(*_args, **_kwargs):
        return None

    drift_repairs_mod.async_update_humidity_drift_repair_issue = async_noop
    sys.modules[f"{PKG}.helpers.drift_repairs"] = drift_repairs_mod

    core_mod = types.ModuleType(f"{PKG}.sensors.core")
    core_mod.build_entities = lambda *_args, **_kwargs: ([], [], [])
    sys.modules[f"{PKG}.sensors.core"] = core_mod

    slope_mod = types.ModuleType(f"{PKG}.sensors.slope")
    slope_mod.build_slope_entities = lambda *_args, **_kwargs: ([], [], {})
    sys.modules[f"{PKG}.sensors.slope"] = slope_mod

    sys.modules[f"{PKG}.services"] = services_mod
    return _load_module(f"{PKG}.sensor", INTEGRATION_ROOT / "sensor.py")


def _load_integration_init_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")

    sys.modules[
        "homeassistant.helpers.config_validation"
    ].config_entry_only_config_schema = lambda _domain: {}
    sys.modules["homeassistant.helpers.event"].async_call_later = (
        lambda _hass, _delay, _callback: lambda: None
    )

    async def async_noop(*_args, **_kwargs):
        return None

    services_mod = sys.modules[f"{PKG}.services"]
    services_mod.SERVICE_REFRESH_UI = "refresh_ui"
    services_mod.async_export_cards_to_owned_ui = async_noop
    services_mod.async_register_services = async_noop
    services_mod.async_unregister_services = async_noop

    cleanup_mod = types.ModuleType(f"{PKG}.helpers.cleanup")
    cleanup_mod.list_owned_ui_filenames = lambda *_args, **_kwargs: []
    sys.modules[f"{PKG}.helpers.cleanup"] = cleanup_mod
    sys.modules[f"{PKG}.helpers"].cleanup = cleanup_mod

    report_exports_mod = types.ModuleType(f"{PKG}.helpers.report_exports")
    report_exports_mod.ReportExportError = RuntimeError
    report_exports_mod.plan_owned_ui_export_removal = lambda *_args: []
    report_exports_mod.remove_owned_ui_export = lambda *_args: True
    sys.modules[f"{PKG}.helpers.report_exports"] = report_exports_mod
    sys.modules[f"{PKG}.helpers"].report_exports = report_exports_mod

    drift_mod = types.ModuleType(f"{PKG}.helpers.drift_repairs")
    drift_mod.async_update_humidity_drift_repair_issue = async_noop
    sys.modules[f"{PKG}.helpers.drift_repairs"] = drift_mod
    sys.modules[f"{PKG}.helpers"].drift_repairs = drift_mod

    entity_registry_mod = types.ModuleType(f"{PKG}.helpers.entity_registry")
    entity_registry_mod.normalize_pm25_aggregate_entity_ids = (
        lambda _hass, _entry_id: {"changed": {}, "blocked": []}
    )
    sys.modules[f"{PKG}.helpers.entity_registry"] = entity_registry_mod
    sys.modules[f"{PKG}.helpers"].entity_registry = entity_registry_mod

    register_mod = types.ModuleType(f"{PKG}.ui.register")
    register_mod.async_register_cards = async_noop
    register_mod.async_build_entity_mapping = async_noop
    sys.modules[f"{PKG}.ui.register"] = register_mod
    sys.modules[f"{PKG}.ui"].register = register_mod

    automations_mod = sys.modules[f"{PKG}.automations"]
    automations_mod.async_setup_entry = async_noop
    automations_mod.async_unload_entry = async_noop

    return _load_module(f"{PKG}.integration_init", INTEGRATION_ROOT / "__init__.py")


def _load_core_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    return _load_module(f"{PKG}.sensors.core", INTEGRATION_ROOT / "sensors" / "core.py")


def _load_core_module_without_unit_ratio():
    _install_homeassistant_stubs(include_unit_ratio=False)
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    return _load_module(f"{PKG}.sensors.core", INTEGRATION_ROOT / "sensors" / "core.py")


def _load_entity_registry_helper_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    return _load_module(
        f"{PKG}.helpers.entity_registry",
        INTEGRATION_ROOT / "helpers" / "entity_registry.py",
    )


def _load_frontend_dependencies_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    return _load_module(
        f"{PKG}.helpers.frontend_dependencies",
        INTEGRATION_ROOT / "helpers" / "frontend_dependencies.py",
    )


def _install_issue_registry_stub(events):
    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")

    class IssueSeverity:
        WARNING = "warning"

    def async_create_issue(hass, domain, issue_id, **kwargs):
        events.append(("create", domain, issue_id, kwargs))

    def async_delete_issue(hass, domain, issue_id):
        events.append(("delete", domain, issue_id, {}))

    issue_registry.IssueSeverity = IssueSeverity
    issue_registry.async_create_issue = async_create_issue
    issue_registry.async_delete_issue = async_delete_issue
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is not None:
        helpers.issue_registry = issue_registry


class _FakeState:
    def __init__(self, state, attrs=None):
        self.state = str(state)
        self.attributes = attrs or {}


class _FakeStates:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, entity_id):
        return self._values.get(entity_id)

    def is_state(self, entity_id, state):
        st = self._values.get(entity_id)
        return bool(st and st.state == state)


class _FakeServices:
    def __init__(self):
        self.calls = []

    def has_service(self, domain, service):
        return True

    async def async_call(self, domain, service, data=None, blocking=False):
        self.calls.append((domain, service, dict(data or {}), bool(blocking)))


class _FlashServiceRegistry:
    def __init__(self, states):
        self.states = states
        self.calls = []
        self.handler_calls = []
        self.handlers = {}
        self.schemas = {}

    def has_service(self, domain, service):
        return True

    def async_register(self, domain, service, handler, schema=None):
        self.handlers[(domain, service)] = handler
        self.schemas[(domain, service)] = schema

    async def async_call(self, domain, service, data=None, blocking=False):
        payload = dict(data or {})
        handler = self.handlers.get((domain, service))
        if handler is not None:
            schema = self.schemas.get((domain, service))
            if schema is not None:
                payload = schema(payload)
            self.handler_calls.append((domain, service, payload))
            await handler(SimpleNamespace(data=payload, context=None))
            return

        self.calls.append((domain, service, payload, bool(blocking)))
        if domain == "light":
            entity_id = payload.get("entity_id")
            current = self.states.get(entity_id)
            attrs = dict(current.attributes) if current is not None else {}
            if service == "turn_on":
                attrs.update({key: value for key, value in payload.items() if key != "entity_id"})
                self.states._values[entity_id] = _FakeState("on", attrs)
            elif service == "turn_off":
                self.states._values[entity_id] = _FakeState("off", attrs)


class _FlashHass:
    def __init__(self, states):
        self.states = _FakeStates(states)
        self.services = _FlashServiceRegistry(self.states)
        self.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
        self.data = {}


class _FakeBool:
    def __init__(self, initial=False):
        self.is_on = bool(initial)
        self.on_calls = 0
        self.off_calls = 0

    async def async_turn_on(self):
        self.on_calls += 1
        self.is_on = True

    async def async_turn_off(self):
        self.off_calls += 1
        self.is_on = False


class _FakeTimer:
    def __init__(self):
        self.native_value = "idle"
        self.start_calls = 0
        self.cancel_calls = 0

    async def async_start(self, duration):
        self.start_calls += 1
        self.native_value = "active"

    async def async_cancel(self):
        self.cancel_calls += 1
        self.native_value = "idle"


class _FakeAuth:
    def __init__(self, users):
        self._users = dict(users)

    async def async_get_user(self, user_id):
        return self._users.get(user_id)


class _FakeConfigEntries:
    def __init__(self, entry):
        self._entry = entry

    def async_get_entry(self, entry_id):
        return self._entry if entry_id == self._entry.entry_id else None

    def async_entries(self, _domain):
        return [self._entry]


class _FakeRegistry:
    def async_get_entity_id(self, domain, _integration, unique_id):
        suffix = unique_id.split("_", 2)[-1]
        return f"{domain}.hi_{suffix}"


class _FakeRegistryMissingUniqueIds:
    def __init__(self, missing_unique_ids):
        self._missing = set(missing_unique_ids)

    def async_get_entity_id(self, domain, _integration, unique_id):
        if unique_id in self._missing:
            return None
        suffix = unique_id.split("_", 2)[-1]
        return f"{domain}.hi_{suffix}"


class _FakeHass:
    def __init__(self, entry, states):
        self.services = _FakeServices()
        self.states = _FakeStates(states)
        self.config_entries = _FakeConfigEntries(entry)
        self.data = {
            "humidity_intelligence": {
                entry.entry_id: {
                    "hi_input_booleans": {
                        "air_control_enabled": _FakeBool(True),
                        "air_control_manual_override": _FakeBool(False),
                        "air_isolate_fan_outputs": _FakeBool(False),
                        "air_isolate_humidifier_outputs": _FakeBool(False),
                        "air_co_emergency_active": _FakeBool(False),
                        "air_downstairs_humidifier_active": _FakeBool(False),
                        "air_upstairs_humidifier_active": _FakeBool(False),
                        "air_aq_downstairs_active": _FakeBool(False),
                        "air_aq_upstairs_active": _FakeBool(False),
                        "air_alert_1_active": _FakeBool(False),
                        "air_alert_2_active": _FakeBool(False),
                        "air_alert_3_active": _FakeBool(False),
                        "air_alert_4_active": _FakeBool(False),
                        "air_alert_5_active": _FakeBool(False),
                    },
                    "hi_timers": {
                        "air_control_pause": _FakeTimer(),
                        "air_aq_downstairs_run": _FakeTimer(),
                        "air_aq_upstairs_run": _FakeTimer(),
                    },
                }
            }
        }

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _NoStringResource(dict):
    def __str__(self):
        raise AssertionError("resource objects must not be stringified")

    def __repr__(self):
        raise AssertionError("resource objects must not be stringified")


class _FakeLovelaceResources:
    def __init__(self, items, *, loaded=False, load_error=None):
        self._items = list(items)
        self.loaded = loaded
        self.load_error = load_error
        self.load_calls = 0
        self.items_calls = 0

    async def async_load(self):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def async_items(self):
        self.items_calls += 1
        return list(self._items)


class _DumpCardsConfig:
    def __init__(self, root):
        self._root = pathlib.Path(root)

    def path(self, *parts):
        return str(self._root.joinpath(*parts))


class _DumpCardsConfigEntries:
    def __init__(self, entries):
        self._entries = list(entries)

    def async_get_entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    def async_entries(self, _domain):
        return list(self._entries)


class _DumpCardsHass:
    def __init__(self, tmpdir, entries, cards_by_entry):
        self.config = _DumpCardsConfig(tmpdir)
        self.config_entries = _DumpCardsConfigEntries(entries)
        self.data = {
            "humidity_intelligence": {
                entry_id: {"cards": cards}
                for entry_id, cards in cards_by_entry.items()
            }
        }

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _wrap_async_method(obj, method_name: str, trace: list[str]) -> None:
    original = getattr(obj, method_name)

    async def wrapped(self, *args, **kwargs):
        if method_name == "_handle_zone_by_key" and args:
            trace.append(f"{method_name}:{args[0]}")
        else:
            trace.append(method_name)
        return await original(*args, **kwargs)

    setattr(obj, method_name, MethodType(wrapped, obj))


def _base_entry_data():
    return {
        "target_profile": "winter",
        "telemetry": [
            {"entity_id": "sensor.kitchen_h", "sensor_type": "humidity", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.hall_h", "sensor_type": "humidity", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.bed_h", "sensor_type": "humidity", "level": "level2", "room": "Bedroom"},
            {"entity_id": "sensor.kitchen_t", "sensor_type": "temperature", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.hall_t", "sensor_type": "temperature", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.bed_t", "sensor_type": "temperature", "level": "level2", "room": "Bedroom"},
            {"entity_id": "sensor.l1_iaq", "sensor_type": "iaq", "level": "level1", "room": "Hallway"},
            {"entity_id": "sensor.co_val", "sensor_type": "co", "level": "level1", "room": "Kitchen"},
        ],
        "zones": {
            "zone1": {
                "enabled": True,
                "level": "level1",
                "rooms": ["Kitchen"],
                "outputs": ["fan.zone1"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 5},
                "ui_label": "Cooking",
            },
            "zone2": {
                "enabled": True,
                "level": "level2",
                "rooms": ["Bedroom"],
                "outputs": ["fan.zone2"],
                "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 2},
                "ui_label": "Bathroom",
            },
        },
        "humidifiers": {
            "level1": {"enabled": True, "outputs": ["humidifier.l1"], "band_adjust": 0},
        },
        "aq": {
            "level1": {
                "enabled": True,
                "outputs": ["fan.aq1"],
                "triggers": ["iaq_bad"],
                "thresholds": {"iaq_bad": 75},
                "output_level": 66,
                "run_duration": 10,
            }
        },
        "alerts": [
            {
                "enabled": True,
                "trigger_type": "humidity_danger",
                "room": "Kitchen",
                "power_entity": "switch.alert_power",
                "lights": ["light.alert"],
                "flash_mode": "red",
                "duration": 10,
            }
        ],
    }


def _reported_idle_humidifier_truth():
    return {
        "schema": 1,
        "summary": {
            "requested_lanes": 0,
            "degraded_lanes": 0,
            "unknown_lanes": 0,
            "matched_outputs": 1,
            "retrying_outputs": 0,
            "faulted_outputs": 0,
            "degraded_outputs": 0,
            "unknown_outputs": 0,
            "isolated_outputs": 0,
            "ownership_conflicts": 0,
        },
        "outputs": {
            "output_1": {
                "domain": "humidifier",
                "owners": [],
                "configured_owners": ["level1"],
                "desired": "off",
                "observed": "off",
                "platform_action": "not_exposed",
                "reconciliation": "matched_off",
                "attempts": 0,
                "maximum_attempts": 3,
            }
        },
    }


def _minimal_humidity_entry():
    return SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "target_profile": "winter",
            "telemetry": [
                {
                    "entity_id": "sensor.kitchen_h",
                    "sensor_type": "humidity",
                    "level": "level1",
                    "room": "Kitchen",
                }
            ],
        },
        options={},
    )


def _find_sensor(sensors, unique_suffix):
    for sensor in sensors:
        if getattr(sensor, "_attr_unique_id", "").endswith(unique_suffix):
            return sensor
    raise AssertionError(f"sensor ending {unique_suffix!r} was not built")


def test_percentage_computed_sensors_use_home_assistant_unit_ratio_enumerator():
    core_mod = _load_core_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.hall_h": _FakeState(51),
            "sensor.bed_h": _FakeState(49),
            "sensor.kitchen_t": _FakeState(21),
            "sensor.hall_t": _FakeState(20),
            "sensor.bed_t": _FakeState(19),
        },
    )

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)
    percentage_suffixes = (
        "house_avg_humidity",
        "house_target_low",
        "house_target_high",
        "house_drift_7d",
        "air_control_kitchen_humidity_delta",
        "air_control_bathroom_humidity_delta",
        "room_bedroom_humidity_delta",
        "room_hallway_humidity_delta",
        "room_kitchen_humidity_delta",
        "level1_avg_humidity",
        "level1_target_low",
        "level1_target_high",
        "level2_avg_humidity",
        "level2_target_low",
        "level2_target_high",
    )

    for suffix in percentage_suffixes:
        assert (
            _find_sensor(sensors, suffix)._attr_native_unit_of_measurement
            is core_mod.UnitOfRatio.PERCENTAGE
        )


def test_percentage_computed_sensors_keep_legacy_unit_fallback_before_ha_20267():
    core_mod = _load_core_module_without_unit_ratio()
    entry = _minimal_humidity_entry()
    hass = _FakeHass(entry, {"sensor.kitchen_h": _FakeState(55)})

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)

    assert core_mod.UnitOfRatio.PERCENTAGE == "%"
    assert _find_sensor(sensors, "house_avg_humidity")._attr_native_unit_of_measurement == "%"


def test_house_humidity_drift_7d_reports_missing_statistics_dependency():
    core_mod = _load_core_module()
    entry = _minimal_humidity_entry()
    hass = _FakeHass(entry, {"sensor.kitchen_h": _FakeState(55)})

    sensors, _binary_sensors, sources = core_mod.build_entities(hass, entry)
    drift = _find_sensor(sensors, "house_drift_7d")

    assert "sensor.house_humidity_mean_7d" in sources
    assert drift._attr_native_value is None
    attrs = drift._attr_extra_state_attributes
    assert attrs["status"] == "unavailable"
    assert attrs["reason"] == "statistics_dependency_missing"
    assert attrs["required_dependency"] == "sensor.house_humidity_mean_7d"
    assert attrs["dependency_status"] == "missing"
    assert attrs["current_house_humidity"] == 55.0
    assert attrs["repair_kind"] == "missing_helper"
    assert attrs["repair_required"] is True
    assert attrs["history_status"] == "not_ready_or_unavailable"


def test_house_humidity_drift_dependency_status_marks_missing_helper_as_repair_required():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(entry, {"sensor.kitchen_h": _FakeState(55)})

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_entity"] == "sensor.house_humidity_mean_7d"
    assert status["dependency_status"] == "missing"
    assert status["repair_required"] is True
    assert status["repair_kind"] == "missing_helper"
    assert status["repair_issue_id"] == "house_humidity_mean_7d_missing"
    assert "Statistics helper" in status["repair_summary"]
    assert any("House Humidity Mean 7d" in step for step in status["repair_steps"])
    assert status["history_status"] == "not_ready_or_unavailable"


def test_house_humidity_drift_dependency_status_marks_existing_unknown_helper_as_not_ready():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState("unknown"),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "unknown"
    assert status["repair_required"] is False
    assert status["repair_kind"] == "helper_not_ready_or_unavailable"
    assert "create" not in status["repair_summary"].lower()
    assert status["history_status"] == "not_ready_or_unavailable"


def test_house_humidity_drift_dependency_status_marks_low_statistics_coverage_not_ready():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 0.03,
                    "source_value_valid": True,
                },
            ),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "history_not_ready"
    assert status["available"] is False
    assert status["repair_required"] is False
    assert status["repair_kind"] == "history_not_ready"
    assert status["dependency_state"] == "50"
    assert status["age_coverage_ratio"] == 0.03
    assert status["required_age_coverage_ratio"] == 0.85
    assert status["source_value_valid"] is True
    assert status["history_status"] == "not_ready_or_unavailable"
    assert "mean_7d" not in status


def test_house_humidity_drift_dependency_status_marks_existing_non_numeric_helper_as_misconfigured():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState("warming-up"),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "non_numeric"
    assert status["repair_required"] is False
    assert status["repair_kind"] == "helper_misconfigured_or_non_numeric"
    assert status["dependency_state"] == "warming-up"


def test_house_humidity_drift_dependency_status_marks_invalid_statistics_source_not_ready():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 1.0,
                    "source_value_valid": False,
                },
            ),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "source_not_valid"
    assert status["available"] is False
    assert status["repair_required"] is False
    assert status["repair_kind"] == "helper_source_not_valid"
    assert status["age_coverage_ratio"] == 1.0
    assert status["required_age_coverage_ratio"] == 0.85
    assert status["source_value_valid"] is False
    assert status["history_status"] == "not_ready_or_unavailable"
    assert "mean_7d" not in status


def test_house_humidity_drift_dependency_status_preserves_numeric_helper_contract():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(50),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "ok"
    assert status["available"] is True
    assert status["mean_7d"] == 50.0
    assert status["repair_required"] is False
    assert status["repair_kind"] == "none"


def test_house_humidity_drift_dependency_status_accepts_sufficient_statistics_coverage():
    _load_core_module()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 1.0,
                    "source_value_valid": True,
                },
            ),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["dependency_status"] == "ok"
    assert status["available"] is True
    assert status["mean_7d"] == 50.0
    assert status["age_coverage_ratio"] == 1.0
    assert status["required_age_coverage_ratio"] == 0.85
    assert status["source_value_valid"] is True
    assert status["repair_required"] is False
    assert status["repair_kind"] == "none"


def test_house_humidity_drift_dependency_status_reports_source_entity_status():
    _load_core_module()
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistry()
    drift_mod = sys.modules[f"{PKG}.helpers.drift"]
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState("unknown"),
            "sensor.hi_house_avg_humidity": _FakeState(55),
        },
    )

    status = drift_mod.humidity_drift_dependency_status(hass)

    assert status["source_entity"] == "sensor.hi_house_avg_humidity"
    assert status["source_entity_status"] == "ok"


def test_house_humidity_drift_7d_blocks_numeric_helper_until_statistics_coverage_ready():
    core_mod = _load_core_module()
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 0.03,
                    "source_value_valid": True,
                },
            ),
        },
    )

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)
    drift = _find_sensor(sensors, "house_drift_7d")

    assert drift._attr_native_value is None
    attrs = drift._attr_extra_state_attributes
    assert attrs["status"] == "unavailable"
    assert attrs["reason"] == "statistics_dependency_history_not_ready"
    assert attrs["dependency_status"] == "history_not_ready"
    assert attrs["age_coverage_ratio"] == 0.03
    assert attrs["required_age_coverage_ratio"] == 0.85
    assert attrs["source_value_valid"] is True
    assert attrs["repair_required"] is False
    assert attrs["repair_kind"] == "history_not_ready"


def test_drift_repair_issue_created_only_for_missing_helper():
    events = []
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _install_issue_registry_stub(events)
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PKG}.helpers.drift", INTEGRATION_ROOT / "helpers" / "drift.py")
    repairs_mod = _load_module(
        f"{PKG}.helpers.drift_repairs",
        INTEGRATION_ROOT / "helpers" / "drift_repairs.py",
    )
    entry = _minimal_humidity_entry()
    hass = _FakeHass(entry, {"sensor.kitchen_h": _FakeState(55)})

    asyncio.run(repairs_mod.async_update_humidity_drift_repair_issue(hass))

    assert events
    assert events[0][0] == "create"
    assert events[0][2] == "house_humidity_mean_7d_missing"
    assert events[0][3]["is_fixable"] is False
    assert events[0][3]["severity"] == "warning"


def test_drift_repair_issue_deleted_for_existing_not_ready_helper():
    events = []
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _install_issue_registry_stub(events)
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PKG}.helpers.drift", INTEGRATION_ROOT / "helpers" / "drift.py")
    repairs_mod = _load_module(
        f"{PKG}.helpers.drift_repairs",
        INTEGRATION_ROOT / "helpers" / "drift_repairs.py",
    )
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {"sensor.house_humidity_mean_7d": _FakeState("unknown")},
    )

    asyncio.run(repairs_mod.async_update_humidity_drift_repair_issue(hass))

    assert events == [
        (
            "delete",
            "humidity_intelligence",
            "house_humidity_mean_7d_missing",
            {},
        )
    ]


def test_house_humidity_drift_7d_preserves_valid_statistics_calculation():
    core_mod = _load_core_module()
    entry = _minimal_humidity_entry()
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(55),
            "sensor.house_humidity_mean_7d": _FakeState(50),
        },
    )

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)
    drift = _find_sensor(sensors, "house_drift_7d")

    assert drift._attr_native_value == 5.0
    assert drift._attr_extra_state_attributes == {}


async def _run_runtime_assertions(engine_mod) -> None:
    HIAutomationEngine = engine_mod.HIAutomationEngine

    # CO emergency preemption: must short-circuit lower lanes.
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass_co = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(75),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(68),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(16),
        },
    )
    engine_co = HIAutomationEngine(hass_co, entry)
    co_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_co, method, co_trace)
    await engine_co._evaluate()

    assert co_trace == []
    assert hass_co.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "co_emergency"

    # CO emergency should respect configured threshold, but use existing configured
    # ventilation outputs instead of alert-specific output overrides.
    entry_co_cfg_data = _base_entry_data()
    entry_co_cfg_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "co_emergency",
            "threshold": 20,
            "outputs": ["fan.legacy_co_only"],
            "lights": ["light.alert"],
            "power_entity": "switch.alert_power",
            "flash_mode": "red",
            "duration": 10,
        }
    ]
    entry_co_cfg = SimpleNamespace(entry_id=ENTRY_ID, data=entry_co_cfg_data, options={})
    hass_co_cfg = _FakeHass(
        entry_co_cfg,
        {
            "sensor.kitchen_h": _FakeState(60),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(60),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(21),  # above configured CO threshold (20)
        },
    )
    engine_co_cfg = HIAutomationEngine(hass_co_cfg, entry_co_cfg)
    await engine_co_cfg._evaluate()
    assert hass_co_cfg.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "co_emergency"
    co_percentage_outputs = {
        data.get("entity_id")
        for domain, service, data, _ in hass_co_cfg.services.calls
        if domain == "fan" and service == "set_percentage"
    }
    assert {"fan.zone1", "fan.zone2", "fan.aq1"} <= co_percentage_outputs
    assert "fan.legacy_co_only" not in co_percentage_outputs

    # Safe-threshold enforcement: CO emergency threshold is clamped to minimum safe value.
    # With threshold configured as 1 and CO at 8, emergency should not trigger.
    entry_co_guard_data = _base_entry_data()
    entry_co_guard_data["zones"]["zone1"]["enabled"] = False
    entry_co_guard_data["zones"]["zone2"]["enabled"] = False
    entry_co_guard_data["aq"] = {}
    entry_co_guard_data["humidifiers"] = {}
    entry_co_guard_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "co_emergency",
            "threshold": 1,  # below safe floor, should clamp up.
            "lights": ["light.alert"],
            "power_entity": "switch.alert_power",
            "flash_mode": "red",
            "duration": 10,
        }
    ]
    entry_co_guard = SimpleNamespace(entry_id=ENTRY_ID, data=entry_co_guard_data, options={})
    hass_co_guard = _FakeHass(
        entry_co_guard,
        {
            "sensor.kitchen_h": _FakeState(60),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(60),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(8),
        },
    )
    engine_co_guard = HIAutomationEngine(hass_co_guard, entry_co_guard)
    await engine_co_guard._evaluate()
    assert hass_co_guard.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") != "co_emergency"

    # CO clear is a timed safety hold. Once CO falls below the clear threshold,
    # the engine must schedule its own recheck at the clear deadline instead of
    # waiting for the normal periodic interval.
    entry_co_clear = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass_co_clear = _FakeHass(
        entry_co_clear,
        {
            "sensor.kitchen_h": _FakeState(60),
            "sensor.hall_h": _FakeState(60),
            "sensor.bed_h": _FakeState(60),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(16),
        },
    )
    engine_co_clear = HIAutomationEngine(hass_co_clear, entry_co_clear)
    await engine_co_clear._evaluate()
    assert hass_co_clear.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "co_emergency"

    hass_co_clear.states._values["sensor.co_val"] = _FakeState(0)
    await engine_co_clear._evaluate()
    assert engine_co_clear._co_below_since is not None
    assert engine_co_clear._co_clear_recheck_task is not None
    assert not engine_co_clear._co_clear_recheck_task.done()
    engine_co_clear._co_clear_recheck_task.cancel()
    try:
        await engine_co_clear._co_clear_recheck_task
    except asyncio.CancelledError:
        pass

    # Missing required humidity telemetry should stand down before lower-priority
    # lanes rather than presenting a normal/all-clear control state.
    entry_humidity_missing_data = _base_entry_data()
    entry_humidity_missing = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_humidity_missing_data,
        options={},
    )
    hass_humidity_missing = _FakeHass(
        entry_humidity_missing,
        {
            "sensor.kitchen_h": _FakeState("unavailable"),
            "sensor.hall_h": _FakeState("unavailable"),
            "sensor.bed_h": _FakeState("unavailable"),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(0),
        },
    )
    engine_humidity_missing = HIAutomationEngine(hass_humidity_missing, entry_humidity_missing)
    humidity_missing_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_humidity_missing, method, humidity_missing_trace)
    await engine_humidity_missing._evaluate()
    humidity_missing_data = hass_humidity_missing.data["humidity_intelligence"][ENTRY_ID]
    assert humidity_missing_trace == []
    assert humidity_missing_data.get("runtime_mode") == "telemetry_unavailable"
    assert humidity_missing_data.get("runtime_mode_display") == "TELEMETRY UNAVAILABLE"
    assert "Required humidity telemetry is unavailable" in humidity_missing_data.get("runtime_reason", "")

    entry_temperature_missing_data = _base_entry_data()
    entry_temperature_missing = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_temperature_missing_data,
        options={},
    )
    hass_temperature_missing = _FakeHass(
        entry_temperature_missing,
        {
            "sensor.kitchen_h": _FakeState(57),
            "sensor.hall_h": _FakeState(57),
            "sensor.bed_h": _FakeState(57),
            "sensor.kitchen_t": _FakeState("unavailable"),
            "sensor.hall_t": _FakeState("unavailable"),
            "sensor.bed_t": _FakeState("unavailable"),
            "sensor.l1_iaq": _FakeState(40),
            "sensor.co_val": _FakeState(0),
        },
    )
    engine_temperature_missing = HIAutomationEngine(hass_temperature_missing, entry_temperature_missing)
    temperature_missing_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_temperature_missing, method, temperature_missing_trace)
    await engine_temperature_missing._evaluate()
    temperature_missing_data = hass_temperature_missing.data["humidity_intelligence"][ENTRY_ID]
    assert temperature_missing_trace == []
    assert temperature_missing_data.get("runtime_mode") == "telemetry_unavailable"
    assert "Required temperature telemetry is unavailable" in temperature_missing_data.get("runtime_reason", "")

    # Alert lane is now exclusive: no humidifier/zone/AQ handling should run.
    entry2 = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry2,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine = HIAutomationEngine(hass, entry2)
    trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine, method, trace)
    await engine._evaluate()

    assert trace == ["_handle_alerts"]
    assert "_handle_aq" not in trace

    calls = hass.services.calls
    assert hass.data["_trusted_visual_alert_calls"]
    assert not hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 100
        for domain, service, data, _ in calls
    )
    assert not any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") in {"fan.zone2", "fan.aq1"}
        for domain, service, data, _ in calls
    )

    # Runtime mode priority should prefer alert while alert lane is active.
    assert hass.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    assert hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_alert_1_active"].is_on
    alert_switch = hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_alert_1_active"]
    assert alert_switch.on_calls == 1
    assert alert_switch.off_calls == 0
    alert_reason = hass.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "Alert response is active" in alert_reason
    assert "resolved zone" in alert_reason or "Degraded mode" in alert_reason
    await engine._evaluate()
    assert alert_switch.on_calls == 1
    assert alert_switch.off_calls == 0
    hass.states._values["sensor.kitchen_h"] = _FakeState(45)
    hass.states._values["sensor.hall_h"] = _FakeState(45)
    hass.states._values["sensor.bed_h"] = _FakeState(45)
    hass.states._values["sensor.l1_iaq"] = _FakeState(90)
    await engine._evaluate()
    assert alert_switch.on_calls == 1
    assert alert_switch.off_calls == 1
    assert hass.data["humidity_intelligence"][ENTRY_ID].get("active_alert_context") == "None"
    await engine._evaluate()
    assert alert_switch.on_calls == 1
    assert alert_switch.off_calls == 1

    # Room-scoped humidity danger alert should only trigger for the selected room.
    entry_room_alert_data = _base_entry_data()
    entry_room_alert_data["aq"] = {}
    entry_room_alert_data["humidifiers"] = {}
    entry_room_alert_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Kitchen",
            "lights": ["light.alert"],
            "duration": 10,
        }
    ]
    entry_room_alert = SimpleNamespace(entry_id=ENTRY_ID, data=entry_room_alert_data, options={})
    hass_room_alert = _FakeHass(
        entry_room_alert,
        {
            "sensor.kitchen_h": _FakeState(82),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_room_alert = HIAutomationEngine(hass_room_alert, entry_room_alert)
    await engine_room_alert._evaluate()
    assert hass_room_alert.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    room_alert_reason = hass_room_alert.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "Humidity Danger" in room_alert_reason
    assert "Kitchen" in room_alert_reason
    assert "sensor.kitchen_h" in room_alert_reason
    assert "resolved zone: Zone 1" in room_alert_reason
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_room_alert.services.calls
    )

    entry_zone_alert_data = _base_entry_data()
    entry_zone_alert_data["aq"] = {}
    entry_zone_alert_data["humidifiers"] = {}
    entry_zone_alert_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Kitchen",
            "lights": [],
        }
    ]
    entry_zone_alert = SimpleNamespace(entry_id=ENTRY_ID, data=entry_zone_alert_data, options={})
    hass_zone_alert = _FakeHass(
        entry_zone_alert,
        {
            "sensor.kitchen_h": _FakeState(72),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_zone_alert = HIAutomationEngine(hass_zone_alert, entry_zone_alert)
    await engine_zone_alert._evaluate()
    assert hass_zone_alert.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    assert hass_zone_alert.data["humidity_intelligence"][ENTRY_ID].get("active_alert_context") == (
        "Humidity Danger · Kitchen · Zone 1 · 72.0% >= 62% threshold"
    )
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_zone_alert.services.calls
    )

    # Alert hierarchy should beat zone priority: mould risk in Zone 2 outranks
    # condensation risk in Zone 1.
    entry_alert_hierarchy_data = _base_entry_data()
    entry_alert_hierarchy_data["target_profile"] = "custom"
    entry_alert_hierarchy_data["custom_target_low"] = 40
    entry_alert_hierarchy_data["custom_target_high"] = 79
    entry_alert_hierarchy_data["aq"] = {}
    entry_alert_hierarchy_data["humidifiers"] = {}
    entry_alert_hierarchy_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "condensation_risk",
            "room": "Kitchen",
            "lights": [],
        },
        {
            "enabled": True,
            "trigger_type": "mould_risk",
            "room": "Bedroom",
            "lights": [],
        },
    ]
    entry_alert_hierarchy = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_alert_hierarchy_data,
        options={},
    )
    hass_alert_hierarchy = _FakeHass(
        entry_alert_hierarchy,
        {
            "sensor.kitchen_h": _FakeState(77),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(83),
            "sensor.kitchen_t": _FakeState(20),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(20),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_alert_hierarchy = HIAutomationEngine(hass_alert_hierarchy, entry_alert_hierarchy)
    await engine_alert_hierarchy._evaluate()
    hierarchy_data = hass_alert_hierarchy.data["humidity_intelligence"][ENTRY_ID]
    assert hierarchy_data.get("active_alert_context") == "Mould Risk · Bedroom · Zone 2"
    assert "Conflict detected" in hierarchy_data.get("runtime_reason_full", "")
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone2"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_alert_hierarchy.services.calls
    )

    # Same-priority alerts should resolve by zone priority: Zone 1 before Zone 2.
    entry_zone_priority_data = _base_entry_data()
    entry_zone_priority_data["target_profile"] = "custom"
    entry_zone_priority_data["custom_target_low"] = 40
    entry_zone_priority_data["custom_target_high"] = 79
    entry_zone_priority_data["aq"] = {}
    entry_zone_priority_data["humidifiers"] = {}
    entry_zone_priority_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "mould_risk",
            "room": "Kitchen",
            "lights": [],
        },
        {
            "enabled": True,
            "trigger_type": "mould_risk",
            "room": "Bedroom",
            "lights": [],
        },
    ]
    entry_zone_priority = SimpleNamespace(entry_id=ENTRY_ID, data=entry_zone_priority_data, options={})
    hass_zone_priority = _FakeHass(
        entry_zone_priority,
        {
            "sensor.kitchen_h": _FakeState(83),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(83),
            "sensor.kitchen_t": _FakeState(20),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(20),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_zone_priority = HIAutomationEngine(hass_zone_priority, entry_zone_priority)
    await engine_zone_priority._evaluate()
    assert hass_zone_priority.data["humidity_intelligence"][ENTRY_ID].get("active_alert_context") == (
        "Mould Risk · Kitchen · Zone 1"
    )
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_zone_priority.services.calls
    )

    # Unknown/unavailable source telemetry should not trigger blind boost.
    entry_alert_degraded_data = _base_entry_data()
    entry_alert_degraded_data["aq"] = {}
    entry_alert_degraded_data["humidifiers"] = {}
    entry_alert_degraded_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "condensation_risk",
            "room": "Bedroom",
            "lights": [],
        }
    ]
    entry_alert_degraded = SimpleNamespace(entry_id=ENTRY_ID, data=entry_alert_degraded_data, options={})
    hass_alert_degraded = _FakeHass(
        entry_alert_degraded,
        {
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState("unavailable"),
            "sensor.kitchen_t": _FakeState(22),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState("unknown"),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_alert_degraded = HIAutomationEngine(hass_alert_degraded, entry_alert_degraded)
    await engine_alert_degraded._evaluate()
    degraded_data = hass_alert_degraded.data["humidity_intelligence"][ENTRY_ID]
    assert degraded_data.get("runtime_mode") != "alert"
    assert degraded_data.get("active_alert_context") == "None"
    assert not any(
        domain == "fan" and service == "set_percentage"
        for domain, service, _data, _ in hass_alert_degraded.services.calls
    )

    # Disabled alert handling should skip non-CO internally calculated alerts.
    entry_alert_disabled_data = _base_entry_data()
    entry_alert_disabled_data["alert_handling_enabled"] = False
    entry_alert_disabled = SimpleNamespace(entry_id=ENTRY_ID, data=entry_alert_disabled_data, options={})
    hass_alert_disabled = _FakeHass(
        entry_alert_disabled,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_alert_disabled = HIAutomationEngine(hass_alert_disabled, entry_alert_disabled)
    alert_active, alert_details = await engine_alert_disabled._handle_alerts()
    assert alert_active is False
    assert alert_details == []

    # Unmapped alert candidates should be reported, skipped for boost, and
    # allow the next eligible lane to run.
    entry_unmapped_alert_data = _base_entry_data()
    entry_unmapped_alert_data["zones"]["zone1"]["rooms"] = ["Hallway"]
    entry_unmapped_alert_data["zones"]["zone2"]["rooms"] = ["Bedroom"]
    entry_unmapped_alert_data["humidifiers"] = {}
    entry_unmapped_alert_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Kitchen",
            "lights": [],
        }
    ]
    entry_unmapped_alert = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_unmapped_alert_data,
        options={},
    )
    hass_unmapped_alert = _FakeHass(
        entry_unmapped_alert,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_unmapped_alert = HIAutomationEngine(hass_unmapped_alert, entry_unmapped_alert)
    await engine_unmapped_alert._evaluate()
    unmapped_data = hass_unmapped_alert.data["humidity_intelligence"][ENTRY_ID]
    unmapped_reason = unmapped_data.get("runtime_reason_full", "")
    assert unmapped_data.get("runtime_mode") == "air_quality"
    assert "Skipped alert candidate" in unmapped_reason
    assert "No enabled zone maps room 'Kitchen'" in unmapped_reason
    assert not any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") in {"fan.zone1", "fan.zone2"}
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_unmapped_alert.services.calls
    )

    # Humidity danger with no explicit threshold should use active profile high-risk.
    entry_room_alert_dynamic_data = _base_entry_data()
    entry_room_alert_dynamic_data["aq"] = {}
    entry_room_alert_dynamic_data["humidifiers"] = {}
    entry_room_alert_dynamic_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Kitchen",
            "lights": ["light.alert"],
            "duration": 10,
        }
    ]
    entry_room_alert_dynamic = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_room_alert_dynamic_data,
        options={},
    )
    hass_room_alert_dynamic = _FakeHass(
        entry_room_alert_dynamic,
        {
            "sensor.kitchen_h": _FakeState(64),  # winter high-risk default is 62
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_room_alert_dynamic = HIAutomationEngine(hass_room_alert_dynamic, entry_room_alert_dynamic)
    await engine_room_alert_dynamic._evaluate()
    assert hass_room_alert_dynamic.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    dynamic_reason = hass_room_alert_dynamic.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason_full", "")
    assert "Threshold source: active profile" in dynamic_reason
    assert "sensor.kitchen_h" in dynamic_reason
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_room_alert_dynamic.services.calls
    )
    dynamic_flash_calls = hass_room_alert_dynamic.data["_trusted_visual_alert_calls"]
    assert dynamic_flash_calls
    assert all(data.get("flash_count") == 10 for data in dynamic_flash_calls)
    assert all(data.get("power_entity") is None for data in dynamic_flash_calls)
    assert all(isinstance(data.get("color"), list) for data in dynamic_flash_calls)
    assert all(len(data.get("color")) == 3 for data in dynamic_flash_calls)
    assert all(
        all(isinstance(channel, int) for channel in data.get("color"))
        for data in dynamic_flash_calls
    )
    assert len(engine_room_alert_dynamic._visual_alert_tasks) == 1
    flash_call_count_before_repeat = len(dynamic_flash_calls)
    await engine_room_alert_dynamic._evaluate()
    dynamic_flash_calls_after_repeat_eval = hass_room_alert_dynamic.data[
        "_trusted_visual_alert_calls"
    ]
    assert len(dynamic_flash_calls_after_repeat_eval) == flash_call_count_before_repeat
    assert len(engine_room_alert_dynamic._visual_alert_tasks) == 1
    await engine_room_alert_dynamic.async_stop()

    # Alerts without target lights should still activate runtime alert mode,
    # but skip light flash service calls cleanly.
    entry_room_alert_no_lights_data = _base_entry_data()
    entry_room_alert_no_lights_data["aq"] = {}
    entry_room_alert_no_lights_data["humidifiers"] = {}
    entry_room_alert_no_lights_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Kitchen",
            "duration": 10,
        }
    ]
    entry_room_alert_no_lights = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_room_alert_no_lights_data,
        options={},
    )
    hass_room_alert_no_lights = _FakeHass(
        entry_room_alert_no_lights,
        {
            "sensor.kitchen_h": _FakeState(82),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_room_alert_no_lights = HIAutomationEngine(
        hass_room_alert_no_lights,
        entry_room_alert_no_lights,
    )
    await engine_room_alert_no_lights._evaluate()
    assert hass_room_alert_no_lights.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "alert"
    assert not hass_room_alert_no_lights.data.get("_trusted_visual_alert_calls")

    entry_room_alert_miss_data = _base_entry_data()
    entry_room_alert_miss_data["zones"]["zone1"]["enabled"] = False
    entry_room_alert_miss_data["zones"]["zone2"]["enabled"] = False
    entry_room_alert_miss_data["aq"] = {}
    entry_room_alert_miss_data["humidifiers"] = {}
    entry_room_alert_miss_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "humidity_danger",
            "room": "Hallway",
            "lights": ["light.alert"],
            "duration": 10,
        }
    ]
    entry_room_alert_miss = SimpleNamespace(entry_id=ENTRY_ID, data=entry_room_alert_miss_data, options={})
    hass_room_alert_miss = _FakeHass(
        entry_room_alert_miss,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_room_alert_miss = HIAutomationEngine(hass_room_alert_miss, entry_room_alert_miss)
    await engine_room_alert_miss._evaluate()
    assert hass_room_alert_miss.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") != "alert"

    # Zone label and fan-step enforcement: custom UI label should be surfaced,
    # and unsupported percentages should snap to the nearest supported level.
    entry_label_data = _base_entry_data()
    entry_label_data["alert_handling_enabled"] = False
    entry_label_data["zones"]["zone1"]["ui_label"] = "Kitchen Extract"
    entry_label_data["zones"]["zone1"]["output_level"] = 64
    entry_label_data["zones"]["zone2"]["enabled"] = False
    entry_label_data["aq"] = {}
    entry_label = SimpleNamespace(entry_id=ENTRY_ID, data=entry_label_data, options={})
    hass_label = _FakeHass(
        entry_label,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_label = HIAutomationEngine(hass_label, entry_label)
    await engine_label._evaluate()

    assert hass_label.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "cooking"
    assert hass_label.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode_display") == "Kitchen Extract"
    assert (
        hass_label.data["humidity_intelligence"][ENTRY_ID]["runtime_display_reason"]["headline"]
        == "Kitchen Extract response lane selected"
    )
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 66
        for domain, service, data, _ in hass_label.services.calls
    )

    # Zone lane priority must select one ventilation lane per cycle:
    # zone1 beats zone2 and zone2 must not write its fan output.
    entry_zone_select_data = _base_entry_data()
    entry_zone_select_data["alert_handling_enabled"] = False
    entry_zone_select_data["humidifiers"] = {}
    entry_zone_select_data["aq"] = {}
    entry_zone_select = SimpleNamespace(entry_id=ENTRY_ID, data=entry_zone_select_data, options={})
    hass_zone_select = _FakeHass(
        entry_zone_select,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(90),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_zone_select = HIAutomationEngine(hass_zone_select, entry_zone_select)
    await engine_zone_select._evaluate()

    assert hass_zone_select.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "cooking"
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone1"
        and data.get("percentage") == 66
        for domain, service, data, _ in hass_zone_select.services.calls
    )
    assert not any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone2"
        for domain, service, data, _ in hass_zone_select.services.calls
    )

    # AQ-only scenario: no alert and no zone should allow AQ lane execution.
    entry3_data = _base_entry_data()
    entry3_data["zones"]["zone1"]["enabled"] = False
    entry3_data["zones"]["zone2"]["enabled"] = False
    entry3_data["alert_handling_enabled"] = False
    # Overlap AQ output with a zone output to ensure AQ is not immediately reset to auto.
    entry3_data["aq"]["level1"]["outputs"] = ["fan.zone1"]
    entry3 = SimpleNamespace(entry_id=ENTRY_ID, data=entry3_data, options={})
    hass_aq = _FakeHass(
        entry3,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_aq = HIAutomationEngine(hass_aq, entry3)
    aq_trace = []
    for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
        _wrap_async_method(engine_aq, method, aq_trace)
    await engine_aq._evaluate()

    assert "_handle_aq" in aq_trace
    assert any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.zone1"
        for domain, service, data, _ in hass_aq.services.calls
    )
    assert not any(
        domain == "fan" and service == "set_preset_mode" and data.get("entity_id") == "fan.zone1"
        for domain, service, data, _ in hass_aq.services.calls
    )
    assert hass_aq.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "air_quality"
    aq_reason = hass_aq.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "AQ is active" in aq_reason or "Air-quality assist is active" in aq_reason
    assert "Trigger detail:" in aq_reason

    # AQ auto level should use fan preset mode instead of percentage service.
    entry_aq_auto_data = _base_entry_data()
    entry_aq_auto_data["zones"]["zone1"]["enabled"] = False
    entry_aq_auto_data["zones"]["zone2"]["enabled"] = False
    entry_aq_auto_data["alert_handling_enabled"] = False
    entry_aq_auto_data["aq"]["level1"]["output_level"] = "auto"
    entry_aq_auto = SimpleNamespace(entry_id=ENTRY_ID, data=entry_aq_auto_data, options={})
    hass_aq_auto = _FakeHass(
        entry_aq_auto,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_aq_auto = HIAutomationEngine(hass_aq_auto, entry_aq_auto)
    await engine_aq_auto._evaluate()
    assert any(
        domain == "fan" and service == "set_preset_mode" and data.get("entity_id") == "fan.aq1"
        for domain, service, data, _ in hass_aq_auto.services.calls
    )
    assert not any(
        domain == "fan" and service == "set_percentage" and data.get("entity_id") == "fan.aq1"
        for domain, service, data, _ in hass_aq_auto.services.calls
    )

    # Independent AQ lanes sharing one output: both can run; newest trigger wins output level.
    entry_shared_aq_data = _base_entry_data()
    entry_shared_aq_data["zones"]["zone1"]["enabled"] = False
    entry_shared_aq_data["zones"]["zone2"]["enabled"] = False
    entry_shared_aq_data["alert_handling_enabled"] = False
    entry_shared_aq_data["telemetry"].append(
        {"entity_id": "sensor.l2_iaq", "sensor_type": "iaq", "level": "level2", "room": "Bedroom"}
    )
    entry_shared_aq_data["aq"] = {
        "level1": {
            "enabled": True,
            "outputs": ["fan.shared"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 33,
            "run_duration": 10,
        },
        "level2": {
            "enabled": True,
            "outputs": ["fan.shared"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 100,
            "run_duration": 10,
        },
    }
    entry_shared_aq = SimpleNamespace(entry_id=ENTRY_ID, data=entry_shared_aq_data, options={})
    hass_shared_aq = _FakeHass(
        entry_shared_aq,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(70),   # level1 triggers first
            "sensor.l2_iaq": _FakeState(90),   # level2 idle initially
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_shared_aq = HIAutomationEngine(hass_shared_aq, entry_shared_aq)
    await engine_shared_aq._evaluate()
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.shared"
        and data.get("percentage") == 33
        for domain, service, data, _ in hass_shared_aq.services.calls
    )
    # New level2 trigger arrives later: shared output should move to level2 setting.
    hass_shared_aq.states._values["sensor.l2_iaq"] = _FakeState(70)
    await engine_shared_aq._evaluate()
    assert hass_shared_aq.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_downstairs_active"].is_on
    assert hass_shared_aq.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.shared"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass_shared_aq.services.calls
    )

    # Shared humidifier output follows aggregate demand; one recovering lane
    # cannot turn it off while another lane still requests humidification.
    entry_shared_humid_data = _base_entry_data()
    entry_shared_humid_data["zones"]["zone1"]["enabled"] = False
    entry_shared_humid_data["zones"]["zone2"]["enabled"] = False
    entry_shared_humid_data["alert_handling_enabled"] = False
    entry_shared_humid_data["aq"] = {}
    entry_shared_humid_data["humidifiers"] = {
        "level1": {"enabled": True, "outputs": ["humidifier.shared"], "band_adjust": 0},
        "level2": {"enabled": True, "outputs": ["humidifier.shared"], "band_adjust": 0},
    }
    entry_shared_humid = SimpleNamespace(entry_id=ENTRY_ID, data=entry_shared_humid_data, options={})
    hass_shared_humid = _FakeHass(
        entry_shared_humid,
        {
            "sensor.kitchen_h": _FakeState(40),  # level1 below low -> on
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),      # level2 below low -> on
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(90),
            "sensor.co_val": _FakeState(4),
            "humidifier.shared": _FakeState("off"),
        },
    )
    engine_shared_humid = HIAutomationEngine(hass_shared_humid, entry_shared_humid)
    await engine_shared_humid._evaluate()
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_upstairs_humidifier_active"].is_on
    humid_reason = (
        hass_shared_humid.data["humidity_intelligence"][ENTRY_ID].get(
            "runtime_reason_full"
        )
        or hass_shared_humid.data["humidity_intelligence"][ENTRY_ID].get(
            "runtime_reason",
            "",
        )
    )
    assert "Humidifier demand is requested" in humid_reason
    assert "status=" not in humid_reason
    assert "action=" not in humid_reason
    assert "Trigger:" not in humid_reason
    assert "Recovery:" not in humid_reason
    assert sum(
        domain == "humidifier"
        and service == "turn_on"
        and data.get("entity_id") == "humidifier.shared"
        for domain, service, data, _ in hass_shared_humid.services.calls
    ) == 1
    hass_shared_humid.states._values["humidifier.shared"] = _FakeState("on")
    # Level1 recovers while Level2 still owns demand.
    hass_shared_humid.states._values["sensor.kitchen_h"] = _FakeState(55)
    hass_shared_humid.states._values["sensor.hall_h"] = _FakeState(55)
    await engine_shared_humid._evaluate()
    assert not any(
        domain == "humidifier"
        and service == "turn_off"
        and data.get("entity_id") == "humidifier.shared"
        for domain, service, data, _ in hass_shared_humid.services.calls
    )
    assert not hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert hass_shared_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_upstairs_humidifier_active"].is_on

    # Testing isolation toggles suppress output service calls while logic state still updates.
    entry_isolated_data = _base_entry_data()
    entry_isolated_data["alert_handling_enabled"] = False
    entry_isolated_data["zones"]["zone2"]["enabled"] = False
    entry_isolated_data["aq"] = {}
    entry_isolated = SimpleNamespace(entry_id=ENTRY_ID, data=entry_isolated_data, options={})
    hass_isolated = _FakeHass(
        entry_isolated,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(90),
            "sensor.co_val": _FakeState(4),
        },
    )
    hass_isolated.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_isolate_fan_outputs"].is_on = True
    hass_isolated.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_isolate_humidifier_outputs"].is_on = True
    engine_isolated = HIAutomationEngine(hass_isolated, entry_isolated)
    await engine_isolated._evaluate()
    assert hass_isolated.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "cooking"
    isolated_reason = hass_isolated.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "isolated for testing" in isolated_reason
    assert not any(
        domain in {"fan", "switch", "humidifier"} and service in {"set_percentage", "set_preset_mode", "turn_on", "turn_off"}
        for domain, service, data, _ in hass_isolated.services.calls
    )

    # Stale AQ state from an old level config must be cleared (prevents AQ badge/mode drift).
    entry4_data = _base_entry_data()
    entry4_data["zones"]["zone1"]["enabled"] = False
    entry4_data["zones"]["zone2"]["enabled"] = False
    entry4_data["alert_handling_enabled"] = False
    entry4_data["aq"] = {
        "level1": {
            "enabled": False,
            "outputs": ["fan.aq1"],
            "triggers": ["iaq_bad"],
            "thresholds": {"iaq_bad": 75},
            "output_level": 66,
            "run_duration": 10,
        }
    }
    entry4 = SimpleNamespace(entry_id=ENTRY_ID, data=entry4_data, options={})
    hass_stale = _FakeHass(
        entry4,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    hass_stale.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on = True
    engine_stale = HIAutomationEngine(hass_stale, entry4)
    engine_stale._aq_tasks["level2"] = asyncio.create_task(asyncio.sleep(3600))
    await engine_stale._evaluate()

    assert not hass_stale.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_aq_upstairs_active"].is_on
    assert "level2" not in engine_stale._aq_tasks
    assert hass_stale.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "normal"

    # Global gate should publish dedicated runtime mode for UI chip/border sync.
    entry_gate_data = _base_entry_data()
    entry_gate_data["alert_handling_enabled"] = False
    entry_gate_data["zones"]["zone1"]["enabled"] = False
    entry_gate_data["zones"]["zone2"]["enabled"] = False
    entry_gate_data["aq"] = {}
    entry_gate_data["humidifiers"] = {}
    entry_gate_data["presence_gate"] = {
        "enabled": True,
        "entities": ["binary_sensor.home_presence"],
        "present_states": ["on"],
        "away_states": ["off"],
    }
    entry_gate = SimpleNamespace(entry_id=ENTRY_ID, data=entry_gate_data, options={})
    hass_gate = _FakeHass(
        entry_gate,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.home_presence": _FakeState("off"),
        },
    )
    engine_gate = HIAutomationEngine(hass_gate, entry_gate)
    await engine_gate._evaluate()
    assert hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode") == "global_gate"
    assert hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_mode_display") == "GLOBAL GATE"
    gate_reason = hass_gate.data["humidity_intelligence"][ENTRY_ID].get("runtime_reason", "")
    assert "Presence gate is active" in gate_reason

    # Global gate preemption should stop an active humidity-danger alert lane and
    # clear the UI alert context immediately, even if humidity is still high.
    entry_gate_alert_data = _base_entry_data()
    entry_gate_alert_data["aq"] = {}
    entry_gate_alert_data["humidifiers"] = {}
    entry_gate_alert_data["alerts"][0]["lights"] = []
    entry_gate_alert_data["alerts"][0].pop("power_entity", None)
    entry_gate_alert_data["presence_gate"] = {
        "enabled": True,
        "entities": ["binary_sensor.home_presence"],
        "present_states": ["on"],
        "away_states": ["off"],
    }
    entry_gate_alert = SimpleNamespace(entry_id=ENTRY_ID, data=entry_gate_alert_data, options={})
    hass_gate_alert = _FakeHass(
        entry_gate_alert,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "binary_sensor.home_presence": _FakeState("on"),
        },
    )
    engine_gate_alert = HIAutomationEngine(hass_gate_alert, entry_gate_alert)
    await engine_gate_alert._evaluate()
    gate_alert_data = hass_gate_alert.data["humidity_intelligence"][ENTRY_ID]
    gate_alert_switch = gate_alert_data["hi_input_booleans"]["air_alert_1_active"]
    assert gate_alert_data.get("runtime_mode") == "alert"
    assert gate_alert_switch.is_on
    assert str(gate_alert_data.get("active_alert_context", "")).startswith("Humidity Danger")

    hass_gate_alert.states._values["binary_sensor.home_presence"] = _FakeState("off")
    await engine_gate_alert._evaluate()
    gate_alert_data = hass_gate_alert.data["humidity_intelligence"][ENTRY_ID]
    assert gate_alert_data.get("runtime_mode") == "global_gate"
    assert gate_alert_data.get("runtime_mode_display") == "GLOBAL GATE"
    assert not gate_alert_switch.is_on
    assert gate_alert_data.get("active_alert_context") == "None"
    assert gate_alert_data.get("alert_telemetry") == []
    assert engine_gate_alert._active_alert_identity is None
    assert "Presence gate is active" in gate_alert_data.get("runtime_reason", "")

    hass_gate_alert.states._values["sensor.kitchen_h"] = _FakeState(45)
    hass_gate_alert.states._values["sensor.hall_h"] = _FakeState(45)
    hass_gate_alert.states._values["sensor.bed_h"] = _FakeState(45)
    await engine_gate_alert._evaluate()
    gate_alert_data = hass_gate_alert.data["humidity_intelligence"][ENTRY_ID]
    assert gate_alert_data.get("runtime_mode") == "global_gate"
    assert gate_alert_data.get("active_alert_context") == "None"
    assert gate_alert_data.get("alert_telemetry") == []
    assert not gate_alert_switch.is_on

    # The non-safe-state time gate path should also clear stale alert UI state.
    entry_time_gate_alert_data = _base_entry_data()
    entry_time_gate_alert_data["aq"] = {}
    entry_time_gate_alert_data["humidifiers"] = {}
    entry_time_gate_alert_data["alerts"][0]["lights"] = []
    entry_time_gate_alert_data["alerts"][0].pop("power_entity", None)
    entry_time_gate_alert_data["time_gate"] = {"enabled": False}
    entry_time_gate_alert = SimpleNamespace(entry_id=ENTRY_ID, data=entry_time_gate_alert_data, options={})
    hass_time_gate_alert = _FakeHass(
        entry_time_gate_alert,
        {
            "sensor.kitchen_h": _FakeState(90),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(45),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )
    engine_time_gate_alert = HIAutomationEngine(hass_time_gate_alert, entry_time_gate_alert)
    await engine_time_gate_alert._evaluate()
    time_gate_data = hass_time_gate_alert.data["humidity_intelligence"][ENTRY_ID]
    time_gate_alert_switch = time_gate_data["hi_input_booleans"]["air_alert_1_active"]
    assert time_gate_data.get("runtime_mode") == "alert"
    assert time_gate_alert_switch.is_on
    assert str(time_gate_data.get("active_alert_context", "")).startswith("Humidity Danger")

    outside_start = (datetime.now() + timedelta(hours=1)).time()
    outside_end = (datetime.now() + timedelta(hours=1, minutes=1)).time()
    engine_time_gate_alert.time_gate.update(
        {
            "enabled": True,
            "start": outside_start,
            "end": outside_end,
            "outside_action": "pause",
        }
    )
    await engine_time_gate_alert._evaluate()
    time_gate_data = hass_time_gate_alert.data["humidity_intelligence"][ENTRY_ID]
    assert time_gate_data.get("runtime_mode") == "global_gate"
    assert time_gate_data.get("runtime_mode_display") == "GLOBAL GATE"
    assert not time_gate_alert_switch.is_on
    assert time_gate_data.get("active_alert_context") == "None"
    assert time_gate_data.get("alert_telemetry") == []
    assert engine_time_gate_alert._active_alert_identity is None
    assert "Time gate is outside" in time_gate_data.get("runtime_reason", "")

    # Disabled humidifier lanes should clear stale active state and turn outputs off.
    entry5_data = _base_entry_data()
    entry5_data["zones"]["zone1"]["enabled"] = False
    entry5_data["zones"]["zone2"]["enabled"] = False
    entry5_data["alert_handling_enabled"] = False
    entry5_data["aq"] = {}
    entry5_data["humidifiers"]["level1"]["enabled"] = False
    entry5 = SimpleNamespace(entry_id=ENTRY_ID, data=entry5_data, options={})
    hass_humid = _FakeHass(
        entry5,
        {
            "sensor.kitchen_h": _FakeState(40),
            "sensor.hall_h": _FakeState(40),
            "sensor.bed_h": _FakeState(40),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "humidifier.l1": _FakeState("on"),
        },
    )
    hass_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on = True
    engine_humid = HIAutomationEngine(hass_humid, entry5)
    await engine_humid._evaluate()

    assert not hass_humid.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert any(
        domain == "humidifier" and service == "turn_off" and data.get("entity_id") == "humidifier.l1"
        for domain, service, data, _ in hass_humid.services.calls
    )

    # Humidifier off threshold should recover inside target band (low + 4%), not only at high target.
    entry6_data = _base_entry_data()
    entry6_data["zones"]["zone1"]["enabled"] = False
    entry6_data["zones"]["zone2"]["enabled"] = False
    entry6_data["alert_handling_enabled"] = False
    entry6_data["aq"] = {}
    entry6 = SimpleNamespace(entry_id=ENTRY_ID, data=entry6_data, options={})
    hass_humid_band = _FakeHass(
        entry6,
        {
            "sensor.kitchen_h": _FakeState(50),
            "sensor.hall_h": _FakeState(50),
            "sensor.bed_h": _FakeState(50),
            "sensor.kitchen_t": _FakeState(23),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(21),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
            "humidifier.l1": _FakeState("on"),
        },
    )
    # Simulate humidifier already running; at 50% in winter, it should now shut off at low+4.
    hass_humid_band.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on = True
    engine_humid_band = HIAutomationEngine(hass_humid_band, entry6)
    await engine_humid_band._evaluate()
    assert not hass_humid_band.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"].is_on
    assert any(
        domain == "humidifier" and service == "turn_off" and data.get("entity_id") == "humidifier.l1"
        for domain, service, data, _ in hass_humid_band.services.calls
    )

    # Runtime reason state must stay within HA state limit and preserve full text.
    long_reason = "X" * 400
    await engine_humid_band._set_runtime_reason(long_reason)
    stored = hass_humid_band.data["humidity_intelligence"][ENTRY_ID]
    assert isinstance(stored.get("runtime_reason"), str)
    assert len(stored.get("runtime_reason")) <= 255
    assert stored.get("runtime_reason_full") == long_reason
    assert stored.get("runtime_reason_truncated") is True

    # Re-entrant requests caused by helper state changes should be coalesced
    # instead of recursively running overlapping evaluation cycles.
    entry_reentry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass_reentry = _FakeHass(entry_reentry, {})
    engine_reentry = HIAutomationEngine(hass_reentry, entry_reentry)
    reentry_calls = []

    async def fake_evaluate():
        reentry_calls.append("run")
        if len(reentry_calls) == 1:
            await engine_reentry.async_request_evaluate()

    engine_reentry._evaluate = fake_evaluate
    await engine_reentry.async_request_evaluate()
    assert reentry_calls == ["run", "run"]

    # Internal status helpers should not be tracked as evaluation sources; they
    # are outputs of the engine, not inputs that should retrigger the engine.
    for key, entity in hass_reentry.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"].items():
        entity.entity_id = f"switch.hi_{key}"
    sources = engine_reentry._evaluation_sources()
    assert "switch.hi_air_control_enabled" in sources
    assert "switch.hi_air_alert_1_active" not in sources
    assert "switch.hi_air_aq_downstairs_active" not in sources
    assert "switch.hi_air_downstairs_humidifier_active" not in sources

    # Cleanup background AQ tasks.
    for task in list(engine._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_aq._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_stale._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_aq_auto._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in list(engine_shared_aq._aq_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _contains_v2_border_pill_sync_logic(yaml_text: str) -> bool:
    chip_tokens = [
        "const red =",
        "const gateActive =",
        "const zone1 =",
        "const zone2 =",
        "const aqActive =",
        "if (red) return '#ef4444'",
        "if (gateActive) return '#f59e0b'",
        "if (zone1) return '#38bdf8'",
        "if (zone2) return '#4ade80'",
        "if (aqActive) return '#a855f7'",
    ]
    border_tokens = [
        "if (red) return '1px solid rgba(239,68,68",
        "if (gateActive) return '1px solid rgba(245,158,11",
        "if (zone1) return '1px solid rgba(56,189,248",
        "if (zone2) return '1px solid rgba(74,222,128",
        "if (aqActive) return '1px solid rgba(168,85,247",
    ]
    return all(token in yaml_text for token in chip_tokens) and all(
        token in yaml_text for token in border_tokens
    )


def _has_empty_cards_block(yaml_text: str) -> bool:
    lines = yaml_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "cards:":
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        next_idx = idx + 1
        while next_idx < len(lines) and not lines[next_idx].strip():
            next_idx += 1
        if next_idx >= len(lines):
            return True
        next_indent = len(lines[next_idx]) - len(lines[next_idx].lstrip(" \t"))
        if next_indent <= indent:
            return True
    return False


def _has_invalid_conditional_block(yaml_text: str) -> bool:
    lines = yaml_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "- type: conditional":
            continue

        base_indent = len(line) - len(line.lstrip(" \t"))
        end = idx + 1
        while end < len(lines):
            nxt = lines[end]
            if not nxt.strip():
                end += 1
                continue
            nxt_indent = len(nxt) - len(nxt.lstrip(" \t"))
            if nxt_indent <= base_indent and nxt.lstrip().startswith("- "):
                break
            end += 1

        block = lines[idx:end]
        top_level_indent = base_indent + 2
        conditions_idx = None
        card_idx = None
        for rel, bline in enumerate(block[1:], start=1):
            stripped = bline.lstrip(" \t")
            indent = len(bline) - len(stripped)
            if indent != top_level_indent:
                continue
            if stripped.startswith("conditions:") and conditions_idx is None:
                conditions_idx = rel
            if stripped.startswith("card:") and card_idx is None:
                card_idx = rel

        if conditions_idx is None or card_idx is None:
            return True

        conditions_indent = top_level_indent
        has_condition_item = False
        for rel in range(conditions_idx + 1, len(block)):
            bline = block[rel]
            if not bline.strip():
                continue
            indent = len(bline) - len(bline.lstrip(" \t"))
            if indent <= conditions_indent:
                break
            if bline.lstrip(" \t").startswith("- "):
                has_condition_item = True
                break
        if not has_condition_item:
            return True

        card_indent = top_level_indent
        has_card_body = False
        for rel in range(card_idx + 1, len(block)):
            bline = block[rel]
            if not bline.strip():
                continue
            indent = len(bline) - len(bline.lstrip(" \t"))
            if indent <= card_indent:
                break
            has_card_body = True
            break
        if not has_card_body:
            return True
    return False


async def _run_card_assertions(register_mod) -> None:
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistry()

    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "telemetry": [
                {"entity_id": "sensor.kitchen_h", "sensor_type": "humidity", "level": "level1", "room": "Kitchen"},
                {"entity_id": "sensor.hall_h", "sensor_type": "humidity", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.bed_h", "sensor_type": "humidity", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.willow_h", "sensor_type": "humidity", "level": "level2", "room": "Willow Room"},
                {"entity_id": "sensor.bath_h", "sensor_type": "humidity", "level": "level1", "room": "Bathroom"},
                {"entity_id": "sensor.kitchen_t", "sensor_type": "temperature", "level": "level1", "room": "Kitchen"},
                {"entity_id": "sensor.bed_t", "sensor_type": "temperature", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_iaq", "sensor_type": "iaq", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_iaq", "sensor_type": "iaq", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_pm25", "sensor_type": "pm25", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_pm25", "sensor_type": "pm25", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_voc", "sensor_type": "voc", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_voc", "sensor_type": "voc", "level": "level2", "room": "Bedroom"},
                {"entity_id": "sensor.l1_co", "sensor_type": "co", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_co", "sensor_type": "co", "level": "level2", "room": "Bedroom"},
            ],
            "zones": {
                "zone1": {"level": "level1", "rooms": ["Bathroom", "Kitchen"], "outputs": ["fan.zone1"]},
                "zone2": {"level": "level2", "rooms": ["Bedroom"], "outputs": ["fan.zone2"]},
            },
            "humidifiers": {
                "level1": {"outputs": ["humidifier.l1"]},
                "level2": {"outputs": ["humidifier.l2"]},
            },
            "alerts": [{"lights": ["light.alert1"]}],
            "temperature_comfort_mode": "auto",
            "slope": {
                "mode": "hi_calculates",
                "source_entities": ["sensor.kitchen_t", "sensor.bed_t"],
                "show_temperature_chips": True,
            },
            "level_labels": {"level1": "Ground Floor", "level2": "Loft"},
        },
        options={},
    )
    hass = _FakeHass(entry, {})
    hass.config_entries = _FakeConfigEntries(entry)

    mapping = await register_mod.async_build_entity_mapping(hass, ENTRY_ID)
    cards = await register_mod.async_register_cards(hass, ENTRY_ID, mapping)
    mobile = cards.get("v2_mobile", "")
    tablet = cards.get("v2_tablet", "")
    legacy = cards.get("v1_mobile", "")

    assert hass.data["humidity_intelligence"][ENTRY_ID].get("unresolved_placeholders_by_card", {}) == {}
    assert mobile.startswith("# Humidity Intelligence V2 Mobile Manual-card YAML")
    assert tablet.startswith("# Humidity Intelligence V2 Tablet Manual-card YAML")
    assert "const escapeHtml = " in legacy
    assert "${escapeHtml(item.label)}" in legacy
    assert "Target humidity (${escapeHtml(season)}):" in legacy
    assert "Condensation: ${escapeHtml(condRisk)} in ${escapeHtml(condRoom)}" in legacy
    assert "Mould: ${escapeHtml(mouldRisk)} in ${escapeHtml(mouldRoom)}" in legacy
    assert "Export refreshed Humidity Intelligence card YAML from Home Assistant." in mobile
    assert "Dashboard Manual card" in tablet
    assert hass.data["humidity_intelligence"][ENTRY_ID]["level_labels"] == {
        "level1": "Ground Floor",
        "level2": "Loft",
    }

    # Phase 3: prove the real rendered cache survives the owned export byte-for-byte
    # and remains one Manual-card fragment rather than a dashboard document.
    services_mod = _load_services_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        export_hass = _DumpCardsHass(tmpdir, [entry], {ENTRY_ID: cards})
        written = await services_mod.async_export_cards_to_owned_ui(
            export_hass,
            entry_id=ENTRY_ID,
            filename=None,
            layout="v2_mobile",
        )
        assert written == [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        ]
        exported = (
            pathlib.Path(tmpdir)
            / "humidity_intelligence"
            / "ui"
            / "humidity_intelligence_cards_v2_mobile.yaml"
        ).read_text(encoding="utf-8")
        assert exported == mobile
        first_yaml_line = next(
            line for line in exported.splitlines() if line and not line.startswith("#")
        )
        assert first_yaml_line == "type: custom:mod-card"
        assert not any(line.startswith("views:") for line in exported.splitlines())
        assert "Stage:" not in _v2_reason_block(exported)
        assert "Engine:" not in _v2_reason_block(exported)

    room_placeholders = [
        "sensor.bedroom_humidity",
        "sensor.hallway_humidity",
        "sensor.kids_room_humidity",
        "sensor.living_room_humidity",
        "sensor.toilet_humidity",
        "sensor.bathroom_humidity",
    ]
    for placeholder in room_placeholders:
        assert mapping.get(placeholder)
        assert placeholder not in cards.get("v1_mobile", "")
    assert mapping.get("sensor.hi_diagnostics")

    for card in (mobile, tablet):
        assert "Kitchen Δ slope" not in card
        assert "sensor.air_control_kitchen_slope_delta" not in card
        assert "sensor.air_control_bathroom_humidity_delta" not in card
        assert "sensor.air_control_kitchen_humidity_delta" not in card
        assert "House PM2.5" in card
        assert "House VOC" in card
        assert "House CO" in card
        assert "House Temp" in card
        assert "Loft Temp" in card
        assert "Ground Floor Temp" in card
        assert "Loft AVG" in card
        assert "Ground Floor AVG" in card
        assert "AQ Loft" in card
        assert "AQ Ground Floor" in card
        assert "Upstairs" not in card
        assert "Downstairs" not in card
        assert "show_temperature_chips" in card
        assert "slope_map" in card
        assert "sensor.hi_house_temperature_comfort_low" in card
        assert "sensor.hi_house_temperature_comfort_high" in card
        assert "warm_high" in card
        assert "warmHigh" in card
        assert "comfortHigh + 1" not in card
        temperature_block = card[card.index("temperature: |"):]
        assert "const attrNum" in temperature_block
        assert temperature_block.index("const attrNum") < temperature_block.index("const warmHigh")
        assert "tempColor(tempValueC(entity))" in card
        assert "slopeEntityFor(item)" in card
        assert "states['sensor.hi_diagnostics']" in card
        assert "CHIPSET_SCROLL_RESET_DELAY_MS = 15000" in card
        assert "data-scroll-reset-delay-ms" in card
        assert "output_on: 'On'" in card
        assert "output_on: 'Output on'" not in card
        assert "output_on: '#22d3ee'" in card
        assert "requested: '#22d3ee'" in card
        assert "`${label} Humidifier · ${text}`" in card
        assert "`Humidifier ${label} · ${text}`" not in card
        assert ".replace(/\\s*·\\s*[^·]*\\s>=\\s.*$/, '')" in card
        assert "const humidifierOut = [];" in card
        assert "const splitHumidifierRow" not in card
        assert "scrollRow(out, 'Ventilation status')" not in card
        assert "scrollRow(humidifierOut, 'Humidifier status')" not in card
        assert "out.push(...humidifierOut);" in card
        assert "return scrollRow(out, 'Current Air Control status');" in card
        assert "alertContext.startsWith('Humidity Danger · ')" in card
        assert ".cv-chip-stack{" not in card
        assert "activeAlertNames.forEach" not in card
        assert "if (alertLaneActive && alertContext" in card
        assert "states['binary_sensor.humidity_danger']?.state === 'on'" not in card
        assert "states['binary_sensor.condensation_danger']?.state === 'on'" not in card
        assert "states['binary_sensor.mould_danger']?.state === 'on'" not in card
        assert "_humidity_danger']?.state === 'on'" not in card
        assert "_condensation_danger']?.state === 'on'" not in card
        assert "_mould_danger']?.state === 'on'" not in card
        assert "DEGRADED ALERT CONTEXT" not in card
        assert "Stage: Degraded alert context detected" not in card
        assert "displayReason.schema !== 'hi.reason.v1'" in card
        assert "displayReason.lines.map((line) => escapeHtml(line.text))" in card
        assert "Stage:" not in _v2_reason_block(card)
        assert "Engine:" not in _v2_reason_block(card)
        assert "(!gateActive && anyAlertActive)" in card
        assert "states['sensor.air_control_mode']?.state || 'normal'" not in card
        assert "entity.state || 'normal'" not in card
        assert "'telemetry_unavailable'," in card
        assert "const modeKnown =" in card
        assert "const mode = modeKnown ? rawMode : 'unknown'" in card
        assert "if (!modeKnown) return 'UNKNOWN';" in card
        assert "const ready = modeKnown && mode === 'normal'" in card
        assert "if (mode === 'telemetry_unavailable') return '#f59e0b';" in card
        assert "if (mode === 'telemetry_unavailable') return 'TELEMETRY UNAVAILABLE';" in card
        assert "mode === 'telemetry_unavailable'" in card
        assert "if (mode === 'telemetry_unavailable') return '1px solid rgba(245,158,11" in card
        assert card.index("if (mode === 'telemetry_unavailable') return '#f59e0b';") < card.index("if (red || coE")
        assert card.index("if (!modeKnown) return '#94a3b8';") < card.index("if (red || coE")
        assert card.index("if (mode === 'telemetry_unavailable') return 'TELEMETRY UNAVAILABLE';") < card.index("if (red) return 'ALERT';")
        assert card.index("if (!modeKnown) return 'UNKNOWN';") < card.index("if (red) return 'ALERT';")
        assert "const borderModeKnown =" in card
        assert "if (!borderModeKnown) return '1px solid rgba(148,163,184,0.55)';" in card
        assert card.index("if (!borderModeKnown) return '1px solid rgba(148,163,184,0.55)';") < card.index("if (red) return '1px solid rgba(239,68,68,0.85)'")
        assert card.index("if (mode === 'telemetry_unavailable') return '1px solid rgba(245,158,11") < card.index("if (red) return '1px solid rgba(239,68,68,0.85)'")
        assert "sensor.hi_level2_avg_temperature" in card
        assert "sensor.hi_level1_avg_temperature" in card
        assert card.index("House AVG") < card.index("Loft AVG") < card.index("Ground Floor AVG")
        assert card.index("House IAQ") < card.index("Loft IAQ") < card.index("Ground Floor IAQ")

    assert _contains_v2_border_pill_sync_logic(mobile)
    assert _contains_v2_border_pill_sync_logic(tablet)
    # Outputs should only include configured alert placeholders.
    assert "input_boolean.air_alert_2_active" not in mobile
    assert "light.alert_2" not in mobile
    assert "name: Alert 2 Active" not in mobile
    assert "name: Alert light 2" not in mobile
    assert "air_bathroom_alert_77" not in mobile
    assert "air_bathroom_alert_81" not in mobile
    assert "air_bathroom_alert_77" not in tablet
    assert "air_bathroom_alert_81" not in tablet
    assert "input_boolean.air_isolate_fan_outputs" not in mobile
    assert "input_boolean.air_isolate_humidifier_outputs" not in mobile
    assert "input_boolean.air_isolate_fan_outputs" not in tablet
    assert "input_boolean.air_isolate_humidifier_outputs" not in tablet
    assert not _has_empty_cards_block(mobile)
    assert not _has_empty_cards_block(tablet)
    assert not _has_invalid_conditional_block(mobile)
    assert not _has_invalid_conditional_block(tablet)


async def _run_output_detail_visibility_assertions(register_mod) -> None:
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistry()

    hidden_data = _base_entry_data()
    hidden_data["show_output_entity_details"] = False
    hidden_entry = SimpleNamespace(entry_id=ENTRY_ID, data=hidden_data, options={})
    hidden_hass = _FakeHass(hidden_entry, {})
    hidden_mapping = await register_mod.async_build_entity_mapping(hidden_hass, ENTRY_ID)
    hidden_cards = await register_mod.async_register_cards(hidden_hass, ENTRY_ID, hidden_mapping)

    for card in (hidden_cards.get("v2_mobile", ""), hidden_cards.get("v2_tablet", "")):
        assert "name: Outputs" not in card
        assert "entity: switch.hi_input_air_control_output_expanded" not in card
        assert "entity: input_boolean.air_control_output_expanded" not in card
        assert "hi:output-details" not in card
        assert not _has_empty_cards_block(card)
        assert not _has_invalid_conditional_block(card)

    shown_data = _base_entry_data()
    shown_data["show_output_entity_details"] = True
    shown_entry = SimpleNamespace(entry_id=ENTRY_ID, data=shown_data, options={})
    shown_hass = _FakeHass(shown_entry, {})
    shown_mapping = await register_mod.async_build_entity_mapping(shown_hass, ENTRY_ID)
    shown_cards = await register_mod.async_register_cards(shown_hass, ENTRY_ID, shown_mapping)

    for card in (shown_cards.get("v2_mobile", ""), shown_cards.get("v2_tablet", "")):
        assert "name: Outputs" in card
        assert "air_control_output_expanded" in card
        assert "hi:output-details" not in card


async def _run_optional_aq_output_detail_pruning_assertions(register_mod) -> None:
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistryMissingUniqueIds(
        {
            f"hi_{ENTRY_ID}_level1_pm25_average",
            f"hi_{ENTRY_ID}_level2_pm25_average",
        }
    )

    data = _base_entry_data()
    data["show_output_entity_details"] = True
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=data, options={})
    hass = _FakeHass(entry, {})

    mapping = await register_mod.async_build_entity_mapping(hass, ENTRY_ID)
    cards = await register_mod.async_register_cards(hass, ENTRY_ID, mapping)

    assert "sensor.air_control_downstairs_pm25_average" not in mapping
    assert "sensor.air_control_upstairs_pm25_average" not in mapping
    assert hass.data["humidity_intelligence"][ENTRY_ID].get("unresolved_placeholders_by_card", {}) == {}

    for card in (cards.get("v2_mobile", ""), cards.get("v2_tablet", "")):
        assert "entity: sensor.air_control_downstairs_pm25_average" not in card
        assert "entity: sensor.air_control_upstairs_pm25_average" not in card
        assert "name: Level 1 PM2.5" not in card
        assert "name: Level 2 PM2.5" not in card
        assert "name: Level 1 IAQ" in card
        assert "name: Level 1 CO" in card


async def _run_alert_only_card_assertions(register_mod) -> None:
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: _FakeRegistry()

    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "alert_only_mode": True,
            "telemetry": [
                {"entity_id": "sensor.kitchen_h", "sensor_type": "humidity", "level": "level1", "room": "Kitchen"},
                {"entity_id": "sensor.kitchen_t", "sensor_type": "temperature", "level": "level1", "room": "Kitchen"},
            ],
            "zones": {},
            "humidifiers": {},
            "alerts": [],
        },
        options={},
    )
    hass = _FakeHass(entry, {})
    hass.config_entries = _FakeConfigEntries(entry)

    mapping = await register_mod.async_build_entity_mapping(hass, ENTRY_ID)
    cards = await register_mod.async_register_cards(hass, ENTRY_ID, mapping)
    mobile = cards.get("v2_mobile", "")
    tablet = cards.get("v2_tablet", "")

    assert "entity: input_boolean.air_control_enabled" not in mobile
    assert "entity: timer.air_control_pause" not in mobile
    assert "entity: input_boolean.air_control_output_expanded" not in mobile
    assert "- entity: fan.kitchen_air" not in mobile
    assert "- entity: humidifier.downstairs_humidifier" not in mobile
    for card in (mobile, tablet):
        reason_block = _v2_reason_block(card)
        assert "displayReason.schema !== 'hi.reason.v1'" in reason_block
        assert "Monitor + alerts only (no automation output controls configured)." not in reason_block
        assert "input_boolean.air_control_enabled" not in reason_block
    assert not _has_empty_cards_block(mobile)
    assert not _has_invalid_conditional_block(mobile)


async def _run_condensation_risk_alert_assertions(engine_mod) -> None:
    HIAutomationEngine = engine_mod.HIAutomationEngine
    original_resolver = engine_mod.resolve_target_profile

    def fixed_winter_resolver(config, now=None):
        # Test-only fixed date: runtime remains season-aware, this fixture does not.
        return original_resolver(config, datetime(2026, 1, 3))

    entry_data = _base_entry_data()
    entry_data["target_profile"] = "custom"
    entry_data["custom_target_low"] = 40
    entry_data["custom_target_high"] = 79
    entry_data["aq"] = {}
    entry_data["humidifiers"] = {}
    entry_data["alerts"] = [
        {
            "enabled": True,
            "trigger_type": "condensation_risk",
            "room": "Bedroom",
            "lights": [],
        }
    ]
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=entry_data,
        options={},
    )
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(45),
            "sensor.bed_h": _FakeState(77),
            "sensor.kitchen_t": _FakeState(22),
            "sensor.hall_t": _FakeState(22),
            "sensor.bed_t": _FakeState(20),
            "sensor.l1_iaq": _FakeState(85),
            "sensor.co_val": _FakeState(4),
        },
    )

    engine_mod.resolve_target_profile = fixed_winter_resolver
    try:
        engine = HIAutomationEngine(hass, entry)
        await engine._evaluate()
    finally:
        engine_mod.resolve_target_profile = original_resolver

    assert hass.data["humidity_intelligence"][ENTRY_ID].get("active_alert_context") == (
        "Condensation Risk · Bedroom · Zone 2"
    )
    assert any(
        domain == "fan"
        and service == "set_percentage"
        and data.get("entity_id") == "fan.zone2"
        and data.get("percentage") == 100
        for domain, service, data, _ in hass.services.calls
    )


def test_runtime_lane_order_and_service_simulation():
    engine_mod, _ = _load_target_modules()
    asyncio.run(_run_runtime_assertions(engine_mod))


def test_condensation_risk_alert_binds_to_zone_boost_with_fixed_profile():
    engine_mod, _ = _load_target_modules()
    asyncio.run(_run_condensation_risk_alert_assertions(engine_mod))


def test_custom_profile_condensation_thresholds_follow_current_season():
    engine_mod, _ = _load_target_modules()
    config = {
        "target_profile": "custom",
        "custom_target_low": 40,
        "custom_target_high": 79,
    }
    representative_spread = 4.16

    winter_profile = engine_mod.resolve_target_profile(config, datetime(2026, 1, 3))
    summer_profile = engine_mod.resolve_target_profile(config, datetime(2026, 6, 3))

    assert engine_mod.seasonal_condensation_risk(representative_spread, winter_profile) == "Risk"
    assert engine_mod.seasonal_condensation_risk(representative_spread, summer_profile) == "Watch"


def test_card_render_sanity_and_placeholder_resolution():
    _, register_mod = _load_target_modules()
    asyncio.run(_run_card_assertions(register_mod))


def test_level_label_card_replacement_is_single_pass_for_swapped_names():
    _, register_mod = _load_target_modules()

    rendered = register_mod._apply_level_labels(
        "AQ Downstairs / AQ Upstairs / Downs.. IAQ / name: Downstairs IAQ",
        {"level1": "Upstairs", "level2": "Downstairs"},
    )

    assert rendered == "AQ Upstairs / AQ Downstairs / Upstairs IAQ / name: Upstairs IAQ"


def test_output_detail_visibility_option_prunes_v2_cards():
    _, register_mod = _load_target_modules()
    asyncio.run(_run_output_detail_visibility_assertions(register_mod))


def test_optional_aq_output_detail_rows_prune_when_aggregate_entities_are_unresolved():
    _, register_mod = _load_target_modules()
    asyncio.run(_run_optional_aq_output_detail_pruning_assertions(register_mod))


def test_card_render_hides_controls_in_alert_only_mode():
    _, register_mod = _load_target_modules()
    asyncio.run(_run_alert_only_card_assertions(register_mod))


def test_temperature_normalization_respects_source_units():
    engine_mod, _ = _load_target_modules()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={}, options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.temp_f": _FakeState(68, {"unit_of_measurement": "°F"}),
            "sensor.temp_c": _FakeState(20, {"unit_of_measurement": "°C"}),
            "sensor.temp_no_unit": _FakeState(21),
        },
    )

    from_f = engine_mod._get_float(hass, "sensor.temp_f", sensor_type="temperature")
    from_c = engine_mod._get_float(hass, "sensor.temp_c", sensor_type="temperature")
    from_missing_unit = engine_mod._get_float(hass, "sensor.temp_no_unit", sensor_type="temperature")

    assert from_f is not None and abs(from_f - 20.0) < 0.05
    assert from_c is not None and abs(from_c - 20.0) < 0.05
    assert from_missing_unit is not None and abs(from_missing_unit - 21.0) < 0.05


def test_temperature_comfort_profiles_use_explicit_seasonal_warm_boundaries():
    core_mod = _load_core_module()
    cases = [
        (datetime(2026, 1, 15), "winter", 20.0, 21.0, 21.5),
        (datetime(2026, 4, 15), "spring", 20.5, 22.0, 23.5),
        (datetime(2026, 7, 15), "summer", 21.0, 24.0, 26.5),
        (datetime(2026, 10, 15), "autumn", 20.0, 21.5, 23.0),
    ]

    for now, key, low, high, warm_high in cases:
        profile = core_mod.resolve_temperature_comfort_profile(
            {"temperature_comfort_mode": "auto"},
            now,
        )

        assert profile.key == key
        assert profile.low == low
        assert profile.high == high
        assert profile.warm_high == warm_high
        assert core_mod.temperature_comfort_state(low - 0.1, profile) == "below_comfort"
        assert core_mod.temperature_comfort_state(high, profile) == "in_comfort"
        assert core_mod.temperature_comfort_state((high + warm_high) / 2, profile) == "above_comfort_watch"
        assert core_mod.temperature_comfort_state(warm_high + 0.1, profile) == "above_comfort_high"


def test_custom_temperature_comfort_keeps_high_plus_one_warm_boundary():
    core_mod = _load_core_module()

    profile = core_mod.resolve_temperature_comfort_profile(
        {
            "temperature_comfort_mode": "custom",
            "temperature_comfort_custom_low": 18.5,
            "temperature_comfort_custom_high": 22.0,
        },
        datetime(2026, 7, 15),
    )

    assert profile.key == "custom"
    assert profile.low == 18.5
    assert profile.high == 22.0
    assert profile.warm_high == 23.0
    assert core_mod.temperature_comfort_state(22.5, profile) == "above_comfort_watch"
    assert core_mod.temperature_comfort_state(23.1, profile) == "above_comfort_high"


async def _registered_flash_handler(services_mod, hass):
    await services_mod.async_register_services(hass)
    return hass.services.handlers[(services_mod.DOMAIN, services_mod.SERVICE_FLASH_LIGHTS)]


def _light_service_calls(hass):
    return [
        (service, data)
        for domain, service, data, _blocking in hass.services.calls
        if domain == "light"
    ]


async def _run_visual_flash_restore_assertions(services_mod) -> None:
    original_sleep = services_mod.asyncio.sleep

    async def fast_sleep(_delay):
        await original_sleep(0)

    services_mod.asyncio.sleep = fast_sleep
    try:
        attrs = {
            "supported_color_modes": ["rgb"],
            "brightness": 77,
            "rgb_color": (1, 2, 3),
        }
        payload = {
            "lights": ["light.alert"],
            "color": [255, 0, 0],
            "duration": 10,
            "flash_count": 10,
        }

        hass_on = _FlashHass({"light.alert": _FakeState("on", attrs)})
        handler_on = await _registered_flash_handler(services_mod, hass_on)
        await handler_on(
            SimpleNamespace(
                data=payload,
                context=SimpleNamespace(user_id="admin"),
            )
        )
        on_calls = _light_service_calls(hass_on)
        assert [service for service, _data in on_calls[:20]] == ["turn_on", "turn_off"] * 10
        assert len(on_calls) == 21
        assert on_calls[-1][0] == "turn_on"
        assert on_calls[-1][1]["brightness"] == 77
        assert on_calls[-1][1]["rgb_color"] == (1, 2, 3)
        assert hass_on.states.get("light.alert").state == "on"

        hass_off = _FlashHass({"light.alert": _FakeState("off", attrs)})
        handler_off = await _registered_flash_handler(services_mod, hass_off)
        await handler_off(
            SimpleNamespace(
                data=payload,
                context=SimpleNamespace(user_id="admin"),
            )
        )
        off_calls = _light_service_calls(hass_off)
        assert [service for service, _data in off_calls[:20]] == ["turn_on", "turn_off"] * 10
        assert len(off_calls) == 21
        assert off_calls[-1][0] == "turn_off"
        assert hass_off.states.get("light.alert").state == "off"

        hass_overlap = _FlashHass({"light.alert": _FakeState("on", attrs)})
        handler_overlap = await _registered_flash_handler(services_mod, hass_overlap)
        await asyncio.gather(
            handler_overlap(
                SimpleNamespace(
                    data=payload,
                    context=SimpleNamespace(user_id="admin"),
                )
            ),
            handler_overlap(
                SimpleNamespace(
                    data=payload,
                    context=SimpleNamespace(user_id="admin"),
                )
            ),
        )
        overlap_services = [service for service, _data in _light_service_calls(hass_overlap)]
        one_sequence = ["turn_on", "turn_off"] * 10 + ["turn_on"]
        assert overlap_services == one_sequence + one_sequence
        assert hass_overlap.states.get("light.alert").state == "on"
    finally:
        services_mod.asyncio.sleep = original_sleep


def test_visual_alert_flash_restores_initial_light_state_and_serializes_overlap():
    services_mod = _load_services_module()
    asyncio.run(_run_visual_flash_restore_assertions(services_mod))


def test_pause_and_resume_require_admin_for_targeted_and_global_calls():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth(
        {
            "admin": SimpleNamespace(is_admin=True),
            "viewer": SimpleNamespace(is_admin=False),
        }
    )

    asyncio.run(services_mod.async_register_services(hass))
    pause_handler = hass.services.handlers[(services_mod.DOMAIN, services_mod.SERVICE_PAUSE_CONTROL)]
    resume_handler = hass.services.handlers[(services_mod.DOMAIN, services_mod.SERVICE_RESUME_CONTROL)]
    timer = hass.data[services_mod.DOMAIN][ENTRY_ID]["hi_timers"]["air_control_pause"]

    for handler, action in (
        (pause_handler, "pause"),
        (resume_handler, "resume"),
    ):
        for context in (
            SimpleNamespace(user_id="viewer"),
            SimpleNamespace(user_id=None),
        ):
            try:
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={"entry_id": ENTRY_ID},
                            context=context,
                        )
                    )
                )
            except Exception as err:
                assert "requires an admin user" in str(err)
            else:
                raise AssertionError(f"targeted {action} should require admin context")

    assert timer.start_calls == 0
    assert timer.cancel_calls == 0

    asyncio.run(
        pause_handler(
            SimpleNamespace(
                data={"entry_id": ENTRY_ID},
                context=SimpleNamespace(user_id="admin"),
            )
        )
    )
    asyncio.run(
        resume_handler(
            SimpleNamespace(
                data={"entry_id": ENTRY_ID},
                context=SimpleNamespace(user_id="admin"),
            )
        )
    )
    assert timer.start_calls == 1
    assert timer.cancel_calls == 1

    try:
        asyncio.run(pause_handler(SimpleNamespace(data={}, context=SimpleNamespace(user_id="viewer"))))
    except Exception as err:
        assert "requires an admin user" in str(err)
    else:
        raise AssertionError("global pause should reject non-admin user context")

    assert timer.start_calls == 1

    asyncio.run(pause_handler(SimpleNamespace(data={}, context=SimpleNamespace(user_id="admin"))))
    assert timer.start_calls == 2
    assert timer.native_value == "active"

    try:
        asyncio.run(resume_handler(SimpleNamespace(data={}, context=SimpleNamespace(user_id="viewer"))))
    except Exception as err:
        assert "requires an admin user" in str(err)
    else:
        raise AssertionError("global resume should reject non-admin user context")

    assert timer.cancel_calls == 1

    asyncio.run(resume_handler(SimpleNamespace(data={}, context=SimpleNamespace(user_id="admin"))))
    assert timer.cancel_calls == 2
    assert timer.native_value == "idle"


def test_support_state_summary_treats_blank_state_as_unknown():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {"sensor.blank_state": _FakeState("   ")})

    summary = services_mod._support_state_summary(hass, ["sensor.blank_state"])

    assert summary == {
        "count": 1,
        "by_status": {"available": 0, "missing": 0, "unknown": 1, "unavailable": 0},
    }


def test_public_card_surfaces_do_not_ship_private_entity_ids():
    offenders = []
    for path in PUBLIC_CARD_SURFACES:
        if not path.exists():
            continue
        source = path.read_text()
        for marker in PRIVATE_CARD_IDENTIFIERS:
            if marker in source:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")

    assert offenders == []


def test_default_public_card_surfaces_block_unsafe_service_controls():
    default_surfaces = (
        INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
        INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
        INTEGRATION_ROOT / "ui" / "cards" / "view_cards_button.yaml",
        ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
        ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    )
    mutation_markers = (
        "action: call-service",
        "action: toggle",
        "humidity_intelligence.pause_control",
        "humidity_intelligence.resume_control",
        "humidity_intelligence.refresh_ui",
        "humidity_intelligence.dump_cards",
        "humidity_intelligence.view_cards",
        "humidity_intelligence.create_dashboard",
        "humidity_intelligence.purge_files",
    )
    offenders = []
    for path in default_surfaces:
        source = path.read_text(encoding="utf-8")
        source = _strip_allowed_output_expander_toggle(source)
        source = _strip_allowed_v207_control_toggles(source)
        for marker in mutation_markers:
            if marker in source:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")

    assert offenders == []


def test_system_and_manual_buttons_use_v207_toggle_actions():
    missing = []
    hold_action = "          hold_action:\n            action: more-info"
    labels = {
        "input_boolean.air_control_enabled": "System",
        "input_boolean.air_control_manual_override": "Manual",
    }
    for path in OUTPUT_DETAILS_SURFACES:
        source = path.read_text(encoding="utf-8")
        for entity_id, label in labels.items():
            block = _button_card_block(source, entity_id)
            if V207_CONTROL_TOGGLE_ACTION not in block:
                missing.append(f"{path.relative_to(ROOT)}: {label} tap toggle missing")
            if hold_action not in block:
                missing.append(f"{path.relative_to(ROOT)}: {label} hold more-info missing")

    assert missing == []


def test_output_details_header_uses_v207_expander_toggle_action():
    missing = []
    for path in OUTPUT_DETAILS_SURFACES:
        source = path.read_text(encoding="utf-8")
        block = _output_details_block(source)
        if OUTPUT_EXPANDER_TOGGLE_ACTION not in block:
            missing.append(f"{path.relative_to(ROOT)}: missing output expander toggle")

    assert missing == []


def test_v2_reason_panels_use_backend_schema_with_atomic_escaped_fallback():
    blocks = []
    required = (
        "states['sensor.air_control_reason']",
        "reasonState?.attributes?.display_reason",
        "displayReason.schema !== 'hi.reason.v1'",
        "displayReason.locale !== 'en'",
        "const hasExactKeys =",
        "const codePointLength = (value) => Array.from(value).length",
        "displayReason.lines.length > 8",
        "keys.length > 6",
        "new TextEncoder().encode(JSON.stringify(displayReason)).length <= 4096",
        "displayReason.lines.map((line) => escapeHtml(line.text))",
        "escapeHtml(displayReason.headline)",
        "reasonState?.attributes?.full_reason",
        "reasonState?.state",
        "return 'Reason unavailable.'",
        'role="region"',
        'aria-label="Current Air Control reason"',
        'tabindex="0"',
    )
    forbidden = (
        "greenNoise",
        "showReason",
        "Stage:",
        "Engine:",
        "Risk:",
        "Timer:",
        "Testing safeguard:",
        "Alert context active.",
        "timer.air_",
        "input_boolean.air_",
        "sensor.worst_room_",
        "alert_telemetry",
        "humidifier_status",
    )

    for path in V2_REASON_SURFACES:
        source = path.read_text(encoding="utf-8")
        block = _v2_reason_block(source)
        blocks.append(block)
        for marker in required:
            assert marker in block, (path.relative_to(ROOT), marker)
        for marker in forbidden:
            assert marker not in block, (path.relative_to(ROOT), marker)
        assert block.count("states[") == 1
        assert block.index("reasonState?.attributes?.full_reason") < block.index(
            "reasonState?.state"
        )
        assert "max-height: 60px" in source
        assert "overflow-y: auto" in source
        assert ".cv-reason:focus-visible" in source
        assert ".cv-reason__headline" in source

    assert len(set(blocks)) == 1

    v1_mobile = (INTEGRATION_ROOT / "ui" / "cards" / "v1_mobile.yaml").read_text(
        encoding="utf-8"
    )
    v1_gallery = (
        ROOT / "ui-gallery" / "default-v1-mobile" / "card.yaml"
    ).read_text(encoding="utf-8")
    for source in (v1_mobile, v1_gallery):
        assert "display_reason" not in source
        assert "hi.reason.v1" not in source


def test_default_public_card_surfaces_use_passive_stability_badge_instead_of_pause_tile():
    default_surfaces = (
        INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
        INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
        ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
        ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    )
    forbidden_pause_tile_markers = (
        "name: Pause",
        "icon: mdi:pause-circle",
        "return entity.state === 'active' ? 'PAUSED' : 'LIVE';",
    )
    missing_stability_markers = []
    pause_tile_offenders = []
    stability_blocks = []
    for path in default_surfaces:
        source = path.read_text(encoding="utf-8")
        stability_block = _button_card_block(source, "sensor.hi_diagnostics")
        stability_blocks.append(stability_block)
        for marker in forbidden_pause_tile_markers:
            if marker in source:
                pause_tile_offenders.append(f"{path.relative_to(ROOT)}: {marker}")
        for marker in (
            "type: custom:button-card",
            "name: Stability Score",
            "entity: sensor.hi_diagnostics",
            "show_label: false",
            "hi-stability-gauge",
            "hi-stability-gauge-white",
            "hi-stability-leds",
            'return `<i class="led-${index} ${active ? \'active\' : \'\'}"></i>`;',
            ".hi-stability-leds i.led-3 { left: 40px; top: 2px; }",
            "const hasNestedStabilityContract =",
            "Object.prototype.hasOwnProperty.call(summary, 'stability_score');",
            "const hasStabilityContract =",
            "const preview = !hasValue && !hasStabilityContract;",
            "const completeWhite = hasValue && (value >= 99 || classification === 'excellent');",
            "preview ? '#f8fafc'",
            "completeWhite ? '#f8fafc'",
            "preview ? 'hi-stability-gauge-preview' : '',",
            ".hi-stability-gauge-preview::before,",
            ".hi-stability-gauge-preview .hi-stability-leds i.active,",
            "animation: hi-stability-white-shimmer 6000ms ease-in-out infinite;",
            "animation: hi-stability-led-shimmer 6000ms ease-in-out infinite;",
            "@keyframes hi-stability-white-shimmer",
            "@keyframes hi-stability-led-shimmer",
            "@media (prefers-reduced-motion: reduce)",
            "- border: 1px solid rgba(148,163,184,0.22)",
            "- box-shadow: inset 0 0 0 1px rgba(255,255,255,0.035), 0 0 16px rgba(15,23,42,0.55)",
            "inset: 14px;",
            "box-shadow: 0 0 9px 3px var(--hi-stability-color);",
            "display_score",
            "display_classification",
            "const hasRawValue = rawValue !== null && rawValue !== undefined && rawValue !== '';",
            "const value = hasRawValue ? Number(rawValue) : NaN;",
            "const hasValue = hasRawValue && Number.isFinite(value);",
            "const valueText = hasValue ? String(Math.round(value)) : preview ? '2.1' : '—';",
            "preview ? 'PREVIEW'",
            "unavailable ? 'NO DATA'",
            "collecting ? 'COLLECTING'",
            "'NO SCORE'",
            "const gaugeClass = [",
            'role="img" aria-label="${accessibilityText}" title="${accessibilityText}"',
            "const normalized = hasValue ? Math.max(-1, Math.min(1, (value - 50) / 50)) : 0;",
            "direction === 'left'",
        ):
            if marker not in source:
                missing_stability_markers.append(f"{path.relative_to(ROOT)}: {marker}")
        proven_stability_position = """            custom_fields:
              gauge:
                - grid-area: gauge
                - align-self: center
                - justify-self: center
          extra_styles: |
"""
        if proven_stability_position not in stability_block:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: Stability wrapper differs from the established centred layout"
            )
        proven_stability_name_area = """            name:
              - grid-area: 'n'
"""
        if proven_stability_name_area not in stability_block:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: Stability name grid area must remain the quoted string 'n'"
            )
        for marker in (
            "\n              - grid-area: n\n",
            "\n              - grid-area: false\n",
        ):
            if marker in stability_block:
                missing_stability_markers.append(
                    f"{path.relative_to(ROOT)}: Stability name grid area can be coerced to YAML boolean false"
                )
        proven_inner_gauge_position = """            .hi-stability-gauge {
              width: 82px;
              height: 82px;
              border-radius: 999px;
"""
        if proven_inner_gauge_position not in stability_block:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: fixed-width Stability gauge geometry has drifted"
            )
        if "margin-inline: auto;" in stability_block:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: Stability gauge still relies on inner auto margins"
            )
        for marker in ("- align-self: stretch", "- justify-self: stretch"):
            if marker in stability_block:
                missing_stability_markers.append(
                    f"{path.relative_to(ROOT)}: Stability position uses the rejected stretch layout"
                )
        for entity_id in (
            "input_boolean.air_control_enabled",
            "input_boolean.air_control_manual_override",
        ):
            block = _button_card_block(source, entity_id)
            if "- box-shadow: 0 0 18px rgba(148,163,184,0.12)" not in block:
                missing_stability_markers.append(
                    f"{path.relative_to(ROOT)}: missing v2 control glow for {entity_id}"
                )
        if source.count("min-height: 132px") < 3:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: System/Stability/Manual row height mismatch"
            )
        if "hi-stability-ring" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale button-card ring")
        if "type: custom:custom-gauge-card" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: invalid custom gauge dependency")
        if "attribute: stability_score_display_score" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: invalid flattened score attribute")
        if "FUTURE 2.1" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale bottom future label")
        if "const completeWhite = !hasValue" in source:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: absent Stability data still inherits completed styling"
            )
        if "const unitText = hasValue ? 'score' : 'future';" in source:
            missing_stability_markers.append(
                f"{path.relative_to(ROOT)}: stale internal future fallback copy"
            )
        if "repeating-conic-gradient" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale full-circumference LED halo")
        if "bottom: 5px;" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale bottom LED row")
        if "box-shadow: 0 0 15px 5px var(--hi-stability-color);" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale oversized center aura")
        if "return `2px solid ${color}`;" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stability border no longer matches row")
        if "return `1px solid ${color}`;" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stability border light should be off")
        if "box-shadow: 0 0 6px 2px var(--hi-stability-color);" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale undersized center aura")
        if "classification === 'excellent' ? '#22c55e'" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: completed stability hue is not white")
        if "classification === 'excellent' ? '#38bdf8'" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: completed stability hue is not white")
        if "hi-stability-white-shimmer 2600ms" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale 2600ms stability pulse")
        if "hi-stability-led-shimmer 2600ms" in source:
            missing_stability_markers.append(f"{path.relative_to(ROOT)}: stale 2600ms stability led pulse")

    assert pause_tile_offenders == []
    assert missing_stability_markers == []
    assert len(set(stability_blocks)) == 1


def test_public_v2_gallery_cards_preserve_air_control_mode_truth():
    gallery_cards = (
        ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
        ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    )

    for path in gallery_cards:
        source = path.read_text()
        assert "states['sensor.air_control_mode']?.state || 'normal'" not in source
        assert "entity.state || 'normal'" not in source
        assert "'telemetry_unavailable'," in source
        assert "const modeKnown =" in source
        assert "const mode = modeKnown ? rawMode : 'unknown'" in source
        assert "if (!modeKnown) return 'UNKNOWN';" in source
        assert "const ready = modeKnown && mode === 'normal'" in source
        assert "states['binary_sensor.humidity_danger']?.state === 'on'" not in source
        assert "states['binary_sensor.condensation_danger']?.state === 'on'" not in source
        assert "states['binary_sensor.mould_danger']?.state === 'on'" not in source
        assert "_humidity_danger']?.state === 'on'" not in source
        assert "_condensation_danger']?.state === 'on'" not in source
        assert "_mould_danger']?.state === 'on'" not in source
        assert "if (mode === 'telemetry_unavailable') return '#f59e0b';" in source
        assert "if (mode === 'telemetry_unavailable') return 'TELEMETRY UNAVAILABLE';" in source
        assert "tempColor(tempValueC(entity))" in source
        assert "slopeEntityFor(item)" in source
        assert "displayReason.schema !== 'hi.reason.v1'" in source
        assert "displayReason.lines.map((line) => escapeHtml(line.text))" in source
        assert "Stage:" not in _v2_reason_block(source)
        assert "Engine:" not in _v2_reason_block(source)
        assert "if (mode === 'telemetry_unavailable') return '1px solid rgba(245,158,11" in source
        assert source.index("if (mode === 'telemetry_unavailable') return '#f59e0b';") < source.index("if (red || coE")
        assert source.index("if (!modeKnown) return '#94a3b8';") < source.index("if (red || coE")
        assert source.index("if (mode === 'telemetry_unavailable') return 'TELEMETRY UNAVAILABLE';") < source.index("if (red) return 'ALERT';")
        assert source.index("if (!modeKnown) return 'UNKNOWN';") < source.index("if (red) return 'ALERT';")
        assert "const borderModeKnown =" in source
        assert "if (!borderModeKnown) return '1px solid rgba(148,163,184,0.55)';" in source
        assert source.index("if (!borderModeKnown) return '1px solid rgba(148,163,184,0.55)';") < source.index("if (red) return '1px solid rgba(239,68,68,0.85)'")
        assert source.index("if (mode === 'telemetry_unavailable') return '1px solid rgba(245,158,11") < source.index("if (red) return '1px solid rgba(239,68,68,0.85)'")


def test_startup_ui_refresh_contract_is_wired():
    init_source = (INTEGRATION_ROOT / "__init__.py").read_text()
    const_source = (INTEGRATION_ROOT / "const.py").read_text()
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    strings_source = (INTEGRATION_ROOT / "strings.json").read_text()
    services_source = (INTEGRATION_ROOT / "services.yaml").read_text()

    assert "EVENT_HOMEASSISTANT_STARTED" in init_source
    assert ".async_listen_once(" in init_source
    assert "@callback" in init_source
    assert "hass.create_task(_run_startup_ui_refresh())" in init_source
    assert "hass.async_create_task(_async_refresh_and_dump_cards" not in init_source
    assert ".add_done_callback(" not in init_source
    assert "startup_ui_refresh_scheduled" in init_source
    assert "SERVICE_REFRESH_UI" in init_source
    assert '"dump_cards",' not in init_source
    assert "STARTUP_UI_REFRESH_DELAY_SECONDS" in init_source
    assert "blocking=True" in init_source
    assert "auto_refresh_ui_on_startup" in const_source
    assert "show_output_entity_details" in const_source
    assert "CONF_AUTO_REFRESH_UI_ON_STARTUP" in config_source
    assert "DEFAULT_AUTO_REFRESH_UI_ON_STARTUP" in config_source
    assert "CONF_SHOW_OUTPUT_ENTITY_DETAILS" in config_source
    assert "DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS" in config_source
    assert "ADVANCED_OPTIONS_FIELD" in config_source
    assert "show_advanced_options" in config_source
    assert '"show_advanced_options": "Show advanced tuning"' in strings_source
    assert "show_output_entity_details" in strings_source
    assert "Show output entity details" in strings_source
    assert "['v2_tablet']" in config_source or 'default=["v2_tablet"]' in config_source
    assert "async_step_options_thresholds" in config_source
    assert "zone1_threshold_humidity_high" in strings_source
    assert "temperature_comfort_mode" in strings_source
    assert "auto_refresh_ui_on_startup" in strings_source
    assert "recommended defaults" in config_source
    assert "recommended thresholds" in strings_source
    assert "automatically shortly after Home Assistant startup" in services_source
    assert "_entry_show_output_entity_details" in init_source
    assert "generated-card output details" in init_source
    assert "UI visibility changes" in init_source
    startup_method = init_source.split(
        "async def _async_delayed_startup_ui_refresh",
        1,
    )[1].split("def _entry_auto_refresh_ui_on_startup", 1)[0]
    assert "SERVICE_REFRESH_UI" in startup_method
    assert "async_export_cards_to_owned_ui" not in startup_method


def test_options_refresh_uses_trusted_card_export_after_mapping_refresh():
    integration_mod = _load_integration_init_module()
    events = []

    async def async_call(domain, service, data=None, blocking=False):
        events.append(("service", domain, service, data or {}, blocking))

    async def export_cards(_hass, entry_id, filename, layout=None):
        events.append(("export", entry_id, filename, layout))
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        ]

    integration_mod.async_export_cards_to_owned_ui = export_cards
    hass = SimpleNamespace(
        services=SimpleNamespace(async_call=async_call),
    )

    asyncio.run(integration_mod._async_refresh_and_dump_cards(hass, ENTRY_ID))

    assert events == [
        (
            "service",
            integration_mod.DOMAIN,
            "refresh_ui",
            {"entry_id": ENTRY_ID},
            True,
        ),
        ("export", ENTRY_ID, None, None),
    ]


def test_options_update_reloads_entry_then_regenerates_owned_ui_with_loaded_code():
    integration_mod = _load_integration_init_module()
    events = []

    async def async_reload(entry_id):
        events.append(("reload", entry_id))

    async def refresh_and_dump(_hass, entry_id):
        events.append(("refresh_export", entry_id))
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_entry123_v2_mobile.yaml"
        ]

    async def async_call(domain, service, data=None, blocking=False):
        events.append(
            (
                "service",
                domain,
                service,
                data or {},
                blocking,
            )
        )

    integration_mod._async_refresh_and_dump_cards = refresh_and_dump
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={},
        options={
            "alert_only_mode": True,
            "show_output_entity_details": False,
        },
    )
    hass = SimpleNamespace(
        data={
            integration_mod.DOMAIN: {
                ENTRY_ID: {
                    "config": {
                        "alert_only_mode": False,
                        "show_output_entity_details": False,
                    }
                }
            }
        },
        config_entries=SimpleNamespace(async_reload=async_reload),
        services=SimpleNamespace(async_call=async_call),
    )

    asyncio.run(integration_mod._async_options_updated(hass, entry))

    assert events[0:2] == [
        ("reload", ENTRY_ID),
        ("refresh_export", ENTRY_ID),
    ]
    notification = events[2]
    assert notification[0:3] == (
        "service",
        "persistent_notification",
        "create",
    )
    assert (
        "/config/humidity_intelligence/ui/"
        "humidity_intelligence_cards_entry123_v2_mobile.yaml"
        in notification[3]["message"]
    )
    assert "Use only the exact paths above" in notification[3]["message"]
    assert "legacy generated card files in the /config root" in (
        notification[3]["message"]
    )


def test_options_update_reports_export_failure_without_success_path():
    integration_mod = _load_integration_init_module()
    service_calls = []

    async def async_reload(_entry_id):
        return None

    async def failed_refresh_and_dump(_hass, _entry_id):
        raise RuntimeError("fixture writer rejected")

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    integration_mod._async_refresh_and_dump_cards = failed_refresh_and_dump
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={},
        options={
            "alert_only_mode": True,
            "show_output_entity_details": False,
        },
    )
    hass = SimpleNamespace(
        data={
            integration_mod.DOMAIN: {
                ENTRY_ID: {
                    "config": {
                        "alert_only_mode": False,
                        "show_output_entity_details": False,
                    }
                }
            }
        },
        config_entries=SimpleNamespace(async_reload=async_reload),
        services=SimpleNamespace(async_call=async_call),
    )

    asyncio.run(integration_mod._async_options_updated(hass, entry))

    notifications = [
        call
        for call in service_calls
        if call[0:2] == ("persistent_notification", "create")
    ]
    assert len(notifications) == 1
    assert notifications[0][2]["title"] == (
        "Humidity Intelligence UI Update Incomplete"
    )
    assert "fixture writer rejected" in notifications[0][2]["message"]
    assert "files were written" not in notifications[0][2]["message"]


def test_options_gates_keeps_custom_targets_behind_advanced():
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    method_source = config_source.split("async def async_step_options_gates", 1)[1].split(
        "async def async_step_options_presence_states", 1
    )[0]
    schema_source = method_source.split("schema_fields: Dict[Any, Any]", 1)[1]
    visible_schema_source = schema_source.split("vol.Optional(ADVANCED_OPTIONS_FIELD", 1)[0]
    advanced_schema_source = schema_source.split("vol.Optional(ADVANCED_OPTIONS_FIELD", 1)[1]

    assert 'vol.Optional("target_profile"' in visible_schema_source
    assert '"custom_target_low"' not in visible_schema_source
    assert '"custom_target_high"' not in visible_schema_source
    assert '"custom_target_low"' in advanced_schema_source
    assert '"custom_target_high"' in advanced_schema_source


def test_options_thresholds_only_persists_real_zone_configs():
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    method_source = config_source.split("async def async_step_options_thresholds", 1)[1].split(
        "async def async_step_options_sensors", 1
    )[0]

    assert "_configured_zone_items(zones)" in method_source
    assert 'for zone_key in ("zone1", "zone2")' not in method_source
    assert "zones[zone_key] = zone" in method_source
    assert "zone[\"thresholds\"] = thresholds" in method_source


def test_advanced_tuning_uses_collapsible_sections_not_submit_reveal():
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()

    assert "from homeassistant.data_entry_flow import section" in config_source
    assert "def _advanced_section(" in config_source
    assert "section(vol.Schema(fields), {\"collapsed\": True})" in config_source
    assert "_flatten_advanced_section_input(user_input)" in config_source
    assert "_should_reveal_advanced" not in config_source
    assert "_advanced_toggle" not in config_source
    assert "self._advanced_visible" not in config_source
    assert "self._advanced_inputs" not in config_source
    assert 'slope_sources = _sanitize_entity_ids(user_input.get("slope_sources") or temp_entities)' in config_source
    assert 'slope_sources = _sanitize_entity_ids(user_input.get("slope_sources") or default_sources)' in config_source
    assert '"run_duration": user_input.get("run_duration", existing.get("run_duration", 30))' in config_source

    advanced_steps = (
        "async_step_gates",
        "async_step_slope",
        "_async_step_zone_config",
        "async_step_zone_thresholds",
        "_async_step_humidifier",
        "_async_step_aq",
        "async_step_aq_thresholds",
        "async_step_alert_add",
        "async_step_options_gates",
        "async_step_options_thresholds",
        "async_step_options_zone_edit",
        "async_step_options_humidifier_edit",
        "async_step_options_aq_edit",
        "async_step_options_alert_add",
        "async_step_options_alert_edit",
        "async_step_options_slope",
    )
    for step_name in advanced_steps:
        method_source = config_source.split(f"async def {step_name}", 1)[1].split(
            "\n    async def ",
            1,
        )[0]
        assert "user_input = _flatten_advanced_section_input(user_input)" in method_source
        assert "_advanced_section(" in method_source


def test_readme_uses_manifest_version_badge_not_static_ha_compatibility_badge():
    readme_source = (ROOT / "README.md").read_text()

    assert "dynamic/json" in readme_source
    assert "manifest.json" in readme_source
    assert "query=%24.version" in readme_source
    assert "Home%20Assistant-2026.4.3%2B" not in readme_source


def test_readme_keeps_three_current_release_summaries_before_previous_releases():
    readme_source = (ROOT / "README.md").read_text()
    release_notes = readme_source.split("## Release Notes", 1)[1]
    visible_notes, previous_releases = release_notes.split("<details>", 1)

    assert "### v2.0.12 (Maintenance candidate; not published)" in visible_notes
    assert "### v2.0.11 — Poetic Justice (Current Published Stable)" in visible_notes
    assert "### v2.0.10 (Previous Published Stable)" in visible_notes
    assert "was published on 11 August 2026" in visible_notes
    assert "was published on 2026-08-10" in visible_notes
    assert "### v2.0.9" not in visible_notes
    assert "### v2.0.8" not in visible_notes
    assert "### v2.0.9" in previous_releases
    assert "set integration metadata to stable `2.0.9`" in previous_releases
    assert "v2.0.1 through v2.0.8" in previous_releases
    assert "assets/release_banner/v2.0.9_release.png" not in visible_notes
    assert (ROOT / "assets" / "release_banner" / "v2.0.9_release.png").read_bytes()[:8] == (
        b"\x89PNG\r\n\x1a\n"
    )
    assert (ROOT / "assets" / "release_banner" / "v2.0.10_release.png").read_bytes()[:8] == (
        b"\x89PNG\r\n\x1a\n"
    )
    assert (ROOT / "assets" / "release_banner" / "v2.0.11_release.png").read_bytes()[:8] == (
        b"\x89PNG\r\n\x1a\n"
    )
    assert (ROOT / "assets" / "release_banner" / "v2.0.12_release.png").read_bytes()[:8] == (
        b"\x89PNG\r\n\x1a\n"
    )
    assert "<summary>Previous Releases</summary>" in previous_releases
    assert "current candidate, current Published" in visible_notes
    assert (
        "https://my.home-assistant.io/redirect/hacs_repository/"
        "?owner=senyo888&repository=humidity-intelligence&category=integration"
        in readme_source
    )
    assert "it does not install automatically" in readme_source


def test_v2012_public_release_surfaces_track_candidate_and_v2011_stable_truth():
    readme_source = (ROOT / "README.md").read_text()
    release_notes = readme_source.split("## Release Notes", 1)[1]
    visible_notes = release_notes.split("<details>", 1)[0]
    changelog_source = (ROOT / "CHANGELOG.md").read_text()
    release_governance = (ROOT / "docs" / "release-governance.md").read_text()
    normalized_readme = " ".join(readme_source.split())
    normalized_visible_notes = " ".join(visible_notes.split())
    normalized_changelog = " ".join(changelog_source.split())
    normalized_governance = " ".join(release_governance.split())

    assert "Current development manifest version: **v2.0.12-beta.4**" in normalized_readme
    assert "It is not a published release" in normalized_readme
    assert "current published Stable GitHub Release and tag are **v2.0.11**" in normalized_readme
    assert "included in the HACS default repository" in normalized_readme
    assert "carries development manifest identity `2.0.12-beta.4`" in normalized_visible_notes
    assert "not a published GitHub Release or an HACS-offered v2.0.12 package" in normalized_visible_notes
    assert "Manual override a complete handover" in normalized_visible_notes
    assert "observed-only `manual_hold`" in normalized_visible_notes
    assert "normal non-Manual AUTO ownership" in normalized_visible_notes
    assert "CO remains the sole ventilation exception" in normalized_visible_notes
    assert "canonical lane order, output ownership" not in normalized_visible_notes
    assert "0dd3e68ab9f35608641dc64efc4b2c4bfacb06ce" in normalized_visible_notes
    assert "## 2.0.11 - 2026-08-11" in changelog_source
    assert "Advanced development identity to `2.0.12-beta.2`" in normalized_changelog
    assert "Advanced the development identity to `2.0.12-beta.3`" in normalized_changelog
    assert "Advanced the development identity to `2.0.12-beta.4`" in normalized_changelog
    assert "Published Stable is `2.0.11`" in normalized_governance
    assert "Manual override output-handover repair" in normalized_governance
    assert "Manual ownership/reconciliation/diagnostic truth" in normalized_governance
    assert "normal non-Manual AUTO semantics" in normalized_governance
    assert "## v2.0.12 Release Checklist" in release_governance
    assert "No Manual-card re-export" in normalized_governance
    assert "v2.0.11 release source is now on `main`" not in normalized_readme
    assert "GitHub Release draft is release preparation only" not in normalized_governance


def test_dump_cards_without_layout_exports_all_cached_layouts():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID)
    cards = {
        "v2_mobile": "mobile-card",
        "v2_tablet": "tablet-card",
        "v1_mobile": "legacy-card",
        "view_cards_button": "button-card",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _DumpCardsHass(tmpdir, [entry], {ENTRY_ID: cards})
        written = asyncio.run(
            services_mod.async_export_cards_to_owned_ui(
                hass,
                entry_id=None,
                filename="humidity_intelligence_cards",
                layout=None,
            )
        )

        assert written == [
            "/config/humidity_intelligence/ui/humidity_intelligence_cards_v2_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_cards_v2_tablet.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_cards_v1_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_cards_view_cards_button.yaml",
        ]
        for layout, yaml in cards.items():
            path = (
                pathlib.Path(tmpdir)
                / "humidity_intelligence"
                / "ui"
                / f"humidity_intelligence_cards_{layout}.yaml"
            )
            assert path.read_text() == yaml


def test_dump_cards_with_layout_exports_only_requested_layout():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID)
    cards = {
        "v2_mobile": "mobile-card",
        "v2_tablet": "tablet-card",
        "v1_mobile": "legacy-card",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _DumpCardsHass(tmpdir, [entry], {ENTRY_ID: cards})
        written = asyncio.run(
            services_mod.async_export_cards_to_owned_ui(
                hass,
                entry_id=None,
                filename="humidity_intelligence_cards",
                layout="v2_tablet",
            )
        )

        ui_dir = pathlib.Path(tmpdir) / "humidity_intelligence" / "ui"
        assert written == [
            "/config/humidity_intelligence/ui/humidity_intelligence_cards_v2_tablet.yaml"
        ]
        assert (
            ui_dir / "humidity_intelligence_cards_v2_tablet.yaml"
        ).read_text() == "tablet-card"
        assert not (ui_dir / "humidity_intelligence_cards_v2_mobile.yaml").exists()
        assert not (ui_dir / "humidity_intelligence_cards_v1_mobile.yaml").exists()


def test_card_exports_are_entry_qualified_only_for_multi_entry_installations():
    services_mod = _load_services_module()
    first = SimpleNamespace(entry_id="entry_one")
    second = SimpleNamespace(entry_id="entry_two")
    cards = {"v2_mobile": "type: markdown\ncontent: Ready\n"}

    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _DumpCardsHass(
            tmpdir,
            [first, second],
            {
                first.entry_id: cards,
                second.entry_id: cards,
            },
        )
        written = asyncio.run(
            services_mod.async_export_cards_to_owned_ui(
                hass,
                entry_id=None,
                filename=None,
                layout="v2_mobile",
            )
        )
        assert written == [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_entry_one_v2_mobile.yaml",
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_entry_two_v2_mobile.yaml",
        ]

        custom = asyncio.run(
            services_mod.async_export_cards_to_owned_ui(
                hass,
                entry_id=first.entry_id,
                filename="humidity_intelligence_custom_cards",
                layout="v2_mobile",
            )
        )
        assert custom == [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_custom_cards_entry_one_v2_mobile.yaml"
        ]

        boundary_base = "x" * 128
        assert (
            services_mod.SERVICE_DUMP_CARDS_SCHEMA(
                {"filename": boundary_base}
            )["filename"]
            == boundary_base
        )
        boundary = asyncio.run(
            services_mod.async_export_cards_to_owned_ui(
                hass,
                entry_id=first.entry_id,
                filename=boundary_base,
                layout="v2_mobile",
            )
        )
        boundary_name = boundary[0].removeprefix(
            "/config/humidity_intelligence/ui/"
        )
        assert len(boundary_name) <= 255
        assert (
            pathlib.Path(tmpdir)
            / "humidity_intelligence"
            / "ui"
            / boundary_name
        ).is_file()


def test_service_schema_stub_rejects_undeclared_keys_by_default():
    services_mod = _load_services_module()

    release_defaults = services_mod.SERVICE_V205_RELEASE_CHECK_SCHEMA({})
    assert release_defaults["write_test_exports"] is False
    assert release_defaults["require_local_hi_snapshot"] is False

    try:
        services_mod.SERVICE_DUMP_CARDS_SCHEMA({"undeclared": True})
    except services_mod.vol.Invalid as err:
        assert "extra keys not allowed" in str(err)
    else:
        raise AssertionError("service schema stub accepted an undeclared key")

    allow_extra_schema = services_mod.vol.Schema(
        {services_mod.vol.Optional("layout"): str},
        extra=services_mod.vol.ALLOW_EXTRA,
    )
    assert allow_extra_schema(
        {"layout": "v2_mobile", "undeclared": True}
    ) == {
        "layout": "v2_mobile",
        "undeclared": True,
    }


def test_owned_ui_purge_names_are_exact_for_default_and_release_test_exports():
    services_mod = _load_services_module()
    cleanup_mod = sys.modules[f"{PKG}.helpers.cleanup"]
    entry = SimpleNamespace(entry_id="entry_one")

    single = cleanup_mod.list_owned_ui_filenames(
        [entry],
        multiple_installation=False,
        include_unqualified_defaults=True,
    )
    assert "humidity_intelligence_cards_v2_mobile.yaml" in single
    assert (
        "humidity_intelligence_v205_release_check_cards_v2_mobile.yaml"
        in single
    )
    assert (
        "humidity_intelligence_v205_release_check_cards_scoped_v2_tablet.yaml"
        in single
    )
    assert "humidity_intelligence_cards_entry_one_v2_mobile.yaml" in single
    assert (
        "humidity_intelligence_v205_release_check_cards_entry_one_v2_mobile.yaml"
        in single
    )
    assert "humidity_intelligence_custom_cards_v2_mobile.yaml" not in single

    multi = cleanup_mod.list_owned_ui_filenames(
        [entry],
        multiple_installation=True,
        include_unqualified_defaults=False,
    )
    assert "humidity_intelligence_cards_entry_one_v2_mobile.yaml" in multi
    assert (
        "humidity_intelligence_v205_release_check_cards_entry_one_v2_mobile.yaml"
        in multi
    )
    assert "humidity_intelligence_cards_v2_mobile.yaml" not in multi


def test_v205_release_check_report_verifies_export_contract_and_ui_visibility():
    services_mod = _load_services_module()
    entry_data = _base_entry_data()
    entry_data["show_output_entity_details"] = False
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.hi_runtime_mode": _FakeState("normal"),
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(44),
            "sensor.bed_h": _FakeState(46),
            "sensor.house_humidity_mean_7d": _FakeState(43),
            "sensor.kitchen_t": _FakeState(21),
            "sensor.hall_t": _FakeState(20),
            "sensor.bed_t": _FakeState(19),
            "sensor.l1_iaq": _FakeState(35),
            "sensor.co_val": _FakeState(4),
            "fan.zone1": _FakeState("off"),
            "fan.zone2": _FakeState("off"),
            "fan.aq1": _FakeState("off"),
            "humidifier.l1": _FakeState("off"),
            "light.alert": _FakeState("off"),
            "switch.alert_power": _FakeState("off"),
        },
    )
    cards = {
        "v2_mobile": "type: vertical-stack\ncards:\n  - type: markdown\n    content: Mobile ready\n",
        "v2_tablet": "type: vertical-stack\ncards:\n  - type: markdown\n    content: Tablet ready\n",
        "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
        "view_cards_button": "type: button\nname: View cards\n",
    }
    runtime_data = {
        "entity_map": {"runtime_mode": "sensor.hi_runtime_mode"},
        "cards": cards,
        "unresolved_placeholders_by_card": {},
        "humidifier_reconciliation": _reported_idle_humidifier_truth(),
    }

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        frontend_dependencies={
            "status": "not_inspectable",
            "reason": "Lovelace resource collection is not available in this Home Assistant runtime context.",
        },
        write_test_exports=True,
        unscoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v2_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v2_tablet.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v1_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_view_cards_button.yaml",
        ],
        scoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_scoped_v2_tablet.yaml",
        ],
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert report["status"] == "pass"
    assert checks["manifest_version"]["status"] == "pass"
    assert checks["output_details_visibility"]["status"] == "pass"
    assert checks["dump_cards_unscoped_export_all"]["status"] == "pass"
    assert checks["dump_cards_scoped_export_single_layout"]["status"] == "pass"
    assert checks["generated_cards_text_sanity"]["status"] == "pass"
    assert checks["frontend_dependencies_reported"]["status"] == "pass"
    assert checks["humidifier_reconciliation_truth"]["status"] == "pass"
    assert "does not prove physical moisture production" in checks[
        "humidifier_reconciliation_truth"
    ]["message"]

    beta_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.9-beta.1",
        frontend_dependencies={
            "status": "not_inspectable",
            "reason": "Lovelace resource collection is not available in this Home Assistant runtime context.",
        },
    )
    beta_checks = {check["id"]: check for check in beta_report["checks"]}
    assert beta_report["status"] == "pass"
    assert beta_checks["manifest_version"]["status"] == "pass"

    for candidate_version in (
        "2.0.10-beta.1",
        "2.0.10-rc.1",
        "2.0.10",
        "2.0.11-beta.1",
        "2.0.11-rc.1",
        "2.0.11",
        "2.0.12-beta.1",
        "2.0.12-beta.2",
        "2.0.12-beta.3",
        "2.0.12-beta.4",
        "2.0.12-rc.1",
        "2.0.12",
    ):
        future_report = services_mod._build_v205_release_check_entry_report(
            hass,
            entry,
            runtime_data,
            manifest_version=candidate_version,
            frontend_dependencies={"status": "not_inspectable"},
        )
        future_checks = {check["id"]: check for check in future_report["checks"]}
        assert future_report["status"] == "pass"
        assert future_checks["manifest_version"]["status"] == "pass"

    out_of_range_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.13-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    out_of_range_checks = {
        check["id"]: check for check in out_of_range_report["checks"]
    }
    assert out_of_range_report["status"] == "fail"
    assert out_of_range_checks["manifest_version"]["status"] == "fail"

    failed_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        frontend_dependencies={
            "status": "not_inspectable",
            "reason": "Lovelace resource collection is not available in this Home Assistant runtime context.",
        },
        write_test_exports=True,
        unscoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v2_tablet.yaml",
        ],
        scoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_scoped_v2_tablet.yaml",
        ],
    )
    failed_checks = {check["id"]: check for check in failed_report["checks"]}
    assert failed_report["status"] == "fail"
    assert failed_checks["dump_cards_unscoped_export_all"]["status"] == "fail"

    beta_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.8-beta.1",
    )
    beta_checks = {check["id"]: check for check in beta_report["checks"]}
    assert beta_checks["manifest_version"]["status"] == "pass"


def test_frontend_dependency_status_detects_lovelace_async_items_urls():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    resources = _FakeLovelaceResources(
        [
            _NoStringResource({"url": "/hacsfiles/apexcharts-card/apexcharts-card.js"}),
            _NoStringResource({"url": "/hacsfiles/button-card/button-card.js"}),
            _NoStringResource({"url": "/hacsfiles/lovelace-card-mod/card-mod.js"}),
            _NoStringResource({"url": "/hacsfiles/lovelace-card-mod/mod-card.js"}),
        ],
        loaded=False,
    )
    hass.data["lovelace"] = SimpleNamespace(resources=resources)

    status = asyncio.run(services_mod._async_frontend_dependency_status(hass))

    assert resources.load_calls == 1
    assert resources.loaded is True
    assert resources.items_calls == 1
    assert status == {
        "apexcharts-card": {
            "detected": True,
            "url": "/hacsfiles/apexcharts-card/apexcharts-card.js",
        },
        "button-card": {
            "detected": True,
            "url": "/hacsfiles/button-card/button-card.js",
        },
        "card-mod": {
            "detected": True,
            "url": "/hacsfiles/lovelace-card-mod/card-mod.js",
        },
        "mod-card": {
            "detected": True,
            "url": "/hacsfiles/lovelace-card-mod/mod-card.js",
        },
    }


def test_shared_frontend_dependency_helper_renders_form_status_from_lovelace_resources():
    frontend_mod = _load_frontend_dependencies_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    with tempfile.TemporaryDirectory() as tmpdir:
        hass.config = _DumpCardsConfig(tmpdir)
        resources = _FakeLovelaceResources(
            [
                _NoStringResource({"url": "/hacsfiles/button-card/button-card.js"}),
                _NoStringResource({"url": "/hacsfiles/lovelace-card-mod/card-mod.js"}),
            ],
            loaded=True,
        )
        hass.data["lovelace"] = SimpleNamespace(resources=resources)

        status = asyncio.run(frontend_mod.async_frontend_dependency_status(hass))
        lines = asyncio.run(frontend_mod.async_render_dependency_status(hass))

    assert status["button-card"] == {
        "detected": True,
        "url": "/hacsfiles/button-card/button-card.js",
    }
    assert status["card-mod"] == {
        "detected": True,
        "url": "/hacsfiles/lovelace-card-mod/card-mod.js",
    }
    assert status["mod-card"] == {
        "detected": True,
        "url": "/hacsfiles/lovelace-card-mod/card-mod.js",
        "provided_by": "card-mod",
    }
    assert status["apexcharts-card"] == {"detected": False}
    assert "- button-card: Installed | repo: https://github.com/custom-cards/button-card" in lines
    assert "- card-mod: Installed | repo: https://github.com/thomasloven/lovelace-card-mod" in lines
    assert "- mod-card: Installed | repo: https://github.com/thomasloven/lovelace-card-mod" in lines
    assert "- apexcharts-card: Not detected | repo: https://github.com/RomRider/apexcharts-card" in lines


def test_frontend_dependency_status_distinguishes_card_mod_and_mod_card_resources():
    frontend_mod = _load_frontend_dependencies_module()

    status = frontend_mod.frontend_dependency_status_from_urls(
        ["/hacsfiles/lovelace-card-mod/mod-card.js"]
    )

    assert status["mod-card"] == {
        "detected": True,
        "url": "/hacsfiles/lovelace-card-mod/mod-card.js",
    }
    assert status["card-mod"] == {"detected": False}


def test_frontend_dependency_status_accepts_mod_card_from_card_mod_resource():
    frontend_mod = _load_frontend_dependencies_module()

    status = frontend_mod.frontend_dependency_status_from_urls(
        ["/hacsfiles/lovelace-card-mod/card-mod.js"]
    )

    assert status["card-mod"] == {
        "detected": True,
        "url": "/hacsfiles/lovelace-card-mod/card-mod.js",
    }
    assert status["mod-card"] == {
        "detected": True,
        "url": "/hacsfiles/lovelace-card-mod/card-mod.js",
        "provided_by": "card-mod",
    }


def test_config_flow_dependency_pages_delegate_to_shared_frontend_helper():
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    dependency_renderer = config_source.split("async def _render_dependency_status", 1)[1].split(
        "def _entry_section", 1
    )[0]

    assert "from .helpers.frontend_dependencies import async_render_dependency_status" in config_source
    assert "async_render_dependency_status(hass)" in dependency_renderer
    assert "humidity_drift_dependency_status" not in dependency_renderer
    assert "_render_drift_statistics_status" not in config_source
    assert "lovelace_resources" not in dependency_renderer


def test_config_flow_dependency_pages_keep_drift_statistics_status_out_of_frontend_text():
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    strings = json.loads((INTEGRATION_ROOT / "strings.json").read_text())
    translations = json.loads((INTEGRATION_ROOT / "translations" / "en.json").read_text())

    assert "drift_statistics" not in config_source
    assert "_render_drift_statistics_status" not in config_source
    for payload in (strings, translations):
        setup_description = payload["config"]["step"]["dependencies"]["description"]
        options_description = payload["options"]["step"]["options_dependencies"]["description"]
        assert "House Humidity Mean 7d" not in setup_description
        assert "House Humidity Mean 7d" not in options_description
        assert "drift statistics helper status" not in setup_description
        assert "house_humidity_mean_7d_missing" in payload["issues"]


def test_frontend_dependency_status_missing_lovelace_is_not_inspectable():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})

    status = asyncio.run(services_mod._async_frontend_dependency_status(hass))

    assert status["status"] == "not_inspectable"
    assert "Lovelace" in status["reason"]
    for dependency in ("apexcharts-card", "button-card", "card-mod", "mod-card"):
        assert dependency not in status

    resources = _FakeLovelaceResources([], loaded=False, load_error=RuntimeError("storage offline"))
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    failed_load_status = asyncio.run(services_mod._async_frontend_dependency_status(hass))

    assert failed_load_status["status"] == "not_inspectable"
    assert "could not be loaded" in failed_load_status["reason"]
    for dependency in ("apexcharts-card", "button-card", "card-mod", "mod-card"):
        assert dependency not in failed_load_status


def test_diagnostics_summary_can_surface_shared_frontend_dependency_status_without_live_bloat():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    frontend_status = {
        "button-card": {
            "detected": True,
            "url": "/hacsfiles/button-card/button-card.js",
        },
        "card-mod": {"detected": False},
    }

    runtime_data = {
        "runtime_mode": "manual_override",
        "runtime_mode_display": "MANUAL OVERRIDE",
        "runtime_reason": "Manual override is enabled.",
    }
    full_summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        {},
        {},
        runtime_data,
        frontend_dependencies=frontend_status,
    )
    live_summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        {},
        {},
        runtime_data,
    )

    assert full_summary["frontend_dependency_resources"] == frontend_status
    assert "frontend_dependency_resources" not in live_summary
    assert full_summary["runtime_control"] == {
        "mode": "manual_override",
        "display": "MANUAL OVERRIDE",
        "reason_available": True,
    }
    support_summary = services_mod._support_safe_diagnostics_summary(full_summary)
    assert support_summary["runtime_control"] == full_summary["runtime_control"]
    sensor_mod = _load_sensor_platform_module()
    compact = sensor_mod._compact_diagnostics_summary(full_summary)
    assert compact["runtime_control"] == full_summary["runtime_control"]


def test_support_diagnostics_summary_uses_canonical_level_label_source():
    services_mod = _load_services_module()
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=_base_entry_data(),
        options={
            "level_labels": {
                "level1": "  Ground <Floor>  ",
                "level2": "",
            }
        },
    )
    hass = _FakeHass(entry, {})

    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        entry.options,
        {},
        {},
    )

    assert summary["level_labels"] == {
        "level1": {"label": "Ground Floor", "source": "config"},
        "level2": {"label": "Level 2", "source": "fallback"},
    }


def test_support_diagnostics_summary_sanitizes_duplicate_zone_mapping_evidence():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=copy.deepcopy(_base_entry_data()), options={})
    entry.data["zones"]["zone2"] = {
        "enabled": True,
        "level": "level1",
        "rooms": ["Kitchen"],
        "outputs": ["fan.zone2_private"],
        "triggers": ["humidity_high"],
    }
    hass = _FakeHass(entry, {})

    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        entry.options,
        {},
        {},
    )
    support_summary = services_mod._support_safe_diagnostics_summary(summary)
    rendered = json.dumps(support_summary, sort_keys=True)

    assert "sensor.kitchen_h" not in rendered
    assert "Kitchen" not in rendered
    assert support_summary["zone_mapping_duplicates"] == {
        "count": 1,
        "pairs": {"zone1:zone2": {"entity_count": 3}},
    }
    assert (
        "1 duplicate zone mapping pair includes 3 overlapping telemetry sources."
        in support_summary["warnings"]
    )


def test_flash_lights_power_entity_rejects_non_switch_light_domains():
    services_mod = _load_services_module()

    assert services_mod._validate_visual_power_entity("switch.alert_power") == "switch.alert_power"
    assert services_mod._validate_visual_power_entity("light.alert_power") == "light.alert_power"

    try:
        services_mod._validate_visual_power_entity("fan.extractor")
    except Exception as err:
        assert "switch or light" in str(err)
    else:
        raise AssertionError("fan power_entity should be rejected")


def test_external_flash_and_local_snapshot_services_require_admin_before_work():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {"light.alert": _FakeState("off")})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth(
        {
            "admin": SimpleNamespace(is_admin=True),
            "viewer": SimpleNamespace(is_admin=False),
        }
    )
    local_version_calls = {"create": 0, "list": 0}
    original_create_local_backup = services_mod.async_create_local_backup
    original_list_saved_versions = services_mod.async_list_saved_versions

    async def unexpected_local_backup(*_args, **_kwargs):
        local_version_calls["create"] += 1
        raise AssertionError("local backup work must not begin before authorization")

    async def tracked_list_saved_versions(*_args, **_kwargs):
        local_version_calls["list"] += 1
        return {
            "success": True,
            "valid_snapshots": [],
            "invalid_snapshots": [],
            "latest_snapshot": None,
            "total_size": 0,
        }

    services_mod.async_create_local_backup = unexpected_local_backup
    services_mod.async_list_saved_versions = tracked_list_saved_versions
    try:
        asyncio.run(services_mod.async_register_services(hass))
        handlers = {
            services_mod.SERVICE_FLASH_LIGHTS: hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_FLASH_LIGHTS)
            ],
            services_mod.SERVICE_CREATE_LOCAL_BACKUP: hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_CREATE_LOCAL_BACKUP)
            ],
            services_mod.SERVICE_LIST_SAVED_VERSIONS: hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_LIST_SAVED_VERSIONS)
            ],
        }

        for service, handler in handlers.items():
            for user_id in ("viewer", None, "missing"):
                calls_before = list(hass.services.calls)
                try:
                    asyncio.run(
                        handler(
                            SimpleNamespace(
                                data={"lights": ["light.alert"]}
                                if service == services_mod.SERVICE_FLASH_LIGHTS
                                else {},
                                context=SimpleNamespace(user_id=user_id),
                            )
                        )
                    )
                except services_mod.HomeAssistantError as err:
                    assert str(err) == f"{service} requires an admin user context"
                else:
                    raise AssertionError(
                        f"{service} should reject user context {user_id!r}"
                    )
                assert hass.services.calls == calls_before
                assert local_version_calls == {"create": 0, "list": 0}

        listed = asyncio.run(
            handlers[services_mod.SERVICE_LIST_SAVED_VERSIONS](
                SimpleNamespace(
                    data={},
                    context=SimpleNamespace(user_id="admin"),
                )
            )
        )
        assert listed["success"] is True
        assert local_version_calls == {"create": 0, "list": 1}
        assert any(
            call[0:2] == ("persistent_notification", "create")
            and call[2].get("title") == "Humidity Intelligence Local Snapshots"
            for call in hass.services.calls
        )
    finally:
        services_mod.async_create_local_backup = original_create_local_backup
        services_mod.async_list_saved_versions = original_list_saved_versions


def test_report_service_schemas_reject_non_owned_root_filenames_before_write():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    executor_calls = 0

    async def counting_executor_job(func, *args):
        nonlocal executor_calls
        executor_calls += 1
        return func(*args)

    hass.async_add_executor_job = counting_executor_job
    asyncio.run(services_mod.async_register_services(hass))

    services = (
        (
            services_mod.SERVICE_DUMP_DIAGNOSTICS,
            "humidity_intelligence_diagnostics.json",
        ),
        (
            services_mod.SERVICE_V205_RELEASE_CHECK,
            "humidity_intelligence_v205_release_check.json",
        ),
    )
    rejected = (
        "configuration.yaml",
        "secrets.yaml",
        "automations.yaml",
        "scripts.yaml",
        "scenes.yaml",
        ".HA_VERSION",
        "my_report.json",
        "Humidity_intelligence_report.json",
        "humidity_intelligence_report.JSON",
        "humidity_intelligence_report.txt",
        " humidity_intelligence_report.json ",
        "humidity_intelligence_../secrets.json",
        "humidity_intelligence_reports/report.json",
        "humidity_intelligence_reports\\report.json",
    )

    for service, default_filename in services:
        schema = hass.services.schemas[(services_mod.DOMAIN, service)]
        assert schema is not None
        assert schema({})["filename"] == default_filename
        assert (
            schema({"filename": "humidity_intelligence_release_2026.json"})["filename"]
            == "humidity_intelligence_release_2026.json"
        )

        for filename in rejected:
            calls_before = executor_calls
            dispatches_before = len(hass.services.handler_calls)
            try:
                asyncio.run(
                    hass.services.async_call(
                        services_mod.DOMAIN,
                        service,
                        {"filename": filename},
                        blocking=True,
                    )
                )
            except Exception as err:
                assert "humidity_intelligence_*.json" in str(err)
            else:
                raise AssertionError(f"{service} should reject non-owned report filename {filename!r}")
            assert executor_calls == calls_before
            assert len(hass.services.handler_calls) == dispatches_before

    card_schema = hass.services.schemas[(services_mod.DOMAIN, services_mod.SERVICE_DUMP_CARDS)]
    assert card_schema({"filename": "custom_cards"})["filename"] == "custom_cards"
    view_schema = hass.services.schemas[(services_mod.DOMAIN, services_mod.SERVICE_VIEW_CARDS)]
    assert view_schema({"filename": "custom_cards"})["filename"] == "custom_cards"


def test_report_writers_require_admin_before_report_side_effects():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth(
        {
            "admin": SimpleNamespace(is_admin=True),
            "viewer": SimpleNamespace(is_admin=False),
        }
    )
    counters = {
        "config_entries": 0,
        "destination": 0,
        "executor": 0,
    }
    original_config_entries = hass.config_entries

    class CountingConfigEntries:
        def async_get_entry(self, entry_id):
            counters["config_entries"] += 1
            return original_config_entries.async_get_entry(entry_id)

        def async_entries(self, domain):
            counters["config_entries"] += 1
            return original_config_entries.async_entries(domain)

    class CountingConfig:
        def path(self, *parts):
            counters["destination"] += 1
            return str(pathlib.Path(tempfile.gettempdir()).joinpath(*parts))

    async def counting_executor_job(func, *args):
        counters["executor"] += 1
        return func(*args)

    hass.config_entries = CountingConfigEntries()
    hass.config = CountingConfig()
    hass.async_add_executor_job = counting_executor_job
    asyncio.run(services_mod.async_register_services(hass))

    for service in (
        services_mod.SERVICE_DUMP_DIAGNOSTICS,
        services_mod.SERVICE_SELF_CHECK,
        services_mod.SERVICE_V205_RELEASE_CHECK,
        services_mod.SERVICE_DUMP_CARDS,
        services_mod.SERVICE_VIEW_CARDS,
    ):
        handler = hass.services.handlers[(services_mod.DOMAIN, service)]
        for user_id in ("viewer", None, "missing"):
            before = dict(counters)
            calls_before = list(hass.services.calls)
            try:
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={},
                            context=SimpleNamespace(user_id=user_id),
                        )
                    )
                )
            except Exception as err:
                assert str(err) == f"{service} requires an admin user context"
            else:
                raise AssertionError(f"{service} should reject user context {user_id!r}")
            assert counters == before
            assert hass.services.calls == calls_before


def test_report_writer_admin_lookup_precedes_async_report_work():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    events = []

    class RecordingAuth:
        async def async_get_user(self, user_id):
            events.append(("auth", user_id))
            return SimpleNamespace(is_admin=True)

    async def frontend_status(_hass):
        events.append(("frontend", None))
        return {"status": "not_inspectable"}

    async def local_version_status(_hass):
        events.append(("local_versions", None))
        return {"status": "not_configured"}

    original_frontend_status = services_mod.async_frontend_dependency_status
    original_local_version_status = services_mod.async_local_version_status
    original_executor = hass.async_add_executor_job

    async def tracking_executor(func, *args):
        events.append(("executor", func.__name__))
        return await original_executor(func, *args)

    hass.auth = RecordingAuth()
    hass.async_add_executor_job = tracking_executor

    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        try:
            services_mod.async_frontend_dependency_status = frontend_status
            services_mod.async_local_version_status = local_version_status
            asyncio.run(services_mod.async_register_services(hass))

            for service in (
                services_mod.SERVICE_DUMP_DIAGNOSTICS,
                services_mod.SERVICE_SELF_CHECK,
                services_mod.SERVICE_V205_RELEASE_CHECK,
            ):
                events.clear()
                handler = hass.services.handlers[(services_mod.DOMAIN, service)]
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={"entry_id": "missing"},
                            context=SimpleNamespace(user_id="admin"),
                        )
                    )
                )
                assert events[0] == ("auth", "admin")
                assert any(event[0] == "executor" for event in events)
        finally:
            services_mod.async_frontend_dependency_status = original_frontend_status
            services_mod.async_local_version_status = original_local_version_status


def test_report_writer_services_use_owned_directory_and_truthful_notification():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})

    async def frontend_status(_hass):
        return {"status": "not_inspectable"}

    async def local_version_status(_hass):
        return {"status": "not_configured"}

    original_frontend_status = services_mod.async_frontend_dependency_status
    original_local_version_status = services_mod.async_local_version_status

    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        _set_fake_config_path(hass, root)
        try:
            services_mod.async_frontend_dependency_status = frontend_status
            services_mod.async_local_version_status = local_version_status
            asyncio.run(services_mod.async_register_services(hass))

            diagnostics_name = "humidity_intelligence_diagnostics_test.json"
            release_name = "humidity_intelligence_release_test.json"
            diagnostics_handler = hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_DUMP_DIAGNOSTICS)
            ]
            release_handler = hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_V205_RELEASE_CHECK)
            ]
            asyncio.run(
                diagnostics_handler(
                    SimpleNamespace(
                        data={
                            "entry_id": "missing",
                            "filename": diagnostics_name,
                        },
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
            asyncio.run(
                release_handler(
                    SimpleNamespace(
                        data={
                            "entry_id": "missing",
                            "filename": release_name,
                        },
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
        finally:
            services_mod.async_frontend_dependency_status = original_frontend_status
            services_mod.async_local_version_status = original_local_version_status

        for filename in (diagnostics_name, release_name):
            assert not (root / filename).exists()
            report = root / "humidity_intelligence" / "exports" / filename
            assert report.is_file()
            json.loads(report.read_text(encoding="utf-8"))

        notifications = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
        ]
        assert len(notifications) == 1
        message = notifications[0][2]["message"]
        assert (
            "Home Assistant config/humidity_intelligence/exports/"
            + release_name
        ) in message
        assert f"/config/{release_name}" not in message


def test_self_check_uses_fixed_owned_report_and_retains_payload_semantics():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    hass.data[services_mod.DOMAIN][ENTRY_ID].update(
        {
            "entity_map": {"runtime_mode": "sensor.missing_runtime_mode"},
            "cards": {},
            "unresolved_placeholders": ["sensor.unresolved"],
            "unresolved_placeholders_by_card": {
                "v2_mobile": ["sensor.unresolved"]
            },
        }
    )

    async def frontend_status(_hass):
        return {"status": "not_inspectable"}

    async def local_version_status(_hass):
        return {"status": "not_configured"}

    original_frontend_status = services_mod.async_frontend_dependency_status
    original_local_version_status = services_mod.async_local_version_status
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        legacy = root / "humidity_intelligence_self_check.json"
        legacy.write_text('{"legacy": true}\n', encoding="utf-8")
        _set_fake_config_path(hass, root)
        try:
            services_mod.async_frontend_dependency_status = frontend_status
            services_mod.async_local_version_status = local_version_status
            asyncio.run(services_mod.async_register_services(hass))
            handler = hass.services.handlers[
                (services_mod.DOMAIN, services_mod.SERVICE_SELF_CHECK)
            ]
            asyncio.run(
                handler(
                    SimpleNamespace(
                        data={"entry_id": ENTRY_ID},
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
        finally:
            services_mod.async_frontend_dependency_status = original_frontend_status
            services_mod.async_local_version_status = original_local_version_status

        destination = (
            root
            / "humidity_intelligence"
            / "exports"
            / "humidity_intelligence_self_check.json"
        )
        payload = json.loads(destination.read_text(encoding="utf-8"))
        assert payload[ENTRY_ID]["missing_entities"] == [
            "sensor.missing_runtime_mode"
        ]
        assert payload[ENTRY_ID]["telemetry_count"] == len(
            entry.data["telemetry"]
        )
        assert payload[ENTRY_ID]["unresolved_placeholders"] == [
            "sensor.unresolved"
        ]
        assert legacy.read_text(encoding="utf-8") == '{"legacy": true}\n'
        notification = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
        ][-1]
        assert (
            "Home Assistant config/humidity_intelligence/exports/"
            "humidity_intelligence_self_check.json"
        ) in notification[2]["message"]
        assert "local/private" in notification[2]["message"]


def test_view_cards_notification_reports_exact_owned_ui_path():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    hass.data[services_mod.DOMAIN][ENTRY_ID]["cards"] = {
        "v2_tablet": "type: markdown\ncontent: Tablet\n"
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        _set_fake_config_path(hass, root)
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_VIEW_CARDS)
        ]
        asyncio.run(
            handler(
                SimpleNamespace(
                    data={
                        "entry_id": ENTRY_ID,
                        "layout": "v2_tablet",
                    },
                    context=SimpleNamespace(user_id="admin"),
                )
            )
        )

        expected = (
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_tablet.yaml"
        )
        assert root.joinpath(expected.removeprefix("/config/")).is_file()
        notification = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
        ][-1]
        assert expected in notification[2]["message"]


def test_report_writers_surface_owned_export_failure_as_service_error():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})

    async def frontend_status(_hass):
        return {"status": "not_inspectable"}

    async def local_version_status(_hass):
        return {"status": "not_configured"}

    def failed_write(*_args):
        raise services_mod.ReportExportError("fixture destination rejected")

    original_frontend_status = services_mod.async_frontend_dependency_status
    original_local_version_status = services_mod.async_local_version_status
    original_write = services_mod.write_owned_report

    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        try:
            services_mod.async_frontend_dependency_status = frontend_status
            services_mod.async_local_version_status = local_version_status
            services_mod.write_owned_report = failed_write
            asyncio.run(services_mod.async_register_services(hass))
            for service, expected in (
                (
                    services_mod.SERVICE_DUMP_DIAGNOSTICS,
                    "Diagnostics report operation incomplete: "
                    "fixture destination rejected",
                ),
                (
                    services_mod.SERVICE_V205_RELEASE_CHECK,
                    "Release-check report operation incomplete: "
                    "fixture destination rejected",
                ),
            ):
                handler = hass.services.handlers[(services_mod.DOMAIN, service)]
                try:
                    asyncio.run(
                        handler(
                            SimpleNamespace(
                                data={"entry_id": "missing"},
                                context=SimpleNamespace(user_id="admin"),
                            )
                        )
                    )
                except Exception as err:
                    assert str(err) == expected
                else:
                    raise AssertionError(
                        f"{service} export failure should be reported"
                    )
        finally:
            services_mod.async_frontend_dependency_status = original_frontend_status
            services_mod.async_local_version_status = original_local_version_status
            services_mod.write_owned_report = original_write

    assert not [
        call
        for call in hass.services.calls
        if call[0:2] == ("persistent_notification", "create")
    ]


def test_dump_diagnostics_owned_export_redacts_sensitive_payload_before_write():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(
                "72",
                {
                    "friendly_name": "https://user:pass@example.invalid/sensor?token=REDACTION_FIXTURE",
                    "access_token": "REDACTION_FIXTURE_STATE_TOKEN",
                    "host": "REDACTION_FIXTURE_STATE_HOST",
                },
            )
        },
    )
    hass.config = _DumpCardsConfig(tempfile.mkdtemp())
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    hass.data["lovelace"] = SimpleNamespace(
        resources=_FakeLovelaceResources(
            [
                _NoStringResource(
                    {
                        "url": (
                            "https://user:pass@example.invalid/card-mod.js"
                            "?token=REDACTION_FIXTURE_RESOURCE_TOKEN"
                        )
                    }
                ),
                _NoStringResource({"url": "/hacsfiles/button-card/button-card.js?v=abc123"}),
            ],
            loaded=True,
        )
    )
    hass.data["humidity_intelligence"][ENTRY_ID].update(
        {
            "config": {
                **entry.data,
                "api_key": "REDACTION_FIXTURE_API_KEY",
                "host": "REDACTION_FIXTURE_HOST",
                "ip_address": "REDACTION_FIXTURE_IP",
                "device_id": "REDACTION_FIXTURE_DEVICE_ID",
                "unique_id": "REDACTION_FIXTURE_UNIQUE_ID",
                "external_url": "https://alice:pass@example.invalid/path?access_token=REDACTION_FIXTURE",
            },
            "options": {
                "access_token": "REDACTION_FIXTURE_ACCESS_TOKEN",
                "password": "REDACTION_FIXTURE_PASSWORD",
            },
            "entity_map": {
                "humidity": "sensor.kitchen_h",
                "diagnostic_entity": "sensor.private_diagnostic",
            },
            "cards": {"v2_mobile": "type: entities\n"},
        }
    )

    async def local_version_status(_hass):
        return {"status": "not_configured"}

    captured = {}

    def capture_write(config_root, filename, payload):
        captured["config_root"] = config_root
        captured["filename"] = filename
        captured["payload"] = payload

    original_local_version_status = services_mod.async_local_version_status
    original_write_owned_report = services_mod.write_owned_report
    try:
        services_mod.async_local_version_status = local_version_status
        services_mod.write_owned_report = capture_write
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[(services_mod.DOMAIN, services_mod.SERVICE_DUMP_DIAGNOSTICS)]
        asyncio.run(
            handler(
                SimpleNamespace(
                    data={"entry_id": ENTRY_ID},
                    context=SimpleNamespace(user_id="admin"),
                )
            )
        )
    finally:
        services_mod.async_local_version_status = original_local_version_status
        services_mod.write_owned_report = original_write_owned_report

    rendered = json.dumps(captured["payload"], sort_keys=True)
    for secret in (
        "REDACTION_FIXTURE_API_KEY",
        "REDACTION_FIXTURE_ACCESS_TOKEN",
        "REDACTION_FIXTURE_PASSWORD",
        "REDACTION_FIXTURE_HOST",
        "REDACTION_FIXTURE_IP",
        "REDACTION_FIXTURE_DEVICE_ID",
        "REDACTION_FIXTURE_UNIQUE_ID",
        "REDACTION_FIXTURE_RESOURCE_TOKEN",
        "REDACTION_FIXTURE_STATE_TOKEN",
        "REDACTION_FIXTURE_STATE_HOST",
        "alice:pass",
        "user:pass",
    ):
        assert secret not in rendered

    assert "sensor.kitchen_h" not in rendered
    assert "sensor.private_diagnostic" not in rendered
    assert "/hacsfiles/button-card/button-card.js" not in rendered
    assert "configuration_summary" in captured["payload"][ENTRY_ID]
    assert "entity_map_summary" in captured["payload"][ENTRY_ID]
    assert captured["payload"][ENTRY_ID]["entity_map_summary"] == {
        "mapped_entity_count": 2,
    }
    assert captured["filename"] == "humidity_intelligence_diagnostics.json"


def test_generated_v2_cards_escape_dynamic_html_text():
    for path in (
        INTEGRATION_ROOT / "ui" / "cards" / "v2_mobile.yaml",
        INTEGRATION_ROOT / "ui" / "cards" / "v2_tablet.yaml",
        ROOT / "ui-gallery" / "default-v2-mobile-aq" / "card.yaml",
        ROOT / "ui-gallery" / "default-v2-tablet-zone-1-cooking" / "card.yaml",
    ):
        source = path.read_text(encoding="utf-8")
        assert "const escapeHtml = " in source, path
        assert "escapeHtml(displayReason.headline)" in source, path
        assert "displayReason.lines.map((line) => escapeHtml(line.text))" in source, path
        assert "wrapReason(escapeHtml(legacyReason()))" in source, path
        assert "${escapeHtml(k)}" in source, path
        assert "${escapeHtml(v === null ? '—' : `${v}${unit || ''}`)}" in source, path


def test_diagnostics_summary_surfaces_temperature_comfort_warm_boundary():
    services_mod = _load_services_module()
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data=_base_entry_data(),
        options={
            "temperature_comfort_mode": "custom",
            "temperature_comfort_custom_low": 18.5,
            "temperature_comfort_custom_high": 22.0,
        },
    )
    hass = _FakeHass(entry, {})

    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        entry.options,
        {},
        {},
    )

    comfort = summary["temperature_comfort"]
    assert comfort["mode"] == "custom"
    assert comfort["active_profile"] == "custom"
    assert comfort["target_low"] == 18.5
    assert comfort["target_high"] == 22.0
    assert comfort["warm_high"] == 23.0
    assert comfort["watch_high"] == 23.0


def test_diagnostics_summary_surfaces_house_drift_statistics_dependency():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})

    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        {},
        {},
        {},
    )

    drift = summary["humidity_drift_7d"]
    assert drift["required_for"] == "HI House Humidity Drift 7d"
    assert drift["dependency_entity"] == "sensor.house_humidity_mean_7d"
    assert drift["dependency_status"] == "missing"
    assert drift["available"] is False
    assert drift["repair_kind"] == "missing_helper"
    assert drift["repair_required"] is True
    assert any("HI House Humidity Drift 7d" in warning for warning in summary["warnings"])


def test_diagnostics_summary_distinguishes_missing_drift_helper_from_existing_not_ready_helper():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    missing_hass = _FakeHass(entry, {})
    not_ready_hass = _FakeHass(
        entry,
        {"sensor.house_humidity_mean_7d": _FakeState("unknown")},
    )

    missing_summary = services_mod._build_diagnostics_summary(
        missing_hass,
        entry.data,
        {},
        {},
        {},
    )
    not_ready_summary = services_mod._build_diagnostics_summary(
        not_ready_hass,
        entry.data,
        {},
        {},
        {},
    )

    assert missing_summary["humidity_drift_7d"]["repair_kind"] == "missing_helper"
    assert missing_summary["humidity_drift_7d"]["repair_required"] is True
    assert not_ready_summary["humidity_drift_7d"]["repair_kind"] == "helper_not_ready_or_unavailable"
    assert not_ready_summary["humidity_drift_7d"]["repair_required"] is False


def test_diagnostics_summary_reports_low_statistics_coverage_as_not_ready():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 0.03,
                    "source_value_valid": True,
                },
            ),
        },
    )

    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        {},
        {},
        {},
    )

    drift = summary["humidity_drift_7d"]
    assert drift["dependency_status"] == "history_not_ready"
    assert drift["available"] is False
    assert drift["repair_required"] is False
    assert drift["repair_kind"] == "history_not_ready"
    assert drift["age_coverage_ratio"] == 0.03
    assert drift["required_age_coverage_ratio"] == 0.85
    assert any("history_not_ready" in warning for warning in summary["warnings"])


def test_v205_release_check_warns_on_drift_dependency_without_hidden_pass():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
                "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert checks["house_humidity_drift_7d_dependency"]["status"] == "warn"
    assert checks["house_humidity_drift_7d_dependency"]["details"]["repair_kind"] == "missing_helper"


def test_v205_release_check_warns_on_low_statistics_coverage():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(
                50,
                {
                    "age_coverage_ratio": 0.03,
                    "source_value_valid": True,
                },
            ),
        },
    )

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
                "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert checks["house_humidity_drift_7d_dependency"]["status"] == "warn"
    details = checks["house_humidity_drift_7d_dependency"]["details"]
    assert details["dependency_status"] == "history_not_ready"
    assert details["repair_required"] is False
    assert details["age_coverage_ratio"] == 0.03
    assert details["required_age_coverage_ratio"] == 0.85


def test_frontend_dependency_status_is_non_blocking_for_release_contract_checks():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.hi_runtime_mode": _FakeState("normal"),
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(44),
            "sensor.bed_h": _FakeState(46),
            "sensor.house_humidity_mean_7d": _FakeState(43),
            "sensor.kitchen_t": _FakeState(21),
            "sensor.hall_t": _FakeState(20),
            "sensor.bed_t": _FakeState(19),
            "sensor.l1_iaq": _FakeState(35),
            "sensor.co_val": _FakeState(4),
            "fan.zone1": _FakeState("off"),
            "fan.zone2": _FakeState("off"),
            "fan.aq1": _FakeState("off"),
            "humidifier.l1": _FakeState("off"),
            "light.alert": _FakeState("off"),
            "switch.alert_power": _FakeState("off"),
        },
    )
    runtime_data = {
        "entity_map": {"runtime_mode": "sensor.hi_runtime_mode"},
        "cards": {
            "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
            "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
            "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
            "view_cards_button": "type: button\nname: View cards\n",
        },
        "unresolved_placeholders_by_card": {},
        "humidifier_reconciliation": _reported_idle_humidifier_truth(),
    }

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        frontend_dependencies={
            "status": "not_inspectable",
            "reason": "Lovelace resource collection is not available in this Home Assistant runtime context.",
        },
        write_test_exports=True,
        unscoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v2_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v2_tablet.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_v1_mobile.yaml",
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_view_cards_button.yaml",
        ],
        scoped_written=[
            "/config/humidity_intelligence/ui/humidity_intelligence_v205_release_check_cards_scoped_v2_tablet.yaml",
        ],
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert report["status"] == "pass"
    assert checks["frontend_dependencies_reported"]["status"] == "pass"
    assert checks["frontend_dependencies_reported"]["details"]["status"] == "not_inspectable"
    assert checks["local_hi_snapshot"]["status"] == "info"
    assert checks["unresolved_placeholders"]["status"] == "pass"
    assert checks["configured_entity_availability"]["status"] == "pass"
    assert checks["house_humidity_drift_7d_dependency"]["status"] == "pass"
    assert checks["generated_cards_text_sanity"]["status"] == "pass"


def test_v205_release_check_fails_stale_generated_card_entity_references():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(43),
            "sensor.humidity_intelligence_hi_level1_iaq_average": _FakeState(87),
        },
    )

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": (
                    "type: entities\n"
                    "entities:\n"
                    "  - entity: sensor.humidity_intelligence_hi_level1_iaq_average\n"
                    "    name: Downstairs IAQ\n"
                    "  - entity: sensor.air_control_downstairs_pm25_average\n"
                    "    name: Downstairs PM2.5\n"
                ),
                "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert report["status"] == "fail"
    assert checks["generated_card_entity_availability"]["status"] == "fail"
    assert checks["generated_card_entity_availability"]["details"]["missing_entities"] == [
        {"layout": "v2_mobile", "entity_id": "sensor.air_control_downstairs_pm25_average"}
    ]


def test_v205_release_check_warns_for_existing_unavailable_card_reference():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(44),
            "sensor.bed_h": _FakeState(46),
            "sensor.house_humidity_mean_7d": _FakeState(43),
            "sensor.kitchen_t": _FakeState(21),
            "sensor.hall_t": _FakeState(20),
            "sensor.bed_t": _FakeState(19),
            "sensor.l1_iaq": _FakeState(35),
            "sensor.co_val": _FakeState(4),
            "fan.zone1": _FakeState("off"),
            "fan.zone2": _FakeState("off"),
            "fan.aq1": _FakeState("off"),
            "humidifier.l1": _FakeState("off"),
            "light.alert": _FakeState("unavailable"),
            "switch.alert_power": _FakeState("off"),
        },
    )

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": "type: entity\nentity: light.alert\n",
                "v2_tablet": "type: entity\nentity: light.alert\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.9-rc.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert report["status"] == "warn"
    assert checks["generated_card_entity_availability"]["status"] == "warn"
    assert checks["generated_card_entity_availability"]["details"]["missing_entities"] == []
    assert checks["generated_card_entity_availability"]["details"][
        "unknown_or_unavailable_entities"
    ] == [
        {"layout": "v2_mobile", "entity_id": "light.alert", "status": "unavailable"},
        {"layout": "v2_tablet", "entity_id": "light.alert", "status": "unavailable"},
    ]
    assert checks["configured_entity_availability"]["status"] == "warn"


def test_generated_card_entity_extraction_includes_embedded_js_references():
    services_mod = _load_services_module()

    entity_ids = services_mod._extract_generated_card_entity_ids(
        "\n".join(
            [
                "type: custom:button-card",
                "entity: sensor.hi_air_control_mode",
                "tap_action:",
                "  service_data:",
                "    entity_id: input_boolean.air_control_enabled",
                "custom_fields:",
                "  reason: >",
                "    [[[",
                "      const pause = states['timer.air_control_pause']?.state;",
                "      const output = fanTxt('fan.kitchen_air');",
                "      const service = 'switch.toggle';",
                "      const prefix = id.startsWith('sensor.hi_');",
                "      const rooms = zone && zone.enabled !== false && Array.isArray(zone?.rooms);",
                "      const docs = 'https://github.com/senyo888/Humidity-Intelligence';",
                "    ]]]",
            ]
        )
    )

    assert entity_ids == [
        "sensor.hi_air_control_mode",
        "input_boolean.air_control_enabled",
        "timer.air_control_pause",
        "fan.kitchen_air",
    ]


def test_v205_release_check_fails_js_only_stale_generated_card_references():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(43),
        },
    )

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": (
                    "type: markdown\n"
                    "content: |\n"
                    "  [[[ return states['sensor.hi_js_only_missing']?.state || 'unknown'; ]]]\n"
                ),
                "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert checks["generated_card_entity_availability"]["status"] == "fail"
    assert checks["generated_card_entity_availability"]["details"]["missing_entities"] == [
        {"layout": "v2_mobile", "entity_id": "sensor.hi_js_only_missing"}
    ]


def test_v205_release_check_uses_card_scoped_unresolved_placeholders_when_available():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(43),
        },
    )

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        {
            "entity_map": {},
            "cards": {
                "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
                "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
                "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
                "view_cards_button": "type: button\nname: View cards\n",
            },
            "unresolved_placeholders": [
                "fan.kitchen_air",
                "sensor.air_control_downstairs_pm25_average",
            ],
            "unresolved_placeholders_by_card": {},
        },
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}

    assert checks["unresolved_placeholders"]["status"] == "pass"
    assert checks["unresolved_placeholders"]["details"]["unresolved"] == {}


def test_v205_release_check_service_is_documented_and_registered():
    services_source = (INTEGRATION_ROOT / "services.py").read_text()
    services_yaml = (INTEGRATION_ROOT / "services.yaml").read_text()
    readme_source = (ROOT / "README.md").read_text()
    manifest = json.loads((INTEGRATION_ROOT / "manifest.json").read_text())

    assert 'SERVICE_V205_RELEASE_CHECK = "v205_release_check"' in services_source
    assert "SERVICE_V205_RELEASE_CHECK_SCHEMA" in services_source
    assert "handle_v205_release_check" in services_source
    assert "SERVICE_V205_RELEASE_CHECK" in services_source.split("async_unregister_services", 1)[1]
    assert "v205_release_check:" in services_yaml
    assert "v2.0.5-v2.0.12" in services_yaml
    assert "v2.0.5-v2.0.12" in readme_source
    assert "write_test_exports" in services_yaml
    assert "humidity_intelligence.v205_release_check" in readme_source
    assert "humidity_intelligence_v205_release_check.json" in readme_source
    assert manifest["version"] == "2.0.12-beta.4"


def test_owned_ui_path_discovery_and_legacy_cleanup_guidance_is_explicit():
    services_yaml = (INTEGRATION_ROOT / "services.yaml").read_text()
    strings_data = json.loads((INTEGRATION_ROOT / "strings.json").read_text())
    translations_data = json.loads((INTEGRATION_ROOT / "translations" / "en.json").read_text())
    readme_source = (ROOT / "README.md").read_text()
    support_source = (ROOT / "docs" / "support.md").read_text()

    for source in (services_yaml, readme_source, support_source):
        assert "dump_cards" in source
        assert "view_cards" in source
        assert "humidity_intelligence/ui" in source

    assert "does not post a completion path notification" in services_yaml
    assert "Use this instead of dump_cards when path discovery is the priority" in (
        services_yaml
    )
    assert "Manually Removing Files Purge Intentionally Retains" in readme_source
    assert "does not own or purge registered dashboards" in readme_source
    assert "Never overwrite a dashboard file" in readme_source
    assert "Dashboard Setup Guidance" in services_yaml
    assert "performs no file or dashboard writes" in services_yaml
    assert "dashboards are user-managed and are never listed or removed" in services_yaml
    assert "`dump_cards` writes under" in support_source
    assert "completion path notification" in support_source
    assert "does not write a file" in support_source

    for data in (strings_data, translations_data):
        description = data["config"]["step"]["ui_install"]["description"]
        assert "/config/humidity_intelligence/ui/" in description
        assert "/config/humidity_intelligence_cards_v2_mobile.yaml" in description
        assert "retained legacy root file" in description
        assert "no longer refreshed" in description
        assert "refresh its file tree" in description
        assert "card fragments" in description
        assert "does not create, register, replace, or delete" in description


def test_v205_release_check_only_fails_local_snapshot_when_required():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.kitchen_h": _FakeState(45),
            "sensor.hall_h": _FakeState(44),
            "sensor.bed_h": _FakeState(46),
            "sensor.house_humidity_mean_7d": _FakeState(43),
            "sensor.kitchen_t": _FakeState(21),
            "sensor.hall_t": _FakeState(20),
            "sensor.bed_t": _FakeState(19),
            "sensor.l1_iaq": _FakeState(35),
            "sensor.co_val": _FakeState(4),
            "fan.zone1": _FakeState("off"),
            "fan.zone2": _FakeState("off"),
            "fan.aq1": _FakeState("off"),
            "humidifier.l1": _FakeState("off"),
            "light.alert": _FakeState("off"),
            "switch.alert_power": _FakeState("off"),
        },
    )
    runtime_data = {
        "entity_map": {},
        "cards": {
            "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
            "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
            "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
            "view_cards_button": "type: button\nname: View cards\n",
        },
        "unresolved_placeholders_by_card": {},
        "humidifier_reconciliation": _reported_idle_humidifier_truth(),
    }

    optional_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        local_version_status={
            "status": "listed",
            "snapshot_count": 0,
            "latest_snapshot_id": None,
            "latest_snapshot_version": None,
            "latest_snapshot_created_at_utc": None,
        },
    )
    required_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        local_version_status={
            "status": "listed",
            "snapshot_count": 0,
            "latest_snapshot_id": None,
            "latest_snapshot_version": None,
            "latest_snapshot_created_at_utc": None,
        },
        require_local_hi_snapshot=True,
        max_snapshot_age_minutes=60,
    )
    fresh_required_report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.5",
        local_version_status={
            "status": "listed",
            "snapshot_count": 1,
            "latest_snapshot_id": "2.0.5_2999-01-01T000000Z_fixture",
            "latest_snapshot_version": "2.0.5",
            "latest_snapshot_created_at_utc": "2999-01-01T00:00:00Z",
        },
        require_local_hi_snapshot=True,
        max_snapshot_age_minutes=60,
    )

    optional_checks = {check["id"]: check for check in optional_report["checks"]}
    required_checks = {check["id"]: check for check in required_report["checks"]}
    fresh_required_checks = {check["id"]: check for check in fresh_required_report["checks"]}

    assert optional_report["status"] == "pass"
    assert optional_checks["local_hi_snapshot"]["status"] == "info"
    assert required_report["status"] == "fail"
    assert required_checks["local_hi_snapshot"]["status"] == "fail"
    assert fresh_required_checks["local_hi_snapshot"]["status"] == "pass"


def test_alert_configuration_contract_uses_internal_sources():
    const_source = (INTEGRATION_ROOT / "const.py").read_text()
    config_source = (INTEGRATION_ROOT / "config_flow.py").read_text()
    services_source = (INTEGRATION_ROOT / "services.py").read_text()
    strings_source = (INTEGRATION_ROOT / "strings.json").read_text()
    translation_source = (INTEGRATION_ROOT / "translations" / "en.json").read_text()

    for source in (const_source, config_source, strings_source, translation_source):
        assert '"custom_binary"' not in source
        assert '"custom_trigger"' not in source
        assert "custom_trigger_required" not in source

    assert "Internal HI alert source" in strings_source
    assert "Visual Indicator Rule" in strings_source
    assert "Frontend Dependencies" in strings_source
    assert "Frontend Dependencies" in translation_source
    assert "frontend dependencies" in strings_source
    assert "frontend dependencies" in translation_source
    assert "frontend_dependency_resources" in services_source
    assert '"dependency_resources"' not in services_source
    assert "CONF_SHOW_TEMPERATURE_CHIPS" in const_source
    assert "DEFAULT_SHOW_TEMPERATURE_CHIPS" in const_source
    assert "show_temperature_chips" in config_source
    assert "Show temperature chip row in Air Control" in strings_source
    assert "Show temperature chip row in Air Control" in translation_source
    assert "Humidity Intelligence target profile mode" in strings_source
    assert "Humidity custom target low" in strings_source
    assert "HI target profile mode" not in strings_source
    assert "HI custom target low" not in strings_source
    assert "diagnostics_summary" in services_source
    assert "visual_alerts" in services_source
    assert "active_alert_resolution" in services_source
    assert "pm25_entity_id_normalization" in services_source
    sensor_source = (INTEGRATION_ROOT / "sensor.py").read_text()
    assert '"config": _sanitize_json(config)' not in sensor_source
    assert '"entity_map": _sanitize_json(entity_map)' not in sensor_source
    assert '"alert_telemetry": _sanitize_json(alert_telemetry)' not in sensor_source
    assert "_compact_diagnostics_summary" in sensor_source
    assert "pm25_entity_id_normalization" in sensor_source
    assert "Use service humidity_intelligence.dump_diagnostics" in sensor_source
    assert "HUMIDITY_ALERT_FLASH_COUNT = 10" in (INTEGRATION_ROOT / "automations" / "engine.py").read_text()
    assert "HUMIDITY_ALERT_REPEAT_MINUTES = 30" in (INTEGRATION_ROOT / "automations" / "engine.py").read_text()
    assert "alert_remove" in config_source
    assert "options_alert_remove" in config_source
    assert "Remove alert visual rule" in strings_source
    assert "alert_handling_enabled" in strings_source
    assert "Boost settings should normally be higher" in config_source
    assert "existing configured ventilation outputs" in strings_source


def test_v206_drift_statistics_helper_docs_preserve_repair_status_split():
    readme = (ROOT / "README.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert "House Humidity Mean 7d" in readme
    assert "Statistics helper" in readme
    assert "Do not fabricate history" in readme
    assert "not ready or unavailable" in readme
    assert "2.0.7" in changelog
    assert "setup/repair" in changelog
    assert "algorithm" not in changelog.lower()


def test_level_average_ignores_unknown_unavailable_and_non_numeric_states():
    engine_mod, _ = _load_target_modules()
    entry_data = _base_entry_data()
    entry_data["telemetry"].extend(
        [
            {"entity_id": "sensor.l1_iaq_unavailable", "sensor_type": "iaq", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.l1_iaq_text", "sensor_type": "iaq", "level": "level1", "room": "Kitchen"},
            {"entity_id": "sensor.l1_iaq_bad", "sensor_type": "iaq", "level": "level1", "room": "Kitchen"},
        ]
    )
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.l1_iaq": _FakeState("unknown"),
            "sensor.l1_iaq_unavailable": _FakeState("unavailable"),
            "sensor.l1_iaq_text": _FakeState("57.2"),
            "sensor.l1_iaq_bad": _FakeState("not_a_number"),
        },
    )

    engine = engine_mod.HIAutomationEngine(hass, entry)
    assert engine._level_avg("iaq", "level1") == 57.2


def test_pm25_aggregate_sensors_use_object_id_safe_pm25_names_for_new_installs():
    core_mod = _load_core_module()
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "telemetry": [
                {"entity_id": "sensor.l1_pm25", "sensor_type": "pm25", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_pm25", "sensor_type": "pm25", "level": "level2", "room": "Bedroom"},
            ],
            "zones": {},
        },
        options={},
    )
    hass = _FakeHass(
        entry,
        {
            "sensor.l1_pm25": _FakeState("5.0", {"unit_of_measurement": "μg/m³"}),
            "sensor.l2_pm25": _FakeState("7.0", {"unit_of_measurement": "μg/m³"}),
        },
    )

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)
    by_unique_id = {sensor._attr_unique_id: sensor for sensor in sensors}

    expected = {
        f"hi_{ENTRY_ID}_house_pm25_average": "HI House PM25 Average",
        f"hi_{ENTRY_ID}_level1_pm25_average": "HI Level1 PM25 Average",
        f"hi_{ENTRY_ID}_level2_pm25_average": "HI Level2 PM25 Average",
    }
    for unique_id, name in expected.items():
        sensor = by_unique_id[unique_id]
        assert sensor._attr_name == name
        assert "PM2.5" not in sensor._attr_name


def test_pm25_aggregate_sensors_degrade_when_all_pm25_sources_unavailable():
    core_mod = _load_core_module()
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={
            "telemetry": [
                {"entity_id": "sensor.l1_pm25", "sensor_type": "pm25", "level": "level1", "room": "Hallway"},
                {"entity_id": "sensor.l2_pm25", "sensor_type": "pm25", "level": "level2", "room": "Bedroom"},
            ],
            "zones": {},
        },
        options={},
    )
    hass = _FakeHass(
        entry,
        {
            "sensor.l1_pm25": _FakeState("unknown", {"unit_of_measurement": "μg/m³"}),
            "sensor.l2_pm25": _FakeState("unavailable", {"unit_of_measurement": "μg/m³"}),
        },
    )

    sensors, _binary_sensors, _sources = core_mod.build_entities(hass, entry)
    by_unique_id = {sensor._attr_unique_id: sensor for sensor in sensors}

    assert by_unique_id[f"hi_{ENTRY_ID}_house_pm25_average"]._attr_native_value is None
    assert by_unique_id[f"hi_{ENTRY_ID}_level1_pm25_average"]._attr_native_value is None
    assert by_unique_id[f"hi_{ENTRY_ID}_level2_pm25_average"]._attr_native_value is None


def test_pm25_aggregate_registry_normalizes_legacy_pm2_5_entity_ids():
    registry_mod = _load_entity_registry_helper_module()

    class _Entry:
        def __init__(self, entity_id):
            self.entity_id = entity_id

    class _Registry:
        def __init__(self):
            self.updated = []
            self.entries = {
                "sensor.hi_house_pm2_5_average": _Entry("sensor.hi_house_pm2_5_average"),
                "sensor.hi_house_voc_average": _Entry("sensor.hi_house_voc_average"),
            }

        def async_get_entity_id(self, domain, platform, unique_id):
            if (domain, platform, unique_id) == (
                "sensor",
                "humidity_intelligence",
                f"hi_{ENTRY_ID}_house_pm25_average",
            ):
                return "sensor.hi_house_pm2_5_average"
            return None

        def async_get(self, entity_id):
            return self.entries.get(entity_id)

        def async_update_entity(self, entity_id, *, new_entity_id):
            entry = self.entries.pop(entity_id)
            entry.entity_id = new_entity_id
            self.entries[new_entity_id] = entry
            self.updated.append((entity_id, new_entity_id))

    registry = _Registry()
    hass = SimpleNamespace()
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda _hass: registry

    changed = registry_mod.normalize_pm25_aggregate_entity_ids(hass, ENTRY_ID)

    assert changed == {
        "changed": {
            "sensor.hi_house_pm2_5_average": "sensor.hi_house_pm25_average",
        },
        "blocked": [],
    }
    assert "sensor.hi_house_pm25_average" in registry.entries
    assert "sensor.hi_house_pm2_5_average" not in registry.entries
    assert "sensor.hi_house_voc_average" in registry.entries
    assert registry.updated == [
        ("sensor.hi_house_pm2_5_average", "sensor.hi_house_pm25_average")
    ]


def test_pm25_aggregate_registry_reports_blocked_target_conflict():
    registry_mod = _load_entity_registry_helper_module()

    class _Entry:
        def __init__(self, entity_id):
            self.entity_id = entity_id

    class _Registry:
        def __init__(self):
            self.updated = []
            self.entries = {
                "sensor.hi_house_pm2_5_average": _Entry("sensor.hi_house_pm2_5_average"),
                "sensor.hi_house_pm25_average": _Entry("sensor.hi_house_pm25_average"),
            }

        def async_get_entity_id(self, domain, platform, unique_id):
            if (domain, platform, unique_id) == (
                "sensor",
                "humidity_intelligence",
                f"hi_{ENTRY_ID}_house_pm25_average",
            ):
                return "sensor.hi_house_pm2_5_average"
            return None

        def async_get(self, entity_id):
            return self.entries.get(entity_id)

        def async_update_entity(self, entity_id, *, new_entity_id):
            self.updated.append((entity_id, new_entity_id))

    registry = _Registry()
    hass = SimpleNamespace()
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda _hass: registry

    status = registry_mod.normalize_pm25_aggregate_entity_ids(hass, ENTRY_ID)

    assert status == {
        "changed": {},
        "blocked": [
            {
                "unique_suffix": "house_pm25_average",
                "current_entity_id": "sensor.hi_house_pm2_5_average",
                "target_entity_id": "sensor.hi_house_pm25_average",
                "reason": "target_exists",
            }
        ],
    }
    assert registry.updated == []


def test_v205_release_check_warns_on_blocked_pm25_normalization():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(
        entry,
        {
            "sensor.house_humidity_mean_7d": _FakeState(43),
        },
    )
    runtime_data = {
        "entity_map": {},
        "cards": {
            "v2_mobile": "type: markdown\ncontent: Mobile ready\n",
            "v2_tablet": "type: markdown\ncontent: Tablet ready\n",
            "v1_mobile": "type: markdown\ncontent: Legacy ready\n",
            "view_cards_button": "type: button\nname: View cards\n",
        },
        "unresolved_placeholders_by_card": {},
        "pm25_entity_id_normalization": {
            "changed": {},
            "blocked": [
                {
                    "unique_suffix": "house_pm25_average",
                    "current_entity_id": "sensor.hi_house_pm2_5_average",
                    "target_entity_id": "sensor.hi_house_pm25_average",
                    "reason": "target_exists",
                }
            ],
        },
    }

    report = services_mod._build_v205_release_check_entry_report(
        hass,
        entry,
        runtime_data,
        manifest_version="2.0.7-beta.1",
        frontend_dependencies={"status": "not_inspectable"},
    )
    checks = {check["id"]: check for check in report["checks"]}
    summary = services_mod._build_diagnostics_summary(
        hass,
        entry.data,
        entry.options,
        {},
        runtime_data,
    )

    assert checks["pm25_entity_id_normalization"]["status"] == "warn"
    assert checks["pm25_entity_id_normalization"]["details"]["status"] == "blocked"
    assert summary["pm25_entity_id_normalization"]["status"] == "blocked"
    assert any("PM25 aggregate entity ID normalization is blocked" in warning for warning in summary["warnings"])


def _set_fake_config_path(hass, root):
    hass.config = SimpleNamespace(
        path=lambda *parts: str(pathlib.Path(root).joinpath(*parts)),
    )


def test_create_dashboard_requires_admin_then_returns_guidance_without_side_effects():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth(
        {
            "admin": SimpleNamespace(is_admin=True),
            "viewer": SimpleNamespace(is_admin=False),
        }
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_CREATE_DASHBOARD)
        ]

        for context in (
            SimpleNamespace(user_id="viewer"),
            SimpleNamespace(user_id=None),
        ):
            try:
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={
                                "entry_id": ENTRY_ID,
                                "layout": "v2_mobile",
                                "title": "Humidity Intelligence",
                                "url_path": "humidity-intelligence",
                            },
                            context=context,
                        )
                    )
                )
            except Exception as err:
                assert "requires an admin user" in str(err)
            else:
                raise AssertionError("create_dashboard should require admin context")

        assert not (
            pathlib.Path(tmpdir) / "dashboards" / "humidity-intelligence.yaml"
        ).exists()

        class RejectConfigEntries:
            def __getattr__(self, name):
                raise AssertionError(f"config-entry lookup must not run: {name}")

        hass.config_entries = RejectConfigEntries()

        try:
            asyncio.run(
                handler(
                    SimpleNamespace(
                        data={
                            "entry_id": ENTRY_ID,
                            "layout": "v2_mobile",
                            "title": "Humidity Intelligence",
                            "url_path": "humidity-intelligence",
                        },
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
        except services_mod.HomeAssistantError as err:
            message = str(err)
            assert "cannot create or register" in message
            assert "No file or dashboard was changed" in message
            assert "humidity_intelligence.refresh_ui" in message
            assert "humidity_intelligence.view_cards" in message
            assert "card fragment" in message
            assert "/config/dashboards/" in message
        else:
            raise AssertionError("create_dashboard should return Manual-card guidance")
        assert (
            pathlib.Path(tmpdir) / "dashboards" / "humidity-intelligence.yaml"
        ).exists() is False
        assert hass.services.calls == []


def test_create_dashboard_helper_returns_guidance_before_any_runtime_work():
    services_mod = _load_services_module()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})

    compatibility_payload = services_mod.SERVICE_CREATE_DASHBOARD_SCHEMA(
        {
            "entry_id": ENTRY_ID,
            "layout": "legacy-caller-value",
            "title": "Legacy caller",
            "url_path": "../legacy-caller-value",
        }
    )
    assert compatibility_payload["layout"] == "legacy-caller-value"
    assert compatibility_payload["url_path"] == "../legacy-caller-value"

    class RejectPathAccess:
        def path(self, *_parts):
            raise AssertionError("config path must not be evaluated")

    hass = SimpleNamespace(config=RejectPathAccess())
    try:
        asyncio.run(
            services_mod.async_create_dashboard_for_entry(
                hass,
                entry,
                layout="v2_mobile",
                title="Humidity Intelligence",
                url_path="../configuration",
            )
        )
    except services_mod.HomeAssistantError as err:
        assert "No file or dashboard was changed" in str(err)
        assert "card fragment" in str(err)
    else:
        raise AssertionError("dashboard helper should be guidance-only")


def test_first_run_legacy_dashboard_selection_is_ignored_export_only():
    integration_mod = _load_integration_init_module()
    service_calls = []
    updates = []
    card_export_calls = []

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    async def export_cards(_hass, entry_id, filename, layout=None):
        card_export_calls.append((entry_id, filename, layout))
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        ]

    integration_mod.async_export_cards_to_owned_ui = export_cards
    hass = SimpleNamespace(
        services=SimpleNamespace(async_call=async_call),
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: [entry],
            async_update_entry=lambda entry, *, data: updates.append(
                (entry.entry_id, data)
            )
        ),
    )
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={"ui_layouts": ["v2_mobile", "create_dashboard"]},
    )

    asyncio.run(integration_mod._async_install_selected_ui(hass, entry))

    assert card_export_calls == [(ENTRY_ID, None, None)]
    assert all(
        call[0:2] != (integration_mod.DOMAIN, "dump_cards")
        for call in service_calls
    )
    assert [
        call[2]["title"]
        for call in service_calls
        if call[0:2] == ("persistent_notification", "create")
    ] == ["Humidity Intelligence UI Cards"]
    card_notification = [
        call[2]["message"]
        for call in service_calls
        if call[0:2] == ("persistent_notification", "create")
    ][0]
    assert "/config/humidity_intelligence/ui/" in card_notification
    assert "Manual-card YAML written" in card_notification
    assert "does not create or replace dashboards automatically" in card_notification
    assert "card fragments" in card_notification
    assert "do not copy them to /config/dashboards/" in card_notification
    assert "Older generated card files in the /config root" in card_notification
    assert "Use only the exact paths above" in card_notification
    assert updates == [
        (
            ENTRY_ID,
            {
                "ui_layouts": ["v2_mobile", "create_dashboard"],
                "ui_install_done": True,
            },
        )
    ]


def test_second_entry_first_run_reexports_all_entries_with_qualified_paths():
    integration_mod = _load_integration_init_module()
    service_calls = []
    export_calls = []
    updates = []
    first = SimpleNamespace(
        entry_id="entry_one",
        data={"ui_layouts": ["v2_mobile"], "ui_install_done": True},
    )
    second = SimpleNamespace(
        entry_id="entry_two",
        data={"ui_layouts": ["v2_mobile"]},
    )

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    async def export_cards(_hass, entry_id, filename, layout=None):
        export_calls.append((entry_id, filename, layout))
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_entry_one_v2_mobile.yaml",
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_entry_two_v2_mobile.yaml",
        ]

    integration_mod.async_export_cards_to_owned_ui = export_cards
    hass = SimpleNamespace(
        services=SimpleNamespace(async_call=async_call),
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: [first, second],
            async_update_entry=lambda entry, *, data: updates.append(
                (entry.entry_id, data)
            ),
        ),
    )

    asyncio.run(integration_mod._async_install_selected_ui(hass, second))

    assert export_calls == [(None, None, None)]
    notification = [
        call
        for call in service_calls
        if call[0:2] == ("persistent_notification", "create")
    ][0]
    assert "humidity_intelligence_cards_entry_one_v2_mobile.yaml" in (
        notification[2]["message"]
    )
    assert "humidity_intelligence_cards_entry_two_v2_mobile.yaml" in (
        notification[2]["message"]
    )
    assert updates[0][0] == "entry_two"


def test_first_run_legacy_dashboard_selection_does_not_retry_or_loop():
    integration_mod = _load_integration_init_module()
    service_calls = []
    updates = []

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    async def export_cards(_hass, _entry_id, _filename, layout=None):
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_tablet.yaml"
        ]

    integration_mod.async_export_cards_to_owned_ui = export_cards
    hass = SimpleNamespace(
        services=SimpleNamespace(async_call=async_call),
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: [entry],
            async_update_entry=lambda entry, *, data: updates.append(
                (entry.entry_id, data)
            )
        ),
    )
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={"ui_layouts": ["v2_tablet", "create_dashboard"]},
    )

    asyncio.run(integration_mod._async_install_selected_ui(hass, entry))

    notifications = [
        call
        for call in service_calls
        if call[0:2] == ("persistent_notification", "create")
    ]
    assert [call[2]["title"] for call in notifications] == [
        "Humidity Intelligence UI Cards",
    ]
    assert "does not create or replace dashboards automatically" in (
        notifications[0][2]["message"]
    )
    assert updates == [
        (
            ENTRY_ID,
            {
                "ui_layouts": ["v2_tablet", "create_dashboard"],
                "ui_install_done": True,
            },
        )
    ]


def test_config_entry_removal_uses_owned_ui_plans_without_report_or_legacy_cleanup():
    integration_mod = _load_integration_init_module()
    planned_names = []
    removed_paths = []
    service_calls = []
    plan = SimpleNamespace(
        relative_path=(
            "humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        )
    )

    def list_names(entries, **kwargs):
        assert [item.entry_id for item in entries] == [ENTRY_ID]
        assert kwargs == {
            "multiple_installation": False,
            "include_unqualified_defaults": True,
        }
        return ["humidity_intelligence_cards_v2_mobile.yaml"]

    def plan_removal(config_root, filenames):
        planned_names.append((config_root, list(filenames)))
        return [plan]

    def remove_export(config_root, removal_plan):
        removed_paths.append((config_root, removal_plan.relative_path))
        return True

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    async def executor_job(func, *args):
        return func(*args)

    integration_mod.list_owned_ui_filenames = list_names
    integration_mod.plan_owned_ui_export_removal = plan_removal
    integration_mod.remove_owned_ui_export = remove_export
    entry = SimpleNamespace(
        entry_id=ENTRY_ID,
        data={"ui_dashboard_id": "humidity-intelligence"},
    )
    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_parts: "/config"),
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: [entry],
        ),
        services=SimpleNamespace(async_call=async_call),
        async_add_executor_job=executor_job,
    )

    asyncio.run(integration_mod.async_remove_entry(hass, entry))

    assert planned_names == [
        ("/config", ["humidity_intelligence_cards_v2_mobile.yaml"])
    ]
    assert removed_paths == [
        (
            "/config",
            "humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml",
        )
    ]
    message = service_calls[0][2]["message"]
    assert "/config/humidity_intelligence/ui/" in message
    assert "exports/" not in message
    assert "/config/humidity_intelligence_cards_" not in message
    assert "dashboards are user-managed" in message
    assert "Dashboard: humidity-intelligence" not in message


def test_two_to_one_entry_removal_reexports_remaining_entry_and_owns_qualified_remnants():
    integration_mod = _load_integration_init_module()
    listed = []
    export_calls = []
    service_calls = []
    removed = SimpleNamespace(
        entry_id="entry_two",
        data={},
    )
    remaining = SimpleNamespace(
        entry_id="entry_one",
        data={},
    )

    def list_names(entries, **kwargs):
        listed.append(([item.entry_id for item in entries], kwargs))
        return [
            "humidity_intelligence_cards_entry_two_v2_mobile.yaml",
        ]

    async def export_cards(
        _hass,
        entry_id,
        filename,
        layout=None,
        *,
        multiple_installation=None,
    ):
        export_calls.append(
            (
                entry_id,
                filename,
                layout,
                multiple_installation,
            )
        )
        return [
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        ]

    async def async_call(domain, service, data=None, blocking=False):
        service_calls.append((domain, service, data or {}, blocking))

    async def executor_job(func, *args):
        return func(*args)

    integration_mod.list_owned_ui_filenames = list_names
    integration_mod.plan_owned_ui_export_removal = lambda *_args: []
    integration_mod.async_export_cards_to_owned_ui = export_cards
    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_parts: "/config"),
        config_entries=SimpleNamespace(
            async_entries=lambda _domain: [removed, remaining],
        ),
        services=SimpleNamespace(async_call=async_call),
        async_add_executor_job=executor_job,
    )

    asyncio.run(integration_mod.async_remove_entry(hass, removed))

    assert listed == [
        (
            ["entry_two"],
            {
                "multiple_installation": True,
                "include_unqualified_defaults": False,
            },
        )
    ]
    assert export_calls == [
        ("entry_one", None, None, False),
    ]
    updated = [
        call
        for call in service_calls
        if call[2].get("title") == "Humidity Intelligence UI Cards Updated"
    ]
    assert len(updated) == 1
    assert "humidity_intelligence_cards_v2_mobile.yaml" in updated[0][2]["message"]


def test_dashboard_compatibility_path_contains_no_unsupported_lovelace_api():
    source = (INTEGRATION_ROOT / "services.py").read_text(encoding="utf-8")
    cleanup_source = (INTEGRATION_ROOT / "helpers" / "cleanup.py").read_text(encoding="utf-8")
    integration_source = (INTEGRATION_ROOT / "__init__.py").read_text(encoding="utf-8")

    assert "async_create_dashboard" not in source.replace(
        "async_create_dashboard_for_entry", ""
    )
    assert "async_delete_dashboard" not in cleanup_source
    assert "remove_dashboard" not in cleanup_source
    assert 'f"dashboards/{url_path}.yaml"' not in source
    assert "ui_dashboard_id" not in integration_source


def test_purge_validates_all_candidates_before_any_side_effect():
    services_mod = _load_services_module()
    entry_data = _base_entry_data()
    entry_data["ui_dashboard_id"] = "humidity-intelligence"
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        ui_dir = pathlib.Path(tmpdir) / "humidity_intelligence" / "ui"
        ui_dir.mkdir(parents=True)
        safe_path = ui_dir / "humidity_intelligence_cards_v2_mobile.yaml"
        safe_path.write_text("safe", encoding="utf-8")
        unsafe_path = ui_dir / "humidity_intelligence_cards_v2_tablet.yaml"
        unsafe_path.symlink_to(safe_path)
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_PURGE_FILES)
        ]

        try:
            asyncio.run(
                handler(
                    SimpleNamespace(
                        data={"entry_id": ENTRY_ID},
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
        except Exception as err:
            assert "Cleanup plan rejected" in str(err)
        else:
            raise AssertionError("purge should reject an unsafe complete target plan")

        assert safe_path.read_text(encoding="utf-8") == "safe"
        assert hass.services.calls == []


def test_purge_requires_admin_and_uses_exact_blocking_preview():
    services_mod = _load_services_module()
    report_exports_mod = sys.modules[f"{PKG}.helpers.report_exports"]
    entry_data = _base_entry_data()
    entry_data["ui_layouts"] = ["v2_mobile"]
    entry_data["ui_dashboard_id"] = "humidity-intelligence"
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth(
        {
            "admin": SimpleNamespace(is_admin=True),
            "viewer": SimpleNamespace(is_admin=False),
        }
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        ui_dir = pathlib.Path(tmpdir) / "humidity_intelligence" / "ui"
        ui_dir.mkdir(parents=True)
        generated = ui_dir / "humidity_intelligence_cards_v2_mobile.yaml"
        generated.write_text("generated", encoding="utf-8")
        legacy_root = pathlib.Path(tmpdir) / "humidity_intelligence_cards.yaml"
        legacy_root.write_text("legacy", encoding="utf-8")
        owned_diagnostics = report_exports_mod.write_owned_report(
            tmpdir,
            report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_FILENAME,
            {"status": "retained"},
        )
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_PURGE_FILES)
        ]

        for context in (
            SimpleNamespace(user_id="viewer"),
            SimpleNamespace(user_id=None),
        ):
            try:
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={"entry_id": ENTRY_ID},
                            context=context,
                        )
                    )
                )
            except Exception as err:
                assert "requires an admin user" in str(err)
            else:
                raise AssertionError("purge_files should require admin context")

        assert generated.exists()
        assert hass.services.calls == []

        sequence = []
        original_async_call = hass.services.async_call
        original_executor = hass.async_add_executor_job

        async def tracking_call(domain, service, data=None, blocking=False):
            if (domain, service) == ("persistent_notification", "create"):
                sequence.append(("notification", bool(blocking)))
            return await original_async_call(domain, service, data, blocking)

        async def tracking_executor(func, *args):
            sequence.append((func.__name__, None))
            return await original_executor(func, *args)

        hass.services.async_call = tracking_call
        hass.async_add_executor_job = tracking_executor
        asyncio.run(
            handler(
                SimpleNamespace(
                    data={"entry_id": ENTRY_ID},
                    context=SimpleNamespace(user_id="admin"),
                )
            )
        )

        preview_calls = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
            and call[2].get("title") == "Humidity Intelligence Cleanup Preview"
        ]
        assert len(preview_calls) == 1
        preview = preview_calls[0]
        assert preview[3] is True
        assert (
            "/config/humidity_intelligence/ui/"
            "humidity_intelligence_cards_v2_mobile.yaml"
        ) in preview[2]["message"]
        assert "/config/humidity_intelligence_cards.yaml" not in preview[2]["message"]
        assert "Dashboard: humidity-intelligence" not in preview[2]["message"]
        assert "dashboards are user-managed" in preview[2]["message"]
        assert "humidity_intelligence_diagnostics.json" not in preview[2]["message"]
        assert sequence.index(("notification", True)) < sequence.index(
            ("remove_owned_ui_export", None)
        )
        assert not generated.exists()
        assert legacy_root.read_text(encoding="utf-8") == "legacy"
        assert (pathlib.Path(tmpdir) / owned_diagnostics).is_file()


def test_unscoped_purge_removes_only_fixed_owned_reports():
    services_mod = _load_services_module()
    report_exports_mod = sys.modules[f"{PKG}.helpers.report_exports"]
    entry_data = _base_entry_data()
    entry_data["ui_layouts"] = ["v2_mobile"]
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})

    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        _set_fake_config_path(hass, root)
        default_name = report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_FILENAME
        self_check_name = report_exports_mod.DEFAULT_SELF_CHECK_REPORT_FILENAME
        release_name = "humidity_intelligence_v205_release_check.json"
        custom_name = "humidity_intelligence_custom.json"
        legacy_root = root / default_name
        legacy_root.write_text('{"legacy": true}\n', encoding="utf-8")
        legacy_self_check = root / self_check_name
        legacy_self_check.write_text('{"legacy_self_check": true}\n', encoding="utf-8")
        for filename in (
            default_name,
            self_check_name,
            release_name,
            custom_name,
        ):
            report_exports_mod.write_owned_report(
                root,
                filename,
                {"name": filename},
            )

        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_PURGE_FILES)
        ]
        asyncio.run(
            handler(
                SimpleNamespace(
                    data={},
                    context=SimpleNamespace(user_id="admin"),
                )
            )
        )

        exports_dir = root / "humidity_intelligence" / "exports"
        assert not (exports_dir / default_name).exists()
        assert not (exports_dir / self_check_name).exists()
        assert (exports_dir / release_name).is_file()
        assert (exports_dir / custom_name).is_file()
        assert legacy_root.read_text(encoding="utf-8") == '{"legacy": true}\n'
        assert (
            legacy_self_check.read_text(encoding="utf-8")
            == '{"legacy_self_check": true}\n'
        )

        preview_calls = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
            and call[2].get("title") == "Humidity Intelligence Cleanup Preview"
        ]
        assert len(preview_calls) == 1
        preview_message = preview_calls[0][2]["message"]
        assert (
            "Home Assistant config/humidity_intelligence/exports/" + default_name
        ) in preview_message
        assert (
            "Home Assistant config/humidity_intelligence/exports/"
            + self_check_name
        ) in preview_message
        assert release_name not in preview_message
        assert custom_name not in preview_message


def test_unscoped_purge_reports_owned_diagnostics_changed_after_preview():
    services_mod = _load_services_module()
    report_exports_mod = sys.modules[f"{PKG}.helpers.report_exports"]
    entry_data = _base_entry_data()
    entry_data["ui_layouts"] = ["v2_mobile"]
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})

    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        _set_fake_config_path(hass, root)
        default_name = report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_FILENAME
        report_exports_mod.write_owned_report(
            root,
            default_name,
            {"version": 1},
        )
        destination = root / report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_RELATIVE_PATH

        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_PURGE_FILES)
        ]
        original_async_call = hass.services.async_call

        async def replace_after_preview(domain, service, data=None, blocking=False):
            result = await original_async_call(domain, service, data, blocking)
            if (
                (domain, service) == ("persistent_notification", "create")
                and (data or {}).get("title")
                == "Humidity Intelligence Cleanup Preview"
            ):
                destination.unlink()
                destination.write_text('{"version": 2}\n', encoding="utf-8")
            return result

        hass.services.async_call = replace_after_preview
        try:
            asyncio.run(
                handler(
                    SimpleNamespace(
                        data={},
                        context=SimpleNamespace(user_id="admin"),
                    )
                )
            )
        except Exception as err:
            message = str(err)
            assert "Purge incomplete" in message
            assert "reports:" in message
            assert report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_RELATIVE_PATH in message
        else:
            raise AssertionError("changed diagnostics export should fail the purge")

        assert json.loads(destination.read_text(encoding="utf-8")) == {"version": 2}
        incomplete = [
            call
            for call in hass.services.calls
            if call[0:2] == ("persistent_notification", "create")
            and call[2].get("title") == "Humidity Intelligence Cleanup Incomplete"
        ]
        assert len(incomplete) == 1
        assert (
            report_exports_mod.DEFAULT_DIAGNOSTICS_REPORT_RELATIVE_PATH
            in incomplete[0][2]["message"]
        )


def test_purge_reports_file_failures_without_dashboard_ownership():
    services_mod = _load_services_module()
    entry_data = _base_entry_data()
    entry_data["ui_dashboard_id"] = "humidity-intelligence"
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.auth = _FakeAuth({"admin": SimpleNamespace(is_admin=True)})
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_fake_config_path(hass, tmpdir)
        generated_name = "humidity_intelligence_cards_v2_mobile.yaml"
        generated_relative = f"humidity_intelligence/ui/{generated_name}"
        generated_path = (
            pathlib.Path(tmpdir) / "humidity_intelligence" / "ui" / generated_name
        )
        generated_path.parent.mkdir(parents=True)
        generated_path.write_text(
            "generated",
            encoding="utf-8",
        )
        asyncio.run(services_mod.async_register_services(hass))
        handler = hass.services.handlers[
            (services_mod.DOMAIN, services_mod.SERVICE_PURGE_FILES)
        ]
        original_remove_export = services_mod.remove_owned_ui_export

        def fail_remove_export(*_args):
            raise services_mod.ReportExportError("fixture removal failed")

        services_mod.remove_owned_ui_export = fail_remove_export
        try:
            try:
                asyncio.run(
                    handler(
                        SimpleNamespace(
                            data={"entry_id": ENTRY_ID},
                            context=SimpleNamespace(user_id="admin"),
                        )
                    )
                )
            except Exception as err:
                message = str(err)
                assert "Purge incomplete" in message
                assert generated_relative in message
                assert "dashboards:" not in message
            else:
                raise AssertionError("partial purge failure should be reported")
        finally:
            services_mod.remove_owned_ui_export = original_remove_export


def test_generated_v1_cards_escape_dynamic_html_text():
    sources = []
    for path in (
        INTEGRATION_ROOT / "ui" / "cards" / "v1_mobile.yaml",
        ROOT / "ui-gallery" / "default-v1-mobile" / "card.yaml",
    ):
        source = path.read_text(encoding="utf-8")
        sources.append(source)
        assert source.count("const escapeHtml = ") >= 2, path
        assert "${escapeHtml(item.label)}" in source, path
        assert "Target humidity (${escapeHtml(season)}):" in source, path
        assert (
            "Condensation: ${escapeHtml(condRisk)} in ${escapeHtml(condRoom)}"
            in source
        ), path
        assert (
            "Mould: ${escapeHtml(mouldRisk)} in ${escapeHtml(mouldRoom)}"
            in source
        ), path
        assert '<span class="k">${item.label}</span>' not in source, path
        assert "Condensation: ${condRisk} in ${condRoom}" not in source, path
        assert "Mould: ${mouldRisk} in ${mouldRoom}" not in source, path
    assert sources[0] == sources[1]


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
    print(f"{len(tests)} direct sanity checks passed.")
