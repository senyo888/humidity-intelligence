#!/usr/bin/env python3
"""Read-only release presentation and maintainer-note custody checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NOTES = "## Maintainer notes"
RESERVED = "<!-- Reserved for the maintainer's manual notes. -->"


def _section_headings(body: str) -> list[tuple[str, int, int]]:
    """Locate level-two ATX headings outside fenced Markdown examples."""
    headings = []
    fence = ""
    offset = 0
    for line in body.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*", text):
                fence = ""
        else:
            opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", text)
            if opening and not (opening[1][0] == "`" and "`" in opening[2]):
                fence = opening[1]
            else:
                heading = re.fullmatch(r" {0,3}##(?:[ \t]+(.*))?", text)
                if heading:
                    title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[1] or "").strip()
                    headings.append((title, offset, offset + len(line)))
        offset += len(line)
    return headings


def notes_block(body: str) -> str | None:
    headings = _section_headings(body)
    for index, (title, _start, end) in enumerate(headings):
        if title == "Maintainer notes":
            stop = headings[index + 1][1] if index + 1 < len(headings) else len(body)
            return body[end:stop]
    return None


def check_pr_notes(body: str, previous: str | None = None) -> list[str]:
    if sum(title == "Maintainer notes" for title, _, _ in _section_headings(body)) != 1:
        return ["PR body must contain exactly one reserved Maintainer notes section."]
    block = notes_block(body)
    if block is None:
        return ["PR body omits the reserved Maintainer notes section."]
    if not block.strip():
        return ["Blank Maintainer notes must retain the reserved template marker."]
    old = notes_block(previous) if previous is not None else None
    # Preserve the owned section exactly, including existing manual prose.
    if old is not None and old.strip() and block != old:
        return ["Existing Maintainer notes changed; preserve the owned block verbatim."]
    return []


def check_sources(root: Path, wiki_root: Path | None = None) -> list[str]:
    errors = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    first_image = re.search(r"!\[[^\]]*\]\(([^)]+)\)", readme)
    if first_image is None or first_image.group(1) != "assets/header.png":
        errors.append("README must retain its canonical opening product banner.")
    if "## Release Notes" not in readme:
        errors.append("README Release Notes section is missing.")
    elif "assets/release_banner/" in readme.split("## Release Notes", 1)[0]:
        errors.append("README release artwork must stay in Release Notes.")
    site = (root / "site/index.html").read_text(encoding="utf-8")
    header = re.search(r'<header class="site-header".*?</header>', site, re.S)
    header_contract = ('src="assets/logo.png"', 'Humidity Intelligence',
                       'href="#inside"', 'In your home', 'href="#stability"', 'Stability Score')
    if header is None or any(item not in header.group(0) for item in header_contract):
        errors.append("Website must retain its established product header and navigation.")
    hero = re.search(r'<section class="hero".*?</section>', site, re.S)
    required = ('<h1 id="hero-title">Humidity Intelligence</h1>',
                'class="hero-logo" src="assets/logo.png"', 'class="hero-copy"')
    if hero is None or any(item not in hero.group(0) for item in required):
        errors.append("Website must retain its original product hero and logo.")
    elif "release_banner/" in hero.group(0):
        errors.append("Release artwork belongs below the original product hero.")
    stability = re.search(r'<section class="stability-section section".*?</section>', site, re.S)
    artwork = ('02 / The bigger picture', 'src="assets/release_banner/v2.1_release.png"',
               'class="led-layer"', 'class="pause-motion"')
    if stability is None or any(item not in stability.group(0) for item in artwork):
        errors.append("Section 02 must retain the V2.1 artwork, LEDs and pause control.")
    styles = (root / "site/styles.css").read_text(encoding="utf-8")
    hero_background = re.search(r"\.hero::before\s*\{([^}]+)\}", styles)
    welcome_workflow = (root / ".github/workflows/first-interaction.yml").read_text(encoding="utf-8")
    welcome_image = re.search(
        r"issue_message:\s*\|\s*!\[[^\]]*\]\([^)]*/(assets/[^)]+)\)",
        welcome_workflow,
    )
    if welcome_image is None:
        errors.append("The issue welcome image reference could not be verified.")
    elif hero_background is None or welcome_image.group(1) not in hero_background.group(1):
        errors.append("The website hero must use the same image as the issue welcome.")
    template = (root / ".github/pull_request_template.md").read_text(encoding="utf-8")
    if NOTES not in template or RESERVED not in template:
        errors.append("PR template lost the reserved Maintainer notes contract.")
    version = json.loads((root / "custom_components/humidity_intelligence/manifest.json").read_text(encoding="utf-8"))["version"]
    if "-" not in version:
        release = root / "docs/releases" / f"v{version}.md"
        if not release.is_file() or "## A note from Senyo" not in release.read_text(encoding="utf-8"):
            errors.append("Stable release notes must retain the maintainer's personal notes section.")
    if wiki_root is not None:
        home = (wiki_root / "Home.md").read_text(encoding="utf-8")
        if not home.startswith("![Humidity Intelligence Wiki](assets/hi-wiki-banner.png)"):
            errors.append("Wiki Home must retain its canonical opening banner.")
        if "release_banner/" in home:
            errors.append("Wiki Home release emphasis must preserve the product header.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path)
    parser.add_argument("--pr-body", type=Path)
    parser.add_argument("--previous-pr-body", type=Path)
    args = parser.parse_args()
    errors = check_sources(ROOT, args.wiki_root)
    if args.previous_pr_body and not args.pr_body:
        parser.error("--previous-pr-body requires --pr-body")
    if args.pr_body:
        errors += check_pr_notes(args.pr_body.read_text(encoding="utf-8"), args.previous_pr_body.read_text(encoding="utf-8") if args.previous_pr_body else None)
    if errors:
        print("\n".join(errors))
        return 1
    print("Release presentation and selected maintainer-note custody checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
