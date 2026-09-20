"""Cancel/return transaction regressions with native Home Assistant flow schemas.

Run directly in a supported HA environment, separately from stub-based tests:
    python 'tests 2/test_config_flow_cancel_native.py'
No integration setup, live target, or device services are used.
"""
import copy
import importlib
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType, ModuleType, SimpleNamespace
import unittest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.helpers import area_registry, device_registry, entity_registry

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hi_cancel_native'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'custom_components/humidity_intelligence')]
sys.modules[PACKAGE] = package
config_flow = importlib.import_module(PACKAGE + '.config_flow')


class NativeCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.temp.name)
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass)
        await entity_registry.async_load(self.hass)
        await area_registry.async_load(self.hass)
        self.sensor = dict(entity_id='sensor.example_humidity', sensor_type='humidity',
                           level='level1', room='Example room', friendly_name='Example room')
        self.entry = SimpleNamespace(data={'telemetry': [self.sensor]}, options={})

    async def asyncTearDown(self):
        await self.hass.async_block_till_done()
        self.temp.cleanup()

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
        # Flush the real store directly instead of waiting its delayed timer.
        await manager._store.async_save(manager._data_to_save())
        reloaded = ConfigEntries(self.hass, {})
        self.hass.config_entries = reloaded
        await reloaded.async_initialize()
        persisted = reloaded.async_get_known_entry(entry.entry_id)
        self.assertIsNot(persisted, entry)
        reopened = config_flow.HumidityIntelligenceOptionsFlow(persisted)
        reopened.hass = self.hass
        self.assertEqual(reopened._observation(), staged)
        self.assertEqual(reopened._observation()['custom_meanings'][ident]['instructions'],
                         'Inspect using the device manual.')
        self.assertEqual(reopened._observation()['confirmations'][0]['active_values'], ['replace'])
        self.assertEqual(reopened._observation()['confirmations'][0]['source_identity'],
                         staged['confirmations'][0]['source_identity'])


if __name__ == '__main__':
    unittest.main()
