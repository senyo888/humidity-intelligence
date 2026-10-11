"""Tracked pure Adaptive Output model, configuration, discovery and presentation contracts."""

"""Behavioral contract checks for the pure model, including adversarial inputs."""
import copy
import json
import math
import unittest
from adaptive_test_support import normalize, MAX_CONFIG, INTEGRATION_ROOT
from adaptive_test_fixtures import fixtures, build_scenarios


class AdaptiveOutputTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures()[0]

    def run_model(self):
        return normalize(self.f['configured'],self.f['states'],self.f['mappings'])

    def test_scenarios_are_json_safe_and_synthetic(self):
        for scenario in build_scenarios():
            p = scenario['payload']
            json.dumps(p,allow_nan=False)
            self.assertTrue(p['synthetic'])
            self.assertLessEqual(len(p['chips']),3)
            self.assertNotIn('healthy',json.dumps(p).lower())
            for r in p['records']:
                self.assertIn('.hi_example_',r['entity_id'])

    def test_fixed_role_order_and_shared_output_dedupe(self):
        c = self.f['configured']
        shared = dict(c[0],role='aq',label='Ignored later role label')
        c.insert(0,shared)
        p = self.run_model()
        self.assertEqual(p['counts']['configured'],4)
        self.assertEqual(p['records'][0]['roles'],['ventilation_zone_1','aq'])
        self.assertEqual(p['records'][0]['label'],'Extract fan')
        self.assertEqual(normalize(list(reversed(c)),self.f['states'],self.f['mappings'])['records'][0]['entity_id'],c[1]['entity_id'])

    def test_saved_order_within_role_and_not_label_order(self):
        c = self.f['configured']
        c[1]['role']=c[0]['role']
        c[0]['label']='Zebra';c[1]['label']='Apple'
        self.assertEqual([r['label'] for r in self.run_model()['records']][:2],['Zebra','Apple'])

    def test_availability_never_infers_fault(self):
        for value in ('unknown','unavailable'):
            self.f['states'][self.f['configured'][0]['entity_id']]={'state':value}
            p=self.run_model()
            self.assertEqual(p['records'][0]['fault']['state'],'not_reported')
            self.assertEqual(p['records'][0]['status']['tone'],'warning')

    def test_bad_source_does_not_make_output_unavailable(self):
        self.f['states'][self.f['mappings'][0]['source']]={'state':'unavailable'}
        p=self.run_model()
        self.assertEqual(p['counts']['available'],4)
        self.assertEqual(p['records'][0]['monitoring']['state'],'incomplete')
        self.assertEqual(p['state'],'degraded')

    def test_active_isolated_fault_and_maintenance_are_independent(self):
        f=next(f for f in fixtures() if f['id']=='multiple_conditions')
        f['configured'][0]['isolated']=True
        p=normalize(f['configured'],f['states'],f['mappings'])
        r=p['records'][0]
        self.assertEqual(r['operation']['state'],'on')
        self.assertEqual(r['isolation']['state'],'isolated')
        self.assertEqual(r['fault']['state'],'reported')
        self.assertEqual(r['maintenance']['state'],'required')
        self.assertEqual(p['counts']['affected'],1)
        self.assertEqual(p['counts']['conditions'],2)

    def test_exact_overflow_counts_outputs(self):
        p=next(s['payload'] for s in build_scenarios() if s['id']=='mixed')
        self.assertEqual(p['counts']['affected'],4)
        self.assertEqual(p['counts']['conditions'],5)
        self.assertEqual(p['chips'][2]['count'],3)

    def test_severity_precedes_selected_lane_relevance(self):
        f=next(f for f in fixtures() if f['id']=='mixed')
        p=normalize(f['configured'],f['states'],list(reversed(f['mappings'])))
        self.assertEqual(p['attention'][0]['code'],'unavailable')
        self.assertEqual(p['attention'][1]['code'],'fault')

    def test_mapping_order_and_state_dictionary_order_do_not_change_truth(self):
        f=next(f for f in fixtures() if f['id']=='mixed')
        p=normalize(f['configured'],f['states'],f['mappings'])
        q=normalize(f['configured'],dict(reversed(list(f['states'].items()))),list(reversed(f['mappings'])))
        self.assertEqual(p,q)

    def test_missing_unsupported_and_no_outputs(self):
        results={s['id']:s['payload'] for s in build_scenarios()}
        self.assertEqual(results['missing']['attention'][0]['code'],'missing')
        self.assertEqual(results['unsupported']['counts']['supported'],4)
        self.assertEqual(results['no_outputs']['state'],'not_configured')
        self.assertEqual(len(results['no_outputs']['chips']),1)

    def test_unmonitored_is_not_clear(self):
        self.f['mappings']=[]
        p=self.run_model()
        self.assertEqual(p['state'],'unmonitored')
        self.assertEqual(p['coverage']['state'],'unmonitored')
        self.assertEqual(p['attention'],[])

    def test_enum_novel_value_and_conflicting_rule_fail_closed(self):
        m=self.f['mappings'][0]
        m.update(rule='enum_active_values',active_values=['bad'],clear_values=['clear'])
        for value in ('vendor_new','unknown','unavailable'):
            self.f['states'][m['source']]={'state':value}
            self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')
        self.f['states'][m['source']]={'state':'clear'}
        self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'reporting')
        m['clear_values']=['bad']
        self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')

    def test_numeric_finite_strict_thresholds_and_invalid_input(self):
        m=self.f['mappings'][0]
        m.update(rule='numeric_below',threshold=10,semantic='refill')
        for value,expected in [('9','required'),('10','not_reported'),('11','not_reported')]:
            self.f['states'][m['source']]={'state':value}
            self.assertEqual(self.run_model()['records'][0]['maintenance']['state'],expected)
        m['rule']='numeric_above'
        self.assertEqual(self.run_model()['records'][0]['maintenance']['state'],'required')
        for value in ('nan','inf','-inf','garbage'):
            self.f['states'][m['source']]={'state':value}
            self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')
        for value in (math.nan,math.inf,True,'10'):
            m['threshold']=value
            self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')

    def test_duplicate_mapping_not_double_counted_and_orphan_visible(self):
        self.f['mappings'].append(copy.deepcopy(self.f['mappings'][0]))
        self.assertEqual(self.run_model()['records'][0]['mapping_count'],1)
        self.f['mappings'][0]['output']='fan.hi_example_removed'
        self.assertTrue(any(a['code']=='orphaned_mapping' for a in self.run_model()['attention']))

    def test_percentage_is_only_observed_valid_fan_attribute(self):
        entity=self.f['configured'][0]['entity_id']
        for value in (float('nan'),-1,101,True,'65'):
            self.f['states'][entity]={'state':'on','attributes':{'percentage':value}}
            self.assertIsNone(self.run_model()['records'][0]['percentage'])
        self.f['states'][entity]={'state':'on','attributes':{'percentage':65}}
        self.assertEqual(self.run_model()['records'][0]['operation']['label'],'On · 65%')

    def test_plain_text_contract_no_raw_attributes_and_no_mutation(self):
        label='<img src=x onerror=alert(1)>'
        self.f['configured'][0]['label']=label
        self.f['states'][self.f['configured'][0]['entity_id']]['attributes']={'vendor_secret':'should never be copied'}
        before=copy.deepcopy(self.f)
        p=self.run_model()
        self.assertEqual(p['records'][0]['label'],label) # Renderer must use textContent.
        self.assertNotIn('vendor_secret',json.dumps(p))
        self.assertEqual(self.f,before)

    def test_limits_and_malformed_inputs_reject(self):
        for args in [(None,{},[]),([],{ },None),([],[],[]),([{}],{},[]),([],{},[{}]),([self.f['configured'][0]]*(MAX_CONFIG+1),{},[])]:
            with self.assertRaises(ValueError):normalize(*args)
        self.f['configured'][0]['isolated']='false'
        with self.assertRaises(ValueError):self.run_model()

    def test_unknown_domain_on_is_not_active(self):
        self.f['configured'][0]['entity_id']='air_purifier.hi_example_unknown'
        self.f['states']['air_purifier.hi_example_unknown']={'state':'on'}
        p=self.run_model()
        self.assertEqual(p['counts']['on'],0)
        self.assertFalse(p['records'][0]['supported'])

    def test_malformed_semantic_and_rule_fail_closed(self):
        self.f['mappings'][0]['semantic']=[]
        self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')
        self.f['mappings'][0]['semantic']='fault'
        self.f['mappings'][0]['rule']={}
        self.assertEqual(self.run_model()['records'][0]['monitoring']['state'],'incomplete')

    def test_same_source_rule_ties_use_configuration_not_container_order(self):
        m=self.f['mappings'][0]
        m.update(rule='numeric_below',threshold=20,semantic='refill')
        self.f['states'][m['source']]={'state':'5'}
        self.f['mappings'].append(dict(m,threshold=10))
        before=self.run_model()
        self.f['mappings'].reverse()
        self.assertEqual(before,self.run_model())

    def test_problem_and_obstruction_are_not_relabelled_fault(self):
        for semantic in ('problem','obstruction'):
            self.f['mappings'][0]['semantic']=semantic
            self.f['states'][self.f['mappings'][0]['source']]={'state':'on'}
            p=self.run_model()
            self.assertEqual(p['records'][0]['fault']['state'],'not_reported')
            self.assertEqual(p['attention'][0]['code'],semantic)

    def test_humidifier_action_is_explicit_and_separate_from_on(self):
        entity=self.f['configured'][2]['entity_id']
        for value in ('idle','humidifying','drying','off','vendor_new',None):
            self.f['states'][entity]={'state':'on','attributes':{'action':value}}
            p=self.run_model()
            r=p['records'][2]
            self.assertEqual(r['operation']['label'],'On')
            self.assertEqual(p['headline'],'1/4 on')
            self.assertEqual(r['platform_action']['state'],value if value in ('idle','humidifying','drying','off') else 'unknown')
        self.f['states'][entity]={'state':'unavailable','attributes':{'action':'humidifying'}}
        self.assertEqual(self.run_model()['records'][2]['platform_action']['state'],'unknown')

    def test_retry_context_is_separate_fixture_truth_not_inferred(self):
        fixture=next(f for f in fixtures() if f['id']=='humidifier_retry_refill')
        scenario=next(f for f in build_scenarios() if f['id']=='humidifier_retry_refill')
        p=scenario['payload']
        self.assertEqual(p['records'][2]['operation']['state'],'off')
        self.assertEqual(p['attention'][0]['title'],'Refill suggested')
        self.assertEqual(scenario['control_context'],fixture['control_context'])
        self.assertNotIn('Retrying',json.dumps(p))
        self.assertIn('causation is not established',scenario['control_context']['detail'])

    def test_partially_mapped_inventory_never_claims_clear(self):
        p=next(s['payload'] for s in build_scenarios() if s['id']=='partial_mapping_only')
        self.assertEqual(p['state'],'unmonitored')
        self.assertEqual(p['coverage']['state'],'incomplete')
        self.assertEqual(p['coverage']['label'],'Monitoring configured: 3/4 outputs')
        self.assertEqual(p['attention'],[])
        self.assertEqual(p['records'][-1]['monitoring']['state'],'unmonitored')

    def test_larger_fleet_preserves_inventory_shared_roles_and_exact_overflow(self):
        f=next(f for f in fixtures() if f['id']=='larger_mixed_fleet')
        p=normalize(f['configured'],f['states'],f['mappings'])
        self.assertEqual(len(f['configured']),14)
        self.assertEqual(p['counts']['configured'],12)
        self.assertEqual(p['counts']['mapped'],12)
        self.assertEqual(sum(r['mapping_count'] for r in p['records']),14)
        self.assertEqual(p['records'][0]['roles'],['ventilation_zone_1','aq'])
        self.assertEqual(p['records'][1]['roles'],['ventilation_zone_1','alert_power'])
        self.assertEqual(p['records'][0]['mapping_count'],2)
        self.assertEqual([r['entity_id'] for r in p['records']], [r['entity_id'] for r in f['configured'][:12]])
        self.assertEqual(p['counts']['affected'],6)
        self.assertEqual(p['counts']['conditions'],8)
        self.assertEqual(p['chips'][2]['count'],5)
        self.assertGreater(len(p['records'][0]['label']),60)

    def test_alert_only_and_switch_only_have_no_assumed_role_slots(self):
        scenarios={s['id']:s['payload'] for s in build_scenarios()}
        alert=scenarios['alert_only']
        self.assertEqual(alert['counts']['configured'],3)
        self.assertEqual([r['roles'] for r in alert['records']],[['alert_light'],['alert_light'],['alert_power']])
        switches=scenarios['switches_only']
        self.assertEqual(switches['counts']['configured'],5)
        self.assertEqual(switches['counts']['on'],2)
        self.assertEqual(switches['state'],'unmonitored')
        self.assertTrue(all(r['supported'] for r in switches['records']))

    def test_maximum_config_accepts_128_distinct_outputs_and_rejects_129(self):
        configured=[dict(entity_id=f'switch.hi_example_limit_{i}',role='ventilation_zone_1') for i in range(MAX_CONFIG)]
        states={r['entity_id']:{'state':'off'} for r in configured}
        p=normalize(configured,states,[])
        self.assertEqual(p['counts']['configured'],MAX_CONFIG)
        self.assertEqual(len(p['records']),MAX_CONFIG)
        self.assertEqual(p['records'][-1]['entity_id'],configured[-1]['entity_id'])
        with self.assertRaises(ValueError):
            normalize(configured+[dict(entity_id='switch.hi_example_limit_extra',role='aq')],states,[])

    def test_no_service_or_integration_imports(self):
        import ast
        from pathlib import Path
        tree=ast.parse((INTEGRATION_ROOT / 'model.py').read_text())
        imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        self.assertEqual(imports,['math'])

"""Current saved-config contracts for the integrated observer adapter."""
import copy
import unittest

from adaptive_test_support import extract_configured
from adaptive_test_support import MAX_CONFIG, normalize


FAN = 'fan.hi_example_extract'
HUMIDIFIER = 'humidifier.hi_example_reservoir'
LIGHT = 'light.hi_example_alert'
POWER = 'switch.hi_example_alert_power'


def saved_config():
    return {
        'zones': {
            'zone1': {'enabled': True, 'level': 'level2', 'outputs': [FAN], 'rooms': []},
            'zone2': {'enabled': False, 'outputs': ['switch.hi_example_extract']},
        },
        'humidifiers': {
            'level1': {'enabled': False, 'band_adjust': 0, 'outputs': [HUMIDIFIER]},
            'level2': {'enabled': True, 'outputs': [HUMIDIFIER]},
        },
        'aq': {'level1': {'outputs': [FAN]}, 'level2': {'outputs': [POWER]}},
        'alerts': [{'enabled': False, 'trigger_type': 'humidity', 'lights': [LIGHT],
                    'power_entity': POWER, 'duration': 10}],
        'telemetry': [],
    }


class ConfigAdapterTests(unittest.TestCase):
    def test_current_schema_disabled_roles_and_shared_outputs(self):
        rows = extract_configured(saved_config(), {})
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0], {'entity_id': FAN, 'role': 'ventilation_zone_1', 'role_enabled': True})
        self.assertEqual(rows[1]['role'], 'ventilation_zone_2')
        payload = normalize(rows, {}, [])
        by_id = {record['entity_id']: record for record in payload['records']}
        self.assertEqual(by_id[FAN]['roles'], ['ventilation_zone_1', 'aq'])
        self.assertEqual(by_id[HUMIDIFIER]['roles'], ['humidifier_zone_1', 'humidifier_zone_2'])
        self.assertEqual(by_id[POWER]['roles'], ['aq', 'alert_power'])
        self.assertEqual(payload['counts']['configured'], 5)

    def test_whole_section_options_precedence_including_empty(self):
        options = {'zones': {'zone1': {'outputs': [POWER]}}, 'humidifiers': {}, 'alerts': []}
        rows = extract_configured(saved_config(), options)
        self.assertEqual(rows, [
            {'entity_id': POWER, 'role': 'ventilation_zone_1', 'role_enabled': False},
            {'entity_id': FAN, 'role': 'aq', 'role_enabled': False}, {'entity_id': POWER, 'role': 'aq', 'role_enabled': False},
        ])
        self.assertEqual(extract_configured(saved_config(), {
            'zones': {}, 'humidifiers': {}, 'aq': {}, 'alerts': []}), [])

    def test_selected_effective_section_is_validated(self):
        self.assertEqual(extract_configured({'zones': None}, {'zones': {}}), [])
        with self.assertRaisesRegex(ValueError, 'zones'):
            extract_configured({}, {'zones': None})

    def test_explicit_context_and_plain_labels_only(self):
        rows = extract_configured(saved_config(), {}, {FAN: 'Example extract'},
                                  {FAN: {'selected': True, 'isolated': False}})
        self.assertEqual(rows[0]['label'], 'Example extract')
        self.assertIs(rows[0]['selected'], True)
        self.assertIs(rows[0]['isolated'], False)
        self.assertNotIn('safety_conflict', rows[0])
        self.assertNotIn('selected', rows[1])
        for bad in ({'selected': 1}, {'isolated': None}, {'enabled': True}, []):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                extract_configured({}, {}, context={FAN: bad})

    def test_malformed_and_unknown_role_sections_reject(self):
        cases = [
            {'zones': []}, {'zones': {'zone3': {'outputs': [FAN]}}},
            {'zones': {'zone1': None}}, {'humidifiers': {'zone1': {}}},
            {'aq': {'level3': {}}}, {'aq': {'level1': {'outputs': FAN}}},
            {'zones': {'zone1': {'outputs': ['bad entity']}}},
            {'alerts': {}}, {'alerts': [None]}, {'alerts': [{'lights': None}]},
            {'alerts': [{'power_entity': [POWER]}]},
        ]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):
                extract_configured(config, {})

    def test_saved_list_order_and_large_alert_only_inventory(self):
        entities = [f'light.hi_example_alert_{n}' for n in range(24)]
        rows = extract_configured({'alerts': [{'lights': entities, 'power_entity': POWER}]}, {})
        self.assertEqual([row['entity_id'] for row in rows], entities + [POWER])
        self.assertEqual(rows[-1]['role'], 'alert_power')

    def test_record_limit_applies_before_deduplication(self):
        config = {'zones': {'zone1': {'outputs': [FAN] * MAX_CONFIG}}}
        self.assertEqual(len(extract_configured(config, {})), MAX_CONFIG)
        config['alerts'] = [{'power_entity': POWER}]
        with self.assertRaisesRegex(ValueError, '128'):
            extract_configured(config, {})

    def test_no_input_mutation_or_shared_result_context(self):
        arguments = [saved_config(), {}, {FAN: 'Example fan'}, {FAN: {'selected': True}}]
        before = copy.deepcopy(arguments)
        rows = extract_configured(*arguments)
        rows[0]['selected'] = False
        self.assertEqual(arguments, before)
        self.assertTrue(next(row for row in rows if row['role'] == 'aq')['selected'])

    def test_empty_optional_alert_power_is_not_a_phantom_output(self):
        for power in (None, ''):
            self.assertEqual(extract_configured({'alerts': [{'power_entity': power}]}, {}), [])

    def test_invalid_adapter_input_and_labels_reject(self):
        for arguments in (([], {}), ({}, None), ({}, {}, []), ({}, {}, {FAN: 3}),
                          ({}, {}, {'bad': 'Example'}), ({}, {}, {}, [])):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                extract_configured(*arguments)

"""Synthetic registry contract regressions; no Home Assistant dependency."""
import copy
import itertools
import unittest
from adaptive_test_support import discover, identity

O = 'fan.example_output'
S = 'binary_sensor.example_problem'
CONFIG = [dict(entity_id=O, role='ventilation_zone_1')]


def entry(entity, **kw):
    return dict(entity_id=entity, id='example_' + entity.replace('.', '_'), device_id='example_device', **kw)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.registry = [entry(O), entry(S, original_device_class='problem')]
        self.states = {O: 'on', S: 'off'}

    def result(self, **kw):
        args = dict(configured=CONFIG, registry_entries=self.registry, states=self.states)
        args.update(kw)
        return discover(**args)

    def confirmation(self, **kw):
        return dict(output=O, source=S, output_identity=identity(self.registry[0]),
                    source_identity=identity(self.registry[1]), semantic='refill', rule='binary_active', **kw)

    def test_automatic_problem(self):
        result = self.result()
        self.assertEqual(result['mappings'][0]['semantic'], 'problem')
        self.assertEqual(result['mappings'][0]['scope'], 'device')
        self.assertEqual(result['watch_entities'], sorted([O, S]))

    def test_binary_battery_and_connection_polarity(self):
        for cls, semantic in [('battery', 'battery_low'), ('connectivity', 'disconnected')]:
            self.registry[1]['original_device_class'] = cls
            mapping = self.result()['mappings'][0]
            self.assertEqual(mapping['semantic'], semantic)
            if cls == 'connectivity':
                self.assertEqual(mapping['active_values'], ['off'])
                self.assertEqual(mapping['clear_values'], ['on'])

    def test_no_name_inference(self):
        self.registry[1].pop('original_device_class')
        self.registry[1]['entity_category'] = 'diagnostic'
        result = self.result()
        self.assertFalse(result['mappings'])
        self.assertEqual(result['candidates'][0]['status'], 'needs_confirmation')

    def test_class_precedence(self):
        self.states[S] = dict(state='off', attributes=dict(device_class='battery'))
        self.assertEqual(self.result()['mappings'][0]['semantic'], 'battery_low')
        self.registry[1]['device_class'] = 'connectivity'
        self.assertEqual(self.result()['mappings'][0]['semantic'], 'disconnected')
        self.registry[1]['device_class'] = 'motion'
        self.assertFalse(self.result()['mappings'])

    def test_unknown_missing_unavailable_remain_mapped(self):
        for value in ['unknown', 'unavailable', None]:
            self.states[S] = value
            self.assertEqual(len(self.result()['mappings']), 1)

    def test_disabled_not_watched_hidden_watched(self):
        self.registry[1]['disabled_by'] = 'user'
        self.assertEqual(self.result()['candidates'][0]['status'], 'disabled')
        self.assertNotIn(S, self.result()['watch_entities'])
        self.assertFalse(self.result()['mappings'])
        self.registry[1].pop('disabled_by')
        self.registry[1]['hidden_by'] = 'user'
        self.assertTrue(self.result()['candidates'][0]['hidden'])
        self.assertIn(S, self.result()['watch_entities'])

    def test_shared_device_and_duplicate_roles(self):
        other = 'switch.example_output'
        config = CONFIG + [dict(entity_id=other, role='alert_power'), dict(entity_id=O, role='aq')]
        result = self.result(configured=config, registry_entries=self.registry + [entry(other)])
        self.assertEqual(len(result['mappings']), 2)
        self.assertEqual(result['counts']['sources'], 1)
        self.assertTrue(all(x['scope'] == 'device' for x in result['mappings']))

    def test_does_not_scan_other_device_states(self):
        extra = entry('binary_sensor.example_other', original_device_class='problem')
        extra['device_id'] = 'example_other_device'
        self.assertEqual(self.result(), self.result(registry_entries=self.registry + [extra], states=dict(self.states, unrelated='on')))

    def test_no_device_explicitly_unmonitored(self):
        self.registry[0].pop('device_id')
        result = self.result()
        self.assertEqual({n['code'] for n in result['notices']}, {'no_device', 'unmonitored'})
        self.assertFalse(result['candidates'])

    def test_confirmation_overrides_automatic(self):
        result = self.result(confirmations=[self.confirmation()])
        self.assertEqual(len(result['mappings']), 1)
        self.assertEqual(result['mappings'][0]['semantic'], 'refill')

    def test_cross_device_confirmation_explicit(self):
        self.registry[1]['device_id'] = 'example_other_device'
        result = self.result(confirmations=[self.confirmation()])
        self.assertEqual(result['mappings'][0]['scope'], 'explicit_cross_device')

    def test_replacement_and_absent_identity_fail_closed(self):
        confirmation = self.confirmation()
        for changed in ['replacement', None]:
            self.registry[1]['id'] = changed
            result = self.result(confirmations=[confirmation])
            self.assertFalse(result['mappings'])
            self.assertEqual(result['candidates'][0]['status'], 'identity_changed')

    def test_missing_binding_retained_for_review(self):
        confirmation = self.confirmation()
        result = self.result(registry_entries=self.registry[:1], confirmations=[confirmation])
        self.assertEqual(result['candidates'][0]['status'], 'missing')
        self.assertFalse(result['mappings'])

    def test_rename_follows_stable_identity_when_old_id_absent(self):
        confirmation = self.confirmation()
        self.registry[1]['entity_id'] = 'binary_sensor.example_renamed'
        result = self.result(confirmations=[confirmation])
        self.assertEqual(result['mappings'][0]['source'], 'binary_sensor.example_renamed')
        self.assertEqual(result['mappings'][0]['semantic'], 'refill')
        replacement = entry(S, original_device_class='problem')
        replacement['id'] = 'example_replacement'
        result = self.result(registry_entries=self.registry + [replacement], confirmations=[confirmation])
        old = next(c for c in result['candidates'] if c['source'] == S)
        self.assertEqual(old['status'], 'identity_changed')
        self.assertTrue(all(m['semantic'] != 'refill' for m in result['mappings']))

    def test_deterministic_and_no_mutation(self):
        before = copy.deepcopy((CONFIG, self.registry, self.states))
        expected = self.result()
        for reg in itertools.permutations(self.registry):
            self.assertEqual(expected, self.result(registry_entries=list(reg)))
        self.assertEqual(before, (CONFIG, self.registry, self.states))

    def test_numeric_sensor_context_no_threshold(self):
        for cls in ['battery', 'signal_strength']:
            self.registry[1]['entity_id'] = 'sensor.example_reading'
            self.registry[1]['original_device_class'] = cls
            result = self.result()
            self.assertFalse(result['mappings'])
            self.assertEqual(result['candidates'][0]['status'], 'context_only')

    def test_numeric_and_enum_explicit_rules(self):
        for fields in [dict(rule='numeric_below', threshold=20), dict(rule='enum_active_values', active_values=['dirty'], clear_values=['clean'])]:
            confirmation = self.confirmation()
            confirmation.update(fields)
            self.assertEqual(self.result(confirmations=[confirmation])['mappings'][0]['rule'], fields['rule'])

    def test_invalid_and_duplicate_contracts_rejected(self):
        for kwargs in [dict(registry_entries=self.registry * 2), dict(confirmations=[self.confirmation()] * 2),
                       dict(states=[]), dict(configured=[dict(entity_id=O, role='invented')]),
                       dict(registry_entries=[dict(entity_id=O, device_id=[])])]:
            with self.assertRaises(ValueError):
                self.result(**kwargs)
        for change in [dict(rule='numeric_below', threshold=float('nan')), dict(rule='numeric_above', threshold=True), dict(rule='enum_active_values', active_values=['on'], clear_values=['on'])]:
            confirmation = self.confirmation()
            confirmation.update(change)
            with self.assertRaises(ValueError):
                self.result(confirmations=[confirmation])

    def test_unique_identity_fallback_has_no_delimiter_collision(self):
        first = dict(entity_id=S, platform='example:a', unique_id='b')
        second = dict(entity_id=S, platform='example', unique_id='a:b')
        self.assertNotEqual(identity(first), identity(second))

    def test_bounds_fail_instead_of_truncation(self):
        with self.assertRaises(ValueError):
            self.result(registry_entries=[entry('sensor.example_' + str(i)) for i in range(4097)])
        with self.assertRaises(ValueError):
            self.result(registry_entries=self.registry[:1] + [entry('sensor.example_' + str(i), entity_category='diagnostic') for i in range(257)])

"""Snapshot -> discovery -> status -> event transition regressions."""
import copy
import unittest
from adaptive_test_fixtures import base_inputs, confirmation, build_discovery_scenarios
from adaptive_test_support import DiscoverySession


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.configured, self.registry, self.states = base_inputs()
        self.session = DiscoverySession(self.configured, self.registry, self.states)
        self.source = 'binary_sensor.hi_example_device_problem'

    def test_only_targeted_state_events_change_snapshot(self):
        revision=self.session.revision
        self.assertFalse(self.session.state_changed('binary_sensor.hi_example_unrelated_problem', {'state':'on'}))
        self.assertEqual(self.session.revision,revision)
        self.assertTrue(self.session.state_changed(self.source, {'state':'on'}))
        self.assertEqual(self.session.snapshot['payload']['counts']['affected'],2)
        for item in self.session.snapshot['payload']['attention']:
            self.assertEqual(item['scope'],'device')
            self.assertIn('component is not identified',item['scope_label'])

    def test_removed_source_keeps_gap_despite_stale_state(self):
        self.session.state_changed(self.source, {'state':'on'})
        removed=[r for r in self.registry if r['entity_id']!=self.source]
        p=self.session.registry_changed(removed)['payload']
        self.assertEqual({a['code'] for a in p['attention']},{'monitoring_unknown'})
        self.assertEqual(len(p['discovery']['gaps']),2)
        self.assertEqual(p['counts']['available'],3)
        self.session.registry_changed(self.registry)
        self.session.state_changed(self.source, {'state':'off'})
        self.assertEqual(self.session.snapshot['payload']['attention'],[])

    def test_disabled_source_never_watched_or_uses_stale_state(self):
        disabled=copy.deepcopy(self.registry)
        next(r for r in disabled if r['entity_id']==self.source)['disabled_by']='user'
        p=self.session.registry_changed(disabled)
        self.assertNotIn(self.source,p['watch_entities'])
        self.assertEqual({a['code'] for a in p['payload']['attention']},{'monitoring_unknown'})
        self.assertTrue(any(c['status']=='disabled' for c in p['discovery']['candidates']))

    def test_auto_replacement_does_not_silently_reuse_identity(self):
        replacement=copy.deepcopy(self.registry)
        next(r for r in replacement if r['entity_id']==self.source)['id']='example_replacement'
        p=self.session.registry_changed(replacement)
        self.assertEqual(len(p['discovery']['gaps']),2)
        self.assertTrue(all(c['status']=='identity_changed' for c in p['discovery']['candidates'] if c['source']==self.source))
        self.assertEqual({a['code'] for a in p['payload']['attention']},{'monitoring_unknown'})
        self.assertEqual(p['discovery']['counts']['mapped'],3)
        self.assertEqual(p['discovery']['counts']['needs_confirmation'],5)
        self.assertFalse(any(m['source']==self.source for m in p['discovery']['mappings']))

    def test_reenabled_source_requires_fresh_state(self):
        disabled=copy.deepcopy(self.registry)
        next(r for r in disabled if r['entity_id']==self.source)['disabled_by']='user'
        self.session.registry_changed(disabled)
        p=self.session.registry_changed(self.registry)['payload']
        self.assertEqual({a['code'] for a in p['attention']},{'monitoring_unknown'})
        self.session.state_changed(self.source,{'state':'off'})
        self.assertEqual(self.session.snapshot['payload']['attention'],[])

    def test_initial_disabled_recognized_source_is_visible_in_collapsed_coverage(self):
        registry=[r for r in self.registry if not r['entity_id'].endswith(('_filter','_tank'))]
        next(r for r in registry if r['entity_id']==self.source)['disabled_by']='integration'
        p=DiscoverySession(self.configured,registry,self.states).snapshot['payload']
        self.assertEqual(p['coverage']['state'],'incomplete')
        self.assertEqual(p['state'],'unmonitored')
        self.assertIn('1 diagnostic source needs review',[c['label'] for c in p['chips']])
        self.assertFalse(any(a['code']=='fault' for a in p['attention']))

    def test_notices_identify_the_output(self):
        registry=copy.deepcopy(self.registry)
        next(r for r in registry if r['entity_id']=='humidifier.hi_example_device_humidifier')['device_id']=None
        notices=DiscoverySession(self.configured,registry,self.states).snapshot['discovery']['notices']
        self.assertTrue(all(n['output_label']=='Humidifier' for n in notices))

    def test_auto_rename_uses_stable_identity_without_old_gap(self):
        renamed=copy.deepcopy(self.registry)
        new='binary_sensor.hi_example_renamed_problem'
        next(r for r in renamed if r['entity_id']==self.source)['entity_id']=new
        self.session.registry_changed(renamed)
        self.session.state_changed(new, {'state':'off'})
        self.assertEqual(self.session.snapshot['payload']['attention'],[])
        self.assertEqual(self.session.snapshot['discovery']['gaps'],[])
        self.assertNotIn(self.source,self.session.snapshot['watch_entities'])

    def test_confirm_remove_and_rebind_are_explicit(self):
        source='sensor.hi_example_device_tank'
        rule=confirmation(self.registry,'humidifier.hi_example_device_humidifier',source,
                          semantic='refill',rule='enum_active_values',active_values=['empty'],clear_values=['filled'])
        self.session.confirm([rule])
        self.assertEqual(self.session.snapshot['payload']['attention'][0]['code'],'refill')
        self.session.confirm([])
        self.assertEqual(self.session.snapshot['payload']['attention'],[])
        self.assertEqual(self.session.snapshot['discovery']['gaps'],[])

    def test_rejected_registry_is_atomic_and_stop_ignores_events(self):
        before=copy.deepcopy(self.session.snapshot)
        with self.assertRaises(ValueError):self.session.registry_changed(self.registry+self.registry[:1])
        self.assertEqual(self.session.snapshot,before)
        self.assertEqual(self.session.registry,self.registry)
        self.session.stop()
        self.assertFalse(self.session.state_changed(self.source,{'state':'on'}))
        self.assertEqual(self.session.snapshot['watch_entities'],[])
        with self.assertRaises(RuntimeError):self.session.registry_changed(self.registry)

    def test_revoking_renamed_confirmation_drops_intentionally_removed_binding(self):
        source='sensor.hi_example_device_filter'
        rule=confirmation(self.registry,'fan.hi_example_device_fan',source,
                          semantic='replace_filter',rule='numeric_below',threshold=10)
        self.session.confirm([rule])
        renamed=copy.deepcopy(self.registry)
        new='sensor.hi_example_renamed_filter'
        next(r for r in renamed if r['entity_id']==source)['entity_id']=new
        self.session.registry_changed(renamed)
        self.session.state_changed(new,{'state':'7'})
        self.session.confirm([])
        self.assertEqual(self.session.snapshot['payload']['attention'],[])
        self.assertEqual(self.session.snapshot['discovery']['gaps'],[])

    def test_scenario_pipeline_preserves_discovery_and_scope(self):
        scenarios={s['id']:s for s in build_discovery_scenarios()}
        p=scenarios['discovery_confirmed']['payload']
        self.assertEqual({a['code'] for a in p['attention']},{'replace_filter','refill'})
        self.assertEqual(scenarios['discovery_restored']['payload']['attention'],[])
        self.assertTrue(scenarios['discovery_replaced']['payload']['discovery']['gaps'])
        self.assertNotIn('binary_sensor.hi_example_unrelated_problem',scenarios['discovery_automatic']['observer']['watch_entities'])

"""Public display projection must not expose private observer custody."""
import json
import unittest

from adaptive_test_support import identity
from adaptive_test_support import MAX_TEXT
from adaptive_test_support import DiscoverySession


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.outputs = ['fan.example_one', 'fan.example_two']
        self.source = 'sensor.example_diagnostic'
        self.configured = [dict(entity_id=e, role='ventilation_zone_1', label='Output ' + str(i))
                           for i, e in enumerate(self.outputs)]
        self.registry = [dict(entity_id=e, id='private_registry_' + str(i), device_id='private_device')
                         for i, e in enumerate(self.outputs + [self.source])]
        self.registry[-1]['entity_category'] = 'diagnostic'
        self.states = dict.fromkeys(self.outputs, 'on')
        self.states[self.source] = 'clear'

    def rule(self, output=0, semantic='replace_filter', **kwargs):
        return dict(output=self.outputs[output], source=self.source,
                    output_identity=identity(self.registry[output]), source_identity=identity(self.registry[-1]),
                    semantic=semantic, **(kwargs or dict(rule='enum_active_values', active_values=['replace'], clear_values=['clear'])))

    def session(self, rules=None):
        return DiscoverySession(self.configured, self.registry, self.states, rules)

    def association(self, session):
        return session.snapshot['payload']['discovery']['sources'][0]['associations'][0]

    def test_private_inventory_and_identity_never_reach_display(self):
        session = self.session([self.rule()])
        self.assertEqual(session.snapshot['payload']['schema_version'], 2)
        display = session.snapshot['payload']['discovery']
        forbidden = {'candidates', 'mappings', 'watch_entities', 'output_identity', 'source_identity',
                     'device_id', 'unique_id', 'platform', 'id'}
        def check(value):
            if isinstance(value, dict):
                self.assertFalse({key for key in forbidden.intersection(value) if not (key == 'candidates' and isinstance(value[key], int))})
                for child in value.values(): check(child)
            elif isinstance(value, list):
                for child in value: check(child)
        check(display)
        self.assertNotIn('private_registry_', json.dumps(display))
        self.assertNotIn('private_device', json.dumps(display))
        self.assertIn('mappings', session.snapshot['discovery'])
        self.assertIn('source_identity', session.snapshot['discovery']['mappings'][0])
        display['counts']['mapped'] = -1
        self.assertGreaterEqual(session.snapshot['discovery']['counts']['mapped'], 1)

    def test_clear_confirmed_rule_is_inspectable(self):
        session = self.session([self.rule()])
        self.assertFalse(session.snapshot['payload']['attention'])
        association = self.association(session)
        self.assertEqual(association['semantic'], 'replace_filter')
        self.assertEqual(association['origin_label'], 'Explicit confirmation')
        self.assertEqual(association['rule_lines'], ['Attention values:', 'replace', 'Clear values:', 'clear'])

    def test_configured_meanings_stay_neutral_for_clear_active_and_unknown(self):
        from adaptive_test_support import model
        expected = {
            'replace_filter': ('Filter replacement', 'Filter replacement suggested'),
            'refill': ('Refilling', 'Refill suggested'),
            'clean': ('Cleaning', 'Cleaning suggested'),
            'fault': ('Fault', 'Fault reported'),
            'problem': ('Problem', 'Problem reported'),
            'obstruction': ('Obstruction', 'Obstruction reported'),
            'battery_low': ('Low battery', 'Low battery reported'),
            'disconnected': ('Connection loss', 'Connection loss reported'),
            'generic_attention': ('Other attention', 'Attention needed'),
        }
        self.assertEqual(set(expected), set(model.SEMANTICS))
        for semantic, (neutral, active) in expected.items():
            for reading in ('clear', 'replace', 'unfamiliar', 'unavailable'):
                with self.subTest(semantic=semantic, reading=reading):
                    self.states[self.source] = reading
                    session = self.session([self.rule(semantic=semantic)])
                    payload = session.snapshot['payload']
                    self.assertEqual(self.association(session)['meaning_label'], neutral)
                    if reading == 'clear':
                        self.assertEqual(payload['attention'], [])
                    elif reading == 'replace':
                        self.assertEqual(payload['attention'][0]['title'], active)
                        self.assertEqual(payload['attention'][0]['code'], semantic)
                        self.assertEqual(payload['attention'][0]['severity'], model.SEMANTICS[semantic][2])
                    else:
                        self.assertEqual(payload['attention'][0]['code'], 'monitoring_unknown')
                        self.assertNotIn(active, [a['title'] for a in payload['attention']])

    def test_shared_confirmed_meanings_are_not_flattened_by_equal_status(self):
        display = self.session([self.rule(), self.rule(1, 'clean')]).snapshot['payload']['discovery']
        source = display['sources'][0]
        self.assertEqual(source['title'], 'Different meanings by output')
        self.assertEqual({a['semantic'] for a in source['associations']}, {'replace_filter', 'clean'})
        self.assertEqual(len(display['sources']), 1)

    def test_shared_rule_difference_remains_inspectable(self):
        other = self.rule(1, rule='enum_active_values', active_values=['dirty'], clear_values=['clear'])
        source = self.session([self.rule(), other]).snapshot['payload']['discovery']['sources'][0]
        self.assertEqual(source['title'], 'Different meanings by output')
        self.assertIn('dirty', source['associations'][1]['rule_lines'])

    def test_unknown_vendor_value_does_not_change_rule_or_claim_clear(self):
        self.states[self.source] = 'new_vendor_value'
        session = self.session([self.rule()])
        self.assertEqual(session.snapshot['payload']['attention'][0]['code'], 'monitoring_unknown')
        self.assertIn('replace', self.association(session)['rule_lines'])
        self.assertEqual(session.snapshot['payload']['discovery']['sources'][0]['state'], 'new_vendor_value')

    def test_unknown_meaning_has_no_invented_rule(self):
        association = self.association(self.session())
        self.assertIsNone(association['semantic'])
        self.assertEqual(association['rule_lines'], [])
        self.assertEqual(association['meaning_label'], 'Monitoring rule not configured')

    def test_numeric_boundaries_are_explicit_and_do_not_invent_units(self):
        for kind, comparator in [('numeric_below', '<'), ('numeric_above', '>')]:
            with self.subTest(kind=kind):
                association = self.association(self.session([self.rule(rule=kind, threshold=10)]))
                self.assertEqual(association['rule_lines'][0], f'Attention when value {comparator} 10')
                self.assertIn('A value equal to the threshold does not trigger this rule', association['rule_lines'][1])
                self.assertIn('Units are not checked or converted', association['rule_lines'][1])

    def test_binary_rule_has_exact_polarity(self):
        association = self.association(self.session([self.rule(rule='binary_active')]))
        self.assertEqual(association['rule_lines'], ['Attention when: on', 'Clear when: off'])

    def test_display_labels_bounded_but_enum_values_preserved_in_full(self):
        self.configured[0]['label'] = 'x' * 300
        self.registry[-1]['name'] = 'y' * 300
        value = 'v' * MAX_TEXT
        association = self.association(self.session([self.rule(rule='enum_active_values', active_values=[value], clear_values=['clear'])]))
        self.assertEqual(len(association['label']), MAX_TEXT)
        self.assertIn(value, association['rule_lines'])
        self.assertTrue(all(len(line) <= MAX_TEXT for line in association['rule_lines']))

    def test_removed_confirmed_source_has_no_current_applied_rule(self):
        session = self.session([self.rule()])
        session.registry_changed(self.registry[:-1])
        association = self.association(session)
        self.assertEqual(association['status'], 'missing')
        self.assertIsNone(association['semantic'])
        self.assertEqual(association['rule_lines'], [])
        self.assertTrue(session.snapshot['payload']['discovery']['gaps'])

if __name__ == "__main__":
    unittest.main()
