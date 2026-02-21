"""Humidity Intelligence integration for Home Assistant."""

from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .services import async_register_services, async_unregister_services
from .helpers.cleanup import list_generated_files, remove_files, remove_dashboard
from .ui.register import async_register_cards, async_build_entity_mapping
from .automations import async_setup_entry as async_setup_automations
from .automations import async_unload_entry as async_unload_automations

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Humidity Intelligence integration via YAML."""
    if DOMAIN in config:
        _LOGGER.warning(
            "Configuration via YAML is deprecated for %s; please use the configuration UI.",
            DOMAIN,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Humidity Intelligence from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    effective_config = _effective_entry_config(entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "config": effective_config,
        "options": entry.options,
    }

    await async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "binary_sensor", "switch"])
    await async_setup_automations(hass, entry)

    # Prepare UI card YAML for this entry using entity mapping.
    try:
        mapping = await async_build_entity_mapping(hass, entry.entry_id)
        cards = await async_register_cards(hass, entry.entry_id, mapping=mapping)
    except Exception:
        _LOGGER.exception("Failed to build UI mapping/cards for entry %s", entry.entry_id)
        mapping = {}
        cards = {}
    hass.data[DOMAIN][entry.entry_id]["cards"] = cards
    hass.data[DOMAIN][entry.entry_id]["entity_map"] = mapping
    hass.async_create_task(_async_refresh_and_dump_cards(hass, entry.entry_id))

    ui_layouts = entry.data.get("ui_layouts") or []
    if ui_layouts and not entry.data.get("ui_install_done"):
        await hass.services.async_call(
            DOMAIN,
            "dump_cards",
            {"entry_id": entry.entry_id},
            blocking=False,
        )
        dashboard_id = "humidity-intelligence"
        if "create_dashboard" in ui_layouts:
            await hass.services.async_call(
                DOMAIN,
                "create_dashboard",
                {
                    "entry_id": entry.entry_id,
                    "layout": "v2_mobile" if "v2_mobile" in ui_layouts else "v2_tablet",
                    "title": "Humidity Intelligence",
                    "url_path": dashboard_id,
                },
                blocking=False,
            )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence UI Cards",
                "message": (
                    "Cards written to /config/humidity_intelligence_cards_<layout>.yaml. "
                    "Open File Editor, copy the YAML for your chosen layout(s), and paste into a Manual card."
                ),
            },
            blocking=False,
        )
        data = dict(entry.data)
        data["ui_install_done"] = True
        if "create_dashboard" in ui_layouts:
            data["ui_dashboard_id"] = dashboard_id
        hass.config_entries.async_update_entry(entry, data=data)
    _LOGGER.info("Humidity Intelligence v2 entry %s set up", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor", "binary_sensor", "switch"])
    await async_unload_automations(hass, entry)
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if unsub := data.get("core_unsub"):
        unsub()
    if unsub := data.get("slope_unsub"):
        unsub()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    await async_unregister_services(hass)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove config entry data and generated files."""
    files = list_generated_files(entry)
    dashboard_id = entry.data.get("ui_dashboard_id")
    message_lines = [f"/config/{f}" for f in files]
    if dashboard_id:
        message_lines.append(f"Dashboard: {dashboard_id}")
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Humidity Intelligence Cleanup",
            "message": "Removing generated files:\n" + "\n".join(message_lines),
        },
        blocking=False,
    )
    await hass.async_add_executor_job(remove_files, hass, files)
    await remove_dashboard(hass, dashboard_id)


async def _async_refresh_and_dump_cards(hass: HomeAssistant, entry_id: str) -> None:
    """Rebuild mapping and rewrite card files after startup."""
    try:
        await hass.services.async_call(
            DOMAIN,
            "refresh_ui",
            {"entry_id": entry_id},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "dump_cards",
            {"entry_id": entry_id},
            blocking=True,
        )
    except Exception:
        _LOGGER.exception(
            "Failed startup refresh/dump for Humidity Intelligence entry %s",
            entry_id,
        )


def _effective_entry_config(entry: ConfigEntry) -> dict:
    config = dict(entry.data or {})
    options = dict(entry.options or {})
    config.update(options)
    return config


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change so runtime lanes immediately honor updates."""
    await hass.config_entries.async_reload(entry.entry_id)
