import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Unit DOM only: models ownership, events and stable nodes. Does not measure CSS,
// native browser dialogs, actual HA nested controls or physical touch behavior.
const source=fs.readFileSync(new URL('../custom_components/humidity_intelligence/adaptive_output/hi-adaptive-output-card.js',import.meta.url),'utf8');
function harness({modalFailure=false,deferHelpers=false}={}){
 let root,resolveHelpers,mounts=0,seenConfigs=[];const registry=new Map();
 class N {
  constructor(tag='host'){this.tagName=tag;this.children=[];this.parentNode=null;this.dataset={};this.attributes={};this.listeners={};this.hidden=false;this.open=false;this.className='';this._text='';}
  get isConnected(){return this===root||!!this.parentNode?.isConnected;}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  set textContent(v){this._text=String(v);this.children.forEach(c=>c.parentNode=null);this.children=[];}
  append(...nodes){for(const n of nodes){n.remove();n.parentNode=this;this.children.push(n);}}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}
  replaceChildren(...nodes){this.children.forEach(c=>c.parentNode=null);this.children=[];this._text='';this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);}
  getAttribute(k){return this.attributes[k]??null;}
  addEventListener(t,f){(this.listeners[t]??=[]).push(f);}
  dispatchEvent(e){e.target??=this;for(const fn of this.listeners[e.type]||[])fn(e);if(e.bubbles&&this.parentNode)this.parentNode.dispatchEvent(e);return true;}
  contains(n){return this===n||this.children.some(c=>c.contains(n));}
  matches(s){if(s.startsWith('.'))return this.className.split(' ').includes(s.slice(1));if(s.startsWith('[data-focus-key')){const key=s.match(/="([^"]+)"/);return this.dataset.focusKey!==undefined&&(!key||this.dataset.focusKey===key[1]);}return this.tagName===s;}
  querySelectorAll(s){return this.children.flatMap(c=>[...(c.matches(s)?[c]:[]),...c.querySelectorAll(s)]);}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  focus(){let n=this;while(n){if(n.tagName==='shadow-root'){n.activeElement=this;break;}n=n.parentNode;}}
  scrollIntoView(){this.scrolled=true;}
  getBoundingClientRect(){return {left:0,top:0,right:100,bottom:100};}
  showModal(){if(modalFailure)throw Error('No modal');this.open=true;}
  close(){this.open=false;this.dispatchEvent({type:'close'});}
  attachShadow(){this.shadowRoot=new N('shadow-root');this.append(this.shadowRoot);return this.shadowRoot;}
 }
 root=new N('document');const document={createElement:t=>new N(t),createElementNS:(ns,t)=>{const n=new N(t);n.namespaceURI=ns;return n;}};
 const helpers={createCardElement(config){mounts++;seenConfigs.push(config);return new N('native-card');}};
 const window={customCards:[],loadCardHelpers:()=>deferHelpers?new Promise(r=>resolveHelpers=r):Promise.resolve(helpers)};
 vm.runInNewContext(source,{HTMLElement:N,document,window,customElements:{get:t=>registry.get(t),define:(t,c)=>registry.set(t,c)},CustomEvent:class {constructor(type,opts){this.type=type;Object.assign(this,opts);}},console});
 const C=registry.get('hi-adaptive-output-card'),card=new C();root.append(card);
 const config={entity:'sensor.example_status',control_context:{type:'entities',show_header_toggle:false,card_mod:{style:'test'},entities:[{entity:'fan.example',name:'Native fan',tap_action:{action:'more-info'}},{entity:'switch.example_isolation'},{entity:'sensor.example_support'}]}};
 card.setConfig(config);
 const update=p=>card.hass={connected:true,states:{'sensor.example_status':{state:'ready',attributes:{payload:p}}}};
 return {card,C,root,N,update,config,mounts:()=>mounts,seenConfigs,finishHelpers:()=>resolveHelpers(helpers)};
}
function payload(count=0){
 const attention=Array.from({length:count},(_,i)=>({label:`Output ${i}`,title:`Condition ${i}`,action:`Action ${i}`,evidence:`Evidence ${i}`,source:`binary_sensor.source_${i}`,tone:'warning'}));
 return {schema_version:2,synthetic:false,summary:'No mapped issues reported',attention_label:'Attention required',counts:{configured:10,affected:count},coverage:{label:'Monitoring 2/10 mapped',detail:'Only mapped conditions covered'},chips:[{kind:'fleet',label:'1/10 on',icon:'devices'}],attention,records:[{entity_id:'fan.example',label:'Example fan',roles:['ventilation_zone_1'],operation:{label:'On'},context:'Observed state is not command success',device_icon:'fan'}],discovery:{summary:'Sources',detail:'Source details',sources:[],gaps:[],notices:[]},compact:{schema_version:1,title:count?`${count} conditions · ${count} outputs affected`:'Monitoring incomplete',tone:'warning',condition_count:count,affected_output_count:count,shown_condition_count:Math.min(2,count),remaining_condition_count:Math.max(0,count-2),remainder_label:count>2?`Showing 2 of ${count} conditions · ${count-2} more`:'',monitoring_lines:['2/10 outputs mapped','3 meanings need confirmation'],context_lines:['Partial isolation reported']}};
}
const tick=()=>new Promise(r=>setImmediate(r));
test('summary prefix/totals/context, HVAC and one footer; complete details retained',async()=>{
 const h=harness();await tick();h.update(payload(7));const c=h.card;
 assert.equal(c._body.querySelectorAll('.compact-report').length,2);assert.match(c._body.querySelector('.reason').getAttribute('aria-label'),/Condition 0/);assert.match(c._body.textContent,/5 more/);assert.match(c._chips.textContent,/7 conditions · 7 outputs affected/);assert.equal(c._chips.children.length,2);assert.match(c._body.textContent,/Partial isolation/);assert.equal(c._body.querySelectorAll('.footer').length,1);assert.equal(c._body.querySelectorAll('.row').length,0);assert.equal(c._evidence.querySelectorAll('.attention').length,7);
 assert.equal(c._header.querySelector('ha-icon').getAttribute('icon'),'mdi:hvac');assert.equal(c._chips.querySelector('ha-icon').getAttribute('icon'),'mdi:hvac');
 assert.match(source,/width:25px;height:25px/);assert.match(source,/width:18px;height:18px/);
});
test('native config/node survives dialog toggles, payload and feed loss',async()=>{
 const h=harness();await tick();h.update(payload());const c=h.card,n=c._nativeCard;c._open=true;c._expanded();c._openDetails('controls','outputs-controls');n.focus();h.update(payload(3));assert.equal(c._nativeCard,n);assert.equal(h.mounts(),1);assert.equal(h.seenConfigs[0],h.config.control_context);assert.equal(c.shadowRoot.activeElement,n);
 c.hass={connected:false,states:{}};assert.equal(c._nativeCard,n);assert.match(c._body.textContent,/Monitoring unavailable/);assert.equal(c._evidence.querySelectorAll('.attention').length,0);assert.equal(c._body.querySelector('.footer').textContent,'Outputs & controls');assert.equal(c._dialog.open,true);
 c._closeDetails();c._openDetails('controls','outputs-controls');assert.equal(h.mounts(),1);h.update(payload());assert.equal(h.mounts(),1);
});
test('single event handoff closes custom modal before HA receiver; no controls interception',async()=>{
 const h=harness();await tick();h.update(payload());const c=h.card;c._open=true;c._expanded();c._openDetails('controls','outputs-controls');let calls=0;h.root.addEventListener('hass-more-info',()=>{calls++;assert.equal(c._dialog.open,false);assert.equal(c.shadowRoot.activeElement,c._body.querySelector('.footer'));});
 c._nativeCard.dispatchEvent({type:'hass-more-info',bubbles:true,composed:true,detail:{entityId:'fan.example'}});assert.equal(calls,1);
 c._openDetails('controls','outputs-controls');c._nativeCard.dispatchEvent({type:'change',bubbles:true});assert.equal(c._dialog.open,true);
});
test('showModal failure retains exact native node inline; collapse/owner removal clean up',async()=>{
 const h=harness({modalFailure:true});await tick();h.update(payload());const c=h.card,n=c._nativeCard;c._open=true;c._expanded();c._openDetails('controls','outputs-controls');assert.equal(c._inline,true);assert.equal(c._fallback.hidden,false);assert.equal(c._nativeCard,n);assert(c._fallback.contains(n));c._open=false;c._expanded();assert.equal(c._fallback.hidden,true);assert.equal(c._nativeCard,n);assert(c._dialog.contains(n));c._open=true;c._expanded();c._openDetails('controls','outputs-controls');c.remove();c.disconnectedCallback();assert.equal(c._inline,false);
});
test('missing/malformed compact retains truthful legacy context, literal text',async()=>{
 const h=harness();await tick();const p=payload(3);delete p.compact;p.context_notice='Control context unknown';p.runtime_context=[{label:'Manual ownership',state:'on',detail:'Manual'}];p.records[0].configured_roles=[{label:'ventilation zone 1 · disabled'}];p.records[0].context='<img src=x>';h.update(p);assert.match(h.card._body.textContent,/Control context unknown/);assert.match(h.card._body.textContent,/Manual ownership · on/);assert.match(h.card._body.textContent,/ventilation zone 1 · disabled/);assert.match(h.card._body.textContent,/<img src=x>/);assert.equal(h.card._body.querySelectorAll('img').length,0);assert.match(h.card._body.textContent,/Showing 2 of 3 reports/);p.compact={schema_version:99};h.update(p);assert.match(h.card._body.textContent,/Monitoring 2\/10/);
});
test('pending native mount cannot attach after owner removal',async()=>{
 const h=harness({deferHelpers:true});h.card.remove();h.card.disconnectedCallback();h.finishHelpers();await tick();assert.equal(h.mounts(),0);assert.equal(h.card._nativeCard,null);
});
test('independent instances and deleted evidence focus recovery',async()=>{
 const h=harness();await tick();h.update(payload(2));const c=h.card,second=new h.C();h.root.append(second);c._open=true;c._expanded();assert.equal(second._open,false);c._openDetails('evidence','output-reason');c._evidence.querySelector('.inspect').focus();h.update(payload(0));assert.equal(c.shadowRoot.activeElement,c._dialogClose);c._closeDetails();assert.equal(c.shadowRoot.activeElement,c._body.querySelector('.reason'));
});

test('legacy overflow and monitoring entry remain truthful',async()=>{
 const h=harness();await tick();const p=payload(7);delete p.compact;p.chips.push({label:'First report'},{label:'+6 more outputs'});p.discovery.lost_notice='1 source lost';h.update(p);const c=h.card;assert.equal(c._chips.children.length,3);assert.match(c._chips.textContent,/6 more/);assert.match(c._sources.textContent,/1 source lost/);assert.match(c._sources.textContent,/Monitoring 2\/10/);
 h.update(payload(0));assert.match(c._body.querySelector('.reason').className,/quiet/);c._body.querySelector('.reason').onclick();assert.equal(c.shadowRoot.activeElement,c._sources);
});
