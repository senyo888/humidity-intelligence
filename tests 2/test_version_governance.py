"""Regression checks for branch/version release governance."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_version_governance.py"


def _load_version_governance():
    spec = importlib.util.spec_from_file_location("check_version_governance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["check_version_governance"] = module
    spec.loader.exec_module(module)
    return module


class VersionGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governance = _load_version_governance()

    def _run_check(self, *, branch: str, version: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(self.governance, "_active_branch", return_value=branch):
            with mock.patch.object(self.governance, "_manifest_version", return_value=version):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = self.governance.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_v21_beta_is_allowed_on_patch_lane_but_not_main_or_develop(self) -> None:
        for branch, expected in (("senyo888-patch-1", 0), ("main", 1), ("develop", 1)):
            with self.subTest(branch=branch):
                result, _stdout, _stderr = self._run_check(branch=branch, version="2.1.0-beta.1")
                self.assertEqual(expected, result)

    def test_manifest_path_targets_conventional_component(self) -> None:
        self.assertEqual(
            ROOT
            / "custom_components"
            / "humidity_intelligence"
            / "manifest.json",
            self.governance.MANIFEST_PATH,
        )

    def test_manifest_version_reads_nested_component_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = (
                pathlib.Path(tmpdir)
                / "custom_components"
                / "humidity_intelligence"
                / "manifest.json"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"version": "2.0.10-beta.3"}\n', encoding="utf-8")

            with mock.patch.object(self.governance, "MANIFEST_PATH", manifest):
                self.assertEqual("2.0.10-beta.3", self.governance._manifest_version())

    def test_exact_release_branch_may_carry_matching_stable_version(self) -> None:
        result, stdout, stderr = self._run_check(branch="v2.0.5", version="2.0.5")

        self.assertEqual(result, 0, stderr)
        self.assertIn("Version governance OK", stdout)

    def test_release_branch_rejects_prerelease_version(self) -> None:
        result, _stdout, stderr = self._run_check(branch="v2.0.5", version="2.0.5-rc.1")

        self.assertEqual(result, 1)
        self.assertIn("Release branch 'v2.0.5' must carry matching stable version", stderr)

    def test_release_branch_rejects_mismatched_stable_version(self) -> None:
        result, _stdout, stderr = self._run_check(branch="v2.0.5", version="2.0.6")

        self.assertEqual(result, 1)
        self.assertIn("Release branch 'v2.0.5' must carry matching stable version", stderr)

    def test_testing_branch_still_rejects_stable_version(self) -> None:
        result, _stdout, stderr = self._run_check(branch="fix/version-check", version="2.0.5")

        self.assertEqual(result, 1)
        self.assertIn("must not carry stable version", stderr)

    def test_dependabot_branch_may_carry_current_stable_version(self) -> None:
        result, stdout, stderr = self._run_check(
            branch="dependabot/github_actions/actions/checkout-7.0.0",
            version="2.0.7",
        )

        self.assertEqual(result, 0, stderr)
        self.assertIn("Version governance OK", stdout)

    def test_active_branch_prefers_github_head_ref_over_base_ref(self) -> None:
        env = {
            "GITHUB_BASE_REF": "develop",
            "GITHUB_HEAD_REF": "fix/stable-test",
        }

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(self.governance, "_git_branch", return_value="main"):
                self.assertEqual(self.governance._active_branch(), "fix/stable-test")

    def test_active_branch_prefers_ref_name_over_base_ref_without_head_ref(self) -> None:
        env = {
            "GITHUB_BASE_REF": "develop",
            "GITHUB_REF_NAME": "fix/stable-test",
        }

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(self.governance, "_git_branch", return_value="main"):
                self.assertEqual(self.governance._active_branch(), "fix/stable-test")

    def test_active_branch_prefers_version_governance_override(self) -> None:
        env = {
            "VERSION_GOVERNANCE_BRANCH": "manual/stable-test",
            "GITHUB_BASE_REF": "develop",
            "GITHUB_HEAD_REF": "fix/stable-test",
            "GITHUB_REF_NAME": "feature/ref-name",
        }

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(self.governance, "_git_branch", return_value="main"):
                self.assertEqual(self.governance._active_branch(), "manual/stable-test")


if __name__ == "__main__":
    unittest.main()
