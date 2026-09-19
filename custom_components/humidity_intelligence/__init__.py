"""Humidity Intelligence integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AUTO_REFRESH_UI_ON_STARTUP,
    CONF_SHOW_OUTPUT_ENTITY_DETAILS,
    DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
    DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS,
    DOMAIN,
    STARTUP_UI_REFRESH_DELAY_SECONDS,
)
from .services import (
    SERVICE_REFRESH_UI,
    async_export_cards_to_owned_ui,
    async_register_services,
    async_unregister_services,
)
from .helpers.cleanup import list_owned_ui_filenames
from .helpers.report_exports import (
    ReportExportError,
    plan_owned_ui_export_removal,
    remove_owned_ui_export,
)
from .helpers.drift_repairs import async_update_humidity_drift_repair_issue
from .helpers.entity_registry import normalize_pm25_aggregate_entity_ids
from .ui.register import async_register_cards, async_build_entity_mapping
from .automations import async_setup_entry as async_setup_automations
from .automations import async_unload_entry as async_unload_automations

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    entry_data.update({
        "config": effective_config,
        "options": entry.options,
    })

    await async_register_services(hass)

    try:
        pm25_normalization = normalize_pm25_aggregate_entity_ids(hass, entry.entry_id)
    except Exception:
        _LOGGER.exception(
            "Failed PM2.5 aggregate entity ID normalization for HI entry %s",
            entry.entry_id,
        )
        pm25_normalization = {
            "changed": {},
            "blocked": [
                {
                    "reason": "normalization_exception",
                }
            ],
        }
    else:
        changed_pm25_entity_ids = pm25_normalization.get("changed", {})
        blocked_pm25_entity_ids = pm25_normalization.get("blocked", [])
        if changed_pm25_entity_ids:
            _LOGGER.info(
                "Normalized HI PM2.5 aggregate entity IDs for entry %s: %s",
                entry.entry_id,
                sorted(changed_pm25_entity_ids.values()),
            )
        if blocked_pm25_entity_ids:
            _LOGGER.warning(
                "HI PM2.5 aggregate entity ID normalization has blocked conflicts for entry %s: %s",
                entry.entry_id,
                blocked_pm25_entity_ids,
            )
    entry_data["pm25_entity_id_normalization"] = pm25_normalization

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "binary_sensor", "switch"])
    await async_update_humidity_drift_repair_issue(hass)
    await async_setup_automations(hass, entry)

    # Optional static presentation resource; it has no authority over the engine.
    observation_settings = effective_config.get("output_observation", {})
    if isinstance(observation_settings, dict) and observation_settings.get("enabled") is True:
        try:
            from .adaptive_output.frontend import async_register_frontend

            await async_register_frontend(hass)
        except Exception:
            _LOGGER.exception("Output-status resource unavailable; native card export remains available")

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
    _async_register_startup_ui_refresh(hass, entry)

    await _async_install_selected_ui(hass, entry)
    _LOGGER.info("Humidity Intelligence v2 entry %s set up", entry.entry_id)
    return True


async def _async_install_selected_ui(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Complete the persisted first-run UI choice without blocking backend setup."""
    ui_layouts = entry.data.get("ui_layouts") or []
    if not ui_layouts or entry.data.get("ui_install_done"):
        return

    written_cards = []
    card_export_error = None
    multi_entry_export = False
    try:
        all_entries = hass.config_entries.async_entries(DOMAIN)
        multi_entry_export = len(all_entries) > 1
        export_entry_id = None if multi_entry_export else entry.entry_id
        written_cards = await async_export_cards_to_owned_ui(
            hass,
            export_entry_id,
            None,
            layout=None,
        )
    except Exception as err:
        card_export_error = err
        _LOGGER.exception(
            "First-run generated card export failed for HI entry %s",
            entry.entry_id,
        )
    legacy_dashboard_selection = "create_dashboard" in ui_layouts
    if legacy_dashboard_selection:
        _LOGGER.info(
            "Ignoring legacy create_dashboard UI selection for HI entry %s; "
            "Manual-card exports remain available",
            entry.entry_id,
        )
    if card_export_error is not None:
        card_title = "Humidity Intelligence UI Card Export Incomplete"
        card_message = (
            "Generated cards could not be written to "
            "/config/humidity_intelligence/ui/. HI backend setup remains available. "
            "Retry humidity_intelligence.dump_cards from an authenticated admin UI "
            "or API session and check the Home Assistant log."
        )
    elif written_cards:
        card_title = "Humidity Intelligence UI Cards"
        card_message = (
            "Manual-card YAML written:\n"
            + "\n".join(written_cards)
            + "\n\nOpen the required file in File Editor and copy the complete YAML. "
            "For a new dashboard, create it through Home Assistant, open Edit "
            "dashboard, choose Add card -> Manual, and paste the YAML. For an "
            "existing HI Manual card, edit that card and replace its complete YAML. "
            "HI does not create or replace dashboards automatically. These exports "
            "are card fragments; do not copy them to /config/dashboards/."
            "\n\nSince v2.0.9, generated card files live under "
            "/config/humidity_intelligence/ui/. Older generated card files in the "
            "/config root are retained but are no longer refreshed. Use only the "
            "exact paths above."
        )
        if multi_entry_export:
            card_message += (
                "\n\nThis is a multi-entry installation. Use only the exact "
                "entry-qualified paths above. Any earlier unqualified owned UI "
                "exports are retained but are no longer refreshed."
            )
    else:
        card_title = "Humidity Intelligence UI Cards"
        card_message = "No generated cards were available to export."
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": card_title,
            "message": card_message,
        },
        blocking=False,
    )
    data = dict(entry.data)
    data["ui_install_done"] = True
    hass.config_entries.async_update_entry(entry, data=data)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor", "binary_sensor", "switch"])
    await async_unload_automations(hass, entry)
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    observer = data.pop("output_observer", None)
    if observer is not None and observer.active:
        try:
            await observer.async_stop()
        except Exception:
            _LOGGER.exception("Optional output observer cleanup failed")
    if unsub := data.get("startup_ui_refresh_unsub"):
        unsub()
    data.pop("startup_ui_refresh_scheduled", None)
    task = data.pop("startup_ui_refresh_task", None)
    if isinstance(task, asyncio.Task):
        task.cancel()
    if unsub := data.get("stability_snapshot_unsub"):
        unsub()
    if unsub := data.get("core_unsub"):
        unsub()
    if unsub := data.get("slope_unsub"):
        unsub()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    await async_unregister_services(hass)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove config entry data and generated files."""
    cleanup_failures = []
    current_entries = hass.config_entries.async_entries(DOMAIN)
    remaining_entries = [
        item for item in current_entries if item.entry_id != entry.entry_id
    ]
    known_entry_ids = {item.entry_id for item in current_entries}
    known_entry_ids.add(entry.entry_id)
    multiple_installation = len(known_entry_ids) > 1
    filenames = list_owned_ui_filenames(
        [entry],
        multiple_installation=multiple_installation,
        include_unqualified_defaults=not multiple_installation,
    )
    try:
        ui_plans = await hass.async_add_executor_job(
            plan_owned_ui_export_removal,
            hass.config.path(),
            filenames,
        )
    except ReportExportError as err:
        ui_plans = []
        cleanup_failures.append(f"UI cleanup plan: {err}")
        _LOGGER.warning(
            "Unable to plan generated UI cleanup for HI entry %s: %s",
            entry.entry_id,
            err,
        )
    message_lines = [f"/config/{plan.relative_path}" for plan in ui_plans]
    cleanup_message = (
        "Removing generated artifacts:\n" + "\n".join(message_lines)
        if message_lines
        else "No existing generated UI files were found."
    )
    cleanup_message += (
        "\n\nHome Assistant dashboards are user-managed and are not removed by "
        "Humidity Intelligence."
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Humidity Intelligence Cleanup",
            "message": cleanup_message,
        },
        blocking=False,
    )
    for plan in ui_plans:
        try:
            await hass.async_add_executor_job(
                remove_owned_ui_export,
                hass.config.path(),
                plan,
            )
        except ReportExportError as err:
            cleanup_failures.append(f"/config/{plan.relative_path}: {err}")
            _LOGGER.exception(
                "Unable to remove generated UI export %s during entry removal",
                plan.relative_path,
            )
    remaining_written = []
    if len(remaining_entries) == 1:
        try:
            remaining_written = await async_export_cards_to_owned_ui(
                hass,
                remaining_entries[0].entry_id,
                None,
                layout=None,
                multiple_installation=False,
            )
        except Exception as err:
            cleanup_failures.append(
                "Remaining single-entry card export: " + str(err)
            )
            _LOGGER.exception(
                "Unable to export unqualified generated UI after removing HI entry %s",
                entry.entry_id,
            )
    if remaining_written:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence UI Cards Updated",
                "message": (
                    "The remaining single entry now uses these generated card paths:\n"
                    + "\n".join(remaining_written)
                ),
            },
            blocking=False,
        )
    if cleanup_failures:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Cleanup Incomplete",
                "message": (
                    "Some generated artifacts could not be removed:\n"
                    + "\n".join(cleanup_failures)
                ),
            },
            blocking=False,
        )


async def _async_refresh_and_dump_cards(
    hass: HomeAssistant,
    entry_id: str,
) -> list[str]:
    """Rebuild mapping and rewrite card files for explicit UI export refreshes."""
    await hass.services.async_call(
        DOMAIN,
        "refresh_ui",
        {"entry_id": entry_id},
        blocking=True,
    )
    return await async_export_cards_to_owned_ui(
        hass,
        entry_id,
        None,
        layout=None,
    )


def _async_register_startup_ui_refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh HI UI mapping once Home Assistant has finished startup."""
    if not _entry_auto_refresh_ui_on_startup(entry):
        _LOGGER.debug(
            "HI entry %s startup UI refresh skipped: option disabled.",
            entry.entry_id,
        )
        return

    if _hass_already_started(hass):
        _LOGGER.debug(
            "HI entry %s startup UI refresh skipped: Home Assistant is already running.",
            entry.entry_id,
        )
        return

    data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    if data.get("startup_ui_refresh_unsub") or data.get("startup_ui_refresh_scheduled"):
        _LOGGER.debug(
            "HI entry %s startup UI refresh skipped: listener/task already exists.",
            entry.entry_id,
        )
        return

    @callback
    def _handle_started(_event) -> None:
        data.pop("startup_ui_refresh_unsub", None)
        data["startup_ui_refresh_scheduled"] = True

        async def _run_startup_ui_refresh() -> None:
            try:
                await _async_delayed_startup_ui_refresh(hass, entry.entry_id)
            finally:
                data.pop("startup_ui_refresh_scheduled", None)
                data.pop("startup_ui_refresh_task", None)

        # EVENT_HOMEASSISTANT_STARTED can be fired from outside the event-loop
        # thread during startup; create_task may return None on some HA builds.
        task = hass.create_task(_run_startup_ui_refresh())
        if isinstance(task, asyncio.Task):
            data["startup_ui_refresh_task"] = task
        _LOGGER.debug(
            "HI entry %s startup UI refresh scheduled after Home Assistant started.",
            entry.entry_id,
        )

    data["startup_ui_refresh_unsub"] = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED,
        _handle_started,
    )
    _LOGGER.debug(
        "HI entry %s startup UI refresh listener registered.",
        entry.entry_id,
    )


async def _async_delayed_startup_ui_refresh(hass: HomeAssistant, entry_id: str) -> None:
    """Run the startup UI refresh after a short availability delay."""
    try:
        await asyncio.sleep(STARTUP_UI_REFRESH_DELAY_SECONDS)
        if entry_id not in hass.data.get(DOMAIN, {}):
            _LOGGER.debug(
                "HI entry %s startup UI refresh skipped: integration data is no longer loaded.",
                entry_id,
            )
            return
        if not hass.config_entries.async_get_entry(entry_id):
            _LOGGER.debug(
                "HI entry %s startup UI refresh skipped: config entry is no longer loaded.",
                entry_id,
            )
            return

        await hass.services.async_call(
            DOMAIN,
            SERVICE_REFRESH_UI,
            {"entry_id": entry_id},
            blocking=True,
        )
        _LOGGER.debug("HI entry %s startup UI refresh completed.", entry_id)
    except asyncio.CancelledError:
        _LOGGER.debug("HI entry %s startup UI refresh cancelled.", entry_id)
        raise
    except Exception:
        _LOGGER.exception("HI entry %s startup UI refresh failed.", entry_id)


def _entry_auto_refresh_ui_on_startup(entry: ConfigEntry) -> bool:
    """Resolve startup UI refresh option with a default-on fallback."""
    return bool(
        _effective_entry_config(entry).get(
            CONF_AUTO_REFRESH_UI_ON_STARTUP,
            DEFAULT_AUTO_REFRESH_UI_ON_STARTUP,
        )
    )


def _hass_already_started(hass: HomeAssistant) -> bool:
    """Return true when setup is running after the startup event has passed."""
    state = getattr(hass, "state", None)
    return state == "running" or getattr(state, "value", None) == "running"


def _effective_entry_config(entry: ConfigEntry) -> dict:
    config = dict(entry.data or {})
    options = dict(entry.options or {})
    config.update(options)
    return config


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change so runtime lanes immediately honor updates."""
    previous_cfg = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("config", {}) or {}
    )
    prev_alert_only = bool(previous_cfg.get("alert_only_mode", _entry_alert_only_mode(entry)))
    prev_output_details = bool(
        previous_cfg.get(
            CONF_SHOW_OUTPUT_ENTITY_DETAILS,
            _entry_show_output_entity_details(entry),
        )
    )
    def observation_presentation(config):
        settings = config.get("output_observation", {})
        if not isinstance(settings, dict):
            return (False, "native")
        return (settings.get("enabled") is True, settings.get("presentation", "native"))

    previous_observation = observation_presentation(previous_cfg)
    next_observation = observation_presentation({**entry.data, **entry.options})
    next_alert_only = _entry_alert_only_mode(entry)
    next_output_details = _entry_show_output_entity_details(entry)
    await hass.config_entries.async_reload(entry.entry_id)
    ui_visibility_changed = (
        prev_alert_only != next_alert_only
        or prev_output_details != next_output_details
        or previous_observation != next_observation
    )
    if not ui_visibility_changed:
        return

    _LOGGER.info(
        "HI entry %s UI visibility changed; regenerating UI card exports.",
        entry.entry_id,
    )
    changed = []
    if prev_alert_only != next_alert_only:
        changed.append("alert-only mode")
    if prev_output_details != next_output_details:
        changed.append("generated-card output details")
    if previous_observation != next_observation:
        changed.append("output observation presentation")
    try:
        written = await _async_refresh_and_dump_cards(hass, entry.entry_id)
    except Exception as err:
        _LOGGER.exception(
            "Failed UI refresh/export after options update for HI entry %s",
            entry.entry_id,
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence UI Update Incomplete",
                "message": (
                    f"{', '.join(changed).title()} changed, but generated card "
                    "export did not complete. No success path is being reported. "
                    f"Check the Home Assistant log and retry dump_cards: {err}"
                ),
            },
            blocking=False,
        )
        return
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Humidity Intelligence UI Updated",
            "message": (
                f"{', '.join(changed).title()} changed. Updated card files:\n"
                + ("\n".join(written) if written else "No card files were generated.")
                + "\n\n"
                "Re-copy/paste the layout YAML into your Manual card to apply UI visibility changes. "
                "Use only the exact paths above; legacy generated card files in "
                "the /config root are no longer refreshed."
            ),
        },
        blocking=False,
    )


def _entry_alert_only_mode(entry: ConfigEntry) -> bool:
    options = getattr(entry, "options", None) or {}
    if "alert_only_mode" in options:
        return bool(options.get("alert_only_mode"))
    data = getattr(entry, "data", None) or {}
    return bool(data.get("alert_only_mode", False))


def _entry_show_output_entity_details(entry: ConfigEntry) -> bool:
    options = getattr(entry, "options", None) or {}
    if CONF_SHOW_OUTPUT_ENTITY_DETAILS in options:
        return bool(options.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS))
    data = getattr(entry, "data", None) or {}
    if CONF_SHOW_OUTPUT_ENTITY_DETAILS in data:
        return bool(data.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS))
    return DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS
