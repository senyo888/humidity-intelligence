# Full-layout touch regression

This harness runs the complete **production-generated** V2 mobile and tablet trees,
with native and adaptive Outputs variants. It loads unmodified button-card 7.0.1
and the repository's actual adaptive resource. No copied third-party library is
committed. Every entity, history response, user and service result is synthetic.
The server binds only to loopback, and browser requests outside that origin are
blocked. Nothing connects to Home Assistant or controls a household device.

## Run

Use a disposable Python environment with PyYAML and Node with Playwright 1.63.0.
Install Playwright's Chromium and WebKit browsers. Obtain the unmodified
[button-card 7.0.1 release](https://github.com/custom-cards/button-card/releases/download/v7.0.1/button-card.js)
and set `BUTTON_CARD_PATH` to that local file. The runner rejects any other SHA-256:
`5d6e9c6afca01e8014653fa56bb5d6aa9248d832c34fb944a7f2c36329bc22d1`.

From the repository root:

```sh
python 'tests 2/browser_touch/build_fixture.py' --output .codex/reports/browser-touch
BUTTON_CARD_PATH=/path/to/button-card.js \
  FIXTURE_DIR="$PWD/.codex/reports/browser-touch" \
  node 'tests 2/browser_touch/run.mjs'
```

Playwright resolves from Node's module path. Alternatively set `PLAYWRIGHT_MODULE`
to the installed `playwright` package directory. `BROWSERS=chromium` narrows an
investigation; omit it for both engines. `CHROME_CHANNEL=chrome` uses an installed
Chrome instead of bundled Chromium. `TOUCH_CASE=substring` selects cases for
investigation and **does not constitute a complete suite pass**.

The runner writes `results.json` and failure screenshots into `FIXTURE_DIR`.
The JSON includes the dependency hash, actual browser/Playwright versions,
viewport profile, user agent, coarse-pointer capability and actual
`navigator.maxTouchPoints`. WebKit's reported touch-point count may be zero in
emulation even when trusted browser touch events are delivered; the harness does
not override that property. Genuine touchscreen events are separately recorded.

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
- Embedded history, range changes, Back and native source handoff.
- System/Manual valid and unavailable states with service spies; native Outputs
  toggles exactly once; Chromium hold routes do not also toggle on release.
- Adaptive expansion, evidence/guidance, source inspection, native-row handoff,
  backdrop, Escape and parent/child inactivity reset and reopen custody.
- Chromium badge/chip drag cancellation and footer hold/drag/cancel/multitouch.
- Disconnect, ready-without-evidence, fresh evidence and owner removal.
- Trusted interaction renews inactivity; passive state updates do not.

A complete result must contain both engines and layouts. Investigative narrowed
runs and explicitly unsupported sequences must be reported separately from passes.
