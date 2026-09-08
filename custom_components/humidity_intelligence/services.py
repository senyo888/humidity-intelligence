"""Service handlers for Humidity Intelligence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import CONF_SHOW_OUTPUT_ENTITY_DETAILS, DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS, DOMAIN
from .helpers.cleanup import (
    RELEASE_CHECK_CARD_BASE,
    build_generated_card_filename,
    list_owned_ui_filenames,
)
from .helpers.drift import humidity_drift_dependency_status, humidity_drift_warning
from .helpers.diagnostics_redaction import redact_diagnostics_payload
from .helpers.frontend_dependencies import (
    async_frontend_dependency_status,
    frontend_dependency_not_inspectable,
)
from .helpers.level_labels import resolve_level_label_details
from .helpers.local_versions import (
    DEFAULT_MAX_TOTAL_BYTES,
    DEFAULT_RETAIN_COUNT,
    HARD_MAX_TOTAL_BYTES,
    MAX_RETAIN_COUNT,
    MIN_RETAIN_COUNT,
    LocalVersionError,
    async_create_local_backup,
    async_list_saved_versions,
    async_local_version_status,
    cached_local_version_status,
)
from .helpers.report_exports import (
    DEFAULT_SELF_CHECK_REPORT_FILENAME,
    ReportExportError,
    plan_default_diagnostics_report_removal,
    plan_default_self_check_report_removal,
    plan_owned_ui_export_removal,
    remove_default_diagnostics_report,
    remove_default_self_check_report,
    remove_owned_ui_export,
    write_owned_report,
    write_owned_ui_export,
)
from .helpers.runtime_control import runtime_control_summary
from .helpers.seasonal import resolve_target_profile, resolve_temperature_comfort_profile
from .helpers.zone_validation import (
    detect_zone_mapping_duplicates,
    summarize_zone_mapping_duplicate_count_warning,
    summarize_zone_mapping_duplicate_counts,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_FLASH_LIGHTS = "flash_lights"
SERVICE_REFRESH_UI = "refresh_ui"
SERVICE_DUMP_DIAGNOSTICS = "dump_diagnostics"
SERVICE_SELF_CHECK = "self_check"
SERVICE_V205_RELEASE_CHECK = "v205_release_check"
SERVICE_DUMP_CARDS = "dump_cards"
SERVICE_CREATE_DASHBOARD = "create_dashboard"
SERVICE_VIEW_CARDS = "view_cards"
SERVICE_PURGE_FILES = "purge_files"
SERVICE_PAUSE_CONTROL = "pause_control"
SERVICE_RESUME_CONTROL = "resume_control"
SERVICE_CREATE_LOCAL_BACKUP = "create_local_backup"
SERVICE_LIST_SAVED_VERSIONS = "list_saved_versions"
_FLASH_LIGHT_LOCKS_KEY = "_flash_light_locks"

_ALLOWED_LAYOUTS = {"v2_mobile", "v2_tablet", "v1_mobile", "view_cards_button"}
_ALLOWED_VISUAL_POWER_DOMAINS = {"light", "switch"}
_GENERATED_CARD_ENTITY_DOMAINS = (
    "alarm_control_panel",
    "binary_sensor",
    "button",
    "calendar",
    "camera",
    "climate",
    "cover",
    "device_tracker",
    "event",
    "fan",
    "humidifier",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "light",
    "lock",
    "media_player",
    "number",
    "person",
    "remote",
    "scene",
    "script",
    "select",
    "sensor",
    "siren",
    "switch",
    "timer",
    "update",
    "vacuum",
    "weather",
    "zone",
)
_GENERATED_CARD_ENTITY_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(domain) for domain in _GENERATED_CARD_ENTITY_DOMAINS)
    + r")\.[A-Za-z0-9_]+\b"
)
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_OWNED_REPORT_FILENAME_PREFIX = "humidity_intelligence_"
_OWNED_REPORT_FILENAME_SUFFIX = ".json"
_RELEASE_CHECK_MANIFEST_VERSION_RE = re.compile(
    r"^2\.0\.(?:5|(?:[6-9]|1[0-2])(?:-(?:beta|rc)\.[1-9]\d*)?)$"
)
_SENSITIVE_ATTR_EXACT = {
    "access_token",
    "token",
    "refresh_token",
    "password",
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "credential_json",
    "latitude",
    "longitude",
    "gps_accuracy",
    "address",
    "email",
    "phone",
    "device_id",
    "unique_id",
    "mac",
    "ssid",
    "ip",
}
_SENSITIVE_ATTR_PARTIAL = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "bearer",
    "credential",
    "latitude",
    "longitude",
    "gps_",
    "address",
    "email",
    "phone",
    "device_id",
    "unique_id",
    "mac_",
    "_mac",
    "ssid",
    "ip_address",
)


def _validate_layout(value: str) -> str:
    text = str(value).strip()
    if text not in _ALLOWED_LAYOUTS:
        raise vol.Invalid(
            f"Unsupported layout '{text}'. Allowed: {', '.join(sorted(_ALLOWED_LAYOUTS))}"
        )
    return text


def _validate_safe_filename(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise vol.Invalid("Filename cannot be empty")
    if "/" in text or "\\" in text or ".." in text:
        raise vol.Invalid("Filename must not include directory traversal or separators")
    if not _SAFE_FILENAME_RE.fullmatch(text):
        raise vol.Invalid("Filename contains invalid characters")
    return text


def _validate_owned_report_filename(value: str) -> str:
    try:
        text = _validate_safe_filename(value)
    except vol.Invalid as err:
        raise vol.Invalid(
            "Report filename must use humidity_intelligence_*.json"
        ) from err
    if not (
        isinstance(value, str)
        and text == value
        and text.startswith(_OWNED_REPORT_FILENAME_PREFIX)
        and text.endswith(_OWNED_REPORT_FILENAME_SUFFIX)
    ):
        raise vol.Invalid("Report filename must use humidity_intelligence_*.json")
    return text


def _validate_rgb_color(value) -> List[int]:
    """Accept service/YAML RGB colors and normalize them to a plain list."""
    if isinstance(value, tuple):
        values = list(value)
    else:
        values = cv.ensure_list(value)
    values = [vol.Coerce(int)(item) for item in values]
    if len(values) < 3:
        raise vol.Invalid("RGB color must include red, green, and blue values")
    for item in values[:3]:
        if item < 0 or item > 255:
            raise vol.Invalid("RGB color values must be between 0 and 255")
    return values[:3]


def _validate_visual_power_entity(value: str) -> str:
    text = cv.entity_id(value)
    domain = text.split(".", 1)[0]
    if domain not in _ALLOWED_VISUAL_POWER_DOMAINS:
        raise vol.Invalid("Visual alert power_entity must be a switch or light entity")
    return text


def _validate_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    raise vol.Invalid("Expected a boolean value")


async def _async_require_admin_user(hass: HomeAssistant, call: ServiceCall, service_name: str) -> None:
    context = getattr(call, "context", None)
    user_id = getattr(context, "user_id", None)
    auth = getattr(hass, "auth", None)
    async_get_user = getattr(auth, "async_get_user", None)
    if not user_id or not callable(async_get_user):
        raise HomeAssistantError(f"{service_name} requires an admin user context")
    user = await async_get_user(user_id)
    if not bool(getattr(user, "is_admin", False)):
        raise HomeAssistantError(f"{service_name} requires an admin user context")


SERVICE_FLASH_SCHEMA = vol.Schema({
    vol.Optional("power_entity"): _validate_visual_power_entity,
    vol.Optional("lights", default=[]): cv.entity_ids,
    vol.Optional("color", default=[255, 0, 0]): _validate_rgb_color,
    vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
    vol.Optional("flash_count", default=None): vol.Any(
        None,
        vol.All(vol.Coerce(int), vol.Range(min=1, max=240)),
    ),
})
SERVICE_REFRESH_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_DUMP_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename", default="humidity_intelligence_diagnostics.json"): _validate_owned_report_filename,
})
SERVICE_SELF_CHECK_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_V205_RELEASE_CHECK_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename", default="humidity_intelligence_v205_release_check.json"): _validate_owned_report_filename,
    vol.Optional("write_test_exports", default=False): _validate_bool,
    vol.Optional("require_local_hi_snapshot", default=False): _validate_bool,
    vol.Optional("max_snapshot_age_minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=10080)),
})
SERVICE_DUMP_CARDS_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename"): _validate_safe_filename,
    vol.Optional("layout"): _validate_layout,
})
SERVICE_CREATE_DASHBOARD_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("layout", default="v2_mobile"): cv.string,
    vol.Optional("title", default="Humidity Intelligence"): cv.string,
    vol.Optional("url_path", default="humidity-intelligence"): cv.string,
})
SERVICE_VIEW_CARDS_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename"): _validate_safe_filename,
    vol.Optional("layout"): _validate_layout,
})
SERVICE_PURGE_FILES_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_PAUSE_CONTROL_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
})
SERVICE_RESUME_CONTROL_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_CREATE_LOCAL_BACKUP_SCHEMA = vol.Schema({
    vol.Optional("retain_count", default=DEFAULT_RETAIN_COUNT): vol.All(
        vol.Coerce(int),
        vol.Range(min=MIN_RETAIN_COUNT, max=MAX_RETAIN_COUNT),
    ),
    vol.Optional("max_total_bytes", default=DEFAULT_MAX_TOTAL_BYTES): vol.All(
        vol.Coerce(int),
        vol.Range(min=1, max=HARD_MAX_TOTAL_BYTES),
    ),
})
SERVICE_LIST_SAVED_VERSIONS_SCHEMA = vol.Schema({})


async def async_create_dashboard_for_entry(
    hass: HomeAssistant,
    entry: Any,
    *,
    layout: str,
    title: str,
    url_path: str,
) -> bool:
    """Return deterministic Manual-card guidance without dashboard mutation."""
    del hass, entry, layout, title, url_path
    raise HomeAssistantError(
        "Humidity Intelligence cannot create or register a Home Assistant dashboard "
        "automatically. No file or dashboard was changed. Run "
        "humidity_intelligence.refresh_ui, then humidity_intelligence.view_cards "
        "with the intended entry_id and layout. Open the exact "
        "/config/humidity_intelligence/ui/... path from the notification. In Home "
        "Assistant, create or open a dashboard, choose Edit dashboard, then add or "
        "edit a Manual card and paste the full exported YAML. The export is a card "
        "fragment; do not copy it to /config/dashboards/."
    )


async def async_flash_lights_for_alert(
    hass: HomeAssistant,
    *,
    power_entity: Optional[str] = None,
    lights: Optional[List[str]] = None,
    color: Optional[List[int]] = None,
    duration: int = 10,
    flash_count: Optional[int] = None,
) -> None:
    """Run one trusted HI visual-alert flash without using the public service."""
    if power_entity:
        try:
            power_entity = _validate_visual_power_entity(power_entity)
        except vol.Invalid as err:
            raise HomeAssistantError(str(err)) from err

    lights = _dedupe_lights(lights or [])
    color_list = color or [255, 0, 0]
    duration = max(1, int(duration))
    rgb_color = tuple(color_list[:3]) if len(color_list) >= 3 else (255, 0, 0)

    if not lights:
        _LOGGER.debug("No lights provided for visual alert; skipping light flash.")
        return

    locks = _light_flash_locks(hass, lights)
    acquired_locks: List[asyncio.Lock] = []
    try:
        for lock in locks:
            await lock.acquire()
            acquired_locks.append(lock)

        initial_states = _capture_light_states(hass, lights)

        if power_entity:
            domain = power_entity.split(".")[0]
            if hass.services.has_service(domain, "turn_on"):
                try:
                    await hass.services.async_call(
                        domain,
                        "turn_on",
                        {"entity_id": power_entity},
                        blocking=True,
                    )
                    await asyncio.sleep(0.5)
                except Exception:
                    _LOGGER.exception(
                        "Failed to turn on alert power entity %s",
                        power_entity,
                    )

        supports_color = {
            light: _supports_color(hass.states.get(light))
            for light in lights
        }
        await _flash_lights(
            hass,
            lights,
            rgb_color,
            duration,
            flash_count,
            supports_color,
        )
        await _restore_lights(hass, initial_states)
    finally:
        for lock in reversed(acquired_locks):
            try:
                lock.release()
            except RuntimeError:
                continue


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def handle_flash(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_FLASH_LIGHTS)
        await async_flash_lights_for_alert(
            hass,
            power_entity=call.data.get("power_entity"),
            lights=call.data.get("lights"),
            color=call.data.get("color"),
            duration=call.data.get("duration", 10),
            flash_count=call.data.get("flash_count"),
        )

    hass.services.async_register(DOMAIN, SERVICE_FLASH_LIGHTS, handle_flash, schema=SERVICE_FLASH_SCHEMA)

    async def handle_refresh(call: ServiceCall) -> None:
        from .ui.register import async_build_entity_mapping, async_register_cards

        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            mapping = await async_build_entity_mapping(hass, entry.entry_id)
            cards = await async_register_cards(hass, entry.entry_id, mapping=mapping)
            hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
            hass.data[DOMAIN][entry.entry_id]["entity_map"] = mapping
            hass.data[DOMAIN][entry.entry_id]["cards"] = cards

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_UI, handle_refresh, schema=SERVICE_REFRESH_SCHEMA)

    async def handle_dump(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_DUMP_DIAGNOSTICS)
        try:
            entry_id = call.data.get("entry_id")
            filename = call.data.get("filename", "humidity_intelligence_diagnostics.json")
            entries = []
            if entry_id:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry:
                    entries = [entry]
            else:
                entries = hass.config_entries.async_entries(DOMAIN)

            frontend_dependencies = await async_frontend_dependency_status(hass)
            local_version_status = await async_local_version_status(hass)
            payload = {}
            for entry in entries:
                data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
                entity_map = data.get("entity_map", {})
                config = data.get("config", {})
                options = data.get("options", {})
                diagnostics_summary = _build_diagnostics_summary(
                    hass,
                    config,
                    options,
                    entity_map,
                    data,
                    frontend_dependencies=frontend_dependencies,
                    local_version_status=local_version_status,
                )
                payload[entry.entry_id] = {
                    "configuration_summary": _support_configuration_summary(config, options),
                    "diagnostics_summary": _support_safe_diagnostics_summary(diagnostics_summary),
                    "entity_map_summary": _support_entity_map_summary(entity_map),
                    "cards": list((data.get("cards") or {}).keys()),
                    "state_summary": _support_state_summary(hass, entity_map.values()),
                }

            await hass.async_add_executor_job(
                write_owned_report,
                hass.config.path(),
                filename,
                redact_diagnostics_payload(payload),
            )
        except Exception as err:
            _LOGGER.exception("Diagnostics report operation did not complete")
            raise HomeAssistantError(
                f"Diagnostics report operation incomplete: {err}"
            ) from err

    hass.services.async_register(DOMAIN, SERVICE_DUMP_DIAGNOSTICS, handle_dump, schema=SERVICE_DUMP_SCHEMA)

    async def handle_create_local_backup(call: ServiceCall) -> dict:
        await _async_require_admin_user(hass, call, SERVICE_CREATE_LOCAL_BACKUP)
        try:
            result = await async_create_local_backup(
                hass,
                retain_count=call.data.get("retain_count", DEFAULT_RETAIN_COUNT),
                max_total_bytes=call.data.get("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
            )
        except LocalVersionError as err:
            await _notify_local_version_result(
                hass,
                "Humidity Intelligence Local Snapshot Failed",
                f"FAILED: {err.message}\n\nCategory: `{err.category}`\n\nNo runtime control behavior was changed.",
            )
            raise HomeAssistantError(f"Local HI-only snapshot failed: {err.message}") from err

        await _notify_local_version_result(
            hass,
            "Humidity Intelligence Local Snapshot Created",
            _format_local_backup_created_message(result),
        )
        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_LOCAL_BACKUP,
        handle_create_local_backup,
        schema=SERVICE_CREATE_LOCAL_BACKUP_SCHEMA,
    )

    async def handle_list_saved_versions(call: ServiceCall) -> dict:
        await _async_require_admin_user(hass, call, SERVICE_LIST_SAVED_VERSIONS)
        try:
            result = await async_list_saved_versions(hass)
        except LocalVersionError as err:
            await _notify_local_version_result(
                hass,
                "Humidity Intelligence Local Snapshots Failed",
                f"FAILED: {err.message}\n\nCategory: `{err.category}`",
            )
            raise HomeAssistantError(f"Local HI-only snapshot list failed: {err.message}") from err

        await _notify_local_version_result(
            hass,
            "Humidity Intelligence Local Snapshots",
            _format_local_versions_list_message(result),
        )
        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_SAVED_VERSIONS,
        handle_list_saved_versions,
        schema=SERVICE_LIST_SAVED_VERSIONS_SCHEMA,
    )

    async def handle_self_check(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_SELF_CHECK)
        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        local_version_status = await async_local_version_status(hass)
        report = {}
        for entry in entries:
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            mapping = data.get("entity_map", {})
            missing_entities = []
            for ent in mapping.values():
                if hass.states.get(ent) is None:
                    missing_entities.append(ent)
            frontend_dependencies = await async_frontend_dependency_status(hass)
            drift_dependency = humidity_drift_dependency_status(hass)
            card_entity_availability = _generated_card_entity_availability(
                hass,
                data.get("cards", {}) or {},
            )

            report[entry.entry_id] = {
                "missing_entities": missing_entities,
                "generated_card_entity_availability": card_entity_availability,
                "frontend_dependency_resources": frontend_dependencies,
                "humidity_drift_7d": drift_dependency,
                "pm25_entity_id_normalization": _pm25_normalization_status(data),
                "local_version_preservation": local_version_status,
                "telemetry_count": len(entry.data.get("telemetry", [])),
                "unresolved_placeholders": data.get("unresolved_placeholders", []),
                "unresolved_placeholders_by_card": data.get("unresolved_placeholders_by_card", {}),
            }

        try:
            report_path = await hass.async_add_executor_job(
                write_owned_report,
                hass.config.path(),
                DEFAULT_SELF_CHECK_REPORT_FILENAME,
                report,
            )
        except Exception as err:
            _LOGGER.exception("Self-check report operation did not complete")
            raise HomeAssistantError(
                f"Self-check report operation incomplete: {err}"
            ) from err
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Self Check",
                "message": (
                    "Self-check report written to "
                    f"Home Assistant config/{report_path}. "
                    "Treat this entity-bearing validation report as local/private."
                ),
            },
            blocking=False,
        )

    hass.services.async_register(DOMAIN, SERVICE_SELF_CHECK, handle_self_check, schema=SERVICE_SELF_CHECK_SCHEMA)

    async def handle_v205_release_check(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_V205_RELEASE_CHECK)
        from .ui.register import async_build_entity_mapping, async_register_cards

        entry_id = call.data.get("entry_id")
        filename = call.data.get("filename", "humidity_intelligence_v205_release_check.json")
        write_test_exports = bool(call.data.get("write_test_exports", False))
        require_local_hi_snapshot = bool(call.data.get("require_local_hi_snapshot", False))
        max_snapshot_age_minutes = int(call.data.get("max_snapshot_age_minutes", 60))
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        manifest_version = await _async_read_manifest_version(hass)
        report: Dict[str, Any] = {
            "check": SERVICE_V205_RELEASE_CHECK,
            "status": "pass",
            "entries": {},
        }
        frontend_dependencies = await async_frontend_dependency_status(hass)
        local_version_status = await async_local_version_status(hass)

        if not entries:
            report["status"] = "fail"
            report["entries"] = {}
            report["checks"] = [
                {
                    "id": "config_entry",
                    "status": "fail",
                    "message": "No Humidity Intelligence config entry was found.",
                }
            ]
        else:
            entry_reports = []
            for entry in entries:
                mapping = await async_build_entity_mapping(hass, entry.entry_id)
                cards = await async_register_cards(hass, entry.entry_id, mapping=mapping)
                domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
                domain_data["entity_map"] = mapping
                domain_data["cards"] = cards

                unscoped_written: List[str] = []
                scoped_written: List[str] = []
                if write_test_exports:
                    scoped_base = f"{RELEASE_CHECK_CARD_BASE}_scoped"
                    unscoped_written = await async_export_cards_to_owned_ui(
                        hass,
                        entry.entry_id,
                        RELEASE_CHECK_CARD_BASE,
                        layout=None,
                    )
                    scoped_written = await async_export_cards_to_owned_ui(
                        hass,
                        entry.entry_id,
                        scoped_base,
                        layout="v2_tablet",
                    )

                entry_report = _build_v205_release_check_entry_report(
                    hass,
                    entry,
                    domain_data,
                    manifest_version=manifest_version,
                    frontend_dependencies=frontend_dependencies,
                    local_version_status=local_version_status,
                    require_local_hi_snapshot=require_local_hi_snapshot,
                    max_snapshot_age_minutes=max_snapshot_age_minutes,
                    write_test_exports=write_test_exports,
                    unscoped_written=unscoped_written,
                    scoped_written=scoped_written,
                )
                report["entries"][entry.entry_id] = entry_report
                entry_reports.append(entry_report)

            report["status"] = _combined_check_status(entry_reports)

        try:
            report_path = await hass.async_add_executor_job(
                write_owned_report,
                hass.config.path(),
                filename,
                report,
            )
        except Exception as err:
            _LOGGER.exception("Release-check report operation did not complete")
            raise HomeAssistantError(
                f"Release-check report operation incomplete: {err}"
            ) from err
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Release Check",
                "message": (
                    f"{report['status'].upper()}: report written to "
                    f"Home Assistant config/{report_path}"
                ),
            },
            blocking=False,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_V205_RELEASE_CHECK,
        handle_v205_release_check,
        schema=SERVICE_V205_RELEASE_CHECK_SCHEMA,
    )

    async def handle_dump_cards(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_DUMP_CARDS)
        entry_id = call.data.get("entry_id")
        filename = call.data.get("filename")
        layout = call.data.get("layout")
        await async_export_cards_to_owned_ui(
            hass,
            entry_id,
            filename,
            layout=layout,
        )

    hass.services.async_register(DOMAIN, SERVICE_DUMP_CARDS, handle_dump_cards, schema=SERVICE_DUMP_CARDS_SCHEMA)

    async def handle_create_dashboard(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_CREATE_DASHBOARD)
        await async_create_dashboard_for_entry(
            hass,
            None,
            layout=call.data.get("layout", "v2_mobile"),
            title=call.data.get("title", "Humidity Intelligence"),
            url_path=call.data.get("url_path", "humidity-intelligence"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_DASHBOARD,
        handle_create_dashboard,
        schema=SERVICE_CREATE_DASHBOARD_SCHEMA,
    )

    async def handle_view_cards(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_VIEW_CARDS)
        filename = call.data.get("filename")
        layout = call.data.get("layout")
        written = await async_export_cards_to_owned_ui(
            hass,
            call.data.get("entry_id"),
            filename,
            layout=layout,
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Cards",
                "message": _format_cards_message(written),
            },
            blocking=False,
        )

    hass.services.async_register(DOMAIN, SERVICE_VIEW_CARDS, handle_view_cards, schema=SERVICE_VIEW_CARDS_SCHEMA)

    async def handle_purge_files(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_PURGE_FILES)
        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        if not entries:
            raise HomeAssistantError("No Humidity Intelligence config entry found")

        all_entries = hass.config_entries.async_entries(DOMAIN)
        multiple_installation = len(all_entries) > 1
        try:
            ui_filenames = list_owned_ui_filenames(
                entries,
                multiple_installation=multiple_installation,
                include_unqualified_defaults=not entry_id,
            )
            ui_plans = await hass.async_add_executor_job(
                plan_owned_ui_export_removal,
                hass.config.path(),
                ui_filenames,
            )
        except ReportExportError as err:
            raise HomeAssistantError(f"Cleanup plan rejected: {err}") from err
        files = [plan.relative_path for plan in ui_plans]

        report_plans = []
        if not entry_id:
            try:
                for planner, remover in (
                    (
                        plan_default_diagnostics_report_removal,
                        remove_default_diagnostics_report,
                    ),
                    (
                        plan_default_self_check_report_removal,
                        remove_default_self_check_report,
                    ),
                ):
                    plans = await hass.async_add_executor_job(
                        planner,
                        hass.config.path(),
                    )
                    report_plans.extend((plan, remover) for plan in plans)
            except ReportExportError as err:
                raise HomeAssistantError(f"Cleanup plan rejected: {err}") from err
        report_files = [plan.relative_path for plan, _remover in report_plans]

        message_lines = [f"/config/{f}" for f in files]
        message_lines.extend(
            f"Home Assistant config/{name}" for name in report_files
        )
        preview_message = (
            "The following generated artifacts will be removed:\n"
            + "\n".join(message_lines)
            if message_lines
            else "No generated files were found."
        )
        preview_message += (
            "\n\nHome Assistant dashboards are user-managed and are not removed by "
            "Humidity Intelligence."
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Cleanup Preview",
                "message": preview_message,
            },
            blocking=True,
        )

        failed_files = []
        for ui_plan in ui_plans:
            try:
                await hass.async_add_executor_job(
                    remove_owned_ui_export,
                    hass.config.path(),
                    ui_plan,
                )
            except ReportExportError as err:
                _LOGGER.warning(
                    "Unable to remove owned UI export %s: %s",
                    ui_plan.relative_path,
                    err,
                )
                failed_files.append(ui_plan.relative_path)
        failed_report_files = []
        for report_plan, remover in report_plans:
            try:
                await hass.async_add_executor_job(
                    remover,
                    hass.config.path(),
                    report_plan,
                )
            except ReportExportError as err:
                _LOGGER.warning(
                    "Unable to remove owned report export %s: %s",
                    report_plan.relative_path,
                    err,
                )
                failed_report_files.append(report_plan.relative_path)
        if failed_files or failed_report_files:
            failure_lines = [f"/config/{name}" for name in failed_files]
            failure_lines.extend(
                f"Home Assistant config/{name}"
                for name in failed_report_files
            )
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Humidity Intelligence Cleanup Incomplete",
                    "message": (
                        "Some generated artifacts could not be removed:\n"
                        + "\n".join(failure_lines)
                    ),
                },
                blocking=True,
            )
            details = []
            if failed_files:
                details.append("files: " + ", ".join(failed_files))
            if failed_report_files:
                details.append("reports: " + ", ".join(failed_report_files))
            raise HomeAssistantError("Purge incomplete: " + "; ".join(details))

    hass.services.async_register(DOMAIN, SERVICE_PURGE_FILES, handle_purge_files, schema=SERVICE_PURGE_FILES_SCHEMA)

    async def handle_pause_control(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_PAUSE_CONTROL)
        entry_id = call.data.get("entry_id")
        minutes = int(call.data.get("minutes", 60))
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        if not entries:
            raise HomeAssistantError("No Humidity Intelligence config entry found")

        for entry in entries:
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            timer = (data.get("hi_timers") or {}).get("air_control_pause")
            if timer is None:
                raise HomeAssistantError("Pause timer is not available yet")
            await timer.async_start(timedelta(minutes=minutes))
            engine = data.get("automation_engine")
            if engine:
                await engine.async_request_evaluate()

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_CONTROL,
        handle_pause_control,
        schema=SERVICE_PAUSE_CONTROL_SCHEMA,
    )

    async def handle_resume_control(call: ServiceCall) -> None:
        await _async_require_admin_user(hass, call, SERVICE_RESUME_CONTROL)
        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        if not entries:
            raise HomeAssistantError("No Humidity Intelligence config entry found")

        for entry in entries:
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            timer = (data.get("hi_timers") or {}).get("air_control_pause")
            if timer is None:
                raise HomeAssistantError("Pause timer is not available yet")
            await timer.async_cancel()
            engine = data.get("automation_engine")
            if engine:
                await engine.async_request_evaluate()

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_CONTROL,
        handle_resume_control,
        schema=SERVICE_RESUME_CONTROL_SCHEMA,
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services for the integration."""
    if hass.services.has_service(DOMAIN, SERVICE_FLASH_LIGHTS):
        hass.services.async_remove(DOMAIN, SERVICE_FLASH_LIGHTS)
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_UI):
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH_UI)
    if hass.services.has_service(DOMAIN, SERVICE_DUMP_DIAGNOSTICS):
        hass.services.async_remove(DOMAIN, SERVICE_DUMP_DIAGNOSTICS)
    if hass.services.has_service(DOMAIN, SERVICE_SELF_CHECK):
        hass.services.async_remove(DOMAIN, SERVICE_SELF_CHECK)
    if hass.services.has_service(DOMAIN, SERVICE_V205_RELEASE_CHECK):
        hass.services.async_remove(DOMAIN, SERVICE_V205_RELEASE_CHECK)
    if hass.services.has_service(DOMAIN, SERVICE_DUMP_CARDS):
        hass.services.async_remove(DOMAIN, SERVICE_DUMP_CARDS)
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_DASHBOARD):
        hass.services.async_remove(DOMAIN, SERVICE_CREATE_DASHBOARD)
    if hass.services.has_service(DOMAIN, SERVICE_VIEW_CARDS):
        hass.services.async_remove(DOMAIN, SERVICE_VIEW_CARDS)
    if hass.services.has_service(DOMAIN, SERVICE_PURGE_FILES):
        hass.services.async_remove(DOMAIN, SERVICE_PURGE_FILES)
    if hass.services.has_service(DOMAIN, SERVICE_PAUSE_CONTROL):
        hass.services.async_remove(DOMAIN, SERVICE_PAUSE_CONTROL)
    if hass.services.has_service(DOMAIN, SERVICE_RESUME_CONTROL):
        hass.services.async_remove(DOMAIN, SERVICE_RESUME_CONTROL)
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_LOCAL_BACKUP):
        hass.services.async_remove(DOMAIN, SERVICE_CREATE_LOCAL_BACKUP)
    if hass.services.has_service(DOMAIN, SERVICE_LIST_SAVED_VERSIONS):
        hass.services.async_remove(DOMAIN, SERVICE_LIST_SAVED_VERSIONS)

async def _async_read_manifest_version(hass: HomeAssistant) -> Optional[str]:
    def _read_version() -> Optional[str]:
        path = os.path.join(os.path.dirname(__file__), "manifest.json")
        with open(path, "r", encoding="utf-8") as manifest:
            data = json.load(manifest)
        version = data.get("version")
        return str(version) if version is not None else None

    try:
        return await hass.async_add_executor_job(_read_version)
    except Exception:
        _LOGGER.exception("Unable to read Humidity Intelligence manifest version")
        return None


def _to_jsonable(value):
    """Convert HA/runtime objects into JSON-serializable primitives."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "items"):
        try:
            return {str(k): _to_jsonable(v) for k, v in value.items()}
        except (AttributeError, TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    return str(value)


def _redact_sensitive_attributes(attributes: dict) -> dict:
    redacted = {}
    for key, value in attributes.items():
        key_text = str(key)
        key_norm = key_text.lower()
        if key_norm in _SENSITIVE_ATTR_EXACT or any(part in key_norm for part in _SENSITIVE_ATTR_PARTIAL):
            redacted[key_text] = "[REDACTED]"
        else:
            redacted[key_text] = _to_jsonable(value)
    return redacted


def _support_configuration_summary(config: dict, options: dict) -> dict:
    effective = dict(config or {}) if isinstance(config, dict) else {}
    if isinstance(options, dict):
        effective.update(options)
    telemetry = [item for item in effective.get("telemetry", []) or [] if isinstance(item, dict)]
    zones = {key: row for key, row in (effective.get("zones", {}) or {}).items() if isinstance(row, dict)}
    aq = {key: row for key, row in (effective.get("aq", {}) or {}).items() if isinstance(row, dict)}
    humidifiers = {
        key: row for key, row in (effective.get("humidifiers", {}) or {}).items() if isinstance(row, dict)
    }
    alerts = [item for item in effective.get("alerts", []) or [] if isinstance(item, dict)]
    return {
        "telemetry_count": len(telemetry),
        "telemetry_by_sensor_type": _count_config_rows(telemetry, "sensor_type"),
        "telemetry_by_level": _count_config_rows(telemetry, "level"),
        "zone_count": len(zones),
        "zone_output_count": sum(len(row.get("outputs") or []) for row in zones.values()),
        "aq_lane_count": len(aq),
        "aq_output_count": sum(len(row.get("outputs") or []) for row in aq.values()),
        "humidifier_lane_count": len(humidifiers),
        "humidifier_output_count": sum(len(row.get("outputs") or []) for row in humidifiers.values()),
        "presence_gate_entity_count": len((effective.get("presence_gate", {}) or {}).get("entities") or []),
        "alert_rule_count": len(alerts),
        "visual_alert_light_count": sum(len(row.get("lights") or []) for row in alerts),
        "visual_alert_power_entity_count": len([row for row in alerts if row.get("power_entity")]),
        "option_keys": sorted(str(key) for key in (options or {})),
    }


def _support_entity_map_summary(entity_map: dict) -> dict:
    return {
        "mapped_entity_count": len([value for value in (entity_map or {}).values() if value]),
    }


def _support_state_summary(hass: HomeAssistant, entity_ids) -> dict:
    counts = {"available": 0, "missing": 0, "unknown": 0, "unavailable": 0}
    total = 0
    for entity_id in entity_ids or []:
        if not entity_id:
            continue
        total += 1
        state = hass.states.get(str(entity_id))
        if state is None:
            counts["missing"] += 1
            continue
        state_text = str(getattr(state, "state", "unknown") or "").strip().lower()
        if not state_text:
            state_text = "unknown"
        if state_text in {"unknown", "unavailable"}:
            counts[state_text] += 1
        else:
            counts["available"] += 1
    return {"count": total, "by_status": counts}


def _support_safe_diagnostics_summary(summary: dict) -> dict:
    unavailable = summary.get("unavailable_or_unknown_entities") or []
    active_alerts = [item for item in summary.get("active_alert_resolution") or [] if isinstance(item, dict)]
    runtime_control = (
        summary.get("runtime_control")
        if isinstance(summary.get("runtime_control"), dict)
        else {}
    )
    return {
        "runtime_control": {
            "mode": runtime_control.get("mode"),
            "display": runtime_control.get("display"),
            "reason_available": bool(runtime_control.get("reason_available")),
        },
        "target_profile": summary.get("target_profile", {}),
        "temperature_comfort": summary.get("temperature_comfort", {}),
        "level_labels": summary.get("level_labels", {}),
        "zone_mapping_count": len(summary.get("zone_mappings") or {}),
        "zone_mapping_duplicates": summary.get("zone_mapping_duplicates", {}),
        "alert_mapping_count": len(summary.get("alert_mappings") or []),
        "visual_alert_count": len(summary.get("visual_alerts") or []),
        "active_alert_resolution": {
            "count": len(active_alerts),
            "trigger_types": sorted(
                {str(item.get("trigger_type")) for item in active_alerts if item.get("trigger_type")}
            ),
        },
        "humidity_drift_7d": summary.get("humidity_drift_7d", {}),
        "humidifier_reconciliation": _support_humidifier_reconciliation_summary(
            summary.get("humidifier_reconciliation") or {}
        ),
        "pm25_entity_id_normalization": _support_pm25_normalization_summary(
            summary.get("pm25_entity_id_normalization") or {}
        ),
        "frontend_dependency_resources": _support_frontend_dependency_summary(
            summary.get("frontend_dependency_resources") or {}
        ),
        "local_version_preservation": summary.get("local_version_preservation", {}),
        "unavailable_or_unknown_entities": _support_unavailable_summary(unavailable),
        "warnings": list(summary.get("warnings") or []),
    }


def _support_humidifier_reconciliation_summary(value: dict) -> dict:
    """Return a bounded, entity-id-free humidifier reconciliation summary."""
    if not isinstance(value, dict):
        value = {}
    status = value.get("status")
    if status not in {"reported", "not_available"}:
        status = (
            "reported"
            if any(key in value for key in ("schema", "summary", "outputs"))
            else "not_available"
        )
    raw_summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    summary_keys = (
        "requested_lanes",
        "degraded_lanes",
        "unknown_lanes",
        "matched_outputs",
        "retrying_outputs",
        "faulted_outputs",
        "degraded_outputs",
        "unknown_outputs",
        "isolated_outputs",
        "manual_hold_outputs",
        "ownership_conflicts",
    )
    summary = {
        key: _support_nonnegative_int(raw_summary.get(key, 0))
        for key in summary_keys
    }
    outputs = {}
    raw_outputs = value.get("outputs") if isinstance(value.get("outputs"), dict) else {}
    for slot, row in sorted(raw_outputs.items()):
        if not str(slot).startswith("output_") or not isinstance(row, dict):
            continue
        outputs[str(slot)] = {
            "domain": row.get("domain"),
            "owners": [
                str(owner)
                for owner in row.get("owners", [])
                if str(owner) in {"level1", "level2"}
            ],
            "configured_owners": [
                str(owner)
                for owner in row.get("configured_owners", [])
                if str(owner) in {"level1", "level2"}
            ],
            "desired": row.get("desired"),
            "observed": row.get("observed"),
            "platform_action": row.get("platform_action"),
            "reconciliation": row.get("reconciliation"),
            "dispatch_result": row.get("dispatch_result"),
            "last_command_intent": row.get("last_command_intent"),
            "last_dispatch_utc": row.get("last_dispatch_utc"),
            "attempts": _support_nonnegative_int(row.get("attempts", 0)),
            "maximum_attempts": _support_nonnegative_int(row.get("maximum_attempts", 0)),
            "mismatch_age_seconds": (
                _support_nonnegative_int(row["mismatch_age_seconds"])
                if isinstance(row.get("mismatch_age_seconds"), (int, float))
                else None
            ),
            "failure_category": row.get("failure_category"),
            "fault_latched": bool(row.get("fault_latched")),
            "ownership_conflict": row.get("ownership_conflict"),
        }
    return {
        "schema": 1,
        "status": status,
        "summary": summary,
        "outputs": outputs,
        "truth_boundary": (
            "Observed output state and optional platform action are Home Assistant evidence only; "
            "they do not prove physical moisture production."
        ),
    }


def _support_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _enabled_humidifier_lane_count(config: dict) -> int:
    """Return enabled humidifier lanes that can participate in runtime control."""
    if not isinstance(config, dict) or config.get("alert_only_mode"):
        return 0
    humidifiers = config.get("humidifiers")
    if not isinstance(humidifiers, dict):
        return 0
    return sum(
        isinstance(row, dict) and row.get("enabled", True)
        for row in humidifiers.values()
    )


def _support_pm25_normalization_summary(value: dict) -> dict:
    changed = value.get("changed") if isinstance(value.get("changed"), dict) else {}
    blocked = value.get("blocked") if isinstance(value.get("blocked"), list) else []
    return {
        "status": value.get("status", "not_run"),
        "changed_count": len(changed),
        "blocked_count": len(blocked),
        "blocked_reasons": sorted(
            {str(item.get("reason")) for item in blocked if isinstance(item, dict) and item.get("reason")}
        ),
    }


def _support_frontend_dependency_summary(value: dict) -> dict:
    if value.get("status") == "not_inspectable":
        return {
            "status": "not_inspectable",
            "reason": value.get("reason"),
        }
    rows = {}
    for key, row in (value or {}).items():
        if not isinstance(row, dict):
            continue
        rows[str(key)] = {
            "detected": bool(row.get("detected")),
            "provided_by": row.get("provided_by"),
        }
    return rows


def _support_unavailable_summary(value) -> dict:
    counts = {"missing": 0, "unknown": 0, "unavailable": 0}
    for item in value or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {"count": len(value or []), "by_status": counts}


def _count_config_rows(rows: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _build_diagnostics_summary(
    hass: HomeAssistant,
    config: dict,
    options: dict,
    entity_map: dict,
    runtime_data: dict,
    *,
    frontend_dependencies: Optional[dict] = None,
    local_version_status: Optional[dict] = None,
) -> dict:
    """Build a support-focused, truth-only diagnostics summary."""
    effective = dict(config or {})
    effective.update(dict(options or {}))
    telemetry = effective.get("telemetry", []) if isinstance(effective, dict) else []
    zones = effective.get("zones", {}) if isinstance(effective, dict) else {}
    alerts = effective.get("alerts", []) if isinstance(effective, dict) else []
    profile = resolve_target_profile(effective)
    comfort_profile = resolve_temperature_comfort_profile(effective)
    duplicates = detect_zone_mapping_duplicates(telemetry, zones if isinstance(zones, dict) else {})
    unavailable = _unavailable_configured_entities(hass, effective, entity_map)
    drift_dependency = humidity_drift_dependency_status(hass)
    drift_dependency_warning = humidity_drift_warning(drift_dependency)
    warnings = []
    duplicate_summary = summarize_zone_mapping_duplicate_count_warning(duplicates)
    if duplicate_summary:
        warnings.append(duplicate_summary)
    if unavailable:
        warnings.append(f"{len(unavailable)} configured/mapped entity references are missing, unknown, or unavailable.")
    if drift_dependency_warning:
        warnings.append(drift_dependency_warning)
    pm25_normalization = _pm25_normalization_status(runtime_data)
    if pm25_normalization.get("blocked"):
        warnings.append("PM25 aggregate entity ID normalization is blocked by an existing target entity.")
    if not telemetry:
        warnings.append("No telemetry sensors are configured.")
    if not zones and not effective.get("alert_only_mode"):
        warnings.append("No control zones are configured.")
    humidifier_reconciliation = _support_humidifier_reconciliation_summary(
        runtime_data.get("humidifier_reconciliation") or {}
    )
    humidifier_summary = humidifier_reconciliation.get("summary", {})
    humidifier_truth_missing = (
        _enabled_humidifier_lane_count(effective) > 0
        and humidifier_reconciliation.get("status") != "reported"
    )
    if humidifier_truth_missing:
        warnings.append(
            "Humidifier lanes are enabled, but runtime demand/output reconciliation truth is not available yet."
        )
    if humidifier_summary.get("faulted_outputs"):
        warnings.append("One or more humidifier outputs have a latched reconciliation fault.")
    if humidifier_summary.get("degraded_outputs") or humidifier_summary.get("unknown_outputs"):
        warnings.append("One or more humidifier outputs have degraded or unknown reconciliation truth.")
    if humidifier_summary.get("degraded_lanes") or humidifier_summary.get("unknown_lanes"):
        warnings.append("One or more humidifier lanes have degraded or unknown demand truth.")
    if humidifier_summary.get("ownership_conflicts"):
        warnings.append("One or more humidifier outputs have a conflicting configured output owner.")

    summary = {
        "runtime_control": runtime_control_summary(runtime_data),
        "target_profile": {
            "mode": effective.get("target_profile", "auto"),
            "active_profile": profile.key,
            "active_season": profile.label,
            "target_low": profile.low,
            "target_high": profile.high,
            "high_risk": profile.high_risk,
            "custom_target_low": effective.get("custom_target_low"),
            "custom_target_high": effective.get("custom_target_high"),
        },
        "temperature_comfort": {
            "mode": effective.get("temperature_comfort_mode", "auto"),
            "active_profile": comfort_profile.key,
            "active_label": comfort_profile.label,
            "target_low": comfort_profile.low,
            "target_high": comfort_profile.high,
            "warm_high": comfort_profile.warm_high,
            "watch_high": comfort_profile.warm_high,
            "custom_low": effective.get("temperature_comfort_custom_low"),
            "custom_high": effective.get("temperature_comfort_custom_high"),
        },
        "level_labels": resolve_level_label_details(effective),
        "zone_mappings": _zone_mapping_summary(zones),
        "zone_mapping_duplicates": summarize_zone_mapping_duplicate_counts(duplicates),
        "alert_mappings": _alert_mapping_summary(alerts),
        "active_alert_resolution": runtime_data.get("alert_telemetry", []),
        "visual_alerts": _visual_alert_summary(alerts),
        "humidity_drift_7d": drift_dependency,
        "humidifier_reconciliation": humidifier_reconciliation,
        "pm25_entity_id_normalization": pm25_normalization,
        "local_version_preservation": local_version_status or cached_local_version_status(hass),
        "unavailable_or_unknown_entities": unavailable,
        "warnings": warnings,
    }
    if frontend_dependencies is not None:
        summary["frontend_dependency_resources"] = frontend_dependencies

    return _to_jsonable(summary)


def _build_v205_release_check_entry_report(
    hass: HomeAssistant,
    entry: Any,
    runtime_data: dict,
    *,
    manifest_version: Optional[str],
    frontend_dependencies: Optional[dict] = None,
    local_version_status: Optional[dict] = None,
    require_local_hi_snapshot: bool = False,
    max_snapshot_age_minutes: int = 60,
    write_test_exports: bool = False,
    unscoped_written: Optional[List[str]] = None,
    scoped_written: Optional[List[str]] = None,
) -> dict:
    """Build a truth-only release-validation report for one entry."""
    cards = runtime_data.get("cards", {}) or {}
    entity_map = runtime_data.get("entity_map", {}) or {}
    effective = _effective_entry_config(entry)
    checks: List[Dict[str, Any]] = []
    manifest_status, manifest_message = _release_check_manifest_status(manifest_version)

    _add_check(
        checks,
        "manifest_version",
        manifest_status,
        manifest_message,
    )

    runtime_control = runtime_control_summary(runtime_data)
    runtime_mode_reported = runtime_control.get("mode") is not None
    _add_check(
        checks,
        "runtime_control_truth",
        "pass" if runtime_mode_reported else "skip",
        (
            "Runtime control mode and reason availability are reported from backend truth."
            if runtime_mode_reported
            else "Runtime control mode is not available yet."
        ),
        runtime_control,
    )

    show_output_details = bool(
        effective.get(CONF_SHOW_OUTPUT_ENTITY_DETAILS, DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS)
    )
    _add_check(
        checks,
        "show_output_entity_details_option",
        "pass",
        "show_output_entity_details resolved as a generated-card visibility option.",
        {
            "configured": CONF_SHOW_OUTPUT_ENTITY_DETAILS in effective,
            "resolved_value": show_output_details,
        },
    )

    required_layouts = {"v2_mobile", "v2_tablet", "v1_mobile", "view_cards_button"}
    cached_layouts = set(cards)
    missing_layouts = sorted(required_layouts - cached_layouts)
    _add_check(
        checks,
        "cached_layouts",
        "pass" if not missing_layouts else "fail",
        "All expected generated card layouts are cached." if not missing_layouts else "Generated card layout cache is incomplete.",
        {"cached_layouts": sorted(cached_layouts), "missing_layouts": missing_layouts},
    )

    visibility_failures = _output_details_visibility_failures(cards, show_output_details)
    _add_check(
        checks,
        "output_details_visibility",
        "pass" if not visibility_failures else "fail",
        "Generated V2 output details visibility matches show_output_entity_details.",
        {"show_output_entity_details": show_output_details, "failures": visibility_failures},
    )

    if "unresolved_placeholders_by_card" in runtime_data:
        unresolved = runtime_data.get("unresolved_placeholders_by_card") or {}
    else:
        unresolved = runtime_data.get("unresolved_placeholders") or []
    _add_check(
        checks,
        "unresolved_placeholders",
        "pass" if not unresolved else "fail",
        "No unresolved placeholders are recorded for generated cards." if not unresolved else "Generated cards have unresolved placeholders.",
        {"unresolved": unresolved},
    )

    card_entity_availability = _generated_card_entity_availability(hass, cards)
    card_entity_status = card_entity_availability["status"]
    _add_check(
        checks,
        "generated_card_entity_availability",
        card_entity_status,
        "All generated card entity references resolve in Home Assistant."
        if card_entity_status == "pass"
        else "Generated cards contain missing, unknown, or unavailable entity references.",
        card_entity_availability,
    )

    card_sanity_failures = _generated_card_text_sanity_failures(cards)
    _add_check(
        checks,
        "generated_cards_text_sanity",
        "pass" if not card_sanity_failures else "fail",
        "Generated card YAML text has no obvious empty containers, invalid conditionals, or leftover HI markers.",
        {"failures": card_sanity_failures},
    )

    if write_test_exports:
        unscoped_layouts = _layouts_from_written_paths(unscoped_written or [])
        scoped_layouts = _layouts_from_written_paths(scoped_written or [])
        _add_check(
            checks,
            "dump_cards_unscoped_export_all",
            "pass" if required_layouts <= unscoped_layouts else "fail",
            "Unscoped dump_cards exported every cached/generated layout.",
            {"written": list(unscoped_written or []), "layouts": sorted(unscoped_layouts)},
        )
        _add_check(
            checks,
            "dump_cards_scoped_export_single_layout",
            "pass" if scoped_layouts == {"v2_tablet"} else "fail",
            "Scoped dump_cards exported only the selected v2_tablet layout.",
            {"written": list(scoped_written or []), "layouts": sorted(scoped_layouts)},
        )
    else:
        _add_check(
            checks,
            "dump_cards_export_contract",
            "skip",
            "Set write_test_exports: true to write test card exports and verify scoped/unscoped dump_cards behavior in Home Assistant.",
        )

    if frontend_dependencies is None:
        frontend_dependencies = frontend_dependency_not_inspectable(
            "Frontend dependency status was not supplied by the service handler."
        )
    _add_check(
        checks,
        "frontend_dependencies_reported",
        "pass",
        "Optional frontend dependency resource status was reported without blocking backend validation.",
        frontend_dependencies,
    )

    drift_dependency = humidity_drift_dependency_status(hass)
    _add_check(
        checks,
        "house_humidity_drift_7d_dependency",
        "pass" if drift_dependency.get("available") else "warn",
        "House humidity drift 7d statistics dependency is available."
        if drift_dependency.get("available")
        else "House humidity drift 7d is unavailable until its statistics dependency reports a numeric value.",
        drift_dependency,
    )

    pm25_normalization = _pm25_normalization_status(runtime_data)
    pm25_blocked = bool(pm25_normalization.get("blocked"))
    _add_check(
        checks,
        "pm25_entity_id_normalization",
        "warn" if pm25_blocked else "pass",
        "PM25 aggregate entity ID normalization has no blocked conflicts."
        if not pm25_blocked
        else "PM25 aggregate entity ID normalization is blocked by an existing target entity.",
        pm25_normalization,
    )

    humidifier_reconciliation = _support_humidifier_reconciliation_summary(
        runtime_data.get("humidifier_reconciliation") or {}
    )
    humidifier_summary = humidifier_reconciliation.get("summary", {})
    enabled_humidifier_lanes = _enabled_humidifier_lane_count(effective)
    humidifier_truth_missing = (
        enabled_humidifier_lanes > 0
        and humidifier_reconciliation.get("status") != "reported"
    )
    humidifier_issue = humidifier_truth_missing or any(
        humidifier_summary.get(key)
        for key in (
            "faulted_outputs",
            "degraded_outputs",
            "unknown_outputs",
            "degraded_lanes",
            "unknown_lanes",
            "ownership_conflicts",
        )
    )
    if humidifier_truth_missing:
        humidifier_message = (
            "Humidifier lanes are enabled, but runtime demand/output reconciliation "
            "truth is not available yet."
        )
    elif humidifier_issue:
        humidifier_message = (
            "Humidifier demand/output reconciliation reports a fault or ownership "
            "conflict. Observed state remains Home Assistant evidence only."
        )
    elif humidifier_reconciliation.get("status") == "reported":
        humidifier_message = (
            "Humidifier demand/output reconciliation is reported; observed state "
            "does not prove physical moisture production."
        )
    else:
        humidifier_message = (
            "No enabled humidifier lane requires a runtime reconciliation report."
        )
    _add_check(
        checks,
        "humidifier_reconciliation_truth",
        "warn" if humidifier_issue else "pass",
        humidifier_message,
        humidifier_reconciliation,
    )

    local_snapshot_status, local_snapshot_message, local_snapshot_details = _local_snapshot_release_check(
        local_version_status or cached_local_version_status(hass),
        require_local_hi_snapshot=require_local_hi_snapshot,
        max_snapshot_age_minutes=max_snapshot_age_minutes,
    )
    _add_check(
        checks,
        "local_hi_snapshot",
        local_snapshot_status,
        local_snapshot_message,
        local_snapshot_details,
    )

    unavailable = _unavailable_configured_entities(hass, effective, entity_map)
    _add_check(
        checks,
        "configured_entity_availability",
        "pass" if not unavailable else "warn",
        "All configured/mapped entity references are currently available." if not unavailable else "Some configured/mapped entity references are missing, unknown, or unavailable.",
        {"unavailable_or_unknown_entities": unavailable},
    )

    return {
        "status": _combined_check_status([{"status": check["status"]} for check in checks]),
        "entry_id": getattr(entry, "entry_id", None),
        "checks": checks,
    }


def _release_check_manifest_status(manifest_version: Optional[str]) -> Tuple[str, str]:
    version = manifest_version or "unknown"
    if manifest_version and _RELEASE_CHECK_MANIFEST_VERSION_RE.fullmatch(manifest_version):
        return (
            "pass",
            f"Manifest version is {version}; release-check contract is valid for the v2.0.5-v2.0.12 line.",
        )
    return (
        "fail",
        f"Manifest version is {version}; expected v2.0.5 or a v2.0.6-v2.0.12 beta/rc/stable version.",
    )


def _local_snapshot_release_check(
    local_version_status: dict,
    *,
    require_local_hi_snapshot: bool,
    max_snapshot_age_minutes: int,
) -> Tuple[str, str, dict]:
    latest_id = local_version_status.get("latest_snapshot_id")
    details = {
        "required": bool(require_local_hi_snapshot),
        "max_snapshot_age_minutes": int(max_snapshot_age_minutes),
        "status": _to_jsonable(local_version_status),
    }
    if not latest_id:
        status = "fail" if require_local_hi_snapshot else "info"
        message = (
            "No local HI-only snapshot is available and this release check requires one."
            if require_local_hi_snapshot
            else "No local HI-only snapshot is available. This optional advanced maintenance feature is not required for normal release validation."
        )
        return status, message, details

    created_at = _parse_utc(local_version_status.get("latest_snapshot_created_at_utc"))
    if require_local_hi_snapshot and created_at is not None:
        age_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
        details["latest_snapshot_age_minutes"] = round(age_minutes, 1)
        if age_minutes > max_snapshot_age_minutes:
            return (
                "fail",
                "Latest local HI-only snapshot is older than the required maximum age.",
                details,
            )

    return (
        "pass",
        "Local HI-only snapshot status was reported. Creating or listing snapshots does not change running code.",
        details,
    )


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _effective_entry_config(entry: Any) -> dict:
    effective = dict(getattr(entry, "data", None) or {})
    effective.update(dict(getattr(entry, "options", None) or {}))
    return effective


def _add_check(
    checks: List[Dict[str, Any]],
    check_id: str,
    status: str,
    message: str,
    details: Optional[Any] = None,
) -> None:
    row: Dict[str, Any] = {"id": check_id, "status": status, "message": message}
    if details is not None:
        row["details"] = _to_jsonable(details)
    checks.append(row)


def _combined_check_status(items: List[dict]) -> str:
    statuses = [item.get("status") for item in items]
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    return "pass"


def _pm25_normalization_status(runtime_data: dict) -> dict:
    details = runtime_data.get("pm25_entity_id_normalization")
    if not isinstance(details, dict):
        return {"status": "not_run", "changed": {}, "blocked": []}
    changed = details.get("changed") if isinstance(details.get("changed"), dict) else {}
    blocked = details.get("blocked") if isinstance(details.get("blocked"), list) else []
    if blocked:
        status = "blocked"
    elif changed:
        status = "changed"
    else:
        status = "ok"
    return {
        "status": status,
        "changed": changed,
        "blocked": blocked,
    }


def _output_details_visibility_failures(cards: dict, show_output_details: bool) -> List[str]:
    failures: List[str] = []
    for layout in ("v2_mobile", "v2_tablet"):
        card = str(cards.get(layout, ""))
        has_output_panel = "name: Outputs" in card or "entity: input_boolean.air_control_output_expanded" in card or "entity: switch.hi_input_air_control_output_expanded" in card
        if show_output_details and not has_output_panel:
            failures.append(f"{layout}: output details panel expected but not found")
        if not show_output_details and has_output_panel:
            failures.append(f"{layout}: output details panel present while disabled")
    return failures


def _generated_card_text_sanity_failures(cards: dict) -> List[str]:
    failures: List[str] = []
    for layout, card in (cards or {}).items():
        text = str(card)
        if "cards: []" in text:
            failures.append(f"{layout}: empty cards list")
        if "# hi:output-details" in text:
            failures.append(f"{layout}: output-details marker was not stripped")
        if re.search(r"type:\s*conditional\s*\n\s*(?:conditions:\s*\[\]|card:\s*(?:\n|$))", text):
            failures.append(f"{layout}: invalid conditional block")
    return failures


def _generated_card_entity_availability(hass: HomeAssistant, cards: dict) -> dict:
    missing: List[dict] = []
    unavailable: List[dict] = []
    seen: set[tuple[str, str]] = set()

    for layout, card in sorted((cards or {}).items()):
        for entity_id in _extract_generated_card_entity_ids(str(card)):
            key = (str(layout), entity_id)
            if key in seen:
                continue
            seen.add(key)
            state = hass.states.get(entity_id)
            if state is None:
                missing.append({"layout": str(layout), "entity_id": entity_id})
                continue
            state_text = str(state.state).lower()
            if state_text in {"unknown", "unavailable"}:
                unavailable.append(
                    {
                        "layout": str(layout),
                        "entity_id": entity_id,
                        "status": state_text,
                    }
                )

    status = "pass"
    if missing:
        status = "fail"
    elif unavailable:
        status = "warn"

    return {
        "status": status,
        "checked_entity_count": len(seen),
        "missing_entities": missing,
        "unknown_or_unavailable_entities": unavailable,
    }


def _extract_generated_card_entity_ids(card: str) -> List[str]:
    entity_ids: List[str] = []
    seen: set[str] = set()
    text = card or ""
    for match in _GENERATED_CARD_ENTITY_RE.finditer(text):
        entity_id = match.group(0)
        if not _is_generated_card_entity_reference(text, match):
            continue
        if entity_id in seen:
            continue
        seen.add(entity_id)
        entity_ids.append(entity_id)
    return entity_ids


def _is_generated_card_entity_reference(card: str, match: re.Match[str]) -> bool:
    """Return true when a generated-card match is an HA entity reference.

    Card JavaScript also contains object properties such as ``zone.enabled``,
    service names such as ``switch.toggle``, and string prefixes such as
    ``sensor.hi_``. Those are not Home Assistant entity references and should
    not fail release validation.
    """
    entity_id = match.group(0)
    start, end = match.span()
    if entity_id.endswith("_"):
        return False

    before = card[max(0, start - 80) : start]
    after = card[end : min(len(card), end + 8)]
    before_stripped = before.rstrip()

    if re.search(r"(?:^|[\s{,])entity(?:_id)?:\s*$", before):
        return True

    if before_stripped.endswith(("states['", 'states["')):
        return True

    quote = card[start - 1] if start > 0 else ""
    if quote in {"'", '"'} and after.startswith(quote):
        if re.search(r"(?:^|[\s;])(?:const|let|var)?\s*service\s*=\s*['\"]$", before_stripped):
            return False
        predicate_prefixes = (
            ".startsWith(" + quote,
            ".endsWith(" + quote,
            ".includes(" + quote,
        )
        if before_stripped.endswith(predicate_prefixes):
            return False
        return True

    return False


def _layouts_from_written_paths(paths: List[str]) -> set[str]:
    layouts = set()
    for path in paths:
        text = str(path)
        for layout in _ALLOWED_LAYOUTS:
            if text.endswith(f"_{layout}.yaml") or f"_{layout}." in text:
                layouts.add(layout)
    return layouts


_async_frontend_dependency_status = async_frontend_dependency_status
_frontend_dependency_not_inspectable = frontend_dependency_not_inspectable


def _zone_mapping_summary(zones: dict) -> dict:
    summary = {}
    if not isinstance(zones, dict):
        return summary
    for key, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        summary[str(key)] = {
            "enabled": bool(zone.get("enabled")),
            "level": zone.get("level"),
            "rooms": list(zone.get("rooms") or []),
            "outputs": list(zone.get("outputs") or []),
            "output_level": zone.get("output_level"),
            "boost_output_level": zone.get("boost_output_level"),
            "triggers": list(zone.get("triggers") or []),
            "thresholds": dict(zone.get("thresholds") or {}),
        }
    return summary


def _alert_mapping_summary(alerts: list) -> list:
    rows = []
    for idx, alert in enumerate(alerts or [], start=1):
        if not isinstance(alert, dict):
            continue
        rows.append({
            "index": idx,
            "enabled": bool(alert.get("enabled", True)),
            "trigger_type": alert.get("trigger_type"),
            "room": alert.get("room"),
            "threshold": alert.get("threshold"),
            "visual_lights": list(alert.get("lights") or []),
            "power_entity": alert.get("power_entity"),
            "flash_mode": alert.get("flash_mode", "red"),
            "duration": alert.get("duration", 10),
        })
    return rows


def _visual_alert_summary(alerts: list) -> list:
    return [
        {
            "index": row["index"],
            "trigger_type": row["trigger_type"],
            "room": row["room"],
            "lights": row["visual_lights"],
            "power_entity": row["power_entity"],
            "flash_mode": row["flash_mode"],
            "flash_count": 10,
            "repeat_minutes": 30,
            "restore_state": True,
        }
        for row in _alert_mapping_summary(alerts)
        if row.get("visual_lights")
    ]


def _unavailable_configured_entities(hass: HomeAssistant, config: dict, entity_map: dict) -> list:
    entity_ids = set()
    for item in config.get("telemetry", []) or []:
        if isinstance(item, dict) and item.get("entity_id"):
            entity_ids.add(item["entity_id"])
    for entity_id in config.get("presence_gate", {}).get("entities", []) or []:
        entity_ids.add(entity_id)
    for section_name in ("zones", "aq", "humidifiers"):
        section = config.get(section_name, {})
        if isinstance(section, dict):
            for row in section.values():
                if not isinstance(row, dict):
                    continue
                for entity_id in row.get("outputs", []) or []:
                    entity_ids.add(entity_id)
    for alert in config.get("alerts", []) or []:
        if not isinstance(alert, dict):
            continue
        for entity_id in alert.get("lights", []) or []:
            entity_ids.add(entity_id)
        if alert.get("power_entity"):
            entity_ids.add(alert["power_entity"])
    for entity_id in (entity_map or {}).values():
        if entity_id:
            entity_ids.add(entity_id)

    missing = []
    for entity_id in sorted(entity_ids):
        state = hass.states.get(entity_id)
        if state is None:
            missing.append({"entity_id": entity_id, "status": "missing"})
            continue
        if str(state.state).lower() in {"unknown", "unavailable"}:
            missing.append({"entity_id": entity_id, "status": str(state.state).lower()})
    return missing


async def async_export_cards_to_owned_ui(
    hass: HomeAssistant,
    entry_id: str | None,
    filename: str | None,
    layout: str | None = None,
    *,
    multiple_installation: bool | None = None,
) -> List[str]:
    """Write generated cards through the trusted confined UI export path."""
    all_entries = hass.config_entries.async_entries(DOMAIN)
    entries = []
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry:
            entries = [entry]
    else:
        entries = all_entries

    written: List[str] = []
    if multiple_installation is None:
        multiple_installation = len(all_entries) > 1
    for entry in entries:
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        cards = data.get("cards", {}) or {}
        for name, card_yaml in cards.items():
            if layout and name != layout:
                continue
            target = build_generated_card_filename(
                filename,
                name,
                entry.entry_id,
                multiple_installation,
            )
            try:
                relative_path = await hass.async_add_executor_job(
                    write_owned_ui_export,
                    hass.config.path(),
                    target,
                    card_yaml,
                )
            except Exception as err:
                completed = (
                    " No files were written."
                    if not written
                    else " Files already written: " + ", ".join(written)
                )
                raise HomeAssistantError(
                    f"Generated UI export incomplete for {target}: {err}.{completed}"
                ) from err
            written.append(f"/config/{relative_path}")
    return written


def _format_cards_message(paths: List[str]) -> str:
    if not paths:
        return "No cards were generated."
    if len(paths) == 1:
        return f"Card written to {paths[0]}. Open in File Editor to copy YAML."
    lines = "\n".join(paths)
    return f"Cards written:\n{lines}\n\nOpen any file in File Editor to copy YAML."


async def _notify_local_version_result(hass: HomeAssistant, title: str, message: str) -> None:
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": title,
            "message": message,
        },
        blocking=False,
    )


def _format_local_backup_created_message(result: dict) -> str:
    deleted = result.get("deleted_snapshots") or []
    return (
        "Created local HI-only snapshot.\n\n"
        f"Snapshot ID: `{result.get('snapshot_id')}`\n"
        f"Manifest version: `{result.get('manifest_version')}`\n"
        f"Files: `{result.get('file_count')}`\n"
        f"Bytes: `{result.get('total_bytes')}`\n"
        f"Retained snapshots: `{result.get('retained_count')}`\n"
        f"Deleted by retention: `{len(deleted)}`\n\n"
        "This is not a Home Assistant backup and does not change running code until Home Assistant is restarted."
    )


def _format_local_versions_list_message(result: dict) -> str:
    latest = result.get("latest_snapshot") or {}
    invalid = result.get("invalid_snapshots") or []
    latest_id = latest.get("snapshot_id") or "none"
    latest_version = latest.get("manifest_version") or "unknown"
    return (
        "Listed local HI-only snapshots.\n\n"
        f"Valid snapshots: `{len(result.get('valid_snapshots') or [])}`\n"
        f"Invalid snapshots: `{len(invalid)}`\n"
        f"Latest snapshot: `{latest_id}`\n"
        f"Latest version: `{latest_version}`\n"
        f"Total bytes: `{result.get('total_size', 0)}`\n\n"
        "This is not a Home Assistant backup and does not change running code."
    )


def _supports_color(state) -> bool:
    if state is None:
        return False
    modes = state.attributes.get("supported_color_modes") or []
    return "rgb" in modes or "hs" in modes


def _dedupe_lights(lights: List[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for light in lights:
        if light in seen:
            continue
        ordered.append(light)
        seen.add(light)
    return ordered


def _light_flash_locks(hass: HomeAssistant, lights: List[str]) -> List[asyncio.Lock]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    locks: Dict[str, asyncio.Lock] = domain_data.setdefault(_FLASH_LIGHT_LOCKS_KEY, {})
    return [locks.setdefault(light, asyncio.Lock()) for light in sorted(set(lights))]


def _capture_light_states(hass: HomeAssistant, lights: List[str]) -> Dict[str, Dict[str, Any]]:
    captured: Dict[str, Dict[str, Any]] = {}
    for light in lights:
        state = hass.states.get(light)
        captured[light] = {
            "state": state.state if state is not None else None,
            "attributes": dict(state.attributes) if state is not None else {},
        }
    return captured


async def _flash_lights(
    hass: HomeAssistant,
    lights: List[str],
    color: Tuple[int, int, int],
    duration: int,
    flash_count: Optional[int],
    supports_color: dict,
) -> None:
    interval = 0.5
    if flash_count is None:
        flash_count = max(1, int(duration / interval))

    for _ in range(flash_count):
        for light in lights:
            data = {"entity_id": light, "brightness": 255}
            if supports_color.get(light):
                data["rgb_color"] = color
            try:
                await hass.services.async_call("light", "turn_on", data, blocking=True)
            except Exception:
                _LOGGER.exception("Failed to turn on flashing light %s", light)
        await asyncio.sleep(interval)
        for light in lights:
            try:
                await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
            except Exception:
                _LOGGER.exception("Failed to turn off flashing light %s", light)
        await asyncio.sleep(interval)


async def _restore_lights(hass: HomeAssistant, states: Dict[str, Dict[str, Any]]) -> None:
    for entity_id, snapshot in states.items():
        initial_state = snapshot.get("state")
        if initial_state is None:
            continue
        if initial_state == "on":
            data = {"entity_id": entity_id}
            attrs = snapshot.get("attributes") or {}
            if "brightness" in attrs:
                data["brightness"] = attrs.get("brightness")
            if "rgb_color" in attrs:
                data["rgb_color"] = attrs.get("rgb_color")
            if "hs_color" in attrs:
                data["hs_color"] = attrs.get("hs_color")
            if "color_temp" in attrs:
                data["color_temp"] = attrs.get("color_temp")
            if "effect" in attrs:
                data["effect"] = attrs.get("effect")
            try:
                await hass.services.async_call("light", "turn_on", data, blocking=True)
            except Exception:
                _LOGGER.exception("Failed to restore light state for %s", entity_id)
        else:
            try:
                await hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=True)
            except Exception:
                _LOGGER.exception("Failed to restore light off state for %s", entity_id)
