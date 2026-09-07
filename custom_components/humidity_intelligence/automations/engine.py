"""Automation engine for Humidity Intelligence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import (
    ALERT_THRESHOLD_BOUNDS,
    ALERT_TRIGGER_DEFS,
    ROOM_SCOPED_ALERT_TRIGGERS,
    DOMAIN,
    ENGINE_INTERVAL_MAX,
    ENGINE_INTERVAL_MIN,
    ENGINE_INTERVAL_MINUTES_DEFAULT,
    FAN_OUTPUT_LEVEL_AUTO,
    FAN_OUTPUT_LEVEL_STEPS,
    CONF_ALERT_HANDLING_ENABLED,
    DEFAULT_ALERT_HANDLING_ENABLED,
    HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT,
    HUMIDIFIER_RECONCILE_CONFIRM_SECONDS,
    HUMIDIFIER_RECONCILE_HISTORY_LIMIT,
    HUMIDIFIER_RECONCILE_MAX_ATTEMPTS,
    HUMIDIFIER_RECONCILE_RETRY_DELAYS_SECONDS,
    STARTUP_SENSOR_RECHECK_SECONDS,
    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
    ZONE_OUTPUT_LEVEL_DEFAULT,
    ZONE_OUTPUT_LEVEL_MAX,
    ZONE_OUTPUT_LEVEL_MIN,
)
from ..services import async_flash_lights_for_alert
from ..helpers.level_labels import resolve_level_labels
from ..helpers.parsing import hass_temperature_unit, parse_numeric, parse_temperature
from ..helpers.reason_presentation import (
    DISPLAY_REASON_MAX_BYTES,
    DISPLAY_REASON_MAX_LINE_TEXT,
    DISPLAY_REASON_MAX_LINES,
    DISPLAY_REASON_TARGET_LINES,
    ReasonFacts,
    ReasonLine,
    ReasonPresentationError,
    build_display_reason,
    sanitize_display_label,
)
from ..helpers.seasonal import (
    condensation_risk as seasonal_condensation_risk,
    humidity_state as seasonal_humidity_state,
    mould_level as seasonal_mould_level,
    resolve_target_profile,
)

CO_EMERGENCY_START = 15
CO_EMERGENCY_CLEAR = 10
CO_EMERGENCY_CLEAR_HOLD = timedelta(minutes=2)
_RISK_ORDER = {"OK": 0, "Watch": 1, "Risk": 2, "Danger": 3, "Unknown": -1}
_RISK_DISPLAY_BY_LEVEL = {
    rank: "Normal" if label == "OK" else label
    for label, rank in _RISK_ORDER.items()
    if label != "Unknown"
}
_ALERT_PRIORITY = {
    "humidity_danger": 10,
    "mould_danger": 20,
    "mould_risk": 30,
    "condensation_danger": 40,
    "condensation_risk": 50,
    "co_emergency": 0,
}
_BUILT_IN_ZONE_ALERT_TRIGGERS = (
    "humidity_danger",
    "mould_danger",
    "mould_risk",
    "condensation_danger",
    "condensation_risk",
)
HUMIDITY_ALERT_FLASH_COUNT = 10
HUMIDITY_ALERT_REPEAT_MINUTES = 30
_EVALUATION_SWITCH_SOURCE_KEYS = {
    "air_control_enabled",
    "air_control_manual_override",
    "air_isolate_fan_outputs",
    "air_isolate_humidifier_outputs",
}
_EVALUATION_TIMER_SOURCE_KEYS = {
    "air_control_pause",
}

_LOGGER = logging.getLogger(__name__)

_MAX_STATE_LENGTH = 255
_TRUNCATION_SUFFIX = " [full in attribute]"
_HUMIDIFIER_OUTPUT_DOMAINS = {"humidifier", "fan", "switch"}
_DISPLAY_OUTPUT_SUMMARY_MAX_BYTES = 192


@dataclass(frozen=True)
class _GateStatus:
    allowed: bool
    kind: Optional[str] = None
    technical_reason: Optional[str] = None
    presentation_variant: Optional[str] = None
    configured_count: int = 0
    unavailable_count: int = 0
    away_count: int = 0
    other_count: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None


@dataclass(frozen=True)
class _TriggerFact:
    code: str
    measured: float
    threshold: float
    unit: str
    comparison: str
    profile_label: Optional[str] = None


@dataclass(frozen=True)
class _AlertMatch:
    room: str
    sensor: Optional[str]
    measured: float
    threshold: float
    unit: str
    comparison: str
    profile_label: str


class HIAutomationEngine:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.telemetry = self._cfg("telemetry", [])
        self.time_gate = self._cfg("time_gate", {})
        self.presence_gate = self._cfg("presence_gate", {})
        self.zones = self._cfg("zones", {})
        self.humidifiers = self._cfg("humidifiers", {})
        self.aq = self._cfg("aq", {})
        self.alerts = self._cfg("alerts", [])
        self._level_labels = resolve_level_labels(entry.data, entry.options)
        self.alert_handling_enabled = bool(
            self._cfg(CONF_ALERT_HANDLING_ENABLED, DEFAULT_ALERT_HANDLING_ENABLED)
        )
        self.alert_only_mode = bool(self._cfg("alert_only_mode", False))
        self._unsub = None
        self._periodic = None
        self._aq_tasks: Dict[str, asyncio.Task] = {}
        self._aq_trigger_active: Dict[str, bool] = {}
        self._visual_alert_tasks: Dict[Tuple[str, str, str], asyncio.Task] = {}
        self._visual_alert_active: set[Tuple[str, str, str]] = set()
        self._startup_recheck_task: Optional[asyncio.Task] = None
        self._co_clear_recheck_task: Optional[asyncio.Task] = None
        self._last_alert: Dict[int, datetime] = {}
        self._active_alert_identity: Optional[Tuple[str, str, str]] = None
        self._co_emergency_active = False
        self._co_below_since: Optional[datetime] = None
        self._evaluate_lock: Optional[asyncio.Lock] = None
        self._evaluate_pending = False
        self._stopped = False
        self._humidifier_lane_demand: Dict[str, bool] = {}
        self._humidifier_output_records: Dict[str, Dict[str, Any]] = {}
        self._humidifier_retry_tasks: Dict[str, asyncio.Task] = {}
        configured_interval = None
        if entry.options:
            configured_interval = entry.options.get("engine_interval_minutes")
        if configured_interval is None:
            configured_interval = entry.data.get(
                "engine_interval_minutes",
                ENGINE_INTERVAL_MINUTES_DEFAULT,
            )
        self.engine_interval_minutes = _bounded_int(
            configured_interval,
            ENGINE_INTERVAL_MIN,
            ENGINE_INTERVAL_MAX,
            ENGINE_INTERVAL_MINUTES_DEFAULT,
        )
        if self.alert_only_mode:
            self.zones = {}
            self.humidifiers = {}
            self.aq = {}
            _LOGGER.info(
                "HI entry %s is running in alert-only mode; zone/humidifier/AQ output lanes are disabled.",
                entry.entry_id,
            )

    def _cfg(self, key: str, default: Any) -> Any:
        if self.entry.options and key in self.entry.options:
            return self.entry.options.get(key, default)
        return self.entry.data.get(key, default)

    async def async_start(self) -> None:
        self._stopped = False
        sources = self._evaluation_sources()
        self._unsub = async_track_state_change_event(self.hass, sources, self._handle_change)
        self._periodic = async_track_time_interval(
            self.hass,
            self._periodic_check,
            timedelta(minutes=self.engine_interval_minutes),
        )
        await self.async_request_evaluate()
        self._schedule_startup_recheck()
        self._notify_other_humidifier_engines()

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unsub:
            self._unsub()
        if self._periodic:
            self._periodic()
        if self._startup_recheck_task and not self._startup_recheck_task.done():
            self._startup_recheck_task.cancel()
        self._startup_recheck_task = None
        self._cancel_co_clear_recheck()
        for task in self._aq_tasks.values():
            task.cancel()
        for task in self._visual_alert_tasks.values():
            task.cancel()
        for task in self._humidifier_retry_tasks.values():
            task.cancel()
        self._humidifier_retry_tasks.clear()
        self._visual_alert_tasks.clear()
        self._visual_alert_active.clear()
        self._notify_other_humidifier_engines()

    async def _handle_change(self, event) -> None:
        if self._is_pause_timer_countdown_update(event):
            return
        await self.async_request_evaluate()

    def _is_pause_timer_countdown_update(self, event) -> bool:
        """Return whether an event only refreshes the active pause countdown."""
        event_data = getattr(event, "data", {}) or {}
        entity_id = event_data.get("entity_id")
        if not entity_id:
            return False
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        pause_timer = data.get("hi_timers", {}).get("air_control_pause")
        if entity_id != getattr(pause_timer, "entity_id", None):
            return False
        old_state = event_data.get("old_state")
        new_state = event_data.get("new_state")
        return (
            getattr(old_state, "state", None) == "active"
            and getattr(new_state, "state", None) == "active"
        )

    async def _periodic_check(self, now) -> None:
        await self.async_request_evaluate()

    async def async_request_evaluate(self) -> None:
        """Request an immediate evaluation cycle."""
        if self._stopped:
            return
        evaluate_lock = self._get_evaluate_lock()
        if evaluate_lock.locked():
            self._evaluate_pending = True
            _LOGGER.debug(
                "HI entry %s evaluation already running; queued one follow-up cycle.",
                self.entry.entry_id,
            )
            return
        async with evaluate_lock:
            while True:
                self._evaluate_pending = False
                await self._evaluate()
                if not self._evaluate_pending:
                    break

    def _get_evaluate_lock(self) -> asyncio.Lock:
        if self._evaluate_lock is None:
            self._evaluate_lock = asyncio.Lock()
        return self._evaluate_lock

    def _schedule_startup_recheck(self) -> None:
        if self._startup_recheck_task and not self._startup_recheck_task.done():
            self._startup_recheck_task.cancel()

        async def _startup_recheck() -> None:
            try:
                await asyncio.sleep(STARTUP_SENSOR_RECHECK_SECONDS)
                await self.async_request_evaluate()
            except asyncio.CancelledError:
                return

        self._startup_recheck_task = asyncio.create_task(_startup_recheck())

    async def _evaluate(self) -> None:
        try:
            target_profile = self._active_target_profile()
            house_humidity = self._level_avg("humidity", None)
            humidity_class = seasonal_humidity_state(house_humidity, target_profile)
            _LOGGER.debug(
                "HI entry %s active target profile: %s (low=%.1f high=%.1f high_risk=%.1f)",
                self.entry.entry_id,
                target_profile.label,
                target_profile.low,
                target_profile.high,
                target_profile.high_risk,
            )
            _LOGGER.debug(
                "HI entry %s seasonal adjustments applied: condensation danger<=%.1f risk<=%.1f watch<=%.1f; mould spread danger<=%.1f risk<=%.1f; mould excess risk>=%.1f danger>=%.1f",
                self.entry.entry_id,
                target_profile.condensation_danger_spread,
                target_profile.condensation_risk_spread,
                target_profile.condensation_watch_spread,
                target_profile.mould_spread_danger,
                target_profile.mould_spread_risk,
                target_profile.mould_excess_risk,
                target_profile.mould_excess_danger,
            )
            _LOGGER.debug(
                "HI entry %s humidity badge classification: %s (humidity=%s)",
                self.entry.entry_id,
                humidity_class,
                f"{house_humidity:.1f}%" if house_humidity is not None else "unknown",
            )

            # Absolute top-priority lane: CO emergency must bypass gates,
            # pause, manual override, and normal control locks.
            if self._co_emergency_active and self._co_clear_ready():
                self._co_emergency_active = False
                self._co_below_since = None
                self._cancel_co_clear_recheck()
            if self._co_emergency_triggered():
                await self._sync_visual_alert_tasks([])
                await self._apply_co_emergency()
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        "CO emergency protection is active, so all configured ventilation outputs are forced to 100%."
                    ),
                    display_facts_factory=self._co_display_facts,
                )
                return
            await self._set_bool("air_co_emergency_active", self._co_emergency_active)

            if self._manual_override_active():
                await self._stand_down_for_manual_override()
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        "Manual control is active. HI leaves fans, switches, humidifiers, and alert lights as they are. Control stays with you or another automation until Manual is turned off. CO emergency protection can still run configured ventilation at full speed."
                    ),
                    display_facts_factory=lambda: self._control_lock_display_facts(
                        "manual_override"
                    ),
                )
                return

            control_lock_kind, control_lock_reason = self._control_lock_status()
            if control_lock_reason:
                await self._sync_visual_alert_tasks([])
                await self._return_to_normal()
                await self._set_runtime_reason(
                    self._with_isolation_notice(control_lock_reason),
                    display_facts_factory=lambda: self._control_lock_display_facts(
                        control_lock_kind or "disabled"
                    ),
                )
                return

            gate_status = self._gate_evaluation()
            if not gate_status.allowed:
                await self._sync_visual_alert_tasks([])
                action = self.time_gate.get("outside_action", "safe_state")
                if action == "safe_state":
                    await self._return_to_normal()
                    await self._set_runtime_mode("global_gate", "GLOBAL GATE")
                    await self._set_runtime_reason(
                        self._with_isolation_notice(
                            gate_status.technical_reason
                            or "Global gate is blocking automation, so outputs were moved to a safe state."
                        ),
                        display_facts_factory=lambda: self._gate_display_facts(
                            gate_status, action="safe_state"
                        ),
                    )
                else:
                    await self._clear_alert_runtime_state()
                    await self._set_runtime_mode("global_gate", "GLOBAL GATE")
                    await self._set_runtime_reason(
                        self._with_isolation_notice(
                            gate_status.technical_reason
                            or "Global gate is blocking automation; no output changes were applied."
                        ),
                        display_facts_factory=lambda: self._gate_display_facts(
                            gate_status, action="no_change"
                        ),
                    )
                return
            if self._pause_active():
                await self._sync_visual_alert_tasks([])
                await self._return_to_normal()
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        "Pause is active, so automation is temporarily standing down."
                    ),
                    display_facts_factory=self._pause_display_facts,
                )
                return
            missing_required_telemetry = self._missing_required_telemetry(house_humidity)
            if missing_required_telemetry:
                telemetry_label = " and ".join(missing_required_telemetry)
                telemetry_verb = "is" if len(missing_required_telemetry) == 1 else "are"
                await self._sync_visual_alert_tasks([])
                await self._return_to_normal()
                await self._set_runtime_mode("telemetry_unavailable", "TELEMETRY UNAVAILABLE")
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        f"Required {telemetry_label} telemetry {telemetry_verb} unavailable, so automation is standing down instead of running zone, alert, AQ, or humidifier lanes."
                    ),
                    display_facts_factory=lambda: self._telemetry_display_facts(
                        missing_required_telemetry
                    ),
                )
                return

            # Alert lane is high priority and suppresses all lower lanes.
            alert_active, alert_details = await self._handle_alerts()
            if alert_active:
                selected_alert = alert_details[0] if alert_details else {}
                selected_outputs = selected_alert.get("outputs", []) if selected_alert else []
                await self._deactivate_non_alert_activity(exclude_zone_outputs=selected_outputs)
                if selected_outputs and selected_alert.get("boost_level"):
                    await self._set_fan_outputs_level(selected_outputs, selected_alert["boost_level"])
                await self._set_runtime_mode("alert", "ALERT")
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        self._build_runtime_reason(
                            runtime_mode="alert",
                            alert_labels=alert_details,
                            zone1_active=False,
                            zone2_active=False,
                            aq_active=False,
                            zone1_detail=None,
                            zone2_detail=None,
                            aq_details=[],
                            humidifier_details=[],
                        )
                    ),
                    display_facts_factory=lambda: self._runtime_display_facts(
                        runtime_mode="alert",
                        alert_details=alert_details,
                        zone_detail=None,
                        aq_details=[],
                        humidifier_details=[],
                    ),
                )
                return

            # Humidifiers are independent from zone/AQ lane order.
            humidifier_details = await self._handle_humidifiers()

            # Requested lane order: zone1 -> zone2 -> AQ. Only the selected
            # ventilation lane may write fan outputs in a cycle.
            zone1_active, zone1_mode, zone1_detail = await self._handle_zone_by_key("zone1")
            zone2_active = False
            zone2_mode = None
            zone2_detail = None
            if zone1_active:
                await self._set_zone_outputs_auto(exclude=zone1_detail.get("outputs", []) if zone1_detail else [])
            else:
                zone2_active, zone2_mode, zone2_detail = await self._handle_zone_by_key("zone2")
                if zone2_active:
                    await self._set_zone_outputs_auto(exclude=zone2_detail.get("outputs", []) if zone2_detail else [])
            zone_outputs_active = zone1_active or zone2_active

            # AQ lane only runs when no alert or zone lane is active.
            aq_active = False
            aq_details: List[Dict[str, Any]] = []
            if not alert_active and not zone_outputs_active:
                aq_active, aq_details = await self._handle_aq()
            else:
                await self._deactivate_aq_activity(set_fan_auto=not zone_outputs_active)

            if not (zone1_active or zone2_active):
                await self._set_zone_outputs_auto(exclude=self._active_aq_outputs() if aq_active else None)

            runtime_mode = "normal"
            runtime_display = "NORMAL"
            if alert_active:
                runtime_mode = "alert"
                runtime_display = "ALERT"
            elif zone1_active:
                runtime_mode = zone1_mode or "cooking"
                runtime_display = self._zone_display_label("zone1", runtime_mode)
            elif zone2_active:
                runtime_mode = zone2_mode or "bathroom"
                runtime_display = self._zone_display_label("zone2", runtime_mode)
            elif aq_active:
                runtime_mode = "air_quality"
                runtime_display = "AIR QUALITY"
            await self._set_runtime_mode(runtime_mode, runtime_display)
            await self._set_runtime_reason(
                self._with_isolation_notice(
                    self._build_runtime_reason(
                        runtime_mode=runtime_mode,
                        alert_labels=alert_details,
                        zone1_active=zone1_active,
                        zone2_active=zone2_active,
                        aq_active=aq_active,
                        zone1_detail=zone1_detail,
                        zone2_detail=zone2_detail,
                        aq_details=aq_details,
                        humidifier_details=humidifier_details,
                    )
                ),
                display_facts_factory=lambda: self._runtime_display_facts(
                    runtime_mode=runtime_mode,
                    alert_details=alert_details,
                    zone_detail=zone1_detail if zone1_active else zone2_detail,
                    aq_details=aq_details,
                    humidifier_details=humidifier_details,
                ),
            )
        except Exception:
            _LOGGER.exception("Unhandled error in HI automation evaluation cycle")
        finally:
            self._refresh_core_entities()

    def _control_lock_status(self) -> Tuple[Optional[str], Optional[str]]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        if booleans.get("air_control_enabled") and not booleans["air_control_enabled"].is_on:
            return "disabled", "System control is disabled, so all automation lanes are idle."
        if booleans.get("air_control_manual_override") and booleans["air_control_manual_override"].is_on:
            return "manual_override", "Manual control is active, so HI leaves ordinary outputs as they are unless CO emergency protection needs to run configured ventilation at full speed."
        return None, None

    def _control_lock_reason(self) -> Optional[str]:
        return self._control_lock_status()[1]

    def _manual_override_active(self) -> bool:
        return self._bool_is_on("air_control_manual_override")

    def _gate_status(self) -> Tuple[bool, Optional[str]]:
        status = self._gate_evaluation()
        return status.allowed, status.technical_reason

    def _gate_evaluation(self) -> _GateStatus:
        if self.time_gate.get("enabled"):
            now = dt_util.now().time()
            start = _parse_time(self.time_gate.get("start"))
            end = _parse_time(self.time_gate.get("end"))
            if start and end:
                in_window = _time_in_window(now, start, end)
                if not in_window:
                    action = self.time_gate.get("outside_action", "no_action")
                    if action == "no_action":
                        return _GateStatus(allowed=True)
                    return _GateStatus(
                        allowed=False,
                        kind="time",
                        technical_reason=(
                            f"Time gate is outside {start.strftime('%H:%M')} - "
                            f"{end.strftime('%H:%M')}; action '{action}' is active."
                        ),
                        presentation_variant="time_outside_window",
                        window_start=start.strftime("%H:%M"),
                        window_end=end.strftime("%H:%M"),
                    )
        if self.presence_gate.get("enabled"):
            entities = self.presence_gate.get("entities", [])
            present_states = set(self.presence_gate.get("present_states", []))
            away_states = set(self.presence_gate.get("away_states", []))
            if entities and present_states:
                unavailable_count = 0
                away_count = 0
                other_count = 0
                for entity_id in entities:
                    state = self.hass.states.get(entity_id)
                    state_text = str(getattr(state, "state", "") or "").strip()
                    if not state or state_text.lower() in {"unknown", "unavailable"}:
                        unavailable_count += 1
                        continue
                    if state_text in present_states:
                        return _GateStatus(allowed=True)
                    if away_states and state_text in away_states:
                        away_count += 1
                        continue
                    other_count += 1
                variant = (
                    "presence_unavailable"
                    if unavailable_count or other_count
                    else "presence_away"
                )
                return _GateStatus(
                    allowed=False,
                    kind="presence",
                    technical_reason=(
                        "Presence gate is active (no entity in present states). "
                        f"Snapshot: {self._presence_snapshot(entities)}."
                    ),
                    presentation_variant=variant,
                    configured_count=len(entities),
                    unavailable_count=unavailable_count,
                    away_count=away_count,
                    other_count=other_count,
                )
        return _GateStatus(allowed=True)

    def _presence_snapshot(self, entities: List[str]) -> str:
        parts: List[str] = []
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            name = self._entity_display_name(entity_id)
            parts.append(f"{name}={state.state if state else 'unknown'}")
        return ", ".join(parts) if parts else "no presence entities configured"

    def _evaluation_sources(self) -> List[str]:
        sources = [t["entity_id"] for t in self.telemetry if t.get("entity_id")]
        sources.extend(self.presence_gate.get("entities", []) or [])
        for cfg in self.humidifiers.values():
            if isinstance(cfg, dict):
                sources.extend(cfg.get("outputs", []) or [])
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        timers = data.get("hi_timers", {})
        for key, entity in booleans.items():
            if key not in _EVALUATION_SWITCH_SOURCE_KEYS:
                continue
            entity_id = getattr(entity, "entity_id", None)
            if entity_id:
                sources.append(entity_id)
        for key, entity in timers.items():
            if key not in _EVALUATION_TIMER_SOURCE_KEYS:
                continue
            entity_id = getattr(entity, "entity_id", None)
            if entity_id:
                sources.append(entity_id)
        return sorted(set(sources))

    def _has_telemetry_type(self, sensor_type: str) -> bool:
        return any(item.get("sensor_type") == sensor_type for item in self.telemetry)

    def _missing_required_telemetry(self, house_humidity: Optional[float]) -> List[str]:
        missing: List[str] = []
        if house_humidity is None:
            missing.append("humidity")
        if self._has_telemetry_type("temperature") and self._level_avg("temperature", None) is None:
            missing.append("temperature")
        return missing

    def _co_emergency_triggered(self) -> bool:
        start_threshold, _, _ = self._co_emergency_settings()
        co_values = self._collect_values("co")
        if any(val >= start_threshold for val in co_values):
            self._co_emergency_active = True
            return True
        return self._co_emergency_active

    def _co_clear_ready(self) -> bool:
        _, clear_threshold, _ = self._co_emergency_settings()
        co_values = self._collect_values("co")
        if not co_values:
            self._cancel_co_clear_recheck()
            return False
        now = datetime.now()
        if all(val < clear_threshold for val in co_values):
            if not self._co_below_since:
                self._co_below_since = now
            ready = now - self._co_below_since >= CO_EMERGENCY_CLEAR_HOLD
            if not ready:
                self._schedule_co_clear_recheck(now)
            return ready
        self._co_below_since = None
        self._cancel_co_clear_recheck()
        return False

    def _schedule_co_clear_recheck(self, now: datetime) -> None:
        if self._co_clear_recheck_task and not self._co_clear_recheck_task.done():
            return
        if self._co_below_since is None:
            return
        remaining = CO_EMERGENCY_CLEAR_HOLD - (now - self._co_below_since)
        delay = max(0.0, remaining.total_seconds())

        async def _co_clear_recheck() -> None:
            task = asyncio.current_task()
            try:
                await asyncio.sleep(delay)
                await self.async_request_evaluate()
            except asyncio.CancelledError:
                return
            finally:
                if self._co_clear_recheck_task is task:
                    self._co_clear_recheck_task = None

        self._co_clear_recheck_task = asyncio.create_task(_co_clear_recheck())

    def _cancel_co_clear_recheck(self) -> None:
        if self._co_clear_recheck_task and not self._co_clear_recheck_task.done():
            self._co_clear_recheck_task.cancel()
        self._co_clear_recheck_task = None

    async def _apply_co_emergency(self) -> None:
        _, _, outputs = self._co_emergency_settings()
        await self._deactivate_aq_activity(set_fan_auto=False)
        manual_override = self._manual_override_active()
        if manual_override:
            await self._hold_humidifier_activity_for_manual_override()
        else:
            await self._deactivate_humidifier_activity(turn_off_outputs=True)
        await self._clear_alert_runtime_state()
        await self._set_bool("air_co_emergency_active", True)
        if not manual_override:
            all_outputs = self._all_fan_outputs()
            outputs_to_auto = [entity_id for entity_id in all_outputs if entity_id not in outputs]
            await self._set_fan_outputs_auto(outputs_to_auto)
        await self._set_fan_outputs_level(
            outputs,
            "100",
            allow_manual_override=True,
        )
        await self._set_runtime_mode("co_emergency", "CO EMERGENCY")

    async def _handle_alerts(self) -> Tuple[bool, List[Dict[str, Any]]]:
        active_details: List[Dict[str, Any]] = []
        alert_switch_states = {
            idx: False for idx in range(max(len(self.alerts), 5))
        }
        if not self.alert_handling_enabled:
            await self._clear_alert_runtime_state()
            _LOGGER.debug(
                "HI alert handling is disabled for entry %s; non-CO alert lane skipped.",
                self.entry.entry_id,
            )
            await self._sync_visual_alert_tasks([])
            return False, []
        for idx, alert in enumerate(self.alerts):
            if not alert.get("enabled", True):
                continue
            detail = self._alert_detail(idx, alert)
            triggered = detail is not None
            alert_switch_states[idx] = triggered
            if not triggered:
                continue
            active_details.append(detail)
        await self._sync_alert_activity_switches(alert_switch_states)
        await self._sync_visual_alert_tasks(active_details)
        inferred_details = self._inferred_alert_details(active_details)
        if inferred_details:
            _LOGGER.debug(
                "HI inferred %s built-in alert candidate(s) for entry %s.",
                len(inferred_details),
                self.entry.entry_id,
            )
            active_details.extend(inferred_details)
        active_details.sort(
            key=lambda item: (
                item.get("priority", 999),
                item.get("zone_priority", 999),
                item.get("index", 999),
            )
        )
        selected_alert = self._select_alert_detail(active_details)
        if selected_alert:
            active_details = [selected_alert] + [
                detail for detail in active_details if detail is not selected_alert
            ]
        self._record_alert_resolution(active_details)
        return selected_alert is not None, active_details

    def _alert_triggered(self, alert: Dict[str, Any]) -> bool:
        return self._alert_detail(0, alert) is not None

    def _select_alert_detail(self, details: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select the actionable alert to control outputs, holding it until it clears."""
        actionable = [detail for detail in details if _alert_can_control(detail)]
        if not actionable:
            if details:
                _LOGGER.debug(
                    "HI alert candidate(s) found for entry %s but none can safely control outputs; automation will continue to the next lane.",
                    self.entry.entry_id,
                )
            self._active_alert_identity = None
            return None

        best = actionable[0]
        current = None
        if self._active_alert_identity:
            for detail in actionable:
                if _alert_identity(detail) == self._active_alert_identity:
                    current = detail
                    break

        selected = best
        if current and int(best.get("priority", 999)) >= int(current.get("priority", 999)):
            selected = current
            if selected is not best:
                selected["held_until_clear"] = True
                _LOGGER.debug(
                    "HI holding alert selection for entry %s until clear: selected=%s; best_candidate=%s",
                    self.entry.entry_id,
                    selected.get("companion") or selected.get("label"),
                    best.get("companion") or best.get("label"),
                )
        else:
            selected.pop("held_until_clear", None)

        self._active_alert_identity = _alert_identity(selected)
        return selected

    def _inferred_alert_details(self, configured_details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build alert candidates from HI's own risk model without duplicating explicit rows."""
        active_keys = {
            (str(detail.get("trigger_type") or ""), str(detail.get("room") or "").lower())
            for detail in configured_details
        }
        inferred: List[Dict[str, Any]] = []
        base_index = len(self.alerts)
        for offset, trigger_type in enumerate(_BUILT_IN_ZONE_ALERT_TRIGGERS):
            detail = self._alert_detail(
                base_index + offset,
                {
                    "enabled": True,
                    "trigger_type": trigger_type,
                    "room": None,
                    "threshold": None,
                    "_inferred": True,
                },
            )
            if not detail:
                continue
            key = (str(detail.get("trigger_type") or ""), str(detail.get("room") or "").lower())
            if key in active_keys:
                continue
            detail["source"] = "built_in_risk_model"
            detail["label"] = f"Built-in {detail.get('label')}"
            inferred.append(detail)
        return inferred

    def _alert_detail(self, idx: int, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ttype = alert.get("trigger_type")
        room_scope = self._alert_room_scope(alert)
        if ttype == "condensation_danger":
            match = self._matching_condensation_room("Danger", room_scope)
            if match:
                return self._build_environmental_alert_detail(idx, alert, match)
            return None
        if ttype == "condensation_risk":
            match = self._matching_condensation_room("Risk", room_scope)
            if match:
                return self._build_environmental_alert_detail(idx, alert, match)
            return None
        if ttype == "mould_danger":
            match = self._matching_mould_room("Danger", room_scope)
            if match:
                return self._build_environmental_alert_detail(idx, alert, match)
            return None
        if ttype == "mould_risk":
            match = self._matching_mould_room("Risk", room_scope)
            if match:
                return self._build_environmental_alert_detail(idx, alert, match)
            return None
        if ttype == "humidity_danger":
            profile = self._active_target_profile()
            threshold = float(profile.high_risk)
            match = self._matching_humidity_sensor(threshold, room_scope)
            if match:
                sensor, room, value = match
                detail = self._build_alert_detail(idx, alert, sensor=sensor, room=room)
                detail["measured"] = f"{value:.1f}% >= active {profile.label} high-risk threshold {threshold:g}%"
                detail["measured_value"] = value
                detail["measured_unit"] = "%"
                detail["threshold"] = threshold
                detail["comparison"] = "at_or_above"
                detail["_display_profile_label"] = profile.label
                detail["threshold_source"] = f"active profile ({profile.label})"
                detail["source_summary"] = _alert_source_summary(
                    trigger_type=ttype,
                    room=room,
                    zone=detail.get("zone"),
                    measured=f"{value:.1f}%",
                    threshold=f"{threshold:g}% threshold",
                )
                return detail
            return None
        if ttype == "co_emergency":
            threshold = _safe_alert_threshold("co_emergency", alert.get("threshold"), float(CO_EMERGENCY_START))
            values = self._collect_values("co")
            if any(val >= threshold for val in values):
                return self._build_alert_detail(idx, alert, sensor=None, room=None)
        return None

    def _build_environmental_alert_detail(
        self,
        idx: int,
        alert: Dict[str, Any],
        match: _AlertMatch,
    ) -> Dict[str, Any]:
        detail = self._build_alert_detail(
            idx,
            alert,
            sensor=match.sensor,
            room=match.room,
        )
        detail.update(
            {
                "measured_value": match.measured,
                "measured_unit": match.unit,
                "threshold": match.threshold,
                "comparison": match.comparison,
                "profile_label": match.profile_label,
            }
        )
        return detail

    def _build_alert_detail(
        self,
        idx: int,
        alert: Dict[str, Any],
        *,
        sensor: Optional[str],
        room: Optional[str],
    ) -> Dict[str, Any]:
        trigger_type = str(alert.get("trigger_type") or "unknown")
        zone_key, zone = self._zone_for_room(room)
        boost_level = None
        outputs: List[str] = []
        zone_label = None
        degraded_reasons: List[str] = []
        if room and not zone_key:
            degraded_reasons.append(f"No enabled zone maps room '{room}'.")
        if zone_key and zone:
            outputs = list(zone.get("outputs", []) or [])
            zone_label = "Zone 1" if zone_key == "zone1" else "Zone 2" if zone_key == "zone2" else zone_key
            boost_level = _normalize_fan_level(
                zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
                ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
            )
            if not outputs:
                degraded_reasons.append(f"{zone_label} has no fan outputs configured.")
        if trigger_type in ROOM_SCOPED_ALERT_TRIGGERS and not sensor:
            degraded_reasons.append("Originating telemetry sensor could not be resolved.")
        label = self._alert_label(idx, alert, resolved_room=room)
        alert_kind, severity = _alert_kind_and_severity(trigger_type)
        companion = _alert_companion_label(alert_kind, severity, room, zone_label)
        return {
            "index": idx,
            "label": label,
            "companion": companion,
            "trigger_type": trigger_type,
            "alert_type": alert_kind,
            "severity": severity,
            "sensor": sensor,
            "room": room,
            "zone_key": zone_key,
            "zone": zone_label,
            "zone_priority": _zone_priority(zone_key),
            "outputs": outputs,
            "boost_level": boost_level,
            "priority": _alert_priority(trigger_type),
            "source": "configured_alert" if not alert.get("_inferred") else "built_in_risk_model",
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "source_summary": _alert_source_summary(
                trigger_type=trigger_type,
                room=room,
                zone=zone_label,
                measured=None,
                threshold=None,
            ),
            "visual_alert": {
                "configured": bool(alert.get("lights")),
                "lights": list(alert.get("lights", []) or []),
                "power_entity": alert.get("power_entity"),
                "flash_mode": alert.get("flash_mode") or "red",
                "duration": alert.get("duration", 10),
                "flash_count": HUMIDITY_ALERT_FLASH_COUNT,
                "repeat_minutes": HUMIDITY_ALERT_REPEAT_MINUTES,
                "restore_state": True,
            },
        }

    def _record_alert_resolution(self, details: List[Dict[str, Any]]) -> None:
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
        if not details:
            data["active_alert_context"] = "None"
            data["alert_telemetry"] = []
            return
        selected = details[0]
        data["active_alert_context"] = selected.get("source_summary") or selected.get("companion") or selected.get("label") or "Alert"
        data["alert_telemetry"] = [
            {
                key: value
                for key, value in detail.items()
                if key != "_display_profile_label"
            }
            for detail in details
        ]
        _LOGGER.debug(
            "HI alert resolved for entry %s: selected=%s; source=%s; sensor=%s; room=%s; zone=%s; outputs=%s; boost=%s",
            self.entry.entry_id,
            selected.get("companion") or selected.get("label"),
            selected.get("source"),
            selected.get("sensor"),
            selected.get("room"),
            selected.get("zone"),
            selected.get("outputs"),
            selected.get("boost_level"),
        )
        if len(details) > 1:
            _LOGGER.debug(
                "HI alert conflict resolved for entry %s: selected=%s; candidates=%s",
                self.entry.entry_id,
                selected.get("companion"),
                [
                    {
                        "alert": item.get("companion"),
                        "priority": item.get("priority"),
                        "zone": item.get("zone"),
                        "zone_priority": item.get("zone_priority"),
                    }
                    for item in details
                ],
            )
        if selected.get("degraded"):
            _LOGGER.debug(
                "HI alert degraded mode for entry %s: %s",
                self.entry.entry_id,
                "; ".join(selected.get("degraded_reasons", [])),
            )

    async def _sync_visual_alert_tasks(self, active_details: List[Dict[str, Any]]) -> None:
        active_identities = {
            _alert_identity(detail)
            for detail in active_details
            if self._visual_alert_configured(detail)
        }
        self._visual_alert_active = active_identities
        cancelled_tasks: List[asyncio.Task[Any]] = []
        for identity, task in list(self._visual_alert_tasks.items()):
            if identity not in active_identities:
                if task is not asyncio.current_task() and not task.done():
                    task.cancel()
                    cancelled_tasks.append(task)
                self._visual_alert_tasks.pop(identity, None)
        if cancelled_tasks:
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        for detail in active_details:
            if not self._visual_alert_configured(detail):
                if detail.get("trigger_type") in _BUILT_IN_ZONE_ALERT_TRIGGERS:
                    _LOGGER.debug(
                        "Alert %s triggered with no target lights configured; skipping visual flash task.",
                        int(detail.get("index", 0)) + 1,
                    )
                continue
            identity = _alert_identity(detail)
            existing = self._visual_alert_tasks.get(identity)
            if existing and not existing.done():
                continue
            task = asyncio.create_task(self._visual_alert_loop(identity, dict(detail)))
            self._visual_alert_tasks[identity] = task
            await asyncio.sleep(0)

    def _visual_alert_configured(self, detail: Dict[str, Any]) -> bool:
        visual = detail.get("visual_alert") if isinstance(detail, dict) else {}
        return bool(isinstance(visual, dict) and visual.get("lights"))

    async def _visual_alert_loop(
        self,
        identity: Tuple[str, str, str],
        detail: Dict[str, Any],
    ) -> None:
        try:
            while identity in self._visual_alert_active:
                if self._manual_override_active():
                    return
                visual = detail.get("visual_alert") or {}
                lights = list(visual.get("lights") or [])
                if not lights:
                    return
                flash_payload = {
                    "lights": lights,
                    "color": [255, 0, 0] if visual.get("flash_mode") == "red" else [255, 255, 255],
                    "duration": visual.get("duration", 10),
                    "flash_count": HUMIDITY_ALERT_FLASH_COUNT,
                }
                power_entity = visual.get("power_entity")
                if power_entity:
                    flash_payload["power_entity"] = power_entity
                if self._manual_override_active():
                    return
                try:
                    await async_flash_lights_for_alert(
                        self.hass,
                        power_entity=flash_payload.get("power_entity"),
                        lights=flash_payload["lights"],
                        color=flash_payload["color"],
                        duration=flash_payload["duration"],
                        flash_count=flash_payload["flash_count"],
                    )
                except Exception:
                    _LOGGER.exception(
                        "Alert flash service call failed for alert identity %s",
                        identity,
                    )
                await asyncio.sleep(timedelta(minutes=HUMIDITY_ALERT_REPEAT_MINUTES).total_seconds())
        except asyncio.CancelledError:
            return
        finally:
            current = self._visual_alert_tasks.get(identity)
            if current is asyncio.current_task():
                self._visual_alert_tasks.pop(identity, None)

    async def _handle_zone_by_key(self, zone_key: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        zone = self.zones.get(zone_key, {})
        if not zone.get("enabled"):
            return False, None, None

        triggers = zone.get("triggers", [])
        level = zone.get("level")
        outputs = zone.get("outputs", [])
        if not triggers or not outputs:
            return False, None, None

        run_level, trigger_details, trigger_facts = self._zone_trigger_level(
            triggers,
            zone,
            level,
        )
        if not run_level:
            return False, None, None

        await self._set_fan_outputs_level(outputs, run_level)
        zone_mode = self._zone_mode_from_zone(zone_key, zone)
        return (
            True,
            zone_mode,
            {
                "zone_key": zone_key,
                "ui_label": self._zone_display_label(zone_key, zone_mode),
                "outputs": outputs,
                "output_level": run_level,
                "triggers": trigger_details,
                "trigger_facts": trigger_facts,
            },
        )

    def _zone_trigger_level(
        self,
        triggers: List[str],
        zone: Dict[str, Any],
        level: Optional[str],
    ) -> Tuple[Optional[str], List[str], Tuple[_TriggerFact, ...]]:
        profile = self._active_target_profile()
        normal_level = _normalize_fan_level(
            zone.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
            ZONE_OUTPUT_LEVEL_DEFAULT,
        )
        boost_level = _normalize_fan_level(
            zone.get("boost_output_level", ZONE_OUTPUT_LEVEL_BOOST_DEFAULT),
            ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
        )
        if _fan_level_rank(boost_level) < _fan_level_rank(normal_level):
            boost_level = normal_level
        selected_level: Optional[str] = None
        trigger_details: List[str] = []
        trigger_facts: List[_TriggerFact] = []
        for trig in triggers:
            threshold = zone.get("thresholds", {}).get(trig)
            if trig == "humidity_high":
                zone_rooms = zone.get("rooms", [])
                room_avg = self._rooms_avg("humidity", zone_rooms)
                house_avg = self._level_avg("humidity", None)
                try:
                    threshold_val = float(threshold) if threshold is not None else None
                except (TypeError, ValueError):
                    threshold_val = None
                if room_avg is not None and house_avg is not None and threshold_val is not None:
                    delta = room_avg - house_avg
                    if delta >= threshold_val:
                        selected_level = _max_fan_level(selected_level, normal_level)
                        trigger_details.append(
                            f"Humidity delta {delta:.1f}% >= threshold {threshold_val:g}%"
                        )
                        trigger_facts.append(
                            _TriggerFact(
                                code="humidity_delta",
                                measured=round(delta, 1),
                                threshold=threshold_val,
                                unit="percentage_points",
                                comparison="at_or_above",
                            )
                        )
            elif trig == "air_quality_bad":
                iaq = self._level_avg("iaq", level)
                threshold_val = _to_float(threshold)
                if iaq is not None and threshold_val is not None and iaq <= threshold_val:
                    selected_level = _max_fan_level(selected_level, normal_level)
                    trigger_details.append(f"IAQ {iaq:.1f} <= threshold {threshold_val:g}")
                    trigger_facts.append(
                        _TriggerFact(
                            code="iaq_bad",
                            measured=iaq,
                            threshold=threshold_val,
                            unit="index",
                            comparison="at_or_below",
                        )
                    )
            elif trig == "condensation_risk":
                spread = self._worst_spread()
                threshold_val = _to_float(threshold)
                if threshold_val is None:
                    threshold_val = 4.0
                adjusted_threshold = profile.condensation_risk_spread + (threshold_val - 4.0)
                adjusted_threshold = max(0.5, min(12.0, adjusted_threshold))
                if spread is not None and spread <= adjusted_threshold:
                    selected_level = _max_fan_level(selected_level, boost_level)
                    trigger_details.append(
                        "Dew-point spread "
                        f"{spread:.1f} degC <= seasonal threshold {adjusted_threshold:g} degC "
                        f"(profile {profile.label}, user baseline {threshold_val:g} degC)"
                    )
                    trigger_facts.append(
                        _TriggerFact(
                            code="condensation_risk",
                            measured=round(spread, 1),
                            threshold=adjusted_threshold,
                            unit="degC",
                            comparison="at_or_below",
                            profile_label=profile.label,
                        )
                    )
            elif trig == "mould_risk":
                risk_level = self._worst_mould_level()
                threshold_val = _to_float(threshold)
                if threshold_val is not None and risk_level >= threshold_val:
                    selected_level = _max_fan_level(selected_level, boost_level)
                    trigger_details.append(
                        f"Mould risk level {risk_level} >= threshold {threshold_val:g}"
                    )
                    trigger_facts.append(
                        _TriggerFact(
                            code="mould_risk",
                            measured=float(risk_level),
                            threshold=threshold_val,
                            unit="risk_level",
                            comparison="at_or_above",
                            profile_label=profile.label,
                        )
                    )
        return selected_level, trigger_details, tuple(trigger_facts)

    async def _handle_aq(self) -> Tuple[bool, List[Dict[str, Any]]]:
        active = False
        active_details: List[Dict[str, Any]] = []
        configured_levels = set(self.aq.keys())
        for level in ("level1", "level2"):
            if level in configured_levels:
                continue
            await self._cancel_aq_task(level)
            await self._set_aq_level_active(level, False)
            await self._clear_aq_level_timer(level)
            self._aq_trigger_active[level] = False

        for level, cfg in self.aq.items():
            if not cfg.get("enabled"):
                await self._cancel_aq_task(level)
                await self._set_aq_level_active(level, False)
                await self._clear_aq_level_timer(level)
                self._aq_trigger_active[level] = False
                continue
            outputs = cfg.get("outputs", [])
            if not outputs:
                await self._cancel_aq_task(level)
                await self._set_aq_level_active(level, False)
                await self._clear_aq_level_timer(level)
                self._aq_trigger_active[level] = False
                continue
            task = self._aq_tasks.get(level)
            running = bool(task and not task.done())
            trigger_details, trigger_facts = self._aq_trigger_evaluation(level, cfg)
            triggered = bool(trigger_details)
            previously_triggered = self._aq_trigger_active.get(level, False)
            if triggered:
                active = True
                if not running or not previously_triggered:
                    await self._start_aq(level, cfg)
                    running = True
            elif not running:
                await self._cancel_aq_task(level)
                await self._set_aq_level_active(level, False)
                await self._clear_aq_level_timer(level)
            self._aq_trigger_active[level] = triggered
            if running or triggered:
                active = True
                active_details.append({
                    "level": level,
                    "outputs": cfg.get("outputs", []),
                    "output_level": _normalize_fan_level(
                        cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
                        ZONE_OUTPUT_LEVEL_DEFAULT,
                    ),
                    "run_duration": _bounded_int(cfg.get("run_duration", 30), 1, 24 * 60, 30),
                    "trigger_active": triggered,
                    "run_window_active": running,
                    "trigger_facts": trigger_facts,
                    "triggers": trigger_details
                    or ["AQ run window is still active from a recent trigger."],
                })
        return active, active_details

    def _aq_trigger_evaluation(
        self,
        level: str,
        cfg: Dict[str, Any],
    ) -> Tuple[List[str], Tuple[_TriggerFact, ...]]:
        details: List[str] = []
        facts: List[_TriggerFact] = []
        triggers = cfg.get("triggers", [])
        thresholds = cfg.get("thresholds", {})
        for trig in triggers:
            threshold = thresholds.get(trig)
            if trig == "iaq_bad":
                val = self._level_avg("iaq", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val <= threshold_val:
                    details.append(f"IAQ {val:.1f} <= threshold {threshold_val:g}")
                    facts.append(
                        _TriggerFact("iaq_bad", val, threshold_val, "index", "at_or_below")
                    )
            if trig == "pm25_high":
                val = self._level_avg("pm25", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"PM2.5 {val:.1f} >= threshold {threshold_val:g}")
                    facts.append(
                        _TriggerFact("pm25_high", val, threshold_val, "ug_m3", "at_or_above")
                    )
            if trig == "voc_bad":
                val = self._level_avg("voc", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"VOC {val:.1f} >= threshold {threshold_val:g}")
                    facts.append(
                        _TriggerFact("voc_bad", val, threshold_val, "index", "at_or_above")
                    )
            if trig == "co2_high":
                val = self._level_avg("co2", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"CO2 {val:.1f} >= threshold {threshold_val:g}")
                    facts.append(
                        _TriggerFact("co2_high", val, threshold_val, "ppm", "at_or_above")
                    )
            if trig == "co_warning":
                val = self._level_avg("co", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"CO {val:.1f} >= threshold {threshold_val:g}")
                    facts.append(
                        _TriggerFact("co_warning", val, threshold_val, "ppm", "at_or_above")
                    )
        return details, tuple(facts)

    def _aq_trigger_details(self, level: str, cfg: Dict[str, Any]) -> List[str]:
        return self._aq_trigger_evaluation(level, cfg)[0]

    async def _start_aq(self, level: str, cfg: Dict[str, Any]) -> None:
        if self._manual_override_active():
            return
        outputs = cfg.get("outputs", [])
        output_level = _normalize_fan_level(
            cfg.get("output_level", ZONE_OUTPUT_LEVEL_DEFAULT),
            ZONE_OUTPUT_LEVEL_DEFAULT,
        )
        duration = _bounded_int(cfg.get("run_duration", 30), 1, 24 * 60, 30) * 60
        await self._set_fan_outputs_level(outputs, output_level)
        await self._set_aq_level_active(level, True)
        await self._set_aq_level_timer(level, duration)

        if task := self._aq_tasks.get(level):
            task.cancel()

        async def _timer() -> None:
            try:
                await asyncio.sleep(duration)
                if self._manual_override_active():
                    return
                if self._aq_trigger_details(level, cfg):
                    await self._start_aq(level, cfg)
                else:
                    reserved = self._aq_outputs_reserved_by_other_levels(level)
                    outputs_to_auto = [entity_id for entity_id in outputs if entity_id not in reserved]
                    await self._set_fan_outputs_auto(outputs_to_auto)
                    await self._set_aq_level_active(level, False)
                    await self._clear_aq_level_timer(level)
                    self._aq_trigger_active[level] = False
                    await self.async_request_evaluate()
            except asyncio.CancelledError:
                return

        self._aq_tasks[level] = asyncio.create_task(_timer())

    async def _handle_humidifiers(self) -> List[Dict[str, Any]]:
        lane_details: Dict[str, Dict[str, Any]] = {}
        output_owners: Dict[str, set[str]] = {}
        profile = self._active_target_profile()
        for level in ("level1", "level2"):
            active_key = self._humidifier_active_key(level)
            cfg = self.humidifiers.get(level)
            if not isinstance(cfg, dict):
                self._humidifier_lane_demand[level] = False
                await self._set_bool(active_key, False)
                continue

            outputs = cfg.get("outputs", [])
            outputs = sorted(
                {
                    str(entity_id).strip()
                    for entity_id in outputs
                    if str(entity_id).strip()
                }
            )
            for entity_id in outputs:
                output_owners.setdefault(entity_id, set()).add(level)

            lane_label = "downstairs" if level == "level1" else "upstairs"
            detail: Dict[str, Any] = {
                "level": level,
                "lane": lane_label,
                "season": profile.label,
                "profile": profile.key,
                "outputs": outputs,
                "demand": False,
                "status": "inactive",
                "environmental_state": "inactive",
            }

            if not cfg.get("enabled"):
                self._humidifier_lane_demand[level] = False
                await self._set_bool(active_key, False)
                lane_details[level] = detail
                continue
            if not outputs:
                self._humidifier_lane_demand[level] = False
                await self._set_bool(active_key, False)
                detail["status"] = "degraded"
                detail["reconciliation"] = "degraded"
                detail["failure_category"] = "no_outputs"
                lane_details[level] = detail
                continue

            avg = self._level_avg("humidity", level)
            if avg is None:
                self._humidifier_lane_demand[level] = False
                await self._set_bool(active_key, False)
                detail["status"] = "degraded"
                detail["environmental_state"] = "unknown"
                detail["reconciliation"] = "degraded"
                detail["failure_category"] = "telemetry_unavailable"
                lane_details[level] = detail
                continue

            band_adjust = _to_float(cfg.get("band_adjust", 0))
            if band_adjust is None:
                band_adjust = 0.0
            recovery_in_band = _to_float(cfg.get("recovery_in_band", HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT))
            if recovery_in_band is None:
                recovery_in_band = float(HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT)
            recovery_in_band = max(1.0, min(8.0, recovery_in_band))
            low = profile.low + band_adjust
            high = profile.high + band_adjust
            high_risk = profile.high_risk + band_adjust
            recovery_off = min(high, low + recovery_in_band)
            previous_demand = self._humidifier_lane_demand.get(
                level,
                self._bool_is_on(active_key),
            )

            if avg <= low:
                demand = True
                environmental_state = "start"
                trigger_condition = f"{avg:.1f}% <= start threshold {low:.1f}%"
            elif avg >= recovery_off:
                demand = False
                environmental_state = "inactive"
                trigger_condition = f"{avg:.1f}% >= stop threshold {recovery_off:.1f}%"
            else:
                demand = bool(previous_demand)
                environmental_state = "recovering" if demand else "inactive"
                trigger_condition = (
                    f"{avg:.1f}% is between start {low:.1f}% and stop {recovery_off:.1f}%"
                )

            self._humidifier_lane_demand[level] = demand
            await self._set_bool(active_key, demand)
            detail.update(
                {
                    "demand": demand,
                    "status": "active" if demand else "inactive",
                    "environmental_state": environmental_state,
                    "humidity": avg,
                    "low": low,
                    "high": high,
                    "high_risk": high_risk,
                    "recovery_off": recovery_off,
                    "trigger_condition": trigger_condition,
                    "recovery_behavior": (
                        f"Stop when humidity recovers to {recovery_off:.1f}% "
                        f"(inside target band {low:.1f}-{high:.1f}%)."
                    ),
                }
            )
            lane_details[level] = detail

            if demand:
                _LOGGER.debug(
                    "HI entry %s humidifier demand: lane=%s humidity=%.1f start<=%.1f stop>=%.1f target=%.1f-%.1f season=%s state=%s",
                    self.entry.entry_id,
                    lane_label,
                    avg,
                    low,
                    recovery_off,
                    low,
                    high,
                    profile.label,
                    environmental_state,
                )
            elif previous_demand:
                _LOGGER.debug(
                    "HI entry %s humidifier demand cleared: lane=%s humidity=%.1f start<=%.1f stop>=%.1f target=%.1f-%.1f season=%s",
                    self.entry.entry_id,
                    lane_label,
                    avg,
                    low,
                    recovery_off,
                    low,
                    high,
                    profile.label,
                )

        output_status = await self._reconcile_humidifier_outputs(
            {
                entity_id: {
                    level
                    for level in owners
                    if bool(lane_details.get(level, {}).get("demand"))
                }
                for entity_id, owners in output_owners.items()
            },
            configured_owners=output_owners,
        )
        self._apply_humidifier_output_truth_to_lanes(lane_details, output_status)
        self._publish_humidifier_truth(lane_details, output_status)
        return [
            detail
            for level, detail in lane_details.items()
            if level in {"level1", "level2"} and detail.get("demand")
        ]

    async def _return_to_normal(self) -> None:
        await self._clear_alert_runtime_state()
        await self._set_zone_outputs_auto()
        await self._deactivate_aq_activity(set_fan_auto=True)
        await self._deactivate_humidifier_activity(turn_off_outputs=True)
        await self._set_runtime_mode("normal", "NORMAL")
        await self._set_runtime_reason(
            self._with_isolation_notice(
                "All lanes are idle, so outputs have returned to normal automatic behavior."
            )
        )

    async def _stand_down_for_manual_override(self) -> None:
        """Release ordinary HI ownership without changing physical outputs."""
        await self._sync_visual_alert_tasks([])
        await self._clear_alert_runtime_state()
        await self._deactivate_aq_activity(set_fan_auto=False)
        await self._hold_humidifier_activity_for_manual_override()
        await self._set_runtime_mode("manual_override", "MANUAL OVERRIDE")

    async def _hold_humidifier_activity_for_manual_override(self) -> None:
        """Publish observed humidifier truth while Manual owns physical outputs."""
        lane_details: Dict[str, Dict[str, Any]] = {}
        configured_owners: Dict[str, set[str]] = {}
        cancelled_retry_tasks = [
            task
            for task in self._humidifier_retry_tasks.values()
            if task is not asyncio.current_task() and not task.done()
        ]
        for entity_id in list(self._humidifier_retry_tasks):
            self._cancel_humidifier_retry(entity_id)
        if cancelled_retry_tasks:
            await asyncio.gather(*cancelled_retry_tasks, return_exceptions=True)
        for level in ("level1", "level2"):
            cfg = self.humidifiers.get(level)
            outputs: List[str] = []
            if isinstance(cfg, dict):
                outputs = sorted(
                    {
                        str(entity_id).strip()
                        for entity_id in cfg.get("outputs", []) or []
                        if str(entity_id).strip()
                    }
                )
            for entity_id in outputs:
                configured_owners.setdefault(entity_id, set()).add(level)
            self._humidifier_lane_demand[level] = False
            await self._set_bool(self._humidifier_active_key(level), False)
            lane_details[level] = {
                "level": level,
                "lane": "downstairs" if level == "level1" else "upstairs",
                "outputs": outputs,
                "demand": False,
                "status": "manual_hold",
                "environmental_state": "manual_hold",
            }

        for entity_id in set(self._humidifier_output_records) - set(configured_owners):
            self._cancel_humidifier_retry(entity_id)
            self._humidifier_output_records.pop(entity_id, None)

        now = self._monotonic()
        output_status: Dict[str, Dict[str, Any]] = {}
        for entity_id in sorted(configured_owners):
            self._cancel_humidifier_retry(entity_id)
            record = self._humidifier_output_records.setdefault(
                entity_id,
                self._new_humidifier_output_record(),
            )
            observed, platform_action = self._humidifier_observed_state(entity_id)
            record["generation"] = int(record.get("generation", 0)) + 1
            record["desired_on"] = None
            record["owners"] = []
            record["configured_owners"] = sorted(configured_owners[entity_id])
            record["domain"] = entity_id.partition(".")[0]
            record["observed"] = observed
            record["platform_action"] = platform_action
            record["on_attempts"] = 0
            record["off_attempts"] = 0
            record["settling_until"] = 0.0
            record["next_allowed_at"] = 0.0
            record["mismatch_started"] = None
            record["last_command_intent"] = "none"
            record["last_dispatch_result"] = "not_requested"
            record["last_dispatch_utc"] = None
            record["failure_category"] = None
            record["fault_latched"] = False
            record["ownership_conflict"] = self._humidifier_ownership_conflict(
                entity_id
            )
            self._set_humidifier_reconciliation_state(
                record,
                "manual_hold",
                "manual_handover",
            )
            output_status[entity_id] = self._humidifier_output_status(record, now)

        self._apply_humidifier_output_truth_to_lanes(lane_details, output_status)
        self._publish_humidifier_truth(lane_details, output_status)

    async def _deactivate_non_alert_activity(self, exclude_zone_outputs: Optional[List[str]] = None) -> None:
        await self._deactivate_aq_activity(
            set_fan_auto=True,
            exclude_outputs=exclude_zone_outputs,
        )
        await self._set_zone_outputs_auto(exclude=exclude_zone_outputs)
        await self._deactivate_humidifier_activity(turn_off_outputs=True)

    async def _deactivate_humidifier_activity(self, *, turn_off_outputs: bool) -> None:
        lane_details: Dict[str, Dict[str, Any]] = {}
        configured_owners: Dict[str, set[str]] = {}
        for level in ("level1", "level2"):
            cfg = self.humidifiers.get(level)
            outputs = []
            if isinstance(cfg, dict):
                outputs = sorted(
                    {
                        str(entity_id).strip()
                        for entity_id in cfg.get("outputs", []) or []
                        if str(entity_id).strip()
                    }
                )
            for entity_id in outputs:
                configured_owners.setdefault(entity_id, set()).add(level)
            self._humidifier_lane_demand[level] = False
            await self._set_bool(self._humidifier_active_key(level), False)
            lane_details[level] = {
                "level": level,
                "lane": "downstairs" if level == "level1" else "upstairs",
                "outputs": outputs,
                "demand": False,
                "status": "inactive",
                "environmental_state": "inactive",
            }

        output_status: Dict[str, Dict[str, Any]] = {}
        if turn_off_outputs:
            output_status = await self._reconcile_humidifier_outputs(
                {entity_id: set() for entity_id in configured_owners},
                configured_owners=configured_owners,
            )
        self._apply_humidifier_output_truth_to_lanes(lane_details, output_status)
        self._publish_humidifier_truth(lane_details, output_status)

    async def _reconcile_humidifier_outputs(
        self,
        desired_owners: Dict[str, set[str]],
        *,
        configured_owners: Optional[Dict[str, set[str]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        configured = configured_owners or desired_owners
        configured_outputs = sorted(configured)
        for entity_id in set(self._humidifier_output_records) - set(configured_outputs):
            self._cancel_humidifier_retry(entity_id)
            self._humidifier_output_records.pop(entity_id, None)

        now = self._monotonic()
        isolated = self._humidifier_outputs_isolated()
        results: Dict[str, Dict[str, Any]] = {}
        for entity_id in configured_outputs:
            owners = set(desired_owners.get(entity_id, set()))
            all_owners = set(configured.get(entity_id, set()))
            desired_on = bool(owners)
            record = self._humidifier_output_records.setdefault(
                entity_id,
                self._new_humidifier_output_record(),
            )
            observed, platform_action = self._humidifier_observed_state(entity_id)
            record["owners"] = sorted(owners)
            record["configured_owners"] = sorted(all_owners)
            record["domain"] = entity_id.partition(".")[0]
            record["observed"] = observed
            record["platform_action"] = platform_action
            if record.get("desired_on") is None or bool(record.get("desired_on")) != desired_on:
                self._cancel_humidifier_retry(entity_id)
                record["generation"] = int(record.get("generation", 0)) + 1
                record["desired_on"] = desired_on
                record["on_attempts"] = 0
                record["off_attempts"] = 0
                record["fault_latched"] = False
                record["failure_category"] = None
                record["next_allowed_at"] = 0.0
                record["settling_until"] = 0.0
                record["mismatch_started"] = None
                self._record_humidifier_transition(
                    record,
                    "desired_on" if desired_on else "desired_off",
                )

            conflict = self._humidifier_ownership_conflict(entity_id)
            record["ownership_conflict"] = conflict

            if conflict:
                self._cancel_humidifier_retry(entity_id)
                record["failure_category"] = conflict
                record["fault_latched"] = False
                self._set_humidifier_reconciliation_state(
                    record,
                    "degraded",
                    "ownership_conflict",
                )
            elif isolated:
                self._cancel_humidifier_retry(entity_id)
                record["failure_category"] = None
                record["fault_latched"] = False
                self._set_humidifier_reconciliation_state(record, "isolated")
            elif desired_on and observed == "on":
                self._cancel_humidifier_retry(entity_id)
                record["mismatch_started"] = None
                record["failure_category"] = None
                record["fault_latched"] = False
                if platform_action == "idle":
                    state = "platform_idle"
                elif platform_action in {"drying", "off", "unknown"}:
                    state = "degraded"
                    record["failure_category"] = "unexpected_platform_action"
                else:
                    state = "output_on"
                self._set_humidifier_reconciliation_state(record, state, "observed_match")
            elif not desired_on and observed == "off":
                self._cancel_humidifier_retry(entity_id)
                record["mismatch_started"] = None
                record["failure_category"] = None
                record["fault_latched"] = False
                record["on_attempts"] = 0
                record["off_attempts"] = 0
                record["next_allowed_at"] = 0.0
                record["settling_until"] = 0.0
                self._set_humidifier_reconciliation_state(
                    record,
                    "matched_off",
                    "observed_match",
                )
            elif desired_on and observed == "off":
                await self._reconcile_humidifier_mismatch(
                    entity_id,
                    record,
                    desired_on=True,
                    now=now,
                )
            elif not desired_on and observed == "on":
                await self._reconcile_humidifier_mismatch(
                    entity_id,
                    record,
                    desired_on=False,
                    now=now,
                )
            elif not desired_on and observed == "unknown":
                await self._reconcile_unknown_humidifier_off(
                    entity_id,
                    record,
                    now=now,
                )
            else:
                self._cancel_humidifier_retry(entity_id)
                record["failure_category"] = observed
                record["fault_latched"] = False
                state = "unknown" if observed in {"missing", "unknown", "unavailable", "other"} else "degraded"
                self._set_humidifier_reconciliation_state(
                    record,
                    state,
                    f"observed_{observed}",
                )

            results[entity_id] = self._humidifier_output_status(record, now)
        return results

    async def _reconcile_humidifier_mismatch(
        self,
        entity_id: str,
        record: Dict[str, Any],
        *,
        desired_on: bool,
        now: float,
    ) -> None:
        attempts_key = "on_attempts" if desired_on else "off_attempts"
        attempts = int(record.get(attempts_key, 0))
        if record.get("mismatch_started") is None:
            record["mismatch_started"] = now
            self._record_humidifier_transition(record, "mismatch_opened")

        settling_until = float(record.get("settling_until") or 0.0)
        if attempts >= HUMIDIFIER_RECONCILE_MAX_ATTEMPTS:
            if now < settling_until:
                self._schedule_humidifier_retry(entity_id, settling_until)
                state = "retrying" if desired_on else "stopping"
                self._set_humidifier_reconciliation_state(record, state)
                return
            self._cancel_humidifier_retry(entity_id)
            record["fault_latched"] = True
            record["failure_category"] = "retry_exhausted"
            self._set_humidifier_reconciliation_state(
                record,
                "fault_latched",
                "retry_exhausted",
            )
            return

        next_allowed_at = float(record.get("next_allowed_at") or 0.0)
        if now < next_allowed_at:
            self._schedule_humidifier_retry(entity_id, next_allowed_at)
            state = "retrying" if desired_on and attempts > 1 else (
                "requested" if desired_on else "stopping"
            )
            self._set_humidifier_reconciliation_state(record, state)
            return

        attempted, dispatch_result = await self._dispatch_humidifier_output(
            entity_id,
            desired_on,
        )
        record["last_command_intent"] = "turn_on" if desired_on else "turn_off"
        record["last_dispatch_result"] = dispatch_result
        if not attempted:
            self._cancel_humidifier_retry(entity_id)
            record["failure_category"] = dispatch_result
            record["fault_latched"] = False
            self._set_humidifier_reconciliation_state(
                record,
                "degraded",
                dispatch_result,
            )
            return

        record["last_dispatch_utc"] = datetime.now().astimezone().isoformat()
        attempts += 1
        record[attempts_key] = attempts
        record["failure_category"] = (
            "dispatch_exception" if dispatch_result == "exception" else "confirmation_pending"
        )
        record["settling_until"] = now + HUMIDIFIER_RECONCILE_CONFIRM_SECONDS
        if attempts == 1:
            record["next_allowed_at"] = (
                now + HUMIDIFIER_RECONCILE_RETRY_DELAYS_SECONDS[0]
            )
        elif attempts == 2:
            record["next_allowed_at"] = (
                now + HUMIDIFIER_RECONCILE_RETRY_DELAYS_SECONDS[1]
            )
        else:
            record["next_allowed_at"] = record["settling_until"]
        self._record_humidifier_transition(record, dispatch_result)
        self._schedule_humidifier_retry(
            entity_id,
            float(record["next_allowed_at"]),
        )
        state = (
            "retrying"
            if desired_on and dispatch_result == "exception"
            else "requested"
            if desired_on and attempts == 1
            else "retrying"
            if desired_on
            else "stopping"
        )
        self._set_humidifier_reconciliation_state(record, state)

    async def _reconcile_unknown_humidifier_off(
        self,
        entity_id: str,
        record: Dict[str, Any],
        *,
        now: float,
    ) -> None:
        attempts = int(record.get("off_attempts", 0))
        settling_until = float(record.get("settling_until") or 0.0)
        if attempts:
            if now < settling_until:
                self._schedule_humidifier_retry(entity_id, settling_until)
                self._set_humidifier_reconciliation_state(record, "stopping")
            else:
                self._cancel_humidifier_retry(entity_id)
                record["failure_category"] = "confirmation_timeout"
                self._set_humidifier_reconciliation_state(
                    record,
                    "degraded",
                    "unknown_off_unconfirmed",
                )
            return

        attempted, dispatch_result = await self._dispatch_humidifier_output(
            entity_id,
            False,
        )
        record["last_command_intent"] = "turn_off"
        record["last_dispatch_result"] = dispatch_result
        if not attempted:
            record["failure_category"] = dispatch_result
            self._set_humidifier_reconciliation_state(
                record,
                "degraded",
                dispatch_result,
            )
            return

        record["last_dispatch_utc"] = datetime.now().astimezone().isoformat()
        record["off_attempts"] = 1
        record["settling_until"] = now + HUMIDIFIER_RECONCILE_CONFIRM_SECONDS
        record["failure_category"] = (
            "dispatch_exception" if dispatch_result == "exception" else "confirmation_pending"
        )
        self._record_humidifier_transition(record, dispatch_result)
        self._schedule_humidifier_retry(
            entity_id,
            float(record["settling_until"]),
        )
        self._set_humidifier_reconciliation_state(record, "stopping")

    async def _dispatch_humidifier_output(
        self,
        entity_id: str,
        on: bool,
    ) -> Tuple[bool, str]:
        if self._manual_override_active():
            return False, "manual_override"
        domain, separator, _object_id = entity_id.partition(".")
        if not separator or domain not in _HUMIDIFIER_OUTPUT_DOMAINS:
            return False, "unsupported_domain"
        service = "turn_on" if on else "turn_off"
        if not self.hass.services.has_service(domain, service):
            return False, "service_unavailable"

        state = self.hass.states.get(entity_id)
        if state is None:
            return False, "missing"
        state_text = str(getattr(state, "state", "") or "").strip().lower()
        if on and state_text in {"unknown", "unavailable"}:
            return False, state_text
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=False,
            )
        except Exception:
            _LOGGER.exception(
                "HI humidifier output dispatch failed: domain=%s intent=%s",
                domain,
                service,
            )
            return True, "exception"
        return True, "dispatched_unconfirmed"

    def _humidifier_observed_state(self, entity_id: str) -> Tuple[str, str]:
        state = self.hass.states.get(entity_id)
        if state is None:
            return "missing", "not_exposed"
        state_text = str(getattr(state, "state", "") or "").strip().lower()
        if state_text in {"on", "off", "unknown", "unavailable"}:
            observed = state_text
        else:
            observed = "other"

        platform_action = "not_exposed"
        if entity_id.startswith("humidifier."):
            action = str(
                getattr(state, "attributes", {}).get("action") or ""
            ).strip().lower()
            if action in {"humidifying", "idle", "drying", "off"}:
                platform_action = action
            elif action:
                platform_action = "unknown"
        return observed, platform_action

    def _humidifier_ownership_conflict(self, entity_id: str) -> Optional[str]:
        if entity_id in self._configured_non_humidifier_outputs():
            return "cross_family_ownership"
        domain_data = self.hass.data.get(DOMAIN, {})
        if not isinstance(domain_data, dict):
            return None
        for entry_id, runtime_data in domain_data.items():
            if entry_id == self.entry.entry_id or not isinstance(runtime_data, dict):
                continue
            engine = runtime_data.get("automation_engine")
            if not isinstance(engine, HIAutomationEngine) or engine._stopped:
                continue
            if entity_id in engine._configured_humidifier_outputs():
                return "cross_entry_ownership"
        return None

    def _configured_humidifier_outputs(self) -> set[str]:
        outputs: set[str] = set()
        for cfg in self.humidifiers.values():
            if isinstance(cfg, dict):
                outputs.update(
                    str(entity_id).strip()
                    for entity_id in cfg.get("outputs", []) or []
                    if str(entity_id).strip()
                )
        return outputs

    def _configured_non_humidifier_outputs(self) -> set[str]:
        outputs: set[str] = set()
        for section in (self.zones, self.aq):
            for cfg in section.values():
                if isinstance(cfg, dict):
                    outputs.update(
                        str(entity_id).strip()
                        for entity_id in cfg.get("outputs", []) or []
                        if str(entity_id).strip()
                    )
        for alert in self.alerts:
            if not isinstance(alert, dict):
                continue
            power_entity = str(alert.get("power_entity") or "").strip()
            if power_entity:
                outputs.add(power_entity)
        return outputs

    def _notify_other_humidifier_engines(self) -> None:
        domain_data = self.hass.data.get(DOMAIN, {})
        if not isinstance(domain_data, dict):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for runtime_data in domain_data.values():
            if not isinstance(runtime_data, dict):
                continue
            engine = runtime_data.get("automation_engine")
            if (
                isinstance(engine, HIAutomationEngine)
                and engine is not self
                and not engine._stopped
            ):
                loop.create_task(engine.async_request_evaluate())

    def _new_humidifier_output_record(self) -> Dict[str, Any]:
        return {
            "desired_on": None,
            "owners": [],
            "configured_owners": [],
            "domain": None,
            "observed": "missing",
            "platform_action": "not_exposed",
            "generation": 0,
            "on_attempts": 0,
            "off_attempts": 0,
            "settling_until": 0.0,
            "next_allowed_at": 0.0,
            "mismatch_started": None,
            "last_command_intent": "none",
            "last_dispatch_result": "not_requested",
            "last_dispatch_utc": None,
            "failure_category": None,
            "fault_latched": False,
            "ownership_conflict": None,
            "reconciliation": "matched_off",
            "history": [],
            "scheduled_for": None,
        }

    def _set_humidifier_reconciliation_state(
        self,
        record: Dict[str, Any],
        state: str,
        event: Optional[str] = None,
    ) -> None:
        previous = record.get("reconciliation")
        record["reconciliation"] = state
        if previous != state:
            self._record_humidifier_transition(
                record,
                event or f"state_{state}",
            )
            if state in {"degraded", "fault_latched"}:
                _LOGGER.warning(
                    "HI humidifier reconciliation entered %s: entry=%s domain=%s owners=%s failure=%s",
                    state,
                    self.entry.entry_id,
                    record.get("domain") or "unknown",
                    ",".join(record.get("configured_owners") or []) or "none",
                    record.get("failure_category") or "unknown",
                )

    def _record_humidifier_transition(
        self,
        record: Dict[str, Any],
        event: str,
    ) -> None:
        history = record.setdefault("history", [])
        desired_on = record.get("desired_on")
        history.append(
            {
                "event": str(event),
                "desired": (
                    "manual"
                    if desired_on is None
                    else "on"
                    if desired_on
                    else "off"
                ),
                "observed": str(record.get("observed") or "missing"),
                "attempts": int(
                    record.get(
                        "on_attempts" if record.get("desired_on") else "off_attempts",
                        0,
                    )
                ),
            }
        )
        del history[:-HUMIDIFIER_RECONCILE_HISTORY_LIMIT]

    def _schedule_humidifier_retry(self, entity_id: str, when: float) -> None:
        if self._stopped:
            return
        record = self._humidifier_output_records.get(entity_id)
        existing = self._humidifier_retry_tasks.get(entity_id)
        if (
            existing
            and not existing.done()
            and record
            and record.get("scheduled_for") == when
        ):
            return
        self._cancel_humidifier_retry(entity_id)
        if record is not None:
            record["scheduled_for"] = when

        async def _wake() -> None:
            try:
                delay = max(0.0, when - self._monotonic())
                await asyncio.sleep(delay)
                if not self._stopped:
                    await self.async_request_evaluate()
            except asyncio.CancelledError:
                return
            finally:
                current = self._humidifier_retry_tasks.get(entity_id)
                if current is asyncio.current_task():
                    self._humidifier_retry_tasks.pop(entity_id, None)
                current_record = self._humidifier_output_records.get(entity_id)
                if current_record and current_record.get("scheduled_for") == when:
                    current_record["scheduled_for"] = None

        self._humidifier_retry_tasks[entity_id] = asyncio.create_task(_wake())

    def _cancel_humidifier_retry(self, entity_id: str) -> None:
        task = self._humidifier_retry_tasks.pop(entity_id, None)
        if (
            task
            and not task.done()
            and task is not asyncio.current_task()
        ):
            task.cancel()
        record = self._humidifier_output_records.get(entity_id)
        if record is not None:
            record["scheduled_for"] = None

    def _monotonic(self) -> float:
        return time.monotonic()

    def _humidifier_output_status(
        self,
        record: Dict[str, Any],
        now: float,
    ) -> Dict[str, Any]:
        mismatch_started = record.get("mismatch_started")
        mismatch_age = None
        if isinstance(mismatch_started, (int, float)):
            mismatch_age = max(0, int(now - mismatch_started))
        desired_on = record.get("desired_on")
        attempts_key = "on_attempts" if desired_on else "off_attempts"
        return {
            "domain": record.get("domain"),
            "owners": list(record.get("owners") or []),
            "configured_owners": list(record.get("configured_owners") or []),
            "desired": (
                "manual"
                if desired_on is None
                else "on"
                if desired_on
                else "off"
            ),
            "observed": record.get("observed"),
            "platform_action": record.get("platform_action"),
            "reconciliation": record.get("reconciliation"),
            "dispatch_result": record.get("last_dispatch_result"),
            "last_command_intent": record.get("last_command_intent"),
            "last_dispatch_utc": record.get("last_dispatch_utc"),
            "attempts": int(record.get(attempts_key, 0)),
            "maximum_attempts": HUMIDIFIER_RECONCILE_MAX_ATTEMPTS,
            "mismatch_age_seconds": mismatch_age,
            "failure_category": record.get("failure_category"),
            "fault_latched": bool(record.get("fault_latched")),
            "ownership_conflict": record.get("ownership_conflict"),
            "history": [dict(item) for item in record.get("history", [])],
        }

    def _apply_humidifier_output_truth_to_lanes(
        self,
        lane_details: Dict[str, Dict[str, Any]],
        output_status: Dict[str, Dict[str, Any]],
    ) -> None:
        priority = {
            "fault_latched": 0,
            "degraded": 1,
            "unknown": 2,
            "isolated": 3,
            "manual_hold": 4,
            "retrying": 5,
            "stopping": 6,
            "requested": 7,
            "platform_idle": 8,
            "output_on": 9,
            "matched_off": 10,
        }
        for detail in lane_details.values():
            outputs = detail.get("outputs", []) or []
            statuses = [
                output_status[entity_id]
                for entity_id in outputs
                if entity_id in output_status
            ]
            if not statuses:
                detail.setdefault("reconciliation", "inactive")
                detail.setdefault("observed", "missing" if outputs else "not_configured")
                detail.setdefault("platform_action", "not_exposed")
                continue

            lane_truth_is_degraded = detail.get("reconciliation") in {
                "degraded",
                "unknown",
            }
            if not lane_truth_is_degraded:
                if not detail.get("demand") and any(
                    status.get("desired") == "on" for status in statuses
                ):
                    detail["reconciliation"] = "inactive_shared_output"
                else:
                    detail["reconciliation"] = min(
                        (
                            str(status.get("reconciliation") or "degraded")
                            for status in statuses
                        ),
                        key=lambda value: priority.get(value, 1),
                    )
            detail["observed"] = _aggregate_humidifier_status_value(
                statuses,
                "observed",
            )
            detail["platform_action"] = _aggregate_humidifier_status_value(
                statuses,
                "platform_action",
            )

    def _publish_humidifier_truth(
        self,
        lane_details: Dict[str, Dict[str, Any]],
        output_status: Dict[str, Dict[str, Any]],
    ) -> None:
        runtime_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self.entry.entry_id,
            {},
        )
        public_lanes: Dict[str, Dict[str, Any]] = {}
        for level in ("level1", "level2"):
            detail = lane_details.get(level)
            if not isinstance(detail, dict):
                continue
            public_lanes[level] = {
                "demand": "requested" if detail.get("demand") else "inactive",
                "environmental_state": detail.get("environmental_state", "inactive"),
                "reconciliation": detail.get("reconciliation", "inactive"),
                "observed": detail.get("observed", "not_configured"),
                "platform_action": detail.get("platform_action", "not_exposed"),
                "output_count": len(detail.get("outputs", []) or []),
                "failure_category": detail.get("failure_category"),
            }

        active_states = [
            str(lane.get("reconciliation") or "inactive")
            for lane in public_lanes.values()
            if lane.get("demand") == "requested"
            or lane.get("reconciliation") in {
                "stopping",
                "fault_latched",
                "degraded",
                "unknown",
                "manual_hold",
            }
        ]
        overall_priority = (
            "fault_latched",
            "degraded",
            "unknown",
            "isolated",
            "manual_hold",
            "retrying",
            "stopping",
            "requested",
            "platform_idle",
            "output_on",
        )
        overall = "inactive"
        for candidate in overall_priority:
            if candidate in active_states:
                overall = candidate
                break

        runtime_data["humidifier_status"] = {
            "schema": 1,
            "overall": overall,
            "lanes": public_lanes,
        }

        public_outputs: Dict[str, Dict[str, Any]] = {}
        for index, entity_id in enumerate(sorted(output_status), start=1):
            public_outputs[f"output_{index}"] = dict(output_status[entity_id])
        runtime_data["humidifier_reconciliation"] = {
            "schema": 1,
            "summary": {
                "requested_lanes": sum(
                    lane.get("demand") == "requested"
                    for lane in public_lanes.values()
                ),
                "degraded_lanes": sum(
                    lane.get("reconciliation") == "degraded"
                    for lane in public_lanes.values()
                ),
                "unknown_lanes": sum(
                    lane.get("environmental_state") == "unknown"
                    or lane.get("reconciliation") == "unknown"
                    for lane in public_lanes.values()
                ),
                "matched_outputs": sum(
                    output.get("reconciliation") in {"output_on", "platform_idle", "matched_off"}
                    for output in public_outputs.values()
                ),
                "retrying_outputs": sum(
                    output.get("reconciliation") in {"requested", "retrying", "stopping"}
                    for output in public_outputs.values()
                ),
                "faulted_outputs": sum(
                    output.get("reconciliation") == "fault_latched"
                    for output in public_outputs.values()
                ),
                "degraded_outputs": sum(
                    output.get("reconciliation") == "degraded"
                    for output in public_outputs.values()
                ),
                "unknown_outputs": sum(
                    output.get("reconciliation") == "unknown"
                    for output in public_outputs.values()
                ),
                "isolated_outputs": sum(
                    output.get("reconciliation") == "isolated"
                    for output in public_outputs.values()
                ),
                "manual_hold_outputs": sum(
                    output.get("reconciliation") == "manual_hold"
                    for output in public_outputs.values()
                ),
                "ownership_conflicts": sum(
                    bool(output.get("ownership_conflict"))
                    for output in public_outputs.values()
                ),
            },
            "outputs": public_outputs,
        }

    async def _deactivate_aq_activity(
        self,
        *,
        set_fan_auto: bool,
        exclude_outputs: Optional[List[str]] = None,
    ) -> None:
        excluded = set(exclude_outputs or [])
        cancelled_tasks: List[asyncio.Task[Any]] = []
        for level, task in list(self._aq_tasks.items()):
            if (
                task
                and not task.done()
                and task is not asyncio.current_task()
            ):
                task.cancel()
                cancelled_tasks.append(task)
            self._aq_tasks.pop(level, None)
        if cancelled_tasks:
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)

        for cfg in self.aq.values():
            outputs = cfg.get("outputs", [])
            if set_fan_auto:
                outputs = [entity_id for entity_id in outputs if entity_id not in excluded]
                await self._set_fan_outputs_auto(outputs)
        self._aq_trigger_active = {}
        await self._set_bool("air_aq_upstairs_active", False)
        await self._set_bool("air_aq_downstairs_active", False)
        await self._clear_timer("air_aq_upstairs_run")
        await self._clear_timer("air_aq_downstairs_run")

    async def _clear_alert_activity_switches(self) -> None:
        await self._sync_alert_activity_switches({})

    async def _clear_alert_runtime_state(self) -> None:
        await self._clear_alert_activity_switches()
        self._active_alert_identity = None
        self._record_alert_resolution([])

    async def _sync_alert_activity_switches(self, states: Dict[int, bool]) -> None:
        for idx in range(max(len(self.alerts), 5)):
            await self._set_bool(self._alert_switch_key(idx), bool(states.get(idx, False)))

    async def _cancel_aq_task(self, level: str) -> None:
        task = self._aq_tasks.pop(level, None)
        if task and not task.done():
            task.cancel()
        self._aq_trigger_active[level] = False

    def _alert_switch_key(self, idx: int) -> str:
        return f"air_alert_{idx + 1}_active"

    def _alert_label(
        self,
        idx: int,
        alert: Dict[str, Any],
        *,
        resolved_room: Optional[str] = None,
    ) -> str:
        trigger_type = str(alert.get("trigger_type") or "unknown")
        trigger_label = ALERT_TRIGGER_DEFS.get(trigger_type, {}).get(
            "label",
            trigger_type.replace("_", " ").title(),
        )
        threshold = alert.get("threshold")
        threshold_suffix = ""
        if trigger_type == "humidity_danger":
            profile = self._active_target_profile()
            threshold_suffix = f" @ active {profile.label} high-risk {profile.high_risk:g}"
        elif threshold not in (None, "") and trigger_type == "co_emergency":
            default_threshold = (
                float(CO_EMERGENCY_START)
            )
            threshold = _safe_alert_threshold(trigger_type, threshold, default_threshold)
            threshold_suffix = f" @ {threshold}"
        room_scope = resolved_room or self._alert_room_scope(alert)
        room_suffix = f" in {room_scope}" if room_scope else ""
        return f"Alert {idx + 1}: {trigger_label}{threshold_suffix}{room_suffix}"

    def _alert_room_scope(self, alert: Dict[str, Any]) -> Optional[str]:
        trigger_type = str(alert.get("trigger_type") or "")
        if trigger_type not in ROOM_SCOPED_ALERT_TRIGGERS:
            return None
        raw = str(alert.get("room") or "").strip()
        if not raw:
            return None
        raw_key = raw.lower()
        for item in self.telemetry:
            room = str(item.get("room") or "").strip()
            if not room:
                continue
            if room.lower() == raw_key:
                return room
        return raw

    def _room_condensation_danger(self, room: str) -> bool:
        rh = self._rooms_avg("humidity", [room])
        temp = self._rooms_avg("temperature", [room])
        if rh is None or temp is None:
            _LOGGER.debug(
                "Room-scoped condensation alert skipped for %s: missing humidity/temperature telemetry.",
                room,
            )
            return False
        dp = _dew_point(temp, rh)
        if dp is None:
            return False
        spread = temp - dp
        profile = self._active_target_profile()
        return seasonal_condensation_risk(spread, profile) == "Danger"

    def _room_mould_danger(self, room: str) -> bool:
        rh = self._rooms_avg("humidity", [room])
        temp = self._rooms_avg("temperature", [room])
        if rh is None or temp is None:
            _LOGGER.debug(
                "Room-scoped mould alert skipped for %s: missing humidity/temperature telemetry.",
                room,
            )
            return False
        dp = _dew_point(temp, rh)
        if dp is None:
            return False
        spread = temp - dp
        profile = self._active_target_profile()
        return seasonal_mould_level(rh, spread, profile) >= 3

    def _matching_humidity_sensor(
        self,
        threshold: float,
        room_scope: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        matches: List[Tuple[str, str, float]] = []
        room_filter = room_scope.lower().strip() if room_scope else None
        for item in self.telemetry:
            if item.get("sensor_type") != "humidity":
                continue
            room = str(item.get("room") or "").strip()
            if room_filter and room.lower() != room_filter:
                continue
            entity_id = item.get("entity_id")
            value = _get_float(self.hass, entity_id, sensor_type="humidity")
            if entity_id and room and value is not None and value >= threshold:
                matches.append((entity_id, room, value))
        if not matches:
            return None
        return max(matches, key=lambda item: item[2])

    def _matching_condensation_room(
        self,
        severity: str,
        room_scope: Optional[str],
    ) -> Optional[_AlertMatch]:
        profile = self._active_target_profile()
        target_rank = _RISK_ORDER.get(severity, 2)
        threshold = (
            profile.condensation_danger_spread
            if severity == "Danger"
            else profile.condensation_risk_spread
        )
        candidates: List[Tuple[int, float, str, Optional[str], float]] = []
        for room, sensors in _room_map(self.telemetry).items():
            if room_scope and room.lower().strip() != room_scope.lower().strip():
                continue
            rh = _get_float(self.hass, sensors.get("humidity"), sensor_type="humidity")
            temp = _get_float(self.hass, sensors.get("temperature"), sensor_type="temperature")
            if rh is None or temp is None:
                _LOGGER.debug(
                    "Condensation alert skipped for %s: missing humidity/temperature telemetry.",
                    room,
                )
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spread = temp - dp
            risk = seasonal_condensation_risk(spread, profile)
            rank = _RISK_ORDER.get(risk, -1)
            if rank >= target_rank:
                candidates.append(
                    (rank, -spread, room, sensors.get("humidity"), spread)
                )
        if not candidates:
            return None
        _rank, _spread_rank, room, sensor, spread = max(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        return _AlertMatch(
            room=room,
            sensor=sensor,
            measured=round(spread, 1),
            threshold=threshold,
            unit="degC",
            comparison="at_or_below",
            profile_label=profile.label,
        )

    def _matching_mould_room(
        self,
        severity: str,
        room_scope: Optional[str],
    ) -> Optional[_AlertMatch]:
        profile = self._active_target_profile()
        target_rank = _RISK_ORDER.get(severity, 2)
        candidates: List[Tuple[int, float, str, Optional[str]]] = []
        for room, sensors in _room_map(self.telemetry).items():
            if room_scope and room.lower().strip() != room_scope.lower().strip():
                continue
            rh = _get_float(self.hass, sensors.get("humidity"), sensor_type="humidity")
            temp = _get_float(self.hass, sensors.get("temperature"), sensor_type="temperature")
            if rh is None or temp is None:
                _LOGGER.debug(
                    "Mould alert skipped for %s: missing humidity/temperature telemetry.",
                    room,
                )
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spread = temp - dp
            risk = seasonal_mould_level(rh, spread, profile)
            if risk >= target_rank:
                candidates.append((risk, rh, room, sensors.get("humidity")))
        if not candidates:
            return None
        risk, _rh, room, sensor = max(candidates, key=lambda item: (item[0], item[1]))
        return _AlertMatch(
            room=room,
            sensor=sensor,
            measured=float(risk),
            threshold=float(target_rank),
            unit="risk_level",
            comparison="at_or_above",
            profile_label=profile.label,
        )

    def _zone_for_room(self, room: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not room:
            return None, None
        room_key = room.lower().strip()
        matches: List[Tuple[int, str, Dict[str, Any]]] = []
        for zone_key, zone in self.zones.items():
            if not isinstance(zone, dict) or not zone.get("enabled"):
                continue
            rooms = [str(item).lower().strip() for item in zone.get("rooms", []) or []]
            if room_key in rooms:
                matches.append((_zone_priority(zone_key), zone_key, zone))
        if not matches:
            return None, None
        matches.sort(key=lambda item: item[0])
        if len(matches) > 1:
            _LOGGER.debug(
                "HI alert room-zone ambiguity for %s resolved to %s by zone priority.",
                room,
                matches[0][1],
            )
        return matches[0][1], matches[0][2]

    def _build_runtime_reason(
        self,
        *,
        runtime_mode: str,
        alert_labels: List[Any],
        zone1_active: bool,
        zone2_active: bool,
        aq_active: bool,
        zone1_detail: Optional[Dict[str, Any]],
        zone2_detail: Optional[Dict[str, Any]],
        aq_details: List[Dict[str, Any]],
        humidifier_details: List[Dict[str, Any]],
    ) -> str:
        base_reason = ""
        if runtime_mode == "alert" and alert_labels:
            base_reason = self._format_alert_detail(alert_labels)
        elif runtime_mode == "cooking":
            if zone1_detail:
                zone_label = zone1_detail.get("ui_label") or "Zone 1"
                base_reason = self._format_zone_detail(zone1_detail, str(zone_label))
            else:
                base_reason = "Zone 1 extraction is active."
        elif runtime_mode == "bathroom":
            if zone2_detail:
                zone_label = zone2_detail.get("ui_label") or "Zone 2"
                base_reason = self._format_zone_detail(zone2_detail, str(zone_label))
            else:
                base_reason = "Zone 2 extraction is active."
        elif runtime_mode == "air_quality" and aq_active:
            base_reason = self._format_aq_detail(aq_details)
        else:
            house_humidity = self._level_avg("humidity", None)
            if house_humidity is not None:
                lane_text = (
                    "no ventilation lane currently needs to run"
                    if humidifier_details
                    else "no lane currently needs to run"
                )
                base_reason = (
                    "System is armed and monitoring telemetry. "
                    f"Current house humidity is {house_humidity:.1f}% and {lane_text}."
                )
            else:
                lane_text = (
                    "No ventilation lane currently needs to run."
                    if humidifier_details
                    else "No automation lane currently needs to run."
                )
                base_reason = f"System is armed and monitoring telemetry. {lane_text}"

        notices: List[str] = []
        humidifier_reason = self._format_humidifier_detail(humidifier_details) if humidifier_details else ""
        if humidifier_reason:
            notices.append(humidifier_reason)
        if runtime_mode != "alert":
            alert_notice = self._format_nonblocking_alert_notice(alert_labels)
            if alert_notice:
                notices.append(alert_notice)
        if notices:
            return f"{base_reason} {' '.join(notices)}".strip()
        return base_reason

    def _control_lock_display_facts(self, kind: str) -> ReasonFacts:
        if kind == "manual_override":
            headline = "Manual control is active"
            family = "manual"
            variant = "manual_override"
            lines = [
                ReasonLine(
                    "why",
                    "system",
                    "control.manual_override_active",
                    "blocked",
                    "HI leaves fans, switches, humidifiers, and alert lights as they are.",
                ),
                ReasonLine(
                    "action",
                    "system",
                    "control.manual_authority",
                    "blocked",
                    "Control stays with you or another automation until Manual is turned off. CO emergency protection can still run configured ventilation at full speed.",
                ),
            ]
        else:
            headline = "Automatic control disabled"
            family = "disabled"
            variant = "control_disabled"
            lines = [
                ReasonLine(
                    "why",
                    "system",
                    "control.automatic_disabled",
                    "blocked",
                    "HI is not making automatic control decisions.",
                ),
            ]
        lines.extend(self._humidifier_display_lines([]))
        lines.extend(self._isolation_display_lines())
        return self._make_reason_facts(
            family,
            variant,
            "hold",
            headline,
            lines,
        )

    def _gate_display_facts(self, status: _GateStatus, *, action: str) -> ReasonFacts:
        lines: List[ReasonLine] = []
        attention = "hold"
        variant = status.presentation_variant or "global_gate"
        if status.kind == "time":
            headline = "Time gate active"
            window = f"{status.window_start or 'configured start'}–{status.window_end or 'configured end'}"
            lines.append(
                ReasonLine(
                    "why",
                    "system",
                    "gate.time_outside_window",
                    "observed",
                    f"The current time is outside the configured {window} window.",
                    {
                        "start": status.window_start or "configured",
                        "end": status.window_end or "configured",
                    },
                )
            )
        elif status.presentation_variant == "presence_unavailable":
            headline = "Presence status unavailable"
            attention = "degraded"
            if status.unavailable_count == status.configured_count:
                why = "All configured presence sources are unknown or unavailable."
            else:
                why = (
                    "No configured presence source currently reports present, and the "
                    "available evidence is incomplete."
                )
            lines.extend(
                [
                    ReasonLine(
                        "why",
                        "system",
                        "gate.presence_unavailable",
                        "unavailable",
                        why,
                        {
                            "configured_count": status.configured_count,
                            "unavailable_count": status.unavailable_count,
                            "unrecognized_count": status.other_count,
                        },
                    ),
                    ReasonLine(
                        "notice",
                        "system",
                        "gate.occupancy_not_confirmed",
                        "not_confirmed",
                        "Occupancy cannot be confirmed.",
                    ),
                ]
            )
        else:
            headline = "Presence gate active"
            lines.append(
                ReasonLine(
                    "why",
                    "system",
                    "gate.presence_no_present_source",
                    "observed",
                    "All configured presence sources explicitly report away.",
                    {"configured_count": status.configured_count},
                )
            )

        if action == "safe_state":
            if self._fan_outputs_isolated() or self._humidifier_outputs_isolated():
                action_text = (
                    "Automatic control is blocked. Output isolation is on, so HI did "
                    "not send the affected reset commands."
                )
                action_truth = "blocked"
            else:
                action_text = (
                    "Automatic control is blocked; HI selected the configured gate "
                    "output reset."
                )
                action_truth = "selected"
            action_code = "gate.output_reset_selected"
        else:
            action_text = "The gate path made no new output changes."
            action_truth = "blocked"
            action_code = "gate.no_output_change"
        lines.append(
            ReasonLine(
                "action",
                "ventilation",
                action_code,
                action_truth,
                action_text,
            )
        )
        lines.extend(self._humidifier_display_lines([]))
        lines.extend(self._isolation_display_lines(include_fan=False))
        return self._make_reason_facts(
            "gate",
            variant,
            attention,
            headline,
            lines,
        )

    def _pause_display_facts(self) -> ReasonFacts:
        lines = [
            ReasonLine(
                "why",
                "system",
                    "pause.automatic_control_paused",
                    "blocked",
                    "Automatic control is paused.",
            ),
            ReasonLine(
                "next",
                "system",
                "pause.timer_end_reassessment",
                "blocked",
                "Pause remains active until the pause timer ends.",
            ),
        ]
        lines.extend(self._humidifier_display_lines([]))
        lines.extend(self._isolation_display_lines())
        return self._make_reason_facts(
            "pause",
            "active",
            "hold",
            "Automatic control paused",
            lines,
        )

    def _telemetry_display_facts(self, missing: List[str]) -> ReasonFacts:
        labels = [sanitize_display_label(item) for item in missing]
        labels = [item for item in labels if item]
        missing_text = " and ".join(labels) or "required"
        lines = [
            ReasonLine(
                "why",
                "system",
                "telemetry.required_unavailable",
                "unavailable",
                f"Required {missing_text} telemetry is unavailable.",
                {"missing_count": len(missing)},
            ),
            ReasonLine(
                "action",
                "system",
                "telemetry.lower_lanes_not_evaluated",
                "blocked",
                "HI did not continue with zone, alert, air-quality, or humidifier decisions.",
            ),
        ]
        lines.extend(self._humidifier_display_lines([]))
        lines.extend(self._isolation_display_lines())
        return self._make_reason_facts(
            "telemetry",
            "required_unavailable",
            "degraded",
            "Required telemetry unavailable",
            lines,
        )

    def _co_display_facts(self) -> ReasonFacts:
        start_threshold, clear_threshold, outputs = self._co_emergency_settings()
        co_values = self._collect_values("co")
        lines: List[ReasonLine] = []
        if co_values:
            maximum = max(co_values)
            lines.append(
                ReasonLine(
                    "why",
                    "safety",
                    "co.reading_above_threshold",
                    "observed",
                    (
                        f"The highest configured CO reading is {maximum:g} ppm, at or "
                        f"above the {start_threshold:g} ppm threshold."
                    ),
                    {
                        "measured": maximum,
                        "threshold": start_threshold,
                        "unit": "ppm",
                    },
                )
            )
        output_summary = self._presentation_output_summary(
            outputs,
            generic="configured emergency ventilation output",
        )
        if self._fan_outputs_isolated():
            lines.append(
                ReasonLine(
                    "action",
                    "safety",
                    "co.output_isolated",
                    "blocked",
                    (
                        "Fan-output isolation is active, so HI is not sending emergency "
                        "ventilation commands to Home Assistant."
                    ),
                )
            )
        elif not outputs:
            lines.append(
                ReasonLine(
                    "action",
                    "safety",
                    "co.output_unmapped",
                    "unmapped",
                    "No configured emergency ventilation output is available for selection.",
                )
            )
        else:
            lines.append(
                ReasonLine(
                    "action",
                    "safety",
                    "co.output_level_selected",
                    "selected",
                    f"HI selected 100% for {output_summary}.",
                    {"level": 100, "output_count": len(outputs)},
                )
            )
        lines.append(
            ReasonLine(
                "next",
                "safety",
                "co.clear_hold",
                "selected",
                (
                    f"Valid CO readings must remain below {clear_threshold:g} ppm for "
                    "two minutes before HI clears this response."
                ),
                {"clear_threshold": clear_threshold, "hold_minutes": 2},
            )
        )
        lines.extend(self._humidifier_display_lines([]))
        lines.extend(self._isolation_display_lines(include_fan=False))
        return self._make_reason_facts(
            "co_emergency",
            "threshold_active",
            "critical",
            "Carbon monoxide emergency lane selected",
            lines,
        )

    def _runtime_display_facts(
        self,
        *,
        runtime_mode: str,
        alert_details: List[Any],
        zone_detail: Optional[Dict[str, Any]],
        aq_details: List[Dict[str, Any]],
        humidifier_details: List[Dict[str, Any]],
    ) -> ReasonFacts:
        if runtime_mode == "alert" and alert_details:
            family = "alert"
            attention = "critical"
            headline, variant, lines = self._alert_display_content(alert_details)
        elif runtime_mode in {"cooking", "bathroom", "zone"} and zone_detail:
            family = "zone"
            attention = "active"
            variant = str(zone_detail.get("zone_key") or "selected")
            zone_label = self._presentation_label(
                zone_detail.get("ui_label"),
                "Configured zone",
            )
            headline = f"{zone_label} response lane selected"
            lines = self._zone_display_lines(zone_detail)
        elif runtime_mode == "air_quality" and aq_details:
            family = "air_quality"
            attention = "active"
            variant = (
                "trigger_active"
                if any(detail.get("trigger_active") for detail in aq_details)
                else "run_window_active"
            )
            headline = "Air quality response lane selected"
            lines = self._aq_display_lines(aq_details)
        elif self.alert_only_mode:
            family = "normal"
            attention = "neutral"
            variant = "alert_only_monitoring"
            headline = "Monitoring alerts"
            lines = [
                ReasonLine(
                    "why",
                    "system",
                    "normal.alert_only_monitoring",
                    "selected",
                    (
                        "Monitor + Alerts Only mode is active; HI is monitoring alerts "
                        "without automatic zone, air-quality, or humidifier output control."
                    ),
                )
            ]
        else:
            family = "normal"
            attention = "neutral"
            variant = "monitoring"
            headline = "Monitoring"
            lines = [
                ReasonLine(
                    "why",
                    "system",
                    "normal.no_higher_priority_lane",
                    "selected",
                    "HI is monitoring, and no ventilation response is selected.",
                )
            ]

        degraded = [
            item
            for item in alert_details
            if isinstance(item, dict) and not _alert_can_control(item)
        ]
        if degraded:
            if attention == "neutral":
                attention = "degraded"
                variant = "monitoring_with_degraded_alert"
                headline = "Monitoring with limited alert response"
            lines.append(
                ReasonLine(
                    "notice",
                    "safety",
                    "alert.degraded_candidate_not_selected",
                    "unmapped",
                    (
                        "Another active alert has no usable zone-output mapping, so HI "
                        "did not select an automatic boost for it."
                    ),
                    {"candidate_count": len(degraded)},
                )
            )
        lines.extend(self._humidifier_display_lines(humidifier_details))
        lines.extend(self._isolation_display_lines(include_fan=family == "normal"))
        return self._make_reason_facts(
            family,
            variant,
            attention,
            headline,
            lines,
        )

    def _zone_display_lines(self, detail: Dict[str, Any]) -> List[ReasonLine]:
        lines = [
            self._trigger_display_line("zone", fact)
            for fact in tuple(detail.get("trigger_facts") or ())[:2]
            if isinstance(fact, _TriggerFact)
        ]
        zone_label = self._presentation_label(
            detail.get("ui_label"),
            "the configured zone",
            maximum=40,
        )
        output_level = _fan_level_text(detail.get("output_level"))
        outputs = list(detail.get("outputs") or [])
        output_summary = self._presentation_output_summary(
            outputs,
            generic="configured zone ventilation output",
        )
        action_text = (
            f"So for {zone_label}, HI selected {output_level} for {output_summary}."
        )
        if len(action_text) > DISPLAY_REASON_MAX_LINE_TEXT:
            output_summary = (
                f"{len(outputs)} configured zone ventilation outputs"
                if len(outputs) > 1
                else "configured zone ventilation output"
            )
            action_text = (
                f"So for {zone_label}, HI selected {output_level} for "
                f"{output_summary}."
            )
        if self._fan_outputs_isolated():
            lines.append(
                ReasonLine(
                    "action",
                    "ventilation",
                    "zone.output_isolated",
                    "blocked",
                    (
                        "Fan-output isolation is active, so HI is not sending zone "
                        "ventilation commands to Home Assistant."
                    ),
                )
            )
        else:
            lines.append(
                ReasonLine(
                    "action",
                    "ventilation",
                    "zone.output_level_selected",
                    "selected",
                    action_text,
                    {"output_count": len(outputs), "output_level": output_level},
                )
            )
        return lines

    def _aq_display_lines(self, details: List[Dict[str, Any]]) -> List[ReasonLine]:
        lines: List[ReasonLine] = []
        ordered_details = sorted(
            details,
            key=lambda detail: {
                "level1": 0,
                "level2": 1,
            }.get(str(detail.get("level") or ""), 2),
        )
        for detail in ordered_details[:2]:
            level_label = self._presentation_level_label(detail.get("level"))
            facts = [
                fact
                for fact in tuple(detail.get("trigger_facts") or ())
                if isinstance(fact, _TriggerFact)
            ]
            if facts:
                line = self._trigger_display_line("air_quality", facts[0])
                lines.append(
                    ReasonLine(
                        line.role,
                        line.scope,
                        line.code,
                        line.truth,
                        f"{level_label} {line.text}",
                        line.args,
                    )
                )
            else:
                lines.append(
                    ReasonLine(
                        "why",
                        "ventilation",
                        "air_quality.run_window_active",
                        "selected",
                        (
                            f"{level_label} air-quality response remains selected while "
                            "its run window is active."
                        ),
                    )
                )
            outputs = list(detail.get("outputs") or [])
            output_level = _fan_level_text(detail.get("output_level"))
            output_summary = self._presentation_output_summary(
                outputs,
                generic="configured air-quality ventilation output",
            )
            if self._fan_outputs_isolated():
                action_text = (
                    f"For {level_label}, fan-output isolation is preventing HI from "
                    "changing the air-quality ventilation outputs."
                )
                truth = "blocked"
                code = "air_quality.output_isolated"
            else:
                if facts:
                    action_text = (
                        f"So for {level_label}, HI selected {output_level} for "
                        f"{output_summary}."
                    )
                else:
                    action_text = (
                        f"For {level_label}, HI keeps {output_level} selected for "
                        f"{output_summary} while the run window remains active."
                    )
                if len(action_text) > DISPLAY_REASON_MAX_LINE_TEXT:
                    if len(outputs) > 1:
                        output_summary = (
                            f"{len(outputs)} configured air-quality ventilation outputs"
                        )
                    elif outputs:
                        output_summary = (
                            "the configured air-quality ventilation output"
                        )
                    else:
                        output_summary = "configured air-quality ventilation output"
                    if facts:
                        action_text = (
                            f"So for {level_label}, HI selected {output_level} for "
                            f"{output_summary}."
                        )
                    else:
                        action_text = (
                            f"For {level_label}, HI keeps {output_level} selected for "
                            f"{output_summary} while the run window remains active."
                        )
                truth = "selected"
                code = "air_quality.output_level_selected"
            lines.append(
                ReasonLine(
                    "action",
                    "ventilation",
                    code,
                    truth,
                    action_text,
                    {"output_count": len(outputs), "output_level": output_level},
                )
            )
        return lines

    def _alert_display_content(
        self,
        details: List[Any],
    ) -> Tuple[str, str, List[ReasonLine]]:
        selected = details[0] if details and isinstance(details[0], dict) else {}
        alert_type = str(selected.get("alert_type") or "alert")
        severity = str(selected.get("severity") or "active")
        variant = str(selected.get("trigger_type") or "selected")
        if variant.startswith("humidity_"):
            headline = "High humidity alert lane selected"
        elif variant.startswith("mould_"):
            headline = "Mould alert lane selected"
        elif variant.startswith("condensation_"):
            headline = "Condensation alert lane selected"
        else:
            headline = f"{alert_type.title()} alert lane selected"
        lines: List[ReasonLine] = []
        measured = _to_float(selected.get("measured_value"))
        threshold = _to_float(selected.get("threshold"))
        room = self._presentation_label(
            selected.get("room"),
            "",
            maximum=40,
        )
        measurement_room = room or "the affected room"
        if measured is not None and threshold is not None:
            profile_value = selected.get("profile_label") or selected.get(
                "_display_profile_label"
            )
            profile = self._presentation_label(
                profile_value,
                "current",
                maximum=32,
            )
            if variant.startswith("condensation_"):
                measurement_text = (
                    f"{severity} alert: the dew-point gap in {measurement_room} is {measured:.1f}°C, "
                    f"at or below the {profile} {severity} point of {threshold:g}°C."
                )
                unit = "degC"
                measurement_code = "alert.measurement_at_or_below_threshold"
            elif variant.startswith("mould_"):
                measured_range = _risk_range_label(measured)
                threshold_range = _risk_range_label(threshold, fallback=severity)
                if measured > threshold:
                    measurement_text = (
                        f"{severity} alert: mould conditions in {measurement_room} are in the "
                        f"{measured_range} range for the {profile} profile; this "
                        f"response starts at {threshold_range}."
                    )
                else:
                    measurement_text = (
                        f"{severity} alert: mould conditions in {measurement_room} have reached "
                        f"the {measured_range} range for the {profile} profile."
                    )
                unit = "risk_level"
                measurement_code = "alert.measurement_at_or_above_threshold"
            else:
                measurement_text = (
                    f"Danger alert: humidity in {measurement_room} is {measured:.1f}%, at or above "
                    f"the high-risk threshold of {threshold:g}% for the active {profile} profile."
                )
                unit = "%"
                measurement_code = "alert.measurement_at_or_above_threshold"
            lines.append(
                ReasonLine(
                    "why",
                    "safety",
                    measurement_code,
                    "observed",
                    measurement_text,
                    {
                        "comparison": selected.get("comparison") or "at_or_above",
                        "measured": measured,
                        "threshold": threshold,
                        "unit": unit,
                    },
                )
            )
        zone = self._presentation_label(selected.get("zone"), "", maximum=40)
        if room or zone:
            if room and zone:
                source_text = f"{room} is assigned to {zone} for this response."
            elif room:
                source_text = f"This alert comes from {room}."
            else:
                source_text = f"This alert is assigned to {zone}."
            lines.append(
                ReasonLine(
                    "why",
                    "safety",
                    "alert.source_resolved",
                    "observed",
                    source_text,
                )
            )
        outputs = list(selected.get("outputs") or [])
        if outputs and selected.get("boost_level"):
            level = _fan_level_text(selected.get("boost_level"))
            output_summary = self._presentation_output_summary(
                outputs,
                generic="configured alert ventilation output",
            )
            if self._fan_outputs_isolated():
                text = (
                    "Fan-output isolation is active, so HI is not sending alert "
                    "ventilation commands to Home Assistant."
                )
                truth = "blocked"
                code = "alert.output_isolated"
            else:
                text = f"For this alert, HI selected {level} for {output_summary}."
                truth = "selected"
                code = "alert.output_level_selected"
            lines.append(
                ReasonLine(
                    "action",
                    "ventilation",
                    code,
                    truth,
                    text,
                    {"output_count": len(outputs), "output_level": level},
                )
            )
        else:
            lines.append(
                ReasonLine(
                    "action",
                    "ventilation",
                    "alert.output_unmapped",
                    "unmapped",
                    (
                        "HI could not select an automatic alert boost because no usable "
                        "zone-output mapping is available."
                    ),
                )
            )
        if selected.get("held_until_clear"):
            lines.append(
                ReasonLine(
                    "notice",
                    "safety",
                    "alert.existing_selection_held",
                    "selected",
                    "This alert remains selected until it clears.",
                )
            )
        elif len(details) > 1:
            lines.append(
                ReasonLine(
                    "notice",
                    "safety",
                    "alert.conflict_resolved",
                    "selected",
                    "HI selected this alert using the fixed alert and zone priority order.",
                    {"candidate_count": len(details)},
                )
            )
        return headline, variant, lines

    def _trigger_display_line(self, family: str, fact: _TriggerFact) -> ReasonLine:
        if fact.code == "humidity_delta":
            text = (
                f"Humidity is {fact.measured:.1f} percentage points above the home "
                f"average, meeting the configured {fact.threshold:g} percentage-point "
                "response threshold."
            )
        elif fact.code == "condensation_risk":
            profile = self._presentation_label(fact.profile_label, "active profile")
            text = (
                f"Dew-point spread is {fact.measured:.1f}°C, at or below the "
                f"{fact.threshold:g}°C {profile} risk point."
            )
        elif fact.code == "mould_risk":
            profile = self._presentation_label(fact.profile_label, "active profile")
            measured_range = _risk_range_label(fact.measured)
            threshold_range = _risk_range_label(fact.threshold, fallback="")
            if fact.measured > fact.threshold:
                if threshold_range:
                    text = (
                        f"Mould conditions are in the {measured_range} range, above the "
                        f"configured {threshold_range} response point for the {profile} profile."
                    )
                else:
                    text = (
                        f"Mould conditions are in the {measured_range} range, above the "
                        f"configured mould response point for the {profile} profile."
                    )
            else:
                if threshold_range:
                    text = (
                        f"Mould conditions have reached the configured {threshold_range} "
                        f"response point for the {profile} profile."
                    )
                else:
                    text = (
                        "Mould conditions have reached the configured mould response "
                        f"point for the {profile} profile."
                    )
        elif fact.code == "pm25_high":
            text = (
                f"PM2.5 is {fact.measured:g} µg/m³, at or above the "
                f"response point of {fact.threshold:g} µg/m³."
            )
        elif fact.code == "co2_high":
            text = (
                f"CO2 is {fact.measured:g} ppm, at or above the "
                f"response point of {fact.threshold:g} ppm."
            )
        elif fact.code == "co_warning":
            text = (
                f"CO is {fact.measured:g} ppm, at or above the "
                f"warning point of {fact.threshold:g} ppm."
            )
        elif fact.code == "iaq_bad":
            text = (
                f"IAQ is {fact.measured:g}, at or below the "
                f"response point of {fact.threshold:g}."
            )
        else:
            text = (
                f"VOC is {fact.measured:g}, at or above the "
                f"response point of {fact.threshold:g}."
            )
        return ReasonLine(
            "why",
            "ventilation",
            f"{family}.{fact.code}",
            "observed",
            text,
            {
                "measured": fact.measured,
                "threshold": fact.threshold,
                "unit": fact.unit,
            },
        )

    def _humidifier_display_lines(
        self,
        active_details: List[Dict[str, Any]],
    ) -> List[ReasonLine]:
        """Return self-contained, plain-language humidifier response lines."""

        runtime_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        status = runtime_data.get("humidifier_status")
        if not isinstance(status, dict):
            return []
        lanes = status.get("lanes")
        if not isinstance(lanes, dict):
            return []
        active_by_level = {
            str(detail.get("level")): detail
            for detail in active_details
            if isinstance(detail, dict) and detail.get("level")
        }
        lines: List[ReasonLine] = []
        active_demand_seen = False
        for level in ("level1", "level2"):
            lane = lanes.get(level)
            if not isinstance(lane, dict):
                continue
            demand = str(lane.get("demand") or "inactive")
            reconciliation = str(lane.get("reconciliation") or "inactive")
            observed = str(lane.get("observed") or "not_configured")
            platform_action = str(lane.get("platform_action") or "not_exposed")
            failure_category = str(lane.get("failure_category") or "")
            on_dispatch = self._humidifier_lane_dispatch_evidence(level, "turn_on")
            off_dispatch = self._humidifier_lane_dispatch_evidence(level, "turn_off")
            not_attempted = self._humidifier_lane_not_attempted_evidence(
                level,
                "turn_on" if demand == "requested" else "turn_off",
            )
            if reconciliation == "isolated" and demand != "requested":
                # Preserve the single existing global notice for inactive isolation.
                continue
            relevant = demand == "requested" or reconciliation in {
                "degraded",
                "fault_latched",
                "inactive_shared_output",
                "isolated",
                "manual_hold",
                "output_on",
                "platform_idle",
                "requested",
                "retrying",
                "stopping",
                "unknown",
            }
            if not relevant:
                continue
            label = self._presentation_level_label(level)
            first_response = not lines
            detail = active_by_level.get(level, {})
            humidity = _to_float(detail.get("humidity"))
            start = _to_float(detail.get("low"))
            stop = _to_float(detail.get("recovery_off"))
            environment = str(
                detail.get("environmental_state")
                or lane.get("environmental_state")
                or "inactive"
            )
            environment_text: Optional[str]
            if (
                demand == "requested"
                and humidity is not None
                and start is not None
                and stop is not None
            ):
                season = sanitize_display_label(detail.get("season"), maximum=32)
                profile_context = (
                    f"the {season} profile" if season else "the current profile"
                )
                lead = "Separately, " if first_response else "Meanwhile, "
                if environment == "recovering":
                    environment_text = (
                        f"{lead}{label} still needs humidification at {humidity:.1f}%. "
                        f"Under {profile_context}, demand starts at {start:.1f}% "
                        "and clears at "
                        f"{stop:.1f}% to avoid short cycling."
                    )
                else:
                    connector = "needs" if not active_demand_seen else "also needs"
                    environment_text = (
                        f"{lead}{label} {connector} humidification at {humidity:.1f}%. "
                        f"Under {profile_context}, demand starts at {start:.1f}% "
                        "and clears at "
                        f"{stop:.1f}% to avoid short cycling."
                    )
            elif demand == "requested":
                lead = "Separately, " if first_response else "Meanwhile, "
                connector = "needs" if not active_demand_seen else "also needs"
                environment_text = f"{lead}{label} {connector} humidification."
            else:
                lead = "Separately, " if first_response else "Meanwhile, "
                environment_text = f"{lead}{label} no longer needs humidification."

            if reconciliation == "output_on":
                if platform_action == "humidifying":
                    response_text = (
                        "Home Assistant reports its output on and its humidifier action "
                        "as humidifying; "
                        "physical moisture output is not measured."
                    )
                else:
                    response_text = (
                        "Home Assistant reports that the output is on; physical moisture "
                        "output is not measured."
                    )
                truth = "observed"
            elif reconciliation == "platform_idle":
                response_text = (
                    "Home Assistant reports its output on, but its humidifier action is idle; "
                    "physical moisture output is not measured."
                )
                truth = "observed"
            elif reconciliation == "requested":
                if on_dispatch == "requested":
                    response_text = (
                        "HI sent the output-on request to Home Assistant; confirmation "
                        "is pending."
                    )
                    truth = "requested"
                else:
                    response_text = (
                        "HI is waiting for output-on confirmation, but cannot confirm "
                        "that Home Assistant received a request."
                    )
                    truth = "not_confirmed"
            elif reconciliation == "retrying":
                if on_dispatch == "failed":
                    response_text = (
                        "A Home Assistant output-on request failed, so HI is "
                        "retrying within its configured limit."
                    )
                    truth = "failed"
                elif on_dispatch == "requested":
                    response_text = (
                        "HI sent an output-on retry to Home Assistant; confirmation is pending."
                    )
                    truth = "requested"
                else:
                    response_text = (
                        "The output still does not match the expected on state. HI is "
                        "retrying within its configured limit, but cannot confirm that "
                        "Home Assistant received a request."
                    )
                    truth = "not_confirmed"
            elif reconciliation == "stopping":
                if off_dispatch == "failed":
                    response_text = (
                        "A Home Assistant output-off request failed, so HI is "
                        "still checking for the output to turn off within its configured limit."
                    )
                    truth = "failed"
                elif off_dispatch == "requested":
                    response_text = (
                        "HI sent the output-off request to Home Assistant; confirmation is pending."
                    )
                    truth = "requested"
                else:
                    response_text = (
                        "HI is waiting for output-off confirmation, but cannot confirm "
                        "that Home Assistant received a request."
                    )
                    truth = "not_confirmed"
            elif reconciliation == "isolated":
                response_text = (
                    "Humidifier-output isolation is active, so HI is not sending "
                    "humidifier commands to Home Assistant."
                )
                truth = "blocked"
            elif reconciliation == "manual_hold":
                environment_text = None
                response_text = (
                    "While Manual is on, HI shows the humidifier state reported by "
                    "Home Assistant without changing it."
                )
                truth = "observed"
            elif reconciliation == "unknown":
                response_text = (
                    "Home Assistant is not reporting the output state, so HI cannot "
                    "confirm whether it is on."
                )
                truth = "unavailable"
            elif reconciliation == "degraded":
                if failure_category == "telemetry_unavailable":
                    environment_text = None
                    response_text = (
                        "Humidity data is unavailable, so HI cannot assess humidifier demand."
                    )
                    truth = "unavailable"
                elif failure_category == "no_outputs":
                    environment_text = None
                    response_text = (
                        "No humidifier output is configured, so no command was sent."
                    )
                    truth = "blocked"
                elif not_attempted == "unsupported_domain":
                    response_text = (
                        "A configured humidifier output uses an unsupported entity type, "
                        "so HI did not send that request."
                    )
                    truth = "blocked"
                elif not_attempted == "service_unavailable":
                    intent_label = (
                        "output-on" if demand == "requested" else "output-off"
                    )
                    response_text = (
                        f"A required Home Assistant {intent_label} service is unavailable, "
                        "so HI did not send that request."
                    )
                    truth = "blocked"
                elif not_attempted == "missing":
                    response_text = (
                        "A configured humidifier output is not available in Home Assistant, "
                        "so HI did not send that request."
                    )
                    truth = "unavailable"
                elif not_attempted in {"unknown", "unavailable"}:
                    response_text = (
                        "A required humidifier output state is unavailable, so HI did not "
                        "send that request."
                    )
                    truth = "unavailable"
                else:
                    response_text = (
                        "HI cannot confirm how the humidifier output responded."
                    )
                    truth = "not_confirmed"
            elif reconciliation == "fault_latched":
                response_text = (
                    "HI has used all configured confirmation attempts and still cannot "
                    "confirm the output state."
                )
                truth = "failed"
            elif reconciliation == "inactive_shared_output":
                response_text = (
                    "Demand is inactive here, but another area still needs the "
                    "shared output."
                )
                environment_text = None
                truth = "selected"
            else:
                response_text = ""
                truth = "selected"
            args = {
                "demand_active": demand == "requested",
                "dispatch_evidence": (
                    off_dispatch if reconciliation == "stopping" else on_dispatch
                ),
                "environmental_state": environment,
                "lane": level,
                "observed": observed,
                "reconciliation": reconciliation,
            }
            lines.extend(
                self._bounded_humidifier_response_lines(
                    label=label,
                    environment_text=environment_text,
                    response_text=response_text,
                    reconciliation=reconciliation,
                    truth=truth,
                    args=args,
                )
            )
            active_demand_seen = active_demand_seen or demand == "requested"
        return lines

    @staticmethod
    def _bounded_humidifier_response_lines(
        *,
        label: str,
        environment_text: Optional[str],
        response_text: str,
        reconciliation: str,
        truth: str,
        args: Dict[str, Any],
    ) -> List[ReasonLine]:
        """Combine or split one lane response without losing its friendly scope."""

        code = f"humidifier.{reconciliation}"
        if environment_text:
            environment_text = HIAutomationEngine._bounded_humidifier_environment(
                label,
                environment_text,
            )
        if environment_text and response_text:
            combined = f"{environment_text} {response_text}"
            if len(combined) <= DISPLAY_REASON_MAX_LINE_TEXT:
                return [
                    ReasonLine(
                        "notice",
                        "humidifier",
                        code,
                        truth,
                        combined,
                        args,
                    )
                ]
            return [
                ReasonLine(
                    "notice",
                    "humidifier",
                    "humidifier.environment",
                    "selected",
                    environment_text,
                    args,
                ),
                ReasonLine(
                    "notice",
                    "humidifier",
                    code,
                    truth,
                    HIAutomationEngine._scoped_humidifier_response(label, response_text),
                    args,
                ),
            ]
        text = environment_text or response_text
        if not environment_text:
            text = HIAutomationEngine._scoped_humidifier_response(label, text)
        return [
            ReasonLine(
                "notice",
                "humidifier",
                code,
                truth,
                text,
                args,
            )
        ]

    @staticmethod
    def _bounded_humidifier_environment(label: str, text: str) -> str:
        """Shorten only the scoped label when environment prose exceeds its bound."""

        if len(text) <= DISPLAY_REASON_MAX_LINE_TEXT:
            return text
        for lead in ("Separately, ", "Meanwhile, "):
            marker = f"{lead}{label}"
            if not text.startswith(marker):
                continue
            suffix = text[len(marker) :]
            available = DISPLAY_REASON_MAX_LINE_TEXT - len(lead) - len(suffix)
            if available <= 0:
                break
            bounded_label = label
            if len(bounded_label) > available:
                bounded_label = f"{bounded_label[:max(1, available - 1)].rstrip()}…"
            return f"{lead}{bounded_label}{suffix}"
        if "no longer needs humidification" in text:
            return (
                f"{lead}the configured humidifier level no longer needs "
                "humidification."
            )
        return f"{lead}the configured humidifier level needs humidification."

    @staticmethod
    def _scoped_humidifier_response(label: str, text: str) -> str:
        """Prefix a split response with its resolved level without ledger phrasing."""

        response = (
            text
            if text.startswith(("HI ", "Home Assistant "))
            else f"{text[:1].lower()}{text[1:]}"
        )
        suffix = f", {response}"
        available = DISPLAY_REASON_MAX_LINE_TEXT - len("For ") - len(suffix)
        bounded_label = label
        if len(bounded_label) > available:
            bounded_label = f"{bounded_label[:max(1, available - 1)].rstrip()}…"
        return f"For {bounded_label}{suffix}"

    def _humidifier_lane_dispatch_evidence(self, level: str, intent: str) -> str:
        runtime_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        reconciliation = runtime_data.get("humidifier_reconciliation")
        if not isinstance(reconciliation, dict):
            return "not_confirmed"
        outputs = reconciliation.get("outputs")
        if not isinstance(outputs, dict):
            return "not_confirmed"
        results: List[str] = []
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            owners = set(output.get("owners") or ()) | set(
                output.get("configured_owners") or ()
            )
            if level not in owners or output.get("last_command_intent") != intent:
                continue
            results.append(str(output.get("dispatch_result") or "not_confirmed"))
        if "exception" in results:
            return "failed"
        if "dispatched_unconfirmed" in results:
            return "requested"
        return "not_confirmed"

    def _humidifier_lane_not_attempted_evidence(
        self,
        level: str,
        intent: str,
    ) -> Optional[str]:
        """Return existing output evidence that explains why dispatch was skipped."""

        runtime_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        reconciliation = runtime_data.get("humidifier_reconciliation")
        if not isinstance(reconciliation, dict):
            return None
        outputs = reconciliation.get("outputs")
        if not isinstance(outputs, dict):
            return None
        results: set[str] = set()
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            owners = set(output.get("owners") or ()) | set(
                output.get("configured_owners") or ()
            )
            if level not in owners or output.get("last_command_intent") != intent:
                continue
            results.add(str(output.get("dispatch_result") or ""))
        for result in (
            "unsupported_domain",
            "service_unavailable",
            "missing",
            "unavailable",
            "unknown",
        ):
            if result in results:
                return result
        return None

    def _isolation_display_lines(self, *, include_fan: bool = True) -> List[ReasonLine]:
        lines: List[ReasonLine] = []
        if include_fan and self._fan_outputs_isolated():
            lines.append(
                ReasonLine(
                    "notice",
                    "ventilation",
                    "isolation.fan_outputs",
                    "blocked",
                    (
                        "Fan-output isolation is active, so HI is not sending fan "
                        "commands to Home Assistant."
                    ),
                )
            )
        if self._humidifier_outputs_isolated():
            status = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {}).get(
                "humidifier_status",
                {},
            )
            if (
                not isinstance(status, dict)
                or status.get("overall") in {None, "inactive"}
            ):
                lines.append(
                    ReasonLine(
                        "notice",
                        "humidifier",
                        "isolation.humidifier_outputs",
                        "blocked",
                        (
                            "Humidifier-output isolation is active, so HI is not sending "
                            "humidifier commands to Home Assistant."
                        ),
                    )
                )
        return lines

    def _presentation_label(
        self,
        value: Any,
        generic: str,
        *,
        maximum: int = 64,
    ) -> str:
        return sanitize_display_label(value, maximum=maximum) or generic

    def _presentation_level_label(self, level: Any) -> str:
        key = str(level or "").strip()
        fallback = "Downstairs" if key == "level1" else "Upstairs" if key == "level2" else "Configured level"
        return sanitize_display_label(self._level_labels.get(key)) or fallback

    def _presentation_output_summary(self, outputs: List[str], *, generic: str) -> str:
        entities = [str(entity_id).strip() for entity_id in outputs if str(entity_id).strip()]
        labels: List[str] = []
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            friendly_name = None
            if state is not None:
                friendly_name = getattr(state, "attributes", {}).get("friendly_name")
            label = sanitize_display_label(friendly_name)
            if label and label.lower() != entity_id.lower():
                labels.append(label)
        if labels and len(labels) == len(entities) and len(labels) <= 2:
            summary = " and ".join(labels)
            if len(summary.encode("utf-8")) <= _DISPLAY_OUTPUT_SUMMARY_MAX_BYTES:
                return summary
        if len(entities) > 1:
            return f"{len(entities)} {generic}s"
        if len(entities) == 1:
            return f"the {generic}"
        return generic

    def _make_reason_facts(
        self,
        family: str,
        variant: str,
        attention: str,
        headline: str,
        lines: List[ReasonLine],
    ) -> ReasonFacts:
        truncated = len(lines) > DISPLAY_REASON_MAX_LINES
        if len(lines) <= DISPLAY_REASON_TARGET_LINES:
            bounded_lines = lines
        elif not truncated:
            bounded_lines = lines
        else:
            retained = sorted(
                range(len(lines)),
                key=lambda index: (
                    self._reason_line_retention_priority(lines[index]),
                    index,
                ),
            )[:DISPLAY_REASON_MAX_LINES]
            retained_indexes = set(retained)
            bounded_lines = [
                line for index, line in enumerate(lines) if index in retained_indexes
            ]
        facts = ReasonFacts(
            family=family,
            variant=variant,
            attention=attention,
            headline=headline,
            lines=tuple(bounded_lines),
            truncated=truncated,
        )
        while True:
            try:
                build_display_reason(facts)
                return facts
            except ReasonPresentationError as err:
                if str(err) != "display reason exceeds the 4 KiB limit":
                    raise
                if len(facts.lines) <= 1:
                    raise
                remove_index = max(
                    range(len(facts.lines)),
                    key=lambda index: (
                        self._reason_line_retention_priority(facts.lines[index]),
                        index,
                    ),
                )
                facts = ReasonFacts(
                    family=family,
                    variant=variant,
                    attention=attention,
                    headline=headline,
                    lines=tuple(
                        line
                        for index, line in enumerate(facts.lines)
                        if index != remove_index
                    ),
                    truncated=True,
                )

    @staticmethod
    def _reason_line_retention_priority(line: ReasonLine) -> int:
        if line.truth == "failed":
            return 0
        if line.scope == "safety":
            return 1
        if line.truth in {"unavailable", "unmapped", "not_confirmed"}:
            return 2
        if line.code.startswith("isolation."):
            return 3
        if line.role == "action":
            return 4
        if line.truth == "observed":
            return 5
        if line.scope == "humidifier":
            return 6
        if line.role == "why":
            return 7
        return 8

    def _format_zone_detail(self, detail: Dict[str, Any], zone_label: str) -> str:
        outputs = self._format_output_entities(detail.get("outputs", []))
        run_level = _fan_level_text(detail.get("output_level"))
        trigger_summary = "; ".join(detail.get("triggers", [])) or "configured trigger condition met"
        return (
            f"{zone_label} is active at {run_level} on {outputs}. "
            f"Trigger detail: {trigger_summary}."
        )

    def _format_alert_detail(self, details: List[Any]) -> str:
        if not details:
            return "Alert response is active. All lower-priority lanes are paused until the alert clears."
        if not isinstance(details[0], dict):
            return (
                f"Alert response is active ({'; '.join(str(item) for item in details)}). "
                "All lower-priority lanes are paused until the alert clears."
            )
        selected = details[0]
        segments = [
            f"Alert response is active ({selected.get('companion') or selected.get('label')})."
        ]
        sensor = selected.get("sensor") or "unknown"
        room = selected.get("room") or "unknown"
        zone = selected.get("zone") or "unmapped"
        segments.append(f"Originating sensor: {sensor}; room: {room}; resolved zone: {zone}.")
        if selected.get("outputs") and selected.get("boost_level"):
            outputs = self._format_output_entities(selected.get("outputs", []))
            run_level = _fan_level_text(selected.get("boost_level"))
            segments.append(
                f"Selected {zone} boost level {run_level} on {outputs} because alerts override zone, AQ, and normal lanes."
            )
            if selected.get("held_until_clear"):
                segments.append(
                    "Boost selection is being held until this originating alert clears; equal-priority candidates wait their turn."
                )
            else:
                segments.append(
                    "Boost selection will be held while this originating alert remains active, then the next priority is evaluated."
                )
        else:
            segments.append("Degraded mode: no zone boost was applied because the alert could not be safely mapped to configured zone outputs.")
        if selected.get("threshold_source") and selected.get("threshold") is not None:
            threshold = selected.get("threshold")
            unit = "%" if selected.get("trigger_type") == "humidity_danger" else ""
            segments.append(
                f"Threshold source: {selected['threshold_source']}; threshold {threshold:g}{unit}."
            )
        if selected.get("measured"):
            segments.append(f"Trigger detail: {selected['measured']}.")
        if len(details) > 1:
            candidates = "; ".join(
                str(item.get("companion") or item.get("label")) for item in details
            )
            if any(not _alert_can_control(item) for item in details[1:] if isinstance(item, dict)):
                segments.append(
                    f"Conflict detected across active alerts; selected the next actionable mapped alert after skipping degraded candidates. Candidates: {candidates}."
                )
            elif selected.get("held_until_clear"):
                segments.append(
                    f"Conflict detected across active alerts; held the existing actionable alert until clear. Candidates: {candidates}."
                )
            else:
                segments.append(
                    f"Conflict detected across active alerts; resolved deterministically by alert hierarchy then zone priority. Candidates: {candidates}."
                )
        if selected.get("degraded_reasons"):
            segments.append("Mapping issues: " + "; ".join(selected.get("degraded_reasons", [])))
        skipped_notice = self._format_skipped_alert_notice(details[1:])
        if skipped_notice:
            segments.append(skipped_notice)
        segments.append("Overridden logic: zone automation, AQ, and normal lanes are paused until the selected alert clears.")
        return " ".join(segments)

    def _format_nonblocking_alert_notice(self, details: List[Any]) -> str:
        if not details or not isinstance(details[0], dict):
            return ""
        skipped_notice = self._format_skipped_alert_notice(
            [detail for detail in details if not _alert_can_control(detail)]
        )
        if not skipped_notice:
            return ""
        return (
            f"{skipped_notice} Automation continued to the next eligible priority "
            "instead of applying a blind boost."
        )

    def _format_skipped_alert_notice(self, details: List[Dict[str, Any]]) -> str:
        skipped = [detail for detail in details if not _alert_can_control(detail)]
        if not skipped:
            return ""
        parts = []
        for detail in skipped[:3]:
            label = str(detail.get("companion") or detail.get("label") or "Alert")
            reasons = detail.get("degraded_reasons") or []
            if reasons:
                parts.append(f"{label} ({'; '.join(str(reason) for reason in reasons)})")
            else:
                parts.append(f"{label} (no mapped zone boost output)")
        suffix = "" if len(skipped) <= 3 else f"; plus {len(skipped) - 3} more"
        return f"Skipped alert candidate(s): {'; '.join(parts)}{suffix}."

    def _format_aq_detail(self, details: List[Dict[str, Any]]) -> str:
        if not details:
            return "Air-quality assist is active."
        segments: List[str] = []
        for item in details:
            level = "Downstairs" if item.get("level") == "level1" else "Upstairs"
            outputs = self._format_output_entities(item.get("outputs", []))
            run_level = _fan_level_text(item.get("output_level"))
            triggers = "; ".join(item.get("triggers", []))
            segments.append(
                f"{level} AQ is active at {run_level} on {outputs}. Trigger detail: {triggers}."
            )
        return " ".join(segments)

    def _format_humidifier_detail(self, details: List[Dict[str, Any]]) -> str:
        if not details:
            return ""

        active = [item for item in details if item.get("demand")]
        if not active:
            return ""

        if len(active) >= 2:
            segments: List[str] = [
                "Humidifier demand is requested for downstairs and upstairs."
            ]
        else:
            lane = "downstairs" if active[0].get("level") == "level1" else "upstairs"
            segments = [f"Humidifier demand is requested for {lane}."]

        for item in active:
            level = "Downstairs" if item.get("level") == "level1" else "Upstairs"
            humidity = _to_float(item.get("humidity"))
            low = _to_float(item.get("low"))
            high = _to_float(item.get("high"))
            recovery_off = _to_float(item.get("recovery_off"))
            environmental_state = str(item.get("environmental_state") or "start")
            reconciliation = str(item.get("reconciliation") or "degraded")
            platform_action = str(item.get("platform_action") or "not_exposed")

            if humidity is None or low is None or high is None or recovery_off is None:
                segments.append(f"{level}: humidity data is unavailable.")
                continue

            if environmental_state == "recovering":
                segments.append(
                    f"{level}: {humidity:.1f}% (target {low:.1f}-{high:.1f}%). "
                    f"Demand remains requested until {recovery_off:.1f}% to avoid short-cycling."
                )
            else:
                segments.append(
                    f"{level}: {humidity:.1f}% is at or below the {low:.1f}% start point "
                    f"(target {low:.1f}-{high:.1f}%). It will stop at {recovery_off:.1f}%."
                )

            if reconciliation == "output_on":
                segments.append(
                    f"{level}: Home Assistant reports the configured output on. "
                    "Physical moisture production is not independently verified."
                )
            elif reconciliation == "platform_idle":
                segments.append(
                    f"{level}: Home Assistant reports the output on and the humidifier action idle. "
                    "Physical moisture production is not confirmed."
                )
            elif reconciliation == "requested":
                segments.append(
                    f"{level}: an output command was requested and remains unconfirmed."
                )
            elif reconciliation == "retrying":
                segments.append(
                    f"{level}: the output remains off and bounded reconciliation is retrying."
                )
            elif reconciliation == "isolated":
                segments.append(
                    f"{level}: humidifier-output isolation is suppressing commands."
                )
            elif reconciliation == "manual_hold":
                segments.append(
                    f"{level}: While Manual is on, HI reports the humidifier state "
                    "observed by Home Assistant without changing it."
                )
            elif reconciliation in {"unknown", "degraded"}:
                segments.append(
                    f"{level}: output state is unknown or degraded, so HI is not claiming activity."
                )
            elif reconciliation == "fault_latched":
                segments.append(
                    f"{level}: reconciliation attempts are exhausted and a fault is latched for this demand period."
                )
            if platform_action == "humidifying":
                segments.append(
                    f"{level}: the Home Assistant humidifier action reports humidifying; "
                    "this is platform-reported action, not measured moisture output."
                )
        return " ".join(segments)

    def _entity_display_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is not None:
            friendly_name = state.attributes.get("friendly_name")
            if friendly_name:
                return str(friendly_name)
        return entity_id

    def _format_output_entities(self, entity_ids: List[str]) -> str:
        entities = [entity_id for entity_id in entity_ids if entity_id]
        if not entities:
            return "no outputs configured"
        return ", ".join(self._entity_display_name(entity_id) for entity_id in entities)

    def _co_emergency_settings(self) -> Tuple[float, float, List[str]]:
        start_threshold = float(CO_EMERGENCY_START)
        configured_thresholds: List[float] = []

        for alert in self.alerts:
            if not alert.get("enabled", True):
                continue
            if alert.get("trigger_type") != "co_emergency":
                continue
            threshold = _safe_alert_threshold("co_emergency", alert.get("threshold"), float(CO_EMERGENCY_START))
            configured_thresholds.append(threshold)

        if configured_thresholds:
            start_threshold = min(configured_thresholds)

        clear_threshold = max(0.0, start_threshold - 5.0)
        if clear_threshold >= start_threshold:
            clear_threshold = max(0.0, start_threshold - 1.0)

        return start_threshold, clear_threshold, self._all_fan_outputs()

    def _humidifier_active_key(self, level: str) -> str:
        return f"air_{'downstairs' if level == 'level1' else 'upstairs'}_humidifier_active"

    def _active_humidifier_levels(self) -> List[str]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        active: List[str] = []
        if booleans.get("air_downstairs_humidifier_active") and booleans["air_downstairs_humidifier_active"].is_on:
            active.append("Downstairs")
        if booleans.get("air_upstairs_humidifier_active") and booleans["air_upstairs_humidifier_active"].is_on:
            active.append("Upstairs")
        return active

    async def _set_aq_level_active(self, level: str, is_active: bool) -> None:
        key = f"air_aq_{'upstairs' if level == 'level2' else 'downstairs'}_active"
        await self._set_bool(key, is_active)

    async def _set_aq_level_timer(self, level: str, duration_seconds: int) -> None:
        key = f"air_aq_{'upstairs' if level == 'level2' else 'downstairs'}_run"
        await self._set_timer(key, duration_seconds)

    async def _clear_aq_level_timer(self, level: str) -> None:
        key = f"air_aq_{'upstairs' if level == 'level2' else 'downstairs'}_run"
        await self._clear_timer(key)

    async def _set_bool(self, key: str, value: bool) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        entity = booleans.get(key)
        if entity:
            if bool(getattr(entity, "is_on", False)) == bool(value):
                return
            if value:
                await entity.async_turn_on()
            else:
                await entity.async_turn_off()

    async def _set_timer(self, key: str, duration_seconds: int) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        timers = data.get("hi_timers", {})
        entity = timers.get(key)
        if entity:
            await entity.async_start(timedelta(seconds=duration_seconds))

    async def _clear_timer(self, key: str) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        timers = data.get("hi_timers", {})
        entity = timers.get(key)
        if entity:
            await entity.async_cancel()

    async def _set_runtime_mode(self, mode: str, display: Optional[str] = None) -> None:
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
        data["runtime_mode"] = mode
        data["runtime_mode_display"] = display or mode.replace("_", " ").upper()

    async def _set_runtime_reason(
        self,
        reason: str,
        *,
        display_facts_factory: Optional[Callable[[], ReasonFacts]] = None,
    ) -> None:
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
        safe_reason, full_reason = _state_safe_reason(reason)
        data["runtime_reason"] = safe_reason
        data["runtime_reason_full"] = full_reason
        data["runtime_reason_truncated"] = bool(full_reason)
        data.pop("runtime_display_reason", None)
        if display_facts_factory is None:
            return
        try:
            display_facts = display_facts_factory()
            data["runtime_display_reason"] = build_display_reason(display_facts)
        except Exception:
            _LOGGER.exception("HI display-reason presentation failed")

    def _bool_is_on(self, key: str) -> bool:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        entity = booleans.get(key)
        return bool(entity and getattr(entity, "is_on", False))

    def _fan_outputs_isolated(self) -> bool:
        return self._bool_is_on("air_isolate_fan_outputs")

    def _humidifier_outputs_isolated(self) -> bool:
        return self._bool_is_on("air_isolate_humidifier_outputs")

    async def _set_fan_outputs_level(
        self,
        outputs: List[str],
        level: Any,
        *,
        allow_manual_override: bool = False,
    ) -> None:
        if self._fan_outputs_isolated():
            return
        if self._manual_override_active() and not allow_manual_override:
            return
        await _apply_fan_level(
            self.hass,
            outputs,
            level,
            should_abort=(
                None if allow_manual_override else self._manual_override_active
            ),
        )

    async def _set_fan_outputs_auto(
        self,
        outputs: List[str],
        *,
        allow_manual_override: bool = False,
    ) -> None:
        if self._fan_outputs_isolated():
            return
        if self._manual_override_active() and not allow_manual_override:
            return
        await _set_fan_auto(
            self.hass,
            outputs,
            should_abort=(
                None if allow_manual_override else self._manual_override_active
            ),
        )

    def _aq_outputs_reserved_by_other_levels(self, level: str) -> set[str]:
        reserved: set[str] = set()
        for other_level, cfg in self.aq.items():
            if other_level == level:
                continue
            task = self._aq_tasks.get(other_level)
            if task and not task.done():
                reserved.update(cfg.get("outputs", []))
        return reserved

    def _with_isolation_notice(self, reason: str) -> str:
        notices: List[str] = []
        if self._fan_outputs_isolated():
            notices.append("Fan outputs are isolated for testing (service calls suppressed).")
        if self._humidifier_outputs_isolated():
            notices.append("Humidifier outputs are isolated for testing (service calls suppressed).")
        if not notices:
            return reason
        return f"{reason} {' '.join(notices)}"

    def _zone_mode_from_zone(self, zone_key: str, zone: Dict[str, Any]) -> str:
        zone_key_lower = str(zone_key).lower()
        if "zone1" in zone_key_lower:
            return "cooking"
        if "zone2" in zone_key_lower:
            return "bathroom"

        rooms = [str(r).lower() for r in zone.get("rooms", []) if r]
        if any("kitchen" in room for room in rooms):
            return "cooking"
        if any(("bath" in room) or ("toilet" in room) or ("shower" in room) for room in rooms):
            return "bathroom"
        return "zone"

    def _zone_display_label(self, zone_key: str, mode: str) -> str:
        zone = self.zones.get(zone_key, {}) if isinstance(self.zones, dict) else {}
        configured = str(zone.get("ui_label") or "").strip()
        if configured:
            return configured[:40]
        if mode == "cooking":
            return "Cooking"
        if mode == "bathroom":
            return "Bathroom"
        if "zone1" in str(zone_key).lower():
            return "Zone 1"
        if "zone2" in str(zone_key).lower():
            return "Zone 2"
        return "Zone"

    def _pause_active(self) -> bool:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        timer = (data.get("hi_timers") or {}).get("air_control_pause")
        if timer:
            return timer.native_value == "active"
        state = self.hass.states.get("sensor.hi_air_control_pause")
        return bool(state and state.state == "active")

    async def _set_zone_outputs_auto(self, exclude: Optional[List[str]] = None) -> None:
        outputs = self._all_zone_outputs()
        if exclude:
            excluded = set(exclude)
            outputs = [entity_id for entity_id in outputs if entity_id not in excluded]
        await self._set_fan_outputs_auto(outputs)

    def _active_aq_outputs(self) -> List[str]:
        outputs: List[str] = []
        for level, cfg in self.aq.items():
            task = self._aq_tasks.get(level)
            if task and not task.done():
                outputs.extend(cfg.get("outputs", []))
        return list(set(outputs))

    def _refresh_core_entities(self) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        for sensor in data.get("core_sensors", []) or []:
            try:
                sensor.update_from_hass()
                sensor.async_write_ha_state()
            except Exception:
                _LOGGER.debug("Failed refreshing core sensor %s", getattr(sensor, "entity_id", "unknown"), exc_info=True)
        for sensor in data.get("core_binary_sensors", []) or []:
            try:
                sensor.update_from_hass()
                sensor.async_write_ha_state()
            except Exception:
                _LOGGER.debug("Failed refreshing core binary sensor %s", getattr(sensor, "entity_id", "unknown"), exc_info=True)

    def _all_zone_outputs(self) -> List[str]:
        outputs: List[str] = []
        for zone in self.zones.values():
            outputs.extend(zone.get("outputs", []))
        return list(set(outputs))

    def _all_fan_outputs(self) -> List[str]:
        outputs = self._all_zone_outputs()
        for cfg in self.aq.values():
            outputs.extend(cfg.get("outputs", []))
        return list(set(outputs))

    def _collect_values(self, sensor_type: str, room_scope: Optional[str] = None) -> List[float]:
        values: List[float] = []
        room_filter = room_scope.lower().strip() if room_scope else None
        for item in self.telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            if room_filter:
                item_room = str(item.get("room") or "").strip().lower()
                if item_room != room_filter:
                    continue
            val = _get_float(self.hass, item.get("entity_id"), sensor_type=sensor_type)
            if val is not None:
                values.append(val)
        return values

    def _level_avg(self, sensor_type: str, level: Optional[str]) -> Optional[float]:
        vals: List[float] = []
        for item in self.telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            if level and item.get("level") != level:
                continue
            val = _get_float(self.hass, item.get("entity_id"), sensor_type=sensor_type)
            if val is not None:
                vals.append(val)
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    def _rooms_avg(self, sensor_type: str, rooms: List[str]) -> Optional[float]:
        if not rooms:
            return None
        room_set = {room.lower() for room in rooms if room}
        vals: List[float] = []
        for item in self.telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            room = (item.get("room") or "").lower()
            if room not in room_set:
                continue
            val = _get_float(self.hass, item.get("entity_id"), sensor_type=sensor_type)
            if val is not None:
                vals.append(val)
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    def _worst_spread(self) -> Optional[float]:
        spreads: List[float] = []
        rooms = _room_map(self.telemetry)
        for room, sensors in rooms.items():
            rh = _get_float(self.hass, sensors.get("humidity"), sensor_type="humidity")
            temp = _get_float(self.hass, sensors.get("temperature"), sensor_type="temperature")
            if rh is None or temp is None:
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spreads.append(temp - dp)
        return min(spreads) if spreads else None

    def _worst_mould_level(self) -> int:
        rooms = _room_map(self.telemetry)
        profile = self._active_target_profile()
        level = 0
        for room, sensors in rooms.items():
            rh = _get_float(self.hass, sensors.get("humidity"), sensor_type="humidity")
            temp = _get_float(self.hass, sensors.get("temperature"), sensor_type="temperature")
            if rh is None or temp is None:
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spread = temp - dp
            risk = seasonal_mould_level(rh, spread, profile)
            level = max(level, risk)
        return level

    def _active_target_profile(self):
        return resolve_target_profile(self._effective_config())

    def _effective_config(self) -> Dict[str, Any]:
        config = dict(getattr(self.entry, "data", None) or {})
        config.update(dict(getattr(self.entry, "options", None) or {}))
        return config


def _get_float(
    hass: HomeAssistant,
    entity_id: Optional[str],
    *,
    sensor_type: Optional[str] = None,
) -> Optional[float]:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    raw_state = str(state.state).strip()
    if raw_state.lower() in ("unknown", "unavailable"):
        return None
    if sensor_type == "temperature":
        value_c, _reason = parse_temperature(
            state.state,
            state.attributes.get("unit_of_measurement"),
            hass_temperature_unit(hass),
        )
        return value_c
    return parse_numeric(raw_state)


def _room_map(telemetry: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    rooms: Dict[str, Dict[str, str]] = {}
    for item in telemetry:
        room = item.get("room")
        if not room:
            continue
        rooms.setdefault(room, {})[item.get("sensor_type")] = item.get("entity_id")
    return rooms


def _dew_point(temp_c: float, rh: float) -> Optional[float]:
    if rh <= 0:
        return None
    import math
    a = 17.62
    b = 243.12
    gamma = (a * temp_c / (b + temp_c)) + math.log(rh / 100.0)
    return (b * gamma) / (a - gamma)


def _parse_time(value) -> Optional[datetime.time]:
    if value is None:
        return None
    if hasattr(value, "hour"):
        return value
    try:
        parts = str(value).split(":")
        return datetime.strptime(f"{int(parts[0]):02d}:{int(parts[1]):02d}", "%H:%M").time()
    except Exception:
        return None


def _time_in_window(now, start, end) -> bool:
    if start <= end:
        return start <= now <= end
    # Overnight window
    return now >= start or now <= end


def _normalize_fan_level(value: Any, fallback: Any) -> str:
    raw = value if value is not None else fallback
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text == FAN_OUTPUT_LEVEL_AUTO:
            return FAN_OUTPUT_LEVEL_AUTO
        if text.endswith("%"):
            text = text[:-1]
        try:
            raw = int(float(text))
        except (TypeError, ValueError):
            raw = None
    try:
        numeric = int(raw)
    except (TypeError, ValueError):
        numeric = int(fallback) if str(fallback).isdigit() else ZONE_OUTPUT_LEVEL_DEFAULT
    if numeric <= 0:
        return FAN_OUTPUT_LEVEL_AUTO
    if numeric >= 100:
        return "100"
    nearest = min(FAN_OUTPUT_LEVEL_STEPS, key=lambda step: abs(step - numeric))
    return str(nearest)


def _fan_level_rank(level: Optional[str]) -> int:
    if not level:
        return 0
    normalized = _normalize_fan_level(level, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        return 0
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return 0


def _max_fan_level(current: Optional[str], candidate: str) -> str:
    if current is None:
        return candidate
    return candidate if _fan_level_rank(candidate) >= _fan_level_rank(current) else current


def _fan_level_text(level: Any) -> str:
    normalized = _normalize_fan_level(level, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        return "Auto"
    return f"{normalized}%"


def _alert_can_control(detail: Dict[str, Any]) -> bool:
    return bool(
        detail
        and not detail.get("degraded")
        and detail.get("outputs")
        and detail.get("boost_level")
    )


def _alert_identity(detail: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(detail.get("trigger_type") or ""),
        str(detail.get("sensor") or ""),
        str(detail.get("room") or ""),
    )


def _alert_priority(trigger_type: str) -> int:
    return _ALERT_PRIORITY.get(str(trigger_type or ""), 999)


def _zone_priority(zone_key: Optional[str]) -> int:
    if zone_key == "zone1":
        return 1
    if zone_key == "zone2":
        return 2
    return 999


def _alert_kind_and_severity(trigger_type: str) -> Tuple[str, str]:
    text = str(trigger_type or "alert").lower()
    if "mould" in text:
        kind = "Mould"
    elif "condensation" in text:
        kind = "Condensation"
    elif "humidity" in text:
        kind = "Humidity"
    elif "co" in text:
        kind = "CO"
    else:
        kind = "Alert"
    if "danger" in text:
        severity = "Danger"
    elif "risk" in text:
        severity = "Risk"
    elif "emergency" in text:
        severity = "Emergency"
    else:
        severity = "Active"
    return kind, severity


def _risk_range_label(value: Any, *, fallback: str = "active") -> str:
    """Translate an internal ordinal risk value into bounded display wording."""
    numeric = _to_float(value)
    if numeric is None:
        return fallback
    rounded = int(round(numeric))
    if abs(numeric - rounded) > 0.001:
        return fallback
    return _RISK_DISPLAY_BY_LEVEL.get(rounded, fallback)


def _alert_companion_label(
    kind: str,
    severity: str,
    room: Optional[str],
    zone_label: Optional[str],
) -> str:
    base = f"{kind} {severity}".strip()
    if room and zone_label:
        return f"{base} - {room} ({zone_label})"
    if room:
        return f"{base} - {room} (unmapped zone)"
    if zone_label:
        return f"{base} - {zone_label}"
    return base


def _alert_source_summary(
    *,
    trigger_type: str,
    room: Optional[str],
    zone: Optional[str],
    measured: Optional[str],
    threshold: Optional[str],
) -> str:
    kind, severity = _alert_kind_and_severity(trigger_type)
    parts = [f"{kind} {severity}".strip()]
    if room:
        parts.append(str(room))
    if zone:
        parts.append(str(zone))
    if measured and threshold:
        parts.append(f"{measured} >= {threshold}")
    return " · ".join(part for part in parts if part)


async def _apply_fan_level(
    hass: HomeAssistant,
    entities: List[str],
    level: Any,
    *,
    should_abort: Optional[Callable[[], bool]] = None,
) -> None:
    normalized = _normalize_fan_level(level, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        await _set_fan_auto(hass, entities, should_abort=should_abort)
        return
    await _set_fan_percentage(
        hass,
        entities,
        int(normalized),
        should_abort=should_abort,
    )


def _coerce_fan_percentage(value: Any) -> int:
    pct = _bounded_int(value, 0, 100, ZONE_OUTPUT_LEVEL_DEFAULT)
    if pct <= 0:
        return 0
    if pct >= 100:
        return 100
    return min(FAN_OUTPUT_LEVEL_STEPS, key=lambda step: abs(step - pct))


async def _set_fan_percentage(
    hass: HomeAssistant,
    entities: List[str],
    pct: int,
    *,
    should_abort: Optional[Callable[[], bool]] = None,
) -> None:
    pct = _coerce_fan_percentage(pct)
    for entity_id in entities:
        if should_abort and should_abort():
            return
        domain = entity_id.split(".")[0]
        state = hass.states.get(entity_id)
        if domain == "fan":
            if not hass.services.has_service("fan", "turn_on") or not hass.services.has_service("fan", "set_percentage"):
                _LOGGER.debug("Skipping fan percentage for %s; service unavailable", entity_id)
                continue
            current_pct = state.attributes.get("percentage") if state else None
            if state and state.state == "on" and current_pct is not None:
                try:
                    if int(current_pct) == int(pct):
                        continue
                except (TypeError, ValueError):
                    pass
            try:
                if not state or state.state != "on":
                    if should_abort and should_abort():
                        return
                    await hass.services.async_call("fan", "turn_on", {"entity_id": entity_id}, blocking=False)
                if should_abort and should_abort():
                    return
                await hass.services.async_call(
                    "fan",
                    "set_percentage",
                    {"entity_id": entity_id, "percentage": pct},
                    blocking=False,
                )
            except Exception:
                _LOGGER.exception("Failed to set fan percentage for %s", entity_id)
        elif domain == "switch":
            service = "turn_on" if pct > 0 else "turn_off"
            if not hass.services.has_service("switch", service):
                _LOGGER.debug("Skipping switch update for %s; service %s unavailable", entity_id, service)
                continue
            if state and ((pct > 0 and state.state == "on") or (pct <= 0 and state.state == "off")):
                continue
            try:
                if should_abort and should_abort():
                    return
                await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=False)
            except Exception:
                _LOGGER.exception("Failed to set switch %s via %s", entity_id, service)


async def _set_fan_auto(
    hass: HomeAssistant,
    entities: List[str],
    *,
    should_abort: Optional[Callable[[], bool]] = None,
) -> None:
    for entity_id in entities:
        if should_abort and should_abort():
            return
        domain = entity_id.split(".")[0]
        state = hass.states.get(entity_id)
        if domain == "fan":
            if not hass.services.has_service("fan", "set_preset_mode"):
                _LOGGER.debug("Skipping fan auto for %s; set_preset_mode unavailable", entity_id)
                continue
            preset_mode = str(state.attributes.get("preset_mode", "")).lower() if state else ""
            if preset_mode == "auto":
                continue
            try:
                if should_abort and should_abort():
                    return
                await hass.services.async_call(
                    "fan",
                    "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": "auto"},
                    blocking=False,
                )
            except Exception:
                _LOGGER.exception("Failed to set fan %s to auto", entity_id)
        elif domain == "switch":
            if not hass.services.has_service("switch", "turn_off"):
                _LOGGER.debug("Skipping switch turn_off for %s; service unavailable", entity_id)
                continue
            if state and state.state == "off":
                continue
            try:
                if should_abort and should_abort():
                    return
                await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=False)
            except Exception:
                _LOGGER.exception("Failed to turn off switch %s", entity_id)


def _bounded_int(value: Any, min_value: int, max_value: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(min_value, min(max_value, parsed))


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate_humidifier_status_value(
    statuses: List[Dict[str, Any]],
    key: str,
) -> str:
    values = {
        str(status.get(key) or "unknown")
        for status in statuses
    }
    if not values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _safe_alert_threshold(trigger_type: str, value: Any, fallback: float) -> float:
    bounds = ALERT_THRESHOLD_BOUNDS.get(trigger_type, {})
    min_value = _to_float(bounds.get("min"))
    max_value = _to_float(bounds.get("max"))
    default_value = _to_float(bounds.get("default"))

    if default_value is None:
        default_value = fallback
    if min_value is None:
        min_value = default_value
    if max_value is None:
        max_value = default_value

    threshold = _to_float(value)
    if threshold is None:
        threshold = _to_float(fallback)
    if threshold is None:
        threshold = default_value
    return max(min_value, min(max_value, threshold))


def _state_safe_reason(reason: Any) -> Tuple[str, Optional[str]]:
    text = str(reason or "").strip()
    if not text:
        return "", None
    if len(text) <= _MAX_STATE_LENGTH:
        return text, None

    # Keep sensor state within HA's state length while preserving full context in attributes.
    head_limit = _MAX_STATE_LENGTH - len(_TRUNCATION_SUFFIX) - 3
    if head_limit < 0:
        head_limit = 0
    head = text[:head_limit].rstrip()
    if head.endswith("."):
        state = f"{head}..{_TRUNCATION_SUFFIX}"
    else:
        state = f"{head}...{_TRUNCATION_SUFFIX}"
    if len(state) > _MAX_STATE_LENGTH:
        state = state[:_MAX_STATE_LENGTH]
    return state, text
