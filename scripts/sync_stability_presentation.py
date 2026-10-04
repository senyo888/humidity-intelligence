#!/usr/bin/env python3
"""Synchronize the supported user-preference helper in the four Stability badges."""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/humidity_intelligence/ui/stability_presentation.js"
TARGETS = (
    "custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml",
    "custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml",
    "ui-gallery/default-v2-mobile-aq/card.yaml",
    "ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml",
)
PATTERN = re.compile(r"(?m)^( +)// HI-STABILITY-PRESENTATION:START\n.*?^\1// HI-STABILITY-PRESENTATION:END$", re.S)


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
            return indent + "// HI-STABILITY-PRESENTATION:START\n" + "\n".join(
                indent + line for line in source.splitlines()
            ) + "\n" + indent + "// HI-STABILITY-PRESENTATION:END"

        updated, count = PATTERN.subn(embed, original)
        if count != 1:
            raise SystemExit(f"{name}: expected one preference helper, found {count}")
        if updated != original:
            stale.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and stale:
        raise SystemExit("Outdated Stability preference embeds: " + ", ".join(stale))
    print("Stability preference embeds verified." if args.check else f"Updated {len(stale)} cards.")


if __name__ == "__main__":
    main()
