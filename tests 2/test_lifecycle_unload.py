"""Entry/public-service ownership with deterministic, offline failure boundaries."""

import asyncio
from types import SimpleNamespace

import pytest

from test_flash_cancellation import (
    LIGHT, ATTRS, environment, worker, assert_released, suspend_phase,
)
from test_runtime_card_sanity import ENTRY_ID, _load_integration_init_module


SECOND = "example_second_entry"


async def fixture(monkeypatch):
    services, engine, hass, entry = environment()
    integration = _load_integration_init_module()
    # The real relative import is deliberate: exercise production handlers/unload.
    services = __import__(integration.__package__ + ".services", fromlist=["services"])
    assert integration.async_unregister_services is services.async_unregister_services
    assert integration.async_unload_automations.__module__.endswith(".automations")
    engine_module = __import__(engine.__module__, fromlist=["engine"])
    monkeypatch.setattr(engine_module, "async_flash_lights_for_alert", services.async_flash_lights_for_alert)
    owner = services.lifecycle_for(hass)
    owner.reserve_setup(ENTRY_ID)
    owner.finish_setup(ENTRY_ID)

    async def get_user(_user_id):
        return SimpleNamespace(is_admin=True)

    hass.auth = SimpleNamespace(async_get_user=get_user)
    platforms = []

    async def unload_platforms(entry, _platforms):
        platforms.append(entry.entry_id)
        return True

    hass.config_entries.async_unload_platforms = unload_platforms
    await services.async_register_services(hass)
    handler = hass.services.handlers[(services.DOMAIN, services.SERVICE_FLASH_LIGHTS)]
    call = SimpleNamespace(data={"lights": [LIGHT], "flash_count": 1},
                           context=SimpleNamespace(user_id="admin"))
    monkeypatch.setattr(integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.04)
    return services, engine, hass, entry, integration, owner, handler, call, platforms


async def drain_task(hass, domain, entry):
    task = hass.data[domain][entry.entry_id]["unload_task"]
    done, _ = await asyncio.wait({task}, timeout=2)
    assert done, "test handler must be released; watchdog does not cancel custody"
    task.result()


def test_last_unload_restores_public_flash_before_removing_entry(monkeypatch):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        paused, _ = suspend_phase(monkeypatch, 1)
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(paused.wait(), 1)
        assert len(owner.public_tasks) == 1
        assert await integration.async_unload_entry(hass, entry)
        await asyncio.gather(public, return_exceptions=True)
        assert platforms == [ENTRY_ID]
        assert ENTRY_ID not in hass.data[services.DOMAIN]
        assert not owner.entries and not owner.public_tasks
        assert not hass.services.handlers
        assert hass.states.get(LIGHT).attributes["brightness"] == ATTRS["brightness"]
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("route", ["public", "engine"])
@pytest.mark.parametrize("phase", ["forward", "restore"])
def test_stalled_handler_bounds_unload_without_discarding_custody(monkeypatch, caplog, route, phase):
    async def run():
        services, engine, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        original = hass.services.async_call
        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        async def blocked(domain, service, data=None, blocking=False):
            restoring = (data or {}).get("brightness") == ATTRS["brightness"]
            if not entered.is_set() and restoring == (phase == "restore"):
                entered.set()
                await release.wait()
            await original(domain, service, data, blocking)

        hass.services.async_call = blocked
        operation = asyncio.create_task(handler(call)) if route == "public" else worker(engine)
        try:
            await asyncio.wait_for(entered.wait(), 1)
            start = asyncio.get_running_loop().time()
            assert await integration.async_unload_entry(hass, entry) is False
            assert asyncio.get_running_loop().time() - start < 0.5
            retained = hass.data[services.DOMAIN][ENTRY_ID]
            assert retained["automation_engine"] is engine
            cleanup = retained["unload_task"]
            assert not cleanup.done() and not operation.done()
            assert platforms == []
            assert owner.entries[ENTRY_ID] == "failed"
            assert services._light_flash_locks(hass, [LIGHT])[0].locked()
            assert "runtime drain timed out" in caplog.text
            with pytest.raises(services.HomeAssistantError, match="unavailable"):
                await handler(call)
            with pytest.raises(services.HomeAssistantError, match="restart"):
                await integration.async_setup_entry(hass, entry)
            assert await integration.async_unload_entry(hass, entry) is False
            assert retained["unload_task"] is cleanup
        finally:
            release.set()
            await asyncio.gather(operation, return_exceptions=True)
            await drain_task(hass, services.DOMAIN, entry)
        assert owner.entries[ENTRY_ID] == "failed"
        assert platforms == [] and hass.data[services.DOMAIN][ENTRY_ID] is retained
        with pytest.raises(services.HomeAssistantError, match="unavailable"):
            await handler(call)
        assert_released(services, hass)
    asyncio.run(run())


def test_one_of_two_entries_keeps_public_calls_and_services(monkeypatch):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        second = SimpleNamespace(entry_id=SECOND)
        hass.data[services.DOMAIN][SECOND] = {}
        owner.reserve_setup(SECOND)
        owner.finish_setup(SECOND)
        paused, _ = suspend_phase(monkeypatch, 1)
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(paused.wait(), 1)
        assert await integration.async_unload_entry(hass, entry)
        assert not public.done() and len(owner.public_tasks) == 1
        assert (services.DOMAIN, services.SERVICE_FLASH_LIGHTS) in hass.services.handlers
        assert owner.entries == {SECOND: "loaded"}
        assert await integration.async_unload_entry(hass, second)
        await asyncio.gather(public, return_exceptions=True)
        assert platforms == [ENTRY_ID, SECOND]
        assert not hass.services.handlers and not owner.entries
        assert_released(services, hass)
    asyncio.run(run())


def test_simultaneous_unloads_drain_public_work_once(monkeypatch):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        second = SimpleNamespace(entry_id=SECOND)
        hass.data[services.DOMAIN][SECOND] = {}
        owner.reserve_setup(SECOND)
        owner.finish_setup(SECOND)
        paused, _ = suspend_phase(monkeypatch, 1)
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(paused.wait(), 1)
        assert await asyncio.gather(integration.async_unload_entry(hass, entry),
                                    integration.async_unload_entry(hass, second)) == [True, True]
        await asyncio.gather(public, return_exceptions=True)
        assert set(platforms) == {ENTRY_ID, SECOND} and len(platforms) == 2
        assert not owner.entries and not owner.public_tasks and not hass.services.handlers
        assert_released(services, hass)
    asyncio.run(run())


def test_authentication_cannot_admit_across_closure_or_new_setup(monkeypatch):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, _ = await fixture(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()

        async def authorize(_user_id):
            entered.set()
            await release.wait()
            return SimpleNamespace(is_admin=True)

        hass.auth.async_get_user = authorize
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(entered.wait(), 1)
        assert await integration.async_unload_entry(hass, entry)
        owner.reserve_setup(SECOND)
        owner.finish_setup(SECOND)
        release.set()
        with pytest.raises(services.HomeAssistantError, match="unavailable"):
            await public
        assert not hass.services.calls and not owner.public_tasks
    asyncio.run(run())


def test_cancelled_unload_retains_the_same_drain_and_blocks_late_teardown(monkeypatch):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        original = hass.services.async_call

        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            await original(*args, **kwargs)

        hass.services.async_call = blocked
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(entered.wait(), 1)
        unload = asyncio.create_task(integration.async_unload_entry(hass, entry))
        await asyncio.sleep(0)
        retained = hass.data[services.DOMAIN][ENTRY_ID]["unload_task"]
        unload.cancel()
        with pytest.raises(asyncio.CancelledError):
            await unload
        assert not retained.done() and not retained.cancelled()
        assert owner.entries[ENTRY_ID] == "failed"
        assert await integration.async_unload_entry(hass, entry) is False
        assert hass.data[services.DOMAIN][ENTRY_ID]["unload_task"] is retained
        release.set()
        await asyncio.gather(public, return_exceptions=True)
        await drain_task(hass, services.DOMAIN, entry)
        assert platforms == [] and ENTRY_ID in hass.data[services.DOMAIN]
        assert_released(services, hass)
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["false", "exception", "cancel", "engine"])
def test_failed_teardown_keeps_stopped_engine_and_closes_public_admission(monkeypatch, failure):
    async def run():
        services, engine, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)

        async def fail(*_args):
            if failure == "false":
                return False
            if failure == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("test teardown failure")

        if failure == "engine":
            async def stop():
                engine._stopped = True
                await fail()
            monkeypatch.setattr(engine, "async_stop", stop)
        else:
            hass.config_entries.async_unload_platforms = fail
        if failure in {"exception", "cancel"}:
            with pytest.raises(RuntimeError if failure == "exception" else asyncio.CancelledError):
                await integration.async_unload_entry(hass, entry)
        else:
            assert await integration.async_unload_entry(hass, entry) is False
        assert engine._stopped
        assert hass.data[services.DOMAIN][ENTRY_ID]["automation_engine"] is engine
        assert owner.entries[ENTRY_ID] == "failed"
        assert (services.DOMAIN, services.SERVICE_FLASH_LIGHTS) in hass.services.handlers
        with pytest.raises(services.HomeAssistantError, match="unavailable"):
            await handler(call)
        assert not hass.services.calls
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_setup_reservation_precedes_last_unload_and_rollback_drains(monkeypatch, outcome):
    async def run():
        services, _, hass, entry, integration, owner, handler, call, platforms = await fixture(monkeypatch)
        second = SimpleNamespace(entry_id=SECOND)
        entered, release = asyncio.Event(), asyncio.Event()

        async def setup(_hass, _entry):
            entered.set()
            await release.wait()
            if outcome == "failure":
                raise ValueError("setup failed")
            return True

        monkeypatch.setattr(integration, "_async_setup_entry", setup)
        starting = asyncio.create_task(integration.async_setup_entry(hass, second))
        await asyncio.wait_for(entered.wait(), 1)
        assert owner.entries[SECOND] == "starting"
        paused, _ = suspend_phase(monkeypatch, 1)
        public = asyncio.create_task(handler(call))
        await asyncio.wait_for(paused.wait(), 1)
        assert await integration.async_unload_entry(hass, entry)
        assert not public.done() and hass.services.handlers
        if outcome == "cancel":
            starting.cancel()
        else:
            release.set()
        if outcome == "success":
            assert await starting
            assert owner.entries[SECOND] == "loaded"
            assert await integration.async_unload_entry(hass, second)
        else:
            with pytest.raises(ValueError if outcome == "failure" else asyncio.CancelledError):
                await starting
        await asyncio.gather(public, return_exceptions=True)
        assert not owner.entries and not owner.public_tasks and not hass.services.handlers
        assert_released(services, hass)
    asyncio.run(run())


def test_failed_entry_does_not_stop_other_loaded_engine(monkeypatch):
    async def run():
        services, engine, hass, entry, integration, owner, handler, call, _ = await fixture(monkeypatch)
        owner.reserve_setup(SECOND)
        owner.finish_setup(SECOND)
        calls = []

        async def second_stop():
            calls.append("stop")

        other = SimpleNamespace(async_stop=second_stop, _stopped=False)
        hass.data[services.DOMAIN][SECOND] = {"automation_engine": other}

        async def fail(*_args):
            return False

        hass.config_entries.async_unload_platforms = fail
        assert await integration.async_unload_entry(hass, entry) is False
        assert not other._stopped and not calls
        assert owner.entries == {ENTRY_ID: "failed", SECOND: "loaded"}
        assert engine._stopped
        with pytest.raises(services.HomeAssistantError, match="unavailable"):
            await handler(call)
        assert hass.services.handlers
    asyncio.run(run())


def test_partial_engine_start_failure_retains_accepted_work(monkeypatch):
    async def run():
        services, _, hass, _, integration, owner, _, _, platforms = await fixture(monkeypatch)
        second = SimpleNamespace(entry_id=SECOND, data={}, options={})
        automations = __import__(integration.__package__ + ".automations", fromlist=["automations"])
        entered, release = asyncio.Event(), asyncio.Event()
        original = hass.services.async_call

        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            await original(*args, **kwargs)

        hass.services.async_call = blocked

        class PartialEngine(automations.HIAutomationEngine):
            async def async_start(self):
                task = asyncio.create_task(services.async_flash_lights_for_alert(
                    self.hass, lights=[LIGHT], flash_count=1,
                ))
                self._visual_alert_tasks[("example", "level1", "humidity")] = task
                await entered.wait()
                raise RuntimeError("partial startup failure")

        async def setup(_hass, entry):
            await automations.async_setup_entry(_hass, entry)

        monkeypatch.setattr(automations, "HIAutomationEngine", PartialEngine)
        monkeypatch.setattr(integration, "_async_setup_entry", setup)
        try:
            with pytest.raises(RuntimeError, match="partial startup"):
                await integration.async_setup_entry(hass, second)
            retained = hass.data[services.DOMAIN][SECOND]
            assert retained["automation_engine"]._stopped
            assert not retained["unload_task"].done()
            assert owner.entries[SECOND] == "failed"
            assert platforms == []
            assert services._light_flash_locks(hass, [LIGHT])[0].locked()
        finally:
            release.set()
            await drain_task(hass, services.DOMAIN, second)
        assert_released(services, hass)
    asyncio.run(run())
