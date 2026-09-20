#!/usr/bin/env python3
"""Check canonical UI revision maintenance without importing Home Assistant.

Compare working-tree files with an explicit --base, GitHub PR/push base, or
HEAD^ locally. A first adoption without historical metadata is allowed.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
METADATA = "custom_components/humidity_intelligence/ui/revision.py"
LAYOUT_FILES = {
    "v2_mobile": ("custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml", "ui-gallery/default-v2-mobile-aq/card.yaml"),
    "v2_tablet": ("custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml", "ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml"),
}
SHARED_FILES = (
    "custom_components/humidity_intelligence/ui/inactivity.js",
    "custom_components/humidity_intelligence/ui/register.py",
    "custom_components/humidity_intelligence/ui/revision_status.js",
    "custom_components/humidity_intelligence/adaptive_output/cards.py",
    "custom_components/humidity_intelligence/adaptive_output/hi-adaptive-output-card.js",
    "custom_components/humidity_intelligence/ui/badge_history.js",
)
CONSTANTS = ("UI_REVISION_SCHEMA", "UI_GENERATOR_CONTRACT", "UI_LAYOUT_REVISIONS", "UI_LAYOUT_SUPERSEDES")


def positive(value):
    return type(value) is int and 0 < value <= 9007199254740991


def parse_metadata(source):
    """Read literal top-level constants only; never execute the module."""
    values = {}
    for node in ast.parse(source).body:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else [node.target.id] if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) else []
        for name in names:
            if name in CONSTANTS:
                if name in values:
                    raise ValueError(f"Duplicate metadata constant: {name}")
                values[name] = ast.literal_eval(node.value)
    if set(values) != set(CONSTANTS):
        raise ValueError("UI revision metadata must define all four literal contract constants.")
    for name in CONSTANTS[:2]:
        if not positive(values[name]):
            raise ValueError(f"{name} must be a positive safe integer.")
    revisions, supersedes = (values[name] for name in CONSTANTS[2:])
    if not isinstance(revisions, dict) or not isinstance(supersedes, dict) or set(revisions) != set(LAYOUT_FILES) or set(supersedes) != set(LAYOUT_FILES):
        raise ValueError("Revision and supersedes mappings must cover both canonical V2 layouts.")
    for layout, revision in revisions.items():
        older = supersedes[layout]
        if not positive(revision) or not isinstance(older, (tuple, list)) or any(not positive(item) or item >= revision for item in older) or len(set(older)) != len(older):
            raise ValueError(f"{layout}: revision must be positive; supersedes must contain unique positive older revisions.")
    return values


def implementation(source):
    """Compare executable stamp/binding code independently of revision constants."""
    tree = ast.parse(source)
    def owned(node):
        if isinstance(node, ast.Assign):
            return bool(node.targets) and all(isinstance(target, ast.Name) and target.id in CONSTANTS for target in node.targets)
        return isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in CONSTANTS
    tree.body = [node for node in tree.body if not owned(node)]
    return ast.dump(tree, include_attributes=False)


def compare(current, previous, changed):
    """Return violations for a validated metadata pair and changed path set."""
    if previous is None:
        return []
    errors = []
    contract_changed = False
    for name in CONSTANTS[:2]:
        if current[name] < previous[name]:
            errors.append(f"{name} cannot decrease.")
        contract_changed |= current[name] != previous[name]
    shared_changed = bool((set(SHARED_FILES) | {METADATA}) & set(changed))
    for layout, files in LAYOUT_FILES.items():
        revision = current["UI_LAYOUT_REVISIONS"][layout]
        old = previous["UI_LAYOUT_REVISIONS"][layout]
        if revision < old:
            errors.append(f"{layout}: revision cannot decrease ({old} -> {revision}).")
        if (contract_changed or shared_changed or set(files) & set(changed)) and revision <= old:
            errors.append(f"{layout}: canonical UI/generator changed; increment its revision above {old}.")
    return errors


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], check=check, text=True, capture_output=True)


def choose_base(root, explicit=None, event_path=None):
    if explicit:
        return explicit
    event_path = event_path if event_path is not None else os.getenv("GITHUB_EVENT_PATH")
    if event_path:
        event = json.loads(Path(event_path).read_text())
        if not isinstance(event, dict):
            raise ValueError("GitHub event must be an object.")
        before = event.get("before")
        if isinstance(before, str) and before and set(before) == {"0"}:
            default = event.get("repository", {}).get("default_branch")
            if not isinstance(default, str) or not default:
                raise ValueError("New-branch push requires repository.default_branch or explicit --base.")
            merged = git(root, "merge-base", "HEAD", f"refs/remotes/origin/{default}", check=False)
            if merged.returncode != 0 or not merged.stdout.strip():
                raise ValueError("Cannot resolve new-branch merge-base; fetch the default branch or provide --base.")
            return merged.stdout.strip()
        candidate = event.get("pull_request", {}).get("base", {}).get("sha") or event.get("before")
        if isinstance(candidate, str) and candidate and set(candidate) != {"0"}:
            return candidate
    parent = git(root, "rev-parse", "--verify", "HEAD^", check=False)
    return parent.stdout.strip() if parent.returncode == 0 else None


def historical(root, base, path):
    result = git(root, "show", f"{base}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def check_repository(root, base):
    current_source = (root / METADATA).read_text()
    current = parse_metadata(current_source)
    if base is None:
        return []
    git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    old_source = historical(root, base, METADATA)
    previous = parse_metadata(old_source) if old_source is not None else None
    paths = set(SHARED_FILES) | {path for files in LAYOUT_FILES.values() for path in files}
    changed = {path for path in paths if historical(root, base, path) != ((root / path).read_text() if (root / path).is_file() else None)}
    if old_source is not None and implementation(current_source) != implementation(old_source):
        changed.add(METADATA)
    return compare(current, previous, changed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Git commit/ref to compare with (for example a preceding release tag)")
    args = parser.parse_args(argv)
    try:
        base = choose_base(ROOT, args.base)
        errors = check_repository(ROOT, base)
    except (OSError, ValueError, SyntaxError, subprocess.CalledProcessError) as exc:
        print(f"UI revision governance failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("UI revision governance failed:\n" + "\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"UI revision governance passed (base: {base or 'first adoption'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
