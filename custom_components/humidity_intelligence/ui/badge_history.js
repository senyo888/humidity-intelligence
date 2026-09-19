/* HI badge history: canonical source, embedded by scripts/sync_badge_history.py.
 * No network or DOM work occurs until create().open() is called by View history.
 * Historical records are observations, never control decisions or health scores.
 */
const hiBadgeHistory = (() => {
  const MAX_RESPONSE_RECORDS = 10000;
  const MAX_DISPLAY_RECORDS = 500;
  const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const text = value => typeof value === 'string' ? (value.length > 2000 ? value.slice(0, 2000) + '… [text shortened]' : value) : '';
  const numeric = value => typeof value === 'string' && NUMBER.test(value.trim()) && Number.isFinite(Number(value.trim())) ? Number(value.trim()) : null;
  const timestamp = value => typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 1000) : typeof value === 'string' ? Date.parse(value) : NaN;
  function normalize(raw, start, end, kind) {
    if (!Array.isArray(raw)) return {records: [], status: 'missing', omitted: 0};
    if (raw.length > MAX_RESPONSE_RECORDS) return {records: [], status: 'oversize', omitted: raw.length};
    let invalid = 0;
    const rows = [];
    for (const item of raw) {
      if (!item || typeof item !== 'object') { invalid++; continue; }
      // lu/last_updated is the recorded observation time, including attribute updates.
      const time = timestamp(item.lu ?? item.last_updated ?? item.lc ?? item.last_changed);
      if (!Number.isFinite(time) || time > end || time < start) { invalid++; continue; }
      const attrs = item.a && typeof item.a === 'object' ? item.a : item.attributes && typeof item.attributes === 'object' ? item.attributes : {};
      const state = text(item.s ?? item.state);
      const value = kind === 'reason' ? text(attrs.full_reason) || state : state;
      const unit = typeof attrs.unit_of_measurement === 'string' && attrs.unit_of_measurement.trim() ? text(attrs.unit_of_measurement.trim()) : null;
      rows.push({time, state: value || 'Unknown', unit, number: numeric(value), boundary: time === start, conflict: false});
    }
    rows.sort((a, b) => a.time - b.time);
    const unique = [];
    for (const row of rows) {
      const previous = unique[unique.length - 1];
      if (previous?.time === row.time) {
        if (previous.state !== row.state || previous.unit !== row.unit) {
          previous.state = 'Conflicting records'; previous.number = null; previous.unit = null; previous.conflict = true;
        }
      } else unique.push(row);
    }
    const omitted = Math.max(0, unique.length - MAX_DISPLAY_RECORDS);
    unique.forEach((record, index) => {record.transition = index > 0 && (record.state !== unique[index - 1].state || record.conflict);});
    return {records: unique.slice(omitted), status: unique.length ? 'ok' : 'empty', omitted, invalid};
  }
  function category(value, kind) {
    if (kind === 'source' || kind === 'reason') return {label: value, tone: 'neutral'};
    if (['unknown', 'unavailable', 'Conflicting records'].some(x => x.toLowerCase() === value.toLowerCase())) return {label: value, tone: 'unknown'};
    if (kind === 'risk') {
      const risk = {OK: 'ok', Watch: 'watch', Risk: 'risk', Danger: 'danger', Unknown: 'unknown'};
      return Object.hasOwn(risk, value) ? {label: value, tone: risk[value]} : {label: `Unrecognised recorded value: ${value}`, tone: 'unknown'};
    }
    const modes = {normal: 'Normal', cooking: 'Zone 1', bathroom: 'Zone 2', bath: 'Zone 2', air_quality: 'Air quality', global_gate: 'Global gate', away: 'Away', paused: 'Paused', manual_override: 'Manual override', disabled: 'Disabled', telemetry_unavailable: 'Telemetry unavailable', co_emergency: 'CO emergency', danger: 'Danger', alert: 'Alert'};
    return Object.hasOwn(modes, value) ? {label: modes[value], tone: value === 'co_emergency' ? 'danger' : 'neutral'} : {label: `Unrecognised recorded value: ${value}`, tone: 'unknown'};
  }
  function transitions(records) {
    return records.filter((record, index) => !record.boundary && (typeof record.transition === 'boolean' ? record.transition : index > 0 && record.state !== records[index - 1].state));
  }
  function seriesPaths(records, start, end) {
    const values = records.map(r => r.number).filter(v => v !== null);
    if (!values.length) return {segments: [], points: [], min: null, max: null};
    const min = Math.min(...values), max = Math.max(...values);
    const scale = Math.max(Math.abs(min), Math.abs(max), 1);
    const span = max / scale - min / scale;
    const project = record => ({x: 48 + 420 * (record.time - start) / Math.max(1, end - start), y: span ? 156 - 120 * (record.number / scale - min / scale) / span : 96});
    const segments = [], points = [];
    let segment = [], previous;
    for (const record of records) {
      if (record.number === null) { if (segment.length) segments.push(segment); segment = []; previous = undefined; continue; }
      if (previous && previous.unit !== record.unit) { if (segment.length) segments.push(segment); segment = []; }
      const point = {...project(record), record};
      segment.push(point); points.push(point); previous = record;
    }
    if (segment.length) segments.push(segment);
    return {segments, points, min, max};
  }
  function create({dialog, owner, title, entities, states, close, openEntity, nativeLabel = 'entity', nativeAvailable = true, now = () => Date.now(), timeoutMs = 15000}) {
    const document = dialog.ownerDocument;
    const allowed = entities.slice(0, 4).filter(item => item && typeof item.id === 'string' && /^sensor\.[a-z0-9_]+$/.test(item.id));
    const requested = [...new Set(allowed.filter(item => states[item.id]).map(item => item.id))];
    const summaryNodes = Array.from(dialog.children).filter(node => node.tagName !== 'STYLE' && !node.classList.contains('hi-summary-close'));
    const closeButton = dialog.querySelector('.hi-summary-close');
    const section = document.createElement('section'); section.className = 'hi-history'; section.hidden = true;
    section.innerHTML = `<style>
      .hi-history { min-height:320px; overflow-wrap:anywhere; }
      .hi-history[hidden] { display:none; }
      .hi-history nav { display:flex; gap:8px; align-items:center; position:sticky; top:0; z-index:2; padding-bottom:8px; background:#0d1522; }
      .hi-history .hi-history-ranges { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
      .hi-history .hi-history-ranges button[aria-pressed="true"] { border-color:#38bdf8; }
      .hi-history .hi-history-content { min-height:240px; }
      .hi-history article { margin:20px 0; padding-top:12px; border-top:1px solid #354762; }
      .hi-history .hi-history-chart { display:block; width:100%; height:auto; background:#101d30; border-radius:10px; }
      .hi-history .hi-history-axis { display:flex; justify-content:space-between; gap:16px; font-size:11px; color:#aebed1; }
      .hi-history select { display:block; box-sizing:border-box; width:100%; max-width:100%; min-height:44px; margin-top:12px; padding:8px; background:#18253a; color:#e2e8f0; border:1px solid #64748b; border-radius:8px; font:inherit; }
      .hi-history output { display:block; min-height:48px; margin-top:8px; white-space:normal; }
      .hi-history .hi-history-records { margin-top:12px; }
      .hi-history .hi-history-records summary { min-height:44px; cursor:pointer; }
      .hi-history .hi-history-records ul { padding-left:20px; max-height:200px; overflow:auto; }
      .hi-history .hi-history-legend { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:8px; font-size:12px; }
      .hi-history .hi-history-legend i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; }
      .hi-history .hi-history-note { color:#bdcad9; font-size:12px; }
      .hi-history button:focus-visible,.hi-history select:focus-visible,.hi-history summary:focus-visible { outline:2px solid #38bdf8; outline-offset:2px; }
    </style><nav aria-label="History navigation"><button type="button" data-back>Back</button></nav><h2 tabindex="-1">${escape(title === 'Current Air Control' ? 'Operating mode history' : title === 'AQ' ? 'Air quality history' : title === 'Mould' ? 'Mould risk history' : title === 'Condensation' ? 'Condensation history' : 'Recorded history')}</h2><div class="hi-history-ranges" role="group" aria-label="History range"><button type="button" data-hours="24" aria-pressed="true">24 hours</button><button type="button" data-hours="168" aria-pressed="false">7 days</button></div><div class="hi-history-content" aria-live="polite"></div><button type="button" data-native ${nativeAvailable ? '' : 'disabled'}>Open ${escape(nativeLabel)} details</button>`;
    dialog.appendChild(section);
    const content = section.querySelector('.hi-history-content');
    let hours = 24, generation = 0, active = false, disposed = false, timer;
    const hass = owner.hass || owner._hass;
    const date = time => {
      try { return new Intl.DateTimeFormat(hass?.locale?.language || undefined, {timeZone: hass?.config?.time_zone || undefined, year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset'}).format(time); }
      catch (_) { return new Date(time).toISOString(); }
    };
    const invalidate = () => { generation++; clearTimeout(timer); };
    const restoreClose = () => { if (closeButton) {dialog.insertBefore(closeButton, dialog.firstChild); closeButton.style.margin = ''; } };
    const back = () => {
      invalidate(); active = false; restoreClose(); section.hidden = true; dialog.scrollTop = 0;
      summaryNodes.forEach(node => { node.hidden = false; });
      dialog.querySelector('.hi-summary-history')?.focus({preventScroll:true});
      dialog.scrollTop = 0;
    };
    section.querySelector('[data-back]').addEventListener('click', back);
    section.querySelector('[data-native]').addEventListener('click', () => { if (nativeAvailable) {close(); openEntity();} });
    for (const button of section.querySelectorAll('[data-hours]')) button.addEventListener('click', () => {
      hours = Number(button.dataset.hours);
      for (const choice of section.querySelectorAll('[data-hours]')) choice.setAttribute('aria-pressed', String(Number(choice.dataset.hours) === hours));
      load();
    });
    function inspect(article, records) {
      const select = article.querySelector('select');
      if (!select) return;
      const output = article.querySelector('output');
      select.value = String(records.length - 1);
      const show = () => {
        const record = records[Number(select.value)];
        if (record) output.textContent = `${date(record.time)} — ${record.state}${record.unit ? ' ' + record.unit : ''}${record.boundary ? ' · state at start' : ''}`;
      };
      select.addEventListener('change', show); show();
    }
    const inspection = (records, label) => `<label>Inspect ${escape(label)}<select aria-label="Inspect ${escape(label)}">${records.map((record, i) => `<option value="${i}">${escape(date(record.time))} — ${escape(record.state)}${record.boundary ? ' · state at start' : ''}</option>`).join('')}</select></label><output></output>`;
    function draw(model, item, start, end) {
      const article = document.createElement('article');
      const heading = `<h3>${escape(item.label)}</h3>`;
      if (model.status !== 'ok') {
        const message = {unmapped:'History becomes available when this metric has a mapped source.',missing:'History for this source is currently unavailable.',empty:'History is available when Recorder retains accessible records for this period.',oversize:'Choose 24 hours or open entity details to explore this larger history.'}[model.status] || 'History unavailable.';
        article.innerHTML = heading + `<p>${message}</p>`; return article;
      }
      const records = model.records;
      let html = heading;
      if (model.omitted) html += `<p>Partial view: latest ${records.length} of ${records.length + model.omitted} records. Choose a shorter range for finer detail, or open entity details to explore the wider history.</p>`;
      if (model.invalid) html += `<p>${model.invalid} records need a valid timestamp within this period to display.</p>`;
      const shortDate = time => { try {return new Intl.DateTimeFormat(hass?.locale?.language || undefined,{timeZone:hass?.config?.time_zone || undefined,month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(time);} catch (_) {return new Date(time).toISOString().slice(5,16);} };
      const tick = value => Number(value.toPrecision(3)).toLocaleString('en',{notation:Math.abs(value)>=10000 || (value!==0 && Math.abs(value)<.01) ? 'scientific' : 'standard',maximumSignificantDigits:3});
      const axis = `<div class="hi-history-axis"><span>${escape(shortDate(start))}</span><span>${escape(shortDate(end))}</span></div>`;
      if (item.kind === 'numeric') {
        const units = [...new Set(records.filter(record => record.number !== null).map(record => record.unit))];
        if (units.length > 1) html += '<p class="hi-history-note">Recorded units change; each unit has a separate chart.</p>';
        if (!units.length) html += '<p>Recorded categorical states are available in the inspector below.</p>';
        if (units.length > 8) html += '<p>Inspect individual values below to explore the many recorded units in this period.</p>';
        for (const unit of units.slice(0, units.length > 8 ? 0 : 8)) {
          html += `<p>${unit === null ? 'Reported aggregate value · unit unspecified' : 'Recorded unit: ' + escape(unit)}</p>`;
        const group = records.map(record => record.unit === unit ? record : {...record, number:null});
        const chart = seriesPaths(group, start, end);
        if (chart.points.length) {
          const paths = chart.segments.map(points => `<polyline points="${points.map(p => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')}" fill="none" stroke="#7dd3fc" stroke-width="2"/>`).join('');
          const dots = chart.points.map(p => `<circle cx="${p.x.toFixed(2)}" cy="${p.y.toFixed(2)}" r="2" fill="#7dd3fc"/>`).join('');
          html += `<svg class="hi-history-chart" viewBox="0 0 500 190" role="img" aria-label="${escape(item.label)} recorded values. Inspect exact values below."><path d="M48 20V156H475" fill="none" stroke="#64748b"/><text x="4" y="30" fill="#cbd5e1" font-size="10">${escape(tick(chart.max))}</text><text x="4" y="158" fill="#cbd5e1" font-size="10">${escape(tick(chart.min))}</text>${paths}${dots}</svg>${axis}`;
        }
        }
        html += '<p class="hi-history-note">Lines join recorded observations, with breaks at categorical states and unit changes.</p>';
      } else if (item.kind !== 'reason') {
        const colors = {ok:'#4ade80',watch:'#facc15',risk:'#fb923c',danger:'#f87171',unknown:'#64748b',neutral:'#7dd3fc'};
        const ribbons = records.map((record,index) => {
          const next = records[index+1]?.time ?? end;
          const x = 500 * (record.time-start) / Math.max(1,end-start);
          const width = Math.max(0,500 * (next-record.time) / Math.max(1,end-start));
          const label = category(record.state,item.kind);
          return `<rect x="${x.toFixed(2)}" y="0" width="${width.toFixed(2)}" height="36" fill="${colors[label.tone]}" stroke="#0d1522" stroke-width="1"><title>${escape(label.label)} · ${escape(date(record.time))}</title></rect>${width >= 50 ? `<text x="${(x+5).toFixed(2)}" y="23" font-size="13" fill="#071523">${escape(label.label.slice(0, Math.max(1, Math.floor((width-10)/8))))}${label.label.length > Math.floor((width-10)/8) ? '…' : ''}</text>` : ''}`;
        }).join('');
        html += `<svg class="hi-history-chart" viewBox="0 0 500 36" role="img" aria-label="${escape(item.label)} recorded states. Inspect states below.">${ribbons}</svg>${axis}`;
        html += `<div class="hi-history-legend">${[...new Set(records.map(record => record.state))].map(value => {const label=category(value,item.kind); return `<span><i style="background:${colors[label.tone]}" aria-hidden="true"></i>${escape(label.label)}</span>`;}).join('')}</div>`;
      }
      html += inspection(records,item.label);
      const updates = item.kind === 'numeric' || item.kind === 'reason' ? records.filter(record => !record.boundary) : transitions(records);
      html += `<details class="hi-history-records"><summary>${item.kind === 'numeric' || item.kind === 'reason' ? 'Recorded updates' : 'Recorded transitions'} (${updates.length})</summary><ul>${updates.map(record => `<li>${escape(date(record.time))} — ${escape(record.state)}${record.unit ? ' ' + escape(record.unit) : ''}</li>`).join('')}</ul></details>`;

      article.innerHTML = html; inspect(article, records); return article;
    }
    async function load() {
      invalidate(); const requestGeneration = generation;
      const end = now(), start = end - hours * 3600000;
      content.innerHTML = '<p role="status">Loading recorded history…</p>';
      if (!requested.length) { content.innerHTML = '<p>History becomes available when its sources are mapped.</p>'; return; }
      if (typeof hass?.callWS !== 'function') { content.innerHTML = '<p>Open entity details to access history in this client.</p>'; return; }
      let timedOut = false;
      timer = setTimeout(() => {
        if (disposed || !active || requestGeneration !== generation) return;
        timedOut = true; generation++;
        content.innerHTML = '<p>History request timed out. Choose a range to try again, or open entity details.</p>';
      }, timeoutMs);
      try {
        const response = await hass.callWS({type:'history/history_during_period',start_time:new Date(start).toISOString(),end_time:new Date(end).toISOString(),entity_ids:requested,include_start_time_state:true,significant_changes_only:false,minimal_response:false,no_attributes:false});
        if (disposed || !active || timedOut || requestGeneration !== generation || !owner.isConnected || !dialog.isConnected) return;
        clearTimeout(timer);
        content.replaceChildren();
        const context = document.createElement('p'); context.className='hi-history-note';
        context.textContent = allowed.some(item=>item.kind==='numeric') ? 'Each chart follows one recorded aggregate and its available inputs. Historical membership is unspecified. Use dedicated CO safety status when assessing CO emergencies.' : allowed.some(item=>item.kind==='risk') ? 'Risk and room records keep independent timestamps. An OK classification reflects the available room evidence.' : 'Recorded operating modes describe controller state. Reasons retain their own timestamps. Physical output activity is separate evidence.';
        content.appendChild(context);
        const range = document.createElement('p'); range.className='hi-history-note';
        range.textContent = `${date(start)} — ${date(end)}. State at start provides carried context; its original change time is unspecified.`;
        content.appendChild(range);
        if (!response || typeof response !== 'object' || Array.isArray(response)) throw new Error('Invalid history response');
        for (const item of allowed) {
          // Ignore all unrequested response keys, even if the server supplied them.
          const model = requested.includes(item.id) ? normalize(Object.hasOwn(response,item.id) ? response[item.id] : undefined,start,end,item.kind) : {status:'unmapped',records:[]};
          content.appendChild(draw(model,item,start,end));
        }
      } catch (_) {
        if (disposed || !active || requestGeneration !== generation) return;
        clearTimeout(timer); content.innerHTML = '<p>History is currently unavailable. Try another range or open entity details to continue.</p>';
      }
    }
    return {
      open() { if (disposed) return; active = true; summaryNodes.forEach(node => {node.hidden = true;}); section.hidden = false; if (closeButton) {section.querySelector('nav').appendChild(closeButton); closeButton.style.margin='0 0 0 auto';} dialog.scrollTop=0; section.querySelector('[data-back]').focus({preventScroll:true}); dialog.scrollTop=0; load(); },
      dispose() { disposed = true; active = false; invalidate(); section.remove(); },
    };
  }
  return {normalize, numeric, category, transitions, seriesPaths, create};
})();
