#!/usr/bin/env node
// Actual browser input + production HI/card code; no live Home Assistant access.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import crypto from 'node:crypto';
import assert from 'node:assert/strict';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);const pw=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../..');
const output=path.resolve(process.env.FIXTURE_DIR||'.codex/reports/browser-touch');
const card=process.env.BUTTON_CARD_PATH;
if(!card)throw Error('Set BUTTON_CARD_PATH to the unmodified button-card7.0.1 JavaScript file');
const expected='5d6e9c6afca01e8014653fa56bb5d6aa9248d832c34fb944a7f2c36329bc22d1';
assert.equal(crypto.createHash('sha256').update(fs.readFileSync(card)).digest('hex'),expected,'button-card dependency hash');
const files={'/':path.join(here,'index.html'),'/fixture.mjs':path.join(here,'fixture.mjs'),'/config.json':path.join(output,'config.json'),'/button-card.js':card,'/adaptive.js':path.join(root,'custom_components/humidity_intelligence/adaptive_output/hi-adaptive-output-card.js')};
const preferenceStore=new Map();
const server=http.createServer(async(req,res)=>{const name=new URL(req.url,'http://localhost').pathname;
 if(name==='/fixture-preference'&&req.method==='POST'){
  try{let body='';for await(const chunk of req)body+=chunk;const data=JSON.parse(body);
   if(data.reset===true)preferenceStore.clear();
   else{
    assert.match(data.key,/^humidity_intelligence\.stability_badge\.disabled\.v1\.[a-f0-9]{64}$/);
    assert.ok(['frontend/get_user_data','frontend/subscribe_user_data','frontend/set_user_data'].includes(data.type));
    if(data.type==='frontend/set_user_data'){assert.equal(typeof data.value,'boolean');preferenceStore.set(data.key,data.value);}
   }
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({value:preferenceStore.get(data.key)??null}));
  }catch(error){res.writeHead(400);res.end(JSON.stringify({error:String(error)}));}return;
 }
 const file=files[name];if(!file){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',name==='/'?'text/html':name.endsWith('.json')?'application/json':'text/javascript');res.end(fs.readFileSync(file));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
const results=[],environments=[];let browser;
const only=process.env.TOUCH_CASE;
async function check(label,fn,page){if(only&&!label.includes(only))return;try{await fn();results.push({label,status:'pass'});console.log('PASS '+label);}catch(error){results.push({label,status:'fail',error:error.message});console.error('FAIL '+label+' '+error.message);results.at(-1).events=await page.evaluate(()=>window.fixture?.events).catch(()=>null);results.at(-1).debug=await page.evaluate(()=>window.fixture?.all.filter(e=>e.tagName==='BUTTON-CARD').map(e=>({name:e.dataset.hiName,state:e._hass?.states?.[e._config?.entity]?.state,revision:e[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')]?.result?.(),life:(()=>{const s=e[Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1')];return s?{ready:s.ready,blocked:s.blocked,connected:s.connection?.connected,sameStates:s.hass?.states===s.blockedStates,sameEntity:s.entity===s.blockedEntity,stamp:s.entity?.last_updated,ownerstamp:e._hass?.states?.[e._config?.entity]?.last_updated}:null})()}))).catch(()=>null);await page.screenshot({path:path.join(output,'failure-'+results.length+'.png'),fullPage:true}).catch(()=>{});}}
async function open(page,layout){await page.goto(`${origin}/?layout=${layout}`);await page.waitForSelector('html[data-ready=true]');await page.locator('button-card').first().locator('#card').waitFor();await page.waitForTimeout(120);}
async function opened(page){await page.locator('dialog[open]').last().waitFor({state:'visible',timeout:3000});}
async function close(page){const modal=page.locator('dialog[open]');if(await modal.count()){await modal.last().getByRole('button',{name:'Close',exact:true}).tap();await page.waitForTimeout(40);}}
async function touchGesture(page,locator,kind){await locator.scrollIntoViewIfNeeded();const box=await locator.boundingBox();const x=box.x+box.width/2,y=box.y+box.height/2;const cdp=await page.context().newCDPSession(page);
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:0}]});
 if(kind==='hold')await page.waitForTimeout(800);
 if(kind==='drag'){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+70,y:y-70,id:0}]});}
 if(kind==='multi'){await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:0},{x:x+30,y:y-30,id:1}]});}
 await cdp.send('Input.dispatchTouchEvent',{type:['cancel','multi'].includes(kind)?'touchCancel':'touchEnd',touchPoints:[]});await cdp.detach();await page.waitForTimeout(150);}
try{
for(const engine of (process.env.BROWSERS||'chromium,webkit').split(',')){
 browser=await pw[engine].launch(engine==='chromium'&&process.env.CHROME_CHANNEL?{channel:process.env.CHROME_CHANNEL}:{});
 for(const [layout,width,height] of [['v2_mobile',390,844],['v2_tablet',1024,1366]]){
  const context=await browser.newContext({viewport:{width,height},isMobile:true,hasTouch:true,userAgent:engine==='webkit'?`Mozilla/5.0 (${layout==='v2_tablet'?'iPad':'iPhone'}; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1`:'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'});
  await context.route('**/*',route=>route.request().url().startsWith(origin)?route.continue():route.abort());
  const page=await context.newPage();page.setDefaultTimeout(7000);await page.clock.install();page.on('pageerror',error=>console.error('BROWSER '+error.message));const prefix=engine+'/'+layout;
  await check(prefix+'/complete-mount',async()=>{await open(page,layout);environments.push({engine,layout,viewport:{width,height},browser:browser.version(),playwright:require(path.join(path.dirname(require.resolve(process.env.PLAYWRIGHT_MODULE||'playwright')),'package.json')).version,...await page.evaluate(()=>({userAgent:navigator.userAgent,maxTouchPoints:navigator.maxTouchPoints,coarse:matchMedia('(pointer:coarse)').matches}))});assert.ok(await page.locator('button-card').count()>10);assert.equal(await page.evaluate(()=>matchMedia('(pointer:coarse)').matches),true);if(engine==='chromium')assert.ok(await page.evaluate(()=>navigator.maxTouchPoints)>0);assert.deepEqual(await page.evaluate(()=>fixture.events.errors),[]);},page);
  await check(prefix+'/LED-touch-label-dot-hit-area',async()=>{await open(page,layout);for(const part of ['.hi-ui-revision-label','.hi-ui-revision-led']){await page.locator(part).tap();assert.equal(await page.locator('dialog.hi-ui-revision-details[open]').count(),1);await close(page);}const button=page.locator('.hi-ui-revision');await button.scrollIntoViewIfNeeded();const b=await button.boundingBox();await page.touchscreen.tap(b.x+4,b.y-5);assert.equal(await page.locator('dialog.hi-ui-revision-details[open]').count(),1);await close(page);assert.ok((await page.evaluate(()=>fixture.events.touch)).every(e=>e.trusted));assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/all-custom-dialogs-touch-close',async()=>{await open(page,layout);for(const name of ['Humidity','Condensation','Mould','7 Day Drift','Current Air Control','Ready','Zone 1','Zone 2','AQ','Stability Score']){const card=page.locator(`button-card[data-hi-name="${name}"]`);await card.locator('#card').tap();await opened(page);assert.equal(await page.locator('dialog[open]').count(),1,name);await close(page);assert.equal(await page.locator('dialog[open]').count(),0,name);}assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/embedded-history-navigation',async()=>{await open(page,layout);await page.locator('button-card[data-hi-name="Condensation"] #card').tap();await page.getByRole('button',{name:'View history',exact:true}).tap();await page.locator('.hi-history').waitFor();assert.equal(await page.evaluate(()=>fixture.events.history.length),1);await page.locator('[data-hours="168"]').tap();assert.equal(await page.evaluate(()=>fixture.events.history.length),2);await page.locator('[data-back]').tap();await page.getByRole('button',{name:'View history',exact:true}).tap();await page.locator('[data-native]').tap();await page.locator('dialog[data-native-stub=true]').waitFor();await close(page);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/System-Manual-exact-spies-valid-invalid',async()=>{await open(page,layout);for(const name of ['System','Manual']){const card=page.locator(`button-card[data-hi-name="${name}"]`);await card.locator('#card').tap();}const calls=await page.evaluate(()=>fixture.events.services);assert.equal(calls.length,2);assert.ok(calls.every(c=>c.service==='toggle'));await page.evaluate(()=>{fixture.setState('input_boolean.air_control_enabled','unavailable');fixture.setState('input_boolean.air_control_manual_override','unknown');fixture.reset();});await page.locator('button-card[data-hi-name="System"]').getByText('UNAVAILABLE',{exact:true}).waitFor();await page.locator('button-card[data-hi-name="Manual"]').getByText('UNKNOWN',{exact:true}).waitFor();for(const name of ['System','Manual'])await page.locator(`button-card[data-hi-name="${name}"] #card`).tap();assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/keyboard-rapid-reopen-Escape',async()=>{await open(page,layout);const b=page.locator('.hi-ui-revision');await b.focus();await page.keyboard.press('Enter');assert.equal(await page.locator('dialog[open]').count(),1);await page.keyboard.press('Escape');for(let i=0;i<3;i++){await b.tap();assert.equal(await page.locator('dialog[open]').count(),1);await close(page);}await b.focus();await page.keyboard.press('Space');assert.equal(await page.locator('dialog[open]').count(),1);await close(page);},page);
  await check(prefix+'/disconnect-reconnect-removal',async()=>{await open(page,layout);await page.locator('.hi-ui-revision').tap();await page.evaluate(()=>fixture.disconnect());assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await page.locator('.hi-ui-revision').getAttribute('data-status'),'unknown');await page.evaluate(()=>fixture.ready());assert.equal(await page.locator('.hi-ui-revision').getAttribute('data-status'),'unknown');await page.evaluate(()=>fixture.fresh());await page.locator('.hi-ui-revision[data-status="current"]').waitFor();await page.locator('.hi-ui-revision').tap();await page.evaluate(()=>fixture.remove());assert.equal(await page.locator('dialog[open]').count(),0);},page);
  await check(prefix+'/adaptive-parent-child-native-control',async()=>{await open(page,layout+'_adaptive');const adaptive=page.locator('hi-adaptive-output-card');await adaptive.locator('.header').tap();assert.equal(await adaptive.locator('.header').getAttribute('aria-expanded'),'true');await adaptive.locator('.footer').tap();assert.equal(await adaptive.locator('dialog[open]').count(),1);await adaptive.locator('fixture-entities').evaluate(el=>el.dataset.nodeCustody='original');await page.evaluate(()=>fixture.repaintOutputs());assert.equal(await adaptive.locator('fixture-entities').getAttribute('data-node-custody'),'original');await adaptive.locator('fixture-entities button').first().tap();assert.equal(await page.locator('dialog[data-native-stub=true][open]').count(),1);assert.equal(await adaptive.locator('dialog[open]').count(),0);await close(page);await adaptive.locator('.header').tap();assert.equal(await adaptive.locator('.header').getAttribute('aria-expanded'),'false');assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/native-Outputs-single-action',async()=>{await open(page,layout);await page.locator('button-card[data-hi-name="Outputs"] #card').tap();await page.waitForTimeout(100);const calls=await page.evaluate(()=>fixture.events.services);assert.equal(calls.length,1);assert.equal(calls[0].domain,'switch');assert.equal(calls[0].service,'toggle');assert.equal(calls[0].data.entity_id,await page.evaluate(()=>fixture.mapping['input_boolean.air_control_output_expanded']));},page);
  await check(prefix+'/adaptive-backdrop-Escape-evidence-source',async()=>{await open(page,layout+'_adaptive');const a=page.locator('hi-adaptive-output-card');await a.locator('.header').tap();await a.locator('.reason').tap();await opened(page);assert.match(await a.locator('dialog').textContent(),/Inspect the intake/);const box=await a.locator('dialog').boundingBox();await page.touchscreen.tap(Math.max(1,box.x-5),box.y+box.height/2);assert.equal(await a.locator('dialog[open]').count(),0);await a.locator('.footer').tap();await opened(page);await page.keyboard.press('Escape');assert.equal(await a.locator('dialog[open]').count(),0);await a.locator('.reason').tap();await opened(page);await a.getByRole('button',{name:/Why Example output is shown/}).first().tap();await page.locator('dialog[data-native-stub=true]').waitFor();await close(page);await a.locator('.footer').tap();await opened(page);await a.getByRole('button',{name:'Open Example diagnostic details',exact:true}).tap();await page.locator('dialog[data-native-stub=true]').waitFor();assert.equal(await page.evaluate(()=>fixture.events.moreInfo.at(-1).entityId),'binary_sensor.fixture_source');await close(page);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/adaptive-child-idle-reset-reopen-stale',async()=>{await open(page,layout+'_adaptive');const a=page.locator('hi-adaptive-output-card');await a.locator('.header').tap();await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(110000);await a.locator('dialog h3').first().tap();await page.clock.fastForward(110000);assert.equal(await a.locator('dialog[open]').count(),1);assert.equal(await a.locator('.header').getAttribute('aria-expanded'),'true');await page.evaluate(()=>fixture.publish());await page.clock.fastForward(10001);assert.equal(await a.locator('dialog[open]').count(),0);assert.equal(await a.locator('.header').getAttribute('aria-expanded'),'false');await a.locator('.header').tap();await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(60000);await close(page);await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(60001);assert.equal(await a.locator('dialog[open]').count(),1);await close(page);},page);
  if(engine==='chromium'){
   await check(prefix+'/Stability-preference-hold-refresh-unavailable',async()=>{
    await page.request.post(origin+'/fixture-preference',{data:{reset:true}});await open(page,layout);
    await page.evaluate(()=>fixture.scoreCase('available'));
    const badge=page.locator('button-card[data-hi-name="Stability Score"]');
    await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
    await badge.locator('#card').tap();await opened(page);await close(page);
    await page.evaluate(()=>fixture.reset());
    await touchGesture(page,badge.locator('#card'),'hold');
    await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
    assert.equal(await page.locator('dialog[open]').count(),0,'hold release must not open details');
    assert.equal(await page.evaluate(()=>fixture.events.preferences.filter(x=>x.type==='frontend/set_user_data').length),1);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
    const before=await page.evaluate(()=>JSON.stringify(fixture.hass.states[fixture.mapping['sensor.hi_diagnostics']].attributes.stability_score));
    await badge.locator('#card').tap();await opened(page);assert.match(await page.locator('dialog').textContent(),/Displayed score/);await close(page);
    assert.equal(await page.evaluate(()=>JSON.stringify(fixture.hass.states[fixture.mapping['sensor.hi_diagnostics']].attributes.stability_score)),before);
    await page.evaluate(()=>fixture.scoreCase('updated'));assert.equal(await badge.getAttribute('data-hi-stability-presentation'),'disabled');
    await page.reload();await page.waitForSelector('html[data-ready=true]');
    await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
    await page.evaluate(()=>fixture.scoreCase('unavailable'));
    assert.equal(await badge.getAttribute('data-hi-stability-presentation'),'disabled');
    await badge.screenshot({path:path.join(output,engine+'-'+layout+'-disabled-offline-fixture.png')});
    await touchGesture(page,badge.locator('#card'),'hold');
    await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
    assert.equal(await badge.locator('.hi-stability-gauge .hi-stability-center').textContent(),'—');
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
    await page.evaluate(()=>fixture.scoreCase('available'));
    await badge.screenshot({path:path.join(output,engine+'-'+layout+'-enabled-offline-fixture.png')});
   },page);
   await check(prefix+'/Stability-preference-failure-scroll-reduced-motion',async()=>{
    await page.request.post(origin+'/fixture-preference',{data:{reset:true}});await open(page,layout);
    const badge=page.locator('button-card[data-hi-name="Stability Score"]');
    await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
    await page.evaluate(()=>{fixture.scoreCase('available');fixture.preferenceFailure('write');fixture.reset();});
    await touchGesture(page,badge.locator('#card'),'hold');await badge.locator('.hi-stability-display-label').filter({hasText:'Save unconfirmed'}).waitFor();
    assert.equal(await badge.getAttribute('data-hi-stability-presentation'),'enabled');
    await page.evaluate(()=>{fixture.preferenceFailure('');fixture.reset();});
    await touchGesture(page,badge.locator('#card'),'drag');assert.equal(await page.locator('dialog[open]').count(),0);
    assert.equal(await page.evaluate(()=>fixture.events.preferences.filter(x=>x.type==='frontend/set_user_data').length),0);
    await page.emulateMedia({reducedMotion:'reduce'});await touchGesture(page,badge.locator('#card'),'hold');
    await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
    for(const selector of ['.hi-stability-presentation-overlay','.hi-stability-disabled-leds'])assert.equal(await badge.locator(selector).evaluate(el=>getComputedStyle(el).animationName),'none');
    await badge.locator('#card').focus();await page.keyboard.press('Enter');await opened(page);await close(page);
    await badge.locator('#card').focus();await page.keyboard.press('Space');await opened(page);await close(page);
    for(const mode of ['enabled','disabled']){
     await badge.locator('#card').focus();await page.keyboard.down('Space');await page.waitForTimeout(800);await page.keyboard.up('Space');
     await page.waitForFunction(expected=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')===expected,mode);
     assert.equal(await page.locator('dialog[open]').count(),0,'held Space release must not open details');
    }
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.request.post(origin+'/fixture-preference',{data:{reset:true}});
   },page);
  }
  if(engine==='webkit')await check(prefix+'/Stability-preference-keyboard-refresh-unavailable',async()=>{
   await page.request.post(origin+'/fixture-preference',{data:{reset:true}});await open(page,layout);
   const badge=page.locator('button-card[data-hi-name="Stability Score"]');
   await page.evaluate(()=>fixture.scoreCase('available'));
   await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
   await badge.locator('#card').focus();await page.keyboard.down('Space');await page.waitForTimeout(800);await page.keyboard.up('Space');
   await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
   assert.equal(await page.locator('dialog[open]').count(),0);
   await page.reload();await page.waitForSelector('html[data-ready=true]');
   await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
   await page.evaluate(()=>fixture.scoreCase('unavailable'));
   await badge.locator('#card').tap();await opened(page);await close(page);
   await badge.locator('#card').focus();await page.keyboard.down('Space');await page.waitForTimeout(800);await page.keyboard.up('Space');
   await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
   assert.equal(await badge.locator('.hi-stability-gauge .hi-stability-center').textContent(),'—');
   assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
   await page.request.post(origin+'/fixture-preference',{data:{reset:true}});
  },page);
  if(engine==='chromium'){
   await check(prefix+'/holds-native-actions-without-release-toggle',async()=>{await open(page,layout);for(const name of ['System','Manual','7 Day Drift']){await touchGesture(page,page.locator(`button-card[data-hi-name="${name}"] #card`),'hold');await page.locator('dialog[data-native-stub=true]').waitFor();await close(page);}assert.equal(await page.evaluate(()=>fixture.events.services.length),0);assert.equal(await page.evaluate(()=>fixture.events.moreInfo.length),3);},page);
   await check(prefix+'/badge-and-chip-scroll-cancels-tap',async()=>{await open(page,layout);for(const name of ['Humidity','Current Air Control','Ready','AQ']){await touchGesture(page,page.locator(`button-card[data-hi-name="${name}"] #card`),'drag');assert.equal(await page.locator('dialog[open]').count(),0,name);}assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  }
  if(engine==='chromium')for(const gesture of ['hold','drag','cancel','multi'])await check(prefix+'/native-touch-'+gesture,async()=>{await open(page,layout);await touchGesture(page,page.locator('.hi-ui-revision'),gesture);if(gesture==='hold')assert.ok(await page.locator('dialog[open]').count()<=1);else assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);await close(page);},page);
  else results.push({label:prefix+'/hold-drag-multitouch',status:'not-run',reason:'Playwright WebKit exposes trusted tap but no public arbitrary-touch-sequence API; no synthetic dispatch substituted.'});
  await check(prefix+'/duplicate-card-independent-touch-owners',async()=>{await open(page,layout);await page.evaluate(()=>fixture.duplicate());const buttons=page.locator('.hi-ui-revision');assert.equal(await buttons.count(),2);await buttons.nth(0).tap();await opened(page);await close(page);await buttons.nth(1).tap();await opened(page);assert.equal(await page.locator('dialog[open]').count(),1);await page.evaluate(()=>fixture.remove());await page.locator('dialog[open]').waitFor({state:'hidden'});assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/idle-touch-reset-passive-no-reset',async()=>{await open(page,layout);await page.locator('.hi-ui-revision').tap();await page.clock.fastForward(110000);await page.locator('dialog[open] h2').tap();await page.clock.fastForward(110000);assert.equal(await page.locator('dialog[open]').count(),1);await page.evaluate(()=>fixture.publish());await page.clock.fastForward(10001);assert.equal(await page.locator('dialog[open]').count(),0);},page);
  if(engine==='chromium'&&process.env.VISUAL_REVIEW==='1')await check(prefix+'/Stability-responsive-visual-review',async()=>{
   const measurements=[];
   for(const viewportWidth of [320,390,430,820,1024]){
    await page.setViewportSize({width:viewportWidth,height:1024});
    await page.request.post(origin+'/fixture-preference',{data:{reset:true}});await open(page,layout);
    const badge=page.locator('button-card[data-hi-name="Stability Score"]');
    await page.waitForFunction(()=>fixture.all.find(e=>e.dataset.hiName==='Stability Score')?.getAttribute('data-hi-stability-presentation')==='enabled');
    const controls=await badge.locator('button,input,select,ha-icon').count();
    for(const state of ['collecting','available','partial','unavailable','recent_poor','recent_expired']){
     await page.evaluate(name=>fixture.scoreCase(name),state);await badge.scrollIntoViewIfNeeded();
     await badge.screenshot({path:path.join(output,`${layout}-${state}-${viewportWidth}-offline-fixture.png`)});
     if(state.startsWith('recent_')){
      const gauge=badge.locator('.hi-stability-gauge');
      assert.equal(await gauge.evaluate(el=>getComputedStyle(el).getPropertyValue('--hi-stability-color').trim()),'#ef4444');
      assert.equal(await gauge.evaluate(el=>getComputedStyle(el).getPropertyValue('--hi-stability-led-sweep').trim()),state==='recent_poor'?'11deg':'0deg');
      await badge.locator('#card').tap();await opened(page);
      const detail=page.locator('dialog[open]');
      assert.match(await detail.textContent(),/Recent score movement/);
      assert.match(await detail.textContent(),state==='recent_poor'?/Recent score change: \+3 points/:/Recent score change: 0 points/);
      assert.equal(await detail.evaluate(el=>el.scrollWidth>el.clientWidth),false);
      await detail.screenshot({path:path.join(output,`${layout}-${state}-details-${viewportWidth}-offline-fixture.png`)});
      await detail.locator('.hi-stability-help summary').click();
      await detail.getByRole('heading',{name:'Recent score movement',exact:true}).scrollIntoViewIfNeeded();
      await detail.screenshot({path:path.join(output,`${layout}-${state}-movement-${viewportWidth}-offline-fixture.png`)});
      await close(page);
     }
    }
    await page.evaluate(()=>fixture.scoreCase('available'));await touchGesture(page,badge.locator('#card'),'hold');
    await badge.locator('.hi-stability-presentation-center').filter({hasText:'Disabled'}).waitFor();
    assert.equal(await badge.locator('button,input,select,ha-icon').count(),controls,'no extra control or icon');
    await badge.screenshot({path:path.join(output,`${layout}-disabled-${viewportWidth}-offline-fixture.png`)});
    const gauge=await badge.locator('.hi-stability-presentation-overlay').evaluate(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,overflow:el.scrollWidth>el.clientWidth,background:getComputedStyle(el).backgroundImage,animation:getComputedStyle(el).animationName}));
    assert.equal(gauge.width,82);assert.equal(gauge.height,82);assert.equal(gauge.overflow,false);
    await badge.locator('#card').tap();await opened(page);
    const history=page.locator('dialog[open] .hi-stability-history');await history.locator('summary').tap();
    await history.scrollIntoViewIfNeeded();
    const dialog=page.locator('dialog[open]');
    const detail=await dialog.evaluate(el=>({width:el.getBoundingClientRect().width,overflow:el.scrollWidth>el.clientWidth,historyOpen:el.querySelector('.hi-stability-history').open,closeWidth:el.querySelector('.hi-stability-close').getBoundingClientRect().width}));
    assert.equal(detail.overflow,false);assert.equal(detail.historyOpen,true);assert.equal(detail.closeWidth,44);
    await dialog.screenshot({path:path.join(output,`${layout}-history-while-disabled-${viewportWidth}-offline-fixture.png`)});
    await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),0);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
    measurements.push({layout,viewportWidth,gauge,detail});
   }
   fs.writeFileSync(path.join(output,`${layout}-visual-measurements.json`),JSON.stringify({provenance:'Synthetic backend replay in production-generated layout; no live Home Assistant',measurements},null,2));
  },page);
  await context.close();
 }
 await browser.close();browser=null;
}
}finally{await browser?.close();await new Promise(r=>server.close(r));fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({buttonCard:{version:'7.0.1',sha256:expected},environments,limitations:['Native HA stack/mod-card/entities substitutes, not HA frontend','No physical iOS/Android or household integration','WebKit arbitrary-touch-sequence limitation explicitly recorded'],results},null,2));}
const failures=results.filter(r=>r.status==='fail');console.log(`${results.length} cases; ${failures.length} failed`);if(failures.length)process.exitCode=1;
