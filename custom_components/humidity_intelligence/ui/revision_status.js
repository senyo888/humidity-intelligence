/* Canonical read-only UI revision and HACS observation footer.
 * Declared revisions and provider-reported updates remain independent claims.
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
  // Ancestor button-card consumes touchend and suppresses the native click.
  // Isolate this button without cancelling browser scrolling or synthesizing taps.
  const nativeEvents = ['touchstart','touchend','touchcancel','mousedown','mouseup','keyup'];
  const positive = value => Number.isSafeInteger(value) && value > 0;
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const available = entity => typeof entity?.state === 'string' && Boolean(entity.state.trim()) && !['unknown','unavailable'].includes(entity.state);
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
  const version = value => typeof value === 'string' && value.length > 0 && value.length <= 128 && value === value.trim() && !/[\p{C}\p{Z}]/u.test(value.replaceAll(' ','')) && !['unknown','unavailable'].includes(value.toLowerCase());
  const updateEntity = value => typeof value === 'string' && value.length <= 255 && /^update\.[a-z0-9_]+$/.test(value);
  const updateLabels = {
    reported_update:'Update available', no_update_reported:'No update reported',
    skipped:'Update skipped', in_progress:'HI update in progress', unverified:'Updates unverified',
  };
  function classifyUpdate(observation, live = false) {
    const unverified = {kind:'unverified',label:updateLabels.unverified,reason:'A supported HI update source and live Home Assistant evidence are required.',observation:null};
    if (!live || !object(observation) || observation.schema !== 1 || observation.provider !== 'hacs' || observation.repository !== 'senyo888/humidity-intelligence' || !Object.hasOwn(updateLabels,observation.status)) return unverified;
    if (observation.status === 'unverified') return {...unverified,reason:'HI update information is missing, unavailable or cannot be verified. UI revision status remains independent.'};
    if (!updateEntity(observation.entity_id) || !['on','off'].includes(observation.provider_state) || !version(observation.downloaded_version) || !version(observation.latest_version) || !(observation.skipped_version === null || version(observation.skipped_version))) return unverified;
    if (observation.status === 'reported_update' && observation.provider_state !== 'on') return unverified;
    if (['no_update_reported','skipped'].includes(observation.status) && observation.provider_state !== 'off') return unverified;
    if (observation.provider_state === 'on' && (observation.downloaded_version === observation.latest_version || observation.skipped_version === observation.latest_version)) return unverified;
    const skipped = observation.skipped_version !== null && observation.skipped_version === observation.latest_version && observation.downloaded_version !== observation.latest_version;
    if ((observation.status === 'skipped') !== skipped && observation.status !== 'in_progress') return unverified;
    const reasons = {
      reported_update:'HACS reports an update for Humidity Intelligence. This is the provider’s report, not an independent comparison with the code currently running.',
      no_update_reported:'HACS reports no update. This can also occur when the downloaded version is ahead of the offered version; it does not prove that the latest code is running.',
      skipped:'The release currently offered by HACS was skipped. This choice is retained; no update is installed from this card.',
      in_progress:'HACS reports an update in progress. A completed download does not establish that Home Assistant has loaded the new code.',
    };
    return {kind:observation.status,label:updateLabels[observation.status],reason:reasons[observation.status],observation};
  }
  function canViewUpdate(result, hass) {
    const observation = result.observation;
    if (!observation || hass?.connection?.connected !== true) return false;
    const entity = hass.states?.[observation.entity_id];
    return available(entity) && entity.state === observation.provider_state &&
      entity.attributes?.installed_version === observation.downloaded_version &&
      entity.attributes?.latest_version === observation.latest_version &&
      (entity.attributes?.skipped_version ?? null) === observation.skipped_version;
  }
  function dispose(owner) { owner?.[KEY]?.dispose(); }
  function render(owner, hass, entity, stamp) {
    if (!owner || !owner.isConnected) return '';
    const connection = hass?.connection;
    let state = owner[KEY];
    if (state && state.connection !== connection) { state.dispose(); state = null; }
    if (!state) {
      state = {connection, blocked:connection?.connected !== true, blockedEntity:entity, ready:false, owner, hass, entity, stamp, button:null, disposed:false};
      owner[KEY] = state;
      const usable = () => !state.blocked && state.connection?.connected === true && available(state.entity);
      state.result = () => classify(state.stamp,state.entity?.attributes?.ui_revision,usable());
      state.updateResult = () => classifyUpdate(state.entity?.attributes?.update_observation,usable());
      state.paint = () => {
        const button = owner.shadowRoot?.querySelector('.hi-ui-revision');
        if (state.button !== button) {
          state.button?.removeEventListener('click',state.activate);
          for (const name of nativeEvents) state.button?.removeEventListener(name,state.isolate);
          state.button = button;
          button?.addEventListener('click',state.activate);
          for (const name of nativeEvents) button?.addEventListener(name,state.isolate,{passive:true});
        }
        if (!button) return;
        const result=state.result();
        const update=state.updateResult();
        if (button.dataset.status !== result.kind) button.dataset.status=result.kind;
        if (button.dataset.updateStatus !== update.kind) button.dataset.updateStatus=update.kind;
        const label=button.querySelector('.hi-ui-revision-label');
        if (label && label.textContent !== result.label) label.textContent=result.label;
        const updateLabel=button.querySelector('.hi-update-label');
        const updateText=(update.kind === 'reported_update' ? '↑ ' : '')+update.label;
        if (updateLabel && updateLabel.textContent !== updateText) updateLabel.textContent=updateText;
        const accessible=result.label+'. '+update.label+'. Open UI and software versions';
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
        const update=state.updateResult();
        const observation=update.observation;
        dialog.className='hi-ui-revision-details';
        dialog.setAttribute('aria-label','UI and software versions');
        const validStamp=object(state.stamp);
        const target=state.entity?.attributes?.ui_revision?.layouts?.[state.stamp?.layout];
        dialog.innerHTML=`<style>.hi-ui-revision-details{box-sizing:border-box;width:min(460px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:20px;border:1px solid #64748b;border-radius:20px;background:#0d1522;color:#e2e8f0;font:14px/1.6 system-ui,sans-serif}.hi-ui-revision-details::backdrop{background:rgba(0,0,0,.55)}.hi-ui-revision-details button{min-width:44px;min-height:44px;border:1px solid #64748b;border-radius:10px;background:#18253a;color:#e2e8f0;font:inherit;padding:8px 12px}.hi-ui-revision-details button[aria-label="Close"]{float:right;border-radius:50%;padding:0}.hi-ui-revision-details button:focus-visible{outline:2px solid #38bdf8;outline-offset:2px}.hi-ui-revision-details p{overflow-wrap:anywhere}.hi-ui-revision-details h3{margin-bottom:4px}.hi-ui-revision-details hr{border:0;border-top:1px solid #475569;margin:20px 0}</style><button type="button" aria-label="Close" autofocus>×</button><h2>UI and software versions</h2><h3>${escape(result.label)}</h3><p>${escape(result.reason)}</p><p>Displayed revision: ${validStamp && positive(state.stamp.revision)?state.stamp.revision:'Unavailable'}. Backend-advertised revision: ${positive(target?.revision)?target.revision:'Unavailable'}.</p><p>To replace the UI, export the selected layout, replace the complete Manual-card YAML, and save the dashboard. Refresh the browser or app if the old UI remains cached.</p><hr><h3>${escape(update.label)}</h3><p>${escape(update.reason)}</p>${observation ? `<p>Source: HACS<br>HACS downloaded version: ${escape(observation.downloaded_version)}<br>HACS available version: ${escape(observation.latest_version)}${observation.skipped_version ? `<br>HACS skipped version: ${escape(observation.skipped_version)}` : ''}</p>` : ''}<p>Update information follows HACS’s selected release channel and refresh schedule. It may be cached; a fresh Internet check and the running version are not verified.</p>${canViewUpdate(update,state.hass) ? '<button type="button" data-view-update>View update</button><p data-update-action-status role="status"></p>' : ''}<p>This indicator does not diagnose browser caching or confirm that a downloaded file was installed. These details are a snapshot; reopen to check again.</p>`;
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
        if (canViewUpdate(update,state.hass)) dialog.querySelector('[data-view-update]')?.addEventListener('click',()=>{
          const current=state.updateResult();
          // A dialog snapshot must never silently retarget a renamed/replaced source.
          if (!canViewUpdate(current,state.hass) || JSON.stringify(current.observation) !== JSON.stringify(observation)) {
            const message=dialog.querySelector('[data-update-action-status]');
            if(message)message.textContent='Update information changed or is unavailable. Close and reopen these details.';
            return;
          }
          close();
          owner.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:observation.entity_id},bubbles:true,composed:true}));
        });
        dialog.addEventListener('close',()=>close(),{once:true});
        dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const b=dialog.getBoundingClientRect();if(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom)close();});
        document.body.appendChild(dialog);
        try {dialog.showModal();stopIdle=hiDialogInactivity(dialog,owner,close,connection);} catch (_) {close();}
      };
      state.isolate=event=>{
        if(event?.type==='keyup' && !['Enter',' '].includes(event.key))return;
        event?.stopPropagation();
      };
      state.activate=event=>{event?.stopPropagation();state.open();};
      // button-card's ancestor keyboard handler can consume native activation.
      // Preserve the footer's one-shot keyboard behavior, including key repeats.
      state.keyRoot=owner.shadowRoot;
      state.keydown=event=>{
        if(!['Enter',' '].includes(event.key) || !state.button || !event.composedPath?.().includes(state.button))return;
        event.preventDefault();event.stopPropagation();
        if(!event.repeat)state.open();
      };
      state.keyRoot?.addEventListener('keydown',state.keydown,true);
      state.disconnected=()=>{state.close?.(false);state.blocked=true;state.ready=false;state.blockedEntity=state.entity;state.paint();};
      state.connected=()=>{state.ready=true;state.paint();};
      state.navigation=()=>state.dispose();
      state.observer=new MutationObserver(()=>{if(!owner.isConnected)state.dispose();else state.paint();});
      let root=owner.shadowRoot || owner.getRootNode();
      while(root){state.observer.observe(root,{childList:true,subtree:true});root=root.host?root.host.getRootNode():null;}
      state.dispose=()=>{
        if(state.disposed)return;state.disposed=true;
        state.observer.disconnect();state.close?.(false);
        state.button?.removeEventListener('click',state.activate);
        for (const name of nativeEvents) state.button?.removeEventListener(name,state.isolate);
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
    // button-card keeps a persistent states Proxy across live updates. Require a
    // fresh available Diagnostics entity after ready, not a new container object.
    else if(state.blocked && state.ready && available(entity) && entity!==state.blockedEntity)state.blocked=false;
    const result=state.result();
    const update=state.updateResult();
    queueMicrotask(()=>{if(!state.disposed)state.paint();});
    return `<button type="button" class="hi-ui-revision" data-status="${result.kind}" data-update-status="${update.kind}" aria-label="${escape(result.label)}. ${escape(update.label)}. Open UI and software versions"><span class="hi-ui-revision-summary"><span class="hi-ui-revision-led" aria-hidden="true"></span><span class="hi-ui-revision-label">${escape(result.label)}</span></span><span class="hi-update-label">${update.kind === 'reported_update' ? '↑ ' : ''}${escape(update.label)}</span></button>`;
  }
  return {classify,classifyUpdate,canViewUpdate,render,dispose};
})();
