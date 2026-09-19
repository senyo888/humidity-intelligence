import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SURFACES = [
  'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
  'ui-gallery/default-v2-mobile-aq/card.yaml',
  'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
];

function gaugeBody(relativePath) {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const cardStart = source.indexOf('          entity: sensor.hi_diagnostics\n');
  assert.notEqual(cardStart, -1, `${relativePath}: Stability Score card missing`);
  const gaugeStart = source.indexOf('            gauge: |\n', cardStart);
  const tapAction = source.indexOf('          tap_action:\n', gaugeStart);
  assert.notEqual(gaugeStart, -1, `${relativePath}: Stability gauge missing`);
  assert.notEqual(tapAction, -1, `${relativePath}: Stability gauge boundary missing`);

  const lines = source.slice(gaugeStart, tapAction).split('\n');
  const open = lines.indexOf('              [[[');
  const close = lines.lastIndexOf('              ]]]');
  assert.ok(open >= 0 && close > open, `${relativePath}: gauge wrapper missing`);
  return lines
    .slice(open + 1, close)
    .map((line) => (line.startsWith('                ') ? line.slice(16) : line))
    .join('\n');
}

function labelBody(relativePath) {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const start = source.indexOf('          entity: sensor.hi_diagnostics\n');
  const labelStart = source.indexOf('          label: |\n', start);
  assert.ok(start >= 0 && labelStart > start, `${relativePath}: native label missing`);
  const open = source.indexOf('[[[', labelStart);
  const close = source.indexOf(']]]', open);
  assert.ok(close > open, `${relativePath}: label wrapper missing`);
  return source.slice(open + 3, close).trim();
}

const LABEL_BODIES = SURFACES.map(labelBody);
const LABEL_RENDERERS = LABEL_BODIES.map((body) => new Function('entity', body));

function renderLabel(contract) {
  return assertIdentical(LABEL_RENDERERS.map((render) => render({ attributes: { diagnostics_summary: { stability_score: contract } } })));
}

const BODIES = SURFACES.map(gaugeBody);
const RENDERERS = BODIES.map((body) => new Function('entity', body));

function renderAll(attributes = {}) {
  return RENDERERS.map((render) => render({ state: 'ok', attributes }));
}

function assertIdentical(outputs) {
  assert.equal(new Set(outputs).size, 1, 'all four Stability surfaces must render identically');
  return outputs[0];
}

test('all four public surfaces carry one identical Stability renderer', () => {
  assert.equal(new Set(BODIES).size, 1);
  assert.equal(new Set(LABEL_BODIES).size, 1);
});

function renderContract(contract) {
  const output = assertIdentical(renderAll({ diagnostics_summary: { stability_score: contract } }));
  assert.doesNotMatch(output, /<small\b/, 'compact status must stay outside the ring');
  return output;
}

test('missing and malformed contracts cannot imply a preview or completed score', () => {
  for (const contract of [undefined, null, {}, 'malformed', []]) {
    const output = renderContract(contract);
    assert.match(output, /<span>—<\/span><\/div>/);
    assert.equal(renderLabel(contract), 'NO SCORE');
    assert.match(output, /--hi-stability-color:#94a3b8/);
    assert.doesNotMatch(output, /gauge-white|PREVIEW|2\.1/);
  }
});

test('backend collecting presentation reports real sample progress', () => {
  const contract = {
    availability: 'insufficient_coverage',
    window: { valid_samples: 288, minimum_valid_samples: 303 },
    score: { suppression_reason: 'coverage_below_threshold' },
    presentation: { state_code: 'collecting', tone: 'collecting', primary_text: '288', compact_text: 'OF 303', detail_text: 'Collecting valid samples.' },
  };
  const output = renderContract(contract);
  assert.match(output, /<span>288<\/span><\/div>/);
  assert.equal(renderLabel(contract), 'OF 303');
  assert.doesNotMatch(output, /OF 303/);
  assert.match(output, /--hi-stability-color:#38bdf8/);
  assert.match(output, /aria-label="Collecting valid samples\."/);
  assert.doesNotMatch(output, /gauge-white/);
});

test('numeric score never overrides the backend classification or class cap', () => {
  for (const [classification, color] of [['excellent', '#f8fafc'], ['good', '#4ade80'], ['unstable', '#facc15'], ['poor', '#ef4444']]) {
    const contract = { score: { display_score: 99, display_classification: classification }, presentation: { tone: classification, primary_text: '99', compact_text: classification.toUpperCase() } };
    const output = renderContract(contract);
    assert.ok(output.includes(`--hi-stability-color:${color}`));
    assert.ok(output.includes('<span>99</span></div>'));
    assert.equal(renderLabel(contract), classification.toUpperCase());
    assert.ok(!output.includes(classification.toUpperCase()));
    assert.equal(output.includes('hi-stability-gauge-white'), classification === 'excellent');
  }
});

test('suppressed evidence and live data have distinct truthful states', () => {
  for (const [suppression, label, color] of [
    ['current_telemetry_unavailable', 'LIVE DATA', '#94a3b8'],
    ['insufficient_consecutive_samples', 'GAPS', '#ec4899'],
    ['insufficient_balance_sources', 'BALANCE', '#ec4899'],
  ]) {
    const contract = { availability: 'unavailable', score: { suppression_reason: suppression }, presentation: { compact_text: label } };
    const output = renderContract(contract);
    assert.ok(output.includes('<span>—</span></div>'));
    assert.equal(renderLabel(contract), label);
    assert.ok(output.includes(`--hi-stability-color:${color}`));
  }
});

test('presentation text is escaped in visible content and accessible detail', () => {
  const unsafe = '<img src=x onerror="bad"> & \'quoted\'';
  const output = renderContract({ presentation: { primary_text: unsafe, compact_text: unsafe, detail_text: unsafe }, movement: { detail_text: unsafe } });
  assert.doesNotMatch(output, /<img|onerror="bad"/);
  assert.match(output, /&lt;img src=x onerror=&quot;bad&quot;&gt; &amp; &#039;quoted&#039;/);
});

test('native compact label escapes backend text without deriving score classification', () => {
  const unsafe = '<img src=x onerror="bad"> & \'quoted\'';
  assert.equal(renderLabel({ presentation: { compact_text: unsafe } }),
    '&lt;img src=x onerror=&quot;bad&quot;&gt; &amp; &#039;quoted&#039;');
  assert.equal(renderLabel({ score: { display_score: 99, display_classification: 'excellent' } }), 'NO SCORE');
});

test('LED palette consumes backend tokens independently of the condition halo', () => {
  for (const [color_token, expected] of [['rise_gentle','#38bdf8'],['rise_strong','#4ade80'],['fall_gentle','#fb923c'],['fall_strong','#ef4444'],['neutral','#94a3b8'],['unknown','#94a3b8']]) {
    const output = renderContract({
      score: { display_score: 95, display_classification: 'excellent' },
      presentation: { tone: 'excellent', primary_text: '95', compact_text: 'EXCELLENT' },
      movement: { status: 'available', direction: 'lower', start_position_degrees: 0, end_position_degrees: -18, color_token },
    });
    assert.ok(output.includes('--hi-stability-color:#f8fafc;'));
    assert.ok(output.includes(`--hi-stability-led-color:${expected};`));
    assert.ok(output.includes('--hi-stability-led-sweep:18deg;'));
  }
});

function arcs(start, end, extra = {}) {
  const output = renderContract({ movement: { status: 'available', start_position_degrees: start, end_position_degrees: end, ...extra } });
  const extract = (side) => {
    const html = output.match(new RegExp(`hi-stability-direction-${side}" aria-hidden="true">(.*?)</div>`))[1];
    return [...html.matchAll(/--hi-mark-angle:(\d+)deg;--hi-mark-delay:(\d+)ms;--hi-mark-from:(\d);--hi-mark-to:(\d);([^"]*)/g)]
      .map((m) => ({ angle: +m[1], delay: +m[2], from: +m[3], to: +m[4], fixed: m[5].includes('animation:none') }));
  };
  return { output, right: extract('higher'), left: extract('lower') };
}

test('steady endpoint preserves lit marks and backend colour without replaying fades', () => {
  const {output, left, right} = arcs(-18, -18, {direction: 'steady', color_token: 'fall_gentle'});
  assert.equal(left.length, 6);
  assert.equal(right.length, 0);
  assert.ok(left.every((m) => m.from === 1 && m.to === 1 && m.fixed));
  assert.ok(output.includes('--hi-stability-led-color:#fb923c;'));
});

test('higher trend retracts an existing left arc toward the origin', () => {
  const {left, right} = arcs(-18, -6, {direction: 'higher'});
  assert.equal(right.length, 0);
  assert.deepEqual(left.filter((m) => m.to).map((m) => m.angle), [0, 3]);
  const fading = left.filter((m) => !m.to).sort((a,b) => a.delay-b.delay);
  assert.deepEqual(fading.map((m) => m.angle), [15, 12, 9, 6]);
  assert.ok(fading.every((m) => m.from === 1 && !m.fixed));
});

test('crossing the origin clears the old side before filling the new side', () => {
  for (const sign of [1, -1]) {
    const rendered = arcs(-6 * sign, 9 * sign);
    const old = sign === 1 ? rendered.left : rendered.right;
    const fresh = sign === 1 ? rendered.right : rendered.left;
    assert.equal(old.length, 2);
    assert.equal(fresh.length, 3);
    assert.ok(old.every((m) => m.from === 1 && m.to === 0));
    assert.ok(fresh.every((m) => m.from === 0 && m.to === 1));
    assert.ok(Math.max(...old.map((m) => m.delay)) < Math.min(...fresh.map((m) => m.delay)));
  }
});

test('half and full circle endpoints are bounded and reveal at the agreed pace', () => {
  for (const sign of [1, -1]) {
    for (const [extent, count, duration] of [[180, 60, 1200], [360, 120, 2280]]) {
      const rendered = arcs(0, sign * extent);
      const marks = sign === 1 ? rendered.right : rendered.left;
      assert.equal(marks.length, count);
      assert.equal(Math.max(...marks.map((m) => m.delay)) + 138, duration);
      assert.equal(marks[0].delay, 0);
      assert.ok(marks.every((m) => m.from === 0 && m.to === 1));
    }
  }
});

test('missing, invalid and unavailable endpoints fail closed', () => {
  for (const bad of [undefined, null, NaN, Infinity, '18', 1.5, 361, -361, true]) {
    for (const [start, end] of [[bad, 18], [18, bad]]) {
      const rendered = arcs(start, end);
      assert.equal(rendered.left.length + rendered.right.length, 0);
    }
  }
  const unavailable = arcs(18, 36, {status: 'unavailable'});
  assert.equal(unavailable.left.length + unavailable.right.length, 0);
});

test('reduced motion renders the final endpoint including cleared marks', () => {
  for (const relativePath of SURFACES) {
    const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
    const badge = source.slice(source.indexOf('          entity: sensor.hi_diagnostics'));
    const reduced = badge.slice(badge.indexOf('@media (prefers-reduced-motion: reduce)'));
    assert.match(reduced, /\.hi-stability-mark\s*\{\s*animation: none !important;\s*opacity: var\(--hi-mark-to\);/);
  }
  const {left} = arcs(-18, -6);
  assert.deepEqual(left.map((m) => m.to), [1, 1, 0, 0, 0, 0]);
});

test('partial scored evidence pulses to backend classification while retaining magenta evidence and independent movement', () => {
  for (const [classification, expected] of [['excellent', '#f8fafc'], ['good', '#4ade80'], ['unstable', '#facc15'], ['poor', '#ef4444']]) {
    const output = renderContract({
      score: { display_score: 82, display_classification: classification },
      presentation: { tone: 'incomplete', primary_text: '82', compact_text: 'PARTIAL', indicator_mode: 'incomplete' },
      movement: { status: 'available', start_position_degrees: 18, end_position_degrees: 18, color_token: 'fall_gentle' },
    });
    assert.match(output, /hi-stability-gauge-partial-pulse/);
    assert.ok(output.includes(`--hi-stability-score-color:${expected};`));
    assert.ok(output.includes('--hi-stability-color:#ec4899;'));
    assert.ok(output.includes('--hi-stability-led-color:#fb923c;'));
    assert.match(output, /hi-stability-evidence active/);
    assert.doesNotMatch(output, /hi-stability-gauge-white/);
  }
});

test('partial pulse requires a real score and a known backend classification', () => {
  for (const display_score of [null, undefined, '', 'unavailable', NaN, Infinity]) {
    const output = renderContract({ score: { display_score, display_classification: 'good' }, presentation: { tone: 'incomplete' } });
    assert.doesNotMatch(output, /hi-stability-gauge-partial-pulse/);
  }
  for (const classification of [undefined, '', 'unknown', '__proto__']) {
    const output = renderContract({ score: { display_score: 82, display_classification: classification }, presentation: { tone: 'incomplete' } });
    assert.doesNotMatch(output, /hi-stability-gauge-partial-pulse/);
  }
  for (const tone of ['excellent', 'good', 'unstable', 'poor', 'collecting', 'unavailable']) {
    const output = renderContract({ score: { display_score: 82, display_classification: 'good' }, presentation: { tone } });
    assert.doesNotMatch(output, /hi-stability-gauge-partial-pulse/);
  }
});

test('partial halo has a six-second cycle and reduced motion separates static score and evidence', () => {
  for (const relativePath of SURFACES) {
    const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
    const badge = source.slice(source.indexOf('          entity: sensor.hi_diagnostics'));
    assert.match(badge, /\.hi-stability-gauge-partial-pulse::before\s*\{\s*animation: hi-stability-partial-pulse 6000ms ease-in-out infinite;/);
    assert.match(badge, /\.hi-stability-gauge::before\s*\{[^}]*box-shadow: 0 0 9px 3px var\(--hi-stability-color\);/);
    const reduced = badge.slice(badge.indexOf('@media (prefers-reduced-motion: reduce)'));
    const normal = badge.slice(0, badge.indexOf('@media (prefers-reduced-motion: reduce)'));
    assert.doesNotMatch(normal, /\.hi-stability-partial-label::before/);
    assert.match(reduced, /\.hi-stability-gauge-partial-pulse::before\s*\{\s*box-shadow: 0 0 9px 3px var\(--hi-stability-score-color\);/);
    assert.match(reduced, /\.hi-stability-partial-label::before\s*\{[^}]*width: 4px;[^}]*height: 4px;[^}]*background: #ec4899;/);

    assert.match(reduced, /\.hi-stability-gauge-partial-pulse::before,[^{]*\{\s*animation: none !important;/);
  }
});

test('incomplete native label preserves escaped text inside the evidence marker wrapper', () => {
  const unsafe = '<img src=x onerror="bad"> & \'quoted\'';
  assert.equal(renderLabel({ presentation: { tone: 'incomplete', compact_text: unsafe } }),
    '<span class="hi-stability-partial-label">&lt;img src=x onerror=&quot;bad&quot;&gt; &amp; &#039;quoted&#039;</span>');
  assert.equal(renderLabel({ presentation: { tone: 'incomplete', compact_text: 'PARTIAL' } }),
    '<span class="hi-stability-partial-label">PARTIAL</span>');
  for (const tone of [undefined, 'excellent', 'good', 'unstable', 'poor', 'collecting', 'unavailable']) {
    assert.equal(renderLabel({ presentation: { tone, compact_text: 'EXAMPLE' } }), 'EXAMPLE');
  }
});

test('badge provides an inert dialog snapshot with backend explanation evidence and movement', () => {
  const output = renderContract({
    presentation: { detail_text: 'Backend partial evidence explanation.' },
    window: { valid_samples: 303, expected_samples: 432 },
    movement: { detail_text: 'Backend movement explanation.' },
  });
  assert.match(output, /<template class="hi-stability-details-template">/);
  assert.doesNotMatch(output, /popovertarget|popover="auto"|hi-stability-open/);
  assert.match(output, /Details reflect the snapshot when opened/);
  assert.match(output, /<p>Backend partial evidence explanation\.<\/p>/);
  assert.match(output, /<p>Rolling-window coverage: 303 of 432 valid samples\.<\/p>/);
  assert.match(output, /<h3>Recent trend<\/h3>/);
  assert.match(output, /Arc position does not measure elapsed time\./);
  assert.match(output, /<p>Backend movement explanation\.<\/p>/);
  assert.match(output, /<button type="button" class="hi-stability-close" autofocus>Close<\/button>/);
  assert.doesNotMatch(output, /browser_mod|call-service/);
});

test('dialog snapshot escapes every dynamic text surface and reports absent evidence', () => {
  const unsafe = '<img src=x onerror="bad">';
  const output = renderContract({ presentation: { detail_text: unsafe }, window: { valid_samples: unsafe, expected_samples: unsafe }, movement: { detail_text: unsafe } });
  assert.doesNotMatch(output, /<img|onerror="bad"/);
  assert.match(output, /<p>&lt;img src=x onerror=&quot;bad&quot;&gt;<\/p>/);
  assert.match(output, /Sample progress unavailable\./);
  const absent = renderContract({});
  assert.match(absent, /Sample progress unavailable\./);
  assert.match(absent, /Movement unavailable\./);
});

test('malformed score types and ranges fail closed despite healthy presentation and retained movement', () => {
  for (const value of [false, true, [], [88], {}, '', ' ', '0', '88', NaN, Infinity, -Infinity, -1, 101, 88.5]) {
    for (const tone of ['excellent', 'good', 'incomplete']) {
      const contract = {
        availability: 'available',
        score: { display_score: value, display_classification: 'Excellent' },
        presentation: { state_code: 'available', tone, primary_text: '100', compact_text: 'EXCELLENT', detail_text: 'Healthy stale text', indicator_mode: 'score' },
        message: 'Healthy stale message',
        movement: { status: 'available', start_position_degrees: 90, end_position_degrees: 180, color_token: 'rise_strong', detail_text: 'Stale movement' },
      };
      const output = renderContract(contract);
      assert.match(output, /<span>—<\/span><\/div>/);
      assert.match(output, /--hi-stability-color:#94a3b8;/);
      assert.match(output, /--hi-stability-led-sweep:0deg;/);
      assert.match(output, /Stability Score unavailable\./);
      assert.doesNotMatch(output, /gauge-white|partial-pulse|Healthy stale|Stale movement|class="hi-stability-mark"/);
      assert.equal(renderLabel(contract), 'NO SCORE');
    }
  }
});

test('legacy score locations use the same strict numeric validation', () => {
  for (const value of [false, [], [88], '88', -1, 101]) {
    for (const attributes of [
      { diagnostics_summary: { stability_score: { display_score: value, display_classification: 'Excellent' } } },
      { stability_score_display_score: value, stability_score_display_classification: 'Excellent' },
    ]) {
      const output = assertIdentical(renderAll(attributes));
      assert.match(output, /<span>—<\/span><\/div>/);
      assert.match(output, /--hi-stability-color:#94a3b8;/);
      assert.doesNotMatch(output, /gauge-white/);
      assert.equal(assertIdentical(LABEL_RENDERERS.map(render => render({attributes}))), 'NO SCORE');
    }
  }
});

test('available payload without a numeric score and unavailable payload with stale score fail closed', () => {
  for (const [availability, value] of [['available', null], ['available', undefined], ['unavailable', 100], ['insufficient_coverage', 100]]) {
    const contract = {availability, score: {display_score: value, display_classification: 'Excellent'}, presentation: {tone: 'excellent', primary_text: '100', compact_text: 'EXCELLENT'}};
    const output = renderContract(contract);
    assert.match(output, /<span>—<\/span><\/div>/);
    assert.match(output, /--hi-stability-color:#94a3b8;/);
    assert.equal(renderLabel(contract), 'NO SCORE');
  }
});

test('all valid integer scores including genuine zero retain backend presentation', () => {
  for (let value = 0; value <= 100; value++) {
    const contract = {availability: 'available', score: {display_score: value, display_classification: 'Poor'}, presentation: {tone: 'poor', primary_text: String(value), compact_text: 'POOR'}};
    const output = renderContract(contract);
    assert.ok(output.includes(`<span>${value}</span></div>`));
    assert.match(output, /--hi-stability-color:#ef4444;/);
    assert.equal(renderLabel(contract), 'POOR');
  }
});

function collectingContract(samples, ratio) {
  return {
    availability: 'insufficient_coverage',
    window: { valid_samples: samples, minimum_valid_samples: 303, expected_samples: 432 },
    presentation: {
      state_code: 'collecting', indicator_mode: 'collection', tone: 'collecting',
      primary_text: String(samples), compact_text: 'OF 303', progress_ratio: ratio,
    },
  };
}

function renderedMarks(output) {
  return [...output.matchAll(/<i class="hi-stability-mark"[^>]*>/g)].map(([html]) => html);
}

test('collection fills clockwise by actual minimum-sample progress without completing early', () => {
  for (let samples = 0; samples <= 303; samples++) {
    const ratio = Math.round(samples / 303 * 10000) / 10000;
    const output = renderContract(collectingContract(samples, ratio));
    const marks = renderedMarks(output);
    assert.equal(marks.length, samples, `${samples}/303`);
    marks.forEach((mark, index) => {
      const step = 360 / 303;
      const width = Math.min(0.8, step * 0.7);
      assert.ok(mark.includes(`--hi-mark-angle:${index * step + (step - width) / 2}deg;`));
      assert.ok(mark.includes(`--hi-mark-width:${width}deg;`));
      assert.ok(mark.includes('--hi-mark-from:1;--hi-mark-to:1;'));
      assert.ok(mark.includes('animation:none;'));
    });
    assert.equal(output.includes('<div class="hi-stability-origin"></div>'), samples === 0);
    assert.match(output, /hi-stability-direction-higher/);
    assert.match(output, /--hi-stability-led-color:#38bdf8;/);
    assert.ok(output.includes(`Baseline progress: ${samples} of 303 valid samples.`));
    assert.match(output, /Baseline collection/);
    assert.doesNotMatch(output, /Recent trend|arc retains accumulated score movement|of 432 valid samples/);
  }
});

test('malformed collection ratios do not create progress LEDs or coerce values', () => {
  for (const ratio of [undefined, null, false, true, [], [1], {}, '1', NaN, Infinity, -Infinity, -0.1, 1.1]) {
    const contract = collectingContract(302, ratio);
    // A stale score movement must never fill a collecting ring.
    contract.movement = { status: 'available', start_position_degrees: 0, end_position_degrees: 360 };
    assert.equal(renderedMarks(renderContract(contract)).length, 0, String(ratio));
  }
});

test('collection counts use the minimum target and fail safely for malformed evidence', () => {
  for (const field of ['valid_samples', 'minimum_valid_samples']) {
    for (const value of [undefined, null, false, [], '303', -1, 1.5, Infinity]) {
      const contract = collectingContract(151, 0.4983);
      contract.window[field] = value;
      const output = renderContract(contract);
      assert.doesNotMatch(output, /Baseline progress: \d+ of \d+ valid samples\./);
      assert.match(output, /unavailable/i);
    }
  }
});

test('available score keeps movement LEDs and reports rolling-window coverage separately', () => {
  const output = renderContract({
    availability: 'available',
    score: { display_score: 90, display_classification: 'Good' },
    window: { valid_samples: 303, minimum_valid_samples: 303, expected_samples: 432 },
    presentation: { state_code: 'available', indicator_mode: 'score', tone: 'good', progress_ratio: 1 },
    movement: { status: 'available', start_position_degrees: -18, end_position_degrees: -18, color_token: 'fall_gentle' },
  });
  assert.equal(renderedMarks(output).length, 6);
  assert.match(output, /--hi-stability-led-color:#fb923c;/);
  assert.match(output, /Rolling-window coverage: 303 of 432 valid samples\./);
  assert.match(output, /Recent trend/);
  assert.doesNotMatch(output, /Baseline collection/);
});

test('collection state and indicator mode must agree before progress is drawn', () => {
  for (const [state, mode] of [['incomplete_evidence_gaps', 'collection'], ['collecting', 'none'], ['live_data_unavailable', 'none']]) {
    const contract = collectingContract(303, 1);
    contract.presentation.state_code = state;
    contract.presentation.indicator_mode = mode;
    assert.equal(renderedMarks(renderContract(contract)).length, 0);
  }
});

function withFailureHistory(contract, history = {}) {
  return { ...contract, sampling: { failure_history: {
    status: 'available', failed_bucket_count: 2,
    marker_angles_degrees: [12.5, 359.166667],
    detail_text: 'Two failed scheduled sampling buckets remain in the 72-hour window.',
    ...history,
  } } };
}

function failureMarks(output) {
  return [...output.matchAll(/<i class="hi-stability-failure-mark"[^>]*>/g)].map(([html]) => html);
}

test('failed bucket markers use a separate history track without consuming valid progress', () => {
  const clean = renderContract(collectingContract(151, 0.4983));
  const marked = renderContract(withFailureHistory(collectingContract(151, 0.4983)));
  assert.deepEqual(renderedMarks(marked), renderedMarks(clean));
  assert.equal(failureMarks(marked).length, 2);
  assert.match(marked, /hi-stability-failure-history/);
  assert.match(marked, /Two failed scheduled sampling buckets remain in the 72-hour window\./);
  assert.match(marked, /Baseline progress: 151 of 303 valid samples\./);
});

test('failure markers remain during backend evidence gaps and live-data suppression', () => {
  for (const state of ['collecting', 'incomplete_evidence_gaps', 'incomplete_evidence_balance', 'live_data_unavailable']) {
    const contract = collectingContract(151, 0.4983);
    contract.presentation.state_code = state;
    contract.presentation.indicator_mode = state === 'collecting' ? 'collection' : 'none';
    const output = renderContract(withFailureHistory(contract));
    assert.equal(failureMarks(output).length, 2, state);
  }
});

test('missing malformed or inconsistent failure history never invents red markers', () => {
  const invalidHistories = [undefined, null, [], {}, false, 'failed',
    { status: 'unavailable' },
    ...[undefined, null, false, '2', -1, 1.5, 433, Infinity].map(failed_bucket_count => ({ failed_bucket_count })),
    ...[undefined, null, false, {}, '12,24', [12], [12,12], [0,360], [-1,12], [NaN,12], [Infinity,12], ['12',24], [false,24], [[],24]].map(marker_angles_degrees => ({ marker_angles_degrees })),
  ];
  for (const bad of invalidHistories) {
    const contract = withFailureHistory(collectingContract(151, 0.4983));
    contract.sampling.failure_history = bad && typeof bad === 'object' && !Array.isArray(bad)
      ? { ...contract.sampling.failure_history, ...bad } : bad;
    if (bad && typeof bad === 'object' && Object.keys(bad).length === 0) contract.sampling.failure_history = bad;
    assert.equal(failureMarks(renderContract(contract)).length, 0, JSON.stringify(bad));
  }
  assert.equal(failureMarks(renderContract(collectingContract(151, 0.4983))).length, 0);
});

test('failure marker capacity is bounded and admits all 432 unique backend slots', () => {
  for (const count of [0, 1, 432]) {
    const output = renderContract(withFailureHistory(collectingContract(151, 0.4983), {
      failed_bucket_count: count,
      marker_angles_degrees: Array.from({ length: count }, (_, index) => index * 360 / 432),
    }));
    assert.equal(failureMarks(output).length, count);
  }
});

test('failure history hides on valid scores invalid scores and unsupported evidence states', () => {
  const available = {
    availability: 'available', score: { display_score: 90, display_classification: 'Good' },
    presentation: { state_code: 'available', indicator_mode: 'score', tone: 'good' },
    movement: { status: 'available', start_position_degrees: -18, end_position_degrees: -18, color_token: 'fall_gentle' },
  };
  const markedAvailable = renderContract(withFailureHistory(available));
  assert.equal(failureMarks(markedAvailable).length, 0);
  assert.deepEqual(renderedMarks(markedAvailable), renderedMarks(renderContract(available)));
  for (const value of [false, [], '90', 101]) {
    const contract = collectingContract(151, 0.4983);
    contract.score = { display_score: value };
    assert.equal(failureMarks(renderContract(withFailureHistory(contract))).length, 0);
  }
  for (const state of ['unavailable', 'unknown', 'available']) {
    const contract = collectingContract(151, 0.4983);
    contract.presentation.state_code = state;
    assert.equal(failureMarks(renderContract(withFailureHistory(contract))).length, 0);
  }
});

test('failure history detail is escaped and cannot inject popup markup', () => {
  const output = renderContract(withFailureHistory(collectingContract(151, 0.4983), {
    detail_text: '<img src=x onerror="bad"> & \'failed\'',
  }));
  assert.doesNotMatch(output, /<img|onerror="bad"/);
  assert.match(output, /&lt;img src=x onerror=&quot;bad&quot;&gt; &amp; &#039;failed&#039;/);
});

test('early collection shows four distinct ticks and over-target evidence clamps at full ring', () => {
  const early = renderedMarks(renderContract(collectingContract(4, 0.0132)));
  assert.equal(early.length, 4);
  assert.equal(new Set(early.map(mark => mark.match(/--hi-mark-angle:([^;]+)/)[1])).size, 4);
  const before = renderedMarks(renderContract(collectingContract(302, 0.9967)));
  const full = renderedMarks(renderContract(collectingContract(303, 1)));
  assert.equal(before.length, 302); assert.equal(full.length, 303);
  assert.deepEqual(before, full.slice(0,302));
  assert.deepEqual(renderedMarks(renderContract(collectingContract(432, 1))), full);
});

test('collection count target and ratio must be bounded and mutually consistent', () => {
  for (const [count, required, ratio, expected] of [
    [0,1,0,0], [1,1,1,1], [432,432,1,432],
    [1,0,1,0], [1,433,0.0023,0], [433,303,1,0],
    [4,303,0.0131,0], [4,303,1,0], [302,303,1,0], [0,303,0.1,0],
    [-1,303,0,0], [4.5,303,0.0149,0], [4,303.5,0.0132,0],
  ]) {
    const contract = collectingContract(count, ratio);
    contract.window.minimum_valid_samples = required;
    assert.equal(renderedMarks(renderContract(contract)).length, expected, `${count}/${required} ratio ${ratio}`);
  }
  for (const field of ['valid_samples','minimum_valid_samples']) {
    for (const bad of [undefined,null,false,true,[],{},'303',NaN,Infinity]) {
      const contract = collectingContract(4,0.0132); contract.window[field] = bad;
      assert.equal(renderedMarks(renderContract(contract)).length, 0, `${field}: ${String(bad)}`);
    }
  }
});

test('maximum collection density retains positive gaps and scored ticks keep original width', () => {
  const contract = collectingContract(432,1); contract.window.minimum_valid_samples = 432;
  const marks = renderedMarks(renderContract(contract));
  const angles = marks.map(mark => Number(mark.match(/--hi-mark-angle:([^d]+)deg/)[1]));
  const widths = marks.map(mark => Number(mark.match(/--hi-mark-width:([^d]+)deg/)[1]));
  assert.ok(widths.every(width => width > 0 && width < 360 / 432));
  assert.ok(angles.every((angle,index) => angle >= 0 && angle + widths[index] < 360));
  assert.ok(angles.slice(1).every((angle,index) => angle > angles[index] + widths[index]));
  const scored = arcs(0,18).output;
  assert.ok(renderedMarks(scored).every(mark => !mark.includes('--hi-mark-width:')));
  for (const surface of SURFACES) {
    const source = fs.readFileSync(path.join(ROOT,surface),'utf8');
    assert.match(source,/var\(--hi-mark-width, 0\.8deg\)/);
  }
});
