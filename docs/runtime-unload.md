# Runtime unload and recovery

HI stops runtime work before removing an entry's platforms. Successful unload
means its evaluations and background workers have finished, including visual
cleanup. A service call returning does not prove the physical light state.

## Public flash ownership

The admin-only `humidity_intelligence.flash_lights` service keeps its existing
schema. It remains separate from engine lane selection. Each accepted call has a
dedicated domain-owned task and uses the same light locks as internal visual alerts.
Admin authorization finishes before the admission check and task registration,
with no intervening await. A request authenticating across final closure is rejected,
even if another entry is subsequently set up.

Setup waits for any ongoing entry closure to succeed before reserving ownership.
A failed close wakes waiting setups and rejects them; cancelling a waiting setup
does not cancel the close or leave a reservation. Once admitted, an entry reserves
before its initialization first awaits and becomes available for new public calls
only after setup succeeds. A reservation already in progress
counts when another entry unloads. Failed setup uses the same cleanup path, so
removing the last reservation cannot orphan public calls or services.

Cancelled setup retains its platform-forwarding task until it settles. Rollback
then unloads only this attempt's initialized entry platforms, excluding platforms
from other entries and reset objects left by earlier attempts on older HA versions.
A loaded base component alone does not mean the entry platform was initialized.
Actual platform-unload failures still retain failed custody.

Unloading one of several entries preserves public calls and shared services for
the others. Last-owner closure rejects new public calls, cancels the owned flash
workers and waits for accepted service calls and captured-state restoration.
Services are removed only when all entries have successfully released ownership.
Normal completion and HI-managed cancellation preserve accepted-call custody;
optional power entities are not restored.

Restoration uses only captured `on` or `off` states; unknown, unavailable and
missing snapshots do not produce restoration commands. For an `on` snapshot,
HI restores brightness and effect with one color descriptor matching its captured
color mode, using Kelvin for color temperature. When an older/custom source omits
the mode, HI selects one saved descriptor rather than sending conflicting formats.

## Bounded runtime drainage

HI allows **30 seconds** for retained setup forwarding, engine and required
public-flash drainage. This wait
does not cancel the retained cleanup task. If a handler stalls, unload returns
failure before platform teardown and logs that restoration is unconfirmed. The
entry retains its engine, pending cleanup and light locks. Accepted work may still
finish, and cleanup may then attempt to restore the captured state.
The stopped engine keeps observing Manual until its owned work finishes. Even a
brief Manual ON/OFF handover permanently suppresses that worker's remaining writes;
evaluation and periodic control remain stopped.

A failed or interrupted unload closes new public-flash admission and blocks new
setup. Other loaded entries' engines continue, including CO control. A setup that
reserved before closure can finish, but cannot override a failed entry's admission
restriction. Late cleanup does not remove the entry, reopen admission or launch
deferred platform teardown. Repeated unload does not create a replacement drain.

Platform teardown follows successful runtime drainage and is governed separately
by Home Assistant; the 30-second bound does not cover platform teardown. Platform
failure retains **stopped** runtime custody. Cancellation of the unload caller also
retains the drain and marks HI's local lifecycle failed.
Cleanup failures log their original chained exception and traceback, including
failures that finish after the caller's wait has timed out.

## Recovery and limits

Check the Home Assistant log and resolve the stalled or failed device integration.
Then restart Home Assistant through the normal user-controlled workflow. HI does
not automatically restart, replay commands, re-enable a failed entry or silently
report recovery. HA marks a false unload result `FAILED_UNLOAD`, which ordinary
reload cannot recover; an interrupted HA unload may instead remain in progress.
HI retains its failed state in either case. A restart rebuilds normal entry
ownership and also resets HI's in-memory Stability history.

The custody guarantee covers HI-managed cancellation. It cannot guarantee device
completion after direct cancellation of a protected child/executor Future or HA
global shutdown. A timeout, cancellation or restart cannot recall an accepted
device command. External manual commands do not use HI's locks.

Offline regressions cover public and engine flashes, suspended forward/restore
calls, multiple entries, setup reservations and failures, authorization races,
caller cancellation, retained cleanup and platform failures. Native HA tests use
the actual service registry and executor on the supported compatibility versions.
They contact no devices and do not establish live or physical-light acceptance.
