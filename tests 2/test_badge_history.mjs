import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=fs.readFileSync(path.join(ROOT,'custom_components/humidity_intelligence/ui/badge_history.js'),'utf8');
const model=new Function(source+'\nreturn hiBadgeHistory;')();
const start=Date.UTC(2026,8,19), end=start+24*3600000;
const row=(seconds,state,attrs={})=>({lu:(start+seconds*1000)/1000,s:state,a:attrs});
test('strict numeric parsing preserves finite decimals, zero and negative values only',()=>{
 for(const value of ['0','-3.2','+2','.4','1e3','-1e-3'])assert.equal(model.numeric(value),Number(value));
 for(const value of [null,undefined,true,false,3,'',' ','bad','NaN','Infinity','1bad','0x10','1e999'])assert.equal(model.numeric(value),null,String(value));
});
test('compressed/full records use update time, preserve units and exclude boundary as transition',()=>{
 const raw=[row(0,'normal'),row(5,'cooking'),{state:'bathroom',last_updated:new Date(start+10000).toISOString(),last_changed:new Date(start).toISOString(),attributes:{unit_of_measurement:'reported'}}];
 const result=model.normalize(raw,start,end,'mode');assert.equal(result.records[0].boundary,true);assert.equal(result.records[2].time,start+10000);assert.equal(result.records[2].unit,'reported');
 assert.deepEqual(model.transitions(result.records).map(r=>r.state),['cooking','bathroom']);
});
test('historical reason attributes retain their own update timestamps with no live fallback',()=>{
 const result=model.normalize([{s:'summary',lu:(start+2000)/1000,lc:start/1000,a:{full_reason:'Historical reason'}}],start,end,'reason');
 assert.equal(result.records[0].time,start+2000);assert.equal(result.records[0].state,'Historical reason');
 assert.equal(model.normalize([row(1,'recorded short reason')],start,end,'reason').records[0].state,'recorded short reason');
});
test('unordered duplicates collapse only identical evidence; timestamp conflicts become visible gaps',()=>{
 const result=model.normalize([row(2,'4'),row(1,'3'),row(1,'3'),row(2,'5'),row(3,'6')],start,end,'numeric');
 assert.equal(result.records.length,3);assert.equal(result.records[1].conflict,true);assert.equal(result.records[1].number,null);
 assert.equal(model.seriesPaths(result.records,start,end).segments.length,2);
});
test('unavailable and changed historical units break numeric lines without fabricating outages',()=>{
 const records=model.normalize([row(1,'0',{unit_of_measurement:'a'}),row(60,'2',{unit_of_measurement:'a'}),row(61,'unavailable'),row(1000,'3',{unit_of_measurement:'a'}),row(1001,'4',{unit_of_measurement:'b'})],start,end,'numeric').records;
 const chart=model.seriesPaths(records,start,end);assert.equal(chart.segments.length,3);assert.equal(chart.points.length,4);assert.equal(chart.segments[0].length,2);
});
test('extreme but finite observations never yield nonfinite chart coordinates',()=>{
 for(const states of [['1e308','-1e308'],['1e308','1e308'],['0','0']]){
  const records=model.normalize(states.map((v,i)=>row(i+1,v)),start,end,'numeric').records;
  for(const p of model.seriesPaths(records,start,end).points){assert.ok(Number.isFinite(p.x));assert.ok(Number.isFinite(p.y));}
 }
});
test('unexpected categories never become OK or Normal, including inherited object keys',()=>{
 for(const kind of ['risk','mode'])for(const value of ['alien','constructor','__proto__','toString'])assert.match(model.category(value,kind).label,/Unrecognised/);
 assert.equal(model.category('Danger','risk').tone,'danger');assert.equal(model.category('co_emergency','mode').tone,'danger');
});
test('response size, display truncation and invalid timestamp evidence are explicit',()=>{
 assert.equal(model.normalize(undefined,start,end,'risk').status,'missing');assert.equal(model.normalize([],start,end,'risk').status,'empty');
 assert.equal(model.normalize(Array(10001).fill(row(1,'OK')),start,end,'risk').status,'oversize');
 const truncated=model.normalize(Array.from({length:600},(_,i)=>row(i,'OK')),start,end,'risk');assert.equal(truncated.omitted,100);assert.equal(truncated.records.length,500);assert.equal(truncated.records[0].time,start+100000);
 const invalid=model.normalize([{s:'OK',lu:'bad'},row(-1,'OK'),row(90000,'OK')],start,end,'risk');assert.equal(invalid.invalid,3);
});
// Minimal DOM controller harness. Actual native controls/SVG/layout are exercised
// separately in a browser using the same canonical/embedded source.
class Node extends EventTarget {
 constructor(tag,doc){super();this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.className='';this.hidden=false;this.parentNode=null;this.dataset={};this.attributes={};this.value='0';this.style={};this.classList={contains:value=>this.className.split(' ').includes(value)};}
 get isConnected(){return this.tagName==='BODY'||Boolean(this.parentNode?.isConnected);}
 appendChild(node){node.remove();this.children.push(node);node.parentNode=this;return node;}
 get firstChild(){return this.children[0]||null;}
 insertBefore(node,reference){node.remove();const at=this.children.indexOf(reference);this.children.splice(at<0?0:at,0,node);node.parentNode=this;return node;}
 replaceChildren(...nodes){for(const child of this.children)child.parentNode=null;this.children=[];nodes.forEach(n=>this.appendChild(n));this._html='';}
 remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}
 setAttribute(key,value){this.attributes[key]=String(value);}
 getAttribute(key){return this.attributes[key];}
 focus(){this.ownerDocument.activeElement=this;}
 set innerHTML(html){this.replaceChildren();this._html=html;this.selectors=new Map();
  const add=(selector,tag='button')=>{const node=new Node(tag,this.ownerDocument);this.selectors.set(selector,node);this.appendChild(node);return node;};
  if(html.includes('data-back')){add('nav','nav');add('[data-back]');add('[data-native]');const day=add('[data-hours="24"]');day.dataset.hours='24';const week=add('[data-hours="168"]');week.dataset.hours='168';const c=add('.hi-history-content','div');c.className='hi-history-content';}
  if(html.includes('<select')){add('select','select');add('output','output');}
 }
 get innerHTML(){return this._html||'';}
 querySelector(selector){return this.selectors?.get(selector)||this.children.find(node=>selector==='.'+node.className)||null;}
 querySelectorAll(selector){return selector==='[data-hours]'?[this.selectors.get('[data-hours="24"]'),this.selectors.get('[data-hours="168"]')]:[];}
}
function harness({timeoutMs=1000, entities=[{id:'sensor.entry_risk',label:'Highest reported risk',kind:'risk'},{id:'sensor.entry_source',label:'Reported source room',kind:'source'}], states, callWS, endTime=end}={}){
 const document={createElement(tag){return new Node(tag,document);}};const body=document.createElement('body');const dialog=body.appendChild(document.createElement('dialog'));
 const close=dialog.appendChild(document.createElement('button'));close.className='hi-summary-close';const title=dialog.appendChild(document.createElement('h2'));const button=dialog.appendChild(document.createElement('button'));button.className='hi-summary-history';
 const requests=[],pending=[];const owner={isConnected:true,hass:{config:{time_zone:'Europe/London'},locale:{language:'en-GB'},callWS:callWS||((request)=>{requests.push(request);return new Promise((resolve,reject)=>pending.push({resolve,reject}));})}};
 let native=0;let controller;
 controller=model.create({dialog,owner,entities,states:states||Object.fromEntries(entities.map(e=>[e.id,{state:'unknown'}])),now:()=>endTime,timeoutMs,close:()=>controller.dispose(),openEntity:()=>native++});
 const section=dialog.children.find(n=>n.className==='hi-history');
 return {controller,document,dialog,section,owner,requests,pending,content:section.querySelector('.hi-history-content'),button,title,native:()=>native};
}
const flush=()=>new Promise(resolve=>setTimeout(resolve,0));
test('no request before open; request is bounded explicit mapped ids with full historical attributes',async()=>{
 const h=harness();assert.equal(h.requests.length,0);h.controller.open();assert.equal(h.requests.length,1);const req=h.requests[0];assert.deepEqual(req.entity_ids,['sensor.entry_risk','sensor.entry_source']);assert.equal(req.start_time,new Date(start).toISOString());assert.equal(req.no_attributes,false);assert.equal(req.minimal_response,false);assert.equal(req.significant_changes_only,false);assert.equal(req.include_start_time_state,true);
 h.pending[0].resolve({'sensor.entry_risk':[row(0,'OK'),row(20,'Danger')],'sensor.entry_source':[row(0,'Room A')],'sensor.outside_entry':[row(10,'SECRET')]});await flush();
 const html=h.content.children.map(n=>n.innerHTML).join('');assert.match(html,/Danger/);assert.ok(!html.includes('SECRET'));h.controller.dispose();
});
test('Back and range switches discard stale results and preserve chosen range',async()=>{
 const h=harness();h.controller.open();h.section.querySelector('[data-hours="168"]').dispatchEvent(new Event('click'));assert.equal(h.requests.length,2);h.pending[0].resolve({'sensor.entry_risk':[row(20,'OLD')]});await flush();assert.match(h.content.innerHTML,/Loading/);
 h.section.querySelector('[data-back]').dispatchEvent(new Event('click'));assert.equal(h.section.hidden,true);assert.equal(h.title.hidden,false);assert.equal(h.document.activeElement,h.button);
 h.pending[1].resolve({'sensor.entry_risk':[row(20,'OLD2')]});await flush();assert.match(h.content.innerHTML,/Loading/);
 h.controller.open();assert.equal(Date.parse(h.requests[2].end_time)-Date.parse(h.requests[2].start_time),7*86400000);h.controller.dispose();
});
test('timeout, failures, close and owner removal never paint a late response',async()=>{
 const h=harness({timeoutMs:5});h.controller.open();await new Promise(r=>setTimeout(r,15));assert.match(h.content.innerHTML,/timed out/);h.pending[0].resolve({'sensor.entry_risk':[row(1,'LATE')]});await flush();assert.match(h.content.innerHTML,/timed out/);h.controller.dispose();
 const f=harness();f.controller.open();f.pending[0].reject(new Error('denied'));await flush();assert.match(f.content.innerHTML,/currently unavailable/);f.controller.dispose();
 const c=harness();c.controller.open();c.owner.isConnected=false;c.pending[0].resolve({'sensor.entry_risk':[row(1,'REMOVED')]});await flush();assert.match(c.content.innerHTML,/Loading/);c.controller.dispose();
 const d=harness();d.controller.open();d.controller.dispose();d.pending[0].resolve({'sensor.entry_risk':[row(1,'CLOSED')]});await flush();assert.equal(d.section.isConnected,false);
});
test('missing optional metrics do not broaden query and all-missing does not fetch',async()=>{
 const entities=[{id:'sensor.entry_iaq',kind:'numeric',label:'IAQ'},{id:'sensor.entry_voc',kind:'numeric',label:'VOC'},{id:'not_an_entity',kind:'numeric',label:'Invalid'}];
 const h=harness({entities,states:{'sensor.entry_iaq':{state:'0'}}});h.controller.open();assert.deepEqual(h.requests[0].entity_ids,['sensor.entry_iaq']);h.pending[0].resolve({'sensor.entry_iaq':[row(1,'0')]});await flush();assert.match(h.content.children.map(n=>n.innerHTML).join(''),/metric has a mapped source/);h.controller.dispose();
 const absent=harness({states:{}});absent.controller.open();assert.equal(absent.requests.length,0);assert.match(absent.content.innerHTML,/sources are mapped/);absent.controller.dispose();
});
test('numeric rendering uses historical units, separate charts, escaped inspection and exact zero',async()=>{
 const h=harness({entities:[{id:'sensor.entry_iaq',kind:'numeric',label:'IAQ'}]});h.controller.open();h.pending[0].resolve({'sensor.entry_iaq':[row(1,'0'),row(2,'2',{unit_of_measurement:'x'}),row(3,'3',{unit_of_measurement:'y'}),row(4,'<script>bad</script>')]});await flush();
 const html=h.content.children.map(n=>n.innerHTML).join('');assert.equal((html.match(/<svg/g)||[]).length,3);assert.match(html,/unit unspecified/);assert.match(html,/&lt;script&gt;/);assert.ok(!html.includes('<script>'));
 const article=h.content.children.find(n=>n.tagName==='ARTICLE');assert.match(article.querySelector('output').textContent,/bad/);article.querySelector('select').value='0';article.querySelector('select').dispatchEvent(new Event('change'));assert.match(article.querySelector('output').textContent,/— 0/);h.controller.dispose();
});
test('native secondary action disposes before opening existing entity details',()=>{
 const h=harness();h.controller.open();h.section.querySelector('[data-native]').dispatchEvent(new Event('click'));assert.equal(h.native(),1);assert.equal(h.section.isConnected,false);
});

test('truncation preserves predecessor evidence and never invents a first retained transition',()=>{
 const same=model.normalize(Array.from({length:600},(_,i)=>row(i,'normal')),start,end,'mode');assert.equal(same.records.length,500);assert.equal(model.transitions(same.records).length,0);
 const changed=model.normalize(Array.from({length:600},(_,i)=>row(i,i<100?'normal':'cooking')),start,end,'mode');assert.equal(model.transitions(changed.records).length,1);assert.equal(model.transitions(changed.records)[0].time,start+100000);
});

test('range caption preserves timezone offsets across the daylight-saving boundary',async()=>{
 const h=harness({endTime:Date.UTC(2026,9,26)});h.controller.open();h.section.querySelector('[data-hours="168"]').dispatchEvent(new Event('click'));
 h.pending[1].resolve({});await flush();
 const caption=h.content.children.map(n=>n.textContent||'').join(' ');assert.match(caption,/GMT\+1/);assert.match(caption,/GMT/);h.controller.dispose();
});
