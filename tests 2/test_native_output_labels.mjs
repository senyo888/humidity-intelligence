import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const paths = [
  'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
  'ui-gallery/default-v2-mobile-aq/card.yaml',
  'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
];
function expression(path) {
  const source = fs.readFileSync(new URL('../' + path, import.meta.url), 'utf8');
  const card = source.indexOf('entity: input_boolean.air_control_output_expanded\n');
  assert.ok(card >= 0);
  const field = card + /^ +label:/m.exec(source.slice(card)).index;
  const start = source.indexOf('[[[', field) + 3;
  const body = source.slice(start, source.indexOf(']]]', start));
  const ids = new Function('return ' + /const outputIds = (\[[^\n]+\]);/.exec(body)[1])();
  return {body, ids, render: new Function('states', body)};
}
const labels = paths.map(path => ({path, ...expression(path)}));
test('all native label copies enforce the same boundary', () => {
  const normalise = body => body.trim().split('\n').map(line => line.trim()).join('\n');
  for (const label of labels) assert.equal(normalise(label.body), normalise(labels[0].body));
});
for (const {path, ids, render} of labels) {
  function output(state = 'on', attrs = {}) {
    return render({[ids[0]]: {state, attributes: {friendly_name: 'Ventilation', ...attrs}}});
  }
  test(path + ': every device text field stays text', () => {
    for (const field of ['friendly_name', 'preset_mode', 'state']) {
      const marker = '<em title="quoted" data-note=\'value\'>A & B</em>';
      const result = field === 'state' ? output(marker) : output('on', {[field]: marker});
      assert.doesNotMatch(result, /[<>]/);
      assert.match(result, /&lt;/); assert.match(result, /&gt;/);
      assert.match(result, /&amp;/); assert.match(result, /&quot;/); assert.match(result, /&#39;/);
    }
    assert.match(output('on', {friendly_name: '&lt;em&gt;literal&lt;/em&gt;'}), /&amp;lt;em&amp;gt;/);
  });
  test(path + ': percentages require finite numbers and retain normal precedence', () => {
    for (const percentage of [0, 37.5, 100]) {
      assert.ok(output('on', {percentage, preset_mode: 'quiet'}).includes(`Ventilation: ${percentage}%`));
    }
    for (const percentage of ['<em>bad</em>', '50', NaN, Infinity, -Infinity, true, {}, []]) {
      const rendered = output('on', {percentage, preset_mode: 'quiet'});
      assert.ok(rendered.includes('Ventilation: QUIET'));
      assert.doesNotMatch(rendered, /<|>|NaN|Infinity|50%/);
    }
    assert.ok(output('on', {percentage: NaN}).includes('Ventilation: ON'));
  });
  test(path + ': missing, unavailable, off, and isolation status remain explicit', () => {
    assert.ok(output('unknown').includes('Ventilation: UNKNOWN'));
    assert.ok(output('unavailable').includes('Ventilation: UNAVAILABLE'));
    assert.ok(output('off', {percentage: 50}).includes('Ventilation: OFF'));
    assert.ok(output(null).includes('Ventilation: UNAVAILABLE'));
    assert.ok(render({}).includes('UNAVAILABLE'));
    const rendered = render({
      [ids[0]]: {state: 'on', attributes: {friendly_name: '  Fan & Filter  ', percentage: 0}},
      'input_boolean.air_co_emergency_active': {state: 'on'},
      'input_boolean.air_isolate_fan_outputs': {state: 'on'},
      'input_boolean.air_isolate_humidifier_outputs': {state: 'on'},
    });
    assert.ok(rendered.includes('Fan &amp; Filter: 0%'));
    assert.ok(rendered.endsWith(' • CO EMERGENCY • FAN ISO • HUM ISO'));
  });
}
