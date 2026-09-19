#!/usr/bin/env python3
"""Deterministically embed the owned history renderer into self-contained V2 cards.

Run with --check in validation. No Home Assistant mutation or resource registration.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/humidity_intelligence/ui/badge_history.js'
TARGETS = (
    'custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml',
    'custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml',
    'ui-gallery/default-v2-mobile-aq/card.yaml',
    'ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml',
)
PATTERN = re.compile(r'(?m)^( +)// HI-HISTORY-RENDERER:START\n.*?^\1// HI-HISTORY-RENDERER:END$', re.S)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = SOURCE.read_text().rstrip()
    stale = []
    for name in TARGETS:
        path = ROOT / name
        original = path.read_text()
        def embed(match):
            indent = match.group(1)
            return indent + '// HI-HISTORY-RENDERER:START\n' + '\n'.join(indent + line if line else indent.rstrip() for line in source.splitlines()) + '\n' + indent + '// HI-HISTORY-RENDERER:END'
        updated, count = PATTERN.subn(embed, original)
        if count != 4:
            raise SystemExit(f'{name}: expected four renderer markers, found {count}')
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
