"""Verify V2 summary routes survive actual mapping/export and V1 stays unchanged."""
import asyncio
import importlib.util
import pathlib
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('summary_export_fixtures', pathlib.Path(__file__).with_name('test_runtime_card_sanity.py'))
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)
ROUTES = {
    'Humidity': 'sensor.house_average_humidity',
    'Condensation': 'sensor.worst_room_condensation',
    'Mould': 'sensor.worst_room_mould',
    'Current Air Control': 'sensor.air_control_mode',
    'Ready': 'sensor.house_average_humidity',
    'Zone 1': 'sensor.kitchen_humidity',
    'Zone 2': 'sensor.bathroom_humidity',
    'AQ': 'sensor.air_control_house_iaq_average',
}

class BadgeSummaryExportTests(unittest.TestCase):
    def export(self, suffix):
        _, register = fixtures._load_target_modules()
        entry = SimpleNamespace(entry_id=fixtures.ENTRY_ID, data={}, options={})
        hass = fixtures._FakeHass(entry, {})
        async def run():
            mapping = await register.async_build_entity_mapping(hass, entry.entry_id)
            # Simulate registry-renamed identities/second entry after the real
            # mapping builder resolves room and house fallback destinations.
            for index, key in enumerate(dict.fromkeys(ROUTES.values())):
                mapping[key] = f'sensor.summary_{suffix}_{index}'
            cards = await register.async_register_cards(hass, entry.entry_id, mapping)
            return mapping, cards
        with patch.object(sys.modules['homeassistant.helpers.entity_registry'], 'async_get', return_value=fixtures._FakeRegistry()):
            return asyncio.run(run())

    def test_all_summary_routes_are_replaced_in_rendered_configuration(self):
        for suffix in ('renamed', 'entry_two'):
            mapping, cards = self.export(suffix)
            for layout in ('v2_mobile', 'v2_tablet'):
                source = cards[layout]
                configs = re.findall(r'\[\[\[ return (\{"title": .*?\}); \]\]\]', source)
                self.assertEqual(len(configs), 8)
                import json
                for raw in configs:
                    config = json.loads(raw)
                    self.assertEqual(config['history'], mapping[ROUTES[config['title']]])
                    self.assertNotIn(ROUTES[config['title']], raw)
                self.assertIn('states[entityId]', source)
                self.assertIn('mapped entity is missing', source)
                self.assertIn('window.__hiBadgeDetailsDispose', source)
            self.assertNotIn('hi-summary-template', cards['v1_mobile'])
            self.assertNotIn('__hiBadgeDetailsDispose', cards['v1_mobile'])

    def test_gallery_card_payloads_match_templates(self):
        for layout, folder in (('v2_mobile', 'default-v2-mobile-aq'), ('v2_tablet', 'default-v2-tablet-zone-1-cooking')):
            template = (ROOT/'custom_components/humidity_intelligence/ui/cards'/f'{layout}.yaml').read_text()
            gallery = (ROOT/'ui-gallery'/folder/'card.yaml').read_text()
            self.assertEqual(template[template.index('type: custom:mod-card'):], gallery[gallery.index('type: custom:mod-card'):])

if __name__ == '__main__':
    unittest.main()
