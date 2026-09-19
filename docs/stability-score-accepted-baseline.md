# Accepted Stability Score baseline

Status: accepted functional and presentation contract; local unreleased integration.
This records the accepted behaviour for the current implementation work. It does not
claim publication, HACS availability, deployment, or a newly approved release version.
Historical release notes retain their original scope.

Stability is integrated alongside the current control engine. Existing Manual handover,
CO precedence, independent humidifier authority and reason presentation remain intact.
Material changes to calculation, evidence, movement, layout or interaction require an
explicit maintainer decision; documentary corrections must follow source and tests.

## Protected architecture and source map

Stability is observational: no lane selection, gate changes, output service calls,
hidden automation, competing writer, or humidifier-control changes. Preserve CO-first
ventilation priority and independent humidifier authority. Optional frontend resources
must not block backend operation. Existing control entities and native states remain
unchanged; the readable Diagnostics attribute is additive.

Implementation anchors in this repository:

- `custom_components/humidity_intelligence/helpers/stability.py`: window, formulas,
  caps, availability, movement, presentation and input normalization.
- `custom_components/humidity_intelligence/helpers/air_quality.py`: configured AQ
  thresholds, units, condition coverage and level aggregation.
- `custom_components/humidity_intelligence/sensor.py`: scheduler lifecycle,
  Diagnostics telemetry and readable explanation.
- `custom_components/humidity_intelligence/services.py`: shared runtime Diagnostics
  payload and privacy-filtered support export; the sensor consumes this shared builder.
- `custom_components/humidity_intelligence/diagnostics.py`: native downloadable
  diagnostics, separately from the live sensor and service export.
- `custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml` and
  `v2_tablet.yaml`: renderer, animation, compact labels and interactions.
- `ui-gallery/default-v2-mobile-aq/card.yaml` and
  `ui-gallery/default-v2-tablet-zone-1-cooking/card.yaml`: identical gauge contract.
- `scripts/stability_scenario.py`, `tools/stability-scenario/index.html`: independent
  controllable scenario using actual backend and shipped renderer.

## Calculation, inputs and history

The rolling window is 72 hours, with 432 fixed ten-minute UTC buckets. A score needs
303 valid samples (70%, rounded up). The sampler runs at UTC minutes
00/10/20/30/40/50, first strictly after setup. There is no immediate setup sample or
startup/offline/restart backfill. More than 60 seconds late means skip. Invalid samples
cannot populate an empty bucket or replace a complete sample; the last complete
scheduled observation is the bucket representative. Exceptions must not stop future
scheduling. Bounded sampling diagnostics report status, latest bucket and missed count.

History and movement are in memory only. Restart or entry reload resets both; 303 new
valid samples are required. There is no Recorder recovery, durable ring persistence,
synthetic seeding or interpolation. With uninterrupted capture, eligibility takes
50h20m after the first sample, up to about 50h30m after setup. Preserve this limitation
explicitly rather than promising restart continuity. A future persistence change is a
material proposal, not an implied part of acceptance.

Inputs: HI house humidity and active seasonal/custom target bounds; worst condensation
and mould states; distinct mapped room/level humidity; seven-day humidity drift;
enabled per-level AQ conditions and saved thresholds; current runtime and CO truth.
Missing live required humidity/target/condensation/mould truth suppresses a historic
score immediately. Required values must be finite and valid. Unknown is never healthy.

| Component | Weight | Accepted calculation |
| --- | --- | --- |
| Target adherence | 30% | Fraction of valid samples inside inclusive bounds captured with each sample |
| Volatility | 15% | `1 - clamp(p95(abs(consecutive ten-minute RH change)) / 12)`; nearest-rank p95; at least 70% of `valid_count - 1` possible pairs |
| Balance | 15% | `1 - clamp(p95(spread) / 10)`; at least 70% of valid samples have balance evidence |
| Risk clearance | 15% | Equal average of condensation, mould and eligible drift clearance; OK=1, Watch=.75, Risk=.25, Danger=0; drift clear when absolute drift <=5 RH points |
| AQ clearance | 15% | Mean eligible sample clearance; conditions averaged within each level, then levels equally weighted |
| Recovery | 10% | `1 - clamp(median(excursion duration hours) / 12)`; full-envelope excursion closes at next stable observation; open excursion includes one final bucket and caps at 12h; elapsed timestamps include gaps |

Clamp component ratios to [0,1]. Balance deduplicates entity mappings, averages
readings within each distinct room, and takes maximum minus minimum average; use at
least two rooms, falling back to at least two levels. Duplicate mappings do not create
independent evidence. Full-envelope recovery uses the source's combined humidity,
condensation/mould, available drift and AQ conditions; preserve its exact missing
component treatment and timestamp behaviour through fixtures.

AQ is based on configured conditions, not merely visible sensor chips. IAQ crosses
at or below threshold; PM2.5/VOC/CO2/CO at or above. Accepted units: IAQ unitless/index,
PM2.5 micrograms/m3 (supported normalized spellings), VOC ppb, CO2/CO ppm. Unsupported
units and invalid thresholds are missing evidence, not clear air or a crossing.
Configured readings of a type are averaged within their level. No AQ hardware,
unmapped conditions, insufficient historical coverage and current unavailable evidence
must remain distinguishable in diagnostics.

## Missing evidence, penalties and caps

Below total coverage, insufficient consecutive-pair coverage, or insufficient balance
coverage: no score. With adequate overall coverage:

- Coverage penalty: `round((1 - coverage_ratio) * 10, 2)`; backend ratio is rounded
  to four decimal places.
- Drift coverage below 70%: omit drift from risk averaging and subtract 3 points.
- AQ condition coverage below 70%: omit AQ weight, renormalize other weights by .85,
  subtract 3 points and apply incomplete-AQ cap.
- Eligible partial AQ: include AQ component and subtract
  `min(3, round((1 - AQ coverage) * 10, 2))`.
- Clamp penalized result to 0–100 and retain a two-decimal `window_score`.
  Headline uses Python integer rounding, then the strictest applicable cap.

| Condition | Maximum headline |
| --- | --- |
| Current backend CO emergency | 0 / Poor |
| Current condensation/mould Danger or configured AQ crossing | 54 / Poor |
| Recorded CO emergency in prior 12 hours | 54 / Poor |
| Recorded condensation/mould Danger or AQ crossing in prior 12 hours | 69 / Unstable |
| Incomplete current AQ evidence, or unavailable historical AQ component | 91 / Good |
| Condensation Risk, mould Risk or AQ crossing in >=10% of fixed 144 expected buckets over 24h (at least 15 buckets) | 91 / Good |

Classification: 92–100 Excellent, 70–91 Good, 55–69 Unstable, 0–54 Poor.
Retain raw score, uncapped window score, penalties, all cap reasons and highest-priority
headline reason. No separate direct humidity-danger cap exists in this baseline.
The score is not an alarm, clean-air guarantee, physical health assessment or control
command. Certified alarms retain their authority.

## Presentation and interaction contract

Backend schema 3/formula 3 owns availability, displayed integer/classification,
labels, explanatory text, cap and evidence states, movement endpoints and colour token.
Frontend only renders presentation and visual geometry; it does not recalculate or
repair backend truth. Escape every dynamic text surface.

The receiving renderer validates displayed scores as numeric integers in 0–100 without
coercion. Malformed values, an available payload without a score, or an explicitly
unavailable payload carrying a stale score fail closed to a dash, neutral halo and
`NO SCORE`; stale presentation and movement are discarded. This maintainer-approved
correction preserves valid backend payloads, including a genuine numeric zero.

| Backend state | Visible presentation |
| --- | --- |
| Collecting | Valid count centred in circle; `Collecting baseline`; `OF 303` below label; clockwise LED fill from backend collection progress |
| Available complete | Displayed integer; `Stability Score`; backend classification label |
| Partial without stronger condition headline | Numeric score; `PARTIAL`; incomplete-evidence treatment |
| Insufficient consecutive evidence | Dash; `Evidence gaps`; `GAPS` |
| Insufficient balance | Dash; `Balance evidence`; `BALANCE` |
| Live required data absent | Dash; `Live data unavailable`; `LIVE DATA` |
| Missing/malformed/unavailable payload | Safe no-score presentation, never zero-as-a-score or invented healthy state |

Halo classification hierarchy: Excellent white, Good green, Unstable amber/yellow,
Poor red. Numeric Partial with known classification gently pulses between evidence
magenta and displayed-classification colour over six seconds. `PARTIAL` is shown when historical AQ coverage status is not `complete` and the
selected headline cap reason is absent or `air_quality_evidence_incomplete`. Other
selected headline reasons retain classification wording/colour, with partial evidence
still exposed in details. Historical AQ coverage of at least 70% but below 100%, with
complete current AQ evidence, can produce an Excellent Partial score: historical
partial coverage alone does not force the 91 cap. Missing score/unknown classification gets no Partial pulse.
Reduced-motion: static score-colour halo plus magenta marker by Partial; final LED
endpoint immediately; no motion. Preserve Excellent breathing and its reduced-motion
fallback. Do not couple independent LED colour back to halo colour.

Preserve accepted footprint: 82px gauge, centred numeric content (26px, 23px for three
digits), label below, compact status below label at 8px. No extra inner grey circle,
no visible dormant LED bank. Fine 0.8-degree marks spaced at three-degree intervals
sit on the outer edge; small top origin. Do not move or enlarge the badge during
integration. Exact CSS at baseline remains the visual reference.

During collection, the LED ring fills clockwise from the top using backend
`presentation.progress_ratio`, with `floor(ratio * 120)` illuminated marks. Accept
only finite numeric ratios in [0,1], without coercion; malformed progress stays
unlit. Incomplete progress cannot appear as a full ring. Collection uses the blue
collection colour and represents valid-sample progress, not elapsed time or score
movement. A ratio of 1 renders a full ring only while the backend still reports
collection. Transition immediately to backend-reported score or incomplete evidence;
do not hold completion, delay a score, or hide unmet evidence requirements.

Non-scored collection/evidence states also show a separate thin red failure-history
track inside the blue progress ring. It consumes backend
`sampling.failure_history` status, count, angles and description; the renderer does
not reconstruct failed buckets. Red marks represent known unsuccessful or missed
scheduled collections, not score decline, elapsed collection progress or samples
that count toward 303. The 82px badge footprint and readable central count remain.

Failure history contains at most 432 unique fixed ten-minute UTC slots in the rolling
72-hour window. Each bucket keeps a fixed modulo-432 angular position until it
expires; repeated reports deduplicate, and a later successful capture for the same
bucket removes its failure. Record only actual incomplete captures and known missed
scheduled buckets, never inferred offline or pre-setup gaps. Dense marks may overlap:
the popup's exact backend count is authoritative, not visual counting. Explain the
72-hour window in details. This history is retained only in memory and resets on
restart/reload alongside baseline samples. Available-score movement remains unchanged
and does not show this separate failure track.

Once a score is available, LED movement retains signed integer endpoints within [-360,+360]. Each scheduled
valid score comparison adds signed `ceil(abs(delta) * 3.6)` degrees, higher clockwise,
lower counter-clockwise. Saturate each step; at full circle hold until reversal.
Reversal retracts from retained endpoint, potentially crossing the origin. Steady
holds endpoint and colour; no per-cycle restart. Arc position is accumulated displayed
score movement, including cap changes, **not elapsed time**.

Independent colour: gentle rise blue `#38bdf8`, strong rise green `#4ade80`, gentle
fall orange `#fb923c`, strong fall red `#ef4444`. Strong means absolute rate >=5 score
points per ten minutes, normalized by actual positive comparison interval. Invalid
timing is neutral. The first scored movement baseline and unavailable states are
unlit; collection progress is the separate presentation described above. Scheduled unavailable truth resets
the chain; a later valid score establishes a new baseline. Read-time unavailable hides
the arc without mutating stored scheduled history. Late skipped callbacks add no move.

Only changed marks fade sequentially (138ms fade, 18ms stagger); retained marks remain.
Half-circle settles in about 1.2s, full circle about 2.4s; at most 120 marks per winding.
Crossing origin can render both windings temporarily. Invalid endpoints fail closed.

Tap/click/keyboard activation of gauge opens native Popover API details: backend
explanation and, while collecting, **Baseline progress: N of 303 valid samples**, using backend
`window.valid_samples` and `window.minimum_valid_samples`, never a hardcoded
denominator. During collection, details explain the clockwise sample-progress ring
and that score eligibility still depends on backend evidence requirements. Once
scored, **Recent trend** explains retained arc versus current colour plus exact
backend movement detail. Outside collection, the tally is explicitly labelled
**Rolling-window coverage: N of 432 valid samples**, using backend expected samples.
Close, Escape and outside
tap dismiss. Hold opens HI Diagnostics more-info. Readable Diagnostics attribute
exposes score, evidence and movement; native Activity is not a substitute telemetry
panel. Modern Popover-capable client required; older WebViews need explicit handling,
not a silent removal of the detail interaction.

`count/303` is progress toward the minimum sample requirement; it does not guarantee
score eligibility on its own. The 432 buckets remain the 72-hour rolling-window
capacity in backend telemetry and the separately labelled coverage tally, not the popup's baseline
target. This presentation change does not alter the sampling window or evidence gates.

## Scenario and acceptance coverage

The synthetic scenario uses actual backend calculation and the identical shipped
renderer. Play/pause, speed, timeline scrubbing, stage jumps and four LED-colour
moments are regression/demo controls. The scenario cannot connect to Home Assistant,
seed live history or operate outputs. Synthetic playback is separate from live evidence.
See [Stability testing](stability-testing.md) for the receiving validation matrix.

All four shipped card surfaces must preserve this contract: generated Mobile and
Tablet, and both default gallery cards. Repository `ui-gallery/` remains canonical;
the Wiki is an explanatory index. A passing static or synthetic check does not prove
animation or compatibility on an untested client.

## Installation, compatibility and rollback

No configuration, entity-registry or stored-data migration is required. The Diagnostics
readable attribute is additive; existing entity IDs and native states are unchanged.
After installing changed Python, perform a full Home Assistant restart. Restart and
entry reload discard in-memory history and movement and restart baseline collection.

Run `humidity_intelligence.refresh_ui`, then obtain fresh supported `dump_cards` or
`view_cards` exports. Replace the complete pasted Manual-card YAML and refresh the
browser/app frontend; clear its cache if it retains an older renderer. Existing pasted
cards do not update themselves. Validate Mobile, Tablet and the cards actually in use.

Use a modern Popover-capable browser/WebView for score details. On older clients,
update the browser/WebView and use the readable Diagnostics attribute to inspect truth
until compatibility is restored. A missing detail interaction is a compatibility gap,
not equivalent support for the accepted interaction.

Rollback has two parts: restore the preserved integration package and restart, and
separately restore saved dashboard/Manual-card YAML. Keep package backups outside
`custom_components`. Package rollback alone does not restore pasted cards. Restart
resets Stability history. Lab observation is advisory and is never a mandatory
promotion or release gate.
