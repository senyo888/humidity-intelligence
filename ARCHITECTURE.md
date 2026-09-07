# Humidity Intelligence Architecture Contract

This is the public architecture contract for Humidity Intelligence. It records the
durable runtime and documentation rules that contributors, reviewers, and release
checks can rely on from tracked repository files.

Maintainers may keep deeper planning notes in ignored local files such as
`DESIGN_BRIEF.md`, `PROJECT_SUMMARY.md`, `ROADMAP.md`, or `PROPOSALS.md`. Those
files are not required for public contributor correctness and must not become release
authority unless their sanitized value is promoted into tracked documentation.

## Runtime Authority

Humidity Intelligence is a deterministic Home Assistant environmental control engine.
It resolves one selected ventilation lane per evaluation cycle and exposes the reason
through Home Assistant entities, diagnostics, and exported Manual-card YAML.

Runtime behavior is owned by tracked integration code, tracked tests, tracked service
schemas, tracked generated-card templates, and release documentation. Ignored local
planning notes may inform maintainer review, but they do not override tracked runtime
truth.

## Deterministic Lane Order

Ventilation lane priority is fixed:

1. CO emergency
2. Humidity danger
3. Mould danger
4. Mould risk
5. Condensation danger
6. Condensation risk
7. Zone 1
8. Zone 2
9. Air quality
10. Normal

CO emergency is always highest priority. Humidity, mould, and condensation alert lanes
must resolve source, room, and zone before applying zone-bound control. If an alert
candidate cannot be mapped safely, Humidity Intelligence must skip blind output writes,
surface degraded context, and continue explainably.

Humidifier lanes remain independent from ventilation lane resolution.

Manual override is a complete handover of ordinary output ownership. While Manual is
active, HI cancels or neutralizes pending non-CO alert, AQ, and humidifier work, clears
its active-lane helper/timer truth, and sends no ordinary fan, switch, humidifier, or
visual-alert command. Existing physical output states remain untouched and are
reported only as Home Assistant-observed truth; HI must not describe them as selected
or commanded. Humidifier reconciliation uses the explicit additive `manual_hold`
state rather than desired-off, stopping, or isolated truth. CO emergency remains the
sole exception and may force only its configured ventilation outputs to 100%. Turning
Manual off requests a fresh evaluation so normal deterministic AUTO ownership can
resume immediately.

Humidifier control has separate truth layers:

- effective lane demand after runtime gates and before humidifier-output isolation
- command intent and dispatch result
- Home Assistant-observed output state
- optional platform action when the entity domain exposes it
- isolated, retrying, degraded, unknown, or fault-latched reconciliation state

The existing humidifier-active helper entities represent effective demand only.
They do not prove command completion, an `on` output, or physical moisture
production. Configured humidifier outputs are observed directly and are aggregated
before writes; when both humidifier lanes share an output, demand is OR-owned and the
engine emits at most one non-conflicting command for that output per evaluation.

Output state-change events request coalesced evaluation and the configured engine
interval remains the periodic reconciliation safety net. Reconciliation is bounded:
one immediate dispatch, two delayed retries, then a visible fault latch until demand
changes or observed output truth recovers. Missing, unknown, unavailable, unsupported,
isolated, cross-family-owned, or active cross-entry-owned outputs suppress blind
turn-on behavior. A generic Home Assistant `on` state is only observed output truth;
even an optional humidifier action attribute is platform-reported evidence, not proof
of physical moisture production.

## Season-Aware Targets

Humidity danger and comfort interpretation are profile-relative. Runtime thresholds
must be derived from the active seasonal or custom target profile, not from stale static
alert values.

Temperature comfort display follows the same principle: UI colors and chips should use
backend comfort truth instead of card-only assumptions.

## UI Truth Contract

Generated dashboards are presentation surfaces, not decision engines.

They may render:

- selected runtime lane
- gate, pause, override, and disabled states
- active alert context
- degraded or unmapped alert context
- configured telemetry and output availability
- diagnostics and generated-card validation results

They must not invent entities, infer lane decisions independently, hide degraded
inputs, or imply output control that the backend did not select.

Current Air Control chips are display surfaces only. They must not create, reorder, or
alter lane decisions. Red control-row styling is reserved for selected alert or CO
runtime truth; environmental risk readings may still show risk colors in telemetry
chips without implying a selected command lane.

The existing Current Air Control Reason entity may expose the additive
`display_reason` attribute using the exact `hi.reason.v1` schema. That object is the
backend-owned V2 reason-presentation authority and is built only after authoritative
lane, gate, timer, helper, reconciliation, and output-selection work. Its presenter is
pure, bounded to 4 KiB, and failure-isolated: invalid or failed presentation is
omitted while the existing technical state, `full_reason`, truncation behavior, and
`humidifier_status` remain available as the compatibility fallback.

The exact top-level object contains only required fields `schema`, `locale`, `family`,
`variant`, `attention`, `truncated`, `headline`, and `lines`. `schema` is
`hi.reason.v1`; `locale` is `en`; attention is `neutral`, `active`, `hold`,
`degraded`, `critical`, or `unknown`. Each ordered line contains required `role`,
`scope`, `code`, `truth`, and `text`, plus optional `args`. Roles are `why`, `action`,
`next`, and `notice`; scopes are `system`, `safety`, `ventilation`, and `humidifier`;
truth values are `selected`, `blocked`, `requested`, `observed`, `unavailable`,
`unmapped`, `not_confirmed`, and `failed`.

The contract targets six lines and permits no more than eight. Headline text is
bounded to 120 characters and each line to 200; family, variant, and argument-key
tokens are at most 64 characters, dotted line codes are at most 96, each line permits
six JSON-scalar arguments, and string argument values are at most 64 characters. The
serialized object is limited to 4 KiB. Normalized text rejects control characters,
the markup delimiters `<`, `>`, and backtick, and raw entity IDs. One line represents
one role and one truth; cause and
action remain separate, and every retained line must be semantically complete if
bounded compaction removes its neighbours.

Schema-1 cards render final backend-authored headline and line text. They may validate
schema support, escape text, and fall back atomically, but must not reconstruct prose
from codes/arguments or add independent Stage, risk, timer, isolation, or Engine
explanations. Ventilation output wording must remain selection truth unless dispatch
and observation are separately proven. Humidifier wording may use its stronger
reconciliation evidence while preserving the physical-moisture caveat.

The title-case card chip `Requested` means effective backend humidification demand;
it does not prove a service call, output state, or physical moisture. It must not be
conflated with line truth `requested`, which means the backend recorded handoff to
Home Assistant without an immediate exception. Neither namespace proves physical
moisture production.

Unavailable-only presence evidence is presented as degraded
`presence_unavailable`, not confirmed absence. The v2.0.10 contract preserves the
existing fail-closed gate effect and CO bypass; changing presence unknown-policy is a
separate runtime decision.

## Safe Degradation

Unknown, unavailable, incomplete, or unmapped inputs must degrade safely and
explainably. Missing outputs or failed optional service calls must be logged, skipped,
and exposed without crashing the control loop.

Optional frontend cards and UI dependencies must never block backend functionality.

## External Service Authority

External Home Assistant calls to `pause_control`, `resume_control`,
`create_dashboard`, `purge_files`, `dump_diagnostics`, `self_check`,
`v205_release_check`, `dump_cards`, `view_cards`, `flash_lights`, and
`create_local_backup` require an admin user context whether they target one config
entry or all entries. The read-only `list_saved_versions` service is also admin-gated
because it exposes package-local snapshot inventory through a persistent
notification. An `entry_id` narrows a target only; it is not an authorization bypass.

Contextless background automation/script calls are intentionally rejected. Supported
external use originates from an authenticated admin UI or API session; any future
automated trusted route requires separate design approval.

`create_dashboard` is retained as an admin-gated compatibility service but is a
guidance-only fail-safe: after authorization it raises deterministic `refresh_ui`,
`view_cards`, and Manual-card instructions before mapping, rendering, filesystem
access, or Lovelace imports. First-run card export, option-triggered regeneration, and
release-check test exports use the trusted internal card exporter so admin-gating the
public `dump_cards` and `view_cards` handlers does not break integration-owned
continuity. Startup refresh remains cache-only and does not claim a filesystem export.
New setup does not offer dashboard creation. Legacy `create_dashboard` selections and
`ui_dashboard_id` values are inert compatibility data and require no migration.

Runtime-owned visual alerts call a separate trusted internal flashing helper after
the deterministic engine has selected an alert lane. The public `flash_lights`
service is admin-gated and is not the engine's control path; it cannot create,
reorder, or override a lane decision.

Generated-artifact purge must validate its full fixed file target set before mutation,
show the exact existing files in a completed blocking notification before deletion,
reject paths outside the direct owned basename set and non-regular filesystem objects,
and report partial failures truthfully. Home Assistant dashboards are user-managed and
must never be inferred as HI-owned, previewed, or deleted from legacy stored IDs.

Caller-selectable diagnostics and release-check report basenames must match
`humidity_intelligence_*.json` and are written only inside the owned
`<config>/humidity_intelligence/exports/` directory. Directory verification,
creation, temporary writes, atomic replacement, cleanup, and report purge stay
descriptor-relative, reject symlink/non-regular targets, and fail closed without a
config-root fallback. In-process writes are serialized; concurrent same-name calls
produce complete JSON and the last atomic replacement wins without promising caller
invocation order. The fixed self-check report uses the same writer and exact
`<config>/humidity_intelligence/exports/humidity_intelligence_self_check.json`
destination. Entry-scoped purge owns no export report. Only an unscoped all-entry
purge may remove the exact default diagnostics and fixed self-check exports;
release-check, custom, and legacy config-root reports remain retained.

Generated Manual-card YAML fragments are written only inside
`<config>/humidity_intelligence/ui/`. Directory verification, creation, temporary
writes, atomic replacement, and cleanup are descriptor-relative and no-follow,
reject symlink and non-regular targets, revalidate directory/file identity, and fail
closed without a config-root fallback. Same-name writes are serialized. Multi-entry
installations use entry-qualified filenames; single-entry installations retain the
unqualified default names. Exact default/per-entry card and release-check test-card
exports are purge-owned. Custom card names and legacy root YAML are retained.
Adding a second entry re-exports every loaded entry with qualified names; removing
back to one entry re-exports the remaining entry with unqualified names. Superseded
owned-UI names are retained non-destructively, are no longer refreshed by HI, and
remain externally readable until an exact purge. Config-entry removal owns only the
removed entry's exact default/release-test UI exports; it does not own Home Assistant
dashboards, reports, custom card exports, or legacy root files. When removal returns
a multi-entry installation to one entry, the remaining entry's qualified files stay
retained while fresh unqualified exports are written. Card exports are not complete
dashboard documents and must not be written to `<config>/dashboards/`; dashboard
creation, registration, editing, and deletion stay within Home Assistant's UI.

Dynamic state or attribute text rendered through generated-card HTML must be escaped
at the HTML sink. The V1 Mobile presentation remains available but deprecated through
v2.0.9; any removal requires a separately approved v2.1 migration contract.

## Home Assistant And HACS Boundaries

Config flow, options flow, entity registry behavior, services, translations,
diagnostics, and generated files must remain compatible with supported Home Assistant
versions.

Avoid blocking filesystem, network, or slow I/O work in async Home Assistant paths.
Keep service schemas explicit and error messages actionable. Keep `hacs.json` limited
to HACS-supported keys and keep integration metadata in
`custom_components/humidity_intelligence/manifest.json`.

The installable integration package is tracked under
`custom_components/humidity_intelligence/`, which is the conventional HACS integration
layout. HACS must install that package only; repository documentation, tests, scripts,
site files, legacy material, and `ui-gallery/` remain repository surfaces rather than
Home Assistant runtime payload. Custom-integration branding is packaged only as
`custom_components/humidity_intelligence/brand/icon.png` and `brand/logo.png` inside
that component. The repository-root `brand/` pair is the authoring source; the
component pair is its byte-identical release/install mirror, not a second authoring
location.

The branch-bound controller package workflow is an external validation-artifact lane,
not a second HI installation or release path. It may reproduce the exact tracked
component from `senyo888-patch-1` with a strict manifest and short retention, but it
cannot publish a GitHub Release, change HACS availability, install or deploy HI, define
rollback, or transfer HI runtime and release authority to the external controller.
The public repository, manifest, tag, GitHub Release, HACS package, and explicit
maintainer gates retain their existing roles.

## Documentation And Release Boundaries

When architecture, runtime behavior, security posture, release flow, contributor
expectations, documentation expectations, generated UI truth, or entity semantics
change, update the relevant tracked public docs in the same work.

Release truth must remain in tracked repository files, release notes, and Home
Assistant metadata. Private maintenance evidence and ignored local planning surfaces
may support review, while release approval, runtime behavior, and tracked validation
stay with the canonical repository surfaces.

HA Lab evidence is optional advisory operational evidence. Its presence, absence,
failure, blocked status, incomplete scenario coverage, or soak state may be recorded
as risk context, but none of those states is a promotion or release veto. Promotion,
tagging, GitHub Release publication, HACS publication, and Stable approval are decided
only by the canonical tracked validation, review, version-governance, CI, and explicit
maintainer gates documented for the release scope.
