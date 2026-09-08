"""Read-only setup assistance from Home Assistant registry metadata."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
except Exception:  # pragma: no cover - keeps direct sanity imports HA-optional.
    HomeAssistant = Any  # type: ignore[misc, assignment]
    ar = None  # type: ignore[assignment]
    dr = None  # type: ignore[assignment]
    er = None  # type: ignore[assignment]

try:
    from homeassistant.helpers import label_registry as lr
except Exception:  # pragma: no cover - older HA versions may not expose labels.
    lr = None  # type: ignore[assignment]


LEVEL1_HINTS = (
    "downstairs",
    "ground",
    "ground floor",
    "level 1",
    "level1",
)
LEVEL2_HINTS = (
    "upstairs",
    "second floor",
    "level 2",
    "level2",
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetupAssistSuggestion:
    """Advisory setup suggestion derived from HA metadata."""

    entity_id: str
    status: str
    room: str = ""
    level: str = ""
    area_id: str = ""
    area_name: str = ""
    labels: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    runtime_authority: bool = False
    save_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.save_payload is None:
            object.__setattr__(self, "save_payload", {})

    @property
    def has_context(self) -> bool:
        """Return True when HA metadata produced any advisory context."""

        return bool(self.room or self.labels or self.warnings)

    @property
    def unsupported(self) -> bool:
        """Return True when the metadata lookup itself is unsupported."""

        return self.status == "unsupported"


def setup_assist_suggestion(
    hass: HomeAssistant,
    entity_id: str | None,
) -> SetupAssistSuggestion:
    """Return read-only Area/Label suggestions for a Home Assistant entity."""

    clean_entity_id = _clean_text(entity_id)
    if not clean_entity_id:
        return SetupAssistSuggestion(entity_id="", status="empty")

    if ar is None or er is None:
        return unsupported_setup_assist_suggestion("registry_unavailable", clean_entity_id)

    try:
        entity_reg = er.async_get(hass)
        area_reg = ar.async_get(hass)
        device_reg = dr.async_get(hass) if dr is not None else None
        label_reg = lr.async_get(hass) if lr is not None else None
    except Exception as err:
        _LOGGER.debug(
            "Setup assist registry lookup failed for %s: %s",
            clean_entity_id,
            err,
        )
        return unsupported_setup_assist_suggestion("registry_lookup_failed", clean_entity_id)

    try:
        entity_entry = entity_reg.async_get(clean_entity_id) if entity_reg is not None else None
    except Exception as err:
        _LOGGER.debug(
            "Setup assist entity lookup failed for %s: %s",
            clean_entity_id,
            err,
        )
        return unsupported_setup_assist_suggestion("entity_lookup_failed", clean_entity_id)
    if entity_entry is None:
        return SetupAssistSuggestion(entity_id=clean_entity_id, status="not_found")

    device_id = _clean_text(getattr(entity_entry, "device_id", ""))
    device_entry = _registry_get(device_reg, device_id)
    area_id = _clean_text(getattr(entity_entry, "area_id", "")) or _clean_text(
        getattr(device_entry, "area_id", "")
    )
    if not area_id:
        # HA 2026.9 child devices inherit Area from their single-level parent.
        parent_device_id = _clean_text(getattr(device_entry, "parent_device_id", ""))
        if parent_device_id and parent_device_id != device_id:
            parent_device_entry = _registry_get(device_reg, parent_device_id)
            if not _clean_text(getattr(parent_device_entry, "parent_device_id", "")):
                area_id = _clean_text(getattr(parent_device_entry, "area_id", ""))
    area_entry = _area_registry_get(area_reg, area_id)
    area_name = _clean_text(getattr(area_entry, "name", ""))
    label_names = _label_names(label_reg, entity_entry, device_entry, area_entry)
    level, warnings = _suggest_level(area_name, label_names)

    return SetupAssistSuggestion(
        entity_id=clean_entity_id,
        status="available" if area_name or label_names else "no_metadata",
        room=area_name,
        level=level,
        area_id=area_id,
        area_name=area_name,
        labels=label_names,
        warnings=tuple(warnings),
    )


def unsupported_setup_assist_suggestion(
    reason: str,
    entity_id: str | None = None,
) -> SetupAssistSuggestion:
    """Return an unsupported suggestion record without raising in config flow."""

    return SetupAssistSuggestion(
        entity_id=_clean_text(entity_id),
        status="unsupported",
        warnings=(_clean_text(reason) or "unsupported",),
    )


def advisory_text(suggestion: SetupAssistSuggestion) -> str:
    """Render short config-flow copy for advisory metadata suggestions."""

    if suggestion.unsupported:
        return "Home Assistant Area/Label metadata is unavailable; manual HI mapping remains active."
    if suggestion.status in {"empty", "not_found", "no_metadata"}:
        return "No Home Assistant Area/Label suggestion is available; manual HI mapping remains active."

    lines: list[str] = []
    if suggestion.room:
        lines.append("Suggested from Home Assistant Area: review the room default before saving.")
    if suggestion.labels:
        lines.append("Suggested from Home Assistant Label: review advisory label context before saving.")
    if "conflicting_level_hints" in suggestion.warnings:
        lines.append("Conflicting Area/Label level hints found; no level was selected automatically.")
    if not lines:
        return "No Home Assistant Area/Label suggestion is available; manual HI mapping remains active."
    lines.append("HI saves only explicit fields you review here; Areas and Labels are not runtime authority.")
    return "\n".join(lines)


def diagnostics_setup_assist_summary(
    hass: HomeAssistant,
    telemetry: list[Any],
) -> dict[str, Any]:
    """Return sanitized diagnostics counts for configured telemetry metadata."""

    rows = [row for row in telemetry if isinstance(row, dict)]
    if not rows:
        return {
            "status": "not_configured",
            "telemetry_checked_count": 0,
            "area_context_count": 0,
            "label_context_count": 0,
            "area_mismatch_count": 0,
            "conflicting_level_hint_count": 0,
            "unsupported_metadata": False,
        }

    counts = {
        "telemetry_checked_count": 0,
        "area_context_count": 0,
        "label_context_count": 0,
        "area_mismatch_count": 0,
        "conflicting_level_hint_count": 0,
    }
    unsupported = False
    any_available = False

    for row in rows:
        entity_id = _clean_text(row.get("entity_id"))
        if not entity_id:
            continue
        counts["telemetry_checked_count"] += 1
        suggestion = setup_assist_suggestion(hass, entity_id)
        unsupported = unsupported or suggestion.unsupported
        any_available = any_available or suggestion.status == "available"
        if suggestion.room:
            counts["area_context_count"] += 1
        if suggestion.labels:
            counts["label_context_count"] += 1
        saved_room = _clean_text(row.get("room"))
        if saved_room and suggestion.room and saved_room.casefold() != suggestion.room.casefold():
            counts["area_mismatch_count"] += 1
        if "conflicting_level_hints" in suggestion.warnings:
            counts["conflicting_level_hint_count"] += 1

    if unsupported:
        status = "unsupported"
    elif any_available:
        status = "available"
    else:
        status = "no_metadata"

    return {
        "status": status,
        **counts,
        "unsupported_metadata": unsupported,
    }


def diagnostics_setup_assist_warnings(summary: dict[str, Any]) -> list[str]:
    """Return sanitized diagnostics warnings for setup-assist summary counts."""

    warnings: list[str] = []
    if summary.get("unsupported_metadata"):
        warnings.append(
            "HA Area/Label metadata unavailable on this Home Assistant version; "
            "manual HI mapping remains active."
        )
    if summary.get("area_mismatch_count"):
        warnings.append(
            "HA Area differs from saved HI room for one or more telemetry entries; "
            "HI will keep using the saved HI room until changed in options."
        )
    if summary.get("conflicting_level_hint_count"):
        warnings.append(
            "One or more telemetry entries have conflicting Area/Label level hints; "
            "no automatic mapping was applied."
        )
    return warnings


def _registry_get(registry: Any, key: str) -> Any:
    if registry is None or not key:
        return None
    try:
        return registry.async_get(key)
    except Exception as err:
        _LOGGER.debug("Setup assist registry get failed for %s: %s", key, err)
        return None


def _area_registry_get(registry: Any, key: str) -> Any:
    if registry is None or not key:
        return None
    try:
        return registry.async_get_area(key)
    except Exception as err:
        _LOGGER.debug("Setup assist area registry get failed for %s: %s", key, err)
        return None


def _label_names(label_reg: Any, *entries: Any) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for label_id in _entry_label_ids(entry):
            label_name = _label_name(label_reg, label_id)
            key = label_name.casefold()
            if not label_name or key in seen:
                continue
            seen.add(key)
            names.append(label_name)
    return tuple(names)


def _entry_label_ids(entry: Any) -> tuple[str, ...]:
    raw = getattr(entry, "labels", None)
    if not raw:
        return ()
    if isinstance(raw, str):
        values = [raw]
    else:
        try:
            values = list(raw)
        except TypeError:
            values = []
    cleaned = sorted({_clean_text(value) for value in values if _clean_text(value)})
    return tuple(cleaned)


def _label_name(label_reg: Any, label_id: str) -> str:
    entry = _registry_get(label_reg, label_id)
    return _clean_text(getattr(entry, "name", "")) or _clean_text(label_id)


def _suggest_level(area_name: str, label_names: tuple[str, ...]) -> tuple[str, list[str]]:
    hints = set()
    for text in (area_name, *label_names):
        level = _level_from_text(text)
        if level:
            hints.add(level)
    if len(hints) > 1:
        return "", ["conflicting_level_hints"]
    if hints:
        return next(iter(hints)), []
    return "", []


def _level_from_text(value: str) -> str:
    text = f" {_clean_text(value).casefold()} "
    if any(f" {hint} " in text for hint in LEVEL2_HINTS):
        return "level2"
    if any(f" {hint} " in text for hint in LEVEL1_HINTS):
        return "level1"
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
