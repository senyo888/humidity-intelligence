import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {setImmediate as settle} from 'node:timers/promises';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../custom_components/humidity_intelligence/ui/voc_presentation.js', import.meta.url), 'utf8');
const accepted = 'Request accepted by Home Assistant.';
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
    const Presentation = elements.get('hi-voc-presentation-v5');
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
    const resend = {matches: selector => selector === '[data-voc-resend]'};
    const labels = {all:'All configured readings', indices:'Monitor indices only', concentrations:'Concentration averages only'};
    const radios = Object.entries(labels).map(([value, textContent]) => Object.assign(new Element(), {
      value, labels: [{textContent}], matches: selector => selector === 'input[name="hi-voc-choice"]',
    }));
    const controls = {'[role="status"]': status, '[data-voc-retry]': retry, '[data-voc-resend]': resend};
    fields.querySelector = selector => controls[selector];
    fields.querySelectorAll = () => radios;
    details.fields = fields;
    details.connectedCallback();
    return {
      owner, render, dialog, fields, status, retry, resend, radios,
      choose: mode => details.handleEvent({type: 'change', target: radios.find(radio => radio.value === mode)}),
      retryRead: () => details.handleEvent({type: 'click', target: retry}),
      resendWrite: () => details.handleEvent({type: 'click', target: resend}),
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
  assert.deepEqual(card.visible(), [false, true, true]);
  assert.equal(card.status.textContent, 'Display preference unavailable');
  assert.ok(card.radios.every(radio => radio.attributes['aria-disabled'] === 'true'));
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

test('ready reuses an in-flight subscription and read retry reopens a failed read', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const subscribe = connection.subscribeMessage.bind(connection);
  let acknowledge;
  connection.subscribeMessage = async (...args) => {
    const off = await subscribe(...args);
    await new Promise(resolve => { acknowledge = resolve; });
    return off;
  };
  const card = mount(connection, 'v2_mobile');
  await settle();
  connection.connected = false;
  connection.dispatchEvent(new Event('disconnected'));
  connection.connected = true;
  connection.dispatchEvent(new Event('ready'));
  await settle();
  assert.equal(connection.subscriptions.length, 1);
  acknowledge();
  await settle();
  advance(10000);
  assert.equal(card.status.textContent, 'Display preference unavailable');
  connection.subscribeMessage = subscribe;
  card.retryRead();
  await settle();
  assert.equal(connection.subscriptions.length, 2);
  assert.equal(connection.subscriptions[0].active, false);
  connection.subscriptions[1].receive({value: null});
  assert.equal(card.status.textContent, '');
  assert.equal(connection.writes.length, 0);
  card.remove();
  await settle();
});

test('a readback of a failed save keeps the attempted value retryable across layouts', async () => {
  const {mount} = fixture();
  const connection = new Connection();
  const mobile = mount(connection, 'v2_mobile');
  const tablet = mount(connection, 'v2_tablet');
  await settle();
  const subscription = connection.subscriptions[0];
  subscription.receive({value: null});
  mobile.choose('indices');
  connection.writes[0].reject(new Error('Write failed'));
  await settle();
  subscription.receive({value: 'indices'});
  assert.equal(tablet.status.textContent, 'Request unconfirmed.');
  assert.equal(tablet.resend.hidden, false);
  assert.equal(tablet.resend.textContent, 'Resend “Monitor indices only”');
  tablet.resendWrite();
  assert.deepEqual(connection.writes[1].request, connection.writes[0].request);
  connection.writes[1].resolve();
  await settle();
  assert.equal(subscription.active, false);
  assert.equal(connection.subscriptions.length, 2);
  for (const card of [mobile, tablet]) {
    assert.equal(card.status.textContent, accepted + ' Loading display preference…');
    assert.deepEqual(card.visible(), [true, false, true]);
    assert.equal(card.radios.find(radio => radio.checked)?.value, 'indices');
    assert.ok(card.radios.every(radio => radio.attributes['aria-disabled'] === 'true'));
  }
  mobile.choose('all');
  assert.equal(connection.writes.length, 2);
  const live = connection.subscriptions[1];
  live.receive({value: 'indices'});
  assert.equal(mobile.status.textContent, accepted);
  assert.equal(tablet.resend.hidden, true);
  live.receive({value: 'concentrations'});
  assert.deepEqual(mobile.visible(), [false, true, true]);
  mobile.remove(); tablet.remove();
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
    assert.equal(mobile.status.textContent, 'Request unconfirmed.');
    assert.equal(tablet.fields.attributes['aria-busy'], 'false');
    assert.equal(mobile.resend.hidden, false);
    const expected = lateOutcome === 'resolve' ? [false, true, true] : [true, true, true];
    assert.deepEqual(tablet.visible(), expected);

    mobile.resendWrite();
    assert.equal(original.active, true);
    assert.equal(connection.writes.length, 2);
    assert.deepEqual(connection.writes[1].request, first.request);
    if (lateOutcome === 'resolve') first.resolve();
    else first.reject(new Error('Late failure'));
    await settle();
    assert.equal(tablet.fields.attributes['aria-busy'], 'true');
    assert.deepEqual(mobile.visible(), expected);
    connection.writes[1].resolve();
    await settle();
    assert.equal(original.active, false);
    connection.subscriptions.at(-1).receive({value: 'indices'});
    assert.equal(mobile.fields.attributes['aria-busy'], 'false');
    assert.deepEqual(tablet.visible(), [true, false, true]);
    mobile.remove();
    tablet.remove();
    await settle();
    assert.equal(original.active, false);
  });
}

test('a late acknowledgement confirms the latest write without a second write', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const card = mount(connection, 'v2_mobile');
  await settle();
  connection.subscriptions[0].receive({value: null});
  card.choose('indices');
  assert.equal(card.status.textContent, 'Sending request…');
  advance(10000);
  assert.equal(card.status.textContent, 'Request unconfirmed.');
  connection.writes[0].resolve();
  await settle();
  assert.equal(card.status.textContent, accepted);
  assert.equal(card.resend.hidden, true);
  assert.deepEqual(card.visible(), [true, false, true]);
  assert.equal(connection.writes.length, 1);
  card.remove();
  await settle();
});

test('Diagnostics loss releases the read and restores only the same scoped retry', async () => {
  const {mount} = fixture();
  const connection = new Connection();
  const tablet = mount(connection, 'v2_tablet');
  await settle();
  const original = connection.subscriptions[0];
  original.receive({value: null});
  tablet.choose('concentrations');
  connection.writes[0].reject(new Error('Write failed'));
  await settle();
  const diag = tablet.owner.hass.states.diagnostics;
  diag.state = 'unavailable';
  tablet.render();
  await settle();
  assert.equal(original.active, false);
  assert.equal(tablet.fields.hidden, true);
  const otherConnection = new Connection();
  const others = [mount(connection, 'v2_mobile', secondEntry), mount(connection, 'v2_mobile', entry, 'other'),
    mount(otherConnection, 'v2_mobile')];
  await settle();
  for (const sub of [...connection.subscriptions.slice(1), ...otherConnection.subscriptions]) sub.receive({value: null});
  assert.ok(others.every(card => card.resend.hidden));
  diag.state = 'ok';
  tablet.render();
  await settle();
  const restored = connection.subscriptions.at(-1);
  restored.receive({value: 'concentrations'});
  assert.equal(tablet.status.textContent, 'Request unconfirmed.');
  assert.match(tablet.resend.textContent, /Concentration averages only/);
  assert.equal(connection.writes.length, 1);
  tablet.resendWrite();
  connection.writes[1].resolve();
  await settle();
  assert.equal(restored.active, false);
  restored.receive({value: 'indices'});  // Retired callback cannot complete the new read.
  assert.match(tablet.status.textContent, /Loading/);
  assert.deepEqual(tablet.visible(), [false, true, true]);
  connection.subscriptions.at(-1).receive({value: 'all'});
  assert.equal(tablet.status.textContent, '');
  assert.deepEqual(tablet.visible(), [true, true, true]);
  for (const card of [tablet, ...others]) card.remove();
  await settle();
});

test('a late acknowledgement clears the warning and keeps a newer live choice', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const card = mount(connection, 'v2_tablet');
  await settle();
  const live = connection.subscriptions[0];
  live.receive({value: null});
  card.choose('indices');
  assert.equal(card.status.textContent, 'Sending request…');
  advance(10000);
  live.receive({value: 'concentrations'});
  assert.equal(card.status.textContent, 'Request unconfirmed.');
  connection.writes[0].resolve();
  await settle();
  assert.equal(card.status.textContent, '');
  assert.deepEqual(card.visible(), [false, true, true]);
  assert.equal(connection.subscriptions.length, 1);
  card.remove();
  await settle();
});

test('a failed reread keeps the last verified choice until a fresh valid value arrives', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const mobile = mount(connection, 'v2_mobile');
  const tablet = mount(connection, 'v2_tablet');
  await settle();
  connection.subscriptions[0].receive({value: 'concentrations'});
  mobile.choose('indices');
  connection.writes[0].reject(new Error('No acknowledgement'));
  await settle();
  tablet.resendWrite();
  connection.writes[1].resolve();
  await settle();
  advance(10000);
  for (const card of [mobile, tablet]) {
    assert.equal(card.status.textContent, accepted + ' Display preference unavailable');
    assert.deepEqual(card.visible(), [false, true, true]);
    assert.equal(card.retry.hidden, false);
  }
  const separate = [mount(connection, 'v2_mobile', secondEntry), mount(connection, 'v2_mobile', entry, 'other'),
    mount(new Connection(), 'v2_tablet')];
  for (const card of separate) {
    assert.deepEqual(card.visible(), [true, true, true]);
    assert.ok(card.radios.every(radio => !radio.checked));
    assert.equal(card.status.textContent, 'Loading display preference…');
  }
  mobile.retryRead();
  await settle();
  const fresh = connection.subscriptions.at(-1);
  fresh.receive({value: 'unsupported'});
  tablet.choose('all');
  assert.equal(connection.writes.length, 2);
  assert.deepEqual(mobile.visible(), [false, true, true]);
  fresh.receive({value: 'indices'});
  for (const card of [mobile, tablet]) {
    assert.deepEqual(card.visible(), [true, false, true]);
    assert.equal(card.status.textContent, accepted);
    assert.ok(card.radios.every(radio => radio.attributes['aria-disabled'] === 'false'));
  }
  for (const card of [mobile, tablet, ...separate]) card.remove();
  await settle();
});

for (const value of ['indices', 'concentrations']) {
  test('a valid ' + value + ' update during resend keeps its live subscription', async () => {
    const {mount, advance} = fixture();
    const connection = new Connection();
    const mobile = mount(connection, 'v2_mobile');
    const tablet = mount(connection, 'v2_tablet');
    await settle();
    const live = connection.subscriptions[0];
    live.receive({value: 'all'});
    mobile.choose('indices');
    advance(10000);
    tablet.resendWrite();
    live.receive({value});
    connection.writes[1].resolve();
    await settle();
    advance(10000);
    assert.equal(connection.subscriptions.length, 1);
    assert.ok(live.active);
    for (const card of [mobile, tablet]) {
      assert.equal(card.status.textContent, value === 'indices' ? accepted : '');
      assert.equal(card.radios.find(radio => radio.checked)?.value, value);
      assert.ok(card.radios.every(radio => radio.attributes['aria-disabled'] === 'false'));
    }
    live.receive({value: 'all'});
    assert.deepEqual(tablet.visible(), [true, true, true]);
    mobile.remove(); tablet.remove();
    await settle();
  });
}

test('Diagnostics recovery reuses the scoped filter after the last view releases its subscription', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const mobile = mount(connection, 'v2_mobile');
  await settle();
  const previous = connection.subscriptions[0];
  previous.receive({value: 'indices'});
  const diag = mobile.owner.hass.states.diagnostics;
  diag.state = 'unavailable';
  mobile.render();
  await settle();
  assert.equal(previous.active, false);
  assert.deepEqual(mobile.visible(), [true, true, true]);
  const others = [mount(connection, 'v2_mobile', secondEntry), mount(connection, 'v2_tablet', entry, 'other'),
    mount(new Connection(), 'v2_mobile')];
  assert.ok(others.every(card => card.radios.every(radio => !radio.checked)));
  diag.state = 'ok';
  diag.attributes.diagnostics_summary.voc_index_sources.configured = 0;
  mobile.render();
  assert.equal(mobile.fields.hidden, true);
  diag.attributes.diagnostics_summary.voc_index_sources.configured = 1;
  mobile.render();
  await settle();
  previous.receive({value: 'all'});
  const tablet = mount(connection, 'v2_tablet');
  advance(10000);
  for (const card of [mobile, tablet]) {
    assert.deepEqual(card.visible(), [true, false, true]);
    assert.equal(card.status.textContent, 'Display preference unavailable');
    assert.ok(card.radios.every(radio => radio.attributes['aria-disabled'] === 'true'));
  }
  connection.subscriptions.at(-1).receive({value: 'concentrations'});
  assert.deepEqual(mobile.visible(), [false, true, true]);
  assert.deepEqual(tablet.visible(), mobile.visible());
  assert.equal(connection.writes.length, 0);
  for (const card of [mobile, tablet, ...others]) card.remove();
  await settle();
});

test('Retry read and Resend recover independently when both requests fail', async () => {
  const {mount, advance} = fixture();
  const connection = new Connection();
  const mobile = mount(connection, 'v2_mobile');
  const tablet = mount(connection, 'v2_tablet');
  await settle();
  connection.subscriptions[0].receive({value: 'indices'});
  mobile.choose('concentrations');
  connection.writes[0].reject(new Error('No acknowledgement'));
  await settle();
  connection.connected = false;
  connection.dispatchEvent(new Event('disconnected'));
  assert.ok(mobile.retry.disabled && mobile.resend.disabled);
  mobile.retryRead();
  mobile.resendWrite();
  assert.equal(connection.writes.length, 1);
  connection.connected = true;
  connection.dispatchEvent(new Event('ready'));
  advance(10000);
  for (const card of [mobile, tablet]) {
    assert.equal(card.status.textContent, 'Request unconfirmed. Display preference unavailable');
    assert.ok(!card.retry.hidden && !card.resend.hidden && !card.retry.disabled && !card.resend.disabled);
    assert.equal(card.resend.textContent, 'Resend “Concentration averages only”');
  }
  tablet.retryRead();
  tablet.retryRead();
  await settle();
  assert.equal(connection.writes.length, 1);
  assert.equal(connection.subscriptions.length, 2);
  assert.ok(mobile.retry.hidden && !mobile.resend.hidden);
  const live = connection.subscriptions[1];
  live.receive({value: 'all'});
  assert.equal(mobile.status.textContent, 'Request unconfirmed.');
  assert.deepEqual(tablet.visible(), [true, true, true]);
  mobile.resendWrite();
  assert.deepEqual(connection.writes[1].request, connection.writes[0].request);
  live.receive({value: 'concentrations'});
  connection.writes[1].resolve();
  await settle();
  assert.ok(live.active);
  assert.equal(tablet.status.textContent, accepted);
  assert.ok(tablet.retry.hidden && tablet.resend.hidden);
  mobile.remove(); tablet.remove();
  await settle();
});

test('an acknowledgement during a read retry lets that pending read complete', async () => {
  const {mount} = fixture();
  const connection = new Connection();
  const card = mount(connection, 'v2_mobile');
  await settle();
  const original = connection.subscriptions[0];
  original.receive({value: 'indices'});
  card.choose('concentrations');
  connection.writes[0].reject(new Error('Write failed'));
  await settle();
  original.receive({value: 'invalid'});
  card.resendWrite();
  card.retryRead();
  await settle();
  const replacement = connection.subscriptions[1];
  connection.writes[1].resolve();
  await settle();
  assert.ok(replacement.active);
  assert.equal(connection.subscriptions.length, 2);
  assert.deepEqual(card.visible(), [true, false, true]);
  replacement.receive({value: 'concentrations'});
  assert.equal(card.status.textContent, accepted);
  assert.deepEqual(card.visible(), [false, true, true]);
  card.remove();
  await settle();
});
