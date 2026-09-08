# Runtime Simulation Validation

This maintainer validation harness proves backend-owned Air Control Mode truth with
deterministic fake telemetry. It is local validation infrastructure for code checks.
V2.1 display fixtures, HA Lab evidence, and live Home Assistant runtime validation
remain separate surfaces.

HA Lab is an optional advisory surface. Its availability, result, playback coverage,
or soak state must not be used as a promotion or release blocker.

## Scope

The harness in `tests 2/hi_runtime_fixtures.py` creates a fresh fake Home
Assistant runtime for each scenario, feeds configured telemetry entities into
`HIAutomationEngine`, refreshes the computed core sensors, and reads the
`HI Air Control Mode` and `HI Air Control Reason` sensors.

It covers:

- baseline normal telemetry
- all configured humidity unavailable or unknown
- all configured temperature unavailable or unknown
- distinct Kitchen, Hallway, and Bedroom room values for zone delta pressure
- Level 1 IAQ pressure independent of zone pressure
- disabled/manual/global gates
- isolation-off Manual handover for switch, fan, AQ, and humidifier outputs, including
  repeated evaluation, delayed-work cancellation, observed-only truth, AUTO resume,
  and the CO-only ventilation exception
- CO ppm defaulting clear at `0`
- opt-in CO emergency pressure
- per-run reset back to baseline telemetry
- restored humidifier demand with an observed-off output
- prompt reconciliation when an output stops during sustained demand
- no duplicate write when the observed output is already on
- missing, unknown, unavailable, unsupported-service, and service-exception paths
- non-blocking `humidifier`, `fan`, and `switch` command dispatch
- bounded 30-second/120-second retry timing, final confirmation, and fault latching
- isolation release, shared-output OR ownership, and conflicting-output suppression
- sanitized humidifier diagnostics plus V2 Mobile/Tablet and gallery truth strings
- every `hi.reason.v1` runtime family, line/size/privacy bounds, and presentation
  failure isolation from technical reason and service/lane truth
- the strict V2 reason renderer's valid, malformed, future-schema, Unicode, escaping,
  raw-ID, and atomic-fallback behavior

## Run

Use the direct harness when local pytest collection is blocked by missing Home
Assistant test dependencies:

```bash
python3 "tests 2/test_air_control_mode_simulation.py"
python3 "tests 2/test_humidifier_reconciliation.py"
python3 "tests 2/test_reason_presentation.py"
node "tests 2/test_reason_card_renderer.mjs"
```

Expected local pass output:

```text
28 air-control mode simulation checks passed.
42 humidifier reconciliation checks passed.
14 reason-presentation contract checks passed.
13 reason-card renderer checks passed.
```

Where full test dependencies are available, this file can also be run through
pytest:

```bash
python3 -m pytest -q "tests 2/test_air_control_mode_simulation.py"
```

## Safety Boundaries

- Fake telemetry is test-only Python data.
- The harness runs locally without creating helpers, services, automations,
  dashboards, or persistent Home Assistant entities.
- Fan and humidifier output isolation defaults on, so fake scenarios stay away from
  fan output writes by default.
- Humidifier reconciliation tests replace Home Assistant services and entity state
  with local fakes. They verify command intent and observed-state handling without
  calling a real device or claiming physical moisture production.
- CO pressure cannot be triggered accidentally. A CO value at or above the
  emergency threshold requires `co_pressure=True` in the scenario.
- Each run constructs a fresh fake runtime, keeping scenario state isolated between
  cases.

## Release Interpretation

Passing this harness proves the backend engine can consume simulated telemetry
and that the exposed Air Control Mode/Reason sensors reflect the selected
runtime mode for the covered scenarios.

Passing the humidifier reconciliation harness additionally proves the covered demand,
dispatch, observed-state, retry, ownership, diagnostics, and generated-V2 truth
contracts at source level. It cannot prove a vendor integration accepted a command,
a physical device actuated, or moisture was produced.

It complements:

- full Home Assistant install/update validation
- startup log review
- HACS packaging/preflight checks
- generated dashboard export and visual checks
- physical device/output validation
