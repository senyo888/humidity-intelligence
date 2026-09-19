"""Pure output observation normalization; never imports Home Assistant.

Input records are role-tagged configuration entries in saved order. The adapter
must supply authoritative booleans for selected/isolation/conflict context.
Strings are plain text: consumers MUST use textContent or equivalent escaping.
Oversize/malformed top-level inputs reject rather than silently truncate truth.
"""
from math import isfinite
import re

ROLES = ('ventilation_zone_1', 'ventilation_zone_2', 'aq', 'humidifier_zone_1',
         'humidifier_zone_2', 'alert_light', 'alert_power')
SUPPORTED = {'fan', 'switch', 'humidifier', 'light'}
MAX_CONFIG = 128
MAX_MAPPINGS = 256
MAX_TEXT = 120
ENTITY = re.compile(r'^[a-z_]+\.[a-z0-9_]{1,96}$')
SEMANTICS = {
    'fault': ('Fault reported', 'Inspect the mapped fault source and device instructions.', 4, 'alert-circle'),
    'problem': ('Problem reported', 'Inspect the mapped problem source and device instructions.', 4, 'alert-circle'),
    'obstruction': ('Obstruction reported', 'Inspect the device safely using its obstruction instructions.', 4, 'alert-circle'),
    'replace_filter': ('Filter replacement reported', 'Check the filter and follow the device replacement instructions.', 5, 'filter'),
    'refill': ('Refill reported', 'Check the reservoir and follow the device refill instructions.', 5, 'water'),
    'clean': ('Cleaning reported', 'Follow the device cleaning instructions.', 5, 'brush'),
    'generic_attention': ('Attention reported', 'Inspect the explicitly mapped source and device instructions.', 5, 'information'),
    'battery_low': ('Low battery reported', 'Check the device battery and its replacement instructions.', 5, 'battery'),
    'disconnected': ('Connection lost reported', 'Check the device connection and its integration.', 6, 'wifi-off'),
}


def _text(value, fallback=''):
    return value[:MAX_TEXT] if isinstance(value, str) else fallback


def _id(value):
    return isinstance(value, str) and ENTITY.fullmatch(value) is not None


def _state(states, entity):
    value = states.get(entity)
    if isinstance(value, dict):
        value = value.get('state')
    return value if isinstance(value, str) and len(value) <= MAX_TEXT else None


def _facet(state, label, tone='neutral', icon='information'):
    return dict(state=state, label=label, tone=tone, icon=icon)


def _rule(mapping, value):
    """Return active bool or None when rule/source evidence cannot be evaluated."""
    rule = mapping.get('rule')
    if rule == 'binary_active':
        if value not in ('on', 'off'):
            return None
        return value == 'on'
    if rule == 'enum_active_values':
        active = mapping.get('active_values')
        # Explicit clear values prevent novel vendor states from becoming all-clear.
        clear = mapping.get('clear_values')
        if not isinstance(active, list) or not isinstance(clear, list):
            return None
        if not active or not clear or len(active) + len(clear) > 32:
            return None
        if not all(isinstance(v, str) and 0 < len(v) <= MAX_TEXT for v in active + clear):
            return None
        if set(active) & set(clear) or value not in active + clear:
            return None
        return value in active
    if rule in ('numeric_below', 'numeric_above'):
        threshold = mapping.get('threshold')
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            return None
        try:
            measured = float(value)
            if not isfinite(measured) or not isfinite(threshold):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return measured < threshold if rule == 'numeric_below' else measured > threshold
    return None


def normalize(configured, states, mappings):
    """Produce deterministic, bounded, display-ready observational status only."""
    if not isinstance(configured, list) or len(configured) > MAX_CONFIG:
        raise ValueError('Configuration must be a list of at most 128 records.')
    if not isinstance(mappings, list) or len(mappings) > MAX_MAPPINGS:
        raise ValueError('Mappings must be a list of at most 256 records.')
    if not isinstance(states, dict) or len(states) > 1024:
        raise ValueError('States must be a dictionary of at most 1024 entries.')
    for row in configured:
        if not isinstance(row, dict) or not _id(row.get('entity_id')) or row.get('role') not in ROLES:
            raise ValueError('Each output requires a valid entity ID and a known role.')
        if any(k in row and type(row[k]) is not bool for k in ('selected', 'isolated', 'safety_conflict')):
            raise ValueError('Runtime context must contain explicit booleans.')
    records, by_id, attention = [], {}, []
    for role in ROLES:
        for row in configured:
            if row['role'] != role:
                continue
            entity = row['entity_id']
            if entity not in by_id:
                record = dict(entity_id=entity, label=_text(row.get('label'), entity), roles=[],
                              selected=False, isolated=False, safety_conflict=False, index=len(records))
                by_id[entity] = record
                records.append(record)
            record = by_id[entity]
            if role not in record['roles']:
                record['roles'].append(role)
            for key in ('selected', 'isolated', 'safety_conflict'):
                record[key] |= row.get(key, False)

    def add(record, code, title, evidence, action, severity, source='', icon='information'):
        attention.append(dict(entity_id=record['entity_id'] if record else '',
            label=record['label'] if record else 'Saved mapping', code=code, title=title,
            evidence=_text(evidence), action=action, source=source, severity=severity,
            tone='danger' if severity in (0, 4) else 'warning',
            icon=icon, selected=record['selected'] if record else False,
            role_rank=ROLES.index(record['roles'][0]) if record else len(ROLES),
            inventory_index=record['index'] if record else MAX_CONFIG))

    for record in records:
        entity = record['entity_id']
        value = _state(states, entity)
        supported = entity.split('.')[0] in SUPPORTED
        record['supported'] = supported
        record['observed_state'] = _text(value, 'No usable state')
        availability = 'missing' if entity not in states else 'unavailable' if value == 'unavailable' else 'unknown' if value in (None, 'unknown', '') else 'available'
        record['availability'] = _facet(availability, dict(missing='Missing output', unavailable='Unavailable', unknown='State unknown', available='Available')[availability], 'warning' if availability != 'available' else 'neutral')
        operation = ('on' if value == 'on' else 'off' if value == 'off' else 'unknown') if supported and availability == 'available' else 'unknown'
        raw = states.get(entity)
        attrs = raw.get('attributes', {}) if isinstance(raw, dict) else {}
        percent = attrs.get('percentage') if isinstance(attrs, dict) else None
        record['percentage'] = percent if supported and entity.startswith('fan.') and type(percent) in (int, float) and isfinite(percent) and 0 <= percent <= 100 else None
        record['operation'] = _facet(operation, {'on':'On', 'off':'Off', 'unknown':'Operation unknown'}[operation], 'active' if operation == 'on' else 'neutral', 'fan' if operation == 'on' else 'power')
        if operation == 'on' and record['percentage'] is not None:
            record['operation']['label'] = f'On · {record["percentage"]:g}%'
        # A humidifier may be on while idle. Only the platform's explicit action
        # attribute describes activity; absence never becomes inferred operation.
        if entity.startswith('humidifier.'):
            action = attrs.get('action') if isinstance(attrs, dict) else None
            action = action if isinstance(action, str) and action in ('idle', 'humidifying', 'drying', 'off') and availability == 'available' else 'unknown'
            record['platform_action'] = _facet(action, {
                'idle': 'Reported action · Idle', 'humidifying': 'Reported action · Humidifying',
                'drying': 'Reported action · Drying', 'off': 'Reported action · Off',
                'unknown': 'Reported action · Unknown',
            }[action], 'active' if action in ('humidifying', 'drying') else 'neutral')
        record['isolation'] = _facet('isolated' if record['isolated'] else 'not_isolated', 'Isolated' if record['isolated'] else 'Not isolated', 'context', 'lock')
        record['context'] = 'Isolation is reported for a configured role; this is not proof the device is off.' if record['isolated'] else 'Observed state does not prove an HI command succeeded.'
        if record['safety_conflict']:
            add(record, 'safety_conflict', 'Output conflict reported', 'Explicit runtime safety/output conflict is true.', 'Inspect the existing HI reason and isolation controls.', 0, icon='shield-alert')
        if availability == 'missing':
            add(record, 'missing', 'Missing output', 'Configured output has no state entry.', 'Check the saved output mapping and entity registry.', 1)
        if not supported:
            add(record, 'unsupported', 'Control support unconfirmed', 'Configured domain has no confirmed control support.', 'Review the output domain and supported integration contract.', 2)
        if availability == 'unavailable':
            add(record, 'unavailable', 'Unavailable', 'Output state reports unavailable.', 'Check the device connection and its integration.', 3, icon='wifi-off')
        if availability == 'unknown' or (supported and availability == 'available' and operation == 'unknown'):
            add(record, 'state_unknown', 'State unknown', 'Output operation cannot be confirmed from its reported state.', 'Inspect the entity state and integration diagnostics.', 6)
        record['mapping_count'] = record['reporting_count'] = 0

    def mapping_key(mapping):
        # Only bounded declarative rule configuration participates, never observed
        # values, labels, time or arbitrary vendor payloads.
        if not isinstance(mapping, dict):
            raise ValueError('Every mapping must be a dictionary.')
        parts = []
        for field in ('output', 'source', 'semantic', 'rule', 'active_values', 'clear_values', 'threshold'):
            value = mapping.get(field)
            if isinstance(value, list):
                value = tuple(_text(v, '<invalid>') for v in value[:33])
            elif isinstance(value, str):
                value = _text(value)
            elif type(value) not in (int, float, bool, type(None)):
                value = '<invalid>'
            # Reject pathological giant integers before converting to text.
            if type(value) is int and value.bit_length() > 1024:
                value = '<invalid>'
            parts.append(repr(value))
        return tuple(parts)

    seen_mappings = set()
    for mapping in sorted(mappings, key=mapping_key):
        if not isinstance(mapping, dict):
            raise ValueError('Every mapping must be a dictionary.')
        output, source, semantic = mapping.get('output'), mapping.get('source'), mapping.get('semantic')
        if not _id(output) or not _id(source):
            raise ValueError('Every mapping requires valid output and source entity IDs.')
        record = by_id.get(output)
        # Identical mappings count once; differently configured rules remain explicit.
        key = mapping_key(mapping)
        if key in seen_mappings:
            continue
        seen_mappings.add(key)
        if record is None:
            add(None, 'orphaned_mapping', 'Orphaned mapping', 'Mapping refers to an output absent from this configured inventory.', 'Review or remove the saved mapping; it has not been reassigned.', 6, source)
            continue
        record['mapping_count'] += 1
        value = _state(states, source)
        valid = isinstance(semantic, str) and semantic in SEMANTICS and source.split('.')[0] in ('sensor', 'binary_sensor')
        result = _rule(mapping, value) if valid and value not in (None, '', 'unknown', 'unavailable') else None
        if result is None:
            add(record, 'monitoring_unknown', 'Monitoring unknown', f'Source state: {_text(value, "missing")}. Explicit monitoring rule cannot be evaluated.', 'Inspect the saved monitoring source and explicit rule.', 6, source)
        else:
            record['reporting_count'] += 1
            if result:
                title, action, severity, icon = SEMANTICS[semantic]
                rule = mapping['rule']
                criterion = (f'Below the configured threshold of {mapping["threshold"]}.' if rule == 'numeric_below'
                             else f'Above the configured threshold of {mapping["threshold"]}.' if rule == 'numeric_above'
                             else 'Matches a configured attention value.' if rule == 'enum_active_values'
                             else 'Matches the configured active state.')
                add(record, semantic, title, f'Source reports {value}. {criterion}', action, severity, source, icon)

    attention.sort(key=lambda a: (a['severity'], not a['selected'], a['role_rank'], a['inventory_index'], a['code'], a['entity_id'], a['source']))
    affected = []
    for item in attention:
        if item['entity_id'] and item['entity_id'] not in affected:
            affected.append(item['entity_id'])
    for record in records:
        items = [a for a in attention if a['entity_id'] == record['entity_id']]
        mapped, reporting = record['mapping_count'], record['reporting_count']
        monitoring = 'unmonitored' if not mapped else 'reporting' if reporting == mapped else 'incomplete'
        record['monitoring'] = _facet(monitoring, 'Not monitored' if not mapped else f'{reporting}/{mapped} sources reporting')
        record['fault'] = _facet('reported' if any(a['code'] == 'fault' for a in items) else 'not_reported', 'Fault reported' if any(a['code'] == 'fault' for a in items) else 'No mapped fault reported')
        record['maintenance'] = _facet('required' if any(a['severity'] == 5 for a in items) else 'not_reported', 'Maintenance required' if any(a['severity'] == 5 for a in items) else 'No mapped maintenance reported')
        record['status'] = _facet(items[0]['code'], items[0]['title'], items[0]['tone'], items[0]['icon']) if items else record['isolation'] if record['isolated'] else record['operation']
        record['attention'] = items
    count = len(records)
    mapped = sum(r['mapping_count'] > 0 for r in records)
    reporting = sum(r['mapping_count'] > 0 and r['mapping_count'] == r['reporting_count'] for r in records)
    on = sum(r['operation']['state'] == 'on' for r in records)
    counts = dict(configured=count, supported=sum(r['supported'] for r in records), available=sum(r['availability']['state'] == 'available' for r in records), on=on, mapped=mapped, reporting=reporting, affected=len(affected), conditions=len(attention), isolated=sum(r['isolated'] for r in records))
    coverage_state = 'not_configured' if not count else 'unmonitored' if not mapped else 'complete' if reporting == count else 'incomplete'
    coverage = dict(state=coverage_state, label=f'Monitoring {mapped}/{count} mapped', detail=f'{reporting}/{count} outputs have all mapped sources reporting. Only explicitly mapped conditions are covered.')
    state = 'not_configured' if not count and not attention else 'attention' if any(a['severity'] <= 5 for a in attention) else 'degraded' if attention else 'unmonitored' if mapped < count else 'clear'
    headline = f'{on}/{count} on' if count else 'No outputs configured'
    summary = 'Attention required' if attention else 'No mapped issues reported' if mapped else 'Monitoring not configured' if count else 'No outputs configured'
    chips = [dict(label=headline, tone='active' if on else 'neutral', icon='fan', kind='fleet')]
    if affected:
        first = next(a for a in attention if a['entity_id'] == affected[0])
        chips.append(dict(label=f'{first["label"]} · {first["title"]}', tone=first['tone'], icon=first['icon'], kind='attention'))
        if len(affected) > 1:
            chips.append(dict(label=f'+{len(affected)-1} more outputs', tone='warning', icon='plus', kind='overflow', count=len(affected)-1))
    elif attention:
        chips.append(dict(label='Saved mapping needs review', tone='warning', icon='information', kind='attention'))
    elif counts['isolated']:
        chips.append(dict(label=f'{counts["isolated"]} isolated', tone='context', icon='lock', kind='context'))
    if len(chips) < 3 and count:
        chips.append(dict(label=coverage['label'] if mapped else 'Not monitored', tone='neutral', icon='eye', kind='coverage'))
    attention_label = f'Attention required · {len(affected)} ' + ('output' if len(affected) == 1 else 'outputs')
    return dict(schema_version=1, synthetic=True, state=state, headline=headline, summary=summary, attention_label=(attention_label if affected else 'Saved mappings need attention') if attention else 'No attention reported', counts=counts, coverage=coverage, records=records, attention=attention, chips=chips, limits=dict(configured=MAX_CONFIG, mappings=MAX_MAPPINGS, truncated=False), disclaimer='Synthetic sandbox evidence. No live Home Assistant data or control.')
