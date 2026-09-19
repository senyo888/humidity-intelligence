"""Exercise drift badges through the actual registry mapping and card exporter.

Run directly with Python or through unittest discovery; no Home Assistant install
is needed. Browser behavior is covered separately by the drift UI checks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hi_drift_export_fixtures", pathlib.Path(__file__).with_name("test_runtime_card_sanity.py")
)
assert SPEC and SPEC.loader
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)

PLACEHOLDER = "sensor.house_humidity_drift_7d"
LAYOUTS = ("v1_mobile", "v2_mobile", "v2_tablet")
GALLERIES = (
    "default-v1-mobile",
    "default-v2-mobile-aq",
    "default-v2-tablet-zone-1-cooking",
)


def drift_block(source: str, entity_id: str) -> str:
    """Extract the complete drift card, independent of layout indentation."""
    entity = re.search(rf"(?m)^([ ]*)entity: {re.escape(entity_id)}$", source)
    assert entity, f"Missing drift card entity: {entity_id}"
    start = source.rfind("- type: custom:button-card", 0, entity.start())
    assert start >= 0
    indent = len(entity.group(1)) - 2
    sibling = re.search(rf"(?m)^ {{0,{indent}}}\S", source[entity.end():])
    end = entity.end() + sibling.start() if sibling else len(source)
    return source[start:end]


class DriftCardExportTests(unittest.TestCase):
    def export(self, drift_entity_id: str | None):
        _, register = fixtures._load_target_modules()

        class Registry(fixtures._FakeRegistry):
            def async_get_entity_id(self, domain, integration, unique_id):
                if unique_id == f"hi_{fixtures.ENTRY_ID}_house_drift_7d":
                    return drift_entity_id
                return super().async_get_entity_id(domain, integration, unique_id)

        entry = SimpleNamespace(entry_id=fixtures.ENTRY_ID, data={}, options={})
        hass = fixtures._FakeHass(entry, {})

        async def run():
            mapping = await register.async_build_entity_mapping(hass, entry.entry_id)
            cards = await register.async_register_cards(hass, entry.entry_id, mapping)
            return mapping, cards, hass.data["humidity_intelligence"][entry.entry_id]

        with patch.object(
            sys.modules["homeassistant.helpers.entity_registry"],
            "async_get", return_value=Registry(),
        ):
            return asyncio.run(run())

    def assert_details_preserved(self, block: str):
        for text in (
            "Baseline · ${progress}%", "Waiting for history", "coverage_ratio",
            "required_age_coverage_ratio", "Baseline progress measures Statistics time coverage",
            "Seven-day humidity drift", "View history", ">Close</button>",
            "action: javascript", "const entityId = entity?.entity_id;",
            "hass-more-info", "detail: { entityId }", "historyButton.disabled = !entityId",
        ):
            self.assertTrue(text in block, f"Missing drift export contract: {text}")

    def test_registry_identity_and_renamed_identity_survive_export(self):
        for entity_id in ("sensor.hi_house_drift_7d", "sensor.example_renamed_drift"):
            with self.subTest(entity_id=entity_id):
                mapping, cards, data = self.export(entity_id)
                self.assertEqual(mapping[PLACEHOLDER], entity_id)
                self.assertEqual(data["unresolved_placeholders_by_card"], {})
                for layout in LAYOUTS:
                    with self.subTest(layout=layout):
                        self.assertNotIn(PLACEHOLDER, cards[layout])
                        self.assert_details_preserved(drift_block(cards[layout], entity_id))

    def test_missing_registry_identity_is_reported_without_inventing_entity(self):
        mapping, cards, data = self.export(None)
        self.assertNotIn(PLACEHOLDER, mapping)
        self.assertIn(PLACEHOLDER, data["unresolved_placeholders"])
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                # Drift is a required sensor: existing export policy keeps it
                # with a warning rather than silently dropping the badge.
                self.assertEqual(data["unresolved_placeholders_by_card"][layout], [PLACEHOLDER])
                self.assertTrue(cards[layout].startswith("# HI WARNING: unresolved placeholders"))
                self.assertNotIn("sensor.hi_house_drift_7d", cards[layout])
                block = drift_block(cards[layout], PLACEHOLDER)
                self.assert_details_preserved(block)
                self.assertIn("const attrs = entity?.attributes || {};", block)
                self.assertIn("text: 'Unavailable'", block)

    def test_gallery_drift_blocks_match_canonical_templates(self):
        for layout, gallery in zip(LAYOUTS, GALLERIES):
            with self.subTest(layout=layout):
                canonical = (ROOT / "custom_components/humidity_intelligence/ui/cards" / f"{layout}.yaml").read_text()
                published = (ROOT / "ui-gallery" / gallery / "card.yaml").read_text()
                self.assertEqual(drift_block(canonical, PLACEHOLDER), drift_block(published, PLACEHOLDER))


if __name__ == "__main__":
    unittest.main()
