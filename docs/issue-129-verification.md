# Issue #129: optional Lab verification

The live checks below passed on 14 October 2026 for the single-level V2 export fix.
They supplement the automated regressions and house review. **Lab verification is
optional and non-blocking:** its availability, result, playback coverage or soak
status is not a merge, promotion, tag, publication or release gate. A passing check
also does not grant release approval.

The record is pinned to the revision-10 package below. The beta.2 candidate uses
revision 11 and adds device-text, calculated-trend and issue-summary hardening.
Those changes are not covered by these live results or the ongoing soak. Validation does not transfer to changed package bytes.

## Tested identity

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

## Live results

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

## Coverage limits and supplemental checks

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

## Containment, restoration and soak

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

A fresh 48-hour reported-health soak started on 14 October 2026 at 18:45 UTC after
restoration. At the recorded handoff, its first of nine checkpoints was healthy;
the final checkpoint is scheduled for 16 October at 18:45 UTC. This is a running
soak, not a completed result. The preceding partial campaign and older history
were preserved.

Before that start, a controller worker became unavailable. One reviewed relaunch
of the same controller version restored the native connection; no controller
upgrade or store repair was performed. This observation is separate from the HI
regression results.

The soak remains optional and non-blocking. It checks reported health over time;
it does not substitute for the single-level regression or accept a Stability baseline.

Private operational receipts and screenshots remain outside the public repository.
This sanitized record is sufficient to understand the scope and limits; private
credentials, entity IDs, machine paths and controller identifiers are not required.
