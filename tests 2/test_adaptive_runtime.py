"""HA adapter contracts using bounded in-memory state/registry/lifecycle doubles."""
import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hi_adaptive_runtime_test'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'custom_components/humidity_intelligence/adaptive_output')]
sys.modules[PACKAGE] = package
bridge_module = importlib.import_module(f'{PACKAGE}.bridge')
Bridge = bridge_module.ObservationBridge

OUTPUT = 'fan.hi_example_fan'
SOURCE = 'binary_sensor.hi_example_problem'
HELPER_KEYS = tuple(bridge_module.HELPERS)
HELPERS = {key: f'switch.hi_example_{key}' for key in HELPER_KEYS}


def fixtures():
    data = {'zones': {'zone1': {'outputs': [OUTPUT]}}}
    registry = [
        dict(entity_id=OUTPUT,id='output-id',device_id='device-a',platform='example',unique_id='output-unique',disabled_by=None,name='Example fan'),
        dict(entity_id=SOURCE,id='source-id',device_id='device-a',platform='example',unique_id='source-unique',disabled_by=None,device_class='problem',entity_category='diagnostic',name='Example problem'),
    ]
    states = {OUTPUT:{'state':'on','attributes':{'percentage':60}}, SOURCE:{'state':'off'}}
    states.update({eid:{'state':'off'} for eid in HELPERS.values()})
    states[HELPERS['air_control_enabled']]={'state':'on'}
    return data,registry,states


class FakeStore:
    def __init__(self,*args):
        self.saved=None;self.writes=[];self.delayed=None
    async def async_load(self):return deepcopy(self.saved)
    async def async_save(self,data):self.writes.append(deepcopy(data))
    def async_delay_save(self,callback,delay):self.delayed=callback

class Handle:
    def __init__(self,callback):self.callback=callback;self.cancelled=False
    def cancel(self):self.cancelled=True

class Registry:
    def __init__(self,rows,target_id):
        self.entities={}
        defaults={k:None for k in ('original_device_class','hidden_by','original_name','entity_category','device_class','platform','unique_id','device_id','id','disabled_by','name')}
        for row in rows:self.entities[row['entity_id']]=SimpleNamespace(**{**defaults,**row},config_entry_id=None)
        for key,eid in HELPERS.items():
            self.entities[eid]=SimpleNamespace(**{**defaults,'entity_id':eid,'id':'helper-'+key,'platform':'humidity_intelligence','unique_id':f'hi_{target_id}_input_{key}'},config_entry_id=target_id)
    def async_get(self,eid):return self.entities.get(eid)
    def async_get_entity_id(self,domain,platform,uid):
        return next((r.entity_id for r in self.entities.values() if r.entity_id.startswith(domain+'.') and r.platform==platform and r.unique_id==uid),None)

class Target:
    domain='humidity_intelligence';state='loaded';entry_id='hi-example';options={}
    def __init__(self,data):self.data={**data,'output_observation':{'enabled':True}};self.listeners=[];self.state_listeners=[]
    def add_update_listener(self,cb):
        self.listeners.append(cb)
        return lambda:self.listeners.remove(cb)
    def async_on_state_change(self,cb):
        self.state_listeners.append(cb)
        return lambda:self.state_listeners.remove(cb)

class FakeHass:
    def __init__(self):
        data,rows,states=fixtures();self.target=Target(data)
        self.registry=Registry(rows,self.target.entry_id)
        self.raw_states=states
        self.states=SimpleNamespace(get=lambda eid:SimpleNamespace(state=self.raw_states[eid]['state'],attributes=self.raw_states[eid].get('attributes',{})) if eid in self.raw_states else None)
        self.config_entries=SimpleNamespace(async_get_entry=lambda eid:self.target if eid==self.target.entry_id else None)
        self.state_listeners=[];self.bus_listeners=[];self.handles=[]
        def soon(cb):
            handle=Handle(cb);self.handles.append(handle);return handle
        self.loop=SimpleNamespace(call_soon=soon)
        def listen(event,cb):
            item=(event,cb);self.bus_listeners.append(item)
            return lambda:self.bus_listeners.remove(item)
        self.bus=SimpleNamespace(async_listen=listen)


def coordinator_module():
    names=['homeassistant','homeassistant.config_entries','homeassistant.core','homeassistant.helpers','homeassistant.helpers.entity_registry','homeassistant.helpers.device_registry','homeassistant.helpers.event','homeassistant.helpers.storage']
    modules={name:ModuleType(name) for name in names}
    modules['homeassistant.config_entries'].ConfigEntryState=SimpleNamespace(LOADED='loaded')
    modules['homeassistant.core'].callback=lambda f:f
    er=modules['homeassistant.helpers.entity_registry']
    er.EVENT_ENTITY_REGISTRY_UPDATED='entity_registry_updated';er.async_get=lambda hass:hass.registry
    er.async_entries_for_device=lambda registry,device_id,include_disabled_entities=True:[r for r in registry.entities.values() if r.device_id==device_id]
    modules['homeassistant.helpers.device_registry'].EVENT_DEVICE_REGISTRY_UPDATED='device_registry_updated'
    def track(hass,ids,cb):
        item=(ids,cb);hass.state_listeners.append(item)
        return lambda:hass.state_listeners.remove(item)
    modules['homeassistant.helpers.event'].async_track_state_change_event=track
    modules['homeassistant.helpers.storage'].Store=FakeStore
    with patch.dict(sys.modules,modules):
        name=f'{PACKAGE}.coordinator'
        sys.modules.pop(name,None)
        return importlib.import_module(name)



class AdaptiveCoreTests(unittest.TestCase):
    def setUp(self):
        self.data,self.registry,self.states=fixtures()
        self.retired=[dict(output=OUTPUT,source=SOURCE,output_identity='registry:output-id',source_identity='registry:source-id')]

    def evaluate(self, bridge=None, **kwargs):
        return (bridge or Bridge()).evaluate(self.data,{},self.registry,self.states,HELPERS,**kwargs)

    def test_retirement_is_context_only_and_not_clear_then_resumes(self):
        bridge=Bridge();self.evaluate(bridge)
        self.states[SOURCE]={'state':'on'}
        payload=self.evaluate(bridge,retired=self.retired)
        self.assertEqual(payload['attention'],[])
        self.assertEqual(payload['state'],'unmonitored')
        self.assertEqual(payload['coverage']['state'],'incomplete')
        self.assertEqual(payload['discovery']['sources'][0]['title'],'Interpretation paused')
        self.assertEqual(bridge.bindings(),[])
        self.assertEqual(self.evaluate(bridge)['attention'][0]['code'],'problem')

    def test_retirement_does_not_bind_replacement_or_wrong_identity(self):
        self.registry[1]['id']='replacement';self.states[SOURCE]={'state':'on'}
        payload=self.evaluate(retired=self.retired)
        self.assertEqual(payload['attention'],[])
        self.assertEqual(payload['discovery']['sources'][0]['title'],'Paused association needs review')
        self.assertEqual(payload['coverage']['state'],'incomplete')

    def test_retirement_follows_identity_rename_and_missing_retirement_is_explicit(self):
        self.registry[1]['entity_id']='binary_sensor.hi_example_new'
        self.states['binary_sensor.hi_example_new']={'state':'on'}
        payload=self.evaluate(retired=self.retired)
        self.assertEqual(payload['discovery']['sources'][0]['title'],'Interpretation paused')
        self.registry.pop()
        payload=self.evaluate(retired=self.retired)
        self.assertEqual(payload['discovery']['sources'][0]['title'],'Interpretation paused')
        self.assertEqual(payload['discovery']['review_count'],0)
        self.assertEqual(payload['discovery']['sources'][0]['state'],'Not used as current evidence')

    def test_explicit_rule_stays_dormant_until_resume(self):
        confirmation={**self.retired[0],'semantic':'replace_filter','rule':'binary_active'}
        self.states[SOURCE]={'state':'on'}
        bridge=Bridge()
        self.assertEqual(self.evaluate(bridge,confirmations=[confirmation],retired=self.retired)['attention'],[])
        self.assertEqual(self.evaluate(bridge,confirmations=[confirmation])['attention'][0]['code'],'replace_filter')

    def test_roles_keep_enabled_and_disabled_context_without_selected_claim(self):
        self.data={'zones':{'zone1':{'enabled':True,'outputs':[OUTPUT]},'zone2':{'enabled':False,'outputs':[OUTPUT]}}}
        record=self.evaluate()['records'][0]
        self.assertEqual([(r['role'],r['enabled']) for r in record['configured_roles']],[('ventilation_zone_1',True),('ventilation_zone_2',False)])
        self.assertFalse(record['selected'])

    def test_setup_and_lost_monitoring_are_distinct(self):
        bridge=Bridge();self.evaluate(bridge)
        self.registry.pop()
        payload=self.evaluate(bridge)
        self.assertEqual(payload['discovery']['lost_count'],1)
        self.assertEqual(payload['discovery']['setup_count'],0)
        self.registry.append(dict(entity_id='sensor.hi_example_enum',id='enum',device_id='device-a',entity_category='diagnostic'))
        self.states['sensor.hi_example_enum']={'state':'normal'}
        payload=self.evaluate(bridge)
        self.assertEqual(payload['discovery']['setup_count'],1)
        self.assertIn('not device failure',payload['discovery']['setup_notice'])
        self.assertEqual(payload['discovery']['lost_count'],1)

    def test_metadata_allowlist_no_derived_freshness_and_no_persistence(self):
        self.states[SOURCE]={'state':'off','observation':{'last_reported':'2026-01-01T00:00:00+00:00','restored':True,'secret':'not public'}}
        bridge=Bridge();payload=self.evaluate(bridge)
        observation=payload['discovery']['sources'][0]['observation']
        self.assertTrue(observation['restored'])
        self.assertEqual(observation['physical_freshness'],'not_established')
        self.assertNotIn('secret',observation)
        self.assertNotIn('last_reported',repr(bridge.custody()))

    def test_invalid_retirement_and_candidate_bounds_fail_closed(self):
        with self.assertRaises(ValueError):self.evaluate(retired=[{**self.retired[0],'rule':'binary_active'}])
        with self.assertRaises(ValueError):self.evaluate(retired=self.retired*257)
        self.registry.extend(dict(entity_id=f'binary_sensor.hi_example_source_{i}',id=f'source-{i}',device_id='device-a',device_class='problem') for i in range(257))
        with self.assertRaises(ValueError):self.evaluate()

    def test_quarantine_still_survives_reload_and_offline_changes(self):
        bridge=Bridge();self.evaluate(bridge)
        self.registry[1]['device_class']='battery'
        self.states[SOURCE]={'state':'on'}
        restored=Bridge.from_custody(bridge.custody())
        self.assertEqual(self.evaluate(restored)['attention'][0]['code'],'monitoring_unknown')
        restored=Bridge.from_custody(restored.custody())
        self.assertEqual(self.evaluate(restored)['attention'][0]['code'],'monitoring_unknown')
        self.assertEqual(self.evaluate(restored,fresh_entity=SOURCE)['attention'][0]['code'],'battery_low')


class AdaptiveCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module=coordinator_module();self.hass=FakeHass()
        self.observer=self.module.OutputObserver(self.hass,self.hass.target)
        await self.observer.async_start()

    async def asyncTearDown(self):
        if self.observer.active:await self.observer.async_stop()

    async def test_hi_entry_identity_and_no_duplicate_update_listener(self):
        self.assertEqual(self.observer.target_id,self.hass.target.entry_id)
        self.assertEqual(self.hass.target.listeners,[])
        self.assertEqual(len(self.hass.target.state_listeners),1)
        self.assertIsNotNone(self.observer.payload)

    async def test_setup_in_progress_pauses_then_loaded_refreshes(self):
        await self.observer.async_stop()
        self.hass.target.state='setup_in_progress'
        self.observer=self.module.OutputObserver(self.hass,self.hass.target)
        await self.observer.async_start()
        self.assertIsNone(self.observer.payload)
        self.hass.target.state='loaded'
        self.observer._target_state_changed()
        self.assertIsNotNone(self.observer.payload)

    async def test_enabled_false_fails_only_observer_and_native_presentation_still_observes(self):
        original=deepcopy(self.hass.target.data)
        self.hass.target.options={'output_observation':{'enabled':False,'presentation':'adaptive'}}
        self.observer.refresh();self.assertIsNone(self.observer.payload)
        self.hass.target.options={'output_observation':{'enabled':True,'presentation':'native'}}
        self.observer.refresh();self.assertIsNotNone(self.observer.payload)
        self.assertEqual(self.hass.target.data,original)
        self.hass.target.options={}

    async def test_state_changes_reuse_metadata_cache_registry_events_invalidate(self):
        snapshots=self.observer._snapshot_cache
        self.observer._state_changed(SimpleNamespace(data={'entity_id':SOURCE}))
        self.observer.refresh()
        self.assertIs(self.observer._snapshot_cache,snapshots)
        self.hass.registry.entities[SOURCE].device_class='battery'
        self.observer._registry_changed(SimpleNamespace(data={}))
        self.assertIsNone(self.observer._snapshot_cache)
        self.observer.refresh()
        self.assertIsNot(self.observer._snapshot_cache,snapshots)
        self.assertIn(SOURCE,self.observer.bridge.quarantined)

    async def test_pending_batch_flush_and_unload_cleanup(self):
        self.hass.registry.entities[SOURCE].device_class='battery'
        self.observer._registry_changed(SimpleNamespace(data={}))
        await self.observer.async_stop()
        self.assertIn(SOURCE,self.observer.store.writes[-1]['quarantined'])
        self.assertEqual(self.hass.state_listeners,[])
        self.assertEqual(self.hass.bus_listeners,[])

    async def test_snapshot_metadata_only_captures_actual_datetime_and_boolean(self):
        from datetime import datetime,timezone
        original=self.hass.states.get
        def get(eid):
            state=original(eid)
            if state:
                state.last_reported=datetime(2026,1,1,tzinfo=timezone.utc)
                state.last_updated='not a platform timestamp'
                state.attributes={**state.attributes,'restored':True}
            return state
        self.hass.states.get=get
        self.observer.refresh()
        metadata=self.observer.payload['discovery']['sources'][0]['observation']
        self.assertEqual(metadata['last_reported'],'2026-01-01T00:00:00+00:00')
        self.assertNotIn('last_updated',metadata)
        self.assertTrue(metadata['restored'])

    async def test_snapshot_accumulation_bound_does_not_publish_partial_fleet(self):
        for i in range(1100):
            row=deepcopy(self.hass.registry.entities[SOURCE]);row.entity_id=f'sensor.hi_example_{i}';row.id=f'source-{i}'
            self.hass.registry.entities[row.entity_id]=row
        self.observer._registry_changed(SimpleNamespace(data={}))
        self.observer.refresh()
        self.assertIsNone(self.observer.payload)
        self.assertIn('limit',self.observer.failure)


class IntegratedCustodyTests(unittest.TestCase):
    def setUp(self):
        self.data, self.registry, self.states = fixtures()
        self.bridge = Bridge()
        self.evaluate()

    def evaluate(self, bridge=None, **kwargs):
        return (bridge or self.bridge).evaluate(self.data, {}, self.registry, self.states, HELPERS, **kwargs)

    def reload(self):
        return Bridge.from_custody(self.bridge.custody())

    def test_class_invalidation_on_and_off_survives_reload_until_source_event(self):
        for value in ('on', 'off'):
            with self.subTest(value=value):
                self.setUp()
                self.registry[1]['device_class'] = 'battery'
                self.states[SOURCE] = {'state': value}
                before = self.evaluate(registry_event=True)
                after_bridge = self.reload()
                after = self.evaluate(after_bridge)
                self.assertEqual(before['attention'][0]['code'], 'monitoring_unknown')
                self.assertEqual(after['attention'][0]['code'], 'monitoring_unknown')
                self.assertIn(SOURCE, after_bridge.quarantined)
                recovered = self.evaluate(after_bridge, fresh_entity=SOURCE)
                self.assertEqual([a['code'] for a in recovered['attention']], ['battery_low'] if value == 'on' else [])

    def test_offline_class_identity_association_disabled_changes_are_not_trusted(self):
        for field, value in [('device_class', 'battery'), ('id', 'replacement'), ('device_id', 'moved-device'), ('disabled_by', 'user')]:
            with self.subTest(field=field):
                self.setUp()
                restored = self.reload()
                self.registry[1][field] = value
                self.states[SOURCE] = {'state': 'on'}
                payload = self.evaluate(restored)
                self.assertIn(SOURCE, restored.quarantined)
                self.assertTrue(any(a['code'] == 'monitoring_unknown' for a in payload['attention']))
                self.assertFalse(any(a['code'] in ('problem', 'battery_low') for a in payload['attention']))

    def test_unchanged_reload_and_brand_new_install_accept_current_snapshot(self):
        for bridge in (self.reload(), Bridge()):
            self.assertEqual(self.evaluate(bridge)['attention'], [])
            self.assertEqual(bridge.quarantined, set())

    def test_legacy_migration_requires_later_event_and_survives_second_reload(self):
        legacy = Bridge.from_custody({'known': self.bridge.bindings()})
        self.evaluate(legacy)
        self.assertTrue({OUTPUT, SOURCE} <= legacy.quarantined)
        again = Bridge.from_custody(legacy.custody())
        self.evaluate(again)
        self.assertTrue({OUTPUT, SOURCE} <= again.quarantined)
        self.evaluate(again, fresh_entity=OUTPUT)
        self.assertIn(SOURCE, again.quarantined)
        self.assertEqual(self.evaluate(again, fresh_entity=SOURCE)['attention'], [])

    def test_legacy_rename_cannot_bypass_migration_uncertainty(self):
        legacy = Bridge.from_custody({'known': self.bridge.bindings()})
        renamed = 'binary_sensor.hi_example_renamed'
        self.registry[1]['entity_id'] = renamed
        self.states[renamed] = {'state': 'on'}
        payload = self.evaluate(legacy)
        self.assertIn(renamed, legacy.quarantined)
        self.assertFalse(any(a['code'] == 'problem' for a in payload['attention']))

    def test_names_unrelated_events_and_source_values_do_not_invalidate(self):
        self.registry[1]['name'] = 'A new display name'
        self.states[SOURCE] = {'state': 'on', 'attributes': {'private_blob': 'not stored'}}
        self.evaluate(registry_event=True)
        self.assertEqual(self.bridge.quarantined, set())
        saved = self.bridge.custody()
        self.assertTrue(all(len(value) == 64 for value in saved['registry'].values()))
        self.assertNotIn('private_blob', repr(saved))
        self.assertNotIn('A new display name', repr(saved))
        self.assertNotIn('attributes', repr(saved))

    def test_failed_presentation_retains_pending_invalidation_in_custody(self):
        self.registry[1]['device_class'] = 'battery'
        with patch.object(bridge_module, 'MAX_PAYLOAD_BYTES', 1):
            with self.assertRaises(ValueError):
                self.evaluate(registry_event=True)
        restored = self.reload()
        self.assertIn(SOURCE, restored.quarantined)
        self.assertEqual(self.evaluate(restored)['attention'][0]['code'], 'monitoring_unknown')

    def test_replacement_stays_unresolved_after_fresh_event(self):
        self.registry[1]['id'] = 'replacement'
        self.evaluate(registry_event=True)
        restored = self.reload()
        payload = self.evaluate(restored, fresh_entity=SOURCE)
        self.assertEqual(payload['attention'][0]['code'], 'monitoring_unknown')
        self.assertEqual(payload['discovery']['gaps'][0]['label'], 'Diagnostic identity changed')

    def test_removal_reappearance_and_reenable_need_new_report(self):
        original = deepcopy(self.registry[1])
        self.registry.pop()
        self.evaluate(registry_event=True)
        restored = self.reload()
        self.registry.append(original)
        self.assertEqual(self.evaluate(restored)['attention'][0]['code'], 'monitoring_unknown')
        self.assertEqual(self.evaluate(restored, fresh_entity=SOURCE)['attention'], [])
        self.registry[1]['disabled_by'] = 'user'
        self.evaluate(restored, registry_event=True)
        self.registry[1]['disabled_by'] = None
        restored = Bridge.from_custody(restored.custody())
        self.assertEqual(self.evaluate(restored)['attention'][0]['code'], 'monitoring_unknown')

    def test_schema_bounds_corruption_and_duplicate_rules_reject(self):
        saved = self.bridge.custody()
        variants = [None, {}, {**saved, 'schema_version': True}, {**saved, 'schema_version': 3},
                    {**saved, 'raw_states': {}}, {**saved, 'registry': {SOURCE: 'bad'}},
                    {**saved, 'quarantined': [SOURCE, SOURCE]}, {**saved, 'quarantined': ['bad']},
                    {**saved, 'quarantined': [SOURCE] * 4097},
                    {**saved, 'known': saved['known'] * 2}]
        for bad in variants:
            with self.subTest(bad=repr(bad)[:80]), self.assertRaises(ValueError):
                Bridge.from_custody(bad)
        with patch.object(bridge_module, 'MAX_CUSTODY_BYTES', 1), self.assertRaises(ValueError):
            Bridge.from_custody(saved)
        with patch.object(bridge_module, 'MAX_CUSTODY_ENTITIES', 1), self.assertRaises(ValueError):
            Bridge.from_custody(saved)



if __name__=='__main__':unittest.main()
