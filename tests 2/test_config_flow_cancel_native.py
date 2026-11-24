"""Cancel/return transaction regressions with native Home Assistant flow schemas.

Run directly in a supported HA environment, separately from stub-based tests:
    python 'tests 2/test_config_flow_cancel_native.py'
No integration setup, live target, or device services are used.
"""
import copy
from functools import partial
import gc
import importlib
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType, ModuleType, SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

from homeassistant import core as ha_core
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.helpers import (
    area_registry, device_registry, entity_registry, issue_registry, label_registry,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hi_cancel_native'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'custom_components/humidity_intelligence')]
sys.modules[PACKAGE] = package
config_flow = importlib.import_module(PACKAGE + '.config_flow')
HA_INSTANCES = []


def tearDownModule():
    """Collect stopped fixture cycles before extension modules are finalized.

    orjson.Fragment retained in cycles can crash during interpreter shutdown in
    the pinned native environment. This is fixture cleanup, not an upstream fix;
    see docs/config-flow-testing.md for the independent reproducer and limits.
    """
    # Registry singleton caches otherwise own stopped instances until module
    # destruction. Clear only the native registries used by this isolated suite.
    for registry in (
        area_registry, device_registry, entity_registry, issue_registry, label_registry,
    ):
        # Older supported HA versions also cache the device registry; newer
        # getters may read hass.data directly and expose no singleton cache.
        clear_cache = getattr(registry.async_get, 'cache_clear', None)
        if callable(clear_cache):
            clear_cache()
    gc.collect()
    if any(reference() is not None for reference in HA_INSTANCES):
        raise AssertionError('Native flow fixture retained a Home Assistant instance')
    HA_INSTANCES.clear()


class NativeCancelTests(unittest.IsolatedAsyncioTestCase):
    async def stop_hass(self, hass):
        """Finish writes and release the test-owned thread-local HA reference."""
        try:
            if hass.state is not ha_core.CoreState.stopped:
                await hass.async_stop(force=True)
        finally:
            # HA's native test fixtures also reset this per-thread reference.
            if ha_core.async_get_hass_or_none() is hass:
                ha_core._hass.__dict__.clear()
            if getattr(self, 'hass', None) is hass:
                self.hass = None

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hass = HomeAssistant(self.temp.name)
        HA_INSTANCES.append(weakref.ref(self.hass))
        # This fixture never starts HA. force=True runs its shutdown lifecycle
        # even in not_running state, before the temporary storage is removed.
        self.addAsyncCleanup(self.stop_hass, self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        setup = getattr(device_registry, "async_setup", None)
        if setup is not None:
            setup(self.hass)
        await device_registry.async_load(self.hass)
        await entity_registry.async_load(self.hass)
        await area_registry.async_load(self.hass)
        self.sensor = dict(entity_id='sensor.example_humidity', sensor_type='humidity',
                           level='level1', room='Example room', friendly_name='Example room')
        self.entry = SimpleNamespace(data={'telemetry': [self.sensor]}, options={})

    def flow(self, options=False):
        if options:
            flow = config_flow.HumidityIntelligenceOptionsFlow(self.entry)
        else:
            flow = config_flow.HumidityIntelligenceConfigFlow()
            flow._telemetry = [copy.deepcopy(self.sensor)]
            flow._data['telemetry'] = flow._telemetry
            flow._data['telemetry_edit_index'] = 0
        flow.hass = self.hass
        return flow

    async def test_zone_thresholds_share_the_selected_zone_and_wait_for_final_save(self):
        from homeassistant import config_entries

        original = {
            "enabled": False, "level": "level1", "rooms": ["Example room"], "ui_label": "Cooking",
            "outputs": ["fan.example"], "output_level": 66, "boost_output_level": "100%",
            "triggers": ["legacy", "humidity_high"], "thresholds": {
                "humidity_high": "7", "mould_risk": 8, "legacy": "keep",
            }, "legacy_key": 8,
        }
        entry = ConfigEntry(domain="humidity_intelligence", version=1, minor_version=1,
            title="Example HI", source="user", unique_id=None, discovery_keys=MappingProxyType({}),
            subentries_data=[], data={"telemetry": [self.sensor], "zones": {"zone1": {"enabled": True}}},
            options={"zones": {"zone2": copy.deepcopy(original)}, "level_labels": {"level1": "Lower"}})
        manager = self.hass.config_entries
        manager._entries[entry.entry_id] = entry
        with patch.object(config_entries, "_async_get_flow_handler",
                          return_value=config_flow.HumidityIntelligenceConfigFlow):
            root = await manager.options.async_init(entry.entry_id)
        post = partial(manager.options.async_configure, root["flow_id"])
        picker = await post({"next_step_id": "options_zones"})
        choice = next(iter(picker["data_schema"].schema.values()))
        self.assertEqual([opt["value"] for opt in choice.config["options"]],
                         ["zone2", "zone1", "level_labels", "done"])
        self.assertIn("Lower", choice.config["options"][0]["label"])
        await post({"action": "zone2"})
        # A populated Advanced section includes old values and unselected controls.
        advanced = {"threshold_humidity_high": "7", "threshold_mould_risk": "8",
                    "threshold_condensation_risk": "", "threshold_air_quality_bad": "63"}
        result = await post({"show_advanced_options": {**advanced, "threshold_humidity_high": "NaN"}})
        self.assertIn("threshold_humidity_high", result["errors"])
        await post({"show_advanced_options": advanced})
        self.assertEqual(entry.options["zones"], {"zone2": original})
        await post({"action": "level_labels"})
        await post({"level1_label": "Lower", "level2_label": "Upper"})
        await post({"action": "done"})
        await post({"next_step_id": "options_done"})
        self.assertEqual(entry.options["zones"], {"zone2": {**original, "thresholds": {
            **original["thresholds"], "air_quality_bad": 63}}})
        self.assertEqual(entry.data["zones"], {"zone1": {"enabled": True}})

    async def test_zone_empty_slot_discard_trigger_defaults_and_unreadable_limits(self):
        other = {"enabled": False, "level": "level1", "thresholds": {"legacy": 21}}
        self.entry.data["zones"] = {"zone1": copy.deepcopy(other)}
        flow = self.flow(True)
        self.assertEqual((await flow.async_step_options_zone_edit({"enabled": True}))["step_id"], "options_zones")
        empty = await flow.async_step_options_zones({"action": "zone2"})
        cancel = empty["data_schema"]({"action": "back", "enabled": True,
                                      "show_advanced_options": {"threshold_humidity_high": "999"}})
        await flow.async_step_options_zone_edit(cancel)
        self.assertNotIn("zones", flow._options)
        empty = await flow.async_step_options_zones({"action": "zone2"})
        # Submitting default values also keeps a truly empty slot empty.
        await flow.async_step_options_zone_edit(empty["data_schema"]({"show_advanced_options": {}}))
        self.assertNotIn("zones", flow._options)
        empty = await flow.async_step_options_zones({"action": "zone2"})
        changes = empty["data_schema"]({"triggers": ["humidity_high", "air_quality_bad"],
                                        "show_advanced_options": {"threshold_air_quality_bad": "67.5"}})
        await flow.async_step_options_zone_edit(changes)
        zone = flow._options["zones"]["zone2"]
        self.assertFalse(zone["enabled"])
        self.assertEqual(zone["level"], "level2")
        self.assertEqual(zone["thresholds"], {"humidity_high": 5, "air_quality_bad": 67.5})
        self.assertEqual(flow._options["zones"]["zone1"], other)
        await flow.async_step_options_cancel_confirm({"action": "close"})
        self.assertEqual(self.entry.data["zones"], {"zone1": other})
        self.assertEqual(self.entry.options, {})

        self.entry.data["zones"]["zone1"]["thresholds"] = ["old format"]
        flow = self.flow(True)
        editor = await flow.async_step_options_zones({"action": "zone1"})
        result = await flow.async_step_options_zone_edit(editor["data_schema"]({
            "show_advanced_options": {"threshold_mould_risk": "2"}}))
        self.assertEqual(result["errors"]["base"], "unrecognised_zone_thresholds")
        self.assertNotIn("zones", flow._options)
        self.assertEqual(self.entry.data["zones"]["zone1"]["thresholds"], ["old format"])

    async def test_unreadable_zone_data_cannot_be_activated_by_enabling_or_adding_outputs(self):
        for stored, update in (
            ({"enabled": False, "outputs": ["fan.example"]}, {"enabled": True}),
            ({"enabled": True, "outputs": []}, {"outputs": ["fan.example"]}),
        ):
            for corruption, error in (
                ({"thresholds": ["old format"]}, "unrecognised_zone_thresholds"),
                ({"triggers": ["humidity_high", {"old": "format"}]}, "unrecognised_zone_settings"),
            ):
                with self.subTest(stored=stored, corruption=corruption):
                    zone = {"triggers": ["humidity_high"], **stored, **corruption}
                    self.entry.data["zones"] = {"zone2": copy.deepcopy(zone)}
                    flow = self.flow(True)
                    form = await flow.async_step_options_zones({"action": "zone2"})
                    failed = await flow.async_step_options_zone_edit(form["data_schema"](update))
                    self.assertEqual(failed["errors"]["base"], error)
                    self.assertNotIn("zones", flow._options)
                    self.assertEqual(self.entry.data["zones"]["zone2"], zone)

        self.entry.data["zones"]["zone2"] = {
            "enabled": True, "triggers": ["humidity_high"], "outputs": ["fan.example"], "thresholds": ["old"],
        }
        flow = self.flow(True)
        form = await flow.async_step_options_zones({"action": "zone2"})
        with self.assertNoLogs(config_flow._LOGGER, level="WARNING"):
            await flow.async_step_options_zone_edit(form["data_schema"]({"enabled": False}))
        self.assertEqual(flow._options["zones"]["zone2"], {**self.entry.data["zones"]["zone2"], "enabled": False})

    async def test_profile_edits_preserve_legacy_aliases_gates_and_dormant_limits(self):
        seasonal = importlib.import_module(PACKAGE + ".helpers.seasonal")
        self.entry.data.update({
            "target_profile_mode": "custom", "target_custom": {"low": "43.5", "high": "57.5"},
            "time_gate": {"enabled": True}, "presence_gate": {"enabled": False}, "alert_only_mode": True,
            "zones": {"zone2": {"enabled": False}},
        })
        self.entry.options = {"temperature_comfort_mode": "auto"}
        before = copy.deepcopy(self.entry.data)
        flow = self.flow(True)
        form = await flow.async_step_options_thresholds()
        populated = form["data_schema"]({"humidity_targets": {}, "temperature_comfort": {}})
        self.assertEqual(populated["humidity_targets"], {
            "target_profile": "custom", "custom_target_low": 43.5, "custom_target_high": 57.5,
        })
        await flow.async_step_options_thresholds(populated)
        self.assertEqual(flow._options, self.entry.options)
        populated["temperature_comfort"] = {
            "temperature_comfort_mode": "custom", "temperature_comfort_custom_low": 18.5,
            "temperature_comfort_custom_high": 22,
        }
        await flow.async_step_options_thresholds(form["data_schema"](populated))
        self.assertEqual(flow._options, populated["temperature_comfort"])
        self.assertEqual(seasonal.resolve_target_profile(flow._effective_config()), seasonal.resolve_target_profile(before))

        for selected in ("winter", "custom"):
            form = await flow.async_step_options_thresholds()
            submission = form["data_schema"]({"humidity_targets": {"target_profile": selected}, "temperature_comfort": {}})
            await flow.async_step_options_thresholds(submission)
            self.assertEqual(seasonal.resolve_target_profile(flow._effective_config()).key, selected)
        self.assertEqual(self.entry.options, {"temperature_comfort_mode": "auto"})
        self.assertEqual(self.entry.data, before)
        saved = await flow.async_step_options_done()
        self.assertEqual(saved["data"], {**populated["temperature_comfort"], "target_profile": "custom", "alerts": []})

    async def test_dormant_legacy_profile_limits_require_repair_before_custom_activation(self):
        for group, mode, low, high, valid_low, valid_high in (
            ("humidity_targets", "target_profile", "custom_target_low", "custom_target_high", 45, 55),
            ("temperature_comfort", "temperature_comfort_mode", "temperature_comfort_custom_low",
             "temperature_comfort_custom_high", 19, 21),
        ):
            for bad in (99, "old"):
                with self.subTest(group=group, bad=bad):
                    self.entry.options = {mode: "auto", low: valid_low, high: bad}
                    flow = self.flow(True)
                    form = await flow.async_step_options_thresholds()
                    self.assertTrue(form["description_placeholders"]["range_notes"])
                    populated = form["data_schema"]({group: {}})
                    self.assertNotIn(high, populated[group])
                    await flow.async_step_options_thresholds(populated)
                    self.assertEqual(flow._options, self.entry.options)
                    populated[group][mode] = "custom"
                    error = await flow.async_step_options_thresholds(populated)
                    self.assertTrue(error["errors"])
                    self.assertEqual(flow._options, self.entry.options)
                    populated[group][high] = valid_high
                    await flow.async_step_options_thresholds(error["data_schema"](populated))
                    self.assertEqual(flow._options, {mode: "custom", low: valid_low, high: valid_high})
                    self.assertEqual(self.entry.options[high], bad)

    async def test_profile_invalid_pair_is_atomic_and_existing_incomplete_custom_can_remain_unedited(self):
        self.entry.options = {"target_profile": "custom", "custom_target_low": 48}
        flow = self.flow(True)
        form = await flow.async_step_options_thresholds()
        fields = form["data_schema"]({"humidity_targets": {}, "temperature_comfort": {}})
        self.assertNotIn("custom_target_high", fields["humidity_targets"])
        fields["temperature_comfort"]["temperature_comfort_mode"] = "custom"
        await flow.async_step_options_thresholds(fields)
        self.assertNotIn("custom_target_high", flow._options)
        saved = copy.deepcopy(flow._options)
        error = await flow.async_step_options_thresholds(form["data_schema"]({
            "temperature_comfort": {"temperature_comfort_mode": "auto"},
            "humidity_targets": {"custom_target_low": 55, "custom_target_high": 54},
        }))
        self.assertEqual(error["errors"]["base"], "humidity_range_invalid")
        self.assertEqual(flow._options, saved)

    async def test_setup_and_later_options_present_the_same_uninspectable_addons(self):
        from homeassistant import data_entry_flow

        flow = self.flow()
        form = await flow.async_step_alerts_done()
        later = await self.flow(True).async_step_options_dependencies()
        compact = form["description_placeholders"]["dependencies"]
        detailed = later["description_placeholders"]["dependencies"]
        for dep in importlib.import_module(PACKAGE + ".const").DEPENDENCIES:
            self.assertIn(dep["name"], compact)
            self.assertIn(dep["name"], detailed)
        self.assertIn("Not inspectable", compact)
        self.assertIn("Not inspectable", detailed)
        self.assertNotIn("https://", compact)
        self.assertIn("https://", detailed)
        for layouts in ([], ["v2_mobile"], ["v2_tablet"]):
            result = await flow.async_step_ui_install(form["data_schema"]({"ui_layouts": layouts, "skip": True}))
            self.assertEqual(result["type"], data_entry_flow.FlowResultType.CREATE_ENTRY)
            self.assertEqual(result["data"]["ui_layouts"], layouts)
            self.assertTrue(result["data"]["skip_dependencies"])

    async def test_all_six_callers_return_to_origin_and_preserve_unsubmitted_fields(self):
        for options in (False, True):
            prefix = 'options_' if options else ''
            for suffix in ('add', 'manage', 'edit'):
                with self.subTest(options=options, form=suffix):
                    flow = self.flow(options)
                    step = prefix + 'telemetry_' + suffix
                    confirm = getattr(flow, 'async_step_' + prefix + 'cancel_confirm')
                    values = {'selection': '0'} if suffix == 'manage' else {
                        'entity_id': 'sensor.example_other', 'room': 'Draft room',
                        'level': 'level2', 'sensor_type': 'temperature'}
                    before = copy.deepcopy(flow._options if options else flow._data)
                    result = await getattr(flow, 'async_step_' + step)({'action': 'cancel', **values})
                    self.assertEqual(result['step_id'], prefix + 'cancel_confirm')
                    result = await confirm({'action': 'return'})
                    self.assertEqual(result['step_id'], step)
                    fields = {key.schema: key for key in result['data_schema'].schema}
                    for key, value in values.items():
                        self.assertEqual(fields[key].description['suggested_value'], value)
                    self.assertNotEqual(fields['action'].default(), 'cancel')
                    action = result['data_schema'].schema[fields['action']]
                    self.assertEqual(action.config['mode'], 'list')
                    self.assertEqual(flow._options if options else flow._data, before)
                    self.assertEqual(self.entry.options, {})
                    self.assertEqual(self.entry.data['telemetry'], [self.sensor])

    async def test_return_keeps_nested_advanced_draft_finish_alone_emits_saved_options(self):
        flow = self.flow(True)
        result = await flow.async_step_options_slope({
            'slope_mode': 'hi_calculates',
            'show_advanced_options': {'slope_sources': ['sensor.example_temperature'],
                                      'slope_sensors': [], 'show_temperature_chips': True}})
        self.assertEqual(result['step_id'], 'init')
        staged = copy.deepcopy(flow._options)
        self.assertEqual(staged['slope']['source_entities'], ['sensor.example_temperature'])
        self.assertTrue(staged['slope']['show_temperature_chips'])
        await flow.async_step_options_telemetry_edit({'action': 'cancel', 'room': 'Draft room'})
        await flow.async_step_options_cancel_confirm({'action': 'return'})
        self.assertEqual(flow._options, staged)
        self.assertEqual(self.entry.options, {})
        await flow.async_step_options_telemetry_edit({'action': 'save', 'room': 'Draft room'})
        self.assertEqual(self.entry.data['telemetry'][0]['room'], 'Example room')
        self.assertEqual(self.entry.options, {})
        result = await flow.async_step_options_done()
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['slope'], staged['slope'])
        self.assertEqual(result['data']['telemetry'][0]['room'], 'Draft room')

    async def test_close_discards_staged_changes_and_reopen_uses_saved_values(self):
        self.entry.options = {'slope': {'mode': 'none', 'source_entities': [],
                                        'show_temperature_chips': False}}
        saved = copy.deepcopy(self.entry.options)
        flow = self.flow(True)
        await flow.async_step_options_slope({
            'slope_mode': 'hi_calculates',
            'show_advanced_options': {'slope_sources': ['sensor.example_temperature'],
                                      'show_temperature_chips': True}})
        await flow.async_step_options_telemetry_add({'action': 'cancel'})
        result = await flow.async_step_options_cancel_confirm({'action': 'close'})
        self.assertEqual(result['type'], 'abort')
        self.assertEqual(result['reason'], 'user_cancelled')
        self.assertEqual(self.entry.options, saved)
        self.assertEqual(self.flow(True)._options, saved)
        setup = self.flow()
        await setup.async_step_telemetry_edit({'action': 'cancel', 'room': 'Draft room'})
        self.assertEqual((await setup.async_step_cancel_confirm({'action': 'close'}))['type'], 'abort')
        self.assertEqual(setup._data['telemetry'][0]['room'], 'Example room')

    async def test_unknown_destination_cannot_invoke_save(self):
        for options in (False, True):
            flow = self.flow(options)
            prefix = 'options_' if options else ''
            flow._cancel_return_step = 'options_done'
            result = await getattr(flow, 'async_step_' + prefix + 'cancel_confirm')({'action': 'return'})
            self.assertEqual(result['step_id'], prefix + 'telemetry')
            self.assertEqual(self.entry.options, {})

    async def test_aq_additions_back_retry_and_save_through_native_manager(self):
        from homeassistant import config_entries

        telemetry = [
            {'sensor_type': 'voc', 'level': None},
            {'sensor_type': 'pm25', 'level': 'level2'},
        ]
        sibling = {'enabled': True, 'triggers': ['co2_high'], 'thresholds': {'co2_high': 1450}}
        lane = {'enabled': False, 'triggers': ['iaq_bad', 'legacy'], 'outputs': [],
                'run_duration': 30, 'output_level': 'auto',
                'thresholds': {'pm25_high': '41', 'legacy': 19}}
        entry = ConfigEntry(domain='humidity_intelligence', version=1, minor_version=1,
            title='Example HI', source='user', unique_id=None, discovery_keys=MappingProxyType({}),
            subentries_data=[], data={'telemetry': telemetry, 'aq': {'level1': sibling, 'level2': lane}},
            options={})
        manager = self.hass.config_entries
        manager._entries[entry.entry_id] = entry
        # Only package discovery is substituted. HA dispatches, validates and saves the flow.
        with patch.object(config_entries, '_async_get_flow_handler',
                          return_value=config_flow.HumidityIntelligenceConfigFlow):
            root = await manager.options.async_init(entry.entry_id)
        post = partial(manager.options.async_configure, root['flow_id'])
        await post({'next_step_id': 'options_aq'})
        await post({'action': 'level2'})
        additions = {'triggers': ['iaq_bad', 'pm25_high', 'co2_high']}
        review = await post(additions)
        self.assertEqual(review['step_id'], 'options_aq_thresholds')
        self.assertIn('41', review['description_placeholders']['threshold_sources'])
        # Even an invalid number must not block Back or save the pending selection.
        back = await post({'action': 'back', 'threshold_co2_high': '9999', 'threshold_pm25_high': ''})
        self.assertEqual(back['step_id'], 'options_aq_edit')
        trigger_key = next(k for k in back['data_schema'].schema if k.schema == 'triggers')
        self.assertEqual(trigger_key.default(), ['iaq_bad'])
        await post(additions)
        invalid = await post({'action': 'confirm', 'threshold_co2_high': 'NaN', 'threshold_pm25_high': '42'})
        self.assertIn('threshold_co2_high', invalid['errors'])
        await post({'action': 'confirm', 'threshold_co2_high': '1200', 'threshold_pm25_high': '42'})
        await post({'action': 'done'})
        await post({'next_step_id': 'options_output_observation'})
        await post({'next_step_id': 'options_output_cancel'})
        self.assertEqual(dict(entry.options), {})
        await post({'next_step_id': 'options_done'})
        self.assertEqual(entry.options['aq']['level1'], sibling)
        levels = entry.options['aq']['level2']
        self.assertFalse(levels['enabled'])
        self.assertEqual(levels['triggers'], ['iaq_bad', 'legacy', 'pm25_high', 'co2_high'])
        self.assertEqual(levels['thresholds'], {'pm25_high': 42, 'co2_high': 1200, 'legacy': 19})
        self.assertEqual(entry.data['aq']['level2'], lane)
        self.assertEqual(entry.data['telemetry'], telemetry)
        self.assertNotIn('output_observation', entry.options)

    async def test_aq_missing_and_legacy_values_require_explicit_repair(self):
        saved = {'iaq_bad': '72', 'voc_bad': 1200, 'legacy': 123}
        self.entry.options = {'aq': {'level2': {
            'triggers': ['iaq_bad', 'voc_bad', 'co_warning'], 'thresholds': copy.deepcopy(saved)}}}
        flow = self.flow(True)
        editor = await flow.async_step_options_aq({'action': 'level2'})
        payload = editor['data_schema']({'show_advanced_options': {'threshold_iaq_bad': 'NaN'}})
        self.assertTrue((await flow.async_step_options_aq_edit(payload))['errors'])
        self.assertEqual(flow._section('aq', {})['level2']['thresholds'], saved)
        editor = await flow.async_step_options_aq_edit()
        ordinary = editor['data_schema']({'show_advanced_options': {}})
        result = await flow.async_step_options_aq_edit(ordinary)
        self.assertEqual(result['step_id'], 'options_aq')
        self.assertEqual(flow._options['aq']['level2']['thresholds'], saved)
        editor = await flow.async_step_options_aq({'action': 'level2'})
        request = editor['data_schema']({'show_advanced_options': {'set_thresholds': ['voc_bad']}})
        review = await flow.async_step_options_aq_edit(request)
        self.assertIn('1200', review['description_placeholders']['threshold_sources'])
        self.assertIn('outside the editable range', review['description_placeholders']['threshold_sources'])
        await flow.async_step_options_aq_thresholds({'action': 'confirm', 'threshold_voc_bad': '650'})
        self.assertEqual(flow._options['aq']['level2']['thresholds'], {**saved, 'voc_bad': 650})
        await flow.async_step_options_cancel_confirm({'action': 'close'})
        self.assertEqual(self.entry.options['aq']['level2']['thresholds'], saved)

    async def test_aq_level_routes_and_abandoned_review(self):
        setup = self.flow()
        setup._telemetry = [{'sensor_type': 'voc'}, {'sensor_type': 'co', 'level': 'unknown'}]
        self.assertEqual((await setup.async_step_aq())['step_id'], 'aq_skip')
        setup._telemetry.append({'sensor_type': 'co2', 'level': 'level2'})
        menu = await setup.async_step_aq()
        self.assertEqual(menu['menu_options'], ['aq_level2', 'aq_done', 'aq_back'])
        self.entry.data['aq'] = {'level1': {'thresholds': {'co2_high': 1000}},
                                 'legacy-level': {'triggers': ['co2_high']}}
        self.entry.data['telemetry'] = copy.deepcopy(setup._telemetry)
        flow = self.flow(True)
        self.assertEqual((await flow.async_step_options_aq_edit({'remove_lane': True}))['step_id'], 'options_aq')
        await flow.async_step_options_aq({'action': 'level2'})
        await flow.async_step_options_aq_edit({'triggers': ['co_warning']})
        another = self.flow(True)
        self.assertEqual((await another.async_step_options_aq_thresholds({'action': 'confirm'}))['step_id'], 'options_aq')
        await flow.async_step_options_aq({'action': 'legacy-level'})
        self.assertEqual((await flow.async_step_options_aq_thresholds({'action': 'confirm'}))['step_id'], 'options_aq')
        self.assertEqual(flow._options, {})
        await flow.async_step_options_aq({'action': 'legacy-level'})
        await flow.async_step_options_aq_edit({'remove_lane': True})
        self.assertEqual(flow._options['aq'], {'level1': {'thresholds': {'co2_high': 1000}}})
        self.assertIn('legacy-level', self.entry.data['aq'])

    async def test_aq_review_preserves_a_changed_lane_and_unrecognised_thresholds(self):
        self.entry.data['aq'] = {'level2': {'triggers': ['voc_bad'], 'thresholds': {'voc_bad': 400}}}
        flow = self.flow(True)
        await flow.async_step_options_aq({'action': 'level2'})
        await flow.async_step_options_aq_edit({'triggers': ['voc_bad', 'co2_high']})
        self.entry.data['aq']['level2']['thresholds']['voc_bad'] = 550
        result = await flow.async_step_options_aq_thresholds({'action': 'confirm', 'threshold_co2_high': '1200'})
        self.assertEqual(result['step_id'], 'options_aq')
        self.assertEqual(flow._options, {})
        self.entry.data['aq']['level2']['thresholds'] = ['old format']
        await flow.async_step_options_aq({'action': 'level2'})
        result = await flow.async_step_options_aq_edit({'triggers': ['voc_bad', 'co2_high']})
        self.assertEqual(result['step_id'], 'options_aq_thresholds_unavailable')
        await flow.async_step_options_aq_thresholds_unavailable({})
        self.assertEqual(flow._options, {})
        self.assertEqual(self.entry.data['aq']['level2']['thresholds'], ['old format'])

    async def test_custom_meaning_main_save_persists_and_reopens_from_native_entry_store(self):
        """Exercise HI Save changes and HA's real finish/persistence boundary."""
        manager = ConfigEntries(self.hass, {})
        self.hass.config_entries = manager
        await manager.async_initialize()
        registry = entity_registry.async_get(self.hass)
        output = registry.async_get_or_create('fan', 'test', 'example_output',
                                              suggested_object_id='example_output')
        source = registry.async_get_or_create('sensor', 'test', 'example_filter',
                                              suggested_object_id='example_filter')
        entry = ConfigEntry(domain='humidity_intelligence', version=1, minor_version=1,
            title='Example HI', source='user', unique_id=None, discovery_keys=MappingProxyType({}),
            subentries_data=[], data={'zones': {'zone1': {'outputs': [output.entity_id]}}}, options={})
        # Register only fixture custody: no integration setup or device calls.
        manager._entries[entry.entry_id] = entry
        flow = config_flow.HumidityIntelligenceOptionsFlow(entry)
        flow.hass = self.hass
        flow.handler = entry.entry_id
        await flow.async_step_options_output_add({'output': output.entity_id,
            'source': source.entity_id, 'semantic': '__add_custom__', 'rule': 'enum_active_values'})
        await flow.async_step_options_output_meaning_edit({'name': 'Check media',
            'classification': 'replace_filter', 'instructions': 'Inspect using the device manual.'})
        await flow.async_step_options_output_rule({'active_values': ['replace'], 'clear_values': ['clear']})
        self.assertEqual(dict(entry.options), {})
        self.assertEqual(flow._observation()['custom_meanings'], {})
        await flow.async_step_options_output_confirm({'confirm': True})
        await flow.async_step_options_output_back()
        staged = copy.deepcopy(flow._options['output_observation'])
        self.assertEqual(dict(entry.options), {})
        ident = next(iter(staged['custom_meanings']))
        self.assertEqual(staged['confirmations'][0]['custom_meaning_id'], ident)

        # This is the actual main-menu Save changes step, followed by HA's
        # unmodified options-flow manager which commits its CREATE_ENTRY result.
        result = await flow.async_step_options_done()
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(dict(entry.options), {})
        await manager.options.async_finish_flow(flow, result)
        self.assertEqual(entry.options['output_observation'], staged)
        # Shutdown must flush HA's scheduled save to disk. A fresh HA instance
        # cannot reuse the original instance's in-memory storage cache.
        await self.stop_hass(self.hass)
        restarted_hass = HomeAssistant(self.temp.name)
        HA_INSTANCES.append(weakref.ref(restarted_hass))
        self.addAsyncCleanup(self.stop_hass, restarted_hass)
        reloaded = ConfigEntries(restarted_hass, {})
        restarted_hass.config_entries = reloaded
        await reloaded.async_initialize()
        persisted = reloaded.async_get_known_entry(entry.entry_id)
        self.assertIsNot(persisted, entry)
        reopened = config_flow.HumidityIntelligenceOptionsFlow(persisted)
        reopened.hass = restarted_hass
        self.assertEqual(reopened._observation(), staged)
        self.assertEqual(reopened._observation()['custom_meanings'][ident]['instructions'],
                         'Inspect using the device manual.')
        self.assertEqual(reopened._observation()['confirmations'][0]['active_values'], ['replace'])
        self.assertEqual(reopened._observation()['confirmations'][0]['source_identity'],
                         staged['confirmations'][0]['source_identity'])


if __name__ == '__main__':
    unittest.main()
