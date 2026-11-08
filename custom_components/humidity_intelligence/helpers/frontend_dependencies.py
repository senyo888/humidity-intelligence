"""Shared frontend dependency inspection helpers for Humidity Intelligence."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, List

from homeassistant.core import HomeAssistant

from ..const import DEPENDENCIES

_LOGGER = logging.getLogger(__name__)


async def async_frontend_dependency_status(hass: HomeAssistant) -> dict:
    """Inspect current Lovelace resource URLs without making them a blocker."""
    lovelace_data_key = _lovelace_data_key()
    if lovelace_data_key is None:
        return frontend_dependency_not_inspectable(
            "Lovelace resource constants are not available in this Home Assistant runtime context."
        )

    if bool(getattr(getattr(hass, "config", None), "safe_mode", False)):
        return frontend_dependency_not_inspectable(
            "Home Assistant is running in safe mode; Lovelace resources are not inspectable."
        )

    try:
        lovelace_data = getattr(hass, "data", {}).get(lovelace_data_key)
    except Exception:
        _LOGGER.debug("Unable to read Lovelace runtime data for dependency inspection", exc_info=True)
        return frontend_dependency_not_inspectable(
            "Lovelace runtime data could not be read in this Home Assistant runtime context."
        )

    if lovelace_data is None:
        return frontend_dependency_not_inspectable(
            "Lovelace resource collection is not available in this Home Assistant runtime context."
        )

    resources = _lovelace_resource_collection(lovelace_data)
    if resources is None:
        return frontend_dependency_not_inspectable(
            "Lovelace resource collection is not available in this Home Assistant runtime context."
        )

    if getattr(resources, "loaded", True) is False:
        async_load = getattr(resources, "async_load", None)
        if not callable(async_load):
            return frontend_dependency_not_inspectable(
                "Lovelace resource collection is not loaded and cannot be loaded in this runtime context."
            )
        try:
            await _maybe_await(async_load())
            try:
                resources.loaded = True
            except Exception:
                pass
        except Exception:
            _LOGGER.debug("Unable to load Lovelace resources for dependency inspection", exc_info=True)
            return frontend_dependency_not_inspectable(
                "Lovelace resource collection could not be loaded for inspection."
            )

    async_items = getattr(resources, "async_items", None)
    if not callable(async_items):
        return frontend_dependency_not_inspectable(
            "Lovelace resource collection does not expose async_items() for inspection."
        )

    try:
        items = await _maybe_await(async_items())
    except Exception:
        _LOGGER.debug("Unable to inspect Lovelace resource URLs", exc_info=True)
        return frontend_dependency_not_inspectable(
            "Lovelace resource URLs could not be inspected in this Home Assistant runtime context."
        )

    if items is None:
        return frontend_dependency_not_inspectable(
            "Lovelace resource collection returned no inspectable resource list."
        )

    try:
        urls = _lovelace_resource_urls(items)
    except Exception:
        _LOGGER.debug("Unable to extract Lovelace resource URLs", exc_info=True)
        return frontend_dependency_not_inspectable(
            "Lovelace resource URLs could not be extracted in this Home Assistant runtime context."
        )

    return frontend_dependency_status_from_urls(urls)


async def async_render_dependency_status(hass: HomeAssistant) -> str:
    """Render setup/options dependency status from the shared resource truth."""
    frontend_status = await async_frontend_dependency_status(hass)
    return render_dependency_status(frontend_status)


def render_dependency_status(frontend_status: dict, custom_components_path: Path | None = None) -> str:
    """Render dependency status lines for Home Assistant config-flow forms."""
    lines: List[str] = []
    for dep in DEPENDENCIES:
        status = _dependency_display_status(dep, frontend_status, custom_components_path)
        suffix = f" | repo: {dep['url']}" if dep.get("url") else ""
        lines.append(f"- {dep['name']}: {status}{suffix}")
    return "\n".join(lines)


def frontend_dependency_status_from_urls(urls: List[str]) -> dict:
    """Build the shared dependency report from Lovelace resource URLs."""
    lowered_urls = [(url, url.lower()) for url in urls]
    status = {}
    for dependency in _frontend_resource_dependencies():
        name = str(dependency.get("name", ""))
        resource = str(dependency.get("resource") or name).lower()
        match = next(
            (
                url
                for url, lowered in lowered_urls
                if resource in lowered
            ),
            None,
        )
        status[name] = (
            {"detected": True, "url": match}
            if match is not None
            else {"detected": False}
        )
    _apply_frontend_resource_aliases(status)
    return status


def _apply_frontend_resource_aliases(status: dict) -> None:
    """Account for custom elements that are provided by another loaded resource."""
    card_mod_status = status.get("card-mod")
    mod_card_status = status.get("mod-card")
    if not isinstance(card_mod_status, dict) or not isinstance(mod_card_status, dict):
        return
    if card_mod_status.get("detected") is not True or mod_card_status.get("detected") is True:
        return

    card_mod_url = card_mod_status.get("url")
    if not isinstance(card_mod_url, str) or "card-mod.js" not in card_mod_url.lower():
        return

    status["mod-card"] = {
        "detected": True,
        "url": card_mod_url,
        "provided_by": "card-mod",
    }


def frontend_dependency_not_inspectable(reason: str) -> dict:
    """Return the explicit non-blocking status used when Lovelace cannot be read."""
    return {"status": "not_inspectable", "reason": reason}


def _frontend_resource_dependencies() -> List[dict]:
    return [dep for dep in DEPENDENCIES if dep.get("resource")]


def _dependency_display_status(
    dependency: dict,
    frontend_status: dict,
    custom_components_path: Path | None,
) -> str:
    name = str(dependency.get("name", ""))
    if dependency.get("resource"):
        if frontend_status.get("status") == "not_inspectable":
            return "Not inspectable"
        resource_status = frontend_status.get(name)
        if isinstance(resource_status, dict) and resource_status.get("detected") is True:
            return "Installed"
        if isinstance(resource_status, dict) and resource_status.get("detected") is False:
            return "Not detected"
        return "Unknown (verify manually)"

    domain = dependency.get("domain")
    if domain and custom_components_path is not None and (custom_components_path / str(domain)).exists():
        return "Detected"
    return "Unknown (verify manually)"


def _custom_components_path(hass: HomeAssistant) -> Path | None:
    config = getattr(hass, "config", None)
    path_func = getattr(config, "path", None)
    if not callable(path_func):
        return None
    try:
        return Path(path_func("custom_components"))
    except Exception:
        return None


def _lovelace_data_key() -> Any | None:
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except Exception:
        return None
    return LOVELACE_DATA


def _lovelace_resource_collection(lovelace_data: Any) -> Any | None:
    if isinstance(lovelace_data, dict):
        return lovelace_data.get("resources")
    return getattr(lovelace_data, "resources", None)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _lovelace_resource_urls(items: Any) -> List[str]:
    if items is None:
        return []
    iterable = items.values() if isinstance(items, dict) else items

    urls: List[str] = []
    for item in iterable:
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if isinstance(url, str) and url:
            urls.append(url)
    return urls
