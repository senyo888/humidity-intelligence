#!/usr/bin/env python3
"""Build or verify the install ZIP against one immutable Git commit.

Only committed component blobs are included. This tool never uploads, publishes,
installs, or reads package bytes from the working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import unicodedata
import zipfile

PREFIX = "custom_components/humidity_intelligence/"
FILENAME = "humidity_intelligence.zip"
# Leave substantial headroom below Marketplace's 100 MiB transfer/expansion cap.
MAX_BYTES = 16 * 1024 * 1024
MAX_FILES = 2000
REQUIRED = {"manifest.json", "__init__.py", "config_flow.py", "services.yaml",
            "strings.json", "translations/en.json", "brand/icon.png", "brand/logo.png"}
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:beta|rc)\.[1-9]\d*)?")


class PackageError(ValueError):
    """The package does not match the release contract."""


def git(repository: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repository), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def safe_name(name: str) -> None:
    parts = PurePosixPath(name).parts
    if (not parts or name != "/".join(parts) or name.startswith("/")
            or "\\" in name or any(p in {".", "..", "__pycache__"} or p.startswith(".") for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or name != unicodedata.normalize("NFC", name)
            or PurePosixPath(name).suffix.lower() in {".pyc", ".pem", ".key", ".p12", ".pfx"}):
        raise PackageError(f"Unsafe package path: {name!r}")


def source(repository: Path, ref: str) -> tuple[str, str, dict[str, bytes]]:
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    hacs = json.loads(git(repository, "show", f"{commit}:hacs.json"))
    if (hacs.get("zip_release") is not True or hacs.get("filename") != FILENAME
            or hacs.get("hide_default_branch") is not True or "content_in_root" in hacs):
        raise PackageError("Commit must declare the named release ZIP, hide_default_branch, and conventional layout")
    files: dict[str, bytes] = {}
    folded: set[str] = set()
    total = 0
    tree = git(repository, "ls-tree", "-r", "-l", "-z", commit, "--", PREFIX)
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if not path.startswith(PREFIX) or kind != "blob" or mode not in {"100644", "100755"}:
            raise PackageError("Component must contain regular tracked files only")
        name = path[len(PREFIX):]
        safe_name(name)
        if name.casefold() in folded:
            raise PackageError("Case-insensitive duplicate package path")
        folded.add(name.casefold())
        total += int(size)
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise PackageError("Component exceeds the release package size or file-count budget")
        files[name] = git(repository, "cat-file", "blob", oid)
    if missing := REQUIRED - files.keys():
        raise PackageError(f"Missing required component files: {sorted(missing)}")
    manifest = json.loads(files["manifest.json"])
    version = manifest.get("version", "")
    if manifest.get("domain") != "humidity_intelligence" or not isinstance(version, str) or not VERSION.fullmatch(version):
        raise PackageError("Invalid integration domain or version")
    return commit, version, files


def verify_bytes(data: bytes, files: dict[str, bytes]) -> None:
    if len(data) > MAX_BYTES:
        raise PackageError("ZIP exceeds the transfer budget")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_BYTES:
                raise PackageError("ZIP exceeds the expanded size or file-count budget")
            if len(names) != len(set(names)) or set(names) != files.keys():
                raise PackageError("ZIP inventory differs from the exact component tree")
            for item in entries:
                safe_name(item.filename)
                if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise PackageError("ZIP contains a directory, link or encrypted entry")
                if archive.read(item) != files[item.filename]:
                    raise PackageError(f"ZIP bytes differ from the commit: {item.filename}")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise PackageError(f"Unreadable ZIP: {exc}") from exc


def build_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    # Stored entries avoid dependence on the host's compression library. The
    # complete component is small; byte reproducibility is more useful here.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(item, content)
    data = buffer.getvalue()
    verify_bytes(data, files)
    return data


def package(repository: Path, ref: str, *, output: Path | None = None,
            verify: Path | None = None, tag: str | None = None) -> dict:
    commit, version, files = source(repository, ref)
    if tag is not None:
        if tag != f"v{version}":
            raise PackageError("Release tag must exactly match the component version")
        tagged = git(repository, "rev-parse", "--verify", "--end-of-options", f"refs/tags/{tag}^{{commit}}").decode().strip()
        if tagged != commit:
            raise PackageError("Release tag does not point to the selected commit")
    if (output is None) == (verify is None):
        raise PackageError("Choose exactly one output directory or existing ZIP to verify")
    if verify is not None:
        if verify.name != FILENAME or verify.is_symlink() or not verify.is_file():
            raise PackageError(f"Expected a regular {FILENAME} file")
        with verify.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        verify_bytes(data, files)
    else:
        data = build_bytes(files)
        output.mkdir(parents=True, exist_ok=True)
        # Never clobber an existing artifact, including a symbolic link.
        with (output / FILENAME).open("xb") as handle:
            handle.write(data)
    return {"commit": commit, "version": version, "filename": FILENAME,
            "file_count": len(files), "archive_bytes": len(data),
            "expanded_bytes": sum(map(len, files.values())),
            "sha256": hashlib.sha256(data).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--commit", required=True, help="Immutable commit or ref, resolved once before reading")
    parser.add_argument("--tag", help="Additionally require this existing tag and version to match the commit")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="New artifact directory; existing ZIPs are never overwritten")
    action.add_argument("--verify", type=Path, help="Verify an existing/downloaded ZIP against the commit")
    args = parser.parse_args()
    try:
        result = package(args.repository, args.commit, output=args.output, verify=args.verify, tag=args.tag)
    except (PackageError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Release ZIP check failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
