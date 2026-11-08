"""Pinned native HA service/executor and failed-unload contract regressions.

Run separately from modules that install Home Assistant stubs. No devices or
running Home Assistant instance are contacted.
"""

import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant import core
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event


ROOT = Path(__file__).resolve().parents[1] / "custom_components/humidity_intelligence"
NAME = "_hi_lifecycle_native"
spec = importlib.util.spec_from_file_location(NAME, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
integration = importlib.util.module_from_spec(spec)
sys.modules[NAME] = integration
spec.loader.exec_module(integration)
services = sys.modules[NAME + ".services"]
engine_class = sys.modules[NAME + ".automations.engine"].HIAutomationEngine


class NativeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hass = HomeAssistant(self.temp.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        self.addAsyncCleanup(self.stop)
        self.hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True)))
        self.entry = SimpleNamespace(entry_id="example_entry", data={}, options={})
        self.engine = engine_class(self.hass, self.entry)
        self.hass.data[services.DOMAIN] = {self.entry.entry_id: {"automation_engine": self.engine}}
        self.owner = services.lifecycle_for(self.hass)
        self.owner.reserve_setup(self.entry.entry_id)
        self.owner.finish_setup(self.entry.entry_id)
        self.hass.states.async_set("light.example_alert", "off")
        await services.async_register_services(self.hass)

    async def stop(self):
        try:
            await self.hass.async_stop(force=True)
        finally:
            if core.async_get_hass_or_none() is self.hass:
                core._hass.__dict__.clear()
            self.hass = None

    async def test_executor_public_flash_timeout_retains_call_and_lock(self):
        await self.executor_timeout(public=True)

    async def test_executor_engine_flash_timeout_retains_call_and_lock(self):
        await self.executor_timeout(public=False)

    async def test_manual_pulse_during_failed_unload_revokes_late_restoration(self):
        await self.manual_during_unload(cancel=False)

    async def test_manual_pulse_during_interrupted_unload_revokes_late_restoration(self):
        await self.manual_during_unload(cancel=True)

    async def manual_during_unload(self, *, cancel):
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        calls = []
        manual_id = "switch.example_manual"
        self.hass.states.async_set(manual_id, "off")
        self.hass.data[services.DOMAIN][self.entry.entry_id]["hi_input_booleans"] = {
            "air_control_manual_override": SimpleNamespace(entity_id=manual_id, is_on=False),
        }
        self.engine._unsub = async_track_state_change_event(
            self.hass, [manual_id], self.engine._handle_change,
        )

        def device_handler(call):
            calls.append(call.service)
            if len(calls) == 1:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise AssertionError("test did not release executor service")

        self.hass.services.async_register("light", "turn_on", device_handler)
        self.hass.services.async_register("light", "turn_off", device_handler)
        identity = ("example", "level1", "humidity")
        self.engine._visual_alert_active = {identity}
        worker = asyncio.create_task(self.engine._visual_alert_loop(
            identity, {"visual_alert": {"lights": ["light.example_alert"], "flash_mode": "red"}},
        ))
        self.engine._visual_alert_tasks[identity] = worker
        try:
            await asyncio.wait_for(entered.wait(), 2)
            with patch.object(integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.05), patch.object(
                self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True),
            ) as platforms:
                unload = asyncio.create_task(integration.async_unload_entry(self.hass, self.entry))
                if cancel:
                    await asyncio.sleep(0)
                    unload.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await unload
                else:
                    self.assertFalse(await unload)
                platforms.assert_not_awaited()
            self.assertIsNotNone(self.engine._unsub)
            self.assertTrue(self.engine._stopped)
            self.assertEqual(calls, ["turn_on"])
            with patch.object(self.engine, "async_request_evaluate", new=AsyncMock()) as evaluate:
                self.hass.states.async_set(manual_id, "on")
                self.hass.states.async_set(manual_id, "off")
                # Do not use HA's block-till-done: intentionally accepted work is pending.
                for _ in range(30):
                    if self.engine._visual_alert_manual_epoch:
                        break
                    await asyncio.sleep(0)
                self.assertGreater(self.engine._visual_alert_manual_epoch, 0)
                evaluate.assert_not_awaited()
        finally:
            release.set()
            await asyncio.gather(worker, return_exceptions=True)
            cleanup = self.hass.data[services.DOMAIN][self.entry.entry_id].get("unload_task")
            if cleanup is not None:
                done, _ = await asyncio.wait({cleanup}, timeout=2)
                self.assertTrue(done)
                cleanup.result()
        self.assertEqual(calls, ["turn_on"], "Manual handover must suppress late restoration")
        self.assertIsNone(self.engine._unsub)
        self.assertEqual(self.owner.entries[self.entry.entry_id], "failed")
        self.assertFalse(services._light_flash_locks(self.hass, ["light.example_alert"])[0].locked())

    async def executor_timeout(self, *, public):
        entered = asyncio.Event()
        release, finished = threading.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        calls = []

        def device_handler(call):
            calls.append(call.service)
            if len(calls) == 1:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise AssertionError("test did not release executor service")
                finished.set()

        self.hass.services.async_register("light", "turn_on", device_handler)
        self.hass.services.async_register("light", "turn_off", device_handler)
        if public:
            operation = asyncio.create_task(self.hass.services.async_call(
                services.DOMAIN, services.SERVICE_FLASH_LIGHTS,
                {"lights": ["light.example_alert"], "flash_count": 1},
                blocking=True, context=Context(user_id="example_admin"),
            ))
        else:
            operation = asyncio.create_task(services.async_flash_lights_for_alert(
                self.hass, lights=["light.example_alert"], flash_count=1,
            ))
            self.engine._visual_alert_tasks[("example", "level1", "humidity")] = operation
        try:
            await asyncio.wait_for(entered.wait(), 2)
            with patch.object(integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.05), patch.object(
                self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True),
            ) as platforms:
                self.assertFalse(await integration.async_unload_entry(self.hass, self.entry))
                platforms.assert_not_awaited()
            retained = self.hass.data[services.DOMAIN][self.entry.entry_id]
            self.assertIs(retained["automation_engine"], self.engine)
            self.assertFalse(retained["unload_task"].done())
            self.assertFalse(finished.is_set())
            self.assertTrue(services._light_flash_locks(self.hass, ["light.example_alert"])[0].locked())
            self.assertEqual(self.owner.entries[self.entry.entry_id], "failed")
        finally:
            release.set()
            await asyncio.gather(operation, return_exceptions=True)
            cleanup = self.hass.data[services.DOMAIN][self.entry.entry_id].get("unload_task")
            if cleanup is not None:
                done, _ = await asyncio.wait({cleanup}, timeout=2)
                self.assertTrue(done)
                cleanup.result()
        self.assertTrue(finished.is_set())
        self.assertFalse(services._light_flash_locks(self.hass, ["light.example_alert"])[0].locked())
        self.assertEqual(self.owner.entries[self.entry.entry_id], "failed")
        self.assertTrue(self.hass.services.has_service(services.DOMAIN, services.SERVICE_FLASH_LIGHTS))
