window.customCards=[];window.litHtmlVersions=[];
customElements.define('ha-card',class extends HTMLElement{});
customElements.define('ha-icon',class extends HTMLElement{set icon(v){this.setAttribute('icon',v);this.textContent='◇';}});
let hass,freshSequence=0;const all=[];const events={services:[],history:[],moreInfo:[],touch:[],actions:[],errors:[]};
window.addEventListener('error',e=>events.errors.push(e.message));
window.addEventListener('unhandledrejection',e=>events.errors.push(String(e.reason)));
for(const type of ['touchstart','touchend','touchcancel','click'])window.addEventListener(type,e=>events.touch.push({type,trusted:e.isTrusted,touches:e.touches?.length||0}),true);
class Container extends HTMLElement {
 setConfig(config){this.config=config;const root=this.attachShadow({mode:'open'});const style=document.createElement('style');
 style.textContent=':host{display:block;min-width:0}:host([hidden]){display:none}#children{display:flex;flex-direction:column;gap:8px;min-width:0}#children>*{min-width:0}';root.append(style);
 const shell=document.createElement('ha-card'),children=document.createElement('div');children.id='children';shell.append(children);root.append(shell);
 if(config.type==='horizontal-stack'){children.style.flexDirection='row';}
 if(config.type==='grid'){children.style.display='grid';children.style.gridTemplateColumns=`repeat(${config.columns||3},minmax(0,1fr))`;}
 if(config.card_mod?.style){const mod=document.createElement('style');mod.textContent=config.card_mod.style;root.append(mod);}
 for(const child of config.cards||[config.card].filter(Boolean)){const el=create(child);if(config.type==='horizontal-stack')el.style.flex='1 1 0';children.append(el);}
 }
 set hass(value){this._hass=value;if(this.config.type==='conditional')this.hidden=!(this.config.conditions||[]).every(c=>c.state===undefined||value.states[c.entity]?.state===c.state);}
}
customElements.define('fixture-container',Container);
class Entities extends HTMLElement {
 setConfig(config){this.config=config;const root=this.attachShadow({mode:'open'});root.innerHTML='<style>:host{display:block}button{display:block;min-height:44px;background:#18253a;color:white;border:1px solid #475569;width:100%;text-align:left;padding:8px}</style>';
 for(const row of config.entities||[]){const id=typeof row==='string'?row:row.entity;if(!id)continue;const b=document.createElement('button');b.textContent=row.name||id;b.onclick=()=>this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true}));root.append(b);}}
 set hass(value){this._hass=value;}
}
customElements.define('fixture-entities',Entities);
function create(config){let el;if(config.type==='custom:button-card'){el=document.createElement('button-card');el.dataset.hiName=config.custom_fields?.gauge?'Stability Score':config.name||'UI revision';}
 else if(config.type==='custom:hi-adaptive-output-card'){el=document.createElement('hi-adaptive-output-card');el.dataset.hiName='Adaptive Outputs';}
 else if(config.type==='entities')el=document.createElement('fixture-entities');
 else if(['custom:mod-card','vertical-stack','horizontal-stack','grid','conditional'].includes(config.type))el=document.createElement('fixture-container');
 else throw Error('Unsupported full-layout card '+config.type);
 el.setConfig(config);all.push(el);if(hass)el.hass=hass;return el;}
// HA normally consumes hass-action. This explicit native-shell substitute routes
// only the configured actions used here; it never calls a network or HA service.
window.addEventListener('hass-action',event=>{
 const {config,action}=event.detail;const choice=config[action+'_action']||{};
 events.actions.push({action,entity:config.entity,kind:choice.action});
 if(choice.action==='fire-dom-event')event.target.dispatchEvent(new CustomEvent('ll-custom',{detail:choice,bubbles:true,composed:true}));
 else if(choice.action==='more-info')event.target.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:choice.entity||config.entity},bubbles:true,composed:true}));
 else if(choice.action==='toggle')hass.callService('homeassistant','toggle',{entity_id:config.entity});
 else if(choice.action==='call-service'||choice.action==='perform-action'){const [domain,service]=(choice.service||choice.perform_action).split('.');hass.callService(domain,service,choice.service_data||choice.data||{});}
 else if(choice.action&&choice.action!=='none')throw Error('Unsupported HA-shell action '+choice.action);
});
window.loadCardHelpers=async()=>({createCardElement:create});
await import('/button-card.js');await import('/adaptive.js');
const input=await (await fetch('/config.json')).json();const connection=new EventTarget();connection.connected=true;
const states={};for(const id of Object.values(input.mapping)){if(id)states[id]={entity_id:id,state:id.startsWith('sensor.')?'46':'off',attributes:{friendly_name:'Example reading'},last_changed:new Date().toISOString(),last_updated:new Date(Date.now()+(++freshSequence)).toISOString()};}
function seed(key,state,attributes={}){const id=input.mapping[key]||key;states[id]={entity_id:id,state,attributes:{friendly_name:'Example '+key.split('.')[1],...attributes},last_changed:new Date().toISOString(),last_updated:new Date(Date.now()+(++freshSequence)).toISOString()};}
for(const key of ['input_boolean.air_control_enabled'])seed(key,'on');
seed('sensor.air_control_mode','normal',{display:'Normal'});seed('sensor.air_control_reason','Normal environmental control',{full_reason:'Synthetic normal control; no household connection.'});
seed('sensor.house_humidity_state','in_target');seed('sensor.house_humidity_target_low','40');seed('sensor.house_humidity_target_high','60');seed('sensor.house_humidity_target_season','summer');
for(const risk of ['condensation','mould']){seed('sensor.worst_room_'+risk,'Example room',{risk:'low'});seed('sensor.worst_room_'+risk+'_risk','low');}
seed('sensor.house_humidity_drift_7d','0.4',{available_samples:432,required_samples:303});
const diag=input.mapping['sensor.hi_diagnostics'];seed('sensor.hi_diagnostics','ok',{ui_revision:input.metadata,diagnostics_summary:{stability_score:{availability:'collecting',window:{valid_samples:12},message:'Synthetic baseline collection'}}});
const payload={schema_version:2,synthetic:false,summary:'Synthetic monitoring only',attention_label:'Attention required',counts:{configured:1,affected:1},coverage:{label:'Monitoring 1/1 mapped',detail:'Synthetic fixture'},chips:[{kind:'fleet',label:'1/1 on',icon:'devices'}],attention:[{label:'Example output',title:'Filter condition',action:'Follow the device instructions. Your guidance: Inspect the intake.',evidence:'Synthetic diagnostic active',source:'binary_sensor.fixture_source',tone:'warning'}],records:[{entity_id:'fan.fixture_output',label:'Example output',roles:['ventilation_zone_1'],operation:{label:'On'},context:'Synthetic observed state',device_icon:'fan'}],discovery:{summary:'Sources',detail:'Synthetic source details',sources:[{source:'binary_sensor.fixture_source',label:'Example diagnostic',title:'Filter notice',tone:'warning',state:'on',association_label:'Configured meaning',reason:'Confirmed custom meaning',scope_label:'Example output',associations:[{label:'Example output',title:'Filter notice',scope_label:'Example output',meaning_label:'Custom meaning: Intake check · Classification: Filter replacement',rule_summary:'Binary state interpretation',rule_lines:['Attention when: on','Clear when: off'],reason:'Configured guidance: Inspect the intake.'}]}],gaps:[],notices:[]},compact:{schema_version:1,title:'1 condition · 1 output affected',tone:'warning',condition_count:1,affected_output_count:1,shown_condition_count:1,remaining_condition_count:0,remainder_label:'',monitoring_lines:['1/1 output mapped'],context_lines:[]}};
states['sensor.fixture_output_status']={entity_id:'sensor.fixture_output_status',state:'ready',attributes:{payload}};
hass={connection,connected:true,states,config:{unit_system:{temperature:'°C'}},themes:{darkMode:true,themes:{}},locale:{language:'en',number_format:'language'},language:'en',localize:key=>key,user:{name:'Synthetic fixture'},formatEntityState:e=>e.state,formatEntityAttributeValue:()=>'',
 callService:async(domain,service,data)=>{events.services.push({domain,service,data});if(service==='toggle'&&hass.states[data.entity_id]){const id=data.entity_id;hass={...hass,states:{...hass.states,[id]:{...hass.states[id],state:hass.states[id].state==='on'?'off':'on'}}};publish();}},
 callWS:async request=>{events.history.push(request);if(request.type!=='history/history_during_period')throw Error('Unexpected fixture WS request');return Object.fromEntries(request.entity_ids.map(id=>[id,[{entity_id:id,state:states[id]?.state||'unknown',attributes:{},last_changed:new Date(Date.now()-3600000).toISOString(),last_updated:new Date(Date.now()-3600000).toISOString()}]]));}};
function publish(fresh=true){if(fresh)hass={...hass,connected:connection.connected,states:{...hass.states,[diag]:{...structuredClone(hass.states[diag]),last_updated:new Date(Date.now()+(++freshSequence)).toISOString()}}};for(const el of all)el.hass=hass;}
window.addEventListener('hass-more-info',event=>{events.moreInfo.push(event.detail);const d=document.createElement('dialog');d.dataset.nativeStub='true';d.innerHTML='<p>Native HA more-info stub</p><button>Close</button>';d.querySelector('button').onclick=()=>{d.close();d.remove();};document.body.append(d);d.showModal();});
const layout=new URLSearchParams(location.search).get('layout')||'v2_mobile';document.querySelector('#fixture').append(create(input.layouts[layout]));publish();
window.fixture={events,layout,publish,all,mapping:input.mapping,
 setState(key,state){const id=input.mapping[key]||key;hass={...hass,states:{...hass.states,[id]:{...hass.states[id],state}}};publish();},
 disconnect(){connection.connected=false;connection.dispatchEvent(new Event('disconnected'));publish(false);},
 ready(){connection.connected=true;connection.dispatchEvent(new Event('ready'));publish(false);},
 fresh(){publish();},remove(){document.querySelector('#fixture').replaceChildren();},
 duplicate(){document.querySelector('#fixture').append(create(input.layouts[layout]));publish();},
 repaintOutputs(){const id='sensor.fixture_output_status';const old=hass.states[id];hass={...hass,states:{...hass.states,[id]:{...old,attributes:{payload:{...old.attributes.payload,summary:old.attributes.payload.summary+'.'}}}}};publish();},
 reset(){for(const key of Object.keys(events))events[key].length=0;},get hass(){return hass;}};
document.documentElement.dataset.ready='true';
