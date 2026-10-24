# Rendered UI revision

The V2 mobile and tablet cards include a small bottom-left UI indicator. Open it
for UI and software version details and the next step. The UI label reports the revision declared by this
rendered card, compared with the compatible target advertised by its HI backend.
It is independent of environmental alerts, Stability and control health. Its 4px
top margin keeps the footer close to Outputs. A single button occupies at least
44px of real layout height and wraps visible labels on narrow screens; the UI LED
retains its size and revision meaning.

| Indicator | Meaning |
|---|---|
| UI current | This card's revision matches the backend target for this layout. |
| UI update | The backend explicitly identifies this revision as superseded by its compatible target. Export and replace the card. |
| UI differs | The revisions differ without an established upgrade relationship, including a card retained after backend rollback. Use the matching backend export. |
| UI unverified | Revision evidence is missing, unsupported, disconnected or cannot be associated with this card. No current-status claim is made. |

## Updating a card

1. Use HI's existing `refresh_ui` and `view_cards` workflow to obtain fresh exports.
2. Open the exact file named by the notification for the intended entry and layout.
3. Replace the complete YAML in that saved Manual card, then save the dashboard.
4. Refresh the browser or Companion app if it still displays the old card.

Exporting or downloading a file does not replace a saved dashboard. The indicator
cannot determine whether old rendered YAML comes from an unchanged saved card or
a browser cache. Refreshing alone cannot install new YAML. Each saved mobile,
tablet or duplicate dashboard card needs its own replacement. Older cards need an
initial replacement to gain the indicator.

“UI current” is a revision comparison, not verification of saved dashboard bytes,
local YAML edits, entity mappings, options, frontend dependencies, other clients,
or an available integration release. Continue to regenerate and replace cards
after UI-affecting configuration changes even if their UI revision is unchanged.
An integration update that changes no UI need not change the UI revision.
The separate software label below never changes the UI LED's colour or meaning.

Every package version update includes the [canonical release revision check](release-governance.md#rendered-ui-revision-check-for-every-version-update). The LED is maintained with HI; its revision is not a copy of the package version.

## Software update observation

Introduced in beta.3, the optional software observation uses HACS's reported update
state for HI. Since beta.4, the footer keeps the UI revision status on the
left and right-aligns any visible software cue. HACS remains optional: manual
installations and unavailable update sources retain the UI revision comparison.

| Software state | Footer presentation and meaning |
|---|---|
| Update available | **↑ Update available** on the right means HACS reports an update; it is separate from a card replacement. |
| No update reported | No visible software cue or separator. Details retain HACS's no-update report; this does not prove globally latest or loaded code. |
| Update skipped | Muted **Update skipped** on the right; HI preserves the deliberate skip. |
| HI update in progress | Visible on the right. HACS reports progress, not proof that new code is running. |
| Updates unverified | Subdued but visible on the right. Evidence is absent, disabled, ambiguous, unavailable, malformed, unsupported or disconnected. |

Only the routine no-update cue is hidden. The UI revision LED and label remain
visible in every software state: **UI current** with **Update available** means the
card matches its backend while HACS reports a software update; **UI update** with
**Update available** preserves both separate next steps. Neither cue overrides the
other. Loss of provider evidence reveals **Updates unverified** rather than retaining
a quiet no-update state.

Both ends remain part of one accessible button and open the same details panel.
The accessible name includes the classified software state even when its visible
no-update cue is hidden. Text accompanies the update arrow; no color-only or
hover-only meaning is required. Narrow layouts wrap the right cue into real space
without covering Outputs or the UI revision warning.

Open the footer for **UI and software versions**. The software section identifies
HACS and labels its downloaded, available and skipped versions. **View update**
opens the exact existing HA update entity's native details only while its current
state and versions still match the observed source. Changed or missing evidence
requires reopening the details. The footer does not call an install action,
download anything, restart HA or replace dashboard YAML.

HACS owns update discovery, release-channel preference and refresh timing. HI
introduces no GitHub checker or beta selector. HA's `off` can include a skipped
release or a downloaded version ahead of the offered version; `on` can include
incomparable version identifiers. These are provider reports, not HI's independent
version comparison. HACS's downloaded version may differ from manually installed
or loaded code. Cached provider information and HA entity timestamps do not prove
a recent successful Internet check. See [HA update states](https://www.home-assistant.io/integrations/update/),
[HACS updates](https://www.hacs.xyz/docs/use/entities/update/) and
[HACS prerelease selection](https://www.hacs.xyz/docs/use/entities/switch/).

The backend matches the official HI repository's stable HACS unique ID in HA's
entity registry, rather than its editable entity ID or display name. It re-resolves
that identity during existing Diagnostics refreshes, including after renames or
late HACS startup. `update_observation` is a separate schema-1 attribute and compact
Diagnostics summary. It contains fixed status/reason values and bounded version
text; no provider HTML, release URLs, credentials or claimed check timestamps.
Native/support exports omit the locally resolved source entity ID. No new listener,
scheduler, control input or Stability publication path is added.

### Single-level installations

V2.1.0 can leave both layout targets empty when only one level is configured,
even after a complete fresh export. The v2.1.1 candidates retain the beta.2 fix
by excluding unconfigured-level humidity and temperature chips and references
during generation.
Adding a dummy level or clearing the browser cache does not repair that generator defect.

Level presence follows effective configured telemetry, including Options. Any
configured telemetry type establishes a level; its humidity and temperature
averages remain visible even when readings are unavailable. A required configured
entity that cannot be mapped still blocks target publication. Raw unresolved
placeholder counts include optional features; the per-card list identifies the
references that prevented an export from advertising its revision.

## Contributor contract

`ui/revision.py` owns the metadata schema, generator contract and separate mobile
and tablet revisions. The generator embeds a stamp after mapping, pruning and
optional presentation transforms, and advertises only successfully stamped layouts.
The HI Diagnostics entity exposes the additive `ui_revision` attribute. Its
existing primary state and all control entity IDs and service schemas are unchanged.

Schema 1 identifies an opaque entry association and a layout. Each target includes
an integer revision, generator contract and explicit `supersedes` list. The rendered
stamp includes the same association, layout, schema, revision and generator contract.
The association prevents accidental cross-entry comparisons; it is not a secret or
an authentication credential. This contract intentionally excludes configuration
fingerprints and arbitrary customization verification.

Change the appropriate layout revision when its canonical presentation or embedded
renderer changes. Add previously released compatible revisions to `supersedes` only
when their upgrade relationship is established. Keep the generator contract explicit
when generation semantics change. Do not derive any of these values from the
integration manifest, export timestamp or file download. Unknown schema/generator
contracts remain unverified. A valid newer card against an older backend remains a
revision difference, never a fabricated update or healthy match.

Revision details use the [two-minute inactivity policy](ui-inactivity.md), while
Close, Escape and backdrop dismissal remain available.

The self-contained footer uses the existing button-card dependency and its live HA
connection. Disconnection invalidates current status even if old entities remain
cached; reconnect requires fresh evidence. It creates no output commands, automatic
download, dashboard writes, network polling or reloads. Maintain the canonical
renderer and regenerate its four embeds with `scripts/sync_ui_revision.py`.

## Validation and activation

Check both generated layouts and gallery mirrors with renamed entities, separate
entries, missing or malformed metadata, match/update/rollback, unavailable
Diagnostics, disconnect/reconnect and duplicate cards. Export without replacement
must leave an old card old. Check native button activation, dialog Close/Escape,
focus restoration and removal/navigation cleanup. Verify narrow phones, tablet
orientation and expanded Outputs without covering any existing action. Validate
both native and adaptive output generation: trailing footer comments must remain
outside the rewritten output rows, and configured observation summaries and
controls must survive the full export path.

The associated display fixes preserve controls: System and Manual explicitly show
unknown input, humidity uses finite numeric evidence, comfort describes position
relative to the seasonal band, and Outputs names come from the mapped entities.
The seasonal description never prescribes an action in competition with the backend
reason. Outputs expansion remains shared per entry and retains its existing timer.
The revision indicator itself leaves Stability and lane selection unchanged.
The unpublished v2.1.1-rc.1 candidate retains beta.4 revision 13 in both layouts,
superseding revisions 1–12. Existing beta.4 revision-13 cards stay compatible;
older revisions require fresh exports and full saved-card replacement.
Beta.3 remains the earlier revision-12 candidate and beta.2 the revision-11 candidate;
earlier deployment and Lab evidence apply only to their exact packages. The update-observation contract is independent of the stamp.
Published v2.1.0 retains revision 9 and its compatibility with RC.1 revision-9 cards.
Stamp schema and generator contract remain 1. See
[the release compatibility record](release-governance.md#rendered-ui-revision-check-for-every-version-update).

Installing the Python metadata changes requires the normal complete-package update
and Home Assistant restart. A restart resets in-memory Stability collection; it is
not required merely to paste replacement YAML. No configuration migration is
required. Rollback uses the previous complete package and its saved card YAML; a
new card against a backend without revision support safely shows unverified.
Source tests and browser fixtures do not replace validation in an actual supported
Home Assistant client.

Run the focused regression checks from the repository root with pytest and PyYAML
installed in a development environment:

```sh
python -m pytest -q "tests 2/test_single_level_ui.py" "tests 2/test_adaptive_cards.py" "tests 2/test_ui_revision_contract.py" "tests 2/test_badge_summary_export.py" "tests 2/test_runtime_card_sanity.py"
python -m pytest -q "tests 2/test_update_observation.py" "tests 2/test_diagnostics.py"
node --test "tests 2/test_ui_revision_status.mjs" "tests 2/test_v2_display_truth.mjs"
python scripts/sync_ui_revision.py --check
python scripts/sync_badge_history.py --check
```

For the full Python suite, preserve the [separate real-HA test processes](output-observation.md#validation)
so the lightweight test scaffolds cannot replace the native selector environment.
