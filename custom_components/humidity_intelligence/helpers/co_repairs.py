"""Entry-owned, observational repair notices for unsupported CO source units."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DOMAIN
from .air_quality import aq_unit_supported


@callback
def async_setup_co_unit_repair(hass: Any, entry: Any, config: dict[str, Any]) -> None:
    """Warn on explicit unit problems without changing sources or control decisions."""
    sources = sorted({
        item["entity_id"]
        for item in config.get("telemetry", []) or []
        if isinstance(item, dict) and item.get("sensor_type") == "co"
        and isinstance(item.get("entity_id"), str) and item["entity_id"]
    })
    issue_id = f"co_unit_unsupported_{entry.entry_id}"

    @callback
    def update(_event: Any = None) -> None:
        invalid = []
        for entity_id in sources:
            state = hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue
            if not aq_unit_supported(
                "co", state.attributes.get("unit_of_measurement")
            ):
                invalid.append(entity_id)
        if invalid:
            ir.async_create_issue(
                hass, DOMAIN, issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="co_unit_unsupported",
                translation_placeholders={"entities": ", ".join(invalid)},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    unsubscribe = async_track_state_change_event(hass, sources, update) if sources else None

    @callback
    def cleanup() -> None:
        if unsubscribe is not None:
            unsubscribe()
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    entry.async_on_unload(cleanup)
    update()
