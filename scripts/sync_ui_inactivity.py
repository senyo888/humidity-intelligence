#!/usr/bin/env python3
"""Synchronize the self-contained inactivity helper in existing details dialogs."""
from __future__ import annotations
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/humidity_intelligence/ui/inactivity.js"
TARGETS = (
    "custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml",
    "custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml",
    "ui-gallery/default-v2-mobile-aq/card.yaml",
    "ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml",
    "custom_components/humidity_intelligence/ui/revision_status.js",
)
PATTERN = re.compile(r"(?m)^( +)// HI-INACTIVITY:START\n.*?^\1// HI-INACTIVITY:END$", re.S)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = SOURCE.read_text().rstrip()
    stale = []
    for name in TARGETS:
        path = ROOT / name
        original = path.read_text()
        def embed(match):
            indent = match.group(1)
            return (indent + "// HI-INACTIVITY:START\n"
                    + "\n".join(indent + line for line in source.splitlines())
                    + "\n" + indent + "// HI-INACTIVITY:END")
        # Footer copies belong to sync_ui_revision.py; update its canonical JS
        # below, without independently mutating the nested YAML copies here.
        prefix, separator, footer = original.partition("// HI-UI-REVISION:START")
        updated, count = PATTERN.subn(embed, prefix)
        updated += separator + footer
        expected = 1 if name.endswith(".js") else 10
        if count != expected:
            raise SystemExit(f"{name}: expected {expected} dialog helpers, found {count}")
        if updated != original:
            stale.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and stale:
        raise SystemExit("Outdated inactivity embeds: " + ", ".join(stale))
    print("UI inactivity embeds verified." if args.check else f"Updated {len(stale)} card files.")

if __name__ == "__main__":
    main()
