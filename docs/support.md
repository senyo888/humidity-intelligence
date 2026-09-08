# Support and Diagnostics

Use Home Assistant's native diagnostics download when reporting a Humidity Intelligence issue. This is the preferred GitHub support bundle for v2.0.5 and later.

## Download Diagnostics

1. Open **Settings -> Devices & services**.
2. Open **Humidity Intelligence**.
3. Use the entry menu and select **Download diagnostics**.
4. Attach the downloaded file to your GitHub issue.

This helps maintainers understand your setup without asking lots of follow-up questions.

Please review the bundle before attaching if you are concerned about privacy. The bundle is designed to redact sensitive values, but you remain in control of what you upload.

## What It Contains

- Humidity Intelligence version
- Home Assistant version
- sanitized config entry and options summaries
- configuration counts and selected-entity category/status summaries
- enabled feature areas
- Home Assistant Area/Label setup-assist status, including sanitized counts for
  advisory metadata context and saved-room mismatches
- current runtime mode/lane and reason availability/truncation
- gate states
- output state summary
- sanitized humidifier demand/output reconciliation, including desired and observed
  categories, dispatch result, retry/fault state, mismatch age, and bounded history
  without configured humidifier output entity IDs
- active alert resolution
- compact local HI-only snapshot status
- house humidity drift 7d statistics dependency status, including helper readiness
  fields such as `age_coverage_ratio`, `required_age_coverage_ratio`,
  `source_value_valid`, `repair_required`, and `repair_kind` when available
- optional frontend dependency status when Home Assistant exposes Lovelace resources
- generated UI/card summary
- generated-card entity reference availability
- unavailable or unknown configured entities
- diagnostics warnings

## What Is Redacted

The diagnostics platform uses Home Assistant `async_redact_data` plus HI's own URL and token sanitising.

It redacts sensitive keys and values such as:

- tokens and bearer credentials
- credential-style keys
- secrets and passwords
- API keys
- webhook URLs
- URLs and URL query credentials
- latitude, longitude, and address-style location fields
- usernames, email, phone, host, IP, MAC, SSID, device ID, and unique ID fields

Native diagnostics prefer structure, counts, and statuses over raw entity IDs, room
names, Area names, Label names, entity maps, and state dumps. Selected mapping and
local-name evidence is generally reduced, but user-configured display and level labels may remain.
Review the complete file before uploading it to a public issue.

## v2.0.12 Diagnostics And Release Check

The v2.0.12 maintenance candidate keeps native diagnostics schema `1`, existing
redaction, aggregate mapped-entity availability, and browser-local Inspector
compatibility unchanged. After a full restart, confirm loaded identity using Home
Assistant's native diagnostics fields `custom_components.humidity_intelligence.version`
and `integration_manifest.version`, then check entry setup and entity/service
registration. HI's `data.integration.integration_version` rereads the on-disk manifest
and does not independently prove which version is loaded. See
[Candidate Registration Evidence](release-governance.md#candidate-registration-evidence)
for the separate package, restart, and registration checks.

The historical `v205_release_check` service name is unchanged. Its accepted manifest
range and result wording now cover v2.0.5-v2.0.12 beta/rc/stable. The service remains
admin-only and runtime/device read-only, writes under
`<config>/humidity_intelligence/exports/`, and cannot prove physical moisture output.
Treat its entity-bearing report as local/private until reviewed or sanitized.

## Humidifier Demand/Output Troubleshooting

The humidifier-active helper and V2 `Requested` chip mean HI currently has effective
humidification demand. They do not mean a command completed or a device is physically
producing moisture.

Use the V2 chip/reason state and native diagnostics together:

- `On`: concise V2 chip wording for backend `output_on`; Home Assistant reports the
  configured output `on`
- `Idle`: Home Assistant reports `on`, but a humidifier action attribute reports idle
- `Retrying` or `Stopping`: HI dispatched a command and is waiting or retrying within
  the bounded schedule
- `Isolated`: demand remains visible but humidifier output service calls are
  intentionally suppressed
- `Manual hold`: Manual override owns the output; HI reports the Home Assistant-
  observed state without selecting it, dispatching a command, or scheduling a retry
- `Unknown` or `Degraded`: state/service/domain/ownership evidence is not safe enough
  for a normal reconciliation claim
- `Fault`: HI has used all configured confirmation attempts; inspect the device,
  water/safety state, vendor integration, and Home Assistant entity before recovery

V2 Mobile and Tablet place ventilation and humidifier chips in one horizontally
scrollable Current Air Control row. `On` and `Requested` use cyan; `Idle`, `Retrying`,
`Stopping`, and `Isolated` amber; `Fault` and `Degraded` red; and `Unknown` grey. If an
older pasted card still shows a separate humidifier row, run `refresh_ui`, export with
`dump_cards` or `view_cards`, replace the complete Manual-card YAML, and refresh the
frontend if its styling is cached.

Manual hold is carried by the existing Manual mode badge and reason panel; it does
not add a separate generated-card chip. Native diagnostics and support-safe aggregate
truth expose `manual_hold` and `manual_hold_outputs` without configured output IDs.

HI does not bypass a device-local target, idle mode, empty-water protection, safety
timeout, or vendor fault. A later output state change, unavailable-to-available
recovery, demand transition, integration reload, or Home Assistant restart triggers
fresh evaluation; toggling helpers or repeatedly calling services is not the
recommended recovery path. If the output is `on` but no moisture is produced, inspect
the physical device and vendor integration because Home Assistant output state alone
cannot establish physical actuation.

## Optional Public Inspector Preflight

The public
[HI Support Bundle Inspector](https://senyo888.github.io/humidity-intelligence/inspector/)
processes a supported diagnostics file in the browser tab and can generate a short
`HI-SUPPORT-HANDOFF/1` block. Bug reports and configuration-help issues provide a
separate optional field for that text.

The handoff is a reduced, unsigned advisory snapshot. Native Home Assistant
diagnostics remain the preferred attachment. Runtime decisions, source
authentication, live-state verification, reason and lane selection remain with Home
Assistant and HI; correctness and anonymity remain separate user assessments.

The Inspector is an optional preflight; repository and Wiki guidance remain canonical
support documentation. Parsing and handoff generation stay in the browser tab.
GitHub Pages receives normal page-request metadata while selected diagnostic contents
remain in the tab. Copying occurs only when the user activates Copy; pasting the
result into a GitHub issue creates normal GitHub retention. The handoff field accepts
only the generated handoff text. Full `dump_diagnostics` exports remain local unless
a maintainer explicitly requests one.

## If You Cannot Download Diagnostics

Open the issue anyway and fill in the fallback fields:

- Humidity Intelligence version
- Home Assistant version
- affected area
- what happened
- checks already tried
- redacted logs or screenshots if useful

## Community Ideas & Proposals

Use the Community Ideas & Proposals issue form for ideas, dashboard suggestions, documentation
improvements, compatibility requests, diagnostics/support-flow improvements, and
automation/control suggestions that are not immediate bug reports.

Community ideas do not require a diagnostics bundle unless the idea depends on a
specific runtime, dashboard, or integration behavior. If a proposal is really a bug or
configuration problem, maintainers may reclassify it and ask for the native Home
Assistant diagnostics download.

Community interest helps maintainers understand visibility and demand. Implementation
approval stays with maintainer review, deterministic runtime behavior, UI truth, Home
Assistant compatibility, and maintainability.

Idea submission is an intake signal rather than an implementation, release-scheduling,
or acceptance commitment. The usual path is:

```text
Community idea issue -> maintainer triage -> formal HI proposal only if warranted
```

Public status wording should stay expectation-safe:

- Submitted
- Needs Info
- Triaged
- Accepted for Review
- Proposal Drafted
- Planned
- Not Accepted
- Archived

## Maintainer Notes

Native diagnostics are the preferred GitHub attachment. The existing
`humidity_intelligence.dump_diagnostics` service remains useful for local Home
Assistant validation and writes a fuller JSON export under
`<config>/humidity_intelligence/exports/`. The service requires an authenticated
admin user context; non-admin and contextless background calls are rejected. Users
should attach the native Home Assistant diagnostics download unless asked otherwise.
Review any full `dump_diagnostics` export before sharing it publicly because it
intentionally contains more local troubleshooting context than the native issue
bundle.

The v2.0.9 path change is non-destructive. Existing report and card files in the
config root are not moved, copied, symlinked, dual-written, or deleted. The fixed
self-check report now lives at
`<config>/humidity_intelligence/exports/humidity_intelligence_self_check.json`;
generated Manual-card YAML lives under `<config>/humidity_intelligence/ui/`. Those
exports are card fragments and must not be copied to `<config>/dashboards/`.

Update file sensors, shell commands, support tools, or other consumers from
`<config>/<report filename>` to
`<config>/humidity_intelligence/exports/<report filename>` and from
`<config>/<card filename>` to
`<config>/humidity_intelligence/ui/<card filename>` only after verifying a newly
generated owned-directory artifact. Then disable or remove the stale root consumer
explicitly so old JSON/YAML cannot silently remain authoritative. Multi-entry
installations must use the entry-qualified card filename reported by the service
notification. Adding a second entry re-exports every loaded entry with qualified
names; removing back to one re-exports the remaining entry with unqualified names.
HI no longer refreshes superseded owned-UI files, but external consumers can still
read their stale content. Do not treat an older inferred filename as current truth;
follow the newest notification and remove stale defaults through an explicit
previewed purge when desired. Config-entry removal deletes only the removed entry's
exact default/release-test UI exports. It retains Home Assistant dashboards, reports,
custom card exports, legacy root files, and the remaining entry's superseded
qualified files after a multi-entry installation returns to one entry.

`dump_cards` writes under `<config>/humidity_intelligence/ui/` but does not post a
completion path notification. `view_cards`, first-run export, and relevant options
regeneration do post exact written paths. Use `view_cards` when path discovery is the
priority. `refresh_ui` changes the in-memory cache only and does not write a file.
Refresh or reopen File Editor after export if the new directory is not immediately
visible.

For an artifact that exact purge intentionally retains:

1. verify the fresh replacement and its exact path
2. back up and update every file sensor, shell command, script, or support-tool
   consumer
3. delete only the confirmed regular file through File Editor, Studio Code Server,
   Samba, or SSH
4. do not delete an owned directory, use a wildcard, follow a symlink/non-regular
   object, or overwrite a dashboard file with a Manual-card fragment
5. confirm the active owned-directory artifact and Manual card remain correct

Manual deletion of an unused retained file does not itself require a Home Assistant
restart. Use the affected consumer's normal reload if its configuration changed.

External `self_check`, `dump_cards`, and `view_cards` calls now require an
authenticated admin user context, matching the existing report-writer authority
boundary. Contextless automations/scripts are rejected. HI-owned first-run, options,
and release-check test-card regeneration continues through its trusted internal path.
Startup refresh remains cache-only and does not claim that files were written.

External `flash_lights`, `create_local_backup`, and `list_saved_versions` calls also
require authenticated admin user context and reject non-admin or contextless callers
before light, snapshot, or inventory work begins. Engine-owned visual alerts use a
separate trusted internal helper after lane selection; the public service is not a
parallel control path. The inventory service remains read-only but is admin-gated
because its persistent notification exposes package-local snapshot metadata.

Keep a backup of every external consumer definition before changing it. A full Home
Assistant restart is required after installing or rolling back the package; a
config-entry reload is suitable only for exercising already-loaded updated code.
Rollback restores the complete prior integration package and backed-up consumer
paths, then requires another full restart. Files already written in either owned
directory are retained and are not moved back to the config root. Rolling back also
restores the older root-writer and external caller-authority behavior.
