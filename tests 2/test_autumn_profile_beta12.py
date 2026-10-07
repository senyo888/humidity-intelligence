"""Autumn target boundaries and their real runtime consumers."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    ENTRY_ID,
    INTEGRATION_ROOT,
    _FakeHass,
    _FakeState,
    _find_sensor,
    _load_core_module,
    _load_module,
    _load_target_modules,
    _wrap_async_method,
)


@pytest.fixture
def seasonal():
    return _load_module(
        "hi_autumn_profile_test", INTEGRATION_ROOT / "helpers" / "seasonal.py"
    )


@pytest.mark.parametrize("month", [9, 10, 11])
@pytest.mark.parametrize("config", [{}, {"target_profile": "auto"}])
def test_automatic_autumn_uses_new_band_with_original_high_risk(seasonal, month, config):
    profile = seasonal.resolve_target_profile(config, datetime(2026, month, 15))
    assert (profile.key, profile.low, profile.high, profile.high_risk) == (
        "autumn", 50.0, 60.0, 64.0
    )


@pytest.mark.parametrize("key", ["target_profile", "target_profile_mode"])
def test_explicit_autumn_and_legacy_mode_work_outside_autumn(seasonal, key):
    profile = seasonal.resolve_target_profile({key: "autumn"}, datetime(2026, 1, 15))
    assert (profile.low, profile.high, profile.high_risk) == (50.0, 60.0, 64.0)


@pytest.mark.parametrize(
    "month,key,bounds",
    [(1, "winter", (45.0, 55.0, 62.0)),
     (4, "spring", (47.0, 58.0, 64.0)),
     (7, "summer", (51.0, 60.0, 68.0))],
)
def test_other_seasons_keep_their_own_targets(seasonal, month, key, bounds):
    automatic = seasonal.resolve_target_profile({}, datetime(2026, month, 15))
    explicit = seasonal.resolve_target_profile({"target_profile": key}, datetime(2026, 10, 15))
    assert automatic == explicit
    assert (automatic.low, automatic.high, automatic.high_risk) == bounds


@pytest.mark.parametrize(
    "custom",
    [{"custom_target_low": 47, "custom_target_high": 58},
     {"target_custom_low": 47, "target_custom_high": 58},
     {"target_custom": {"low": 47, "high": 58}}],
)
def test_explicit_old_band_custom_values_and_aliases_are_not_migrated(seasonal, custom):
    config = {"target_profile": "custom", **custom}
    original = deepcopy(config)
    profile = seasonal.resolve_target_profile(config, datetime(2026, 10, 15))
    assert (profile.key, profile.low, profile.high, profile.high_risk) == (
        "custom", 47.0, 58.0, 66.2
    )
    assert config == original


@pytest.mark.parametrize(
    "humidity,expected",
    [(None, "unknown"), (49.9, "below_target"), (50.0, "in_target"),
     (60.0, "in_target"), (60.1, "above_target"), (63.9, "above_target"),
     (64.0, "high_risk")],
)
def test_humidity_classification_uses_inclusive_target_and_unchanged_danger(seasonal, humidity, expected):
    assert seasonal.humidity_state(humidity, seasonal.SEASONAL_PROFILES["autumn"]) == expected


@pytest.mark.parametrize(
    "humidity,spread,expected",
    [(62.0, 2.3, "Risk"), (63.0, 2.3, "Danger"),
     (61.0, 4.1, "Watch"), (62.9, 4.1, "Watch"), (63.0, 4.1, "Risk"),
     (63.9, 5.0, "Watch"), (64.0, 5.0, "Risk"),
     (67.9, 4.1, "Risk"), (68.0, 4.1, "Danger"),
     (None, 2.3, "Unknown"), (64.0, None, "Unknown")],
)
def test_mould_excess_follows_new_high_without_weakening_high_risk_floor(seasonal, humidity, spread, expected):
    assert seasonal.mould_risk(humidity, spread, seasonal.SEASONAL_PROFILES["autumn"]) == expected


@pytest.mark.parametrize(
    "spread,expected", [(2.3, "Danger"), (4.3, "Risk"), (6.3, "Watch"), (6.31, "OK")]
)
def test_autumn_condensation_boundaries_remain_unchanged(seasonal, spread, expected):
    assert seasonal.condensation_risk(spread, seasonal.SEASONAL_PROFILES["autumn"]) == expected


def _entry(*, options=None, band_adjust=0, recovery=None):
    humidifier = {"enabled": True, "outputs": ["humidifier.example_output"], "band_adjust": band_adjust}
    if recovery is not None:
        humidifier["recovery_in_band"] = recovery
    return SimpleNamespace(
        entry_id=ENTRY_ID,
        options=options or {},
        data={
            "target_profile": "autumn",
            "telemetry": [
                {"entity_id": "sensor.example_humidity", "sensor_type": "humidity", "level": "level1", "room": "Example room"},
                {"entity_id": "sensor.example_temperature", "sensor_type": "temperature", "level": "level1", "room": "Example room"},
                {"entity_id": "sensor.example_co", "sensor_type": "co", "level": "level1", "room": "Example room"},
            ],
            "zones": {"zone1": {
                "enabled": True, "level": "level1", "rooms": ["Example room"],
                "outputs": ["fan.example_ventilation"], "triggers": ["humidity_high"],
                "thresholds": {"humidity_high": 5},
            }},
            "alerts": [], "aq": {}, "humidifiers": {"level1": humidifier},
        },
    )


def _states(humidity, *, co=0, output="off"):
    return {
        "sensor.example_humidity": _FakeState(humidity),
        "sensor.example_temperature": _FakeState(21),
        "sensor.example_co": _FakeState(co),
        "humidifier.example_output": _FakeState(output),
    }


@pytest.mark.parametrize(
    "data,options,expected",
    [({"target_profile": "autumn"},
      {"target_profile": "custom", "custom_target_low": 47, "custom_target_high": 58},
      (47.0, 58.0, 66.2)),
     ({"target_profile": "custom", "custom_target_low": 40, "custom_target_high": 70},
      {"target_profile": "autumn"}, (50.0, 60.0, 64.0))],
)
def test_runtime_and_target_entities_use_options_precedence(data, options, expected):
    engine_mod, _ = _load_target_modules()
    entry = _entry(options=options)
    entry.data.update(data)
    hass = _FakeHass(entry, _states(55))
    engine = engine_mod.HIAutomationEngine(hass, entry)
    profile = engine._active_target_profile()
    assert (profile.low, profile.high, profile.high_risk) == expected

    core = _load_core_module()
    sensors, _, _ = core.build_entities(hass, entry)
    for scope in ("house", "level1"):
        low = _find_sensor(sensors, f"{scope}_target_low")
        high = _find_sensor(sensors, f"{scope}_target_high")
        assert (low._attr_native_value, high._attr_native_value) == expected[:2]
        assert high._attr_extra_state_attributes["high_risk"] == expected[2]


@pytest.mark.parametrize(
    "band_adjust,recovery,options,start,stop,high",
    [(0, None, {}, 50, 53, 60), (2, None, {}, 52, 55, 62),
     (0, 8, {}, 50, 58, 60),
     (0, None, {"target_profile": "custom", "custom_target_low": 47, "custom_target_high": 58}, 47, 50, 58)],
)
def test_humidifier_dispatch_and_hysteresis_follow_resolved_targets(band_adjust, recovery, options, start, stop, high):
    async def run():
        engine_mod, _ = _load_target_modules()
        entry = _entry(options=options, band_adjust=band_adjust, recovery=recovery)
        hass = _FakeHass(entry, _states(start + 0.1))
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            assert await engine._handle_humidifiers() == []
            hass.states._values["sensor.example_humidity"] = _FakeState(start)
            active = await engine._handle_humidifiers()
            assert len(active) == 1
            assert (active[0]["low"], active[0]["high"], active[0]["recovery_off"]) == (start, high, stop)
            assert any(domain == "humidifier" and service == "turn_on" for domain, service, _, _ in hass.services.calls)

            hass.states._values["humidifier.example_output"] = _FakeState("on")
            hass.states._values["sensor.example_humidity"] = _FakeState(stop - 0.1)
            assert len(await engine._handle_humidifiers()) == 1
            hass.states._values["sensor.example_humidity"] = _FakeState(stop)
            assert await engine._handle_humidifiers() == []
            assert any(domain == "humidifier" and service == "turn_off" for domain, service, _, _ in hass.services.calls)
            helper = hass.data["humidity_intelligence"][ENTRY_ID]["hi_input_booleans"]["air_downstairs_humidifier_active"]
            assert helper.is_on is False
        finally:
            await engine.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("humidity", ["unknown", "unavailable"])
def test_autumn_missing_humidity_cannot_request_humidification(humidity):
    async def run():
        engine_mod, _ = _load_target_modules()
        entry = _entry()
        hass = _FakeHass(entry, _states(humidity))
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            assert await engine._handle_humidifiers() == []
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            lane = runtime["humidifier_status"]["lanes"]["level1"]
            assert lane["environmental_state"] == "unknown"
            assert lane["failure_category"] == "telemetry_unavailable"
            assert not any(
                domain == "humidifier" and service == "turn_on"
                for domain, service, _, _ in hass.services.calls
            )
        finally:
            await engine.async_stop()

    asyncio.run(run())


def test_humidity_danger_uses_profile_64_and_resolved_zone_not_legacy_threshold():
    async def run():
        engine_mod, _ = _load_target_modules()
        entry = _entry()
        alert = {"enabled": True, "trigger_type": "humidity_danger", "room": "Example room", "threshold": 99}
        entry.data["alerts"] = [alert]
        hass = _FakeHass(entry, _states(63.9))
        engine = engine_mod.HIAutomationEngine(hass, entry)
        try:
            assert engine._alert_detail(0, alert) is None
            hass.states._values["sensor.example_humidity"] = _FakeState(64)
            detail = engine._alert_detail(0, alert)
            assert detail["threshold"] == 64
            assert detail["zone_key"] == "zone1"
            await engine._evaluate()
            runtime = hass.data["humidity_intelligence"][ENTRY_ID]
            assert runtime["runtime_mode"] == "alert"
            fan_commands = [(data["entity_id"], data["percentage"]) for domain, service, data, _ in hass.services.calls if domain == "fan" and service == "set_percentage"]
            assert fan_commands == [("fan.example_ventilation", 100)]
        finally:
            await engine.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("manual", [False, True])
def test_autumn_humidity_danger_cannot_preempt_co_even_during_manual_handover(manual):
    async def run():
        engine_mod, _ = _load_target_modules()
        entry = _entry()
        entry.data["alerts"] = [{"enabled": True, "trigger_type": "humidity_danger", "room": "Example room"}]
        hass = _FakeHass(entry, _states(70, co=16))
        runtime = hass.data["humidity_intelligence"][ENTRY_ID]
        runtime["hi_input_booleans"]["air_control_manual_override"].is_on = manual
        engine = engine_mod.HIAutomationEngine(hass, entry)
        trace = []
        for method in ("_handle_alerts", "_handle_humidifiers", "_handle_zone_by_key", "_handle_aq"):
            _wrap_async_method(engine, method, trace)
        try:
            await engine._evaluate()
            assert trace == []
            assert runtime["runtime_mode"] == "co_emergency"
            fan_commands = [(data["entity_id"], data["percentage"]) for domain, service, data, _ in hass.services.calls if domain == "fan" and service == "set_percentage"]
            assert fan_commands == [("fan.example_ventilation", 100)]
            assert not any(domain == "humidifier" and service == "turn_on" for domain, service, _, _ in hass.services.calls)
        finally:
            await engine.async_stop()

    asyncio.run(run())
