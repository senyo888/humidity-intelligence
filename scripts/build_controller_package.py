#!/usr/bin/env python3
"""Build the deterministic HI package consumed by external validation tooling.

The builder reads only tracked Git blobs from one immutable commit. It does not read
package bytes from the mutable working tree and it never publishes, installs, or
executes the resulting package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


SOURCE_PROFILE = "public_patch_1"
SOURCE_PREFIX = "custom_components/humidity_intelligence"
CONTRACT_ID = "hi-package-public-v20-conventional-1"
DOMAIN = "humidity_intelligence"
MAX_PACKAGE_BYTES = 16_777_216
SAFE_FILE_MODES = {"100644", "100755"}
INCLUDE_FILES = {
    "__init__.py",
    "binary_sensor.py",
    "config_flow.py",
    "const.py",
    "diagnostics.py",
    "manifest.json",
    "migration.py",
    "sensor.py",
    "services.py",
    "services.yaml",
    "strings.json",
    "switch.py",
}
INCLUDE_DIRECTORIES = {
    "automations",
    "brand",
    "helpers",
    "sensors",
    "translations",
    "ui",
}
REQUIRED_PATHS = {
    "__init__.py",
    "brand/icon.png",
    "brand/logo.png",
    "config_flow.py",
    "const.py",
    "diagnostics.py",
    "manifest.json",
    "sensor.py",
    "services.py",
    "services.yaml",
    "strings.json",
}
ALLOWED_NON_RUNTIME_FILES = {
    ".coderabbit.yaml",
    ".gitignore",
    ".gitleaks.toml",
    "hacs.json",
    "pyproject.toml",
}
ALLOWED_NON_RUNTIME_DIRECTORIES = {
    ".github",
    "assets",
    "docs",
    "legacy",
    "scripts",
    "site",
    "tests 2",
    "ui-gallery",
}
RUNTIME_SUFFIXES = (".py", ".json", ".yaml", ".yml")
FORBIDDEN_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".pyc"}
HIGH_CONFIDENCE_SECRET_MARKERS = (
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
    b"-----BEGIN " + b"RSA PRIVATE KEY-----",
    b"-----BEGIN " + b"EC PRIVATE KEY-----",
    b"-----BEGIN " + b"PRIVATE KEY-----",
)
SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?"
    r"(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class PackageBuildError(RuntimeError):
    """Raised when the package cannot be reproduced safely."""


@dataclass(frozen=True)
class PackageFile:
    relative_path: str
    blob_hash: str
    sha256: str
    size: int
    executable: bool


def _run_git(repository: Path, *arguments: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    if result.returncode != 0:
        raise PackageBuildError("Git could not resolve the requested package identity")
    return result.stdout


def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or value != unicodedata.normalize("NFC", value)
        or "." in path.parts
        or ".." in path.parts
        or "\\" in value
        or "//" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PackageBuildError("Git contains an unsafe package path")
    return path


def _under(path: str, directories: set[str]) -> bool:
    return any(path == directory or path.startswith(f"{directory}/") for directory in directories)


def _project_path(repository_path: str) -> str | None:
    prefix = f"{SOURCE_PREFIX}/"
    if not repository_path.startswith(prefix):
        return None
    projected = repository_path[len(prefix) :]
    _safe_path(projected)
    return projected


def _parse_tree(repository: Path, commit: str) -> list[tuple[str, str, str, str]]:
    raw = _run_git(repository, "ls-tree", "-r", "-z", "--full-tree", commit, text=False)
    assert isinstance(raw, bytes)
    entries: list[tuple[str, str, str, str]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise PackageBuildError("Git tree metadata is not safely decodable") from error
        _safe_path(path)
        entries.append((mode, object_type, object_id, path))
    if not entries:
        raise PackageBuildError("The source commit has no tracked files")
    return entries


def _read_blob(repository: Path, object_id: str) -> bytes:
    raw = _run_git(repository, "cat-file", "blob", object_id, text=False)
    assert isinstance(raw, bytes)
    return raw


def _package_hash(files: list[PackageFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda candidate: candidate.relative_path):
        digest.update(item.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(b"1" if item.executable else b"0")
        digest.update(b"\0")
    return digest.hexdigest()


def _write_new_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def build_package(repository: Path, commitish: str, output: Path) -> dict[str, object]:
    """Build one strict package tree from tracked blobs at ``commitish``."""

    repository = repository.resolve()
    top_level = Path(str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()).resolve()
    if top_level != repository:
        raise PackageBuildError("Repository path is not the resolved Git top level")
    commit = str(_run_git(repository, "rev-parse", "--verify", f"{commitish}^{{commit}}")).strip()
    tree_hash = str(_run_git(repository, "rev-parse", f"{commit}^{{tree}}")).strip()
    if not HEX40.fullmatch(commit) or not HEX40.fullmatch(tree_hash):
        raise PackageBuildError("Git identity is not a full SHA-1 commit and tree")
    if output.exists() or output.is_symlink():
        raise PackageBuildError("Package output path already exists")

    selected: list[tuple[str, str, str]] = []
    projected_keys: set[str] = set()
    for mode, object_type, object_id, source_path in _parse_tree(repository, commit):
        package_path = _project_path(source_path)
        is_selected = package_path is not None and (
            package_path in INCLUDE_FILES or _under(package_path, INCLUDE_DIRECTORIES)
        )
        is_allowed_non_runtime = source_path in ALLOWED_NON_RUNTIME_FILES or _under(
            source_path, ALLOWED_NON_RUNTIME_DIRECTORIES
        )
        if not is_selected and source_path.endswith(RUNTIME_SUFFIXES) and not is_allowed_non_runtime:
            raise PackageBuildError("A tracked runtime-looking path is not classified")
        if not is_selected:
            continue
        assert package_path is not None
        if object_type != "blob" or mode not in SAFE_FILE_MODES:
            raise PackageBuildError("The package contains an unsupported Git object or mode")
        if mode == "100755":
            raise PackageBuildError("Executable integration files are not eligible for controller intake")
        key = unicodedata.normalize("NFC", package_path).casefold()
        if key in projected_keys:
            raise PackageBuildError("Package paths collide after normalization")
        projected_keys.add(key)
        pure = _safe_path(package_path)
        if pure.name in FORBIDDEN_NAMES or pure.suffix in FORBIDDEN_SUFFIXES:
            raise PackageBuildError("The package contains a forbidden path")
        selected.append((object_id, source_path, package_path))

    selected_paths = {package_path for _object_id, _source_path, package_path in selected}
    missing = sorted(REQUIRED_PATHS - selected_paths)
    if missing:
        raise PackageBuildError(f"Required package path is missing: {missing[0]}")

    output.mkdir(parents=True, mode=0o755)
    package_root = output / "humidity_intelligence"
    package_root.mkdir(mode=0o755)
    package_files: list[PackageFile] = []
    total_bytes = 0
    manifest_document: object | None = None
    try:
        for object_id, _source_path, package_path in sorted(selected, key=lambda item: item[2]):
            content = _read_blob(repository, object_id)
            if any(marker in content for marker in HIGH_CONFIDENCE_SECRET_MARKERS):
                raise PackageBuildError("The package contains a private-key marker")
            total_bytes += len(content)
            if total_bytes > MAX_PACKAGE_BYTES:
                raise PackageBuildError("Package exceeds the fixed expanded-byte limit")
            _write_new_file(package_root.joinpath(*PurePosixPath(package_path).parts), content)
            package_files.append(
                PackageFile(
                    relative_path=package_path,
                    blob_hash=object_id,
                    sha256=hashlib.sha256(content).hexdigest(),
                    size=len(content),
                    executable=False,
                )
            )
            if package_path == "manifest.json":
                try:
                    manifest_document = json.loads(content.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise PackageBuildError("Integration manifest is invalid JSON") from error

        if not isinstance(manifest_document, dict):
            raise PackageBuildError("Integration manifest must be a JSON object")
        if manifest_document.get("domain") != DOMAIN:
            raise PackageBuildError("Integration manifest domain differs from the package contract")
        manifest_version = str(manifest_document.get("version") or "")
        if not SEMANTIC_VERSION.fullmatch(manifest_version) or not manifest_version.startswith("2.0."):
            raise PackageBuildError("Integration manifest version is outside the public V2.0 contract")

        package_hash = _package_hash(package_files)
        artifact_manifest = {
            "schema_version": 1,
            "source_profile": SOURCE_PROFILE,
            "commit": commit,
            "tree_hash": tree_hash,
            "manifest_version": manifest_version,
            "contract_id": CONTRACT_ID,
            "package_hash": package_hash,
            "files": [asdict(item) for item in package_files],
        }
        manifest_bytes = (
            json.dumps(artifact_manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        _write_new_file(output / "artifact-manifest.json", manifest_bytes)
    except Exception:
        # The output path is caller-owned evidence. Never erase partial output
        # automatically; a caller can inspect and remove its disposable directory.
        raise

    return {
        "schema_version": 1,
        "source_profile": SOURCE_PROFILE,
        "commit": commit,
        "tree_hash": tree_hash,
        "manifest_version": manifest_version,
        "contract_id": CONTRACT_ID,
        "package_hash": package_hash,
        "file_count": len(package_files),
        "total_bytes": total_bytes,
        "artifact_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = build_package(args.repository, args.commit, args.output)
    except PackageBuildError as error:
        raise SystemExit(f"controller package build blocked: {error}") from error
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
