# State machines: inventory and decisions

Audit of 2026-11-16. Every place where the app's behaviour depends on a phase. For each one: where it lives, its
states and transitions, what was wrong, and whether it was made explicit. [state-machine.md](state-machine.md) is the
spec of the PC hub's connection model and switch flow. This file covers the code that implements that spec, plus the
front ends.

"Explicit" means four things:
- one typed state value;
- one transition function or table that is its only writer, where an event the state does not accept changes
  nothing;
- tests that cover the table.

Line numbers are those on the branch that made the change.

## Summary

| # | Machine | Where | Decision | Status |
|---|---|---|---|---|
| 1 | Operation phase (switch / override) | `statemachine.py:32-120`, `controller.py:579-690` | explicit | done |
| 1b | Operation slot: switch lock ↔ hub operation | `controller.py:649-676` | race fixed; left as lock + phase | done |
| 2 | Dashboard interaction (connect, replace choice, Use here offer) | `web/app.js:8-19`, `71-75` | explicit | done |
| 3 | Dashboard Use-here tap on shared state | `web/app.js:21-38`, `394`, `620-632` | explicit | done |
| 4 | Dashboard link to `/api/state` | `web/app.js:40-49`, `416-424` | explicit | done |
| 5 | Dashboard noise (ANC) writer | `web/app.js:51-60`, `286-300` | explicit | done |
| 6 | Omarchy popup model (`BoseModel.qml`) | `linux/BoseModel.qml:19-30`, `202-360` | stale-read race fixed; conversion in backlog | partial: backlog |
| 7 | Android tile and panel (`BoseTileService`) | `android/BoseTileService.java:25-240` | backlog | not changed |
| 8 | Android core and switcher | `android/Core.java`, `android/Switcher.java` | backlog | not changed |
| 9 | Mac menu (`Launcher.m`) | `mac/Launcher.m:60-260` | backlog | not changed |
| 10 | Watcher child lifecycle | `statemachine.py:273-303` | leave | — |
| 11 | Headset read scheduler | `statemachine.py:361-383` | leave | — |
| 12 | Hub inputs: own link, audio, read age | `statemachine.py:140-260` | leave | — |
| 13 | Switch algorithm steps | `controller.py:751-835` | leave (procedural) | — |
| 14 | Forgotten-key re-pair job | `controller.py:700-740` | leave | — |
| 15 | Discovery window | `controller.py:274-296` | leave | — |
| 16 | Probe futures, prelude cache, `ident_ok` | `controller.py:211-212`, `297-333`, `492-495` | leave | — |
| 17 | Dashboard overview refresh | `web/app.js:77`, `382-388` | leave; race fixed | done |
| 18 | Android relay service | `android/RelayService.java` | leave | — |

## 1. Operation phase (backend)

One switch or connection change. Every front end that follows `GET /api/state` renders it.

- **State:** `Operation.phase`, a `Phase` `StrEnum`. It stays a plain string in JSON and in comparisons.
- **Only writer:** `Operation._go`, checked against `TRANSITIONS`. The methods that call it are `step`, `choose` and
  `finish`.
- **Start:** an operation is born in its first step: `reading` for a switch, and `connecting` or `releasing` for an
  override.

| from \ to | reading | releasing | connecting | audio | choose | done / failed |
|---|---|---|---|---|---|---|
| reading | keep | ✓ | ✓ | ✓ | ✓ | ✓ |
| releasing | ✓ | keep | ✓ | — | ✓ | ✓ |
| connecting | ✓ | ✓ | keep | ✓ | ✓ | ✓ |
| audio | ✓ | — | — | keep | — | ✓ |
| choose | — | — | — | — | — | ✓ |
| done, failed | — | — | — | — | — | — |

- **keep:** re-entering the active step keeps its timer and updates only its label and marks.
- **Back to `reading`:** a same-tap re-pair runs the switch again on the same operation.
- **`connecting → releasing`:** when no controller can read the headset, the PC pages first, then may release a slot.
- **Illegal changes:** an illegal change raises `IllegalTransition` and changes nothing. Inside a switch it ends the
  operation as `failed`, so the operation is never left in a running phase.

Found before the change:
- **No phase in the accepted reply.** `POST /api/switch` answered `{accepted:true, operation:{phase:null, steps:[]}}`,
  because the worker thread had not yet entered `reading`. On the dashboard the tap's "Checking the headphones" step
  disappeared and then came back.
- **Phase was a free string.** Any code could set any value, for example a `step()` after `finish()`.

Tests: `tests/test_state_machine.py` `PhaseTableTests`. They check every from/to pair, the birth step, the kept timer,
an illegal step inside a switch, and the accepted reply.

## 1b. Operation slot (switch lock and hub operation)

"An operation is running" is stored twice: `Controller.switch_lock` is held, and `hub.operation.running` is true. The
worker settles the operation first, then releases the lock. A tap that landed between those two moments got
`{accepted:false}` with the finished operation. **Fixed:** when no operation is running, `switch_start` waits up to 2 s
for the lock instead of refusing. Test: `test_a_tap_right_after_a_finish_is_accepted_not_rejected`. It failed before
the fix.

The lock and the phase stay as two values. The lock serializes the blocking `?wait=1` and override callers, while the
phase is what front ends see. Merging them would mean moving every blocking caller onto the hub's condition variable,
which is out of scope.

## 2. Dashboard interaction (`interact`)

- **State:** `ui`. It replaces three loose globals: `op`, `choosing` and `busySlots`.
- **Only writer:** `uiSend`. Readers use `mut()`, `choosingAddr()` and `offerSlots()`.

| state \ event | pick(a) | cancel | drop-choice | start | busy | settled |
|---|---|---|---|---|---|---|
| idle | choosing(a) | idle | idle | mutating | idle | idle |
| choosing(a) | idle if same a, else choosing(b) | idle | idle | mutating | — | — |
| offer(slots) | choosing(a) | idle | — | mutating | — | — |
| mutating | — | — | — | — | offer if `here` | idle |

`—` means the state stays the same. `drop-choice` is sent by a refresh or a switch tap. Before the change, both of
these cleared only `choosing`.

Found before the change: **a Use here offer and a slot choice at once.** After a busy Use here reply (`busySlots` set),
pressing Connect on a saved device also set `choosing`. The page then showed the Replace-per-slot box and the
replace-target cups together.

## 3. Use-here tap on shared state (`tapper`, `foldAccepted`)

- **State:** `ST.taps`, which is `idle`, `posting{tap}` or `refused{fail}`. It replaces `ST.tap` and `ST.fail`.
- **Transitions:**
  - `tap` from `idle` or `refused` goes to `posting`.
  - `answered` from `posting` goes to `idle`.
  - `refused` from `posting` goes to `refused`.
  - `operation` from `refused` goes to `idle`: a snapshot that carries an operation replaces the local refusal.
- **Expiry:** a refusal is shown for 8 s; `shownOp` derives this from the time.

Found before the change: **a late reply could replace a newer operation.** The reply to `POST /api/switch` replaced the
snapshot's operation whenever the two ids differed. A reply that arrived after a newer snapshot already showed a newer
operation would therefore put the older one back. `foldAccepted` now keeps the snapshot when the snapshot is newer
(higher `seq`) and its operation started no earlier. A restarted controller counts `seq` from 0 again, so start times
still order its operations.

## 4. Link to `/api/state` (`linker`)

- **State:** `ST.link`, which is `boot`, `live`, `lost` or `legacy`. It replaces `ST.mode` and `ST.lost`.
- **`boot`:** a snapshot goes to `live`; an error or a 404 goes to `legacy`.
- **`live` and `lost`:** an error goes to `lost` (with backoff of 1 s, doubling up to 8 s), a snapshot goes to `live`,
  and a 404 goes to `legacy`.
- **`legacy`** is final.

Known and not fixed: after the controller restarts, `seq` starts again from 0. The first long-poll with the old
`after` then waits out its full 25 s before the page catches up. Fixing this needs a boot id in the snapshot; see the
backlog.

## 5. Noise writer (`noiser`)

- **State:** `anc.m`, which is `idle`, `waiting{queued}` or `sending{sent, queued}`. It replaces
  `anc.desired/queued/inFlight`.
- **Shown value:** `noiseShown(m)`, the newest input, or `null` when idle.
- **Transitions:**
  - `input` from `idle` or `waiting` goes to `waiting{v}`.
  - `input` while `sending` sets `queued=v`.
  - `send` from `waiting` goes to `sending`.
  - `ok` while `sending` goes to `waiting{queued}` if a value is queued, otherwise to `idle`.
  - `fail` goes to `idle`: the display reverts to the verified headset value and the error is shown.
- **Throttle:** 250 ms between sends. A burst sends its first value and then its last.

No bug was found here. The conversion is for DX and AX.

## 6. Omarchy popup model (`linux/BoseModel.qml`)

The model's phase is spread across several properties:
- `pending`, which holds a connect, disconnect or here action;
- `replacing`, `busySlots`, `loading` and `savingRoles`;
- `ancInFlight`, `ancQueued` and `notice`;
- the derived `busy`, `canMutate`, `canUseHere` and `canNoise`.

It talks to the old `/api/overview` and `/api/switch` endpoints, not `/api/state`.

- **Fixed: a stale read could undo a change.** `canUseHere` ignores `loading`. An overview requested before a Use here
  could therefore land after it and restore the old slots, and so could the 30 s `loadCached` poll in `Panel.qml`. A
  `changes` counter now drops reads that were sent before the latest change. The offscreen harness
  (`tests/bose_model.qml`) covers this case, and the check fails without the guard.
- **Backlog: convert to one state value.** Use the same states as the dashboard's `interact`, or follow `/api/state`
  as the dashboard does. The offscreen harness is the test bed.

## 7–9. Android and Mac (backlog)

Neither front end could be built or run here: there is no JDK on this machine and no macOS. Changing their state code
blind is riskier than leaving it, so the following findings come from a read-only sweep and are not fixed.

- **Android `BoseTileService`.**
  - Its phase is spread over `mutating`, `switching`, `ancInFlight`, `reading`, `replacing`, `pendingAction` and
    `tileNote`.
  - `busy()` covers `mutating || ancInFlight || switching`.
  - `requestNoise` checks `mutating` but not `switching`, so an ANC write can run during a switch.
  - A tile tap while busy is ignored with no feedback.
  - Each `setTileNote` posts an `updateTile` that is never cancelled.
  - The single-thread `work` executor queues every refresh and ANC write behind a switch of up to 150 s.
- **Android `Core` and `Switcher`.**
  - The switch loop's attempt state is implicit: up to 3 passes, and a resend only with at least 30 s left.
  - `LOCAL_OK` is never cleared once set.
  - These mirror the Python rules and are tested by `tests/test_android_contract.py` when a JDK is present.
- **Mac `Launcher.m`.**
  - Its phase is spread over `refreshing`, `changing`, `pending`, `busySlots` and `menuMessage`.
  - Every menu item is disabled while `changing`.
  - Noise presets are not queued.
  - `menuMessage` stays until the next refresh succeeds.
  - The popover and window are `web/app.js` and get machines 2–5.

## 10–18. Left as they are

- **10. `LineWatcher`:** a supervisor loop with one thread as its writer. A `stop()` that lands between the loop check
  and `popen` can leave a child running until its next output line. Only tests call `stop()`; the service never stops
  its watchers.
- **11. `ReadScheduler`:** one thread with `last` and `kicked`. Its only rule, skipping reads during an operation,
  reads `hub.running()`, which is now table-backed.
- **12. Hub inputs:** these are observations, not phases. The precedence rules for `own_link`, the read age and
  peers' `link:false` are spec §1 and are tested in `ModelTests`.
- **13. Switch algorithm:** the order of steps is procedural code with blocking I/O and one deadline. The operation
  record (machine 1) is the explicit state it moves through. Rewriting the algorithm as a table would add risk without
  changing any state that front ends can see.
- **14. Re-pair job:** a two-state `repairing` flag with one writer, under `repair_lock`.
- **15. Discovery window:** `discovery_restore` set means the window is open. It has one writer under
  `discovery_lock`, and a timer restores the setting.
- **16. Caches:** `probes` are in-flight futures that are reused, `last_overview` is a TTL cache and `ident_ok` is a
  handshake cache. None of these is a phase.
- **17. Dashboard refresh:** a two-state `refreshing` toggle. **Fixed race:** in overview mode (the Android in-app page
  and older controllers), a refresh sent before a Connect or Disconnect could land afterwards and undo the verified
  result. The `mutations` counter now drops such replies. The GUI check "A refresh answered after a change" fails on
  the old code.
- **18. Android relay service:** a listen loop with a fixed 5 s retry, restarted by Android (`START_STICKY`).

## Responsiveness rule: where it is violated

The rule: an input shows at once, the work runs behind it, repeated input is throttled with the final value sent, and
a failure reverts and says so.

| Where | Violation | Status |
|---|---|---|
| Dashboard and QML: ANC controls during a connection change | disabled until the change ends | kept; see the note below |
| Dashboard: Connect, Disconnect and Use here during an ANC write | disabled for the write (0.3–1 s) | kept: one control channel |
| Dashboard: Use here and Connect during a running switch | disabled (one operation at a time) | kept: the backend allows one operation; the card shows it |
| Dashboard and QML: a refresh landing after a change | undid the shown result | **fixed** |
| QML: `setNoise` while `!canNoise` | input dropped with no notice | backlog (6) |
| QML: slider while pressed | sends on release only | matches the rule: the final value is sent |
| Android: tile tap while busy, `requestNoise` while `mutating` | input dropped | backlog (7) |
| Android: one `work` executor | refresh and ANC wait behind a switch of up to 150 s | backlog (7) |
| Mac: all items while `changing`, noise presets | disabled; no queue | backlog (9) |

Note on the ANC row: queueing a noise change behind a switch of up to 150 s needs a product decision about what the
slider shows in the meantime. The GUI suite also asserts "one mutation at a time".

## Backlog, by user impact

1. Android tile and panel (7): one state value, a queued ANC final value, feedback on a busy tap, and a separate
   executor for reads. Needs a JDK to compile, plus the emulator for a check.
2. QML model (6): one state value, or follow `/api/state` as the dashboard does.
3. Mac menu (9): queue the last noise preset, and clear stale `menuMessage`. Needs macOS.
4. A boot id in `/api/state`, so a restarted controller does not stall the long-poll for 25 s (4).
5. `LineWatcher.stop` race (10): only if the service ever starts stopping its watchers.
