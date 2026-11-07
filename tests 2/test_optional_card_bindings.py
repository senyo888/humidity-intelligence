"""Optional generated sources must not bind unrelated legacy-named entities."""
import json
import re
import subprocess

import pytest
import yaml

from test_runtime_card_sanity import _FakeHass, _FakeState, _load_target_modules, _load_services_module
from test_single_level_ui import generate, created_registry, LAYOUTS


def available_states(entry, mapping):
    # The configured adaptive feed is a real registry member in generate(),
    # injected by its renderer rather than the legacy placeholder mapping.
    entities = set(mapping.values()) | set(created_registry(entry).values())
    entities.add("sensor.example_output_status")
    return {entity: _FakeState("0") for entity in entities}


def execute(codes, states):
    result = subprocess.run(
        ["node", "-e", """
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = input.codes.map(code => new Function('states', 'variables', 'hass', 'entity', code)(input.states, {}, {states:input.states}, undefined));
console.log(JSON.stringify(result));
"""], input=json.dumps({"codes": codes, "states": states}), text=True,
        capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("alert_only", [False, True])
@pytest.mark.parametrize("show_outputs", [False, True])
@pytest.mark.parametrize("presentation", ["native", "adaptive"])
def test_unmapped_optional_sources_cannot_bind_legacy_entities(monkeypatch, alert_only, show_outputs, presentation):
    entry, mapping, cards, runtime = generate(
        monkeypatch, alert_only=alert_only, show_outputs=show_outputs,
        presentation=presentation,
    )
    _, register = _load_target_modules()
    services = _load_services_module()
    optional = {item for item in runtime["unresolved_placeholders"] if register._is_optional_placeholder(item)}
    states = {entity: {"state": "0", "attributes": {}} for entity in mapping.values()}
    states[mapping["sensor.hi_diagnostics"]] = {"state": "ok", "attributes": {"config": entry.data}}
    collisions = {**states, **{entity: {"state": "on" if entity.startswith("input_boolean.") else "99", "attributes": {}} for entity in optional}}
    for layout in LAYOUTS:
        yaml.safe_load(cards[layout])
        refs = services._extract_generated_card_entity_ids(cards[layout])
        assert not optional.intersection(refs)
        codes = re.findall(r"\[\[\[(.*?)\]\]\]", cards[layout], re.S)
        affected = [code for code in codes if "states[null]" in code or "num(null)" in code]
        assert affected
        assert execute(affected, states) == execute(affected, collisions)
    available = _FakeHass(entry, available_states(entry, mapping))
    assert services._generated_card_entity_availability(available, cards)["status"] == "pass"
    assert runtime["unresolved_placeholders_by_card"] == {}


@pytest.mark.parametrize("state, expected", [("0", "pass"), ("unknown", "warn"), ("unavailable", "warn"), (None, "fail")])
def test_configured_optional_source_retains_missing_and_unavailable_truth(monkeypatch, state, expected):
    entry, mapping, cards, _ = generate(monkeypatch, metric="pm25", show_outputs=True)
    services = _load_services_module()
    entity = mapping["sensor.air_control_downstairs_pm25_average"]
    states = available_states(entry, mapping)
    if state is None:
        states.pop(entity)
    else:
        states[entity] = _FakeState(state)
    result = services._generated_card_entity_availability(_FakeHass(entry, states), cards)
    assert result["status"] == expected
    for layout in LAYOUTS:
        assert entity in services._extract_generated_card_entity_ids(cards[layout])


def test_configured_legacy_shaped_output_is_not_pruned_or_neutralized(monkeypatch):
    entry, mapping, cards, runtime = generate(monkeypatch, show_outputs=True, options={
        "zones": {"zone1": {"level": "level1", "outputs": ["fan.upstairs_air"]}},
    })
    services = _load_services_module()
    assert mapping["fan.kitchen_air"] == "fan.upstairs_air"
    assert "fan.upstairs_air" in runtime["unresolved_placeholders"]
    for layout in LAYOUTS:
        assert "entity: fan.upstairs_air" in cards[layout]
        assert "const outputIds = [\"fan.upstairs_air\"]" in cards[layout]
        assert "fan.upstairs_air" in services._extract_generated_card_entity_ids(cards[layout])
    states = available_states(entry, mapping)
    assert services._generated_card_entity_availability(_FakeHass(entry, states), cards)["status"] == "pass"


def test_optional_history_and_required_sources_keep_distinct_meaning():
    _, register = _load_target_modules()
    source = '''type: markdown
content: sensor.air_control_house_iaq_average
variables:
  hi_summary: >-
    [[[ return {"history": "sensor.air_control_house_iaq_average", "historyEntities": [{"id": "sensor.air_control_house_iaq_average"}], "required": "sensor.house_humidity_drift_7d"}; ]]]
'''
    result = register._neutralize_unresolved_optional_js(source, ["sensor.air_control_house_iaq_average", "sensor.house_humidity_drift_7d"])
    code = re.search(r"\[\[\[(.*?)\]\]\]", result, re.S).group(1)
    value = execute([code], {})[0]
    assert value == {"history": None, "historyEntities": [{"id": None}], "required": "sensor.house_humidity_drift_7d"}
    assert "content: sensor.air_control_house_iaq_average" in result


def test_canonical_literal_matching_handles_surrounding_quotes_and_boundaries():
    _, register = _load_target_modules()
    entity = "input_boolean.air_aq_downstairs_active"
    source = """outside: 'input_boolean.air_aq_downstairs_active'
[[[
// don't let HTML's quotes consume a source literal
const html = `<span class="label">Today's reading</span>`;
const a = states['input_boolean.air_aq_downstairs_active'];
const b = states["input_boolean.air_aq_downstairs_active"];
const longer = 'input_boolean.air_aq_downstairs_active_extra';
return [html, a, b, longer];
]]]
"""
    rendered = register._neutralize_unresolved_optional_js(source, [entity])
    assert rendered.startswith("outside: '" + entity + "'")
    assert "const a = states[null]" in rendered
    assert "const b = states[null]" in rendered
    assert "'" + entity + "_extra'" in rendered
    code = re.search(r"\[\[\[(.*?)\]\]\]", rendered, re.S).group(1)
    assert execute([code], {}) == execute([code], {entity: {"state": "on"}})
