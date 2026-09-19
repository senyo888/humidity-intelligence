"""Pure, bounded registry-snapshot discovery; no HA access.

Only standardized binary classes have automatic attention rules. Source:
https://developers.home-assistant.io/docs/core/entity/binary-sensor/
Names, percentages and diagnostic category never imply a fault or threshold.
Identity tokens are internal binding metadata, not public diagnostics output.
"""
import json
from math import isfinite
from .model import ENTITY, MAX_CONFIG, MAX_MAPPINGS, ROLES, SEMANTICS

MAX_REGISTRY = 4096
MAX_CANDIDATES = 256
AUTO = {'problem': ('problem', 'binary_active'),
        'battery': ('battery_low', 'binary_active'),
        'connectivity': ('disconnected', 'enum_active_values')}


def identity(entry):
    """Prefer HA's stable registry entry id; entity names are never identity."""
    if not entry:
        return ''
    if entry.get('id'):
        return 'registry:' + entry['id']
    if entry.get('platform') and entry.get('unique_id'):
        return 'unique:' + json.dumps([entry['entity_id'].split('.')[0], entry['platform'], entry['unique_id']], separators=(',', ':'))
    return ''


def _entity(value):
    return isinstance(value, str) and ENTITY.fullmatch(value) is not None


def _class(entry, states):
    raw = states.get(entry['entity_id'])
    attrs = raw.get('attributes', {}) if isinstance(raw, dict) else {}
    live = attrs.get('device_class') if isinstance(attrs, dict) else None
    return entry.get('device_class') if entry.get('device_class') is not None else live if isinstance(live, str) else entry.get('original_device_class')


def _value(states, entity):
    raw = states.get(entity)
    value = raw.get('state') if isinstance(raw, dict) else raw
    return value[:120] if isinstance(value, str) else 'missing'


def _rule(confirmation):
    semantic, rule = confirmation.get('semantic'), confirmation.get('rule')
    if not isinstance(semantic, str) or (semantic not in SEMANTICS and semantic not in ('battery_low', 'disconnected')):
        raise ValueError('Confirmation requires a supported attention semantic.')
    result = dict(semantic=semantic, rule=rule)
    if rule == 'binary_active':
        return result
    if rule == 'enum_active_values':
        active, clear = confirmation.get('active_values'), confirmation.get('clear_values')
        if not isinstance(active, list) or not isinstance(clear, list) or not active or not clear or len(active) + len(clear) > 32:
            raise ValueError('Enum rules require bounded active and clear values.')
        if not all(isinstance(x, str) and 0 < len(x) <= 120 for x in active + clear) or set(active) & set(clear):
            raise ValueError('Enum active and clear values must be valid and disjoint.')
        result.update(active_values=sorted(set(active)), clear_values=sorted(set(clear)))
        return result
    threshold = confirmation.get('threshold')
    if rule not in ('numeric_below', 'numeric_above') or type(threshold) not in (int, float):
        raise ValueError('Numeric rules require a finite threshold.')
    try:
        valid = isfinite(threshold)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Numeric rules require a finite threshold.')
    return dict(result, threshold=threshold)


def validate_retired(retired):
    """Validate exact identity-bound context-only choices; no inferred meaning."""
    if not isinstance(retired, list) or len(retired) > MAX_MAPPINGS:
        raise ValueError('Retired monitoring choices exceed supported bounds.')
    seen = set()
    for item in retired:
        if not isinstance(item, dict) or set(item) != {'output', 'source', 'output_identity', 'source_identity'}:
            raise ValueError('Invalid retired monitoring fields.')
        if not _entity(item['output']) or not _entity(item['source']) or item['source'].split('.')[0] not in ('sensor', 'binary_sensor'):
            raise ValueError('Retired monitoring requires valid output and diagnostic sources.')
        pair = item['output_identity'], item['source_identity']
        if any(not isinstance(value, str) or not 0 < len(value) <= 800 for value in pair):
            raise ValueError('Retired monitoring requires bounded stable identities.')
        if pair in seen:
            raise ValueError('Duplicate retired monitoring identity pair.')
        seen.add(pair)
    return retired


def discover(configured, registry_entries, states, confirmations=None, retired=None):
    """Discover device-scoped sources from supplied snapshots without writes.

    Confirmations bind explicit output/source IDs and both stable identity tokens.
    Missing/replaced bindings remain review candidates; they never silently rebind.
    This stateless call does not remember disappeared auto sources: a lifecycle
    owner must retain prior inventory for removal/rename notices.
    """
    retired = validate_retired([] if retired is None else retired)
    retired_identities = {(row['output_identity'], row['source_identity']) for row in retired}
    confirmations = [] if confirmations is None else confirmations
    if not isinstance(configured, list) or len(configured) > MAX_CONFIG:
        raise ValueError('Configured output collection exceeds supported bounds.')
    if not isinstance(registry_entries, list) or len(registry_entries) > MAX_REGISTRY:
        raise ValueError('Registry snapshot exceeds supported bounds.')
    if not isinstance(states, dict) or len(states) > 1024:
        raise ValueError('State snapshot exceeds supported bounds.')
    if not isinstance(confirmations, list) or len(confirmations) > MAX_MAPPINGS:
        raise ValueError('Confirmation collection exceeds supported bounds.')
    outputs = set()
    for item in configured:
        if not isinstance(item, dict) or not _entity(item.get('entity_id')) or item.get('role') not in ROLES:
            raise ValueError('Configured outputs require valid entity IDs and roles.')
        outputs.add(item['entity_id'])
    registry, devices, identities = {}, {}, set()
    for entry in registry_entries:
        if not isinstance(entry, dict) or not _entity(entry.get('entity_id')):
            raise ValueError('Registry entries require valid entity IDs.')
        for key in ('id', 'device_id', 'entity_category', 'device_class', 'original_device_class', 'platform', 'unique_id', 'disabled_by', 'hidden_by'):
            val = entry.get(key)
            if val is not None and (not isinstance(val, str) or not val or len(val) > 256):
                raise ValueError('Registry metadata must contain bounded nonempty strings or null.')
        eid, ident = entry['entity_id'], identity(entry)
        if eid in registry or (ident and ident in identities):
            raise ValueError('Duplicate registry entity or stable identity is ambiguous.')
        registry[eid] = entry
        if ident:
            identities.add(ident)
        if entry.get('device_id'):
            devices.setdefault(entry['device_id'], []).append(entry)
    by_identity = {identity(entry): entry for entry in registry.values() if identity(entry)}
    confirmed = {}
    for item in confirmations:
        if not isinstance(item, dict) or not _entity(item.get('output')) or not _entity(item.get('source')):
            raise ValueError('Confirmation requires explicit valid output and source IDs.')
        # Follow stable identity only when the old ID is absent. A replacement
        # occupying that ID must be reviewed, never silently bypassed.
        item = dict(item)
        for field in ('output', 'source'):
            expected = item.get(field + '_identity')
            if not isinstance(expected, str) or len(expected) > 800:
                expected = ''
            renamed = by_identity.get(expected)
            if item[field] not in registry and renamed:
                item[field] = renamed['entity_id']
        pair = item['output'], item['source']
        if pair in confirmed:
            raise ValueError('Duplicate confirmation pair is ambiguous.')
        if item['source'].split('.')[0] not in ('sensor', 'binary_sensor'):
            raise ValueError('Only sensor diagnostics can be confirmed.')
        confirmed[pair] = (item, _rule(item))
    candidates, mappings, notices, watch = [], [], [], set(outputs)
    retired_pairs = {}
    for item in retired:
        output = registry.get(item['output']) or by_identity.get(item['output_identity'])
        source = registry.get(item['source']) or by_identity.get(item['source_identity'])
        pair = (output['entity_id'] if output else item['output'], source['entity_id'] if source else item['source'])
        retired_pairs[pair] = item
    pairs = set(confirmed) | set(retired_pairs)
    for output in sorted(outputs):
        entry = registry.get(output)
        device = entry.get('device_id') if entry else None
        if not device:
            notices.append(dict(output=output, code='no_device', title='No device association', reason='Automatic discovery is unavailable. An explicit source can still be confirmed.'))
            continue
        for source in devices.get(device, []):
            domain = source['entity_id'].split('.')[0]
            cls = _class(source, states)
            if source['entity_id'] == output or domain not in ('sensor', 'binary_sensor'):
                continue
            if source.get('entity_category') == 'diagnostic' or (domain == 'binary_sensor' and cls in AUTO) or (domain == 'sensor' and cls in ('battery', 'signal_strength')):
                pairs.add((output, source['entity_id']))
                if len(pairs) > MAX_CANDIDATES:
                    raise ValueError('Discovered output/source pairs exceed supported bounds.')
    if len(pairs) > MAX_CANDIDATES:
        raise ValueError('Discovered output/source pairs exceed supported bounds.')
    for output, source in sorted(pairs):
        out, entry = registry.get(output), registry.get(source)
        item, rule = confirmed.get((output, source), ({}, {}))
        same_device = bool(out and entry and out.get('device_id') and out.get('device_id') == entry.get('device_id'))
        scope = 'device' if same_device else 'explicit_cross_device'
        label = (entry.get('name') or entry.get('original_name')) if entry else None
        label = label[:120] if isinstance(label, str) and label else source
        recognized = bool(rule) or bool(entry and source.startswith('binary_sensor.') and _class(entry, states) in AUTO)
        candidate = dict(output=output, source=source, label=label, state=_value(states, source),
                         recognized=recognized,
                         scope=scope, hidden=bool(entry and entry.get('hidden_by')),
                         output_identity=identity(out), source_identity=identity(entry),
                         origin='confirmed' if item else 'auto',
                         status='needs_confirmation', title='Meaning needs confirmation',
                         reason='Source discovered automatically. Its class does not define an attention rule.')
        retirement = retired_pairs.get((output, source))
        retired_match = (identity(out), identity(entry)) in retired_identities
        if retired_match:
            candidate.update(status='context_only', title='Interpretation paused', recognized=False,
                             reason='Monitoring intentionally not interpreted for this output. Device health is not established.')
            if entry and entry.get('disabled_by') is None:
                watch.add(source)
            else:
                candidate['state'] = 'Not used as current evidence'
        elif retirement and (not out or not entry) and all(
                actual is None or identity(actual) == retirement[field + '_identity']
                for field, actual in (('output', out), ('source', entry))):
            candidate.update(status='context_only', title='Interpretation paused', recognized=False, state='Not used as current evidence',
                             reason='The saved interpretation is intentionally paused. Its source or output is absent; no current evidence is claimed.')
        elif retirement:
            candidate.update(status='identity_changed', title='Paused association needs review',
                             reason='The saved paused association is absent or changed. It has not attached to a replacement.')
        elif not entry or not out or output not in outputs:
            candidate.update(status='missing', title='Saved source or output missing', reason='Saved binding is retained for review and has not been reassigned.')
        elif item and (not identity(out) or not identity(entry) or item.get('output_identity') != identity(out) or item.get('source_identity') != identity(entry)):
            candidate.update(status='identity_changed', title='Binding needs confirmation', reason='Stable identity is absent or changed. Saved meaning has not been applied.')
        elif entry.get('disabled_by') is not None:
            candidate.update(status='disabled', title='Diagnostic disabled', reason='This source is disabled in Home Assistant. HI does not enable it.')
        else:
            watch.add(source)
            cls = _class(entry, states)
            if not item and source.startswith('binary_sensor.') and cls in AUTO:
                semantic, kind = AUTO[cls]
                rule = dict(semantic=semantic, rule=kind)
                if cls == 'connectivity':
                    rule.update(active_values=['off'], clear_values=['on'])
            if rule:
                mapping = dict(output=output, source=source, **rule, origin=candidate['origin'], scope=scope,
                               source_identity=identity(entry), output_identity=identity(out))
                mappings.append(mapping)
                candidate.update(status='confirmed' if item else 'auto_mapped', title='Confirmed meaning' if item else 'Automatically monitored', semantic=rule['semantic'],
                                 reason='Explicitly confirmed source meaning.' if item else 'Recognized Home Assistant binary device class; no name or threshold inference.')
            elif source.startswith('sensor.') and cls in ('battery', 'signal_strength'):
                candidate.update(status='context_only', title='Supporting reading', reason='Reading discovered automatically. No attention threshold is invented.')
        candidate['scope_label'] = 'Device-level evidence; does not identify which output has a hardware fault.' if same_device else 'Explicit association outside the output device.'
        candidates.append(candidate)
    for output in sorted(outputs):
        if not any(m['output'] == output for m in mappings):
            notices.append(dict(output=output, code='unmonitored', title='No interpreted monitoring sources', reason='Operating state remains observable. Device health has not been established.'))
    return dict(mappings=mappings, candidates=candidates, notices=notices, watch_entities=sorted(watch),
                counts=dict(outputs=len(outputs), candidates=len(candidates), mapped=len(mappings),
                            sources=len({c['source'] for c in candidates}),
                            needs_confirmation=sum(c['status'] in ('needs_confirmation', 'identity_changed', 'missing') for c in candidates),
                            disabled=sum(c['status'] == 'disabled' for c in candidates)))
