import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// A dependency-free DOM lifecycle harness. Native EventTarget handles listeners and
// cancellation; the tree only models the APIs this action uses. This does not prove
// browser touch synthesis, native dialog focus trapping, or physical-device support.
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SURFACES = [
  'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
  'ui-gallery/default-v2-mobile-aq/card.yaml',
  'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
];
function actionBody(relativePath) {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const card = source.indexOf('          entity: sensor.hi_diagnostics\n');
  const tap = source.indexOf('          tap_action:\n', card);
  const hold = source.indexOf('          hold_action:\n', tap);
  const block = source.slice(tap, hold);
  assert.match(block, /action: javascript/);
  return block.slice(block.indexOf('[[[') + 3, block.lastIndexOf(']]]'));
}
class DetailEvent extends Event {
  constructor(type, options = {}) { super(type, options); this.detail = options.detail; }
}
function harness({ supported = true, deferredClose = false, showThrows = false } = {}) {
  const observers = new Set();
  const queuedCloseEvents = [];
  const window = new EventTarget();
  class Node extends EventTarget {
    constructor(tagName = 'div') {
      super(); this.tagName = tagName.toUpperCase(); this.children = [];
      this.parentNode = null; this.attributes = {}; this.dataset = {}; this.style = {};
      this.className = ''; this.textContent = ''; this.open = false;
    }
    get innerHTML() { return this._html || ''; }
    set innerHTML(html) {
      this._html = html; this.replaceChildren();
      if (html.includes('hi-stability-close')) { const button = new Node('button'); button.className = 'hi-stability-close'; this.appendChild(button); }
    }
    get isConnected() { return this === document.body || Boolean(this.parentNode?.isConnected); }
    getRootNode() { return this.parentNode ? this.parentNode.getRootNode() : this; }
    get firstElementChild() { return this.children[0] || null; }
    get childNodes() { return this.children; }
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this.append(...children); }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; }
    setAttribute(key, value) { this.attributes[key] = String(value); if (key === 'class') this.className = String(value); }
    getAttribute(key) { return this.attributes[key] ?? null; }
    hasAttribute(key) { return key in this.attributes; }
    matches(selector) {
      if (selector.includes('hi-stability-close')) return this.className.includes('hi-stability-close');
      if (selector.includes('hi-stability-details-template')) return this.tagName === 'TEMPLATE';
      if (selector.includes('hi-stability-dialog')) return this.tagName === 'DIALOG' && (this.hasAttribute('data-hi-stability-dialog') || 'hiStabilityDialog' in this.dataset);
      if (selector.includes('hi-stability-details')) return this.className.includes('hi-stability-details');
      if (selector === '#card') return this.getAttribute('id') === 'card';
      return this.tagName.toLowerCase() === selector;
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
    cloneNode(deep) { const copy = new Node(this.tagName); copy.className = this.className; copy.textContent = this.textContent; copy.attributes = {...this.attributes}; if (deep) this.children.forEach(child => copy.appendChild(child.cloneNode(true))); return copy; }
    focus() { document.activeElement = this; this.focused = true; }
    getBoundingClientRect() { return { left: 10, top: 10, right: 300, bottom: 300 }; }
    showModal() { if (showThrows) throw new Error('Native dialog rejected'); this.open = true; this.querySelector('.hi-stability-close')?.focus(); }
    close() { this.open = false; const fire = () => this.dispatchEvent(new Event('close')); if (deferredClose) queuedCloseEvents.push(fire); else fire(); }
  }
  const document = new EventTarget();
  document.body = new Node('body'); document.documentElement = document.body;
  document.activeElement = document.body;
  document.createElement = tag => { const node = new Node(tag); if (tag === 'dialog' && !supported) node.showModal = undefined; return node; };
  document.querySelectorAll = selector => document.body.querySelectorAll(selector);
  document.querySelector = selector => document.body.querySelector(selector);
  class Observer {
    constructor(callback) { this.callback = callback; }
    observe(target) { this.targets ||= new Set(); this.targets.add(target); observers.add(this); }
    disconnect() { observers.delete(this); }
  }
  function owner() {
    const card = new Node('button-card'); card.shadowRoot = new Node('shadow-root');
    const button = new Node('ha-card'); button.setAttribute('id', 'card'); card.shadowRoot.appendChild(button);
    const template = new Node('template'); template.className = 'hi-stability-details-template';
    template.innerHTML = '<button class="hi-stability-close">Close</button>';
    template.content = new Node('fragment');
    const close = new Node('button'); close.className = 'hi-stability-close';
    template.content.appendChild(close); card.shadowRoot.appendChild(template);
    document.body.appendChild(card); card.focus();
    return card;
  }
  function invoke(card, source = SURFACES[0]) {
    const body = actionBody(source);
    new Function('document', 'window', 'MutationObserver', 'CustomEvent', 'entity', 'requestAnimationFrame', body)
      .call(card, document, window, Observer, DetailEvent, { entity_id: 'sensor.hi_diagnostics' }, callback => callback());
  }
  return { document, window, owner, invoke, observers,
    dialogs: () => document.querySelectorAll('[data-hi-stability-dialog]'),
    flushClose: () => queuedCloseEvents.splice(0).forEach(fire => fire()),
    flushObservers: () => [...observers].forEach(observer => observer.callback()),
  };
}

test('four surfaces share the same supported card action', () => {
  assert.equal(new Set(SURFACES.map(actionBody)).size, 1);
});

test('dialog is detached from gesture parent and Close cleans up and restores focus', () => {
  const h = harness(); const card = h.owner(); let parentTouches = 0;
  card.addEventListener('touchend', event => { parentTouches++; event.preventDefault(); });
  h.invoke(card); const [dialog] = h.dialogs();
  assert.ok(dialog.open); assert.equal(dialog.parentNode, h.document.body); assert.equal(card.contains(dialog), false);
  const close = dialog.querySelector('.hi-stability-close');
  close.dispatchEvent(new Event('touchend', { cancelable: true, bubbles: true }));
  assert.equal(parentTouches, 0);
  close.dispatchEvent(new Event('click', { bubbles: true }));
  assert.equal(h.dialogs().length, 0); assert.equal(h.observers.size, 0);
  assert.ok(card.focused || card.shadowRoot.querySelector('#card').focused);
});

test('two badges replace the active snapshot and do not leak observers', () => {
  const h = harness(); const one = h.owner(); const two = h.owner();
  h.invoke(one); const first = h.dialogs()[0]; h.invoke(two);
  assert.equal(h.dialogs().length, 1); assert.notEqual(h.dialogs()[0], first);
  assert.equal(first.isConnected, false); assert.equal(h.observers.size, 1);
  h.dialogs()[0].close(); assert.equal(h.observers.size, 0);
});

test('telemetry rerender leaves detached snapshot open while owner removal closes it', () => {
  const h = harness(); const card = h.owner(); h.invoke(card); const dialog = h.dialogs()[0];
  card.shadowRoot.replaceChildren(); h.flushObservers(); assert.equal(h.dialogs()[0], dialog);
  assert.ok(dialog.open); card.remove(); h.flushObservers();
  assert.equal(h.dialogs().length, 0); assert.equal(h.observers.size, 0);
});

test('navigation lifecycle closes dialogs and releases active observers', () => {
  for (const type of ['pagehide', 'popstate', 'location-changed']) {
    const h = harness(); const card = h.owner(); h.invoke(card);
    h.window.dispatchEvent(new Event(type));
    assert.equal(h.dialogs().length, 0, type); assert.equal(h.observers.size, 0, type);
  }
});

test('unsupported native dialog falls back to Diagnostics without retaining nodes', () => {
  const h = harness({ supported: false }); const card = h.owner(); let fallback;
  card.addEventListener('hass-more-info', event => { fallback = event.detail; });
  h.invoke(card);
  assert.equal(fallback?.entityId, 'sensor.hi_diagnostics');
  assert.equal(h.dialogs().length, 0); assert.equal(h.observers.size, 0);
});

test('backdrop click closes but dialog content-area click does not', () => {
  const h = harness(); const card = h.owner(); h.invoke(card); const dialog = h.dialogs()[0];
  const click = (x,y) => { const event = new Event('click'); Object.assign(event, {clientX:x,clientY:y}); dialog.dispatchEvent(event); };
  click(20,20); assert.equal(h.dialogs().length, 1);
  click(0,0); assert.equal(h.dialogs().length, 0); assert.equal(h.observers.size, 0);
});

test('native show failure falls back after disposing all dialog resources', () => {
  const h = harness({ showThrows: true }); const card = h.owner(); let fallback;
  card.addEventListener('hass-more-info', event => { fallback = event.detail; });
  h.invoke(card); assert.equal(fallback?.entityId, 'sensor.hi_diagnostics');
  assert.equal(h.dialogs().length, 0); assert.equal(h.observers.size, 0);
});

test('asynchronous replaced-dialog close cannot steal focus from its successor', () => {
  const h = harness({ deferredClose: true }); const one = h.owner(); const two = h.owner();
  h.invoke(one); h.invoke(two); const active = h.dialogs()[0];
  assert.equal(h.dialogs().length, 1); assert.equal(h.observers.size, 1);
  assert.equal(h.document.activeElement, active.querySelector('.hi-stability-close'));
  h.flushClose();
  assert.equal(h.document.activeElement, active.querySelector('.hi-stability-close'));
  assert.equal(h.dialogs().length, 1); assert.equal(h.observers.size, 1);
});

test('owner removal observation includes enclosing shadow roots and outer document', () => {
  const h = harness(); const card = h.owner(); const outer = h.document.body;
  const root = {host: {getRootNode: () => outer}};
  card.getRootNode = () => root;
  h.invoke(card); const [observer] = h.observers;
  assert.ok(observer.targets.has(root)); assert.ok(observer.targets.has(outer));
  card.remove(); h.flushObservers(); assert.equal(h.dialogs().length, 0);
});
