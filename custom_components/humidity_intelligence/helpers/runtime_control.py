"""Bounded runtime-control truth shared by diagnostics surfaces."""

from __future__ import annotations

from typing import Any


_RUNTIME_CONTROL_DISPLAYS = {
    "air_quality": "AIR QUALITY",
    "alert": "ALERT",
    "bathroom": "BATHROOM",
    "co_emergency": "CO EMERGENCY",
    "cooking": "COOKING",
    "global_gate": "GLOBAL GATE",
    "manual_override": "MANUAL OVERRIDE",
    "normal": "NORMAL",
    "telemetry_unavailable": "TELEMETRY UNAVAILABLE",
    "zone": "ZONE",
}


def runtime_control_summary(runtime_data: dict[str, Any]) -> dict[str, Any]:
    """Return canonical runtime mode truth without user-configured labels."""
    raw_mode = str(runtime_data.get("runtime_mode") or "").strip()
    mode = raw_mode if raw_mode in _RUNTIME_CONTROL_DISPLAYS else None
    return {
        "mode": mode,
        "display": _RUNTIME_CONTROL_DISPLAYS.get(mode),
        "reason_available": bool(
            runtime_data.get("runtime_reason_full")
            or runtime_data.get("runtime_reason")
        ),
    }
