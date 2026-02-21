"""Cleanup helpers for Humidity Intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry


def list_generated_files(entry: ConfigEntry) -> List[str]:
    """Return generated filenames (relative to /config) for an entry."""
    layouts = entry.data.get("ui_layouts") or []
    if not layouts:
        layouts = ["v2_mobile", "v2_tablet", "v1_mobile", "view_cards_button"]

    filenames = set()
    base = "humidity_intelligence_cards"
    for layout in layouts:
        filenames.add(f"{base}_{layout}.yaml")
        filenames.add(f"{base}_{entry.entry_id}_{layout}.yaml")
    # Legacy or single-file outputs
    filenames.add("humidity_intelligence_cards.json")
    filenames.add("humidity_intelligence_cards.yaml")
    # Diagnostics outputs
    filenames.add("humidity_intelligence_diagnostics.json")
    filenames.add("humidity_intelligence_self_check.json")
    return sorted(filenames)


def list_all_generated_files(entries: Iterable[ConfigEntry]) -> List[str]:
    files = set()
    for entry in entries:
        for name in list_generated_files(entry):
            files.add(name)
    return sorted(files)


def remove_files(hass: HomeAssistant, filenames: Iterable[str]) -> None:
    for name in filenames:
        path = Path(hass.config.path(name))
        try:
            if path.exists():
                path.unlink()
        except Exception:
            # swallow any file errors
            continue


async def remove_dashboard(hass: HomeAssistant, dashboard_id: str | None) -> None:
    if not dashboard_id:
        return
    try:
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard
        await lovelace_dashboard.async_delete_dashboard(hass, dashboard_id=dashboard_id)
    except Exception:
        # ignore dashboard removal failures
        return
