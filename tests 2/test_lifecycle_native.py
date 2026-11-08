"""Pinned native HA service/executor and failed-unload contract regressions.

Run separately from modules that install Home Assistant stubs. No devices or
running Home Assistant instance are contacted.
"""

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant import core, loader, setup as ha_setup
from homeassistant.components import light
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_component, entity_platform


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

    async def test_restore_color_snapshots_use_native_service_schema(self):
        calls = []

        async def record(call):
            calls.append(dict(call.data))

        self.hass.services.async_register(
            "light", "turn_on", record,
            schema=cv.make_entity_service_schema(light.LIGHT_TURN_ON_SCHEMA),
        )
        descriptors = {
            "color_temp": ("color_temp_kelvin", 3000),
            "hs": ("hs_color", (120, 50)),
            "xy": ("xy_color", (0.3, 0.4)),
            "rgb": ("rgb_color", (10, 20, 30)),
            "rgbw": ("rgbw_color", (10, 20, 30, 40)),
            "rgbww": ("rgbww_color", (10, 20, 30, 40, 50)),
        }
        for mode, (key, value) in descriptors.items():
            with self.subTest(color_mode=mode):
                # HA publishes converted formats alongside the active one.
                attrs = {name: saved for name, saved in descriptors.values()}
                attrs.update(color_mode=mode, brightness=77, effect="example_effect")
                calls.clear()
                await services._restore_lights(self.hass, {
                    "light.example_alert": {"state": "on", "attributes": attrs},
                })
                self.assertEqual(len(calls), 1)
                self.assertEqual({name for name, _ in descriptors.values()} & calls[0].keys(), {key})
                self.assertEqual(tuple(calls[0][key]) if isinstance(value, tuple) else calls[0][key], value)
                self.assertEqual(calls[0]["brightness"], 77)
                self.assertEqual(calls[0]["effect"], "example_effect")

    async def test_restoration_skips_unknown_snapshots_after_light_recovers(self):
        calls = []

        async def record(call):
            calls.append((call.service, call.data["entity_id"]))

        self.hass.services.async_register("light", "turn_on", record)
        self.hass.services.async_register("light", "turn_off", record)
        for original in ("unknown", "unavailable", None):
            with self.subTest(original=original):
                if original is None:
                    self.hass.states.async_remove("light.example_alert")
                else:
                    self.hass.states.async_set("light.example_alert", original)
                snapshot = services._capture_light_states(self.hass, ["light.example_alert"])
                self.hass.states.async_set("light.example_alert", "on")
                calls.clear()
                await services._restore_lights(self.hass, snapshot)
                self.assertEqual(calls, [])
        await services._restore_lights(self.hass, {
            "light.example_alert": {"state": "off", "attributes": {}},
        })
        self.assertEqual(calls, [("turn_off", "light.example_alert")])

    async def test_restore_noncolor_and_legacy_snapshots_remain_valid(self):
        calls = []

        async def record(call):
            calls.append(dict(call.data))

        self.hass.services.async_register(
            "light", "turn_on", record,
            schema=cv.make_entity_service_schema(light.LIGHT_TURN_ON_SCHEMA),
        )
        for mode in (None, "brightness", "onoff", "unknown"):
            with self.subTest(color_mode=mode):
                attrs = {"brightness": 77, "rgb_color": (10, 20, 30), "hs_color": (120, 50)}
                if mode is not None:
                    attrs["color_mode"] = mode
                calls.clear()
                await services._restore_lights(self.hass, {
                    "light.example_alert": {"state": "on", "attributes": attrs},
                })
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["brightness"], 77)
                self.assertEqual(len({"rgb_color", "hs_color"} & calls[0].keys()), int(mode is None))

    async def test_partial_setup_rollback_skips_uninitialized_and_previous_platforms(self):
        await self.partial_setup_rollback("partial")

    async def test_setup_rollback_before_any_platform_is_initialized(self):
        await self.partial_setup_rollback("none")

    async def test_cancelled_setup_retains_native_forwarding_until_finished(self):
        await self.partial_setup_rollback("cancel")

    async def test_stalled_setup_retains_forwarding_without_late_teardown(self):
        await self.partial_setup_rollback("stall")

    async def test_failed_setup_platform_unload_keeps_failed_custody(self):
        await self.partial_setup_rollback("unload_failure")

    async def test_native_forward_error_waits_for_sibling_platforms(self):
        await self.sibling_platform_error(cancel=False)

    async def test_cancel_after_native_forward_error_retains_siblings(self):
        await self.sibling_platform_error(cancel=True)

    async def sibling_platform_error(self, *, cancel):
        entry = SimpleNamespace(
            entry_id="example_sibling_failure", domain=services.DOMAIN, title="Example",
            data={}, options={}, async_on_unload=lambda _callback: None,
            add_update_listener=lambda _callback: lambda: None,
            state=ConfigEntryState.SETUP_IN_PROGRESS, setup_lock=asyncio.Lock(),
        )
        await entry.setup_lock.acquire()
        components = {
            domain: entity_component.EntityComponent(logging.getLogger(__name__), domain, self.hass)
            for domain in ("sensor", "switch")
        }
        entered, release, failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        started, finished, unloads = [], [], []

        async def body(_hass, _entry, _add_entities):
            domain = entity_platform.async_get_current_platform().domain
            started.append(domain)
            if len(started) == 2:
                entered.set()
            await release.wait()
            finished.append(domain)

        async def entry_setup(_hass, *, integration):
            return await components[integration.domain].async_setup_entry(entry)

        entry.async_setup = entry_setup

        async def failing_base(_hass, domain, _config):
            self.assertEqual(domain, "binary_sensor")
            await entered.wait()
            failed.set()
            raise RuntimeError("example base-component failure")

        async def unload(current, platforms):
            unloads.append(tuple(platforms))
            self.assertCountEqual(finished, ["sensor", "switch"])
            for domain in platforms:
                self.assertTrue(await components[domain].async_unload_entry(current))
            return True

        self.hass.config.components.update(components)
        with patch.object(loader, "async_get_integration", new=AsyncMock(
            return_value=SimpleNamespace(platforms_are_loaded=lambda _platforms: True),
        )), patch.object(loader, "async_get_loaded_integration", side_effect=(
            lambda _hass, domain: SimpleNamespace(domain=domain)
        )), patch.object(ha_setup, "_async_setup_component", new=failing_base), patch.object(
            entity_component, "async_prepare_setup_platform", new=AsyncMock(
                return_value=SimpleNamespace(async_setup_entry=body),
            ),
        ), patch.object(entity_platform.PlatformData, "async_load_translations", new=AsyncMock()), patch.object(
            self.hass.config_entries, "async_unload_platforms", new=unload,
        ), patch.object(integration, "normalize_pm25_aggregate_entity_ids", return_value={}):
            # Keep HA's actual public ConfigEntries forwarding and its native
            # EntityComponent/EntityPlatform setup; inject one base failure only.
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            try:
                await asyncio.wait_for(failed.wait(), 1)
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(setup), 0.02)
                if cancel:
                    setup.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(setup.done())
                self.assertIn(entry.entry_id, self.owner.entries)
                retained = self.hass.data[services.DOMAIN][entry.entry_id]
                self.assertFalse(retained["setup_forward_task"].done())
                self.assertEqual(finished, [])
                self.assertEqual(unloads, [])
                release.set()
                with self.assertRaises(asyncio.CancelledError if cancel else RuntimeError):
                    await asyncio.wait_for(setup, 1)
                self.assertCountEqual(finished, ["sensor", "switch"])
                self.assertEqual(unloads, [("sensor", "switch")])
                self.assertNotIn(entry.entry_id, self.owner.entries)
                self.assertNotIn(entry.entry_id, self.hass.data[services.DOMAIN])
            finally:
                release.set()
                await asyncio.gather(setup, return_exceptions=True)
                entry.setup_lock.release()
                await self.hass.async_block_till_done()

    async def partial_setup_rollback(self, outcome):
        entry = SimpleNamespace(
            entry_id="example_partial_entry", domain=services.DOMAIN, title="Example",
            data={}, options={}, async_on_unload=lambda _callback: None,
            add_update_listener=lambda _callback: lambda: None,
        )
        other = SimpleNamespace(entry_id="example_other_entry", domain=services.DOMAIN, title="Other")
        components = {
            domain: entity_component.EntityComponent(logging.getLogger(__name__), domain, self.hass)
            for domain in ("sensor", "binary_sensor", "switch")
        }
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        hold = False
        unloads = []

        async def platform_setup(_hass, current, _add_entities):
            if hold and current is entry:
                entered.set()
                await release.wait()
                finished.set()

        async def forward(current, platforms):
            if "sensor" in platforms and outcome != "none":
                self.assertTrue(await components["sensor"].async_setup_entry(current))
            if "binary_sensor" in platforms:
                raise ValueError("example platform setup failure")

        async def unload(current, platforms):
            unloads.append(tuple(platforms))
            if outcome == "unload_failure":
                return False
            for domain in platforms:
                self.assertTrue(await components[domain].async_unload_entry(current))
            return True

        with patch.object(entity_component, "async_prepare_setup_platform", new=AsyncMock(
            return_value=SimpleNamespace(async_setup_entry=platform_setup),
        )), patch.object(entity_platform.PlatformData, "async_load_translations", new=AsyncMock()), patch.object(
            self.hass.config_entries, "async_forward_entry_setups", new=forward,
        ), patch.object(self.hass.config_entries, "async_unload_platforms", new=unload), patch.object(
            integration, "normalize_pm25_aggregate_entity_ids", return_value={},
        ), patch.object(integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.05 if outcome == "stall" else 2):
            # HA 2026.5 retains reset platform objects. They must not be treated
            # as this new attempt, nor may another entry's platform be removed.
            self.assertTrue(await components["binary_sensor"].async_setup_entry(entry))
            self.assertTrue(await components["binary_sensor"].async_unload_entry(entry))
            self.assertTrue(await components["switch"].async_setup_entry(other))
            hold = outcome in {"cancel", "stall"}
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            try:
                if hold:
                    await asyncio.wait_for(entered.wait(), 1)
                    setup.cancel()
                    await asyncio.sleep(0)
                    retained = self.hass.data[services.DOMAIN][entry.entry_id]
                    forwarding = retained["setup_forward_task"]
                    self.assertFalse(forwarding.done())
                    self.assertEqual(unloads, [])
                    if outcome == "cancel":
                        self.assertFalse(setup.done())
                        release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(setup, 1)
                else:
                    with self.assertRaisesRegex(ValueError, "example platform setup"):
                        await asyncio.wait_for(setup, 1)
                if outcome in {"stall", "unload_failure"}:
                    self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                    with self.assertRaises(services.HomeAssistantError):
                        await integration.async_setup_entry(self.hass, entry)
                else:
                    self.assertNotIn(entry.entry_id, self.owner.entries)
                    self.assertNotIn(entry.entry_id, self.hass.data[services.DOMAIN])
                self.assertEqual(unloads, [] if outcome == "stall" else [() if outcome == "none" else ("sensor",)])
                self.assertEqual(self.owner.entries[self.entry.entry_id], "loaded")
                self.assertTrue(await components["switch"].async_unload_entry(other))
            finally:
                release.set()
                await asyncio.gather(setup, return_exceptions=True)
                retained = self.hass.data[services.DOMAIN].get(entry.entry_id, {})
                if cleanup := retained.get("unload_task"):
                    await asyncio.wait_for(asyncio.shield(cleanup), 1)
            if hold:
                self.assertTrue(finished.is_set())
            if outcome == "stall":
                self.assertEqual(unloads, [])
                self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                self.assertTrue(forwarding.done())

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
        self.assertEqual(calls, ["turn_on", "turn_off"])
        self.assertFalse(services._light_flash_locks(self.hass, ["light.example_alert"])[0].locked())
        self.assertEqual(self.owner.entries[self.entry.entry_id], "failed")
        self.assertTrue(self.hass.services.has_service(services.DOMAIN, services.SERVICE_FLASH_LIGHTS))
