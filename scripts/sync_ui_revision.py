#!/usr/bin/env python3
"""Embed the owned UI-revision renderer in both canonical and gallery cards."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/humidity_intelligence/ui/revision_status.js"
TARGETS = (
    "custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml",
    "custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml",
    "ui-gallery/default-v2-mobile-aq/card.yaml",
    "ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml",
)
PATTERN = re.compile(r"(?m)^( +)// HI-UI-REVISION:START\n.*?^\1// HI-UI-REVISION:END$", re.S)


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
            return (indent + "// HI-UI-REVISION:START\n"
                    + "\n".join(indent + line if line else indent.rstrip() for line in source.splitlines())
                    + "\n" + indent + "// HI-UI-REVISION:END")
        updated, count = PATTERN.subn(embed, original)
        if count != 1:
            raise SystemExit(f"{name}: expected one revision renderer, found {count}")
        if updated != original:
            stale.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and stale:
        raise SystemExit("Outdated revision embeds: " + ", ".join(stale))
    print("UI revision embeds verified." if args.check else f"Updated {len(stale)} card files.")


if __name__ == "__main__":
    main()
