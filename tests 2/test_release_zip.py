"""Release packaging tests with real Git trees and ZIP payloads."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_zip", ROOT / "scripts/build_release_zip.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseZipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Package test")
        self.git("config", "user.email", "package@example.invalid")
        self.component = self.repo / builder.PREFIX
        self.component.mkdir(parents=True)
        self.files = {name: b"fixture\n" for name in builder.REQUIRED}
        self.files.update({"ui/cards/v2_mobile.yaml": b"type: markdown\ncontent: fixture\n",
                           "helpers/example.py": b"VALUE = 1\n",
                           "manifest.json": json.dumps({"domain": "humidity_intelligence", "version": "2.1.2-beta.1"}).encode()})
        for name, content in self.files.items():
            path = self.component / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.hacs = {"name": "Humidity Intelligence", "zip_release": True,
                     "filename": builder.FILENAME, "hide_default_branch": True}
        (self.repo / "hacs.json").write_text(json.dumps(self.hacs))
        (self.repo / "assets").mkdir()
        (self.repo / "assets/art.png").write_bytes(b"repository artwork")
        self.commit = self.commit_all()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit_all(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Package fixture")
        return self.git("rev-parse", "HEAD")

    def make_zip(self, entries):
        data = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(data, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in entries:
                archive.writestr(name, content)
        return data.getvalue()

    def test_exact_commit_ignores_dirty_untracked_and_repository_files(self):
        (self.component / "helpers/example.py").write_bytes(b"unreviewed edit")
        (self.component / "manifest 2.json").write_bytes(b"untracked copy")
        first = builder.package(self.repo, self.commit, output=self.root / "one")
        second = builder.package(self.repo, self.commit, output=self.root / "two")
        self.assertEqual(first, second)
        archive = self.root / "one" / builder.FILENAME
        self.assertEqual(first, builder.package(self.repo, self.commit, verify=archive))
        with zipfile.ZipFile(archive) as zip_file:
            self.assertEqual(set(self.files), set(zip_file.namelist()))
            self.assertEqual(self.files, {name: zip_file.read(name) for name in zip_file.namelist()})
            # Both supported installers extract this asset into their domain directory.
            destination = self.root / "config/custom_components/humidity_intelligence"
            zip_file.extractall(destination)
        self.assertEqual("2.1.2-beta.1", json.loads((destination / "manifest.json").read_bytes())["version"])
        self.assertFalse((destination / "humidity_intelligence").exists())

    def test_pins_selected_version_and_validates_tag_identity(self):
        self.git("tag", "v2.1.2-beta.1")
        builder.package(self.repo, self.commit, output=self.root / "tagged", tag="v2.1.2-beta.1")
        manifest = self.component / "manifest.json"
        manifest.write_text(json.dumps({"domain": "humidity_intelligence", "version": "2.1.2-beta.2"}))
        newer = self.commit_all()
        with self.assertRaises(builder.PackageError):
            builder.package(self.repo, newer, output=self.root / "bad", tag="v2.1.2-beta.1")
        self.assertEqual("2.1.2-beta.1", builder.source(self.repo, self.commit)[1])
        self.assertEqual("2.1.2-beta.2", builder.source(self.repo, newer)[1])

    def test_rejects_wrong_hacs_asset_or_unsafe_branch_option(self):
        for key, value in (("filename", "other.zip"), ("zip_release", False), ("hide_default_branch", False), ("content_in_root", True)):
            with self.subTest(key=key):
                (self.repo / "hacs.json").write_text(json.dumps({**self.hacs, key: value}))
                commit = self.commit_all()
                with self.assertRaises(builder.PackageError):
                    builder.source(self.repo, commit)

    def test_rejects_committed_links_and_missing_required_files(self):
        (self.component / "linked.py").symlink_to("helpers/example.py")
        linked = self.commit_all()
        with self.assertRaises(builder.PackageError):
            builder.source(self.repo, linked)
        (self.component / "linked.py").unlink()
        (self.component / "manifest.json").unlink()
        missing = self.commit_all()
        with self.assertRaises(builder.PackageError):
            builder.source(self.repo, missing)

    def test_rejects_mutated_missing_extra_nested_and_duplicate_entries(self):
        original = list(self.files.items())
        variants = [original[:-1], original + [("unexpected.txt", b"extra")],
                    [("humidity_intelligence/" + n, b) for n, b in original],
                    original + [original[0]],
                    [(n, b"tampered" if n == "manifest.json" else b) for n, b in original]]
        for entries in variants:
            with self.subTest(names=[n for n, _ in entries]), self.assertRaises(builder.PackageError):
                builder.verify_bytes(self.make_zip(entries), self.files)

    def test_rejects_missing_corrupt_and_oversized_assets(self):
        path = self.root / builder.FILENAME
        with self.assertRaises(builder.PackageError):
            builder.package(self.repo, self.commit, verify=path)
        with self.assertRaises(builder.PackageError):
            builder.verify_bytes(b"not a zip", self.files)
        with patch.object(builder, "MAX_BYTES", 10), self.assertRaises(builder.PackageError):
            builder.verify_bytes(b"x" * 11, self.files)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("large", b"x" * 10000)
        with patch.object(builder, "MAX_BYTES", 1000), self.assertRaises(builder.PackageError):
            builder.verify_bytes(data.getvalue(), {"large": b"x" * 10000})
        with patch.object(builder, "MAX_BYTES", 10), self.assertRaises(builder.PackageError):
            builder.source(self.repo, self.commit)

    def test_rejects_zip_symlinks_and_unsafe_paths(self):
        item = zipfile.ZipInfo("manifest.json")
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        entries = [(item if n == "manifest.json" else n, b) for n, b in self.files.items()]
        with self.assertRaises(builder.PackageError):
            builder.verify_bytes(self.make_zip(entries), self.files)
        for name in ("../outside", "/absolute", "a\\b", "a//b", ".env", "secret.pem", "__pycache__/x.pyc"):
            with self.subTest(name=name), self.assertRaises(builder.PackageError):
                builder.safe_name(name)

    def test_never_overwrites_artifact_or_link(self):
        output = self.root / "out"
        builder.package(self.repo, self.commit, output=output)
        before = (output / builder.FILENAME).read_bytes()
        with self.assertRaises(FileExistsError):
            builder.package(self.repo, self.commit, output=output)
        self.assertEqual(before, (output / builder.FILENAME).read_bytes())


if __name__ == "__main__":
    unittest.main()
