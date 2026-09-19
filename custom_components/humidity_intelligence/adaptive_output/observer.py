"""Pure registry/state observation session. Does not register HA listeners.

Preserves previously recognised source gaps for the session, so deleting a source
cannot silently turn incomplete monitoring into clear. State events only affect the
explicit watch set. No source writes, polling, credentials or device operations.
"""
from copy import deepcopy
from .discovery import discover, validate_retired
from .model import normalize, MAX_MAPPINGS, MAX_TEXT, SEMANTICS


def _display(value):
    """Bound display text only; never use truncation to alter a rule's meaning."""
    return value[:MAX_TEXT] if isinstance(value, str) else ''


def _meaning(mapping):
    """Presentation of an applicable rule, separate from custody and raw config."""
    if not mapping:
        return dict(semantic=None, meaning_label='Meaning not configured',
                    rule_summary='No interpretation applied', rule_lines=[])
    semantic = mapping['semantic']
    rule = mapping['rule']
    result = dict(semantic=semantic, meaning_label=SEMANTICS[semantic][0], rule_lines=[])
    if rule == 'binary_active':
        result.update(rule_summary='Binary state interpretation',
                      rule_lines=['Attention when: on', 'Clear when: off'])
    elif rule == 'enum_active_values':
        # Values are already validated at <=120 characters. Keep each complete
        # value in its own line: prefixing/truncating could change its meaning.
        result.update(rule_summary='Explicit active and clear values',
                      rule_lines=['Attention values:'] + list(mapping['active_values'])
                      + ['Clear values:'] + list(mapping['clear_values']))
    elif rule in ('numeric_below', 'numeric_above'):
        comparator = '<' if rule == 'numeric_below' else '>'
        threshold = str(mapping['threshold'])
        # Finite float-convertible thresholds fit within 400 characters even
        # as full decimal integers. Preserve the exact boundary, not rounding.
        line = f'Attention when value {comparator} {threshold}'
        if len(line) > 400:
            raise ValueError('Numeric rule presentation exceeds supported text bounds.')
        result.update(rule_summary='Strict numeric comparison',
                      rule_lines=[line, 'Equality does not match. Units are not bound by this rule.'])
    else:
        return _meaning(None)
    return result


def _presentation(found, gaps, labels):
    """Whitelist the public display DTO; custody stays in snapshot.discovery.

    HA entity IDs remain only as source more-info targets. Registry/device IDs,
    identity tokens, raw mapping/candidate inventories and watch sets are private
    coordinator state, never sensor presentation attributes.
    """
    display = dict(counts=deepcopy(found['counts']),
        gaps=[{key: _display(gap.get(key)) for key in ('output_label', 'label', 'detail')} for gap in gaps],
        notices=[{key: _display(notice.get(key)) for key in ('output_label', 'code', 'title', 'reason')}
                 for notice in found['notices']],
        summary=f"Device diagnostics · {found['counts']['sources']} sources found",
        detail='Automatically found through output device associations. Recognised meanings are monitored; other readings remain explicit.')
    mappings = {(m['output'], m['source']): m for m in found['mappings']}
    grouped = {}
    for candidate in found['candidates']:
        source = candidate['source']
        row = grouped.setdefault(source, dict(source=source, label=_display(candidate['label']),
                                              state=_display(candidate['state']), associations=[]))
        association = {key: _display(candidate[key]) for key in ('status', 'title', 'reason', 'scope_label')}
        association.update(label=_display(labels.get(candidate['output'], 'Removed output')),
                           origin_label='Explicit confirmation' if candidate['origin'] == 'confirmed' else 'Automatic discovery')
        association.update(_meaning(mappings.get((candidate['output'], source))))
        row['associations'].append(association)
    for row in grouped.values():
        associations = row['associations']
        first = associations[0]
        statuses = {a['status'] for a in associations}
        meanings = {(a['status'], a['semantic'], a['rule_summary'], tuple(a['rule_lines'])) for a in associations}
        different = len(meanings) > 1
        row['title'] = 'Different meanings by output' if different else first['title']
        row['association_label'] = _display(' · '.join(a['label'] for a in associations))
        row['reason'] = 'Interpretation differs by output; inspect the association details.' if different else first['reason']
        row['scope_label'] = first['scope_label'] if len({a['scope_label'] for a in associations}) == 1 else 'Sources include explicitly confirmed associations.'
        row['tone'] = 'warning' if statuses & {'missing', 'disabled', 'identity_changed', 'needs_confirmation'} else 'neutral'
        if statuses <= {'disabled', 'missing', 'identity_changed'}:
            row['state'] = 'Not used as current evidence'
    display['sources'] = list(grouped.values())
    return display


class DiscoverySession:
    def __init__(self, configured, registry, states, confirmations=None, *, known=None, retired=None):
        self.configured = deepcopy(configured)
        self.registry = deepcopy(registry)
        self.states = deepcopy(states)
        self.confirmations = deepcopy(confirmations or [])
        self.retired = deepcopy(validate_retired([] if retired is None else retired))
        retired_identities = {(r['output_identity'], r['source_identity']) for r in self.retired}
        self.known = {pair: deepcopy(row) for pair, row in (known or {}).items()
                      if (row.get('output_identity'), row.get('source_identity')) not in retired_identities}
        self.active = True
        self.revision = 0
        self.snapshot = self._evaluate()

    def _evaluate(self):
        found = discover(self.configured, self.registry, self.states, self.confirmations, self.retired)
        current = {(m['output'], m['source']): deepcopy(m) for m in found['mappings']}
        configured_ids = {row['entity_id'] for row in self.configured}
        gaps = []
        renamed = set()
        for pair, prior in self.known.items():
            if pair[0] not in configured_ids:
                continue
            now = current.get(pair)
            if now is None and prior.get('source_identity') and prior.get('output_identity'):
                # Registry identities survive a harmless entity-id rename. This
                # never follows a replacement entity occupying the old ID.
                matches = [m for m in current.values() if m.get('source_identity') == prior['source_identity']
                           and m.get('output_identity') == prior['output_identity']]
                if len(matches) == 1:
                    renamed.add(pair)
                    continue
            replaced = now and now.get('origin') != 'confirmed' and any(prior.get(k) != now.get(k) for k in ('source_identity', 'output_identity'))
            if now is None or replaced:
                # An unresolved rule is deliberately non-evaluable even if a stale
                # state remains in the state machine. It never replays old alerts.
                current[pair] = {**prior, 'rule': 'unresolved_source'}
                gaps.append(dict(output=pair[0], source=pair[1],
                    label='Diagnostic identity changed' if replaced else 'Previously monitored source unavailable',
                    detail='Review the changed registry association. Previous conditions are not reused.' if replaced
                    else 'A previously recognised source is missing, disabled or no longer associated with this output.'))
                if replaced:
                    for candidate in found['candidates']:
                        if candidate.get('output') == pair[0] and candidate.get('source') == pair[1]:
                            candidate.update(status='identity_changed', title='Binding needs confirmation', reason=gaps[-1]['detail'])
        if len(current) > MAX_MAPPINGS:
            raise ValueError('Discovered monitoring exceeds the supported mapping limit.')
        mappings = list(current.values())
        # Discovery is a candidate inventory; expose only final usable mappings
        # after lifecycle quarantine, not stale pre-reconciliation claims.
        found['mappings'] = [deepcopy(m) for m in mappings if m['rule'] != 'unresolved_source']
        found['counts']['mapped'] = len(found['mappings'])
        found['counts']['needs_confirmation'] = sum(c['status'] in ('needs_confirmation', 'identity_changed', 'missing') for c in found['candidates'])
        payload = normalize(self.configured, self.states, mappings)
        # Version 2 separates the display contract from internal custody.
        payload['schema_version'] = 2
        for record in payload['records']:
            record['configured_roles'] = [dict(role=row['role'], enabled=row.get('role_enabled', False),
                label=row['role'].replace('_', ' ') + (' · enabled' if row.get('role_enabled', False) else ' · disabled'))
                for row in self.configured if row['entity_id'] == record['entity_id']]
            # Listing configuration never means that a role is selected now.
            record['role_context'] = 'Configured roles; enable settings do not prove current selection.'
        for item in payload['attention']:
            match = next((m for m in mappings if m['output'] == item['entity_id'] and m['source'] == item['source']), None)
            if match:
                item['scope'] = match.get('scope', 'explicit')
                item['origin'] = match.get('origin', 'confirmed')
                item['scope_label'] = 'Device-level report; the affected component is not identified.' if item['scope'] == 'device' else 'Explicitly confirmed source-to-output mapping.'
        labels = {r['entity_id']: r['label'] for r in payload['records']}
        for notice in found['notices']:
            notice['output_label'] = labels.get(notice['output'], 'Removed output')
        for gap in gaps:
            gap['output_label'] = labels.get(gap['output'], 'Removed output')
        found['gaps'] = gaps
        payload['discovery'] = _presentation(found, gaps, labels)
        for source in payload['discovery']['sources']:
            raw = self.states.get(source['source'], {})
            metadata = raw.get('observation', {}) if isinstance(raw, dict) else {}
            source['observation'] = {key: value for key, value in metadata.items()
                if (key in ('last_reported', 'last_updated', 'last_changed') and isinstance(value, str) and len(value) <= 64)
                or (key == 'restored' and type(value) is bool)}
            source['observation']['physical_freshness'] = 'not_established'
        unresolved = len({c['source'] for c in found['candidates'] if c['status'] in ('needs_confirmation', 'identity_changed', 'missing')
                          or (c['status'] == 'disabled' and c['recognized'])})
        payload['discovery']['review_count'] = unresolved
        setup_sources = {c['source'] for c in found['candidates'] if c['status'] == 'needs_confirmation'}
        lost_sources = {gap['source'] for gap in gaps}
        payload['discovery']['setup_count'] = len(setup_sources)
        payload['discovery']['lost_count'] = len(lost_sources)
        payload['discovery']['setup_notice'] = (f'{len(setup_sources)} sources have no confirmed interpretation; this is monitoring setup, not device failure.' if setup_sources else '')
        payload['discovery']['lost_notice'] = (f'{len(lost_sources)} previously monitored sources are no longer usable; review their associations.' if lost_sources else '')
        payload['discovery']['retired_count'] = len(self.retired)
        if self.retired:
            payload['coverage']['detail'] += ' Some interpretations are intentionally paused; this does not establish device health.'
            payload['coverage']['state'] = 'incomplete'
            if payload['state'] == 'clear':
                payload['state'] = 'unmonitored'
        if unresolved:
            label = f'{unresolved} diagnostic ' + ('source needs review' if unresolved == 1 else 'sources need review')
            payload['coverage']['detail'] += ' ' + label + '.'
            payload['coverage']['state'] = 'incomplete'
            for chip in payload['chips']:
                if chip['kind'] == 'coverage':
                    chip.update(label=label, tone='warning')
            if payload['state'] == 'clear':
                payload['state'] = 'unmonitored'
        # No previously discovered raw state is retained as current evidence.
        known = {pair: prior for pair, prior in self.known.items() if pair[0] in configured_ids and pair not in renamed}
        for pair, mapping in current.items():
            if mapping['rule'] != 'unresolved_source':
                known[pair] = deepcopy(mapping)
        self.known = known
        self.revision += 1
        disabled = {r['entity_id'] for r in self.registry if r.get('disabled_by') is not None}
        watch = sorted((set(found['watch_entities']) | {p[1] for p in known}) - disabled)
        return dict(payload=payload, discovery=deepcopy(found), watch_entities=watch,
                    revision=self.revision, synthetic=True)

    def _change(self, field, value):
        if not self.active:
            raise RuntimeError('The observation session is stopped.')
        previous = getattr(self, field)
        setattr(self, field, deepcopy(value))
        try:
            result = self._evaluate()
        except Exception:
            setattr(self, field, previous)
            raise
        self.snapshot = result
        return deepcopy(result)

    def state_changed(self, entity_id, state):
        if not self.active or entity_id not in self.snapshot['watch_entities']:
            return False
        states = deepcopy(self.states)
        if state is None:
            states.pop(entity_id, None)
        else:
            states[entity_id] = deepcopy(state)
        self._change('states', states)
        return True

    def registry_changed(self, registry):
        # Validate before touching state. A restored/enabled/replaced source must
        # report again; cached state from before the registry change is not proof.
        discover(self.configured, registry, self.states, self.confirmations, self.retired)
        old = {r['entity_id']:r for r in self.registry}
        new = {r['entity_id']:r for r in registry}
        invalid = set(old) - set(new)
        fields = ('id', 'platform', 'unique_id', 'device_id', 'disabled_by', 'device_class', 'original_device_class')
        invalid.update(eid for eid, row in new.items() if eid not in old or any(row.get(k) != old[eid].get(k) for k in fields))
        previous_states = self.states
        self.states = {eid: state for eid, state in self.states.items() if eid not in invalid}
        try:
            return self._change('registry', registry)
        except Exception:
            self.states = previous_states
            raise

    def confirm(self, confirmations):
        discover(self.configured, self.registry, self.states, confirmations, self.retired)
        removed = {(c['output'], c['source']) for c in self.confirmations} - {(c['output'], c['source']) for c in confirmations}
        revoked = {(c.get('output_identity'), c.get('source_identity')) for c in self.confirmations} - {(c.get('output_identity'), c.get('source_identity')) for c in confirmations}
        previous_known = deepcopy(self.known)
        self.known = {pair: value for pair, value in self.known.items() if pair not in removed
                      and (value.get('output_identity'), value.get('source_identity')) not in revoked}
        try:
            return self._change('confirmations', confirmations)
        except Exception:
            self.known = previous_known
            raise

    def configure(self, configured):
        return self._change('configured', configured)

    def stop(self):
        self.active = False
        self.snapshot = {**self.snapshot, 'watch_entities': []}
