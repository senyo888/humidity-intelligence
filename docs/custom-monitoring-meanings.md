# Reusable monitoring meanings

This feature belongs to the unpublished v2.1.0-beta.8 candidate. It extends optional
output monitoring; published Stable remains v2.0.12.

A custom meaning gives a monitoring condition a reusable name, an existing HI
classification and optional **What to do** guidance. The library belongs to one HI
entry. Each source keeps its own detection rule and identity; selecting a saved
meaning does not copy another source's threshold, active values or clear values.

For example, two outputs can use a meaning named **Check water supply**, classified
as **Refilling**. One source may report an explicit binary condition while another
uses a numeric threshold. Those rules are configured and reviewed independently.

## Create and reuse

1. Open **Configure → Output monitoring → Add a monitoring rule**.
2. Select the output and source. Choose **Add custom meaning** in the meaning list,
   or select an existing saved meaning.
3. For a new meaning, enter its name and choose a classification. **Other attention**
   is the neutral default. Optionally enter **What to do**.
4. Complete the source's exact detection rule and review the preview. Confirm the
   proposed change to keep the new meaning and rule together in the current draft.
5. Choose **Keep changes and return**, then **Save changes** on the main settings
   page to apply the draft.

Names are plain text, up to 80 characters. Each entry supports up to 32 saved
meanings. Names are unique after Unicode normalization and case-insensitive
comparison, including the built-in choices. Names cannot contain control characters.

**What to do** accepts up to 240 characters of plain text, including line breaks.
Leave it empty for standard HI guidance alone. Your text appears alongside that
guidance, labelled **Your guidance** for active attention and **Configured guidance**
in monitoring details. It is displayed as text, never run as a command or automation.

The classification retains HI's existing severity, icon and device guidance.
Monitoring details show the custom name and underlying classification. A configured
name or instruction does not mean its condition is currently active. Only the
source's validated rule determines active, clear or unknown evidence.

## Manage saved meanings

Use **Reusable monitoring meanings** in Output monitoring to manage the library.

- **Rename or edit guidance:** affected rules use the revised name or guidance when
  saved. Source identities and detection rules remain unchanged.
- **Change classification:** review every affected rule before confirming. The
  classification and its associated rules change together; thresholds and exact
  active/clear values remain unchanged. Attention severity, icon and standard
  guidance follow the new classification.
- **Delete an unused meaning:** review and confirm the deletion.
- **Delete an in-use meaning:** choose a replacement built-in or saved meaning, or
  explicitly remove every rule using it. Review all affected rules before confirming.
  Removing explicit rules can allow standard automatic discovery to apply again.
  Use the existing context-only action when the intention is to stop interpreting
  a particular association.

A shared source may have different meanings for different outputs. Its monitoring
details keep those associations separate. The library is not shared between HI
entries, and editing one entry does not alter another.

## Save, return and cancel

Meaning and rule edits use the existing staged options transaction. **Return without
changing** cancels the nested editor or deletion step. Leaving the preview's confirm
box unchecked discards that proposed change, including a meaning created for that
pending rule; earlier staged changes remain intact.

**Keep changes and return** retains the monitoring draft without persisting it.
**Discard this visit's monitoring edits** restores the monitoring state from entry
to that subflow, preserving earlier main-settings edits. Closing the unsaved options
flow writes nothing. Only the main **Save changes** applies the result. Reopening
options reads the saved library and rules.

## Missing evidence and compatibility

Missing or unavailable sources remain explicit monitoring gaps. If a rule references
a saved meaning that is absent, HI shows that interpretation as unavailable instead
of falling back to its stored built-in classification or claiming clear monitoring.
Malformed settings are preserved for review rather than silently replaced.

Existing settings without a custom library continue with an empty library and their
current built-in meanings. Names are tied to stable internal references, so renaming
retains associations. Companion imports retain their existing supported mappings;
this feature does not create a cross-entry or companion-library synchronization path.

Custom names and guidance use the existing backend-authored text fields. They add
no frontend classification, custom icon system, output commands or lane inputs.
They do not change control ownership, entity primary states or Stability scoring.
This additive text feature requires no new frontend resource or renderer revision.
An already compatible adaptive Outputs card receives the text through its status
entity; changing presentation or card-generation options still requires the usual
export and saved-YAML replacement.

## Activation and rollback

Installing the complete beta.8 Python package requires a Home Assistant restart.
Saving options subsequently uses the existing entry reload; it does not restart
Home Assistant. Restart or reload resets the existing in-memory runtime history,
including Stability collection. Existing configurations require no manual migration.

Before adopting custom meanings, retain a restorable backup of the prior complete
package, saved entry settings, monitoring custody and dashboard YAML. Older packages
reject the new library key even when the library is empty, and lack its reference
handling. For downgrade, restore
the matching earlier settings and custody together with the earlier package; retain
the newer backup separately. Do not assume that changing only the package preserves
custom meanings or their monitoring interpretation. Follow the
[output-monitoring rollback guidance](output-observation.md#rollback-and-validation)
when disabling observation or removing its optional resource.

Tests and review evidence belong to the candidate being assessed. This guide does
not establish deployment, live device compatibility or physical-device proof.
