// The authenticated preference belongs to one user and one stamped HI entry.
function hiVocScope(stamp, diag) {
  const entry = stamp?.schema === 1 && stamp.generator === 1 &&
    ['v2_mobile', 'v2_tablet'].includes(stamp.layout) && /^[a-f0-9]{64}$/.test(stamp.entry || '') ? stamp.entry : null;
  const available = typeof diag?.state === 'string' && !!diag.state.trim() &&
    !['unknown', 'unavailable'].includes(diag.state.trim().toLowerCase());
  const metadata = diag?.attributes?.ui_revision;
  const foreign = !!metadata?.entry && metadata.entry !== entry && !!entry;
  const inventory = available && !foreign ? diag.attributes?.config?.telemetry : null;
  const owned = entry && available && metadata?.schema === 1 && metadata.entry === entry;
  const count = owned ? diag.attributes?.diagnostics_summary?.voc_index_sources?.configured : null;
  const indices = Number.isSafeInteger(count) && count >= 0 ? count : null;
  const inventoryKnown = Array.isArray(inventory) &&
    inventory.every(row => row && typeof row.sensor_type === 'string');
  return {entry, indices, inventory, inventoryKnown,
    mixed: inventoryKnown && indices > 0 && inventory.some(row => row.sensor_type === 'voc')};
}

function hiPrepareVoc(owner, hass, stamp, diagId) {
  if (!owner?.shadowRoot || !hass || !globalThis.customElements) return;
  const tag = 'hi-voc-presentation-v3';
  const contextKey = Symbol.for('humidity_intelligence.voc_chips.context.v1');
  const changed = 'hi-voc-presentation-context';
  const modes = ['all', 'indices', 'concentrations'];
  if (!customElements.get(tag)) {
    // Mounted rows and dialogs on the same connection share one HA subscription.
    const connections = new WeakMap();
    function subscribe(hass, entry, view) {
      const {connection} = hass;
      const identity = hass.user.id + ':' + entry;
      let entries = connections.get(connection);
      if (!entries) { entries = new Map(); connections.set(connection, entries); }
      let store = entries.get(identity);
      if (!store) {
        const key = 'humidity_intelligence.voc_chips.v1.' + entry;
        const views = new Set();
        let off, listening = false, subscribing = false, attempt = 0, sequence = 0, timer, writeTimer;
        const paint = () => { for (const node of views) node.paint(); };
        const fail = message => { store.value = null; store.status = message; paint(); };
        const waiting = () => {
          clearTimeout(timer);
          store.value = null; store.status = 'Loading display preference…'; paint();
          timer = setTimeout(() => fail('Display preference unavailable'), 10000);
        };
        const receive = data => {
          if (!listening || connection.connected !== true) return;
          clearTimeout(timer); sequence++;
          if (data?.value !== null && !modes.includes(data?.value)) {
            fail('Display preference unavailable'); return;
          }
          store.value = data.value ?? 'all'; store.status = ''; paint();
        };
        const stopRead = () => {
          attempt++; subscribing = false; clearTimeout(timer);
          off?.(); off = null;
        };
        const start = () => {
          stopRead();
          const token = attempt;
          subscribing = true;
          waiting();
          Promise.resolve().then(() => connection.subscribeMessage(data => {
            if (token === attempt) receive(data);
          }, {type:'frontend/subscribe_user_data', key})).then(unsub => {
            if (token !== attempt) unsub();
            else { subscribing = false; off = unsub; }
          }).catch(() => {
            if (token === attempt) {
              subscribing = false; clearTimeout(timer); fail('Display preference unavailable');
            }
          });
        };
        const disconnected = () => {
          clearTimeout(timer); clearTimeout(writeTimer);
          if (store.write) store.write.pending = false;
          fail('Display preference unavailable');
        };
        // HA automatically restores its subscriptions after reconnect.
        const ready = () => { if (off || subscribing) waiting(); else start(); };
        store = {value:null, status:'', write:null,
          get pending() { return this.write?.pending === true; },
          get retryValue() { return this.pending ? null : this.write?.value; },
          retry(node) {
            if (!listening || !connection.connected || store.pending) return;
            if (store.retryValue) return store.save(node, store.retryValue);
            start();
          },
          async save(node, next) {
            if (!listening || !node.eligible() || !modes.includes(next) || (!store.value && next !== store.retryValue) ||
                store.pending || connection.connected !== true) return;
            const recovering = !!store.write;
            const before = sequence;
            // Only a newer write supersedes this command's eventual acknowledgement.
            const write = {value:next, pending:true};
            store.write = write;
            const unconfirmed = () => {
              if (store.write !== write || !write.pending) return;
              clearTimeout(writeTimer);
              write.pending = false;
              if (before === sequence) store.value = null;
              paint();
            };
            paint();
            writeTimer = setTimeout(unconfirmed, 10000);
            try {
              await node.ha().callWS({type:'frontend/set_user_data', key, value:next});
            } catch {
              unconfirmed(); return;
            }
            if (store.write !== write) return;
            clearTimeout(writeTimer);
            store.write = null;
            if (!listening) { entries.delete(identity); return; }
            if (connection.connected && (recovering || store.status)) {
              start();
            } else {
              if (connection.connected && sequence === before) store.value = next;
              paint();
            }
          },
          attach(node) {
            views.add(node);
            if (listening) return;
            listening = true;
            connection.addEventListener?.('disconnected', disconnected);
            connection.addEventListener?.('ready', ready);
            if (connection.connected === true) start(); else disconnected();
          },
          release(node) {
            views.delete(node);
            // button-card may replace its HTML in the same render.
            queueMicrotask(() => {
              if (views.size || !listening) return;
              listening = false; stopRead();
              connection.removeEventListener?.('disconnected', disconnected);
              connection.removeEventListener?.('ready', ready);
              store.value = null; store.status = '';
              // Keep only outstanding write intent for this connection, user and entry.
              if (!store.write) entries.delete(identity);
            });
          }
        };
        entries.set(identity, store);
      }
      store.attach(view);
      return store;
    }
    customElements.define(tag, class extends HTMLElement {
      connectedCallback() {
        this.dialog = this.closest('dialog');
        this.owner = this.dialog?.hiVocOwner || this.getRootNode().host;
        this.owner?.addEventListener(changed, this);
        this.addEventListener('change', this); this.addEventListener('click', this);
        this.refresh();
      }
      disconnectedCallback() {
        this.owner?.removeEventListener(changed, this);
        this.removeEventListener('change', this); this.removeEventListener('click', this);
        this.store?.release(this); this.store = null; this.owner = null;
      }
      ha() { return this.owner?.hass || this.owner?._hass; }
      sameViewer(ha, entry) {
        const opening = this.dialog?.hiVocSession;
        return !this.dialog || !!(opening && ha && opening.user === ha.user?.id &&
          opening.connection === ha.connection && opening.entry === entry);
      }
      eligible() {
        const ctx = this.owner?.[contextKey], ha = this.ha();
        return !!(this.isConnected && this.owner?.isConnected && ctx && ha?.user?.id && this.sameViewer(ha, ctx.entry) &&
          ha.connection === this.connection && ha.user.id === this.user && ctx.stamp?.entry === this.entry &&
          hiVocScope(ctx.stamp, ha.states?.[ctx.diagId]).mixed);
      }
      refresh() {
        const ctx = this.owner?.[contextKey], ha = this.ha();
        const scope = hiVocScope(ctx?.stamp, ha?.states?.[ctx?.diagId]);
        const mixed = scope.mixed && this.sameViewer(ha, scope.entry);
        if (!mixed || this.connection !== ha?.connection || this.user !== ha?.user?.id || this.entry !== scope.entry) {
          this.store?.release(this); this.store = null;
        }
        this.connection = ha?.connection; this.user = ha?.user?.id; this.entry = scope.entry;
        this.mixed = mixed;
        if (mixed && !this.store && this.user && typeof ha.callWS === 'function' &&
            typeof this.connection?.subscribeMessage === 'function') this.store = subscribe(ha, this.entry, this);
        this.paint();
        if (this.dialog?.open && !this.sameViewer(ha, scope.entry)) this.dialog.close();
      }
      handleEvent(event) {
        if (event.type === changed) { this.refresh(); return; }
        if (!this.eligible() || !this.closest('dialog')?.open) return;
        if (event.type === 'change' && event.target.matches('input[name="hi-voc-choice"]')) {
          if (!this.store?.value || this.store.pending) this.paint();
          else this.store?.save(this, event.target.value);
        } else if (event.type === 'click' && event.target.matches('[data-voc-retry]')) {
          this.store?.retry(this);
        }
      }
      paint() {
        const mode = this.store?.value;
        this.setAttribute('data-show', mode || 'all');
        for (const chip of this.querySelectorAll('[data-voc]')) {
          chip.style.display = mode && mode !== 'all' && mode !== chip.dataset.voc ? 'none' : '';
        }
        const fields = this.querySelector('fieldset');
        if (!fields) return;
        fields.hidden = !this.mixed;
        fields.setAttribute('aria-busy', String(!!this.store?.pending));
        let retryLabel = 'Retry';
        for (const input of fields.querySelectorAll('input')) {
          if (input.value === this.store?.retryValue && input.labels?.length)
            retryLabel = 'Retry saving “' + input.labels[0].textContent.trim() + '”';
          input.checked = input.value === (this.store?.pending ? this.store.write.value : mode);
          input.tabIndex = input.checked || (!mode && input.value === 'all') ? 0 : -1;
          input.setAttribute('aria-disabled', String(!mode || !!this.store?.pending));
        }
        const message = this.store?.pending ? 'Saving…' : this.store?.retryValue ? 'Save unconfirmed'
          : this.store?.status ?? 'Display preference unavailable';
        fields.querySelector('[role="status"]').textContent = message;
        const retry = fields.querySelector('[data-voc-retry]');
        retry.textContent = retryLabel;
        retry.hidden = !this.store || !['Display preference unavailable', 'Save unconfirmed'].includes(message);
      }
    });
  }
  const {entry, mixed} = hiVocScope(stamp, hass.states?.[diagId]);
  const prior = owner[contextKey];
  owner[contextKey] = {stamp, diagId, entry, mixed, connection:hass.connection, user:hass.user?.id};
  if (!prior || prior.entry !== entry || prior.diagId !== diagId || prior.mixed !== mixed ||
      prior.connection !== hass.connection || prior.user !== hass.user?.id) owner.dispatchEvent(new Event(changed));
}
