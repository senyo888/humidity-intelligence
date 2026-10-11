"""Compact display preserves full backend truth after observation overlays."""
from copy import deepcopy
from importlib import import_module
import json
import unittest
from unittest.mock import patch

from adaptive_test_support import PACKAGE, normalize

compact_module = import_module(f'{PACKAGE}.compact')
bridge_module = import_module(f'{PACKAGE}.bridge')
build_compact = compact_module.build_compact


def fixture(count=10, mapped=2):
    configured = [dict(entity_id=f'fan.hi_example_{i}', role='ventilation_zone_1') for i in range(count)]
    states = {row['entity_id']: {'state': 'off'} for row in configured}
    mappings = [dict(output=configured[i]['entity_id'], source=f'binary_sensor.hi_example_{i}', semantic='problem', rule='binary_active') for i in range(min(mapped,count))]
    states.update({row['source']: {'state': 'off'} for row in mappings})
    return normalize(configured, states, mappings)


class CompactTests(unittest.TestCase):
    def test_partial_monitoring_leads_without_health_claim(self):
        result=build_compact(fixture())
        self.assertEqual(result['title'],'Monitoring incomplete')
        self.assertEqual(result['condition_count'],0)
        self.assertIn('Monitoring configured: 2/10 outputs',result['monitoring_lines'][0])
        self.assertEqual(len(result['monitoring_lines']),1)
        self.assertNotIn('healthy',json.dumps(result).lower())

    def test_routine_setup_combines_into_one_short_backend_line(self):
        payload=fixture()
        payload['discovery']={'setup_count':3,'review_count':3}
        result=build_compact(payload)
        self.assertEqual(result['monitoring_lines'],['Monitoring configured: 2/10 outputs · 3 readings need a monitoring rule'])
        payload['counts']['reporting']=1
        result=build_compact(payload)
        self.assertIn('Readings usable for 1/10 outputs',result['monitoring_lines'][0])

    def test_complete_unmonitored_and_empty_are_distinct(self):
        cases=[(fixture(10,10),'No monitored issues reported'),(fixture(10,0),'Monitoring not configured'),(fixture(0,0),'No outputs configured')]
        for payload,title in cases:
            with self.subTest(title=title):
                result=build_compact(payload)
                self.assertEqual(result['title'],title)
                self.assertEqual(result['remaining_condition_count'],0)

    def test_existing_order_and_exact_counts_remain_unchanged_with_lost_setup(self):
        payload=fixture()
        payload['attention']=[dict(code='problem',entity_id=f'fan.hi_example_{i%4}',source=f'binary_sensor.hi_example_{i}',tone='danger',label=f'Output {i%4}',title='Problem reported',action='Inspect the source.') for i in range(7)]
        payload['counts'].update(conditions=7,affected=4)
        payload['discovery']=dict(lost_count=1,setup_count=3,retired_count=2,review_count=4)
        before=deepcopy(payload)
        result=build_compact(payload)
        self.assertEqual(payload,before)
        self.assertEqual(result['title'],'7 conditions · 4 outputs')
        self.assertEqual(result['shown_condition_count'],2)
        self.assertEqual(result['remaining_condition_count'],5)
        self.assertEqual(result['remainder_label'],'Showing 2 of 7 conditions · 5 more')
        self.assertEqual(result['monitoring_lines'][0],'1 previously monitored source is no longer usable.')
        self.assertTrue(any('3 readings need a monitoring rule' in line for line in result['monitoring_lines']))
        self.assertTrue(any('Monitoring is paused for 2 output/source links' in line for line in result['monitoring_lines']))

    def test_monitoring_unknown_is_visible_without_lost_source_inference(self):
        payload=fixture(1,1)
        payload['attention']=[dict(code='monitoring_unknown',entity_id='fan.hi_example_0',source='binary_sensor.hi_example_0',tone='warning')]
        payload['counts'].update(conditions=1,affected=1,reporting=0)
        payload['coverage']['state']='incomplete'
        result=build_compact(payload)
        self.assertTrue(any('cannot currently be interpreted' in line for line in result['monitoring_lines']))
        self.assertFalse(any('previously monitored' in line for line in result['monitoring_lines']))
        self.assertEqual(result['tone'],'warning')

    def test_counts_malformed_and_bounds_omit_optional_projection(self):
        for value in (-1,True,1025,'7'):
            payload=fixture();payload['counts']['conditions']=value
            self.assertIsNone(build_compact(payload))
        payload=fixture();payload['counts']['mapped']=11
        self.assertIsNone(build_compact(payload))
        self.assertIsNone(build_compact({}))

    def test_two_conditions_no_fabricated_remainder(self):
        payload=fixture(2,2)
        payload['attention']=[dict(code='problem',tone='warning')]*2
        payload['counts'].update(conditions=2,affected=1)
        result=build_compact(payload)
        self.assertEqual(result['title'],'2 conditions · 1 output')
        self.assertEqual(result['remainder_label'],'')

    def test_context_and_pending_are_projected_after_bridge_overlays(self):
        bridge=bridge_module.ObservationBridge()
        data={'zones':{'zone1':{'enabled':False,'outputs':['fan.hi_example_output']}},
              'humidifiers':{'level1':{'enabled':False,'outputs':['fan.hi_example_output']}}}
        registry=[dict(entity_id='fan.hi_example_output',id='example-output',device_id='example-device')]
        helpers={key:f'switch.hi_example_{key}' for key in bridge_module.HELPERS}
        states={'fan.hi_example_output':{'state':'on'}}
        states.update({eid:{'state':'off'} for eid in helpers.values()})
        states[helpers['air_control_manual_override']]={'state':'on'}
        states[helpers['air_isolate_fan_outputs']]={'state':'on'}
        bridge.evaluate(data,{},registry,states,helpers)
        registry[0]['device_id']='example-new-device'
        payload=bridge.evaluate(data,{},registry,states,helpers,registry_event=True)
        context=payload['compact']['context_lines']
        self.assertTrue(any('Manual control is active' in line for line in context))
        self.assertTrue(any('Automatic air control is disabled' in line for line in context))
        self.assertTrue(any('some roles isolated' in line for line in context))
        self.assertTrue(any('waiting for a new Home Assistant report' in line for line in context))
        self.assertTrue(any('only disabled configured roles' in line for line in context))
        self.assertEqual(payload['records'][0]['availability']['state'],'unknown')
        self.assertTrue(payload['records'][0]['observation_pending'])

    def test_compact_omitted_rather_than_breaking_existing_payload_size_limit(self):
        data={'zones':{'zone1':{'outputs':['fan.hi_example_output']}}}
        states={'fan.hi_example_output':{'state':'off'}}
        bridge=bridge_module.ObservationBridge()
        payload=bridge.evaluate(data,{},[],states,{})
        base=deepcopy(payload);base.pop('compact')
        limit=len(json.dumps(base,allow_nan=False,separators=(',',':')).encode())
        with patch.object(bridge_module,'MAX_PAYLOAD_BYTES',limit):
            fallback=bridge.evaluate(data,{},[],states,{})
        self.assertEqual(fallback,base)
        self.assertNotIn('compact',fallback)

    def test_missing_helper_context_cannot_vanish_in_summary(self):
        data={'zones':{'zone1':{'outputs':['fan.hi_example_output']}}}
        payload=bridge_module.ObservationBridge().evaluate(data,{},[],{'fan.hi_example_output':{'state':'off'}},{})
        lines=payload['compact']['context_lines']
        self.assertIn('HI control or isolation context is incomplete.',lines)
        self.assertTrue(any('isolation unknown' in line for line in lines))

    def test_context_does_not_claim_disabled_output_is_off_or_whole_output_isolated(self):
        payload=fixture(1,1)
        payload['records'][0].update(isolation={'state':'partial'},configured_roles=[{'enabled':True},{'enabled':False}])
        result=build_compact(payload)
        self.assertEqual(result['context_lines'],['1 output with some roles isolated.'])


if __name__=='__main__':unittest.main()
