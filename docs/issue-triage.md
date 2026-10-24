# Report-Only Issue Triage

Humidity Intelligence includes a report-only Codex workspace helper for GitHub issue
triage.

The helper fetches open GitHub issues, identifies new, untriaged, or recently updated
items, and writes a structured Markdown report for Bella, Aetherwing, Aetherbite, or
the human maintainer to review.

It writes reports only. Closing, editing, labeling, assigning, and public comments stay
manual maintainer actions.
It also treats Community Ideas & Proposals issues as intake signals only: interest and
comments can inform visibility, while implementation, runtime, release, and Home
Assistant authority stay with maintainer review.

## Manual Run

From the repository root:

```bash
GITHUB_REPOSITORY=senyo888/humidity-intelligence python3 scripts/issue_triage.py --dry-run
```

Default output:

```text
.codex/reports/issue_triage/daily_issue_triage.md
```

`.codex/` is local workspace output. Keep generated triage reports ignored/local unless
the maintainer explicitly asks to publish a sanitized summary.

Generated triage reports are timestamped support snapshots. The current release state
stays in `CHANGELOG.md`, `custom_components/humidity_intelligence/manifest.json`, and
`docs/release-governance.md`.

## Privacy Boundary

Issue-body summaries are privacy-filtered before report escaping. The filter removes
private Home Assistant URLs and hosts, local network addresses, bearer credentials and
tokens, device IDs, local user paths, and Home Assistant entity IDs. Public issue links
remain available for triage. Repeated Markdown decorators around sensitive keys
use an unambiguous character pattern, preserving redaction without exponential
backtracking on ordinary nonmatching text. Summary input remains length-bounded;
this does not claim that every regex operation has linear runtime.

Inspector handoffs are parsed as an exact, bounded `HI-SUPPORT-HANDOFF/1` contract.
Only fixed fields, bounded counts, and allowlisted warning/privacy categories are
accepted. Closed, bounded malformed, injected, duplicated, or unsupported-version
blocks are classified without rendering their contents or influencing priority,
safety, release, runtime, or lane analysis. For unmatched or over-bound attempts,
marker lines and consecutive lines that strictly match the handoff contract grammar
are neutralized; privacy-filtered triage resumes at the first ordinary line so
legitimate safety or release evidence that follows cannot be suppressed.

The filter is defense in depth, not permission to publish a generated report
automatically. Reports remain ignored/local and must be reviewed before any sanitized
extract is shared.

## Authentication

The script works without `GITHUB_TOKEN` for public, low-volume checks. Unauthenticated
GitHub API runs are rate limited, so scheduled workspace use should set a token through
the environment when available:

```bash
# With GITHUB_TOKEN already set in the environment:
GITHUB_REPOSITORY=senyo888/humidity-intelligence python3 scripts/issue_triage.py --dry-run
```

Never write tokens into docs, reports, shell history exports, cron logs, or issue text.

## Useful Options

```bash
# Include all fetched open issues instead of only new/recent/untriaged candidates.
python3 scripts/issue_triage.py --include-all-open

# Widen the recent-update window.
python3 scripts/issue_triage.py --lookback-days 7

# Write to a custom local report path.
python3 scripts/issue_triage.py --output .codex/reports/issue_triage/weekly_issue_triage.md

# Test report rendering from a saved GitHub issues JSON fixture.
python3 scripts/issue_triage.py --input-json /path/to/issues.json

# Render an optional external advisory queue from a local directory.
python3 scripts/issue_triage.py --maintenance-queue-dir /path/to/actions/open

# Suppress external advisory queue rendering for an issue-only report fixture.
python3 scripts/issue_triage.py --skip-maintenance-queue
```

## External Advisory Queue

The report can optionally render public-safe advisory YAML files from a local
directory. These entries are inert report text only; implementation, GitHub issue
mutation, Home Assistant calls, runtime changes, generated dashboard edits,
entity-semantic changes, and release-state changes stay behind maintainer approval.
Malformed or private-looking entries become report warnings instead of stopping the
issue triage run.

## Safe Optional Scheduling

Use a read-only workspace schedule only if it matches maintainer capacity. For
community ideas, weekly or maintainer-capacity triage is safer than promising daily
attention. The scheduled command should run from the repository root and should only
write local `.codex/reports/` output.

Weekly cron-style example:

```cron
0 8 * * 1 cd <repo> && GITHUB_REPOSITORY=senyo888/humidity-intelligence python3 scripts/issue_triage.py --dry-run >> .codex/reports/issue_triage/issue_triage.log 2>&1
```

Codex workspace automation wording:

```text
Every Monday at 08:00, run from the Humidity Intelligence repository root:
GITHUB_REPOSITORY=senyo888/humidity-intelligence python3 scripts/issue_triage.py --dry-run

Keep the task read-only/report-only. Do not close, edit, label, assign, or comment on
GitHub issues.
```

## Triage Mapping

Suggested owner mapping:

- Bella: architecture, roadmap, governance, proposals, community ideas/proposals intake, coherence, documentation truth
- Aetherwing: runtime safety, regression protection, release validation, deterministic lane logic, issue fixes
- Aetherbite: UI ideas, visual polish, brainstorms, experimental UX proposals
- Human maintainer/Senyo: unclear reports, repo policy decisions, community-facing replies, release approval

Priority mapping:

- P0: safety, CO/emergency logic, data loss, broken install, HACS-breaking, release-blocking
- P1: runtime correctness, false UI state, broken config flow, broken services, major docs mismatch
- P2: normal bug, UX issue, dependency detection issue, confusing behaviour
- P3: enhancement, polish, wording, future idea
- Watch: unclear, needs reproduction, potentially duplicate, not enough detail

## Diagnostics Bundle Signal

Bug and configuration-help issues now ask users to attach the downloaded Home Assistant
diagnostics file for Humidity Intelligence:

```text
Settings -> Devices & services -> Humidity Intelligence -> Download diagnostics
```

The triage script detects issue bodies that mention or link the native Home Assistant
diagnostics download and suggests `has-diagnostics`. Bug, runtime, UI, or support
issues without an attached or mentioned native diagnostics file are suggested for
`needs-bundle`.

Bug and configuration-help forms also provide a separate optional Inspector handoff
field. Triage reports classify it as `absent`, `native-summary`, `dump-summary`,
`invalid`, or `unsupported-version`. A valid block suggests
`has-inspector-handoff`, but never satisfies the diagnostics-bundle signal, suggests
`has-diagnostics`, removes `needs-bundle`, or changes runtime, safety, priority, and
release inference. It is an unsigned advisory summary, not a diagnostics attachment
or proof that the source is anonymous or correct.

The existing `humidity_intelligence.dump_diagnostics` JSON export remains a local
maintainer/debug tool. It should not be counted as the safe GitHub issue attachment
path unless a maintainer explicitly asks for it.

These are manual label recommendations only. Label creation, label application,
comments, closing, assignment, and uploads stay outside the script.

Suggested maintainer flow:

1. Triage safety/release blockers first.
2. Prioritise `has-diagnostics` issues next because they are faster to inspect.
3. For `needs-bundle` issues, ask the reporter to attach the downloaded Home Assistant diagnostics file when practical.
4. Route `community-proposal` issues through maintainer/Bella review before any implementation planning. Convert a community idea into a formal HI proposal only if warranted.
5. Inspect diagnostics locally before deep investigation; the file should include versions, sanitized configuration and selected-entity summaries, runtime lane/mode and reason availability, gates, outputs, frontend dependency status, generated UI summary, and redacted diagnostics.

## Implemented Issue Template Triage Fields

The GitHub issue templates include maintainer-friendly triage fields so the report has
better signals without needing a bot to edit public issues.

Bug reports, configuration help, and feature requests include a shared `Affected area`
dropdown:

- Runtime/control
- Config flow/options
- Generated UI/dashboard
- Services/diagnostics
- Documentation
- HACS/install
- Governance/release
- Unsure

Bug reports and configuration help include shared `Triage signals` checkboxes:

- Safety, CO, or emergency behaviour may be affected.
- This may block a release or HACS install.
- This looks like a regression from a previous HI version.
- This may be a duplicate of another issue.
- I think this needs maintainer/community reply rather than code.
- I think this needs proposal review before implementation.

Bug reports include a `Checks already tried` field for commands or services already
run, such as downloading diagnostics, `refresh_ui`, `self_check`,
`v205_release_check`, `dump_diagnostics`, or a Home Assistant restart.

Bug reports and configuration help include an optional diagnostics attachment field
and a separate optional Inspector handoff field. The handoff field accepts only the
copied v1 block and explicitly warns users not to paste original diagnostic content.
Version/setup fallback fields remain available for users who cannot download
diagnostics.

Feature requests include a required `Proposal scope` dropdown:

- Small bugfix-sized change
- UI polish
- Runtime semantics
- Release/governance
- v2.1 or later exploration
- Unsure

Community Ideas & Proposals issues include user-friendly intake fields:

- problem being solved
- requested improvement
- kind of idea
- affected area
- affected rooms, devices, integrations, or dashboards
- behavior HI should avoid
- practical benefit
- similar issues or proposals
- optional screenshots, examples, diagnostics, or workaround

Community idea labels are advisory workflow signals. Acceptance, scheduling,
implementation-readiness, release scheduling, and roadmap inclusion stay with
maintainer review.

Expected public lifecycle wording:

- Submitted
- Needs Info
- Triaged
- Accepted for Review
- Proposal Drafted
- Planned
- Not Accepted
- Archived

UI Gallery submissions include fields for:

- source layout
- frontend dependencies used
- whether the YAML was exported by HI, lightly edited from HI output, hand-written, or unsure

The script still treats all template-derived signals as advisory. Labels, assignments,
comments, duplicate links, closures, and proposal promotion remain manual maintainer
actions.

Recommended manual labels after review:

- `needs-triage`
- `community-proposal`
- `proposal-review`
- `support`
- `needs-bundle`
- `has-diagnostics`
- `has-inspector-handoff`
