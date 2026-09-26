"""Backend-owned identity for rendered canonical UI revisions.

This contract does not verify saved dashboards, browser caches, user edits, or
configuration/mapping freshness. Revisions are independent of manifest versions.
Increment a layout revision when its canonical presentation changes; increment
the generator contract when interpretation of the stamp changes. A revision is
only an advertised update when explicitly listed in ``supersedes``.
"""

from __future__ import annotations

import hashlib
import json

UI_REVISION_SCHEMA = 1
UI_GENERATOR_CONTRACT = 1
UI_REVISION_STAMP = "__HI_UI_REVISION_STAMP__"
UI_LAYOUT_REVISIONS = {"v2_mobile": 5, "v2_tablet": 5}
UI_LAYOUT_SUPERSEDES: dict[str, tuple[int, ...]] = {
    "v2_mobile": (1, 2, 3, 4),
    "v2_tablet": (1, 2, 3, 4),
}


def revision_metadata(entry_id: str) -> dict:
    """Return an empty advertisement scoped to an opaque config-entry identity."""
    binding = hashlib.sha256(
        f"humidity_intelligence:ui-revision:{entry_id}".encode("utf-8")
    ).hexdigest()
    return {"schema": UI_REVISION_SCHEMA, "entry": binding, "layouts": {}}


def stamp_card(content: str, layout: str, metadata: dict) -> tuple[str, dict | None]:
    """Stamp a supported template; never advertise an unstamped legacy card."""
    if layout not in UI_LAYOUT_REVISIONS or UI_REVISION_STAMP not in content:
        return content, None
    target = {
        "revision": UI_LAYOUT_REVISIONS[layout],
        "generator": UI_GENERATOR_CONTRACT,
        "supersedes": list(UI_LAYOUT_SUPERSEDES[layout]),
    }
    stamp = {
        "schema": UI_REVISION_SCHEMA,
        "entry": metadata["entry"],
        "layout": layout,
        "revision": target["revision"],
        "generator": target["generator"],
    }
    return content.replace(
        UI_REVISION_STAMP, json.dumps(stamp, separators=(",", ":"), sort_keys=True)
    ), target
