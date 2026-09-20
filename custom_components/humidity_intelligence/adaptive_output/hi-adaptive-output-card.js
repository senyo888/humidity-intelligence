/* Optional HI output display. All status comes from the backend feed.
 * Native HA entities remain a separate child card; this card writes no services.
 */
(() => {
  const TYPE = 'hi-adaptive-output-card';
  // Shipped translations only. Unsupported HA locales use reviewed English copy.
  // Backend observation strings remain backend-owned; this dictionary owns chrome.
  const MESSAGES = Object.freeze({en:Object.freeze({
    outputs:'Outputs', outputs_controls:'Outputs & controls', details:'Output details', review_details:'View all output evidence and monitoring details', review_link:'View details', view_conditions:'View all {count} conditions', shown_counts:'{conditions} conditions · {outputs} outputs affected', shown_reports:'Showing {shown} of {total} reports', diagnostic_sources:'Monitoring sources', close:'Close',
    controls:'Controls and supporting readings',
    controls_unavailable:'Controls could not load. Reload the dashboard to try again.',
    catalogue_unavailable:'Monitoring sources unavailable',
    status_unavailable:'Output status unavailable', monitoring_unavailable:'Monitoring unavailable',
    feed_unavailable:'Output monitoring is unavailable. Open Outputs & controls to access the existing controls.',
    configured_outputs:'Configured outputs', control_context:'HI control state', inspect:'Inspect',
    unknown:'Unknown', evidence:'Why this is shown', source:'Source', reported_state:'Source reading',
    ha_reported:'Last reported to Home Assistant', ha_updated:'Last updated in Home Assistant', ha_changed:'Last changed in Home Assistant',
    restored:'Restored by Home Assistant', yes:'Yes', no:'No',
    inspect_evidence:'Why {label} is shown', inspect_diagnostic:'Open {label} details',
    open_controls:'Open {label} controls', inspect_sources:'Inspect {count} monitoring sources',
    preview:'Synthetic rendering harness · No live Home Assistant data',
    observation:'Output observation · Home Assistant state evidence'
  })});
  const message = (language,key,values={}) => {
    const locale=String(language||'en').toLowerCase().split('-')[0];
    const text=(MESSAGES[locale]||MESSAGES.en)[key]||MESSAGES.en[key]||key;
    return text.replace(/\{([a-z]+)\}/g,(_,name)=>String(values[name]??''));
  };

  const entityId = value => typeof value === 'string' && /^[a-z_]+\.[a-z0-9_]+$/.test(value);
  // Only buttons constructed here belong to HI. Native HA child controls keep
  // their own routing. Let the browser produce (or cancel) the sole native click;
  // button-card ancestors must not consume touchend or start hold actions first.
  const isolateNativeButton = event => {
    if (['keydown','keyup'].includes(event.type) && !['Enter',' '].includes(event.key)) return;
    event.stopPropagation();
  };
  const node = (tag, text, cls) => {
    const n=document.createElement(tag);
    if(tag==='button')for(const name of ['touchstart','touchend','touchcancel','mousedown','mouseup','click','keydown','keyup'])n.addEventListener(name,isolateNativeButton,{passive:true});
    if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;
  };
  const tone = value => ['active','warning','danger','context','neutral'].includes(value)?value:'neutral';
  const icon = name => { const n=node('ha-icon');n.setAttribute('icon','mdi:'+(/^[a-z0-9-]+$/.test(name||'')?name:'information-outline'));return n; };
  const object = x => x!==null&&typeof x==='object'&&!Array.isArray(x);
  const list = (x,check,max=1024) => Array.isArray(x)&&x.length<=max&&x.every(check);
  const textFields = (x,keys) => object(x)&&keys.every(k=>typeof x[k]==='string');
  const validAssociation = a => textFields(a,['label','title','reason','scope_label']) &&
    ['origin_label','meaning_label','rule_summary'].every(k=>a[k]===undefined||(typeof a[k]==='string'&&a[k].length<=240)) &&
    (a.rule_lines===undefined||list(a.rule_lines,v=>typeof v==='string'&&v.length<=400,34));
  const validPayload = p => object(p)&&[1,2].includes(p.schema_version)&&p.synthetic===false&&
    textFields(p,['summary','attention_label'])&&
    (p.observation===undefined||textFields(p.observation,['basis','physical_freshness','detail']))&&object(p.counts)&&Number.isInteger(p.counts.configured)&&
    textFields(p.coverage,['label','detail'])&&
    list(p.chips,c=>textFields(c,['label']),3)&&
    list(p.attention,a=>textFields(a,['label','title','action','evidence']))&&
    list(p.records,r=>textFields(r,['label','entity_id'])&&entityId(r.entity_id)&&list(r.roles,x=>typeof x==='string',16)&&textFields(r.operation,['label'])&&
      (r.configured_roles===undefined||list(r.configured_roles,v=>textFields(v,['label']),128))&&
      (r.role_context===undefined||typeof r.role_context==='string'),128)&&
    (p.runtime_context===undefined||list(p.runtime_context,c=>textFields(c,['label','state','detail']),16))&&
    (p.discovery===undefined||(textFields(p.discovery,['summary','detail'])&&
      ['setup_notice','lost_notice'].every(k=>p.discovery[k]===undefined||typeof p.discovery[k]==='string')&&
      list(p.discovery.gaps||[],g=>textFields(g,['output_label','label','detail']))&&
      list(p.discovery.notices||[],n=>textFields(n,['output_label','title','reason']))&&
      list(p.discovery.sources||[],r=>textFields(r,['label','title','state','association_label','reason','scope_label']) &&
        (r.associations===undefined||list(r.associations,validAssociation,128))&&
        (r.observation===undefined||(object(r.observation)&&['last_reported','last_updated','last_changed'].every(k=>r.observation[k]===undefined||(typeof r.observation[k]==='string'&&r.observation[k].length<=64))&&(r.observation.restored===undefined||typeof r.observation.restored==='boolean'))))));
  const CSS = `
    :host{--primary-text-color:#e2e8f0;--secondary-text-color:#a8b8cb;--state-inactive-color:#94a3b8;display:block;container-type:inline-size;color:var(--primary-text-color,#e2e8f0);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}*{box-sizing:border-box}[hidden]{display:none!important}
    button{font:inherit;color:inherit;cursor:pointer}button:focus-visible{outline:2px solid var(--primary-color,#7dd3fc);outline-offset:3px}
    .header{width:100%;text-align:left;border:2px solid rgba(148,163,184,.18);border-radius:22px;padding:12px 14px;background:rgba(10,12,16,.62);box-shadow:0 0 18px rgba(148,163,184,.18);backdrop-filter:blur(12px)}
    .title{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:900;letter-spacing:.2px}.title>ha-icon{--mdc-icon-size:18px;color:#94a3b8}
    .chevron{margin-left:auto;margin-top:2px;align-self:flex-start;flex:0 0 25px;width:25px;height:25px;display:grid;place-items:center;border-radius:999px;background:rgba(15,23,42,.85);box-shadow:0 0 12px rgba(148,163,184,.45);color:#94a3b8;pointer-events:none}.chevron svg{display:block;width:18px;height:18px;fill:currentColor}.header[aria-expanded=true] .chevron{color:#4ade80}
    .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;line-height:1.4;padding:4px 8px;border:1px solid #3b4b60;border-radius:99px;color:#c5d3e1;overflow-wrap:anywhere;max-width:100%}.chip ha-icon{--mdc-icon-size:14px}
    .active{color:#7bdcfa}.warning{color:#fbc56d}.danger{color:#ffa1a1}.context{color:#d0b4f8}.chip.active{border-color:#386f8b}.chip.warning{border-color:#846032}.chip.danger{border-color:#954f57}.chip.context{border-color:#725693}
    .detail{margin-top:10px;background:rgba(2,6,23,.35);border:1px solid rgba(148,163,184,.20);border-radius:20px;padding:14px;overflow-wrap:anywhere;backdrop-filter:blur(12px)}h3{font-size:14px;margin:3px 0 12px}h4{font-size:13px;margin:0 0 8px}p{line-height:1.5;font-size:12px;margin:6px 0;color:var(--secondary-text-color,#a8b8cb)}
    .attention{border-left:2px solid #846032;padding-left:12px;margin:16px 0 22px}.attention.danger{border-color:#954f57}.evidence{border-top:1px solid #293b4c;padding-top:8px;margin-top:8px}.inspect{font-size:11px;padding:7px 10px;min-height:44px;margin-top:6px;background:rgba(21,34,56,.65);border:1px solid #3c4c60;border-radius:9px}
    .reason{display:block;width:100%;text-align:left;border:0;border-left:2px solid #536479;background:transparent;padding:0 0 0 12px;min-height:44px;overflow-wrap:anywhere}.reason.quiet{border-left:0;padding-left:0}.reason .summary-line{display:block;font-size:12px;margin:4px 0}.reason strong{display:block;font-size:13px}.reason p{margin:4px 0}.reason .view{display:block;font-size:11px;text-decoration:underline;margin-top:6px}.compact-report{display:block;margin:8px 0}.monitoring-line{margin:5px 0}.footer{display:block;width:100%;text-align:left;margin-top:10px}.fallback{margin-top:12px}.output-context{border-top:1px solid #283748;padding:10px 0}.output-context ha-icon{--mdc-icon-size:18px;margin-right:8px}.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;border-top:1px solid #283748;padding:12px 0;font-size:12px}.row>span{align-self:center}.name{padding:0;background:none;border:0;text-align:left;font-weight:600;min-height:44px;overflow-wrap:anywhere}.name{display:flex;align-items:center;gap:8px}.name ha-icon{--mdc-icon-size:18px;flex:0 0 18px}.name span{min-width:0;overflow-wrap:anywhere}.facets,.roles{grid-column:1/-1;color:var(--secondary-text-color,#a8b8cb);font-size:11px;line-height:1.6}.coverage{border-top:1px solid #283748;padding-top:12px}.diagnostic{border-top:1px solid #283748;padding:12px 0}.context-host{margin-top:16px}.experimental{font-size:10px;opacity:.7;margin-top:10px}
    .association{border-left:2px solid #536479;margin:12px 0;padding-left:12px}.association ul{margin:6px 0;padding-left:18px;font-size:12px;line-height:1.5;overflow-wrap:anywhere}.association h4{margin-bottom:4px}
    .context-row{display:flex;gap:8px;align-items:center;justify-content:space-between;border-top:1px solid #283748;padding:5px 0;font-size:12px}.context-row .inspect{margin:0;flex:0 0 auto}dialog{overflow-wrap:anywhere;max-width:620px;width:calc(100% - 28px);max-height:85vh;color:inherit;background:#101b29;border:1px solid #536479;border-radius:20px;padding:18px;overflow:auto}dialog::backdrop{background:#000a}.dialog-top{display:flex;align-items:center;gap:12px;justify-content:space-between;position:sticky;top:-18px;background:#101b29;padding:8px 0;z-index:1}.dialog-top h3{margin:0}.catalogue-button{width:100%;text-align:left;margin-top:10px}
    @container(min-width:600px){.attention{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.evidence{border-top:0;padding-top:0;margin-top:0}}
  `;
  class HIAdaptiveOutputCard extends HTMLElement {
    _t(key,values){return message(this._hass?.language,key,values);}
    constructor(){super();this.attachShadow({mode:'open'});this._open=false;this._generation=0;this._signature=null;this._payload=null;this._build();}
    _build(){
      const style=node('style',CSS);
      this._header=node('button',undefined,'header');this._header.type='button';this._header.setAttribute('aria-controls','output-detail');
      const title=node('span',undefined,'title');title.append(icon('hvac'),node('span',this._t('outputs')));
      this._chevron=node('span',undefined,'chevron');this._chevron.setAttribute('aria-hidden','true');
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('focusable','false');
      this._path=document.createElementNS(svg.namespaceURI,'path');this._path.setAttribute('d','M7.41 8.59 12 13.17 16.59 8.59 18 10 12 16 6 10z');svg.append(this._path);this._chevron.append(svg);title.append(this._chevron);
      this._chips=node('span',undefined,'chips');this._header.append(title,this._chips);
      this._detail=node('section',undefined,'detail');this._detail.id='output-detail';this._body=node('div');
      this._fallback=node('section',undefined,'fallback');this._fallback.hidden=true;this._detail.append(this._body,this._fallback);
      this._dialog=node('dialog');this._dialog.setAttribute('aria-labelledby','output-dialog-title');
      const bar=node('div',undefined,'dialog-top');const heading=node('h3',this._t('outputs_controls'));heading.id='output-dialog-title';this._dialogTitle=heading;
      this._dialogClose=node('button',this._t('close'),'inspect');this._dialogClose.type='button';this._dialogClose.dataset.focusKey='dialog-close';this._dialogClose.onclick=()=>this._closeDetails();bar.append(heading,this._dialogClose);
      this._dialogBody=node('div');this._native=node('div',undefined,'context-host');this._native.id='output-native-controls';this._native.tabIndex=-1;
      this._evidence=node('section');this._evidence.tabIndex=-1;this._sources=node('section');this._sources.tabIndex=-1;
      this._dialogBody.append(this._evidence,this._sources);
      // Native host never belongs to a replaceChildren evidence subtree.
      this._dialog.append(bar,this._native,this._dialogBody);
      this._dialog.addEventListener('close',()=>{if(!this._dialog.open){this._cancelIdle('details');this._stopIdleIfClosed();}if(this._skipCloseFocus){this._skipCloseFocus=false;return;}if(!this._dialog.open)this._restoreFocus();});
      this._dialog.addEventListener('click',event=>{if(event.target===this._dialog){const r=this._dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)this._closeDetails();}});
      this._fallbackClose=node('button',this._t('close'),'inspect');this._fallbackClose.type='button';this._fallbackClose.onclick=()=>this._closeDetails();
      // Before HA receives a native more-info event, dismiss our modal and focus
      // its outside opener so HA can restore to a usable target on dismissal.
      this.addEventListener('hass-more-info',()=>{if(this._dialog.open||this._inline){this._closeDetails(false);this._restoreFocus();}});
      this.shadowRoot.append(style,this._header,this._detail,this._dialog);
      this._header.onclick=()=>{this._open=!this._open;this._expanded();};this._expanded();
    }
    connectedCallback(){if(this._config&&!this._nativeCard){this._generation++;this._mountNative(this._generation);}}
    disconnectedCallback(){this._generation++;this._collapseIdle();}
    _cancelIdle(kind){
      this._idleVersions??={};this._idleVersions[kind]=(this._idleVersions[kind]||0)+1;
      this._idleTimers??={};clearTimeout(this._idleTimers[kind]);delete this._idleTimers[kind];
    }
    _renewIdle(kind){
      this._cancelIdle(kind);const version=this._idleVersions[kind];
      this._idleTimers[kind]=setTimeout(()=>{
        if(this._idleVersions[kind]!==version)return;
        if(kind==='expansion'){const focused=this.shadowRoot.activeElement;const restore=focused&&(this._detail.contains(focused)||this._dialog.contains(focused));this._open=false;this._expanded();if(restore&&this.isConnected)this._header.focus();}
        else this._closeDetails();
      },120000);
    }
    _collapseIdle(){this._open=false;this._expanded();this._cancelIdle('expansion');this._cancelIdle('details');this._stopIdleIfClosed();}
    _bindIdleConnection(){
      const connection=this._hass?.connection;
      if(this._idleConnection===connection)return;
      this._idleConnection?.removeEventListener?.('disconnected',this._idleNavigation);
      this._idleConnection=connection;
      connection?.addEventListener?.('disconnected',this._idleNavigation);
    }
    _ensureIdle(){
      if(this._idleActivity)return;
      this._idleNavigation=()=>this._collapseIdle();
      this._idleActivity=event=>{
        if(event.isTrusted!==true)return;
        const now=Date.now();
        // Programmatic focus/scroll during passive rendering is not activity.
        if(event.type==='scroll'){if(this._idleIntentAt===undefined||now-this._idleIntentAt>1000)return;}
        else this._idleIntentAt=now;
        if(this._open)this._renewIdle('expansion');
        const path=event.composedPath?.()||[];
        if((this._dialog.open||this._inline)&&(path.includes(this._dialog)||path.includes(this._fallback)))this._renewIdle('details');
      };
      this._idleEvents=['pointerdown','pointermove','touchstart','touchmove','keydown','wheel','scroll','click','input'];
      for(const name of this._idleEvents)this.shadowRoot.addEventListener(name,this._idleActivity,{capture:true,passive:true});
      for(const name of ['location-changed','popstate','pagehide'])window.addEventListener(name,this._idleNavigation);
      this._bindIdleConnection();
    }
    _stopIdleIfClosed(){
      if(this._open||this._dialog.open||this._inline||!this._idleActivity)return;
      for(const name of this._idleEvents)this.shadowRoot.removeEventListener(name,this._idleActivity,true);
      for(const name of ['location-changed','popstate','pagehide'])window.removeEventListener(name,this._idleNavigation);
      this._idleConnection?.removeEventListener?.('disconnected',this._idleNavigation);
      this._idleConnection=null;this._idleActivity=null;this._idleIntentAt=undefined;
    }
    _restoreFocus(){if(!this.isConnected)return;const target=this._open&&this._body.querySelector('[data-focus-key="'+(this._openerKey||'outputs-controls')+'"]');(target||this._header).focus();}
    _closeDetails(restore=true){
      this._cancelIdle('details');
      if(this._dialog.open){this._skipCloseFocus=!restore;this._dialog.close();}
      if(this._inline){this._inline=false;this._dialog.append(this._native,this._dialogBody);this._fallback.replaceChildren();this._fallback.hidden=true;if(restore)this._restoreFocus();}
      this._stopIdleIfClosed();
    }
    _openDetails(section,openerKey){
      this._openerKey=openerKey;
      const target=section==='controls'?this._native:section==='monitoring'?this._sources:this._evidence;
      if(!this._inline){try{if(!this._dialog.open)this._dialog.showModal();}catch(error){
        this._inline=true;this._fallback.hidden=false;this._fallback.append(this._fallbackClose,this._native,this._dialogBody);
      }}
      target.scrollIntoView?.({block:'start'});target.focus();
      this._ensureIdle();this._renewIdle('details');if(this._open)this._renewIdle('expansion');
    }
    _expanded(){if(!this._open){this._cancelIdle('expansion');this._closeDetails(false);}else{this._ensureIdle();this._renewIdle('expansion');}this._header.setAttribute('aria-expanded',String(this._open));this._detail.hidden=!this._open;this._path.setAttribute('transform',this._open?'rotate(180 12 12)':'');}
    setConfig(config){
      if(!config||!entityId(config.entity))throw new Error('HI Adaptive Output requires a backend sensor entity.');
      if(config.control_context&&config.control_context.type!=='entities')throw new Error('Control context must retain the native entities card.');
      this._collapseIdle();this._config={...config};this._signature=null;this._generation++;this._mountNative(this._generation);this._render();
    }
    set hass(hass){this._hass=hass;if(this._idleActivity){this._bindIdleConnection();if(hass?.connected===false||hass?.connection?.connected===false)this._collapseIdle();}if(this._nativeCard)this._nativeCard.hass=hass;this._render();}
    get hass(){return this._hass;}
    getCardSize(){return this._open?4:2;}
    async _mountNative(generation){
      this._native.replaceChildren();this._nativeCard=null;if(!this._config.control_context){this._native.append(node('p',this._t('controls_unavailable'),'warning'));return;}
      this._native.append(node('h3',this._t('controls')));
      try{if(typeof window.loadCardHelpers!=='function')throw new Error('Card helpers unavailable');const helpers=await window.loadCardHelpers();if(generation!==this._generation)return;const card=helpers.createCardElement(this._config.control_context);card.hass=this._hass;this._nativeCard=card;this._native.append(card);}
      catch(error){if(generation===this._generation)this._native.append(node('p',this._t('controls_unavailable'),'warning'));}
    }
    _moreInfo(id){if(entityId(id))this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true}));}
    _inspect(label,id){if(!entityId(id))return null;const b=node('button',label,'inspect');b.type='button';b.dataset.focusKey='inspect:'+id+':'+label;b.onclick=()=>this._moreInfo(id);return b;}
    _compact(p){
      const c=p.compact;
      return object(c)&&c.schema_version===1&&textFields(c,['title','tone','remainder_label'])&&
        list(c.monitoring_lines,v=>typeof v==='string',128)&&list(c.context_lines,v=>typeof v==='string',128)&&
        ['condition_count','affected_output_count','shown_condition_count','remaining_condition_count'].every(k=>Number.isInteger(c[k])&&c[k]>=0)&&
        c.condition_count===p.attention.length&&c.shown_condition_count===Math.min(2,p.attention.length)&&c.remaining_condition_count===Math.max(0,p.attention.length-2)&&
        c.affected_output_count===p.counts.affected?c:null;
    }
    _renderDetails(p){
      const focused=this._dialogBody.contains(this.shadowRoot.activeElement)?this.shadowRoot.activeElement?.dataset?.focusKey:null;
      this._evidence.replaceChildren();
      if(!p){this._evidence.append(node('h3',this._t('monitoring_unavailable')),node('p',this._t('feed_unavailable')));this._sources.replaceChildren();}
      else{
        this._evidence.append(node('h3',p.attention.length?p.attention_label:p.summary));
        for(const a of p.attention){const article=node('article',undefined,'attention '+tone(a.tone));article.append(node('h4',a.label+' · '+a.title),node('p',a.action),node('p',this._t('evidence')+' · '+a.evidence));if(a.scope_label)article.append(node('p',a.scope_label));if(a.source)article.append(node('p',this._t('source')+' · '+a.source));const inspect=this._inspect(this._t('inspect_evidence',{label:a.label}),a.source||a.entity_id);if(inspect)article.append(inspect);this._evidence.append(article);}
        this._evidence.append(node('h3',this._t('control_context')));
        if(p.context_notice)this._evidence.append(node('p',p.context_notice,'warning'));
        for(const c of p.runtime_context||[]){const row=node('div',undefined,'context-row');row.append(node('span',c.label+' · '+c.state));const inspect=this._inspect(this._t('inspect')+' '+c.label,c.source);if(inspect)row.append(inspect);this._evidence.append(row);if(c.state==='unknown')this._evidence.append(node('p',c.detail,'warning'));}
        // Context only, not a second custom control roster; the native card above
        // is the sole complete output inventory/control surface.
        for(const r of p.records){const section=node('section',undefined,'output-context');const title=node('h4');title.append(icon(r.device_icon||'devices'),node('span',r.label));section.append(title,node('p',r.configured_roles?r.configured_roles.map(v=>v.label).join(' · '):r.roles.join(' · ').replaceAll('_',' ')),node('p',[r.availability?.label,r.isolation?.label,r.monitoring?.label,r.platform_action?.label].filter(Boolean).join(' · ')));if(r.context)section.append(node('p',r.context));if(r.role_context)section.append(node('p',r.role_context));this._evidence.append(section);}
        this._catalogueObservation=p.observation?.detail||null;this._renderCatalogue(p.discovery?.sources||[],p);
      }
      if(focused&&(this._dialog.open||this._inline)){const target=[...this._dialogBody.querySelectorAll('[data-focus-key]')].find(n=>n.dataset.focusKey===focused);(target||(this._inline?this._fallbackClose:this._dialogClose)).focus();}
    }
    _renderCatalogue(sources,p){

      this._sources.replaceChildren(node('h3',p.coverage.label),node('p',p.coverage.detail));
      const d=p.discovery;if(d){this._sources.append(node('p',d.detail));for(const text of [d.setup_notice,d.lost_notice].filter(Boolean))this._sources.append(node('p',text));for(const g of d.gaps||[])this._sources.append(node('p',g.output_label+' · '+g.label+' · '+g.detail,'warning'));for(const n of d.notices||[])this._sources.append(node('p',n.output_label+' · '+n.title+' · '+n.reason));this._sources.append(node('h3',this._t('diagnostic_sources')+' · '+sources.length));}
      if(this._catalogueObservation)this._sources.append(node('p',this._catalogueObservation,'observation'));
      for(const source of sources){const row=node('article',undefined,'diagnostic');row.append(node('h4',source.label+' · '+source.title,tone(source.tone)),node('p',this._t('reported_state')+' · '+source.state),node('p',source.association_label),node('p',source.reason),node('p',source.scope_label));if(source.observation){for(const [key,label] of [['last_reported','ha_reported'],['last_updated','ha_updated'],['last_changed','ha_changed']]){if(source.observation[key])row.append(node('p',this._t(label)+' · '+source.observation[key]));}if(typeof source.observation.restored==='boolean')row.append(node('p',this._t('restored')+' · '+this._t(source.observation.restored?'yes':'no')));}for(const association of source.associations||[]){
          const detail=node('section',undefined,'association');
          detail.append(node('h4',association.label+' · '+association.title));
          if(association.origin_label)detail.append(node('p',association.origin_label));
          if(association.meaning_label)detail.append(node('p',association.meaning_label));
          if(association.rule_summary)detail.append(node('p',association.rule_summary));
          if(association.rule_lines?.length){const rules=node('ul');for(const line of association.rule_lines)rules.append(node('li',line));detail.append(rules);}
          detail.append(node('p',association.reason),node('p',association.scope_label));row.append(detail);
        }
        const id=source.source||source.entity_id||source.source_entity_id;const inspect=this._inspect(this._t('inspect_diagnostic',{label:source.label}),id);if(inspect){inspect.onclick=()=>this._moreInfo(id);row.append(inspect);}this._sources.append(row);}
    }
    _render(){
      if(!this._config)return;
      const feed=this._hass?.states?.[this._config.entity],p=feed?.attributes?.payload;
      const valid=this._hass?.connected!==false&&feed&&!['unknown','unavailable'].includes(feed.state)&&validPayload(p);
      const signature=valid?JSON.stringify(p):'unavailable';if(signature===this._signature)return;this._signature=signature;
      const focusKey=this._body.contains(this.shadowRoot.activeElement)?this.shadowRoot.activeElement?.dataset?.focusKey:null;
      this._chips.replaceChildren();this._body.replaceChildren();this._payload=valid?p:null;
      if(!valid){this._chips.append(node('span',this._t('status_unavailable'),'chip warning'));this._body.append(node('h3',this._t('monitoring_unavailable')),node('p',this._t('feed_unavailable')));}
      else{
        const c=this._compact(p);
        // Compact aggregate preserves multi-condition totals while using two
        // chips. Legacy payloads retain their entire backend overflow summary.
        const chips=c?[...p.chips.slice(0,1),...(p.chips[0]?.label===c.title?[]:[{label:c.title,tone:c.tone,icon:'information-outline'}])]:p.chips;
        for(const chip of chips){const el=node('span',undefined,'chip '+tone(chip.tone));el.append(icon(chip.kind==='fleet'?'hvac':chip.icon),node('span',chip.label));this._chips.append(el);}
        const reason=node('button',undefined,'reason '+(p.attention.length?'':'quiet ')+tone(c?.tone));reason.type='button';reason.dataset.focusKey='output-reason';reason.setAttribute('aria-haspopup','dialog');
        reason.append(node('strong',c?.title||(p.attention.length?p.attention_label:p.summary)));
        for(const a of p.attention.slice(0,2)){const report=node('span',undefined,'compact-report '+tone(a.tone));report.append(node('strong',a.label+' · '+a.title),node('span',a.action));reason.append(report);}
        if(c?.remainder_label)reason.append(node('span',c.remainder_label,'summary-line'));
        if(!c&&p.attention.length>2)reason.append(node('span',this._t('shown_reports',{shown:2,total:p.attention.length}),'summary-line'));
        reason.append(node('span',p.attention.length>2?this._t('view_conditions',{count:p.attention.length}):this._t('review_link'),'view'));
        reason.setAttribute('aria-label',reason.textContent);
        reason.onclick=()=>this._openDetails(p.attention.length?'evidence':'monitoring','output-reason');this._body.append(reason);
        const lines=c?[...c.monitoring_lines,...c.context_lines]:[p.coverage.label+' · '+p.coverage.detail,p.context_notice,p.discovery?.setup_notice,p.discovery?.lost_notice,...p.records.map(r=>r.context),...(p.runtime_context||[]).map(v=>v.label+' · '+v.state),...p.records.flatMap(r=>(r.configured_roles||[]).map(v=>r.label+' · '+v.label))].filter(Boolean);
        for(const line of new Set(lines))this._body.append(node('p',line,'monitoring-line'));
      }
      const footer=node('button',this._t('outputs_controls')+(valid?' · '+p.counts.configured:''),'inspect footer');footer.type='button';footer.dataset.focusKey='outputs-controls';footer.setAttribute('aria-haspopup','dialog');footer.onclick=()=>this._openDetails('controls','outputs-controls');this._body.append(footer);
      this._renderDetails(this._payload);
      if(focusKey){const target=[...this._body.querySelectorAll('[data-focus-key]')].find(n=>n.dataset.focusKey===focusKey);(target||footer).focus();}
    }
  }
  if(!customElements.get(TYPE))customElements.define(TYPE,HIAdaptiveOutputCard);
  window.customCards=window.customCards||[];if(!window.customCards.some(c=>c.type===TYPE))window.customCards.push({type:TYPE,name:'HI Adaptive Output',description:'Backend-owned output observation and native controls.'});
})();
