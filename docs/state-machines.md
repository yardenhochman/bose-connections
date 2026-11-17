# State machines: inventory and decisions

Audit of 2026-11-16, extended 2026-11-17 (instant input: machines 5, 6 and 6b). Every place where the app's behaviour depends on a phase. For each one: where it lives, its
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
| 5 | Noise (ANC) writer, dashboard and popup | `web/app.js:49-66`, `357-394`; `linux/BoseModel.qml:247-259`, `452-480` | explicit; held state added | done |
| 6b | Intent queue and scheduler, dashboard and popup | `web/app.js:67-103`, `390-420`; `linux/BoseModel.qml:261-345` | explicit (new) | done |
| 6 | Omarchy popup model (`BoseModel.qml`) | `linux/BoseModel.qml:19-40`, `200-480` | noise and intents explicit; the interaction flags in backlog | partial: backlog |
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

`mutating` is the one change in flight. A tap during it no longer meets a disabled control: it goes to the intent
queue (6b), and the cups draw both layers with `overlaySlots`.

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

## 5. Noise writer (`noiser`, popup `noiseNext`)

- **State:** `anc.m` (dashboard) and `anc` (popup): `idle`, `waiting{queued}`, `held{queued}` or `sending{sent, queued}`.
  The popup's `ancInFlight` and `ancQueued` pair is gone.
- **Shown value:** `noiseShown(m)`, the newest input, or `null` when idle (then the verified headset value shows).
- **Transitions:**
  - `input` from `idle` or `waiting` goes to `waiting{v}`, from `held` to `held{v}`; while `sending` it sets `queued=v`.
  - `hold` from `waiting` goes to `held`: a connection change or switch is running.
  - `resume` from `held` goes to `waiting`: the change ended and the headset is reachable.
  - `drop` from `held` goes to `idle`: the change ended with the headset out of reach. The display reverts and the
    status line says "Noise change not sent: the headphones aren’t reachable now".
  - `send` from `waiting` goes to `sending`.
  - `ok` while `sending` goes to `waiting{queued}` if a value is queued, otherwise to `idle`.
  - `fail` goes to `idle`: the display reverts to the verified headset value and the error is shown.
- **Throttle:** 250 ms between sends. A burst sends its first value and then its last.
- **Cue:** a held value shows at once, with a hollow ochre ring and "Level 4 · applies when the switch ends" ("… when the
  change ends" for a Connect or Disconnect). A value being sent shows a filled pulsing light and "Setting level 4…".
- **Popup only:** a write whose value already equals the verified one is skipped (`send`, then `ok`, no request).

Before 2026-11-17 the slider and switch were disabled during a connection change, and the popup's `setNoise` dropped
input while `!canNoise` with no notice.

Tests: the shared table `noiser` in `tests/machine-tables.json`. `tests/web_machines.cjs` runs it against `noiser`, and
`tests/bose_model.qml` against `noiseNext`.

## 6b. Intent queue and scheduler (`intents`, `schedule`, `overlaySlots`)

The backend runs one operation at a time, and the front ends keep it so: at most one `/api/override` or `/api/switch`
request is open. The queueing happens in the front-end machines; the backend is unchanged.

- **State:** `iq` (dashboard) and `queue` (popup): `idle` or `queued{intent}`. An intent is
  `{action: connect | disconnect | here | switch, address, replace, target}`.
- **Only writer:** `queueSend`, through `intents` (popup: `intentNext`).
- **Transitions:**
  - `hold(i)` from `idle` goes to `queued{i}`. From `queued{j}` it goes to `queued{i}`: the latest wins.
  - `hold(i)` from `queued{i}` goes to `idle`: tapping the same pending control again cancels it. "Same" is the same
    `intentKey` (action, address, replace, target).
  - `cancel` and `release` go to `idle`.
- **Entry:** every connection input goes through `act`. With nothing running it runs at once; otherwise it becomes the
  queued intent.
- **Scheduler:** `schedule({change, noise, intent, live})` is the one decision. `pump` (popup: `drain`) calls it whenever
  work ends or input arrives.

| change running | noise | intent | decision |
|---|---|---|---|
| yes | `waiting` | any | `hold-noise` |
| yes | other | any | `wait` |
| no | `sending` | any | `wait` |
| no | not `sending` | `queued` | `intent`: release it and run it |
| no | `held` | `idle` | `resume-noise` if live, else `drop-noise` |
| no | `waiting` | `idle` | `noise` (after the throttle gap) |

- **Change running:** this page's connection change in flight, or, for the dashboard on `/api/state`, a switch running
  anywhere. A queued intent goes before a noise value, and that value is then held behind it, so a slider drag cannot
  starve a tap.
- **Release check:** a released intent is checked against the verified state first.
  - A disconnect of a device that is no longer connected, or a connect of one that already is, says so and sends
    nothing.
  - A connect that finds both slots full asks which slot to replace. It never guesses.
  - With the headset out of reach, it says so and sends nothing.
- **Drawing:** `overlaySlots(slots, flight, queued)` is pure. It draws the change in flight and the queued intent over
  the verified slots and never writes them, so a late reply can only update the layer underneath.
  - A queued connect takes the free slot, or the slot that a disconnect in flight frees.
  - A queued switch target is not drawn in a cup, because the controller picks the slot. Its row and Use here say
    "Queued".
- **Looks:** dashboard `style.css`; popup `SlotCup.qml` and `PillButton.qml`. Light and dark.
  - Verified: surface fill, green light, solid text.
  - In flight: no fill, solid ochre outline, faded device, a turning arc, and "Connecting…", "Disconnecting…" or
    "Moving here…".
  - Queued: no fill, dotted ochre outline, fainter device, a hollow ring, "Connects next", "Disconnects next" or
    "Moves here next", and a "Queued · cancel" control.
- **Deadlines:** every request has one, so a hung request cannot hold the queue.
  - Dashboard: connection changes 160 s, because they may wait out a 150 s switch on the controller. Noise 20 s, reads
    and `/api/roles` 30 s, the accepting `POST /api/switch` 15 s, the long-poll its `wait` plus 10 s.
  - Popup: 160 s for changes and Use here, 20 s for noise, 30 s for reads.
  - A timed-out change says "Controller timed out" or "Took too long to switch". If it was only slow, the controller
    still serializes it behind the switch lock.
- **Failure:** a released intent fails like any change. It reverts to the verified state and shows the error. While a
  released intent runs, the status line keeps the result of the work before it.

Tests:
- `tests/machine-tables.json`: the `intents` and `schedule` tables, run against both front ends.
- `tests/web_machines.cjs`:
  - latest wins and cancel;
  - ANC held behind a switch, then sent with its newest value;
  - a held value dropped when the headset is unreachable;
  - an intent before a waiting noise value;
  - a late `ok` for an older noise value;
  - `overlaySlots` cases, including a stale read underneath a queued intent.
- `tests/gui-fixtures.cjs`, overview mode:
  - a queue during a Disconnect, latest wins and a held slider;
  - the order of the requests (`disconnect`, `connect`, `noise`) and at most one request open;
  - cancel, and a failed queued disconnect reverting;
  - a held value dropped when the change ends unreachable;
  - Use here queued behind a noise write.
- `tests/gui-fixtures.cjs`, `/api/state` mode:
  - a Disconnect queued and cancelled during a switch;
  - the held value sent only once the switch ends;
  - a Move-to queued behind a noise write.
- `tests/bose_model.qml` `runInstant`: the same cases for the popup, plus a stale overview landing after a queued tap.
- `tests/render_popup.qml` renders the popup's in-flight and queued looks offscreen (light and dark) for review.

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
- **Done 2026-11-17:** the noise writer and the intent queue are the dashboard's machines (5, 6b), and the harness
  runs the shared tables against them. `canMutate` and `canNoise` no longer depend on work in progress; only its own
  Use here in flight disables Use here.
- **Backlog: the rest of the interaction state as one value.** `pending`, `replacing` and `busySlots` are still three
  properties. Use the dashboard's `interact`, or follow `/api/state` as the dashboard does. The offscreen harness is
  the test bed.

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
| Dashboard and QML: ANC controls during a connection change or switch | disabled until the change ended | **fixed** 2026-11-17: held, sent when it ends (5) |
| Dashboard: Connect, Disconnect and Use here during an ANC write | disabled for the write (0.3–1 s) | **fixed**: queued (6b) |
| Dashboard: Use here, Move to and Connect during a running switch | disabled (one operation at a time) | **fixed**: queued; the backend still runs one at a time (6b) |
| QML: Connect, Disconnect and Use here during a change or ANC write | disabled | **fixed**: queued (6b) |
| Dashboard and QML: a refresh landing after a change | undid the shown result | **fixed** |
| QML: `setNoise` while `!canNoise` | input dropped with no notice | **fixed**: held during a change; unreachable says so (5) |
| QML: slider while pressed | sends on release only | matches the rule: the final value is sent |
| Dashboard and QML: a request with no deadline | a hung fetch could hold the queue | **fixed**: a deadline on every request (6b) |
| Dashboard and QML: Refresh during work in progress | disabled | kept: a read sent during a change is dropped anyway (17) |
| QML: Save in controller settings during work | disabled | kept: a settings form, not a headset control |
| Android: tile tap while busy, `requestNoise` while `mutating` | input dropped | backlog (7) |
| Android: one `work` executor | refresh and ANC wait behind a switch of up to 150 s | backlog (7) |
| Mac: all items while `changing`, noise presets | disabled; no queue | backlog (9) |

GUI assertions that encoded the disabled UI, changed on 2026-11-17 in `tests/gui-fixtures.cjs`:
- "Other mutations must be disabled while one runs" (Connect into the open slot). It now checks that Disconnect and the
  slider stay enabled and that one cup spins.
- "One operation at a time: other actions disabled" (`/api/state`, Move to Mac). It now checks that a tap queues and
  that nothing reaches the controller during the switch.
- "One mutation at a time" moved to the backend boundary: the fixture counts open `/api/override` and `/api/switch`
  requests and fails above one.

What the native front ends still lack. Neither could be built here (no JDK, no macOS):
- **Android** (`BoseTileService`, `ConnectionsActivity`): no queued intent, no held noise value, no pending or queued
  looks; a busy tap is dropped. The in-app web page is `web/app.js` and has all of it.
- **Mac** (`Launcher.m` menu): items are disabled while `changing`, and noise presets are not queued. The popover and
  window are `web/app.js` and have all of it.

## Backlog, by user impact

1. Android tile and panel (7): one state value, the intent queue and held noise of 5 and 6b (the shared tables in
   `tests/machine-tables.json` are the spec), pending and queued looks, and a separate executor for reads. Needs a JDK
   to compile, plus the emulator for a check.
2. QML model (6): `pending`, `replacing` and `busySlots` as one value, or follow `/api/state` as the dashboard does.
3. Mac menu (9): queue the last noise preset and a tap during `changing`, and clear stale `menuMessage`. Needs macOS.
4. A boot id in `/api/state`, so a restarted controller does not stall the long-poll for 25 s (4).
5. `LineWatcher.stop` race (10): only if the service ever starts stopping its watchers.
