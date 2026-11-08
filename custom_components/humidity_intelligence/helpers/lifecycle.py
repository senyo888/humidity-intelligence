"""In-memory entry and public-flash custody; no device control decisions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN

_LIFECYCLE_KEY = "_lifecycle"


class IntegrationLifecycle:
    """Keep setup reservations, closing entries and accepted public calls owned."""

    def __init__(self) -> None:
        self.entries: dict[str, str] = {}
        self.public_tasks: set[asyncio.Task] = set()
        self.public_drain: asyncio.Task | None = None
        self.generation = 0

    def reserve_setup(self, entry_id: str) -> None:
        """Reserve before setup awaits; never replace retained failed custody."""
        if entry_id in self.entries or any(
            state in {"closing", "failed"} for state in self.entries.values()
        ):
            raise HomeAssistantError(
                "HI setup is blocked by an existing or closing entry. "
                "After a failed unload, resolve the reported service fault and restart Home Assistant."
            )
        self.entries[entry_id] = "starting"

    def finish_setup(self, entry_id: str) -> None:
        self.entries[entry_id] = "loaded"

    def begin_close(self, entry_id: str) -> asyncio.Task | None:
        """Close admission before awaiting; drain public work on last-owner close."""
        self.entries[entry_id] = "closing"
        if any(state in {"starting", "loaded"} for state in self.entries.values()):
            return None
        if self.public_drain is None:
            self.generation += 1
            tasks = tuple(self.public_tasks)
            for task in tasks:
                task.cancel()

            async def drain() -> None:
                # Public cancellation is expected; each worker retains accepted
                # calls and light locks through its own restoration cleanup.
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            self.public_drain = asyncio.create_task(drain(), name="hi-public-flash-drain")
        return self.public_drain

    def fail_close(self, entry_id: str) -> None:
        # Late drainage cannot clear this tombstone or reopen public admission.
        self.entries[entry_id] = "failed"

    def finish_close(self, entry_id: str) -> None:
        self.entries.pop(entry_id, None)
        if not self.entries:
            self.public_drain = None

    async def async_public_flash(
        self, generation: int, run: Callable[[], Awaitable[None]],
    ) -> None:
        """Admit after authorization, atomically owning the dedicated worker."""
        if (generation != self.generation or "loaded" not in self.entries.values()
                or "failed" in self.entries.values() or self.public_drain is not None):
            raise HomeAssistantError(
                "HI flash_lights is unavailable while HI is not loaded or is closing. "
                "After a failed unload, resolve the reported service fault and restart Home Assistant."
            )
        task = asyncio.create_task(run(), name="hi-public-flash")
        self.public_tasks.add(task)
        task.add_done_callback(self.public_tasks.discard)
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not cancelled:
                    task.cancel()
                cancelled = True
            except Exception:
                break
        try:
            task.result()
        except Exception:
            if not cancelled:
                raise
        if cancelled:
            raise asyncio.CancelledError


def lifecycle_for(hass) -> IntegrationLifecycle:
    """Return the same owner across registrations, reloads and failed unloads."""
    data = hass.data.setdefault(DOMAIN, {})
    if _LIFECYCLE_KEY not in data:
        data[_LIFECYCLE_KEY] = IntegrationLifecycle()
    return data[_LIFECYCLE_KEY]
