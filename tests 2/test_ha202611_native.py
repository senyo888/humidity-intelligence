"""Run separately in pinned HA environments; no live instance or device I/O."""
import asyncio
import copy
import gc
import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
import weakref

from homeassistant import core, data_entry_flow
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, device_registry as dr, config_validation as cv
from homeassistant.helpers import area_registry, issue_registry, label_registry

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_hi_alignment_native"
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components/humidity_intelligence")]
sys.modules[PACKAGE] = package
flow_module = importlib.import_module(PACKAGE + ".config_flow")
observer = importlib.import_module(PACKAGE + ".helpers.update_observation")
aq = importlib.import_module(PACKAGE + ".helpers.air_quality")
co_repairs = importlib.import_module(PACKAGE + ".helpers.co_repairs")
HA_INSTANCES = []


def tearDownModule():
    """Collect stopped native storage cycles before extension finalization.

    Preserve HA's dependency pins; see docs/config-flow-testing.md for the
    orjson.Fragment shutdown reproducer and the fixture-cleanup boundary.
    """
    for registry in (er, dr, area_registry, issue_registry, label_registry):
        clear = getattr(registry.async_get, "cache_clear", None)
        if callable(clear):
            clear()
    gc.collect()
    if any(reference() is not None for reference in HA_INSTANCES):
        raise AssertionError("Native alignment fixture retained a Home Assistant instance")
    HA_INSTANCES.clear()


class NativeAlignmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hass = HomeAssistant(self.temp.name)
        HA_INSTANCES.append(weakref.ref(self.hass))
        self.addAsyncCleanup(self.stop)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        setup = getattr(dr, "async_setup", None)
        if setup is not None:
            setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)

    async def stop(self):
        try:
            await self.hass.async_stop(force=True)
        finally:
            if core.async_get_hass_or_none() is self.hass:
                core._hass.__dict__.clear()
            self.hass = None

    def options(self):
        entry = SimpleNamespace(data={
            "time_gate": {"enabled": True, "start": "06:15", "end": "22:45", "outside_action": "pause"},
            "presence_gate": {"enabled": True, "entities": ["person.example"],
                              "present_states": ["home"], "away_states": ["not_home"]},
        }, options={})
        flow = flow_module.HumidityIntelligenceOptionsFlow(entry)
        flow.hass = self.hass
        return flow, entry

    async def test_co_unit_repair_uses_native_events_and_entry_cleanup(self):
        await issue_registry.async_load(self.hass)
        registry = issue_registry.async_get(self.hass)
        source = "sensor.example_co"
        cleanup = []
        entry = SimpleNamespace(entry_id="example_co_entry", async_on_unload=cleanup.append)
        config = {"telemetry": [{"entity_id": source, "sensor_type": "co"}] * 2,
                  "aq": {"level1": {"enabled": False}}}
        issue_id = "co_unit_unsupported_example_co_entry"
        self.hass.states.async_set(source, "30")
        co_repairs.async_setup_co_unit_repair(self.hass, entry, config)
        issue = registry.async_get_issue("humidity_intelligence", issue_id)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.translation_placeholders, {"entities": source})
        self.assertEqual(issue.severity, issue_registry.IssueSeverity.WARNING)
        for unit in ("ppm", "ppb"):
            self.hass.states.async_set(source, "30", {"unit_of_measurement": unit})
            await self.hass.async_block_till_done()
            self.assertIsNone(registry.async_get_issue("humidity_intelligence", issue_id))
            self.hass.states.async_set(source, "30", {"unit_of_measurement": "mg/m³"})
            await self.hass.async_block_till_done()
            self.assertIsNotNone(registry.async_get_issue("humidity_intelligence", issue_id))
        for state in ("unknown", "unavailable"):
            self.hass.states.async_set(source, state)
            await self.hass.async_block_till_done()
            self.assertIsNone(registry.async_get_issue("humidity_intelligence", issue_id))
            self.hass.states.async_set(source, "30")
            await self.hass.async_block_till_done()
            self.assertIsNotNone(registry.async_get_issue("humidity_intelligence", issue_id))
        self.assertEqual(len(cleanup), 1)
        cleanup.pop()()
        self.assertIsNone(registry.async_get_issue("humidity_intelligence", issue_id))
        self.hass.states.async_set(source, "31")
        await self.hass.async_block_till_done()
        self.assertIsNone(registry.async_get_issue("humidity_intelligence", issue_id))
        co_repairs.async_setup_co_unit_repair(self.hass, entry, config)
        self.assertIsNotNone(registry.async_get_issue("humidity_intelligence", issue_id))
        cleanup.pop()()

    async def test_co_repairs_are_entry_scoped_and_do_not_infer_availability(self):
        await issue_registry.async_load(self.hass)
        registry = issue_registry.async_get(self.hass)
        cleanups = []
        for suffix in ("a", "b"):
            entry = SimpleNamespace(entry_id="example_" + suffix, async_on_unload=cleanups.append)
            source = "sensor.example_co_" + suffix
            co_repairs.async_setup_co_unit_repair(self.hass, entry, {
                "telemetry": [{"entity_id": source, "sensor_type": "co"}],
            })
            self.assertIsNone(registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_" + suffix))
            for state in ("unknown", "unavailable"):
                for attributes in ({}, {"unit_of_measurement": "ppm"}):
                    self.hass.states.async_set(source, state, attributes)
                    await self.hass.async_block_till_done()
                    self.assertIsNone(registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_" + suffix))
            self.hass.states.async_set(source, "30")
        await self.hass.async_block_till_done()
        cleanups[0]()
        self.assertIsNone(registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_a"))
        self.assertIsNotNone(registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_b"))
        cleanups[1]()

    async def test_co_repairs_skip_unavailable_source_and_report_later_invalid_source(self):
        await issue_registry.async_load(self.hass)
        registry = issue_registry.async_get(self.hass)
        unavailable_source = "sensor.example_co_a"
        invalid_source = "sensor.example_co_b"
        cleanups = []
        entry = SimpleNamespace(entry_id="example_mixed", async_on_unload=cleanups.append)
        self.hass.states.async_set(
            unavailable_source, "unavailable", {"unit_of_measurement": "mg/m³"}
        )
        self.hass.states.async_set(invalid_source, "30")
        co_repairs.async_setup_co_unit_repair(self.hass, entry, {
            "telemetry": [
                {"entity_id": source, "sensor_type": "co"}
                for source in (invalid_source, unavailable_source)
            ],
        })
        issue = registry.async_get_issue(
            "humidity_intelligence", "co_unit_unsupported_example_mixed"
        )
        self.assertIsNotNone(issue)
        self.assertEqual(issue.translation_placeholders, {"entities": invalid_source})
        self.hass.states.async_set(unavailable_source, "30")
        await self.hass.async_block_till_done()
        issue = registry.async_get_issue(
            "humidity_intelligence", "co_unit_unsupported_example_mixed"
        )
        self.assertIsNotNone(issue)
        self.assertEqual(
            issue.translation_placeholders,
            {"entities": f"{unavailable_source}, {invalid_source}"},
        )
        self.hass.states.async_set(unavailable_source, "unavailable")
        await self.hass.async_block_till_done()
        issue = registry.async_get_issue(
            "humidity_intelligence", "co_unit_unsupported_example_mixed"
        )
        self.assertIsNotNone(issue)
        self.assertEqual(issue.translation_placeholders, {"entities": invalid_source})
        cleanups.pop()()

    async def test_co_repairs_clear_existing_warning_for_unavailable_states_and_retained_units(self):
        await issue_registry.async_load(self.hass)
        registry = issue_registry.async_get(self.hass)
        source = "sensor.example_co_retained"
        cleanups = []
        entry = SimpleNamespace(entry_id="example_retained", async_on_unload=cleanups.append)
        issue_id = "co_unit_unsupported_example_retained"
        co_repairs.async_setup_co_unit_repair(self.hass, entry, {
            "telemetry": [{"entity_id": source, "sensor_type": "co"}],
        })
        for state in ("unknown", "unavailable"):
            for attributes in ({}, {"unit_of_measurement": "ppm"}, {"unit_of_measurement": "mg/m³"}):
                with self.subTest(state=state, attributes=attributes):
                    self.hass.states.async_set(source, "30", {"unit_of_measurement": "mg/m³"})
                    await self.hass.async_block_till_done()
                    self.assertIsNotNone(registry.async_get_issue("humidity_intelligence", issue_id))
                    self.hass.states.async_set(source, state, attributes)
                    await self.hass.async_block_till_done()
                    self.assertIsNone(registry.async_get_issue("humidity_intelligence", issue_id))
        cleanups.pop()()

    async def test_co_repair_uses_effective_options_without_writing_devices(self):
        from unittest.mock import AsyncMock, patch

        integration = importlib.import_module(PACKAGE + ".__init__")
        await issue_registry.async_load(self.hass)
        registry = issue_registry.async_get(self.hass)
        cleanup = []
        entry = SimpleNamespace(
            entry_id="example_options", async_on_unload=cleanup.append,
            data={"telemetry": [{"entity_id": "sensor.example_old_co", "sensor_type": "co"}]},
            options={"telemetry": [{"entity_id": "sensor.example_saved_co", "sensor_type": "co"}]},
        )
        self.hass.states.async_set("sensor.example_old_co", "30")
        self.hass.states.async_set("sensor.example_saved_co", "30", {"unit_of_measurement": "ppm"})
        with patch.object(type(self.hass.services), "async_call", new_callable=AsyncMock) as service_call:
            co_repairs.async_setup_co_unit_repair(self.hass, entry, integration._effective_entry_config(entry))
            self.assertIsNone(registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_options"))
            self.hass.states.async_set("sensor.example_saved_co", "30")
            await self.hass.async_block_till_done()
            issue = registry.async_get_issue("humidity_intelligence", "co_unit_unsupported_example_options")
            self.assertEqual(issue.translation_placeholders, {"entities": "sensor.example_saved_co"})
            cleanup.pop()()
            service_call.assert_not_called()

    async def test_visibility_uses_real_ha_schema_and_hidden_input_processing(self):
        for setup in (False, True):
            flow, _entry = self.options()
            if setup:
                flow = flow_module.HumidityIntelligenceConfigFlow()
                flow.hass = self.hass
            step = flow.async_step_gates if setup else flow.async_step_options_gates
            result = await step()
            schema = result["data_schema"]
            markers = {key.schema: key for key in schema.schema}
            fields = ("start_time", "end_time", "outside_action", "presence_entities")
            if hasattr(data_entry_flow, "Optional"):
                import probatio
                self.assertIsInstance(schema, probatio.Schema)
                serialized = probatio.to_field_list(schema, custom_serializer=cv.custom_serializer)
                data_entry_flow.add_visible_conditions_to_serialized_schema(schema, serialized)
                serialized = {item["name"]: item for item in serialized}
                for field in fields:
                    gate = "enable_presence_gate" if field == "presence_entities" else "enable_time_gate"
                    self.assertEqual(serialized[field]["visible"], {"field": gate, "value": True})
                stripped, submitted = data_entry_flow._strip_hidden_fields(schema, {
                    "enable_time_gate": False, "enable_presence_gate": False,
                    "start_time": "01:00", "presence_entities": [],
                })
                values = stripped(submitted)
                for field in fields:
                    self.assertNotIn(field, values)
            else:
                for field in fields:
                    self.assertIsNone(getattr(markers[field], "visible", None))
                values = schema({"enable_time_gate": False, "enable_presence_gate": False})
                self.assertIn("start_time", values)

    async def test_hidden_gate_settings_preserve_staged_options_and_explicit_clear(self):
        flow, entry = self.options()
        before = copy.deepcopy(entry.data)
        flow._options["time_gate"] = dict(before["time_gate"], start="07:00")
        await flow.async_step_options_gates({"enable_time_gate": False, "enable_presence_gate": False})
        self.assertEqual(flow._options["time_gate"]["start"], "07:00")
        self.assertEqual(flow._options["time_gate"]["end"], "22:45")
        self.assertEqual(flow._options["presence_gate"]["entities"], ["person.example"])
        self.assertEqual(flow._options["presence_gate"]["present_states"], ["home"])
        self.assertEqual(entry.data, before)
        self.assertEqual(entry.options, {})
        result = await flow.async_step_options_gates({"enable_time_gate": True, "enable_presence_gate": True})
        self.assertEqual(result["step_id"], "options_presence_states")
        result = await flow.async_step_options_presence_states({"present_states": ["away"], "away_states": ["away"]})
        self.assertEqual(result["errors"]["away_states"], "overlap")
        markers = {key.schema: key for key in result["data_schema"].schema}
        self.assertEqual(markers["present_states"].default(), ["away"])
        self.assertEqual(entry.data, before)
        self.assertEqual(entry.options, {})
        result = await flow.async_step_options_gates()
        schema = result["data_schema"]
        submitted = {"enable_time_gate": False, "enable_presence_gate": True, "presence_entities": []}
        if hasattr(data_entry_flow, "_strip_hidden_fields"):
            schema, submitted = data_entry_flow._strip_hidden_fields(schema, submitted)
        await flow.async_step_options_gates(schema(submitted))
        self.assertEqual(flow._options["presence_gate"]["entities"], [])

    async def test_fresh_disabled_gates_receive_existing_defaults(self):
        flow = flow_module.HumidityIntelligenceConfigFlow()
        flow.hass = self.hass
        await flow.async_step_gates({"enable_time_gate": False, "enable_presence_gate": False})
        self.assertEqual(flow._data["time_gate"]["start"], flow_module.DEFAULT_TIME_START)
        self.assertEqual(flow._data["time_gate"]["end"], flow_module.DEFAULT_TIME_END)
        self.assertEqual(flow._data["presence_gate"]["entities"], [])

    async def test_saved_slope_bindings_survive_names_and_prune_deleted_source(self):
        flow, entry = self.options()
        telemetry = [
            {"entity_id": "sensor.example_temp_a", "sensor_type": "temperature", "room": "Room A"},
            {"entity_id": "sensor.example_temp_b", "sensor_type": "temperature", "room": "Room B"},
        ]
        entry.data["telemetry"] = telemetry
        for suffix, room in (("x", "Room A"), ("y", "Room B")):
            self.hass.states.async_set("sensor.example_trend_" + suffix, "1", {"friendly_name": room + " slope"})
        values = {"slope_mode": "user_provided", "slope_sources": [item["entity_id"] for item in telemetry],
                  "slope_sensors": ["sensor.example_trend_y", "sensor.example_trend_x"]}
        result = await flow.async_step_options_slope(values)
        self.assertEqual(result["step_id"], "init")
        bindings = copy.deepcopy(flow._options["slope"]["bindings"])
        self.assertEqual(bindings["sensor.example_temp_a"], "sensor.example_trend_x")
        for suffix in ("x", "y"):
            self.hass.states.async_set("sensor.example_trend_" + suffix, "unavailable", {"friendly_name": "Renamed"})
        await flow.async_step_options_slope(values)
        self.assertEqual(flow._options["slope"]["bindings"], bindings)
        self.assertEqual(entry.options, {})
        flow._purge_deleted_telemetry_associations("sensor.example_temp_a", telemetry[1:])
        self.assertEqual(flow._options["slope"]["bindings"], {"sensor.example_temp_b": "sensor.example_trend_y"})

    async def test_real_registry_provider_identity_and_ambiguity(self):
        registry = er.async_get(self.hass)
        for provider in ("hacs", "marketplace"):
            entry = registry.async_get_or_create("update", provider, "1127166185")
            self.hass.states.async_set(entry.entity_id, "on", {
                "installed_version": "2.1.1", "latest_version": "2.1.2-beta.1",
                "in_progress": False,
            })
            result = observer.update_observation(self.hass)
            self.assertEqual(result["provider"], provider)
            self.assertEqual(result["status"], "reported_update")
            registry.async_remove(entry.entity_id)
        for provider in ("hacs", "marketplace"):
            registry.async_get_or_create("update", provider, "1127166185")
        self.assertEqual(observer.update_observation(self.hass)["reason"], "entity_ambiguous")

    async def test_real_states_and_runtime_imports(self):
        for name in ("sensor", "sensors.core", "automations.engine", "diagnostics"):
            importlib.import_module(PACKAGE + "." + name)
        self.hass.states.async_set("sensor.example_voc", ".6", {"unit_of_measurement": "ppm"})
        config = {"telemetry": [{"entity_id": "sensor.example_voc", "sensor_type": "voc", "level": "level1"}],
                  "aq": {"level1": {"enabled": True, "triggers": ["voc_bad"], "thresholds": {"voc_bad": 600}}}}
        self.assertEqual(aq.capture_configured_aq_evidence(self.hass, config)["bad_trigger_count"], 1)


if __name__ == "__main__":
    unittest.main()
