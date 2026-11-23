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
PATTERN = re.compile(
    r"^(?P<card_indent> +)name: (?P<owner>Current Air Control|AQ)\n"
    r"(?:(?P=card_indent)[^\n]*\n|\n)*?"
    r"^(?P<field_indent>(?P=card_indent)  )(?P<field>aq|summary): \|\n(?P=field_indent)  \[\[\[\n"
    r"(?P<block>(?P<indent>(?P=field_indent)    )// HI-VOC-PRESENTATION:START\n"
    r"(?:(?P=indent)[^\n]*\n|\n)*?^(?P=indent)// HI-VOC-PRESENTATION:END)\n"
    r"(?=(?P=indent)let stamp;\n(?P=indent)try \{ stamp = JSON\.parse\([^\n]*\n(?P=indent)hiPrepareVoc\(this,)",
    re.M,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = SOURCE.read_text().rstrip()
    updates = {}
    for name in TARGETS:
        path = ROOT / name
        original = path.read_text()

        matches = list(PATTERN.finditer(original))
        if (
            [(match["owner"], match["field"]) for match in matches] != [("Current Air Control", "aq"), ("AQ", "summary")]
            or original.count("// HI-VOC-PRESENTATION:START") != 2
            or original.count("// HI-VOC-PRESENTATION:END") != 2
        ):
            raise SystemExit(f"{name}: misplaced VOC preference helper in AQ or summary template")

        updated = original
        for match in reversed(matches):
            indent = match["indent"]
            block = indent + "// HI-VOC-PRESENTATION:START\n" + "\n".join(
                indent + line if line else "" for line in source.splitlines()
            ) + "\n" + indent + "// HI-VOC-PRESENTATION:END"
            start, end = match.span("block")
            updated = updated[:start] + block + updated[end:]
        if updated != original:
            updates[name] = updated
    if args.check and updates:
        raise SystemExit("Outdated VOC preference embeds: " + ", ".join(updates))
    for name, updated in updates.items():
        (ROOT / name).write_text(updated)
    print("VOC preference embeds verified." if args.check else f"Updated {len(updates)} cards.")


if __name__ == "__main__":
    main()
