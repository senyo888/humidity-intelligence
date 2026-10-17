"""Bounded, read-only observation of HI's optional HACS update entity.

HACS describes the downloaded package, not the code loaded by Home Assistant.
This adapter never checks GitHub, compares versions, refreshes HACS, or installs
anything. Call it on the event loop alongside the existing Diagnostics refresh.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from homeassistant.helpers import entity_registry as er

PROVIDER = "hacs"
REPOSITORY = "senyo888/humidity-intelligence"
# HACS uses str(repository.data.id), not the display name, as its unique ID.
REPOSITORY_ID = "1127166185"
VERSION_LIMIT = 128
_ENTITY_ID = re.compile(r"update\.[a-z0-9_]+\Z")


def _payload(reason: str, *, entity_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": 1,
        "provider": PROVIDER,
        "repository": REPOSITORY,
        "status": "unverified",
        "reason": reason,
        "entity_id": entity_id,
        "provider_state": None,
        "downloaded_version": None,
        "latest_version": None,
        "skipped_version": None,
    }


def _version(value: Any) -> bool:
    """Accept bounded display text without claiming a version format/order."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= VERSION_LIMIT
        and value == value.strip()
        and value.isprintable()
        and value.lower() not in {"unknown", "unavailable"}
    )


def _resolve_entity(hass: Any) -> tuple[str | None, str | None]:
    registry = er.async_get(hass)
    matches = [
        entry
        for entry in registry.entities.values()
        if entry.domain == "update"
        and entry.platform == PROVIDER
        and entry.unique_id == REPOSITORY_ID
    ]
    if not matches:
        return None, "entity_missing"
    if len(matches) != 1:
        return None, "entity_ambiguous"
    entry = matches[0]
    if entry.disabled_by is not None:
        return None, "entity_disabled"
    entity_id = entry.entity_id
    if (
        not isinstance(entity_id, str)
        or len(entity_id) > 255
        or _ENTITY_ID.fullmatch(entity_id) is None
    ):
        return None, "entity_invalid"
    return entity_id, None


def _observe_state(hass: Any, entity_id: str) -> dict[str, Any]:
    payload = _payload("state_missing", entity_id=entity_id)
    state = hass.states.get(entity_id)
    if state is None:
        return payload
    provider_state = state.state
    if provider_state not in ("on", "off"):
        payload["reason"] = (
            "state_unavailable"
            if provider_state in ("unknown", "unavailable")
            else "state_invalid"
        )
        return payload
    payload["provider_state"] = provider_state
    attrs = state.attributes
    if not isinstance(attrs, Mapping):
        payload["reason"] = "attributes_invalid"
        return payload
    downloaded = attrs.get("installed_version")
    latest = attrs.get("latest_version")
    skipped = attrs.get("skipped_version")
    progress = attrs.get("in_progress")
    # Older HA update entities may expose an integer percentage. Zero is an
    # active progress report too; bool/int truthiness must not decide this.
    valid_progress = type(progress) is bool or (
        type(progress) is int and 0 <= progress <= 100
    )
    if (
        not _version(downloaded)
        or not _version(latest)
        or (skipped is not None and not _version(skipped))
        or not valid_progress
        or (provider_state == "on" and (downloaded == latest or skipped == latest))
    ):
        payload["reason"] = "attributes_invalid"
        return payload
    payload.update(
        downloaded_version=downloaded,
        latest_version=latest,
        skipped_version=skipped,
    )
    if progress is True or type(progress) is int:
        payload.update(status="in_progress", reason="provider_in_progress")
    elif provider_state == "on":
        payload.update(status="reported_update", reason="provider_reported_update")
    elif skipped == latest and downloaded != latest:
        payload.update(status="skipped", reason="provider_release_skipped")
    else:
        payload.update(status="no_update_reported", reason="provider_no_update_reported")
    return payload


def update_observation(hass: Any, *, include_entity_id: bool = True) -> dict[str, Any]:
    """Read the exact registered provider afresh; failures stay informational.

    The two exception boundaries contain only optional registry/provider reads. They
    must never catch failures in the surrounding Diagnostics, Stability, or control
    code. No last-good cache can turn a later missing provider into an all-clear.
    """
    try:
        entity_id, reason = _resolve_entity(hass)
    except Exception:  # Optional provider/registry failure must not break HI.
        return _payload("registry_unavailable")
    if reason is not None:
        return _payload(reason)
    try:
        payload = _observe_state(hass, entity_id)
    except Exception:  # Contain only the optional provider's state/attributes.
        payload = _payload("state_read_failed", entity_id=entity_id)
    return payload if include_entity_id else support_update_observation(payload)


def support_update_observation(payload: dict[str, Any]) -> dict[str, Any]:
    """Omit the locally renamed source identity from support/native exports."""
    return {**payload, "entity_id": None}
