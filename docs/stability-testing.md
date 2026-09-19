# Stability Score testing

Status: accepted baseline under local unreleased integration. This guide describes
validation of [the canonical contract](stability-score-accepted-baseline.md); it is
not a release, deployment or live-observation claim.

## Offline validation

Run from the repository root in the project test environment:

```sh
python3 -m pytest "tests 2/test_stability_score.py" "tests 2/test_stability_scheduler.py" "tests 2/test_stability_fault_isolation.py" "tests 2/test_stability_readable_diagnostics.py"
node --test "tests 2/test_stability_badge_renderer.mjs"
python3 scripts/stability_scenario.py --output /tmp/hi-stability-scenario.html
```

Open the generated HTML in a browser. It uses real scoring/movement code and the
shipped renderer with synthetic inputs only. It has no Home Assistant connection,
cannot seed live history and cannot operate outputs. Check all 12 stages, play/pause,
speeds, scrubbing, stage jumps and all four LED-colour moments. The full replay covers
2490 synthetic buckets; this is never 72 hours of observed live runtime.

| Area | Required regression evidence |
| --- | --- |
| Formula | All six components; inclusive seasonal/custom bounds; nearest-rank p95; timestamp-based recovery through gaps; missing drift treatment |
| AQ | Configured conditions, per-level averaging, IAQ direction, PM2.5/VOC/CO2/CO thresholds and units; unmapped, unsupported, partial, unavailable and no-hardware states |
| Coverage | 432 expected buckets, 303 valid eligibility, consecutive-pair and balance eligibility, fixed 144-bucket sustained-risk denominator |
| Caps | Current CO 0; current danger/AQ 54; prior-12h CO 54 and danger/AQ 69; incomplete AQ and sustained risk 91; strictest cap and backend headline |
| Availability | Collecting, evidence gaps, balance evidence, live required data absent, malformed/missing payload, boolean/array/string/non-finite/out-of-range scores and contradictory availability; never invented health |
| Scheduler | UTC boundaries, first strictly future sample, 60-second grace, no backfill, invalid/duplicate buckets, exceptions, unload and reload |
| Movement | Signed ±360 endpoints; retained position/colour on steady; reversal and origin crossing; saturation; unavailable resets versus read-time hiding; skipped callback no movement |
| Rendering | Four identical Mobile/Tablet/gallery renderers; 82px footprint; classification halo; independent blue/green/orange/red LEDs; 6s Partial pulse and reduced motion |
| Interaction | Tap/click/keyboard details; Close/Escape/outside dismissal; hold opens Diagnostics; readable summary; Popover client compatibility |
| Control/privacy | No Stability output writes, lane/gate changes or humidifier authority; canonical Manual/CO regressions; sanitized support exports |

Classifications are Excellent 92–100, Good 70–91, Unstable 55–69 and Poor 0–54.
An eligible historical AQ component below 100% can produce Excellent Partial when
current AQ is complete; partial historical coverage alone does not impose the 91 cap.
`count/303` means eligibility, while details `count/432` means rolling coverage.
Neither denominator should be changed just to make them match.

## Authorized installation and client checks

Deployment, restart and dashboard replacement require their own authorization.
When testing an installed package, record its exact source revision and package hash;
preserve package and dashboard rollback copies separately. Run the appropriate full
Python/control suite and generated-card sanity checks alongside targeted tests.

After an authorized install, restart Home Assistant, verify loaded identity and
sampling diagnostics, regenerate via `refresh_ui` and `dump_cards`/`view_cards`,
replace complete pasted cards, then refresh the frontend/cache. No configuration,
stored-data or entity migration is required. Restart or entry reload resets history:
303 new valid observations are needed, about 50h20m after the first sample without gaps.
There is no durable persistence, Recorder recovery or startup backfill.

Validate saved generated Mobile/Tablet YAML and actual target clients. Check compact
layout and escaping, Partial/condition distinctions, independent movement colour,
changed-mark fade, reduced-motion static treatment, and every popover dismissal path.
A browser screenshot alone does not prove dynamic movement. Modern Popover API support
is required; update older WebViews and use readable Diagnostics while resolving that
compatibility gap. Native Activity is not a replacement telemetry panel.

Live checks must distinguish complete AQ from no hardware, configured-unmapped,
insufficient historical coverage and unavailable current evidence. Retain exact
observation times and gaps; do not infer missing checkpoints or transfer evidence from
another package. Lab evidence remains optional advisory context, never a release gate.

Rollback restores the package plus a restart and separately restores dashboard YAML.
Both restarting the new package and reverting it discard the in-memory baseline.
