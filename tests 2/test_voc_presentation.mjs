import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {setImmediate as settle} from 'node:timers/promises';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../custom_components/humidity_intelligence/ui/voc_presentation.js', import.meta.url), 'utf8');
const entry = 'a'.repeat(64);
const secondEntry = 'b'.repeat(64);

class Element extends EventTarget {
  isConnected = true;
  attributes = {};
  chips = [];
  setAttribute(name, value) { this.attributes[name] = value; }
  closest() { return this.dialog ?? null; }
  getRootNode() { return {host: this.host}; }
  querySelector() { return this.fields ?? null; }
  querySelectorAll() { return this.chips.filter(chip => chip.dataset.voc); }
}

class Connection extends EventTarget {
  connected = true;
  subscriptions = [];
  writes = [];
  async subscribeMessage(receive, request) {
    assert.equal(request.type, 'frontend/subscribe_user_data');
    const subscription = {key: request.key, receive, active: true};
    this.subscriptions.push(subscription);
    return () => { subscription.active = false; };
  }
  write(request) {
    assert.equal(request.type, 'frontend/set_user_data');
    return new Promise((resolve, reject) => this.writes.push({request, resolve, reject}));
  }
}

function fixture() {
  const elements = new Map();
  const timers = new Map();
  let now = 0;
  let id = 0;
  const prepare = runInNewContext(source + '\nhiPrepareVoc', {
    Event, HTMLElement: Element, queueMicrotask,
    customElements: {get: name => elements.get(name), define: (name, type) => elements.set(name, type)},
    setTimeout(callback, delay) { timers.set(++id, {callback, at: now + delay}); return id; },
    clearTimeout(key) { timers.delete(key); },
  });

  function mount(connection, layout, entryId = entry, user = 'current') {
    const owner = new Element();
    const stamp = {schema: 1, generator: 1, layout, entry: entryId};
    owner.shadowRoot = {};
    owner.hass = {
      connection, user: {id: user}, callWS: request => owner.hass.connection.write(request),
      states: {diagnostics: {state: 'ok', attributes: {
        ui_revision: {schema: 1, entry: entryId},
        config: {telemetry: [{sensor_type: 'voc', level: 'level1'}]},
        diagnostics_summary: {voc_index_sources: {configured: 1}},
      }}},
    };
    const render = () => prepare(owner, owner.hass, stamp, 'diagnostics');
    render();
    const Presentation = elements.get('hi-voc-presentation-v1');
    const row = new Presentation();
    row.host = owner;
    const chip = family => ({dataset: {voc: family}, style: {display: ''}});
    row.chips = [chip('indices'), chip('concentrations'), chip(null)];
    row.connectedCallback();

    const details = new Presentation();
    const dialog = {hiVocOwner: owner, open: true, close() { this.open = false; },
      hiVocSession: {entry: entryId, user, connection}};
    details.dialog = dialog;
    const fields = new Element();
    const status = {};
    const retry = {matches: selector => selector === '[data-voc-retry]'};
    const radios = ['all', 'indices', 'concentrations'].map(value => Object.assign(new Element(), {
      value, matches: selector => selector === 'input[name="hi-voc-choice"]',
    }));
    fields.querySelector = selector => selector === '[role="status"]' ? status : retry;
    fields.querySelectorAll = () => radios;
    details.fields = fields;
    details.connectedCallback();
    return {
      owner, render, dialog, fields, status, retry,
      choose: mode => details.handleEvent({type: 'change', target: radios.find(radio => radio.value === mode)}),
      retryRead: () => details.handleEvent({type: 'click', target: retry}),
      visible: () => row.chips.map(item => item.style.display !== 'none'),
      remove() {
        owner.isConnected = row.isConnected = details.isConnected = false;
        row.disconnectedCallback();
        details.disconnectedCallback();
      },
    };
  }

  function advance(milliseconds) {
    now += milliseconds;
    for (const [key, timer] of timers) {
      if (timer.at <= now) {
        timers.delete(key);
        timer.callback();
      }
    }
  }
  return {mount, advance};
}

test('chip visibility follows one account and entry across both layouts', async () => {
  const {mount} = fixture();
  const connection = new Connection();
  const mobile = mount(connection, 'v2_mobile');
  const tablet = mount(connection, 'v2_tablet');
  const other = mount(connection, 'v2_mobile', secondEntry);
  await settle();
  assert.equal(connection.subscriptions.length, 2);
  const [shared, separate] = connection.subscriptions;
  assert.notEqual(shared.key, separate.key);
  shared.receive({value: 'indices'});
  separate.receive({value: 'concentrations'});
  assert.deepEqual(mobile.visible(), [true, false, true]);
  assert.deepEqual(tablet.visible(), mobile.visible());
  assert.deepEqual(other.visible(), [false, true, true]);

  const replacement = new Connection();
  mobile.owner.hass = {...mobile.owner.hass, connection: replacement, user: {id: 'different'}};
  mobile.choose('all');
  assert.equal(connection.writes.length, 0);
  assert.equal(replacement.writes.length, 0);
  mobile.render();
  await settle();
  assert.equal(mobile.dialog.open, false);
  assert.equal(replacement.subscriptions.length, 1);
  replacement.subscriptions[0].receive({value: null});
  shared.receive({value: 'indices'});
  assert.deepEqual(mobile.visible(), [true, true, true]);
  assert.deepEqual(tablet.visible(), [true, false, true]);
  tablet.remove();
  mobile.remove();
  other.remove();
  await settle();
  assert.ok([...connection.subscriptions, ...replacement.subscriptions].every(sub => !sub.active));
});

test('reconnect restores the subscription and an account change invalidates an open selector', async () => {
  const {mount} = fixture();
  const connection = new Connection();
  const card = mount(connection, 'v2_tablet');
  await settle();
  const original = connection.subscriptions[0];
  original.receive({value: 'concentrations'});
  connection.connected = false;
  connection.dispatchEvent(new Event('disconnected'));
  assert.deepEqual(card.visible(), [true, true, true]);
  connection.connected = true;
  connection.dispatchEvent(new Event('ready'));
  original.receive({value: 'indices'});
  assert.equal(connection.subscriptions.length, 1);
  assert.deepEqual(card.visible(), [true, false, true]);

  card.owner.hass = {...card.owner.hass, user: {id: 'another'}};
  card.choose('all');
  assert.equal(connection.writes.length, 0);
  card.render();
  await settle();
  assert.equal(card.dialog.open, false);
  assert.equal(original.active, false);
  connection.subscriptions.at(-1).receive({value: null});
  original.receive({value: 'indices'});
  assert.deepEqual(card.visible(), [true, true, true]);
  card.remove();
  await settle();
});

for (const lateOutcome of ['resolve', 'reject']) {
  test('timed-out write releases controls and ignores late ' + lateOutcome + ' after retry', async () => {
    const {mount, advance} = fixture();
    const connection = new Connection();
    const mobile = mount(connection, 'v2_mobile');
    const tablet = mount(connection, 'v2_tablet');
    await settle();
    const original = connection.subscriptions[0];
    original.receive({value: null});
    mobile.choose('indices');
    const first = connection.writes[0];
    assert.equal(first.request.key, original.key);
    assert.equal(first.request.value, 'indices');
    assert.equal(tablet.fields.attributes['aria-busy'], 'true');
    if (lateOutcome === 'resolve') original.receive({value: 'concentrations'});
    advance(10000);
    assert.equal(mobile.status.textContent, 'Save unconfirmed');
    assert.equal(tablet.fields.attributes['aria-busy'], 'false');
    assert.equal(mobile.retry.hidden, false);
    const expected = lateOutcome === 'resolve' ? [false, true, true] : [true, true, true];
    assert.deepEqual(tablet.visible(), expected);

    mobile.retryRead();
    await settle();
    assert.equal(original.active, false);
    const refreshed = connection.subscriptions.at(-1);
    refreshed.receive({value: 'concentrations'});
    tablet.choose('all');
    assert.equal(connection.writes.length, 2);
    if (lateOutcome === 'resolve') first.resolve();
    else first.reject(new Error('Late failure'));
    await settle();
    assert.equal(tablet.fields.attributes['aria-busy'], 'true');
    assert.deepEqual(mobile.visible(), [false, true, true]);
    connection.writes[1].resolve();
    await settle();
    assert.equal(mobile.fields.attributes['aria-busy'], 'false');
    assert.deepEqual(tablet.visible(), [true, true, true]);
    mobile.remove();
    tablet.remove();
    await settle();
    assert.equal(refreshed.active, false);
  });
}
