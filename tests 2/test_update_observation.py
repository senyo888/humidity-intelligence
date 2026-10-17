"""Optional HACS update evidence stays separate from HI control and UI revision."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from test_runtime_card_sanity import (
    ENTRY_ID,
    PKG,
    _FakeHass,
    _FakeState,
    _base_entry_data,
    _load_sensor_platform_module,
    _load_services_module,
)


ENTITY_ID = "update.renamed_hi_package"
REPO_ID = "1127166185"


def _registry_entry(**overrides):
    fields = dict(
        domain="update", platform="hacs", unique_id=REPO_ID,
        disabled_by=None, entity_id=ENTITY_ID,
    )
    return SimpleNamespace(**(fields | overrides))


def _state(value="on", **overrides):
    attrs = dict(
        installed_version="2.1.1-beta.2", latest_version="2.1.1-beta.3",
        skipped_version=None, in_progress=False,
        release_summary="<script>do not export provider HTML</script>",
        release_url="https://example.invalid/private-provider-path",
    )
    return _FakeState(value, attrs | overrides)


def _hass(state=None):
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=_base_entry_data(), options={})
    return _FakeHass(entry, {ENTITY_ID: state} if state is not None else {})


def _bind_registry(monkeypatch, mod, entries=None):
    registry = SimpleNamespace(entities={
        str(index): entry
        for index, entry in enumerate([_registry_entry()] if entries is None else entries)
    })
    monkeypatch.setattr(mod.er, "async_get", lambda _hass: registry)
    return registry


@pytest.fixture
def adapter(monkeypatch):
    _load_services_module()
    mod = sys.modules[f"{PKG}.helpers.update_observation"]
    _bind_registry(monkeypatch, mod)
    return mod


@pytest.mark.parametrize(("state", "attrs", "status", "reason"), [
    ("on", {}, "reported_update", "provider_reported_update"),
    ("off", {"installed_version": "2.1.1-beta.3"}, "no_update_reported", "provider_no_update_reported"),
    # A manually installed beta may be ahead of HACS's selected stable channel.
    ("off", {"latest_version": "2.0.12"}, "no_update_reported", "provider_no_update_reported"),
    ("off", {"skipped_version": "2.1.1-beta.3"}, "skipped", "provider_release_skipped"),
    ("on", {"skipped_version": "2.1.1-beta.1"}, "reported_update", "provider_reported_update"),
    ("on", {"in_progress": True}, "in_progress", "provider_in_progress"),
    ("off", {"in_progress": True}, "in_progress", "provider_in_progress"),
    ("on", {"in_progress": 0}, "in_progress", "provider_in_progress"),
    ("on", {"in_progress": 50}, "in_progress", "provider_in_progress"),
    ("on", {"in_progress": 100}, "in_progress", "provider_in_progress"),
    ("unknown", {}, "unverified", "state_unavailable"),
    ("unavailable", {}, "unverified", "state_unavailable"),
    ("true", {}, "unverified", "state_invalid"),
    ("on", {"skipped_version": "2.1.1-beta.3"}, "unverified", "attributes_invalid"),
    ("on", {"installed_version": "2.1.1-beta.3"}, "unverified", "attributes_invalid"),
])
def test_provider_state_matrix(adapter, state, attrs, status, reason):
    result = adapter.update_observation(_hass(_state(state, **attrs)))
    assert result["status"] == status
    assert result["reason"] == reason
    assert result["schema"] == 1
    assert result["provider"] == "hacs"
    assert result["repository"] == "senyo888/humidity-intelligence"
    assert result["entity_id"] == ENTITY_ID
    assert result["provider_state"] == (state if state in {"on", "off"} else None)
    assert set(result) == {
        "schema", "provider", "repository", "status", "reason", "entity_id",
        "provider_state", "downloaded_version", "latest_version", "skipped_version",
    }
    assert "release_summary" not in json.dumps(result)
    assert "private-provider-path" not in json.dumps(result)


@pytest.mark.parametrize("attribute", ["installed_version", "latest_version", "skipped_version"])
@pytest.mark.parametrize("value", ["", " ", "v1\n", "v\x001", "unknown", "UNAVAILABLE", 3, {}, [], False, "x" * 129])
def test_invalid_versions_are_not_green_or_stringified(adapter, attribute, value):
    result = adapter.update_observation(_hass(_state(**{attribute: value})))
    assert result["status"] == "unverified"
    assert result["reason"] == "attributes_invalid"
    assert result["downloaded_version"] is None
    assert result["latest_version"] is None
    assert result["skipped_version"] is None


@pytest.mark.parametrize("attribute", ["installed_version", "latest_version", "in_progress"])
def test_missing_required_provider_attribute_is_unverified(adapter, attribute):
    state = _state()
    state.attributes.pop(attribute)
    assert adapter.update_observation(_hass(state))["status"] == "unverified"


@pytest.mark.parametrize("value", [None, -1, 101, 0.0, 50.5, "false", "true", {}, []])
def test_progress_requires_a_supported_strict_type_and_range(adapter, value):
    result = adapter.update_observation(_hass(_state(in_progress=value)))
    assert result["status"] == "unverified"
    assert result["reason"] == "attributes_invalid"


def test_versions_are_display_text_not_semver_order_or_loaded_identity(adapter):
    result = adapter.update_observation(_hass(_state(
        installed_version="manual-development-ref", latest_version="v2.0.12",
    )))
    assert result["status"] == "reported_update"
    assert result["downloaded_version"] == "manual-development-ref"
    assert "running_version" not in result
    assert "last_checked" not in result


def test_only_registered_state_is_read_without_hass_services_or_storage(adapter):
    reads = []

    class ReadOnlyStates:
        def get(self, entity_id):
            reads.append(entity_id)
            return _state()

    class ReadOnlyHass:
        states = ReadOnlyStates()

        def __getattr__(self, name):
            raise AssertionError(f"Optional observation must not access hass.{name}")

    assert adapter.update_observation(ReadOnlyHass())["status"] == "reported_update"
    assert reads == [ENTITY_ID]


@pytest.mark.parametrize(("entries", "reason"), [
    ([], "entity_missing"),
    ([_registry_entry(platform="other")], "entity_missing"),
    ([_registry_entry(unique_id="not-the-hi-repository")], "entity_missing"),
    ([_registry_entry(unique_id=1127166185)], "entity_missing"),
    ([_registry_entry(domain="sensor")], "entity_missing"),
    ([_registry_entry(disabled_by="user")], "entity_disabled"),
    ([_registry_entry(entity_id="sensor.hi_package")], "entity_invalid"),
    ([_registry_entry(entity_id="update.<unsafe>")], "entity_invalid"),
    ([_registry_entry(entity_id="update." + "x" * 256)], "entity_invalid"),
    ([_registry_entry(), _registry_entry(entity_id="update.other_hi_package")], "entity_ambiguous"),
    ([_registry_entry(), _registry_entry(disabled_by="integration")], "entity_ambiguous"),
])
def test_exact_registry_identity_or_unverified(adapter, monkeypatch, entries, reason):
    _bind_registry(monkeypatch, adapter, entries)
    result = adapter.update_observation(_hass(_state()))
    assert result["status"] == "unverified"
    assert result["reason"] == reason
    assert result["entity_id"] is None


def test_late_startup_rename_disappearance_and_repeated_reads_have_no_cache(adapter, monkeypatch):
    registry = _bind_registry(monkeypatch, adapter, [])
    hass = _hass(_state())
    hass.data = {"unchanged": {"items": [1, 2]}}
    before = copy.deepcopy(hass.data)
    assert adapter.update_observation(hass)["reason"] == "entity_missing"
    entry = _registry_entry()
    registry.entities["entry"] = entry
    first = adapter.update_observation(hass)
    assert first["status"] == "reported_update"
    assert adapter.update_observation(hass) == first
    renamed = "update.another_registered_hi_name"
    entry.entity_id = renamed
    hass.states._values[renamed] = hass.states._values.pop(ENTITY_ID)
    assert adapter.update_observation(hass)["entity_id"] == renamed
    hass.states._values.pop(renamed)
    assert adapter.update_observation(hass)["reason"] == "state_missing"
    registry.entities.clear()
    assert adapter.update_observation(hass)["entity_id"] is None
    assert hass.data == before
    assert hass.services.calls == []


def test_optional_registry_and_state_exceptions_are_contained(adapter, monkeypatch):
    def broken(*_args):
        raise RuntimeError("provider failure must not be exported")

    hass = _hass(_state())
    monkeypatch.setattr(adapter.er, "async_get", broken)
    assert adapter.update_observation(hass)["reason"] == "registry_unavailable"
    _bind_registry(monkeypatch, adapter)
    monkeypatch.setattr(hass.states, "get", broken)
    result = adapter.update_observation(hass)
    assert result["reason"] == "state_read_failed"
    assert "provider failure" not in json.dumps(result)


def test_malformed_provider_attributes_and_raising_properties_are_contained(adapter):
    class BrokenState:
        state = "on"

        @property
        def attributes(self):
            raise RuntimeError("provider attribute failure")

    assert adapter.update_observation(_hass(BrokenState()))["reason"] == "state_read_failed"
    state = _state()
    state.attributes = []
    assert adapter.update_observation(_hass(state))["reason"] == "attributes_invalid"


def test_real_diagnostics_builder_preserves_control_and_stability_across_provider_changes(monkeypatch):
    services = _load_services_module()
    helper = sys.modules[f"{PKG}.helpers.update_observation"]
    _bind_registry(monkeypatch, helper)
    hass = _hass(_state())
    runtime = {
        "runtime_mode": "co_emergency", "runtime_mode_display": "CO EMERGENCY",
        "runtime_reason": "CO emergency is active.",
        "stability_published": {"schema": 3, "score": {"display_score": 0}},
        "stability_failed_buckets": {"retained-bucket"},
        "stability_movement_last_score": 0,
    }
    original = copy.deepcopy(runtime)
    summaries = []
    for state in (_state(), _state("off"), _state("unavailable"), None):
        hass.states._values[ENTITY_ID] = state
        summaries.append(services._build_diagnostics_summary(hass, {}, {}, {}, runtime))
    assert [summary["update_observation"]["status"] for summary in summaries] == [
        "reported_update", "no_update_reported", "unverified", "unverified",
    ]
    invariant = [{key: value for key, value in summary.items() if key != "update_observation"} for summary in summaries]
    assert all(summary == invariant[0] for summary in invariant)
    assert runtime == original
    assert hass.services.calls == []


def test_existing_diagnostics_publication_refreshes_update_without_changing_health(monkeypatch):
    sensor_mod = _load_sensor_platform_module()
    helper = sys.modules[f"{PKG}.helpers.update_observation"]
    registry = _bind_registry(monkeypatch, helper, [])
    hass = _hass(_state())
    runtime = hass.data["humidity_intelligence"][ENTRY_ID]
    runtime.clear()
    runtime["stability_published"] = {"schema": 3, "score": {"display_score": 82}}
    original = copy.deepcopy(runtime)
    sensor = sensor_mod.HIDiagnosticsSensor(hass, ENTRY_ID)
    sensor.update(publish=False)
    assert sensor._attr_extra_state_attributes["update_observation"]["status"] == "unverified"
    registry.entities["entry"] = _registry_entry()
    sensor.update(publish=False)
    attrs = sensor._attr_extra_state_attributes
    assert attrs["update_observation"]["status"] == "reported_update"
    assert attrs["diagnostics_summary"]["update_observation"] == attrs["update_observation"]
    assert sensor._attr_native_value == "ok"
    assert runtime == original
    assert hass.services.calls == []


def test_native_and_support_exports_keep_evidence_but_omit_resolved_entity(monkeypatch):
    from test_diagnostics import _load_diagnostics_module

    services = _load_services_module()
    helper = sys.modules[f"{PKG}.helpers.update_observation"]
    _bind_registry(monkeypatch, helper)
    hass = _hass(_state())
    live = services._build_diagnostics_summary(hass, {}, {}, {}, {})
    support = services._support_safe_diagnostics_summary(live)
    native_mod = _load_diagnostics_module()
    native_helper = sys.modules["hi_diag_testpkg.helpers.update_observation"]
    _bind_registry(monkeypatch, native_helper)
    native = native_mod._diagnostics_summary(
        hass, {}, {}, {}, frontend_dependencies={},
    )
    assert live["update_observation"]["entity_id"] == ENTITY_ID
    expected = {**live["update_observation"], "entity_id": None}
    assert support["update_observation"] == native["update_observation"] == expected
    for exported in (support, native):
        text = json.dumps(native_mod.redact_diagnostics_payload(exported))
        assert ENTITY_ID not in text
        assert "private-provider-path" not in text
        assert "do not export provider HTML" not in text


def test_real_sensor_async_refresh_contains_provider_fault_but_not_core_fault(monkeypatch):
    sensor_mod = _load_sensor_platform_module()
    helper = sys.modules[f"{PKG}.helpers.update_observation"]

    def broken_provider(*_args):
        raise RuntimeError("optional provider failure")

    monkeypatch.setattr(helper.er, "async_get", broken_provider)
    hass = _hass()
    sensor = sensor_mod.HIDiagnosticsSensor(hass, ENTRY_ID)
    asyncio.run(sensor.async_update())
    assert sensor._attr_native_value == "ok"
    assert sensor._attr_extra_state_attributes["update_observation"]["reason"] == "registry_unavailable"

    def core_fault(*_args):
        raise RuntimeError("core builder failure")

    monkeypatch.setattr(sensor_mod, "_build_diagnostics_summary", core_fault)
    with pytest.raises(RuntimeError, match="core builder failure"):
        asyncio.run(sensor.async_update())
