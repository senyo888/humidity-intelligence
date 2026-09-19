# Stability Score testing

Status: implemented in the unreleased 2.1.0-beta.2 candidate. This guide describes
validation of [the canonical contract](stability-score-accepted-baseline.md); it is
not a release, deployment or live-observation claim.

## Offline validation

Run from the repository root in the project test environment:

```sh
python3 -m pytest "tests 2/test_stability_score.py" "tests 2/test_stability_scheduler.py" "tests 2/test_stability_fault_isolation.py" "tests 2/test_stability_readable_diagnostics.py" "tests 2/test_stability_failure_history.py" "tests 2/test_stability_live_pipeline.py"
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
| Failure history | Unique observed failures only; late-range bounds; no future or pre-setup inference; valid-bucket reconciliation; expiry and reset; missing history unavailable |
| Movement | Signed ±360 endpoints; retained position/colour on steady; reversal and origin crossing; saturation; unavailable resets versus read-time hiding; skipped callback no movement |
| Rendering | Four identical Mobile/Tablet/gallery renderers; 82px footprint; classification halo; independent blue/green/orange/red LEDs; 6s Partial pulse and reduced motion |
| Collection rendering | One blue tick per valid sample at 0, 1, 4, 151, 302 and 303; centred slots and hidden origin after first tick; strict integer count/target bounds and matching rounded backend ratio; no early full circle; separate red fixed-slot history; malformed history fails closed |
| Interaction | Whole-badge tap/click/keyboard; detached snapshot dialog; sticky Close/Escape/backdrop; focus restoration; deduplication; refresh, navigation and owner-removal cleanup; unsupported-modal Diagnostics fallback; hold opens Diagnostics |
| Control/privacy | No Stability output writes, lane/gate changes or humidifier authority; canonical Manual/CO regressions; sanitized support exports |

Classifications are Excellent 92–100, Good 70–91, Unstable 55–69 and Poor 0–54.
An eligible historical AQ component below 100% can produce Excellent Partial when
current AQ is complete; partial historical coverage alone does not impose the 91 cap.
During collection, both the badge and its popup show progress toward the backend
minimum of 303 valid samples. Once scored, popup rolling-window coverage uses 432
expected buckets. The sample threshold alone does not override consecutive-pair,
balance or live-evidence requirements. Red failed-bucket marks never add to progress.

## Diagnostics paths and package verification

The live Diagnostics sensor and native config-entry diagnostics expose Stability.
The existing `dump_diagnostics` support allowlist does not include Stability; absence
from that export alone does not prove that the sampler is inactive. Use the live
sensor or native download for this evidence.

Run `tests 2/test_stability_live_pipeline.py` without mocking the shared diagnostics
builder. Package tests build immutable Git source, so pre-commit tests against an older
HEAD do not validate newly added files. Validate a complete isolated candidate snapshot
and repeat the package checks against the final commit before push.

## Authorized installation and client checks

Deployment, restart and dashboard replacement require their own authorization.
When testing an installed package, record its exact source revision and package hash;
preserve package and dashboard rollback copies separately. Keep integration backup
and staging directories outside `custom_components`: duplicate manifests with the
same domain can interfere with integration discovery even when folder names differ.
Run the appropriate full Python/control suite and generated-card sanity checks alongside targeted tests.

After an authorized install, restart Home Assistant, verify loaded identity and
sampling diagnostics, and confirm the expected runtime fields and generated renderer.
On-disk manifest version and file hashes alone do not prove the loaded module identity.
If loaded behavior disagrees, inspect duplicate-domain discovery before repeating a
restart. Regenerate via `refresh_ui` and `dump_cards`/`view_cards`,
replace complete pasted cards, then refresh the frontend/cache. No configuration,
stored-data or entity migration is required. Restart or entry reload resets history:
303 new valid observations are needed, about 50h20m after the first sample without gaps.
There is no durable persistence, Recorder recovery or startup backfill.

Validate saved generated Mobile/Tablet YAML and actual target clients. Check compact
layout and escaping, Partial/condition distinctions, independent movement colour,
changed-mark fade, reduced-motion static treatment, and every dialog dismissal path.
Exercise the actual button-card action with touch and keyboard, including the label
and surrounding badge area. Check Close, Escape, backdrop, reopen, multiple badges,
focus restoration and cleanup after navigation or owner removal. While open, trigger
an ordinary Diagnostics refresh: the labelled snapshot and Close control must remain
usable, and reopening must show current evidence. Verify native Diagnostics more-info
fallback when `showModal` is absent. Native Activity is not a replacement telemetry panel.

A browser screenshot alone proves neither dynamic movement nor mobile touch handling.
Standalone renderer/DOM tests do not reproduce every Home Assistant gesture path.
Phone/tablet opening and dismissal remain unverified until exercised on those actual
clients; earlier desktop collection-popup evidence does not resolve reported touch failures.

Live checks must distinguish complete AQ from no hardware, configured-unmapped,
insufficient historical coverage and unavailable current evidence. Retain exact
observation times and gaps; do not infer missing checkpoints or transfer evidence from
another package. Lab evidence remains optional advisory context, never a release gate.

The recorded candidate checks establish collection UI at zero samples and an empty,
available failure history. They do not establish a completed 303-sample baseline,
sustained soak, injected live failure or observed live red mark. Dense failure-history
rendering has structural regression coverage but remains visually unverified; the
compact ring may merge nearby marks, so use the backend count in details. Deploying
a beta to a production instance is not publication as a Stable release.

Rollback restores the package plus a restart and separately restores dashboard YAML.
Both restarting the new package and reverting it discard the in-memory baseline.
