import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source=fs.readFileSync(new URL('../custom_components/humidity_intelligence/ui/revision_status.js',import.meta.url),'utf8');
const ui=new Function(source+'\nreturn hiUiRevision;')();
const stamp={schema:1,entry:'opaque-entry',layout:'v2_mobile',revision:1,generator:1};
const metadata={schema:1,entry:'opaque-entry',layouts:{v2_mobile:{revision:1,generator:1,supersedes:[]}}};
const copy=()=>structuredClone(metadata);
test('current requires exact supported entry layout revision and generator',()=>{
 assert.equal(ui.classify(stamp,metadata,true).kind,'current');
 assert.equal(ui.classify({...stamp,layout:'v2_tablet'},metadata,true).kind,'unknown');
 assert.equal(ui.classify({...stamp,entry:'another'},metadata,true).kind,'unknown');
 assert.equal(ui.classify(stamp,metadata,false).kind,'unknown');
 for(const generator of [0,2,null,'1'])assert.equal(ui.classify({...stamp,generator},metadata,true).kind,'unknown');
});
test('update is explicit supersession; rollback or different revision does not claim newer',()=>{
 const next=copy();next.layouts.v2_mobile.revision=2;
 assert.equal(ui.classify(stamp,next,true).kind,'different');
 next.layouts.v2_mobile.supersedes=[1];assert.equal(ui.classify(stamp,next,true).kind,'update');
 assert.equal(ui.classify({...stamp,revision:3},next,true).kind,'different');
});
test('missing malformed unsupported metadata never reports current',()=>{
 for(const item of [null,undefined,{},[],{...metadata,schema:2},{...metadata,layouts:null}])assert.equal(ui.classify(stamp,item,true).kind,'unknown');
 for(const revision of [0,-1,1.1,'1',Infinity,NaN,Number.MAX_SAFE_INTEGER+1]){
  const item=copy();item.layouts.v2_mobile.revision=revision;assert.equal(ui.classify(stamp,item,true).kind,'unknown');
 }
 for(const supersedes of [null,{},['1'],[0],[Infinity],[1],[2],[1,1]]){
  const item=copy();item.layouts.v2_mobile.supersedes=supersedes;assert.equal(ui.classify(stamp,item,true).kind,'unknown');
 }
});
class Events {
 listeners=new Map();connected=true;
 addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn);}
 removeEventListener(name,fn){this.listeners.get(name)?.delete(fn);}
 emit(name){for(const fn of [...(this.listeners.get(name)||[])])fn();}
 count(){return [...this.listeners.values()].reduce((sum,set)=>sum+set.size,0);}
}
function harness(){
 const window=new Events();const observers=[];
 class Observer{constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){this.stopped=true;}}
 const model=new Function('window','MutationObserver',source+'\nreturn hiUiRevision;')(window,Observer);
 const button=new Events();button.dataset={};button.label={textContent:''};button.attrs={};button.querySelector=()=>button.label;button.getAttribute=name=>button.attrs[name];button.setAttribute=(name,value)=>button.attrs[name]=value;
 const shadowRoot=new Events();shadowRoot.querySelector=()=>button;
 const owner={isConnected:true,shadowRoot};
 const connection=new Events();const entity={state:'ok',attributes:{ui_revision:metadata}};
 const hass={connection,states:{diagnostics:entity}};
 return {model,window,observers,owner,connection,entity,hass,button};
}
test('disconnect paints unknown immediately; ready alone cannot bless cached evidence',async()=>{
 const h=harness();h.model.render(h.owner,h.hass,h.entity,stamp);await Promise.resolve();assert.equal(h.button.dataset.status,'current');
 h.connection.connected=false;h.connection.emit('disconnected');assert.equal(h.button.dataset.status,'unknown');
 h.connection.connected=true;h.connection.emit('ready');assert.equal(h.button.dataset.status,'unknown');
 assert.match(h.model.render(h.owner,h.hass,h.entity,stamp),/data-status="unknown"/);
 assert.match(h.model.render(h.owner,{...h.hass,states:{diagnostics:h.entity}},h.entity,stamp),/data-status="unknown"/);
 const fresh=structuredClone(h.entity);assert.match(h.model.render(h.owner,{...h.hass,states:{diagnostics:fresh}},fresh,stamp),/data-status="current"/);
 h.model.dispose(h.owner);assert.equal(h.connection.count(),0);assert.equal(h.window.count(),0);assert.equal(h.button.count(),0);assert.ok(h.observers.every(o=>o.stopped));
});
test('unavailable Diagnostics remains unknown with live connection',()=>{
 const h=harness();assert.match(h.model.render(h.owner,h.hass,{...h.entity,state:'unavailable'},stamp),/data-status="unknown"/);h.model.dispose(h.owner);
});
test('repeated render uses one lifecycle; navigation and removal clean up all subscriptions',()=>{
 for(const exit of ['location-changed','popstate','pagehide','removal']){
  const h=harness();for(let i=0;i<5;i++)h.model.render(h.owner,h.hass,h.entity,stamp);
  assert.equal(h.connection.count(),2);assert.equal(h.window.count(),3);assert.equal(h.observers.length,1);
  if(exit==='removal'){h.owner.isConnected=false;h.observers[0].callback();}else h.window.emit(exit);
  assert.equal(h.connection.count(),0);assert.equal(h.window.count(),0);assert.ok(h.observers[0].stopped);
 }
});
test('new connection replaces subscriptions and starts unknown when disconnected',()=>{
 const h=harness();h.model.render(h.owner,h.hass,h.entity,stamp);
 const replacement=new Events();replacement.connected=false;
 assert.match(h.model.render(h.owner,{...h.hass,connection:replacement},h.entity,stamp),/data-status="unknown"/);
 assert.equal(h.connection.count(),0);assert.equal(replacement.count(),2);h.model.dispose(h.owner);
});

test('footer keyboard activation captures only its exact button and cleans up',async()=>{
 const h=harness();h.model.render(h.owner,h.hass,h.entity,stamp);await Promise.resolve();
 const state=h.owner[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];let opened=0;state.open=()=>opened++;
 const event=(key,repeat=false,target=h.button)=>({key,repeat,composedPath:()=>[{},target,h.owner.shadowRoot],preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}});
 for(const key of ['Enter',' ']){
  const e=event(key);state.keydown(e);assert.equal(e.prevented,true);assert.equal(e.stopped,true);
 }
 assert.equal(opened,2);
 const repeat=event('Enter',true);state.keydown(repeat);assert.equal(opened,2);assert.equal(repeat.prevented,true);
 for(const e of [event('Tab'),event('Escape'),event('Enter',false,{})]){state.keydown(e);assert.equal(e.prevented,undefined);assert.equal(e.stopped,undefined);}
 assert.equal(opened,2);assert.equal(h.owner.shadowRoot.count(),1);
 h.model.dispose(h.owner);assert.equal(h.owner.shadowRoot.count(),0);
});

test('supersession excludes duplicate older revisions and cannot mislabel a rollback',()=>{
 const item=copy();item.layouts.v2_mobile={revision:3,generator:1,supersedes:[1,2]};
 assert.equal(ui.classify(stamp,item,true).kind,'update');
 item.layouts.v2_mobile.supersedes=[1,1];assert.equal(ui.classify(stamp,item,true).kind,'unknown');
 item.layouts.v2_mobile.supersedes=[4];assert.equal(ui.classify({...stamp,revision:4},item,true).kind,'unknown');
 assert.match(ui.classify(stamp,metadata,true).reason,/mappings, options and frontend resources are not verified/);
});
