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
const OMIT = Symbol('omit');

function reasonBody(relativePath) {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const start = source.indexOf('        reason: |\n');
  const end = source.indexOf('        aq: |\n', start);
  assert.notEqual(start, -1, `${relativePath}: reason block missing`);
  assert.notEqual(end, -1, `${relativePath}: AQ boundary missing`);
  const lines = source.slice(start, end).split('\n');
  const open = lines.indexOf('          [[[');
  const close = lines.lastIndexOf('          ]]]');
  assert.ok(open >= 0 && close > open, `${relativePath}: button-card wrapper missing`);
  return lines
    .slice(open + 1, close)
    .map((line) => (line.startsWith('            ') ? line.slice(12) : line))
    .join('\n');
}

function statusBody(relativePath) {
  const source = fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
  const start = source.indexOf('        status: |\n');
  const end = source.indexOf('        reason: |\n', start);
  assert.notEqual(start, -1, `${relativePath}: status block missing`);
  assert.notEqual(end, -1, `${relativePath}: reason boundary missing`);
  const lines = source.slice(start, end).split('\n');
  const open = lines.indexOf('          [[[');
  const close = lines.lastIndexOf('          ]]]');
  assert.ok(open >= 0 && close > open, `${relativePath}: button-card wrapper missing`);
  return lines
    .slice(open + 1, close)
    .map((line) => (line.startsWith('            ') ? line.slice(12) : line))
    .join('\n');
}

const BODIES = SURFACES.map(reasonBody);
const RENDERERS = SURFACES.map((file, index) => {
  const source = fs.readFileSync(path.join(ROOT, file), 'utf8');
  const start = source.indexOf('[[[', source.indexOf('hi_reason_html: &hi_reason_html |')) + 3;
  const present = new Function('states', source.slice(start, source.indexOf(']]]', start)));
  const render = new Function('variables', BODIES[index]);
  return states => render({hi_reason_html: present(states)});
});
const STATUS_BODIES = SURFACES.map(statusBody);
const STATUS_RENDERERS = STATUS_BODIES.map((body) => new Function('states', body));

function baseContract() {
  return {
    schema: 'hi.reason.v1',
    locale: 'en',
    family: 'normal',
    variant: 'monitoring',
    attention: 'neutral',
    truncated: false,
    headline: 'Monitoring',
    lines: [
      {
        role: 'notice',
        scope: 'system',
        code: 'normal.monitoring',
        truth: 'observed',
        text: 'HI is monitoring, and no ventilation response is selected.',
        args: { selected: false },
      },
    ],
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function renderAll(
  displayReason,
  {
    fullReason = 'Legacy technical reason.',
    state = 'Legacy state reason.',
    extraStates = {},
  } = {},
) {
  return RENDERERS.map((render) => {
    const attributes = {};
    if (fullReason !== OMIT) attributes.full_reason = fullReason;
    if (displayReason !== OMIT) attributes.display_reason = displayReason;
    const states = {
      ...extraStates,
      'sensor.air_control_reason': {
        state: state === OMIT ? '' : state,
        attributes,
      },
    };
    return render(states);
  });
}

function assertIdentical(outputs) {
  assert.equal(new Set(outputs).size, 1);
  return outputs[0];
}

function assertLegacyFallback(displayReason, options = {}) {
  const output = assertIdentical(renderAll(displayReason, options));
  assert.match(output, /Legacy technical reason\./);
  assert.doesNotMatch(output, /Monitoring<\/span>/);
  return output;
}

test('all four V2 surfaces carry one identical reason renderer', () => {
  assert.equal(new Set(BODIES).size, 1);
});

test('all four V2 surfaces carry one identical status renderer', () => {
  assert.equal(new Set(STATUS_BODIES).size, 1);
});

test('humidity danger chip stops after the resolved zone', () => {
  const states = {
    'sensor.air_control_mode': { state: 'alert', attributes: {} },
    'sensor.active_alert_context': {
      state: 'Humidity Danger · Bathroom · Zone 2 · 68.2% >= 68% threshold',
      attributes: {},
    },
    'sensor.air_control_reason': { state: 'Danger alert active.', attributes: {} },
  };
  const output = assertIdentical(STATUS_RENDERERS.map((render) => render(states)));
  assert.match(output, /Humidity Danger · Bathroom · Zone 2/);
  assert.doesNotMatch(output, /68\.2%|68% threshold/);
});

test('unmapped humidity danger chip drops measurement without dropping room', () => {
  const states = {
    'sensor.air_control_mode': { state: 'alert', attributes: {} },
    'sensor.active_alert_context': {
      state: 'Humidity Danger · Conservatory · 72.1% >= 68% threshold',
      attributes: {},
    },
    'sensor.air_control_reason': { state: 'Danger alert active.', attributes: {} },
  };
  const output = assertIdentical(STATUS_RENDERERS.map((render) => render(states)));
  assert.match(output, /Humidity Danger · Conservatory/);
  assert.doesNotMatch(output, /72\.1%|68% threshold/);
});

test('non-humidity alert context is never shortened by comparison syntax', () => {
  const states = {
    'sensor.air_control_mode': { state: 'alert', attributes: {} },
    'sensor.active_alert_context': {
      state: 'Mould Risk · Bathroom · Zone 2 · observed >= risk threshold',
      attributes: {},
    },
    'sensor.air_control_reason': { state: 'Risk alert active.', attributes: {} },
  };
  const output = assertIdentical(STATUS_RENDERERS.map((render) => render(states)));
  assert.match(output, /Mould Risk · Bathroom · Zone 2 · observed &gt;= risk threshold/);
});

test('active zone and humidifier share one concise labelled status row', () => {
  const states = {
    'sensor.air_control_mode': { state: 'bathroom', attributes: {} },
    'sensor.air_control_reason': {
      state: 'Bathroom response selected.',
      attributes: {
        humidifier_status: {
          lanes: {
            level1: { demand: 'requested', reconciliation: 'output_on' },
            level2: { demand: 'inactive', reconciliation: 'inactive' },
          },
        },
      },
    },
  };
  const output = assertIdentical(STATUS_RENDERERS.map((render) => render(states)));
  assert.doesNotMatch(output, /class="cv-chip-stack"/);
  assert.equal((output.match(/class="cv-scroll"/g) || []).length, 1);
  assert.match(output, /aria-label="Current Air Control status"/);
  assert.match(output, /ZONE 2/);
  assert.match(output, /Downstairs Humidifier · On/);
  assert.doesNotMatch(output, /Humidifier Downstairs|Output on/);
});

test('humidifier stays on the single status row outside an active zone lane', () => {
  const states = {
    'sensor.air_control_mode': { state: 'normal', attributes: {} },
    'sensor.air_control_reason': {
      state: 'Monitoring.',
      attributes: {
        humidifier_status: {
          lanes: {
            level1: { demand: 'requested', reconciliation: 'output_on' },
          },
        },
      },
    },
  };
  const output = assertIdentical(STATUS_RENDERERS.map((render) => render(states)));
  assert.doesNotMatch(output, /class="cv-chip-stack"/);
  assert.equal((output.match(/class="cv-scroll"/g) || []).length, 1);
  assert.match(output, /aria-label="Current Air Control status"/);
  assert.match(output, /Downstairs Humidifier · On/);
});

test('valid schema renders escaped headline and ordered backend text', () => {
  const contract = baseContract();
  contract.headline = 'Monitoring & control "view"';
  contract.lines.push({
    role: 'action',
    scope: 'ventilation',
    code: 'normal.no_output_selected',
    truth: 'selected',
    text: "HI hasn't selected an output & remains ready.",
  });
  const output = assertIdentical(renderAll(contract, {
    extraStates: {
      'timer.air_control_pause': { state: 'active' },
      'input_boolean.air_isolate_fan_outputs': { state: 'on' },
      'sensor.worst_room_mould': { state: 'Kitchen', attributes: { risk: 'danger' } },
    },
  }));

  assert.match(output, /role="region"/);
  assert.match(output, /tabindex="0"/);
  assert.match(output, /Monitoring &amp; control &quot;view&quot;/);
  assert.match(output, /HI hasn&#39;t selected an output &amp; remains ready\./);
  assert.ok(output.indexOf('HI is monitoring') < output.indexOf('HI hasn&#39;t selected'));
  assert.doesNotMatch(output, /Stage:|Engine:|Timer:|Risk:/);
});

test('calm neutral and benign dotted tokens are never suppressed', () => {
  const contract = baseContract();
  contract.family = 'air_quality';
  contract.variant = 'pm25_high';
  contract.headline = 'Air quality response lane selected';
  contract.lines[0].text = 'PM2.5 is 48 µg/m³; HI v2.0.10 selected the configured response.';
  const output = assertIdentical(renderAll(contract));
  assert.match(output, /PM2\.5 is 48 µg\/m³/);
  assert.match(output, /HI v2\.0\.10 selected/);

  contract.lines[0].text = 'Configured label Ground.Floor remains display text.';
  assert.match(assertIdentical(renderAll(contract)), /Ground\.Floor/);
});

test('absent, future, malformed, partial, and privacy-invalid contracts fall back atomically', () => {
  const fixtures = [];
  fixtures.push(OMIT, null, [], 'hi.reason.v1');

  let value = baseContract();
  value.schema = 'hi.reason.v2';
  fixtures.push(value);
  value = baseContract();
  value.locale = 'cy';
  fixtures.push(value);
  value = baseContract();
  delete value.headline;
  fixtures.push(value);
  value = baseContract();
  value.extra = true;
  fixtures.push(value);
  value = baseContract();
  value.headline = '';
  fixtures.push(value);
  value = baseContract();
  value.lines = [];
  fixtures.push(value);
  value = baseContract();
  value.lines = Array.from({ length: 9 }, () => clone(value.lines[0]));
  fixtures.push(value);
  value = baseContract();
  value.attention = 'safe';
  fixtures.push(value);
  value = baseContract();
  value.lines.push({ ...clone(value.lines[0]), text: 42 });
  fixtures.push(value);
  value = baseContract();
  value.lines[0].unexpected = true;
  fixtures.push(value);
  value = baseContract();
  value.lines[0].args = Object.fromEntries(
    Array.from({ length: 7 }, (_, index) => [`arg_${index}`, index]),
  );
  fixtures.push(value);
  value = baseContract();
  value.headline = 'Output sensor.private_room selected';
  fixtures.push(value);
  value = baseContract();
  value.lines[0].args = { output_label: 'fan.private_output' };
  fixtures.push(value);
  value = baseContract();
  value.lines[0].text = '<b>Injected contract text</b>';
  fixtures.push(value);
  value = baseContract();
  value.lines[0].text = 'Hidden\u2066directional isolate';
  fixtures.push(value);

  for (const fixture of fixtures) assertLegacyFallback(fixture);
});

test('unicode, text, argument, line, and serialized byte bounds are enforced', () => {
  let value = baseContract();
  value.headline = '😀'.repeat(120);
  assert.match(assertIdentical(renderAll(value)), /😀/u);

  value = baseContract();
  value.headline = '😀'.repeat(121);
  assertLegacyFallback(value);
  value = baseContract();
  value.lines[0].text = 'x'.repeat(200);
  assert.match(assertIdentical(renderAll(value)), /x{200}/);
  value = baseContract();
  value.lines[0].text = 'x'.repeat(201);
  assertLegacyFallback(value);

  value = baseContract();
  value.lines = Array.from({ length: 8 }, (_, lineIndex) => ({
    role: 'notice',
    scope: 'system',
    code: `normal.long_line_${lineIndex}`,
    truth: 'observed',
    text: 'x'.repeat(200),
    args: Object.fromEntries(
      Array.from({ length: 6 }, (_, argIndex) => [
        `arg_${argIndex}`,
        'y'.repeat(64),
      ]),
    ),
  }));
  assert.ok(new TextEncoder().encode(JSON.stringify(value)).length > 4096);
  assertLegacyFallback(value);
});

test('legacy fallback is escaped and follows full_reason then state then fixed text', () => {
  let output = assertIdentical(renderAll(OMIT, {
    fullReason: '<img src=x onerror=alert(1)>',
    state: '<b>state</b>',
  }));
  assert.match(output, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(output, /<img/);

  output = assertIdentical(renderAll(OMIT, {
    fullReason: '',
    state: '<b>state & reason</b>',
  }));
  assert.match(output, /&lt;b&gt;state &amp; reason&lt;\/b&gt;/);
  assert.doesNotMatch(output, /<b>/);

  for (const state of ['', 'unknown', 'unavailable']) {
    output = assertIdentical(renderAll(OMIT, { fullReason: 'retained healthy text', state }));
    assert.match(output, state === 'unknown' ? /Reason unknown\./ : /Reason unavailable\./);
    assert.doesNotMatch(output, /retained healthy/);
  }
});

test('attribute access failure still reaches the state fallback', () => {
  for (const render of RENDERERS) {
    const reasonState = { state: 'State fallback after attribute failure.' };
    Object.defineProperty(reasonState, 'attributes', {
      get() {
        throw new Error('fixture attribute failure');
      },
    });
    const output = render({ 'sensor.air_control_reason': reasonState });
    assert.match(output, /State fallback after attribute failure\./);
  }
});
