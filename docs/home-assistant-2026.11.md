# Home Assistant 2026.11 compatibility

The `2.1.2` stable source preserves beta.1 Marketplace support, canonical
air-quality units, complete-evidence CO clearance and bounded setup improvements.
Published Stable remains `v2.1.1` while final stable validation is completed. Source tests, publication, installed files and
loaded runtime behavior are separate evidence.

## Installation and update observations

On Home Assistant 2026.11+, use **Settings → Marketplace**. On supported earlier
versions, use HACS. The declared minimum remains 2026.5.1. The named component ZIP
and older-release recovery limits are documented in [release packaging](release-packaging.md).
Published **v2.1.1 exceeds Marketplace's archive limit** and can fail to download.
The beta provides a smaller install ZIP and must be selected explicitly for testing.
For Stable v2.1.1, use
[exact-tag manual recovery](release-packaging.md#earlier-versions-and-current-evidence-limits) if affected.
Marketplace can open a fresh installation's setup flow directly; updates and manual
package replacement require a full Home Assistant restart. A restart discards HI's
in-memory Stability sampling history.

The optional `update_observation` schema remains 1. Its `provider` is `hacs` or
`marketplace` when exactly one supported registry entry matches the official HI
repository ID; it is null when no unique provider can be established. Two matching
entries are ambiguous, including when one is disabled. Disabled, missing and
unavailable sources remain unverified. Renamed update entity IDs are resolved from
the registry. HI neither polls the provider nor installs updates.

The reported installed/downloaded version is provider evidence, not proof of the
code loaded by Home Assistant. Provider choice does not establish frontend-card
availability. Setup inspects optional card resources independently; both the new
`/local/community/` and retained `/hacsfiles/` routes are recognized.

Both V2 layouts now use **revision 16**, superseding revisions 1–15. Stamp schema
and generator contract remain 1. The final v2.1.2 source corrects optional entity
references in generated JavaScript: unconfigured sources remain absent even when
unrelated legacy entities have matching names. Configured missing/unavailable
sources retain their validation and degraded-state meaning.

After the full package update and restart, refresh/export and replace the complete
saved Manual-card YAML, **including beta.1 revision-14 cards**. Revision-13 cards
remain a replacement cue and treat Marketplace evidence as unverified; revision-14
cards introduced Marketplace/HACS support but do not contain this generator fix.
Against an older backend, revision-16 cards show **UI differs** rather than implying
a newer installed release. Restore the previous complete package and matching
saved cards together when rolling back.

## Air-quality units and CO clearance

Runtime comparisons, aggregate sensors and Stability evidence share one parser:

| Measurement | Comparison/output unit | Accepted source units |
|---|---|---|
| VOC concentration | ppb | ppb, ppm |
| CO and CO₂ | ppm | ppm, ppb |
| PM2.5 | µg/m³ | µg/m³, mg/m³, including equivalent ASCII spellings |
| Existing IAQ index | index | index, IAQ, or the existing unitless form |

Conversion happens before averaging or threshold comparison. Display rounding does
not change a threshold decision. Concentrations require explicit units; missing
units, incompatible dimensions, negative/nonfinite values, booleans, embedded-number
text and conversion overflow are excluded. VOC indices and mass concentrations
cannot be inferred as ppb. No molecular-weight assumptions are made.

For example, 600 ppb VOC and 0.6 ppm VOC now have the same meaning. Matter's
2026.11 correction can change the numeric state of an existing sensor while its ID
stays the same. Verify the source's actual unit and retain thresholds in the HI
units above. HI does not rewrite thresholds, source entities or historical records.
Existing aggregate history is not retroactively normalized.

A configured CO source with a missing or unsupported unit now raises a Home
Assistant Repairs warning, including after upgrade. Correct the actual source unit
to ppm or ppb in its integration or template; do not guess or relabel a different
measurement. The warning clears when the units are supported. Missing or invalid
readings still remain unavailable, and the warning never changes control outputs.

Any valid configured CO source at or above the existing start threshold can still
activate the highest-priority emergency, including when another source is invalid.
An active emergency clears only when **every configured CO source** has valid,
normalized readings strictly below the existing clear threshold for a fresh,
continuous two-minute hold. Missing/invalid evidence or a reading at the clear
threshold resets the hold and cancels its waiting deadline. A recovered reading
starts a new hold; it does not inherit time from before the interruption.

The hold uses monotonic elapsed time. CO state-change interruptions are recorded
even while controller evaluations coalesce. The deadline releases its waiting-task
ownership before requesting evaluation, so cleanup cannot cancel that evaluation.
This corrects clearance behavior; thresholds, hold duration, lane priority, Manual
exception, output ownership and humidifier independence remain intact.

Native Diagnostics, compact live Diagnostics and the support export include bounded
`aq_inputs` counts by measurement type: configured, available, unsupported unit,
invalid value and missing source. These counts contain no entity IDs or readings.
An empty configuration is not complete evidence. Incomplete configured inputs also produce a
warning. An emergency retained because clearance is unproved is not a claim that
a new high reading was observed.

The review follow-up restores calculated kitchen-slope lookup when its configured
source differs from the kitchen telemetry sensor. It requires one unambiguous
source and excludes sources explicitly assigned to another room. Supplied slopes
continue to use their saved source identity. This correction and the Repairs
warning leave V2 layout revision 16/schema 1/generator 1 compatible and unchanged.

## Forms, naming and reloads

On compatible 2026.11 forms, time bounds/outside action appear only when the time
gate is enabled; presence entities appear only when the presence gate is enabled.
Omitted hidden values preserve saved settings. Explicitly clearing an entity list
still clears it. Older supported HA versions retain visible fields and the same
save behavior. Options remain staged until the existing final save.

Provided temperature-slope pairs are saved by source and slope entity ID during
explicit setup/Options save. Existing saved pairs survive display-name changes and
unavailable readings. Deleted sources are pruned. Legacy configurations without
saved pairs use only globally unambiguous name matches or a sole source/slope pair;
multi-source list order no longer guesses an association. Ambiguous pairs remain
unmapped with Diagnostics guidance. Review slope Options using matching room names
before saving. No startup migration or source renaming occurs; calculated-slope
identity and sampling are unchanged.

If Home Assistant cannot unload HI's entity platforms, HI returns failure and
retains its remaining runtime/service custody instead of reporting successful
cleanup. The successful unload path is unchanged.

## Validation and rollback

Run stub tests separately from native HA tests. The native compatibility suite is:

```sh
python 'tests 2/test_ha202611_native.py'
```

Run it in separate environments pinned to HA 2026.5.1 and 2026.11.0; retain
2026.10/HACS coverage. It uses disposable local registries and schemas, not a live
installation. Cover unit equivalence, unsupported units, precise thresholds,
partial/full CO outages, continuous holds, timer cancellation, provider ambiguity,
schema serialization, hidden settings and saved slope identities. Validate both
generated layouts and old/new backend-card combinations. Lab evidence is optional.

Each change can be reverted independently before publication. After an authorized
installation, package and saved-card rollback are separate operations. Keep complete
package backups outside `custom_components`. Older packages have the demonstrated
unit-handling defect: check mapped source units before relying on their thresholds.
Older code ignores saved slope bindings and can revert to name/order matching.
No automatic threshold, history, source or dashboard rollback is performed.

## Upstream contracts

- [Marketplace migration](https://www.home-assistant.io/integrations/marketplace/#coming-from-hacs)
- [Matter concentration correction](https://github.com/home-assistant/core/pull/167177)
- [Naming changes](https://www.home-assistant.io/blog/2026/11/03/naming-things-in-home-assistant/)
- [Conditional forms](https://contributors.home-assistant.io/core/integrations/flow-steps/#fields-that-show-based-on-another-field)

Native monitoring sections, section strategies, energy observations and AI support
remain separate future work; this candidate does not implement those features.
