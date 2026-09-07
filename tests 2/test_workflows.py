"""Regression checks for GitHub workflow configuration."""

from __future__ import annotations

import pathlib
import re
import shutil
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIRST_INTERACTION_V3_SHA = "1c4688942c71f71d4f5502a26ea67c331730fa4d"
ACTIONS_CHECKOUT_V7_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
ACTIONS_SETUP_NODE_V7_SHA = "820762786026740c76f36085b0efc47a31fe5020"
HACS_ACTION_MAIN_SHA = "1ebf01c408f29afcb6406bd431bc98fd8cbb15aa"
MUTABLE_ACTION_REF_RE = re.compile(
    r"^\s*uses:\s*[^@\s]+@(main|master|v?\d+(?:\.\d+){0,2})\s*(?:#.*)?$",
    re.MULTILINE,
)


class WorkflowConfigurationTests(unittest.TestCase):
    def test_secret_scan_fails_closed_when_tracked_mode_has_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = pathlib.Path(tmpdir)
            script = workdir / "scripts" / "security" / "scan_secrets.sh"
            script.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "security" / "scan_secrets.sh", script)
            shutil.copy2(ROOT / ".gitleaks.toml", workdir / ".gitleaks.toml")

            fake_bin = workdir / "bin"
            fake_bin.mkdir()
            fake_gitleaks = fake_bin / "gitleaks"
            fake_gitleaks.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake_gitleaks.chmod(fake_gitleaks.stat().st_mode | stat.S_IXUSR)

            subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
            result = subprocess.run(
                ["bash", str(script), "tracked"],
                cwd=workdir,
                env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("No tracked files found", result.stderr)

    def test_secret_scan_runs_gitleaks_when_tracked_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = pathlib.Path(tmpdir)
            script = workdir / "scripts" / "security" / "scan_secrets.sh"
            script.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "security" / "scan_secrets.sh", script)
            shutil.copy2(ROOT / ".gitleaks.toml", workdir / ".gitleaks.toml")
            (workdir / "README.md").write_text("tracked file\n", encoding="utf-8")

            fake_bin = workdir / "bin"
            fake_bin.mkdir()
            marker = workdir / "gitleaks-called.txt"
            fake_gitleaks = fake_bin / "gitleaks"
            fake_gitleaks.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    printf '%s\n' "$@" > {marker}
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            fake_gitleaks.chmod(fake_gitleaks.stat().st_mode | stat.S_IXUSR)

            subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
            subprocess.run(["git", "add", "README.md"], cwd=workdir, check=True)
            result = subprocess.run(
                ["bash", str(script), "tracked"],
                cwd=workdir,
                env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(marker.exists())
            self.assertIn("dir", marker.read_text(encoding="utf-8"))

    def test_validate_requires_exact_conventional_component_layout(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
        hacs = (ROOT / "hacs.json").read_text(encoding="utf-8")

        self.assertNotIn('"content_in_root"', hacs)
        self.assertIn(
            'integration = Path("custom_components/humidity_intelligence")',
            workflow,
        )
        self.assertIn('if "content_in_root" in hacs:', workflow)
        self.assertIn('if Path("manifest.json").exists():', workflow)
        self.assertIn(
            "python -m compileall -q custom_components/humidity_intelligence",
            workflow,
        )
        self.assertNotIn("python -m compileall -q .", workflow)

    def test_validate_executes_generated_card_renderers(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'python "tests 2/test_controller_package.py"', workflow
        )
        self.assertIn(
            'node --test "tests 2/test_reason_card_renderer.mjs"', workflow
        )
        self.assertIn(
            'node --test "tests 2/test_stability_badge_renderer.mjs"', workflow
        )
        setup_node = f"actions/setup-node@{ACTIONS_SETUP_NODE_V7_SHA} # v7.0.0"
        self.assertIn(setup_node, workflow)
        self.assertIn('node-version: "24"', workflow)
        self.assertLess(
            workflow.index(setup_node),
            workflow.index("- name: Validate generated-card renderers"),
        )

    def test_component_brand_assets_use_home_assistant_local_brand_layout(self) -> None:
        integration = ROOT / "custom_components" / "humidity_intelligence"
        repository_brand = ROOT / "brand"

        self.assertTrue((integration / "brand" / "icon.png").is_file())
        self.assertTrue((integration / "brand" / "logo.png").is_file())
        self.assertFalse((integration / "icon.png").exists())
        self.assertFalse((integration / "logo.png").exists())
        self.assertEqual(
            (repository_brand / "icon.png").read_bytes(),
            (integration / "brand" / "icon.png").read_bytes(),
        )
        self.assertEqual(
            (repository_brand / "logo.png").read_bytes(),
            (integration / "brand" / "logo.png").read_bytes(),
        )
        tracked_component_files = subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "custom_components/humidity_intelligence",
            ],
            cwd=ROOT,
        ).split(b"\0")
        self.assertEqual(53, len([path for path in tracked_component_files if path]))

        for workflow_name in ("hassfest.yaml", "release.yml", "validate.yml"):
            workflow = (
                ROOT / ".github" / "workflows" / workflow_name
            ).read_text(encoding="utf-8")
            self.assertIn('("brand/icon.png", "brand/logo.png")', workflow)
            self.assertIn('("icon.png", "logo.png")', workflow)
            self.assertIn("Missing local integration brand asset", workflow)
            self.assertIn("Repository and integration brand assets differ", workflow)

    def test_hassfest_validates_tracked_layout_without_staging(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "hassfest.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Verify tracked Hassfest layout and metadata", workflow)
        self.assertIn(
            'base = Path("custom_components/humidity_intelligence")',
            workflow,
        )
        self.assertIn('if "content_in_root" in hacs:', workflow)
        self.assertIn('if Path("manifest.json").exists():', workflow)
        self.assertNotIn("Stage custom component layout", workflow)
        self.assertNotIn("Normalize staged Hassfest metadata", workflow)
        self.assertNotIn("rsync -a", workflow)
        self.assertNotIn("manifest.pop", workflow)
        self.assertNotIn(".write_text(", workflow)
        self.assertIn("home-assistant/actions/hassfest@", workflow)

    def test_release_requires_exact_conventional_component_layout(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'integration = Path("custom_components/humidity_intelligence")',
            workflow,
        )
        self.assertIn('if "content_in_root" in hacs:', workflow)
        self.assertIn('if Path("manifest.json").exists():', workflow)
        self.assertNotIn('glob("*/manifest.json")', workflow)

    def test_first_interaction_v3_is_pinned_and_uses_supported_input_names(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "first-interaction.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(f"actions/first-interaction@{FIRST_INTERACTION_V3_SHA} # v3", workflow)
        self.assertNotIn("actions/first-interaction@v3", workflow)
        self.assertIn("repo_token:", workflow)
        self.assertIn("issue_message:", workflow)
        self.assertIn("pr_message:", workflow)
        self.assertNotIn("repo-token:", workflow)
        self.assertNotIn("issue-message:", workflow)
        self.assertNotIn("pr-message:", workflow)

    def test_hacs_validation_actions_are_pinned_to_reviewed_commits(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "hacs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(f"actions/checkout@{ACTIONS_CHECKOUT_V7_SHA} # v7", workflow)
        self.assertIn(f"hacs/action@{HACS_ACTION_MAIN_SHA} # main", workflow)
        self.assertNotIn("actions/checkout@v7", workflow)
        self.assertNotIn("hacs/action@main", workflow)

    def test_workflow_actions_do_not_use_mutable_refs(self) -> None:
        mutable_refs = []
        for workflow_path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            workflow = workflow_path.read_text(encoding="utf-8")
            for match in MUTABLE_ACTION_REF_RE.finditer(workflow):
                line_number = workflow[: match.start()].count("\n") + 1
                relative_path = workflow_path.relative_to(ROOT)
                mutable_refs.append(
                    f"{relative_path}:{line_number}: {match.group(0).strip()}"
                )

        self.assertEqual([], mutable_refs)


if __name__ == "__main__":
    unittest.main()
