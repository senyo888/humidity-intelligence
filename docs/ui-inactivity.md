# UI inactivity and manual dismissal

HI-owned details and adaptive Outputs expansions close after two minutes without
interaction. Pointer, touch, keyboard and deliberate scrolling inside an open
surface renew its deadline. Passive telemetry updates do not keep it open.

Manual dismissal remains immediate: use Close, Escape, the backdrop or the Outputs
chevron where that surface offers them. Closing cancels its timer; reopening starts
a fresh deadline. Navigation, removal and disconnection dispose owned timers and
details without operating an output or changing integration options.

| Surface | Close policy |
|---|---|
| Adaptive Outputs chevron | 120 seconds of client-local inactivity; chevron closes immediately |
| Outputs controls, evidence and monitoring details | 120 seconds of inactivity; interaction also keeps the owning expansion open |
| Current Air Control explanation and Ready/Zone/AQ chips | 120 seconds of inactivity, plus existing source-change dismissal |
| Humidity, condensation, mould and drift details, including embedded history | 120 seconds of inactivity, plus existing source-change dismissal |
| Stability and UI revision snapshot details | 120 seconds of inactivity; manual and lifecycle dismissal remain available |
| Legacy/native Outputs expansion | Existing **120 seconds from opening**, controlled by the shared backend helper; interactions do not extend it |
| Home Assistant native more-info/history | Home Assistant owns dismissal; HI adds no timer |

Each custom dialog owns its deadline. In adaptive Outputs, child interaction renews
both the child and its parent expansion; interacting only with the parent does not
extend an idle child. Parent collapse closes its child. Closing one instance cannot
leave an old callback that closes a later dialog.

The legacy Outputs helper is intentionally unchanged: it is shared between clients.
HI does not send hidden helper/service writes merely to extend that timer. The
client-local inactivity policy applies to the adaptive presentation and custom
HI dialogs. Browser timers are client lifecycle behaviour, not a runtime control
or Home Assistant automation.

## Maintainer validation

`ui/inactivity.js` is the canonical helper embedded in badge, Stability and revision
details. Run `python scripts/sync_ui_inactivity.py`, then
`python scripts/sync_ui_revision.py`; both support `--check`. The optional adaptive
Outputs component maintains its parent/child custody in its own lifecycle. All
sources are covered by the UI revision governance guard.

Validate inactivity, trusted interaction reset, passive updates, manual closing,
reopening, stale callbacks, parent/child timing, disconnection and removal. Check
both generated layouts and gallery mirrors, preserving controls and metadata.
The history request timeout is a separate network error boundary, not this timer.
