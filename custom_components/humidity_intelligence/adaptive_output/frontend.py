"""Serve the packaged optional card. Never write Lovelace dashboards/resources."""
from __future__ import annotations

import asyncio
from pathlib import Path

RESOURCE_URL = "/humidity_intelligence/hi-adaptive-output-card.js"
_RESOURCE_KEY = "humidity_intelligence_adaptive_output_frontend"


async def async_register_frontend(hass) -> None:
    """Register one static asset, once per HA process, using the async HTTP API.

    The caller handles unavailable HTTP as an optional presentation failure.
    Lovelace resource registration is an explicit user step, not a dashboard writer.
    """
    from homeassistant.components.http import StaticPathConfig

    state = hass.data.setdefault(_RESOURCE_KEY, {"lock": asyncio.Lock(), "registered": False})
    async with state["lock"]:
        if state["registered"]:
            return
        await hass.http.async_register_static_paths([
            StaticPathConfig(RESOURCE_URL, str(Path(__file__).with_name("hi-adaptive-output-card.js")), False)
        ])
        state["registered"] = True
