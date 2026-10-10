# Stability Score testing

Status: formula 4 with UI revision 7 in the current unreleased 2.1.0-rc.1 candidate. This guide describes
validation of [the canonical contract](stability-score-accepted-baseline.md); it is
not a release, deployment or live-observation claim.

## Offline validation

Run from the repository root in the project test environment. Native Home Assistant
options/config-flow suites require a supported Home Assistant installation and must
run separately from the stub-based suites below:

See [native configuration-flow testing](config-flow-testing.md) for Save/Cancel,
disk persistence, fixture cleanup and the separate interpreter-shutdown limitation.

```sh
python3 -m pytest "tests 2"/test_stability_*.py tools/stability-scenario/test_scenario.py
node --test "tests 2/test_stability_badge_renderer.mjs" "tests 2/test_stability_badge_interaction.mjs" "tests 2/test_stability_presentation.mjs"
python3 scripts/stability_scenario.py --output /tmp/hi-stability-scenario.html
```

Open the generated HTML in a browser. It uses real scoring/movement code and the
shipped renderer with synthetic inputs only. It has no Home Assistant connection,
cannot seed live history and cannot operate outputs. Check all 12 stages, play/pause,
speeds, scrubbing, stage jumps and all four LED-colour moments. The full replay covers
2490 synthetic buckets; this is never 72 hours of observed live runtime. The replay
regression also sends every backend snapshot through the shipped renderer: available
scores must retain a valid headline and reconciled deductions, while unavailable
scores must not acquire a calculation.

| Area | Required regression evidence |
| --- | --- |
| Formula | All six components; inclusive seasonal/custom bounds; nearest-rank p95; timestamp-based recovery through gaps; missing drift treatment |
| AQ | Per-level individual-first selection; configured IAQ fallback only without individual conditions; no outage fallback; selected-input coverage and consistent clearance/recovery/adjustment; CO isolation; configured thresholds/units, unmapped and partial evidence; fresh baseline after policy change |
| Coverage | 432 expected buckets, 303 valid eligibility, consecutive-pair and balance eligibility, fixed 144-bucket sustained-risk denominator |
| Caps/adjustment | Retained CO/danger/incomplete-evidence safeguards; routine AQ has no 54/69/91 ceiling; 12-point additional adjustment at crossing, six observed-clear hours, missing/gap pause, repeated crossing reset, no unknown-interval credit; valid live observations may support recovery despite a missing scheduled graph point |
| Availability | Collecting, evidence gaps, balance evidence, live required data absent, malformed/missing payload, boolean/array/string/non-finite/out-of-range scores and contradictory availability; never invented health |
| Scheduler | UTC boundaries, first strictly future sample, 60-second grace, no backfill, invalid/duplicate buckets, exceptions, unload and reload |
| Failure history | Unique observed failures only; late-range bounds; no future or pre-setup inference; valid-bucket reconciliation; expiry and reset; missing history unavailable |
| Movement | Atomic headline/reference/net/latest-delta publication; first actual observation per ten-minute slot, at most seven within 60 minutes; actual span and shorter warm-up; one net angle conversion and round trips; latest-update colour on either arc side; expiry-only neutral/no pulse; exact eleven-minute continuity boundary; unavailable/source-reset/restart; duplicate/out-of-order timestamps; pure reads and unchanged graph history |
| Rendering | Four identical Mobile/Tablet/gallery renderers; 82px footprint; classification halo; independent soft-green/bright-green/orange/red LEDs; blue baseline collection; 6s Partial pulse and reduced motion |
| Collection rendering | One blue tick per valid sample at 0, 1, 4, 151, 302 and 303; centred slots and hidden origin after first tick; strict integer count/target bounds and matching rounded backend ratio; no early full circle; separate red fixed-slot history; malformed history fails closed |
| Interaction | Whole-badge tap/click/keyboard; detached snapshot dialog; sticky Close/Escape/backdrop; focus restoration; deduplication; refresh, navigation and owner-removal cleanup; unsupported-modal Diagnostics fallback; existing badge is focusable; Enter/short Space retain normal tap, held Space uses the hold action |
| Presentation preference | Hold-only toggle, visible Disabled aurora/LEDs, retained tap details/history, native authenticated HA user-data boolean, refresh/cross-session persistence, user/opaque-entry isolation, explicit read/save failure feedback, no extra control or localStorage fallback, no backend/control effects |
| Score explanation | Backend headline and qualifier; reconciled rows and total; one bottom calculation; 64.91 calculated / 65 displayed / 91 ceiling; ties-to-even rounding, exact zero and deductions above 100; missing, contradictory or malformed arithmetic remains unavailable |
| Score history | Actual ten-minute scores, 432-slot bound, fixed 0–100 scale, disconnected gaps, single point, empty/null-only/malformed history, interval-specific counts, no read-driven growth/backfill, restart reset and expiry, separate latest update; full Stability attribute excluded from Recorder, no history duplication in the legacy summary |
| Autumn | Inclusive 50–60 band and unchanged 64 high-risk boundary; auto September–November and explicit autumn; other seasons, custom/legacy overrides and temperature unchanged; target-relative mould and humidifier recovery; missing high-risk UI evidence neutral |
| Control/privacy | No Stability output writes, lane/gate changes or humidifier authority; canonical Manual/CO regressions; sanitized support exports |

Render a synthetic Poor-score example with +5 then −2 against the same reference:
net +3 remains on the positive arc, the latest −2 is orange, and the Poor halo stays
red. Separately show above-target humidity with an improving score, cap plateaus,
reference expiry without a score change, short coverage, a fresh baseline after a
long publication gap and unavailable/Partial states. Use actual backend outputs;
these fixtures do not establish live environmental or physical-client behavior.

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

## Historical beta.11 browser evidence

The beta.11 run on 2026-10-04 recorded **72 passed, 2 not-run and zero failures**
across Mobile and Tablet, using Chrome **154.0.8037.58**, WebKit **26.5**, Playwright
**1.62.1** and button-card **7.0.1**. Chrome exercised touch hold and Space hold;
WebKit exercised Space hold, refresh persistence, unavailable data and tap details.
The remaining interaction cases retain their existing coverage. The two not-run
results are WebKit arbitrary touch sequences unsupported by this runner, not passes.

Two responsive-review groups produced 60 fixture captures at 320, 390, 430, 820 and
1024 pixels, including the visible Disabled badge and expanded history. The corrected
HA-card substitute uses the shadow-host block layout; native-dialog fixture styles
do not override production HI dialog sizing. Both layouts retained the 82px badge,
44px Close target and overflow-free history at these widths.

User data and telemetry remain synthetic. These results do not validate installed
Home Assistant persistence or physical devices, and emulated WebKit is not physical
iOS Safari. See the [browser harness](../tests%202/browser_touch/README.md) for commands
and limitations; the final source-bound report owns aggregate package and release
validation.

## Beta.12 candidate checks

The offline run on 2026-10-07 also recorded **72 passed, 2 not-run and zero failures**
across the generated Mobile/Tablet layouts. The changed movement cases exercise a
Poor score with a net gain and latest fall, followed by a neutral expired reference.
These are controlled published-score vectors through the actual movement helper;
their headline/explanation fixtures come from the synthetic backend replay. They
are not live observations or a physical humidity trajectory. Populated history,
gaps, unavailable/Partial states, both preference directions and refresh persistence
remain fixture evidence. The WebKit and physical-device limitations above still apply.

An uncommitted candidate is identified by its source-file inventory and package-file
hashes. Commit-bound packaging and any later installed evidence must be verified
against the final committed candidate; an earlier beta's soak cannot supply that proof.

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
Score history has no durable persistence, Recorder recovery or startup backfill.
The saved badge display preference is separate from that history.

For UI revision 7, review the recent reference, actual comparison interval, headline,
deduction table and existing history expander at narrow phone, wider phone and tablet widths. Check that labels remain readable,
content does not overflow, and Close remains reachable when the history is expanded.
Keep offline fixture screenshots labelled as synthetic; supplied state captures that
predate this change are not evidence of the revised explanation or history.

Validate saved generated Mobile/Tablet YAML and actual target clients. Check compact
layout and escaping, Partial/condition distinctions, independent movement colour,
changed-mark fade, reduced-motion static treatment, and every dialog dismissal path.
Exercise the actual button-card action with touch and keyboard, including the label
and surrounding badge area. Check Close, Escape, backdrop, reopen, multiple badges,
focus restoration and cleanup after navigation or owner removal. While open, trigger
an ordinary Diagnostics refresh: the labelled snapshot and Close control must remain
usable, and reopening must show current evidence. Verify native Diagnostics more-info
fallback when `showModal` is absent. Native Activity is not a replacement telemetry panel.

Hold the existing Stability badge in both directions. Disabled must retain its
footprint, static aurora/LEDs and tap details; backend unavailability must not erase
that preference. Confirm persistence after refresh, user/entry isolation and explicit
read/save failures. Drag cancellation must not toggle it. Use the existing focused
badge for keyboard testing: Enter and short Space retain normal tap, while held
Space performs the same hold action. Cancellation, focus loss and key repeat must
not create extra toggles. No extra visible control or scoring/history reset is part
of the preference.

A browser screenshot alone proves neither dynamic movement nor mobile touch handling.
Standalone renderer/DOM tests do not reproduce every Home Assistant gesture path.
Phone/tablet opening and dismissal remain unverified until exercised on those actual
clients; earlier desktop collection-popup evidence does not resolve reported touch failures.

Live checks must distinguish complete AQ from no hardware, configured-unmapped,
insufficient historical coverage and unavailable current evidence. Retain exact
observation times and gaps; do not infer missing checkpoints or transfer evidence from
another package. Lab evidence remains optional advisory context, never a release gate.

Earlier recorded candidate checks established collection UI at zero samples and an empty,
available failure history. They do not establish a completed 303-sample baseline,
sustained soak, injected live failure or observed live red mark. Dense failure-history
rendering has structural regression coverage but remains visually unverified; the
compact ring may merge nearby marks, so use the backend count in details. Deploying
a beta to a production instance is not publication as a Stable release.

Rollback restores the package plus a restart and separately restores dashboard YAML.
Both restarting the new package and reverting it discard the in-memory baseline.
