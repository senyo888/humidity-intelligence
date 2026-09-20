import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source=fs.readFileSync(new URL('../custom_components/humidity_intelligence/ui/inactivity.js',import.meta.url),'utf8');
class Target {
  listeners=new Map(); isConnected=true;
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
  removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
  emit(type,extra={}){for(const fn of [...this.listeners.get(type)||[]])fn({type,isTrusted:true,...extra});}
  count(){return [...this.listeners.values()].reduce((n,s)=>n+s.size,0);}
}
function harness(){
 const window=new Target(),dialog=new Target(),connection=new Target();connection.connected=true;
 const owner=new Target();owner.getRootNode=()=>window;
 let time=0,sequence=0,closed=0;const pending=new Map(),observers=[];
 class Observer{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.stopped=true;}}
 const setTimeout=(fn,delay)=>{const id=++sequence;pending.set(id,{fn,at:time+delay});return id;};
 const clearTimeout=id=>pending.delete(id);
 const helper=new Function('window','MutationObserver','setTimeout','clearTimeout','Date',source+'\nreturn hiDialogInactivity;')(window,Observer,setTimeout,clearTimeout,{now:()=>time});
 const close=()=>{closed++;dialog.emit('close');};
 const open=()=>helper(dialog,owner,close,connection);
 const advance=ms=>{const end=time+ms;while(true){const next=[...pending].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;time=next[1].at;pending.delete(next[0]);next[1].fn();}time=end;};
 return {window,dialog,connection,owner,pending,observers,open,advance,get closed(){return closed;}};
}
test('expires at exactly120 seconds and releases all listeners/timers',()=>{
 const h=harness();h.open();h.advance(119999);assert.equal(h.closed,0);h.advance(1);assert.equal(h.closed,1);
 assert.equal(h.pending.size,0);assert.equal(h.dialog.count()+h.window.count()+h.connection.count(),0);assert.ok(h.observers.every(o=>o.stopped));
});
test('real pointer touch keyboard input and wheel restart owning timer',()=>{
 for(const type of ['pointerdown','touchstart','touchmove','keydown','input','wheel']){
  const h=harness();h.open();h.advance(119000);h.dialog.emit(type);h.advance(119999);assert.equal(h.closed,0,type);h.advance(1);assert.equal(h.closed,1,type);
 }
});
test('nested history input counts; synthetic input and passive scroll do not',()=>{
 const h=harness();h.open();h.advance(60000);
 h.dialog.emit('keydown',{target:{dataset:{history:true}}});h.advance(1000);
 h.dialog.emit('scroll');h.advance(100000);h.dialog.emit('scroll');h.dialog.emit('pointerdown',{isTrusted:false});
 h.advance(19999);assert.equal(h.closed,0);h.advance(1);assert.equal(h.closed,1);
 const passive=harness();passive.open();passive.advance(119000);passive.dialog.emit('scroll');passive.advance(1000);assert.equal(passive.closed,1);
});
test('manual close cancels old callbacks and reopen starts an independent full interval',()=>{
 const h=harness();const dispose=h.open();const stale=[...h.pending.values()][0].fn;
 h.advance(40000);h.dialog.emit('close');dispose();assert.equal(h.pending.size,0);
 h.open();stale();assert.equal(h.closed,0);h.advance(119999);assert.equal(h.closed,0);h.advance(1);assert.equal(h.closed,1);
});
test('stale reset callback cannot close a renewed panel',()=>{
 const h=harness();h.open();const stale=[...h.pending.values()][0].fn;h.advance(60000);h.dialog.emit('pointerdown');stale();assert.equal(h.closed,0);h.advance(120000);assert.equal(h.closed,1);
});
test('navigation removal and disconnect close immediately and cancel timers',()=>{
 for(const exit of ['location-changed','popstate','pagehide','disconnected','owner','dialog']){
  const h=harness();h.open();
  if(exit==='disconnected')h.connection.emit(exit);
  else if(['owner','dialog'].includes(exit)){h[exit].isConnected=false;h.observers[0].fn();}
  else h.window.emit(exit);
  assert.equal(h.closed,1,exit);assert.equal(h.pending.size,0);h.advance(240000);assert.equal(h.closed,1,exit);
 }
});
test('repeated content mutations do not renew inactivity',()=>{
 const h=harness();h.open();h.advance(119000);h.observers[0].fn();h.advance(1000);assert.equal(h.closed,1);
});
test('all existing dialog openers own one helper and dispose in cleanup',()=>{
 for(const path of ['custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml','custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml','ui-gallery/default-v2-mobile-aq/card.yaml','ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml']){
  const yaml=fs.readFileSync(new URL('../'+path,import.meta.url),'utf8').split('// HI-UI-REVISION:START')[0];
  assert.equal((yaml.match(/idleDispose = hiDialogInactivity\(dialog, owner, close, hass\?\.connection\)/g)||[]).length,10,path);
  assert.equal((yaml.match(/idleDispose\?\.\(\)/g)||[]).length,10,path);
 }
});
