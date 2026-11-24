"""Read explicitly selected display-only VOC indices independently of AQ control."""
from __future__ import annotations

import hashlib
import re
from math import isfinite
from typing import Any
from uuid import UUID

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_STATUSES = ("available", "unknown", "unavailable", "invalid", "unsupported_unit")


def provider_identity(source_key: str, registry_entry: Any) -> str | None:
    """Bind this row to a registry record without persisting its private identifier."""
    record_id = getattr(registry_entry, "id", None)
    if not isinstance(record_id, str) or not record_id:
        return None
    return hashlib.sha256(f"voc_index:{source_key}:{record_id}".encode()).hexdigest()


def same_provider(row: dict, registry_entry: Any) -> bool:
    proof = row.get("provider_identity")
    return isinstance(proof, str) and proof == provider_identity(row["source_key"], registry_entry)


def configured_sources(section: Any) -> list[dict[str, str]]:
    """Validate the display binding shape without repairing or rewriting Options."""
    if not isinstance(section, list):
        return []
    sources = []
    keys = set()
    ids = set()
    for row in section:
        if not isinstance(row, dict):
            continue
        key, entity_id, label = (row.get(field) for field in ("source_key", "entity_id", "label"))
        if not all(isinstance(value, str) and value.strip() for value in (key, entity_id, label)):
            continue
        try:
            identity = UUID(key)
        except ValueError:
            continue
        if not re.fullmatch(r"sensor\.[a-z0-9_]+", entity_id) or identity in keys or entity_id in ids:
            continue
        keys.add(identity)
        ids.add(entity_id)
        source = {"source_key": key, "entity_id": entity_id, "label": label}
        if "provider_identity" in row:
            source["provider_identity"] = row["provider_identity"]
        sources.append(source)
    return sources


def _index_value(state: Any) -> tuple[str, float | None]:
    if state is None:
        return "unavailable", None
    raw = state.state
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.lower() in {"unknown", "unavailable"}:
            return raw.lower(), None
    unit = state.attributes.get("unit_of_measurement")
    if unit is not None and str(unit).strip().lower() not in {"", "index"}:
        return "unsupported_unit", None
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return "invalid", None
    if isinstance(raw, str) and not _NUMBER.fullmatch(raw):
        return "invalid", None
    try:
        value = float(raw)
    except (OverflowError, ValueError):
        return "invalid", None
    return ("available", value) if isfinite(value) else ("invalid", None)


def _provider_reading(hass: Any, source: dict) -> tuple[str, float | None]:
    if "provider_identity" in source:
        from homeassistant.helpers import entity_registry as er

        provider = er.async_get(hass).async_get(source["entity_id"])
        if not same_provider(source, provider) or provider.disabled_by is not None:
            return "unavailable", None
    return _index_value(hass.states.get(source["entity_id"]))


def source_readings(hass: Any, sources: list[dict[str, str]]) -> dict[str, dict]:
    readings = {}
    for source in sources:
        status, value = _provider_reading(hass, source)
        readings[source["source_key"]] = {"label": source["label"], "status": status, "value": value}
    return readings


def source_counts(hass: Any, section: Any) -> dict[str, int]:
    """Support-safe counts only. Each index provider has its own numeric scale."""
    sources = configured_sources(section)
    counts = {"configured": len(sources), **dict.fromkeys(_STATUSES, 0)}
    for source in sources:
        status, _ = _provider_reading(hass, source)
        counts[status] += 1
    return counts
