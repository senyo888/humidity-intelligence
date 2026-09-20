# V2 touch and keyboard interactions

The unpublished beta.9 candidate repairs native-button activation inside the
canonical mobile and tablet cards. Its V2 layouts use UI revision 4 with generator
contract 1. Backend control, classification and beta.8 custom monitoring meanings
retain their existing contracts.

## Interaction ownership

| Surface | Tap or click | Other supported interaction |
|---|---|---|
| Humidity, Condensation, Mould | Open HI details | History uses its named native or embedded destination |
| 7 Day Drift | Open HI details | Hold opens native more-info |
| Current Air Control | Open explanation and recorded history | Hold opens native more-info; chips and reason remain scrollable |
| Ready, Zone 1, Zone 2, AQ | Open explanatory details and history | These displays do not select a control lane |
| Stability | Open snapshot details | Hold opens Diagnostics |
| UI revision footer | Open rendered-revision details | Enter and Space activate its native button |
| System and Manual | Toggle once when the input state is valid | Hold opens more-info; unknown/unavailable input cannot toggle |
| Native Outputs header | Toggle the shared expansion helper once | Its native entity rows keep Home Assistant control behavior |
| Adaptive Outputs header | Expand or collapse locally | Evidence, monitoring and controls buttons open their named details |
| Adaptive entity/source links | Open Home Assistant more-info | Device controls remain owned by Home Assistant |

HI detail buttons support keyboard focus and activation. Embedded history keeps
Back, range selection, source selection and native-details handoff available. Close,
Escape and offered backdrop dismissal remain immediate. Reopening begins a new
dialog lifecycle and restores focus on dismissal where its opener still exists.

The interaction repair is scoped to HI-owned native buttons. Existing button-card
service actions retain their owner; touch handling must not synthesize a second
System/Manual toggle, operate an output, or turn a scroll into a tap.

## Mobile and tablet touch matrix

Run this matrix separately for the generated V2 mobile and tablet layouts, including
native and adaptive Outputs presentation. A desktop mouse pass does not establish
touch support. Browser touch emulation must use an actual browser, enabled touch,
a coarse pointer and the real supported card dependencies.

| Check | Mobile touch | Tablet touch | Expected result |
|---|---|---|---|
| Each surface in the inventory | Required | Required | One intended activation; correct destination |
| Footer LED, text and extended hit area | Required | Required | One revision dialog without overlapping another control |
| Tap, hold and rapid repeat | Required | Required | Existing action distinction; no duplicate dialog or service call |
| Vertical scroll, horizontal chip drag and cancelled touch | Required | Required | Scrolling remains usable; no unintended activation |
| Close, backdrop, reopen and history navigation | Required | Required | Immediate dismissal; fresh dialog and correct navigation |
| Missing entities and unverified revision evidence | Required | Required | Safe labels; no unavailable control toggle |
| Reconnect, navigation, removed and duplicate cards | Required | Required | Listeners and timers clean up; instances remain independent |
| Adaptive details with custom names and guidance | Required | Required | Literal readable text and working source/control handoffs |
| Inactivity and parent/child interaction | Required | Required | Existing timer policy, no stale callback closing a later dialog |

Also regress mouse and keyboard Enter/Space/Escape, focus restoration and narrow or
rotated layouts. Check all resulting service requests in a controlled fixture:
read-only details generate none, and an authorized control activation generates
exactly its existing action. Live validation must respect the target's control
boundaries; a fixture result is not physical-device proof.

## Evidence and limits

See the [browser regression harness](../tests%202/browser_touch/README.md) for
reproducible commands, dependency verification and fixture limitations.

The reported failure was reproduced with actual button-card **7.0.1** and generated
card configuration in **Chrome 154**, using Pixel 7 mobile touch emulation
(`hasTouch` enabled and coarse pointer). A touch tap opened zero revision dialogs;
a mouse click opened one. This identifies a real browser/host interaction discrepancy,
rather than relying on a synthetic click event or DOM test double.

That reproduction is not a physical Pixel, iPhone or iPad test and does not establish
Safari or Companion behavior. Record the exact browser, dependency versions,
viewport, input method, generated layout and source revision for repair validation.
Keep unit/DOM results, real-browser touch results, physical-client results and live
Home Assistant observations separate. A mobile-support claim requires the
real-browser touch checks above; report physical-client coverage independently.
This document records the contract and reproduction, not a completed repair test or
deployment result.

## Inactivity, source changes and activation

After a disconnect, the revision footer remains unverified until the connection is
ready and a fresh available Diagnostics entity is rendered. A reused button-card
state wrapper does not prevent recovery; cached or unavailable evidence cannot
restore a verified status.

The [inactivity contract](ui-inactivity.md) remains authoritative: HI-owned details
close after two minutes without interaction; passive telemetry does not renew them.
Adaptive child activity renews its own and its parent's deadline. Native Outputs
keeps its shared backend timer measured from opening, and Home Assistant owns its
native dialogs. Existing source-change dismissal remains in effect where supported.

Renderer changes require synchronized mobile/tablet and gallery embeds, generated
YAML validation and UI revision checks. UI revision 4 supersedes the compatible
previous renderer revisions; package version alone does not update a pasted card.
Install the complete candidate package, restart Home Assistant, then export and
replace the full saved mobile and tablet Manual-card YAML. Refresh clients as
needed to load the updated optional adaptive resource and rendered configuration.
Restart resets existing in-memory Stability history. No configuration or entity
migration is introduced by the touch repair.

Keep the previous complete package and saved card YAML for rollback. Reverting both
restores the earlier interaction behavior, including its known touch limitation.
If rolling further back across beta.8 custom meanings, follow its
[settings and custody rollback requirements](custom-monitoring-meanings.md#activation-and-rollback).
Source validation, target activation and public release remain separate claims.
