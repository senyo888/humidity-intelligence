![Humidity Intelligence changelog header](assets/change-log.png)

# Changelog

All notable changes to Humidity Intelligence will be documented in this file.

This project follows a practical changelog format for Home Assistant and HACS users. Add new entries under a fresh `Unreleased` section before publishing a future release.

## Unreleased — UI harmonisation after beta.6

- Preserves V2 mobile/tablet geometry and actions while adding restrained neutral
  depth and a small bottom-left rendered-UI-revision indicator.
- Distinguishes matching, explicitly superseded, differing and unverified revisions
  using additive Diagnostics metadata, independently of integration version.
  Export/download success and browser refresh are not proof of YAML replacement.
- Corrects unavailable System/Manual labels, missing or malformed humidity values,
  frontend comfort action advice, and positional names in native Outputs.
- Keeps control engine, lane priority, entity primary states, service schemas,
  shared Outputs expansion and the accepted Stability presentation unchanged.
- Activation requires the complete package and a restart for Python metadata,
  then fresh export and full replacement of saved V2 cards. Restart resets
  in-memory Stability history. No configuration migration or new frontend resource.
  [Revision contract and rollback](docs/ui-revision-status.md).

- Preserves the revision footer comments while generating configured native and
  adaptive Outputs, preventing fallback from dropping the observation summary.
- Declares the existing optional HTTP frontend dependency for Hassfest and setup
  ordering when HTTP is configured. HTTP remains optional; runtime control and
  entity semantics are unchanged.

These changes do not assign a new package version or claim deployment/publication.

Validation maintenance also replaces stale beta-version and whole-package-count
assertions with manifest identity and exact tracked branding checks. Real-selector
tests initialize Home Assistant before its validation-library compatibility layer;
native tests run separately from lightweight HA scaffolds. These repairs change
test setup and expectations, with no additional product behavior change.

## Unreleased — v2.1.0-beta.6

Unpublished development candidate based on beta.5 (`f1d6f48`). Published Stable
remains v2.0.12; no tag or HACS publication is implied.

- Separates neutral configured meanings such as Filter replacement from active
  Filter replacement suggested alerts. Faults remain explicitly reported.
- Clarifies monitoring coverage, source readings and detail-window labels while
  preserving exact rules, counts, severity, unavailable states and isolation truth.
- Uses task-oriented native configuration labels and explains which changes are
  staged, retained by Back, discarded locally, or persisted by Save changes.
- Returns Keep editing to the originating sensor form after the flow's close
  confirmation, retaining its draft without saving the options transaction.
- Preserves configuration keys, defaults, strict comparisons, lane ordering, existing
  entity semantics, native output controls and backend ownership of UI meaning.

- Aligns current README, output-monitoring instructions and website candidate copy
  with beta.6 labels and the final Save changes boundary. Historical release notes
  retain their original wording.

### Upgrade from beta.5

Install the complete package and restart Home Assistant, then refresh the frontend
resource and regenerate saved mobile/tablet cards. Restart resets in-memory
Stability collection. No entity or configuration migration is required. Rollback
restores the complete beta.5 package and matching cards/resources.

## v2.1.0-beta.5 — Earlier unpublished candidate

Unpublished development candidate based on beta.4 (`a3f135e`). Published Stable
remains v2.0.12; no tag or HACS publication is implied.

- Uses `mdi:hvac` for shared Outputs identity while retaining individual device icons.
- Reduces the Outputs expansion to a compact backend-authored summary, up to two
  conditions, exact totals, explicit overflow and important monitoring context.
- Places complete evidence and preserved native controls in one on-demand window.
  Missing observation keeps controls available and clears stale evidence; older
  payloads retain the full fallback presentation.
- Preserves control logic, lane ordering, thresholds, mappings and entity semantics.
- Validated with focused backend, native HA API, export and frontend DOM tests;
  actual target UI acceptance is recorded separately.

### Upgrade from beta.4

Install the complete package and restart Home Assistant, then refresh the frontend
resource and regenerate saved mobile/tablet cards. Restart resets in-memory
Stability collection. No entity or configuration migration is required. Rollback
restores the complete beta.4 package and matching cards/resources.

## v2.1.0-beta.4 — Earlier unpublished candidate

Unpublished development candidate based on beta.3 (`345a840`). Published Stable
remains v2.0.12. No release tag or HACS publication is implied.

- Integrates optional, read-only output observation with structured exact-rule
  confirmations, identity-bound recovery, per-association context-only retirement,
  and explicit companion mapping import. It defaults disabled.
- Adds an optional packaged adaptive Outputs card, backend-authored attention and
  coverage, and normal mobile/tablet exports with complete native output controls.
- Preserves beta.3's Stability implementation, drift progress, badge summaries,
  history panels, room colours, lane decisions and existing entity semantics.
- Handles initial setup and unchanged HA state reports without false missing-output
  claims; event timestamps prevent delayed older reports from clearing newer
  registry quarantine.
- Uses a neutral devices icon for shared Outputs and domain-specific row icons;
  fans no longer represent switches, humidifiers or lights. Native V2 and gallery
  headers follow the same convention. The dark Outputs surface owns readable text
  colours locally, including native child rows, when HA uses a light theme.
- Accepts Home Assistant read-only configuration mappings when generating adaptive
  cards; a targeted regression protects the live options/export boundary.
- Bounds observations and identity custody, excludes detailed payloads from Recorder,
  redacts mapping identities in diagnostics, and isolates optional setup failures.
- Validated locally with pure/regression suites, real HA 2026.5.1/2026.9.3 APIs and
  synthetic browser cases. Target deployment evidence remains separately recorded.

### Upgrade from beta.3

Install the complete package and restart Home Assistant to load the new Python
modules. Restart resets in-memory Stability collection; this is a new observation
period, not continuation of the beta.3 soak. No configuration/entity migration is
required for existing HI settings. To use the optional UI, enable observation,
register its module resource, regenerate cards and replace saved Manual-card YAML.
Existing companion users explicitly import reviewed bindings and remove the old
competing frontend resource. See [setup and rollback](docs/output-observation.md).
Rollback restores the complete beta.3 package and prior cards/options/resources.

## v2.1.0-beta.3 — Earlier unpublished candidate

Development candidate, prepared from all changes since the beta.2 version commit
`76285b0`, through `4f86e66`. Published Stable remains v2.0.12; this beta remains
an unpublished candidate.

### V2 badge summaries

- Mould and condensation history give source rooms individual colours with matching
  labelled legends, retained across histories and ranges within the page session.
- Humidity, Condensation, Mould, Current Air Control, Ready, Zone 1, Zone 2 and AQ
  open short explanations before history. Summaries
  identify the actual mapped history source and retain unavailable states.
- Ready, Zone 1, Zone 2 and AQ use compact text-only badges with their existing
  active and alert emphasis. Stability details put the snapshot notice below the
  content and keep Close within a viewport bounded by device safe areas.
  V2 dialogs use compact circular X controls with accessible Close labels and
  comfortable touch targets; explanations use positive, direct language.
  History navigation keeps its background transparent so scrolling content remains
  visible between Back and Close.
- Badge explanations and history messages use plain, friendly language. Recorded
  changes and value selectors have clearer labels, and history availability messages
  offer useful next steps while retaining source status and safety context.
- V2 Mobile and V2 Tablet share the changes. V1 is unchanged. Refresh exports and
  replace pasted Manual cards; this template-only change requires no Python restart
  or configuration/data migration. Runtime control and entity semantics are unchanged.
- Condensation and Mould show recorded risk levels and source rooms on separate
  timelines. Current Air Control shows operating-mode changes and separately
  timestamped recorded reasons. Each source retains its own timing; operating mode
  represents controller state.
- AQ shows separate recorded aggregate charts for available IAQ, PM2.5, VOC and CO
  sources. Missing units are stated, unavailable values break traces, and recorded
  unit changes are kept separate. Values follow the recorded backend aggregates.
- History loads on demand for 24 hours or seven days, with Back, Close and native
  entity-details access. Missing, failed and bounded partial results are explicit;
  history availability continues to depend on Home Assistant Recorder and access.
  Recorder retention, backend control and dashboard refresh behavior are preserved.

### Packaging and validation

- Adds the canonical shared history renderer and deterministic embed-sync tooling
  for both V2 templates and their gallery mirrors. The complete controller package
  contract now includes the renderer (56 files).
- Extends automated validation for summary interactions, recorded history, generated
  entity mappings, packaging, drift and Stability details. Source-room colours have
  regression coverage for matching legends and identity across embedded histories.

### Upgrade from beta.2

- Install the complete beta.3 package when applying this candidate, then run
  `humidity_intelligence.refresh_ui` and export fresh V2 cards with `dump_cards` or
  `view_cards`. Replace each saved Manual card with its complete fresh export and
  refresh the dashboard client to load it.
- The beta.2-to-beta.3 changes are UI assets, packaging checks and documentation;
  backend Python, entity semantics, lane priority and stored data are preserved.
  UI activation uses refreshed exports while the existing runtime and Stability
  collection continue. Home Assistant loads the new manifest identity on its next
  full restart; restarting resets the in-memory Stability collection. Installing
  from an earlier Python baseline requires the cumulative package restart.
- V1 retains its beta.2 behaviour. Dashboard refresh-loading improvements remain
  deferred. Rollback restores the earlier package and saved dashboard cards together.
- The implemented UI through `4f86e66` received Lab checks before this version bump;
  those observations identify the tested UI source. Beta.3 package/loaded-version
  evidence is recorded separately when installed and activated.

## v2.1.0-beta.2 — Earlier unpublished candidate

Version introduced at `76285b0`; subsequent V2 summary and history work is collected
under beta.3 above. Published Stable remains v2.0.12.

### Seven-day drift badge

- Shows backend-derived **Baseline · N%** collection progress before usable drift
  data is available. Missing or invalid coverage remains unknown rather than implying progress.
- Opens a concise explanation on tap, with **View history** opening native Home
  Assistant history for the same drift entity and **Close** dismissing details.
- Preserves drift calculations, Stability scoring, control decisions and entity
  semantics. Regenerate exports and replace pasted Manual cards to receive the UI;
  no configuration or stored-data migration is required.

## v2.1.0-beta.1 — Earlier unpublished candidate

Committed and pushed through `144570b` on `senyo888-patch-1`, with earlier
collection work through `07dc87a`. This candidate remains unpublished: no tag, GitHub Release or HACS
offering. Published Stable remains v2.0.12.

### Accepted Stability Score integration

- Corrects early baseline progress with one clockwise LED per valid sample. Strict
  count/ratio checks keep malformed evidence unlit; the origin clears as collection
  begins. Scored movement and the separate red history track retain their behavior.
- Uses the whole badge action to open a detached details dialog with a visible Close
  button, snapshot label, navigation cleanup and native Diagnostics fallback.
  Readable Diagnostics includes baseline and failure evidence. Refresh exports and
  replace pasted cards; updated Python requires restart, which clears baseline history.
  No configuration migration or control-lane changes are required.

- Retains known failed or missed scheduled sample buckets in memory for the rolling
  72-hour window. A separate thin red track shows that history in non-scored
  collection/evidence states; details give the exact count when marks overlap.
  Backend-owned history is bounded to 432 unique UTC slots, expires with the window,
  and never infers pre-start or offline failures. Successful recovery of a bucket
  clears its failure mark. Restart/reload clears this history with the baseline.
  The Python update requires a restart; no configuration or stored-data migration
  is required. Scoring, score-movement LEDs and control decisions are unchanged.
- Shows collection progress as a clockwise LED fill from the top, using backend
  progress toward the minimum valid-sample requirement. Collection details now show baseline
  progress against that minimum (303), instead of the 432-bucket rolling capacity,
  and explain collection separately from score movement. Outside collection the
  tally is explicitly labelled rolling-window coverage. Incomplete progress never
  fills the whole ring; backend score and evidence transitions remain immediate.
  This presentation-only change preserves scoring, control and entity semantics.
  Regenerate exports and replace pasted Manual cards to receive the updated UI;
  no configuration or stored-data migration is required.
- Restores the accepted shared Diagnostics builder connection so the live sensor
  receives collection progress and scores. Regression checks use the real builder.
- Classifies the isolated scenario tooling for controller packaging and updates
  package-count checks for the two added helpers. V2.1.0 artifacts use the explicit
  `hi-package-public-v21-conventional-1` contract; the V2.0 contract stays unchanged.
  Downstream controller acceptance of the new contract is not yet verified.

- Rejects malformed or out-of-range displayed scores without numeric coercion across
  all four cards. Invalid payloads show a dash, neutral halo and `NO SCORE`, without
  stale healthy text or movement. Valid scores, including zero, remain unchanged.

- Integrates the accepted observational Stability backend, ten-minute UTC sampler,
  bounded diagnostics and readable explanation. Six components use a 72-hour window;
  eligibility needs 303 of 432 valid buckets plus consecutive/balance evidence.
  Configured AQ evidence, penalties, caps and unavailable states stay backend-owned.
- Replaces the historical preview in generated V2 Mobile/Tablet and default gallery
  cards with the accepted score, retained full-circle movement, independent LED
  colours, Partial/reduced-motion treatment and Recent trend details; the later
  correction above uses a detached native dialog with native Diagnostics fallback.
- Preserves control entity IDs/native states, Manual handover, CO-first ordering and
  independent humidifier authority. No configuration or stored-data migration is
  required. Python installation requires a full restart; regenerate exports, replace
  pasted Manual cards and refresh frontend caches. Restart/reload resets in-memory
  score history and movement. Package and card rollback are separate operations.
- Adds the [accepted contract](docs/stability-score-accepted-baseline.md) and
  [synthetic scenario/validation guide](docs/stability-testing.md). Details use a
  native dialog with native more-info fallback. This work is unreleased; earlier preview entries
  below remain historical release truth.

- Extends the existing `v205_release_check` compatibility boundary to v2.1
  beta/rc/stable while retaining v2.0.5–v2.0.12 support. The service name, schema,
  admin requirement, report path and runtime/device-read-only purpose are unchanged.

## v2.0.12 — Published Stable (2026-09-09)

Published as a non-prerelease [GitHub Release](https://github.com/senyo888/humidity-intelligence/releases/tag/v2.0.12).
The exact final package registered after one completed restart in the observed
beta.4-to-Stable update; historical beta validation's two restarts do not establish
an installation rule. No configuration/data migration or Manual-card re-export is
required for v2.0.12; its generated-card bytes are unchanged.

### Historical v2.0.12 candidate preparation

The entries below retain their original candidate scope and evidence limitations;
references to unpublished candidates are historical, not current publication status.

![Humidity Intelligence v2.0.12 release header celebrating repository-level HACS inclusion](assets/release_banner/v2.0.12_release.png)

- Advanced the development identity to `2.0.12-rc.1` for the forward promotion from
  `senyo888-patch-1` to `develop`, then `main`. The beta.4-to-RC delta changes only
  manifest identity, release documentation, and associated tests. Beta.4 live
  validation remains bound to its tested package; the RC is a new package digest.
- Recorded the two completed restarts used for beta.4 candidate validation, with
  separate loaded-identity and registration checks. This is not an established
  installation rule for final v2.0.12. Verify the final package before stating such
  a rule in Stable release notes or update instructions. Keep rollback copies
  outside `custom_components` so duplicate domains cannot interfere with discovery.
- Humanised the Manual reason field into one coherent explanation of the active mode,
  the ordinary outputs HI will leave unchanged, who remains in control, how to return
  to AUTO, and the continuing CO emergency exception. This is a presentation-only
  change; Manual authority, output behavior, lane order, and safety behavior are
  unchanged.
- Advanced the development identity to `2.0.12-beta.4` so the humanised Manual reason
  wording has a distinct package identity for Home Assistant validation. Earlier
  beta.3 validation remains historical evidence for its exact package and does not
  transfer to beta.4.
- Fixed Manual override so it performs a complete non-CO output handover: pending
  alert, AQ, and humidifier retry work is neutralized; existing fan, switch, and
  humidifier states are left unchanged; raw runtime mode/reason and diagnostics report
  Manual truth; and humidifier observation uses additive `manual_hold` reconciliation
  without claiming an HI command. Native diagnostics, the recorder-safe diagnostics
  entity, support dumps, and the release check expose bounded runtime-control truth.
  The shared privacy-safe runtime-control helper increases the tracked installable
  component payload from 52 files to 53; package paths otherwise remain unchanged.
  CO emergency still forces only its configured
  ventilation outputs to 100%, and normal AUTO persistence resumes after Manual is
  turned off. This does not add temporary manual operation while AUTO remains enabled.
- Advanced the development identity to `2.0.12-beta.3` so the Manual override repair
  and its runtime-control diagnostics have a distinct package identity for Home
  Assistant validation. Earlier beta.2 evidence remains historical evidence for its
  exact package and does not transfer to beta.3.
- Advanced development identity to `2.0.12-beta.2` so the Home Assistant 2026.9
  alignment remains distinct from the earlier beta.1 testing bytes. This candidate
  is not a published GitHub Release or an HACS-offered v2.0.12 package.
- Recorded completed inclusion in the HACS default integration repository, added the
  official My Home Assistant repository button, and replaced normal first-install
  custom-repository instructions with the default-store search and download path.
  Historical V1-to-V2 repository-type migration guidance remains available for users
  who need it.
- Corrected the configured time gate to use Home Assistant local time instead of the
  host or container wall clock. Same-day, inclusive boundary, overnight, spring-
  forward, and both autumn-fold cases are covered without changing lane order, CO
  priority, output ownership, or gate actions.
- Replaced `HITimerSensor` raw sleeper tasks with lifecycle-owned Home Assistant
  one-shot callbacks, aware UTC duration arithmetic, generation invalidation, exact
  expiry, and bounded `remaining` publication no more than once per minute. Timer
  unique IDs, entity IDs, `active`/`idle` states, and reset-to-idle restart behavior
  remain unchanged.
- Prevented pause-timer `active` to `active` countdown-only state events from starting
  a full engine cycle, while retaining immediate evaluation for primary-state changes.
- Extended the backward-compatible `v205_release_check` manifest range and result
  wording through v2.0.12 beta/rc/stable. The service name, schema, admin gate, owned
  report path, runtime/device-read-only side effects, and physical-output limitation
  remain unchanged.
- Kept native diagnostics schema `1`, redaction, aggregate mapped-entity privacy, and
  Inspector compatibility unchanged. The installed integration version continues to
  come from `manifest.json` after the updated package is loaded.
- Aligned setup assistance with Home Assistant 2026.9 child-device Area inheritance:
  it now uses the supported Area Registry lookup and inherits a parent device's Area
  when the child has no Area of its own. Missing, broken, nested, cyclic, or incomplete
  parent metadata produces no inherited Area suggestion, and manual HI mapping remains
  authoritative.
- Added the v2.0.12 release header and aligned README, Pages source, release/user
  checklists, support diagnostics guidance, and issue forms with current HACS and
  v2.0.11 publication truth. Generated-card, gallery-card, and Stability bytes
  remain unchanged.
- A full Home Assistant restart is required after installing changed Python and
  service code. No config-entry, entity-registry, stored-data, threshold, lane-order,
  service-name, or dashboard migration is required, and v2.0.12 requires no Manual-
  card re-export.
- Added a `senyo888-patch-1`-only deterministic package workflow for the separately
  governed HI Lab Controller. It builds from exact tracked Git blobs, emits a strict
  file/hash manifest, reproduces the package before upload, retains the immutable
  Actions artifact for seven days, and attaches GitHub provenance to the manifest.
  This adds no Humidity Intelligence runtime, entity, service, dashboard, HACS,
  version, installation, deployment, rollback, tag, release, or Stable behavior.

## 2.0.11 - 2026-08-11

![Humidity Intelligence v2.0.11 Poetic Justice release banner](assets/release_banner/v2.0.11_release.png)

[![Latest Release](https://img.shields.io/github/v/release/senyo888/Humidity-Intelligence?display_name=tag&sort=semver)](https://github.com/senyo888/Humidity-Intelligence/releases) [![Project Site](https://img.shields.io/badge/Project%20Site-GitHub%20Pages-5aa8d6)](https://senyo888.github.io/humidity-intelligence/) [![License](https://img.shields.io/github/license/senyo888/Humidity-Intelligence)](LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/senyo888) [![Star Humidity Intelligence](https://img.shields.io/badge/Star%20%2F%20Support-Humidity%20Intelligence-2ea44f?logo=github&logoColor=white)](https://github.com/senyo888/humidity-intelligence)

- Published **Poetic Justice**, stable identity `2.0.11`, on 11 August 2026 as a
  non-prerelease GitHub Release and immutable tag from exact commit
  `0dd3e68ab9f35608641dc64efc4b2c4bfacb06ce`. The release contains the bounded
  post-v2.0.10 Stability badge correction and extends the existing
  `v205_release_check` range through v2.0.11 beta/rc/stable. Humidity Intelligence was
  subsequently included in the HACS default integration repository; that distribution
  milestone does not rewrite the v2.0.11 tag or package bytes.
- Restored the established Stability preview badge treatment in generated V2 cards:
  the name's `grid-area` is now the quoted string `'n'`, preventing Home Assistant's
  YAML parser from coercing it to Boolean `false` and creating an implicit second
  button-card grid column. This returns the fixed-width 82px circle and its
  `Stability Score` wording to their shared centred layout without widening or
  stretching the badge. The original seven LEDs and neutral-white six-second breathing
  shimmer remain active when future v2.1 diagnostics are absent. The badge reads
  `2.1 / PREVIEW` through a dedicated preview class, so the familiar visual treatment
  does not claim that a completed backend score exists. An explicitly present but
  empty or malformed nested `stability_score` payload degrades to `NO SCORE`;
  collecting and unavailable diagnostics remain explicit, while real backend score and
  classification values keep their existing gauge colours. Reduced-motion preferences
  disable the shimmer.
  This is a presentation-only correction: Stability remains passive, no score is
  calculated in the card, and runtime decisions, lanes, outputs, entities,
  configuration, and services are unchanged. Existing Manual cards require a fresh
  export, complete YAML replacement, and browser/app refresh.

## 2.0.10 - 2026-08-10

![Humidity Intelligence v2.0.10 release banner](assets/release_banner/v2.0.10_release.png)

[![Latest Release](https://img.shields.io/github/v/release/senyo888/Humidity-Intelligence?display_name=tag&sort=semver)](https://github.com/senyo888/Humidity-Intelligence/releases) [![Project Site](https://img.shields.io/badge/Project%20Site-GitHub%20Pages-5aa8d6)](https://senyo888.github.io/humidity-intelligence/) [![License](https://img.shields.io/github/license/senyo888/Humidity-Intelligence)](LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/senyo888) [![Star Humidity Intelligence](https://img.shields.io/badge/Star%20%2F%20Support-Humidity%20Intelligence-2ea44f?logo=github&logoColor=white)](https://github.com/senyo888/humidity-intelligence)

- Fixed a diagnostics privacy gap found during Stable-instance forward validation:
  native diagnostics now report mapped runtime entities only as aggregate availability
  counts, and `dump_diagnostics` no longer emits mapping keys. Entity-ID-shaped map
  keys and mapped entity values are not retained in either sanitized support export.
  The HI Support Bundle Inspector accepts the privacy-safe aggregate schema. This
  changes diagnostics presentation only; control decisions, mappings, entities, and
  outputs are unchanged.
- Clarified the project-wide release boundary: HA Lab deploy, restart, playback, and
  soak evidence is optional advisory context. A pass, failure, blocked run,
  incomplete matrix/soak, or absence of Lab evidence is not a promotion, PR, tag,
  GitHub Release, HACS publication, or Stable-release blocker. Canonical validation,
  review, CI, version governance, and explicit maintainer gates remain unchanged.
- Advanced the implementation identity to `2.0.10-beta.7`. Backend-authored reason
  copy now reads as natural, complete household sentences while preserving one
  `hi.reason.v1` role and truth per line. Cause and action remain separate; every
  retained action is independently scoped so bounded compaction cannot leave an
  orphaned conclusion. Humidifier demand wording names the adjusted profile demand
  start and recovery-off thresholds without misreporting them as the displayed target
  floor, and observed Home Assistant output state retains the physical-moisture
  limitation. The schema, code vocabulary/meanings, argument semantics, technical
  reason state, lane ordering, thresholds, gates, service dispatch, and entity
  semantics are unchanged; bounded presentation line grouping may split differently.
- The beta.7 candidate supersedes beta.5's deliberate second humidifier row: V2
  Mobile, V2 Tablet, and
  both canonical gallery templates now present ventilation and humidifier chips in
  one horizontally scrollable Current Air Control row. `On` and `Requested` are cyan;
  `Idle`, `Retrying`, `Stopping`, and `Isolated` are amber; `Fault` and `Degraded` are
  red; and `Unknown` is grey. Existing Manual cards require
  a fresh export and full YAML
  replacement. A packaged Python update requires a full Home Assistant restart; no
  config-entry, registry, stored-data, service, threshold, or lane migration is
  required. Beta.6's invalidated cadence transfers no validation or soak credit.
- Advanced the implementation identity to `2.0.10-beta.6` with backend-owned
  reason language harmonisation after live
  review found that the inherited AQ-plus-humidifier explanation still read as
  joined diagnostic records. AQ observation and selected action remain adjacent
  but retain separate `observed`/`why` and `selected`/`action` contract lines:
  `Downstairs IAQ is 34, at or below the response point of 60.` followed by
  `For Downstairs, HI selected 66% for ...`. Concurrent humidifier truth now
  continues naturally with `Separately, Downstairs needs humidification ...`,
  while every split line remains independently scoped by its resolved level. The
  retained pair preserves thresholds and reconciliation truth, and an observed-on
  claim keeps its physical-output limitation. Retry, isolation,
  unavailable, and fault copy replaces internal terms such as `bounded retry`,
  `output mismatch`, and `service calls are suppressed` with calm direct language.
  The `hi.reason.v1` schema, line codes, roles, scopes, truth values, arguments,
  maximum bounds, technical reason state, lane selection, dispatch, and entity
  semantics are unchanged. Presentation ordering is intentionally hardened: AQ levels
  are explicitly ordered Downstairs
  then Upstairs even if input details arrive reversed. Long multibyte friendly-output
  summaries fall back to a generic count, and the existing stable retention priorities
  compact any remaining UTF-8-heavy explanation before the 4 KiB contract boundary,
  preserving retained-line semantics and original order instead of dropping
  `display_reason`. Existing V2 and Manual cards consume the revised backend
  attribute automatically; no card replacement, frontend-cache clear, configuration
  migration, or entity migration is required. A packaged Python update requires the
  normal Home Assistant restart. The committed beta.5 identity and its evidence must
  not be overwritten or transferred. Beta.6 is a fresh local identity; push,
  deployment, playback, and soak remain separate gates.
- Advanced the implementation identity to `2.0.10-beta.5` and tightened the V2
  Current Air Control chip strip for mobile readability. Humidity
  Danger chips now stop after the resolved alert type, room, and zone; measurements
  and thresholds remain intact in backend alert telemetry and the plain-language
  explanation. Other alert contexts are not shortened.
  Humidifier chips now read `Downstairs Humidifier` or `Upstairs Humidifier`, and the
  Home Assistant-observed `output_on` state is presented as `On`. When Zone 1 or Zone
  2 and a humidifier lane are active together, humidifier telemetry moves to a second
  row so the independent control families remain visually distinct. V2
  Mobile, V2 Tablet, and canonical gallery cards stay aligned. Existing pasted Manual
  cards must be refreshed/exported and re-copied to receive this presentation-only
  change. There is no Python runtime, entity/config migration, lane-order, or
  output-behaviour change; a future versioned HACS package should still follow the
  normal full-restart installation path.
- Advanced the implementation identity to `2.0.10-beta.4` and completed the
  backend-owned alert-lane wording catalogue. Zone and air-quality headlines now
  explicitly say `response lane selected`; alert headlines use `High humidity alert
  lane selected`, `Mould alert lane selected`, or `Condensation alert lane selected`,
  with the first explanation sentence stating the selected Danger or Risk alert.
  Visible mould prose translates internal ordinal levels into Normal, Watch, Risk,
  or Danger ranges while bounded numeric values remain available in structured
  `display_reason` arguments for deterministic traceability and future localisation.
  Friendly room/zone/output names remain resolved, sanitized labels with generic
  fallbacks, and raw entity IDs remain prohibited. This is presentation-only: lane
  priority, thresholds, output selection, and service dispatch are unchanged. Entity
  identity, state, schema, and structured truth semantics are unchanged; backend
  presentation text changes intentionally. Card YAML, configuration, and stored data
  are unchanged. The humidity profile label is retained only as a private presentation
  fact from the exact profile used to calculate that alert threshold, so no public
  alert-telemetry key is added and the label cannot drift from its threshold. A full
  Home Assistant restart is required to load beta.4 Python;
  no card replacement, frontend-cache refresh, or migration is required.
- Moved the exact 52-file installable integration payload into the conventional
  `custom_components/humidity_intelligence/` layout and removed HACS
  `content_in_root`. HACS, Hassfest, release checks, tests, scripts, and documentation
  now validate the tracked package directly instead of constructing a temporary CI
  package. The existing component icon and logo now live under the supported local
  `brand/` subdirectory, as a byte-identical install mirror of the repository brand
  source, so HACS and Home Assistant can discover them without increasing the package
  count. The integration installation root is unchanged, although those two asset
  paths move. This brand-only correction adds no restart or frontend-cache requirement;
  a full Home Assistant restart remains required for the cumulative beta.3 code update.
  No config, entity, or stored-data migration is required.
- Made every material humidifier explanation independently recognizable as
  `Humidifier response — {resolved label}: ...`. Demand thresholds, Home Assistant
  dispatch evidence, observed output state, retry/fault/isolation truth, and the
  physical-moisture caveat remain distinct; long configured labels split into two
  self-contained bounded lines. Known unavailable service/entity evidence now states
  that no request was sent, and inactive isolation remains visible exactly once on
  gate and CO paths. This changes backend presentation text only, requires no
  generated/Manual-card replacement or frontend cache refresh, and does not change
  control, entity state, configuration, or deterministic lane ordering.
- Added the versioned backend-owned `hi.reason.v1` presentation contract as the
  `display_reason` attribute on the existing Air Control Reason entity. The existing
  state, `full_reason`, truncation behavior, and `humidifier_status` remain backward
  compatible; invalid presentation data is omitted without interrupting control.
- Added plain-language backend presentation for normal, disabled, manual, pause,
  time/presence
  gates, unavailable presence, unavailable telemetry, zones, air quality, mapped and
  degraded alerts, CO emergency, output isolation, and humidifier reconciliation.
  Ventilation copy reports selected output intent because current fan writers do not
  expose dispatch or observed-state confirmation; humidifier copy retains its stronger
  requested/observed/physical-output distinctions.
- Replaced the V2 Mobile, Tablet, and canonical gallery reason composers with one
  strict `hi.reason.v1` consumer. The reason area now renders only the escaped
  backend headline and ordered line text, always keeps calm neutral explanations
  visible, and atomically falls back to escaped `full_reason`, state, or `Reason
  unavailable.` for absent, malformed, or future contracts. The 60-pixel scrolling
  viewport remains; V1 Mobile is unchanged.
- Classified unavailable-only presence evidence as degraded `presence_unavailable`
  presentation without changing the existing fail-closed gate effect. One present
  source still allows control, and CO emergency continues to bypass gates.
- Advanced the implementation identity to `2.0.10-beta.3`. Beta.1 and beta.2 evidence
  remain historical evidence for their exact commits; the incomplete beta.2 soak was
  superseded rather than failed. Beta.3 requires renewed package-layout,
  reason-contract, runtime-invariance, generated-UI, privacy, and HA Lab evidence
  before promotion.
- Converted the legacy `create_dashboard` service into an admin-gated,
  compatibility-only guidance action. It now fails safely before mapping, rendering,
  Lovelace imports, notifications, or filesystem writes and directs users through
  `refresh_ui`, `view_cards`, and Home Assistant's Manual-card workflow. New setup no
  longer offers automatic dashboard creation; older stored selections remain inert
  without migration.
- Removed dashboard ownership and unsupported dashboard-delete behavior from
  `purge_files` and config-entry removal. HI-generated exports are explicitly
  Manual-card fragments, not complete dashboard documents; Home Assistant dashboards
  are retained and remain user-managed. A full Home Assistant restart is required to
  load the changed Python service behavior.
- Separated humidifier demand from command dispatch and Home Assistant-observed
  output state. The existing humidifier-active helpers now mean effective demand
  after normal runtime gates and before humidifier-output isolation; they no longer
  imply that a device is physically producing moisture.
- Added deterministic per-output reconciliation for configured `humidifier`, `fan`,
  and `switch` outputs. Demand-active/output-off mismatches receive one immediate
  command and at most two delayed retries, with confirmation windows, bounded
  backoff, fault latching, recovery on later observed-state changes, and no blind
  turn-on while an output is missing, unknown, or unavailable.
- Added configured humidifier outputs as evaluation sources so output state changes
  request prompt coalesced reevaluation. The normal engine interval remains the
  periodic safety net after missed events, restart, reload, or availability recovery.
- Aggregated shared humidifier outputs before dispatch so two lanes produce at most
  one non-conflicting output write per cycle and one recovering lane cannot turn off
  an output still demanded by the other. Cross-family or active cross-entry output
  ownership is suppressed and reported as degraded.
- Added sanitized runtime, native-diagnostics, diagnostics-sensor, self-check, and
  release-check reconciliation truth: desired/observed categories, last command
  intent/result/time, attempt state, mismatch age, fault category, and bounded
  history without configured output entity IDs. These surfaces can prove HI demand,
  dispatch intent, and Home Assistant-observed state; they cannot prove physical
  moisture production.
- Updated generated V2 Mobile and Tablet chips/reason text plus the canonical gallery
  YAML examples to distinguish Requested, On, Idle, Isolated, Retrying,
  Stopping, Unknown, Degraded, and Fault states. V1 Mobile is unchanged. Existing
  pasted Manual cards must be re-exported and re-copied to receive the new display
  contract.
- Extended the backward-compatible `v205_release_check` service contract through
  the v2.0.10 beta/rc/stable line without renaming the service. The branch now
  carries explicit `2.0.10-beta.3` manifest identity for renewed HA Lab beta validation.
  No config/options schema, stored-data migration, or entity creation is part of
  this unreleased implementation slice.

## 2.0.9 - 2026-07-28

- Added the optional HI Support Bundle Inspector to the Pages artifact as a
  separate, noindex preflight at `/humidity-intelligence/inspector/`. Diagnostic parsing and
  handoff generation remain browser-local with zero automatic or network
  diagnostic-content egress; the only export is user-triggered copying of the
  allowlisted handoff. Native Home Assistant diagnostics remain the preferred
  support attachment and the repository/Wiki remain support truth. Wiki update
  status: `updated`; existing diagnostics guidance remains authoritative, and the
  Services Reference now documents the final external service permission boundaries.
  Release-documentation status: `updated` by this entry.
- Set integration metadata to stable `2.0.9`, aligned the release documentation, and
  extended the backward-compatible `v205_release_check` manifest contract through
  the v2.0.9 beta/rc/stable line. GitHub Releases and HACS remain the authoritative
  publication and installed-package records.
- Removed the HACS `country` metadata so Humidity Intelligence can be listed
  globally instead of being limited to the GB store scope.
- Restricted custom filenames for `dump_diagnostics` and `v205_release_check` to
  the exact lowercase `humidity_intelligence_*.json` namespace so those report
  writers cannot overwrite unrelated basename files in the Home Assistant config
  folder. Defaults are unchanged. Automations or scripts using another custom
  report filename must be updated, and Home Assistant must be fully restarted after
  installing the package update; a config-entry reload alone is insufficient.
- Moved caller-selectable diagnostics and release-check reports into the owned
  `<config>/humidity_intelligence/exports/` directory with descriptor-relative
  no-follow directory creation, same-directory atomic replacement, and no config-root
  fallback. Existing config-root reports are retained without automatic migration.
  Report consumers must update their full path. Concurrent writes are serialized and
  the last atomic replacement wins. Entry-scoped purge does not delete export reports;
  only unscoped all-entry purge may remove the exact default diagnostics export,
  while release-check and custom reports remain retained.
- Completed the runtime-owned artifact namespace: the fixed entity-bearing
  `self_check` report now uses the secure report writer at
  `<config>/humidity_intelligence/exports/humidity_intelligence_self_check.json`,
  while generated `dump_cards`, `view_cards`, setup/options, and release-test card
  YAML now writes under `<config>/humidity_intelligence/ui/`. Startup refresh remains
  cache-only. Existing root
  JSON/YAML is retained without copy, dual-write, symlink, move, or automatic
  deletion; consumers must update paths after verifying fresh owned-directory output.
- Clarified the setup/options UI and service/support guidance for existing users:
  first-run and options notifications point to exact owned UI paths, `dump_cards`
  versus `view_cards` notification behavior is explicit, legacy root cards are marked
  stale, and retained-file manual cleanup is documented without wildcard or
  registered-dashboard deletion.
- Added descriptor-relative, no-follow, same-directory atomic YAML replacement with
  directory/file identity revalidation and no config-root fallback. External
  `self_check`, `dump_cards`, and `view_cards` calls now require authenticated admin
  context before work begins; trusted integration-owned UI regeneration calls the
  internal exporter directly. Adding a second entry re-exports all loaded entries
  with qualified card names; removing back to one re-exports the remaining entry
  with unqualified names while retaining the remaining entry's superseded qualified
  files for exact purge.
- Narrowed cleanup to exact owned artifacts. Entry-scoped purge may remove the
  selected entry's default and release-test card exports plus its registered
  dashboard, but no reports. Unscoped all-entry purge may also remove the fixed
  default diagnostics and self-check reports. Config-entry removal separately owns
  only the removed entry's exact default/release-test card exports and registered
  dashboard. Custom card/report names, release-check reports, remaining-entry
  superseded qualified files, and legacy root artifacts remain retained.
- Required authenticated admin user context for every `dump_diagnostics` and
  `v205_release_check` call. Non-admin, unknown-user, and contextless background
  callers are rejected before report lookup, cache work, path resolution, writes, or
  notifications. Direct authenticated admin UI/API calls remain supported.
- Required admin user context for targeted and all-entry `pause_control` /
  `resume_control` calls, explicit `create_dashboard`, and `purge_files`. Existing
  background automations/scripts whose action context has no `user_id` can no longer
  invoke those mutation services, even when configured by an admin. Use an
  authenticated admin UI or API session; any future automated trusted route requires
  separate design approval. First-run dashboard creation remains available through
  the trusted config-entry setup path.
- Required authenticated admin user context for every external `flash_lights`,
  `create_local_backup`, and `list_saved_versions` call. Non-admin, unknown-user,
  and contextless callers are rejected before light, snapshot, or inventory work.
  `list_saved_versions` remains read-only but is gated because its persistent
  notification exposes package-local snapshot metadata. Engine-owned visual alerts
  use a separate trusted internal helper after deterministic lane selection, so
  alert continuity, entity semantics, and lane ordering are unchanged.
- Made `purge_files` validate its complete fixed set of direct HI-generated file and
  configured-dashboard targets before mutation, publish the exact existing target
  preview with a blocking notification, reject unsafe/non-regular filesystem
  candidates, and report file or dashboard deletion failures as an incomplete purge.
- Escaped dynamic room, target-profile, condensation, and mould text in the V1 Mobile
  source and gallery templates. V1 Mobile remains exportable through v2.0.9 but is
  deprecated for new dashboards in favor of V2 Mobile; removal is deferred to a
  separate v2.1 migration proposal. Existing pasted V1 cards must be re-exported and
  re-copied to receive the escaping fix.
- Redacted private Home Assistant URLs and hosts, local network addresses, bearer
  credentials and tokens, device IDs, local user paths, and Home Assistant entity IDs from
  locally generated issue-triage body summaries before Markdown/HTML escaping.
  Public issue links remain available for maintainer triage.

## 2.0.8 - 2026-07-05

- Declared Home Assistant `2026.5.1` as the minimum HACS install/update
  compatibility floor and surfaced the requirement in installation guidance.
- Migrated computed humidity, target, drift, and delta sensor percentage units from
  the deprecated Home Assistant `PERCENTAGE` unit constant to
  `UnitOfRatio.PERCENTAGE` for Home Assistant Core `2026.7` compatibility, with a
  legacy `%` fallback for older supported Core versions. Entity IDs, values, lane
  ordering, services, diagnostics semantics, and generated-card display behavior are
  unchanged.

- Added a first-run welcome page before Frontend Dependencies that explains the
  staged setup method, with README guidance and telemetry copy updated so users
  can safely save a small initial sensor set and return through Options later.
- Fixed Temperature Slope setup/options submission so collapsed Advanced source
  lists that submit empty fall back to the configured temperature sensors instead
  of re-rendering the same form with a hidden validation error.
- Added Home Assistant Area/Label setup assistance for telemetry configuration:
  HI can use registry metadata to suggest room/level defaults and diagnostics
  mismatch counts, while saving only explicit HI telemetry fields. Areas and Labels
  are advisory only and do not affect lane ordering, entity semantics, generated-card
  truth, output control, or migration behavior.
- Blocked default generated V2 dashboard YAML from shipping runtime mutation controls:
  pause/resume and the standalone View Cards service button are now
  read-only/default-safe surfaces. The System and Manual buttons keep the
  v2.0.7 tap-to-toggle helper behavior, and the output details expander keeps
  the v2.0.7 UI-only helper toggle so the bottom Outputs section still opens
  from the card. Backend services remain available through Home Assistant
  service/admin workflows.
- Replaced the generated V2 Pause LIVE tile with a passive compact
  gauge-style Stability preview badge. The badge reads future v2.1 Stability
  Score diagnostics from the existing HI diagnostics sensor when present,
  otherwise it degrades without calculating scores, requiring a new sensor, or
  creating a control path. Current/complete Stability shimmer is paced at 10 beats
  per minute with a 6 second animation cycle.
- Hardened the Stability preview fallback so null or empty future score values stay
  in the default future/preview state instead of rendering as a real score of zero,
  and aligned the tablet/gallery System and Manual card glow with the mobile layout.
- Made Home Assistant setup-assist suggestions an explicit telemetry form preview
  action so advisory Area/Label-derived defaults are reachable without changing the
  normal save path.
- Kept global pause/resume support, but global all-entry pause/resume calls now
  require an admin user context. Per-entry calls remain scoped to the supplied
  config entry.
- Hardened release hygiene and support output handling: the tracked secret scan now
  fails closed when no tracked files are selected, issue-triage reports are written
  through a confined private atomic writer, and diagnostics/support exports favor
  sanitized structure/count/status summaries and redaction. `self_check` and
  release-validation reports may still include configured/generated entity IDs needed
  to debug missing mappings, so treat those exports as local/private until reviewed or
  sanitized before public sharing.
- Expanded issue-triage public-safety checks to reject macOS, Linux, and Windows
  local absolute paths, and bucketed mapped runtime entity state in native diagnostics
  into privacy-safe availability categories instead of exposing raw Home Assistant
  state text.
- Extended the existing `v205_release_check` manifest-version contract to accept
  the v2.0.8 beta/rc/stable line while preserving the backward-compatible service
  name.
- Release-candidate preparation impact: manifest metadata is stable `2.0.8`, while
  GitHub release publication, tagging, branch promotion, and the user-facing package
  record stay with the normal maintainer approval flow.
- Runtime impact: deterministic lane ordering, output-writer boundaries, entity
  semantics, and migration shape stay aligned with the existing backend contract.
  Generated dashboards should be refreshed or re-exported after update when users rely
  on default V2 cards or pasted Manual-card YAML.

## 2.0.7

- Promoted integration metadata to stable `2.0.7`.
- Added a GitHub Pages SEO landing site for search discovery, with static public
  copy, the Humidity Intelligence logo, wide home-telemetry hero artwork,
  sitemap/robots crawl helpers, structured search metadata, pinned Pages workflow
  actions, README routing, and repository source-of-truth boundaries. Runtime
  behavior, entity semantics, generated dashboards, HACS metadata, and migration
  requirements are unchanged.
- Documented HA Lab as advisory Operational Beta Validation Infrastructure and added
  PR/release-governance wording for reporting sanitized HA Lab evidence without
  changing runtime, UI, entity semantics, migration, or release authority.
- Hardened visual-alert service validation, diagnostics credential-key redaction,
  generated V2 card HTML rendering, and local issue-triage report escaping without
  changing deterministic lane ordering, entity semantics, or migration behavior.
- Fixed PM2.5 aggregate runtime truth by ensuring new PM2.5 aggregate sensors use canonical PM25 entity slugs and by normalizing existing HI PM2.5 aggregate entity IDs from `pm2_5` to `pm25` during setup.
- Hardened generated-card AQ output details so unresolved optional AQ aggregate rows
  are pruned instead of rendering stale `Entity not found` rows, and added
  generated-card entity reference availability checks to `self_check` and
  `v205_release_check`.
- Expanded generated-card entity reference checks so stale IDs embedded inside
  generated-card JavaScript/string expressions are reported, not only YAML `entity:`
  rows.
- Filtered generated-card release-validation extraction so JavaScript service names,
  predicate prefixes, object properties, and entity-prefix strings no longer fail
  generated-card entity availability checks.
- Recorded HA Lab advisory validation for commit `55dc2b9`: lab identity, HI
  presence/diagnostics, scenario-matrix read-only baseline, and Stage 3 six-sensor
  runtime-readiness checks passed after lab-only deploy and manual restart, without
  stable-instance access, service calls, helper mutation, dashboard mutation,
  restart, reload, or output writes by Codex.
- Added diagnostics, `self_check`, and `v205_release_check` reporting for PM2.5
  aggregate entity-ID normalization conflicts when a canonical `pm25` target entity
  already exists.
- Sanitized generated V2 card templates, gallery exports, and test fixtures so
  public artifacts use canonical HI placeholders instead of maintainer-local
  presence, alarm, tracker, or room-sensor entity IDs.
- Refined generated V2 Current Air Control cards so degraded or unmapped alert
  candidates no longer occupy primary chip-row space; no-automation context remains
  visible in reason text.
- Fixed generated V2 Current Air Control cards so missing or unavailable
  `sensor.air_control_mode` no longer falls back to `normal` / `READY`; backend
  `telemetry_unavailable` now renders as explicit degraded UI truth ahead of stale
  helper-derived alert or AQ display state.
- Kept startup UI refresh option semantics deterministic by removing the
  unconditional startup `dump_cards` task; startup now follows the configured
  `auto_refresh_ui_on_startup` refresh path, while explicit UI install,
  option-visibility changes, and manual `dump_cards` still write card files.
- Added Configuration Walkthrough links to setup Frontend Dependencies, post-configuration Frontend Dependencies, and final UI export guidance.
- Added GitHub Wiki support-manual routing from the README, including configuration, services, diagnostics, generated dashboard, HACS/update, AQ/CO safety, troubleshooting, and release-validation guidance.
- Added release/PR checklist support for recording Wiki update status as `updated`, `no-op`, or `blocked` when public manual guidance is affected.
- Added a Wiki Services Reference, footer navigation across public Wiki content pages, and a Wiki banner asset for a clearer support-manual experience.
- Declared native Home Assistant diagnostics as an integration after-dependency so hassfest accepts the diagnostics support surface without changing runtime control behavior.
- Changed generated V2 Current Air Control cards so red control-row styling follows selected alert/CO runtime truth, while degraded or unmapped alert candidates remain in reason text instead of command-state red.
- Moved optional Level 1 / Level 2 display-label editing into setup Zones and post-configuration Zone Options before Zone 1 / Zone 2 editing; labels are sanitized, fallback to `Level 1` / `Level 2`, and affect generated-card/config-flow/support display text only.
- Migration note: users with manually referenced PM2.5 aggregate entity IDs using `pm2_5` should update those references to `pm25` after restart; generated cards should be regenerated/re-copied when PM2.5 aggregate surfaces are used.

## 2.0.6

- Promoted integration metadata to stable `2.0.6`.
- Added a degraded `telemetry_unavailable` runtime mode when required humidity or configured temperature telemetry is unavailable, standing down lower-priority control lanes instead of reporting a normal/all-clear state.
- Fixed global gate preemption so an active humidity-danger alert lane clears its active alert switch, held alert context, and Current Air Control alert chip when the gate takes authority.
- No migration is required for the global gate preemption fix; after updating HI, reload/restart Home Assistant, then run `humidity_intelligence.dump_cards` or re-copy any pasted dashboard YAML and refresh dashboard/browser cache to see the Current Air Control card update.
- Fixed CO emergency clearing so HI schedules a recheck at the two-minute clear deadline instead of waiting for the next normal control interval.
- Added direct backend simulation validation for `HI Air Control Mode` and `HI Air Control Reason`, covering normal, telemetry unavailable, zone, AQ, gate, and opt-in CO pressure scenarios without adding runtime fake telemetry paths.
- Fixed setup/options telemetry add and edit pages so users can cancel back to the previous telemetry page without losing already-saved flow data, with explicit close-without-saving confirmation on HI-controlled Cancel actions.
- Fixed Zone 2 setup/options defaults and trigger labels so Zone 2 trigger ownership is shown and stored as Zone 2 / Level 2 unless explicitly changed.
- Added explicit local HI-only snapshot services for advanced maintenance: `create_local_backup` and `list_saved_versions`.
- Exposed compact local snapshot status through diagnostics, self-check, and optional release-check freshness inputs.
- Kept local snapshot support manual and package-local only; no restore flow, automatic rollback, HACS interception, startup snapshotting, or whole-instance backup behavior is included.
- Added a Community Ideas & Proposals issue form for ideas, dashboard suggestions, compatibility requests, documentation improvements, diagnostics/support-flow ideas, and automation/control suggestions.
- Updated contributor, support, and report-only triage wording so community ideas remain manual intake signals, not implementation authority.
- Added clean-install setup/repair guidance for the `HI House Humidity Drift 7d` Statistics helper dependency.
- Added a non-blocking Home Assistant Repairs issue only when `sensor.house_humidity_mean_7d` is missing.
- Differentiated missing helper, helper not ready or unavailable, non-numeric helper, low history coverage, and invalid source states without fabricating drift values.
- Refined optional Current Air Control temperature chip colours to use backend-owned seasonal cold, comfort, warm, and hot boundaries.
- Retuned Spring and Summer temperature chip comfort/warm bands while keeping the backend-owned seasonal boundary model unchanged.
- Exposed the resolved temperature warm boundary through comfort sensor attributes and diagnostics so generated cards read seasonal thresholds from backend truth.
- Kept setup/options Frontend Dependencies pages frontend-only; drift dependency truth remains available through diagnostics, self-check, release-check, drift sensor attributes, and Repairs.
- Preserved the existing drift calculation and legacy `sensor.house_humidity_mean_7d` compatibility.
- Kept lane ordering, AQ, humidifier, alert, output, migration, restore, HACS update, and runtime-control behavior unchanged except for the explicit `telemetry_unavailable` mode/entity truth correction.

## 2.0.5

- Reorganised setup and options so essentials stay visible while tuning controls move behind Advanced sections.
- Changed Advanced tuning from submit-gated reveal toggles to in-form collapsible sections so tuning controls open and retract immediately without changing saved runtime behavior.
- Added recommended-default guidance across setup/options without changing deterministic runtime behavior.
- Added `show_output_entity_details` as a UI-only generated-card option; new installs default to the cleaner V2 output display unless it is enabled.
- Made `Thresholds & Comfort` easier to scan by keeping comfort mode visible and moving custom comfort/threshold tuning into Advanced.
- Changed first-install UI export default to `v2_tablet`.
- Kept custom humidity target bounds behind Advanced in post-configuration Global Gates and reviewed setup/options parity for the v2.0.5 UX flow.
- Preserved canonical `dump_cards` behavior: unscoped exports all cached/generated layouts; scoped `layout` exports only the specified layout.
- Preserved deterministic runtime lane ordering, alert hierarchy, CO emergency behavior, humidifier independence, and public entity semantics.
- Added `v205_release_check`, a read-only Home Assistant service for test-repo validation of the v2.0.5 generated-card and `dump_cards` contracts.
- Changed setup/options dependency display, `self_check`, `v205_release_check`, and `dump_diagnostics` frontend dependency reporting to use the same Lovelace resource inspection path via `LOVELACE_DATA.resources.async_items()`, returning detected URLs or a non-blocking `not_inspectable` status instead of legacy false negatives.
- Added native Home Assistant diagnostics for Humidity Intelligence config entries so users can download a redacted support file for GitHub issues.
- Updated issue templates and local issue triage to prefer attached native Home Assistant diagnostics, suggest `has-diagnostics` when present, and suggest `needs-bundle` for bug/support reports without one.
- Hardened `HI House Humidity Drift 7d` so missing or unavailable `sensor.house_humidity_mean_7d` statistics dependency is reported in sensor attributes, `self_check`, `v205_release_check`, and diagnostics instead of failing silently.
- Fixed calculated room temperature slope sensors so they publish a seeded state immediately after setup instead of waiting for a later source update, preventing restored-but-unavailable slope chips after HI restarts.
- Fixed calculated temperature slope diagnostics mapping so every configured slope source prefers Home Assistant's registered entity id when it differs from the predicted `sensor.hi_*` fallback.
- Promoted integration metadata to stable `2.0.5`; branch/version governance now allows beta, rc, or stable labels on `senyo888-patch-1`, rc or stable labels on `develop`, and stable releases on `main`.

## 2.0.4

- Promoted integration metadata to stable `2.0.4`.
- Added alert-to-zone binding for humidity, mould, and condensation alerts so the originating room resolves to its configured zone boost level.
- Added mould risk and condensation risk alert trigger types alongside the existing danger triggers.
- Enforced deterministic priority across CO emergency, humidity danger, mould danger, mould risk, condensation danger, condensation risk, Zone 1, Zone 2, AQ, and normal lanes.
- Added deterministic multi-alert conflict reporting in the reason panel and debug logs.
- Added the `auto_refresh_ui_on_startup` option, enabled by default, to refresh HI UI mapping shortly after Home Assistant startup without blocking startup.
- Removed the HACS URL from frontend dependency flow output while retaining HACS detection.
- Fixed alert flash color payloads so internally triggered visual alerts send RGB lists accepted by Home Assistant service validation.
- Added user-friendly headers to V2 card YAML exports with Manual-card paste instructions, `dump_cards` refresh guidance, and frontend dependency reminders.
- Fixed alert flash payloads so optional visual-indicator power entities are omitted when unset, avoiding schema errors and repeated debug logs.
- Refined Air Control UI chips so AQ and humidity rows use House, Upstairs, Downstairs ordering and removed the Kitchen temperature-slope chip from the humidity row.
- Refined Air Control humidity chips to use configured zone-room humidity telemetry, skip legacy bespoke delta chips, and list room humidity deltas alphabetically.
- Added an optional Air Control temperature chip row controlled from Temperature Slope settings, showing house/level temperatures, configured zone-room temperatures, and room temperature slopes.
- Added automatic/custom temperature comfort configuration with runtime comfort sensors used by V2 temperature chip colours.
- Expanded post-configuration zone editing so humidity high, air quality, condensation risk, and mould risk thresholds remain editable per zone.
- Fixed calculated temperature slope chip fallback to use Home Assistant slug-compatible generated slope entity IDs and configured slope source checks.
- Renamed user-facing dependency wording to Frontend Dependencies across setup, options, services, self-check output, and docs.
- Added README v2.0.4 upgrade guidance to run `humidity_intelligence.dump_cards` and paste the generated YAML into existing Manual dashboard cards for UI changes.
- Enlarged the HI icon/logo artwork within the required 256x256 canvas so it appears larger in Home Assistant and HACS surfaces.
- Clarified Global Gates target-profile labels as `Humidity Intelligence target profile mode` and `Humidity custom target`, and added explicit alert visual rule removal in setup and options flows.
- Simplified alert chipsets so they render only the alert lane/status chip and the resolved alert source/context chip.
- Changed humidity/mould/condensation visual alerts to flash 10 times, restore prior light state, wait 30 minutes, and repeat only while the same alert remains active.
- Expanded diagnostics with target profile mode, active profile/season/custom target, zone/alert mappings, visual alert config, active alert resolution, unavailable entities, and warnings.
- Reduced live `HI Diagnostics` state attributes to a compact recorder-safe summary; full diagnostics remain available from `dump_diagnostics`.
- Fixed alert helper switch churn so active alerts no longer flip their UI helper switches off/on during every evaluation cycle.
- Added single-flight automation evaluation and stopped internal status helper switches from retriggering evaluation, preventing alert-clear dogpiles when humidity returns to normal.
- Fixed startup UI refresh scheduling to use Home Assistant's thread-safe task creator, preventing unsafe `hass.async_create_task` calls during startup.
- Fixed startup UI refresh cleanup so Home Assistant builds where `hass.create_task` returns no task handle do not raise during the startup event.
- Removed custom trigger entities and custom binary sensor alert configuration so alerts remain internally calculated from HI telemetry, risk logic, and room/zone resolution; legacy custom alert rows are stripped from config-flow saves.
- Removed CO output-device selection from the main alert flow; CO Emergency now uses configured CO telemetry and existing configured ventilation outputs.
- Added clearer zone boost guidance and warnings when boost levels are not higher than normal zone fan levels.
- Added an alert handling setting for internally calculated humidity, mould, and condensation alert handling while keeping CO Emergency independent.
- Fixed alert boost hold behavior so selected alert zone outputs are not returned to auto while the alert lane is active.
- Changed alert conflict handling to keep the current actionable alert boost until that originating alert clears, unless a higher-priority alert appears.
- Changed unmapped/degraded alert handling so unsafe alert candidates are reported in the reason text while automation continues to the next eligible priority.
- Added degraded-mode handling when an alert sensor, room, zone, or output mapping is incomplete.
- Fixed built-in humidity, mould, and condensation alert candidates so they enter the alert lane, resolve to the mapped zone boost level, and populate `HI Active Alert Context` even when no matching explicit alert row is configured.
- Fixed V2 alert chip detection so generated cards recognise real alert switch entity IDs and the active alert context companion chip.
- Changed Humidity Danger alerts to use the active target profile high-risk threshold instead of any saved static humidity threshold.
- Updated alert metadata/reason text so Humidity Danger reports its active profile threshold source while CO Emergency keeps its configured ppm threshold.
- Fixed CO emergency evaluation so it remains the absolute top-priority lane before gates, pause, manual override, and normal control locks.
- Added GitHub community health files, issue forms, validation workflows, and contributor guidance.
- Added CI SAST/security checks, Bandit configuration, broader diagnostics redaction, and cleanup error logging.
- Added Hassfest validation workflow for Home Assistant custom integration checks.
- Updated Hassfest compatibility by staging the root-content HACS layout as `custom_components/humidity_intelligence`, aligning manifest keys, shared flow errors, and Lovelace after-dependency metadata.
- Added pre-Hassfest staged metadata normalization and verification so CI validates the generated custom component tree, not stale root metadata.
- Added a V2 UI Gallery with default mobile, tablet, and legacy mobile examples plus contributor/reference documentation.

<details>
<summary>Previous Releases</summary>

## 2.0.3

- Promoted integration metadata to stable `2.0.3`.
- Documented minimum Home Assistant version `2026.4.3`.
- Added direct repository links for `card-mod`, `button-card`, `mod-card`, and `apexcharts-card` to frontend dependency status output.
- Added a post-configuration Frontend Dependencies options step so dependency checks remain accessible after initial setup.
- Reordered the options menu for setup-flow clarity: Frontend Dependencies, Sensors, then Global Gates.
- Refreshed README frontend dependency guidance with a HACS-first installation path and acknowledgements.
- Updated the top badges so HACS reads `Custom Integration` and Home Assistant compatibility is visible directly.

## 2.0.2

- Corrected humidity badge semantics to target-relative `below_target`, `in_target`, `above_target`, and `high_risk` states.
- Surfaced the active target season/profile in the UI target display.
- Updated condensation and mould risk evaluation to use season-aware deterministic thresholds.
- Expanded humidifier telemetry reasons with lane scope, trigger condition, measured values versus thresholds, and recovery logic.
- Added runtime debug logging for the active target profile, seasonal adjustments, humidity badge classification, and humidifier trigger/stop events.

## 2.0.1

- Fixed Fahrenheit telemetry normalization by converting internal temperature calculations to Celsius before averages, spreads, deltas, and thresholds.
- Fixed IAQ/AQ aggregation so `unknown`, `unavailable`, and non-numeric states are excluded and the aggregate is unknown only when no valid values remain.
- Added aggregate exclusion debug logging with explicit `unknown`, `unavailable`, `non_numeric`, and `unit_mismatch` reasons.
- Added zone-mapping duplicate warnings in setup/options and a duplicate-diagnostics sensor state.
- Added `alert_only_mode` for monitoring and alerts without output-control lanes.
- Improved generated-UI placeholder pruning so unconfigured optional outputs and controls, including alert-only controls, are hidden.
- Fixed alert-only card rendering by pruning invalid leftover `conditional` blocks after entity pruning.
- Updated Current Air Control reason behavior so alert-only mode reports monitoring/alert context separately from output-control wording.
- Made `alert_only_mode` option changes trigger UI card refresh/export regeneration and a notification.
- Expanded options editing so previously skipped lanes and alerts can be revisited and added later.
- Expanded post-configuration lane management so humidifier and AQ lanes can be restored after removal, with explicit telemetry add/update/remove logging.
- Made alert target lights optional across config, options, services, and runtime; alerts remain active without flash entities.
- Hardened service input validation for filenames, URL paths, layouts, and bounded flash parameters, and expanded diagnostics redaction for sensitive attributes.

### Legacy migration notes

- `alert_only_mode` is available under Global Gates in setup and options. Disable it to restore normal control entities and lane behavior.
- `HI Zone Mapping Duplicates` (`hi_<entry_id>_zone_mapping_duplicates`) exposes duplicate zone-mapping status and details.
- New computed sensors are `HI Active Target Season` (`hi_<entry_id>_target_season`) and `HI House Humidity State` (`hi_<entry_id>_house_humidity_state`).
- Generated V2 cards prune unresolved optional control/output entities instead of leaving stale references.
- Manual-card dashboards should use the latest exported YAML after changing `alert_only_mode` so the UI and reason panel match the selected mode.

</details>
