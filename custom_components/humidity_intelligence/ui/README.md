# Humidity Intelligence V2 UI

## Canonical Runtime Presentation Layer

---

## Purpose

The UI exists to render runtime truth.

It must:

- present active lane state
- show gate blocks
- display reason context
- reflect output stage
- mirror engine behavior

Control logic and lane priority stay in the backend engine.


The engine governs.
The UI reflects.

---

## Included Layouts

- `cards/v2_mobile.yaml`
- `cards/v2_tablet.yaml`
- `cards/v1_mobile.yaml` (deprecated in v2.0.9; use V2 Mobile for new dashboards)
- `cards/view_cards_button.yaml`

Mobile and tablet share identical control logic.

Difference:

- mobile: rounded top badges
- tablet: squared top badges

Feature parity is maintained.

---

## Seven-day humidity drift — v2.1.0-beta.2

The drift badge shows the current house average humidity minus its seven-day mean,
measured in percentage points. Positive values mean wetter than that average;
negative values mean drier.

While the backend reports insufficient history, **Baseline · 25%** shows progress
of reported Statistics time coverage toward the backend requirement. For example,
22% coverage against an 85% requirement displays 25% after rounding down. Coverage
can stall, fall or reset. Missing progress metadata shows **Waiting for history**;
a missing Statistics helper shows **Setup needed**. Other blocked or malformed
inputs show **Unavailable**, with context in the details.

Tap or use Enter/Space to open the explanation and **View history**. History opens
Home Assistant's native more-info surface for the registered drift entity; its
recorded values depend on Recorder and retention. Hold also opens native more-info.
The details use a native modal dialog and close on changed badge evidence,
navigation or card removal. Browsers without native dialog support use more-info
as the tap fallback. Button-card 7.0.1 was exercised with synthetic entity data and
a minimal Home Assistant event router; live Companion/WallPanel validation is
separate.

The change applies to V1 Mobile, V2 Mobile, V2 Tablet and their default gallery
mirrors. Drift calculation, readiness, history ownership, control and entity/service
contracts are unchanged. After installing the updated templates, run `refresh_ui`
and `view_cards`, then replace the pasted Manual-card YAML and refresh the client.
The template-only change needs no configuration/data migration or Python restart;
other changes in an installed beta package may have their own restart requirements.
Reverting the card YAML restores the earlier interaction without changing history.

## V2 badge summaries

Humidity, Condensation, Mould, Current Air Control, Ready, Zone 1, Zone 2 and AQ
open a short explanation before **View history**. Humidity and Ready retain native
Home Assistant entity details; Ready links to house humidity. Zone 1/2 link to their
resolved humidity reading, which can be a fallback rather than a whole-zone
measurement.

Beta.3 collects the V2 summaries, compact status row, friendly wording and history
updates introduced after beta.2. Refresh exports and replace saved V2 cards to
apply them while preserving the running Stability collection.

Condensation, Mould, Current Air Control and AQ use a shared recorded-history panel:

- **24 hours** and **7 days** select a bounded window. **Back** returns to the
  explanation and retains the selected range; **Close** dismisses the dialog.
- Condensation/Mould show categorical risk and worst-room source as separate
  time-aligned ribbons, with timestamped records. Independently recorded updates
  retain their own timing and source context. Unknown and unavailable remain
  distinct from recorded risk categories. Source rooms have individual colours and
  matching labelled legends. Room colours stay consistent across both histories,
  range changes and reopenings within the same page session; they identify rooms
  independently of risk. Unknown/unavailable source states use a neutral grey.
- Current Air Control shows recorded operating mode and separately timestamped
  reason text where Recorder retained it. This records controller state;
  physical output activity is available through the corresponding output entities.
- AQ shows an independent numeric chart for each available mapped IAQ, PM2.5, VOC
  and CO aggregate. Recorded units are used when present; otherwise the chart identifies
  the unit as unspecified. Invalid/unavailable values and unit changes break
  traces. Values follow the recorded aggregates and their own scales. Use dedicated CO
  safety status when assessing CO emergencies.

History is requested only after **View history**, through the authenticated Home
Assistant history WebSocket API, for at most four mapped entities. Loading, empty,
failed and partial results retain explicit availability labels. A carried value
at the start of the window is labelled as starting context. Transitions retain
their recorded evidence; recording frequency follows the source. Bounded rendering discloses
truncation and preserves the retained transitions. Native **Open entity
details** remains available. Back, Close, navigation, card removal and range changes
invalidate pending requests so the latest selected view stays authoritative.

The renderer lives in `badge_history.js` and is embedded in the exported YAML;
Manual cards include the renderer directly.
After editing that source, run `python scripts/sync_badge_history.py` from the repo
root and verify the generated copies with its `--check` option. History preserves
Recorder configuration, retention, entity semantics and runtime control.

Summaries identify their mapped history sources. Enhanced history is available
when at least one source is mapped; native history links follow their mapped entity. Dynamic text is escaped. Only one HI details dialog
is open at a time; Close, Escape, navigation and card removal dispose of it.
New summaries close when their displayed evidence changes. Stability preserves
its opening snapshot and now explains that below the main content; drift retains
its existing evidence-change behavior. Native entity details remain the fallback
when modal dialogs cannot be opened.

Ready, Zone 1, Zone 2 and AQ retain their labels, active tint, borders and alert
emphasis in compact icon-free rows. Their targets remain at least 44px high and
allow text to grow. Close uses a compact circular X with a 44px touch target and an accessible label.
Dialog sizing accounts for device safe areas; physical-client
appearance must be checked separately from synthetic browser validation.

The changes apply only to V2 Mobile, V2 Tablet and their canonical gallery copies.
V1 remains unchanged, with retirement owned by the separate v2.1 migration work.
Refresh exports and replace pasted Manual-card YAML, then refresh the client.
No configuration/data migration, Python restart, runtime decision, entity or
service change is introduced by this template-only update. Rollback restores the
previous templates and saved card YAML. Other changes in an installed beta package
may have their own restart requirements.

The summary and history explanations use plain language. Recorded changes, value
selectors and availability messages describe the available data and useful next
steps. Backend classifications, historical units and CO safety context remain
authoritative. The local Stability fallback reads **Unavailable** when the
score payload needs valid evidence.

## UI Preview

### Live 2.0.10-beta.7 Card State

These captures were taken from an exact live `2.0.10-beta.7` installation after Home
Assistant restart, fresh card export, complete Manual-card YAML replacement, and
dashboard/browser cache refresh.

<img src="../../../assets/ui/v2.0.10-beta.7/mobile-aq-humidifier-retrying.png" width="320" alt="Live HI 2.0.10-beta.7 mobile AQ card with a humidifier retry state">
<img src="../../../assets/ui/v2.0.10-beta.7/tablet-zone1-cooking-output-on.jpg" width="320" alt="Live HI 2.0.10-beta.7 tablet Zone 1 cooking card with observed outputs on">

These images demonstrate the refreshed package and cards. They are not soak,
Stable, release-approval, or HACS-publication evidence.

### The simple reason

The before/after assets are editorial comparisons built from refreshed beta.7 UI
evidence, not continuous playback records.

<img src="../../../assets/ui/v2.0.10-beta.7/comparison-alert-reason-before-after.png" width="760" alt="Editorial comparison of the alert reason presentation before and in v2.0.10">
<img src="../../../assets/ui/v2.0.10-beta.7/comparison-reason-field-before-after.png" width="760" alt="Editorial comparison of reason field presentation before and in v2.0.10">

<details>
<summary>Historical layout references — not beta.7 playback</summary>

### v1 Mobile (Deprecated Legacy-Compatible Skin)
<img src="../../../assets/readme/ui_v1_mobile.png" width="320" alt="HI v1 mobile UI preview">

</details>

---

## Deployment Workflow

### Step 1 - Complete Integration Setup First

Finish:

- telemetry
- zones
- humidifiers
- AQ
- alerts
- gates

The UI maps directly to your configuration, and HI notifies you where generated UI YAML is saved.

### Step 2 - Or Generate Cards via Services

Use:

- `humidity_intelligence.view_cards`
- `humidity_intelligence.dump_cards`

These external services require an authenticated admin user context.
`dump_cards` and `view_cards` write generated YAML under
`/config/humidity_intelligence/ui/`; multi-entry installations add an entry-qualified
token to each filename. Adding a second entry re-exports all loaded entries with
qualified names; removing back to one re-exports the remaining entry with unqualified
names. HI no longer refreshes superseded owned-UI names, but external consumers can
still read their stale content until exact purge. Config-entry removal deletes only
the removed entry's exact default/release-test UI exports; Home Assistant dashboards,
reports, custom exports, legacy root files, and remaining-entry superseded qualified
files are retained. Trusted first-run, options, and release-check regeneration uses
the same internal exporter without routing through the public service handler.
Startup refresh remains cache-only. `humidity_intelligence.create_dashboard` remains
registered for compatibility, but performs no writes and returns the supported
Manual-card steps after admin authorization.

`dump_cards` writes files without a completion path notification. Open
`/config/humidity_intelligence/ui/` in File Editor after the action, or use
`view_cards` when you want the exact path in a persistent notification. First-run and
relevant options regeneration also report exact written paths. `refresh_ui` updates
the in-memory cache only.

If upgrading from the config-root writer, do not copy a retained file such as
`/config/humidity_intelligence_cards_v2_mobile.yaml`; HI no longer refreshes it.
Refresh File Editor and use the new owned-directory file. Before manually deleting a
retained root or custom export, back up and disable every consumer, then delete only
that exact regular file. Never delete the whole owned directory or overwrite a
dashboard file with a Manual-card fragment.

Avoid manual YAML drift.

### Step 3 - After Any Option Change

When modifying:

- sensors
- zones
- alerts
- gates
- slope

Do:

1. save options
2. run `humidity_intelligence.refresh_ui`
3. regenerate cards if required
4. verify Current Air Control panel

Temperature chips:

- render only when `show_temperature_chips` is enabled
- colour against HI runtime comfort sensors
- use blue below band, green in band, yellow up to the backend-owned warm boundary, red above that
- show room slope chips only for configured temperature slope sources or provided slope sensors
- resolve calculated slope chips through diagnostics/backend slope mapping so Home Assistant registry-assigned entity IDs stay truthful

Control row:

- preserve the v2.0.7 tap-to-toggle behavior for the System and Manual helper buttons
- keep the Stability Score badge passive; it must not pause/resume, select lanes, or create output writes
- for the integrated, unpublished `2.1.0-beta.1` Stability candidate, render backend schema 3/formula 3
  score, classifications and evidence states; missing/malformed payloads show no score
- preserve the accepted 82px footprint, independent LED colours, retained signed
  full-circle movement, six-second Partial pulse and reduced-motion alternatives
- whole-badge tap/click/keyboard activation opens a native modal dialog through the
  button-card action. Details are a labelled snapshot copied from the owning card's
  inert template, mounted outside its gesture handlers; there is no nested opener
- keep a visible sticky Close control, native Escape and backdrop dismissal, focus
  restoration, and cleanup on navigation or owner removal. Only one Stability dialog
  may be open; telemetry updates must not silently replace its snapshot
- hold opens Diagnostics. Clients without native `showModal` support fall back to
  Home Assistant's Diagnostics more-info, including readable baseline/failure evidence
- collection LEDs fill clockwise from the top, one per valid sample in backend-defined
  slots (currently 303). Centre ticks in their slots and hide the origin after the first
  tick. Strict integer counts and a target in [1,432] must agree with the finite backend
  ratio; invalid/conflicting progress stays unlit. Incomplete collection never fills
  the ring. This is sample progress, not elapsed time or score movement
- while collecting, details show `Baseline progress: N of 303 valid samples`, using the backend minimum
  rather than a fixed denominator. The 432 buckets remain rolling-window capacity,
  not the baseline target; outside collection the tally is labelled `Rolling-window coverage`.
  Collection details explain that backend evidence requirements still apply;
  do not hold a full ring or delay backend state transitions
- non-scored collection/evidence states show a separate thin red track for backend
  `sampling.failure_history`: known failed or missed scheduled buckets over 72 hours.
  Use backend angles/count/description; do not infer history in the card. At most
  432 unique UTC positions are retained, expire with the window, and clear if their
  bucket is later captured successfully. Dense marks can overlap; details give the
  exact count. This track does not alter blue progress or available-score movement
- failure history is in memory only: restart/reload clears it with the baseline.
  No offline or pre-start failures are inferred. Installing the Python history
  update requires restart; no configuration or stored-data migration is needed
- after changed Python, restart Home Assistant; run `refresh_ui`, obtain fresh
  `dump_cards`/`view_cards` exports, replace complete pasted YAML, and refresh frontend
  caches. No configuration/entity migration is needed. Restart/reload resets history
- restore package and dashboard YAML separately on rollback; package rollback needs
  restart and does not restore pasted cards

The [accepted Stability contract](../../../docs/stability-score-accepted-baseline.md)
and [testing guide](../../../docs/stability-testing.md) own detailed thresholds,
missing AQ treatment, sampling/reset semantics and four-surface parity checks.

Output details:

- render the expandable output details panel only when `show_output_entity_details` is enabled
- tap the Outputs header to toggle the expander helper; this is UI-only, with device
  commands left to the runtime/service paths
- stay display-only; the option must not affect lane selection, output writes, isolation switches, or diagnostics
- prune unresolved optional AQ aggregate rows instead of leaving `Entity not found` rows
- require a fresh `humidity_intelligence.dump_cards` export after changing visibility, templates, or backend entity mappings

---

## Placeholder Mapping Model

`ui/register.py`:

1. builds placeholder to entity map
2. substitutes canonical templates
3. prunes optional rows
4. reports unresolved non-optional placeholders

Inventory files:

- `_sensor_ids.txt`
- `_binary_ids.txt`
- `_input_boolean_ids.txt`
- `_timer_ids.txt`

---

## Unresolved Placeholder

Occurs when:

- optional feature not configured
- telemetry missing
- template updated without mapping update

Impact:

- partial card degradation
- diagnostics report the issue
- `self_check` and release validation also report missing generated-card entity references

---

## Current Air Control Visual Contract

The panel must:

- match active lane
- reflect gate border color
- display correct chip state
- keep alert chipsets to the lane/status chip plus the resolved alert source/context chip only
- show alert source/context chips only while the backend runtime mode or alert activity state says an alert lane is active
- render backend `telemetry_unavailable` as degraded UI truth, not as normal/ready or unknown frontend failure
- treat missing, unavailable, or unrecognized Air Control Mode telemetry as `UNKNOWN` without inventing a normal lane
- show readable reason text
- treat exact `hi.reason.v1` as the sole normal V2 reason authority: render only its
  escaped headline and ordered backend-authored line text
- reject an absent, malformed, unsupported-locale, or future reason contract as a
  whole and fall back to escaped `full_reason`, usable state, then `Reason
  unavailable.` without partial rendering
- preserve the 60-pixel keyboard/touch scroll region and keep calm neutral reasons
  visible
- stay synced with real hardware behavior

If mismatch occurs:

- run `humidity_intelligence.refresh_ui`
- re-export cards
- check diagnostics

---

## Versioned UI Contract Notes

### Published v2.0.10 Contract

- V2 Mobile and Tablet use one strict mechanical `hi.reason.v1` consumer. They do not
  infer reason prose from mode, alerts, risks, timers, helpers, isolation, or
  humidifier attributes, and they do not add `Stage:` or `Engine:` text.
- Backend AQ explanations keep the observed condition and selected/blocked action as
  adjacent but distinct contract lines. Concurrent humidifier explanations follow as
  explicitly separate, self-contained household sentences; cards must not merge,
  relabel, summarize, or add bridge copy between those backend lines.
- The reason headline and every ordered line are escaped independently at the HTML
  sink. Invalid or future contracts fall back atomically; card code never renders a
  valid-looking subset of malformed data or reconstructs from `code`, `args`,
  `family`, `variant`, or `truth`.
- V2 Mobile and Tablet consume the backend `humidifier_status` attribute on the
  existing Air Control Reason entity; they do not calculate control demand.
- Humidifier chips use `Downstairs Humidifier` / `Upstairs Humidifier` ordering and
  distinguish Requested, On, Idle, Isolated, Retrying, Stopping, Unknown, Degraded,
  and Fault. `On` is the concise card label for backend reconciliation state
  `output_on`: Home Assistant has observed the configured output on, but this does
  not claim physical moisture production.
- Ventilation and humidifier chips share one accessibility-labelled, horizontally
  scrollable Current Air Control row. Humidifier demand and reconciliation remain
  independent of ventilation lane selection; layout does not merge their semantics.
- `On` and `Requested` humidifier chips use cyan; `Idle`, `Retrying`, `Stopping`, and
  `Isolated` use amber; `Fault` and `Degraded` use red; and `Unknown` uses grey.
- Humidity Danger chips show the concise backend context through the resolved zone
  (`Humidity Danger · room · zone`). Measurements and thresholds remain available in
  the backend alert context, structured alert telemetry, and reason explanation;
  other alert contexts are not shortened.
- The existing humidifier-active helpers are fallback demand truth for older rendered
  cards and no longer justify a “running” claim.
- Already-pasted Manual cards are static and require a fresh `refresh_ui` plus
  `dump_cards`/`view_cards` export and paste to receive this contract.
- HI exports Manual-card fragments, not complete dashboard documents. Leave existing
  registered or YAML-mode dashboard files unchanged. Create or open a dashboard
  through Home Assistant and add a Manual card, or replace the complete YAML of an
  existing HI Manual card; `refresh_ui` remains cache-only.
- V1 Mobile behavior and public entities are unchanged.

### v2.0.9 Current Contract

- V1 Mobile remains exportable through the v2.0.9 line but is deprecated for new
  dashboards; use V2 Mobile for new installs.
- Dynamic V1 room labels, target-profile labels, condensation context, and mould
  context are escaped before insertion into HTML.
- Already-pasted V1 Manual cards are static and must be re-exported and re-copied to
  receive the escaping fix.
- V1 Mobile removal is deferred to a separately approved v2.1 migration proposal.

### v2.0.5 Current Contract

- `show_output_entity_details` controls only the expandable generated-card output details panel.
- Hiding output details must not affect lane selection, output writes, isolation switches, diagnostics, or entity names.
- Optional Level 1 / Level 2 display labels are configured from setup Zones and post-configuration Zone Options before Zone 1 / Zone 2 editing. They are generated-card/config-flow/support text only. Empty labels fall back to `Level 1` / `Level 2`, and changing labels requires refreshed/exported card YAML for already-pasted Manual cards.
- New generated V2 cards default to the cleaner output display unless output details are enabled.
- `v2_tablet` is the default first-install UI export layout.
- `humidity_intelligence.dump_cards` remains the supported export path after UI visibility, template, or mapping changes.
- Generated-card consumers must use `/config/humidity_intelligence/ui/`; legacy
  config-root YAML is retained and is not refreshed, migrated, or purged.
- Already-pasted Manual cards are static; refresh/export updates HI output files, not the pasted card content.

### Historical v2.0.2 UI Contract Updates

- Humidity badge colors are now target-relative:
  - `below_target` = blue
  - `in_target` = green
  - `above_target` = yellow
  - `high_risk` = red
- Target humidity display includes the active season/profile label (`Spring`, `Summer`, `Autumn`, `Winter`, or `Custom`).
- Reason window includes expanded humidifier logic context from runtime telemetry (lane scope, trigger condition, thresholds, and recovery behavior).

### Historical v2.0.4 UI Contract Updates

- Alert chipsets must not add redundant helper-switch chips after the resolved alert context.
- Chip rows expose a longer scroll reset delay marker (`15000ms`) so mobile/touch layouts are not aggressively snapped back while being read.
- Alert source chips should use `HI Active Alert Context`, backed by runtime alert telemetry, rather than inventing display-only context.

---

## Legacy v1 UI Support

`v1_mobile.yaml` remains compatible with the V2 engine through v2.0.9, but is
deprecated for new dashboards. Prefer `v2_mobile.yaml`.

Legacy support keeps the V2 backend contract. V1 backend templates and packages stay
retired.

Backend must be fully removed before using V2 runtime. Removing the V1 presentation
skin is a separate proposed v2.1 change with an explicit user migration and rollback
plan; v2.0.9 does not remove it.

---

## UI PR Checklist

- no stale placeholders
- no hardcoded alert counts
- canonical badge names preserved
- gate border sync maintained
- reason text remains readable

Humidity Intelligence V2 UI is a structured runtime interface for a deterministic environmental engine.
