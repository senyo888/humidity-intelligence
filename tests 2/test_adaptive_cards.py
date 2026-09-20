"""Normal export path tests for optional adaptive Outputs and native rollback."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adaptive_card_fixtures", Path(__file__).with_name("test_runtime_card_sanity.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def load():
    _, register = fixtures._load_target_modules()
    package = ModuleType(f"{fixtures.PKG}.adaptive_output")
    package.__path__ = [str(fixtures.INTEGRATION_ROOT / "adaptive_output")]
    sys.modules[package.__name__] = package
    cards = fixtures._load_module(f"{package.__name__}.cards", Path(package.__path__[0]) / "cards.py")
    return register, cards


def entry(**changes):
    outputs = [f"fan.example_{i}" for i in range(12)]
    data = {
        "zones": {"zone1": {"level": "level1", "outputs": outputs}, "zone2": {"level": "level2", "outputs": [outputs[0]]}},
        "humidifiers": {"level1": {"outputs": ["humidifier.example"]}},
        "aq": {"level2": {"enabled": False, "outputs": [outputs[-1]]}},
        "alerts": [{"lights": ["light.example"], "power_entity": "switch.example_power"}],
        "output_observation": {"enabled": True, "presentation": "adaptive"},
    }
    data.update(changes)
    return SimpleNamespace(entry_id=fixtures.ENTRY_ID, data=data, options={})


async def generate(register, config, *, feed=True):
    registry = fixtures._FakeRegistry() if feed else fixtures._FakeRegistryMissingUniqueIds({f"hi_{fixtures.ENTRY_ID}_output_status"})
    if isinstance(feed, str):
        original_lookup = registry.async_get_entity_id
        registry.async_get_entity_id = lambda domain, integration, uid: feed if uid == f"hi_{fixtures.ENTRY_ID}_output_status" else original_lookup(domain, integration, uid)
    sys.modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: registry
    hass = fixtures._FakeHass(config, {})
    mapping = await register.async_build_entity_mapping(hass, config.entry_id)
    return await register.async_register_cards(hass, config.entry_id, mapping)


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def test_real_mapping_refresh_inventory_and_surrounding_bytes():
    register, cards_mod = load()
    config = entry()
    adaptive = asyncio.run(generate(register, config))
    config.options = {"output_observation": {"enabled": True, "presentation": "native"}}
    native = asyncio.run(generate(register, config))
    assert set(adaptive) == {"v2_mobile", "v2_tablet", "v1_mobile", "view_cards_button"}
    for kind in ("v2_mobile", "v2_tablet"):
        expected, _ = cards_mod.wire_card(native[kind], "sensor.hi_output_status")
        assert adaptive[kind] == expected
        custom = [n for n in nodes(yaml.safe_load(adaptive[kind])) if n.get("type") == "custom:hi-adaptive-output-card"]
        assert len(custom) == 1
        assert custom[0]["entity"] == "sensor.hi_output_status"
        rows = custom[0]["control_context"]["entities"]
        ids = [r.get("entity") for r in rows if isinstance(r, dict)]
        for eid in [*(f"fan.example_{i}" for i in range(12)), "humidifier.example", "light.example", "switch.example_power"]:
            assert ids.count(eid) == 1
        assert "switch.hi_input_air_isolate_fan_outputs" in ids
        assert "custom:hi-adaptive-output-card" not in native[kind]
        assert "switch.hi_input_air_control_output_expanded" in native[kind]
    assert adaptive["v1_mobile"] == native["v1_mobile"]
    assert adaptive["view_cards_button"] == native["view_cards_button"]
    config.options = {"output_observation": {"enabled": True, "presentation": "adaptive"}}
    assert asyncio.run(generate(register, config)) == adaptive


def test_absent_feed_falls_back_to_independent_native_card():
    register, _ = load()
    config = entry()
    missing = asyncio.run(generate(register, config, feed=False))
    config.options = {"output_observation": {"enabled": True, "presentation": "native"}}
    native = asyncio.run(generate(register, config))
    assert missing == native
    assert "hi-adaptive-output-card" not in missing["v2_mobile"]
    assert "fan.example_11" in missing["v2_mobile"]


def test_hidden_alert_only_and_default_exports_do_not_add_adaptive_dependency():
    register, _ = load()
    for config in (entry(show_output_entity_details=False), entry(alert_only_mode=True), entry(output_observation={}), entry(output_observation={"enabled": False, "presentation": "adaptive"})):
        rendered = asyncio.run(generate(register, config))
        assert all("custom:hi-adaptive-output-card" not in c for c in rendered.values())
        for kind in ("v2_mobile", "v2_tablet"):
            assert yaml.safe_load(rendered[kind])


def test_static_resource_registration_is_retryable_and_once():
    load()
    path = fixtures.INTEGRATION_ROOT / "adaptive_output" / "frontend.py"
    frontend = fixtures._load_module("adaptive_frontend_test", path)
    module = ModuleType("homeassistant.components.http")
    module.StaticPathConfig = lambda url, path, cache: (url, path, cache)
    sys.modules[module.__name__] = module
    calls = []
    fail = True
    async def register(paths):
        nonlocal fail
        calls.append(paths)
        if fail:
            fail = False
            raise RuntimeError("HTTP unavailable")
    hass = SimpleNamespace(data={}, http=SimpleNamespace(async_register_static_paths=register))
    async def run():
        try:
            await frontend.async_register_frontend(hass)
        except RuntimeError:
            pass
        await asyncio.gather(frontend.async_register_frontend(hass), frontend.async_register_frontend(hass))
    asyncio.run(run())
    assert len(calls) == 2
    url, file_path, cache = calls[-1][0]
    assert url == frontend.RESOURCE_URL
    assert Path(file_path).is_file()
    assert cache is False


def test_optional_generation_failure_preserves_native_export():
    register, cards_mod = load()
    config = entry(output_observation={"enabled": False})
    baseline = asyncio.run(generate(register, config))
    config.options = {"output_observation": {"enabled": True, "presentation": "adaptive"}}
    original = cards_mod.render_output_card
    def fail(*args):
        raise RuntimeError("optional presentation failure")
    cards_mod.render_output_card = fail
    try:
        assert asyncio.run(generate(register, config)) == baseline
    finally:
        cards_mod.render_output_card = original


def test_registered_sensor_rename_and_bytes_outside_outputs():
    register, cards_mod = load()
    config = entry()
    adaptive = asyncio.run(generate(register, config, feed="sensor.example_registered_observation"))
    config.options = {"output_observation": {"enabled": False}}
    baseline = asyncio.run(generate(register, config))
    def outside_outputs(text):
        for sequence in cards_mod._sequences(yaml.compose(text)):
            for index, header in enumerate(sequence.value):
                if cards_mod._value(header, "name") == "Outputs":
                    detail = sequence.value[index + 1]
                    start = text.rfind("\n", 0, header.start_mark.index) + 1
                    end = detail.end_mark.index
                    return text[:start], text[end:]
        raise AssertionError("Outputs missing")
    config.options = {"output_observation": {"enabled": True, "presentation": "native"}}
    native = asyncio.run(generate(register, config))
    for kind in ("v2_mobile", "v2_tablet"):
        assert outside_outputs(baseline[kind]) == outside_outputs(native[kind])
        expected, _ = cards_mod.wire_card(native[kind], "sensor.example_registered_observation")
        assert adaptive[kind] == expected


def test_observation_options_regenerate_only_for_presentation_changes():
    integration = fixtures._load_integration_init_module()
    for previous, following, exported in [
        ({}, {'enabled': True, 'presentation': 'native'}, True),
        ({'enabled': True}, {'enabled': True, 'presentation': 'adaptive'}, True),
        ({'enabled': True}, {'enabled': False}, True),
        ({'enabled': True}, {'enabled': True, 'confirmations': []}, False),
    ]:
        events = []
        async def reload_entry(entry_id):
            events.append('reload')
        async def export_cards(hass, entry_id):
            events.append('export')
            return ['humidity_intelligence/ui/example.yaml']
        async def notify(*args, **kwargs):
            events.append('notify')
        integration._async_refresh_and_dump_cards = export_cards
        config = SimpleNamespace(entry_id=fixtures.ENTRY_ID, data={}, options={'output_observation': following})
        hass = SimpleNamespace(
            data={integration.DOMAIN: {config.entry_id: {'config': {'output_observation': previous}}}},
            config_entries=SimpleNamespace(async_reload=reload_entry),
            services=SimpleNamespace(async_call=notify),
        )
        asyncio.run(integration._async_options_updated(hass, config))
        assert events == (['reload', 'export', 'notify'] if exported else ['reload'])


def test_ha_readonly_config_mappings_generate_adaptive_outputs():
    from types import MappingProxyType
    register, _ = load()
    config = entry()
    config.data = MappingProxyType(config.data)
    config.options = MappingProxyType(config.options)
    result = asyncio.run(generate(register, config))
    assert "custom:hi-adaptive-output-card" in result["v2_mobile"]
    assert "custom:hi-adaptive-output-card" in result["v2_tablet"]


def test_revision_footer_survives_native_and_adaptive_output_generation():
    _, cards_mod = load()
    inventory = [{"entity_id": "fan.example_added"}]
    for layout in ("v2_mobile", "v2_tablet"):
        source = (fixtures.INTEGRATION_ROOT / "ui" / "cards" / f"{layout}.yaml").read_text()
        marker = "    # hi:output-details:end"
        suffix = source[source.index(marker):]
        assert "# UI revision is display-only" in suffix
        for feed in (None, "sensor.hi_output_status"):
            rendered = cards_mod.render_output_card(source, inventory, feed)
            assert rendered.endswith(suffix)
            parsed = yaml.safe_load(rendered)
            assert "fan.example_added" in rendered
            assert sum(n.get("type") == "custom:hi-adaptive-output-card" for n in nodes(parsed)) == bool(feed)
            footer = [n for n in nodes(parsed) if "hi_ui_stamp" in n.get("variables", {})]
            assert len(footer) == 1
