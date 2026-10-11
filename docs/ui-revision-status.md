# Rendered UI revision

The V2 mobile and tablet cards include a small bottom-left UI indicator. Open it
for revision details and the next step. It reports the revision declared by this
rendered card, compared with the compatible target advertised by its HI backend.
It is independent of environmental alerts, Stability and control health. Its 4px
top margin keeps the footer close to Outputs; the 44px interaction target, LED,
label and bottom inset retain their sizes.

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

Every package version update includes the [canonical release revision check](release-governance.md#rendered-ui-revision-check-for-every-version-update). The LED is maintained with HI; its revision is not a copy of the package version.

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
Stability presentation, collection, scoring and lane selection are unchanged.

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
python -m pytest -q "tests 2/test_adaptive_cards.py" "tests 2/test_ui_revision_contract.py" "tests 2/test_badge_summary_export.py" "tests 2/test_runtime_card_sanity.py"
node --test "tests 2/test_ui_revision_status.mjs" "tests 2/test_v2_display_truth.mjs"
python scripts/sync_ui_revision.py --check
python scripts/sync_badge_history.py --check
```

For the full Python suite, preserve the [separate real-HA test processes](output-observation.md#validation)
so the lightweight test scaffolds cannot replace the native selector environment.
