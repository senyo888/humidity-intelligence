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


HISTORY_SOURCES = {
    'Condensation': ('sensor.worst_room_condensation_risk', 'sensor.worst_room_condensation'),
    'Mould': ('sensor.worst_room_mould_risk', 'sensor.worst_room_mould'),
    'Current Air Control': ('sensor.air_control_mode', 'sensor.air_control_reason'),
    'AQ': ('sensor.air_control_house_iaq_average', 'sensor.air_control_house_pm25_average', 'sensor.air_control_house_voc_average', 'sensor.air_control_house_co_average'),
}
ALL_SOURCES = tuple(dict.fromkeys((*ROUTES.values(), *(source for values in HISTORY_SOURCES.values() for source in values))))

class BadgeSummaryExportTests(unittest.TestCase):
    def export(self, suffix):
        _, register = fixtures._load_target_modules()
        entry = SimpleNamespace(entry_id=fixtures.ENTRY_ID, data={}, options={})
        hass = fixtures._FakeHass(entry, {})
        async def run():
            mapping = await register.async_build_entity_mapping(hass, entry.entry_id)
            # Simulate registry-renamed identities/second entry after the real
            # mapping builder resolves room and house fallback destinations.
            for index, key in enumerate(ALL_SOURCES):
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
                    if config['title'] in HISTORY_SOURCES:
                        self.assertEqual([item['id'] for item in config['historyEntities']], [mapping[key] for key in HISTORY_SOURCES[config['title']]])
                        for key in HISTORY_SOURCES[config['title']]:
                            self.assertNotIn(key, raw)
                        self.assertLessEqual(len(config['historyEntities']), 4)
                self.assertIn('states[entityId]', source)
                self.assertIn('historyButton.disabled', source)
                self.assertIn('window.__hiBadgeDetailsDispose', source)
                self.assertEqual(source.count('// HI-HISTORY-RENDERER:START'), 4)
                self.assertIn('entity_ids:requested', source)
            self.assertNotIn('hi-summary-template', cards['v1_mobile'])
            self.assertNotIn('__hiBadgeDetailsDispose', cards['v1_mobile'])
            self.assertNotIn('hiBadgeHistory', cards['v1_mobile'])

    def test_all_v2_close_buttons_are_accessible_circles_and_v1_is_preserved(self):
        import hashlib
        for layout, folder in (('v2_mobile', 'default-v2-mobile-aq'), ('v2_tablet', 'default-v2-tablet-zone-1-cooking')):
            for path in (ROOT/'custom_components/humidity_intelligence/ui/cards'/f'{layout}.yaml', ROOT/'ui-gallery'/folder/'card.yaml'):
                source = path.read_text()
                buttons = re.findall(r'<button type="button" class="hi-(?:summary|drift|stability)-close"[^>]*>.*?</button>', source)
                self.assertEqual(len(buttons), 10, str(path))
                for button in buttons:
                    self.assertIn('aria-label="Close"', button)
                    self.assertIn('<svg aria-hidden="true"', button)
                    self.assertNotIn('>Close<', button)
                for kind in ('summary', 'drift', 'stability'):
                    rule = re.search(r'\.hi-' + kind + r'-close \{([^}]+)\}', source).group(1)
                    self.assertIn('width:44px', rule)
                    self.assertIn('height:44px', rule)
                    self.assertIn('border-radius:50%', rule)
                    visual = re.search(r'\.hi-' + kind + r'-close::before \{([^}]+)\}', source).group(1)
                    self.assertIn('inset:6px', visual)  # 44px target, 32px circle.
        for path in (ROOT/'custom_components/humidity_intelligence/ui/cards/v1_mobile.yaml', ROOT/'ui-gallery/default-v1-mobile/card.yaml'):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), '55da18480f54990fe1c46f6a4875c1978076061afa86417206b91f8d10e61a89')

    def test_gallery_card_payloads_match_templates(self):
        for layout, folder in (('v2_mobile', 'default-v2-mobile-aq'), ('v2_tablet', 'default-v2-tablet-zone-1-cooking')):
            template = (ROOT/'custom_components/humidity_intelligence/ui/cards'/f'{layout}.yaml').read_text()
            gallery = (ROOT/'ui-gallery'/folder/'card.yaml').read_text()
            self.assertEqual(template[template.index('type: custom:mod-card'):], gallery[gallery.index('type: custom:mod-card'):])

if __name__ == '__main__':
    unittest.main()
