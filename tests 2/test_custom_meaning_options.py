"""Real-HA selectors and the existing staged settings transaction for meanings."""
import copy
import importlib
from test_adaptive_options import modules, flow, run, fixtures


def library_api(modules):
    return importlib.import_module(modules[1].__package__ + '.meanings')


def begin_custom(f, *, rule='enum_active_values'):
    result = run(f.async_step_options_output_add({'output':'fan.example_output',
        'source':'sensor.example_filter','semantic':'__add_custom__','rule':rule}))
    assert result['step_id'] == 'options_output_meaning_edit'
    return result


def make_bound(modules):
    f = flow(modules)
    begin_custom(f)
    result = run(f.async_step_options_output_meaning_edit({'name':'Check media', 'classification':'replace_filter'}))
    assert result['step_id'] == 'options_output_rule'
    result = run(f.async_step_options_output_rule({'active_values':['replace'], 'clear_values':['clear']}))
    assert 'Check media' in result['description_placeholders']['preview']
    assert not f._observation()['custom_meanings']
    run(f.async_step_options_output_confirm({'confirm':True}))
    return f, next(iter(f._observation()['custom_meanings']))


def test_create_first_rule_stages_name_and_reference_atomically(modules):
    f, ident = make_bound(modules)
    settings=f._observation()
    assert settings['confirmations'][0]['custom_meaning_id']==ident
    assert settings['confirmations'][0]['semantic']=='replace_filter'
    assert not f._options
    run(f.async_step_options_output_back())
    assert f._options['output_observation']==settings
    reopened=flow(modules);reopened._options=copy.deepcopy(f._options)
    assert reopened._observation()==settings


def test_add_cancel_and_false_confirmation_leave_no_orphan_library(modules):
    f=flow(modules);begin_custom(f)
    result=run(f.async_step_options_output_meaning_edit({'cancel':True}))
    assert result['step_id']=='options_output_binding'
    assert not f._observation()['custom_meanings']
    begin_custom(f)
    run(f.async_step_options_output_meaning_edit({'name':'Check media','classification':'generic_attention'}))
    run(f.async_step_options_output_rule({'active_values':['replace'],'clear_values':['clear']}))
    run(f.async_step_options_output_confirm({'confirm':False}))
    assert not f._observation()['custom_meanings'] and not f._observation()['confirmations']
    assert f._observation_rule_settings is None


def test_dropdown_real_selector_uses_names_and_reuse_keeps_independent_rule(modules):
    f,ident=make_bound(modules)
    result=run(f.async_step_options_output_add())
    choices=next(v for k,v in result['data_schema'].schema.items() if k.schema=='semantic').serialize()['selector']['select']['options']
    assert {'value':ident,'label':'Check media'} in choices
    assert not any(ident in row['label'] for row in choices)
    f.registry.append(dict(entity_id='sensor.example_second',id='second_identity',device_id='example_device',entity_category='diagnostic'))
    selected={'output':'fan.example_output','source':'sensor.example_second','semantic':ident,'rule':'numeric_below'}
    assert result['data_schema'](selected)==selected
    run(f.async_step_options_output_binding(selected))
    run(f.async_step_options_output_rule({'threshold':12}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    rows=f._observation()['confirmations']
    assert len(rows)==2 and {r['custom_meaning_id'] for r in rows}=={ident}
    assert rows[0]['active_values']==['replace'] and rows[1]['threshold']==12


def test_rename_reclassify_previews_all_uses_preserves_missing_identity_and_rule(modules):
    f,ident=make_bound(modules);before=copy.deepcopy(f._observation())
    f.registry=[]
    run(f.async_step_options_output_meanings({'meaning':ident,'action':'edit'}))
    preview=run(f.async_step_options_output_meaning_edit({'name':'Check intake','classification':'obstruction'}))
    text=preview['description_placeholders']['preview']
    assert 'Check media' in text and 'Check intake' in text and 'Obstruction' in text
    assert 'device safety instructions' in text and 'sensor.example_filter' in text
    assert f._observation()==before
    run(f.async_step_options_output_confirm({'confirm':True}))
    row=f._observation()['confirmations'][0]
    assert row['semantic']=='obstruction'
    assert {k:v for k,v in row.items() if k!='semantic'}=={k:v for k,v in before['confirmations'][0].items() if k!='semantic'}
    assert f._observation()['custom_meanings'][ident]['name']=='Check intake'


def test_in_use_delete_requires_decision_and_confirmation(modules):
    f,ident=make_bound(modules);before=copy.deepcopy(f._observation())
    run(f.async_step_options_output_meanings({'meaning':ident,'action':'delete'}))
    result=run(f.async_step_options_output_meaning_delete({'replacement':'__none__'}))
    assert result['errors']['base']=='meaning_in_use' and f._observation()==before
    result=run(f.async_step_options_output_meaning_delete({'replacement':'generic_attention'}))
    assert result['step_id']=='options_output_confirm' and 'Other attention' in result['description_placeholders']['preview']
    run(f.async_step_options_output_confirm({'confirm':False}));assert f._observation()==before
    run(f.async_step_options_output_meaning_delete({'replacement':'generic_attention'}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    row=f._observation()['confirmations'][0]
    assert row['semantic']=='generic_attention' and 'custom_meaning_id' not in row
    assert not f._observation()['custom_meanings']


def test_delete_custom_replacement_and_explicit_rule_removal_keep_retirement(modules):
    f,ident=make_bound(modules)
    f._observation_draft=library_api(modules).save_meaning(f._observation(),'Check cartridge','clean')
    replacement=next(k for k in f._observation()['custom_meanings'] if k!=ident)
    run(f.async_step_options_output_meanings({'meaning':ident,'action':'delete'}))
    run(f.async_step_options_output_meaning_delete({'replacement':replacement}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    assert f._observation()['confirmations'][0]['custom_meaning_id']==replacement
    m,_=modules;row=f._observation()['confirmations'][0]
    f._observation_draft=m.transition(f._observation(),row,'retire')
    retired=copy.deepcopy(f._observation()['retired'])
    run(f.async_step_options_output_meanings({'meaning':replacement,'action':'delete'}))
    result=run(f.async_step_options_output_meaning_delete({'replacement':'__remove_uses__'}))
    assert 'standard automatic discovery may still apply' in result['description_placeholders']['preview']
    run(f.async_step_options_output_confirm({'confirm':True}))
    assert not f._observation()['confirmations'] and f._observation()['retired']==retired


def test_library_creation_invalid_names_default_classification_and_visit_cancel(modules):
    f=flow(modules)
    result=run(f.async_step_options_output_meanings({'meaning':'__add_custom__','action':'edit'}))
    assert result['data_schema']({'name':'Inspect intake'})['classification']=='generic_attention'
    for name in ['', 'Fault', 'x'*81]:
        result=run(f.async_step_options_output_meaning_edit({'name':name,'classification':'generic_attention'}))
        assert result['errors'] and not f._observation()['custom_meanings']
    run(f.async_step_options_output_meaning_edit({'name':'Inspect intake','classification':'generic_attention'}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    assert f._observation()['custom_meanings']
    run(f.async_step_options_output_cancel())
    assert not f._observation()['custom_meanings'] and not f._options


def test_nested_cancel_restores_pending_output_source_rule_and_existing_values(modules):
    f,ident=make_bound(modules)
    run(f.async_step_options_output_manage())
    run(f.async_step_options_output_manage({'binding':'0','action':'edit'}))
    old=copy.deepcopy(f._observation_rule)
    run(f.async_step_options_output_binding({'output':old['output'],'source':old['source'],
        'semantic':'__add_custom__','rule':old['rule']}))
    run(f.async_step_options_output_meaning_edit({'cancel':True}))
    assert f._observation_rule==old
    assert f._observation_rule['custom_meaning_id']==ident


def test_optional_instructions_create_preview_edit_cancel_and_reopen(modules):
    f=flow(modules);begin_custom(f)
    text='Inspect the intake.\nUse the device manual.'
    result=run(f.async_step_options_output_meaning_edit({'name':'Check media','classification':'clean','instructions':text}))
    assert result['step_id']=='options_output_rule'
    result=run(f.async_step_options_output_rule({'active_values':['replace'],'clear_values':['clear']}))
    preview=result['description_placeholders']['preview']
    assert 'What to do: Inspect the intake' in preview and 'Standard guidance:' in preview
    run(f.async_step_options_output_confirm({'confirm':True}))
    ident=next(iter(f._observation()['custom_meanings']))
    assert f._observation()['custom_meanings'][ident]['instructions']==text
    run(f.async_step_options_output_meanings({'meaning':ident,'action':'edit'}))
    result=run(f.async_step_options_output_meaning_edit({'name':'Check media','classification':'clean','instructions':'New advice'}))
    preview=result['description_placeholders']['preview']
    assert 'Previous What to do: Inspect the intake' in preview and 'New What to do: New advice' in preview
    run(f.async_step_options_output_confirm({'confirm':False}))
    assert f._observation()['custom_meanings'][ident]['instructions']==text
    run(f.async_step_options_output_back())
    reopened=flow(modules);reopened._options=copy.deepcopy(f._options)
    form=run(reopened.async_step_options_output_meanings({'meaning':ident,'action':'edit'}))
    assert form['data_schema']({'name':'Check media','classification':'clean'})['instructions']==text


def test_preview_custom_text_is_literal_and_instruction_bounds_are_actionable(modules):
    f=flow(modules);begin_custom(f)
    bad=run(f.async_step_options_output_meaning_edit({'name':'Check media','classification':'clean','instructions':'x'*241}))
    assert bad['errors']['base']=='invalid_instructions'
    label='<b>[inspect](https://example.com)</b>'
    instructions='[open](https://example.com) **carefully**'
    run(f.async_step_options_output_meaning_edit({'name':label,'classification':'clean','instructions':instructions}))
    result=run(f.async_step_options_output_rule({'active_values':['replace'],'clear_values':['clear']}))
    text=result['description_placeholders']['preview']
    assert '<b>' not in text and '[open](' not in text and '**carefully**' not in text
    assert '&lt;b&gt;' in text and '\\[open\\]' in text
    assert not f._observation()['custom_meanings']


def test_switching_pending_new_meaning_to_builtin_does_not_keep_unused_definition(modules):
    f=flow(modules);begin_custom(f)
    run(f.async_step_options_output_meaning_edit({'name':'Check media','classification':'clean'}))
    run(f.async_step_options_output_binding({'output':'fan.example_output','source':'sensor.example_filter',
        'semantic':'clean','rule':'enum_active_values'}))
    run(f.async_step_options_output_rule({'active_values':['replace'],'clear_values':['clear']}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    assert not f._observation()['custom_meanings']
    assert f._observation()['confirmations'][0]['semantic']=='clean'


def test_missing_library_reference_has_named_repair_choice_not_raw_id_label(modules):
    f,ident=make_bound(modules)
    f._observation_draft['custom_meanings']={}
    run(f.async_step_options_output_manage())
    result=run(f.async_step_options_output_manage({'binding':'0','action':'edit'}))
    choices=next(v for k,v in result['data_schema'].schema.items() if k.schema=='semantic').serialize()['selector']['select']['options']
    choice=next(row for row in choices if row['value']==ident)
    assert 'unavailable' in choice['label'] and ident not in choice['label']
    run(f.async_step_options_output_binding({'output':'fan.example_output','source':'sensor.example_filter',
        'semantic':'clean','rule':'enum_active_values'}))
    run(f.async_step_options_output_rule({'active_values':['replace'],'clear_values':['clear']}))
    run(f.async_step_options_output_confirm({'confirm':True}))
    assert 'custom_meaning_id' not in f._observation()['confirmations'][0]


def test_missing_meaning_pause_resume_preview_is_gap_not_stale_classification(modules):
    for action in ('retire', 'resume'):
        f, ident = make_bound(modules)
        f._observation_draft['custom_meanings'] = {}
        before = copy.deepcopy(f._observation()['confirmations'])
        run(f.async_step_options_output_manage())
        result = run(f.async_step_options_output_manage({'binding': '0', 'action': action}))
        assert result['step_id'] == 'options_output_confirm'
        preview = result['description_placeholders']['preview']
        assert 'Saved meaning unavailable' in preview
        assert 'Choose an existing meaning or remove this rule' in preview
        assert 'Standard guidance:' not in preview
        assert 'Filter replacement' not in preview and 'device replacement guidance' not in preview
        if action == 'resume':
            assert 'no rule interpretation is applied' in preview
        run(f.async_step_options_output_confirm({'confirm': True}))
        assert f._observation()['confirmations'] == before
        assert f._observation()['confirmations'][0]['custom_meaning_id'] == ident


def test_options_discovery_receives_current_staged_meaning_library(modules, monkeypatch):
    f, _ = make_bound(modules)
    _, options = modules
    seen = []
    original = options.discover
    def capture(*args, **kwargs):
        seen.append(copy.deepcopy(kwargs['custom_meanings']))
        return original(*args, **kwargs)
    monkeypatch.setattr(options, 'discover', capture)
    run(f.async_step_options_output_manage())
    assert seen == [f._observation()['custom_meanings']]


def test_empty_name_does_not_block_native_cancel_but_save_still_requires_name(modules):
    f = flow(modules)
    form = begin_custom(f)
    schema = form['data_schema']
    _, options = modules
    name_key = next(key for key in schema.schema if key.schema == 'name')
    assert isinstance(name_key, options.vol.Optional)
    assert not isinstance(name_key, options.vol.Required)
    cancel = schema({'cancel': True})
    assert cancel['classification'] == 'generic_attention'
    result = run(f.async_step_options_output_meaning_edit(cancel))
    assert result['step_id'] == 'options_output_binding'
    assert f._observation_rule['source'] == 'sensor.example_filter'
    assert not f._observation()['custom_meanings']

    form = begin_custom(f)
    result = run(f.async_step_options_output_meaning_edit(form['data_schema']({})))
    assert result['errors']['base'] == 'invalid_meaning_name'
    assert not f._observation()['custom_meanings']


def test_library_editor_cancel_and_delete_cancel_have_valid_native_defaults(modules):
    f = flow(modules)
    form = run(f.async_step_options_output_meanings({'meaning': '__add_custom__', 'action': 'edit'}))
    result = run(f.async_step_options_output_meaning_edit(form['data_schema']({'cancel': True})))
    assert result['step_id'] == 'options_output_meanings'
    assert not f._observation()['custom_meanings']

    f, ident = make_bound(modules)
    before = copy.deepcopy(f._observation())
    form = run(f.async_step_options_output_meanings({'meaning': ident, 'action': 'delete'}))
    cancel = form['data_schema']({'cancel': True})
    assert cancel['replacement'] == '__none__'
    result = run(f.async_step_options_output_meaning_delete(cancel))
    assert result['step_id'] == 'options_output_meanings'
    assert f._observation() == before
