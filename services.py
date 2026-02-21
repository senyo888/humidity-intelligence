"""Service handlers for Humidity Intelligence."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import timedelta
from typing import List, Optional, Tuple

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .helpers.cleanup import list_all_generated_files, list_generated_files, remove_files, remove_dashboard

_LOGGER = logging.getLogger(__name__)

SERVICE_FLASH_LIGHTS = "flash_lights"
SERVICE_REFRESH_UI = "refresh_ui"
SERVICE_DUMP_DIAGNOSTICS = "dump_diagnostics"
SERVICE_SELF_CHECK = "self_check"
SERVICE_DUMP_CARDS = "dump_cards"
SERVICE_CREATE_DASHBOARD = "create_dashboard"
SERVICE_VIEW_CARDS = "view_cards"
SERVICE_PURGE_FILES = "purge_files"
SERVICE_PAUSE_CONTROL = "pause_control"
SERVICE_RESUME_CONTROL = "resume_control"

SERVICE_FLASH_SCHEMA = vol.Schema({
    vol.Optional("power_entity"): cv.entity_id,
    vol.Required("lights"): cv.entity_ids,
    vol.Optional("color", default=(255, 0, 0)): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional("duration", default=10): vol.Coerce(int),
    vol.Optional("flash_count", default=None): vol.Any(None, vol.Coerce(int)),
})
SERVICE_REFRESH_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_DUMP_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename", default="humidity_intelligence_diagnostics.json"): cv.string,
})
SERVICE_SELF_CHECK_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})
SERVICE_DUMP_CARDS_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename"): cv.string,
    vol.Optional("layout"): cv.string,
})
SERVICE_CREATE_DASHBOARD_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("layout", default="v2_mobile"): cv.string,
    vol.Optional("title", default="Humidity Intelligence"): cv.string,
    vol.Optional("url_path", default="humidity-intelligence"): cv.string,
})
SERVICE_VIEW_CARDS_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
    vol.Optional("filename"): cv.string,
    vol.Optional("layout"): cv.string,
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


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def handle_flash(call: ServiceCall) -> None:
        power_entity = call.data.get("power_entity")
        lights = call.data.get("lights") or []
        color_list = call.data.get("color") or [255, 0, 0]
        duration = max(1, int(call.data.get("duration", 10)))
        flash_count = call.data.get("flash_count")
        color = tuple(color_list[:3]) if len(color_list) >= 3 else (255, 0, 0)

        if not lights:
            _LOGGER.warning("No lights provided to flash")
            return

        if power_entity:
            domain = power_entity.split(".")[0]
            if hass.services.has_service(domain, "turn_on"):
                try:
                    await hass.services.async_call(domain, "turn_on", {"entity_id": power_entity}, blocking=True)
                    await asyncio.sleep(0.5)
                except Exception:
                    _LOGGER.exception("Failed to turn on alert power entity %s", power_entity)

        states = {light: hass.states.get(light) for light in lights}
        supports_color = {light: _supports_color(state) for light, state in states.items()}

        await _flash_lights(hass, lights, color, duration, flash_count, supports_color)
        await _restore_lights(hass, states)

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

            payload = {}
            for entry in entries:
                data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
                entity_map = data.get("entity_map", {})
                state_dump = {}
                for ent in entity_map.values():
                    state = hass.states.get(ent)
                    if state is None:
                        continue
                    state_dump[ent] = {
                        "state": state.state,
                        "attributes": _to_jsonable(dict(state.attributes)),
                    }
                payload[entry.entry_id] = {
                    "config": _to_jsonable(data.get("config", {})),
                    "options": _to_jsonable(data.get("options", {})),
                    "entity_map": _to_jsonable(entity_map),
                    "cards": list((data.get("cards") or {}).keys()),
                    "states": state_dump,
                }

            path = hass.config.path(filename)
            await hass.async_add_executor_job(_write_json, path, payload)
        except Exception as err:
            _LOGGER.exception("Failed to write diagnostics JSON")
            raise HomeAssistantError(f"Failed to write diagnostics JSON: {err}") from err

    hass.services.async_register(DOMAIN, SERVICE_DUMP_DIAGNOSTICS, handle_dump, schema=SERVICE_DUMP_SCHEMA)

    async def handle_self_check(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        report = {}
        for entry in entries:
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            mapping = data.get("entity_map", {})
            missing_entities = []
            for ent in mapping.values():
                if hass.states.get(ent) is None:
                    missing_entities.append(ent)
            # basic dependency checks
            dependencies_ok = {}
            resources = hass.data.get("lovelace_resources") or {}
            for dep in ["card-mod", "button-card", "mod-card", "apexcharts-card"]:
                dependencies_ok[dep] = any(dep in str(v) for v in resources.values())

            report[entry.entry_id] = {
                "missing_entities": missing_entities,
                "dependency_resources": dependencies_ok,
                "telemetry_count": len(entry.data.get("telemetry", [])),
                "unresolved_placeholders": data.get("unresolved_placeholders", []),
                "unresolved_placeholders_by_card": data.get("unresolved_placeholders_by_card", {}),
            }

        path = hass.config.path("humidity_intelligence_self_check.json")
        await hass.async_add_executor_job(_write_json, path, report)

    hass.services.async_register(DOMAIN, SERVICE_SELF_CHECK, handle_self_check, schema=SERVICE_SELF_CHECK_SCHEMA)

    async def handle_dump_cards(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        filename = call.data.get("filename")
        layout = call.data.get("layout")
        await _dump_cards_to_file(hass, entry_id, filename, layout=layout)

    hass.services.async_register(DOMAIN, SERVICE_DUMP_CARDS, handle_dump_cards, schema=SERVICE_DUMP_CARDS_SCHEMA)

    async def handle_create_dashboard(call: ServiceCall) -> None:
        from .ui.register import async_build_entity_mapping, async_register_cards
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard

        entry_id = call.data.get("entry_id")
        layout = call.data.get("layout", "v2_mobile")
        title = call.data.get("title", "Humidity Intelligence")
        url_path = call.data.get("url_path", "humidity-intelligence")

        entry = None
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            entries = hass.config_entries.async_entries(DOMAIN)
            entry = entries[0] if entries else None
        if entry is None:
            return

        mapping = await async_build_entity_mapping(hass, entry.entry_id)
        cards = await async_register_cards(hass, entry.entry_id, mapping=mapping)
        yaml_str = cards.get(layout)
        if not yaml_str:
            return

        filename = f"dashboards/{url_path}.yaml"
        path = hass.config.path(filename)
        await hass.async_add_executor_job(_write_text, path, yaml_str)

        # Best-effort dashboard creation; if HA API changes, this will no-op.
        try:
            await lovelace_dashboard.async_create_dashboard(
                hass,
                dashboard_id=url_path,
                title=title,
                mode="yaml",
                filename=filename,
                icon="mdi:water-percent",
                show_in_sidebar=True,
                require_admin=False,
            )
        except Exception:
            _LOGGER.exception("Unable to auto-create dashboard. YAML written to %s", filename)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_DASHBOARD,
        handle_create_dashboard,
        schema=SERVICE_CREATE_DASHBOARD_SCHEMA,
    )

    async def handle_view_cards(call: ServiceCall) -> None:
        filename = call.data.get("filename")
        layout = call.data.get("layout")
        written = await _dump_cards_to_file(hass, call.data.get("entry_id"), filename, layout=layout)
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
        entry_id = call.data.get("entry_id")
        entries = []
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                entries = [entry]
        else:
            entries = hass.config_entries.async_entries(DOMAIN)

        if not entries:
            return

        files = list_all_generated_files(entries)
        dashboards = [e.data.get("ui_dashboard_id") for e in entries if e.data.get("ui_dashboard_id")]
        message_lines = [f"/config/{f}" for f in files]
        for dash in dashboards:
            message_lines.append(f"Dashboard: {dash}")
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Humidity Intelligence Cleanup",
                "message": "Purging generated files:\n" + "\n".join(message_lines),
            },
            blocking=False,
        )
        await hass.async_add_executor_job(remove_files, hass, files)
        for entry in entries:
            await remove_dashboard(hass, entry.data.get("ui_dashboard_id"))

    hass.services.async_register(DOMAIN, SERVICE_PURGE_FILES, handle_purge_files, schema=SERVICE_PURGE_FILES_SCHEMA)

    async def handle_pause_control(call: ServiceCall) -> None:
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


def _write_json(path: str, payload: dict) -> None:
    import json

    tmp_dir = os.path.dirname(path) or "."
    os.makedirs(tmp_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".hi_diag_", suffix=".json", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _write_text(path: str, payload: str) -> None:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)


def _to_jsonable(value):
    """Convert HA/runtime objects into JSON-serializable primitives."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "items"):
        try:
            return {str(k): _to_jsonable(v) for k, v in value.items()}
        except Exception:
            pass
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


async def _dump_cards_to_file(
    hass: HomeAssistant,
    entry_id: str | None,
    filename: str | None,
    layout: str | None = None,
) -> List[str]:
    entries = []
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry:
            entries = [entry]
    else:
        entries = hass.config_entries.async_entries(DOMAIN)

    written: List[str] = []
    for entry in entries:
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        cards = data.get("cards", {}) or {}
        for name, card_yaml in cards.items():
            if layout and name != layout:
                continue
            target = _build_cards_filename(filename, name, entry.entry_id, len(entries) > 1)
            path = hass.config.path(target)
            await hass.async_add_executor_job(_write_text, path, card_yaml)
            written.append(f"/config/{target}")
    return written


def _build_cards_filename(
    base: str | None,
    layout: str,
    entry_id: str,
    multiple: bool,
) -> str:
    prefix = base or "humidity_intelligence_cards"
    if prefix.endswith(".yaml"):
        prefix = prefix[:-5]
    if prefix.endswith(".yml"):
        prefix = prefix[:-4]
    if multiple:
        return f"{prefix}_{entry_id}_{layout}.yaml"
    return f"{prefix}_{layout}.yaml"


def _format_cards_message(paths: List[str]) -> str:
    if not paths:
        return "No cards were generated."
    if len(paths) == 1:
        return f"Card written to {paths[0]}. Open in File Editor to copy YAML."
    lines = "\n".join(paths)
    return f"Cards written:\n{lines}\n\nOpen any file in File Editor to copy YAML."


def _supports_color(state) -> bool:
    if state is None:
        return False
    modes = state.attributes.get("supported_color_modes") or []
    return "rgb" in modes or "hs" in modes


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


async def _restore_lights(hass: HomeAssistant, states: dict) -> None:
    for entity_id, state in states.items():
        if state is None:
            continue
        if state.state == "on":
            data = {"entity_id": entity_id}
            attrs = state.attributes
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
