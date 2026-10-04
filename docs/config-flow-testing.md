# Native configuration-flow testing

Run native Home Assistant tests in a separate process from the stub-based suite.
These tests use disposable configuration directories and do not set up HI, contact
a running Home Assistant instance or call device services.

## What the transaction tests cover

`tests 2/test_config_flow_cancel_native.py` checks all six setup/options telemetry
Cancel entry points, Return with unsubmitted values, nested staged changes, Close
without saving, and rejection of a return destination that could invoke Save.

The persistence case creates a custom monitoring meaning and detection rule,
then uses HI's actual **Save changes** step and Home Assistant's unmodified
options-flow finish handler. Changes must remain staged until that boundary.
Home Assistant shutdown flushes the scheduled save, and a fresh Home Assistant
instance reads the same directory. The reopened options must retain the meaning,
guidance, rule and source identity. Reopening does not reuse the original storage
cache or call the store's private save method.

This exercises native selectors, flow results and persistence. It is not a browser
walkthrough of every configuration screen or evidence from an installed system.

## Reproduce the checks

Use a disposable virtual environment with a supported Python and Home Assistant.
The 2026-10-04 investigation used Home Assistant **2026.9.3**, its pinned
**orjson 3.11.9**, and CPython **3.14.5** and **3.14.7** on macOS arm64. Preserve
Home Assistant's dependency pins; record the resolved environment with the results.

```sh
python -X faulthandler "tests 2/test_config_flow_cancel_native.py"
python -X faulthandler "tests 2/test_config_flow_cancel_native.py" \
  NativeCancelTests.test_custom_meaning_main_save_persists_and_reopens_from_native_entry_store
python -X faulthandler -m pytest -q "tests 2/test_config_flow_cancel_native.py"
```

Each command must pass its assertions **and exit with status 0**. Repeat the full
suite and the isolated persistence case when changing fixture lifecycle or native
dependencies. An `OK` printed before a process crash is a failed run.

## Fixture cleanup and the shutdown failure

The original harness passed five tests and then crashed during interpreter
finalization. Stopping Home Assistant alone did not resolve it. Registry singleton
caches retained stopped fixture instances, including native storage fragments,
until Python destroyed its modules.

The fixture now registers shutdown and temporary-directory cleanup immediately,
runs shutdown even though it never starts HA, releases its thread-local ownership,
clears the four registry caches it used, and collects cycles at module teardown.
A weak-reference assertion fails if any fixture Home Assistant instance survives.
Persistence remains real; no storage, serializer or finish-handler substitution is
used. The registry cleanup is scoped to this separately run native test module.
Home Assistant's own [test fixtures](https://github.com/home-assistant/core/blob/2026.9.3/tests/conftest.py)
also reset thread-local ownership and collect garbage at known module boundaries.

This repairs the harness lifecycle; it does **not** fix the independent native
dependency/interpreter failure. The following minimal example reproduced SIGSEGV
on CPython 3.14.5 with orjson 3.11.9, without importing Home Assistant or HI:

```python
import orjson

cycle = {}
cycle["self"] = cycle
cycle["fragment"] = orjson.Fragment(b"{}")
```

Run that diagnostic only as its own disposable process. The tiny example exited
cleanly on the tested 3.14.7 build, while the earlier native persistence fixture
still crashed there. A diagnostic orjson 3.12.0 comparison also failed to resolve
the native fixture crash. Neither comparison justifies changing HA's dependency
pins or declaring the upstream issue fixed. Fixture results and this residual
environment risk must remain separate in release evidence.
