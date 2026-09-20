#!/usr/bin/env python3
"""Export complete production V2 trees using isolated synthetic registry fixtures."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
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
    result = {'layouts': layouts, 'mapping': mapping,
              'metadata': hass.data[register.DOMAIN][ENTRY_ID]['ui_revision']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'config.json').write_text(json.dumps(result))
    print(f'Exported {len(layouts)} complete layouts to {args.output}')

if __name__ == '__main__':
    main()
