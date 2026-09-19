/* Optional HI output display. All status comes from the backend feed.
 * Native HA entities remain a separate child card; this card writes no services.
 */
(() => {
  const TYPE = 'hi-adaptive-output-card';
  // Shipped translations only. Unsupported HA locales use reviewed English copy.
  // Backend observation strings remain backend-owned; this dictionary owns chrome.
  const MESSAGES = Object.freeze({en:Object.freeze({
    outputs:'Outputs', diagnostic_sources:'Diagnostic sources', close:'Close',
    controls:'Controls and supporting readings',
    controls_unavailable:'Native controls unavailable. Reload the dashboard to retry.',
    catalogue_unavailable:'Diagnostic sources unavailable',
    status_unavailable:'Output status unavailable', monitoring_unavailable:'Monitoring unavailable',
    feed_unavailable:'The output-status feed is missing or unavailable. No cached output or device-health claims are shown. Existing native controls remain below.',
    configured_outputs:'Configured outputs', control_context:'Control context', inspect:'Inspect',
    unknown:'Unknown', evidence:'Evidence', source:'Source', reported_state:'Reported state',
    ha_reported:'HA last reported', ha_updated:'HA last updated', ha_changed:'HA last changed',
    restored:'HA restored state', yes:'Yes', no:'No',
    inspect_evidence:'Inspect {label} evidence', inspect_diagnostic:'Inspect {label} diagnostic',
    open_controls:'Open {label} controls', inspect_sources:'Inspect {count} diagnostic sources',
    preview:'Synthetic rendering harness · No live Home Assistant data',
    observation:'Output observation · Home Assistant state evidence'
  })});
  const message = (language,key,values={}) => {
    const locale=String(language||'en').toLowerCase().split('-')[0];
    const text=(MESSAGES[locale]||MESSAGES.en)[key]||MESSAGES.en[key]||key;
    return text.replace(/\{([a-z]+)\}/g,(_,name)=>String(values[name]??''));
  };

  const entityId = value => typeof value === 'string' && /^[a-z_]+\.[a-z0-9_]+$/.test(value);
  const node = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n; };
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
    :host{display:block;container-type:inline-size;color:var(--primary-text-color,#e2e8f0);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}*{box-sizing:border-box}[hidden]{display:none!important}
    button{font:inherit;color:inherit;cursor:pointer}button:focus-visible{outline:2px solid var(--primary-color,#7dd3fc);outline-offset:3px}
    .header{width:100%;text-align:left;border:2px solid rgba(148,163,184,.18);border-radius:22px;padding:12px 14px;background:rgba(10,12,16,.62);box-shadow:0 0 18px rgba(148,163,184,.18);backdrop-filter:blur(12px)}
    .title{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:900;letter-spacing:.2px}.title>ha-icon{--mdc-icon-size:18px;color:#94a3b8}
    .chevron{margin-left:auto;margin-top:2px;align-self:flex-start;flex:0 0 25px;width:25px;height:25px;display:grid;place-items:center;border-radius:999px;background:rgba(15,23,42,.85);box-shadow:0 0 12px rgba(148,163,184,.45);color:#94a3b8;pointer-events:none}.chevron svg{display:block;width:18px;height:18px;fill:currentColor}.header[aria-expanded=true] .chevron{color:#4ade80}
    .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;line-height:1.4;padding:4px 8px;border:1px solid #3b4b60;border-radius:99px;color:#c5d3e1;overflow-wrap:anywhere;max-width:100%}.chip ha-icon{--mdc-icon-size:14px}
    .active{color:#7bdcfa}.warning{color:#fbc56d}.danger{color:#ffa1a1}.context{color:#d0b4f8}.chip.active{border-color:#386f8b}.chip.warning{border-color:#846032}.chip.danger{border-color:#954f57}.chip.context{border-color:#725693}
    .detail{margin-top:10px;background:rgba(2,6,23,.35);border:1px solid rgba(148,163,184,.20);border-radius:20px;padding:14px;overflow-wrap:anywhere;backdrop-filter:blur(12px)}h3{font-size:14px;margin:3px 0 12px}h4{font-size:13px;margin:0 0 8px}p{line-height:1.5;font-size:12px;margin:6px 0;color:var(--secondary-text-color,#a8b8cb)}
    .attention{border-left:2px solid #846032;padding-left:12px;margin:16px 0 22px}.attention.danger{border-color:#954f57}.evidence{border-top:1px solid #293b4c;padding-top:8px;margin-top:8px}.inspect{font-size:11px;padding:7px 10px;min-height:44px;margin-top:6px;background:rgba(21,34,56,.65);border:1px solid #3c4c60;border-radius:9px}
    .row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;border-top:1px solid #283748;padding:12px 0;font-size:12px}.row>span{align-self:center}.name{padding:0;background:none;border:0;text-align:left;font-weight:600;min-height:44px;overflow-wrap:anywhere}.name{display:flex;align-items:center;gap:8px}.name ha-icon{--mdc-icon-size:18px;flex:0 0 18px}.name span{min-width:0;overflow-wrap:anywhere}.facets,.roles{grid-column:1/-1;color:var(--secondary-text-color,#a8b8cb);font-size:11px;line-height:1.6}.coverage{border-top:1px solid #283748;padding-top:12px}.diagnostic{border-top:1px solid #283748;padding:12px 0}.context-host{margin-top:16px}.experimental{font-size:10px;opacity:.7;margin-top:10px}
    .association{border-left:2px solid #536479;margin:12px 0;padding-left:12px}.association ul{margin:6px 0;padding-left:18px;font-size:12px;line-height:1.5;overflow-wrap:anywhere}.association h4{margin-bottom:4px}
    .context-row{display:flex;gap:8px;align-items:center;justify-content:space-between;border-top:1px solid #283748;padding:5px 0;font-size:12px}.context-row .inspect{margin:0;flex:0 0 auto}dialog{overflow-wrap:anywhere;max-width:620px;width:calc(100% - 28px);max-height:85vh;color:inherit;background:#101b29;border:1px solid #536479;border-radius:20px;padding:18px;overflow:auto}dialog::backdrop{background:#000a}.dialog-top{display:flex;align-items:center;gap:12px;justify-content:space-between;position:sticky;top:-18px;background:#101b29;padding:8px 0;z-index:1}.dialog-top h3{margin:0}.catalogue-button{width:100%;text-align:left;margin-top:10px}
    @container(min-width:600px){.attention{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.evidence{border-top:0;padding-top:0;margin-top:0}}
  `;
  class HIAdaptiveOutputCard extends HTMLElement {
    _t(key,values){return message(this._hass?.language,key,values);}
    constructor(){super();this.attachShadow({mode:'open'});this._open=false;this._generation=0;this._signature=null;this._build();}
    _build(){
      const style=node('style',CSS);this._header=node('button',undefined,'header');this._header.type='button';this._header.setAttribute('aria-controls','output-detail');
      const title=node('span',undefined,'title');title.append(icon('devices'),node('span',this._t('outputs')));this._chevron=node('span',undefined,'chevron');this._chevron.setAttribute('aria-hidden','true');
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('focusable','false');this._path=document.createElementNS(svg.namespaceURI,'path');this._path.setAttribute('d','M7.41 8.59 12 13.17 16.59 8.59 18 10 12 16 6 10z');svg.append(this._path);this._chevron.append(svg);title.append(this._chevron);this._chips=node('span',undefined,'chips');this._header.append(title,this._chips);
      this._detail=node('section',undefined,'detail');this._detail.id='output-detail';this._body=node('div');this._native=node('div',undefined,'context-host');this._detail.append(this._body,this._native);this._dialog=node('dialog');this._dialog.setAttribute('aria-labelledby','diagnostic-title');const bar=node('div',undefined,'dialog-top');const heading=node('h3',this._t('diagnostic_sources'));heading.id='diagnostic-title';this._dialogTitle=heading;this._dialogClose=node('button',this._t('close'),'inspect');this._dialogClose.type='button';this._dialogClose.dataset.focusKey='dialog-close';this._dialogClose.onclick=()=>this._dialog.close();bar.append(heading,this._dialogClose);this._dialogBody=node('div');this._dialog.append(bar,this._dialogBody);this._dialog.addEventListener('close',()=>{if(this._openingMoreInfo){this._openingMoreInfo=false;return;}const trigger=this._body.querySelector('[data-focus-key=diagnostic-catalogue]');(trigger||this._header).focus();});this._dialog.addEventListener('click',event=>{if(event.target===this._dialog){const r=this._dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)this._dialog.close();}});this.shadowRoot.append(style,this._header,this._detail,this._dialog);this._header.onclick=()=>{this._open=!this._open;this._expanded();};this._expanded();
    }
    _expanded(){if(!this._open&&this._dialog?.open)this._dialog.close();this._header.setAttribute('aria-expanded',String(this._open));this._detail.hidden=!this._open;this._path.setAttribute('transform',this._open?'rotate(180 12 12)':'');}
    setConfig(config){if(!config||!entityId(config.entity))throw new Error('HI Adaptive Output requires a backend sensor entity.');if(config.control_context&&config.control_context.type!=='entities')throw new Error('Control context must retain the native entities card.');this._config={...config};this._signature=null;this._generation++;this._mountNative(this._generation);this._render();}
    set hass(hass){this._hass=hass;if(this._nativeCard)this._nativeCard.hass=hass;this._render();}
    get hass(){return this._hass;}
    getCardSize(){return this._open?8:2;}
    async _mountNative(generation){
      this._native.replaceChildren();this._nativeCard=null;if(!this._config.control_context)return;
      this._native.append(node('h3',this._t('controls')));
      try{if(typeof window.loadCardHelpers!=='function')throw new Error('Card helpers unavailable');const helpers=await window.loadCardHelpers();if(generation!==this._generation)return;const card=helpers.createCardElement(this._config.control_context);card.hass=this._hass;this._nativeCard=card;this._native.append(card);}
      catch(error){if(generation===this._generation)this._native.append(node('p',this._t('controls_unavailable'),'warning'));}
    }
    _moreInfo(id){if(entityId(id))this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true}));}
    _inspect(label,id){if(!entityId(id))return null;const b=node('button',label,'inspect');b.type='button';b.dataset.focusKey='inspect:'+id+':'+label;b.onclick=()=>this._moreInfo(id);return b;}
    _renderCatalogue(sources){
      const focused=this._dialog.contains(this.shadowRoot.activeElement)?this.shadowRoot.activeElement?.dataset?.focusKey:null;
      this._dialogTitle.textContent=this._t('diagnostic_sources')+' · '+sources.length;this._dialogBody.replaceChildren();
      if(this._catalogueObservation)this._dialogBody.append(node('p',this._catalogueObservation,'observation'));
      for(const source of sources){const row=node('article',undefined,'diagnostic');row.append(node('h4',source.label+' · '+source.title,tone(source.tone)),node('p',this._t('reported_state')+' · '+source.state),node('p',source.association_label),node('p',source.reason),node('p',source.scope_label));if(source.observation){for(const [key,label] of [['last_reported','ha_reported'],['last_updated','ha_updated'],['last_changed','ha_changed']]){if(source.observation[key])row.append(node('p',this._t(label)+' · '+source.observation[key]));}if(typeof source.observation.restored==='boolean')row.append(node('p',this._t('restored')+' · '+this._t(source.observation.restored?'yes':'no')));}for(const association of source.associations||[]){
          const detail=node('section',undefined,'association');
          detail.append(node('h4',association.label+' · '+association.title));
          if(association.origin_label)detail.append(node('p',association.origin_label));
          if(association.meaning_label)detail.append(node('p',association.meaning_label));
          if(association.rule_summary)detail.append(node('p',association.rule_summary));
          if(association.rule_lines?.length){const rules=node('ul');for(const line of association.rule_lines)rules.append(node('li',line));detail.append(rules);}
          detail.append(node('p',association.reason),node('p',association.scope_label));row.append(detail);
        }
        const id=source.source||source.entity_id||source.source_entity_id;const inspect=this._inspect(this._t('inspect_diagnostic',{label:source.label}),id);if(inspect){inspect.onclick=()=>{this._openingMoreInfo=true;this._dialog.close();this._moreInfo(id);};row.append(inspect);}this._dialogBody.append(row);}
      if(focused&&this._dialog.open){const target=[...this._dialog.querySelectorAll('[data-focus-key]')].find(n=>n.dataset.focusKey===focused);(target||this._dialogClose).focus();}
    }
    _render(){
      if(!this._config)return;const feed=this._hass?.states?.[this._config.entity];const p=feed?.attributes?.payload;
      const valid=this._hass?.connected!==false&&feed&&!['unknown','unavailable'].includes(feed.state)&&validPayload(p);
      const signature=valid?JSON.stringify(p):'unavailable';if(signature===this._signature)return;this._signature=signature;const focusKey=this.shadowRoot.activeElement?.dataset?.focusKey;this._chips.replaceChildren();this._body.replaceChildren();
      if(!valid){if(this._dialog.open)this._dialog.close();this._catalogueSources=[];this._catalogueObservation=null;this._dialogBody.replaceChildren();this._dialogTitle.textContent=this._t('catalogue_unavailable');this._chips.append(node('span',this._t('status_unavailable'),'chip warning'));this._body.append(node('h3',this._t('monitoring_unavailable')),node('p',this._t('feed_unavailable')));if(focusKey)this._header.focus();return;}
      for(const c of p.chips){const chip=node('span',undefined,'chip '+tone(c.tone));chip.append(icon(c.icon),node('span',c.label));this._chips.append(chip);}
      this._body.append(node('h3',p.attention.length?p.attention_label:p.summary));
      for(const a of p.attention){const article=node('article',undefined,'attention '+tone(a.tone));const what=node('div');what.append(node('h4',a.label+' · '+a.title),node('p',a.action));const evidence=node('div',undefined,'evidence');evidence.append(node('p',this._t('evidence')+' · '+a.evidence));if(a.scope_label)evidence.append(node('p',a.scope_label));if(a.source)evidence.append(node('p',this._t('source')+' · '+a.source));const inspect=this._inspect(this._t('inspect_evidence',{label:a.label}),a.source||a.entity_id);if(inspect)evidence.append(inspect);article.append(what,evidence);this._body.append(article);}
      this._body.append(node('h3',this._t('configured_outputs')+' · '+p.counts.configured));const sharedContexts=new Set(p.records.map(r=>r.context).filter(c=>typeof c==='string'&&c&&p.records.filter(r=>r.context===c).length>1));
      for(const r of p.records){const row=node('div',undefined,'row');const name=node('button',undefined,'name');name.append(icon(r.device_icon||'devices'),node('span',r.label));name.type='button';name.dataset.focusKey='output:'+r.entity_id;name.setAttribute('aria-label',this._t('open_controls',{label:r.label}));name.onclick=()=>this._moreInfo(r.entity_id);row.append(name,node('span',r.operation?.label||this._t('unknown'),''+tone(r.operation?.tone)));row.append(node('div',r.configured_roles?r.configured_roles.map(role=>role.label).join(' · '):(r.roles||[]).join(' · ').replaceAll('_',' '),'roles'));row.append(node('div',[r.availability?.label,r.isolation?.label,r.monitoring?.label,r.platform_action?.label].filter(Boolean).join(' · '),'facets'));if(r.context&&!sharedContexts.has(r.context))row.append(node('p',r.context));this._body.append(row);}
      for(const context of sharedContexts)this._body.append(node('p',context));
      for(const context of new Set(p.records.map(r=>r.role_context).filter(Boolean)))this._body.append(node('p',context));
      this._body.append(node('p',p.coverage.label+' · '+p.coverage.detail,'coverage'));
      this._catalogueObservation=p.observation?.detail||null;
      const discovery=p.discovery;
      if(discovery){this._body.append(node('h3',discovery.summary),node('p',discovery.detail));if(discovery.setup_notice)this._body.append(node('p',discovery.setup_notice));if(discovery.lost_notice)this._body.append(node('p',discovery.lost_notice,'warning'));for(const g of discovery.gaps||[])this._body.append(node('p',g.output_label+' · '+g.label+' · '+g.detail,'warning'));for(const n of discovery.notices||[])this._body.append(node('p',n.output_label+' · '+n.title+' · '+n.reason));const sources=discovery.sources||[];const inspect=node('button',this._t('inspect_sources',{count:sources.length}),'inspect catalogue-button');inspect.type='button';inspect.dataset.focusKey='diagnostic-catalogue';inspect.setAttribute('aria-haspopup','dialog');inspect.onclick=()=>{this._renderCatalogue(this._catalogueSources||[]);this._dialog.showModal();this._dialogClose.focus();};this._body.append(inspect);this._catalogueSources=sources;if(this._dialog.open)this._renderCatalogue(sources);}
      else{this._catalogueSources=[];if(this._dialog.open)this._renderCatalogue([]);}
      if(Array.isArray(p.runtime_context)){this._body.append(node('h3',this._t('control_context')));if(p.context_notice)this._body.append(node('p',p.context_notice,'warning'));for(const c of p.runtime_context){const row=node('div',undefined,'context-row');row.append(node('span',c.label+' · '+c.state));const inspect=this._inspect(this._t('inspect'),c.source);if(inspect){inspect.setAttribute('aria-label',this._t('inspect')+' '+c.label);inspect.dataset.focusKey='context:'+c.key;row.append(inspect);}this._body.append(row);if(c.state==='unknown')this._body.append(node('p',c.detail,'warning'));}}
      this._body.append(node('p',this._config.preview===true?this._t('preview'):this._t('observation'),'experimental'));if(focusKey){const target=[...this.shadowRoot.querySelectorAll('[data-focus-key]')].find(n=>n.dataset.focusKey===focusKey);(target||(this._dialog.open?this._dialogClose:this._header)).focus();}
    }
  }
  if(!customElements.get(TYPE))customElements.define(TYPE,HIAdaptiveOutputCard);
  window.customCards=window.customCards||[];if(!window.customCards.some(c=>c.type===TYPE))window.customCards.push({type:TYPE,name:'HI Adaptive Output',description:'Backend-owned output observation and native controls.'});
})();
