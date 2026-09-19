"""Regression coverage for the deterministic external-controller package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import unittest.mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_controller_package.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "controller-package.yml"
UPLOAD_ARTIFACT_V7_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
ATTEST_V4_1_0_SHA = "59d89421af93a897026c735860bf21b6eb4f7b26"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_controller_package", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("controller package builder could not be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _git(*arguments: str, text: bool = True):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=text)


class ControllerPackageTests(unittest.TestCase):
    def test_explicit_package_version_contracts(self) -> None:
        for version in ("2.0.12", "2.0.12-rc.1"):
            self.assertEqual("hi-package-public-v20-conventional-1", BUILDER._contract_for_version(version))
        for version in ("2.1.0-beta.1", "2.1.0-rc.1", "2.1.0"):
            self.assertEqual("hi-package-public-v21-conventional-1", BUILDER._contract_for_version(version))
        for version in ("2.1.1", "2.2.0", "3.0.0", "2.1.0-beta.0", "2.1.0-alpha.1", "2.1.0-beta.01"):
            with self.subTest(version=version), self.assertRaises(BUILDER.PackageBuildError):
                BUILDER._contract_for_version(version)

    def test_current_commit_build_is_deterministic_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            first = base / "first"
            second = base / "second"
            first_summary = BUILDER.build_package(ROOT, "HEAD", first)
            second_summary = BUILDER.build_package(ROOT, "HEAD", second)

            self.assertEqual(first_summary, second_summary)
            self.assertEqual("public_patch_1", first_summary["source_profile"])
            expected_contract = (
                "hi-package-public-v21-conventional-1"
                if first_summary["manifest_version"].startswith("2.1.0")
                else "hi-package-public-v20-conventional-1"
            )
            self.assertEqual(expected_contract, first_summary["contract_id"])
            self.assertEqual(56, first_summary["file_count"])

            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)
            self.assertEqual(57, len(first_files))
            self.assertIn("humidity_intelligence/ui/badge_history.js", first_files)

            manifest = json.loads(first_files["artifact-manifest.json"])
            self.assertEqual(first_summary["package_hash"], manifest["package_hash"])
            self.assertEqual(first_summary["commit"], manifest["commit"])
            self.assertEqual(first_summary["tree_hash"], manifest["tree_hash"])
            self.assertEqual(56, len(manifest["files"]))

            digest = hashlib.sha256()
            for item in sorted(manifest["files"], key=lambda value: value["relative_path"]):
                relative_path = item["relative_path"]
                content = first_files[f"humidity_intelligence/{relative_path}"]
                self.assertEqual(item["size"], len(content))
                self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())
                self.assertFalse(item["executable"])
                self.assertEqual(
                    content,
                    _git(
                        "cat-file",
                        "blob",
                        item["blob_hash"],
                        text=False,
                    ),
                )
                digest.update(relative_path.encode("utf-8"))
                digest.update(b"\0")
                digest.update(item["sha256"].encode("ascii"))
                digest.update(b"\0")
                digest.update(str(item["size"]).encode("ascii"))
                digest.update(b"\0")
                digest.update(b"0\0")
            self.assertEqual(manifest["package_hash"], digest.hexdigest())

    def test_builder_refuses_an_existing_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "existing"
            output.mkdir()
            with self.assertRaisesRegex(BUILDER.PackageBuildError, "already exists"):
                BUILDER.build_package(ROOT, "HEAD", output)

    def test_builder_blocks_high_confidence_private_key_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "blocked"
            with unittest.mock.patch.object(
                BUILDER,
                "_read_blob",
                return_value=b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----\n",
            ):
                with self.assertRaisesRegex(BUILDER.PackageBuildError, "private-key"):
                    BUILDER.build_package(ROOT, "HEAD", output)

    def test_scenario_is_excluded_without_allowing_other_tools_runtime_paths(self) -> None:
        real_tree = BUILDER._parse_tree(ROOT, "HEAD")
        for path in ("tools/rogue.py", "tools/stability-scenario-other/rogue.py"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary:
                with unittest.mock.patch.object(
                    BUILDER, "_parse_tree",
                    return_value=real_tree + [("100644", "blob", "0" * 40, path)],
                ):
                    with self.assertRaisesRegex(BUILDER.PackageBuildError, "not classified"):
                        BUILDER.build_package(ROOT, "HEAD", pathlib.Path(temporary) / "package")
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "package"
            BUILDER.build_package(ROOT, "HEAD", output)
            self.assertFalse((output / "tools").exists())
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertTrue(all(not item["relative_path"].startswith("tools/") for item in manifest["files"]))

    def test_workflow_is_branch_bound_pinned_and_release_independent(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("github.ref == 'refs/heads/senyo888-patch-1'", workflow)
        self.assertIn("name: humidity-intelligence-controller-package", workflow)
        self.assertIn("retention-days: 7", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("scripts/security/scan_secrets.sh tracked", workflow)
        self.assertIn('python3 "tests 2/test_controller_package.py"', workflow)
        self.assertIn(f"actions/upload-artifact@{UPLOAD_ARTIFACT_V7_SHA} # v7", workflow)
        self.assertIn(f"actions/attest@{ATTEST_V4_1_0_SHA} # v4.1.0", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertNotIn("releases:", workflow)
        self.assertNotIn("packages: write", workflow)
        self.assertNotIn("contents: write", workflow)


if __name__ == "__main__":
    unittest.main()
