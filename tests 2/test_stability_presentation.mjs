import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source=fs.readFileSync(new URL('../custom_components/humidity_intelligence/ui/stability_presentation.js',import.meta.url),'utf8');
const OWNER=Symbol.for('humidity_intelligence.stability_presentation.owner.v1');
const ENTRY='a'.repeat(64), OTHER='b'.repeat(64);
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
class Element extends EventTarget {
 attrs={};textContent='';isConnected=true;
 getAttribute(key){return this.attrs[key]??null;}
 setAttribute(key,value){this.attrs[key]=value;}
}
function harness(){
 const document=new EventTarget();document.visibilityState='visible';
 const window=new EventTarget(),observers=[],timers=new Map(),store=new Map(),calls=[],subscriptions=new Set();
 let nextTimer=0,failRead=false,failWrite=false,holdWrite=false,resolveWrite;
 class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){this.stopped=true;}}
 const api=new Function('window','MutationObserver','setTimeout','clearTimeout',source+'\nreturn hiStabilityPresentation;')(window,Observer,(fn)=>{timers.set(++nextTimer,fn);return nextTimer;},id=>timers.delete(id));
 const connection=new EventTarget();connection.connected=true;
 connection.subscribeMessage=async(callback,request)=>{
  assert.equal(request.type,'frontend/subscribe_user_data');
  if(failRead)throw Error('read failed');
  const sub={callback,key:request.key};subscriptions.add(sub);callback({value:store.get(request.key)??null});
  return ()=>subscriptions.delete(sub);
 };
 const emit=(key,value)=>{store.set(key,value);for(const sub of subscriptions)if(sub.key===key)sub.callback({value});};
 const hass={connection,user:{id:'fixture-user'},callWS:async request=>{
  calls.push(request);
  if(request.type==='frontend/get_user_data'){if(failRead)throw Error('read failed');return {value:store.get(request.key)??null};}
  assert.equal(request.type,'frontend/set_user_data');assert.equal(typeof request.value,'boolean');
  if(holdWrite)await new Promise(resolve=>{resolveWrite=resolve;});
  store.set(request.key,request.value);
  if(failWrite)throw Error('disk write failed after in-memory update');
  emit(request.key,request.value);
 }};
 const owners=[];
 const mount=(entry=ENTRY,layout='v2_mobile',userHass=hass)=>{
  const owner=new Element(),label=new Element(),center=new Element(),overlay=new Element(),card=new Element();
  owner.getRootNode=()=>({});owner.ownerDocument=document;
  owner.shadowRoot={host:owner,querySelector:selector=>({'.hi-stability-display-label':label,'.hi-stability-presentation-center':center,'.hi-stability-presentation-overlay':overlay,'#card':card}[selector]||null)};
  const stamp={schema:1,generator:1,entry,layout};
  const binding=api.bind(owner,userHass,stamp,{schema:1,entry});owners.push(owner);
  return {owner,label,center,overlay,card,binding,stamp};
 };
 return {api,window,document,observers,timers,store,calls,subscriptions,connection,hass,mount,emit,
  key:entry=>`humidity_intelligence.stability_badge.disabled.v1.${entry}`,
  cleanup(){for(const owner of owners)owner[OWNER]?.dispose();},
  setFailRead(value){failRead=value;},setFailWrite(value){failWrite=value;},
  deferWrite(){holdWrite=true;},releaseWrite(){holdWrite=false;resolveWrite();}};
}

test('fresh default and both hold directions use only the scoped presentation preference',async()=>{
 const h=harness(),badge=h.mount();await flush();
 assert.equal(badge.owner.attrs['data-hi-stability-presentation'],'enabled');
 assert.equal(h.calls.length,0);
 await badge.binding.toggle();assert.equal(badge.center.textContent,'Disabled');
 assert.equal(badge.owner.attrs['data-hi-stability-presentation'],'disabled');
 await badge.binding.toggle();assert.equal(badge.owner.attrs['data-hi-stability-presentation'],'enabled');
 assert.deepEqual(h.calls.map(x=>[x.type,x.key,x.value]),[
  ['frontend/set_user_data',h.key(ENTRY),true],['frontend/set_user_data',h.key(ENTRY),false]]);
 h.cleanup();assert.equal(h.subscriptions.size,0);assert.equal(h.timers.size,0);
});
test('saved disable restores after remount and stays shared across Mobile and Tablet',async()=>{
 const h=harness(),mobile=h.mount();await flush();await mobile.binding.toggle();
 const tablet=h.mount(ENTRY,'v2_tablet');await flush();
 assert.equal(h.subscriptions.size,1);assert.equal(tablet.center.textContent,'Disabled');
 mobile.binding.dispose();tablet.binding.dispose();
 const refreshed=h.mount();assert.equal(refreshed.owner.attrs['data-hi-stability-presentation'],'loading');
 await flush();assert.equal(refreshed.center.textContent,'Disabled');
 await refreshed.binding.toggle();assert.equal(h.store.get(h.key(ENTRY)),false);h.cleanup();
});
test('remote changes and distinct entries never overwrite one another',async()=>{
 const h=harness(),one=h.mount(),two=h.mount(OTHER);await flush();
 h.emit(h.key(ENTRY),true);assert.equal(one.center.textContent,'Disabled');
 assert.equal(two.owner.attrs['data-hi-stability-presentation'],'enabled');
 await two.binding.toggle();assert.equal(one.center.textContent,'Disabled');
 assert.equal(h.store.get(h.key(ENTRY)),true);h.cleanup();
});
test('unknown or malformed stored values never claim a saved enabled preference',async()=>{
 for(const value of ['true',1,{},[]]){
  const h=harness();h.store.set(h.key(ENTRY),value);const b=h.mount();await flush();
  assert.equal(b.owner.attrs['data-hi-stability-presentation'],'unavailable');
  await b.binding.toggle();assert.equal(h.calls.filter(x=>x.type==='frontend/set_user_data').length,0);h.cleanup();
 }
});
test('failed reads and writes remain explicit, preserve the confirmed view, and can retry',async()=>{
 const h=harness();h.setFailRead(true);const b=h.mount();await flush();
 assert.equal(b.label.textContent,'Display preference unavailable');await b.binding.toggle();
 assert.equal(h.calls.filter(x=>x.type==='frontend/set_user_data').length,0);
 h.setFailRead(false);await b.binding.toggle();await flush();assert.equal(b.center.textContent,'Disabled');
 assert.equal(h.subscriptions.size,1,'recovered preference keeps subscription updates');
 h.setFailWrite(true);await b.binding.toggle();
 assert.equal(b.owner.attrs['data-hi-stability-presentation'],'disabled');assert.equal(b.label.textContent,'Save unconfirmed');
 assert.match(b.card.attrs.title,/Could not confirm/);
 h.setFailWrite(false);await b.binding.toggle();assert.equal(b.owner.attrs['data-hi-stability-presentation'],'enabled');h.cleanup();
});
test('one pending hold is shared across layouts and late results respect newer subscription truth',async()=>{
 const h=harness(),one=h.mount(),two=h.mount(ENTRY,'v2_tablet');await flush();h.deferWrite();
 const first=one.binding.toggle();await flush();await two.binding.toggle();
 assert.equal(h.calls.length,1);assert.equal(one.label.textContent,'Saving display…');
 h.releaseWrite();await first;assert.equal(two.center.textContent,'Disabled');h.cleanup();
});
test('disconnect blocks writes; reconnect reconciles via subscription without doubling listeners',async()=>{
 const h=harness(),b=h.mount();await flush();await b.binding.toggle();const count=h.calls.length;
 h.connection.connected=false;h.connection.dispatchEvent(new Event('disconnected'));await b.binding.toggle();
 assert.equal(h.calls.length,count);assert.equal(b.center.textContent,'Disabled');
 h.connection.connected=true;h.connection.dispatchEvent(new Event('ready'));h.emit(h.key(ENTRY),false);
 assert.equal(b.owner.attrs['data-hi-stability-presentation'],'enabled');assert.equal(h.subscriptions.size,1);h.cleanup();
});
test('owner removal and late subscription results release custody',async()=>{
 const h=harness(),b=h.mount();b.owner.isConnected=false;h.observers[0].callback();await flush();
 assert.equal(h.subscriptions.size,0);assert.equal(h.timers.size,0);assert.equal(b.owner[OWNER],undefined);
 h.cleanup();
});
test('connected same-view navigation and cached-page restore preserve the hold action',async()=>{
 const h=harness(),b=h.mount();await flush();await b.binding.toggle();
 b.center.textContent='65';b.label.textContent='UNSTABLE';h.observers[0].callback();
 assert.equal(b.center.textContent,'Disabled');assert.equal(b.label.textContent,'Display off');
 h.window.dispatchEvent(new Event('location-changed'));assert.equal(h.subscriptions.size,1);
 h.window.dispatchEvent(new Event('popstate'));await b.owner[OWNER].toggle();
 assert.equal(b.owner.attrs['data-hi-stability-presentation'],'enabled');
 const cached=new Event('pagehide');Object.defineProperty(cached,'persisted',{value:true});h.window.dispatchEvent(cached);
 await b.owner[OWNER].toggle();assert.equal(b.center.textContent,'Disabled');
 h.window.dispatchEvent(new Event('pagehide'));assert.equal(h.subscriptions.size,0);h.cleanup();
});
test('identity mismatch blocks writes; connection/user replacement releases old ownership',async()=>{
 const h=harness(),b=h.mount();await flush();
 h.api.bind(b.owner,h.hass,b.stamp,{schema:1,entry:OTHER});await b.owner[OWNER].toggle();
 assert.equal(h.calls.length,0);assert.equal(h.subscriptions.size,0);
 h.api.bind(b.owner,{...h.hass,user:{id:'second-user'}},b.stamp,{schema:1,entry:ENTRY});await flush();
 assert.equal(b.owner[OWNER].user,'second-user');assert.equal(h.subscriptions.size,1);h.cleanup();
});


test('an explicit hold cannot start a preference write after its owner departs during async preparation',async()=>{
 const h=harness(),one=h.mount(),two=h.mount(ENTRY,'v2_tablet');await flush();
 const pending=one.binding.toggle();one.owner.isConnected=false;one.binding.dispose();await pending;
 assert.equal(h.calls.filter(x=>x.type==='frontend/set_user_data').length,0);
 assert.equal(h.subscriptions.size,1,'another mounted layout keeps its own subscription');
 await two.binding.toggle();assert.equal(two.center.textContent,'Disabled');h.cleanup();
});
test('reconnect automatically retries an initially failed preference subscription',async()=>{
 const h=harness();h.setFailRead(true);const b=h.mount();await flush();
 assert.equal(b.owner.attrs['data-hi-stability-presentation'],'unavailable');
 h.setFailRead(false);h.store.set(h.key(ENTRY),true);h.connection.dispatchEvent(new Event('ready'));await flush();
 assert.equal(b.center.textContent,'Disabled');assert.equal(h.subscriptions.size,1);assert.equal(h.calls.length,0);h.cleanup();
});

test('existing badge keyboard activation remains tap after a hold without adding a control',async()=>{
 const h=harness(),b=h.mount();await flush();await b.binding.toggle();
 assert.equal(b.card.attrs.tabindex,'0');assert.equal(b.card.attrs.role,'button');
 const actions=[];b.card.addEventListener('action',event=>actions.push(event.detail.action));
 const key=new Event('keydown',{cancelable:true});Object.defineProperty(key,'key',{value:'Enter'});
 b.card.dispatchEvent(key);assert.deepEqual(actions,['tap']);assert.equal(key.defaultPrevented,true);
 assert.equal(b.owner.attrs['data-hi-stability-presentation'],'disabled');assert.equal(h.calls.length,1);
 b.binding.dispose();b.card.dispatchEvent(key);assert.deepEqual(actions,['tap']);h.cleanup();
});

test('short Space opens details; held Space changes only presentation once; blur cancels',async()=>{
 const h=harness(),b=h.mount();await flush();const actions=[];
 b.card.addEventListener('action',event=>actions.push(event.detail.action));
 const key=type=>{const e=new Event(type,{cancelable:true});Object.defineProperty(e,'key',{value:' '});return e;};
 b.card.dispatchEvent(key('keydown'));b.card.dispatchEvent(key('keyup'));
 assert.deepEqual(actions,['tap']);assert.equal(h.calls.length,0);
 for(const expected of ['disabled','enabled']){
  b.card.dispatchEvent(key('keydown'));
  for(const [id,callback] of [...h.timers]){h.timers.delete(id);callback();}
  await flush();b.card.dispatchEvent(key('keyup'));
  assert.equal(b.owner.attrs['data-hi-stability-presentation'],expected);
 }
 assert.equal(h.calls.length,2);assert.deepEqual(actions,['tap']);
 b.card.dispatchEvent(key('keydown'));b.card.dispatchEvent(new Event('blur'));
 assert.equal(h.timers.size,0);b.card.dispatchEvent(key('keyup'));assert.deepEqual(actions,['tap']);
 h.cleanup();
});

test('window blur and hidden document cancel pending Space hold without a write',async()=>{
 for(const kind of ['window-blur','hidden']){
  const h=harness(),b=h.mount();await flush();
  const event=new Event('keydown',{cancelable:true});Object.defineProperty(event,'key',{value:' '});b.card.dispatchEvent(event);
  if(kind==='window-blur')h.window.dispatchEvent(new Event('blur'));
  else{h.document.visibilityState='hidden';h.document.dispatchEvent(new Event('visibilitychange'));}
  assert.equal(h.timers.size,0);assert.equal(h.calls.length,0);h.cleanup();
 }
});
