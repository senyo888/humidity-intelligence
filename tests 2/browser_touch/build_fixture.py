#!/usr/bin/env python3
"""Export complete production V2 trees using isolated synthetic registry fixtures."""
import argparse
import asyncio
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests 2'))
from test_runtime_card_sanity import _load_target_modules, _FakeHass, _FakeRegistry, ENTRY_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _, register = _load_target_modules()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={}, options={})
    hass = _FakeHass(entry, {})
    async def generate():
        with patch.object(sys.modules['homeassistant.helpers.entity_registry'], 'async_get', return_value=_FakeRegistry()):
            mapping = await register.async_build_entity_mapping(hass, ENTRY_ID)
            mapping.update({'fan.kitchen_air':'fan.fixture_output', 'fan.living_room_air':'fan.fixture_second',
                            'fan.upstairs_air':'fan.fixture_third'})
            cards = await register.async_register_cards(hass, ENTRY_ID, mapping)
        return cards, mapping
    cards, mapping = asyncio.run(generate())
    spec = importlib.util.spec_from_file_location('fixture_output_cards', ROOT / 'custom_components/humidity_intelligence/adaptive_output/cards.py')
    wiring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wiring)
    layouts = {}
    for name in ('v2_mobile', 'v2_tablet'):
        layouts[name] = yaml.safe_load(cards[name])
        adaptive, _ = wiring.wire_card(cards[name], 'sensor.fixture_output_status')
        layouts[name + '_adaptive'] = yaml.safe_load(adaptive)
    scenario_spec = importlib.util.spec_from_file_location('fixture_stability_replay', ROOT / 'scripts/stability_scenario.py')
    scenario = importlib.util.module_from_spec(scenario_spec)
    scenario_spec.loader.exec_module(scenario)
    backend, _ = scenario.load_backend()
    replay = scenario.build_replay(backend)
    stability_cases = {name: replay['frames'][index]['payload'] for name, index in
                       [('collecting', 12), ('available', 431), ('updated', 432),
                        ('partial', 1188), ('unavailable', 1620)]}
    # A separate movement-vector fixture: each headline/explanation is an actual
    # backend replay result, but 49 -> 54 -> 52 is a controlled score sequence,
    # not a claim about an observed household or a physically timed RH trajectory.
    poor = {score: next(deepcopy(frame['payload']) for frame in replay['frames']
        if frame['payload']['score']['display_score'] == score) for score in (49, 54, 52)}
    at = datetime.fromisoformat(poor[52]['published_at'])
    movement_runtime, previous = {}, {}
    for index, score in enumerate((49, 54, 52)):
        when = at - timedelta(minutes=2 - index)
        movement = backend._recent_score_movement(movement_runtime, previous, score, when)
        previous = {**poor[score], 'published_at': when.isoformat(), 'movement': movement}
    stability_cases['recent_poor'] = previous
    for minutes in range(10, 71, 10):
        when = at + timedelta(minutes=minutes)
        movement = backend._recent_score_movement(movement_runtime, previous, 52, when)
        previous = {**previous, 'published_at': when.isoformat(), 'movement': movement,
            'score_history': {**previous['score_history'], 'current': {'at': when.isoformat(), 'score': 52}}}
    stability_cases['recent_expired'] = previous
    result = {'layouts': layouts, 'mapping': mapping,
              'metadata': hass.data[register.DOMAIN][ENTRY_ID]['ui_revision'],
              'stability_cases': stability_cases, 'stability_provenance': {
                  'simulated': True,
                  'recent_movement_cases': 'Controlled published-score vectors through actual movement backend; headlines/explanations from actual synthetic replay, not live or physical trajectories.',
                  'backend_sha256': hashlib.sha256((ROOT / 'custom_components/humidity_intelligence/helpers/stability.py').read_bytes()).hexdigest(),
                  'formula_version': replay['frames'][-1]['payload']['formula_version']}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'config.json').write_text(json.dumps(result))
    print(f'Exported {len(layouts)} complete layouts to {args.output}')

if __name__ == '__main__':
    main()
