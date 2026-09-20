import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const files = [
  'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
  'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
  'ui-gallery/default-v2-mobile-aq/card.yaml',
  'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
];
function expression(source, entity, key) {
  const card = source.indexOf(`entity: ${entity}\n`);
  const match = new RegExp(`^ +${key}:`, 'm').exec(source.slice(card));
  const field = match ? card + match.index : -1;
  assert.ok(card >= 0 && field > card);
  const start = source.indexOf('[[[', field) + 3;
  const end = source.indexOf(']]]', start);
  return new Function('entity', 'states', source.slice(start, end));
}
for (const file of files) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  test(`${file}: humidity rejects absent, malformed and nonfinite evidence`, () => {
    const render = expression(source, 'sensor.house_average_humidity', 'state_display');
    assert.equal(render(undefined), '—%');
    for (const state of ['', 'unknown', 'unavailable', '52x', 'Infinity', 'NaN', '1e999']) {
      assert.equal(render({ state }), '—%', state);
    }
    assert.equal(render({ state: ' 52.6 ' }), '53%');
    assert.equal(render({ state: '0' }), '0%');
  });
  for (const [entity, on, off] of [
    ['input_boolean.air_control_enabled', 'ARMED', 'DISABLED'],
    ['input_boolean.air_control_manual_override', 'MANUAL', 'AUTO'],
  ]) {
    test(`${file}: ${entity} distinguishes absent states without toggling`, () => {
      const render = expression(source, entity, 'state_display');
      const action = expression(source, entity, 'tap_action');
      for (const [state, text] of [['on', on], ['off', off], ['unknown', 'UNKNOWN'], ['unavailable', 'UNAVAILABLE'], ['bad', 'UNAVAILABLE']]) {
        assert.equal(render({ state }), text);
        assert.equal(action({ state }), ['on', 'off'].includes(state) ? 'toggle' : 'none');
      }
      assert.equal(render(undefined), 'UNAVAILABLE');
      assert.equal(action(undefined), 'none');
    });
  }
  test(`${file}: humidity context reports evidence, never operating advice`, () => {
    const render = expression(source, 'sensor.air_control_mode', 'label');
    const states = {
      'sensor.house_humidity_target_low': { state: '40' },
      'sensor.house_humidity_target_high': { state: '60' },
      'sensor.house_humidity_target_season': { state: 'summer' },
    };
    for (const mode of ['co_emergency', 'manual_override', 'disabled', 'global_gate', 'normal']) {
      for (const [state, text] of [['30', 'Below'], ['50', 'Within'], ['70', 'Above'], ['unavailable', 'Unavailable']]) {
        states['sensor.house_average_humidity'] = { state };
        states['sensor.air_control_mode'] = { state: mode };
        const label = render(undefined, states);
        assert.ok(label.includes(`Humidity: ${text}`));
        assert.doesNotMatch(label, /ventilate|humidify|reduce extraction|keep steady/);
      }
    }
  });
  test(`${file}: malformed or inverted target evidence never gets a position`, () => {
    const render = expression(source, 'sensor.air_control_mode', 'label');
    const base = {
      'sensor.house_humidity_target_low': { state: '40' },
      'sensor.house_humidity_target_high': { state: '60' },
      'sensor.house_average_humidity': { state: '50' },
      'sensor.house_humidity_target_season': { state: 'unknown' },
    };
    for (const key of ['sensor.house_humidity_target_low', 'sensor.house_humidity_target_high', 'sensor.house_average_humidity']) {
      for (const state of ['Infinity', '1e999', '50x', '', 'unavailable']) {
        const label = render(undefined, { ...base, [key]: { state } });
        assert.ok(label.includes('Humidity: Unavailable.'));
        assert.ok(label.includes('(Seasonal)'));
        assert.doesNotMatch(label, /Below|Within|Above|Infinity|NaN/);
      }
    }
    assert.ok(render(undefined, { ...base, 'sensor.house_humidity_target_low': { state: '70' } }).includes('Humidity: Unavailable.'));
  });
  test(`${file}: output summary uses resolved identities and observed states`, () => {
    const render = expression(source, 'input_boolean.air_control_output_expanded', 'label');
    const states = {
      'fan.kitchen_air': { state: 'on', attributes: { friendly_name: 'Study fan', percentage: 35 } },
      'fan.living_room_air': { state: 'off', attributes: { friendly_name: 'Bedroom fan' } },
      'fan.upstairs_air': { state: 'unavailable', attributes: {} },
    };
    assert.equal(render(undefined, states), 'Study fan: 35% • Bedroom fan: OFF • fan.upstairs_air: UNAVAILABLE');
    assert.equal(render(undefined, {}), 'fan.kitchen_air: UNAVAILABLE • fan.living_room_air: UNAVAILABLE • fan.upstairs_air: UNAVAILABLE');
    delete states['fan.living_room_air'];
    assert.ok(render(undefined, states).includes('fan.living_room_air: UNAVAILABLE'));
    assert.doesNotMatch(source, /name: (Kitchen|Living room|Upstairs) purifier/);
  });
}
