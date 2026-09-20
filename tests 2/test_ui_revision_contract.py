"""Exercise revision identity through real card generation and Diagnostics."""

import asyncio
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
import yaml

from test_runtime_card_sanity import (
    ENTRY_ID, PKG, _FakeHass, _FakeRegistry, _load_sensor_platform_module, _load_target_modules,
)


STAMP = "__HI_UI_REVISION_STAMP__"
TEMPLATE = "type: custom:button-card\nvariables:\n  revision: |\n    [[[ return " + STAMP + "; ]]]\n"


def generation(monkeypatch, *, unavailable=(), unresolved=False, entry_id=ENTRY_ID):
    _, register = _load_target_modules()
    entry = SimpleNamespace(entry_id=entry_id, data={}, options={})
    hass = _FakeHass(entry, {})
    runtime = hass.data[register.DOMAIN][entry_id]
    runtime["ui_revision"] = {"schema": 1, "entry": "stale", "layouts": {"old": {}}}
    if unresolved:
        runtime["unresolved_placeholders"] = ["sensor.house_humidity_drift_7d"]

    def read(path, *_args):
        if path.stem in unavailable:
            raise OSError("Template unavailable")
        source = TEMPLATE if path.stem.startswith("v2_") else "type: markdown\ncontent: Legacy\n"
        if unresolved:
            source += "entity: sensor.house_humidity_drift_7d\n"
        return source

    monkeypatch.setattr(Path, "read_text", read)
    cards = asyncio.run(register.async_register_cards(hass, entry_id, {}))
    return register, hass, cards, runtime


def test_rendered_stamp_matches_backend_target_and_is_entry_scoped(monkeypatch):
    _, _, cards, runtime = generation(monkeypatch)
    metadata = runtime["ui_revision"]
    assert metadata["schema"] == 1
    assert set(metadata["layouts"]) == {"v2_mobile", "v2_tablet"}
    assert len(metadata["entry"]) == 64
    assert ENTRY_ID not in metadata["entry"]
    for layout in metadata["layouts"]:
        raw = cards[layout].split("[[[ return ", 1)[1].split("; ]]]", 1)[0]
        stamp = json.loads(raw)
        assert stamp == {
            "schema": 1, "entry": metadata["entry"], "layout": layout,
            "revision": 4, "generator": 1,
        }
        assert metadata["layouts"][layout] == {
            "revision": 4, "generator": 1, "supersedes": [1, 2, 3],
        }
        assert STAMP not in cards[layout]
    module = sys.modules[f"{PKG}.ui.revision"]
    assert module.revision_metadata(ENTRY_ID)["entry"] == metadata["entry"]
    assert module.revision_metadata("another_entry")["entry"] != metadata["entry"]
    assert "v1_mobile" not in metadata["layouts"]


def test_failed_layout_does_not_retain_old_target(monkeypatch):
    _, _, cards, runtime = generation(monkeypatch, unavailable=("v2_tablet",))
    assert "v2_tablet" not in cards
    assert set(runtime["ui_revision"]["layouts"]) == {"v2_mobile"}


def test_unresolved_required_entities_do_not_advertise_success(monkeypatch):
    _, _, cards, runtime = generation(monkeypatch, unresolved=True)
    assert runtime["ui_revision"]["layouts"] == {}
    assert cards["v2_mobile"].startswith("# HI WARNING")
    assert STAMP not in cards["v2_mobile"]


def test_failed_rebuild_clears_previously_successful_metadata(monkeypatch):
    register, hass, _, runtime = generation(monkeypatch)
    assert runtime["ui_revision"]["layouts"]

    def fail(*_args):
        raise ValueError("Generation failed")

    monkeypatch.setattr(register, "_apply_level_labels", fail)
    with pytest.raises(ValueError, match="Generation failed"):
        asyncio.run(register.async_register_cards(hass, ENTRY_ID, {}))
    assert runtime["ui_revision"]["layouts"] == {}


def test_unstamped_template_remains_unverified_and_revisions_are_not_configuration_hashes(monkeypatch):
    _, _, _, runtime = generation(monkeypatch)
    module = sys.modules[f"{PKG}.ui.revision"]
    metadata = runtime["ui_revision"]
    original = "type: markdown\ncontent: Old card\n"
    assert module.stamp_card(original, "v2_mobile", metadata) == (original, None)
    assert module.stamp_card(TEMPLATE, "custom_layout", metadata) == (TEMPLATE, None)
    first, target = module.stamp_card(TEMPLATE + "name: First\n", "v2_mobile", metadata)
    second, other_target = module.stamp_card(TEMPLATE + "name: Other\n", "v2_mobile", metadata)
    assert first != second
    assert target == other_target
    target["supersedes"].append(99)
    assert other_target["supersedes"] == [1, 2, 3]


def test_diagnostics_publishes_revision_without_changing_primary_state(monkeypatch):
    _, _, _, generated = generation(monkeypatch)
    payload = generated["ui_revision"]
    sensor_module = _load_sensor_platform_module()
    monkeypatch.setattr(sensor_module, "_build_diagnostics_summary", lambda *_args: {})
    runtime = {"ui_revision": payload}
    hass = SimpleNamespace(data={"humidity_intelligence": {ENTRY_ID: runtime}})
    sensor = sensor_module.HIDiagnosticsSensor(hass, ENTRY_ID)
    sensor.update()
    assert sensor._attr_native_value == "ok"
    assert sensor._attr_extra_state_attributes["ui_revision"] == payload
    assert "installed" not in sensor._attr_extra_state_attributes["ui_revision"]
    runtime.pop("ui_revision")
    sensor.update()
    assert sensor._attr_extra_state_attributes["ui_revision"] == {}
    assert sensor._attr_native_value == "ok"


def card_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from card_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from card_nodes(child)


@pytest.mark.parametrize("entry_id", ["entry_one", "entry_two"])
@pytest.mark.parametrize("show_outputs", [True, False])
def test_actual_templates_render_scoped_footer_with_optional_outputs(monkeypatch, entry_id, show_outputs):
    _, register = _load_target_modules()
    entry = SimpleNamespace(
        entry_id=entry_id,
        data={"zones": {
            "zone1": {"level": "level1", "outputs": ["fan.example_first", "fan.example_second"]},
            "zone2": {"level": "level2", "outputs": ["fan.example_third"]},
        }},
        options={"show_output_entity_details": show_outputs},
    )
    hass = _FakeHass(entry, {})
    monkeypatch.setattr(sys.modules["homeassistant.helpers.entity_registry"], "async_get", lambda _hass: _FakeRegistry())

    async def render():
        mapping = await register.async_build_entity_mapping(hass, entry_id)
        cards = await register.async_register_cards(hass, entry_id, mapping)
        return mapping, cards

    mapping, cards = asyncio.run(render())
    metadata = hass.data[register.DOMAIN][entry_id]["ui_revision"]
    assert set(metadata["layouts"]) == {"v2_mobile", "v2_tablet"}
    expected_binding = sys.modules[f"{PKG}.ui.revision"].revision_metadata(entry_id)["entry"]
    assert metadata["entry"] == expected_binding
    for layout in ("v2_mobile", "v2_tablet"):
        assert STAMP not in cards[layout]
        nodes = list(card_nodes(yaml.safe_load(cards[layout])))
        footer = [node for node in nodes if "hi_ui_stamp" in (node.get("variables") or {})]
        assert len(footer) == 1
        assert footer[0]["entity"] == mapping["sensor.hi_diagnostics"]
        encoded = re.search(r"JSON\.parse\('([^']+)'\)", footer[0]["variables"]["hi_ui_stamp"])
        assert encoded
        stamp = json.loads(encoded.group(1))
        target = metadata["layouts"][layout]
        assert stamp == {
            "schema": metadata["schema"], "entry": expected_binding, "layout": layout,
            "revision": target["revision"], "generator": target["generator"],
        }
        assert len([node for node in nodes if node.get("name") == "Outputs"]) == int(show_outputs)
        assert footer[0]["tap_action"] == {"action": "none"}
        assert footer[0]["hold_action"] == {"action": "none"}
