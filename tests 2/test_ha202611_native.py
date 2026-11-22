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
import voluptuous as vol

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

    async def test_voc_index_setup_and_options_preserve_concentration_and_source_identity(self):
        from uuid import UUID
        setup = flow_module.HumidityIntelligenceConfigFlow()
        setup.hass = self.hass
        missing = {"sensor_type": "voc", "entity_id": "sensor.example_missing",
                   "room": "Example", "friendly_name": "", "level": "level1"}
        setup._data["telemetry"] = setup._telemetry = [missing.copy()]
        result = await setup.async_step_telemetry_add({
            "entity_id": "sensor.example_index", "sensor_type": "voc_index", "room": "Example",
        })
        self.assertEqual(result["step_id"], "voc_index_edit")
        await setup.async_step_voc_index_edit({"entity_id": "sensor.example_index", "label": "Example"})
        row = setup._data["voc_index_sources"][0].copy()
        self.assertEqual(str(UUID(row["source_key"])), row["source_key"])
        self.assertEqual(setup._telemetry, [missing])

        flow, entry = self.options()
        entry.data.update(copy.deepcopy(setup._data))
        await flow.async_step_options_telemetry({"action": "voc_index"})
        await flow.async_step_voc_index({"source": row["source_key"]})
        await flow.async_step_voc_index_edit({"action": "cancel", "label": "Discard"})
        self.assertNotIn("voc_index_sources", flow._options)
        await flow.async_step_voc_index({"source": row["source_key"]})
        await flow.async_step_voc_index_edit({"label": "Renamed", "entity_id": row["entity_id"]})
        renamed = flow._options["voc_index_sources"][0]
        self.assertEqual(renamed, dict(row, label="Renamed"))
        await flow.async_step_voc_index({"source": "add"})
        for label, entity_id, field in [
            ("Second", missing["entity_id"], "entity_id"),
            ("Second", row["entity_id"], "entity_id"),
            ("Renamed", "sensor.example_other", "label"),
        ]:
            result = await flow.async_step_voc_index_edit({"entity_id": entity_id, "label": label})
            self.assertIn(field, result["errors"])
        await flow.async_step_voc_index_edit({"action": "cancel"})
        await flow.async_step_voc_index({"source": row["source_key"]})
        await flow.async_step_voc_index_edit({"label": "Rebound", "entity_id": "sensor.example_other"})
        rebound = flow._options["voc_index_sources"][0]
        self.assertNotEqual(row["source_key"], rebound["source_key"])
        await flow.async_step_voc_index({"source": rebound["source_key"]})
        await flow.async_step_voc_index_edit({"action": "delete"})
        saved = await flow.async_step_options_done()
        self.assertEqual(saved["data"]["voc_index_sources"], [])
        self.assertNotIn("telemetry", saved["data"])
        self.assertEqual(entry.data["telemetry"], [missing])
        entry.options = saved["data"]
        reopened = flow_module.HumidityIntelligenceOptionsFlow(entry)
        self.assertEqual(reopened._effective_config()["voc_index_sources"], [])
        self.assertEqual(reopened._effective_config()["telemetry"], [missing])

    async def test_voc_index_registry_rename_and_reused_id(self):
        from unittest.mock import patch
        backend = importlib.import_module(PACKAGE + ".helpers.voc_index")
        display = importlib.import_module(PACKAGE + ".sensors.voc_index")
        registry = er.async_get(self.hass)
        original = registry.async_get_or_create("sensor", "example", "voc-a", suggested_object_id="example_a")
        new_id = "sensor.example_renamed"
        flow, _ = self.options()
        await flow.async_step_voc_index({"source": "add"})
        await flow.async_step_voc_index_edit({"label": "A", "entity_id": original.entity_id})
        row, = flow._options["voc_index_sources"]
        self.assertNotEqual(row["provider_identity"], original.id)
        self.hass.states.async_set(original.entity_id, "17")
        sensor = display.HIVocIndexSources("hi_example_voc_index_sources", [row])
        sensor.entity_id, sensor.hass = "sensor.example_index_feed", self.hass
        cleanups = []
        with patch.object(sensor, "async_write_ha_state") as write, patch.object(sensor, "async_on_remove", side_effect=cleanups.append):
            await sensor.async_added_to_hass()
            self.assertEqual(sensor.native_value, 1)
            registry.async_update_entity(original.entity_id, new_entity_id=new_id)
            await self.hass.async_block_till_done()
            self.assertTrue(write.called)
            self.assertEqual(sensor.native_value, 0)
            flow._options["telemetry"] = [{"entity_id": "sensor.example_existing", "sensor_type": "iaq",
                                           "level": "level1", "room": "Example"}]
            for method in (flow.async_step_options_telemetry_add, flow.async_step_options_telemetry_edit):
                rejected = await method({"entity_id": new_id, "sensor_type": "iaq", "action": "save"})
                self.assertEqual(rejected["errors"].get("entity_id"), "duplicate_entity")
            registry.async_get_or_create("sensor", "example", "voc-b", suggested_object_id="example_a")
            self.hass.states.async_set(original.entity_id, "995")
            self.assertEqual(backend.source_counts(self.hass, [row])["unavailable"], 1)
            await flow.async_step_voc_index({"source": row["source_key"]})
            await flow.async_step_voc_index_edit({"label": "Old", "entity_id": original.entity_id})
            self.assertEqual(flow._options["voc_index_sources"][0]["provider_identity"], row["provider_identity"])
            await flow.async_step_voc_index({"source": "add"})
            duplicate = await flow.async_step_voc_index_edit({"label": "B", "entity_id": new_id})
            self.assertEqual(duplicate["errors"]["entity_id"], "duplicate_entity")
            await flow.async_step_voc_index({"source": row["source_key"]})
            await flow.async_step_voc_index_edit({"label": "Renamed", "entity_id": new_id})
            updated, = flow._options["voc_index_sources"]
            self.assertEqual(updated, dict(row, label="Renamed", entity_id=new_id))
            self.hass.states.async_set(new_id, "0")
            reading = backend.source_readings(self.hass, [updated])[row["source_key"]]
            self.assertEqual(reading, {"label": "Renamed", "status": "available", "value": 0})
            # Another newly added mapping has an independent key and proof, even for the same provider.
            second, _ = self.options()
            await second.async_step_voc_index({"source": "add"})
            await second.async_step_voc_index_edit({"label": "Separate", "entity_id": new_id})
            distinct, = second._options["voc_index_sources"]
            self.assertNotEqual(distinct["provider_identity"], updated["provider_identity"])
            registry.async_update_entity(new_id, disabled_by=er.RegistryEntryDisabler.USER)
            self.assertEqual(backend.source_counts(self.hass, [updated])["unavailable"], 1)
            self.assertEqual(backend.source_counts(self.hass, [dict(updated, provider_identity=None)])["unavailable"], 1)
            await flow.async_step_voc_index({"source": updated["source_key"]})
            await flow.async_step_voc_index_edit({"action": "delete"})
            await flow.async_step_voc_index({"source": "add"})
            await flow.async_step_voc_index_edit({"label": "Replacement", "entity_id": original.entity_id})
            replacement, = flow._options["voc_index_sources"]
            self.assertNotEqual(replacement["source_key"], row["source_key"])
            for cleanup in cleanups:
                cleanup()

    async def test_voc_index_observes_only_selected_sources_and_stops_on_removal(self):
        from unittest.mock import AsyncMock, patch

        display = importlib.import_module(PACKAGE + ".sensors.voc_index")
        entry = SimpleNamespace(entry_id="example_index")
        key = "00000000-0000-4000-8000-000000000005"
        entity_id = "sensor.example_selected_index"
        rows = [{"source_key": key, "entity_id": entity_id, "label": "Index A"}]
        created = []
        display.async_setup_index_sensor(self.hass, entry, created.extend, rows)
        sensor, = created
        sensor.hass = self.hass
        sensor.entity_id = "sensor.example_index_sources"
        self.assertEqual(sensor.unique_id, "hi_example_index_voc_index_sources")
        self.assertIn("readings", sensor._unrecorded_attributes)
        with patch.object(sensor, "async_write_ha_state") as write, patch.object(
            type(self.hass.services), "async_call", new_callable=AsyncMock
        ) as service, patch.object(sensor, "async_on_remove") as register_cleanup:
            await sensor.async_added_to_hass()
            self.assertEqual(sensor.native_value, 0)
            self.assertEqual(sensor.extra_state_attributes["readings"][key]["status"], "unavailable")
            self.hass.states.async_set("sensor.example_other_index", "25")
            await self.hass.async_block_till_done()
            write.assert_not_called()
            self.hass.states.async_set(entity_id, "0")
            await self.hass.async_block_till_done()
            write.assert_called_once()
            self.assertEqual(sensor.native_value, 1)
            self.assertEqual(sensor.extra_state_attributes["readings"][key]["value"], 0)
            register_cleanup.call_args.args[0]()
            self.hass.states.async_set(entity_id, "20")
            await self.hass.async_block_till_done()
            write.assert_called_once()
            service.assert_not_called()

    async def test_voc_index_removal_retires_only_its_registered_sensor(self):
        from types import MappingProxyType
        from homeassistant.config_entries import ConfigEntry

        display = importlib.import_module(PACKAGE + ".sensors.voc_index")
        entry = ConfigEntry(domain="humidity_intelligence", version=1, minor_version=1,
                            title="Example HI", source="user", unique_id=None,
                            discovery_keys=MappingProxyType({}), subentries_data=[], data={}, options={})
        self.hass.config_entries._entries[entry.entry_id] = entry
        registry = er.async_get(self.hass)
        unique_id = f"hi_{entry.entry_id}_voc_index_sources"
        feed = registry.async_get_or_create("sensor", "humidity_intelligence", unique_id,
                                            suggested_object_id="example_renamed_feed", config_entry=entry)
        other = registry.async_get_or_create("sensor", "humidity_intelligence", unique_id + "_other",
                                             suggested_object_id="example_other_feed", config_entry=entry)
        created = []
        display.async_setup_index_sensor(self.hass, entry, created.extend, None)
        self.assertIsNotNone(registry.async_get(feed.entity_id))
        display.async_setup_index_sensor(self.hass, entry, created.extend, [])
        self.assertIsNone(registry.async_get(feed.entity_id))
        self.assertIsNotNone(registry.async_get(other.entity_id))
        self.assertFalse(created)

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

    async def test_presence_entity_replacement_requires_mapping_in_setup_and_options(self):
        engine_class = importlib.import_module(PACKAGE + ".automations.engine").HIAutomationEngine
        self.hass.states.async_set("person.example", "home")
        self.hass.states.async_set("binary_sensor.example_presence", "on")
        for setup in (False, True):
            with self.subTest(setup=setup):
                flow, entry = self.options()
                before = copy.deepcopy(entry.data)
                if setup:
                    flow = flow_module.HumidityIntelligenceConfigFlow()
                    flow.hass = self.hass
                    flow._data = copy.deepcopy(before)
                gates = flow.async_step_gates if setup else flow.async_step_options_gates
                states = flow.async_step_presence_states if setup else flow.async_step_options_presence_states
                await gates({"enable_presence_gate": False})
                form = await gates()
                values = {"enable_presence_gate": True, "presence_entities": ["binary_sensor.example_presence"]}
                schema = form["data_schema"]
                if hasattr(data_entry_flow, "_strip_hidden_fields"):
                    schema, values = data_entry_flow._strip_hidden_fields(schema, values)
                form = await gates(schema(values))
                with self.assertRaises(vol.Invalid):
                    form["data_schema"]({})
                rejected = await states({})
                self.assertEqual(rejected["errors"], {"present_states": "required"})
                await states(form["data_schema"]({"present_states": ["on"], "away_states": ["off"]}))
                cfg = flow._data if setup else flow._options
                self.assertEqual(cfg["presence_gate"]["present_states"], ["on"])
                engine = engine_class(self.hass, SimpleNamespace(entry_id="example_mapping", data=cfg, options={}))
                self.assertTrue(engine._gate_evaluation().allowed)
                self.assertEqual(entry.data, before)
                self.assertEqual(entry.options, {})
                # An intentionally empty mapping remains empty on later visits.
                await states({"present_states": [], "away_states": []})
                form = await states()
                self.assertEqual(form["data_schema"]({}), {"present_states": [], "away_states": []})

    async def test_presence_changed_while_disabled_stays_unmapped_after_save(self):
        flow, entry = self.options()
        self.hass.states.async_set("binary_sensor.example_presence", "unknown")
        await flow.async_step_options_gates({
            "enable_presence_gate": False, "presence_entities": ["binary_sensor.example_presence"],
        })
        staged = copy.deepcopy(flow._options)
        self.assertNotIn("present_states", staged["presence_gate"])
        self.assertEqual(entry.options, {})
        # Simulate the explicit final save and a fresh Options session.
        entry.options = staged
        reopened = flow_module.HumidityIntelligenceOptionsFlow(entry)
        reopened.hass = self.hass
        form = await reopened.async_step_options_gates({"enable_presence_gate": True})
        with self.assertRaises(vol.Invalid):
            form["data_schema"]({})
        self.assertEqual(entry.options, staged)

    async def test_presence_reordered_entities_keep_custom_mapping_and_error_values(self):
        flow, entry = self.options()
        entry.data["presence_gate"] = {
            "enabled": True, "entities": ["person.example", "person.example_other"],
            "present_states": ["custom_present"], "away_states": ["custom_away"],
        }
        before = copy.deepcopy(entry.data)
        form = await flow.async_step_options_gates({
            "enable_presence_gate": True, "presence_entities": ["person.example_other", "person.example"],
        })
        self.assertEqual(form["data_schema"]({}), {"present_states": ["custom_present"], "away_states": ["custom_away"]})
        form = await flow.async_step_options_presence_states({"present_states": ["custom"], "away_states": ["custom"]})
        self.assertEqual(form["errors"], {"away_states": "overlap"})
        self.assertEqual(form["data_schema"]({}), {"present_states": ["custom"], "away_states": ["custom"]})
        self.assertEqual(entry.data, before)
        self.assertEqual(entry.options, {})

    async def test_setup_gate_revisit_renders_and_resubmits_staged_values(self):
        flow = flow_module.HumidityIntelligenceConfigFlow()
        flow.hass = self.hass
        _options, entry = self.options()
        flow._data.update(copy.deepcopy(entry.data))
        flow._data["engine_interval_minutes"] = 8
        flow._data["custom_target_low"] = 42.0
        flow._data["custom_target_high"] = 54.0
        before = copy.deepcopy(flow._data)
        result = await flow.async_step_gates()
        markers = {key.schema: key for key in result["data_schema"].schema}
        for key, expected in {
            "enable_time_gate": True, "start_time": "06:15", "end_time": "22:45",
            "outside_action": "pause", "enable_presence_gate": True,
            "presence_entities": ["person.example"],
        }.items():
            self.assertEqual(markers[key].default(), expected)
        submitted = {key: markers[key].default() for key in (
            "enable_time_gate", "enable_presence_gate", "start_time", "end_time",
            "outside_action", "presence_entities",
        )}
        # Leave Advanced collapsed, as the real frontend may omit that section.
        result = await flow.async_step_gates(result["data_schema"](submitted))
        self.assertEqual(result["step_id"], "presence_states")
        await flow.async_step_presence_states(result["data_schema"]({}))
        for key in ("time_gate", "presence_gate", "engine_interval_minutes", "custom_target_low", "custom_target_high"):
            self.assertEqual(flow._data[key], before[key])
        # Revisit, disable (HA 2026.11 omits hidden fields), then re-enable.
        for enabled in (False, True):
            result = await flow.async_step_gates()
            schema = result["data_schema"]
            submitted = {"enable_time_gate": enabled, "enable_presence_gate": enabled}
            if hasattr(data_entry_flow, "_strip_hidden_fields"):
                schema, submitted = data_entry_flow._strip_hidden_fields(schema, submitted)
            await flow.async_step_gates(schema(submitted))
            self.assertEqual(flow._data["time_gate"]["start"], "06:15")
            self.assertEqual(flow._data["time_gate"]["end"], "22:45")
            self.assertEqual(flow._data["presence_gate"]["entities"], ["person.example"])
            self.assertEqual(flow._data["presence_gate"]["present_states"], ["home"])
            self.assertEqual(flow._data["engine_interval_minutes"], 8)
        result = await flow.async_step_presence_states({"present_states": ["away"], "away_states": ["away"]})
        self.assertEqual(result["errors"]["away_states"], "overlap")
        markers = {key.schema: key for key in result["data_schema"].schema}
        self.assertEqual(markers["present_states"].default(), ["away"])
        self.assertEqual(flow._data["presence_gate"]["present_states"], ["home"])
        await flow.async_step_presence_states({"present_states": [], "away_states": []})
        result = await flow.async_step_presence_states()
        self.assertEqual(result["data_schema"]({}), {"present_states": [], "away_states": []})
        result = await flow.async_step_gates()
        await flow.async_step_gates(result["data_schema"]({
            "enable_time_gate": True, "enable_presence_gate": True, "presence_entities": [],
        }))
        self.assertEqual(flow._data["presence_gate"]["entities"], [])

    async def test_options_rejects_unmatched_residual_slope_without_changing_saved_pairs(self):
        flow, entry = self.options()
        entry.data["telemetry"] = [
            {"entity_id": "sensor.example_temp_a", "sensor_type": "temperature", "room": "Room A"},
            {"entity_id": "sensor.example_temp_b", "sensor_type": "temperature", "room": "Room B"},
        ]
        entry.data["slope"] = {"mode": "user_provided",
            "source_entities": ["sensor.example_temp_a"],
            "provided_sensors": ["sensor.example_trend_x"],
            "bindings": {"sensor.example_temp_a": "sensor.example_trend_x"}}
        self.hass.states.async_set("sensor.example_trend_z", "1", {"friendly_name": "Room A slope"})
        before = copy.deepcopy(entry.data)
        result = await flow.async_step_options_slope({
            "slope_mode": "user_provided",
            "slope_sources": ["sensor.example_temp_a", "sensor.example_temp_b"],
            "slope_sensors": ["sensor.example_trend_x", "sensor.example_trend_z"],
        })
        self.assertEqual(result["errors"]["slope_sensors"], "ambiguous_slope_mapping")
        self.assertNotIn("slope", flow._options)
        self.assertEqual(entry.data, before)
        self.assertEqual(entry.options, {})

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
