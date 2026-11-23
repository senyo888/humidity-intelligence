"""Render the production-exported AQ strip, including optional binding collisions."""
import asyncio
import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from test_runtime_card_sanity import ENTRY_ID, _FakeHass, _FakeRegistry, _load_target_modules


ENTRY_BINDING = hashlib.sha256(f"humidity_intelligence:ui-revision:{ENTRY_ID}".encode()).hexdigest()
KEY = "00000000-0000-4000-8000-000000000042"
ROW = {"source_key": KEY, "label": "Test sensor.example_label ]]] <index>", "entity_id": "sensor.example_index"}


def nodes(tree):
    if isinstance(tree, list):
        for child in tree:
            yield from nodes(child)
    elif isinstance(tree, dict):
        yield tree
        for child in tree.values():
            yield from nodes(child)


def exports(section):
    _, register = _load_target_modules()
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={}, options={"voc_index_sources": section})
    hass = _FakeHass(entry, {})

    class Registry(_FakeRegistry):
        def async_get_entity_id(self, domain, integration, unique_id):
            if unique_id == f"hi_{ENTRY_ID}_voc_index_sources":
                return "sensor.hi_diagnostics"  # Deliberate collision with another placeholder.
            if unique_id == f"hi_{ENTRY_ID}_diagnostics":
                return "sensor.example_diagnostics"
            return super().async_get_entity_id(domain, integration, unique_id)

    async def generate():
        mapping = await register.async_build_entity_mapping(hass, ENTRY_ID)
        return await register.async_register_cards(hass, ENTRY_ID, mapping)

    with patch.object(sys.modules["homeassistant.helpers.entity_registry"], "async_get", return_value=Registry()):
        cards = asyncio.run(generate())
    for layout in ("v2_mobile", "v2_tablet"):
        yield next(node for node in nodes(yaml.safe_load(cards[layout])) if node.get("name") == "Current Air Control")


def render(expression, states):
    result = subprocess.run(
        ["node", "-e", """const [body, states] = JSON.parse(require('node:fs').readFileSync(0,'utf8'));
console.log(new Function('states', body)(states));"""],
        input=json.dumps([expression.strip()[3:-3], states]), text=True, capture_output=True, check=True,
    )
    return result.stdout


def test_generated_strip_uses_same_entry_config_units_and_source_status():
    states = {
        "sensor.example_diagnostics": {"state": "ok", "attributes": {"config": {"telemetry": [
            {"sensor_type": "voc", "level": "level1"}, {"sensor_type": "humidity", "level": None},
        ]}}},
        "sensor.hi_house_voc_average": {"state": "100", "attributes": {"unit_of_measurement": "ppb"}},
        "sensor.hi_level1_voc_average": {"state": "unknown", "attributes": {}},
        "sensor.hi_house_co_average": {"state": "50", "attributes": {"unit_of_measurement": "ppm"}},
        "sensor.hi_diagnostics": {"state": "1", "attributes": {"schema": 2, "entry": ENTRY_BINDING, "readings": {
            KEY: {"label": ROW["label"], "status": "available", "value": 0},
        }}},
    }
    for card in exports([ROW]):
        expr = card["custom_fields"]["aq"]
        assert "sensor.hi_diagnostics" in card["triggers_update"]
        assert "sensor.example_diagnostics" in card["triggers_update"]
        assert "sensor.example_label" not in expr
        html = render(expr, states)
        assert "100 ppb" in html and "Unknown" in html and "House CO" not in html
        assert ">House VOC</span>" in html and "VOC concentration" not in html
        assert "AQ configuration" not in html and "Test sensor.example_label ]]] &lt;index&gt; VOC index" in html
        unlevelled = {"sensor_type": "voc", "level": None}
        diag = {"state": "ok", "attributes": {"config": {"telemetry": [unlevelled]}}}
        incomplete = render(expr, {**states, "sensor.example_diagnostics": diag})
        assert "AQ configuration" in incomplete and "Incomplete" in incomplete and "House VOC" in incomplete
        assert '>0</span>' in html and "#ef4444" not in html
        key = "sensor.hi_house_voc_average"
        for band, color in ((1, "#4ade80"), (2, "#facc15"), (3, "#ef4444")):
            attrs = {"unit_of_measurement": "ppb", "aq_display_band": band}
            colored = render(expr, {**states, key: {"state": "100", "attributes": attrs}})
            assert f'color:{color}">100 ppb' in colored
            assert colored.count(f'role="group" aria-label="HI display range {band} of 3"') == 1
            assert "Band " not in colored
            assert '>100 ppb</span></span>' in colored
            for raw, unit in (("unavailable", "ppb"), ("100", "index")):
                fallback = render(expr, {**states, key: {
                    "state": raw, "attributes": {**attrs, "unit_of_measurement": unit},
                }})
                assert "HI display range" not in fallback
        for feed in [None, dict(states["sensor.hi_diagnostics"], state="unavailable"),
                     {"state": "1", "attributes": {"schema": 2, "entry": ENTRY_BINDING, "readings": {}}}]:
            fallback = render(expr, {**states, "sensor.hi_diagnostics": feed})
            assert "VOC index (exported source)" in fallback and "Unavailable" in fallback
            assert '>0</span>' not in fallback
        missing = render(expr, {**states, "sensor.example_diagnostics": None})
        assert "AQ configuration" in missing and "100 ppb" not in missing


def test_unconfigured_feed_has_no_subscription_or_rows():
    for card in exports([]):
        assert "sensor.hi_voc_index_sources" not in card["triggers_update"]
        assert "sensor.hi_voc_index_sources" not in card["custom_fields"]["aq"]
        assert not render(card["custom_fields"]["aq"], {
            "sensor.example_diagnostics": {"state": "ok", "attributes": {"config": {"telemetry": []}}},
        }).strip()


def test_saved_aq_strip_accepts_live_rows_only_from_its_stamped_entry():
    foreign_entry = hashlib.sha256(b"another entry").hexdigest()
    reading = {KEY: {"label": "Live source", "status": "available", "value": 23}}
    for card in exports([ROW]):
        expr = card["custom_fields"]["aq"]
        for attrs in (
            {"schema": 1, "readings": reading},
            {"schema": 2, "readings": reading},
            {"schema": 2, "entry": foreign_entry, "readings": reading},
        ):
            html = render(expr, {"sensor.hi_diagnostics": {"state": "1", "attributes": attrs}})
            assert "Live source" not in html
            assert "VOC index (exported source)" in html and "Unavailable" in html
        owned = {"schema": 2, "entry": ENTRY_BINDING, "readings": reading}
        html = render(expr, {"sensor.hi_diagnostics": {"state": "1", "attributes": owned}})
        assert "Live source VOC index" in html and ">23</span>" in html
        assert "VOC index (exported source)" not in html
