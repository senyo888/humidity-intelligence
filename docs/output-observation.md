# Optional output observation

This beta.4 feature is opt-in and is not part of the current published Stable
release. Existing installations default to observation disabled and native Outputs
presentation. Installing beta.4 requires a full Home Assistant restart to load its Python modules.

## What it observes

The observer reads outputs already configured in HI, their Home Assistant states,
and associated diagnostic entities. Shared outputs appear once, retaining their
configured roles and each role's enable state. Outputs uses a neutral devices icon;
individual rows use their HA entity domain (fan, switch, humidifier or light), with
a generic fallback. A switch icon does not identify the appliance connected to it.
Device icons describe the HA entity type, not availability, activity or health.
These are entity categories, not an appliance allowlist: a switch-backed device
retains switch semantics. Other configured domains use a generic icon and remain
control-support-unconfirmed; an icon never adds a new actuation capability.
A disabled role is configuration context; it does not prove isolation or prevent another enabled role using the output.

Observation does not select lanes, send service calls, change helpers, repair devices,
or become an input to the control engine. Ventilation priority, independent humidifier
resolution, Manual ownership, and Stability calculations remain unchanged.
An observed `on` state means Home Assistant reports On. It does not prove command
completion, physical airflow, moisture production, or device health.

Only supported diagnostic device classes have automatic meanings. Other sources
remain context until explicitly confirmed. Exact binary, enumeration, or numeric
rules determine reported attention. Unknown enumeration values remain unknown;
unknown and unavailable sources never become an all-clear result. One diagnostic
source can have different confirmed meanings for different outputs; each association
shows its own meaning and rule.

Home Assistant report/update timestamps and restored-state metadata are shown only
when the platform supplies them. They are provenance, not a physical freshness
promise or an inferred age threshold. Coverage distinguishes monitoring not yet set
up from previously known monitoring that has been lost. Context-only choices remain
visible as incomplete coverage.

## Configure and recover mappings

Open HI **Configure**, then **Output observation**. Enable observation and choose
native or adaptive presentation. Add a mapping by selecting a configured output,
a diagnostic source, a meaning, and an exact rule. Review the preview before
confirming. Enumeration rules require both active and clear values. Numeric rules
use strict below/above comparisons; units are not guessed.

Manage existing or discovered associations to edit a rule, revoke confirmation,
replace a source, mark it context-only, or explicitly resume interpretation.
Context-only retirement is bound to the particular output/source identities; it
does not globally ignore a shared diagnostic source. Missing mappings remain
reviewable. To manage a formerly automatic source while observation is disabled,
enable observation and Finish first, then reopen Manage; this loads its saved
monitoring history through the observer. Registry replacements require explicit revalidation instead of silently
inheriting the old entity's meaning.

These forms stage changes. Keep changes returns to the main options menu; the
existing Finish action saves the options transaction. Cancel observation changes
returns without staging that draft. Closing the unsaved flow writes nothing.
Saving uses HI's existing entry-reload behavior. It does not restart Home Assistant;
existing in-memory runtime history has the same reload lifecycle as other HI options.

## Generated cards and resource setup

Native presentation uses ordinary output entity rows and does not require the new
resource. With observation enabled, the normal mobile/tablet generator includes
the deduplicated configured output inventory while preserving supporting native
controls. Hidden output details and alert-only mode retain their existing behavior.

For adaptive presentation, manually register this JavaScript module in Home
Assistant dashboard resources:

```text
/humidity_intelligence/hi-adaptive-output-card.js
```

The optional resource renders the backend-authored status sensor and keeps the
native entity controls inside its expanded view. HI serves the file but does not
create or modify a dashboard or resource registration. The generator resolves the
real registered status entity; it does not invent a placeholder entity ID.
Enable/presentation changes regenerate the normal exports. Replace the complete
Manual-card YAML in the dashboard using the new export. `refresh_ui` / `dump_cards`
remain the recovery path if export regeneration is incomplete.

If the resource is missing or cannot load, select native presentation, export again,
and replace the Manual card to recover controls independently of the custom element.
A browser refresh may be needed after resource changes. English is the initial
translation and the fallback for other interface languages; source labels retain
their Home Assistant names. No additional language support is implied.

## Companion prototype migration

There is no automatic companion adoption. The options flow can preview bindings
from a selected existing companion config entry and import them only after explicit
confirmation and identity validation. It does not modify or remove the companion,
its files, options, dashboards, or storage. Unresolved bindings cannot silently bind
to a replacement. Companion monitoring history/custody is not imported; packaged
observation begins with its own identity custody and a current HA snapshot.

The companion and packaged frontend use the same custom-element name. Disable the
companion and remove its old dashboard resource before registering the packaged
resource, then reload the browser; otherwise the first loaded definition wins.
These migration operations are user-managed and are not performed by the flow.
Keep the companion configuration for rollback until the new setup is verified.

## Failure, storage, and support boundaries

Observer setup, collection, storage, and frontend failures cannot block HI's control
setup. Failed or oversized observation becomes unavailable rather than a partial
healthy report. Collection is bounded: 128 configured role records before shared
output deduplication, 256 confirmed mappings, 4096 registry custody entries, and a
512 KiB payload. These are safety limits, not promises about supported device load.

The observer uses targeted state listeners, coalesces events, and caches registry
metadata between registry changes. Custody stores registry fingerprints, known
associations, and pending invalidations in its own entry-scoped HA storage. It does
not restore cached source values. Registry changes quarantine affected states until
a subsequent relevant changed or unchanged HA state report; quarantine survives an
orderly unload/reload.
Pending observations are labelled awaiting a new report, not missing when an HA
state exists. Events predating the registry change cannot release quarantine, even
when HA delivers them later. A genuinely new observer accepts its initial current
snapshot without treating setup registry events as lost evidence.
Delayed HA storage writes and shutdown flushing are best effort, not a crash,
power-loss, or failed-disk durability guarantee. Invalid storage fails closed.

The diagnostic sensor's detailed payload and error attributes are excluded from
Recorder. Integration diagnostics expose aggregate observation state/counts only;
confirmed identities and retired mappings are redacted. The live status payload
still contains entity references needed for local presentation, so share exports
only after review.

## Rollback and validation

Disable observation and select native presentation, regenerate/export, and replace
the dashboard card before removing its resource. This removes the observer from
normal setup and keeps the established engine path. Rolling back to older companion
code does not preserve the new custody safeguards; disabling observation is safer
than presenting older monitoring as equivalent.

Local automated tests cover pure classification, identity custody, staged mappings,
generated-card preservation, optional failure handling, and HA API integration.
Run the focused checks from the repository root in a disposable Python environment
with Home Assistant, pytest, and PyYAML installed:

```sh
python -m pytest -q "tests 2/test_adaptive_options.py"
python -m pytest -q "tests 2/test_adaptive_cards.py"
python "tests 2/test_adaptive_model.py"
python "tests 2/test_adaptive_runtime.py"
python "tests 2/test_adaptive_ha_native.py"
python "tests 2/test_config_flow_sanity.py"
python "tests 2/test_runtime_card_sanity.py"
node --test "tests 2/test_stability_badge_renderer.mjs" "tests 2/test_reason_card_renderer.mjs"
```

Run suites in separate processes where shown because existing tests install HA test
doubles. The HA-native harness uses temporary storage and real HA registries/state
callbacks; it does not boot HI's control engine or connect to a live installation.
Synthetic browser fixtures exercise layout and interactions. These checks do not
establish live device compatibility, physical freshness, or a HA Lab/Stable deployment.
A future deployment requires its own authority, target verification, and observation.
