"""Visual-alert cancellation, lock custody and Manual handover regressions."""
import asyncio
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    ENTRY_ID, _FakeHass, _FakeState, _FlashServiceRegistry, _base_entry_data,
    _load_integration_init_module, _load_services_module, _load_target_modules,
)


LIGHT = "light.example_alert"
OTHER = "light.example_other"
ATTRS = {"supported_color_modes": ["rgb"], "brightness": 77, "rgb_color": (1, 2, 3)}
IDENTITY = ("example", "level1", "humidity")


def environment(initial="on", lights=(LIGHT,)):
    engine_mod, _ = _load_target_modules()
    services = _load_services_module()
    engine_mod.async_flash_lights_for_alert = services.async_flash_lights_for_alert
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    hass = _FakeHass(entry, {light: _FakeState(initial, dict(ATTRS)) for light in lights})
    hass.services = _FlashServiceRegistry(hass.states)
    hass.services.async_remove = lambda domain, name: hass.services.handlers.pop((domain, name), None)
    engine = engine_mod.HIAutomationEngine(hass, entry)
    hass.data[services.DOMAIN][ENTRY_ID]["automation_engine"] = engine
    return services, engine, hass, entry


def suspend_phase(monkeypatch, phase):
    paused = asyncio.Event()
    original_sleep = asyncio.sleep
    count = 0

    async def sleep(delay):
        nonlocal count
        if delay == 0.5:
            count += 1
            if count == phase:
                paused.set()
                await asyncio.Event().wait()
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return paused, original_sleep


def worker(engine, lights=(LIGHT,)):
    engine._visual_alert_active = {IDENTITY}
    task = asyncio.create_task(engine._visual_alert_loop(
        IDENTITY, {"visual_alert": {"lights": list(lights), "flash_mode": "red"}},
    ))
    engine._visual_alert_tasks[IDENTITY] = task
    return task


def assert_released(services, hass, lights=(LIGHT,)):
    assert all(not lock.locked() for lock in services._light_flash_locks(hass, list(lights)))
    assert not [task for task in asyncio.all_tasks()
                if task.get_name() == "hi-flash-restore" and not task.done()]


@pytest.mark.parametrize("initial", ["on", "off"])
@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("route", ["helper", "stop", "clear", "unload"])
def test_cancelled_flash_restores_before_custody_is_released(monkeypatch, initial, phase, route):
    async def run():
        services, engine, hass, entry = environment(initial)
        paused, _ = suspend_phase(monkeypatch, phase)
        if route == "helper":
            task = asyncio.create_task(services.async_flash_lights_for_alert(
                hass, lights=[LIGHT], flash_count=1,
            ))
        else:
            task = worker(engine)
        await asyncio.wait_for(paused.wait(), 1)
        if route == "helper":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif route == "stop":
            await engine.async_stop()
        elif route == "clear":
            await engine._sync_visual_alert_tasks([])
        else:
            integration = _load_integration_init_module()
            async def unload_platforms(*_args):
                return True
            hass.config_entries.async_unload_platforms = unload_platforms
            assert await integration.async_unload_entry(hass, entry)
            assert ENTRY_ID not in hass.data[services.DOMAIN]
        assert task.done()
        state = hass.states.get(LIGHT)
        assert state.state == initial
        last = hass.services.calls[-1]
        assert last[:2] == ("light", "turn_on" if initial == "on" else "turn_off")
        if initial == "on":
            assert state.attributes["brightness"] == 77
            assert state.attributes["rgb_color"] == (1, 2, 3)
        assert_released(services, hass)
    asyncio.run(run())


def test_repeated_cancellation_drains_restore_and_blocks_competing_flash(monkeypatch):
    async def run():
        services, engine, hass, _ = environment()
        paused, yield_once = suspend_phase(monkeypatch, 1)
        restoring, finish_restore = asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("brightness") == 77:
                restoring.set()
                await finish_restore.wait()
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        task = worker(engine)
        await asyncio.wait_for(paused.wait(), 1)
        stop = asyncio.create_task(engine.async_stop())
        await asyncio.wait_for(restoring.wait(), 1)
        contender = asyncio.create_task(services.async_flash_lights_for_alert(
            hass, lights=[LIGHT], flash_count=1,
        ))
        calls = list(hass.services.calls)
        for _ in range(3):
            task.cancel()
            await yield_once(0)
        stop.cancel()  # Cancellation of gather must also keep its worker owned.
        await yield_once(0)
        assert not task.done() and not stop.done() and not contender.done()
        assert hass.services.calls == calls
        assert services._light_flash_locks(hass, [LIGHT])[0].locked()
        contender.cancel()  # Waiting for this lock must not capture/restore state.
        with pytest.raises(asyncio.CancelledError):
            await contender
        finish_restore.set()
        with pytest.raises(asyncio.CancelledError):
            await stop
        await task
        assert hass.states.get(LIGHT).attributes["brightness"] == 77
        assert len(hass.services.calls) == len(calls) + 1
        assert_released(services, hass)
    asyncio.run(run())


def test_cancellation_during_normal_restore_remains_observable(monkeypatch):
    async def run():
        services, _, hass, _ = environment()
        restoring, release = asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            restoring.set()
            await release.wait()
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        task = asyncio.create_task(services.async_flash_lights_for_alert(
            hass, lights=[LIGHT], flash_count=0,
        ))
        await asyncio.wait_for(restoring.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_released(services, hass)
    asyncio.run(run())


def test_partial_lock_acquisition_cancellation_issues_no_light_commands():
    async def run():
        services, _, hass, _ = environment(lights=(LIGHT, OTHER))
        first, second = services._light_flash_locks(hass, [LIGHT, OTHER])
        await second.acquire()
        task = asyncio.create_task(services.async_flash_lights_for_alert(
            hass, lights=[LIGHT, OTHER], flash_count=1,
        ))
        await asyncio.sleep(0)
        assert first.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not first.locked() and second.locked()
        assert hass.services.calls == []
        second.release()
        assert_released(services, hass, (LIGHT, OTHER))
    asyncio.run(run())


@pytest.mark.parametrize("during_restore", [False, True])
def test_manual_handover_suppresses_remaining_restore_writes(monkeypatch, during_restore):
    async def run():
        services, engine, hass, _ = environment(lights=(LIGHT, OTHER))
        paused, _ = suspend_phase(monkeypatch, 1)
        original_call = hass.services.async_call
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]

        async def call(domain, service, data=None, blocking=False):
            await original_call(domain, service, data, blocking)
            if (data or {}).get("brightness") == 77:
                manual.is_on = True
                await asyncio.sleep(0)

        hass.services.async_call = call
        task = worker(engine, (LIGHT, OTHER))
        await asyncio.wait_for(paused.wait(), 1)
        calls = len(hass.services.calls)
        if not during_restore:
            manual.is_on = True
        await engine._sync_visual_alert_tasks([])
        assert task.done()
        assert len(hass.services.calls) == calls + int(during_restore)
        assert hass.states.get(OTHER).attributes["brightness"] == 255
        assert_released(services, hass, (LIGHT, OTHER))
    asyncio.run(run())


def test_restore_service_failure_logs_and_attempts_remaining_lights(monkeypatch, caplog):
    async def run():
        services, _, hass, _ = environment(lights=(LIGHT, OTHER))
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("entity_id") == LIGHT:
                raise RuntimeError("simulated restore failure")
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        await services.async_flash_lights_for_alert(hass, lights=[LIGHT, OTHER], flash_count=0)
        assert "Failed to restore light state" in caplog.text
        assert hass.services.calls[-1][2]["entity_id"] == OTHER
        assert_released(services, hass, (LIGHT, OTHER))
    asyncio.run(run())


def test_restore_timeout_cancels_and_drains_service_before_unlock(monkeypatch, caplog):
    async def run():
        services, _, hass, _ = environment()
        monkeypatch.setattr(services, "_FLASH_RESTORE_TIMEOUT_SECONDS", 0.01)
        finished = asyncio.Event()

        async def stalled(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        hass.services.async_call = stalled
        await asyncio.wait_for(services.async_flash_lights_for_alert(
            hass, lights=[LIGHT], flash_count=0,
        ), 1)
        assert finished.is_set()
        assert "original state is not confirmed" in caplog.text
        assert_released(services, hass)
    asyncio.run(run())


def test_cancelled_restore_task_terminates_without_retry_or_detached_cleanup():
    async def run():
        services, _, hass, _ = environment()
        calls = []

        async def cancelled(*_args, **_kwargs):
            calls.append(True)
            raise asyncio.CancelledError

        hass.services.async_call = cancelled
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(services.async_flash_lights_for_alert(
                hass, lights=[LIGHT], flash_count=0,
            ), 1)
        assert calls == [True]
        assert_released(services, hass)
    asyncio.run(run())
