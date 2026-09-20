"""Reusable entry-scoped meanings: lifecycle and real observer pipeline contracts."""
from copy import deepcopy
from importlib import import_module
import json

import pytest
from adaptive_test_support import PACKAGE, DiscoverySession

meanings = import_module(PACKAGE + '.meanings')
mappings = import_module(PACKAGE + '.mappings')
bridge_module = import_module(PACKAGE + '.bridge')
model = import_module(PACKAGE + '.model')
ID = 'custom_' + 'a' * 32
OTHER = 'custom_' + 'b' * 32


def fixture():
    data = {'zones': {'zone1': {'outputs': ['fan.example_output']}}}
    registry = [dict(entity_id='fan.example_output', id='example_output', device_id='example_device'),
                dict(entity_id='sensor.example_tank', id='example_tank', device_id='example_device', entity_category='diagnostic')]
    states = {'fan.example_output': {'state': 'on'}, 'sensor.example_tank': {'state': 'tank_removed'}}
    library = {ID: {'name': 'Water tank missing', 'classification': 'generic_attention'}}
    rule = dict(output='fan.example_output', source='sensor.example_tank', semantic='generic_attention',
                custom_meaning_id=ID, rule='enum_active_values', active_values=['tank_removed'], clear_values=['ready'])
    bound = mappings.bind(data, {}, registry, rule, custom_meanings=library)
    settings = mappings.section({'enabled': True, 'custom_meanings': library, 'confirmations': [bound]})
    configured = [{'entity_id': 'fan.example_output', 'role': 'ventilation_zone_1', 'label': 'Example output'}]
    return data, registry, states, settings, configured


def session(settings, states=None, registry=None, known=None):
    _, reg, st, _, configured = fixture()
    return DiscoverySession(configured, reg if registry is None else registry, st if states is None else states,
                            settings['confirmations'], custom_meanings=settings['custom_meanings'], known=known,
                            retired=settings['retired'])


def test_existing_settings_need_no_migration_and_library_is_entry_local():
    first = mappings.section(None)
    second = mappings.section({})
    first['custom_meanings'][ID] = {'name': 'Example warning', 'classification': 'generic_attention'}
    assert second['custom_meanings'] == {}
    assert second['enabled'] is False and second['presentation'] == 'native'


def test_create_rename_reclassify_preserve_rule_identity_and_caller_snapshot():
    _, _, _, settings, _ = fixture()
    before = deepcopy(settings)
    renamed = meanings.save_meaning(settings, 'Tank absent', 'generic_attention', ID)
    assert renamed['confirmations'] == settings['confirmations']
    changed = meanings.save_meaning(renamed, 'Tank absent', 'problem', ID)
    assert changed['confirmations'][0] == {**settings['confirmations'][0], 'semantic': 'problem'}
    assert settings == before
    assert len(meanings.meaning_uses(changed, ID)) == 1
    created = meanings.save_meaning(changed, 'Intake needs attention', 'generic_attention')
    new_id = next(k for k in created['custom_meanings'] if k != ID)
    assert meanings.MEANING_ID.fullmatch(new_id)
    assert created['confirmations'] == changed['confirmations']


@pytest.mark.parametrize('name', ['', '   ', 'x'*81, 'Tank\nmissing', '\u202etank', 1, None])
def test_invalid_names_rejected(name):
    with pytest.raises(ValueError, match='invalid_meaning_name'):
        meanings.save_meaning({}, name, 'generic_attention')


@pytest.mark.parametrize('name', ['water TANK missing', ' Water tank missing ', 'Ｗater tank missing', 'Other attention', 'Add custom meaning…'])
def test_duplicate_and_reserved_labels_rejected(name):
    _, _, _, settings, _ = fixture()
    with pytest.raises(ValueError, match='duplicate_meaning_name'):
        meanings.save_meaning(settings, name, 'generic_attention')


def test_literal_markup_name_is_data_not_instructions_or_html():
    _, _, _, settings, _ = fixture()
    changed = meanings.save_meaning(settings, '<b>Tank & lid</b>', 'generic_attention', ID)
    payload = session(changed).snapshot['payload']
    assert payload['attention'][0]['title'] == '<b>Tank & lid</b>'
    assert payload['attention'][0]['action'] == model.SEMANTICS['generic_attention'][1]
    assert '<b>Tank & lid</b>' in payload['discovery']['sources'][0]['associations'][0]['meaning_label']


def test_bounds_and_unknown_ids_fail_without_partial_mutation():
    _, _, _, settings, _ = fixture()
    before = deepcopy(settings)
    with pytest.raises(ValueError, match='unknown_meaning'):
        meanings.save_meaning(settings, 'New', 'problem', OTHER)
    with pytest.raises(ValueError, match='invalid_classification'):
        meanings.save_meaning(settings, 'New', 'invented', ID)
    full = {f'custom_{i:032x}': {'name': f'Example {i}', 'classification': 'generic_attention'} for i in range(32)}
    with pytest.raises(ValueError, match='meaning_limit'):
        meanings.save_meaning({'custom_meanings': full}, 'Too many', 'problem')
    assert settings == before


def test_delete_in_use_requires_explicit_replacement_or_removal():
    _, _, _, settings, _ = fixture()
    with pytest.raises(ValueError, match='meaning_in_use'):
        meanings.delete_meaning(settings, ID)
    replaced = meanings.delete_meaning(settings, ID, replacement='problem')
    assert replaced['custom_meanings'] == {}
    assert replaced['confirmations'][0] == {k: ('problem' if k=='semantic' else v) for k,v in settings['confirmations'][0].items() if k!='custom_meaning_id'}
    removed = meanings.delete_meaning(settings, ID, remove_uses=True)
    assert removed['confirmations'] == [] and removed['custom_meanings'] == {}
    assert settings['confirmations'][0]['custom_meaning_id'] == ID


def test_delete_replace_with_other_meaning_preserves_detection_and_retirement():
    _, _, _, settings, _ = fixture()
    settings['custom_meanings'][OTHER] = {'name': 'Check reservoir', 'classification': 'problem'}
    settings = mappings.transition(settings, settings['confirmations'][0], 'retire')
    result = meanings.delete_meaning(settings, ID, replacement=OTHER)
    assert result['confirmations'][0] == {**settings['confirmations'][0], 'custom_meaning_id': OTHER, 'semantic': 'problem'}
    assert result['retired'] == settings['retired']
    with pytest.raises(ValueError, match='invalid_replacement'):
        meanings.delete_meaning(settings, ID, replacement=ID)


def test_active_clear_novel_and_missing_meaning_never_invent_health():
    _, _, states, settings, _ = fixture()
    active = session(settings).snapshot['payload']
    assert active['attention'][0]['title'] == 'Water tank missing'
    assert active['attention'][0]['code'] == 'generic_attention'
    assert 'Classification: Other attention' in active['discovery']['sources'][0]['associations'][0]['meaning_label']
    states['sensor.example_tank']['state'] = 'ready'
    assert not session(settings, states).snapshot['payload']['attention']
    states['sensor.example_tank']['state'] = 'new_vendor_value'
    assert session(settings, states).snapshot['payload']['attention'][0]['code'] == 'monitoring_unknown'
    settings['custom_meanings'] = {}
    states['sensor.example_tank']['state'] = 'ready'
    missing = session(settings, states).snapshot['payload']
    assert missing['coverage']['state'] == 'incomplete'
    assert missing['attention'][0]['code'] == 'monitoring_unknown'
    assert missing['discovery']['review_count'] == 1
    assert 'Saved meaning unavailable' in json.dumps(missing)
    assert ID not in json.dumps(missing)


def test_missing_custom_reference_blocks_automatic_binary_fallback():
    _, registry, states, settings, _ = fixture()
    registry[1].update(entity_id='binary_sensor.example_problem', device_class='problem')
    states['binary_sensor.example_problem'] = {'state': 'off'}
    settings['confirmations'][0].update(source='binary_sensor.example_problem', rule='binary_active')
    settings['confirmations'][0].pop('active_values');settings['confirmations'][0].pop('clear_values')
    settings['custom_meanings'] = {}
    payload = session(settings, states, registry).snapshot['payload']
    assert payload['coverage']['state'] == 'incomplete'
    assert payload['attention'][0]['code'] == 'monitoring_unknown'


def test_shared_source_different_names_and_reclassification_visible_without_rule_copy():
    _, registry, states, settings, configured = fixture()
    registry.append(dict(entity_id='fan.example_second', id='example_second', device_id='example_device'))
    configured.append(dict(entity_id='fan.example_second', role='ventilation_zone_2', label='Second output'))
    states['fan.example_second'] = {'state': 'off'}
    settings['custom_meanings'][OTHER] = {'name': 'Reservoir not fitted', 'classification': 'generic_attention'}
    settings['confirmations'].append({**settings['confirmations'][0], 'output':'fan.example_second','output_identity':'registry:example_second','custom_meaning_id':OTHER})
    payload = DiscoverySession(configured, registry, states, settings['confirmations'],custom_meanings=settings['custom_meanings']).snapshot['payload']
    assert payload['discovery']['sources'][0]['title'] == 'Different meanings by output'
    assert len(payload['attention']) == 2
    assert {a['title'] for a in payload['attention']} == {'Water tank missing', 'Reservoir not fitted'}


def test_same_custom_id_different_entry_library_and_stale_semantic_are_isolated():
    _, _, _, first, _ = fixture()
    second = deepcopy(first)
    second['custom_meanings'][ID] = {'name': 'Second entry meaning', 'classification':'problem'}
    a, b = session(first).snapshot['payload'], session(second).snapshot['payload']
    assert a['attention'][0]['title'] == 'Water tank missing'
    assert b['attention'][0]['title'] == 'Second entry meaning'
    assert b['attention'][0]['code'] == 'problem'


def test_unknown_reference_cannot_be_bound_or_imported_as_builtin():
    data, registry, _, settings, _ = fixture()
    with pytest.raises(ValueError, match='unknown_meaning'):
        mappings.bind(data, {}, registry, settings['confirmations'][0])
    with pytest.raises(ValueError, match='import_custom_meaning'):
        mappings.import_bindings({}, settings['confirmations'], data, {}, registry)


def test_guidance_is_additive_bounded_literal_and_absent_for_unknown_attention():
    _, _, states, settings, _ = fixture()
    text = 'Reseat the tank.\n<b>Check & close the lid</b>'
    changed = meanings.save_meaning(settings, 'Water tank missing', 'generic_attention', ID, instructions=text)
    payload = session(changed).snapshot['payload']
    assert payload['attention'][0]['action'] == model.SEMANTICS['generic_attention'][1] + '\nYour guidance: ' + text
    association = payload['discovery']['sources'][0]['associations'][0]
    assert association['reason'].endswith('Configured guidance: ' + text)
    states['sensor.example_tank']['state'] = 'unavailable'
    unknown = session(changed, states).snapshot['payload']
    assert text not in unknown['attention'][0]['action']
    assert unknown['coverage']['state'] == 'incomplete'
    # Details explicitly label it configured guidance, not an active-condition claim.
    assert 'Configured guidance:' in unknown['discovery']['sources'][0]['associations'][0]['reason']
    cleared = meanings.save_meaning(changed, 'Water tank missing', 'generic_attention', ID, instructions='')
    assert session(cleared).snapshot['payload']['attention'][0]['action'] == model.SEMANTICS['generic_attention'][1]
    for bad in ['x'*241, 'bad\x00text', '\u202eguidance', None, 42]:
        with pytest.raises(ValueError, match='invalid_instructions'):
            meanings.save_meaning(settings, 'Water tank missing', 'generic_attention', ID, instructions=bad)


def test_maximum_enum_keeps_existing_presentation_line_bound_with_guidance():
    _, _, _, settings, _ = fixture()
    settings['confirmations'][0]['active_values'] = ['tank_removed'] + [f'active_{i}' for i in range(15)]
    settings['confirmations'][0]['clear_values'] = [f'clear_{i}' for i in range(16)]
    settings = meanings.save_meaning(settings, 'x'*80, 'generic_attention', ID, instructions='y'*240)
    association = session(settings).snapshot['payload']['discovery']['sources'][0]['associations'][0]
    assert len(association['rule_lines']) == 34
    assert len(association['meaning_label']) <= 240
    assert all(len(line) <= 400 for line in association['rule_lines'])


def test_custody_roundtrip_rename_reclassification_and_deleted_library_fail_closed():
    data, registry, states, settings, _ = fixture()
    bridge = bridge_module.ObservationBridge()
    kwargs = dict(confirmations=settings['confirmations'], custom_meanings=settings['custom_meanings'])
    payload = bridge.evaluate(data, {}, registry, states, {}, **kwargs)
    assert any(a['title'] == 'Water tank missing' for a in payload['attention'])
    custody = bridge.custody()
    assert 'custom_label' not in json.dumps(custody)
    assert 'custom_instructions' not in json.dumps(custody)
    restored = bridge_module.ObservationBridge.from_custody(custody)
    changed = meanings.save_meaning(settings, 'Changed meaning', 'problem', ID, instructions='Read the label')
    payload = restored.evaluate(data, {}, registry, states, {}, confirmations=changed['confirmations'], custom_meanings=changed['custom_meanings'])
    assert any(a['title'] == 'Changed meaning' and a['code'] == 'problem' for a in payload['attention'])
    missing = restored.evaluate(data, {}, registry, states, {}, confirmations=changed['confirmations'], custom_meanings={})
    assert missing['coverage']['state'] == 'incomplete'
    assert not any(a['title'] in ('Changed meaning','Water tank missing') for a in missing['attention'])
    assert any(a['code'] == 'monitoring_unknown' for a in missing['attention'])
    bridge_module.ObservationBridge.from_custody(restored.custody())
