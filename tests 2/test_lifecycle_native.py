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

    async def test_failed_native_options_reload_does_not_export_or_claim_success(self):
        notifications = []

        async def notify(call):
            notifications.append(dict(call.data))

        self.hass.services.async_register("persistent_notification", "create", notify)
        entry = SimpleNamespace(
            entry_id="example_reload", domain=integration.DOMAIN, data={}, options={},
            setup_lock=asyncio.Lock(), disabled_by=None, state=ConfigEntryState.LOADED,
            async_cancel_retry_setup=lambda: None,
        )
        self.hass.config.components.add(integration.DOMAIN)
        self.hass.data[integration.DOMAIN][entry.entry_id] = {"config": {"alert_only_mode": False}}
        for visibility_changed in (False, True):
            with self.subTest(visibility_changed=visibility_changed):
                entry.options = {"alert_only_mode": visibility_changed}
                notifications.clear()
                with (
                    patch.object(self.hass.config_entries, "async_get_known_entry", return_value=entry),
                    patch.object(self.hass.config_entries, "async_unload", AsyncMock(return_value=False)) as unload,
                    patch.object(integration, "_async_refresh_and_dump_cards", AsyncMock()) as export,
                ):
                    await integration._async_options_updated(self.hass, entry)
                    await self.hass.async_block_till_done()
                unload.assert_awaited_once()
                export.assert_not_awaited()
                self.assertEqual([n["title"] for n in notifications], ["Humidity Intelligence Options Update Incomplete"])
                self.assertIn("restart Home Assistant", notifications[0]["message"])
                self.assertEqual(entry.options, {"alert_only_mode": visibility_changed})

    async def test_options_reload_exception_is_reported_and_cancellation_propagates(self):
        for error in (RuntimeError("example reload failure"), asyncio.CancelledError()):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(self.hass.config_entries, "async_reload", AsyncMock(side_effect=error)),
                patch.object(integration, "_async_refresh_and_dump_cards", AsyncMock()) as export,
                patch.object(type(self.hass.services), "async_call", AsyncMock()) as notify,
            ):
                if isinstance(error, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):
                        await integration._async_options_updated(self.hass, self.entry)
                    notify.assert_not_awaited()
                else:
                    await integration._async_options_updated(self.hass, self.entry)
                    self.assertEqual(notify.await_args.args[2]["title"], "Humidity Intelligence Options Update Incomplete")
                export.assert_not_awaited()

    async def test_native_light_effect_snapshots_restore_missing_null_and_valid_values(self):
        class ExampleLight(light.LightEntity):
            _attr_is_on = True
            _attr_color_mode = light.ColorMode.RGB
            _attr_supported_color_modes = {light.ColorMode.RGB}
            _attr_supported_features = light.LightEntityFeature.EFFECT
            _attr_effect = None
            _attr_brightness = 77
            _attr_rgb_color = (1, 2, 3)

        attrs = ExampleLight().state_attributes
        self.assertIn("effect", attrs)
        self.assertIsNone(attrs["effect"])
        calls = []

        async def restore(call):
            calls.append(dict(call.data))
            self.hass.states.async_set("light.example_alert", "on", call.data)

        self.hass.services.async_register("light", "turn_on", restore,
            schema=cv.make_entity_service_schema(light.LIGHT_TURN_ON_SCHEMA))
        for effect in (None, "example_effect", "missing"):
            with self.subTest(effect=effect):
                saved = dict(attrs, effect=effect)
                if effect == "missing":
                    saved.pop("effect")
                self.hass.states.async_set("light.example_alert", "on", saved)
                snapshot = services._capture_light_states(self.hass, ["light.example_alert"])
                self.hass.states.async_set("light.example_alert", "off")
                calls.clear()
                await services._restore_lights(self.hass, snapshot)
                self.assertEqual(len(calls), 1)
                self.assertEqual(self.hass.states.get("light.example_alert").state, "on")
                self.assertEqual(calls[0]["brightness"], 77)
                self.assertEqual(tuple(calls[0]["rgb_color"]), (1, 2, 3))
                if effect == "example_effect":
                    self.assertEqual(calls[0]["effect"], effect)
                else:
                    self.assertNotIn("effect", calls[0])

    async def test_cancel_after_flash_off_restores_light_with_null_effect(self):
        off = asyncio.Event()
        calls = []
        self.hass.states.async_set("light.example_alert", "on", {
            "effect": None, "brightness": 77, "color_mode": "rgb", "rgb_color": (1, 2, 3),
        })

        async def handle(call):
            calls.append((call.service, dict(call.data)))
            self.hass.states.async_set("light.example_alert", call.service.removeprefix("turn_"), call.data)
            if call.service == "turn_off":
                off.set()

        self.hass.services.async_register("light", "turn_on", handle,
            schema=cv.make_entity_service_schema(light.LIGHT_TURN_ON_SCHEMA))
        self.hass.services.async_register("light", "turn_off", handle)
        task = asyncio.create_task(services.async_flash_lights_for_alert(
            self.hass, lights=["light.example_alert"], flash_count=2, color=[255, 0, 0],
        ))
        await asyncio.wait_for(off.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertEqual([name for name, _ in calls], ["turn_on", "turn_off", "turn_on"])
        self.assertNotIn("effect", calls[-1][1])
        self.assertEqual(self.hass.states.get("light.example_alert").state, "on")
        self.assertEqual(calls[-1][1]["brightness"], 77)

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

    async def test_white_mode_is_restored_after_rgb_flash(self):
        calls = []
        self.hass.states.async_set("light.example_alert", "on", {
            "color_mode": "white", "brightness": 77,
            "rgb_color": (255, 255, 255), "hs_color": (0, 0),
            "supported_color_modes": ["white", "rgb"],
        })

        async def light_handler(call):
            data = dict(call.data)
            calls.append((call.service, data))
            attrs = dict(self.hass.states.get("light.example_alert").attributes)
            if "rgb_color" in data:
                attrs.update(color_mode="rgb", rgb_color=data["rgb_color"])
            if "white" in data:
                attrs.update(color_mode="white", brightness=data["white"])
            if "brightness" in data:
                attrs["brightness"] = data["brightness"]
            self.hass.states.async_set("light.example_alert", call.service.removeprefix("turn_"), attrs)

        self.hass.services.async_register(
            "light", "turn_on", light_handler,
            schema=cv.make_entity_service_schema(light.LIGHT_TURN_ON_SCHEMA),
        )
        self.hass.services.async_register("light", "turn_off", light_handler)
        await services.async_flash_lights_for_alert(
            self.hass, lights=["light.example_alert"], flash_count=1, color=[255, 0, 0],
        )
        self.assertEqual([service for service, _data in calls], ["turn_on", "turn_off", "turn_on"])
        self.assertIn("rgb_color", calls[0][1])
        self.assertEqual(calls[-1][1]["white"], 77)
        self.assertNotIn("rgb_color", calls[-1][1])
        self.assertNotIn("hs_color", calls[-1][1])
        restored = self.hass.states.get("light.example_alert")
        self.assertEqual(restored.state, "on")
        self.assertEqual(restored.attributes["color_mode"], "white")
        self.assertEqual(restored.attributes["brightness"], 77)

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

    async def test_native_translation_stall_starts_bounded_rollback_on_sibling_error(self):
        await self.sibling_platform_error(cancel=False, translation_stall=True)

    async def test_cancelled_setup_logs_all_late_forward_errors_and_cleans_up(self):
        await self.cancelled_setup_logging(timeout=False)

    async def test_timed_out_rollback_logs_late_forward_errors_without_teardown(self):
        await self.cancelled_setup_logging(timeout=True)

    async def cancelled_setup_logging(self, *, timeout):
        entry = SimpleNamespace(
            entry_id="example_forward_logging", data={}, options={},
            async_on_unload=lambda _callback: None,
            add_update_listener=lambda _callback: lambda: None,
        )
        entered, release, fail_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        children = []

        async def forward(_entry, platforms):
            children.append(asyncio.current_task())
            if len(children) == 3:
                entered.set()
            await (release if platforms == ("switch",) else fail_release).wait()
            if platforms == ("sensor",):
                try:
                    raise ValueError("example translation cause")
                except ValueError as cause:
                    raise RuntimeError("example sensor forwarding failure") from cause
            if platforms == ("binary_sensor",):
                raise LookupError("example binary forwarding failure")

        with patch.object(self.hass.config_entries, "async_forward_entry_setups", new=forward), patch.object(
            self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True),
        ) as platforms, patch.object(integration, "normalize_pm25_aggregate_entity_ids", return_value={}), patch.object(
            integration, "async_unload_automations", new=AsyncMock(),
        ) as runtime, patch.object(integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.05 if timeout else 2), self.assertLogs(
            integration._LOGGER, level="ERROR",
        ) as logs:
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                setup.cancel()
                await asyncio.sleep(0)
                retained = self.hass.data[services.DOMAIN][entry.entry_id]
                self.assertEqual(self.owner.entries[entry.entry_id], "closing")
                self.assertTrue(all(not child.cancelled() and not child.cancelling() for child in children))
                if timeout:
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(asyncio.shield(setup), 1)
                    self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                    runtime.assert_not_awaited()
                fail_release.set()
                await asyncio.wait_for(asyncio.gather(*children[:2], return_exceptions=True), 1)
                self.assertFalse(retained["setup_forward_task"].done())
                self.assertEqual(len([
                    record for record in logs.records if "platform setup failed" in record.getMessage()
                ]), 2)
                runtime.assert_not_awaited()
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(setup), 1)
                await asyncio.wait_for(asyncio.shield(retained["unload_task"]), 1)
                runtime.assert_awaited_once_with(self.hass, entry)
                if timeout:
                    platforms.assert_not_awaited()
                    self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                else:
                    platforms.assert_awaited_once_with(entry, ())
                    self.assertNotIn(entry.entry_id, self.owner.entries)
            finally:
                fail_release.set()
                release.set()
                await asyncio.gather(setup, return_exceptions=True)
            failures = [record for record in logs.records if "platform setup failed" in record.getMessage()]
            self.assertEqual(len(failures), 2)
            self.assertIn("sensor", failures[0].getMessage())
            self.assertIsInstance(failures[0].exc_info[1].__cause__, ValueError)
            for record in failures:
                self.assertIsNotNone(record.exc_info[2])
            self.assertIn("example translation cause", "\n".join(logs.output))

    async def test_direct_drain_cancellation_is_not_swallowed_as_child_cancellation(self):
        release = asyncio.Event()
        forward = asyncio.create_task(release.wait())
        data = self.hass.data[services.DOMAIN][self.entry.entry_id]
        data["setup_forward_task"] = forward
        with patch.object(integration, "async_unload_automations", new=AsyncMock()) as runtime, patch.object(
            self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True),
        ) as platforms:
            unload = asyncio.create_task(integration.async_unload_entry(self.hass, self.entry))
            try:
                while "unload_task" not in data:
                    await asyncio.sleep(0)
                await asyncio.sleep(0)
                data["unload_task"].cancel()
                self.assertFalse(await asyncio.wait_for(unload, 1))
                self.assertTrue(data["unload_task"].cancelled())
                self.assertEqual(self.owner.entries[self.entry.entry_id], "failed")
                runtime.assert_not_awaited()
                platforms.assert_not_awaited()
                self.assertFalse(forward.done())
            finally:
                release.set()
                await forward

    async def test_native_forward_child_cancellation_drains_runtime_and_retains_custody(self):
        await self.cancelled_native_forward(cancel_inner=False)

    async def test_native_inner_forward_cancellation_keeps_shielded_body_in_custody(self):
        await self.cancelled_native_forward(cancel_inner=True)

    async def cancelled_native_forward(self, *, cancel_inner):
        entry = SimpleNamespace(
            entry_id="example_cancelled_forward", domain=services.DOMAIN, title="Example",
            data={}, options={}, async_on_unload=lambda _callback: None,
            add_update_listener=lambda _callback: lambda: None,
            state=ConfigEntryState.SETUP_IN_PROGRESS, setup_lock=asyncio.Lock(),
        )
        await entry.setup_lock.acquire()
        entered, release, body_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        components = {
            domain: entity_component.EntityComponent(logging.getLogger(__name__), domain, self.hass)
            for domain in ("sensor", "binary_sensor", "switch")
        }
        inner_tasks, body_tasks = {}, []

        async def body(_hass, _entry, _add_entities):
            if entity_platform.async_get_current_platform().domain != "sensor":
                return
            body_tasks.append(asyncio.current_task())
            entered.set()
            try:
                if cancel_inner:
                    await release.wait()
                else:
                    raise asyncio.CancelledError()
            finally:
                body_done.set()

        async def entry_setup(_hass, *, integration):
            inner_tasks[integration.domain] = asyncio.current_task()
            return await components[integration.domain].async_setup_entry(entry)

        entry.async_setup = entry_setup
        self.hass.config.components.update(components)
        with patch.object(loader, "async_get_integration", new=AsyncMock(
            return_value=SimpleNamespace(platforms_are_loaded=lambda _platforms: True),
        )), patch.object(loader, "async_get_loaded_integration", side_effect=(
            lambda _hass, domain: SimpleNamespace(domain=domain)
        )), patch.object(entity_component, "async_prepare_setup_platform", new=AsyncMock(
            return_value=SimpleNamespace(async_setup_entry=body),
        )), patch.object(entity_platform.PlatformData, "async_load_translations", new=AsyncMock()), patch.object(
            self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True),
        ) as platforms, patch.object(integration, "normalize_pm25_aggregate_entity_ids", return_value={}), patch.object(
            integration, "async_unload_automations", new=AsyncMock(),
        ) as runtime, self.assertLogs(integration._LOGGER, level="WARNING") as logs:
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                if cancel_inner:
                    inner_tasks["sensor"].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(setup), 1)
                data = self.hass.data[services.DOMAIN][entry.entry_id]
                runtime.assert_awaited_once_with(self.hass, entry)
                platforms.assert_not_awaited()
                self.assertFalse(data["setup_forward_task"].cancelled())
                self.assertFalse(data["unload_task"].cancelled())
                self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                self.assertEqual(body_done.is_set(), not cancel_inner)
                self.assertIn("platform setup completion is unconfirmed", "\n".join(logs.output))
                with self.assertRaises(services.HomeAssistantError):
                    await integration.async_setup_entry(self.hass, entry)
            finally:
                release.set()
                await asyncio.gather(setup, *body_tasks, return_exceptions=True)
                entry.setup_lock.release()
                await self.hass.async_block_till_done()
            self.assertTrue(body_done.is_set())
            platforms.assert_not_awaited()
            self.assertEqual(self.owner.entries[entry.entry_id], "failed")

    async def sibling_platform_error(self, *, cancel, translation_stall=False):
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

        async def translations(_data):
            if translation_stall:
                entered.set()
                await release.wait()

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
        ), patch.object(entity_platform.PlatformData, "async_load_translations", new=translations), patch.object(
            self.hass.config_entries, "async_unload_platforms", new=unload,
        ), patch.object(integration, "normalize_pm25_aggregate_entity_ids", return_value={}), patch.object(
            integration, "_UNLOAD_DRAIN_TIMEOUT_SECONDS", 0.05 if translation_stall else 2,
        ):
            # Keep HA's actual public ConfigEntries forwarding and its native
            # EntityComponent/EntityPlatform setup; inject one base failure only.
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            try:
                await asyncio.wait_for(failed.wait(), 1)
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(setup), 0.02)
                self.assertEqual(self.owner.entries[entry.entry_id], "closing")
                retained = self.hass.data[services.DOMAIN][entry.entry_id]
                self.assertFalse(retained["unload_task"].done())
                if cancel:
                    setup.cancel()
                if cancel or translation_stall:
                    # Interrupting rollback preserves the original setup error.
                    with self.assertRaisesRegex(RuntimeError, "base-component failure"):
                        await asyncio.wait_for(asyncio.shield(setup), 1)
                    self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                else:
                    self.assertFalse(setup.done())
                self.assertFalse(retained["setup_forward_task"].done())
                self.assertEqual(finished, [])
                self.assertEqual(unloads, [])
                release.set()
                if not (cancel or translation_stall):
                    with self.assertRaisesRegex(RuntimeError, "base-component failure"):
                        await asyncio.wait_for(setup, 1)
                await asyncio.wait_for(asyncio.shield(retained["unload_task"]), 1)
                self.assertCountEqual(finished, ["sensor", "switch"])
                if cancel or translation_stall:
                    self.assertEqual(unloads, [])
                    self.assertEqual(self.owner.entries[entry.entry_id], "failed")
                else:
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
                if hold:
                    # Exercise caller cancellation before a forwarding error.
                    await release.wait()
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
