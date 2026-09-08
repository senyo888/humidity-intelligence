"""Direct tests for read-only setup assistance from Home Assistant metadata."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from types import SimpleNamespace
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "humidity_intelligence"
PKG = "hi_setup_assist_testpkg"


def _install_homeassistant_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    area_registry = types.ModuleType("homeassistant.helpers.area_registry")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    label_registry = types.ModuleType("homeassistant.helpers.label_registry")

    class HomeAssistant:
        pass

    class _Registry:
        def __init__(self, entries):
            self._entries = dict(entries)

        def async_get(self, key):
            return self._entries.get(key)

    class _AreaRegistry:
        def __init__(self, entries):
            self._entries = dict(entries)

        def async_get_area(self, key):
            return self._entries.get(key)

    class _LabelRegistry(_Registry):
        pass

    core.HomeAssistant = HomeAssistant
    area_registry.async_get = lambda hass: _AreaRegistry(getattr(hass, "areas", {}))
    device_registry.async_get = lambda hass: _Registry(getattr(hass, "devices", {}))
    entity_registry.async_get = lambda hass: _Registry(getattr(hass, "entities", {}))
    label_registry.async_get = lambda hass: _LabelRegistry(getattr(hass, "labels", {}))

    helpers.area_registry = area_registry
    helpers.device_registry = device_registry
    helpers.entity_registry = entity_registry
    helpers.label_registry = label_registry

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.area_registry"] = area_registry
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.helpers.label_registry"] = label_registry


def _install_package_scaffold() -> None:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg

    helpers = types.ModuleType(f"{PKG}.helpers")
    helpers.__path__ = [str(INTEGRATION_ROOT / "helpers")]
    sys.modules[f"{PKG}.helpers"] = helpers


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_setup_assist_module():
    _install_homeassistant_stubs()
    _install_package_scaffold()
    return _load_module(f"{PKG}.helpers.setup_assist", INTEGRATION_ROOT / "helpers" / "setup_assist.py")


def test_setup_assist_suggests_area_room_level_and_labels_without_runtime_authority():
    setup_assist = _load_setup_assist_module()
    hass = SimpleNamespace(
        entities={
            "sensor.example_humidity": SimpleNamespace(
                area_id="bathroom",
                device_id="device-1",
                labels={"humidity-intelligence"},
            ),
        },
        devices={
            "device-1": SimpleNamespace(
                area_id=None,
                labels={"second-floor"},
            ),
        },
        areas={
            "bathroom": SimpleNamespace(
                name="Upstairs bathroom",
                labels={"wet-room"},
            ),
        },
        labels={
            "humidity-intelligence": SimpleNamespace(name="Humidity Intelligence"),
            "second-floor": SimpleNamespace(name="Second floor"),
            "wet-room": SimpleNamespace(name="Wet room"),
        },
    )

    suggestion = setup_assist.setup_assist_suggestion(hass, "sensor.example_humidity")

    assert suggestion.room == "Upstairs bathroom"
    assert suggestion.level == "level2"
    assert suggestion.labels == ("Humidity Intelligence", "Second floor", "Wet room")
    assert suggestion.runtime_authority is False
    assert suggestion.save_payload == {}


def test_setup_assist_prefers_entity_area_and_reports_conflicting_level_labels():
    setup_assist = _load_setup_assist_module()
    hass = SimpleNamespace(
        entities={
            "sensor.example_temperature": SimpleNamespace(
                area_id="ground_hall",
                device_id="device-1",
                labels={"level-two"},
            ),
        },
        devices={
            "device-1": SimpleNamespace(
                area_id="device_area",
                labels=set(),
            ),
        },
        areas={
            "ground_hall": SimpleNamespace(name="Ground hall", labels=set()),
            "device_area": SimpleNamespace(name="Second floor plant room", labels=set()),
        },
        labels={
            "level-two": SimpleNamespace(name="Level 2"),
        },
    )

    suggestion = setup_assist.setup_assist_suggestion(hass, "sensor.example_temperature")

    assert suggestion.room == "Ground hall"
    assert suggestion.level == ""
    assert "conflicting_level_hints" in suggestion.warnings


def test_setup_assist_inherits_parent_area_for_child_device():
    setup_assist = _load_setup_assist_module()
    hass = SimpleNamespace(
        entities={
            "sensor.example_humidity": SimpleNamespace(
                area_id=None,
                device_id="child-device",
                labels=set(),
            ),
        },
        devices={
            "child-device": SimpleNamespace(
                area_id=None,
                parent_device_id="parent-device",
                labels=set(),
            ),
            "parent-device": SimpleNamespace(
                area_id="upstairs_bathroom",
                labels=set(),
            ),
        },
        areas={
            "upstairs_bathroom": SimpleNamespace(
                name="Upstairs bathroom",
                labels=set(),
            ),
        },
        labels={},
    )

    suggestion = setup_assist.setup_assist_suggestion(hass, "sensor.example_humidity")

    assert suggestion.status == "available"
    assert suggestion.area_id == "upstairs_bathroom"
    assert suggestion.room == "Upstairs bathroom"
    assert suggestion.level == "level2"
    assert suggestion.runtime_authority is False
    assert suggestion.save_payload == {}


def test_setup_assist_parent_area_fallback_degrades_safely():
    setup_assist = _load_setup_assist_module()
    device_cases = (
        {
            "child-device": SimpleNamespace(
                area_id=None,
                parent_device_id="missing-parent",
                labels=set(),
            ),
        },
        {
            "child-device": SimpleNamespace(
                area_id=None,
                parent_device_id="parent-device",
                labels=set(),
            ),
            "parent-device": SimpleNamespace(
                area_id=None,
                labels=set(),
            ),
        },
        {
            "child-device": SimpleNamespace(
                area_id=None,
                parent_device_id="child-device",
                labels=set(),
            ),
        },
        {
            "child-device": SimpleNamespace(
                area_id=None,
                parent_device_id="parent-device",
                labels=set(),
            ),
            "parent-device": SimpleNamespace(
                area_id="unexpected_area",
                parent_device_id="child-device",
                labels=set(),
            ),
        },
        {
            "child-device": SimpleNamespace(
                area_id=None,
                labels=set(),
            ),
        },
    )

    for devices in device_cases:
        hass = SimpleNamespace(
            entities={
                "sensor.example_humidity": SimpleNamespace(
                    area_id=None,
                    device_id="child-device",
                    labels=set(),
                ),
            },
            devices=devices,
            areas={
                "unexpected_area": SimpleNamespace(
                    name="Unexpected area",
                    labels=set(),
                ),
            },
            labels={},
        )

        suggestion = setup_assist.setup_assist_suggestion(
            hass,
            "sensor.example_humidity",
        )

        assert suggestion.status == "no_metadata"
        assert suggestion.area_id == ""
        assert suggestion.room == ""
        assert suggestion.level == ""
        assert suggestion.runtime_authority is False
        assert suggestion.save_payload == {}


def test_setup_assist_parent_device_lookup_failure_degrades_safely():
    setup_assist = _load_setup_assist_module()

    child_device = SimpleNamespace(
        area_id=None,
        parent_device_id="parent-device",
        labels=set(),
    )

    class BrokenParentDeviceRegistry:
        def async_get(self, device_id):
            if device_id == "child-device":
                return child_device
            raise RuntimeError("parent lookup exploded")

    hass = SimpleNamespace(
        entities={
            "sensor.example_humidity": SimpleNamespace(
                area_id=None,
                device_id="child-device",
                labels=set(),
            ),
        },
        areas={},
        labels={},
    )
    with (
        mock.patch.object(
            setup_assist.dr,
            "async_get",
            return_value=BrokenParentDeviceRegistry(),
        ),
        mock.patch.object(setup_assist._LOGGER, "debug") as debug,
    ):
        suggestion = setup_assist.setup_assist_suggestion(
            hass,
            "sensor.example_humidity",
        )

    assert suggestion.status == "no_metadata"
    assert suggestion.area_id == ""
    assert suggestion.room == ""
    assert suggestion.runtime_authority is False
    assert suggestion.save_payload == {}
    debug.assert_called()


def test_setup_assist_degrades_when_metadata_is_missing_or_unsupported():
    setup_assist = _load_setup_assist_module()
    hass = SimpleNamespace(entities={}, devices={}, areas={}, labels={})

    missing = setup_assist.setup_assist_suggestion(hass, "sensor.not_registered")
    unsupported = setup_assist.unsupported_setup_assist_suggestion("label_registry_unavailable")

    assert missing.status == "not_found"
    assert missing.room == ""
    assert missing.labels == ()
    assert unsupported.status == "unsupported"
    assert unsupported.warnings == ("label_registry_unavailable",)


def test_setup_assist_logs_registry_failures_without_changing_fallback():
    setup_assist = _load_setup_assist_module()

    with (
        mock.patch.object(setup_assist.er, "async_get", side_effect=RuntimeError("registry exploded")),
        mock.patch.object(setup_assist._LOGGER, "debug") as debug,
    ):
        suggestion = setup_assist.setup_assist_suggestion(
            SimpleNamespace(),
            "sensor.example_humidity",
        )

    assert suggestion.status == "unsupported"
    assert suggestion.warnings == ("registry_lookup_failed",)
    debug.assert_called()


def test_setup_assist_entity_lookup_failure_is_not_reported_as_missing():
    setup_assist = _load_setup_assist_module()

    class BrokenEntityRegistry:
        def async_get(self, _entity_id):
            raise RuntimeError("entity lookup exploded")

    hass = SimpleNamespace(entities={}, devices={}, areas={}, labels={})
    with (
        mock.patch.object(setup_assist.er, "async_get", return_value=BrokenEntityRegistry()),
        mock.patch.object(setup_assist._LOGGER, "debug") as debug,
    ):
        suggestion = setup_assist.setup_assist_suggestion(
            hass,
            "sensor.example_humidity",
        )

    assert suggestion.status == "unsupported"
    assert suggestion.warnings == ("entity_lookup_failed",)
    debug.assert_called()


if __name__ == "__main__":
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for name, test in tests:
        test()
    print(f"{len(tests)} setup-assist sanity checks passed.")
