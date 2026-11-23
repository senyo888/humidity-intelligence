#!/usr/bin/env python3
"""Synchronize the supported user-preference helper in the AQ strip and details on four card surfaces."""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/humidity_intelligence/ui/voc_presentation.js"
TARGETS = (
    "custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml",
    "custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml",
    "ui-gallery/default-v2-mobile-aq/card.yaml",
    "ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml",
)
PATTERN = re.compile(r"(?m)^( +)// HI-VOC-PRESENTATION:START\n.*?^\1// HI-VOC-PRESENTATION:END$", re.S)


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
            return indent + "// HI-VOC-PRESENTATION:START\n" + "\n".join(
                indent + line if line else "" for line in source.splitlines()
            ) + "\n" + indent + "// HI-VOC-PRESENTATION:END"

        updated, count = PATTERN.subn(embed, original)
        if count != 2:
            raise SystemExit(f"{name}: expected two preference helpers, found {count}")
        if updated != original:
            stale.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and stale:
        raise SystemExit("Outdated VOC preference embeds: " + ", ".join(stale))
    print("VOC preference embeds verified." if args.check else f"Updated {len(stale)} cards.")


if __name__ == "__main__":
    main()
