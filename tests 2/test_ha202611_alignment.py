"""Unit, evidence and lifecycle regressions exposed by HA 2026.11."""
import asyncio
import importlib
import time
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    PKG, ENTRY_ID, _FakeHass, _FakeState, _base_entry_data, _load_target_modules,
    _load_core_module, _load_integration_init_module, _load_services_module,
)


def environment(readings):
    engine_mod, _ = _load_target_modules()
    data = _base_entry_data()
    data["telemetry"] = [
        {"entity_id": entity, "sensor_type": kind, "level": "level1", "room": entity}
        for entity, kind, _value, _unit in readings
    ]
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=data, options={})
    hass = _FakeHass(entry, {entity: _FakeState(value, {"unit_of_measurement": unit})
                           for entity, _kind, value, unit in readings})
    return engine_mod, engine_mod.HIAutomationEngine(hass, entry), hass, entry


@pytest.mark.parametrize("kind,raw,unit,expected", [
    ("voc", .6, "ppm", 600), ("voc", 600, "ppb", 600),
    ("co", 14000, "ppb", 14), ("co2", 1200000, "ppb", 1200),
    ("pm25", .035, "mg/m³", 35), ("pm25", 35, "μg/m^3", 35),
    ("iaq", 75, None, 75), ("iaq", 75, "index", 75),
])
def test_shared_parser_canonical_equivalence(kind, raw, unit, expected):
    environment([])
    aq = importlib.import_module(f"{PKG}.helpers.air_quality")
    assert aq.parse_aq_value(kind, raw, unit) == (expected, None)


@pytest.mark.parametrize("value,unit", [
    (15, None), (15, ""), (15, "µg/m³"), (15, "index"),
    (True, "ppm"), (-1, "ppm"), ("inf", "ppm"), ("nan", "ppm"),
    ("14 ppm", "ppm"), ("error 20", "ppm"), (None, "ppm"),
])
def test_invalid_co_is_not_numeric_or_clear(value, unit):
    _mod, engine, hass, entry = environment([("sensor.example_co", "co", value, unit)])
    aq = importlib.import_module(f"{PKG}.helpers.air_quality")
    assert aq.parse_aq_value("co", value, unit)[0] is None
    assert not engine._co_emergency_triggered()
    engine._co_emergency_active = True
    engine._co_below_since = time.monotonic() - 600
    assert not engine._co_clear_ready()
    assert engine._co_below_since is None
    assert engine._co_emergency_triggered()
    summary = aq.aq_source_summary(hass, entry.data)
    assert not summary["complete"]
    assert "sensor.example_co" not in str(summary)


def test_conversion_overflow_and_dimensions():
    environment([])
    aq = importlib.import_module(f"{PKG}.helpers.air_quality")
    assert aq.parse_aq_value("voc", 1e308, "ppm")[0] is None
    assert aq.parse_aq_value("voc", 1000, "µg/m³")[0] is None
    assert aq.parse_aq_value("voc", 100, "index")[0] is None
    assert not aq.aq_source_summary(SimpleNamespace(states={}), {})["complete"]


def test_mixed_units_runtime_aggregate_and_stability_agree():
    readings = [("sensor.example_voc_a", "voc", .6, "ppm"),
                ("sensor.example_voc_b", "voc", 700, "ppb")]
    for ordered in (readings, list(reversed(readings))):
        _mod, engine, hass, entry = environment(ordered)
        cfg = {"enabled": True, "triggers": ["voc_bad"], "thresholds": {"voc_bad": 650}}
        entry.data["aq"] = {"level1": cfg}
        assert engine._level_avg("voc", "level1") == 650
        assert engine._aq_trigger_details("level1", cfg)
        core = _load_core_module()
        computations = core._CoreComputations(hass, entry, entry.data["telemetry"])
        assert computations._compute_house_voc_avg()[0] == 650
        aq = importlib.import_module(f"{PKG}.helpers.air_quality")
        evidence = aq.capture_configured_aq_evidence(hass, entry.data)
        assert evidence["bad_trigger_count"] == 1
        assert evidence["available_source_count"] == 2
        assert evidence["unit_invalid_source_count"] == 0


def test_threshold_uses_unrounded_canonical_value():
    _mod, engine, _hass, _entry = environment([("sensor.example_voc", "voc", .59996, "ppm")])
    assert not engine._aq_trigger_details("level1", {
        "triggers": ["voc_bad"], "thresholds": {"voc_bad": 600},
    })


def test_co_activation_and_complete_clearance():
    async def run():
        _mod, engine, hass, _entry = environment([
            ("sensor.example_co_a", "co", 15000, "ppb"),
            ("sensor.example_co_b", "co", "unavailable", "ppm"),
        ])
        assert engine._co_emergency_triggered()
        hass.states._values["sensor.example_co_a"] = _FakeState(9, {"unit_of_measurement": "ppm"})
        engine._co_below_since = time.monotonic() - 180
        assert not engine._co_clear_ready()
        assert engine._co_below_since is None
        hass.states._values["sensor.example_co_b"] = _FakeState(9, {"unit_of_measurement": "ppm"})
        assert not engine._co_clear_ready()
        engine._co_below_since = time.monotonic() - 180
        assert engine._co_clear_ready()
        hass.states._values["sensor.example_co_b"] = _FakeState(10, {"unit_of_measurement": "ppm"})
        assert not engine._co_clear_ready()
        assert engine._co_below_since is None
        engine.telemetry = []
        assert not engine._co_clear_ready()
        await engine.async_stop()
    asyncio.run(run())


def test_co_interruption_is_not_lost_when_evaluations_coalesce():
    async def run():
        _mod, engine, _hass, _entry = environment([("sensor.example_co", "co", 1, "ppm")])
        engine._co_emergency_active = True
        engine._co_below_since = time.monotonic() - 180
        lock = engine._get_evaluate_lock()
        async with lock:
            await engine._handle_change(SimpleNamespace(data={
                "entity_id": "sensor.example_co", "new_state": _FakeState("unavailable"),
            }))
            await engine._handle_change(SimpleNamespace(data={
                "entity_id": "sensor.example_co", "new_state": _FakeState(1, {"unit_of_measurement": "ppm"}),
            }))
        assert engine._evaluate_pending
        assert engine._co_below_since is None
        assert not engine._co_clear_ready()
        assert engine._co_emergency_active
        await engine.async_stop()
    asyncio.run(run())


def test_clear_deadline_finishes_evaluation_and_reset_invalidates_old_deadline():
    async def run():
        _mod, engine, _hass, _entry = environment([("sensor.example_co", "co", 1, "ppm")])
        completed = []
        async def evaluate():
            engine._cancel_co_clear_recheck()
            await asyncio.sleep(0)
            completed.append(True)
        engine.async_request_evaluate = evaluate
        engine._co_below_since = time.monotonic() - 180
        engine._schedule_co_clear_recheck(time.monotonic())
        task = engine._co_clear_recheck_task
        await task
        assert completed == [True]
        completed.clear()
        engine._co_below_since = time.monotonic() - 180
        engine._schedule_co_clear_recheck(time.monotonic())
        obsolete = engine._co_clear_recheck_task
        engine._reset_co_clear_hold()
        await asyncio.gather(obsolete, return_exceptions=True)
        assert completed == []
        await engine.async_stop()
    asyncio.run(run())


def test_failed_platform_unload_keeps_runtime_custody():
    async def run():
        _load_services_module()
        mod = _load_integration_init_module()
        data = {"output_observer": SimpleNamespace(active=True), "sentinel": object()}
        hass = SimpleNamespace(data={"humidity_intelligence": {ENTRY_ID: data}})
        async def failed(*_args):
            return False
        hass.config_entries = SimpleNamespace(async_unload_platforms=failed)
        assert await mod.async_unload_entry(hass, SimpleNamespace(entry_id=ENTRY_ID)) is False
        assert hass.data["humidity_intelligence"][ENTRY_ID] is data
        assert "output_observer" in data
    asyncio.run(run())


def test_co_hold_uses_continuous_monotonic_boundary(monkeypatch):
    async def run():
        mod, engine, _hass, _entry = environment([('sensor.example_co', 'co', 9, 'ppm')])
        now = [1000.0]
        monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: now[0]))
        monkeypatch.setattr(mod, 'datetime', SimpleNamespace(now=lambda: (_ for _ in ()).throw(AssertionError('wall clock used'))))
        assert not engine._co_clear_ready()
        now[0] += 119.999
        assert not engine._co_clear_ready()
        now[0] += .001
        assert engine._co_clear_ready()
        await engine.async_stop()
    asyncio.run(run())


def test_diagnostics_export_contains_bounded_aq_quality():
    _mod, _engine, hass, entry = environment([('sensor.example_private_voc', 'voc', 600, 'index')])
    services = _load_services_module()
    summary = services._build_diagnostics_summary(hass, entry.data, {}, {}, {})
    exported = services._support_safe_diagnostics_summary(summary)
    assert exported['aq_inputs']['by_type']['voc']['unit_unsupported'] == 1
    assert 'sensor.example_private_voc' not in str(exported['aq_inputs'])
    assert not exported['aq_inputs']['complete']


def test_aggregate_units_and_voc_reason_match_canonical_readings():
    _mod, engine, hass, entry = environment([
        ('sensor.example_voc', 'voc', .6, 'ppm'),
        ('sensor.example_co', 'co', 14000, 'ppb'),
        ('sensor.example_pm25', 'pm25', .035, 'mg/m³'),
    ])
    core = _load_core_module()
    sensors = core._CoreComputations(hass, entry, entry.data['telemetry']).build_sensors()
    for sensor in sensors:
        for kind, unit in [('voc', 'ppb'), ('co', 'ppm'), ('pm25', 'µg/m³')]:
            if sensor._attr_unique_id.endswith(kind + '_average'):
                assert sensor._attr_native_unit_of_measurement == unit
    _details, facts = engine._aq_trigger_evaluation('level1', {'triggers': ['voc_bad'], 'thresholds': {'voc_bad': 600}})
    assert facts[0].unit == 'ppb'
    assert '600 ppb' in engine._trigger_display_line('aq', facts[0]).text


def test_unmapped_source_cannot_borrow_another_rooms_slope():
    _mod, _engine, hass, entry = environment([
        ('sensor.example_temp_a', 'temperature', 20, '°C'),
        ('sensor.example_temp_b', 'temperature', 21, '°C'),
    ])
    entry.data['telemetry'][0]['room'] = 'Room A'
    entry.data['telemetry'][1]['room'] = 'Room B'
    core = _load_core_module()
    for mode in ('hi_calculates', 'user_provided'):
        entry.data['slope'] = {'mode': mode}
        hass.data['humidity_intelligence'][ENTRY_ID]['slope_map'] = {
            'sensor.example_temp_b': 'sensor.room_a_old_slope',
        }
        computations = core._CoreComputations(hass, entry, entry.data['telemetry'])
        assert computations._slope_entity_for_room('Room A') is None
        assert computations._slope_entity_for_room('Room B') == 'sensor.room_a_old_slope'
    assert computations._slope_entity_for_room('room_a') is None


@pytest.mark.parametrize('route', ['/local/community/', '/hacsfiles/'])
def test_frontend_resources_do_not_require_package_manager_files(route):
    environment([])
    frontend = importlib.import_module(f'{PKG}.helpers.frontend_dependencies')
    status = frontend.frontend_dependency_status_from_urls([
        route + 'button-card/button-card.js',
        route + 'lovelace-card-mod/card-mod.js',
    ])
    assert status['button-card']['detected']
    assert status['mod-card']['detected']
    assert not status['apexcharts-card']['detected']
    assert 'HACS:' not in frontend.render_dependency_status(status)


def test_successful_unload_releases_custody_after_platforms(monkeypatch):
    async def run():
        _load_services_module()
        mod = _load_integration_init_module()
        calls = []
        async def unload(*_args):
            calls.append('platforms')
            return True
        async def stop_automations(*_args):
            calls.append('automations')
        async def stop_observer():
            calls.append('observer')
        async def unregister(*_args):
            calls.append('services')
        monkeypatch.setattr(mod, 'async_unload_automations', stop_automations)
        monkeypatch.setattr(mod, 'async_unregister_services', unregister)
        data = {'output_observer': SimpleNamespace(active=True, async_stop=stop_observer),
                'core_unsub': lambda: calls.append('listener')}
        hass = SimpleNamespace(data={'humidity_intelligence': {ENTRY_ID: data}},
                               config_entries=SimpleNamespace(async_unload_platforms=unload))
        assert await mod.async_unload_entry(hass, SimpleNamespace(entry_id=ENTRY_ID))
        assert calls == ['platforms', 'automations', 'observer', 'listener', 'services']
        assert ENTRY_ID not in hass.data['humidity_intelligence']
    asyncio.run(run())
