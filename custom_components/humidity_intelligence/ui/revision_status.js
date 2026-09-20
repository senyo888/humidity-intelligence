/* Canonical read-only UI revision indicator, embedded into generated cards.
 * Declared revisions describe the renderer, not cache health or arbitrary edits.
 */
const hiUiRevision = (() => {
  // HI-INACTIVITY:START
  /* Self-contained inactivity custody for HI-owned details; no runtime writes. */
  function hiDialogInactivity(dialog, owner, close, connection) {
    const idleMs = 120000;
    const activity = ['pointerdown', 'touchstart', 'touchmove', 'keydown', 'input', 'wheel', 'scroll'];
    const navigation = ['location-changed', 'popstate', 'pagehide'];
    let timer, generation = 0, disposed = false, lastIntent = -Infinity;
    const observer = new MutationObserver(() => {
      if (!owner.isConnected || !dialog.isConnected) finish();
    });
    function dispose() {
      if (disposed) return;
      disposed = true; generation++; clearTimeout(timer);
      observer.disconnect();
      for (const name of activity) dialog.removeEventListener(name, interact, true);
      for (const name of navigation) window.removeEventListener(name, finish);
      connection?.removeEventListener?.('disconnected', finish);
      dialog.removeEventListener('close', dispose);
    }
    function finish() {
      if (disposed) return;
      dispose(); close();
    }
    function arm() {
      if (disposed) return;
      clearTimeout(timer); const current = ++generation;
      timer = setTimeout(() => {
        if (!disposed && current === generation) finish();
      }, idleMs);
    }
    function interact(event) {
      // Programmatic clicks/keyboard dispatch and telemetry never extend custody.
      if (event.isTrusted !== true) return;
      // Browser-generated scroll can follow programmatic focus/telemetry changes.
      // Only count it in the wake of actual input within this panel.
      if (event.type === 'scroll') {
        if (Date.now() - lastIntent <= 1000) arm();
      } else {
        lastIntent = Date.now(); arm();
      }
    }
    for (const name of activity) dialog.addEventListener(name, interact, {capture:true, passive:name !== 'keydown'});
    for (const name of navigation) window.addEventListener(name, finish);
    connection?.addEventListener?.('disconnected', finish);
    dialog.addEventListener('close', dispose);
    let root = owner.getRootNode();
    while (root) {
      observer.observe(root, {childList:true, subtree:true});
      root = root.host ? root.host.getRootNode() : null;
    }
    arm();
    if (connection?.connected === false) finish();
    return dispose;
  }
  // HI-INACTIVITY:END
  const KEY = Symbol.for('humidity_intelligence.ui_revision.lifecycle.v1');
  const positive = value => Number.isSafeInteger(value) && value > 0;
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const escape = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const unknown = reason => ({kind:'unknown',label:'UI unverified',reason});
  function classify(stamp, metadata, live = false) {
    if (!live) return unknown('A live Home Assistant connection and current evidence are required.');
    if (!object(stamp) || !object(metadata) || stamp.schema !== 1 || metadata.schema !== 1) return unknown('UI revision information is missing or uses an unsupported contract.');
    if (typeof stamp.entry !== 'string' || !stamp.entry || stamp.entry !== metadata.entry) return unknown('This card cannot be matched to this integration entry.');
    if (!['v2_mobile','v2_tablet'].includes(stamp.layout) || !object(metadata.layouts) || !Object.hasOwn(metadata.layouts,stamp.layout)) return unknown('Revision information for this layout is unavailable.');
    const target = metadata.layouts[stamp.layout];
    if (!object(target) || !positive(stamp.revision) || !positive(target.revision) || stamp.generator !== 1 || target.generator !== 1 || !Array.isArray(target.supersedes) || !target.supersedes.every(value => positive(value) && value < target.revision) || new Set(target.supersedes).size !== target.supersedes.length) return unknown('The renderer revision or generator contract is unsupported.');
    if (stamp.revision === target.revision) return {kind:'current',label:'UI current',reason:'The declared renderer revision matches the UI advertised by this installed backend. Local YAML edits, mappings, options and frontend resources are not verified.'};
    if (target.supersedes.includes(stamp.revision)) return {kind:'update',label:'UI update',reason:'This backend advertises a compatible UI revision that supersedes this displayed revision.'};
    return {kind:'different',label:'UI differs',reason:'The displayed and backend-advertised revisions differ. This may be a rollback or a different revision; a newer release is not established.'};
  }
  function dispose(owner) { owner?.[KEY]?.dispose(); }
  function render(owner, hass, entity, stamp) {
    if (!owner || !owner.isConnected) return '';
    const connection = hass?.connection;
    let state = owner[KEY];
    if (state && state.connection !== connection) { state.dispose(); state = null; }
    if (!state) {
      state = {connection, blocked:connection?.connected !== true, blockedStates:hass?.states, blockedEntity:entity, ready:false, owner, hass, entity, stamp, button:null, disposed:false};
      owner[KEY] = state;
      const usable = () => !state.blocked && state.connection?.connected === true && typeof state.entity?.state === 'string' && Boolean(state.entity.state.trim()) && !['unknown','unavailable'].includes(state.entity.state);
      state.result = () => classify(state.stamp,state.entity?.attributes?.ui_revision,usable());
      state.paint = () => {
        const button = owner.shadowRoot?.querySelector('.hi-ui-revision');
        if (state.button !== button) {
          state.button?.removeEventListener('click',state.open);
          state.button = button;
          button?.addEventListener('click',state.open);
        }
        if (!button) return;
        const result=state.result();
        if (button.dataset.status !== result.kind) button.dataset.status=result.kind;
        const label=button.querySelector('.hi-ui-revision-label');
        if (label && label.textContent !== result.label) label.textContent=result.label;
        const accessible=result.label+'. Open UI revision details';
        if (button.getAttribute('aria-label') !== accessible) button.setAttribute('aria-label',accessible);
      };
      state.open = () => {
        window.__hiBadgeDetailsDispose?.(false);
        const dialog=document.createElement('dialog');
        if (typeof dialog.showModal !== 'function') {
          if (state.entity?.entity_id) owner.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:state.entity.entity_id},bubbles:true,composed:true}));
          return;
        }
        const result=state.result();
        dialog.className='hi-ui-revision-details';
        dialog.setAttribute('aria-label','UI revision details');
        const validStamp=object(state.stamp);
        const target=state.entity?.attributes?.ui_revision?.layouts?.[state.stamp?.layout];
        dialog.innerHTML=`<style>.hi-ui-revision-details{box-sizing:border-box;width:min(460px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:20px;border:1px solid #64748b;border-radius:20px;background:#0d1522;color:#e2e8f0;font:14px/1.6 system-ui,sans-serif}.hi-ui-revision-details::backdrop{background:rgba(0,0,0,.55)}.hi-ui-revision-details button{min-width:44px;min-height:44px;float:right;border:1px solid #64748b;border-radius:50%;background:#18253a;color:#e2e8f0;font:inherit}.hi-ui-revision-details button:focus-visible{outline:2px solid #38bdf8;outline-offset:2px}.hi-ui-revision-details p{overflow-wrap:anywhere}</style><button type="button" aria-label="Close" autofocus>×</button><h2>${escape(result.label)}</h2><p>${escape(result.reason)}</p><p>Displayed revision: ${validStamp && positive(state.stamp.revision)?state.stamp.revision:'Unavailable'}. Backend-advertised revision: ${positive(target?.revision)?target.revision:'Unavailable'}.</p><p>To replace the UI, export the selected layout, replace the complete Manual-card YAML, and save the dashboard. Refresh the browser or app if the old UI remains cached.</p><p>This indicator does not diagnose browser caching or confirm that a downloaded file was installed. These details are a snapshot; reopen to check again.</p>`;
        const previous=owner.shadowRoot?.activeElement || document.activeElement;
        let cleaned=false;
        let stopIdle=()=>{};
        const close=(restore=true)=>{
          if(cleaned)return;cleaned=true;
          stopIdle();
          if(dialog.open)dialog.close();dialog.remove();
          if(window.__hiBadgeDetailsDispose===close)delete window.__hiBadgeDetailsDispose;
          if(state.close===close)state.close=null;
          if(restore && owner.isConnected && previous?.isConnected)previous.focus();
        };
        state.close=close; window.__hiBadgeDetailsDispose=close;
        dialog.querySelector('button').addEventListener('click',()=>close());
        dialog.addEventListener('close',()=>close(),{once:true});
        dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const b=dialog.getBoundingClientRect();if(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom)close();});
        document.body.appendChild(dialog);
        try {dialog.showModal();stopIdle=hiDialogInactivity(dialog,owner,close,connection);} catch (_) {close();}
      };
      // button-card's ancestor keyboard handler can consume native activation.
      // Capture only this exact footer button; leave pointer actions unchanged.
      state.keyRoot=owner.shadowRoot;
      state.keydown=event=>{
        if(!['Enter',' '].includes(event.key) || !state.button || !event.composedPath?.().includes(state.button))return;
        event.preventDefault();event.stopPropagation();
        if(!event.repeat)state.open();
      };
      state.keyRoot?.addEventListener('keydown',state.keydown,true);
      state.disconnected=()=>{state.close?.(false);state.blocked=true;state.ready=false;state.blockedStates=state.hass?.states;state.blockedEntity=state.entity;state.paint();};
      state.connected=()=>{state.ready=true;state.paint();};
      state.navigation=()=>state.dispose();
      state.observer=new MutationObserver(()=>{if(!owner.isConnected)state.dispose();else state.paint();});
      let root=owner.shadowRoot || owner.getRootNode();
      while(root){state.observer.observe(root,{childList:true,subtree:true});root=root.host?root.host.getRootNode():null;}
      state.dispose=()=>{
        if(state.disposed)return;state.disposed=true;
        state.observer.disconnect();state.close?.(false);
        state.button?.removeEventListener('click',state.open);
        state.keyRoot?.removeEventListener('keydown',state.keydown,true);
        connection?.removeEventListener?.('disconnected',state.disconnected);
        connection?.removeEventListener?.('ready',state.connected);
        for(const name of ['location-changed','popstate','pagehide'])window.removeEventListener(name,state.navigation);
        if(owner[KEY]===state)delete owner[KEY];
      };
      connection?.addEventListener?.('disconnected',state.disconnected);
      connection?.addEventListener?.('ready',state.connected);
      for(const name of ['location-changed','popstate','pagehide'])window.addEventListener(name,state.navigation);
    }
    state.hass=hass;state.entity=entity;state.stamp=stamp;
    if(connection?.connected!==true)state.disconnected();
    else if(state.blocked && state.ready && hass?.states && hass.states!==state.blockedStates && entity!==state.blockedEntity)state.blocked=false;
    const result=state.result();
    queueMicrotask(()=>{if(!state.disposed)state.paint();});
    return `<button type="button" class="hi-ui-revision" data-status="${result.kind}" aria-label="${escape(result.label)}. Open UI revision details"><span class="hi-ui-revision-led" aria-hidden="true"></span><span class="hi-ui-revision-label">${escape(result.label)}</span></button>`;
  }
  return {classify,render,dispose};
})();
