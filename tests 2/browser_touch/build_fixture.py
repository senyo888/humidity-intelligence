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


def update_cases():
    """Normalize synthetic HACS states through the production read-only adapter."""
    spec = importlib.util.spec_from_file_location(
        'fixture_update_observation',
        ROOT / 'custom_components/humidity_intelligence/helpers/update_observation.py',
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    entity_id = 'update.fixture_hi_renamed'
    registry_entry = SimpleNamespace(
        entity_id=entity_id, domain='update', platform='hacs',
        unique_id=adapter.REPOSITORY_ID, disabled_by=None,
    )
    cases = {}
    for name, state, attributes in [
        ('reported_update', 'on', {'installed_version': '2.1.1-beta.3', 'latest_version': '2.1.1-beta.4'}),
        ('no_update_reported', 'off', {'installed_version': '2.1.1-beta.4', 'latest_version': '2.1.0'}),
        ('skipped', 'off', {'installed_version': '2.1.1-beta.3', 'latest_version': '2.1.1-beta.4', 'skipped_version': '2.1.1-beta.4'}),
        ('in_progress', 'on', {'installed_version': '2.1.1-beta.3', 'latest_version': '2.1.1-beta.4', 'in_progress': 0}),
        ('unavailable', 'unavailable', {}),
        ('unknown', 'unknown', {}),
        ('missing', None, {}),
        ('escaped_version', 'on', {'installed_version': '2.1.1-beta.3', 'latest_version': '<b data-fixture-untrusted="yes">beta</b>'}),
    ]:
        attributes = {'skipped_version': None, 'in_progress': False, **attributes}
        provider = None if state is None else {'entity_id': entity_id, 'state': state, 'attributes': attributes}
        fake_hass = SimpleNamespace(states={} if provider is None else {entity_id: SimpleNamespace(**provider)})
        entries = {} if provider is None else {entity_id: registry_entry}
        with patch.object(adapter.er, 'async_get', return_value=SimpleNamespace(entities=entries)):
            observation = adapter.update_observation(fake_hass)
        cases[name] = {'observation': observation, 'provider': provider}
    return cases


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
              'source_sha256': {
                  name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in [
                      'custom_components/humidity_intelligence/manifest.json',
                      'custom_components/humidity_intelligence/helpers/update_observation.py',
                      'custom_components/humidity_intelligence/ui/revision.py',
                      'custom_components/humidity_intelligence/ui/revision_status.js',
                      'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
                      'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
                      'custom_components/humidity_intelligence/adaptive_output/hi-adaptive-output-card.js',
                  ]
              },
              'update_cases': update_cases(),
              'update_provenance': {
                  'simulated': True,
                  'adapter_sha256': hashlib.sha256((ROOT / 'custom_components/humidity_intelligence/helpers/update_observation.py').read_bytes()).hexdigest(),
                  'description': 'Synthetic registry and provider states normalized by the production adapter; not installed HACS or live Home Assistant evidence.',
              },
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
