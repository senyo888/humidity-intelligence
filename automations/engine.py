"""Automation engine for Humidity Intelligence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from ..const import (
    ALERT_THRESHOLD_BOUNDS,
    ALERT_TRIGGER_DEFS,
    DOMAIN,
    ENGINE_INTERVAL_MAX,
    ENGINE_INTERVAL_MIN,
    ENGINE_INTERVAL_MINUTES_DEFAULT,
    FAN_OUTPUT_LEVEL_AUTO,
    FAN_OUTPUT_LEVEL_STEPS,
    HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT,
    STARTUP_SENSOR_RECHECK_SECONDS,
    ZONE_OUTPUT_LEVEL_BOOST_DEFAULT,
    ZONE_OUTPUT_LEVEL_DEFAULT,
    ZONE_OUTPUT_LEVEL_MAX,
    ZONE_OUTPUT_LEVEL_MIN,
)
from ..services import SERVICE_FLASH_LIGHTS

CO_EMERGENCY_START = 15
CO_EMERGENCY_CLEAR = 10

_LOGGER = logging.getLogger(__name__)


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
        self._unsub = None
        self._periodic = None
        self._aq_tasks: Dict[str, asyncio.Task] = {}
        self._aq_trigger_active: Dict[str, bool] = {}
        self._startup_recheck_task: Optional[asyncio.Task] = None
        self._last_alert: Dict[int, datetime] = {}
        self._co_emergency_active = False
        self._co_below_since: Optional[datetime] = None
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

    def _cfg(self, key: str, default: Any) -> Any:
        if self.entry.options and key in self.entry.options:
            return self.entry.options.get(key, default)
        return self.entry.data.get(key, default)

    async def async_start(self) -> None:
        sources = self._evaluation_sources()
        self._unsub = async_track_state_change_event(self.hass, sources, self._handle_change)
        self._periodic = async_track_time_interval(
            self.hass,
            self._periodic_check,
            timedelta(minutes=self.engine_interval_minutes),
        )
        await self._evaluate()
        self._schedule_startup_recheck()

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
        if self._periodic:
            self._periodic()
        if self._startup_recheck_task and not self._startup_recheck_task.done():
            self._startup_recheck_task.cancel()
        self._startup_recheck_task = None
        for task in self._aq_tasks.values():
            task.cancel()

    async def _handle_change(self, event) -> None:
        await self._evaluate()

    async def _periodic_check(self, now) -> None:
        await self._evaluate()

    async def async_request_evaluate(self) -> None:
        """Request an immediate evaluation cycle."""
        await self._evaluate()

    def _schedule_startup_recheck(self) -> None:
        if self._startup_recheck_task and not self._startup_recheck_task.done():
            self._startup_recheck_task.cancel()

        async def _startup_recheck() -> None:
            try:
                await asyncio.sleep(STARTUP_SENSOR_RECHECK_SECONDS)
                await self._evaluate()
            except asyncio.CancelledError:
                return

        self._startup_recheck_task = asyncio.create_task(_startup_recheck())

    async def _evaluate(self) -> None:
        try:
            control_lock_reason = self._control_lock_reason()
            if control_lock_reason:
                await self._return_to_normal()
                await self._set_runtime_reason(self._with_isolation_notice(control_lock_reason))
                return

            gates_ok, gate_reason = self._gate_status()
            if not gates_ok:
                action = self.time_gate.get("outside_action", "safe_state")
                if action == "safe_state":
                    await self._return_to_normal()
                    await self._set_runtime_mode("global_gate", "GLOBAL GATE")
                    await self._set_runtime_reason(
                        self._with_isolation_notice(
                            gate_reason
                            or "Global gate is blocking automation, so outputs were moved to a safe state."
                        )
                    )
                else:
                    await self._set_runtime_mode("global_gate", "GLOBAL GATE")
                    await self._set_runtime_reason(
                        self._with_isolation_notice(
                            gate_reason
                            or "Global gate is blocking automation; no output changes were applied."
                        )
                    )
                return
            if self._pause_active():
                await self._return_to_normal()
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        "Pause is active, so automation is temporarily standing down."
                    )
                )
                return

            # Top-priority lane: CO emergency.
            if self._co_emergency_triggered():
                await self._apply_co_emergency()
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        "CO emergency protection is active, so all configured ventilation outputs are forced to 100%."
                    )
                )
                return
            if self._co_emergency_active and self._co_clear_ready():
                self._co_emergency_active = False
                self._co_below_since = None
            await self._set_bool("air_co_emergency_active", self._co_emergency_active)

            # Alert lane is high priority and suppresses all lower lanes.
            alert_active, alert_labels = await self._handle_alerts()
            if alert_active:
                await self._deactivate_non_alert_activity()
                await self._set_runtime_mode("alert", "ALERT")
                await self._set_runtime_reason(
                    self._with_isolation_notice(
                        self._build_runtime_reason(
                            runtime_mode="alert",
                            alert_labels=alert_labels,
                            zone1_active=False,
                            zone2_active=False,
                            aq_active=False,
                            zone1_detail=None,
                            zone2_detail=None,
                            aq_details=[],
                            humidifier_details=[],
                        )
                    )
                )
                return

            # Humidifiers are independent from zone/AQ lane order.
            humidifier_details = await self._handle_humidifiers()

            # Requested lane order: zone1 -> zone2 -> AQ.
            zone1_active, zone1_mode, zone1_detail = await self._handle_zone_by_key("zone1")
            zone2_active, zone2_mode, zone2_detail = await self._handle_zone_by_key("zone2")
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
                        alert_labels=alert_labels,
                        zone1_active=zone1_active,
                        zone2_active=zone2_active,
                        aq_active=aq_active,
                        zone1_detail=zone1_detail,
                        zone2_detail=zone2_detail,
                        aq_details=aq_details,
                        humidifier_details=humidifier_details,
                    )
                )
            )
        except Exception:
            _LOGGER.exception("Unhandled error in HI automation evaluation cycle")
        finally:
            self._refresh_core_entities()

    def _control_lock_reason(self) -> Optional[str]:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        if booleans.get("air_control_enabled") and not booleans["air_control_enabled"].is_on:
            return "System control is disabled, so all automation lanes are idle."
        if booleans.get("air_control_manual_override") and booleans["air_control_manual_override"].is_on:
            return "Manual override is enabled, so HI automation is standing down."
        return None

    def _gate_status(self) -> Tuple[bool, Optional[str]]:
        if self.time_gate.get("enabled"):
            now = datetime.now().time()
            start = _parse_time(self.time_gate.get("start"))
            end = _parse_time(self.time_gate.get("end"))
            if start and end:
                in_window = _time_in_window(now, start, end)
                if not in_window:
                    action = self.time_gate.get("outside_action", "no_action")
                    if action == "no_action":
                        return True, None
                    return (
                        False,
                        f"Time gate is outside {start.strftime('%H:%M')} - {end.strftime('%H:%M')}; action '{action}' is active.",
                    )
        if self.presence_gate.get("enabled"):
            entities = self.presence_gate.get("entities", [])
            present_states = set(self.presence_gate.get("present_states", []))
            away_states = set(self.presence_gate.get("away_states", []))
            if entities and present_states:
                for entity_id in entities:
                    state = self.hass.states.get(entity_id)
                    if not state:
                        continue
                    if state.state in present_states:
                        return True, None
                    if away_states and state.state in away_states:
                        continue
                return (
                    False,
                    f"Presence gate is active (no entity in present states). Snapshot: {self._presence_snapshot(entities)}.",
                )
        return True, None

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
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        timers = data.get("hi_timers", {})
        for entity in booleans.values():
            entity_id = getattr(entity, "entity_id", None)
            if entity_id:
                sources.append(entity_id)
        for entity in timers.values():
            entity_id = getattr(entity, "entity_id", None)
            if entity_id:
                sources.append(entity_id)
        return sorted(set(sources))

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
            return False
        if all(val < clear_threshold for val in co_values):
            if not self._co_below_since:
                self._co_below_since = datetime.now()
            return datetime.now() - self._co_below_since >= timedelta(minutes=2)
        self._co_below_since = None
        return False

    async def _apply_co_emergency(self) -> None:
        _, _, outputs = self._co_emergency_settings()
        await self._deactivate_aq_activity(set_fan_auto=False)
        await self._deactivate_humidifier_activity(turn_off_outputs=True)
        await self._clear_alert_activity_switches()
        await self._set_bool("air_co_emergency_active", True)
        all_outputs = self._all_fan_outputs()
        outputs_to_auto = [entity_id for entity_id in all_outputs if entity_id not in outputs]
        await self._set_fan_outputs_auto(outputs_to_auto)
        await self._set_fan_outputs_level(outputs, "100")
        await self._set_runtime_mode("co_emergency", "CO EMERGENCY")

    async def _handle_alerts(self) -> Tuple[bool, List[str]]:
        any_active = False
        active_labels: List[str] = []
        for idx in range(max(len(self.alerts), 5)):
            await self._set_bool(self._alert_switch_key(idx), False)
        for idx, alert in enumerate(self.alerts):
            if not alert.get("enabled", True):
                continue
            triggered = self._alert_triggered(alert)
            await self._set_bool(self._alert_switch_key(idx), triggered)
            if not triggered:
                continue
            any_active = True
            active_labels.append(self._alert_label(idx, alert))
            last = self._last_alert.get(idx)
            if last and datetime.now() - last < timedelta(seconds=30):
                continue
            self._last_alert[idx] = datetime.now()
            try:
                await self.hass.services.async_call(
                    DOMAIN,
                    SERVICE_FLASH_LIGHTS,
                    {
                        "power_entity": alert.get("power_entity"),
                        "lights": alert.get("lights", []),
                        "color": (255, 0, 0) if alert.get("flash_mode") == "red" else (255, 255, 255),
                        "duration": alert.get("duration", 10),
                    },
                    blocking=False,
                )
            except Exception:
                _LOGGER.exception("Alert flash service call failed for alert index %s", idx)
        return any_active, active_labels

    def _alert_triggered(self, alert: Dict[str, Any]) -> bool:
        ttype = alert.get("trigger_type")
        if ttype == "custom_binary":
            entity_id = alert.get("custom_trigger")
            if entity_id:
                return self.hass.states.is_state(entity_id, "on")
        if ttype == "condensation_danger":
            return self.hass.states.is_state("binary_sensor.hi_condensation_danger", "on")
        if ttype == "mould_danger":
            return self.hass.states.is_state("binary_sensor.hi_mould_danger", "on")
        if ttype == "humidity_danger":
            threshold = _safe_alert_threshold("humidity_danger", alert.get("threshold"), 75.0)
            values = self._collect_values("humidity")
            return any(val >= threshold for val in values)
        if ttype == "co_emergency":
            threshold = _safe_alert_threshold("co_emergency", alert.get("threshold"), float(CO_EMERGENCY_START))
            values = self._collect_values("co")
            return any(val >= threshold for val in values)
        return False

    async def _handle_zone_by_key(self, zone_key: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        zone = self.zones.get(zone_key, {})
        if not zone.get("enabled"):
            return False, None, None

        triggers = zone.get("triggers", [])
        level = zone.get("level")
        outputs = zone.get("outputs", [])
        if not triggers or not outputs:
            return False, None, None

        run_level, trigger_details = self._zone_trigger_level(triggers, zone, level)
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
            },
        )

    def _zone_trigger_level(self, triggers: List[str], zone: Dict[str, Any], level: Optional[str]) -> Tuple[Optional[str], List[str]]:
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
            elif trig == "air_quality_bad":
                iaq = self._level_avg("iaq", level)
                threshold_val = _to_float(threshold)
                if iaq is not None and threshold_val is not None and iaq <= threshold_val:
                    selected_level = _max_fan_level(selected_level, normal_level)
                    trigger_details.append(f"IAQ {iaq:.1f} <= threshold {threshold_val:g}")
            elif trig == "condensation_risk":
                spread = self._worst_spread()
                threshold_val = _to_float(threshold)
                if spread is not None and threshold_val is not None and spread <= threshold_val:
                    selected_level = _max_fan_level(selected_level, boost_level)
                    trigger_details.append(
                        f"Dew-point spread {spread:.1f} degC <= threshold {threshold_val:g} degC"
                    )
            elif trig == "mould_risk":
                risk_level = self._worst_mould_level()
                threshold_val = _to_float(threshold)
                if threshold_val is not None and risk_level >= threshold_val:
                    selected_level = _max_fan_level(selected_level, boost_level)
                    trigger_details.append(
                        f"Mould risk level {risk_level} >= threshold {threshold_val:g}"
                    )
        return selected_level, trigger_details

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
            trigger_details = self._aq_trigger_details(level, cfg)
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
                    "triggers": trigger_details
                    or ["AQ run window is still active from a recent trigger."],
                })
        return active, active_details

    def _aq_trigger_details(self, level: str, cfg: Dict[str, Any]) -> List[str]:
        details: List[str] = []
        triggers = cfg.get("triggers", [])
        thresholds = cfg.get("thresholds", {})
        for trig in triggers:
            threshold = thresholds.get(trig)
            if trig == "iaq_bad":
                val = self._level_avg("iaq", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val <= threshold_val:
                    details.append(f"IAQ {val:.1f} <= threshold {threshold_val:g}")
            if trig == "pm25_high":
                val = self._level_avg("pm25", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"PM2.5 {val:.1f} >= threshold {threshold_val:g}")
            if trig == "voc_bad":
                val = self._level_avg("voc", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"VOC {val:.1f} >= threshold {threshold_val:g}")
            if trig == "co2_high":
                val = self._level_avg("co2", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"CO2 {val:.1f} >= threshold {threshold_val:g}")
            if trig == "co_warning":
                val = self._level_avg("co", level)
                threshold_val = _to_float(threshold)
                if val is not None and threshold_val is not None and val >= threshold_val:
                    details.append(f"CO {val:.1f} >= threshold {threshold_val:g}")
        return details

    async def _start_aq(self, level: str, cfg: Dict[str, Any]) -> None:
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
            await asyncio.sleep(duration)
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

        self._aq_tasks[level] = asyncio.create_task(_timer())

    async def _handle_humidifiers(self) -> List[Dict[str, Any]]:
        active_details: List[Dict[str, Any]] = []
        configured_levels = set(self.humidifiers.keys())
        for level in ("level1", "level2"):
            if level in configured_levels:
                continue
            await self._set_bool(self._humidifier_active_key(level), False)

        for level, cfg in self.humidifiers.items():
            active_key = self._humidifier_active_key(level)
            outputs = cfg.get("outputs", [])
            if not cfg.get("enabled"):
                await self._set_humidifier_outputs_state(outputs, False)
                await self._set_bool(active_key, False)
                continue
            if not outputs:
                await self._set_bool(active_key, False)
                continue
            avg = self._level_avg("humidity", level)
            if avg is None:
                await self._set_bool(active_key, False)
                continue
            band_adjust = _to_float(cfg.get("band_adjust", 0))
            if band_adjust is None:
                band_adjust = 0.0
            recovery_in_band = _to_float(cfg.get("recovery_in_band", HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT))
            if recovery_in_band is None:
                recovery_in_band = float(HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT)
            recovery_in_band = max(1.0, min(8.0, recovery_in_band))
            low = _target_low() + band_adjust
            high = _target_high() + band_adjust
            recovery_off = min(high, low + recovery_in_band)
            currently_active = self._bool_is_on(active_key)
            if avg <= low:
                if not currently_active:
                    await self._set_humidifier_outputs_state(outputs, True)
                    await self._set_bool(active_key, True)
                active_details.append({
                    "level": level,
                    "humidity": avg,
                    "low": low,
                    "high": high,
                    "recovery_off": recovery_off,
                    "outputs": outputs,
                })
            elif avg >= recovery_off:
                if currently_active:
                    await self._set_humidifier_outputs_state(outputs, False)
                    await self._set_bool(active_key, False)
            else:
                if currently_active:
                    active_details.append({
                        "level": level,
                        "humidity": avg,
                        "low": low,
                        "high": high,
                        "recovery_off": recovery_off,
                        "outputs": outputs,
                    })
        return active_details

    async def _return_to_normal(self) -> None:
        await self._clear_alert_activity_switches()
        await self._set_zone_outputs_auto()
        await self._deactivate_aq_activity(set_fan_auto=True)
        await self._deactivate_humidifier_activity(turn_off_outputs=True)
        await self._set_runtime_mode("normal", "NORMAL")
        await self._set_runtime_reason(
            self._with_isolation_notice(
                "All lanes are idle, so outputs have returned to normal automatic behavior."
            )
        )

    async def _deactivate_non_alert_activity(self) -> None:
        await self._deactivate_aq_activity(set_fan_auto=True)
        await self._set_zone_outputs_auto()
        await self._deactivate_humidifier_activity(turn_off_outputs=True)

    async def _deactivate_humidifier_activity(self, *, turn_off_outputs: bool) -> None:
        for cfg in self.humidifiers.values():
            outputs = cfg.get("outputs", [])
            if turn_off_outputs:
                await self._set_humidifier_outputs_state(outputs, False)
        await self._set_bool("air_downstairs_humidifier_active", False)
        await self._set_bool("air_upstairs_humidifier_active", False)

    async def _deactivate_aq_activity(self, *, set_fan_auto: bool) -> None:
        for level, task in list(self._aq_tasks.items()):
            if task and not task.done():
                task.cancel()
            self._aq_tasks.pop(level, None)

        for cfg in self.aq.values():
            outputs = cfg.get("outputs", [])
            if set_fan_auto:
                await self._set_fan_outputs_auto(outputs)
        self._aq_trigger_active = {}
        await self._set_bool("air_aq_upstairs_active", False)
        await self._set_bool("air_aq_downstairs_active", False)
        await self._clear_timer("air_aq_upstairs_run")
        await self._clear_timer("air_aq_downstairs_run")

    async def _clear_alert_activity_switches(self) -> None:
        for idx in range(max(len(self.alerts), 5)):
            await self._set_bool(self._alert_switch_key(idx), False)

    async def _cancel_aq_task(self, level: str) -> None:
        task = self._aq_tasks.pop(level, None)
        if task and not task.done():
            task.cancel()
        self._aq_trigger_active[level] = False

    def _alert_switch_key(self, idx: int) -> str:
        return f"air_alert_{idx + 1}_active"

    def _alert_label(self, idx: int, alert: Dict[str, Any]) -> str:
        trigger_type = str(alert.get("trigger_type") or "unknown")
        trigger_label = ALERT_TRIGGER_DEFS.get(trigger_type, {}).get(
            "label",
            trigger_type.replace("_", " ").title(),
        )
        threshold = alert.get("threshold")
        threshold_suffix = ""
        if threshold not in (None, "") and trigger_type in {"humidity_danger", "co_emergency"}:
            default_threshold = 75.0 if trigger_type == "humidity_danger" else float(CO_EMERGENCY_START)
            threshold = _safe_alert_threshold(trigger_type, threshold, default_threshold)
            threshold_suffix = f" @ {threshold}"
        return f"Alert {idx + 1}: {trigger_label}{threshold_suffix}"

    def _build_runtime_reason(
        self,
        *,
        runtime_mode: str,
        alert_labels: List[str],
        zone1_active: bool,
        zone2_active: bool,
        aq_active: bool,
        zone1_detail: Optional[Dict[str, Any]],
        zone2_detail: Optional[Dict[str, Any]],
        aq_details: List[Dict[str, Any]],
        humidifier_details: List[Dict[str, Any]],
    ) -> str:
        if runtime_mode == "alert" and alert_labels:
            return (
                f"Alert response is active ({'; '.join(alert_labels)}). "
                "All other lanes are paused until the alert clears."
            )
        if runtime_mode == "cooking":
            if zone1_detail:
                zone_label = zone1_detail.get("ui_label") or "Zone 1"
                return self._format_zone_detail(zone1_detail, str(zone_label))
            return "Zone 1 extraction is active."
        if runtime_mode == "bathroom":
            if zone2_detail:
                zone_label = zone2_detail.get("ui_label") or "Zone 2"
                return self._format_zone_detail(zone2_detail, str(zone_label))
            return "Zone 2 extraction is active."
        if runtime_mode == "air_quality" and aq_active:
            return self._format_aq_detail(aq_details)
        if humidifier_details:
            return self._format_humidifier_detail(humidifier_details)
        house_humidity = self._level_avg("humidity", None)
        if house_humidity is not None:
            return (
                f"System is armed and monitoring telemetry. "
                f"Current house humidity is {house_humidity:.1f}% and no lane currently needs to run."
            )
        return "System is armed and monitoring telemetry. No automation lane currently needs to run."

    def _format_zone_detail(self, detail: Dict[str, Any], zone_label: str) -> str:
        outputs = self._format_output_entities(detail.get("outputs", []))
        run_level = _fan_level_text(detail.get("output_level"))
        trigger_summary = "; ".join(detail.get("triggers", [])) or "configured trigger condition met"
        return (
            f"{zone_label} is active at {run_level} on {outputs}. "
            f"Trigger detail: {trigger_summary}."
        )

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
        segments: List[str] = []
        for item in details:
            level = "Downstairs" if item.get("level") == "level1" else "Upstairs"
            humidity = item.get("humidity")
            low = item.get("low")
            high = item.get("high")
            recovery_off = item.get("recovery_off")
            outputs = self._format_output_entities(item.get("outputs", []))
            if humidity is None:
                segments.append(f"{level} humidifier is active on {outputs}.")
                continue
            segments.append(
                f"{level} humidifier is active on {outputs}. "
                f"Humidity is {humidity:.1f}% (target band {low:.1f}% - {high:.1f}%, off threshold {recovery_off:.1f}%)."
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
        configured_outputs: List[str] = []
        configured_thresholds: List[float] = []

        for alert in self.alerts:
            if not alert.get("enabled", True):
                continue
            if alert.get("trigger_type") != "co_emergency":
                continue
            threshold = _safe_alert_threshold("co_emergency", alert.get("threshold"), float(CO_EMERGENCY_START))
            configured_thresholds.append(threshold)
            for entity_id in alert.get("outputs", []) or []:
                if not isinstance(entity_id, str):
                    continue
                if entity_id.startswith("fan.") or entity_id.startswith("switch."):
                    configured_outputs.append(entity_id)

        if configured_thresholds:
            start_threshold = min(configured_thresholds)

        clear_threshold = max(0.0, start_threshold - 5.0)
        if clear_threshold >= start_threshold:
            clear_threshold = max(0.0, start_threshold - 1.0)

        if configured_outputs:
            seen: set[str] = set()
            outputs: List[str] = []
            for entity_id in configured_outputs:
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                outputs.append(entity_id)
            return start_threshold, clear_threshold, outputs

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

    async def _set_runtime_reason(self, reason: str) -> None:
        data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
        data["runtime_reason"] = reason

    def _bool_is_on(self, key: str) -> bool:
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        booleans = data.get("hi_input_booleans", {})
        entity = booleans.get(key)
        return bool(entity and getattr(entity, "is_on", False))

    def _fan_outputs_isolated(self) -> bool:
        return self._bool_is_on("air_isolate_fan_outputs")

    def _humidifier_outputs_isolated(self) -> bool:
        return self._bool_is_on("air_isolate_humidifier_outputs")

    async def _set_fan_outputs_level(self, outputs: List[str], level: Any) -> None:
        if self._fan_outputs_isolated():
            return
        await _apply_fan_level(self.hass, outputs, level)

    async def _set_fan_outputs_auto(self, outputs: List[str]) -> None:
        if self._fan_outputs_isolated():
            return
        await _set_fan_auto(self.hass, outputs)

    async def _set_humidifier_outputs_state(self, outputs: List[str], on: bool) -> None:
        if self._humidifier_outputs_isolated():
            return
        await _set_humidifier_state(self.hass, outputs, on)

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

    def _collect_values(self, sensor_type: str) -> List[float]:
        values: List[float] = []
        for item in self.telemetry:
            if item.get("sensor_type") != sensor_type:
                continue
            val = _get_float(self.hass, item.get("entity_id"))
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
            val = _get_float(self.hass, item.get("entity_id"))
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
            val = _get_float(self.hass, item.get("entity_id"))
            if val is not None:
                vals.append(val)
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    def _worst_spread(self) -> Optional[float]:
        spreads: List[float] = []
        rooms = _room_map(self.telemetry)
        for room, sensors in rooms.items():
            rh = _get_float(self.hass, sensors.get("humidity"))
            temp = _get_float(self.hass, sensors.get("temperature"))
            if rh is None or temp is None:
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spreads.append(temp - dp)
        return min(spreads) if spreads else None

    def _worst_mould_level(self) -> int:
        rooms = _room_map(self.telemetry)
        level = 0
        for room, sensors in rooms.items():
            rh = _get_float(self.hass, sensors.get("humidity"))
            temp = _get_float(self.hass, sensors.get("temperature"))
            if rh is None or temp is None:
                continue
            dp = _dew_point(temp, rh)
            if dp is None:
                continue
            spread = temp - dp
            risk = _mould_level(rh, spread)
            level = max(level, risk)
        return level


def _get_float(hass: HomeAssistant, entity_id: Optional[str]) -> Optional[float]:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


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


def _mould_level(rh: float, spread: float) -> int:
    level = 0
    if rh >= 75:
        level += 2
    elif rh >= 68:
        level += 1
    if spread <= 2:
        level += 2
    elif spread <= 4:
        level += 1
    return min(level, 3)


def _target_low() -> float:
    month = datetime.now().month
    if month in (11, 12, 1, 2, 3):
        return 45
    if month in (6, 7, 8):
        return 51
    return 47


def _target_high() -> float:
    month = datetime.now().month
    if month in (11, 12, 1, 2, 3):
        return 55
    if month in (6, 7, 8):
        return 60
    return 58


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


async def _apply_fan_level(hass: HomeAssistant, entities: List[str], level: Any) -> None:
    normalized = _normalize_fan_level(level, ZONE_OUTPUT_LEVEL_DEFAULT)
    if normalized == FAN_OUTPUT_LEVEL_AUTO:
        await _set_fan_auto(hass, entities)
        return
    await _set_fan_percentage(hass, entities, int(normalized))


def _coerce_fan_percentage(value: Any) -> int:
    pct = _bounded_int(value, 0, 100, ZONE_OUTPUT_LEVEL_DEFAULT)
    if pct <= 0:
        return 0
    if pct >= 100:
        return 100
    return min(FAN_OUTPUT_LEVEL_STEPS, key=lambda step: abs(step - pct))


async def _set_fan_percentage(hass: HomeAssistant, entities: List[str], pct: int) -> None:
    pct = _coerce_fan_percentage(pct)
    for entity_id in entities:
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
                    await hass.services.async_call("fan", "turn_on", {"entity_id": entity_id}, blocking=False)
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
                await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=False)
            except Exception:
                _LOGGER.exception("Failed to set switch %s via %s", entity_id, service)


async def _set_fan_auto(hass: HomeAssistant, entities: List[str]) -> None:
    for entity_id in entities:
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
                await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=False)
            except Exception:
                _LOGGER.exception("Failed to turn off switch %s", entity_id)


async def _set_humidifier_state(hass: HomeAssistant, entities: List[str], on: bool) -> None:
    for entity_id in entities:
        domain = entity_id.split(".")[0]
        service = "turn_on" if on else "turn_off"
        if not hass.services.has_service(domain, service):
            continue
        state = hass.states.get(entity_id)
        if state and ((on and state.state == "on") or ((not on) and state.state == "off")):
            continue
        try:
            await hass.services.async_call(domain, service, {"entity_id": entity_id}, blocking=False)
        except Exception:
            _LOGGER.exception("Failed to call %s.%s for %s", domain, service, entity_id)


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
        threshold = default_value
    return max(min_value, min(max_value, threshold))
