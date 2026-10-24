"""Regression checks for the GitHub issue triage report helper."""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue_triage.py"


def _load_issue_triage():
    spec = importlib.util.spec_from_file_location("issue_triage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["issue_triage"] = module
    spec.loader.exec_module(module)
    return module


class IssueTriageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.triage = _load_issue_triage()
        self.generated_at = datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc)

    def _generated_handoff(
        self,
        fixture_name: str,
        *,
        all_categories: bool = False,
    ) -> str:
        self.assertIn(
            fixture_name,
            {"native_schema1.json", "dump_summary.json"},
        )
        script = f"""
import fs from "node:fs";
import {{ parseDiagnosticsText }} from "./site/inspector/parser.mjs";
import {{
  createSupportHandoff,
  PRIVACY_CATEGORIES,
  WARNING_CATEGORIES,
}} from "./site/inspector/handoff.mjs";
const text = fs.readFileSync(
  "tests 2/fixtures/hi_inspector/{fixture_name}",
  "utf8",
);
const parsed = parseDiagnosticsText(text);
if (!parsed.ok) process.exit(2);
if ({str(all_categories).lower()}) {{
  parsed.report.warnings.categories = WARNING_CATEGORIES.map(
    (category) => ({{ category, count: 1_000_000 }}),
  );
  parsed.report.privacy.categories = PRIVACY_CATEGORIES.map(
    (category) => ({{ category, count: 1_000_000 }}),
  );
}}
const handoff = createSupportHandoff(parsed.report);
if (!handoff.ok) process.exit(3);
process.stdout.write(handoff.text);
"""
        if shutil.which("node") is None:
            self.skipTest("node is required for cross-language handoff tests")
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        return completed.stdout

    def _handoff_issue(self, body: str) -> dict:
        return {
            "number": 91,
            "title": "Inspector handoff review",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/91",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": body,
        }

    def test_co_emergency_issue_routes_to_aetherwing_as_release_blocker(self) -> None:
        issue = {
            "number": 42,
            "title": "CO emergency lane does not trigger after HACS install",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/42",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": "CO emergency never wins the lane order after installing from HACS.",
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.category, "runtime")
        self.assertEqual(analyzed.priority, "P0")
        self.assertEqual(analyzed.owner, "Aetherwing")
        self.assertEqual(analyzed.release_blocker, "yes")
        self.assertEqual(analyzed.proposal_required, "no")
        self.assertIn("release-blocker", analyzed.suggested_labels)
        self.assertIn("runtime", analyzed.suggested_labels)

    def test_future_ui_idea_routes_to_aethermite_with_proposal_review(self) -> None:
        issue = {
            "number": 7,
            "title": "Experimental dashboard polish for orchestration display",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/7",
            "user": {"login": "designer"},
            "created_at": "2026-05-16T09:00:00Z",
            "updated_at": "2026-05-16T09:00:00Z",
            "labels": [{"name": "enhancement"}],
            "body": "Future idea for a more visual dashboard orchestration layer.",
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.category, "UI")
        self.assertEqual(analyzed.priority, "P3")
        self.assertEqual(analyzed.owner, "Aetherbite")
        self.assertEqual(analyzed.proposal_required, "yes")
        self.assertIn("proposal-review", analyzed.suggested_labels)
        self.assertIn("ui", analyzed.suggested_labels)

    def test_community_proposal_routes_to_bella_as_intake_signal(self) -> None:
        issue = {
            "number": 31,
            "title": "[Idea]: Add a dashboard idea queue",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/31",
            "user": {"login": "community-user"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "community-proposal"}, {"name": "needs-triage"}],
            "body": (
                "What problem are you trying to solve? I want a clearer way to suggest "
                "dashboard improvements. What should HI avoid doing? Do not change fan "
                "control automatically."
            ),
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.category, "community-proposal")
        self.assertEqual(analyzed.priority, "P3")
        self.assertEqual(analyzed.owner, "Bella")
        self.assertEqual(analyzed.proposal_required, "yes")
        self.assertEqual(analyzed.release_blocker, "no")
        self.assertEqual(analyzed.diagnostics_bundle, "not applicable")
        self.assertTrue(analyzed.needs_human_decision)
        self.assertIn("proposal-review", analyzed.suggested_labels)
        self.assertNotIn("needs-bundle", analyzed.suggested_labels)
        self.assertIn("Community Ideas & Proposals intake", analyzed.recommended_action)
        self.assertIn("formal HI proposal only if warranted", analyzed.recommended_action)

    def test_malformed_issue_is_reported_instead_of_crashing(self) -> None:
        analyzed = self.triage.analyze_issue({}, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.number, "unknown")
        self.assertEqual(analyzed.title, "Untitled issue")
        self.assertEqual(analyzed.priority, "Watch")
        self.assertEqual(analyzed.owner, "Human maintainer/Senyo")
        self.assertEqual(analyzed.release_blocker, "unknown")
        self.assertEqual(analyzed.confidence, "low")

    def test_report_contains_required_read_only_sections(self) -> None:
        issues = [
            {
                "number": 11,
                "title": "Docs mismatch in v2.0.5 release notes",
                "html_url": "https://github.com/senyo888/humidity-intelligence/issues/11",
                "user": {"login": "reader"},
                "created_at": "2026-05-15T08:00:00Z",
                "updated_at": "2026-05-17T08:00:00Z",
                "labels": [],
                "body": "README says stable release but manifest is beta.",
            }
        ]
        analyzed = [
            self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)
            for issue in issues
        ]

        report = self.triage.render_report(
            repo="senyo888/humidity-intelligence",
            analyzed_issues=analyzed,
            generated_at=self.generated_at,
            lookback_days=3,
            source_note="unit-test fixture",
            api_status="offline",
            rate_limit_note="not checked",
        )

        self.assertIn("# Report-Only GitHub Issue Triage", report)
        self.assertIn("Mode: report-only / dry-run", report)
        self.assertIn("No GitHub issues were closed, edited, labelled, assigned, or commented on.", report)
        self.assertIn("## Recommended next actions", report)
        self.assertIn("## External Advisory Queue", report)
        self.assertIn("Mode: advisory only. Queue entries do not authorize mutation.", report)
        self.assertIn("## Needs human decision", report)
        self.assertIn("## Potential labels to apply manually", report)
        self.assertIn("## Possible owner handoff", report)
        self.assertIn("## Issue template signal notes", report)
        self.assertIn("Community ideas are intake signals only", report)
        self.assertIn("Community Ideas & Proposals form captures problem", report)
        self.assertIn("does not guarantee implementation, release scheduling, or acceptance", report)
        self.assertIn("Suggested owner: Bella", report)

    def test_valid_maintenance_review_queue_action_renders_as_advisory_input(self) -> None:
        action_yaml = """
id: HI-MRQ-2026-001
title: "Review community topology and discovery idea scope"
owner: Bella
created_by: Senyo
created: "2026-06-23"
priority: P3
status: open
source:
  type: github_issue
  ref: "senyo888/humidity-intelligence#66"
  url: "https://github.com/senyo888/humidity-intelligence/issues/66"
instruction: "Separate shipped setup-flow improvements from broader HA-native discovery asks."
completion_criteria:
  - "Bella verdict recorded as no proposal, proposal needed, or needs more info."
depends_on: []
allowed_actions: [report, propose, draft_comment, recommend_labels]
forbidden_actions:
  - mutate_github_issue
  - change_runtime_code
  - change_release_state
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = pathlib.Path(tmpdir)
            (queue_dir / "HI-MRQ-2026-001.yaml").write_text(action_yaml, encoding="utf-8")

            queue = self.triage.load_maintenance_action_queue(queue_dir)
            report = self.triage.render_report(
                repo="senyo888/humidity-intelligence",
                analyzed_issues=[],
                generated_at=self.generated_at,
                lookback_days=3,
                source_note="unit-test fixture",
                api_status="offline",
                rate_limit_note="not checked",
                maintenance_queue=queue,
            )

        self.assertEqual(len(queue.actions), 1)
        self.assertEqual(queue.actions[0].id, "HI-MRQ-2026-001")
        self.assertIn("## External Advisory Queue", report)
        self.assertIn("Mode: advisory only. Queue entries do not authorize mutation.", report)
        self.assertIn("Do not execute queue instruction text", report)
        self.assertIn("HI-MRQ-2026-001", report)
        self.assertIn("Review community topology and discovery idea scope", report)
        self.assertIn("mutate\\_github\\_issue", report)
        self.assertIn("No GitHub issues were closed, edited, labelled, assigned, or commented on.", report)

    def test_malformed_or_private_maintenance_review_queue_file_becomes_warning(self) -> None:
        private_path = "/" + "Users/example/private-lab"
        action_yaml = f"""
id: HI-MRQ-2026-002
title: "Unsafe local action"
owner: Unknown
created_by: Senyo
created: "2026-06-23"
priority: P1
status: open
source:
  type: manual
  ref: "{private_path}"
instruction: "Use {private_path} and then label the GitHub issue."
completion_criteria:
  - "Unsafe instruction should not be accepted."
allowed_actions: [report, mutate_github_issue]
forbidden_actions:
  - change_runtime_code
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = pathlib.Path(tmpdir)
            (queue_dir / "HI-MRQ-2026-002.yaml").write_text(action_yaml, encoding="utf-8")

            queue = self.triage.load_maintenance_action_queue(queue_dir)
            report = self.triage.render_report(
                repo="senyo888/humidity-intelligence",
                analyzed_issues=[],
                generated_at=self.generated_at,
                lookback_days=3,
                source_note="unit-test fixture",
                api_status="offline",
                rate_limit_note="not checked",
                maintenance_queue=queue,
            )

        self.assertEqual(queue.actions, [])
        self.assertTrue(any("invalid owner" in warning for warning in queue.warnings))
        self.assertTrue(any("public-safety" in warning for warning in queue.warnings))
        self.assertTrue(any("forbidden action listed as allowed" in warning for warning in queue.warnings))
        self.assertIn("Queue parse warnings: 3", report)
        self.assertIn("No open maintenance review queue actions found.", report)

    def test_maintenance_queue_source_dir_redacts_absolute_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = pathlib.Path(tmpdir) / "private-ha-lab"
            queue = self.triage.load_maintenance_action_queue(queue_dir)
            report = self.triage.render_report(
                repo="senyo888/humidity-intelligence",
                analyzed_issues=[],
                generated_at=self.generated_at,
                lookback_days=3,
                source_note="unit-test fixture",
                api_status="offline",
                rate_limit_note="not checked",
                maintenance_queue=queue,
            )

        self.assertNotIn(tmpdir, report)
        self.assertIn("Source: directory outside repository; path redacted", report)

    def test_public_safety_rejects_cross_platform_local_paths(self) -> None:
        for local_path in (
            "/" + "home/example/work/private-lab",
            "C:" + r"\Users\Example\private-lab",
        ):
            with self.subTest(local_path=local_path):
                issue = self.triage._public_safety_issue({"instruction": local_path})
                self.assertEqual(issue, "public-safety rejected private-looking value")

    def test_write_report_rejects_paths_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            outside_path = pathlib.Path(tmpdir) / "outside.md"

            with self.assertRaises(ValueError):
                self.triage._write_report(outside_path, "unsafe report")

            self.assertFalse(outside_path.exists())

    def test_write_report_uses_confined_private_atomic_file(self) -> None:
        output_path = ROOT / "tmp_out" / "issue_triage_writer_test.md"
        output_path.unlink(missing_ok=True)

        try:
            self.triage._write_report(output_path, "safe report")

            self.assertEqual("safe report", output_path.read_text(encoding="utf-8"))
            mode = stat.S_IMODE(output_path.stat().st_mode)
            self.assertEqual(0o600, mode)
        finally:
            output_path.unlink(missing_ok=True)

    def test_issue_with_downloaded_diagnostics_gets_has_diagnostics_label(self) -> None:
        issue = {
            "number": 23,
            "title": "Generated dashboard does not show active alert context",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/23",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": (
                "I attached the downloaded Home Assistant diagnostics file: "
                "home-assistant_humidity_intelligence_abc123.json"
            ),
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.diagnostics_bundle, "present")
        self.assertIn("has-diagnostics", analyzed.suggested_labels)
        self.assertNotIn("needs-bundle", analyzed.suggested_labels)
        self.assertIn("diagnostics attached or mentioned", analyzed.signals)

    def test_bug_without_diagnostics_gets_needs_bundle_label(self) -> None:
        issue = {
            "number": 24,
            "title": "self_check says every frontend dependency is missing",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/24",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": "The UI works, but self_check reports missing optional cards.",
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.diagnostics_bundle, "missing")
        self.assertIn("needs-bundle", analyzed.suggested_labels)

    def test_unable_to_download_diagnostics_does_not_count_as_attached(self) -> None:
        issue = {
            "number": 25,
            "title": "Config flow help needed",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/25",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "question"}],
            "body": "Unable to download diagnostics file, but the issue appears after setup.",
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.diagnostics_bundle, "missing")
        self.assertIn("needs-bundle", analyzed.suggested_labels)
        self.assertNotIn("has-diagnostics", analyzed.suggested_labels)

    def test_dump_diagnostics_export_does_not_count_as_native_attachment(self) -> None:
        issue = {
            "number": 26,
            "title": "Runtime issue with diagnostics export",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/26",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": (
                "I attached humidity_intelligence_diagnostics.json from "
                "humidity_intelligence.dump_diagnostics because I could not download diagnostics."
            ),
        }

        analyzed = self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)

        self.assertEqual(analyzed.diagnostics_bundle, "missing")
        self.assertIn("needs-bundle", analyzed.suggested_labels)
        self.assertNotIn("has-diagnostics", analyzed.suggested_labels)

    def test_cross_language_native_handoff_is_advisory_and_needs_bundle_remains(self) -> None:
        handoff = self._generated_handoff("native_schema1.json")
        analyzed = self.triage.analyze_issue(
            self._handoff_issue(handoff),
            now=self.generated_at,
            lookback_days=3,
        )

        self.assertEqual(analyzed.inspector_handoff, "native-summary")
        self.assertEqual(analyzed.diagnostics_bundle, "missing")
        self.assertEqual(analyzed.category, "bug")
        self.assertEqual(analyzed.priority, "P2")
        self.assertIn("has-inspector-handoff", analyzed.suggested_labels)
        self.assertIn("needs-bundle", analyzed.suggested_labels)
        self.assertNotIn("has-diagnostics", analyzed.suggested_labels)
        self.assertIn("Inspector handoff present", analyzed.signals)

    def test_cross_language_dump_handoff_is_separate_from_diagnostics(self) -> None:
        handoff = self._generated_handoff("dump_summary.json")
        analyzed = self.triage.analyze_issue(
            self._handoff_issue(handoff),
            now=self.generated_at,
            lookback_days=3,
        )

        self.assertEqual(analyzed.inspector_handoff, "dump-summary")
        self.assertEqual(analyzed.diagnostics_bundle, "missing")
        self.assertIn("has-inspector-handoff", analyzed.suggested_labels)
        self.assertIn("needs-bundle", analyzed.suggested_labels)
        self.assertNotIn("has-diagnostics", analyzed.suggested_labels)

    def test_cross_language_all_category_handoff_remains_bounded_and_valid(self) -> None:
        handoff = self._generated_handoff(
            "native_schema1.json",
            all_categories=True,
        )
        analyzed = self.triage.analyze_issue(
            self._handoff_issue(handoff),
            now=self.generated_at,
            lookback_days=3,
        )

        self.assertEqual(analyzed.inspector_handoff, "native-summary")
        self.assertIn(
            "Backend warning categories: cfg=1000000; ent-avail=1000000",
            handoff,
        )
        self.assertIn(
            "Privacy finding categories: bearer=1000000; location=1000000",
            handoff,
        )
        self.assertLessEqual(
            max(len(line) for line in handoff.splitlines()),
            self.triage.HANDOFF_MAX_LINE_CHARS,
        )
        self.assertLessEqual(
            len(handoff),
            self.triage.HANDOFF_MAX_BLOCK_CHARS,
        )

    def test_inspector_handoff_coexists_with_native_diagnostics(self) -> None:
        body = (
            "I attached the downloaded Home Assistant diagnostics file: "
            "home-assistant_humidity_intelligence_fixture.json\n\n"
            + self._generated_handoff("native_schema1.json")
        )
        analyzed = self.triage.analyze_issue(
            self._handoff_issue(body),
            now=self.generated_at,
            lookback_days=3,
        )

        self.assertEqual(analyzed.inspector_handoff, "native-summary")
        self.assertEqual(analyzed.diagnostics_bundle, "present")
        self.assertIn("has-inspector-handoff", analyzed.suggested_labels)
        self.assertIn("has-diagnostics", analyzed.suggested_labels)
        self.assertNotIn("needs-bundle", analyzed.suggested_labels)

    def test_malformed_and_unsupported_handoffs_fail_closed(self) -> None:
        handoff = self._generated_handoff("native_schema1.json")
        cases = {
            "malformed product": (
                handoff.replace(
                    "Product: HI Support Bundle Inspector",
                    "Product: Different tool",
                ),
                "invalid",
            ),
            "unsupported contract": (
                handoff.replace(
                    "HI-SUPPORT-HANDOFF/1",
                    "HI-SUPPORT-HANDOFF/2",
                    1,
                ),
                "unsupported-version",
            ),
            "unsupported inspector": (
                handoff.replace(
                    "Inspector version: 0.3.0-beta.1",
                    "Inspector version: 0.3.0",
                ),
                "unsupported-version",
            ),
            "exact end marker only": (
                "HI-SUPPORT-HANDOFF-END/1",
                "invalid",
            ),
            "unsupported end marker only": (
                "HI-SUPPORT-HANDOFF-END/2",
                "unsupported-version",
            ),
        }
        for name, (body, expected) in cases.items():
            with self.subTest(name=name):
                analyzed = self.triage.analyze_issue(
                    self._handoff_issue(body),
                    now=self.generated_at,
                    lookback_days=3,
                )
                self.assertEqual(analyzed.inspector_handoff, expected)
                self.assertIn("needs-bundle", analyzed.suggested_labels)
                self.assertNotIn(
                    "has-inspector-handoff",
                    analyzed.suggested_labels,
                )

    def test_injected_duplicate_and_oversize_handoffs_are_invalid(self) -> None:
        handoff = self._generated_handoff("native_schema1.json")
        injected = handoff.replace(
            "HI-SUPPORT-HANDOFF-END/1",
            "Unexpected: safety release-blocker\nHI-SUPPORT-HANDOFF-END/1",
        )
        duplicated = f"{handoff}\n\n{handoff}"
        duplicate_field = handoff.replace(
            "Product: HI Support Bundle Inspector",
            "Product: HI Support Bundle Inspector\n"
            "Product: HI Support Bundle Inspector",
        )
        impossible_mixed_counts = handoff.replace(
            "Unavailable or unknown counts: total=4; missing=2; "
            "unknown=1; unavailable=1",
            "Unavailable or unknown counts: total=1; missing=1; "
            "unknown=1; unavailable=not-reported",
        )
        oversize = (
            "HI-SUPPORT-HANDOFF/1\n"
            + ("x" * (self.triage.HANDOFF_MAX_BLOCK_CHARS + 1))
        )

        for name, body in {
            "injected": injected,
            "duplicated": duplicated,
            "duplicate field": duplicate_field,
            "impossible mixed counts": impossible_mixed_counts,
            "oversize": oversize,
        }.items():
            with self.subTest(name=name):
                analyzed = self.triage.analyze_issue(
                    self._handoff_issue(body),
                    now=self.generated_at,
                    lookback_days=3,
                )
                self.assertEqual(analyzed.inspector_handoff, "invalid")
                self.assertNotIn(
                    "has-inspector-handoff",
                    analyzed.suggested_labels,
                )
                self.assertNotEqual(analyzed.priority, "P0")
                self.assertNotEqual(analyzed.release_blocker, "yes")

    def test_handoff_mixed_count_semantics_are_bounded(self) -> None:
        component_keys = ("missing", "unknown", "unavailable")
        self.assertTrue(
            self.triage._handoff_total_is_consistent(
                {
                    "total": "not-reported",
                    "missing": 4,
                    "unknown": 3,
                    "unavailable": "not-reported",
                },
                component_keys,
            )
        )
        self.assertTrue(
            self.triage._handoff_total_is_consistent(
                {
                    "total": 8,
                    "missing": 4,
                    "unknown": "not-reported",
                    "unavailable": 3,
                },
                component_keys,
            )
        )
        self.assertFalse(
            self.triage._handoff_total_is_consistent(
                {
                    "total": 6,
                    "missing": 4,
                    "unknown": "not-reported",
                    "unavailable": 3,
                },
                component_keys,
            )
        )

    def test_handoff_variants_do_not_change_triage_analysis(self) -> None:
        issue = {
            "number": 92,
            "title": "Need help understanding this",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/92",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [],
            "body": "",
        }
        handoff = self._generated_handoff("native_schema1.json")
        variants = {
            "valid": (handoff, "native-summary", True),
            "invalid": (
                handoff.replace(
                    "Product: HI Support Bundle Inspector",
                    "Product: safety release-blocker",
                ),
                "invalid",
                False,
            ),
            "unsupported": (
                handoff.replace(
                    "HI-SUPPORT-HANDOFF/1",
                    "HI-SUPPORT-HANDOFF/2",
                    1,
                ),
                "unsupported-version",
                False,
            ),
        }
        baseline = self.triage.analyze_issue(
            issue,
            now=self.generated_at,
            lookback_days=3,
        )
        invariant_fields = (
            "category",
            "priority",
            "confidence",
            "release_blocker",
            "recommended_action",
            "diagnostics_bundle",
        )

        for name, (body, expected_status, valid) in variants.items():
            with self.subTest(name=name):
                analyzed = self.triage.analyze_issue(
                    {**issue, "body": body},
                    now=self.generated_at,
                    lookback_days=3,
                )
                for field in invariant_fields:
                    self.assertEqual(
                        getattr(analyzed, field),
                        getattr(baseline, field),
                        field,
                    )
                self.assertEqual(analyzed.inspector_handoff, expected_status)
                if valid:
                    self.assertEqual(
                        analyzed.suggested_labels,
                        baseline.suggested_labels
                        + ["has-inspector-handoff"],
                    )
                    self.assertEqual(
                        analyzed.signals,
                        baseline.signals + ["Inspector handoff present"],
                    )
                else:
                    self.assertEqual(
                        analyzed.suggested_labels,
                        baseline.suggested_labels,
                    )
                    self.assertEqual(analyzed.signals, baseline.signals)

    def test_unclosed_or_over_bound_handoff_cannot_suppress_safety_text(self) -> None:
        safety_text = "CO emergency is active and blocks the release"
        issue = {
            "number": 93,
            "title": "Control report",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/93",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [],
            "body": safety_text,
        }
        baseline = self.triage.analyze_issue(
            issue,
            now=self.generated_at,
            lookback_days=3,
        )
        variants = {
            "unmatched v1": (
                f"HI-SUPPORT-HANDOFF/1\n{safety_text}",
                "invalid",
            ),
            "unmatched v2": (
                f"HI-SUPPORT-HANDOFF/2\n{safety_text}",
                "unsupported-version",
            ),
            "over-bound before end": (
                (
                    "HI-SUPPORT-HANDOFF/1\n"
                    + ("x" * (self.triage.HANDOFF_MAX_LINE_CHARS + 1))
                    + f"\n{safety_text}\nHI-SUPPORT-HANDOFF-END/1"
                ),
                "invalid",
            ),
            "no near end": (
                (
                    "HI-SUPPORT-HANDOFF/1\n"
                    + "\n".join(
                        "bounded filler"
                        for _ in range(
                            self.triage.HANDOFF_MAX_BLOCK_CHARS
                            // len("bounded filler")
                        )
                    )
                    + f"\n{safety_text}\nHI-SUPPORT-HANDOFF-END/1"
                ),
                "invalid",
            ),
        }
        invariant_fields = (
            "category",
            "priority",
            "confidence",
            "release_blocker",
            "recommended_action",
            "diagnostics_bundle",
        )

        for name, (body, expected_status) in variants.items():
            with self.subTest(name=name):
                analyzed = self.triage.analyze_issue(
                    {**issue, "body": body},
                    now=self.generated_at,
                    lookback_days=3,
                )
                for field in invariant_fields:
                    self.assertEqual(
                        getattr(analyzed, field),
                        getattr(baseline, field),
                        field,
                    )
                self.assertEqual(
                    analyzed.inspector_handoff,
                    expected_status,
                )
                self.assertEqual(analyzed.release_blocker, "yes")
                self.assertEqual(analyzed.priority, "P0")

    def test_handoff_attempt_alone_does_not_inflate_empty_body_confidence(self) -> None:
        issue = {
            "number": 94,
            "title": "Need help understanding this",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/94",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [],
            "body": "",
        }
        baseline = self.triage.analyze_issue(
            issue,
            now=self.generated_at,
            lookback_days=3,
        )
        repeated_prefixes = "\n".join(
            "Configuration counts: zones=0; aq-lanes=0; "
            "humidifier-lanes=0; alert-rules=0"
            for _ in range(70)
        )
        variants = {
            "lone v1": ("HI-SUPPORT-HANDOFF/1", "invalid"),
            "lone v2": (
                "HI-SUPPORT-HANDOFF/2",
                "unsupported-version",
            ),
            "truncated valid prefix": (
                "\n".join(
                    (
                        "HI-SUPPORT-HANDOFF/1",
                        "Product: HI Support Bundle Inspector",
                        "Inspector version: 0.3.0-beta.1",
                        "Recognized input format: native-ha-diagnostics",
                        "Backend diagnostics schema: 1",
                    )
                ),
                "invalid",
            ),
            "over-bound known prefixes": (
                f"HI-SUPPORT-HANDOFF/1\n{repeated_prefixes}",
                "invalid",
            ),
        }
        invariant_fields = (
            "category",
            "priority",
            "confidence",
            "release_blocker",
            "recommended_action",
            "diagnostics_bundle",
        )

        for name, (body, expected_status) in variants.items():
            with self.subTest(name=name):
                analyzed = self.triage.analyze_issue(
                    {**issue, "body": body},
                    now=self.generated_at,
                    lookback_days=3,
                )
                for field in invariant_fields:
                    self.assertEqual(
                        getattr(analyzed, field),
                        getattr(baseline, field),
                        field,
                    )
                self.assertEqual(
                    analyzed.inspector_handoff,
                    expected_status,
                )
                self.assertEqual(
                    analyzed.suggested_labels,
                    baseline.suggested_labels,
                )
                self.assertEqual(analyzed.signals, baseline.signals)

    def test_generic_handoff_prefix_lines_cannot_hide_safety_evidence(self) -> None:
        issue = {
            "number": 95,
            "title": "Control report",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/95",
            "user": {"login": "tester"},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [],
        }
        safety_lines = (
            "Product: carbon monoxide emergency release blocker",
            "Interpretation: CO emergency is active and blocks the release",
            "release-blocker-" * 20,
        )
        invariant_fields = (
            "category",
            "priority",
            "confidence",
            "release_blocker",
            "recommended_action",
            "diagnostics_bundle",
        )

        for safety_line in safety_lines:
            with self.subTest(safety_line=safety_line):
                baseline = self.triage.analyze_issue(
                    {**issue, "body": safety_line},
                    now=self.generated_at,
                    lookback_days=3,
                )
                analyzed = self.triage.analyze_issue(
                    {
                        **issue,
                        "body": f"HI-SUPPORT-HANDOFF/1\n{safety_line}",
                    },
                    now=self.generated_at,
                    lookback_days=3,
                )
                for field in invariant_fields:
                    self.assertEqual(
                        getattr(analyzed, field),
                        getattr(baseline, field),
                        field,
                    )
                self.assertEqual(analyzed.category, "runtime")
                self.assertEqual(analyzed.priority, "P0")
                self.assertEqual(analyzed.confidence, "high")
                self.assertEqual(analyzed.release_blocker, "yes")

    def test_inspector_handoff_status_is_escaped_and_raw_block_is_not_rendered(self) -> None:
        handoff = self._generated_handoff("native_schema1.json")
        injected = handoff.replace(
            "Backend warning categories: ent-avail=2",
            "Backend warning categories: <img src=x onerror=alert(1)>=2",
        )
        analyzed = self.triage.analyze_issue(
            self._handoff_issue(injected),
            now=self.generated_at,
            lookback_days=3,
        )
        report = self.triage.render_report(
            repo="senyo888/humidity-intelligence",
            analyzed_issues=[analyzed],
            generated_at=self.generated_at,
            lookback_days=3,
            source_note="unit-test fixture",
            api_status="offline",
            rate_limit_note="not checked",
        )

        self.assertEqual(analyzed.inspector_handoff, "invalid")
        self.assertIn("Inspector handoff: invalid", report)
        self.assertNotIn("<img", report)
        self.assertNotIn("onerror", report)
        self.assertIn("has-inspector-handoff", report)
        self.assertIn("never satisfies", report)

    def test_issue_forms_expose_optional_separate_inspector_handoff(self) -> None:
        for filename in ("bug_report.yml", "config_help.yml"):
            with self.subTest(filename=filename):
                source = (
                    ROOT / ".github" / "ISSUE_TEMPLATE" / filename
                ).read_text(encoding="utf-8")
                self.assertEqual(source.count("id: inspector-handoff"), 1)
                block = source.split("id: inspector-handoff", 1)[1].split(
                    "\n  - type:",
                    1,
                )[0]
                self.assertIn(
                    "HI Support Bundle Inspector handoff (optional)",
                    block,
                )
                self.assertIn(
                    "does not replace, the preferred native diagnostics",
                    block,
                )
                self.assertNotIn("validations:", block)

    def test_report_escapes_untrusted_issue_markup(self) -> None:
        issue = {
            "number": 88,
            "title": "<img src=x onerror=alert(1)> [fake](https://evil.example)",
            "html_url": "https://github.com/senyo888/humidity-intelligence/issues/88",
            "user": {"login": "attacker]("},
            "created_at": "2026-05-17T08:00:00Z",
            "updated_at": "2026-05-17T08:30:00Z",
            "labels": [{"name": "bug"}],
            "body": "<img src=x onerror=alert(1)> See [trusted](https://evil.example)",
        }
        analyzed = [self.triage.analyze_issue(issue, now=self.generated_at, lookback_days=3)]

        report = self.triage.render_report(
            repo="senyo888/humidity-intelligence",
            analyzed_issues=analyzed,
            generated_at=self.generated_at,
            lookback_days=3,
            source_note="unit-test fixture",
            api_status="offline",
            rate_limit_note="not checked",
        )

        self.assertNotIn("<img", report)
        self.assertNotIn("onerror=alert", report)
        self.assertNotIn("[trusted](https://evil.example)", report)
        self.assertIn("&lt;img", report)
        self.assertIn("\\[trusted\\]\\(https://evil.example\\)", report)

    def test_issue_summary_privacy_redacts_sensitive_operational_details(self) -> None:
        summary = self.triage._body_summary(
            "Failure at http://192.168.1.25:8123/api/states and "
            "http://my-ha.local:8123/api/config with "
            "sensor.private_bedroom_humidity and sensor.hi_private_bedroom. "
            "update.private_router event.private_doorbell text.private_label "
            'password="REDACTION FIXTURE PASSWORD" '
            "HA_TOKEN=REDACTION_FIXTURE_TOKEN "
            "token=REDACTION_FIXTURE_GENERIC_TOKEN "
            "Bearer abc+def/ghi== "
            "Authorization: Token REDACTION_FIXTURE_AUTH_TOKEN "
            "eyJhbGciOiJIUzI1NiJ9.REDACTION_FIXTURE_JWT.signature "
            "device_id=0123456789abcdef "
            "from /Users/example/private-ha. Public reference "
            "https://github.com/senyo888/humidity-intelligence and canonical "
            "sensor.humidity_intelligence_hi_house_average_humidity.",
            max_chars=1000,
        )

        self.assertNotIn("192.168.1.25", summary)
        self.assertNotIn("my-ha.local", summary)
        self.assertNotIn("sensor.private_bedroom_humidity", summary)
        self.assertNotIn("sensor.hi_private_bedroom", summary)
        self.assertNotIn("update.private_router", summary)
        self.assertNotIn("event.private_doorbell", summary)
        self.assertNotIn("text.private_label", summary)
        self.assertNotIn("REDACTION FIXTURE PASSWORD", summary)
        self.assertNotIn("REDACTION_FIXTURE_TOKEN", summary)
        self.assertNotIn("REDACTION_FIXTURE_GENERIC_TOKEN", summary)
        self.assertNotIn("abc+def/ghi==", summary)
        self.assertNotIn("REDACTION_FIXTURE_AUTH_TOKEN", summary)
        self.assertNotIn("REDACTION_FIXTURE_JWT", summary)
        self.assertNotIn("0123456789abcdef", summary)
        self.assertNotIn("/Users/example/private-ha", summary)
        self.assertIn("[redacted private URL]", summary)
        self.assertIn("[redacted entity ID]", summary)
        self.assertIn("password=[redacted]", summary)
        self.assertIn("HA_TOKEN=[redacted]", summary)
        self.assertIn("token=[redacted]", summary)
        self.assertIn("Bearer [redacted]", summary)
        self.assertIn("Authorization: Token [redacted]", summary)
        self.assertIn("[redacted token]", summary)
        self.assertIn("device_id=[redacted]", summary)
        self.assertIn("[redacted local path]", summary)
        self.assertIn("https://github.com/senyo888/humidity-intelligence", summary)
        self.assertNotIn("sensor.humidity_intelligence_hi_house_average_humidity", summary)

    def test_issue_summary_privacy_redacts_structured_and_local_network_variants(
        self,
    ) -> None:
        summary = self.triage._body_summary(
            'Payload {"access_token":"REDACTION_JSON_ACCESS",'
            '"device_id":"0123456789abcdef"} at '
            "http://[fd12:3456::9]:8123/api and http://[fd00::1] plus raw "
            "fd12:3456::10 and fe80::1234. Link-local IPv4 169.254.8.9. Local hosts "
            "http://homeassistant:8123/api and http://ha.lan:8123/config. "
            "Targets notify.mobile_app_private_phone geo_location.private_event "
            "image_processing.private_camera persistent_notification.private_notice "
            "plant.private_fern utility_meter.private_power. Ordinary text remains. "
            "Public references https://github.com/senyo888/humidity-intelligence "
            "and https://github.com/senyo888/ha.lan/sensor.private_room plus "
            "https://example.com/path/token=REDACTION_PUBLIC_PATH_SECRET plus "
            "https://example.com/docs, https://8.8.8.8/status, and "
            "https://[2606:4700:4700::1111]/status with raw 8.8.8.8 and "
            "2001:4860:4860::8888.",
            max_chars=2000,
        )

        for sensitive in (
            "REDACTION_JSON_ACCESS",
            "REDACTION_PUBLIC_PATH_SECRET",
            "0123456789abcdef",
            "fd12:3456::9",
            "fd00::1",
            "fd12:3456::10",
            "fe80::1234",
            "169.254.8.9",
            "homeassistant",
            "notify.mobile_app_private_phone",
            "geo_location.private_event",
            "image_processing.private_camera",
            "persistent_notification.private_notice",
            "plant.private_fern",
            "utility_meter.private_power",
        ):
            self.assertNotIn(sensitive, summary)
        self.assertNotIn("http://ha.lan:8123/config", summary)
        self.assertIn("access_token=[redacted]", summary)
        self.assertIn("device_id=[redacted]", summary)
        self.assertIn("[redacted private URL]", summary)
        self.assertIn("[redacted private address]", summary)
        self.assertIn("[redacted entity ID]", summary)
        self.assertIn("Ordinary text remains.", summary)
        self.assertIn("https://github.com/senyo888/humidity-intelligence", summary)
        self.assertNotIn(
            "https://github.com/senyo888/ha.lan/sensor.private_room",
            summary,
        )
        self.assertIn(
            "https://github.com/senyo888/[redacted private host]/"
            "[redacted entity ID]",
            summary,
        )
        self.assertIn(
            "https://example.com/path/token=[redacted]",
            summary,
        )
        self.assertIn("https://example.com/docs", summary)
        self.assertIn("https://8.8.8.8/status", summary)
        self.assertIn("https://[2606:4700:4700::1111]/status", summary)
        self.assertIn("8.8.8.8", summary)
        self.assertIn("2001:4860:4860::8888", summary)

        truncated = self.triage._body_summary("ordinary " * 20, max_chars=40)
        expected_source = ("ordinary " * 20).strip()
        self.assertEqual(
            truncated,
            expected_source[:39].rstrip() + "...",
        )

    def test_issue_summary_bounds_privacy_filter_input(self) -> None:
        max_chars = 320
        input_limit = max_chars * self.triage._SUMMARY_REDACTION_INPUT_FACTOR
        path_prefix = "/Users/example/HI Work folder/"
        long_path = (
            path_prefix
            + ("a" * (input_limit - len(path_prefix) - 1))
            + "/private-end, ordinary prose"
        )
        self.assertEqual(
            self.triage._redact_issue_summary_privacy(long_path),
            "[redacted local path], ordinary prose",
        )

        with mock.patch.object(
            self.triage,
            "_redact_issue_summary_privacy",
            side_effect=lambda value: value,
        ) as redact:
            summary = self.triage._body_summary(long_path, max_chars=max_chars)

        self.assertLessEqual(
            len(redact.call_args.args[0]),
            input_limit,
        )
        self.assertEqual(summary, self.triage._OVERSIZE_SUMMARY_MESSAGE)
        self.assertNotIn("HI Work folder", summary)
        self.assertNotIn("private-end", summary)

    def test_issue_summary_privacy_redacts_decorated_secrets_mapped_ipv6_and_paths(
        self,
    ) -> None:
        summary = self.triage._body_summary(
            'JSON {"client_secret":"REDACTION_CLIENT_SECRET"} '
            "long_lived_access_token=REDACTION_LONG_LIVED "
            r'literal {\"access_token\":\"REDACTION_ESCAPED_JSON\"} '
            "**token**: REDACTION_MARKDOWN_TOKEN "
            "local http://ha.home.arpa:8123/api "
            "mapped raw ::ffff:192.168.1.25 and URL "
            "http://[::ffff:192.168.1.25]:8123/api. "
            "mac /Users/example/My Private House/configuration.yaml then keep mac prose; "
            "linux /home/example/My Private House/configuration.yaml then keep linux prose; "
            r"windows C:\Users\example\My Private House\configuration.yaml "
            "then keep windows prose. Public "
            "https://github.com/senyo888/humidity-intelligence "
            "https://example.com/docs https://8.8.8.8/status "
            "https://[2606:4700:4700::1111]/status.",
            max_chars=3000,
        )

        for sensitive in (
            "REDACTION_CLIENT_SECRET",
            "REDACTION_LONG_LIVED",
            "REDACTION_ESCAPED_JSON",
            "REDACTION_MARKDOWN_TOKEN",
            "ha.home.arpa",
            "::ffff:192.168.1.25",
            "/Users/example/My Private House/configuration.yaml",
            "/home/example/My Private House/configuration.yaml",
            r"C:\Users\example\My Private House\configuration.yaml",
        ):
            self.assertNotIn(sensitive, summary)
        for redacted_key in (
            "client_secret=[redacted]",
            "long_lived_access_token=[redacted]",
            "access_token=[redacted]",
            "token=[redacted]",
        ):
            self.assertIn(redacted_key, summary)
        self.assertGreaterEqual(summary.count("[redacted private address]"), 1)
        self.assertIn("[redacted private URL]", summary)
        self.assertEqual(summary.count("[redacted local path]"), 3)
        for prose in (
            "then keep mac prose",
            "then keep linux prose",
            "then keep windows prose",
        ):
            self.assertIn(prose, summary)
        for public_url in (
            "https://github.com/senyo888/humidity-intelligence",
            "https://example.com/docs",
            "https://8.8.8.8/status",
            "https://[2606:4700:4700::1111]/status",
        ):
            self.assertIn(public_url, summary)

    def test_issue_summary_privacy_redacts_single_decorators_cgnat_and_local_paths(
        self,
    ) -> None:
        summary = self.triage._body_summary(
            "*token*: REDACTION_STAR_TOKEN "
            "_api_key_: REDACTION_UNDERSCORE_KEY "
            "CGNAT http://100.64.12.34:8123/api and raw 100.64.12.34. "
            "mac /Users/example/HI Work folder/humidity_intelligence_v2-develop, "
            "then keep mac prose; "
            "linux /home/example/HI Work folder/humidity_intelligence_v2-develop; "
            "then keep linux prose; "
            r"windows C:\Users\example\HI Work folder\humidity-intelligence,"
            " then keep windows prose. Public https://8.8.8.8/status "
            "https://[2606:4700:4700::1111]/status.",
            max_chars=3000,
        )
        end_summary = self.triage._body_summary(
            "/Users/example/HI Work folder/humidity_intelligence_v2-develop",
            max_chars=1000,
        )

        for sensitive in (
            "REDACTION_STAR_TOKEN",
            "REDACTION_UNDERSCORE_KEY",
            "100.64.12.34",
            "/Users/example/HI Work folder/humidity_intelligence_v2-develop",
            "/home/example/HI Work folder/humidity_intelligence_v2-develop",
            r"C:\Users\example\HI Work folder\humidity-intelligence",
        ):
            self.assertNotIn(sensitive, summary)
        self.assertIn("token=[redacted]", summary)
        self.assertIn("api_key=[redacted]", summary)
        self.assertIn("[redacted private URL]", summary)
        self.assertIn("[redacted private address]", summary)
        self.assertEqual(summary.count("[redacted local path]"), 3)
        self.assertEqual(end_summary, "[redacted local path]")
        for prose in (
            "then keep mac prose",
            "then keep linux prose",
            "then keep windows prose",
        ):
            self.assertIn(prose, summary)
        self.assertIn("https://8.8.8.8/status", summary)
        self.assertIn("https://[2606:4700:4700::1111]/status", summary)

    def test_privacy_redaction_bounds_hostile_decorator_nonmatches(self) -> None:
        # Isolate the regex so a regression fails within a fixed deadline instead
        # of hanging this report-only helper's entire test batch.
        code = r"""
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('triage_budget_probe', path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
for decorator in ['*', '_', '`', '"', "'", '\\"', '*_`"']:
    for suffix in [' ordinary', 'token ordinary', 'device_id ordinary']:
        body = (decorator * 2560)[:2560 - len(suffix)] + suffix
        assert len(body) == 2560
        assert isinstance(mod._body_summary(body), str)
for key in ['token', 'device_id']:
    for decorator in ['*', '_', '`', '"', "'", '\\"', '*_`"']:
        value = mod._body_summary(decorator * 64 + key + decorator * 64 + '=SYNTHETIC_PRIVATE_VALUE')
        assert 'SYNTHETIC_PRIVATE_VALUE' not in value
        assert key + '=[redacted]' in value
print('Hostile nonmatches and legitimate decorated assignments completed.')
"""
        result = subprocess.run([sys.executable, '-c', code, str(SCRIPT)],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fetch_open_issues_refuses_non_https_request_before_urlopen(self) -> None:
        request = mock.Mock(full_url="file:///tmp/issues.json")

        def fail_urlopen(*_args, **_kwargs):
            raise AssertionError("urlopen should not be called for non-HTTPS URLs")

        with mock.patch.object(self.triage.urllib.request, "Request", return_value=request):
            with mock.patch.object(self.triage.urllib.request, "urlopen", side_effect=fail_urlopen):
                with self.assertRaisesRegex(ValueError, "Refusing non-HTTPS URL: file"):
                    self.triage.fetch_open_issues(
                        "senyo888/humidity-intelligence",
                        max_pages=1,
                        token=None,
                    )


if __name__ == "__main__":
    unittest.main()
