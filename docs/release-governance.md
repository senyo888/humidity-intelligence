# Release Governance

Humidity Intelligence uses semantic versioning with explicit prerelease markers for
testing and validation branches.

## Canonical Version Model

- `2.0.12-beta.1`: initial testing build.
- `2.0.12-beta.2`: prior testing build with the Home Assistant 2026.9 child-device
  Area inheritance alignment.
- `2.0.12-beta.3`: prior testing build with the Manual override output-handover repair
  and bounded runtime-control diagnostics.
- `2.0.12-beta.4`: tested beta build with the same Manual handover behavior and a
  coherent plain-language reason-field explanation.
- `2.0.12-rc.1`: prior release-candidate build; metadata/docs/tests promotion of beta.4.
- `2.0.12`: stable version label. On `senyo888-patch-1`, `develop`, or `main`,
  stable metadata may be staged or promoted through the governed release path.
  Published release status comes from release tags, GitHub release publication, and
  maintainer approval.

The integration version in
`custom_components/humidity_intelligence/manifest.json` is the source of truth for the
installed Home Assistant package and integration metadata checks. When GitHub Releases
are used, HACS derives published version state from the GitHub Release/tag; that state
must remain aligned with the
`custom_components/humidity_intelligence/manifest.json` version contained in the
published GitHub Release/tag.

Published Stable is `2.0.11`, released on 2026-08-11 from exact commit
`0dd3e68ab9f35608641dc64efc4b2c4bfacb06ce`. Humidity Intelligence was subsequently
included in the HACS default integration repository. The current development candidate
uses `2.0.12` Stable metadata on the governed release-preparation lane. A branch or
merge containing that metadata is not by itself a publication. Public release status
comes from GitHub Releases and the version offered through HACS, while
release readiness must be established through public-safe validation summaries,
GitHub CI, the required review gates, and explicit maintainer approval. Local
operational evidence does not replace or become part of the tracked public
correctness contract.

The short-lived deterministic package produced by
`.github/workflows/controller-package.yml` is a separately bounded external-validation
artifact. Its presence, digest, or attestation does not create a tag, GitHub Release,
HACS publication, install, deployment, rollback, Stable state, or release approval.
See [Deterministic controller package artifact](controller-package-artifact.md) for
its exact source, retention, content, provenance, and rollback boundaries.

## Candidate Registration Evidence

Beta.4 validation used two complete Home Assistant restarts, waiting for startup to
finish and recording loaded identity and entity/service registration after each.
The second restart was part of the approved candidate-validation procedure even
though beta.4 registered after the first. A duplicate-domain rollback directory was
moved intact outside `custom_components` before activation. This evidence does not
establish that two restarts are inherently necessary for beta or Stable packages.

Keep package-on-disk evidence, each restart's loaded identity, final registration,
and subsequent runtime validation separate. In native diagnostics, use Home
Assistant's `custom_components.humidity_intelligence.version` and
`integration_manifest.version` as loader identity fields. HI's
`data.integration.integration_version` rereads the loaded module's on-disk manifest;
it is a disk-backed cross-check, not independent proof of loaded identity.
Confirm the config entry is loaded and runtime entities/services are registered.
The beta.4 component has 53 source files; a Lab controller may add its own provenance file. That deployment metadata
is not part of the Stable/HACS payload. Do not manufacture Lab provenance on Stable.

The beta.4-to-RC change is limited to manifest version, documentation, and tests;
runtime Python, services, translations, entities, and generated-card bytes remain
unchanged. The RC has a new package digest. Beta.4 Stable-instance validation and
any advisory Lab observation remain historical evidence for the exact beta.4 bytes,
not proof that RC or final Stable bytes were installed. This metadata-only promotion
does not require another Stable deployment for RC source promotion. Final-package
registration verification below remains separate. Broader runtime/UI changes require
fresh scope-appropriate evidence and separate deployment authority.

The RC-to-Stable preparation also changes only manifest identity, documentation,
and matching tests. Its package digest is distinct; the final-package registration evidence below
comes from a separate authorised installation, not from the metadata promotion.

The exact final v2.0.12 component package
`fcfa2c49f3d0e3282771aab575ab60e35aa31717b2565a77e792737ed557c278`
was installed over verified beta.4 and registered after one completed Home Assistant
restart. Both loader fields reported 2.0.12; the entry loaded, 95 mapped entities
were available, 13 services registered, diagnostics reported ok, and all 16 release
checks passed. The installed 53-file inventory remained exact after startup.
A second restart was not needed. This establishes the observed beta.4-to-Stable
update result, not a guarantee for every starting version or installation method.

Keep the two-restart beta procedure labelled as candidate validation. For Stable,
restart after installation, then verify loaded identity and registration. If setup
is incomplete, inspect errors and duplicate-domain discovery before deciding on
another restart. Keep recoverable predecessors outside `custom_components`; do not
infer an extra restart requirement from the on-disk version or restart in a loop.

## v2.0.11 Publication And v2.0.12 Maintenance Path

The v2.0.11 **Poetic Justice** tag and non-prerelease GitHub Release were published on
2026-08-11 from exact commit `0dd3e68ab9f35608641dc64efc4b2c4bfacb06ce`.
Post-release fixes must use a new version and must not rewrite, retag, or silently
replace that immutable release. HACS default-repository inclusion completed later and
does not alter the release tag or package bytes.

The v2.0.12 maintenance candidate is bounded to HACS/release-documentation coherence,
Home Assistant-local time-gate evaluation, lifecycle-safe timer countdown publication,
Home Assistant 2026.9 child-device Area inheritance in setup assistance, and the
existing `v205_release_check` service's accepted manifest range, plus the Manual
override output-handover repair and bounded runtime-control diagnostics. It changes
timer `remaining` publication cadence, the release-check compatibility claim, reviewed
setup-assist defaults, and Manual ownership/reconciliation/diagnostic truth. It
preserves entity IDs, primary `active`/`idle` states, service and configuration
schemas, deterministic lane order, configured output mappings, normal non-Manual AUTO
semantics, stored data, native diagnostics schema, and generated-card bytes. A full
Home Assistant restart is required after package installation. No Manual-card
re-export or stored-data/config/entity/dashboard migration is required. Before tag or
publication, the exact package still requires the hard gates below plus the v2.0.12
checklist.

The former v2.0.8 candidate moved through `senyo888-patch-1`, `develop`, and `main`
before publication. Stable metadata on a staging or review branch was not release
authority; the published tag and GitHub Release now provide the public release fact.
Senyo has maintainer-confirmed stable-instance testing for v2.0.8; that evidence is
recorded as maintainer confirmation unless independently verified in the same
validation packet. Stable-instance access or mutation requires explicit approval for
this lane.

For future promotion candidates, release readiness is established independently of
HA Lab. Each release-readiness record must state whether the scope-appropriate tracked
validation, generated-card evidence, Bella review, Aetherwing runtime/security review,
AetherCore governance review, Aetherbite release-language/visual review, maintainer
stable-instance confirmation where required, and maintainer promotion approval are
complete. HA Lab deploy, restart, playback, and soak evidence may be attached as
advisory context, but no HA Lab status is a required release field or gate.

## v2.0.8 Release Path Record

The v2.0.8 develop-review merge made `develop` the release-review source only. The
later `main` promotion, tag, and GitHub Release completed the publication path on
2026-07-06. The `develop` merge by itself did not publish or authorize the release.

The recorded develop-to-main promotion checklist was:

1. Confirm the develop-review PR merged to `develop` and GitHub CI is green.
2. Confirm CodeRabbit or human review comments have either been fixed or explicitly
   marked not applicable with a short reason.
3. Record sanitized HA Lab evidence in the PR body or a PR comment. Stage A package
   deploy evidence may prove full-package transport, backup creation, and source/remote
   hash agreement. Read-only Stage B evidence may prove current HA Lab reachability,
   runtime readiness, diagnostics/card counts, and scenario baseline. Without a
   separately approved Home Assistant restart or reload, Stage B does not prove that
   the just-copied package has been activated by Home Assistant.
4. Keep the generated-dashboard checkbox honest: if `refresh_ui`, dashboard paste,
   or browser refresh was not performed, leave that item unchecked and explain that
   users should re-export or refresh generated cards after install.
5. Preserve the hard release gates below as separate `main`, tag, and GitHub Release
   approval requirements.

That v2.0.8 checklist is retained as history. Its request to record HA Lab evidence
does not define a current or future promotion requirement.

For future releases, a `develop` merge must not be treated as tag, GitHub Release, or
`main` authority. Final promotion still requires maintainer approval, Bella coherence
review, Aetherwing runtime/release validation, AetherCore governance consistency
review, README/release approval, and the normal release sanity checks for the exact
branch being promoted.

For v2.0.9, the promotion PR must move from draft to ready only after the local,
house-agent, and explicit maintainer gates are complete. CodeRabbit must then finish
an exact-head review; actionable feedback must be fixed through a prerequisite PR or
explicitly recorded as not applicable before promotion can continue.

For the broadened v2.0.10 humidifier reconciliation, reason-presentation, and HACS
package-layout release, beta.7 established the final runtime candidate identity before
the stable `2.0.10` metadata bridge. Stable release-source metadata does not authorize
HA Lab/Stable-instance mutation, tag, GitHub Release, HACS publication, or deployment.
Beta.7 started a new exact-identity campaign with zero inherited credit. Beta evidence
must cover restored demand,
long-demand device stops, output
availability recovery, all supported output domains, isolation/gate interactions,
shared-output aggregation, bounded retry/fault behavior, generated V2 truth,
diagnostics redaction, the complete `hi.reason.v1` runtime-family matrix,
presenter-failure invariance, mixed-version fallback, line/size bounds, raw-ID and HTML
privacy checks, 52-file count/content parity with the approved brand-path relocation,
the required component-local `brand/icon.png` and `brand/logo.png` paths, direct
Hassfest/HACS validation, and unchanged deterministic ventilation ordering. Beta.1
through beta.6 evidence remain historical evidence for their exact commits and
cannot approve beta.7. The incomplete beta.2 soak is superseded rather than failed;
the separately deployed beta.3 soak is bound to beta.3, and beta.4 deployment and
soak evidence remain beta.4-only; beta.6 is invalidated for cadence failure. None
transfers sample numbering or acceptance to beta.7. HA Lab evidence is advisory;
whether it passes, fails, is blocked, is incomplete, or is not run cannot block
promotion or release. Stable-instance authority and release promotion remain separate
maintainer gates.

The durable beta.7 campaign `P22C-20260808T073919Z-9162eca3` completed with all 9/9
scheduled slots accepted, identity verified, and no failed or missed slots. That is
advisory exact-beta evidence. Stable-instance forward validation then identified a
diagnostics privacy gap: entity-ID-shaped mapping keys could survive value redaction.
The stable release source replaces mapped runtime entity rows with aggregate status
counts, removes mapping keys from the sanitized diagnostics export, and updates the
browser-local Inspector contract. This narrow support-surface change means the stable
package is intentionally not byte-identical to the soaked beta.7 package. Exact stable
HEAD therefore requires its own canonical privacy, diagnostics, Inspector, package,
version-governance, and full-suite validation; no beta soak credit is transferred to
the changed bytes. Control decisions, configuration, entity identity/state, generated
card YAML, and deterministic lane ordering remain unchanged. Attached Stable-instance
diagnostics remain private beta.7 evidence and must be summarized, not copied into
public repositories or PRs.

For v2.0.9 owned-artifact namespace validation, the release packet must separately
record:

- exact diagnostics, self-check, release-check, and generated-card paths, plus proof
  that card fragments are not treated as registered dashboard documents;
- admin rejection before work for external `dump_diagnostics`, `self_check`,
  `v205_release_check`, `dump_cards`, `view_cards`, `flash_lights`,
  `create_local_backup`, `list_saved_versions`, `pause_control`, `resume_control`,
  `create_dashboard`, and `purge_files`; deterministic guidance-only failure for
  `create_dashboard`; continuity of trusted
  setup/options/release-test exports and engine-owned visual alerts; and truthful
  cache-only startup refresh;
- single-entry and entry-qualified multi-entry filenames, exact file-only purge
  preview/removal ownership, dashboard retention, and retention of custom and legacy
  root artifacts;
- descriptor-relative no-follow atomic writer tests, including concurrent writes,
  directory creation/permissions, symlink, non-regular target, and directory
  substitution rejection;
- consumer migration and rollback evidence that does not treat stale root JSON/YAML
  as current output;
- a full Home Assistant restart after package installation before HA Lab runtime
  evidence. A config-entry reload may validate already-loaded options/regeneration
  behavior, but does not prove that newly installed Python or service schemas loaded.

## Branch Responsibilities

- `senyo888-patch-1`: staging lane for all manifest labels. It may carry beta, rc,
  or stable version metadata while work is being prepared and reviewed.
- `develop`: release-candidate or stable version metadata only. Beta labels stay on
  `senyo888-patch-1`.
- `main`: stable production version metadata only. No prerelease suffix is allowed.
- `vMAJOR.MINOR.PATCH`: release-verification branch for the exact matching stable
  manifest version only. For example, `v2.0.7` may carry `2.0.7`, but not
  `2.0.7-rc.1` or `2.0.8`.
- `dependabot/*`: automated dependency-maintenance branches may inherit the
  current stable manifest version from their base branch. Treat them as maintenance
  lanes only; release approval, tagging, and publication stay with the normal release
  gates.
- Short-lived development branches, including `Bella/*`, `codex/*`, `feature/*`,
  `fix/*`, `patch/*`, and `test/*`, must not carry stable manifest versions.

## Promotion Rules

1. Beta, rc, and stable labels may be staged on `senyo888-patch-1`.
2. Promotion to `develop` uses `MAJOR.MINOR.PATCH-rc.N` or stable
   `MAJOR.MINOR.PATCH` version metadata only.
3. Promotion to `main` uses stable `MAJOR.MINOR.PATCH` version metadata only.
4. Exact `vMAJOR.MINOR.PATCH` branches may be used for stable release-verification CI,
   but they do not replace the `main` release/tag gate.
5. A GitHub release is created only from a stable version on `main`.

## README Release-Note Structure

The README keeps the current candidate, current Published Stable, and immediately
preceding Published Stable summaries expanded. When a newer release displaces one of
those three positions, move the older summary into the collapsible `Previous Releases`
container. Retain that container as the canonical older-release structure so
successive releases follow the same visible chronology.

`CHANGELOG.md` owns the complete detailed release and legacy-migration history. The
README container may keep concise displaced summaries and must retain a direct link to
that tracked history.

## Hard Release Gates

No Humidity Intelligence version release, GitHub release, or release tag may be created
until all of these gates are satisfied:

- Bella verification has confirmed source-of-truth alignment, UI truth consistency,
  deterministic release boundaries, and README/release-note coherence.
- AetherCore verification has confirmed governance coherence, role-boundary integrity,
  proposal/release-process consistency, and local/public boundary safety. AetherCore's
  role here is governance verification; runtime authority and release approval stay
  with the established maintainers and gates.
- Release sanity validation has passed for the change scope, including version
  governance, HACS/package metadata checks, and the relevant Home Assistant runtime,
  direct sanity, service, or generated-card checks.
- The `humidity-intelligence-maintenance` companion has been updated with advisory
  release-gate evidence, blocker notes, or an explicit no-op maintenance status for
  the staging promotion. This records maintenance evidence; promotion approval and
  canonical HI truth stay in the canonical repo.
- Wiki update status is recorded as `updated`, `no-op`, or `blocked` for any release
  that changes support flow, diagnostics, generated dashboards, HACS/update guidance,
  configuration behavior, services, entity semantics, or release documentation. The
  Wiki remains a public support manual; runtime and release truth stay in the
  repository source and release documentation.
- The README has maintainer approval before release tagging.

HA Lab is deliberately absent from the hard-gate list. When HA Lab evidence exists,
its status may be recorded as optional operational context. A pass, failure, blocked
run, incomplete playback/soak, or `not run` status is not a missing gate and cannot
block promotion, tagging, GitHub Release or HACS publication, or Stable approval.

If any gate is missing for the version being prepared, the release state is `not ready`,
even when the manifest version already carries a stable number on `senyo888-patch-1`,
`develop`, or `main`.

## v2.0.12 Release Checklist

Use this checklist for the exact v2.0.12 candidate. Keep local validation, Home
Assistant activation, promotion, tag, GitHub Release, HACS availability observation,
and post-release observation as separate evidence states.

- [ ] Exact branch, commit, tree, manifest version, component file count, and package
  hash are recorded.
- [ ] `v205_release_check` accepts v2.0.12 beta/rc/stable and still rejects v2.0.13;
  the generated report for the installed candidate is reviewed.
- [ ] Native diagnostics report the expected installed version and schema `1`, and
  redaction plus aggregate mapped-entity privacy tests pass.
- [ ] Home Assistant local time differs deliberately from the host/container clock;
  same-day, inclusive boundary, overnight, spring-forward, and both autumn-fold cases
  pass.
- [ ] Timer start, replacement, cancel, exact expiry, removal, platform unload,
  config-entry/options reload, restart-to-idle, generation invalidation, maximum
  60-second publication cadence, and no-late-write behavior pass.
- [ ] Pause-timer `active` to `active` countdown events cause no full engine evaluation;
  `active` to `idle` still evaluates immediately.
- [ ] CO emergency precedence, canonical lane order, humidifier independence, output
  ownership, unavailable/degraded handling, and privacy boundaries pass.
- [ ] Generated-card, gallery-card, and Stability source bytes match the protected
  baseline exactly; Manual-card re-export status is `not required`.
- [ ] Full tracked tests, compile/import checks, HACS Action, Hassfest, package layout,
  branding, version governance, docs/link checks, and public secret/privacy scans pass.
- [ ] README, CHANGELOG, Pages source, service descriptions, support diagnostics
  guidance, issue forms, and Wiki status are aligned; Content Harmony completed from
  a clean trusted plugin source.
- [ ] Runtime impact, entity/service contract changes, no-migration result, full-restart
  requirement, rollback package, and observation plan are explicit.
- [ ] Bella, Aetherwing, AetherCore, release-sanity, and final maintainer README/release
  approval gates are complete for the exact final head.

## Enforcement

`scripts/check_version_governance.py` validates the branch/version contract locally and
in CI. It rejects:

- prerelease versions on `main`
- beta versions on `develop`
- stable versions on short-lived testing branches
- prerelease or mismatched stable versions on `vMAJOR.MINOR.PATCH` branches
- stable versions on unapproved branches outside `senyo888-patch-1`, `develop`, and
  `main`, exact matching `vMAJOR.MINOR.PATCH` release-verification branches, and
  automated `dependabot/*` dependency-maintenance branches

This guard protects the release boundary. Runtime logic, entity semantics, generated
dashboards, and Home Assistant services stay governed by the integration source.

## HACS Integration Preflight

HACS Integration Preflight is an optional but recommended local/VS Code release-perimeter
check before promotion. Run it from the release-source checkout or a worktree after
implementation sanity and before the final release readiness review.

Use it for:

- HACS/install metadata validation
- release packaging sanity
- `custom_components/humidity_intelligence/manifest.json`, `hacs.json`, branding,
  workflow, and repository hygiene support

Do not treat it as a replacement for pytest, direct runtime/card sanity, Home Assistant
runtime validation, Bella coherence review, Aetherwing validation, or version governance.
Preflight findings are packaging/readiness findings only; they must not imply runtime
behavior, service, diagnostics, UI generation, or configuration-flow changes unless a
separate implementation patch is explicitly approved.

## HA Lab Operational Beta Validation

HA Lab is admitted into the normal beta-validation workflow as Operational Beta
Validation Infrastructure. Use it after beta deploys to collect practical runtime
evidence from an isolated Home Assistant lab instance while preserving repository and
review authority.

Optional HA Lab evidence for beta-readiness review may include:

- package deploy identity: source branch/worktree, commit, manifest version, target
  classification, and clean/dirty source state;
- Stage A full-package deploy result, including source/remote comparison and rollback
  backup evidence;
- runtime activation or restart approval evidence, clearly separated from Stage A
  deploy authority;
- read-only soak, diagnostics, service-domain, startup/log, and runtime entity checks;
- Stage 3 six-sensor runtime-readiness status where the beta touches air-quality or
  aggregate telemetry truth;
- generated-card and entity-map sanity findings when UI truth or card exports are in
  scope;
- rollback boundary and whether any HA Lab mutation occurred.

HA Lab evidence remains non-binding. It is not release authority, runtime authority,
stable Home Assistant authority, or a substitute for Bella coherence review,
Aetherwing runtime/risk validation, AetherCore governance consistency review,
release-candidate validation, or maintainer approval.

HA Lab is therefore never a promotion or release blocker. A failed, blocked,
incomplete, unavailable, or omitted HA Lab run may be reported as advisory risk
context, but it cannot turn an otherwise satisfied canonical release decision into
`not ready`.
