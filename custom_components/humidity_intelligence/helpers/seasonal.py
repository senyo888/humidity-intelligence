"""Season-aware target profiles and environmental interpretation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class TargetProfile:
    """Resolved humidity target profile used across runtime and UI."""

    key: str
    label: str
    low: float
    high: float
    high_risk: float
    condensation_danger_spread: float
    condensation_risk_spread: float
    condensation_watch_spread: float
    mould_spread_danger: float
    mould_spread_risk: float
    mould_excess_risk: float
    mould_excess_danger: float


@dataclass(frozen=True)
class TemperatureComfortProfile:
    """Resolved temperature comfort band used by runtime sensors and UI."""

    key: str
    label: str
    low: float
    high: float
    warm_high: float


SEASONAL_PROFILES: dict[str, TargetProfile] = {
    "spring": TargetProfile(
        key="spring",
        label="Spring",
        low=47.0,
        high=58.0,
        high_risk=64.0,
        condensation_danger_spread=2.2,
        condensation_risk_spread=4.2,
        condensation_watch_spread=6.2,
        mould_spread_danger=2.3,
        mould_spread_risk=4.1,
        mould_excess_risk=3.0,
        mould_excess_danger=8.0,
    ),
    "summer": TargetProfile(
        key="summer",
        label="Summer",
        low=51.0,
        high=60.0,
        high_risk=68.0,
        condensation_danger_spread=1.8,
        condensation_risk_spread=3.4,
        condensation_watch_spread=5.4,
        mould_spread_danger=1.9,
        mould_spread_risk=3.6,
        mould_excess_risk=2.0,
        mould_excess_danger=6.0,
    ),
    "autumn": TargetProfile(
        key="autumn",
        label="Autumn",
        low=50.0,
        high=60.0,
        high_risk=64.0,
        condensation_danger_spread=2.3,
        condensation_risk_spread=4.3,
        condensation_watch_spread=6.3,
        mould_spread_danger=2.3,
        mould_spread_risk=4.1,
        mould_excess_risk=3.0,
        mould_excess_danger=8.0,
    ),
    "winter": TargetProfile(
        key="winter",
        label="Winter",
        low=45.0,
        high=55.0,
        high_risk=62.0,
        condensation_danger_spread=2.6,
        condensation_risk_spread=4.8,
        condensation_watch_spread=6.8,
        mould_spread_danger=2.6,
        mould_spread_risk=4.6,
        mould_excess_risk=3.0,
        mould_excess_danger=7.0,
    ),
}


SEASONAL_TEMPERATURE_COMFORT: dict[str, TemperatureComfortProfile] = {
    "winter": TemperatureComfortProfile(key="winter", label="Winter", low=20.0, high=21.0, warm_high=21.5),
    "spring": TemperatureComfortProfile(key="spring", label="Spring", low=20.5, high=22.0, warm_high=23.5),
    "summer": TemperatureComfortProfile(key="summer", label="Summer", low=21.0, high=24.0, warm_high=26.5),
    "autumn": TemperatureComfortProfile(key="autumn", label="Autumn", low=20.0, high=21.5, warm_high=23.0),
}


def resolve_target_profile(config: Mapping[str, Any], now: Optional[datetime] = None) -> TargetProfile:
    """Resolve active profile from config with seasonal fallback."""
    now = now or datetime.now()
    profile_mode = str(
        config.get("target_profile")
        or config.get("target_profile_mode")
        or "auto"
    ).strip().lower()

    if profile_mode == "custom":
        custom = _resolve_custom_profile(config, now)
        if custom is not None:
            return custom

    if profile_mode in SEASONAL_PROFILES:
        return SEASONAL_PROFILES[profile_mode]

    return SEASONAL_PROFILES[_season_key_from_month(now.month)]


def resolve_temperature_comfort_profile(
    config: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> TemperatureComfortProfile:
    """Resolve active temperature comfort band from config with seasonal fallback."""
    now = now or datetime.now()
    mode = str(config.get("temperature_comfort_mode") or "auto").strip().lower()
    if mode == "custom":
        low = _to_float(config.get("temperature_comfort_custom_low"))
        high = _to_float(config.get("temperature_comfort_custom_high"))
        if low is not None and high is not None and high > low:
            return TemperatureComfortProfile(
                key="custom",
                label="Custom",
                low=round(low, 1),
                high=round(high, 1),
                warm_high=round(high + 1.0, 1),
            )
    return SEASONAL_TEMPERATURE_COMFORT[_season_key_from_month(now.month)]


def temperature_comfort_state(
    temperature: Optional[float],
    profile: TemperatureComfortProfile,
) -> str:
    """Classify temperature against the active comfort profile."""
    if temperature is None:
        return "unknown"
    if temperature < profile.low:
        return "below_comfort"
    if temperature <= profile.high:
        return "in_comfort"
    if temperature <= profile.warm_high:
        return "above_comfort_watch"
    return "above_comfort_high"


def humidity_state(humidity: Optional[float], profile: TargetProfile) -> str:
    """Classify humidity against the active profile."""
    if humidity is None:
        return "unknown"
    if humidity >= profile.high_risk:
        return "high_risk"
    if humidity < profile.low:
        return "below_target"
    if humidity <= profile.high:
        return "in_target"
    return "above_target"


def condensation_risk(spread: Optional[float], profile: TargetProfile) -> str:
    """Return deterministic condensation risk class for the active profile."""
    if spread is None:
        return "Unknown"
    if spread <= profile.condensation_danger_spread:
        return "Danger"
    if spread <= profile.condensation_risk_spread:
        return "Risk"
    if spread <= profile.condensation_watch_spread:
        return "Watch"
    return "OK"


def mould_level(rh: Optional[float], spread: Optional[float], profile: TargetProfile) -> int:
    """Return deterministic mould level (0-3) using seasonal context."""
    if rh is None or spread is None:
        return 0

    points = 0
    excess = rh - profile.high
    if excess >= profile.mould_excess_danger:
        points += 2
    elif excess >= profile.mould_excess_risk:
        points += 1

    if spread <= profile.mould_spread_danger:
        points += 2
    elif spread <= profile.mould_spread_risk:
        points += 1

    if rh >= profile.high_risk:
        points = max(points, 2)

    return min(points, 3)


def mould_risk(rh: Optional[float], spread: Optional[float], profile: TargetProfile) -> str:
    """Return mould risk class for the active profile."""
    if rh is None or spread is None:
        return "Unknown"
    level = mould_level(rh, spread, profile)
    if level >= 3:
        return "Danger"
    if level == 2:
        return "Risk"
    if level == 1:
        return "Watch"
    return "OK"


def _resolve_custom_profile(config: Mapping[str, Any], now: datetime) -> Optional[TargetProfile]:
    custom_low = _to_float(
        config.get("custom_target_low")
        or config.get("target_custom_low")
        or (config.get("target_custom") or {}).get("low")
    )
    custom_high = _to_float(
        config.get("custom_target_high")
        or config.get("target_custom_high")
        or (config.get("target_custom") or {}).get("high")
    )
    if custom_low is None or custom_high is None:
        return None
    if custom_high <= custom_low:
        return None

    seasonal_base = SEASONAL_PROFILES[_season_key_from_month(now.month)]
    high_risk = custom_high + max(4.0, min(10.0, (custom_high - custom_low) * 0.75))
    return TargetProfile(
        key="custom",
        label="Custom",
        low=round(custom_low, 1),
        high=round(custom_high, 1),
        high_risk=round(high_risk, 1),
        condensation_danger_spread=seasonal_base.condensation_danger_spread,
        condensation_risk_spread=seasonal_base.condensation_risk_spread,
        condensation_watch_spread=seasonal_base.condensation_watch_spread,
        mould_spread_danger=seasonal_base.mould_spread_danger,
        mould_spread_risk=seasonal_base.mould_spread_risk,
        mould_excess_risk=seasonal_base.mould_excess_risk,
        mould_excess_danger=seasonal_base.mould_excess_danger,
    )


def _season_key_from_month(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
