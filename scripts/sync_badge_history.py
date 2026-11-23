#!/usr/bin/env python3
"""Embed the history renderer and its live mode palette into self-contained V2 cards.

Run with --check in validation. No Home Assistant mutation or resource registration.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/humidity_intelligence/ui/badge_history.js'
TARGETS = (
    'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
    'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
    'ui-gallery/default-v2-mobile-aq/card.yaml',
    'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
)


def marked_block(marker):
    return re.compile(
        rf'^( +)// HI-{marker}:START\n(.*?)^\1// HI-{marker}:END$', re.M | re.S
    )


def embed(card, marker, source, expected, name):
    def replace(match):
        indent = match[1]
        return (f'{indent}// HI-{marker}:START\n'
                f'{textwrap.indent(source, indent)}\n{indent}// HI-{marker}:END')

    updated, count = marked_block(marker).subn(replace, card)
    if count != expected:
        raise SystemExit(f'{name}: expected {expected} {marker} blocks, found {count}')
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = SOURCE.read_text().rstrip()
    palettes = marked_block('MODE-PALETTE').findall(source)
    if len(palettes) != 1:
        raise SystemExit('Expected one canonical mode palette in the history renderer')
    palette = textwrap.dedent(palettes[0][1]).rstrip()
    stale = []
    for name in TARGETS:
        path = ROOT / name
        original = path.read_text()
        updated = embed(original, 'HISTORY-RENDERER', source, 4, name)
        updated = embed(updated, 'LIVE-MODE-PALETTE', palette, 1, name)
        if updated != original:
            stale.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and stale:
        print('Outdated history embeds: ' + ', '.join(stale), file=sys.stderr)
        return 1
    print('History renderer embeds verified.' if args.check else f'Updated {len(stale)} card files.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
