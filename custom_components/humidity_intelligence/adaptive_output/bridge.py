"""Pure live-snapshot adapter with explicit context and identity custody.

No HA imports or actions. The caller supplies only configured outputs, associated
registry rows, current states and exact native helper identities.
"""
from copy import deepcopy
import json
from hashlib import sha256
from .const import HELPERS, MAX_PAYLOAD_BYTES
from .compact import build_compact
from .config_adapter import extract_configured
from .discovery import _rule, identity
from .model import ENTITY, MAX_MAPPINGS
from .observer import DiscoverySession

CUSTODY_VERSION = 2
MAX_CUSTODY_ENTITIES = 4096
MAX_CUSTODY_BYTES = 2 * 1024 * 1024

REGISTRY_IDENTITY_FIELDS = ('id', 'platform', 'unique_id', 'device_id', 'disabled_by', 'device_class', 'original_device_class')


def validate_bindings(bindings):
    if not isinstance(bindings, list) or len(bindings) > MAX_MAPPINGS:
        raise ValueError('Explicit monitoring bindings exceed supported bounds.')
    allowed = {'output', 'source', 'semantic', 'rule', 'active_values', 'clear_values', 'threshold', 'output_identity', 'source_identity', 'origin', 'scope', 'custom_meaning_id'}
    pairs = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) - allowed:
            raise ValueError('Invalid explicit monitoring binding fields.')
        for key in ('output', 'source'):
            if not isinstance(binding.get(key), str) or not ENTITY.fullmatch(binding[key]):
                raise ValueError('Monitoring bindings require valid entity IDs.')
        for key in ('output_identity', 'source_identity'):
            if not isinstance(binding.get(key), str) or not 0 < len(binding[key]) <= 800:
                raise ValueError('Monitoring bindings require bounded stable identities.')
        pair = binding['output'], binding['source']
        if pair in pairs:
            raise ValueError('Duplicate monitoring binding is ambiguous.')
        pairs.add(pair)
        _rule(binding)
    return deepcopy(bindings)


class ObservationBridge:
    def __init__(self, known=None):
        self.known = {(m['output'], m['source']): m for m in validate_bindings(known or [])}
        self.registry = None
        self.quarantined = set()
        self.session = None
        self.payload = None

    @classmethod
    def from_custody(cls, custody):
        """Restore only bounded binding/invalidation metadata, never source values.

        Legacy known-only custody lacks the registry baseline needed to disprove
        an offline change. Retained sources and outputs require a later event.
        """
        if not isinstance(custody, dict):
            raise ValueError('Invalid monitoring custody record.')
        if set(custody) == {'known'}:
            bridge = cls(validate_bindings(custody['known']))
            bridge.quarantined = {binding[field] for binding in bridge.known.values()
                                  for field in ('output', 'source')}
            return bridge
        if set(custody) != {'schema_version', 'known', 'registry', 'quarantined'} or type(custody['schema_version']) is not int or custody['schema_version'] != CUSTODY_VERSION:
            raise ValueError('Unsupported monitoring custody schema.')
        bridge = cls(validate_bindings(custody['known']))
        registry = custody['registry']
        if registry is not None:
            if not isinstance(registry, dict) or len(registry) > MAX_CUSTODY_ENTITIES:
                raise ValueError('Stored registry custody exceeds supported bounds.')
            for eid, fingerprint in registry.items():
                if not isinstance(eid, str) or not ENTITY.fullmatch(eid) or not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
                    raise ValueError('Invalid stored registry fingerprint.')
        pending = custody['quarantined']
        if not isinstance(pending, list) or len(pending) > MAX_CUSTODY_ENTITIES or any(not isinstance(eid, str) or not ENTITY.fullmatch(eid) for eid in pending) or len(set(pending)) != len(pending):
            raise ValueError('Invalid stored monitoring invalidations.')
        bridge.registry = deepcopy(registry)
        bridge.quarantined = set(pending)
        bridge.custody()  # Apply the serialized-size bound before acceptance.
        return bridge

    def reconcile_registry(self, registry, *, registry_event=False):
        """Commit invalidation metadata even if later presentation building fails.

        Compare on every snapshot, including startup, so changes while stopped
        cannot bypass a recorded baseline. A brand-new observer has no baseline.
        Fingerprints deliberately exclude names and all observed state values.
        """
        if not isinstance(registry, list) or len(registry) > MAX_CUSTODY_ENTITIES:
            raise ValueError('Registry custody exceeds supported bounds.')
        current = {}
        for row in registry:
            if not isinstance(row, dict) or not isinstance(row.get('entity_id'), str) or not ENTITY.fullmatch(row['entity_id']):
                raise ValueError('Invalid registry custody entity.')
            eid = row['entity_id']
            if eid in current:
                raise ValueError('Duplicate registry custody entity.')
            fields = [row.get(key) for key in REGISTRY_IDENTITY_FIELDS]
            if any(value is not None and (not isinstance(value, str) or not value or len(value) > 256) for value in fields):
                raise ValueError('Invalid registry custody metadata.')
            current[eid] = sha256(json.dumps(fields, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        quarantine = set(self.quarantined)
        if self.registry is not None:
            quarantine.update(eid for eid in set(self.registry) | set(current)
                              if self.registry.get(eid) != current.get(eid))
        elif registry_event or quarantine:
            quarantine.update(current)
        # Keep disappeared monitored sources, but do not accumulate unrelated
        # registry tombstones forever as configured inventory changes.
        relevant = set(current) | {binding[field] for binding in self.known.values()
                                  for field in ('output', 'source')}
        quarantine.intersection_update(relevant)
        if len(quarantine) > MAX_CUSTODY_ENTITIES:
            raise ValueError('Monitoring invalidations exceed supported bounds.')
        self.registry = current
        self.quarantined = quarantine

    def custody(self):
        result = {'schema_version': CUSTODY_VERSION, 'known': self.bindings(),
                  'registry': deepcopy(self.registry), 'quarantined': sorted(self.quarantined)}
        if len(json.dumps(result, allow_nan=False, separators=(',', ':')).encode()) > MAX_CUSTODY_BYTES:
            raise ValueError('Stored monitoring custody exceeds supported size.')
        return result

    def evaluate(self, data, options, registry, states, helper_ids, confirmations=None, registry_event=False, fresh_entity=None, retired=None, custom_meanings=None):
        self.reconcile_registry(registry, registry_event=registry_event)
        quarantine = set(self.quarantined)
        if fresh_entity:
            quarantine.discard(fresh_entity)
        # Quarantine means an existing HA state is not yet usable evidence. It
        # must not turn a present configured output into a fictitious missing one.
        clean_states = {eid: value if eid not in quarantine else {'state': 'unknown', 'attributes': {}}
                        for eid, value in states.items()}
        labels = {r['entity_id']: r.get('name') or r.get('original_name') or r['entity_id'] for r in registry}
        configured = extract_configured(data, options, labels=labels)
        runtime = []
        helper_states = {}
        for key, label in HELPERS.items():
            entity = helper_ids.get(key)
            raw = clean_states.get(entity, {})
            state = raw.get('state') if isinstance(raw, dict) else None
            state = state if state in ('on', 'off') else 'unknown'
            helper_states[key] = state
            runtime.append(dict(key=key, label=label, state=state, source=entity,
                detail='Reported by the bound HI helper.' if state != 'unknown' else 'HI helper is absent, unavailable or unknown; control eligibility is not inferred.'))
        roles = {}
        for row in configured:
            roles.setdefault(row['entity_id'], set()).add(row['role'])
        isolation = {}
        for entity, entity_roles in roles.items():
            keys = []
            if entity_roles & {'ventilation_zone_1', 'ventilation_zone_2', 'aq'}:
                keys.append('air_isolate_fan_outputs')
            if entity_roles & {'humidifier_zone_1', 'humidifier_zone_2'}:
                keys.append('air_isolate_humidifier_outputs')
            values = [helper_states[key] for key in keys]
            # Alert output roles do not share the fan/humidifier isolation gates.
            if entity_roles & {'alert_light', 'alert_power'}:
                values.append('not_applicable')
            state = 'unknown' if 'unknown' in values else 'isolated' if values and all(v == 'on' for v in values) else 'partial' if 'on' in values else 'not_isolated' if keys else 'not_applicable'
            isolation[entity] = dict(state=state, label={
                'unknown': 'Isolation unknown', 'isolated': 'Isolated', 'partial': 'Some roles isolated',
                'not_isolated': 'Not isolated', 'not_applicable': 'No applicable isolation gate',
            }[state], tone='warning' if state == 'unknown' else 'context', icon='lock')
        for row in configured:
            row['isolated'] = isolation[row['entity_id']]['state'] == 'isolated'
        confirmed_identities = {(m.get('output_identity'), m.get('source_identity')) for m in (confirmations or [])}
        known = {pair: deepcopy(m) for pair, m in self.known.items()
                         if m.get('origin') != 'confirmed' or (m.get('output_identity'), m.get('source_identity')) in confirmed_identities}
        session = DiscoverySession(configured, registry, clean_states, confirmations or [], known=known, retired=retired, custom_meanings=custom_meanings)
        payload = deepcopy(session.snapshot['payload'])
        payload['synthetic'] = False
        payload['experimental'] = False
        payload['provenance'] = 'home_assistant'
        payload['observation'] = {
            'basis': 'home_assistant_state', 'physical_freshness': 'not_established',
            'detail': 'Home Assistant state evidence. Physical device report freshness is not established.',
        }
        payload['disclaimer'] = 'Read-only Home Assistant observation. Device-level signals do not prove which output component is affected.'
        payload['runtime_context'] = runtime
        payload['runtime_context_complete'] = all(row['state'] != 'unknown' for row in runtime)
        for record in payload['records']:
            facet = isolation[record['entity_id']]
            record['isolation'] = facet
            if facet['state'] in ('unknown', 'partial'):
                record['context'] = ('Applicable isolation helper truth is incomplete. Observed output state remains separate.' if facet['state'] == 'unknown' else 'Only some configured roles are isolated. Other roles remain separate control paths owned by HI.')
            elif facet['state'] == 'not_applicable':
                record['context'] = 'This alert output is not covered by the fan or humidifier isolation helper. Observed state does not prove a command succeeded.'
            if not record['attention'] and facet['state'] in ('isolated', 'partial', 'unknown'):
                record['status'] = facet
            if record['entity_id'] in quarantine and record['entity_id'] in states:
                record['observation_pending'] = True
                record['availability']['label'] = 'Awaiting new report'
                record['observed_state'] = 'Not used as current evidence'
                record['context'] += ' Registry observation is pending a new Home Assistant report; the entity state exists.'
                for item in record['attention']:
                    if item['code'] == 'state_unknown':
                        item['evidence'] = 'The entity state exists, but registry observation is awaiting a new Home Assistant report.'
        if not payload['runtime_context_complete']:
            payload['context_notice'] = 'HI control or isolation context is incomplete; observed output state and device signals are still shown.'
        compact = build_compact(payload)
        if compact is not None:
            payload['compact'] = compact
        payload_size = len(json.dumps(payload, allow_nan=False, separators=(',', ':')).encode())
        if payload_size > MAX_PAYLOAD_BYTES and 'compact' in payload:
            # Optional convenience text must not make an otherwise valid full
            # observation unavailable at the existing payload boundary.
            payload.pop('compact')
            payload_size = len(json.dumps(payload, allow_nan=False, separators=(',', ':')).encode())
        if payload_size > MAX_PAYLOAD_BYTES:
            session.stop()
            raise ValueError('Output presentation exceeds the supported payload size.')
        if self.session:
            self.session.stop()
        self.session = session
        self.payload = payload
        self.quarantined = quarantine
        self.known = deepcopy(session.known)
        return payload

    def bindings(self):
        return [{k: deepcopy(v) for k, v in value.items() if k not in ('custom_label', 'custom_instructions', 'meaning_unresolved')}
                for _, value in sorted(self.known.items())]

    def stop(self):
        if self.session:
            self.session.stop()
        self.payload = None
