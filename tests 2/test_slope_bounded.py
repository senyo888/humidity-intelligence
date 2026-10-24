"""Bound event-driven slope work without losing the latest observation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from test_slope_sanity import _FakeHass, _FakeState, _load_slope_module


def test_same_minute_burst_retains_latest_real_observation_and_startup_seed():
    mod = _load_slope_module()
    tracker = mod.SlopeTracker()
    start = datetime(2026, 1, 1, 12)
    tracker.record('sensor.room_alpha_temperature', 20, start)
    assert tracker.get_slope('sensor.room_alpha_temperature') == 0.0
    for index in range(10000):
        stamp = start + timedelta(milliseconds=index)
        tracker.record('sensor.room_alpha_temperature', 20 + index / 10000, stamp)
    points = tracker._series['sensor.room_alpha_temperature']
    assert tracker.sample_count('sensor.room_alpha_temperature') == 2
    assert (points[-1].ts, points[-1].value) == (stamp, 20.9999)
    assert points[0].ts == start - timedelta(minutes=5)
    assert tracker.get_slope('sensor.room_alpha_temperature') > 0


def test_bursts_keep_hour_coverage_and_known_linear_trend_with_at_most_61_points():
    mod = _load_slope_module()
    tracker = mod.SlopeTracker()
    start = datetime(2026, 1, 1, 12)
    for minute in range(65):
        for event in range(100):
            stamp = start + timedelta(minutes=minute, milliseconds=event * 500)
            tracker.record('sensor.room_alpha_temperature', 20 + (stamp - start).total_seconds() / 1800, stamp)
            assert tracker.sample_count('sensor.room_alpha_temperature') <= 61
    points = tracker._series['sensor.room_alpha_temperature']
    assert len(points) == 61
    assert points[0].ts == stamp - timedelta(hours=1)
    assert points[-1].ts == stamp
    assert tracker.get_slope('sensor.room_alpha_temperature') == 2.0


def test_regular_five_minute_samples_keep_constant_linear_and_cutoff_semantics():
    mod = _load_slope_module()
    tracker = mod.SlopeTracker()
    start = datetime(2026, 1, 1, 12)
    for minutes in range(0, 66, 5):
        stamp = start + timedelta(minutes=minutes)
        tracker.record('sensor.room_alpha_temperature', 20 + minutes / 30, stamp)
        tracker.record('sensor.room_beta_temperature', 18, stamp)
    assert tracker.get_slope('sensor.room_alpha_temperature') == 2.0
    assert tracker.get_slope('sensor.room_beta_temperature') == 0.0
    assert tracker.sample_count('sensor.room_alpha_temperature') == 13
    assert tracker._series['sensor.room_alpha_temperature'][0].ts == start + timedelta(minutes=5)


def test_minute_boundaries_use_actual_times_and_long_gaps_do_not_fabricate_history():
    mod = _load_slope_module()
    tracker = mod.SlopeTracker()
    start = datetime(2026, 1, 1, 12, 0, 59, 999999)
    entity = 'sensor.room_alpha_temperature'
    tracker.record(entity, 20, start)
    tracker.record(entity, 21, start + timedelta(microseconds=1))
    assert tracker.sample_count(entity) == 3
    assert tracker._series[entity][-1].ts == start + timedelta(microseconds=1)
    tracker.record(entity, 22, start + timedelta(hours=2))
    assert tracker.sample_count(entity) == 1
    assert tracker.get_slope(entity) is None
    tracker.record(entity, 23, start + timedelta(hours=2))
    assert tracker.sample_count(entity) == 1
    assert tracker.get_slope(entity) is None


def test_events_refresh_only_their_source_and_periodic_sampling_and_unload_remain(monkeypatch):
    mod = _load_slope_module()
    callbacks = {}
    cancelled = []
    def track_state(hass, sources, callback):
        callbacks['event'] = callback
        return lambda: cancelled.append('state')
    def track_periodic(hass, callback, interval):
        assert interval == timedelta(minutes=5)
        callbacks['periodic'] = callback
        return lambda: cancelled.append('periodic')
    monkeypatch.setattr(mod, 'async_track_state_change_event', track_state)
    monkeypatch.setattr(mod, 'async_track_time_interval', track_periodic)
    class Clock:
        value = datetime(2026, 1, 1, 12)
        @classmethod
        def now(cls): return cls.value
    monkeypatch.setattr(mod, 'datetime', Clock)
    sources = ['sensor.room_alpha_temperature', 'sensor.room_beta_temperature']
    entry = SimpleNamespace(entry_id='bounded_test', data={'slope': {'mode': 'hi_calculates', 'source_entities': sources}}, options={})
    hass = _FakeHass({source: _FakeState('20', {'unit_of_measurement': '°C'}) for source in sources})
    sensors, _, _ = mod.build_slope_entities(hass, entry)
    writes = dict.fromkeys(sources, 0)
    def write(source): writes[source] += 1
    for sensor in sensors:
        sensor.async_write_ha_state = lambda source=sensor._source: write(source)
    async def burst():
        for index in range(1000):
            Clock.value += timedelta(milliseconds=1)
            hass.states._values[sources[0]] = _FakeState(str(20 + index / 1000), {'unit_of_measurement': '°C'})
            await callbacks['event'](SimpleNamespace(data={'entity_id': sources[0]}))
    asyncio.run(burst())
    assert writes == {sources[0]: 1000, sources[1]: 0}
    assert sensors[0]._attr_native_value > 0
    assert sensors[0]._attr_extra_state_attributes['sample_count'] == 2
    for value in ['unknown', 'unavailable', 'nonnumeric', 'NaN', 'inf']:
        hass.states._values[sources[0]] = _FakeState(value, {'unit_of_measurement': '°C'})
        asyncio.run(callbacks['event'](SimpleNamespace(data={'entity_id': sources[0]})))
    asyncio.run(callbacks['event'](SimpleNamespace(data={'entity_id': 'sensor.unmapped_temperature'})))
    assert writes == {sources[0]: 1000, sources[1]: 0}
    Clock.value += timedelta(minutes=5)
    hass.states._values[sources[0]] = _FakeState('68', {'unit_of_measurement': '°F'})
    asyncio.run(callbacks['periodic'](Clock.value))
    assert writes == {sources[0]: 1001, sources[1]: 1}
    tracker = hass.data[mod.DOMAIN][entry.entry_id]['slope_tracker']
    assert tracker._series[sources[0]][-1].value == pytest.approx(20)
    assert tracker.sample_count(sources[1]) == 3
    hass.data[mod.DOMAIN][entry.entry_id]['slope_unsub']()
    assert cancelled == ['state', 'periodic']


def test_provided_mode_and_options_precedence_do_not_create_a_tracker():
    mod = _load_slope_module()
    source, provided = 'sensor.room_alpha_temperature', 'sensor.room_alpha_slope'
    hass = _FakeHass({source: _FakeState('20')})
    entry = SimpleNamespace(entry_id='provided_test', data={'slope': {'mode': 'hi_calculates', 'source_entities': [source]}}, options={'slope': {'mode': mod.SLOPE_MODE_PROVIDED, 'source_entities': [source], 'provided_sensors': [provided]}})
    assert mod.build_slope_entities(hass, entry) == ([], [provided], {source: provided})
    assert hass.data == {}
