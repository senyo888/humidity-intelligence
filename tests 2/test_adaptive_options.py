"""Identity and staged options regressions using real HA selectors, no HA services."""
import asyncio
import copy
import importlib
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / 'custom_components/humidity_intelligence/adaptive_output'
NAME = 'hi_adaptive_options_test'


@pytest.fixture
def modules(monkeypatch):
    package = types.ModuleType(NAME)
    package.__path__ = [str(PATH)]
    monkeypatch.setitem(sys.modules, NAME, package)
    mappings = importlib.import_module(NAME + '.mappings')
    options = importlib.import_module(NAME + '.options')
    yield mappings, options
    for name in list(sys.modules):
        if name.startswith(NAME + '.'):
            sys.modules.pop(name, None)


def fixtures():
    data = {'zones': {'zone1': {'outputs': ['fan.example_output']}}}
    registry = [dict(entity_id='fan.example_output', id='example_output_identity', device_id='example_device'),
                dict(entity_id='sensor.example_filter', id='example_source_identity', device_id='example_device', entity_category='diagnostic')]
    rule = dict(output='fan.example_output', source='sensor.example_filter', semantic='replace_filter',
                rule='enum_active_values', active_values=['replace'], clear_values=['clear'])
    return data, registry, rule


def test_unresolved_saved_binding_survives_settings_edit(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    settings = m.section({'confirmations': [saved]})
    settings['enabled'] = True
    assert m.section(settings)['confirmations'] == [saved]
    assert not m.resolve(saved, registry[:1])[1]


def test_identity_rename_and_replacement_have_distinct_custody(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    registry[1]['entity_id'] = 'sensor.example_renamed'
    renamed, usable = m.resolve(saved, registry)
    assert usable and renamed['source'] == 'sensor.example_renamed'
    registry.append(dict(entity_id=rule['source'], id='example_replacement'))
    unchanged, usable = m.resolve(saved, registry)
    assert not usable and unchanged['source'] == rule['source']


def test_explicit_replacement_does_not_discard_unrelated_missing_mapping(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    old = m.bind(data, {}, registry, rule)
    unrelated = {**old, 'source': 'sensor.example_missing', 'source_identity': 'registry:example_missing'}
    settings = m.section({'confirmations': [old, unrelated]})
    registry[1]['id'] = 'example_replacement'
    replacement = m.bind(data, {}, registry, rule)
    result = m.replace_binding(settings, replacement, old)
    assert unrelated in result['confirmations']
    assert old not in result['confirmations']
    assert replacement in result['confirmations']
    assert settings['confirmations'] == [old, unrelated]


def test_retire_resume_and_revoke_keep_distinct_meanings(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    original = m.section({'confirmations': [saved]})
    retired = m.transition(original, saved, 'retire')
    assert retired['confirmations'] == [saved]
    assert set(retired['retired'][0]) == set(m.PAIR_FIELDS)
    resumed = m.transition(retired, saved, 'resume')
    assert not resumed['retired'] and resumed['confirmations'] == [saved]
    revoked = m.transition(retired, saved, 'revoke')
    assert not revoked['confirmations'] and revoked['retired']


def test_import_requires_matching_identity_and_never_mutates_source(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    source = [m.bind(data, {}, registry, rule)]
    before = copy.deepcopy(source)
    imported = m.import_bindings(m.section(None), source, data, {}, registry)
    assert imported['confirmations'] == source and source == before
    registry[1]['id'] = 'replacement'
    with pytest.raises(ValueError, match='import_identity_changed'):
        m.import_bindings(m.section(None), source, data, {}, registry)
    assert source == before


def test_import_preserves_retirement_and_rejects_conflicting_meaning(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    retired = m.transition(m.section({'confirmations': [saved]}), saved, 'retire')
    assert m.import_bindings(retired, [saved], data, {}, registry)['retired'] == retired['retired']
    with pytest.raises(ValueError, match='import_conflict'):
        m.import_bindings(retired, [{**saved, 'semantic': 'clean'}], data, {}, registry)


@pytest.mark.parametrize('values', [dict(active_values=['same'], clear_values=['same']), dict(active_values=[], clear_values=['clear']), dict(active_values=['x'] * 33, clear_values=['clear'])])
def test_invalid_enum_rules_reject_without_saved_mutation(modules, values):
    m, _ = modules
    data, registry, rule = fixtures()
    with pytest.raises(ValueError):
        m.bind(data, {}, registry, {**rule, **values})


@pytest.mark.parametrize('threshold', [float('nan'), float('inf'), True])
def test_numeric_rules_require_finite_non_boolean_threshold(modules, threshold):
    m, _ = modules
    data, registry, rule = fixtures()
    with pytest.raises(ValueError):
        m.bind(data, {}, registry, {**rule, 'rule': 'numeric_below', 'threshold': threshold})


def flow(modules):
    m, o = modules
    data, registry, _ = fixtures()
    class Flow(o.OutputObservationOptionsMixin):
        def __init__(self):
            self._entry = types.SimpleNamespace(data=data, entry_id='example_entry')
            self._options = {}
            self.registry = registry
            self.hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda _: None),
                config_entries=types.SimpleNamespace(async_entries=lambda _: []))
        def _section(self, key, default): return self._options.get(key, default)
        def _observation_registry(self): return self.registry
        def async_show_form(self, **kwargs): return {'type': 'form', **kwargs}
        def async_show_menu(self, **kwargs): return {'type': 'menu', **kwargs}
        async def async_step_init(self, user_input=None): return {'type': 'main_menu'}
    return Flow()


def run(coroutine):
    return asyncio.run(coroutine)


def test_flow_structured_rule_preview_confirmation_and_finish_staging(modules):
    f = flow(modules)
    _, _, rule = fixtures()
    start = run(f.async_step_options_output_add())
    assert start['step_id'] == 'options_output_binding'
    binding = {k: rule[k] for k in ('output', 'source', 'semantic', 'rule')}
    selected = run(f.async_step_options_output_binding(binding))
    assert selected['step_id'] == 'options_output_rule'
    preview = run(f.async_step_options_output_rule({'active_values': ['replace'], 'clear_values': ['clear']}))
    assert preview['step_id'] == 'options_output_confirm'
    assert 'replace' in preview['description_placeholders']['preview']
    assert not f._options
    assert not f._observation()['confirmations']
    run(f.async_step_options_output_confirm({'confirm': True}))
    assert f._observation()['confirmations'] and not f._options
    run(f.async_step_options_output_back())
    assert f._options['output_observation']['confirmations']


def test_flow_cancel_false_confirm_and_identity_change_do_not_stage(modules):
    f = flow(modules)
    _, _, rule = fixtures()
    run(f.async_step_options_output_add({k: rule[k] for k in ('output', 'source', 'semantic', 'rule')}))
    run(f.async_step_options_output_rule({'active_values': ['replace'], 'clear_values': ['clear']}))
    run(f.async_step_options_output_confirm({'confirm': False}))
    assert not f._observation()['confirmations']
    run(f.async_step_options_output_rule({'active_values': ['replace'], 'clear_values': ['clear']}))
    f.registry[1]['id'] = 'changed_after_preview'
    result = run(f.async_step_options_output_confirm({'confirm': True}))
    assert result['errors']['base'] == 'identity_changed'
    assert not f._observation()['confirmations']
    run(f.async_step_options_output_settings({'enabled': True, 'presentation': 'adaptive'}))
    run(f.async_step_options_output_cancel())
    assert not f._options and not f._observation()['enabled']


def test_whole_section_defaults_and_unknown_fields_reject(modules):
    m, _ = modules
    assert m.section(None) == {'enabled': False, 'presentation': 'native', 'confirmations': [], 'retired': []}
    with pytest.raises(ValueError): m.section({'enabled': 'true'})
    with pytest.raises(ValueError): m.section({'presentation': 'guess'})
    with pytest.raises(ValueError): m.section({'unexpected': 1})


def test_manage_retire_missing_binding_can_be_confirmed_but_resume_cannot(modules):
    m, _ = modules
    f = flow(modules)
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    f._options['output_observation'] = m.section({'confirmations': [saved]})
    f.registry = f.registry[:1]
    run(f.async_step_options_output_manage())
    preview = run(f.async_step_options_output_manage({'binding': '0', 'action': 'retire'}))
    assert preview['step_id'] == 'options_output_confirm'
    run(f.async_step_options_output_confirm({'confirm': True}))
    assert f._observation()['retired'] and f._observation()['confirmations'] == [saved]
    run(f.async_step_options_output_manage())
    rejected = run(f.async_step_options_output_manage({'binding': '0', 'action': 'resume'}))
    assert rejected['errors']['base'] == 'unavailable_binding'


def test_manage_stable_choice_survives_changed_discovery_order(modules):
    f = flow(modules)
    run(f.async_step_options_output_manage())
    original = copy.deepcopy(f._observation_choices[0])
    f.registry.insert(0, dict(entity_id='sensor.example_another', id='example_another', device_id='example_device', entity_category='diagnostic'))
    preview = run(f.async_step_options_output_manage({'binding': '0', 'action': 'retire'}))
    assert original['source'] in preview['description_placeholders']['preview']
    run(f.async_step_options_output_confirm({'confirm': True}))
    assert f._observation()['retired'][0]['source'] == original['source']


def test_companion_import_flow_requires_preview_confirm_and_keeps_source(modules):
    m, _ = modules
    f = flow(modules)
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    companion = types.SimpleNamespace(entry_id='example_companion', title='Example companion',
        data={'hi_entry_id': 'example_entry', 'confirmations': [saved]}, options={})
    before = copy.deepcopy(companion.data)
    f.hass.config_entries.async_entries = lambda _: [companion]
    run(f.async_step_options_output_import())
    result = run(f.async_step_options_output_import({'companion': companion.entry_id}))
    assert result['step_id'] == 'options_output_confirm'
    assert not f._observation()['confirmations']
    run(f.async_step_options_output_confirm({'confirm': True}))
    assert f._observation()['confirmations'] == [saved]
    assert companion.data == before and not companion.options
    assert not f._options


def test_real_selectors_accept_structured_values_and_numeric_schema(modules):
    f = flow(modules)
    _, _, rule = fixtures()
    binding = {k: rule[k] for k in ('output', 'source', 'semantic', 'rule')}
    result = run(f.async_step_options_output_add())
    assert result['data_schema'](binding) == binding
    result = run(f.async_step_options_output_binding(binding))
    values = {'active_values': ['replace'], 'clear_values': ['clear']}
    assert result['data_schema'](values) == values
    result = run(f.async_step_options_output_binding({**binding, 'rule': 'numeric_below'}))
    assert result['data_schema']({'threshold': 12.5}) == {'threshold': 12.5}


def test_duplicate_current_entity_pair_with_new_identity_requires_edit(modules):
    m, _ = modules
    data, registry, rule = fixtures()
    old = m.bind(data, {}, registry, rule)
    registry[1]['id'] = 'replacement'
    new = m.bind(data, {}, registry, rule)
    with pytest.raises(ValueError, match='duplicate_binding'):
        m.replace_binding(m.section({'confirmations': [old]}), new)


def test_removed_automatic_source_custody_remains_manageable_and_retirable(modules):
    m, _ = modules
    f = flow(modules)
    data, registry, rule = fixtures()
    # Reproduce an automatic binding remembered by runtime after registry removal;
    # neither explicit options nor current discovery contains this source.
    known = m.bind(data, {}, registry, {**rule, 'semantic': 'problem', 'rule': 'binary_active'})
    known['origin'] = 'auto'
    custody = {(known['output'], known['source']): copy.deepcopy(known)}
    f.hass.data = {'humidity_intelligence': {'example_entry': {
        'output_observer': types.SimpleNamespace(bridge=types.SimpleNamespace(known=custody))}}}
    f.registry = f.registry[:1]
    before = copy.deepcopy(custody)
    result = run(f.async_step_options_output_manage())
    assert result['step_id'] == 'options_output_manage'
    assert len(f._observation_choices) == 1
    assert set(f._observation_choices[0]) == set(m.PAIR_FIELDS)
    preview = run(f.async_step_options_output_manage({'binding': '0', 'action': 'retire'}))
    assert known['source'] in preview['description_placeholders']['preview']
    run(f.async_step_options_output_confirm({'confirm': True}))
    assert f._observation()['retired'] == [{key: known[key] for key in m.PAIR_FIELDS}]
    assert not f._options  # Merely staged in subflow, no premature save.
    assert custody == before
    run(f.async_step_options_output_back())
    assert f._options['output_observation']['retired']
    assert custody == before


def test_known_custody_cannot_override_saved_meaning_or_leak_other_entry(modules):
    m, _ = modules
    f = flow(modules)
    data, registry, rule = fixtures()
    saved = m.bind(data, {}, registry, rule)
    f._options['output_observation'] = m.section({'confirmations': [saved]})
    known = {**saved, 'semantic': 'problem', 'rule': 'binary_active', 'origin': 'auto'}
    foreign = {**known, 'source': 'sensor.example_other_entry', 'source_identity': 'registry:foreign'}
    f.hass.data = {'humidity_intelligence': {
        'example_entry': {'output_observer': types.SimpleNamespace(bridge=types.SimpleNamespace(known={0: known}))},
        'other_entry': {'output_observer': types.SimpleNamespace(bridge=types.SimpleNamespace(known={0: foreign}))}}}
    run(f.async_step_options_output_manage())
    assert len(f._observation_choices) == 1
    assert f._observation_choices[0]['semantic'] == 'replace_filter'
    assert 'sensor.example_other_entry' not in str(f._observation_choices)


def test_import_confirmation_preserves_unrelated_unresolved_binding(modules):
    m, _ = modules
    f = flow(modules)
    data, registry, rule = fixtures()
    imported = m.bind(data, {}, registry, rule)
    unresolved = {**imported, 'source': 'sensor.example_removed', 'source_identity': 'registry:example_removed'}
    f._options['output_observation'] = m.section({'confirmations': [unresolved]})
    companion = types.SimpleNamespace(entry_id='example_companion', title='Example companion',
        data={'hi_entry_id': 'example_entry', 'confirmations': [imported]}, options={})
    f.hass.config_entries.async_entries = lambda _: [companion]
    preview = run(f.async_step_options_output_import({'companion': companion.entry_id}))
    assert preview['step_id'] == 'options_output_confirm'
    assert unresolved['source'] not in preview['description_placeholders']['preview']
    assert f._observation_check == [imported]
    accepted = run(f.async_step_options_output_confirm({'confirm': True}))
    assert accepted['step_id'] == 'options_output_observation'
    assert f._observation()['confirmations'] == [unresolved, imported]
    assert f._options['output_observation']['confirmations'] == [unresolved]
