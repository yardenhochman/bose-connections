# State machines: inventory and decisions

Audit of 2026-11-16, extended 2026-11-17 (instant input: machines 5, 6 and 6b), then the whole backlog closed on
2026-11-17 (branch `backlog-fixes`: Android, Mac, popup interaction, boot id, watcher race, Refresh and Save).
Every place where the app's behaviour depends on a phase. For each one: where it lives, its
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
| 2 | Dashboard interaction (connect, replace choice, Use here offer) | `web/app.js:8-19`, `71-75` | explicit; table shared (popup, Android) | done |
| 3 | Dashboard Use-here tap on shared state | `web/app.js:21-38`, `394`, `620-632` | explicit | done |
| 4 | Dashboard link to `/api/state` | `web/app.js:40-49`, `416-424` | explicit; boot id (eb5eb54) | done |
| 5 | Noise (ANC) writer, dashboard and popup | `web/app.js:49-66`, `357-394`; `linux/BoseModel.qml:247-259`, `452-480` | explicit; held state added | done |
| 6b | Intent queue and scheduler, dashboard and popup | `web/app.js:67-103`, `390-420`; `linux/BoseModel.qml:261-345` | explicit (new) | done |
| 6 | Omarchy popup model (`BoseModel.qml`) | `linux/BoseModel.qml` | explicit: one `ui` value (74a2079) | done |
| 7 | Android tile and panel | `android/TileModel.java`, `android/Machines.java`, `android/BoseTileService.java` | explicit (d40beaf, 6589a35) | done |
| 8 | Android core and switcher | `android/Core.java`, `android/Switcher.java` | `LOCAL_OK` fixed (9920bdf); switch loop left (procedural) | done |
| 9 | Mac menu (`Launcher.m`) | `mac/Machines.h`, `mac/Launcher.m` | intents and noise explicit (2a665d5) | done |
| 10 | Watcher child lifecycle | `statemachine.py:281-320` | stop race fixed (eb5eb54) | done |
| 11 | Headset read scheduler | `statemachine.py:361-383` | leave | — |
| 12 | Hub inputs: own link, audio, read age | `statemachine.py:140-260` | leave | — |
| 13 | Switch algorithm steps | `controller.py:751-835` | leave (procedural) | — |
| 14 | Forgotten-key re-pair job | `controller.py:700-740` | leave | — |
| 15 | Discovery window | `controller.py:274-296` | leave | — |
| 16 | Probe futures, prelude cache, `ident_ok` | `controller.py:211-212`, `297-333`, `492-495` | leave | — |
| 17 | Dashboard overview refresh | `web/app.js` `refresh`, `pump` | leave; race fixed; deferred during work (6104bd2) | done |
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

The table is `interact` in `tests/machine-tables.json` since 2026-11-17; it runs against the dashboard, the popup
(`interactNext`) and Android (`Machines.interact`).

**Fixed 2026-11-17 (6104bd2):** a Connect with both slots full while a change ran sent `pick`, which `mutating`
refuses, so the tap did nothing and said nothing. It now queues (6b); its row shows "Connects next · asks which slot
to replace" and "Queued · cancel", and on release it asks for the slot. GUI check "Connect into full slots during a
change is queued".

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

**Fixed 2026-11-17 (eb5eb54): a restarted controller stalled the long-poll.** `seq` starts again from 0, so the first
poll with the old `after` waited out its full 25 s. The snapshot now carries `boot` (`Hub.boot`, a random id per
process). The page sends `&boot=` with `after` and takes `seq` and `boot` from every snapshot; the controller answers a
poll that names another boot at once. Tests: `test_a_restarted_controller_answers_an_old_after_at_once`
(`tests/test_state_machine.py`) and the GUI check "After a controller restart the page must catch up at once"; both
failed before the change.

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

Before 2026-11-17 the model's phase was spread across several properties: `pending`, `replacing`, `busySlots`,
`loading`, `savingRoles`, `ancInFlight`, `ancQueued` and `notice`, with the derived `busy`, `canMutate`, `canUseHere`
and `canNoise`. Now three machine values hold it: `ui` (2), `anc` (5) and `queue` (6b); `loading`, `savingRoles`,
`refreshWanted` and `rolesWanted` are request flags with one writer each.

It talks to the old `/api/overview` and `/api/switch` endpoints, not `/api/state`.

- **Fixed: a stale read could undo a change.** `canUseHere` ignores `loading`. An overview requested before a Use here
  could therefore land after it and restore the old slots, and so could the 30 s `loadCached` poll in `Panel.qml`. A
  `changes` counter now drops reads that were sent before the latest change. The offscreen harness
  (`tests/bose_model.qml`) covers this case, and the check fails without the guard.
- **Done 2026-11-17:** the noise writer and the intent queue are the dashboard's machines (5, 6b), and the harness
  runs the shared tables against them. `canMutate` and `canNoise` no longer depend on work in progress; only its own
  Use here in flight disables Use here.
- **Done 2026-11-17 (74a2079): the interaction state as one value.** `ui` (`interactNext`, the dashboard's
  `interact`) is written only by `uiSend`; `pending`, `replacing` and `busySlots` are now read-only views of it, so the
  views did not change. The old flags allowed a Use here offer and a slot choice at once, like the dashboard before
  machine 2; the harness check "picking a device closes the Use here offer" covers it. A connect into full slots during
  a change queues and asks on release, as on the dashboard.
- **Done 2026-11-17: Refresh and Save during work.** Both were disabled while work ran. Refresh now sets
  `refreshWanted` (button drawn dotted, as a queued control) and reads once `drain` reaches idle; the settings Save
  keeps `rolesWanted` ("Saves after the change", dotted) and sends `/api/roles` once the change ends, never alongside
  it. The `changes` counter also moves when a change ends, so a read sent during a change is dropped.
  `tests/render_popup.qml` renders both looks (scenes `refresh` and `save`).
- The popup still reads `/api/overview`, not `/api/state`: it is the PC's own controller on loopback and gets each
  change's verified state in the reply. Following `/api/state` would be a separate rewrite with no gap left to close.

## 7. Android tile and panel (`TileModel`, `Machines`, `BoseTileService`)

Done 2026-11-17 (d40beaf, 6589a35). Before, the phase was spread over `mutating`, `switching`, `ancInFlight`,
`reading`, `replacing`, `pendingAction` and `tileNote`; a busy tile tap was ignored with no feedback; `requestNoise`
checked `mutating` but not `switching`, so an ANC write could run during a switch; each tile note posted an
`updateTile` that was never cancelled; and one executor queued every read and ANC write behind a switch of up to 150 s.

- **State:** `TileModel` (no Android types) holds the snapshot and three machines from `android/Machines.java`, the
  dashboard's `interact`, `noiser` and `intents`, plus `schedule` and `overlaySlots`. `drain` is the one scheduler.
  `BoseTileService` only draws the model and runs its requests.
- **Tile tap:** during other work it becomes the queued Use here; the subtitle says "Queued here" at once and a second
  tap cancels it. During its own switch it changes nothing (the subtitle already says "Connecting…").
- **Noise:** held behind a connection change or switch ("Level 3 · applies when the change ends"), written 250 ms apart
  with the newest value, dropped with "Noise change not sent: the headphones aren’t reachable now" when the change
  ends unreachable.
- **Refresh:** during work it reads once the work ends; a read answered after a change started or ended is dropped.
- **Threads:** writes (`work`) and reads (`reads`) have their own executors. The model keeps one write open at a time.
- **Tile notes:** a newer note cancels the older note's pending refresh (`Host.cancel` → `removeCallbacks`).
- **Looks:** in flight: no fill, solid ochre outline, faded device, pulsing light, "Connecting…" or "Disconnecting…"
  in a washed button. Queued: dotted ochre outline, hollow light, fainter device, "Connects next" (with "Replacing
  <device>" when it takes a slot being freed) and "Queued · cancel". A queued connect into full slots shows in its row.
  A busy switch opens the panel with "Both slots busy · choose one to replace" and Replace on each cup.
- **Tests:** `tests/android/MachinesTest.java` runs `interact`, `noiser`, `intents` and `schedule` of
  `tests/machine-tables.json` plus overlay cases; `tests/android/TileModelTest.java` drives the model through a fake
  host (latest wins, held noise, busy tap feedback and cancel, offer and Replace, full slots, failure revert and
  re-read, deferred refresh, stale read, note cancellation, noise burst, one request open). Both run under
  `tests/test_android_contract.py` with the JDK. The old behaviour cannot run in the JVM (Android types); mutating the
  model back to it (tap ignored while busy, noise not held, refresh not deferred) fails 8 checks.
- **Checked on an emulator** (preview build, headless, never the phone): offer, in flight with a held value, queued,
  and the queued tile, light and dark.

## 8. Android core and switcher

- **Fixed (9920bdf): `LOCAL_OK` outlived the link.** It was set by a good read and cleared only by a failed overview
  probe. After the link dropped, every noise write still tried Bluetooth first, and `fullState` marked the phone as a
  reachable controller in a peer's reply. `open()` now clears it with `IDENT_OK`. `tests/android/CoreTest.java` runs
  `Core` in the JVM with stub Android types (`tests/android/shim/android`) and failed before the fix.
- **Left: the switch loop's attempt state** (up to 3 passes, a resend only with at least 30 s left) is a loop counter
  with one writer, the mirror of the Python switch algorithm (13). `SwitcherTest` covers every contract scenario plus
  14 cases; a table would add risk without changing anything a front end sees.

## 9. Mac menu (`mac/Machines.h`, `Launcher.m`)

Done 2026-11-17 (2a665d5). Before, every item was disabled while `changing`, noise presets were not queued, Refresh was
skipped while changing, and `menuMessage` stayed until the next refresh succeeded.

- **Machines:** `mac/Machines.h` holds `BoseNoiser`, `BoseNoiseShown`, `BoseIntents`, `BoseIntentKey`, `BoseSchedule`
  and `BoseReleaseCheck` (Foundation only). `pump` is the one scheduler; at most one `/api/override` or `/api/switch`
  request is open.
- **Items stay enabled during work.** A click then is the one queued intent (latest wins; the same row again, or
  "Queued · cancel", cancels it), drawn with a mixed-state mark and "Connects next", "Disconnects next" or "Moves here
  next". On release it is checked against the verified snapshot (already connected or disconnected, both slots full
  without a replace, headset unreachable: it says so and sends nothing).
- **Noise:** held behind a change ("Level n · applies when the change ends"), then sent 250 ms apart, newest value
  last; a value equal to the verified one is skipped; failure reverts and says so.
- **Refresh during work** shows "Refreshing after the change…" and reads once the scheduler is idle; `changes` moves
  when a change starts and ends, so a read sent during it is dropped.
- **Result line:** any new input clears it; it expires after 8 s (success) or 30 s (error).
- **Tests:** `tests/mac/MachinesTest.m` runs the shared tables and release-check cases (117 checks) on macOS;
  `tests/test_mac_contract.py` compiles and runs it there and keeps the static checks on Linux. The menu glue
  (timers, drawing) is covered by the compile only: the installed app was not replaced or run.

## 10–18. Left as they are

- **10. `LineWatcher`:** a supervisor loop with one thread as its writer. **Fixed (eb5eb54):** a `stop()` that landed
  between the loop check and `popen` left a child running until its next output line. `stop()` and the child's start
  now share a lock (`spawn`): a stop either sees the child and terminates it, or prevents it from starting. Test:
  `test_stop_between_the_loop_check_and_popen_leaves_no_child`, which failed before.
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
- **17. Dashboard refresh:** a two-state `refreshing` toggle, plus `refreshWanted` since 2026-11-17 (a press during
  work reads once it ends and keeps the work's result line). **Fixed race:** in overview mode (the Android in-app page
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
| Dashboard and QML: Refresh during work in progress | disabled | **fixed** 2026-11-17: drawn queued, reads once the work ends (6, 17) |
| QML: Save in controller settings during work | disabled | **fixed**: kept and sent once the change ends, never alongside it (6) |
| Dashboard and QML: Connect with both slots full during a change | tap ignored with no notice (dashboard) | **fixed**: queued, asks for the slot on release (2) |
| Android: tile tap while busy, `requestNoise` while switching | input dropped / written during a switch | **fixed**: queued with feedback; noise held (7) |
| Android: one `work` executor | refresh and ANC wait behind a switch of up to 150 s | **fixed**: reads on their own executor; work queued by the model (7) |
| Android: tile notes | each posted an `updateTile` never cancelled | **fixed**: a newer note cancels it (7) |
| Mac: all items while `changing`, noise presets, stale result line | disabled; no queue; message kept | **fixed** (9) |
| Dashboard: a restarted controller | long-poll stalled 25 s | **fixed**: boot id (4) |

GUI assertions that encoded the disabled UI, changed on 2026-11-17 in `tests/gui-fixtures.cjs`:
- "Other mutations must be disabled while one runs" (Connect into the open slot). It now checks that Disconnect and the
  slider stay enabled and that one cup spins.
- "One operation at a time: other actions disabled" (`/api/state`, Move to Mac). It now checks that a tap queues and
  that nothing reaches the controller during the switch.
- "One mutation at a time" moved to the backend boundary: the fixture counts open `/api/override` and `/api/switch`
  requests and fails above one.

Every front end now has the queued intent and the held noise value: dashboard, popup, Android tile and panel, Mac
menu. The Android in-app page and the Mac popover and window are `web/app.js`.

## Backlog

Empty since 2026-11-17. Left on purpose, with the reason:
- **1b:** the switch lock and the operation phase stay two values (blocking `?wait=1` callers need the lock).
- **8:** the Android switch loop's attempt counter (procedural, mirrors 13).
- **Popup on `/api/overview`:** see 6.
- **Mac menu interaction flags:** `changing`, `pending` and `busySlots` stay as fields. The menu is rebuilt from them
  on every open and has no slot-choice screen that could clash with the busy offer; the queue and noise, where input
  was lost, are explicit.
