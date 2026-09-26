"""Receiving-integration lifecycle and native diagnostics acceptance checks."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import _load_integration_init_module
from test_stability_scheduler import DOMAIN, _load_sensor_module
from test_stability_score import _load_stability_module, _sample


@pytest.mark.parametrize("delay_seconds,expected_count", [(60, 1), (60.001, 0)])
def test_scheduled_observation_grace_is_inclusive_at_sixty_seconds(
    delay_seconds, expected_count,
):
    registrations, captures = {}, []
    sensor, _, _ = _load_sensor_module(registrations, captures, [])
    setup_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    sensor._utc_now = lambda: setup_at
    entry = SimpleNamespace(
        entry_id="entry_grace", data={"alert_only_mode": True}, options={},
        async_on_unload=lambda _callback: None,
    )
    hass = SimpleNamespace(data={})
    asyncio.run(sensor.async_setup_entry(hass, entry, lambda *_a, **_k: None))
    scheduled = registrations["points"][0]["point_in_time"]
    sensor._utc_now = lambda: scheduled + timedelta(seconds=delay_seconds)
    registrations["points"][0]["callback"](scheduled)
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert len(captures) == expected_count
    assert len(runtime.get("movement_recorded_at", [])) == expected_count
    if expected_count:
        assert runtime["movement_capture_available"] == [True]
    else:
        assert runtime["published_updates"][-1]["history_available"] is False
        assert "capture_available" not in runtime["published_updates"][-1]
    assert runtime["stability_sampling"]["missed_buckets_since_setup"] == 1 - expected_count
    assert registrations["points"][-1]["point_in_time"] == scheduled + timedelta(minutes=10)


def test_entry_unload_discards_history_and_reload_starts_without_backfill():
    integration = _load_integration_init_module()
    registrations = {}
    sensor, _, _ = _load_sensor_module(registrations, [], [])
    stability = _load_stability_module()
    sensor.StabilitySnapshotRing = stability.StabilitySnapshotRing
    setup_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    sensor._utc_now = lambda: setup_at
    entry = SimpleNamespace(
        entry_id="entry_reload", data={"alert_only_mode": True}, options={},
        async_on_unload=lambda _callback: None,
    )

    async def unload_platforms(*_args):
        return True

    hass = SimpleNamespace(
        data={}, config_entries=SimpleNamespace(async_unload_platforms=unload_platforms),
        services=SimpleNamespace(has_service=lambda *_args: False),
    )
    asyncio.run(sensor.async_setup_entry(hass, entry, lambda *_a, **_k: None))
    old_runtime = hass.data[DOMAIN][entry.entry_id]
    for index in range(432):
        old_runtime["stability_snapshot_ring"].add(_sample(stability, index))
    old_runtime["stability_movement_last_score"] = 91
    old_runtime["stability_score_movement"] = {"end_position_degrees": 180}
    old_callback = registrations["points"][0]

    assert asyncio.run(integration.async_unload_entry(hass, entry)) is True
    assert entry.entry_id not in hass.data[DOMAIN]
    assert old_callback["cancelled"] is True
    assert old_runtime["stability_sampling"]["scheduler_active"] is False

    sensor._utc_now = lambda: setup_at + timedelta(hours=2)
    asyncio.run(sensor.async_setup_entry(hass, entry, lambda *_a, **_k: None))
    new_runtime = hass.data[DOMAIN][entry.entry_id]
    assert new_runtime is not old_runtime
    assert new_runtime["stability_snapshot_ring"].samples() == []
    assert "stability_movement_last_score" not in new_runtime
    assert "stability_score_movement" not in new_runtime
    assert new_runtime["stability_sampling"]["last_capture_status"] == "pending"
    assert registrations["points"][-1]["point_in_time"] == setup_at + timedelta(hours=2, minutes=10)
    old_callback["callback"](old_callback["point_in_time"])
    assert new_runtime["stability_snapshot_ring"].samples() == []
    assert len(registrations["points"]) == 2
