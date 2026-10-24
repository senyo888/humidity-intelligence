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
 emit(name,event){for(const fn of [...(this.listeners.get(name)||[])])fn(event);}
 count(){return [...this.listeners.values()].reduce((sum,set)=>sum+set.size,0);}
}
function harness(){
 const window=new Events();const observers=[],dialogs=[],moreInfo=[];
 class Observer{constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){this.stopped=true;}}
 const document={activeElement:null,body:{appendChild(d){d.isConnected=true;}},createElement(){
  const d=new Events();d.closeButton=new Events();d.updateButton=new Events();d.actionStatus={textContent:''};d.setAttribute=()=>{};
  d.querySelector=selector=>selector==='button'?d.closeButton:selector==='[data-view-update]'?d.updateButton:d.actionStatus;
  d.showModal=()=>{d.open=true;};d.close=()=>{d.open=false;d.emit('close');};d.remove=()=>{d.isConnected=false;};
  d.getBoundingClientRect=()=>({left:0,right:100,top:0,bottom:100});dialogs.push(d);return d;
 }};
 class CustomEvent{constructor(type,options){this.type=type;Object.assign(this,options);}}
 const model=new Function('window','MutationObserver','document','CustomEvent',source+'\nreturn hiUiRevision;')(window,Observer,document,CustomEvent);
 const button=new Events();button.isConnected=true;button.focus=()=>{};button.dataset={};button.label={textContent:''};button.updateLabel={textContent:''};button.attrs={};button.querySelector=s=>s==='.hi-ui-revision-label'?button.label:button.updateLabel;button.getAttribute=name=>button.attrs[name];button.setAttribute=(name,value)=>button.attrs[name]=value;
 const shadowRoot=new Events();shadowRoot.querySelector=()=>button;
 const owner={isConnected:true,shadowRoot,getRootNode:()=>shadowRoot,dispatchEvent:event=>moreInfo.push(event)};
 const connection=new Events();const entity={state:'ok',attributes:{ui_revision:metadata}};
 const hass={connection,states:{diagnostics:entity}};
 return {model,window,observers,owner,connection,entity,hass,button,dialogs,moreInfo};
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
test('reconnect accepts fresh Diagnostics through a persistent states proxy without accepting cached evidence',async()=>{
 const h=harness();const target={diagnostics:h.entity};const proxy=new Proxy(target,{});h.hass.states=proxy;
 h.model.render(h.owner,h.hass,h.entity,stamp);await Promise.resolve();assert.equal(h.button.dataset.status,'current');
 h.connection.connected=false;h.connection.emit('disconnected');assert.equal(h.button.dataset.status,'unknown');
 h.connection.connected=true;
 const fresh=structuredClone(h.entity);target.diagnostics=fresh;
 assert.match(h.model.render(h.owner,h.hass,fresh,stamp),/data-status="unknown"/,'fresh entity alone does not replace the ready gate');
 h.connection.emit('ready');assert.equal(h.button.dataset.status,'unknown','ready alone cannot certify the cached render');
 assert.match(h.model.render(h.owner,h.hass,h.entity,stamp),/data-status="unknown"/,'original cached entity stays blocked');
 for(const state of ['unknown','unavailable','', ' ']){
  const invalid={...fresh,state};target.diagnostics=invalid;
  assert.match(h.model.render(h.owner,h.hass,invalid,stamp),/data-status="unknown"/);
  assert.match(h.model.render(h.owner,h.hass,h.entity,stamp),/data-status="unknown"/,'invalid entity must not release the stale-evidence guard');
 }
 target.diagnostics=fresh;
 assert.equal(h.hass.states,proxy);
 assert.match(h.model.render(h.owner,h.hass,fresh,stamp),/data-status="current"/);
 await Promise.resolve();assert.equal(h.button.dataset.status,'current');
 h.connection.connected=false;h.connection.emit('disconnected');h.connection.connected=true;h.connection.emit('ready');
 assert.match(h.model.render(h.owner,h.hass,fresh,stamp),/data-status="unknown"/,'every reconnect requires another fresh entity');
 h.model.dispose(h.owner);assert.equal(h.connection.count(),0);assert.equal(h.button.count(),0);
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

test('footer isolates ancestor gestures without cancelling native defaults or opening on touch',async()=>{
 const h=harness();h.model.render(h.owner,h.hass,h.entity,stamp);await Promise.resolve();
 const state=h.owner[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];let opened=0;state.open=()=>opened++;
 const event=(type,key)=>({type,key,stopPropagation(){this.stopped=true;},preventDefault(){this.prevented=true;}});
 for(const type of ['touchstart','touchend','touchcancel','mousedown','mouseup']){
  const e=event(type);h.button.emit(type,e);assert.equal(e.stopped,true);assert.equal(e.prevented,undefined);assert.equal(opened,0);
 }
 for(const type of ['touchmove','scroll']){const e=event(type);h.button.emit(type,e);assert.equal(e.stopped,undefined);assert.equal(e.prevented,undefined);}
 const click=event('click');h.button.emit('click',click);assert.equal(opened,1);assert.equal(click.stopped,true);assert.equal(click.prevented,undefined);
 const enter=event('keyup','Enter');h.button.emit('keyup',enter);assert.equal(enter.stopped,true);assert.equal(opened,1);
 const tab=event('keyup','Tab');h.button.emit('keyup',tab);assert.equal(tab.stopped,undefined);
 h.model.dispose(h.owner);assert.equal(h.button.count(),0);
});

test('footer replacement detaches every guard and repeated paints do not duplicate activation',async()=>{
 const h=harness();h.model.render(h.owner,h.hass,h.entity,stamp);await Promise.resolve();
 const state=h.owner[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];let opened=0;state.open=()=>opened++;
 const replacement=harness().button;h.owner.shadowRoot.querySelector=()=>replacement;
 for(let i=0;i<5;i++)h.observers[0].callback();
 assert.equal(h.button.count(),0);assert.equal(replacement.listeners.get('click').size,1);
 for(const name of ['touchstart','touchend','touchcancel','mousedown','mouseup','keyup'])assert.equal(replacement.listeners.get(name).size,1);
 replacement.emit('click',{stopPropagation(){}});assert.equal(opened,1);
 h.model.dispose(h.owner);assert.equal(replacement.count(),0);assert.equal(h.owner.shadowRoot.count(),0);
});

const observedUpdate=(overrides={})=>({schema:1,provider:'hacs',repository:'senyo888/humidity-intelligence',
 status:'reported_update',reason:'provider_reported_update',entity_id:'update.example_hi',provider_state:'on',
 downloaded_version:'2.1.0',latest_version:'2.1.1',skipped_version:null,...overrides});
const providerState=observation=>({state:observation.provider_state,attributes:{installed_version:observation.downloaded_version,latest_version:observation.latest_version,skipped_version:observation.skipped_version,in_progress:false}});
function withUpdate(h,observation=observedUpdate()){
 h.entity.attributes.update_observation=observation;
 h.hass.states[observation.entity_id]=providerState(observation);
 h.model.render(h.owner,h.hass,h.entity,stamp);
 return h.owner[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];
}
test('software status reports provider evidence without comparing versions or changing UI truth',()=>{
 const cases=[
  [observedUpdate(),'reported_update','Update available'],
  [observedUpdate({status:'no_update_reported',provider_state:'off',latest_version:'2.1.0'}),'no_update_reported','No update reported'],
  [observedUpdate({status:'no_update_reported',provider_state:'off',downloaded_version:'2.1.1-beta.3',latest_version:'2.1.0'}),'no_update_reported','No update reported'],
  [observedUpdate({downloaded_version:'feature-branch',latest_version:'commit-reference'}),'reported_update','Update available'],
  [observedUpdate({status:'skipped',provider_state:'off',skipped_version:'2.1.1'}),'skipped','Update skipped'],
  [observedUpdate({status:'in_progress'}),'in_progress','HI update in progress'],
  [observedUpdate({status:'unverified'}),'unverified','Updates unverified'],
 ];
 for(const [observation,kind,label] of cases){
  assert.equal(ui.classifyUpdate(observation,true).kind,kind);assert.equal(ui.classifyUpdate(observation,true).label,label);
  for(const [revision,meta,uiKind] of [[1,metadata,'current'],[2,metadata,'different'],[1,{...metadata,layouts:{v2_mobile:{revision:2,generator:1,supersedes:[1]}}},'update'],[1,null,'unknown']]){
   const h=harness();h.entity.attributes.ui_revision=meta;h.entity.attributes.update_observation=observation;
   const markup=h.model.render(h.owner,h.hass,h.entity,{...stamp,revision});
   assert.ok(markup.includes(`data-status="${uiKind}"`));assert.ok(markup.includes(`data-update-status="${kind}"`));assert.ok(markup.includes(label));h.model.dispose(h.owner);
  }
 }
});
test('missing unsupported contradictory or malformed software evidence stays unverified',()=>{
 for(const observation of [null,{},[],observedUpdate({schema:2}),observedUpdate({provider:'other'}),observedUpdate({repository:'example/fork'}),observedUpdate({status:'current'}),observedUpdate({entity_id:'sensor.example'}),observedUpdate({entity_id:'update.example\n'}),observedUpdate({provider_state:'unknown'}),observedUpdate({status:'reported_update',provider_state:'off'}),observedUpdate({downloaded_version:'2.1.1'}),observedUpdate({skipped_version:'2.1.1'}),observedUpdate({status:'skipped',provider_state:'off'}),observedUpdate({status:'no_update_reported',provider_state:'off',skipped_version:'2.1.1'})]){
  assert.equal(ui.classifyUpdate(observation,true).kind,'unverified');
 }
 for(const value of [null,undefined,3,'',' unknown','unknown','unavailable','2.1\n','2.1\u0085','2.1\u202e','a'.repeat(129)])for(const field of ['downloaded_version','latest_version'])assert.equal(ui.classifyUpdate(observedUpdate({[field]:value}),true).kind,'unverified');
 assert.equal(ui.classifyUpdate(observedUpdate(),false).kind,'unverified');
 const installedSkipped=observedUpdate({status:'no_update_reported',provider_state:'off',downloaded_version:'2.1.1',skipped_version:'2.1.1'});
 assert.equal(ui.classifyUpdate(installedSkipped,true).kind,'no_update_reported');
});
test('software coverage remains visible and invalidates with disconnected Diagnostics',async()=>{
 const h=harness();withUpdate(h);await Promise.resolve();
 assert.equal(h.button.label.textContent,'UI current');assert.equal(h.button.updateLabel.textContent,'↑ Update available');
 assert.match(h.button.attrs['aria-label'],/UI current\. Update available/);
 h.connection.connected=false;h.connection.emit('disconnected');
 assert.equal(h.button.dataset.status,'unknown');assert.equal(h.button.dataset.updateStatus,'unverified');
 h.connection.connected=true;h.connection.emit('ready');assert.equal(h.button.dataset.updateStatus,'unverified');
 const fresh=structuredClone(h.entity);h.model.render(h.owner,h.hass,fresh,stamp);await Promise.resolve();assert.equal(h.button.dataset.updateStatus,'reported_update');
 delete fresh.attributes.update_observation;h.model.render(h.owner,h.hass,{...fresh},stamp);await Promise.resolve();
 assert.equal(h.button.label.textContent,'UI current');assert.equal(h.button.updateLabel.textContent,'Updates unverified');h.model.dispose(h.owner);
});
test('quiet no-update state retains accessible evidence and opens source-bound details',async()=>{
 const h=harness();
 const state=withUpdate(h,observedUpdate({status:'no_update_reported',provider_state:'off',latest_version:'2.1.0'}));
 await Promise.resolve();
 assert.equal(h.button.dataset.updateStatus,'no_update_reported');
 assert.equal(h.button.attrs['aria-label'],'UI current. No update reported. Open UI and software versions');
 h.hass.callService=()=>{throw Error('No services permitted');};state.open();const dialog=h.dialogs.at(-1);
 assert.match(dialog.innerHTML,/<h3>No update reported<\/h3>/);
 assert.match(dialog.innerHTML,/HACS reports no update/);
 assert.match(dialog.innerHTML,/does not prove that the latest code is running/);
 dialog.updateButton.emit('click');assert.equal(dialog.open,false);
 assert.equal(h.moreInfo.length,1);assert.equal(h.moreInfo[0].detail.entityId,'update.example_hi');
 h.model.dispose(h.owner);
});
test('details escape provider text and View update opens only the exact current source without services',()=>{
 const h=harness(),observation=observedUpdate({latest_version:'<img src=x onerror=alert(1)>'});const state=withUpdate(h,observation);
 h.hass.callService=()=>{throw Error('No services permitted');};state.open();const dialog=h.dialogs.at(-1);
 assert.match(dialog.innerHTML,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.ok(!dialog.innerHTML.includes('<img'));
 assert.match(dialog.innerHTML,/<h3>Update available<\/h3>/);
 assert.match(dialog.innerHTML,/HACS downloaded version/);assert.match(dialog.innerHTML,/running version are not verified/);
 dialog.updateButton.emit('click');assert.equal(dialog.open,false);assert.equal(h.moreInfo.length,1);
 assert.equal(h.moreInfo[0].type,'hass-more-info');assert.equal(h.moreInfo[0].detail.entityId,'update.example_hi');h.model.dispose(h.owner);
});
test('View update refuses changed provider data, missing entities and a retargeted dialog',()=>{
 for(const change of ['provider','missing','retarget','diagnostics','disconnect']){
  const h=harness(),state=withUpdate(h);state.open();const dialog=h.dialogs.at(-1);
  if(change==='provider')h.hass.states['update.example_hi'].attributes.latest_version='2.2.0';
  if(change==='missing')delete h.hass.states['update.example_hi'];
  if(change==='retarget'){const observation=observedUpdate({entity_id:'update.renamed_hi'});withUpdate(h,observation);}
  if(change==='diagnostics')h.entity.state='unavailable';
  if(change==='disconnect')h.connection.connected=false;
  dialog.updateButton.emit('click');assert.equal(h.moreInfo.length,0,change);assert.match(dialog.actionStatus.textContent,/changed or is unavailable/);h.model.dispose(h.owner);
 }
});
