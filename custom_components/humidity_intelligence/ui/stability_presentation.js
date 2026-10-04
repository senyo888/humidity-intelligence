/* Persistent badge presentation only. No scoring, history or control writes.
 * Uses HA's authenticated frontend user-data API, scoped to an opaque entry.
 * Paint owned DOM: button-card does not rerender for a bare requestUpdate().
 */
const hiStabilityPresentation = (() => {
  const REGISTRY = Symbol.for('humidity_intelligence.stability_presentation.registry.v1');
  const OWNER = Symbol.for('humidity_intelligence.stability_presentation.owner.v1');
  const validEntry = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const validValue = value => value === null || typeof value === 'boolean';
  const attr = (node, key, value) => {
    if (node.getAttribute(key) !== value) node.setAttribute(key, value);
  };
  function bind(owner, hass, stamp, metadata) {
    // Pure/offline renderer calls have no preference transport or DOM custody.
    if (!owner?.isConnected || !owner.shadowRoot || !hass) return null;
    const connection = hass.connection;
    const user = hass.user?.id;
    const stamped = stamp?.schema === 1 && stamp.generator === 1
      && ['v2_mobile', 'v2_tablet'].includes(stamp.layout) && validEntry(stamp.entry);
    const advertised = metadata?.schema === 1 && validEntry(metadata.entry);
    const entry = stamped ? (!metadata?.entry || (advertised && metadata.entry === stamp.entry) ? stamp.entry : null)
      : advertised ? metadata.entry : null;
    let binding = owner[OWNER];
    if (binding && (binding.connection !== connection || binding.entry !== entry || binding.user !== user)) {
      binding.dispose(); binding = null;
    }
    if (binding) { binding.record.hass = hass; binding.paint(); return binding; }
    const supported = entry && typeof user === 'string' && user
      && typeof connection?.subscribeMessage === 'function' && typeof hass.callWS === 'function';
    const registry = window[REGISTRY] ||= new WeakMap();
    let entries = supported ? registry.get(connection) : null;
    if (supported && !entries) { entries = new Map(); registry.set(connection, entries); }
    const identity = `${user}:${entry}`;
    let record = entries?.get(identity);
    if (!record) {
      record = {hass, connection, entry, user, owners:new Set(), known:false,
        disabled:false, pending:false, error:'', status:supported ? 'loading' : 'unavailable',
        disposed:false, sequence:0, unsubscribe:null};
      record.key = `humidity_intelligence.stability_badge.disabled.v1.${entry}`;
      record.paint = () => { for (const item of record.owners) item.paint(); };
      record.receive = data => {
        if (record.disposed) return;
        clearTimeout(record.readTimer);
        record.sequence++;
        if (!data || !Object.hasOwn(data, 'value') || !validValue(data.value)) {
          record.known = false; record.status = 'unavailable';
          record.error = 'Display preference unavailable';
        } else {
          record.known = true; record.disabled = data.value === true;
          record.status = 'ready'; record.error = '';
        }
        record.paint();
      };
      record.toggle = async initiator => {
        const active = () => !record.disposed && !initiator.disposed && initiator.owner.isConnected;
        if (!active() || record.pending) return;
        if (!supported || connection.connected !== true) {
          record.error = 'Display preference unavailable'; record.paint(); return;
        }
        record.pending = true; record.error = ''; record.paint();
        try {
          await record.subscribe?.();
          if (!active()) return;
          if (!record.known || record.status !== 'ready') {
            const sequence = record.sequence;
            const result = await record.hass.callWS({type:'frontend/get_user_data', key:record.key});
            if (!active()) return;
            if (record.sequence === sequence) record.receive(result);
            if (!record.known) throw new Error('Unsupported preference value');
            await record.subscribe?.();
          }
          if (!active()) return;
          if (connection.connected !== true) throw new Error('Disconnected');
          const next = !record.disabled, sequence = record.sequence;
          await record.hass.callWS({type:'frontend/set_user_data', key:record.key, value:next});
          if (record.disposed) return;
          // A subscription update may already include a newer other-client write.
          if (record.sequence === sequence) record.receive({value:next});
        } catch (_) {
          if (!record.disposed) {
            // HA mutates its in-memory dictionary before disk persistence. Failure
            // cannot establish that the previous value remains durably stored.
            record.error = 'Save unconfirmed';
          }
        } finally {
          record.pending = false;
          if (!record.disposed) record.paint();
        }
      };
      record.disconnected = () => { record.status = 'unavailable'; record.paint(); };
      record.ready = () => {
        record.status = 'loading'; record.error = ''; record.armRead?.();
        record.subscribe?.(); record.paint();
      };
      record.dispose = () => {
        if (record.disposed) return;
        record.disposed = true; clearTimeout(record.readTimer);
        record.unsubscribe?.();
        connection?.removeEventListener?.('disconnected', record.disconnected);
        connection?.removeEventListener?.('ready', record.ready);
        entries?.delete(identity);
      };
      if (supported) {
        entries.set(identity, record);
        connection.addEventListener?.('disconnected', record.disconnected);
        connection.addEventListener?.('ready', record.ready);
        record.armRead = () => {
          clearTimeout(record.readTimer);
          record.readTimer = setTimeout(() => {
            if (!record.disposed && record.status !== 'ready') {
              record.status = 'unavailable'; record.error = 'Display preference unavailable'; record.paint();
            }
          }, 12000);
        };
        record.armRead();
        // One subscription per mounted account/entry, including both layouts.
        // The websocket client owns reconnect/resubscription; ready never doubles it.
        record.subscribe = () => {
          if (record.disposed || record.unsubscribe) return;
          if (record.subscribing) return record.subscriptionPromise;
          record.subscribing = true;
          record.subscriptionPromise = Promise.resolve().then(() => connection.subscribeMessage(record.receive,
            {type:'frontend/subscribe_user_data', key:record.key})).then(unsubscribe => {
            record.subscribing = false;
            if (record.disposed) unsubscribe(); else record.unsubscribe = unsubscribe;
          }).catch(() => {
            record.subscribing = false;
            if (record.disposed) return;
            clearTimeout(record.readTimer); record.status = 'unavailable';
            record.error = 'Display preference unavailable'; record.paint();
          });
          return record.subscriptionPromise;
        };
        record.subscribe();
      }
    }
    binding = {owner, connection, entry, user, record, disposed:false};
    binding.cancelKey = () => {
      clearTimeout(binding.keyTimer); binding.keyTimer = null;
      binding.spaceDown = false; binding.spaceHeld = false;
    };
    binding.tap = () => binding.card.dispatchEvent(new CustomEvent('action', {
      detail:{action:'tap'}, bubbles:true, composed:true,
    }));
    binding.keydown = event => {
      if (!['Enter', ' '].includes(event.key)) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.repeat) return;
      // Keep keys independent of the dependency's retained touch-hold state.
      if (event.key === 'Enter') { binding.cancelKey(); binding.tap(); return; }
      if (binding.spaceDown) return;
      binding.spaceDown = true;
      binding.keyTimer = setTimeout(() => {
        binding.keyTimer = null;
        if (binding.disposed || !binding.spaceDown || !owner.isConnected) return;
        binding.spaceHeld = true; binding.toggle();
      }, 650);
    };
    binding.keyup = event => {
      if (event.key !== ' ') return;
      event.preventDefault(); event.stopImmediatePropagation();
      const tapped = binding.spaceDown && !binding.spaceHeld;
      binding.cancelKey(); if (tapped) binding.tap();
    };
    binding.releaseCard = () => {
      binding.cancelKey();
      binding.card?.removeEventListener('keydown', binding.keydown, true);
      binding.card?.removeEventListener('keyup', binding.keyup, true);
      binding.card?.removeEventListener('blur', binding.cancelKey);
    };
    binding.paint = () => {
      if (binding.disposed) return;
      if (!owner.isConnected) { binding.dispose(); return; }
      const mode = record.known ? (record.disabled ? 'disabled' : 'enabled')
        : record.status === 'loading' ? 'loading' : 'unavailable';
      const feedback = record.error || (record.pending ? 'Saving display…'
        : !record.known ? (mode === 'loading' ? 'Loading display preference' : 'Display preference unavailable')
        : record.disabled ? 'Display off' : '');
      attr(owner, 'data-hi-stability-presentation', mode);
      attr(owner, 'data-hi-stability-feedback', feedback ? 'yes' : 'no');
      const label = owner.shadowRoot.querySelector('.hi-stability-display-label');
      if (label && label.textContent !== feedback) label.textContent = feedback;
      const center = owner.shadowRoot.querySelector('.hi-stability-presentation-center');
      const text = mode === 'disabled' ? 'Disabled' : mode === 'loading' ? '…' : '—';
      if (center && center.textContent !== text) center.textContent = text;
      const overlay = owner.shadowRoot.querySelector('.hi-stability-presentation-overlay');
      if (overlay) attr(overlay, 'aria-label', mode === 'disabled'
        ? 'Stability badge display disabled. Hold this badge to restore it. Calculation and history continue; tap for details.'
        : 'Stability display preference unavailable. Calculation and history continue; tap for details.');
      const card = owner.shadowRoot.querySelector('#card');
      if (card !== binding.card) {
        binding.releaseCard();
        binding.card = card;
        card?.addEventListener('keydown', binding.keydown, true);
        card?.addEventListener('keyup', binding.keyup, true);
        card?.addEventListener('blur', binding.cancelKey);
      }
      if (card) { attr(card, 'tabindex', '0'); attr(card, 'role', 'button'); }
      if (card) attr(card, 'title', record.error === 'Save unconfirmed'
        ? 'Could not confirm the display preference was saved. Hold again to retry. Calculation and history continue.'
        : mode === 'disabled' ? 'Hold this badge or Space to restore the score display. Tap or press Enter for details.'
        : 'Tap or press Enter for Stability details. Hold this badge or Space to disable only the badge display.');
    };
    binding.toggle = () => record.toggle(binding);
    binding.dispose = () => {
      if (binding.disposed) return;
      binding.disposed = true; binding.observer.disconnect(); record.owners.delete(binding);
      binding.releaseCard();
      for (const name of ['location-changed', 'popstate']) window.removeEventListener(name, binding.navigation);
      window.removeEventListener('pagehide', binding.pagehide);
      window.removeEventListener('blur', binding.cancelKey);
      binding.document?.removeEventListener('visibilitychange', binding.visibility);
      if (owner[OWNER] === binding) delete owner[OWNER];
      if (!record.owners.size) record.dispose();
    };
    binding.observer = new MutationObserver(() => binding.paint());
    let root = owner.shadowRoot;
    while (root) { binding.observer.observe(root, {childList:true, subtree:true}); root = root.host ? root.host.getRootNode() : null; }
    owner[OWNER] = binding; record.owners.add(binding);
    binding.navigation = () => { binding.cancelKey(); if (owner.isConnected) binding.paint(); else binding.dispose(); };
    binding.pagehide = event => { binding.cancelKey(); if (!event.persisted) binding.dispose(); };
    for (const name of ['location-changed', 'popstate']) window.addEventListener(name, binding.navigation);
    window.addEventListener('pagehide', binding.pagehide);
    window.addEventListener('blur', binding.cancelKey);
    binding.document = owner.ownerDocument;
    binding.visibility = () => { if (binding.document?.visibilityState === 'hidden') binding.cancelKey(); };
    binding.document?.addEventListener('visibilitychange', binding.visibility);
    binding.paint();
    queueMicrotask(() => binding.paint());
    return binding;
  }
  return {bind};
})();
