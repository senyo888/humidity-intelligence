import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SURFACES = [
  'custom_components/humidity_intelligence/ui/cards/v1_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
  'ui-gallery/default-v1-mobile/card.yaml',
  'ui-gallery/default-v2-mobile-aq/card.yaml',
  'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
];
const sources = SURFACES.map(p => fs.readFileSync(path.join(ROOT, p), 'utf8'));
function body(source, key) {
  const card = source.indexOf('entity: sensor.house_humidity_drift_7d\n');
  const start = source.indexOf(`${key}: |\n`, card);
  assert.ok(start > card, `${key} must exist in drift card`);
  return source.slice(source.indexOf('[[[', start) + 3, source.indexOf(']]]', start)).trim()
    .split('\n').map(s => s.trimStart()).join('\n');
}
const bodies = key => sources.map(s => body(s, key));
const views = bodies('hi_drift').map(s => new Function('entity', s));
const states = bodies('state_display').map(s => new Function('variables', s));
const details = bodies('details').map(s => new Function('variables', s));
const historyReason = 'statistics_dependency_history_not_ready';
const baseline = overrides => ({
  status: 'unavailable', reason: historyReason, blocking_reasons: [historyReason],
  dependency_status: 'history_not_ready', current_house_humidity: 48,
  source_value_valid: true, age_coverage_ratio: .22, required_age_coverage_ratio: .85,
  ...overrides,
});
function render(state = 'unknown', attrs = baseline()) {
  const results = views.map(fn => {
    const result = fn({ state, attributes: attrs });
    // V1 keeps its approved copy; V2 uses positive phrasing with the same status.
    const legacyCopy = {
      'The Statistics helper is waiting for a usable value.': 'The Statistics helper has no usable value yet.',
      'The Statistics helper needs a numeric mean to calculate drift.': 'The Statistics helper is not reporting a numeric mean.',
      'Drift and baseline progress are awaiting valid evidence.': 'Drift is unavailable. Baseline progress cannot be confirmed.',
    };
    return {...result, detail: legacyCopy[result.detail] || result.detail};
  });
  results.forEach(v => assert.deepEqual(v, results[0]));
  return results[0];
}

test('all layouts retain drift calculation and V2 presentation matches its gallery mirrors', () => {
  for (const key of ['state_display', 'open']) {
    assert.equal(new Set(bodies(key)).size, 1, key);
  }
  for (const key of ['hi_drift', 'details', 'javascript']) {
    const all = bodies(key);
    assert.equal(all[0], all[3], `V1 mirror: ${key}`);
    assert.equal(new Set([all[1], all[2], all[4], all[5]]).size, 1, `V2: ${key}`);
  }
});

test('ready positive, negative and zero preserve signed drift semantics', () => {
  for (const [raw, text] of [['2.3', '+2.3%'], ['-2.3', '-2.3%'], ['0', '0.0%']]) {
    const view = render(raw, {});
    assert.equal(view.kind, 'ready'); assert.equal(view.text, text);
    states.forEach(fn => assert.equal(fn({ hi_drift: view }), text));
    assert.equal(view.progress, undefined);
  }
});

test('baseline is floored progress toward the reported requirement, never a bucket count', () => {
  for (const [coverage, expected] of [[0, 0], [.22, 25], [.425, 50], [.849999, 99]]) {
    const view = render('unknown', baseline({ age_coverage_ratio: coverage }));
    assert.equal(view.progress, expected);
    assert.equal(view.text, `Baseline · ${expected}%`);
    details.forEach(fn => {
      const html = fn({ hi_drift: view });
      assert.match(html, new RegExp(`value="${expected}"`));
      assert.match(html, /Baseline progress measures Statistics time coverage|Progress follows the Statistics helper’s time coverage/);
      assert.doesNotMatch(html, /Collecting|Baseline progress: 100%/);
    });
  }
  assert.equal(render('unknown', baseline({ required_age_coverage_ratio: .5 })).progress, 44);
});

test('reset/regression is shown immediately and numeric readiness clears progress', () => {
  assert.equal(render('unknown', baseline({ age_coverage_ratio: .8 })).progress, 94);
  assert.equal(render('unknown', baseline({ age_coverage_ratio: .1 })).progress, 11);
  const ready = render('0', {});
  assert.equal(ready.kind, 'ready'); assert.equal(ready.progress, undefined);
  assert.doesNotMatch(details[0]({ hi_drift: ready }), /<progress/);
});

test('threshold contradictions, malformed ratios and unsafe numeric coercion cannot show progress', () => {
  for (const bad of [null, true, false, '', '0.22', NaN, Infinity, -1, 2]) {
    assert.equal(render('unknown', baseline({ age_coverage_ratio: bad })).kind, 'unavailable');
    assert.equal(render('unknown', baseline({ required_age_coverage_ratio: bad })).kind, 'unavailable');
  }
  for (const required of [0, -.5, 1.1]) {
    assert.equal(render('unknown', baseline({ required_age_coverage_ratio: required })).kind, 'unavailable');
  }
  for (const coverage of [.85, .9, 1]) {
    assert.equal(render('unknown', baseline({ age_coverage_ratio: coverage })).kind, 'unavailable');
  }
  for (const raw of [null, undefined, true, false, NaN, Infinity, '', ' ', '2.3bad', 'NaN', 'Infinity']) {
    assert.equal(render(raw, {}).kind, 'unavailable');
  }
});

test('missing ratios are waiting, never fabricated numeric progress', () => {
  assert.equal(render('unknown', baseline({ age_coverage_ratio: null, required_age_coverage_ratio: undefined })).kind, 'unavailable');
  for (const attrs of [baseline({ age_coverage_ratio: undefined }), baseline({ required_age_coverage_ratio: undefined })]) {
    const view = render('unavailable', attrs);
    assert.equal(view.kind, 'waiting'); assert.equal(view.progress, undefined);
    assert.doesNotMatch(details[0]({ hi_drift: view }), /<progress/);
  }
});

test('current humidity, source-invalid and additional blockers take precedence', () => {
  for (const current of [undefined, null, '', '48', false, NaN, Infinity]) {
    assert.equal(render('unknown', baseline({ current_house_humidity: current })).kind, 'unavailable');
  }
  for (const source of [false, null, 'true', 'unknown', 0]) {
    assert.equal(render('unknown', baseline({ source_value_valid: source })).kind, 'unavailable');
  }
  // Omitted source validity does not prove freshness, but does not override the backend shortfall.
  assert.equal(render('unknown', baseline({ source_value_valid: undefined })).kind, 'baseline');
  for (const blockers of [undefined, null, [], [historyReason, 'current_house_humidity_unavailable'], 'history_not_ready']) {
    assert.equal(render('unknown', baseline({ blocking_reasons: blockers })).kind, 'unavailable');
  }
  assert.equal(render('unknown', baseline({ reason: 'current_house_humidity_unavailable' })).kind, 'unavailable');
  assert.equal(render('unknown', baseline({ dependency_status: 'source_not_valid' })).kind, 'unavailable');
  assert.equal(render('2.3', baseline()).kind, 'unavailable');
});

test('missing helper is explicit setup while other unavailable causes stay distinct', () => {
  const reason = 'statistics_dependency_missing';
  const view = render('unknown', { reason, dependency_status: 'missing', blocking_reasons: [reason] });
  assert.equal(view.kind, 'setup'); assert.equal(view.text, 'Setup needed');
  for (const dependency_status of ['unknown', 'unavailable', 'non_numeric', 'source_not_valid']) {
    const v = render('unknown', baseline({ dependency_status, reason: `statistics_dependency_${dependency_status}` }));
    assert.equal(v.kind, 'unavailable'); assert.equal(v.progress, undefined);
  }
});

test('backend repair text is escaped and no inline executable event attributes are emitted', () => {
  const reason = 'statistics_dependency_missing';
  const view = render('unknown', { reason, blocking_reasons: [reason], dependency_status: 'missing', repair_summary: '<img src=x onerror="bad"> & \'x\'' });
  for (const fn of details) {
    const html = fn({ hi_drift: view });
    assert.doesNotMatch(html, /<img|onclick=|onkeydown=/);
    assert.match(html, /&lt;img src=x onerror=&quot;bad&quot;&gt; &amp; &#039;x&#039;/);
  }
});

test('history action uses the resolved entity and connected owner without a service call', () => {
  for (const action of bodies('javascript')) {
    assert.match(action, /entity\?\.entity_id/);
    assert.match(action, /owner\.dispatchEvent\(new CustomEvent\('hass-more-info'/);
    assert.match(action, /bubbles: true, composed: true/);
    assert.doesNotMatch(action, /callService|call-service|crypto|randomUUID|sensor\.house_humidity/);
    assert.match(action, /observer\?\.disconnect/);
    assert.match(action, /current\.innerHTML !== snapshot/);
  }
});

 test('native opener provides keyboard focus and lets the supported card action handle gestures', () => {
  const view = render();
  for (const code of bodies('open')) {
    const html = new Function('variables', code)({ hi_drift: view });
    assert.match(html, /<button type="button"/);
    assert.match(html, /aria-label="Seven-day humidity drift: Baseline · 25%/);
    assert.doesNotMatch(html, /onclick=|onkeydown=|popovertarget/);
  }
});
