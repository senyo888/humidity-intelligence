"""Focused v2.0.12 Home Assistant-local time-gate tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from test_runtime_card_sanity import (
    ENTRY_ID,
    _FakeHass,
    _base_entry_data,
    _load_target_modules,
)


def _time_gate_engine(start: str, end: str):
    engine_mod, _ = _load_target_modules()
    entry_data = _base_entry_data()
    entry_data["time_gate"] = {
        "enabled": True,
        "start": start,
        "end": end,
        "outside_action": "pause",
    }
    entry = SimpleNamespace(entry_id=ENTRY_ID, data=entry_data, options={})
    hass = _FakeHass(entry, {})
    return engine_mod, engine_mod.HIAutomationEngine(hass, entry)


def test_time_gate_uses_home_assistant_local_time_for_same_day_and_overnight_windows():
    engine_mod, engine = _time_gate_engine("09:00", "17:00")
    auckland = ZoneInfo("Pacific/Auckland")

    engine_mod.dt_util.now = lambda: datetime(2026, 1, 15, 9, 0, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is True
    engine_mod.dt_util.now = lambda: datetime(2026, 1, 15, 17, 0, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is True
    engine_mod.dt_util.now = lambda: datetime(2026, 1, 15, 8, 59, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is False

    engine.time_gate.update({"start": "22:00", "end": "06:00"})
    engine_mod.dt_util.now = lambda: datetime(2026, 1, 15, 23, 30, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is True
    engine_mod.dt_util.now = lambda: datetime(2026, 1, 16, 5, 30, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is True
    engine_mod.dt_util.now = lambda: datetime(2026, 1, 16, 12, 0, tzinfo=auckland)
    assert engine._gate_evaluation().allowed is False


def test_time_gate_handles_real_spring_transition_and_both_autumn_fold_instants():
    engine_mod, engine = _time_gate_engine("01:00", "03:00")
    london = ZoneInfo("Europe/London")

    before_gap = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc).astimezone(london)
    after_gap = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc).astimezone(london)
    engine_mod.dt_util.now = lambda: before_gap
    assert engine._gate_evaluation().allowed is False
    engine_mod.dt_util.now = lambda: after_gap
    assert after_gap.strftime("%H:%M") == "02:30"
    assert engine._gate_evaluation().allowed is True

    engine.time_gate.update({"start": "01:00", "end": "02:00"})
    first_fold = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).astimezone(london)
    second_fold = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).astimezone(london)
    assert first_fold.strftime("%H:%M") == second_fold.strftime("%H:%M") == "01:30"
    assert first_fold.fold == 0
    assert second_fold.fold == 1
    engine_mod.dt_util.now = lambda: first_fold
    assert engine._gate_evaluation().allowed is True
    engine_mod.dt_util.now = lambda: second_fold
    assert engine._gate_evaluation().allowed is True
