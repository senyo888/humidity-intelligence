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
async function footerMeasure(footer){return footer.evaluate(element=>{
 const rect=node=>{const box=node.getBoundingClientRect();return {x:box.x,y:box.y,right:box.right,bottom:box.bottom,width:box.width,height:box.height};};
 const cue=element.querySelector('.hi-update-label'),style=getComputedStyle(element),cueStyle=getComputedStyle(cue);
 return {box:rect(element),owner:rect(element.getRootNode().host),summary:rect(element.querySelector('.hi-ui-revision-summary')),cue:rect(cue),cueDisplay:cueStyle.display,separator:getComputedStyle(cue,'::before').content,overflow:element.scrollWidth>element.clientWidth,paddingLeft:parseFloat(style.paddingLeft),paddingRight:parseFloat(style.paddingRight),borderLeft:parseFloat(style.borderLeftWidth),borderRight:parseFloat(style.borderRightWidth),fontSize:parseFloat(style.fontSize),viewport:innerWidth};
});}
function assertFooterGeometry(measure,visible){
 assert.ok(measure.box.height>=44,'real button retains 44px minimum');
 assert.ok(measure.box.x>=0&&measure.box.right<=measure.viewport+1,'footer fits viewport');assert.equal(measure.overflow,false,'footer has no horizontal overflow');
 assert.ok(measure.box.y>=measure.owner.y-1&&measure.box.bottom<=measure.owner.bottom+1,'owner grows with wrapped footer content');
 assert.ok(Math.abs(measure.summary.x-(measure.box.x+measure.paddingLeft+measure.borderLeft))<=1,'revision status stays at the left edge');
 assert.ok(['none','normal','""',"''"].includes(measure.separator),'software cue has no separator');
 const parts=visible?[measure.summary,measure.cue]:[measure.summary];
 for(const part of parts)assert.ok(part.x>=measure.box.x-1&&part.right<=measure.box.right+1&&part.y>=measure.box.y-1&&part.bottom<=measure.box.bottom+1,'visible labels stay inside touch target');
 if(visible){
  assert.notEqual(measure.cueDisplay,'none');assert.ok(measure.cue.width>0&&measure.cue.height>0);
  assert.ok(Math.abs(measure.cue.right-(measure.box.right-measure.paddingRight-measure.borderRight))<=1,'software cue aligns to the right content edge');
  const left=measure.summary,right=measure.cue;assert.ok(left.right<=right.x+1||right.right<=left.x+1||left.bottom<=right.y+1||right.bottom<=left.y+1,'footer labels do not overlap');
 }else{assert.equal(measure.cueDisplay,'none');assert.equal(measure.cue.width,0);assert.equal(measure.cue.height,0);}
}
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
  await check(prefix+'/LED-touch-label-dot-hit-area',async()=>{await open(page,layout);for(const part of ['.hi-ui-revision-label','.hi-ui-revision-led','.hi-update-label']){await page.locator(part).tap();assert.equal(await page.locator('dialog.hi-ui-revision-details[open]').count(),1);await close(page);}const button=page.locator('.hi-ui-revision');await button.scrollIntoViewIfNeeded();const b=await button.boundingBox();assert.ok(b.height>=44,'real footer button has a 44px minimum touch target');await page.touchscreen.tap(b.x+4,b.y+4);assert.equal(await page.locator('dialog.hi-ui-revision-details[open]').count(),1);await close(page);assert.ok((await page.evaluate(()=>fixture.events.touch)).every(e=>e.trusted));assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  for(const variant of ['', '_adaptive']){
   const targetLayout=layout+variant, footerPrefix=prefix+'/beta4-footer'+(variant||'-native');
   await check(footerPrefix+'/reported-statuses-and-independent-UI',async()=>{
    await open(page,targetLayout);const footer=page.locator('.hi-ui-revision');
    for(const [name,status,label] of [['missing','unverified','Updates unverified'],['unavailable','unverified','Updates unverified'],['unknown','unverified','Updates unverified'],['reported_update','reported_update','↑ Update available'],['no_update_reported','no_update_reported','No update reported'],['skipped','skipped','Update skipped'],['in_progress','in_progress','HI update in progress']]){
     await page.evaluate(name=>fixture.updateCase(name),name);await footer.locator('.hi-update-label').filter({hasText:label}).waitFor({state:name==='no_update_reported'?'hidden':'visible'});
     assert.equal(await footer.getAttribute('data-update-status'),status);assert.equal(await footer.getAttribute('data-status'),'current');
     assert.equal(await footer.locator('.hi-ui-revision-label').textContent(),'UI current');
     assert.match(await footer.getAttribute('aria-label'),/Open UI and software versions/);
     await footer.tap();const details=page.locator('dialog.hi-ui-revision-details[open]');await details.waitFor();
     assert.equal(await details.getAttribute('aria-label'),'UI and software versions');
     assert.equal(await details.locator('[data-view-update]').count(),status==='unverified'?0:1);
     assert.match(await details.textContent(),/fresh Internet check and the running version are not verified/);
     if(name==='no_update_reported')assert.match(await details.textContent(),/downloaded version is ahead/);
     await close(page);
    }
    await page.evaluate(()=>{fixture.updateCase('reported_update');fixture.uiUpdate();});
    await footer.locator('.hi-ui-revision-label').filter({hasText:'UI update'}).waitFor();
    assert.equal(await footer.getAttribute('data-status'),'update');assert.equal(await footer.getAttribute('data-update-status'),'reported_update');
    await footer.tap();assert.match(await page.locator('dialog[open]').textContent(),/UI update[\s\S]*Update available/);await close(page);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);
   },page);
   await check(footerPrefix+'/quiet-state-matrix-and-transitions',async()=>{
    await open(page,targetLayout);const footer=page.locator('.hi-ui-revision'),observations=[];
    const providerCases=[['no_update_reported','no_update_reported','No update reported'],['reported_update','reported_update','Update available'],['skipped','skipped','Update skipped'],['in_progress','in_progress','HI update in progress'],['missing','unverified','Updates unverified'],['no_update_reported','no_update_reported','No update reported']];
    for(const [ui,label] of [['current','UI current'],['update','UI update'],['different','UI differs'],['unknown','UI unverified']]){
     let leftPosition,ledColor;
     for(const [fixture,status,softwareLabel] of providerCases){
      await page.evaluate(({fixture:provider,ui})=>{window.fixture.updateCase(provider);window.fixture.uiCase(ui);},{fixture,ui});
      await page.locator(`.hi-ui-revision[data-status="${ui}"][data-update-status="${status}"]`).waitFor();
      assert.equal(await footer.locator('.hi-ui-revision-label').textContent(),label);
      assert.equal(await footer.getAttribute('aria-label'),`${label}. ${softwareLabel}. Open UI and software versions`);
      assert.equal(await footer.locator('.hi-update-label').textContent(),(status==='reported_update'?'↑ ':'')+softwareLabel);
      assert.equal(await footer.locator('.hi-update-label').isVisible(),status!=='no_update_reported');
      const measure=await footerMeasure(footer);assertFooterGeometry(measure,status!=='no_update_reported');
      const currentColor=await footer.locator('.hi-ui-revision-led').evaluate(element=>getComputedStyle(element).backgroundColor);
      const relativeLeft=measure.summary.x-measure.box.x;
      if(leftPosition===undefined){leftPosition=relativeLeft;ledColor=currentColor;}else{assert.equal(relativeLeft,leftPosition,'provider transitions do not move revision summary');assert.equal(currentColor,ledColor,'provider transitions do not alter revision LED');}
      await footer.focus();await page.keyboard.press('Enter');const detail=page.locator('dialog.hi-ui-revision-details[open]');await detail.waitFor();
      assert.equal(await detail.getByRole('heading',{name:softwareLabel,exact:true}).count(),1);
      if(status==='no_update_reported')assert.match(await detail.textContent(),/HACS reports no update/);
      if(status==='reported_update')assert.match(await detail.textContent(),/HACS reports an update/);
      await close(page);observations.push({ui,providerStatus:status,visible:status!=='no_update_reported',measure});
     }
    }
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);
    fs.writeFileSync(path.join(output,`${engine}-${targetLayout}-beta4-status-matrix.json`),JSON.stringify({provenance:'20 distinct backend-derived UI/provider combinations, plus quiet-state return transitions; synthetic loopback fixture',observations},null,2));
   },page);
   await check(footerPrefix+'/keyboard-and-exact-native-handoff',async()=>{
    await open(page,targetLayout);await page.evaluate(()=>fixture.updateCase('reported_update'));const footer=page.locator('.hi-ui-revision');
    for(const key of ['Enter','Space']){await footer.focus();await page.keyboard.press(key);await opened(page);assert.equal(await page.locator('dialog[open]').count(),1);await page.keyboard.press('Escape');}
    await footer.locator('.hi-update-label').tap();await page.getByRole('button',{name:'View update',exact:true}).tap();
    await page.locator('dialog[data-native-stub=true][open]').waitFor();assert.equal(await page.locator('dialog.hi-ui-revision-details').count(),0);
    assert.deepEqual(await page.evaluate(()=>fixture.events.moreInfo),[{entityId:'update.fixture_hi_renamed'}]);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);assert.equal(await page.evaluate(()=>fixture.events.actions.length),0);await close(page);
   },page);
   await check(footerPrefix+'/stale-provider-and-dialog-retarget-guard',async()=>{
    await open(page,targetLayout);const footer=page.locator('.hi-ui-revision');
    for(const change of [{state:'unavailable'},{attributes:{latest_version:'2.1.1-beta.5'}}]){
     await page.evaluate(()=>fixture.updateCase('reported_update'));await footer.tap();
     await page.evaluate(change=>fixture.providerChange(change),change);await page.getByRole('button',{name:'View update',exact:true}).tap();
     await page.locator('[data-update-action-status]').filter({hasText:'Close and reopen'}).waitFor();assert.equal(await page.evaluate(()=>fixture.events.moreInfo.length),0);await close(page);
     await footer.tap();assert.equal(await page.locator('[data-view-update]').count(),0);await close(page);
    }
    await page.evaluate(()=>fixture.updateCase('reported_update'));await footer.tap();await page.evaluate(()=>fixture.renameUpdateSource());
    await page.getByRole('button',{name:'View update',exact:true}).tap();await page.locator('[data-update-action-status]').filter({hasText:'Close and reopen'}).waitFor();
    assert.equal(await page.evaluate(()=>fixture.events.moreInfo.length),0);await close(page);await footer.tap();await page.getByRole('button',{name:'View update',exact:true}).tap();
    assert.deepEqual(await page.evaluate(()=>fixture.events.moreInfo),[{entityId:'update.fixture_hi_replaced'}]);await close(page);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
   },page);
   await check(footerPrefix+'/version-text-escaped',async()=>{
    await open(page,targetLayout);await page.evaluate(()=>fixture.updateCase('escaped_version'));await page.locator('.hi-ui-revision').tap();
    const details=page.locator('dialog[open]');assert.match(await details.textContent(),/<b data-fixture-untrusted="yes">beta<\/b>/);assert.equal(await details.locator('[data-fixture-untrusted]').count(),0);
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);assert.deepEqual(await page.evaluate(()=>fixture.events.errors),[]);await close(page);
   },page);
   await check(footerPrefix+'/disconnect-freshness-duplicate-cleanup',async()=>{
    await open(page,targetLayout);await page.evaluate(()=>fixture.updateCase('reported_update'));const footer=page.locator('.hi-ui-revision');await footer.tap();
    await page.evaluate(()=>fixture.disconnect());assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await footer.getAttribute('data-update-status'),'unverified');
    await page.evaluate(()=>fixture.ready());assert.equal(await footer.getAttribute('data-update-status'),'unverified');
    await page.evaluate(()=>fixture.fresh());await page.locator('.hi-ui-revision[data-update-status="reported_update"]').waitFor();
    await page.evaluate(()=>fixture.duplicate());assert.equal(await footer.count(),2);
    await footer.nth(0).tap();await opened(page);await close(page);await footer.nth(1).tap();await opened(page);assert.equal(await page.locator('dialog[open]').count(),1);
    await page.evaluate(()=>fixture.remove());await page.locator('dialog[open]').waitFor({state:'hidden'});assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
   },page);
   await check(footerPrefix+'/responsive-footer-and-details',async()=>{
    const measurements=[];
    for(const viewportWidth of [...new Set([320,390,width])]){
     await page.setViewportSize({width:viewportWidth,height:1024});await open(page,targetLayout);
     for(const status of ['no_update_reported','reported_update','in_progress','missing'])for(const scale of [1,2]){
      await page.evaluate(status=>fixture.updateCase(status),status);
      const footer=page.locator('.hi-ui-revision');
      // Local font-size stress tests wrapping; this is not an OS accessibility setting.
      await footer.evaluate((element,scale)=>{element.style.fontSize=11*scale+'px';element.style.lineHeight=20*scale+'px';},scale);
      await footer.scrollIntoViewIfNeeded();const measure=await footerMeasure(footer);assertFooterGeometry(measure,status!=='no_update_reported');
      if(scale===2&&viewportWidth===320&&status==='in_progress')assert.ok(measure.cue.y>=measure.summary.bottom,'large text wraps below the revision summary');
      const capture=engine==='chromium'&&!variant&&((scale===1&&['no_update_reported','reported_update'].includes(status))||(scale===2&&viewportWidth===320&&status==='in_progress'));
      if(capture)await footer.screenshot({path:path.join(output,`${layout}-beta4-footer-${status}-${viewportWidth}-${scale}x-offline-fixture.png`)});
      if(status==='reported_update'&&scale===1){
       await footer.tap();const dialog=page.locator('dialog[open]');const details=await dialog.evaluate(element=>({overflow:element.scrollWidth>element.clientWidth,width:element.getBoundingClientRect().width}));
       assert.equal(details.overflow,false);assert.ok(details.width<=viewportWidth);if(engine==='chromium'&&!variant)await dialog.screenshot({path:path.join(output,`${layout}-beta4-details-${viewportWidth}-offline-fixture.png`)});
       measurements.push({viewportWidth,status,scale,...measure,details});await close(page);
      }else measurements.push({viewportWidth,status,scale,...measure});
     }
    }
    fs.writeFileSync(path.join(output,`${engine}-${targetLayout}-beta4-measurements.json`),JSON.stringify({provenance:'Synthetic normalized provider state; production-generated layouts; scale2 is local font-size/line-height stress only; no live Home Assistant or physical device',measurements},null,2));
    await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
   },page);
  }
  await check(prefix+'/all-custom-dialogs-touch-close',async()=>{await open(page,layout);for(const name of ['Humidity','Condensation','Mould','7 Day Drift','Current Air Control','Ready','Zone 1','Zone 2','AQ','Stability Score']){const card=page.locator(`button-card[data-hi-name="${name}"]`);await card.locator('#card').tap();await opened(page);assert.equal(await page.locator('dialog[open]').count(),1,name);await close(page);assert.equal(await page.locator('dialog[open]').count(),0,name);}assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/embedded-history-navigation',async()=>{await open(page,layout);await page.locator('button-card[data-hi-name="Condensation"] #card').tap();await page.getByRole('button',{name:'View history',exact:true}).tap();await page.locator('.hi-history').waitFor();assert.equal(await page.evaluate(()=>fixture.events.history.length),1);await page.locator('[data-hours="168"]').tap();assert.equal(await page.evaluate(()=>fixture.events.history.length),2);await page.locator('[data-back]').tap();await page.getByRole('button',{name:'View history',exact:true}).tap();await page.locator('[data-native]').tap();await page.locator('dialog[data-native-stub=true]').waitFor();await close(page);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/System-Manual-exact-spies-valid-invalid',async()=>{await open(page,layout);for(const name of ['System','Manual']){const card=page.locator(`button-card[data-hi-name="${name}"]`);await card.locator('#card').tap();}const calls=await page.evaluate(()=>fixture.events.services);assert.equal(calls.length,2);assert.ok(calls.every(c=>c.service==='toggle'));await page.evaluate(()=>{fixture.setState('input_boolean.air_control_enabled','unavailable');fixture.setState('input_boolean.air_control_manual_override','unknown');fixture.reset();});await page.locator('button-card[data-hi-name="System"]').getByText('UNAVAILABLE',{exact:true}).waitFor();await page.locator('button-card[data-hi-name="Manual"]').getByText('UNKNOWN',{exact:true}).waitFor();for(const name of ['System','Manual'])await page.locator(`button-card[data-hi-name="${name}"] #card`).tap();assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/keyboard-rapid-reopen-Escape',async()=>{await open(page,layout);const b=page.locator('.hi-ui-revision');await b.focus();await page.keyboard.press('Enter');assert.equal(await page.locator('dialog[open]').count(),1);await page.keyboard.press('Escape');for(let i=0;i<3;i++){await b.tap();assert.equal(await page.locator('dialog[open]').count(),1);await close(page);}await b.focus();await page.keyboard.press('Space');assert.equal(await page.locator('dialog[open]').count(),1);await close(page);},page);
  await check(prefix+'/disconnect-reconnect-removal',async()=>{await open(page,layout);await page.locator('.hi-ui-revision').tap();await page.evaluate(()=>fixture.disconnect());assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await page.locator('.hi-ui-revision').getAttribute('data-status'),'unknown');await page.evaluate(()=>fixture.ready());assert.equal(await page.locator('.hi-ui-revision').getAttribute('data-status'),'unknown');await page.evaluate(()=>fixture.fresh());await page.locator('.hi-ui-revision[data-status="current"]').waitFor();await page.locator('.hi-ui-revision').tap();await page.evaluate(()=>fixture.remove());assert.equal(await page.locator('dialog[open]').count(),0);},page);
  await check(prefix+'/adaptive-parent-child-native-control',async()=>{await open(page,layout+'_adaptive');const adaptive=page.locator('hi-adaptive-output-card');await adaptive.locator('.header').tap();assert.equal(await adaptive.locator('.header').getAttribute('aria-expanded'),'true');await adaptive.locator('.footer').tap();assert.equal(await adaptive.locator('dialog[open]').count(),1);await adaptive.locator('fixture-entities').evaluate(el=>el.dataset.nodeCustody='original');await page.evaluate(()=>fixture.repaintOutputs());assert.equal(await adaptive.locator('fixture-entities').getAttribute('data-node-custody'),'original');await adaptive.locator('fixture-entities button').first().tap();assert.equal(await page.locator('dialog[data-native-stub=true][open]').count(),1);assert.equal(await adaptive.locator('dialog[open]').count(),0);await close(page);await adaptive.locator('.header').tap();assert.equal(await adaptive.locator('.header').getAttribute('aria-expanded'),'false');assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/native-Outputs-single-action',async()=>{await open(page,layout);await page.locator('button-card[data-hi-name="Outputs"] #card').tap();await page.waitForTimeout(100);const calls=await page.evaluate(()=>fixture.events.services);assert.equal(calls.length,1);assert.equal(calls[0].domain,'switch');assert.equal(calls[0].service,'toggle');assert.equal(calls[0].data.entity_id,await page.evaluate(()=>fixture.mapping['input_boolean.air_control_output_expanded']));},page);
  await check(prefix+'/adaptive-backdrop-Escape-evidence-source',async()=>{await open(page,layout+'_adaptive');const a=page.locator('hi-adaptive-output-card');await a.locator('.header').tap();await a.locator('.reason').tap();await opened(page);assert.match(await a.locator('dialog').textContent(),/Inspect the intake/);const box=await a.locator('dialog').boundingBox();await page.touchscreen.tap(Math.max(1,box.x-5),box.y+box.height/2);assert.equal(await a.locator('dialog[open]').count(),0);await a.locator('.footer').tap();await opened(page);await page.keyboard.press('Escape');assert.equal(await a.locator('dialog[open]').count(),0);await a.locator('.reason').tap();await opened(page);await a.getByRole('button',{name:/Why Example output is shown/}).first().tap();await page.locator('dialog[data-native-stub=true]').waitFor();await close(page);await a.locator('.footer').tap();await opened(page);await a.getByRole('button',{name:'Open Example diagnostic details',exact:true}).tap();await page.locator('dialog[data-native-stub=true]').waitFor();assert.equal(await page.evaluate(()=>fixture.events.moreInfo.at(-1).entityId),'binary_sensor.fixture_source');await close(page);assert.equal(await page.evaluate(()=>fixture.events.services.length),0);},page);
  await check(prefix+'/adaptive-child-idle-reset-reopen-stale',async()=>{await open(page,layout+'_adaptive');const a=page.locator('hi-adaptive-output-card');await a.locator('.header').tap();await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(110000);await a.locator('dialog h3').first().tap();await page.clock.fastForward(110000);assert.equal(await a.locator('dialog[open]').count(),1);assert.equal(await a.locator('.header').getAttribute('aria-expanded'),'true');await page.evaluate(()=>fixture.publish());await page.clock.fastForward(10001);assert.equal(await a.locator('dialog[open]').count(),0);assert.equal(await a.locator('.header').getAttribute('aria-expanded'),'false');await a.locator('.header').tap();await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(60000);await close(page);await a.locator('.footer').tap();await opened(page);await page.clock.fastForward(60001);assert.equal(await a.locator('dialog[open]').count(),1);await close(page);},page);
  for(const failure of ['reject','timeout'])await check(prefix+'/Stability-preference-score-fallback-'+failure,async()=>{
   await page.request.post(origin+'/fixture-preference',{data:{reset:true}});
   const pending=[];
   const intercept=async route=>{
    if(route.request().postDataJSON().type!=='frontend/subscribe_user_data')return route.continue();
    if(failure==='reject')return route.fulfill({status:503,body:'Synthetic preference read failure'});
    pending.push(route);
   };
   await page.route('**/fixture-preference',intercept);
   try{
    await open(page,layout);await page.evaluate(()=>fixture.scoreCase('available'));
    const badge=page.locator('button-card[data-hi-name="Stability Score"]');
    const gauge=badge.locator('.hi-stability-gauge'),overlay=badge.locator('.hi-stability-presentation-overlay');
    const visibleScore=async()=>{
     assert.equal(await gauge.evaluate(el=>getComputedStyle(el).visibility),'visible');
     assert.equal(await overlay.evaluate(el=>getComputedStyle(el).display),'none');
     assert.match(await gauge.locator('.hi-stability-center').textContent(),/^\d+$/);
    };
    if(failure==='timeout'){
     await badge.locator('.hi-stability-display-label').filter({hasText:'Loading display preference'}).waitFor();
     await visibleScore();await page.clock.fastForward(12001);
    }
    await badge.locator('.hi-stability-display-label').filter({hasText:'Display preference unavailable'}).waitFor();
    await visibleScore();
    await badge.screenshot({path:path.join(output,`${engine}-${layout}-preference-${failure}-offline-fixture.png`)});
    await badge.locator('#card').tap();await opened(page);await close(page);
    await page.evaluate(()=>fixture.scoreCase('unavailable'));
    assert.equal(await gauge.locator('.hi-stability-center').textContent(),'—','backend unavailable remains authoritative');
    assert.equal(await gauge.evaluate(el=>getComputedStyle(el).visibility),'visible');
    assert.equal(await overlay.evaluate(el=>getComputedStyle(el).display),'none');
    assert.equal(await page.evaluate(()=>fixture.events.services.length),0);
    assert.equal(await page.evaluate(()=>fixture.events.preferences.filter(x=>x.type==='frontend/set_user_data').length),0);
   }finally{
    await page.unroute('**/fixture-preference',intercept);
    // Navigation or teardown may have already cancelled a held request.
    for(const route of pending)await route.abort().catch(()=>{});
   }
  },page);
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
}finally{await browser?.close();await new Promise(r=>server.close(r));const fixtureConfig=fs.readFileSync(files['/config.json']);fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({buttonCard:{version:'7.0.1',sha256:expected},fixture:{sha256:crypto.createHash('sha256').update(fixtureConfig).digest('hex'),source_sha256:JSON.parse(fixtureConfig).source_sha256,update_provenance:JSON.parse(fixtureConfig).update_provenance},environments,limitations:['Native HA stack/mod-card/entities substitutes, not HA frontend','No physical iOS/Android or household integration','Synthetic HACS registry/provider states; no installed HACS or live release-channel verification','WebKit arbitrary-touch-sequence limitation explicitly recorded'],results},null,2));}
const failures=results.filter(r=>r.status==='fail');console.log(`${results.length} cases; ${failures.length} failed`);if(failures.length)process.exitCode=1;
