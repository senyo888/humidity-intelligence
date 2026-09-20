"""Structured, staged output observation options. No output or companion writes."""
from copy import deepcopy
import html
import re

import voluptuous as vol
from homeassistant.helpers import entity_registry as er, selector

from .config_adapter import extract_configured
from .const import HI_DOMAIN
from .discovery import discover, identity
from .model import SEMANTICS, MEANING_LABELS
from .meanings import save_meaning, delete_meaning, meaning_uses
from .observer import _meaning
from .mappings import SECTION, PAIR_FIELDS, section, bind, resolve, pair, replace_binding, transition, import_bindings


MEANING_ERRORS = {'invalid_meanings', 'invalid_meaning_name', 'duplicate_meaning_name',
                  'invalid_classification', 'unknown_meaning', 'meaning_limit',
                  'meaning_in_use', 'invalid_replacement', 'invalid_instructions'}

def _select(values, key, **kwargs):
    config = dict(options=values, **kwargs)
    if key not in ('output_entity', 'output_values'):
        config['translation_key'] = key
    return selector.SelectSelector(selector.SelectSelectorConfig(**config))


def _preview_text(value):
    """Description placeholders render Markdown; custom names remain literal."""
    return re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', html.escape(value))


def _preview(row, settings=None):
    row = deepcopy(row)
    custom = (settings or {}).get('custom_meanings', {}).get(row.get('custom_meaning_id'))
    if custom:
        row['semantic'] = custom['classification']
        row['custom_label'] = _preview_text(custom['name'])
    elif row.get('custom_meaning_id'):
        # The compatibility semantic cannot substitute for a missing definition.
        row['meaning_unresolved'] = True
    meaning = _meaning(row)
    return '\n'.join([f"Output: {row['output']}", f"Monitoring source: {row['source']}", meaning['meaning_label'],
                      *([f"What to do: {_preview_text(custom['instructions'])}"] if custom and custom.get('instructions') else []),
                      *([f"Standard guidance: {SEMANTICS[meaning['semantic']][1]}"] if meaning['semantic'] else []),
                      meaning['rule_summary'], *meaning['rule_lines'],
                      'These readings do not prove device health or that a command succeeded.'])


class OutputObservationOptionsMixin:
    """Mixin for HI's existing staged options transaction and Finish action."""

    def _observation(self):
        if not hasattr(self, '_observation_draft'):
            self._observation_draft = section(self._section(SECTION, None))
        return self._observation_draft

    def _observation_registry(self):
        return [dict(entity_id=r.entity_id, id=r.id, platform=r.platform, unique_id=r.unique_id,
                     device_id=r.device_id, disabled_by=r.disabled_by,
                     device_class=r.device_class, original_device_class=r.original_device_class,
                     entity_category=r.entity_category, name=r.name, original_name=r.original_name)
                for r in er.async_get(self.hass).entities.values()]

    def _observation_inputs(self):
        return dict(self._entry.data), dict(self._options)

    def _observation_known_pairs(self):
        """Read this entry's private lifecycle custody for explicit recovery.

        Removed automatic sources no longer exist in discovery or options, but
        remain monitored expectations. Expose their pair as a settings choice,
        never their raw custody or state as a presentation payload. Persist only
        an explicit user's retirement/meaning decision through the usual Finish.
        """
        entry_data = getattr(self.hass, 'data', {}).get(HI_DOMAIN, {}).get(self._entry.entry_id, {})
        observer = entry_data.get('output_observer')
        known = getattr(getattr(observer, 'bridge', None), 'known', {})
        rows = [{field: row[field] for field in PAIR_FIELDS} for row in known.values()]
        return section({'retired': rows})['retired']

    def _observation_pairs(self):
        """Discover only registry/device-linked choices, preserving unresolved pairs."""
        data, options = self._observation_inputs()
        configured = extract_configured(data, options)
        registry = self._observation_registry()
        ids = {r['entity_id'] for r in configured}
        saved = self._observation()['confirmations'] + self._observation()['retired']
        retained_pairs = self._observation_known_pairs()
        devices = {r['device_id'] for r in registry if r['entity_id'] in ids and r.get('device_id')}
        retained = {r[k] for r in saved + retained_pairs for k in ('output', 'source')}
        identities = {r[k] for r in saved + retained_pairs for k in ('output_identity', 'source_identity')}
        relevant = [r for r in registry if r['entity_id'] in ids | retained or r.get('device_id') in devices or identity(r) in identities]
        states = {}
        for row in relevant:
            state = self.hass.states.get(row['entity_id'])
            if state is not None:
                states[row['entity_id']] = {'state': state.state, 'attributes': {'device_class': state.attributes.get('device_class')}}
        found = discover(configured, relevant, states, self._observation()['confirmations'],
                         custom_meanings=self._observation().get('custom_meanings', {}))
        choices = {}
        for row in saved + retained_pairs:
            current, _ = resolve(row, registry)
            choices.setdefault(pair(current), current)
        for candidate in found['candidates']:
            if candidate.get('output_identity') and candidate.get('source_identity'):
                key = candidate['output_identity'], candidate['source_identity']
                choices.setdefault(key, {field: candidate[field] for field in PAIR_FIELDS})
        self._observation_choices = list(choices.values())
        return [{'value': str(i), 'label': f"{r['output']} ← {r['source']}"}
                for i, r in enumerate(self._observation_choices)]

    async def async_step_options_output_observation(self, user_input=None):
        try:
            self._observation()
        except (ValueError, TypeError, KeyError):
            return self.async_show_form(step_id='options_output_observation_error', errors={'base': 'invalid_observation'})
        return self.async_show_menu(step_id='options_output_observation', menu_options=[
            'options_output_settings', 'options_output_add', 'options_output_manage',
            'options_output_meanings', 'options_output_import', 'options_output_back', 'options_output_cancel'])

    async def async_step_options_output_settings(self, user_input=None):
        draft = self._observation()
        if user_input is not None:
            try:
                self._observation_draft = section({**draft, **user_input})
            except (ValueError, TypeError):
                return self.async_show_form(step_id='options_output_settings', errors={'base': 'invalid_observation'})
            return await self.async_step_options_output_observation()
        return self.async_show_form(step_id='options_output_settings', data_schema=vol.Schema({
            vol.Required('enabled', default=draft['enabled']): selector.BooleanSelector(),
            vol.Required('presentation', default=draft['presentation']): _select(['native', 'adaptive'], 'output_presentation'),
        }))

    async def async_step_options_output_add(self, user_input=None):
        self._observation_previous = None
        self._observation_rule = {}
        self._observation_rule_settings = None
        return await self.async_step_options_output_binding(user_input)

    async def async_step_options_output_binding(self, user_input=None):
        data, options = self._observation_inputs()
        outputs = list(dict.fromkeys(r['entity_id'] for r in extract_configured(data, options)))
        if not outputs:
            return self.async_show_form(step_id='options_output_empty', data_schema=vol.Schema({})) if user_input is None else await self.async_step_options_output_observation()
        errors = {}
        current = getattr(self, '_observation_rule', {})
        library = (getattr(self, '_observation_rule_settings', None) or self._observation()).get('custom_meanings', {})
        if user_input is not None:
            if user_input.get('output') not in outputs or user_input.get('semantic') not in {*SEMANTICS, *library, '__add_custom__'} or user_input.get('rule') not in ('binary_active', 'enum_active_values', 'numeric_below', 'numeric_above'):
                errors['base'] = 'invalid_binding'
            else:
                # Retain per-source thresholds/value rules across meaning editing.
                self._observation_rule = {**current, **deepcopy(user_input)}
                self._observation_rule.pop('custom_meaning_id', None)
                choice = user_input['semantic']
                if choice == '__add_custom__':
                    self._observation_meaning_previous_rule = deepcopy(self._observation_rule)
                    self._observation_meaning_previous_rule['semantic'] = current.get('semantic', 'generic_attention')
                    if current.get('custom_meaning_id'):
                        self._observation_meaning_previous_rule['custom_meaning_id'] = current['custom_meaning_id']
                    self._observation_meaning_resume = True
                    self._observation_meaning_id = None
                    return await self.async_step_options_output_meaning_edit()
                if choice != getattr(self, '_observation_created_meaning_id', None):
                    self._observation_rule_settings = None
                if choice in library:
                    self._observation_rule['custom_meaning_id'] = choice
                    self._observation_rule['semantic'] = library[choice]['classification']
                if user_input['rule'] == 'binary_active':
                    return await self._observation_prepare_rule()
                return await self.async_step_options_output_rule()
        def required(key, fallback=None):
            default = current.get('custom_meaning_id', current.get(key, fallback)) if key == 'semantic' else current.get(key, fallback)
            return vol.Required(key, default=default) if default is not None else vol.Required(key)
        return self.async_show_form(step_id='options_output_binding', errors=errors, data_schema=vol.Schema({
            required('output', outputs[0]): _select(outputs, 'output_entity'),
            required('source'): selector.EntitySelector(selector.EntitySelectorConfig(domain=['sensor', 'binary_sensor'])),
            required('semantic', 'generic_attention'): selector.SelectSelector(selector.SelectSelectorConfig(options=[
                *({'value': key, 'label': label} for key, label in MEANING_LABELS.items()),
                *({'value': key, 'label': item['name']} for key, item in library.items()),
                *([{'value': current['custom_meaning_id'], 'label': 'Saved meaning unavailable — choose another meaning'}]
                  if current.get('custom_meaning_id') and current['custom_meaning_id'] not in library else []),
                {'value': '__add_custom__', 'label': 'Add custom meaning…'},
            ])),
            required('rule', 'binary_active'): _select(['binary_active', 'enum_active_values', 'numeric_below', 'numeric_above'], 'output_rule'),
        }))

    async def async_step_options_output_meanings(self, user_input=None):
        library = self._observation().get('custom_meanings', {})
        errors = {}
        if user_input is not None:
            selected = user_input.get('meaning')
            action = user_input.get('action')
            if selected == '__add_custom__':
                self._observation_meaning_id = None
                self._observation_meaning_resume = False
                return await self.async_step_options_output_meaning_edit()
            if selected not in library or action not in ('edit', 'delete'):
                errors['base'] = 'unknown_meaning'
            else:
                self._observation_meaning_id = selected
                self._observation_meaning_resume = False
                if action == 'delete':
                    return await self.async_step_options_output_meaning_delete()
                return await self.async_step_options_output_meaning_edit()
        return self.async_show_form(step_id='options_output_meanings', errors=errors, data_schema=vol.Schema({
            vol.Required('meaning'): selector.SelectSelector(selector.SelectSelectorConfig(options=[
                *({'value': key, 'label': item['name']} for key, item in library.items()),
                {'value': '__add_custom__', 'label': 'Add custom meaning…'},
            ])),
            vol.Required('action', default='edit'): _select(['edit', 'delete'], 'output_meaning_action'),
        }))

    def _meaning_change_preview(self, before, after, meaning_id, operation):
        old = before.get('custom_meanings', {}).get(meaning_id)
        new = after.get('custom_meanings', {}).get(meaning_id)
        lines = [operation]
        if old:
            lines.append(f"Previous meaning: {_preview_text(old['name'])} ({MEANING_LABELS[old['classification']]})")
            lines.append(f"Previous What to do: {_preview_text(old.get('instructions', '')) or 'Not set'}")
        if new:
            lines.append(f"New meaning: {_preview_text(new['name'])} ({MEANING_LABELS[new['classification']]})")
            lines.append(f"New What to do: {_preview_text(new.get('instructions', '')) or 'Not set'}")
            lines.append(f"Standard guidance: {SEMANTICS[new['classification']][1]}")
        uses = meaning_uses(before, meaning_id) if old else []
        lines.append(f'Affected monitoring rules: {len(uses)}')
        for row in uses:
            replacement = next((r for r in after['confirmations'] if pair(r) == pair(row)), None)
            lines.append(f"{row['output']} ← {row['source']}")
            lines.append(_preview(replacement, after) if replacement else 'Remove this saved rule; standard automatic discovery may still apply.')
        lines.append('Source identities and detection rules remain unchanged unless you explicitly remove the associated rules. No device commands change.')
        return '\n\n'.join(lines)

    async def async_step_options_output_meaning_edit(self, user_input=None):
        draft = self._observation()
        meaning_id = getattr(self, '_observation_meaning_id', None)
        current = draft.get('custom_meanings', {}).get(meaning_id, {})
        errors = {}
        if user_input is not None:
            if user_input.get('cancel') is True:
                if getattr(self, '_observation_meaning_resume', False):
                    self._observation_rule = deepcopy(self._observation_meaning_previous_rule)
                    return await self.async_step_options_output_binding()
                return await self.async_step_options_output_meanings()
            try:
                proposed = save_meaning(draft, user_input.get('name'), user_input.get('classification'), meaning_id,
                    instructions=user_input.get('instructions', current.get('instructions', '')))
                if meaning_id is None:
                    meaning_id = next(iter(set(proposed['custom_meanings']) - set(draft.get('custom_meanings', {}))))
                if getattr(self, '_observation_meaning_resume', False):
                    # Library creation and its first source rule are one proposal.
                    self._observation_rule_settings = proposed
                    self._observation_created_meaning_id = meaning_id
                    self._observation_rule['custom_meaning_id'] = meaning_id
                    self._observation_rule['semantic'] = proposed['custom_meanings'][meaning_id]['classification']
                    self._observation_meaning_resume = False
                    if self._observation_rule['rule'] == 'binary_active':
                        return await self._observation_prepare_rule()
                    return await self.async_step_options_output_rule()
                self._observation_pending = proposed
                self._observation_preview = self._meaning_change_preview(draft, proposed, meaning_id, 'Review this reusable monitoring meaning.')
                self._observation_check = []  # Definition edits preserve unavailable source custody.
                return await self.async_step_options_output_confirm()
            except (ValueError, TypeError, KeyError) as exc:
                errors['base'] = str(exc) if str(exc) in MEANING_ERRORS else 'invalid_meanings'
        values = user_input or current
        return self.async_show_form(step_id='options_output_meaning_edit', errors=errors, data_schema=vol.Schema({
            # Permit the explicit cancel path with an empty native text field;
            # save_meaning still requires and validates a name when saving.
            vol.Optional('name', default=values.get('name', '')): selector.TextSelector(),
            vol.Required('classification', default=values.get('classification', 'generic_attention')): _select(list(SEMANTICS), 'output_semantic'),
            vol.Optional('instructions', default=values.get('instructions', current.get('instructions', ''))): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Optional('cancel', default=False): selector.BooleanSelector(),
        }))

    async def async_step_options_output_meaning_delete(self, user_input=None):
        draft = self._observation()
        meaning_id = self._observation_meaning_id
        library = draft.get('custom_meanings', {})
        if meaning_id not in library:
            return await self.async_step_options_output_meanings()
        errors = {}
        if user_input is not None:
            if user_input.get('cancel') is True:
                return await self.async_step_options_output_meanings()
            try:
                replacement = user_input.get('replacement')
                remove_uses = replacement == '__remove_uses__'
                proposed = delete_meaning(draft, meaning_id,
                    replacement=None if replacement in (None, '__none__', '__remove_uses__') else replacement,
                    remove_uses=remove_uses)
                self._observation_pending = proposed
                self._observation_preview = self._meaning_change_preview(draft, proposed, meaning_id, 'Delete this reusable meaning after reviewing its affected rules.')
                self._observation_check = []
                return await self.async_step_options_output_confirm()
            except (ValueError, TypeError, KeyError) as exc:
                errors['base'] = str(exc) if str(exc) in MEANING_ERRORS else 'invalid_meanings'
        choices = [{'value': '__none__', 'label': 'Delete only if unused'},
                   *({'value': key, 'label': f'Replace with {label}'} for key, label in MEANING_LABELS.items()),
                   *({'value': key, 'label': f"Replace with {item['name']}"} for key, item in library.items() if key != meaning_id),
                   {'value': '__remove_uses__', 'label': 'Remove all rules using this meaning'}]
        return self.async_show_form(step_id='options_output_meaning_delete', errors=errors,
            description_placeholders={'name': _preview_text(library[meaning_id]['name']), 'count': str(len(meaning_uses(draft, meaning_id)))},
            data_schema=vol.Schema({
                vol.Required('replacement', default='__none__'): selector.SelectSelector(selector.SelectSelectorConfig(options=choices)),
                vol.Optional('cancel', default=False): selector.BooleanSelector(),
            }))

    async def async_step_options_output_rule(self, user_input=None):
        current = self._observation_rule
        errors = {}
        if user_input is not None:
            self._observation_rule.update(deepcopy(user_input))
            try:
                return await self._observation_prepare_rule()
            except (ValueError, TypeError, KeyError, OverflowError):
                errors['base'] = 'invalid_rule'
        if current['rule'] == 'enum_active_values':
            schema = vol.Schema({
                vol.Required('active_values', default=current.get('active_values', [])): _select([], 'output_values', multiple=True, custom_value=True),
                vol.Required('clear_values', default=current.get('clear_values', [])): _select([], 'output_values', multiple=True, custom_value=True),
            })
        else:
            schema = vol.Schema({vol.Required('threshold', default=current.get('threshold', 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, step='any'))})
        return self.async_show_form(step_id='options_output_rule', data_schema=schema, errors=errors)

    async def _observation_prepare_rule(self):
        data, options = self._observation_inputs()
        try:
            settings = getattr(self, '_observation_rule_settings', None) or self._observation()
            bound = bind(data, options, self._observation_registry(), self._observation_rule, custom_meanings=settings.get('custom_meanings', {}))
            proposed = replace_binding(settings, bound, getattr(self, '_observation_previous', None))
        except (ValueError, TypeError, KeyError, OverflowError):
            if self._observation_rule.get('rule') == 'binary_active':
                return self.async_show_form(step_id='options_output_binding_error', data_schema=vol.Schema({}), errors={'base': 'unavailable_binding'})
            raise
        self._observation_pending = proposed
        self._observation_preview = _preview(bound, proposed)
        self._observation_check = [bound]
        return await self.async_step_options_output_confirm()

    async def async_step_options_output_manage(self, user_input=None):
        choices = (self._observation_pairs() if user_input is None or not hasattr(self, '_observation_choices') else
                   [{'value': str(i), 'label': f"{r['output']} ← {r['source']}"} for i, r in enumerate(self._observation_choices)])
        errors = {}
        if user_input is not None:
            try:
                index = int(user_input['binding'])
                if index < 0:
                    raise ValueError('invalid_binding')
                row = self._observation_choices[index]
                action = user_input['action']
                registry = self._observation_registry()
                current, usable = resolve(row, registry)
                saved = next((r for r in self._observation()['confirmations'] if pair(r) == pair(row)), None)
                if action == 'edit':
                    self._observation_rule_settings = None
                    self._observation_previous = saved or row
                    self._observation_rule = {**(saved or {}), 'output': current['output'], 'source': current['source']}
                    return await self.async_step_options_output_binding()
                if action not in ('revoke', 'retire', 'resume'):
                    raise ValueError('invalid_action')
                if action == 'resume' and not usable:
                    raise ValueError('unavailable_binding')
                self._observation_pending = transition(self._observation(), current, action)
                message = {'revoke': 'Remove the custom rule. Standard automatic meanings may still apply.',
                           'retire': 'Pause monitoring for this source and keep it as context. Its saved rule is kept. Monitoring coverage remains incomplete.',
                           'resume': 'Resume the saved rule below, or standard automatic discovery if no rule is saved.'}[action]
                if action == 'resume' and saved and saved.get('custom_meaning_id') and saved['custom_meaning_id'] not in self._observation().get('custom_meanings', {}):
                    message = 'Resume monitoring for this source. Its saved meaning remains unavailable until repaired; no rule interpretation is applied.'
                self._observation_preview = '\n'.join([message, f"Output: {current['output']}", f"Source: {current['source']}"] + ([_preview(saved, self._observation())] if saved else []))
                self._observation_check = [current] if action == 'resume' else []
                return await self.async_step_options_output_confirm()
            except (ValueError, TypeError, KeyError, IndexError):
                errors['base'] = 'unavailable_binding'
        if not choices:
            return await self.async_step_options_output_empty(user_input)
        return self.async_show_form(step_id='options_output_manage', errors=errors, data_schema=vol.Schema({
            vol.Required('binding'): selector.SelectSelector(selector.SelectSelectorConfig(options=choices)),
            vol.Required('action', default='edit'): _select(['edit', 'revoke', 'retire', 'resume'], 'output_action', mode=selector.SelectSelectorMode.LIST),
        }))

    async def async_step_options_output_import(self, user_input=None):
        companions = {e.entry_id: e for e in self.hass.config_entries.async_entries('hi_adaptive_output')
                      if e.data.get('hi_entry_id') == self._entry.entry_id}
        errors = {}
        if user_input is not None:
            try:
                companion = companions[user_input['companion']]
                bindings = companion.options.get('confirmations', companion.data.get('confirmations', []))
                data, options = self._observation_inputs()
                self._observation_pending = import_bindings(self._observation(), bindings, data, options, self._observation_registry())
                # Only imported identities are newly authorised. Unrelated saved
                # unresolved bindings remain intact and must not block import.
                registry = self._observation_registry()
                self._observation_check = [resolve(row, registry)[0] for row in bindings]
                self._observation_preview = '\n\n'.join(_preview(row, self._observation_pending) for row in self._observation_check) or 'No custom rules to import.'
                return await self.async_step_options_output_confirm()
            except (ValueError, TypeError, KeyError):
                errors['base'] = 'import_unresolved'
        if not companions:
            return await self.async_step_options_output_empty(user_input)
        return self.async_show_form(step_id='options_output_import', errors=errors, data_schema=vol.Schema({
            vol.Required('companion'): selector.SelectSelector(selector.SelectSelectorConfig(options=[
                {'value': key, 'label': entry.title} for key, entry in companions.items()])),
        }))

    async def async_step_options_output_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get('confirm') is True:
                registry = self._observation_registry()
                if any(not resolve(row, registry)[1] for row in self._observation_check):
                    errors['base'] = 'identity_changed'
                else:
                    self._observation_draft = deepcopy(self._observation_pending)
                    self._observation_pending = None
                    self._observation_rule_settings = None
                    return await self.async_step_options_output_observation()
            else:
                self._observation_pending = None
                if getattr(self, '_observation_rule_settings', None):
                    self._observation_rule = deepcopy(getattr(self, '_observation_meaning_previous_rule', {}))
                self._observation_rule_settings = None
                return await self.async_step_options_output_observation()
        return self.async_show_form(step_id='options_output_confirm', data_schema=vol.Schema({
            vol.Required('confirm', default=False): selector.BooleanSelector(),
        }), errors=errors, description_placeholders={'preview': self._observation_preview})

    async def async_step_options_output_back(self, user_input=None):
        self._options[SECTION] = section(self._observation())
        return await self.async_step_init()

    async def async_step_options_output_cancel(self, user_input=None):
        # Discard this subflow's changes, preserving earlier staged HI options.
        self._observation_draft = section(self._section(SECTION, None))
        self._observation_pending = None
        self._observation_rule_settings = None
        self._observation_rule = {}
        return await self.async_step_init()

    async def async_step_options_output_empty(self, user_input=None):
        if user_input is not None:
            return await self.async_step_options_output_observation()
        return self.async_show_form(step_id='options_output_empty', data_schema=vol.Schema({}))

    async def async_step_options_output_binding_error(self, user_input=None):
        return await self.async_step_options_output_binding()

    async def async_step_options_output_observation_error(self, user_input=None):
        return await self.async_step_init()
