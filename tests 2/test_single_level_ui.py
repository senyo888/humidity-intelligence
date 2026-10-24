"""Issue #129: exercise real entity creation, mapping, YAML and chip JavaScript."""

import asyncio
import json
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from test_runtime_card_sanity import (
    ENTRY_ID, PKG, ROOT, _FakeHass, _load_core_module, _load_sensor_platform_module,
    _load_target_modules,
)
from test_ui_revision_contract import card_nodes


LAYOUTS = ("v2_mobile", "v2_tablet")


def telemetry(levels, metric="humidity"):
    return [
        {"entity_id": f"sensor.example_{level}_{metric}", "sensor_type": metric,
         "level": level, "room": f"Example {level}"}
        for level in levels
    ]


def created_registry(entry):
    """Resolve only entities actually built by core, plus the Diagnostics platform."""
    core = _load_core_module()
    hass = _FakeHass(entry, {})
    sensors, binary_sensors, _ = core.build_entities(hass, entry)
    platform = _load_sensor_platform_module()
    sensors.append(platform.HIDiagnosticsSensor(hass, entry.entry_id))
    result = {}
    for domain, entities in (("sensor", sensors), ("binary_sensor", binary_sensors)):
        for entity in entities:
            uid = entity._attr_unique_id
            suffix = uid.removeprefix(f"hi_{entry.entry_id}_")
            result[domain, uid] = f"{domain}.example_{suffix}"
    return result


def generate(monkeypatch, *, levels=("level1",), metric="humidity", options=None,
             registry=None, missing=(), show_outputs=False, presentation="native",
             alert_only=False):
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={
        "telemetry": telemetry(levels, metric), "alert_only_mode": alert_only,
        "slope": {"show_humidity_chips": True, "show_temperature_chips": True},
        "show_output_entity_details": show_outputs,
        "zones": {"zone1": {"level": "level1", "outputs": ["fan.example"]}},
        "output_observation": {"enabled": True, "presentation": presentation},
    }, options=options or {})
    registry = dict(created_registry(entry) if registry is None else registry)
    registry["sensor", f"hi_{ENTRY_ID}_output_status"] = "sensor.example_output_status"
    for suffix in missing:
        registry.pop(("sensor", f"hi_{ENTRY_ID}_{suffix}"), None)
    _, register = _load_target_modules()
    adaptive = ModuleType(f"{PKG}.adaptive_output")
    adaptive.__path__ = [str(ROOT / "custom_components/humidity_intelligence/adaptive_output")]
    sys.modules[adaptive.__name__] = adaptive
    fake_registry = SimpleNamespace(async_get_entity_id=lambda domain, _platform, uid: registry.get((domain, uid)))
    monkeypatch.setattr(sys.modules["homeassistant.helpers.entity_registry"], "async_get", lambda _hass: fake_registry)
    hass = _FakeHass(entry, {})

    async def render():
        mapping = await register.async_build_entity_mapping(hass, ENTRY_ID)
        cards = await register.async_register_cards(hass, ENTRY_ID, mapping)
        return mapping, cards

    mapping, cards = asyncio.run(render())
    return entry, mapping, cards, hass.data[register.DOMAIN][ENTRY_ID]


def rendered(card, mapping, runtime, entry, state="unavailable"):
    nodes = list(card_nodes(yaml.safe_load(card)))
    for node in nodes:
        if "cards" in node:
            assert isinstance(node["cards"], list) and node["cards"]
        if node.get("type") == "conditional":
            assert node.get("conditions") and node.get("card")
    fields = next(node["custom_fields"] for node in nodes if "humidity" in node.get("custom_fields", {}))
    expressions = {key: fields[key].split("[[[", 1)[1].rsplit("]]]", 1)[0] for key in ("humidity", "temperature")}
    footer = next(node for node in nodes if "hi_ui_stamp" in (node.get("variables") or {}))
    stamp = json.loads(re.search(r"JSON\.parse\('([^']+)'\)", footer["variables"]["hi_ui_stamp"]).group(1))
    states = {entity: {"state": state, "attributes": {}} for entity in mapping.values()}
    states[mapping["sensor.hi_diagnostics"]] = {"state": "ok", "attributes": {"config": {**entry.data, **entry.options}}}
    result = subprocess.run(["node", "-e", r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const model = new Function(fs.readFileSync(process.argv[1], 'utf8') + '\nreturn hiUiRevision;')();
const output = Object.fromEntries(Object.entries(input.expressions).map(([key, code]) => [key, new Function('states', code)(input.states)]));
output.revision = model.classify(input.stamp, input.metadata, true).kind;
output.oldRevision = model.classify({...input.stamp, revision:9}, input.metadata, true).kind;
const older = structuredClone(input.metadata);
for (const target of Object.values(older.layouts)) {target.revision=9; target.supersedes=[1,2,3,4,5,6,7,8];}
output.rollback = model.classify(input.stamp, older, true).kind;
console.log(JSON.stringify(output));
""", str(ROOT / "custom_components/humidity_intelligence/ui/revision_status.js")],
        input=json.dumps({"expressions": expressions, "states": states, "stamp": stamp,
                          "metadata": runtime["ui_revision"]}), text=True, capture_output=True, check=True)
    return json.loads(result.stdout), nodes


@pytest.mark.parametrize("levels", [(), ("level1",), ("level2",), ("level1", "level2")])
@pytest.mark.parametrize("show_outputs", [False, True])
@pytest.mark.parametrize("presentation", ["native", "adaptive"])
def test_real_created_entities_render_only_configured_levels(monkeypatch, levels, show_outputs, presentation):
    entry, mapping, cards, runtime = generate(monkeypatch, levels=levels, show_outputs=show_outputs, presentation=presentation)
    assert set(runtime["ui_revision"]["layouts"]) == set(LAYOUTS)
    assert runtime["unresolved_placeholders_by_card"] == {}
    for layout in LAYOUTS:
        assert not cards[layout].startswith("# HI WARNING")
        html, nodes = rendered(cards[layout], mapping, runtime, entry)
        assert html["revision"] == "current"
        assert html["oldRevision"] == "update"
        assert html["rollback"] == "different"
        for level, location, label in (("level1", "downstairs", "Level 1"), ("level2", "upstairs", "Level 2")):
            for metric, suffix in (("humidity", "AVG"), ("temperature", "Temp")):
                placeholder = f"sensor.air_control_{location}_average_{metric}"
                assert placeholder not in cards[layout]
                assert (f"{label} {suffix}" in html[metric]) == (level in levels)
                assert (f"sensor.example_{level}_avg_{metric}" in cards[layout]) == (level in levels)
        assert "House AVG" in html["humidity"]
        assert "House Temp" in html["temperature"]
        for metric, house, suffix in (("humidity", "House AVG", "AVG"), ("temperature", "House Temp", "Temp")):
            order = [house] + [f"Level {number} {suffix}" for number in (2, 1) if f"level{number}" in levels]
            assert [html[metric].index(label) for label in order] == sorted(html[metric].index(label) for label in order)
        assert len([n for n in nodes if n.get("type") == "custom:hi-adaptive-output-card"]) == int(show_outputs and presentation == "adaptive")


@pytest.mark.parametrize("metric", ["humidity", "temperature", "co"])
@pytest.mark.parametrize("state", ["unknown", "unavailable"])
def test_any_telemetry_type_keeps_both_unavailable_averages(monkeypatch, metric, state):
    entry, mapping, cards, runtime = generate(monkeypatch, metric=metric)
    for layout in LAYOUTS:
        html, _ = rendered(cards[layout], mapping, runtime, entry, state)
        assert "Level 1 AVG" in html["humidity"] and "—" in html["humidity"]
        assert "Level 1 Temp" in html["temperature"] and "—" in html["temperature"]
        assert html["revision"] == "current"


@pytest.mark.parametrize("missing", ["level1_avg_humidity", "level1_avg_temperature", "house_drift_7d", "diagnostics"])
def test_configured_required_mapping_failure_still_blocks_targets(monkeypatch, missing):
    _, _, cards, runtime = generate(monkeypatch, missing=(missing,))
    assert runtime["ui_revision"]["layouts"] == {}
    for layout in LAYOUTS:
        assert cards[layout].startswith("# HI WARNING")
        assert runtime["unresolved_placeholders_by_card"][layout]


def test_options_remove_and_readd_levels_despite_stale_registry(monkeypatch):
    entry = SimpleNamespace(entry_id=ENTRY_ID, data={"telemetry": telemetry(("level1", "level2"))}, options={})
    stale_registry = created_registry(entry)
    for levels in (("level1",), (), ("level2",), ("level1", "level2")):
        entry, mapping, cards, runtime = generate(monkeypatch, levels=("level1", "level2"),
            registry=stale_registry, options={"telemetry": telemetry(levels)})
        assert set(runtime["ui_revision"]["layouts"]) == set(LAYOUTS)
        for layout in LAYOUTS:
            html, _ = rendered(cards[layout], mapping, runtime, entry)
            for level, label in (("level1", "Level 1"), ("level2", "Level 2")):
                assert (f"{label} AVG" in html["humidity"]) == (level in levels)
                if level not in levels:
                    assert f"sensor.example_{level}_avg_" not in cards[layout]


@pytest.mark.parametrize("levels", [(), ("level1",)])
def test_alert_only_exports_keep_revision_and_valid_structure(monkeypatch, levels):
    entry, mapping, cards, runtime = generate(monkeypatch, levels=levels, alert_only=True)
    for layout in LAYOUTS:
        html, _ = rendered(cards[layout], mapping, runtime, entry)
        assert html["revision"] == "current"


def test_level_labels_are_json_encoded_and_html_escaped(monkeypatch):
    label = 'Example "<&> level'
    entry, mapping, cards, runtime = generate(monkeypatch, options={"level_labels": {"level1": label}})
    for layout in LAYOUTS:
        html, _ = rendered(cards[layout], mapping, runtime, entry)
        assert "Example &amp; level AVG" in html["humidity"]
        assert "Example &amp; level Temp" in html["temperature"]


@pytest.mark.parametrize("active, inactive", [("level1", "level2"), ("level2", "level1")])
@pytest.mark.parametrize("metric", ["humidity", "temperature"])
def test_inventory_marker_in_custom_label_cannot_leave_inactive_references(monkeypatch, active, inactive, metric):
    entry, mapping, cards, runtime = generate(monkeypatch, levels=(active,),
        options={"level_labels": {inactive: f"; // HI level {metric} inventory"}})
    assert set(runtime["ui_revision"]["layouts"]) == set(LAYOUTS)
    assert runtime["unresolved_placeholders_by_card"] == {}
    for layout in LAYOUTS:
        html, _ = rendered(cards[layout], mapping, runtime, entry)
        assert html["revision"] == "current"
        location = "upstairs" if inactive == "level2" else "downstairs"
        assert f"sensor.air_control_{location}_average_" not in cards[layout]
