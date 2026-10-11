import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source=fs.readFileSync(new URL('../custom_components/humidity_intelligence/ui/revision_status.js',import.meta.url),'utf8');
class Events {
 listeners=new Map();isConnected=true;
 addEventListener(n,f){if(!this.listeners.has(n))this.listeners.set(n,new Set());this.listeners.get(n).add(f);}
 removeEventListener(n,f){this.listeners.get(n)?.delete(f);}
 emit(n,event={}){for(const f of [...(this.listeners.get(n)||[])])f({target:this,isTrusted:true,...event});}
 focus(){this.focused=(this.focused||0)+1;}
}
function harness(){
 let now=0,id=0;const timers=new Map(),callbacks=[],observers=[],dialogs=[];
 const schedule=(fn,ms)=>{timers.set(++id,{fn,at:now+ms});callbacks.push(fn);return id;};
 const cancel=id=>timers.delete(id);
 const advance=ms=>{const until=now+ms;while(true){const next=[...timers].filter(([,t])=>t.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;now=next[1].at;timers.delete(next[0]);next[1].fn();}now=until;};
 class Observer{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.disposed=true;}}
 const window=new Events(),connection=new Events();connection.connected=true;
 const footer=new Events();footer.dataset={};footer.label={};footer.querySelector=()=>footer.label;footer.getAttribute=()=>'';footer.setAttribute=()=>{};
 const root=new Events();root.querySelector=()=>footer;root.activeElement=footer;
 const owner=new Events();owner.shadowRoot=root;owner.getRootNode=()=>root;
 const document={activeElement:footer,body:{appendChild(d){d.isConnected=true;}},createElement(){
  const d=new Events();d.closeButton=new Events();d.querySelector=()=>d.closeButton;d.setAttribute=()=>{};d.showModal=()=>{d.open=true;};d.close=()=>{d.open=false;d.emit('close');};d.remove=()=>{d.isConnected=false;};d.getBoundingClientRect=()=>({left:0,right:100,top:0,bottom:100});dialogs.push(d);return d;
 }};
 const model=new Function('window','document','MutationObserver','setTimeout','clearTimeout','Date',source+'\nreturn hiUiRevision;')(window,document,Observer,schedule,cancel,{now:()=>now});
 const stamp={schema:1,entry:'test',layout:'v2_mobile',revision:3,generator:1};const entity={state:'ok',attributes:{ui_revision:{schema:1,entry:'test',layouts:{v2_mobile:{revision:3,generator:1,supersedes:[1,2]}}}}};const hass={connection,states:{test:entity}};
 model.render(owner,hass,entity,stamp);const state=owner[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];
 return {state,dialogs,advance,timers,callbacks,footer,connection,window,owner,observers,model,hass,entity,stamp};
}
test('revision details expire after inactivity, trusted interaction renews, telemetry does not',()=>{
 const h=harness();h.state.open();const d=h.dialogs.at(-1);h.advance(119000);assert.equal(d.open,true);d.emit('pointerdown');h.advance(119000);assert.equal(d.open,true);
 h.model.render(h.owner,{...h.hass,states:{}},structuredClone(h.entity),h.stamp);d.emit('click',{isTrusted:false});h.advance(1000);assert.equal(d.open,false);assert.equal(h.timers.size,0);assert.equal(h.footer.focused,1);h.model.dispose(h.owner);
});
test('manual close and stale deadlines cannot close a reopened or replacement dialog',()=>{
 const h=harness();h.state.open();const first=h.dialogs.at(-1),stale=h.callbacks.at(-1);first.closeButton.emit('click');assert.equal(h.timers.size,0);h.state.open();const second=h.dialogs.at(-1);stale();assert.equal(second.open,true);h.advance(119999);assert.equal(second.open,true);h.advance(1);assert.equal(second.open,false);h.model.dispose(h.owner);
});
test('Escape close event, backdrop, disconnect, navigation and removal dispose idle custody',()=>{
 for(const exit of ['close','backdrop','disconnect','navigation','removal']){
  const h=harness();h.state.open();const d=h.dialogs.at(-1);
  if(exit==='close')d.close();else if(exit==='backdrop')d.emit('click',{clientX:200,clientY:200});else if(exit==='disconnect'){h.connection.connected=false;h.connection.emit('disconnected');}else if(exit==='navigation')h.window.emit('location-changed');else {h.owner.isConnected=false;for(const o of h.observers)if(!o.disposed)o.fn();}
  assert.equal(h.timers.size,0,exit);assert.equal(d.isConnected,false,exit);h.advance(120000);h.model.dispose(h.owner);
 }
});
