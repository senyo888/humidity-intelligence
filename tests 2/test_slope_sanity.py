"""Direct sanity checks for HI slope sensor startup behavior."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "humidity_intelligence"
PKG = "hi_slope_testpkg"


def _install_homeassistant_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    sensor_mod = types.ModuleType("homeassistant.components.sensor")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    event = types.ModuleType("homeassistant.helpers.event")
    util = types.ModuleType("homeassistant.util")
    const = types.ModuleType("homeassistant.const")

    class HomeAssistant:
        pass

    class ConfigEntry:
        pass

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class SensorEntity:
        def __init__(self):
            self.entity_id = None

        def async_write_ha_state(self):
            return None

    class SensorStateClass:
        MEASUREMENT = "measurement"

    class UnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    def async_track_state_change_event(*args, **kwargs):
        return lambda: None

    def async_track_time_interval(*args, **kwargs):
        return lambda: None

    def slugify(value):
        import re

        return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()))

    def async_get_registry(hass):
        return getattr(hass, "entity_registry", None)

    core.HomeAssistant = HomeAssistant
    config_entries.ConfigEntry = ConfigEntry
    device_registry.DeviceInfo = DeviceInfo
    sensor_mod.SensorEntity = SensorEntity
    sensor_mod.SensorStateClass = SensorStateClass
    event.async_track_state_change_event = async_track_state_change_event
    event.async_track_time_interval = async_track_time_interval
    entity_registry.async_get = async_get_registry
    util.slugify = slugify
    const.UnitOfTemperature = UnitOfTemperature

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.sensor"] = sensor_mod
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.const"] = const


def _install_package_scaffold() -> None:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    sensors_pkg = types.ModuleType(f"{PKG}.sensors")
    sensors_pkg.__path__ = [str(INTEGRATION_ROOT / "sensors")]
    sys.modules[f"{PKG}.sensors"] = sensors_pkg

    helpers_pkg = types.ModuleType(f"{PKG}.helpers")
    helpers_pkg.__path__ = [str(INTEGRATION_ROOT / "helpers")]
    sys.modules[f"{PKG}.helpers"] = helpers_pkg


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_slope_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    _load_module(f"{PKG}.const", INTEGRATION_ROOT / "const.py")
    _load_module(f"{PKG}.helpers.parsing", INTEGRATION_ROOT / "helpers" / "parsing.py")
    return _load_module(f"{PKG}.sensors.slope", INTEGRATION_ROOT / "sensors" / "slope.py")


class _FakeState:
    def __init__(self, state, attrs=None):
        self.state = str(state)
        self.attributes = attrs or {}


class _FakeStates:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, entity_id):
        return self._values.get(entity_id)


class _FakeConfig:
    class units:
        temperature_unit = "°C"


class _FakeRegistry:
    def __init__(self, entity_ids=None):
        self._entity_ids = dict(entity_ids or {})

    def async_get_entity_id(self, domain, platform, unique_id):
        return self._entity_ids.get((domain, platform, unique_id))


class _RaisingRegistry:
    def __init__(self, exc):
        self._exc = exc

    def async_get_entity_id(self, domain, platform, unique_id):
        raise self._exc


class _FakeHass:
    def __init__(self, states, registry=None):
        self.states = _FakeStates(states)
        self.data = {}
        self.config = _FakeConfig()
        self.entity_registry = registry


def _single_temperature_entry():
    return SimpleNamespace(
        entry_id="entry123",
        data={
            "telemetry": [
                {
                    "entity_id": "sensor.kitchen_temperature",
                    "sensor_type": "temperature",
                    "room": "Kitchen",
                }
            ],
            "slope": {
                "mode": "hi_calculates",
                "source_entities": ["sensor.kitchen_temperature"],
            },
        },
        options={},
    )


def _single_temperature_hass(registry=None):
    return _FakeHass(
        {
            "sensor.kitchen_temperature": _FakeState(
                "21.0",
                {"unit_of_measurement": "°C"},
            )
        },
        registry,
    )


def test_slope_entities_are_seeded_immediately_on_setup_for_all_sources():
    slope_mod = _load_slope_module()
    entry = SimpleNamespace(
        entry_id="entry123",
        data={
            "telemetry": [
                {
                    "entity_id": "sensor.room_alpha_temperature",
                    "sensor_type": "temperature",
                    "room": "Room Alpha",
                },
                {
                    "entity_id": "sensor.room_beta_temperature",
                    "sensor_type": "temperature",
                    "room": "Room Beta",
                },
                {
                    "entity_id": "sensor.room_gamma_temperature",
                    "sensor_type": "temperature",
                    "room": "Room Gamma",
                }
            ],
            "slope": {
                "mode": "hi_calculates",
                "source_entities": [
                    "sensor.room_alpha_temperature",
                    "sensor.room_beta_temperature",
                    "sensor.room_gamma_temperature",
                ],
            },
        },
        options={},
    )
    hass = _FakeHass(
        {
            "sensor.room_alpha_temperature": _FakeState(
                "20.21",
                {"unit_of_measurement": "°C"},
            ),
            "sensor.room_beta_temperature": _FakeState(
                "20.62",
                {"unit_of_measurement": "°C"},
            ),
            "sensor.room_gamma_temperature": _FakeState(
                "19.75",
                {"unit_of_measurement": "°C"},
            ),
        },
        _FakeRegistry(
            {
                (
                    "sensor",
                    "humidity_intelligence",
                    "hi_entry123_slope_room_alpha",
                ): "sensor.humidity_intelligence_hi_room_alpha_temperature_slope",
                (
                    "sensor",
                    "humidity_intelligence",
                    "hi_entry123_slope_room_beta",
                ): "sensor.hi_room_beta_temperature_slope",
            }
        ),
    )

    sensors, slope_sources, slope_map = slope_mod.build_slope_entities(hass, entry)

    assert slope_sources == [
        "sensor.room_alpha_temperature",
        "sensor.room_beta_temperature",
        "sensor.room_gamma_temperature",
    ]
    assert slope_map == {
        "sensor.room_alpha_temperature": "sensor.humidity_intelligence_hi_room_alpha_temperature_slope",
        "sensor.room_beta_temperature": "sensor.hi_room_beta_temperature_slope",
        "sensor.room_gamma_temperature": "sensor.hi_room_gamma_temperature_slope",
    }
    assert len(sensors) == 3
    for sensor in sensors:
        assert sensor._attr_native_value == 0.0
        assert sensor._attr_extra_state_attributes == {
            "source_entity": sensor._source,
            "window_minutes": 60,
            "sample_count": 2,
        }


def test_slope_mapping_uses_fallback_for_invalid_registered_entity_ids():
    slope_mod = _load_slope_module()
    unique_key = ("sensor", "humidity_intelligence", "hi_entry123_slope_kitchen")

    for invalid_entity_id in ("", 0, object()):
        hass = _single_temperature_hass(
            _FakeRegistry({unique_key: invalid_entity_id})
        )

        _, slope_sources, slope_map = slope_mod.build_slope_entities(
            hass,
            _single_temperature_entry(),
        )

        assert slope_sources == ["sensor.kitchen_temperature"]
        assert slope_map == {
            "sensor.kitchen_temperature": "sensor.hi_kitchen_temperature_slope"
        }


def test_slope_mapping_uses_fallback_when_registry_lookup_raises():
    slope_mod = _load_slope_module()

    for exc in (AttributeError("missing"), TypeError("bad type"), ValueError("bad value")):
        hass = _single_temperature_hass(_RaisingRegistry(exc))

        _, slope_sources, slope_map = slope_mod.build_slope_entities(
            hass,
            _single_temperature_entry(),
        )

        assert slope_sources == ["sensor.kitchen_temperature"]
        assert slope_map == {
            "sensor.kitchen_temperature": "sensor.hi_kitchen_temperature_slope"
        }


def test_slope_mapping_uses_fallback_before_registry_entry_exists():
    slope_mod = _load_slope_module()
    hass = _single_temperature_hass()

    _, slope_sources, slope_map = slope_mod.build_slope_entities(
        hass,
        _single_temperature_entry(),
    )

    assert slope_sources == ["sensor.kitchen_temperature"]
    assert slope_map == {
        "sensor.kitchen_temperature": "sensor.hi_kitchen_temperature_slope"
    }



def test_provided_pairs_do_not_fall_back_to_list_order_after_rename():
    mod = _load_slope_module()
    states = {
        'sensor.example_trend_x': SimpleNamespace(attributes={'friendly_name': 'Room A slope'}),
        'sensor.example_trend_y': SimpleNamespace(attributes={'friendly_name': 'Room B slope'}),
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    sources = ['sensor.example_temp_a', 'sensor.example_temp_b']
    provided = ['sensor.example_trend_y', 'sensor.example_trend_x']
    rooms = dict(zip(sources, ['Room A', 'Room B']))
    expected = {sources[0]: provided[1], sources[1]: provided[0]}
    assert mod._match_provided_sensors_to_sources(hass, sources, provided, rooms) == expected
    for state in states.values():
        state.attributes['friendly_name'] = 'Renamed shared display'
    assert mod._match_provided_sensors_to_sources(hass, sources, provided, rooms) == {}
    assert mod._match_provided_sensors_to_sources(hass, list(reversed(sources)), provided, rooms, expected) == expected
    states.clear()
    assert mod._match_provided_sensors_to_sources(hass, sources, provided, rooms, expected) == expected


def test_ambiguous_names_and_duplicate_saved_targets_are_unmapped():
    mod = _load_slope_module()
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _id: SimpleNamespace(attributes={'friendly_name': 'Room A slope'})))
    sources = ['sensor.example_temp_a', 'sensor.example_temp_b']
    provided = ['sensor.example_trend_x', 'sensor.example_trend_y']
    rooms = {source: 'Room A' for source in sources}
    assert mod._match_provided_sensors_to_sources(hass, sources, provided, rooms) == {}
    assert mod._match_provided_sensors_to_sources(hass, sources, provided, rooms, {source: provided[0] for source in sources}) == {}
    assert mod._match_provided_sensors_to_sources(hass, sources[:1], provided[:1], rooms) == {sources[0]: provided[0]}


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
    print(f"{len(tests)} slope sanity checks passed.")
