"""Disposable real-HA API tests; no integration setup, live target or output calls.

Run with a Python environment containing the supported Home Assistant version:
    python 'tests 2/test_adaptive_ha_native.py'
HA's registries, config-entry state events, state machine, Store and Recorder
serializer are real. The HI parent package is isolated to avoid booting control.
"""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType, ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.const import EntityCategory, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.components.recorder.db_schema import StateAttributes

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hi_adaptive_native'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'custom_components/humidity_intelligence')]
sys.modules[PACKAGE] = package
coordinator = importlib.import_module(PACKAGE + '.adaptive_output.coordinator')
sensor_module = importlib.import_module(PACKAGE + '.adaptive_output.sensor')
DOMAIN = 'humidity_intelligence'


class NativeHomeAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.temp.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.entry = ConfigEntry(
            version=1, minor_version=1, domain=DOMAIN, title='Example HI',
            source='user', unique_id='example-hi', options={}, data={},
            discovery_keys=MappingProxyType({}), subentries_data=None,
            state=ConfigEntryState.LOADED,
        )
        # Register a real entry without loading HI's control integration.
        self.hass.config_entries._entries[self.entry.entry_id] = self.entry
        self.hass.data[DOMAIN] = {self.entry.entry_id: {}}
        self.registry = er.async_get(self.hass)
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={('example', 'example-device')}, name='Example device')
        self.output = self.registry.async_get_or_create(
            'fan', 'example', 'example-fan', suggested_object_id='hi_example_fan',
            config_entry=self.entry, device_id=device.id)
        self.source = self.registry.async_get_or_create(
            'binary_sensor', 'example', 'example-problem',
            suggested_object_id='hi_example_problem', config_entry=self.entry,
            device_id=device.id, original_device_class='problem',
            entity_category=EntityCategory.DIAGNOSTIC)
        self.hass.config_entries.async_update_entry(self.entry, data={
            'zones': {'zone1': {'enabled': True, 'outputs': [self.output.entity_id]}},
            'output_observation': {'enabled': True},
        })
        self.hass.states.async_set(self.output.entity_id, 'on', {'percentage': 50})
        self.hass.states.async_set(self.source.entity_id, 'off')
        for key in coordinator.HELPERS:
            helper = self.registry.async_get_or_create(
                'switch', DOMAIN, f'hi_{self.entry.entry_id}_input_{key}',
                suggested_object_id='hi_example_' + key, config_entry=self.entry)
            self.hass.states.async_set(helper.entity_id, 'on' if key == 'air_control_enabled' else 'off')
        await self.hass.async_block_till_done()
        self.observers = []

    async def asyncTearDown(self):
        for observer in self.observers:
            if observer.active:
                await observer.async_stop()
        await self.hass.async_stop()
        self.temp.cleanup()

    async def start_observer(self):
        observer = coordinator.OutputObserver(self.hass, self.entry)
        self.observers.append(observer)
        await observer.async_start()
        self.assertIsNotNone(observer.payload, observer.failure)
        return observer

    async def set_and_observe(self, observer, entity_id, value):
        # HA 2026.5 dispatches indexed state callbacks one event-loop turn
        # later than 2026.9. async_block_till_done does not drain every raw
        # call_soon callback, so await the observer's actual publication.
        published = asyncio.get_running_loop().create_future()
        def on_publish():
            if not published.done():
                published.set_result(None)
        unsubscribe = observer.subscribe(on_publish)
        try:
            self.hass.states.async_set(entity_id, value)
            await asyncio.wait_for(published, timeout=1)
        finally:
            unsubscribe()

    async def test_native_lifecycle_and_state_events(self):
        observer = await self.start_observer()
        self.assertIn(self.source.entity_id, observer._watch)
        first = json.dumps(observer.payload)
        await self.set_and_observe(observer, self.source.entity_id, 'on')
        self.assertNotEqual(first, json.dumps(observer.payload))
        self.assertIsNotNone(observer.payload)
        self.assertEqual(observer.payload['observation']['basis'], 'home_assistant_state')
        await observer.async_stop()
        self.assertIsNone(observer.payload)
        self.assertFalse(observer._unsub)
        self.assertIsNone(observer._state_unsub)
        self.assertIsNone(observer._report_unsub)

    async def test_entry_custom_meanings_refresh_and_custody_reload_without_actuation(self):
        meanings = importlib.import_module(PACKAGE + '.adaptive_output.meanings')
        mappings = importlib.import_module(PACKAGE + '.adaptive_output.mappings')
        ident = 'custom_' + 'a' * 32
        library = {ident: {'name': 'Inspect intake', 'classification': 'generic_attention',
                           'instructions': 'Read the device label.'}}
        binding = mappings.bind(dict(self.entry.data), {},
            [coordinator.registry_row(row) for row in self.registry.entities.values()],
            {'output': self.output.entity_id, 'source': self.source.entity_id,
             'semantic': 'generic_attention', 'custom_meaning_id': ident,
             'rule': 'binary_active'}, custom_meanings=library)
        settings = mappings.section({'enabled': True, 'custom_meanings': library,
                                     'confirmations': [binding]})
        self.hass.config_entries.async_update_entry(self.entry, options={'output_observation': settings})
        self.hass.states.async_set(self.source.entity_id, 'on')
        await self.hass.async_block_till_done()
        output_before = self.hass.states.get(self.output.entity_id)
        # Calls to HA services would violate this observer's read-only contract.
        with patch.object(type(self.hass.services), 'async_call') as service_call:
            observer = await self.start_observer()
            attention = observer.payload['attention'][0]
            self.assertEqual(attention['title'], 'Inspect intake')
            self.assertEqual(attention['code'], 'generic_attention')
            self.assertIn('Your guidance: Read the device label.', attention['action'])

            changed = meanings.save_meaning(settings, 'Intake obstruction', 'obstruction', ident,
                                            instructions='Consult the device manual.')
            self.hass.config_entries.async_update_entry(self.entry, options={'output_observation': changed})
            observer.refresh()
            self.assertIsNotNone(observer.payload, observer.failure)
            attention = observer.payload['attention'][0]
            self.assertEqual((attention['title'], attention['code']), ('Intake obstruction', 'obstruction'))
            self.assertIn('Consult the device manual.', attention['action'])
            self.assertEqual(changed['confirmations'][0]['source_identity'], binding['source_identity'])

            await observer.async_stop()
            saved_path = Path(self.temp.name) / '.storage' / observer.store.key
            saved = json.loads(saved_path.read_text())['data']
            self.assertEqual(saved['known'][0]['custom_meaning_id'], ident)
            self.assertNotIn('custom_label', json.dumps(saved))
            self.assertNotIn('custom_instructions', json.dumps(saved))
            self.assertNotIn('Consult the device manual.', json.dumps(saved))
            restarted = await self.start_observer()
            self.assertEqual(restarted.payload['attention'][0]['title'], 'Intake obstruction')

            # A retained off state would be clear under either saved or automatic
            # binary rules, but a deleted definition must block both interpretations.
            self.hass.config_entries.async_update_entry(self.entry, options={
                'output_observation': {**changed, 'custom_meanings': {}}})
            await self.set_and_observe(restarted, self.source.entity_id, 'off')
            self.assertEqual(restarted.payload['coverage']['state'], 'incomplete')
            self.assertEqual(restarted.payload['discovery']['review_count'], 1)
            self.assertEqual(restarted.payload['attention'][0]['code'], 'monitoring_unknown')
            self.assertIn('Saved meaning unavailable', json.dumps(restarted.payload))
            await restarted.async_stop()
            missing_reloaded = await self.start_observer()
            self.assertEqual(missing_reloaded.payload['attention'][0]['code'], 'monitoring_unknown')
            self.assertEqual(missing_reloaded.payload['coverage']['state'], 'incomplete')
            service_call.assert_not_called()
        self.assertIs(self.hass.states.get(self.output.entity_id), output_before)

    async def test_registry_quarantine_survives_real_store_reload(self):
        observer = await self.start_observer()
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        await self.hass.async_block_till_done()
        self.assertIn(self.source.entity_id, observer.bridge.quarantined)
        await observer.async_stop()
        saved_path = Path(self.temp.name) / '.storage' / observer.store.key
        self.assertTrue(saved_path.exists())
        restarted = await self.start_observer()
        self.assertIn(self.source.entity_id, restarted.bridge.quarantined)
        await self.set_and_observe(restarted, self.source.entity_id, 'on')
        self.assertNotIn(self.source.entity_id, restarted.bridge.quarantined)

    async def test_same_value_report_releases_registry_quarantine(self):
        observer = await self.start_observer()
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        await self.hass.async_block_till_done()
        self.assertIn(self.source.entity_id, observer.bridge.quarantined)
        state_before = self.hass.states.get(self.source.entity_id)
        self.assertEqual(state_before.state, 'off')
        # Identical state/attributes emits STATE_REPORTED, not STATE_CHANGED.
        await self.set_and_observe(observer, self.source.entity_id, 'off')
        state_after = self.hass.states.get(self.source.entity_id)
        self.assertEqual(state_after.last_changed, state_before.last_changed)
        self.assertEqual(state_after.last_updated, state_before.last_updated)
        self.assertNotIn(self.source.entity_id, observer.bridge.quarantined)
        self.assertEqual(observer.payload['counts']['reporting'], 1)
        self.assertEqual(observer.payload['observation']['physical_freshness'], 'not_established')

    async def test_report_before_registry_change_cannot_release_new_quarantine(self):
        observer = await self.start_observer()
        # HA 2026.5 defers report callback dispatch. Event receipt must not
        # reclassify a pre-registry report as post-registry fresh evidence.
        self.hass.states.async_set(self.source.entity_id, 'off')
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        await self.hass.async_block_till_done()
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertIn(self.source.entity_id, observer.bridge.quarantined)

    async def test_changed_state_before_registry_change_cannot_release_new_quarantine(self):
        observer = await self.start_observer()
        self.hass.states.async_set(self.source.entity_id, 'on')
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        await self.hass.async_block_till_done()
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertIn(self.source.entity_id, observer.bridge.quarantined)

    async def test_first_setup_registry_events_accept_current_snapshot(self):
        self.entry._async_set_state(self.hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
        observer = coordinator.OutputObserver(self.hass, self.entry)
        self.observers.append(observer)
        await observer.async_start()
        self.assertIsNone(observer.payload)
        self.assertIsNone(observer.bridge.registry)
        # The first observer sees registry initialization before HI is loaded.
        self.registry.async_update_entity(self.source.entity_id, original_name='Example problem reading')
        await self.hass.async_block_till_done()
        self.assertTrue(observer._registry_event)
        self.entry._async_set_state(self.hass, ConfigEntryState.LOADED, None)
        await self.hass.async_block_till_done()
        self.assertIsNotNone(observer.payload, observer.failure)
        self.assertEqual(observer.bridge.quarantined, set())
        self.assertEqual(observer.payload['counts']['available'], 1)
        self.assertEqual(observer.payload['counts']['reporting'], 1)

    async def test_registry_change_while_stopped_is_detected_on_start(self):
        observer = await self.start_observer()
        await observer.async_stop()
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        await self.hass.async_block_till_done()
        restarted = await self.start_observer()
        self.assertIn(self.source.entity_id, restarted.bridge.quarantined)

    async def test_queued_registry_change_flushes_before_stop(self):
        observer = await self.start_observer()
        self.registry.async_update_entity(self.source.entity_id, original_device_class='battery')
        # Allow the registry event handler to schedule refresh, then stop before
        # the later call_soon callback. Both possible orderings must be safe.
        await asyncio.sleep(0)
        await observer.async_stop()
        restarted = await self.start_observer()
        self.assertIn(self.source.entity_id, restarted.bridge.quarantined)

    async def test_start_during_hi_setup_recovers_when_loaded(self):
        self.entry._async_set_state(self.hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
        observer = coordinator.OutputObserver(self.hass, self.entry)
        self.observers.append(observer)
        await observer.async_start()
        self.assertIsNone(observer.payload)
        self.entry._async_set_state(self.hass, ConfigEntryState.LOADED, None)
        await self.hass.async_block_till_done()
        self.assertIsNotNone(observer.payload, observer.failure)

    async def test_real_entry_state_transition_pauses_and_recovers(self):
        observer = await self.start_observer()
        self.entry._async_set_state(self.hass, ConfigEntryState.UNLOAD_IN_PROGRESS, None)
        await self.hass.async_block_till_done()
        self.assertIsNone(observer.payload)
        self.entry._async_set_state(self.hass, ConfigEntryState.LOADED, None)
        await self.hass.async_block_till_done()
        self.assertIsNotNone(observer.payload, observer.failure)

    async def test_bad_custody_fails_closed(self):
        observer = coordinator.OutputObserver(self.hass, self.entry)
        self.observers.append(observer)
        await observer.store.async_save({'target_id': 'different-entry', 'known': []})
        await observer.async_start()
        self.assertIsNone(observer.payload)
        self.assertIn('custody', observer.failure)

    async def test_recorder_serializer_excludes_payload_and_error(self):
        observer = await self.start_observer()
        entity = sensor_module.HIOutputStatusSensor(self.entry.entry_id, observer)
        entity.hass = self.hass
        entity.entity_id = 'sensor.hi_example_output_status'
        entity.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=self.entry)
        await entity.async_internal_added_to_hass()
        self.hass.states.async_set(entity.entity_id, entity.native_value,
            entity.extra_state_attributes, state_info=entity._state_info)
        event = Event(EVENT_STATE_CHANGED, {'new_state': self.hass.states.get(entity.entity_id)})
        recorded = json.loads(StateAttributes.shared_attrs_bytes_from_event(event, None))
        self.assertNotIn('payload', recorded)
        self.assertNotIn('error', recorded)
        self.assertIn('counts', recorded)
        self.assertIn('summary', recorded)

    async def test_optional_setup_exception_does_not_escape(self):
        added = []
        with patch.object(coordinator.OutputObserver, 'async_start', side_effect=RuntimeError('synthetic startup fault')):
            with self.assertLogs(sensor_module.__name__, level='ERROR'):
                await sensor_module.async_setup_observation(self.hass, self.entry, added.extend)
        self.assertEqual(added, [])
        self.assertNotIn('output_observer', self.hass.data[DOMAIN][self.entry.entry_id])


if __name__ == '__main__':
    unittest.main(verbosity=2)
