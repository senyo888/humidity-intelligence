"""Diagnostics-only Stability Score helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from statistics import median
from typing import Any, Iterable, Optional

from .air_quality import capture_configured_aq_evidence


WINDOW_HOURS = 72
BUCKET_MINUTES = 10
EXPECTED_SAMPLES = WINDOW_HOURS * 60 // BUCKET_MINUTES
MINIMUM_COVERAGE_RATIO = 0.70
MINIMUM_VALID_SAMPLES = ceil(EXPECTED_SAMPLES * MINIMUM_COVERAGE_RATIO)
COMPONENT_MINIMUM_COVERAGE_RATIO = 0.70
DRIFT_ACCEPTABLE_ABS_RH = 5.0
RISK_CAP_WINDOW_HOURS = 24
DANGER_CAP_WINDOW_HOURS = 12
RISK_CAP_EXPECTED_SAMPLES = RISK_CAP_WINDOW_HOURS * 60 // BUCKET_MINUTES
DIRECTIONAL_LED_STEPS_TOTAL = 360
DIRECTIONAL_LED_STEPS_PER_SIDE = 360
DIRECTIONAL_STRONG_RATE_POINTS_PER_10_MINUTES = 5.0
DIRECTIONAL_LED_STEPS_PER_POINT = 3.6
AQ_COMPONENT_MINIMUM_COVERAGE_RATIO = 0.70
AQ_EVIDENCE_PENALTY_MAX_POINTS = 3.0
SCORE_WEIGHTS = {
    "target_adherence": 0.30,
    "volatility": 0.15,
    "balance": 0.15,
    "risk_clearance": 0.15,
    "air_quality_clearance": 0.15,
    "recovery": 0.10,
}
NON_AQ_WEIGHT_TOTAL = 1.0 - SCORE_WEIGHTS["air_quality_clearance"]
MISSING_DATA_POLICY = "unavailable_below_threshold_penalized_above_threshold"
SNAPSHOT_MINUTES_UTC = (0, 10, 20, 30, 40, 50)
SNAPSHOT_SOURCE = "hi_owned_fixed_bucket"
SNAPSHOT_SCHEDULE = "utc_ten_minute"
SNAPSHOT_REPRESENTATIVE = "last_complete_scheduled_observation"
SNAPSHOT_LATE_GRACE_SECONDS = 60
SNAPSHOT_INVALID_REASONS = {
    "required_telemetry_unavailable",
    "house_humidity_missing",
    "house_humidity_invalid",
    "target_bounds_missing",
    "target_bounds_invalid",
    "condensation_state_invalid",
    "mould_state_invalid",
}

STATE_VALUES = {
    "OK": 1.0,
    "Watch": 0.75,
    "Risk": 0.25,
    "Danger": 0.0,
}

CONTROL_CONTRACT = {
    "runtime_control_changed_by_stability_score": False,
    "lane_selection_input": False,
    "output_write_input": False,
    "dashboard_inference_allowed": False,
}

SUPPRESSION_MESSAGES = {
    "coverage_below_threshold": "Stability Score collecting: fewer than 303 valid HI-owned 10-minute snapshots in the last 72 hours.",
    "current_telemetry_unavailable": (
        "Stability Score unavailable: required live telemetry is unavailable. "
        "Historic window coverage is not used while HI is standing down."
    ),
    "insufficient_consecutive_samples": "Stability Score unavailable: incomplete evidence from gaps between consecutive 10-minute snapshots in the last 72 hours.",
    "insufficient_balance_sources": "Stability Score unavailable: incomplete balance-source evidence in the last 72 hours.",
}


@dataclass(frozen=True)
class StabilitySnapshot:
    observed_at: datetime
    house_humidity: Optional[float]
    target_low: Optional[float]
    target_high: Optional[float]
    worst_condensation_state: str
    worst_mould_state: str
    room_or_level_humidity_spread: Optional[float]
    house_humidity_drift_7d: Optional[float]
    runtime_mode: str
    required_telemetry_available: bool
    balance_scope: Optional[str] = None
    balance_source_count: int = 0
    air_quality_clearance: Optional[float] = None
    air_quality_configured_condition_count: int = 0
    air_quality_evaluated_condition_count: int = 0
    air_quality_bad_condition_count: int = 0
    air_quality_telemetry_source_count: int = 0
    air_quality_source_count: int = 0
    air_quality_available_source_count: int = 0
    air_quality_unit_invalid_source_count: int = 0
    air_quality_invalid_threshold_count: int = 0
    air_quality_bad_trigger_codes: tuple[str, ...] = ()
    co_emergency_active: bool = False


class StabilitySnapshotRing:
    """In-memory fixed-bucket ring for diagnostics-only Stability Score input."""

    def __init__(self, *, window_hours: int = WINDOW_HOURS) -> None:
        self._window = timedelta(hours=window_hours)
        self._bucket = timedelta(minutes=BUCKET_MINUTES)
        self._buckets: dict[datetime, StabilitySnapshot] = {}

    def add(self, sample: StabilitySnapshot) -> bool:
        bucket = bucket_start_for(sample.observed_at)
        existing = self._buckets.get(bucket)
        if not _valid_sample(sample):
            self._prune(sample.observed_at)
            return False
        if existing is None or sample.observed_at >= existing.observed_at:
            self._buckets[bucket] = sample
        self._prune(sample.observed_at)
        return True

    def samples(self) -> list[StabilitySnapshot]:
        return [self._buckets[key] for key in sorted(self._buckets)]

    def prune(self, observed_at: datetime) -> None:
        """Remove buckets that are outside the window at an observed UTC time."""
        self._prune(observed_at)

    def _prune(self, observed_at: datetime) -> None:
        latest_bucket = bucket_start_for(observed_at)
        cutoff = latest_bucket - self._window + self._bucket
        for bucket in list(self._buckets):
            if bucket < cutoff:
                self._buckets.pop(bucket, None)


def bucket_start_for(observed_at: datetime) -> datetime:
    observed_at = _as_utc(observed_at)
    minute = observed_at.minute - (observed_at.minute % BUCKET_MINUTES)
    return observed_at.replace(minute=minute, second=0, microsecond=0)


def next_bucket_boundary_after(observed_at: datetime) -> datetime:
    """Return the first fixed bucket boundary strictly after an observation."""
    return bucket_start_for(observed_at) + timedelta(minutes=BUCKET_MINUTES)


def crossed_bucket_count(scheduled_at: datetime, observed_at: datetime) -> int:
    """Count scheduled bucket boundaries missed before a late callback wakes."""
    scheduled_at = _as_utc(scheduled_at)
    observed_at = _as_utc(observed_at)
    if observed_at < scheduled_at:
        return 1
    bucket_seconds = BUCKET_MINUTES * 60
    return int((observed_at - scheduled_at).total_seconds() // bucket_seconds) + 1


def evaluate_stability_window(
    samples: Iterable[StabilitySnapshot],
    *,
    current_runtime_mode: str = "normal",
    current_condensation_state: Optional[str] = None,
    current_mould_state: Optional[str] = None,
    current_air_quality_bad: Optional[bool] = None,
    current_air_quality_evidence_available: Optional[bool] = None,
    current_co_emergency: Optional[bool] = None,
    current_required_inputs_available: Optional[bool] = None,
    current_invalid_reasons: Optional[Iterable[str]] = None,
    observed_at: Optional[datetime] = None,
) -> dict[str, Any]:
    ordered = _windowed_samples(samples, observed_at=observed_at)
    valid = [sample for sample in ordered if _valid_sample(sample)]
    coverage_ratio = round(min(1.0, len(valid) / EXPECTED_SAMPLES), 4)
    base = _base_payload(len(valid), coverage_ratio)
    live_invalid_reasons = [
        str(reason)
        for reason in (current_invalid_reasons or [])
        if str(reason) in SNAPSHOT_INVALID_REASONS
    ]
    base["live_truth"] = {
        "required_inputs_available": current_required_inputs_available,
        "invalid_reasons": live_invalid_reasons[:5],
    }

    if (
        current_runtime_mode == "telemetry_unavailable"
        or current_required_inputs_available is False
    ):
        return _unavailable(base, "suppressed", "current_telemetry_unavailable")
    if len(valid) < MINIMUM_VALID_SAMPLES or coverage_ratio < MINIMUM_COVERAGE_RATIO:
        return _unavailable(base, "insufficient_coverage", "coverage_below_threshold")

    volatility, volatility_coverage = _volatility_score(valid)
    if volatility is None:
        base["component_coverage"] = {
            "volatility": volatility_coverage,
            "balance": _balance_coverage(valid),
            "drift": _drift_coverage(valid),
            "air_quality": _air_quality_coverage(valid),
        }
        return _unavailable(base, "suppressed", "insufficient_consecutive_samples")
    balance, balance_coverage = _balance_score(valid)
    if balance is None:
        base["component_coverage"] = {
            "volatility": volatility_coverage,
            "balance": balance_coverage,
            "drift": _drift_coverage(valid),
            "air_quality": _air_quality_coverage(valid),
        }
        return _unavailable(base, "suppressed", "insufficient_balance_sources")

    target_adherence = _target_adherence(valid)
    drift_coverage = _drift_coverage(valid)
    drift_available = drift_coverage["status"] == "available"
    risk_clearance, risk_clearance_components = _risk_clearance_score(
        valid,
        include_drift=drift_available,
    )
    air_quality_clearance, air_quality_coverage = _air_quality_score(valid)
    air_quality_available = air_quality_coverage["status"] in {"complete", "partial"}
    latest = valid[-1]
    if current_air_quality_bad is None:
        current_air_quality_bad = latest.air_quality_bad_condition_count > 0
    if current_air_quality_evidence_available is None:
        current_air_quality_evidence_available = (
            latest.air_quality_configured_condition_count > 0
            and latest.air_quality_evaluated_condition_count
            == latest.air_quality_configured_condition_count
        )
    if current_co_emergency is None:
        current_co_emergency = latest.co_emergency_active
    current_air_quality_evidence_available = bool(
        current_air_quality_evidence_available and air_quality_available
    )
    recovery, recovery_details = _recovery_score(valid)
    non_aq_weighted_score = (
        SCORE_WEIGHTS["target_adherence"] * target_adherence
        + SCORE_WEIGHTS["volatility"] * volatility
        + SCORE_WEIGHTS["balance"] * balance
        + SCORE_WEIGHTS["risk_clearance"] * risk_clearance
        + SCORE_WEIGHTS["recovery"] * recovery
    )
    if air_quality_available and air_quality_clearance is not None:
        raw_score = 100 * (
            non_aq_weighted_score
            + SCORE_WEIGHTS["air_quality_clearance"] * air_quality_clearance
        )
        score_basis = "full_environmental"
        air_quality_evidence_penalty = min(
            AQ_EVIDENCE_PENALTY_MAX_POINTS,
            round((1 - float(air_quality_coverage["coverage_ratio"])) * 10, 2),
        )
    else:
        raw_score = 100 * (non_aq_weighted_score / NON_AQ_WEIGHT_TOTAL)
        score_basis = "non_aq_renormalized"
        air_quality_evidence_penalty = AQ_EVIDENCE_PENALTY_MAX_POINTS
    coverage_penalty = round((1 - coverage_ratio) * 10, 2)
    drift_penalty = 3.0 if not drift_available else 0.0
    additional_penalty = drift_penalty + air_quality_evidence_penalty
    window_score = round(
        _clamp(raw_score - coverage_penalty - additional_penalty, 0.0, 100.0),
        2,
    )
    raw_score = round(raw_score, 2)
    raw_classification = _classification(round(raw_score))
    window_classification = _classification(round(window_score))
    caps = _classification_caps(
        valid,
        window_classification,
        current_condensation_state=current_condensation_state,
        current_mould_state=current_mould_state,
        current_air_quality_bad=bool(current_air_quality_bad),
        current_air_quality_evidence_available=bool(
            current_air_quality_evidence_available
        ),
        current_co_emergency=bool(current_co_emergency),
        observed_at=observed_at,
    )
    uncapped_display_score = int(round(window_score))
    score_cap_ceiling = caps.get("score_cap_ceiling")
    display_score = (
        min(uncapped_display_score, int(score_cap_ceiling))
        if caps["cap_condition_active"] and score_cap_ceiling is not None
        else uncapped_display_score
    )
    display_classification = _classification(display_score)
    caps["score_cap_applied"] = display_score != uncapped_display_score
    caps["uncapped_display_score"] = uncapped_display_score
    caps["display_classification"] = display_classification
    message = _available_message(
        display_score=display_score,
        display_classification=display_classification,
        window_score=window_score,
        caps=caps,
        coverage_penalty=coverage_penalty,
        drift_penalty=drift_penalty,
        air_quality_evidence_penalty=air_quality_evidence_penalty,
    )
    base.update(
        {
            "availability": "available",
            "message": message,
            "score": {
                "raw_score": raw_score,
                "raw_classification": raw_classification,
                "window_score": window_score,
                "window_classification": window_classification,
                "display_score": display_score,
                "display_classification": display_classification,
                "score_status": "available",
                "suppression_reason": None,
            },
            "subscores": {
                "target_adherence": round(target_adherence, 4),
                "volatility_score": round(volatility, 4),
                "balance_score": round(balance, 4),
                "risk_clearance_score": round(risk_clearance, 4),
                "risk_clearance_components": risk_clearance_components,
                "air_quality_clearance_score": round(air_quality_clearance, 4)
                if air_quality_clearance is not None
                else None,
                "recovery_score": round(recovery, 4),
            },
            "caps": caps,
            "component_coverage": {
                "volatility": volatility_coverage,
                "balance": balance_coverage,
                "drift": drift_coverage,
                "air_quality": air_quality_coverage,
            },
            "penalties": {
                "coverage_penalty_points": coverage_penalty,
                "drift_unavailable_penalty_points": drift_penalty,
                "air_quality_evidence_penalty_points": air_quality_evidence_penalty,
                "additional_penalty_points": additional_penalty,
            },
            "score_basis": score_basis,
            "environmental_evidence": air_quality_coverage["status"],
            "drift_component_status": "unavailable_penalized"
            if not drift_available
            else "available",
            "recovery": recovery_details,
        }
    )
    base["presentation"] = _available_presentation(
        display_score,
        display_classification,
        message,
        cap_applied=bool(caps["score_cap_applied"]),
        partial_evidence=air_quality_coverage["status"] != "complete",
        condition_truth_active=(
            caps.get("headline_cap_reason")
            not in {None, "air_quality_evidence_incomplete"}
        ),
    )
    return base


def stability_diagnostics_payload(
    runtime_data: dict[str, Any],
    *,
    observed_at: Optional[datetime] = None,
) -> dict[str, Any]:
    ring = runtime_data.get("stability_snapshot_ring") if isinstance(runtime_data, dict) else None
    samples = ring.samples() if hasattr(ring, "samples") else []
    current_condensation_state = _runtime_risk_state(
        runtime_data,
        "worst_condensation_risk",
    )
    current_mould_state = _runtime_risk_state(
        runtime_data,
        "worst_mould_risk",
    )
    current_air_quality = _runtime_air_quality_truth(runtime_data)
    current_runtime_mode = (
        str(runtime_data.get("runtime_mode") or "normal")
        if isinstance(runtime_data, dict)
        else "normal"
    )
    live_invalid_reasons = _runtime_live_invalid_reasons(runtime_data)
    payload = evaluate_stability_window(
        samples,
        current_runtime_mode=current_runtime_mode,
        current_condensation_state=current_condensation_state,
        current_mould_state=current_mould_state,
        current_air_quality_bad=current_air_quality.get("crossed_trigger_count", 0) > 0
        if current_air_quality
        else None,
        current_air_quality_evidence_available=(
            current_air_quality.get("configured_trigger_count", 0) > 0
            and current_air_quality.get("evaluated_trigger_count", 0)
            == current_air_quality.get("configured_trigger_count", 0)
        )
        if current_air_quality
        else None,
        current_co_emergency=current_runtime_mode == "co_emergency",
        current_required_inputs_available=not live_invalid_reasons,
        current_invalid_reasons=live_invalid_reasons,
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    payload["sampling"] = _sampling_payload(runtime_data, observed_at=observed_at)
    payload["movement"] = _movement_from_runtime(runtime_data, payload)
    return payload


def record_stability_score_movement(
    runtime_data: dict[str, Any],
    *,
    observed_at: datetime,
    capture_available: bool = True,
) -> dict[str, Any]:
    """Record one score comparison for an actual fixed-UTC scheduler runtime."""
    current_bucket = bucket_start_for(observed_at).isoformat()
    existing = runtime_data.get("stability_score_movement")
    if (
        isinstance(existing, dict)
        and existing.get("current_bucket_start_utc") == current_bucket
    ):
        return dict(existing)
    current_score = (
        _available_display_score(
            stability_diagnostics_payload(runtime_data, observed_at=observed_at)
        )
        if capture_available
        else None
    )
    previous_score = runtime_data.get("stability_movement_last_score")
    previous_score = (
        int(previous_score)
        if isinstance(previous_score, (int, float))
        and _finite_number(previous_score)
        else None
    )
    previous_bucket = runtime_data.get("stability_movement_last_bucket_start_utc")
    movement = _directional_movement(
        previous_score,
        current_score,
        previous_bucket_start_utc=previous_bucket
        if isinstance(previous_bucket, str)
        else None,
        current_bucket_start_utc=current_bucket,
        previous_position_degrees=existing.get("end_position_degrees", 0)
        if isinstance(existing, dict) else 0,
        previous_color_token=existing.get("color_token", "neutral")
        if isinstance(existing, dict) else "neutral",
    )
    if not capture_available:
        movement["detail_text"] = (
            "Directional movement unavailable because the scheduled Stability "
            "snapshot failed; the next valid runtime establishes a new baseline."
        )
    runtime_data["stability_score_movement"] = movement
    runtime_data["stability_movement_last_score"] = current_score
    runtime_data["stability_movement_last_bucket_start_utc"] = current_bucket
    return dict(movement)


def capture_stability_snapshot(
    hass: Any,
    entry: Any,
    runtime_data: dict[str, Any],
    *,
    observed_at: Optional[datetime] = None,
) -> Optional[StabilitySnapshot]:
    """Capture a passive diagnostics snapshot from existing HI sensor truth."""
    config = _effective_config(entry)
    sensors = list(runtime_data.get("core_sensors") or [])
    values = {
        str(getattr(sensor, "_attr_unique_id", "")): getattr(sensor, "_attr_native_value", None)
        for sensor in sensors
    }
    house_humidity = _float_from(values, "house_avg_humidity")
    target_low, target_high = _target_bounds_from_config(config)
    condensation_state = str(_value_from(values, "worst_condensation_risk") or "Unknown")
    mould_state = str(_value_from(values, "worst_mould_risk") or "Unknown")
    drift = _float_from(values, "house_drift_7d")
    spread, balance_scope, balance_source_count = _humidity_balance_from_config(
        hass,
        config,
    )
    air_quality = capture_configured_aq_evidence(hass, config)
    runtime_mode = str(runtime_data.get("runtime_mode") or "normal")
    return StabilitySnapshot(
        observed_at=_as_utc(observed_at or datetime.now(timezone.utc)),
        house_humidity=house_humidity,
        target_low=target_low,
        target_high=target_high,
        worst_condensation_state=condensation_state,
        worst_mould_state=mould_state,
        room_or_level_humidity_spread=spread,
        house_humidity_drift_7d=drift,
        runtime_mode=runtime_mode,
        required_telemetry_available=runtime_mode != "telemetry_unavailable",
        balance_scope=balance_scope,
        balance_source_count=balance_source_count,
        air_quality_clearance=air_quality["clearance"],
        air_quality_configured_condition_count=air_quality["configured_trigger_count"],
        air_quality_evaluated_condition_count=air_quality["evaluated_trigger_count"],
        air_quality_bad_condition_count=air_quality["bad_trigger_count"],
        air_quality_telemetry_source_count=air_quality["telemetry_source_count"],
        air_quality_source_count=air_quality["expected_source_count"],
        air_quality_available_source_count=air_quality["available_source_count"],
        air_quality_unit_invalid_source_count=air_quality["unit_invalid_source_count"],
        air_quality_invalid_threshold_count=air_quality["invalid_threshold_count"],
        air_quality_bad_trigger_codes=tuple(air_quality["bad_trigger_codes"]),
        co_emergency_active=runtime_mode == "co_emergency",
    )


def _base_payload(valid_samples: int, coverage_ratio: float) -> dict[str, Any]:
    return {
        "schema": 3,
        "formula_version": 3,
        "phase": "v2.1_diagnostics_only",
        "missing_data_policy": MISSING_DATA_POLICY,
        "snapshot": {
            "source": SNAPSHOT_SOURCE,
            "schedule": SNAPSHOT_SCHEDULE,
            "representative": SNAPSHOT_REPRESENTATIVE,
            "capture_minutes_utc": list(SNAPSHOT_MINUTES_UTC),
        },
        "window": {
            "duration_hours": WINDOW_HOURS,
            "bucket_minutes": BUCKET_MINUTES,
            "expected_samples": EXPECTED_SAMPLES,
            "valid_samples": valid_samples,
            "coverage_ratio": coverage_ratio,
            "minimum_valid_samples": MINIMUM_VALID_SAMPLES,
            "minimum_coverage_ratio": MINIMUM_COVERAGE_RATIO,
        },
        "control_contract": dict(CONTROL_CONTRACT),
    }


def _unavailable(base: dict[str, Any], availability: str, reason: str) -> dict[str, Any]:
    message = SUPPRESSION_MESSAGES.get(
        reason,
        f"Stability Score unavailable: {reason}.",
    )
    base.update(
        {
            "availability": availability,
            "message": message,
            "score": {
                "raw_score": None,
                "raw_classification": None,
                "window_score": None,
                "window_classification": None,
                "display_score": None,
                "display_classification": None,
                "score_status": "unavailable",
                "suppression_reason": reason,
            },
            "subscores": {},
            "caps": {
                "classification_cap_applied": False,
                "score_cap_applied": False,
                "classification_cap_reasons": [],
                "headline_cap_reason": None,
                "classification_cap": None,
                "score_cap_ceiling": None,
                "uncapped_display_score": None,
                "display_classification": None,
                "cap_condition_active": False,
            },
            "penalties": {
                "coverage_penalty_points": 0.0,
                "drift_unavailable_penalty_points": 0.0,
                "air_quality_evidence_penalty_points": 0.0,
                "additional_penalty_points": 0.0,
            },
            "score_basis": "not_evaluated",
            "environmental_evidence": "not_evaluated",
            "drift_component_status": "not_evaluated",
            "recovery": {},
            "presentation": _unavailable_presentation(base, reason, message),
        }
    )
    return base


def _valid_sample(sample: StabilitySnapshot) -> bool:
    return not stability_snapshot_invalid_reasons(sample)


def stability_snapshot_invalid_reasons(sample: StabilitySnapshot) -> list[str]:
    """Return bounded, privacy-safe reasons an observation cannot enter a bucket."""
    reasons: list[str] = []
    if not sample.required_telemetry_available:
        reasons.append("required_telemetry_unavailable")
    if sample.runtime_mode == "telemetry_unavailable":
        if "required_telemetry_unavailable" not in reasons:
            reasons.append("required_telemetry_unavailable")
    if sample.house_humidity is None:
        reasons.append("house_humidity_missing")
    elif not _finite_number(sample.house_humidity):
        reasons.append("house_humidity_invalid")
    if sample.target_low is None or sample.target_high is None:
        reasons.append("target_bounds_missing")
    elif (
        not _finite_number(sample.target_low)
        or not _finite_number(sample.target_high)
        or sample.target_low >= sample.target_high
    ):
        reasons.append("target_bounds_invalid")
    if sample.worst_condensation_state not in STATE_VALUES:
        reasons.append("condensation_state_invalid")
    if sample.worst_mould_state not in STATE_VALUES:
        reasons.append("mould_state_invalid")
    return reasons


def record_stability_bucket_outcome(
    runtime_data: dict[str, Any],
    scheduled_at: datetime,
    observed_at: datetime,
    *,
    successful: bool = False,
    missed_range: bool = False,
) -> None:
    """Record observed collection failures only; never infer pre-setup history."""
    scheduled_at = _as_utc(scheduled_at)
    observed_at = _as_utc(observed_at)
    latest = bucket_start_for(observed_at)
    cutoff = latest - timedelta(hours=WINDOW_HOURS) + timedelta(minutes=BUCKET_MINUTES)
    history = runtime_data.get("stability_failed_buckets")
    history = history if isinstance(history, set) else set()
    history = {
        bucket for bucket in history
        if isinstance(bucket, datetime) and bucket.tzinfo is not None
        and cutoff <= bucket <= latest and bucket == bucket_start_for(bucket)
    }
    ring = runtime_data.get("stability_snapshot_ring")
    valid_buckets = {
        bucket_start_for(sample.observed_at) for sample in ring.samples()
    } if isinstance(ring, StabilitySnapshotRing) else set()
    history.difference_update(valid_buckets)
    runtime_data["stability_failed_buckets"] = history
    # Early callbacks are not evidence that a future bucket failed.
    if observed_at < scheduled_at:
        return
    scheduled_bucket = bucket_start_for(scheduled_at)
    if successful:
        history.discard(scheduled_bucket)
        return
    first = max(cutoff, scheduled_bucket)
    last = latest if missed_range else scheduled_bucket
    while first <= last <= latest:
        if first not in valid_buckets:
            history.add(first)
        first += timedelta(minutes=BUCKET_MINUTES)


def _failure_history_payload(runtime_data: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    if not isinstance(runtime_data.get("stability_failed_buckets"), set):
        return {
            "status": "unavailable",
            "failed_bucket_count": 0,
            "marker_angles_degrees": [],
            "detail_text": "Collection failure history unavailable.",
        }
    # Prune on reads too, without recording an unobserved attempt.
    record_stability_bucket_outcome(
        runtime_data, observed_at + timedelta(minutes=BUCKET_MINUTES), observed_at
    )
    history = runtime_data["stability_failed_buckets"]
    angles = sorted(
        round((int(bucket.timestamp()) // (BUCKET_MINUTES * 60) % EXPECTED_SAMPLES)
              * 360 / EXPECTED_SAMPLES, 6)
        for bucket in history
    )
    count = len(history)
    return {
        "status": "available",
        "failed_bucket_count": count,
        "marker_angles_degrees": angles,
        "detail_text": (
            f"{count} unsuccessful scheduled collection buckets in the current 72-hour window. "
            "Red marks show observed missed or invalid collections, not baseline progress. "
            "History resets on restart or reload."
        ),
    }


def _sampling_payload(
    runtime_data: dict[str, Any], *, observed_at: Optional[datetime] = None
) -> dict[str, Any]:
    raw = (
        runtime_data.get("stability_sampling")
        if isinstance(runtime_data, dict)
        else None
    )
    raw = raw if isinstance(raw, dict) else {}
    invalid_reasons = [
        str(reason)
        for reason in raw.get("last_invalid_reasons", [])
        if str(reason) in SNAPSHOT_INVALID_REASONS
    ][:5]
    try:
        missed_buckets = max(0, int(raw.get("missed_buckets_since_setup", 0)))
    except (TypeError, ValueError):
        missed_buckets = 0
    status = str(raw.get("last_capture_status") or "pending")
    if status not in {"pending", "captured", "incomplete", "late_skipped"}:
        status = "pending"
    bucket_start = raw.get("last_bucket_start_utc")
    return {
        "source_schema_version": 2,
        "failure_history": _failure_history_payload(
            runtime_data if isinstance(runtime_data, dict) else {},
            observed_at or datetime.now(timezone.utc),
        ),
        "snapshot_source": SNAPSHOT_SOURCE,
        "alignment": SNAPSHOT_SCHEDULE,
        "interval_minutes": BUCKET_MINUTES,
        "late_grace_seconds": SNAPSHOT_LATE_GRACE_SECONDS,
        "scheduler_active": bool(raw.get("scheduler_active", False)),
        "last_capture_status": status,
        "last_bucket_start_utc": bucket_start
        if isinstance(bucket_start, str)
        else None,
        "missed_buckets_since_setup": missed_buckets,
        "last_invalid_reasons": invalid_reasons,
    }


def _target_adherence(valid: list[StabilitySnapshot]) -> float:
    if not valid:
        return 0.0
    in_band = [
        sample
        for sample in valid
        if sample.target_low is not None
        and sample.target_high is not None
        and sample.house_humidity is not None
        and sample.target_low <= sample.house_humidity <= sample.target_high
    ]
    return len(in_band) / len(valid)


def _volatility_score(
    valid: list[StabilitySnapshot],
) -> tuple[Optional[float], dict[str, Any]]:
    deltas: list[float] = []
    expected_step = timedelta(minutes=BUCKET_MINUTES)
    ordered = sorted(valid, key=lambda item: item.observed_at)
    for previous, current in zip(ordered, ordered[1:]):
        if bucket_start_for(current.observed_at) - bucket_start_for(previous.observed_at) != expected_step:
            continue
        if previous.house_humidity is None or current.house_humidity is None:
            continue
        deltas.append(abs(current.house_humidity - previous.house_humidity))
    possible_pairs = max(0, len(valid) - 1)
    coverage = _component_coverage(len(deltas), possible_pairs)
    volatility_index = _nearest_rank_p95(deltas)
    if volatility_index is None or coverage["status"] != "available":
        return None, coverage
    return 1 - _clamp(volatility_index / 12.0), coverage


def _balance_score(
    valid: list[StabilitySnapshot],
) -> tuple[Optional[float], dict[str, Any]]:
    spreads = [
        sample.room_or_level_humidity_spread
        for sample in valid
        if _balance_sample_available(sample)
    ]
    coverage = _balance_coverage(valid)
    spread_index = _nearest_rank_p95(spreads)
    if spread_index is None or coverage["status"] != "available":
        return None, coverage
    return 1 - _clamp(spread_index / 10.0), coverage


def _risk_clearance_score(
    valid: list[StabilitySnapshot],
    *,
    include_drift: bool,
) -> tuple[float, dict[str, Optional[float]]]:
    condensation = [STATE_VALUES[sample.worst_condensation_state] for sample in valid]
    mould = [STATE_VALUES[sample.worst_mould_state] for sample in valid]
    components: dict[str, Optional[float]] = {
        "condensation": sum(condensation) / len(condensation) if condensation else None,
        "mould": sum(mould) / len(mould) if mould else None,
        "drift": None,
    }
    if include_drift:
        drift = [
            1.0
            if abs(float(sample.house_humidity_drift_7d)) <= DRIFT_ACCEPTABLE_ABS_RH
            else 0.0
            for sample in valid
            if sample.house_humidity_drift_7d is not None
            and _finite_number(sample.house_humidity_drift_7d)
        ]
        if drift:
            components["drift"] = sum(drift) / len(drift)
    available = [value for value in components.values() if value is not None]
    score = sum(available) / len(available) if available else 0.0
    return score, {
        key: round(value, 4) if value is not None else None
        for key, value in components.items()
    }


def _air_quality_score(
    valid: list[StabilitySnapshot],
) -> tuple[Optional[float], dict[str, Any]]:
    coverage = _air_quality_coverage(valid)
    available = [
        sample
        for sample in valid
        if sample.air_quality_clearance is not None
        and _finite_number(sample.air_quality_clearance)
        and sample.air_quality_evaluated_condition_count > 0
    ]
    if coverage["status"] not in {"complete", "partial"} or not available:
        return None, coverage
    return (
        sum(float(sample.air_quality_clearance) for sample in available)
        / len(available),
        coverage,
    )


def _air_quality_coverage(valid: list[StabilitySnapshot]) -> dict[str, Any]:
    configured = sum(
        max(0, int(sample.air_quality_configured_condition_count))
        for sample in valid
    )
    evaluated = sum(
        max(0, int(sample.air_quality_evaluated_condition_count))
        for sample in valid
    )
    expected_sources = sum(
        max(0, int(sample.air_quality_source_count))
        for sample in valid
    )
    available_sources = sum(
        max(0, int(sample.air_quality_available_source_count))
        for sample in valid
    )
    configured_buckets = sum(
        1 for sample in valid if sample.air_quality_configured_condition_count > 0
    )
    evaluated_buckets = sum(
        1 for sample in valid if sample.air_quality_evaluated_condition_count > 0
    )
    ratio = round(evaluated / configured, 4) if configured else 0.0
    telemetry_sources = max(
        (max(0, int(sample.air_quality_telemetry_source_count)) for sample in valid),
        default=0,
    )
    unit_invalid_observations = sum(
        max(0, int(sample.air_quality_unit_invalid_source_count))
        for sample in valid
    )
    if configured == 0:
        status = "configured_unmapped" if telemetry_sources else "no_aq_hardware"
    elif evaluated == 0:
        status = (
            "configured_unmapped"
            if expected_sources == 0
            else "unsupported_unit"
            if unit_invalid_observations > 0
            else "currently_unavailable"
        )
    elif ratio < AQ_COMPONENT_MINIMUM_COVERAGE_RATIO:
        status = "insufficient_window_coverage"
    elif ratio < 1.0:
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "coverage_ratio": ratio,
        "minimum_coverage_ratio": AQ_COMPONENT_MINIMUM_COVERAGE_RATIO,
        "configured_trigger_observations": configured,
        "evaluated_trigger_observations": evaluated,
        "configured_buckets": configured_buckets,
        "evaluated_buckets": evaluated_buckets,
        "configured_telemetry_source_count": telemetry_sources,
        "expected_source_observations": expected_sources,
        "available_source_observations": available_sources,
        "unit_invalid_source_observations": unit_invalid_observations,
        "invalid_threshold_observations": sum(
            max(0, int(sample.air_quality_invalid_threshold_count))
            for sample in valid
        ),
        "bad_trigger_observations": sum(
            max(0, int(sample.air_quality_bad_condition_count))
            for sample in valid
        ),
    }


def _recovery_score(valid: list[StabilitySnapshot]) -> tuple[float, dict[str, Any]]:
    durations: list[float] = []
    open_start: Optional[datetime] = None
    open_event_capped = False
    open_event_duration_used = 0.0
    for sample in sorted(valid, key=lambda item: item.observed_at):
        stable = _full_envelope_stable(sample)
        if not stable and open_start is None:
            open_start = sample.observed_at
        elif stable and open_start is not None:
            durations.append(_duration_hours(open_start, sample.observed_at))
            open_start = None
    if open_start is not None and valid:
        last = max(sample.observed_at for sample in valid)
        open_event_duration_used = min(12.0, _duration_hours(open_start, last + timedelta(minutes=BUCKET_MINUTES)))
        open_event_capped = open_event_duration_used == 12.0
        durations.append(open_event_duration_used)
    if not durations:
        return 1.0, {
            "median_recovery_time_hours": 0.0,
            "open_event_capped": False,
            "open_event_duration_used_hours": 0.0,
        }
    median_hours = min(12.0, median(durations))
    return 1 - _clamp(median_hours / 12.0), {
        "median_recovery_time_hours": round(median_hours, 4),
        "open_event_capped": open_event_capped,
        "open_event_duration_used_hours": round(open_event_duration_used, 4),
        "open_event_cap_hours": 12,
    }


def _classification_caps(
    valid: list[StabilitySnapshot],
    display_classification: Optional[str],
    *,
    current_condensation_state: Optional[str] = None,
    current_mould_state: Optional[str] = None,
    current_air_quality_bad: bool = False,
    current_air_quality_evidence_available: bool = False,
    current_co_emergency: bool = False,
    observed_at: Optional[datetime] = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    ordered = sorted(valid, key=lambda item: item.observed_at)
    current = ordered[-1]
    live_condensation = (
        current_condensation_state
        if current_condensation_state in STATE_VALUES
        else current.worst_condensation_state
    )
    live_mould = (
        current_mould_state
        if current_mould_state in STATE_VALUES
        else current.worst_mould_state
    )
    if current_co_emergency:
        reasons.append("current_co_emergency")
    if live_condensation == "Danger":
        reasons.append("current_condensation_danger")
    if live_mould == "Danger":
        reasons.append("current_mould_danger")
    if current_air_quality_bad:
        reasons.append("current_air_quality_bad")
    if not current_air_quality_evidence_available:
        reasons.append("air_quality_evidence_incomplete")

    evaluation_bucket = bucket_start_for(observed_at or current.observed_at)
    danger_cutoff = evaluation_bucket - timedelta(
        hours=DANGER_CAP_WINDOW_HOURS
    ) + timedelta(minutes=BUCKET_MINUTES)
    recent = [sample for sample in ordered if sample.observed_at >= danger_cutoff]
    if any(sample.worst_condensation_state == "Danger" for sample in recent) and "current_condensation_danger" not in reasons:
        reasons.append("recent_condensation_danger_12h")
    if any(sample.worst_mould_state == "Danger" for sample in recent) and "current_mould_danger" not in reasons:
        reasons.append("recent_mould_danger_12h")
    if (
        any(sample.co_emergency_active for sample in recent)
        and "current_co_emergency" not in reasons
    ):
        reasons.append("recent_co_emergency_12h")
    if (
        any(sample.air_quality_bad_condition_count > 0 for sample in recent)
        and "current_air_quality_bad" not in reasons
    ):
        reasons.append("recent_air_quality_bad_12h")

    risk_cutoff = evaluation_bucket - timedelta(
        hours=RISK_CAP_WINDOW_HOURS
    ) + timedelta(minutes=BUCKET_MINUTES)
    risk_window = [sample for sample in ordered if sample.observed_at >= risk_cutoff]
    if risk_window:
        condensation_risk = sum(1 for sample in risk_window if sample.worst_condensation_state == "Risk")
        mould_risk = sum(1 for sample in risk_window if sample.worst_mould_state == "Risk")
        if condensation_risk / RISK_CAP_EXPECTED_SAMPLES >= 0.10:
            reasons.append("condensation_risk_duration_24h")
        if mould_risk / RISK_CAP_EXPECTED_SAMPLES >= 0.10:
            reasons.append("mould_risk_duration_24h")
        air_quality_bad = sum(
            1
            for sample in risk_window
            if sample.air_quality_bad_condition_count > 0
        )
        if air_quality_bad / RISK_CAP_EXPECTED_SAMPLES >= 0.10:
            reasons.append("air_quality_bad_duration_24h")

    cap = _cap_for_reasons(reasons)
    capped = _apply_cap(display_classification, cap)
    return {
        "classification_cap_applied": bool(reasons) and capped != display_classification,
        "classification_cap_reasons": reasons,
        "headline_cap_reason": _headline_reason(reasons),
        "classification_cap": cap,
        "score_cap_ceiling": _score_cap_ceiling(cap, reasons),
        "display_classification": capped,
        "cap_condition_active": bool(reasons),
    }


def _cap_for_reasons(reasons: list[str]) -> Optional[str]:
    if "current_co_emergency" in reasons or "recent_co_emergency_12h" in reasons:
        return "Poor"
    if any(reason.startswith("current_") for reason in reasons):
        return "Poor"
    if any(reason.startswith("recent_") for reason in reasons):
        return "Unstable"
    if (
        "air_quality_evidence_incomplete" in reasons
        or any(reason.endswith("_risk_duration_24h") for reason in reasons)
        or "air_quality_bad_duration_24h" in reasons
    ):
        return "Good"
    return None


def _apply_cap(
    classification: Optional[str],
    cap: Optional[str],
) -> Optional[str]:
    if classification is None:
        return None
    if cap is None:
        return classification
    return min((classification, cap), key=_classification_rank)


def _score_cap_ceiling(
    cap: Optional[str],
    reasons: Optional[list[str]] = None,
) -> Optional[int]:
    reasons = reasons or []
    if "current_co_emergency" in reasons:
        return 0
    if "recent_co_emergency_12h" in reasons:
        return 54
    return {"Good": 91, "Unstable": 69, "Poor": 54}.get(cap)


def _headline_reason(reasons: list[str]) -> Optional[str]:
    if not reasons:
        return None
    priority = (
        "current_co_emergency",
        "current_condensation_danger",
        "current_mould_danger",
        "current_air_quality_bad",
        "recent_co_emergency_12h",
        "recent_condensation_danger_12h",
        "recent_mould_danger_12h",
        "recent_air_quality_bad_12h",
        "air_quality_evidence_incomplete",
        "condensation_risk_duration_24h",
        "mould_risk_duration_24h",
        "air_quality_bad_duration_24h",
    )
    for reason in priority:
        if reason in reasons:
            return reason
    return reasons[0]


def _classification(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= 92:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Unstable"
    return "Poor"


def _classification_rank(classification: str) -> int:
    return {"Poor": 0, "Unstable": 1, "Good": 2, "Excellent": 3}.get(classification, 0)


def _full_envelope_stable(sample: StabilitySnapshot) -> bool:
    if sample.house_humidity is None or sample.target_low is None or sample.target_high is None:
        return False
    if not sample.target_low <= sample.house_humidity <= sample.target_high:
        return False
    if sample.worst_condensation_state not in {"OK", "Watch"}:
        return False
    if sample.worst_mould_state not in {"OK", "Watch"}:
        return False
    if sample.house_humidity_drift_7d is not None and abs(sample.house_humidity_drift_7d) > DRIFT_ACCEPTABLE_ABS_RH:
        return False
    if (
        sample.air_quality_clearance is not None
        and _finite_number(sample.air_quality_clearance)
        and float(sample.air_quality_clearance) < 1.0
    ):
        return False
    return True


def _nearest_rank_p95(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _duration_hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _windowed_samples(
    samples: Iterable[StabilitySnapshot],
    *,
    observed_at: Optional[datetime] = None,
) -> list[StabilitySnapshot]:
    ordered = sorted(samples, key=lambda item: item.observed_at)
    if not ordered:
        return []
    latest_bucket = bucket_start_for(observed_at or ordered[-1].observed_at)
    cutoff = latest_bucket - timedelta(hours=WINDOW_HOURS) + timedelta(
        minutes=BUCKET_MINUTES
    )
    return [
        sample
        for sample in ordered
        if cutoff <= bucket_start_for(sample.observed_at) <= latest_bucket
    ]


def _finite_number(value: Any) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _component_coverage(valid_count: int, expected_count: int) -> dict[str, Any]:
    ratio = round(valid_count / expected_count, 4) if expected_count else 0.0
    required = ceil(expected_count * COMPONENT_MINIMUM_COVERAGE_RATIO)
    return {
        "valid_samples": valid_count,
        "expected_samples": expected_count,
        "coverage_ratio": ratio,
        "minimum_coverage_ratio": COMPONENT_MINIMUM_COVERAGE_RATIO,
        "minimum_valid_samples": required,
        "status": "available"
        if expected_count > 0 and valid_count >= required
        else "insufficient",
    }


def _balance_coverage(valid: list[StabilitySnapshot]) -> dict[str, Any]:
    available = [sample for sample in valid if _balance_sample_available(sample)]
    source_counts = [sample.balance_source_count for sample in available]
    coverage = _component_coverage(len(available), len(valid))
    coverage.update(
        {
            "minimum_source_count": 2,
            "scope_counts": {
                scope: sum(1 for sample in available if sample.balance_scope == scope)
                for scope in ("room", "level")
            },
            "source_count_range": {
                "minimum": min(source_counts) if source_counts else 0,
                "maximum": max(source_counts) if source_counts else 0,
            },
        }
    )
    return coverage


def _balance_sample_available(sample: StabilitySnapshot) -> bool:
    return (
        sample.room_or_level_humidity_spread is not None
        and _finite_number(sample.room_or_level_humidity_spread)
        and sample.room_or_level_humidity_spread >= 0
        and sample.balance_scope in {"room", "level"}
        and sample.balance_source_count >= 2
    )


def _drift_coverage(valid: list[StabilitySnapshot]) -> dict[str, Any]:
    count = sum(
        1
        for sample in valid
        if sample.house_humidity_drift_7d is not None
        and _finite_number(sample.house_humidity_drift_7d)
    )
    return _component_coverage(count, len(valid))


def _runtime_risk_state(
    runtime_data: dict[str, Any],
    suffix: str,
) -> Optional[str]:
    sensors = list(runtime_data.get("core_sensors") or []) if isinstance(runtime_data, dict) else []
    values = {
        str(getattr(sensor, "_attr_unique_id", "")): getattr(
            sensor,
            "_attr_native_value",
            None,
        )
        for sensor in sensors
    }
    value = _value_from(values, suffix)
    return str(value) if str(value) in STATE_VALUES else None


def _runtime_air_quality_truth(runtime_data: dict[str, Any]) -> dict[str, int]:
    value = (
        runtime_data.get("stability_current_air_quality")
        if isinstance(runtime_data, dict)
        else None
    )
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in (
        "configured_trigger_count",
        "evaluated_trigger_count",
        "crossed_trigger_count",
    ):
        try:
            result[key] = max(0, int(value.get(key, 0)))
        except (TypeError, ValueError):
            result[key] = 0
    return result


def _runtime_live_invalid_reasons(runtime_data: dict[str, Any]) -> list[str]:
    if not isinstance(runtime_data, dict):
        return ["required_telemetry_unavailable"]
    reasons: list[str] = []
    if str(runtime_data.get("runtime_mode")) == "telemetry_unavailable":
        reasons.append("required_telemetry_unavailable")
    sensors = list(runtime_data.get("core_sensors") or [])
    values = {
        str(getattr(sensor, "_attr_unique_id", "")): getattr(
            sensor,
            "_attr_native_value",
            None,
        )
        for sensor in sensors
    }
    house_humidity = _value_from(values, "house_avg_humidity")
    if house_humidity is None:
        reasons.append("house_humidity_missing")
    elif not _finite_number(house_humidity):
        reasons.append("house_humidity_invalid")
    if _runtime_risk_state(runtime_data, "worst_condensation_risk") is None:
        reasons.append("condensation_state_invalid")
    if _runtime_risk_state(runtime_data, "worst_mould_risk") is None:
        reasons.append("mould_state_invalid")
    config = dict(runtime_data.get("config") or {})
    config.update(dict(runtime_data.get("options") or {}))
    target_low, target_high = _target_bounds_from_config(config)
    if target_low is None or target_high is None:
        reasons.append("target_bounds_invalid")
    return list(dict.fromkeys(reasons))


def _available_display_score(payload: dict[str, Any]) -> Optional[int]:
    score = payload.get("score") if isinstance(payload, dict) else None
    if not isinstance(score, dict) or score.get("score_status") != "available":
        return None
    value = score.get("display_score")
    if not _finite_number(value):
        return None
    return int(round(float(value)))


def _movement_from_runtime(
    runtime_data: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    current_score = _available_display_score(payload)
    stored = (
        runtime_data.get("stability_score_movement")
        if isinstance(runtime_data, dict)
        else None
    )
    if current_score is None:
        previous_score = None
        previous_bucket = None
        if isinstance(stored, dict):
            stored_score = stored.get("current_display_score")
            previous_score = (
                int(stored_score)
                if isinstance(stored_score, (int, float))
                and _finite_number(stored_score)
                else None
            )
            stored_bucket = stored.get("current_bucket_start_utc")
            previous_bucket = stored_bucket if isinstance(stored_bucket, str) else None
        return _directional_movement(
            previous_score,
            None,
            previous_bucket_start_utc=previous_bucket,
        )
    if isinstance(stored, dict):
        return dict(stored)
    return _directional_movement(None, current_score)


def _directional_movement(
    previous_score: Optional[int],
    current_score: Optional[int],
    *,
    previous_bucket_start_utc: Optional[str] = None,
    current_bucket_start_utc: Optional[str] = None,
    previous_position_degrees: int = 0,
    previous_color_token: str = "neutral",
) -> dict[str, Any]:
    base = {
        "basis": "fixed_utc_runtime_display_score",
        "origin": "twelve_oclock",
        "led_steps_total": DIRECTIONAL_LED_STEPS_TOTAL,
        "led_steps_per_side": DIRECTIONAL_LED_STEPS_PER_SIDE,
        "led_steps_per_point": DIRECTIONAL_LED_STEPS_PER_POINT,
        "previous_bucket_start_utc": previous_bucket_start_utc,
        "current_bucket_start_utc": current_bucket_start_utc,
        "color_token": "neutral",
        "intensity": "neutral",
        "rate_points_per_10_minutes": None,
        "start_position_degrees": 0,
        "end_position_degrees": 0,
        "arc_side": "none",
    }
    if current_score is None:
        return {
            **base,
            "status": "unavailable",
            "previous_display_score": previous_score,
            "current_display_score": None,
            "delta_points": None,
            "direction": "none",
            "active_led_steps": 0,
            "saturated": False,
            "detail_text": "Directional movement unavailable because the current Stability Score is unavailable.",
        }
    if previous_score is None:
        return {
            **base,
            "status": "baseline",
            "previous_display_score": None,
            "current_display_score": current_score,
            "delta_points": None,
            "direction": "none",
            "active_led_steps": 0,
            "saturated": False,
            "detail_text": "Directional movement baseline recorded; a second valid fixed-UTC runtime is required.",
        }
    delta = int(current_score) - int(previous_score)
    start_position = (
        int(_clamp(previous_position_degrees, -360, 360))
        if _finite_number(previous_position_degrees) else 0
    )
    if not delta and previous_color_token in {
        "rise_gentle", "rise_strong", "fall_gentle", "fall_strong",
    }:
        base["color_token"] = previous_color_token
        base["intensity"] = previous_color_token.rsplit("_", 1)[1]
    rate = _movement_rate_points_per_10_minutes(
        delta, previous_bucket_start_utc, current_bucket_start_utc,
    )
    base["rate_points_per_10_minutes"] = rate
    if delta and rate is not None:
        intensity = (
            "strong"
            if abs(rate) >= DIRECTIONAL_STRONG_RATE_POINTS_PER_10_MINUTES
            else "gentle"
        )
        base["intensity"] = intensity
        base["color_token"] = f"{'rise' if delta > 0 else 'fall'}_{intensity}"
    direction = "higher" if delta > 0 else "lower" if delta < 0 else "steady"
    raw_led_steps = ceil(abs(delta) * DIRECTIONAL_LED_STEPS_PER_POINT)
    signed_steps = raw_led_steps if delta > 0 else -raw_led_steps if delta < 0 else 0
    raw_endpoint = start_position + signed_steps
    end_position = int(_clamp(raw_endpoint, -360, 360))
    active_led_steps = abs(end_position)
    side = "right" if end_position > 0 else "left" if end_position < 0 else "none"
    base.update({
        "start_position_degrees": start_position,
        "end_position_degrees": end_position,
        "arc_side": side,
    })
    if direction == "steady":
        detail = (
            "Stability Score is steady since the previous fixed-UTC runtime; "
            f"the arc holds its {end_position}-degree position and previous colour "
            f"with {active_led_steps} active virtual LED positions."
        )
    else:
        detail = (
            f"Stability Score moved {direction} by {abs(delta)} point"
            f"{'s' if abs(delta) != 1 else ''} since the previous fixed-UTC runtime; "
        )
        detail += (
            f"{active_led_steps} of {DIRECTIONAL_LED_STEPS_PER_SIDE} {side}-side virtual LED positions are active."
            if active_led_steps else "the arc is at the origin with no active virtual LED positions."
        )
        detail += f" The arc moved from {start_position} to {end_position} degrees."
        if abs(raw_endpoint) >= DIRECTIONAL_LED_STEPS_PER_SIDE:
            detail += " The arc has completed a full circle back to the top and is saturated."
        if rate is None:
            detail += " Movement rate is unknown because a valid positive timestamp interval is unavailable; the arc colour is neutral."
        else:
            detail += (
                f" Score movement rate is {rate:+g} points per 10 minutes "
                f"over the actual observation interval ({base['intensity']})."
            )
        detail += " Arc position represents accumulated displayed score movement, not elapsed time. This is displayed score change, including cap changes; it is not a physical environmental rate or health assessment."
    return {
        **base,
        "status": "available",
        "previous_display_score": int(previous_score),
        "current_display_score": int(current_score),
        "delta_points": delta,
        "direction": direction,
        "active_led_steps": active_led_steps,
        "saturated": abs(end_position) == DIRECTIONAL_LED_STEPS_PER_SIDE,
        "detail_text": detail,
    }


def _movement_rate_points_per_10_minutes(
    delta: int,
    previous_bucket_start_utc: Optional[str],
    current_bucket_start_utc: Optional[str],
) -> Optional[float]:
    """Normalize score movement using only a known positive aware interval."""
    try:
        if not isinstance(previous_bucket_start_utc, str) or not isinstance(
            current_bucket_start_utc, str
        ):
            return None
        previous = datetime.fromisoformat(previous_bucket_start_utc)
        current = datetime.fromisoformat(current_bucket_start_utc)
        if previous.utcoffset() is None or current.utcoffset() is None:
            return None
        elapsed_seconds = (current - previous).total_seconds()
        if elapsed_seconds <= 0:
            return None
        rate = delta * (BUCKET_MINUTES * 60) / elapsed_seconds
        return rate if isfinite(rate) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _available_message(
    *,
    display_score: int,
    display_classification: str,
    window_score: float,
    caps: dict[str, Any],
    coverage_penalty: float,
    drift_penalty: float,
    air_quality_evidence_penalty: float,
) -> str:
    message = f"Stability Score {display_score} — {display_classification}."
    details: list[str] = []
    headline_reason = caps.get("headline_cap_reason")
    if caps.get("score_cap_applied"):
        details.append(
            f"Underlying 72-hour score {window_score:.2f}; "
            f"capped because {_cap_reason_text(headline_reason)}."
        )
    elif (
        caps.get("cap_condition_active")
        and headline_reason != "air_quality_evidence_incomplete"
    ):
        details.append(
            f"The backend cap condition remains active because "
            f"{_cap_reason_text(headline_reason)}; the underlying 72-hour score "
            f"{window_score:.2f} was already at or below that ceiling."
        )
    penalties: list[str] = []
    if coverage_penalty:
        penalties.append(f"{coverage_penalty:.2f}-point coverage penalty")
    if drift_penalty:
        penalties.append(f"{drift_penalty:.2f}-point drift-evidence penalty")
    if air_quality_evidence_penalty:
        penalties.append(
            f"{air_quality_evidence_penalty:.2f}-point AQ-evidence penalty"
        )
    if penalties:
        details.append("Includes " + " and ".join(penalties) + ".")
    if "air_quality_evidence_incomplete" in caps.get(
        "classification_cap_reasons", []
    ):
        details.append(
            "AQ evidence is incomplete, so the headline cannot exceed 91 / Good."
        )
    if not details:
        details.append("Calculated from complete 72-hour window coverage.")
    return " ".join((message, *details))


def _cap_reason_text(reason: Any) -> str:
    return {
        "current_condensation_danger": "the current condensation state is Danger",
        "current_mould_danger": "the current mould state is Danger",
        "recent_condensation_danger_12h": "condensation Danger occurred within the last 12 hours",
        "recent_mould_danger_12h": "mould Danger occurred within the last 12 hours",
        "current_co_emergency": "the backend CO-emergency state is active",
        "recent_co_emergency_12h": "a backend CO-emergency state occurred within the last 12 hours",
        "current_air_quality_bad": "a configured AQ threshold is currently crossed",
        "recent_air_quality_bad_12h": "a configured AQ threshold was crossed within the last 12 hours",
        "air_quality_bad_duration_24h": "configured AQ threshold crossings met the 24-hour duration threshold",
        "air_quality_evidence_incomplete": "AQ evidence is incomplete",
        "condensation_risk_duration_24h": "condensation Risk met the 24-hour duration threshold",
        "mould_risk_duration_24h": "mould Risk met the 24-hour duration threshold",
    }.get(str(reason), "a backend stability classification cap applies")


def _available_presentation(
    display_score: int,
    display_classification: str,
    message: str,
    *,
    cap_applied: bool,
    partial_evidence: bool,
    condition_truth_active: bool,
) -> dict[str, Any]:
    show_partial = partial_evidence and not condition_truth_active
    return {
        "state_code": "available_partial_evidence"
        if show_partial
        else "available",
        "card_label": "Stability Score",
        "primary_text": str(display_score),
        "compact_text": "PARTIAL"
        if show_partial
        else display_classification.upper(),
        "detail_text": message,
        "tone": "incomplete" if show_partial else display_classification.lower(),
        "indicator_mode": "score",
        "progress_ratio": round(display_score / 100.0, 4),
        "cap_applied": cap_applied,
        "evidence_status": "partial" if partial_evidence else "complete",
    }


def _unavailable_presentation(
    base: dict[str, Any],
    reason: str,
    message: str,
) -> dict[str, Any]:
    valid_samples = int(base.get("window", {}).get("valid_samples") or 0)
    if reason == "coverage_below_threshold":
        return {
            "state_code": "collecting",
            "card_label": "Collecting baseline",
            "primary_text": str(valid_samples),
            "compact_text": f"OF {MINIMUM_VALID_SAMPLES}",
            "detail_text": message,
            "tone": "collecting",
            "indicator_mode": "collection",
            "progress_ratio": round(
                min(1.0, valid_samples / MINIMUM_VALID_SAMPLES),
                4,
            ),
            "cap_applied": False,
        }
    if reason == "insufficient_consecutive_samples":
        state_code, card_label, compact_text, tone = (
            "incomplete_evidence_gaps",
            "Evidence gaps",
            "GAPS",
            "incomplete",
        )
    elif reason == "insufficient_balance_sources":
        state_code, card_label, compact_text, tone = (
            "incomplete_evidence_balance",
            "Balance evidence",
            "BALANCE",
            "incomplete",
        )
    elif reason == "current_telemetry_unavailable":
        state_code, card_label, compact_text, tone = (
            "live_data_unavailable",
            "Live data unavailable",
            "LIVE DATA",
            "unavailable",
        )
    else:
        state_code, card_label, compact_text, tone = (
            "unavailable",
            "Stability unavailable",
            "NO SCORE",
            "unavailable",
        )
    return {
        "state_code": state_code,
        "card_label": card_label,
        "primary_text": "—",
        "compact_text": compact_text,
        "detail_text": message,
        "tone": tone,
        "indicator_mode": "incomplete" if tone == "incomplete" else "none",
        "progress_ratio": None,
        "cap_applied": False,
    }


def _effective_config(entry: Any) -> dict[str, Any]:
    config = dict(getattr(entry, "data", {}) or {})
    config.update(dict(getattr(entry, "options", {}) or {}))
    return config


def _value_from(values: dict[str, Any], suffix: str) -> Any:
    for key, value in values.items():
        if key.endswith(suffix):
            return value
    return None


def _float_from(values: dict[str, Any], suffix: str) -> Optional[float]:
    value = _value_from(values, suffix)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _target_bounds_from_config(config: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    try:
        from .seasonal import resolve_target_profile

        profile_mode = str(
            config.get("target_profile")
            or config.get("target_profile_mode")
            or "auto"
        ).strip().lower()
        if profile_mode == "custom":
            custom_value = config.get("target_custom")
            custom = custom_value if isinstance(custom_value, dict) else {}
            low_value = (
                config.get("custom_target_low")
                if config.get("custom_target_low") is not None
                else config.get("target_custom_low", custom.get("low"))
            )
            high_value = (
                config.get("custom_target_high")
                if config.get("custom_target_high") is not None
                else config.get("target_custom_high", custom.get("high"))
            )
            if (
                not _finite_number(low_value)
                or not _finite_number(high_value)
                or float(low_value) >= float(high_value)
            ):
                return None, None
        profile = resolve_target_profile(config)
        low = float(profile.low)
        high = float(profile.high)
        if not isfinite(low) or not isfinite(high) or low >= high:
            return None, None
        return low, high
    except (ImportError, TypeError, ValueError, AttributeError):
        return None, None


def _humidity_balance_from_config(
    hass: Any,
    config: dict[str, Any],
) -> tuple[Optional[float], Optional[str], int]:
    records: list[tuple[float, Optional[str], Optional[str]]] = []
    seen_entities: set[str] = set()
    for item in config.get("telemetry", []) or []:
        if not isinstance(item, dict) or item.get("sensor_type") != "humidity":
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if not entity_id or entity_id in seen_entities:
            continue
        seen_entities.add(entity_id)
        state = (
            getattr(hass, "states", None).get(entity_id)
            if getattr(hass, "states", None)
            else None
        )
        if state is None:
            continue
        try:
            value = float(getattr(state, "state", None))
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        room = str(item.get("room") or "").strip() or None
        level = str(item.get("level") or "").strip() or None
        records.append((value, room, level))
    for scope, index in (("room", 1), ("level", 2)):
        grouped: dict[str, list[float]] = {}
        for record in records:
            label = record[index]
            if label is not None:
                grouped.setdefault(label, []).append(record[0])
        if len(grouped) < 2:
            continue
        scope_values = [sum(values) / len(values) for values in grouped.values()]
        return max(scope_values) - min(scope_values), scope, len(scope_values)
    available_scope_count = max(
        len({record[1] for record in records if record[1] is not None}),
        len({record[2] for record in records if record[2] is not None}),
    )
    return None, None, available_scope_count


def _air_quality_from_config(
    hass: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility wrapper for direct contract tests and local callers."""
    return capture_configured_aq_evidence(hass, config)
