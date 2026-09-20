"""Native action presentation preserves values and the monitoring transaction."""
import json

from test_adaptive_options import modules, flow, fixtures, run, ROOT


def test_monitoring_actions_are_visible_native_choices_with_unchanged_values(modules):
    f = flow(modules)
    result = run(f.async_step_options_output_manage())
    schema = result['data_schema']
    action_key = next(key for key in schema.schema if key.schema == 'action')
    action = schema.schema[action_key]
    assert action_key.default() == 'edit'
    assert action.serialize()['selector']['select']['mode'] == 'list'
    assert action.config['translation_key'] == 'output_action'
    assert action.config['options'] == ['edit', 'revoke', 'retire', 'resume']
    for value in action.config['options']:
        assert action(value) == value


def test_configured_meaning_labels_are_neutral_and_english_fallback_matches():
    root = ROOT / 'custom_components/humidity_intelligence'
    strings = json.loads((root / 'strings.json').read_text())
    assert strings == json.loads((root / 'translations/en.json').read_text())
    assert strings['selector']['output_semantic']['options'] == {
        'fault': 'Fault', 'problem': 'Problem', 'obstruction': 'Obstruction',
        'replace_filter': 'Filter replacement', 'refill': 'Refilling', 'clean': 'Cleaning',
        'generic_attention': 'Other attention', 'battery_low': 'Low battery',
        'disconnected': 'Connection loss',
    }


def test_monitoring_return_then_discard_keeps_prior_staged_rule(modules):
    f = flow(modules)
    _, _, rule = fixtures()
    run(f.async_step_options_output_add({k: rule[k] for k in ('output', 'source', 'semantic', 'rule')}))
    run(f.async_step_options_output_rule({'active_values': ['replace'], 'clear_values': ['clear']}))
    run(f.async_step_options_output_confirm({'confirm': True}))
    run(f.async_step_options_output_back())
    retained = f._options['output_observation']
    run(f.async_step_options_output_settings({'enabled': True, 'presentation': 'adaptive'}))
    run(f.async_step_options_output_cancel())
    assert f._options['output_observation'] == retained
    assert f._observation() == retained
    assert f._entry.data == fixtures()[0]
