"""Visual-alert cancellation, lock custody and Manual handover regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
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
                if task.get_name() in {"hi-flash-restore", "hi-flash-service"} and not task.done()]


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
            assert task in engine._visual_alert_retiring
            await task
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
        await task
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


def test_manual_handover_before_queued_restore_service_prevents_submission():
    async def run():
        services, engine, hass, _ = environment()
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]

        def should_abort():
            active = engine._manual_override_active()
            if not active:
                asyncio.get_running_loop().call_soon(setattr, manual, "is_on", True)
            return active

        await services.async_flash_lights_for_alert(
            hass, lights=[LIGHT], flash_count=0, should_abort=should_abort,
        )
        assert manual.is_on and hass.services.calls == []
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("power_entity", [None, "switch.example_alert_power"])
def test_engine_manual_handover_before_queued_flash_or_power_call_prevents_submission(monkeypatch, power_entity):
    async def run():
        services, engine, hass, _ = environment()
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]
        create_task, sleep = asyncio.create_task, asyncio.sleep
        handover_tasks = []

        def handover():
            manual.is_on = True
            handover_tasks.append(create_task(engine.async_request_evaluate()))

        def schedule(coro, *args, **kwargs):
            if kwargs.get("name") == "hi-flash-service" and not manual.is_on:
                asyncio.get_running_loop().call_soon(handover)
            return create_task(coro, *args, **kwargs)

        async def yield_only(_delay):
            await sleep(0)

        monkeypatch.setattr(asyncio, "create_task", schedule)
        monkeypatch.setattr(asyncio, "sleep", yield_only)
        engine._visual_alert_active = {IDENTITY}
        task = create_task(engine._visual_alert_loop(IDENTITY, {
            "visual_alert": {"lights": [LIGHT], "power_entity": power_entity},
        }))
        engine._visual_alert_tasks[IDENTITY] = task
        await asyncio.wait_for(task, 1)
        await asyncio.gather(*handover_tasks)
        assert manual.is_on and hass.services.calls == []
        await engine.async_stop()
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("service_fails", [False, True])
def test_restore_deadline_retains_executor_call_and_stops_remaining_submissions(monkeypatch, caplog, service_fails):
    async def run():
        services, _, hass, _ = environment(lights=(LIGHT, OTHER))
        monkeypatch.setattr(services, "_FLASH_RESTORE_TIMEOUT_SECONDS", 0.01)
        loop = asyncio.get_running_loop()
        started, finished = asyncio.Event(), threading.Event()
        release = threading.Event()
        original_call = hass.services.async_call

        def device_write():
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2), "test did not release executor"
            finished.set()
            if service_fails:
                raise RuntimeError("simulated late executor failure")

        with ThreadPoolExecutor(max_workers=1) as pool:
            async def call(domain, service, data=None, blocking=False):
                if (data or {}).get("entity_id") == LIGHT:
                    await loop.run_in_executor(pool, device_write)
                await original_call(domain, service, data, blocking)

            hass.services.async_call = call
            task = asyncio.create_task(services.async_flash_lights_for_alert(
                hass, lights=[LIGHT, OTHER], flash_count=0,
            ))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await asyncio.sleep(0.03)  # The submission deadline has expired.
                assert not task.done() and not finished.is_set()
                assert services._light_flash_locks(hass, [LIGHT])[0].locked()
                contender = asyncio.create_task(services.async_flash_lights_for_alert(
                    hass, lights=[LIGHT], flash_count=0,
                ))
                await asyncio.sleep(0)
                assert not contender.done() and hass.services.calls == []
                contender.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await contender
            finally:
                release.set()
                await task
        assert finished.is_set() and len(hass.services.calls) == int(not service_fails)
        if not service_fails:
            assert hass.services.calls[0][2]["entity_id"] == LIGHT
        assert "original state is not confirmed" in caplog.text
        assert_released(services, hass, (LIGHT, OTHER))
    asyncio.run(run())


def test_cancellation_drains_inflight_flash_call_before_restoration(monkeypatch):
    async def run():
        services, _, hass, _ = environment()
        started, release = asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("brightness") == 255:
                started.set()
                await release.wait()
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        task = asyncio.create_task(services.async_flash_lights_for_alert(
            hass, lights=[LIGHT], flash_count=1,
        ))
        await asyncio.wait_for(started.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and hass.services.calls == []
        assert services._light_flash_locks(hass, [LIGHT])[0].locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert [call[2]["brightness"] for call in hass.services.calls] == [255, 77]
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("already_retiring", [False, True])
def test_co_ventilation_does_not_wait_for_visual_cleanup_and_stop_retains_it(monkeypatch, already_retiring):
    async def run():
        services, engine, hass, _ = environment()
        paused, yield_once = suspend_phase(monkeypatch, 1)
        restoring, release = asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("brightness") == 77:
                restoring.set()
                await release.wait()
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        task = worker(engine)
        await asyncio.wait_for(paused.wait(), 1)
        if already_retiring:
            # A previous non-CO evaluation must also relinquish its lock.
            await asyncio.wait_for(engine.async_request_evaluate(), 1)
            await asyncio.wait_for(restoring.wait(), 1)
        hass.states._values["sensor.co_val"] = _FakeState(16, {"unit_of_measurement": "ppm"})
        await asyncio.wait_for(engine.async_request_evaluate(), 1)
        assert hass.data[services.DOMAIN][ENTRY_ID]["runtime_mode"] == "co_emergency"
        fan_calls = [c for c in hass.services.calls if c[:2] == ("fan", "set_percentage")]
        assert fan_calls and all(c[2]["percentage"] == 100 for c in fan_calls)
        await asyncio.wait_for(restoring.wait(), 1)
        assert task in engine._visual_alert_retiring and not task.done()
        assert not engine._get_evaluate_lock().locked()
        stop = asyncio.create_task(engine.async_stop())
        await yield_once(0)
        assert not stop.done()
        assert services._light_flash_locks(hass, [LIGHT])[0].locked()
        release.set()
        await asyncio.wait_for(stop, 1)
        assert task.done() and not engine._visual_alert_retiring
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


def test_retiring_worker_cannot_remove_its_replacement_or_release_its_locks_early(monkeypatch):
    async def run():
        services, engine, hass, _ = environment()
        paused, yield_once = suspend_phase(monkeypatch, 1)
        restoring, release = asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("brightness") == 77:
                restoring.set()
                await release.wait()
            await original_call(domain, service, data, blocking)

        hass.services.async_call = call
        old = worker(engine)
        await asyncio.wait_for(paused.wait(), 1)
        await engine._sync_visual_alert_tasks([])
        await asyncio.wait_for(restoring.wait(), 1)
        detail = {"trigger_type": IDENTITY[0], "sensor": IDENTITY[1], "room": IDENTITY[2],
                  "visual_alert": {"lights": [LIGHT], "flash_mode": "red"}}
        try:
            await engine._sync_visual_alert_tasks([detail])
            replacement = engine._visual_alert_tasks[IDENTITY]
            assert replacement is not old and not replacement.done()
            assert old in engine._visual_alert_retiring
            calls = list(hass.services.calls)
            await yield_once(0)
            assert hass.services.calls == calls
            release.set()
            await asyncio.wait_for(old, 1)
            assert engine._visual_alert_tasks[IDENTITY] is replacement
            assert old not in engine._visual_alert_retiring
        finally:
            release.set()
            await engine.async_stop()
        assert not engine._visual_alert_tasks and not engine._visual_alert_retiring
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("co_emergency", [False, True])
@pytest.mark.parametrize("coalesced_events", [False, True])
def test_manual_pulse_permanently_revokes_retiring_snapshot_but_allows_fresh_worker(monkeypatch, co_emergency, coalesced_events):
    async def run():
        services, engine, hass, _ = environment(lights=(LIGHT, OTHER))
        paused, _ = suspend_phase(monkeypatch, 1)
        restoring, release, fresh_restored = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_call = hass.services.async_call
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]
        manual.entity_id = "switch.example_manual"

        async def call(domain, service, data=None, blocking=False):
            if (data or {}).get("brightness") == 77 and data.get("entity_id") == LIGHT:
                restoring.set()
                await release.wait()
            await original_call(domain, service, data, blocking)
            if (data or {}).get("brightness") == 99 and data.get("entity_id") == OTHER:
                fresh_restored.set()

        hass.services.async_call = call
        task = worker(engine, (LIGHT, OTHER))
        try:
            await asyncio.wait_for(paused.wait(), 1)
            if co_emergency:
                hass.states._values["sensor.co_val"] = _FakeState(16, {"unit_of_measurement": "ppm"})
            await engine.async_request_evaluate()
            await asyncio.wait_for(restoring.wait(), 1)
            assert task in engine._visual_alert_retiring
            manual.is_on = True
            hass.states._values[OTHER] = _FakeState("on", {**ATTRS, "brightness": 99})
            if coalesced_events:
                lock = engine._get_evaluate_lock()
                await lock.acquire()
                try:
                    # Live state is already OFF when its queued ON event arrives.
                    manual.is_on = False
                    for state in ("on", "off"):
                        await engine._handle_change(SimpleNamespace(data={
                            "entity_id": manual.entity_id, "new_state": _FakeState(state),
                        }))
                finally:
                    lock.release()
            else:
                await engine.async_request_evaluate()
                assert hass.data[services.DOMAIN][ENTRY_ID]["runtime_mode"] == (
                    "co_emergency" if co_emergency else "manual_override"
                )
                manual.is_on = False
            await engine.async_request_evaluate()
            release.set()
            await asyncio.wait_for(task, 1)
            assert hass.states.get(OTHER).attributes["brightness"] == 99
            assert not any(c[2].get("entity_id") == OTHER and c[2].get("brightness") == 77
                           for c in hass.services.calls)
            # A fresh worker gets a new snapshot and normal authority after OFF.
            detail = {"trigger_type": IDENTITY[0], "sensor": IDENTITY[1], "room": IDENTITY[2],
                      "visual_alert": {"lights": [OTHER]}}
            await engine._sync_visual_alert_tasks([detail])
            await asyncio.wait_for(fresh_restored.wait(), 1)
        finally:
            release.set()
            await engine.async_stop()
        assert hass.states.get(OTHER).attributes["brightness"] == 99
        assert_released(services, hass, (LIGHT, OTHER))
    asyncio.run(run())


def test_manual_handover_before_worker_starts_submits_no_commands(monkeypatch):
    async def run():
        services, engine, hass, _ = environment()
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]
        manual.entity_id = "switch.example_manual"
        create_task = asyncio.create_task
        scheduled = []

        def schedule(coro, *args, **kwargs):
            if coro.cr_code.co_name == "_visual_alert_loop":
                for state in ("on", "off"):
                    scheduled.append(create_task(engine._handle_change(SimpleNamespace(data={
                        "entity_id": manual.entity_id, "new_state": _FakeState(state),
                    }))))
            task = create_task(coro, *args, **kwargs)
            scheduled.append(task)
            return task

        monkeypatch.setattr(asyncio, "create_task", schedule)
        lock = engine._get_evaluate_lock()
        await lock.acquire()
        try:
            await engine._sync_visual_alert_tasks([{
                "trigger_type": IDENTITY[0], "sensor": IDENTITY[1], "room": IDENTITY[2],
                "visual_alert": {"lights": [LIGHT]},
            }])
            results = await asyncio.wait_for(asyncio.gather(*scheduled, return_exceptions=True), 1)
            assert all(result is None or isinstance(result, asyncio.CancelledError)
                       for result in results)
            assert not manual.is_on and engine._visual_alert_manual_epoch > 0
            assert hass.services.calls == []
        finally:
            lock.release()
            await engine.async_stop()
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["flash_sleep", "repeat_sleep", "accepted_call"])
def test_manual_pulse_restarts_same_alert_without_waiting_for_repeat(monkeypatch, phase):
    async def run():
        services, engine, hass, _ = environment()
        manual = hass.data[services.DOMAIN][ENTRY_ID]["hi_input_booleans"]["air_control_manual_override"]
        manual.entity_id = "switch.example_manual"
        paused, release, fresh_flash = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_sleep, original_call = asyncio.sleep, hass.services.async_call
        handed_over = False
        first_call = True

        async def sleep(delay):
            if delay > 1 or (phase == "flash_sleep" and delay == 0.5 and not paused.is_set()):
                paused.set()
                await asyncio.Event().wait()
            await original_sleep(0)

        async def call(domain, service, data=None, blocking=False):
            nonlocal first_call
            if first_call:
                first_call = False
                if phase == "accepted_call":
                    paused.set()
                    await release.wait()
            elif handed_over and (data or {}).get("brightness") == 255:
                fresh_flash.set()
            await original_call(domain, service, data, blocking)

        monkeypatch.setattr(asyncio, "sleep", sleep)
        hass.services.async_call = call
        detail = {"trigger_type": IDENTITY[0], "sensor": IDENTITY[1], "room": IDENTITY[2],
                  "visual_alert": {"lights": [LIGHT]}}
        evaluate_lock = engine._get_evaluate_lock()
        await evaluate_lock.acquire()
        try:
            await engine._sync_visual_alert_tasks([detail])
            old = engine._visual_alert_tasks[IDENTITY]
            await asyncio.wait_for(paused.wait(), 1)
            # Both events arrive while evaluation is busy and live state is OFF.
            for state in ("on", "off"):
                await engine._handle_change(SimpleNamespace(data={
                    "entity_id": manual.entity_id, "new_state": _FakeState(state),
                }))
            handed_over = True
            await engine._sync_visual_alert_tasks([detail])
            replacement = engine._visual_alert_tasks[IDENTITY]
            assert replacement is not old
            # Repeated evaluation must keep exactly one replacement for this alert.
            await engine._sync_visual_alert_tasks([detail])
            assert engine._visual_alert_tasks[IDENTITY] is replacement
            if phase == "accepted_call":
                assert not old.done() and old in engine._visual_alert_retiring
                assert not fresh_flash.is_set()
                assert services._light_flash_locks(hass, [LIGHT])[0].locked()
            release.set()
            await asyncio.wait_for(fresh_flash.wait(), 1)
            # The test's timeout must not supply a cancellation missing in HI.
            await asyncio.wait_for(asyncio.shield(old), 1)
            assert engine._visual_alert_tasks[IDENTITY] is replacement
            assert old not in engine._visual_alert_retiring
        finally:
            release.set()
            evaluate_lock.release()
            await engine.async_stop()
        assert not engine._visual_alert_tasks and not engine._visual_alert_retiring
        assert_released(services, hass)
    asyncio.run(run())
