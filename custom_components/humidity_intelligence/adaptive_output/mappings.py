"""Pure, identity-bound observation options; no entity or service operations."""
from copy import deepcopy

from .config_adapter import extract_configured
from .discovery import identity, _rule
from .model import ENTITY, MAX_MAPPINGS
from .meanings import validate_library

SECTION = 'output_observation'
DEFAULTS = {'enabled': False, 'presentation': 'native', 'confirmations': [], 'retired': [], 'custom_meanings': {}}
PAIR_FIELDS = ('output', 'source', 'output_identity', 'source_identity')


def section(value):
    """Validate shape without requiring currently available entities.

    Unresolved identities survive unrelated settings saves. Never silently discard
    malformed saved configuration or reinterpret an unsupported rule.
    """
    if value is None:
        return deepcopy(DEFAULTS)
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('invalid_observation')
    result = {**deepcopy(DEFAULTS), **deepcopy(value)}
    if type(result['enabled']) is not bool or result['presentation'] not in ('native', 'adaptive'):
        raise ValueError('invalid_observation')
    result['custom_meanings'] = validate_library(result['custom_meanings'])
    for key in ('confirmations', 'retired'):
        rows = result[key]
        if not isinstance(rows, list) or len(rows) > MAX_MAPPINGS:
            raise ValueError('invalid_observation')
        seen = set()
        entity_pairs = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('invalid_observation')
            for field in PAIR_FIELDS:
                value = row.get(field)
                if not isinstance(value, str) or not value or len(value) > (800 if field.endswith('_identity') else 120):
                    raise ValueError('invalid_observation')
                if not field.endswith('_identity') and not ENTITY.fullmatch(value):
                    raise ValueError('invalid_observation')
            if row['source'].split('.')[0] not in ('sensor', 'binary_sensor'):
                raise ValueError('invalid_observation')
            pair = row['output_identity'], row['source_identity']
            if pair in seen:
                raise ValueError('duplicate_binding')
            seen.add(pair)
            entity_pair = row['output'], row['source']
            if key == 'confirmations' and entity_pair in entity_pairs:
                raise ValueError('duplicate_binding')
            entity_pairs.add(entity_pair)
            allowed = set(PAIR_FIELDS)
            if key == 'confirmations':
                allowed |= {'semantic', 'rule', 'active_values', 'clear_values', 'threshold', 'origin', 'scope', 'custom_meaning_id'}
                _rule(row)
            if set(row) - allowed:
                raise ValueError('invalid_observation')
    return result


def resolve(row, registry):
    """Follow a stable rename only when the previous entity ID is absent.

    Keep old identity if an entity replaced it; resolving labels is not consent
    to replacement. Returns current IDs plus a match/usable indication.
    """
    result = deepcopy(row)
    by_id = {r['entity_id']: r for r in registry}
    by_identity = {identity(r): r for r in registry if identity(r)}
    usable = True
    for field in ('output', 'source'):
        entry = by_id.get(row[field])
        if entry is None:
            entry = by_identity.get(row[field + '_identity'])
            if entry is not None:
                result[field] = entry['entity_id']
        if entry is None or identity(entry) != row[field + '_identity'] or entry.get('disabled_by') is not None:
            usable = False
    return result, usable


def bind(data, options, registry, draft, custom_meanings=None):
    """Bind a user-selected interpretation to current identities explicitly."""
    outputs = {r['entity_id'] for r in extract_configured(data, options)}
    if not isinstance(draft, dict) or draft.get('output') not in outputs:
        raise ValueError('invalid_output')
    if not isinstance(draft.get('source'), str) or draft['source'].split('.')[0] not in ('sensor', 'binary_sensor'):
        raise ValueError('invalid_source')
    by_id = {r['entity_id']: r for r in registry}
    result = {field: draft[field] for field in ('output', 'source')}
    for field in ('output', 'source'):
        entry = by_id.get(draft[field])
        if entry is None or entry.get('disabled_by') is not None or not identity(entry):
            raise ValueError('unavailable_binding')
        result[field + '_identity'] = identity(entry)
    draft = deepcopy(draft)
    if 'custom_meaning_id' in draft:
        library = validate_library(custom_meanings or {})
        definition = library.get(draft['custom_meaning_id'])
        if definition is None:
            raise ValueError('unknown_meaning')
        draft['semantic'] = definition['classification']
    result.update(_rule(draft))
    # Reuse saved-schema bounds and reject unsupported extraneous form state.
    section({'confirmations': [result]})
    return result


def pair(row):
    return row['output_identity'], row['source_identity']


def replace_binding(settings, row, previous=None):
    """Stage one explicit meaning; unrelated unresolved mappings are retained."""
    result = section(settings)
    old = pair(previous) if previous else pair(row)
    if any(pair(r) == pair(row) and pair(r) != old for r in result['confirmations']):
        raise ValueError('duplicate_binding')
    result['confirmations'] = [r for r in result['confirmations'] if pair(r) != old] + [deepcopy(row)]
    # Explicit new confirmation resumes this pair; old replacement retirement is
    # removed only for the pair the user explicitly edited.
    result['retired'] = [r for r in result['retired'] if pair(r) not in (old, pair(row))]
    return section(result)


def transition(settings, row, action):
    result = section(settings)
    key = pair(row)
    if action == 'revoke':
        result['confirmations'] = [r for r in result['confirmations'] if pair(r) != key]
    elif action == 'retire':
        result['retired'] = [r for r in result['retired'] if pair(r) != key]
        result['retired'].append({field: row[field] for field in PAIR_FIELDS})
    elif action == 'resume':
        result['retired'] = [r for r in result['retired'] if pair(r) != key]
    else:
        raise ValueError('invalid_action')
    return section(result)


def import_bindings(settings, bindings, data, options, registry):
    """Preview import only when companion identities still match exactly.

    Unresolved imports are blocked individually by the explicit flow; nothing is
    rebound to a replacement. Source companion configuration is never modified.
    """
    source = section({'confirmations': bindings})
    if any('custom_meaning_id' in row for row in source['confirmations']):
        raise ValueError('import_custom_meaning')
    result = section(settings)
    for saved in source['confirmations']:
        current, usable = resolve(saved, registry)
        if not usable:
            raise ValueError('import_identity_changed')
        rebound = bind(data, options, registry, current)
        if pair(rebound) != pair(saved):
            raise ValueError('import_identity_changed')
        # Existing meanings must be reviewed individually, never overwritten by import.
        existing = next((r for r in result['confirmations'] if pair(r) == pair(rebound)), None)
        if existing and _rule(existing) != _rule(rebound):
            raise ValueError('import_conflict')
        retired = deepcopy(result['retired'])
        result = replace_binding(result, rebound)
        result['retired'] = retired
    return result
