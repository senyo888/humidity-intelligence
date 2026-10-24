# Issue #129: optional Lab verification

These live checks supplement automated regressions and house review. **Lab
verification is optional and non-blocking:** its availability, result, playback
coverage or soak status is not a merge, promotion, tag, publication or release gate.
A passing check does not grant release approval. Each record belongs to its exact
package; validation does not transfer to changed bytes.

## Beta.2 verification — 14 October 2026

### Tested identity

- Issue: [#129](https://github.com/senyo888/humidity-intelligence/issues/129).
- Implementation: `32e54ba0482fe8411d6947c7e0022bb13922cc38` on `senyo888-patch-1`.
- Installed integration: `2.1.1-beta.2`; all 76 installed files matched the reviewed package after restart and restoration.
- Package SHA-256: `c58f065768415ab95ef09af6edf842de1e7376b6a91257443a101eccfeb8d4dd`.
- Home Assistant Core: `2026.10.0`; loaded integration and manifest both reported beta.2.
- V2 Mobile and Tablet: revision `11`, schema/generator `1`.
- Browser: desktop Chromium, using 430 px and 1024 px viewports.

### Live regression results

The Lab's 36 telemetry rows were reassigned through the normal Options flow, first
to Level 1 only, then Level 2 only. Each configuration reloaded the integration.
Fresh exports replaced exactly the two existing sandbox cards before browser checks.

| Configured telemetry | Layout | Export and backend | Actual browser |
| --- | --- | --- | --- |
| Level 1 only | V2 Mobile | Pass | UI current; revision 11 / 11 |
| Level 1 only | V2 Tablet | Pass | UI current; revision 11 / 11 |
| Level 2 only | V2 Mobile | Pass | UI current; revision 11 / 11 |
| Level 2 only | V2 Tablet | Pass | UI current; revision 11 / 11 |

All four cases retained the configured level's humidity and temperature average
chips, omitted inactive-level average references and visible chips, and produced
valid YAML without unresolved-placeholder warnings. Actual revision-details dialogs
confirmed displayed revision 11 and backend-advertised revision 11. All four
rendered card screenshots were inspected. Existing “Monitoring incomplete” output
status remained visible and was not treated as proof of healthy physical outputs.

After the initial full restart, Diagnostics briefly had no revision targets. Both
revision-11 targets appeared on normal publication before testing, without another
restart. Both single-level export checks then observed both targets.

### Containment, restoration and health

All four configured destinations were verified as local in-memory Lab simulators,
with complete command-counter coverage. Manual handover preceded fan/humidifier
isolation. Containment remained active through configuration reloads and restoration;
no simulator commands were issued during the contained tests.

Original entry data/options, telemetry assignments, the full entity registry,
dashboard resources, saved revision-11 cards and control-helper states were restored
exactly. Fresh two-level exports matched the saved baseline cards. The package and
protected configuration hashes were unchanged. Isolation was released while Manual
remained on, then Manual was turned off last. The restored browser showed both levels
and two current UI indicators. Restart and Options reloads reset in-memory Stability
history; this run does not accept a completed Stability baseline.

The post-restoration configuration check was valid. The integration's release check
reported 13 passes, three warnings and no failures; all 32 generated YAML exports
parsed. The warnings refer to the same unavailable seven-day humidity-drift value:
its statistics history covered 64% of the required window, below the 85% threshold.
That limitation remains visible. No HI entries appeared in the captured system-log
list, and backend reasoning was available at the recorded check.

### Fresh soak

A fresh 48-hour reported-health soak started on 14 October 2026 at 20:31 UTC
(21:31 BST), after restoration and a successful native readiness check. At the
recorded handoff, checkpoint 1 of 9 was healthy and the campaign was running with
its overall result pending. Checkpoints are six hours apart; the next is scheduled
for 15 October at 02:31 UTC and the final one for 16 October at 20:31 UTC.

The exact beta.2 source reference was enrolled without changing controller version,
credentials, target or earlier campaign records. The six preceding campaigns were
retained, including the stopped beta.1 soak. This is an initial healthy checkpoint,
not a completed 48-hour result. The soak remains optional and non-blocking and does
not accept a Stability baseline or authorize release.

### Coverage limits

This rerun covers #129 on the identified beta.2 package. Existing inactive-level
entity-registry records were retained; never-created inactive entries remain covered
by `tests 2/test_single_level_ui.py`. It does not establish validation on the
reporter's Home Assistant version, Edge, Companion App or physical devices. The
historical beta.1 synthetic unavailable-state probe below was not repeated in this
live rerun. Beta.2's device-text, calculated-trend and issue-summary changes have
separate source regression coverage; these four live cases do not establish exhaustive
validation of those changes, physical output actuation or HACS availability.

## Historical beta.1 verification — 14 October 2026

The following results remain pinned to the earlier revision-10 package. Its stopped,
incomplete soak is retained as historical evidence, independently of beta.2.

### Tested identity

- Issue: [#129](https://github.com/senyo888/humidity-intelligence/issues/129).
- Implementation: `f6e64c7d4d9ac4cebe671f85414653052f614ca5`.
- Installed integration: `2.1.1-beta.1`, with all 76 package files verified.
- Package SHA-256: `77f970e4b170eccf2c1540e9e03c664348dfea53e628a6e1c7d261e7ea28181d`.
- Home Assistant Core: `2026.10.0`.
- V2 Mobile and Tablet: revision `10`, schema/generator `1`.
- Browser: Chromium-based desktop browser, using 430 px and 1024 px viewports.

This is evidence for the identified package and scenarios. It does not establish
HACS availability or validation on the reporter's Home Assistant version, Edge or
Companion App.

### Live results

The Lab began with two configured levels. Its existing telemetry rows were
reassigned through the normal Options flow, first to Level 1 only, then Level 2
only. Each saved configuration reloaded the integration. Fresh exports replaced
the complete existing Mobile and Tablet cards before browser inspection.

| Configured telemetry | Layout | Export and backend | Actual browser |
| --- | --- | --- | --- |
| Level 1 only | V2 Mobile | Pass | UI current; revision 10 / 10 |
| Level 1 only | V2 Tablet | Pass | UI current; revision 10 / 10 |
| Level 2 only | V2 Mobile | Pass | UI current; revision 10 / 10 |
| Level 2 only | V2 Tablet | Pass | UI current; revision 10 / 10 |

For every case:

- YAML parsed successfully, with no unresolved-placeholder warning for either V2 card.
- The configured level retained its humidity and temperature average chips.
- The inactive level's average references and visible chips were absent.
- Both backend revision targets were present, and each rendered revision-details
  dialog reported displayed revision 10 and backend-advertised revision 10.

Immediately after an Options reload, Diagnostics initially contained no revision
targets. In the recorded Level 2 case, its normal publication approximately one
minute later contained both targets, without another refresh or restart. The test
waited for that publication rather than treating the initial snapshot as a result.
This observation is distinct from the permanent missing-target condition in #129.

### Coverage limits and supplemental checks

Existing entity-registry records were preserved. The live scenarios therefore
cover single-level configuration with retained registry history, not a fresh
installation where inactive-level registry entries have never existed. The
absent-registry case remains covered by `tests 2/test_single_level_ui.py`, which
builds mappings from entities actually created by HI and exercises generated YAML,
chip JavaScript and revision classification. It also checks missing required
bindings, Options changes and custom labels.

A separate browser-only probe supplied cloned unavailable states with cleared
`display_value` attributes. Both layouts retained the configured humidity and
temperature chips and displayed a dash for each exact chip. No Home Assistant
sensor state was changed; this is synthetic rendering coverage, not a live sensor
failure test.

An earlier probe retained a numeric temperature `display_value` while forcing only
its state to unavailable. Temperature still displayed that number. This behavior
also exists in the unchanged 2.1.0 renderer; live reachability was not established.
The observation is retained separately from the passing cleared-attribute probe
and from #129's configured-level inventory fix.

### Containment, restoration and soak

The preceding Lab soak was stopped with its partial evidence retained. Manual
handover and fan/humidifier isolation were verified before configuration changes
and after each reload. All four configured outputs belonged to the Lab's local
in-memory simulator. Their command counters remained unchanged during the
contained scenarios; no physical-output validation is claimed.

The original entry data/options, telemetry assignments, entity registry, saved
cards, dashboard resources and control-helper settings were restored exactly.
Fresh exports matched the original saved cards, and the installed package and
protected configuration hashes remained unchanged. Options reloads reset
in-memory Stability history.

A 48-hour reported-health soak started on 14 October 2026 at 18:45 UTC after
restoration. Its first checkpoint was healthy. It was stopped through the normal
controller lifecycle at 20:09 UTC that day for the authorized beta.2 deployment.
Its result is incomplete; the healthy checkpoint, preceding partial campaign and
older history were retained. It did not complete the planned 48 hours.

Before that start, a controller worker became unavailable. One reviewed relaunch
of the same controller version restored the native connection; no controller
upgrade or store repair was performed. This observation is separate from the HI
regression results.

The soak remains optional and non-blocking. It checks reported health over time;
it does not substitute for the single-level regression or accept a Stability baseline.

Private operational receipts and screenshots remain outside the public repository.
This sanitized record is sufficient to understand the scope and limits; private
credentials, entity IDs, machine paths and controller identifiers are not required.
