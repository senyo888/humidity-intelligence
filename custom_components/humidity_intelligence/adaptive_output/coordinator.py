"""HA lifecycle adapter: bounded state reads, targeted listeners, own storage only."""
from copy import deepcopy
import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .bridge import ObservationBridge, validate_bindings
from .const import DOMAIN, HI_DOMAIN, CONF_CONFIRMATIONS, HELPERS, observation_settings
from .config_adapter import extract_configured
from .discovery import MAX_REGISTRY, identity, validate_retired

_LOGGER = logging.getLogger(__name__)
STATE_ATTRIBUTES = ('device_class', 'percentage', 'action', 'preset_mode')


def registry_row(entry):
    row = {'entity_id': entry.entity_id}
    for key in ('id', 'platform', 'unique_id', 'device_id', 'entity_category', 'device_class', 'original_device_class', 'disabled_by', 'hidden_by', 'name', 'original_name'):
        value = getattr(entry, key, None)
        row[key] = str(value) if value is not None else None
    return row


class OutputObserver:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.target_id = entry.entry_id
        self.bridge = ObservationBridge()
        self.store = Store(hass, 1, f'{DOMAIN}.{entry.entry_id}.adaptive_output_custody')
        self.payload = None
        self.failure = None
        self.active = True
        self._listeners = []
        self._unsub = []
        self._state_unsub = None
        self._watch = set()
        self._scheduled = None
        self._registry_event = False
        self._fresh_entities = {}
        self._event_sequence = 0
        self._registry_sequence = 0
        self._storage_valid = False
        self._snapshot_cache = None

    async def async_start(self):
        try:
            saved = await self.store.async_load()
            if saved is not None:
                if not isinstance(saved, dict) or saved.get('target_id') != self.target_id or not isinstance(saved.get('known'), list):
                    raise ValueError('Stored monitoring identity custody does not match the bound HI entry.')
                self.bridge = ObservationBridge.from_custody({key: value for key, value in saved.items() if key != 'target_id'})
            self._storage_valid = True
        except (ValueError, TypeError, OSError) as err:
            self._storage_valid = False
            self.failure = str(err)[:160]
        target = self.hass.config_entries.async_get_entry(self.target_id)
        if target:
            self._unsub.append(target.async_on_state_change(self._target_state_changed))
        self._unsub.append(self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._registry_changed))
        self._unsub.append(self.hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, self._registry_changed))
        self.refresh()

    @callback
    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    @callback
    def _notify(self):
        for listener in tuple(self._listeners):
            listener()

    @callback
    def _target_state_changed(self):
        # Do not keep a cached payload visible through HI unload/reload.
        self.refresh()

    @callback
    def _registry_changed(self, event):
        self._snapshot_cache = None
        self._event_sequence += 1
        self._registry_sequence = self._event_sequence
        self._registry_event = True
        self._schedule()

    @callback
    def _state_changed(self, event):
        self._event_sequence += 1
        self._fresh_entities[event.data['entity_id']] = self._event_sequence
        self._schedule()

    @callback
    def _schedule(self):
        if self.active and self._scheduled is None:
            self._scheduled = self.hass.loop.call_soon(self.refresh)

    def _snapshots(self, target):
        registry = er.async_get(self.hass)
        configured = extract_configured(dict(target.data), dict(target.options))
        output_ids = {row['entity_id'] for row in configured}
        settings = observation_settings(target.data, target.options)
        confirmations = validate_bindings(settings[CONF_CONFIRMATIONS])
        retired = validate_retired(settings['retired'])
        bindings = confirmations + retired
        cache_key = (tuple(sorted(output_ids)), tuple(sorted(
            (row['output'], row['source'], row['output_identity'], row['source_identity']) for row in bindings)))
        if self._snapshot_cache is None or self._snapshot_cache[0] != cache_key:
            rows = {}

            def add(entry):
                if entry.entity_id not in rows and len(rows) >= min(MAX_REGISTRY, 1024):
                    raise ValueError('Relevant registry exceeds the observation limit.')
                rows[entry.entity_id] = registry_row(entry)

            devices = set()
            for output in sorted(output_ids):
                entry = registry.async_get(output)
                if entry is None:
                    continue
                add(entry)
                if entry.device_id:
                    devices.add(entry.device_id)
            for device in sorted(devices):
                for source in er.async_entries_for_device(registry, device, include_disabled_entities=True):
                    if source.entity_id.split('.')[0] in ('sensor', 'binary_sensor'):
                        add(source)
            identities = {binding[field + '_identity'] for binding in bindings for field in ('output', 'source')}
            # Only metadata is scanned, once per registry/config change. State
            # events reuse this bounded relevant index, never a global state scan.
            if identities:
                for candidate in registry.entities.values():
                    if identity(registry_row(candidate)) in identities:
                        add(candidate)
            for binding in bindings:
                for field in ('output', 'source'):
                    entry = registry.async_get(binding[field])
                    if entry:
                        add(entry)
            helpers = {}
            for key in HELPERS:
                entity = registry.async_get_entity_id('switch', HI_DOMAIN, f'hi_{self.target_id}_input_{key}')
                if entity:
                    entry = registry.async_get(entity)
                    if entry and entry.config_entry_id == self.target_id and entry.disabled_by is None:
                        helpers[key] = entity
            self._snapshot_cache = (cache_key, rows, helpers)
        _, cached_rows, helpers = self._snapshot_cache
        rows = deepcopy(cached_rows)
        ids = output_ids | set(rows) | set(helpers.values()) | {key[1] for key in self.bridge.known}
        if len(ids) > 1024:
            raise ValueError('Relevant states exceed the observation limit.')
        states = {}
        for entity in ids:
            state = self.hass.states.get(entity)
            if state:
                metadata = {}
                for key in ('last_reported', 'last_updated', 'last_changed'):
                    stamp = getattr(state, key, None)
                    if isinstance(stamp, datetime):
                        metadata[key] = stamp.isoformat()
                restored = state.attributes.get('restored')
                if type(restored) is bool:
                    metadata['restored'] = restored
                states[entity] = {'state': state.state, 'attributes': {key: state.attributes[key] for key in STATE_ATTRIBUTES if key in state.attributes},
                                  'observation': metadata}
                if entity in rows:
                    rows[entity]['name'] = rows[entity]['name'] or str(state.attributes.get('friendly_name') or '') or None
        return sorted(rows.values(), key=lambda row: row['entity_id']), states, helpers, confirmations, retired

    @callback
    def refresh(self):
        if not self.active:
            return
        if self._scheduled:
            self._scheduled.cancel()
            self._scheduled = None
        succeeded = False
        try:
            if not self._storage_valid:
                raise ValueError(self.failure or 'Stored monitoring identity custody is invalid.')
            target = self.hass.config_entries.async_get_entry(self.target_id)
            if target is None or target.domain != HI_DOMAIN:
                raise ValueError('The explicitly bound HI config entry is missing.')
            if not observation_settings(target.data, target.options)['enabled']:
                raise ValueError('Output observation is disabled.')
            if target.state != ConfigEntryState.LOADED:
                raise ValueError('The bound HI config entry is not loaded; output observation is paused.')
            registry, states, helpers, confirmations, retired = self._snapshots(target)
            # Registry changes invalidate pre-change cached states. Only actual
            # new targeted events may release those quarantine entries.
            self.bridge.reconcile_registry(registry, registry_event=self._registry_event)
            for entity, sequence in self._fresh_entities.items():
                if not self._registry_event or sequence > self._registry_sequence:
                    self.bridge.quarantined.discard(entity)
            payload = self.bridge.evaluate(dict(target.data), dict(target.options), registry, states, helpers, confirmations, retired=retired)
            watch = set(self.bridge.session.snapshot['watch_entities']) | set(helpers.values())
            if watch != self._watch:
                if self._state_unsub:
                    self._state_unsub()
                self._state_unsub = async_track_state_change_event(self.hass, sorted(watch), self._state_changed) if watch else None
                self._watch = watch
            self.payload = payload
            self.failure = None
            self.store.async_delay_save(self._stored_data, 1)
            succeeded = True
        except (ValueError, TypeError, KeyError) as err:
            self.payload = None
            self.failure = str(err)[:160]
        except Exception:
            self.payload = None
            self.failure = 'Output observation failed; inspect the local integration log.'
            _LOGGER.exception('Optional output observation failed')
        finally:
            if succeeded:
                self._registry_event = False
                self._fresh_entities.clear()
        self._notify()

    @callback
    def _stored_data(self):
        return {'target_id': self.target_id, **self.bridge.custody()}

    async def async_stop(self):
        # A queued registry/state batch must be reconciled before its callback is
        # cancelled. On failure the old fingerprints remain, so startup compares
        # again; a failed refresh must never bless a new cached source value.
        if self.active and self._storage_valid and (self._registry_event or self._fresh_entities):
            self.refresh()
        self.active = False
        if self._scheduled:
            self._scheduled.cancel()
            self._scheduled = None
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        self._listeners.clear()
        try:
            if self._storage_valid:
                await self.store.async_save(self._stored_data())
        except Exception:
            _LOGGER.exception('Could not flush output monitoring identity custody during unload')
        finally:
            self.bridge.stop()
            self.payload = None
