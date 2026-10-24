# Full-layout touch regression

This harness runs the complete **production-generated** V2 mobile and tablet trees,
with native and adaptive Outputs variants. It loads unmodified button-card 7.0.1
and the repository's actual adaptive resource. No copied third-party library is
committed. Every entity, history response, user and service result is synthetic.
The server binds only to loopback, and browser requests outside that origin are
blocked. Nothing connects to Home Assistant or controls a household device.

## Run

Use a disposable Python environment with PyYAML and Node with Playwright.
Record the actual Playwright version with each run. Install Chromium and WebKit for the full matrix. Obtain the unmodified
[button-card 7.0.1 release](https://github.com/custom-cards/button-card/releases/download/v7.0.1/button-card.js)
and set `BUTTON_CARD_PATH` to that local file. The runner rejects any other SHA-256:
`5d6e9c6afca01e8014653fa56bb5d6aa9248d832c34fb944a7f2c36329bc22d1`.

From the repository root:

```sh
python 'tests 2/browser_touch/build_fixture.py' --output output/playwright/browser-touch
BUTTON_CARD_PATH=/path/to/button-card.js \
  FIXTURE_DIR="$PWD/output/playwright/browser-touch" \
  VISUAL_REVIEW=1 \
  node 'tests 2/browser_touch/run.mjs'
```

Playwright resolves from Node's module path. Alternatively set `PLAYWRIGHT_MODULE`
to the installed `playwright` package directory. `BROWSERS=chromium` narrows an
investigation; omit it for both engines. `CHROME_CHANNEL=chrome` uses an installed
Chrome instead of bundled Chromium. `TOUCH_CASE=substring` selects cases for
investigation and **does not constitute a complete suite pass**. `VISUAL_REVIEW=1`
adds two Chromium responsive-review groups across 320, 390, 430, 820 and 1024 pixels,
producing 60 captures plus layout measurements; omit it for interaction checks only.

Preference fallback cases inject subscription rejection and timeout in both browser
engines and layouts. They check rendered gauge visibility during loading and failure,
retained tap details, backend no-score truth, and absence of preference or control writes.

The runner writes `results.json` and failure screenshots into `FIXTURE_DIR`.
The JSON includes the dependency hash, actual browser/Playwright versions,
viewport profile, user agent, coarse-pointer capability and actual
`navigator.maxTouchPoints`. WebKit's reported touch-point count may be zero in
emulation even when trusted browser touch events are delivered; the harness does
not override that property. Genuine touchscreen events are separately recorded.
The fixture also records source hashes and the production update adapter used to
normalize synthetic HACS states; the result records the exact fixture digest.

## What is real, and what is substituted

Real: browser touch input, DOM/shadow DOM, button-card templates and action/hold
handling, native dialogs and keyboard input, generated HI layout configuration,
HI dialog/history/idle code, adaptive output code and nested custom-element
lifecycle. The fixture never calls a dialog opener instead of tapping its control.

Substitutes: HA stack/grid/mod-card wrappers, icons, entity rows, more-info panels,
and the HA-shell `hass-action` dispatcher. The dispatcher routes only the actions
used by these cards: real `ll-custom` callbacks, more-info events, and recorded
service requests. It updates synthetic state for toggle responses. Native entity
rows are explicitly labelled fixture controls; this does not validate HA's actual
entities card, native frontend controls, theme/card-mod fidelity or physical-device
behavior. History endpoints return bounded generated samples, not Recorder data.
Frontend user-data requests use a synthetic preference store and subscription shim;
refresh persistence exercises that store, not an installed HA user's saved settings.
The HA-card substitute uses a block, border-box, positioned shadow host with a slot;
this avoids treating a card as an empty inline element in narrow-width checks.
Fixture dialog sizing applies only to native more-info stubs, preserving production
HI dialog width and overflow behavior.

Chromium CDP dispatches trusted touch sequences for hold, drag, cancellation and
two-finger cancellation. Both engines use Playwright's trusted touchscreen tap.
WebKit has no public arbitrary-touch-sequence API in this runner: hold/drag/
multitouch sequences are explicitly `not-run`, never replaced with DOM
`dispatchEvent`. Desktop WebKit with an iOS user agent is **not physical iOS Safari**.

Clock acceleration exercises the production 120-second timers. It does not claim
wall-clock or background-tab timing on an actual phone. Parent controls are inert
while a native modal is open, so impossible parent-only interaction during that
modal is covered by separate component unit tests, not fabricated browser input.

## Coverage

- Mobile 390px and tablet 1024px touch contexts in both engines.
- Full layout mount and all ten custom badge/explanation dialogs.
- LED dot, label and enlarged hit area; keyboard, rapid reopen and dismissal.
- Combined UI/software footer in both native and adaptive variants: independent
  UI revision and provider-reported statuses, skipped releases, a manual beta ahead
  of the offered release, in-progress updates, and visible missing/unavailable
  coverage. Synthetic HACS registry states run through the production adapter.
- All 20 combinations of four UI revision states and five provider states in both
  variants and engines, with live transitions back to quiet. Computed visibility
  hides only the no-update cue; its detail and accessible status remain available.
  The revision LED and label stay left while visible software cues align right,
  with no separator. The positive cue uses **Update available**.
- Exact update-entity more-info handoff with no service writes; stale provider
  state/version and changed source identity refuse the captured action. Version
  strings remain escaped text. Disconnect/reconnect requires fresh evidence,
  duplicate cards retain separate ownership, and removal cleans up open details.
- Footer and details fit at 320px, 390px, and the layout's default width, with
  non-overlapping labels and a real 44px minimum touch target. Chromium captures
  are generated for these cases even without `VISUAL_REVIEW=1`.
- A local 2× font-size and line-height override stresses wrapping at narrow widths,
  including growth of the owning card. It does not emulate an OS accessibility
  text-size setting or establish physical-device behavior.
- Embedded history, range changes, Back and native source handoff.
- System/Manual valid and unavailable states with service spies; native Outputs
  toggles exactly once; Chromium hold routes do not also toggle on release.
- Adaptive expansion, evidence/guidance, source inspection, native-row handoff,
  backdrop, Escape and parent/child inactivity reset and reopen custody.
- Stability hold in both directions, visible Disabled treatment, refresh persistence,
  unavailable backend evidence, retained tap details, save failure, drag cancellation
  and static reduced-motion treatment. The existing badge is focusable; Enter/short
  Space retains normal tap, held Space performs the hold action. No extra control
  is added; cancellation, focus loss and repeat must not produce extra toggles.
- Chromium badge/chip drag cancellation and footer hold/drag/cancel/multitouch.
- Disconnect, ready-without-evidence, fresh evidence and owner removal.
- Trusted interaction renews inactivity; passive state updates do not.

A complete result must contain both engines and layouts. Investigative narrowed
runs and explicitly unsupported sequences must be reported separately from passes.
The update tests do not establish installed HACS behavior, release-channel freshness,
download/install correctness, or compatibility with a particular physical device.

## Historical beta.11 browser check

The 2026-10-04 final run recorded **72 passed, 2 not-run and zero failures**, with
Chrome **154.0.8037.58**, WebKit **26.5**, Playwright **1.62.1** and verified button-card
**7.0.1** bytes. It includes both layouts, the existing interaction cases, Chrome
touch/Space holds, WebKit Space holds and the two responsive visual groups.

The two not-run results are the unsupported WebKit arbitrary touch sequences
explained above. They are not silently counted as passes. The visual groups produced
60 fixture captures at five widths, preserving the badge footprint and history
layout with the corrected shadow-host substitute. Physical devices and installed
Home Assistant persistence remain unvalidated; the source-bound report owns package,
review and release conclusions.

## Beta.12 browser check

The 2026-10-07 candidate run recorded **72 passed, 2 not-run and zero failures**.
Both generated layouts include the bounded recent-score renderer. The two unsupported
WebKit touch sequences remain not-run. Recent movement uses a controlled 49→54→52
published-score vector: the current Poor score stays 52, recent change is +3, and
latest change is −2. Its expiry case retains 52 with neutral LEDs and no old arc.
These cases use the actual movement helper with synthetic calculated headline and
explanation fixtures; they do not model an observed household or physical RH history.

The responsive group captures these cases and their scrolled details at five widths,
alongside collection, Partial, unavailable, Disabled and populated history. Fixture
preferences, browser emulation and rendering do not establish installed persistence
or physical-device behavior. Keep the exact source inventory with each run's receipts.

## v2.1.1-beta.3 browser check

The 2026-10-17 candidate run recorded **128 passed, 2 not-run and zero failures**
with Chromium **153.0.8010.12**, WebKit **26.6**, Playwright **1.63.0**, and the verified
button-card **7.0.1** dependency. The 48 new footer groups cover both layouts, both
output variants and both engines; the existing interaction and Stability visual
groups also passed. WebKit arbitrary touch sequences remain explicitly not-run.

This is local synthetic browser evidence. It does not claim a beta.3 deployment,
physical-device testing, installed HACS verification, or a completed soak.

## v2.1.1-beta.4 browser check

The 2026-10-18 candidate run recorded **136 passed, 2 not-run and zero failures**
with Chromium **153.0.8010.12**, WebKit **26.6**, Playwright **1.63.0**, and verified
button-card **7.0.1** bytes. All 56 footer groups passed, including the 20-state
UI/provider matrix in each layout/variant/engine, quiet-state return transitions,
computed visibility and alignment, and narrow-width 2× font-size stress. The
existing interaction and Stability visual groups also passed.

The two unsupported WebKit arbitrary touch groups remain not-run. These results
are synthetic local browser evidence; they do not establish a beta.4 deployment,
installed HACS behavior, physical-device accessibility or soak completion.
