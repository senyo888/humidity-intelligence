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
function actionBody(relativePath, title = 'Humidity') {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const card = source.indexOf(title === 'Stability Score' ? 'entity: sensor.hi_diagnostics\n' : `name: ${title}\n`);
  const tap = source.indexOf('tap_action:\n', card);
  const start = source.indexOf('[[[', tap);
  const block = source.slice(tap, source.indexOf(']]]', start) + 3);
  assert.match(block, /action: javascript/);
  return block.slice(block.indexOf('[[[') + 3, block.lastIndexOf(']]]'));
}
class DetailEvent extends Event {
  constructor(type, options = {}) { super(type, options); this.detail = options.detail; }
}
function harness({ supported = true, deferredClose = false, showThrows = false, missing = false, statesOverride } = {}) {
  const observers = new Set();
  const queuedCloseEvents = [];
  const window = new EventTarget();
  const connection = new EventTarget(); connection.connected = true;
  const timers = new Map(); let timerSequence = 0;
  const schedule = callback => { const id = ++timerSequence; timers.set(id, callback); return id; };
  class Node extends EventTarget {
    constructor(tagName = 'div') {
      super(); this.tagName = tagName.toUpperCase(); this.children = [];
      this.parentNode = null; this.attributes = {}; this.dataset = {}; this.style = {};
      this.className = ''; this.textContent = ''; this.open = false;
    }
    get innerHTML() { return this._html || ''; }
    set innerHTML(html) {
      this._html = html; this.replaceChildren();
      for (const name of ['hi-summary-close','hi-summary-history','hi-stability-close','hi-drift-close','hi-drift-history']) if (html.includes(name)) { const button = new Node('button'); button.className = name; this.appendChild(button); }
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
      if (selector.includes('close') || selector.includes('history')) return this.className === selector.replace(/^\./, '');
      if (selector.includes('template')) return this.tagName === 'TEMPLATE' && selector.includes(this.className);
      if (selector.includes('dialog')) return this.tagName === 'DIALOG' && Object.keys(this.attributes).some(key => selector.includes(key));
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
    showModal() { if (showThrows) throw new Error('Native dialog rejected'); this.open = true; this.querySelector('.hi-summary-close')?.focus(); }
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
  function owner(kind = 'summary') {
    const card = new Node('button-card'); card.shadowRoot = new Node('shadow-root');
    const button = new Node('ha-card'); button.setAttribute('id', 'card'); card.shadowRoot.appendChild(button);
    const template = new Node('template'); template.className = `hi-${kind}-${kind === 'summary' ? '' : 'details-'}template`;
    template.innerHTML = `<button class="hi-${kind}-close">Close</button><button class="hi-${kind}-history">View history</button>`;
    template.content = new Node('fragment');
    const close = new Node('button'); close.className = 'hi-stability-close';
    template.content.appendChild(close); card.shadowRoot.appendChild(template);
    document.body.appendChild(card); card.focus();
    return card;
  }
  function invoke(card, source = SURFACES[0], title = 'Humidity') {
    const body = actionBody(source, title);
    const routes = {Humidity:'sensor.house_average_humidity',Condensation:'sensor.worst_room_condensation',Mould:'sensor.worst_room_mould','Current Air Control':'sensor.air_control_mode',Ready:'sensor.house_average_humidity','Zone 1':'sensor.kitchen_humidity','Zone 2':'sensor.bathroom_humidity',AQ:'sensor.air_control_house_iaq_average'};
    const history = routes[title] || (title === 'Stability Score' ? 'sensor.hi_diagnostics' : 'sensor.house_humidity_drift_7d');
    const summary = routes[title] ? new Function(rendererBody(source,title,'hi_summary'))() : {history,title};
    new Function('document', 'window', 'MutationObserver', 'CustomEvent', 'entity', 'variables', 'states', 'hass', 'setTimeout', 'clearTimeout', body)
      .call(card, document, window, Observer, DetailEvent, { entity_id: history }, {hi_summary:summary}, statesOverride || (missing ? {} : {[history]:{state:'normal'}}), {connection}, schedule, id => timers.delete(id));
  }
  return { document, window, owner, invoke, observers, timers, connection,
    dialogs: () => document.querySelectorAll('[data-hi-summary-dialog]'),
    flushClose: () => queuedCloseEvents.splice(0).forEach(fire => fire()),
    flushObservers: () => [...observers].forEach(observer => observer.callback()),
  };
}


const TITLES = ['Humidity','Condensation','Mould','Current Air Control','Ready','Zone 1','Zone 2','AQ'];
test('all ten dialog actions expire through existing focus-restoring cleanup',()=>{
  for(const source of SURFACES) for(const title of [...TITLES,'7 Day Drift','Stability Score']){
    const h=harness();const card=h.owner(title==='7 Day Drift'?'drift':title==='Stability Score'?'stability':'summary');
    h.invoke(card,source,title);assert.equal(h.timers.size,1,title);
    [...h.timers.values()][0]();
    assert.equal(h.document.querySelectorAll('dialog').length,0,title);
    assert.equal(h.document.activeElement,card,title);
    assert.equal(h.timers.size,0,title);assert.equal(h.observers.size,0,title);
  }
});
test('each summary action matches all maintained layout and gallery counterparts', () => {
  for (const title of TITLES) assert.equal(new Set(SURFACES.map(source => actionBody(source,title).trim().split('\n').map(line=>line.trim()).join('\n'))).size, 1,title);
});
test('every summary opens and closes before dispatching its explicit history route', () => {
  const routes = ['sensor.house_average_humidity','sensor.worst_room_condensation','sensor.worst_room_mould','sensor.air_control_mode','sensor.house_average_humidity','sensor.kitchen_humidity','sensor.bathroom_humidity','sensor.air_control_house_iaq_average'];
  for (const source of SURFACES) for (const [i,title] of TITLES.entries()) {
    const h=harness(); const card=h.owner(); let detail;
    card.addEventListener('hass-more-info',event=>{assert.equal(h.dialogs().length,0); detail=event.detail;});
    h.invoke(card,source,title); const [dialog]=h.dialogs(); assert.ok(dialog.open);
    assert.equal(dialog.getAttribute('aria-label'),`${title} details`);
    if (['Condensation','Mould','Current Air Control','AQ'].includes(title)) {
      assert.equal(detail,undefined);
      dialog.querySelector('.hi-summary-close').dispatchEvent(new Event('click'));
    } else {
      dialog.querySelector('.hi-summary-history').dispatchEvent(new Event('click'));
      assert.equal(detail.entityId,routes[i]);
    }
    assert.equal(h.observers.size,0);
  }
});
test('Close, native Escape close, navigation, backdrop and removal clean up',()=>{
  for (const exit of ['close','native-close','pagehide','popstate','location-changed','backdrop','remove']) {
    const h=harness(); const card=h.owner(); h.invoke(card); const [d]=h.dialogs();
    if(exit==='close') d.querySelector('.hi-summary-close').dispatchEvent(new Event('click'));
    else if(exit==='native-close') d.close();
    else if(exit==='backdrop'){const e=new Event('click');Object.assign(e,{clientX:0,clientY:0});d.dispatchEvent(e);}
    else if(exit==='remove'){card.remove();h.flushObservers();}
    else h.window.dispatchEvent(new Event(exit));
    assert.equal(h.dialogs().length,0,exit);assert.equal(h.observers.size,0,exit);assert.equal(h.window.__hiBadgeDetailsDispose,undefined,exit);
  }
});
test('relevant rendered evidence changes close summary; unchanged evidence remains open',()=>{
  const h=harness();const card=h.owner();h.invoke(card);h.flushObservers();assert.equal(h.dialogs().length,1);
  card.shadowRoot.querySelector('template.hi-summary-template').innerHTML += 'changed source';
  h.flushObservers();assert.equal(h.dialogs().length,0);assert.equal(h.observers.size,0);
});
test('cross-badge replacement owns one dialog and deferred cleanup cannot steal focus',()=>{
  const h=harness({deferredClose:true});const one=h.owner();const two=h.owner();h.invoke(one);h.invoke(two,SURFACES[0],'AQ');
  assert.equal(h.dialogs().length,1);assert.equal(h.observers.size,2);const d=h.dialogs()[0];h.flushClose();
  assert.equal(h.document.activeElement,d.querySelector('.hi-summary-close'));assert.equal(h.dialogs().length,1);
});
test('fallback only dispatches an existing mapped entity and leaks no nodes',()=>{
  for(const options of [{supported:false},{showThrows:true},{supported:false,missing:true}]){
    const h=harness(options);const card=h.owner();let count=0;card.addEventListener('hass-more-info',()=>count++);h.invoke(card);
    assert.equal(count,options.missing?0:1);assert.equal(h.dialogs().length,0);assert.equal(h.observers.size,0);
  }
});
test('missing mapping disables history while explanation remains accessible',()=>{
  const h=harness({missing:true});const card=h.owner();let count=0;card.addEventListener('hass-more-info',()=>count++);h.invoke(card);
  const button=h.dialogs()[0].querySelector('.hi-summary-history');assert.equal(button.disabled,true);
  button.dispatchEvent(new Event('click'));assert.equal(count,0);
});
function rendererBody(source,title,key){
 const text=fs.readFileSync(path.join(ROOT,source),'utf8');
 const titleAt=text.indexOf(`name: ${title}\n`);
 const begin=key==='hi_summary'?text.lastIndexOf('hi_summary: |',titleAt):text.indexOf(`${key}: |`,titleAt);
 const start=text.indexOf('[[[',begin);return text.slice(start+3,text.indexOf(']]]',start));
}
test('renderer escapes dynamic risk, reason and history labels and qualifies existing routes',()=>{
 for(const source of SURFACES)for(const title of TITLES){
  const config=new Function(rendererBody(source,title,'hi_summary'))();
  const render=new Function('entity','variables','states',rendererBody(source,title,'summary'));
  const hostile='<img src=x onerror="bad()">';
  const entity={state:hostile,attributes:{risk:hostile}};
  const states={[config.history]:{attributes:{friendly_name:hostile}},'sensor.air_control_reason':{state:hostile}};
  const html=render(entity,{hi_summary:config},states);
  assert.ok(!html.includes(hostile),title);assert.match(html,/&lt;img/);assert.match(html,/Recorder and retention/);
  const absent=render(undefined,{hi_summary:config},{});assert.match(absent,/currently unavailable in Home Assistant/);assert.match(absent,/disabled/);assert.match(absent,/Unavailable/);
 }
});
test('compact badges preserve color expressions and icons are removed only from four cards',()=>{
 for(const source of SURFACES){
  const text=fs.readFileSync(path.join(ROOT,source),'utf8');
  for(const title of ['Ready','Zone 1','Zone 2','AQ']){
   const start=text.indexOf(`name: ${title}\n`);const end=text.indexOf('- type:',start);const card=text.slice(start,end);
   assert.match(card,/show_icon: false/);assert.match(card,/min-height: 46px/);assert.match(card,/font-size: 14px/);assert.match(card,/white-space: normal/);assert.match(card,/overflow-wrap: anywhere/);assert.match(card,/text-overflow: clip/);assert.match(card,/co_emergency/);assert.match(card,/box-shadow:/);
  }
  assert.match(text,/safe-area-inset-top/);assert.match(text,/safe-area-inset-bottom/);
  const title=text.indexOf('<h2>Stability Score</h2>');const footer=text.indexOf('These details capture the moment you opened this panel.');assert.ok(footer>title);
 }
});

test('new summaries, drift and Stability dispose one another without changing snapshot policies',()=>{
 for(const source of SURFACES){
  const h=harness();const regular=h.owner();const drift=h.owner('drift');const stability=h.owner('stability');
  h.invoke(regular,source);h.invoke(drift,source,'7 Day Drift');
  assert.equal(h.dialogs().length,0);assert.equal(h.document.querySelectorAll('[data-hi-drift-dialog]').length,1);assert.equal(h.observers.size,2);
  h.invoke(stability,source,'Stability Score');
  assert.equal(h.document.querySelectorAll('[data-hi-drift-dialog]').length,0);assert.equal(h.document.querySelectorAll('[data-hi-stability-dialog]').length,1);assert.equal(h.observers.size,2);
  stability.shadowRoot.replaceChildren();h.flushObservers();assert.equal(h.document.querySelectorAll('[data-hi-stability-dialog]').length,1);
  h.invoke(regular,source);assert.equal(h.document.querySelectorAll('[data-hi-stability-dialog]').length,0);assert.equal(h.dialogs().length,1);assert.equal(h.observers.size,2);
  h.invoke(drift,source,'7 Day Drift');drift.shadowRoot.querySelector('template.hi-drift-details-template').innerHTML+='new evidence';h.flushObservers();assert.equal(h.observers.size,0);assert.equal(h.document.querySelectorAll('[data-hi-drift-dialog]').length,0);
 }
});

test('humidity summary accepts strict finite numeric strings and rejects malformed evidence',()=>{
 for(const source of SURFACES){
  const config=new Function(rendererBody(source,'Humidity','hi_summary'))();
  const render=new Function('entity','variables','states',rendererBody(source,'Humidity','summary'));
  for(const value of ['NaN','Infinity','-Infinity','bad','48bad','',' ','unknown','unavailable','true','0x10',true,false,48,NaN,Infinity,null,undefined]){
   const html=render({state:value},{hi_summary:config},{});
   assert.match(html,/Current humidity: Unavailable\./,String(value));
  }
  for(const value of ['0','-2.5','48','48.5','+1','.5','1e2']){
   const html=render({state:value},{hi_summary:config},{});
   assert.ok(html.includes(`Current humidity: ${value}%.`),value);
  }
 }
});

test('each summary provides an escaped native keyboard button without intercepting pointers',()=>{
 for(const source of SURFACES)for(const title of TITLES){
  const config=new Function(rendererBody(source,title,'hi_summary'))();
  const render=new Function('entity','variables',rendererBody(source,title,'summary_open'));
  const html=render({state:'<bad "value">'},{hi_summary:config});
  assert.match(html,/<button type="button" class="hi-summary-open"/);assert.match(html,/aria-label=/);assert.match(html,/Open details/);
  assert.ok(!html.includes('<bad'));
  const text=fs.readFileSync(path.join(ROOT,source),'utf8');
  assert.match(text,/\.hi-summary-open \{[^}]*pointer-events:none/);
  assert.match(text,/\.hi-summary-open:focus-visible/);
 }
});

test('enhanced-history native fallback selects an available explicitly mapped source',()=>{
 for(const source of SURFACES){
  const h=harness({supported:false,statesOverride:{'sensor.worst_room_condensation_risk':{state:'Risk'}}});
  const card=h.owner();let event;card.addEventListener('hass-more-info',e=>event=e.detail);
  h.invoke(card,source,'Condensation');assert.equal(event.entityId,'sensor.worst_room_condensation_risk');assert.equal(h.dialogs().length,0);
 }
});
