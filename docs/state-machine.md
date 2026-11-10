# Connection state machine (PC hub)

Status: spec, 2026-11-10. Owner of the truth: the PC controller (`controller.py`, user service
`bose-control.service`, loopback :8847, mesh :8848). Every front end renders this state; none runs its own
switch flow. Replaces the two separate flows (desk-bar `controls_actions.switch_steps` and
`Controller.switch`) that drifted apart and left a Mac→PC tap unfinished on 2026-11-10.

## 1. Device model (reconciled view)

Inputs, each with an observation time:

| source | what it says | latency |
|---|---|---|
| headset read (BMAP status from any controller: PC local, phone relay, Mac relay) | which saved devices hold a slot | 0.3–1 s per read |
| PC BlueZ `Device1.Connected` (D-Bus `PropertiesChanged`, watched continuously) | PC link up/down | instant |
| peer `/api/status` `link:false` (Mac IOBluetooth, phone) | that controller has no link | per read |
| PipeWire: Bose A2DP sink present, default sink | PC audio ready | instant (`pactl subscribe`) |

Per saved device, one state: `connected`, `disconnected`, `connecting`, `releasing`, `unknown`.

Rules, in order:
1. An OS "no link" for a controller's own device wins over the headset read: `disconnected`.
2. While an operation is releasing or connecting a device, that device shows `releasing` / `connecting`.
3. Otherwise the newest headset read decides `connected` / `disconnected`.
4. No headset read in the last 60 s and no OS evidence: `unknown`, shown with its age ("2 min ago").
5. PC link up (BlueZ) but the newest read (older than the link-up) lacks the PC: `connected` (BlueZ is newer).

Headset: `reachable` (via which controller, read age), `unreachable` (each controller's reason:
not connected, app not running, no answer), battery, noise.

## 2. Operation machine (one at a time)

```
idle ──tap(target)──▶ reading ──▶ (already on target) ─────────────────────────▶ audio ─▶ done
                         │──▶ releasing(device) ──▶ connecting(target) ──▶ audio ─▶ done
                         │──▶ connecting(target) ──────────────────────────▶ audio ─▶ done
                         └──▶ choose(slots)            (no single clear slot to release)
any step ──error/timeout──▶ failed(step, error_key, text)      done/failed ──8 s or next tap──▶ idle
```

- Target: `pc` (this PC), `mac`, `phone` (front ends on any device can move the headset to any device).
- `releasing`: both slots full and the target holds neither. Release rule: keep the phone, so release the
  one slot that is not the phone. Target is the phone (both slots are PC/Mac/other): no single clear
  choice, so go to `choose`. `choose` waits for `replace=<address>` (a new tap with the choice) or cancel; it
  never guesses.
- `connecting(pc)`: BlueZ `Device1.Connect` from the PC first (one page, ~2–5 s). Not linked: BMAP connect
  through a controller that reaches the headset, resent at most once after a fresh read shows a free slot.
  Still not linked: page every 3 s up to 45 s. Forgotten key (link up, AVDTP refused): the existing same-tap
  re-pair path.
- `connecting(mac|phone)`: BMAP connect through a controller that reaches the headset (the target device
  pages itself where its controller supports it).
- `audio` (target pc only): wait for the A2DP sink (event-driven, not polling), select A2DP / relink /
  restart WirePlumber only when stopped (existing ladder), set default sink, read back.
- Each step has its own timeout and the whole operation one 150 s deadline. A command whose reply may still
  be outstanding is never resent (existing rule).
- Each transition records `started_at` and, on leaving, `seconds`. `done`/`failed` keep the step list.

## 3. API (loopback :8847; mesh :8848 serves the same `GET` to peers with the token)

`GET /api/state?after=<seq>&wait=<s>` — long-poll. Returns at once when `seq > after`, else waits up to
`wait` (max 25) seconds for the next change, then returns the current state. No `after`: returns at once.

```json
{
  "seq": 412,
  "now": 1794325000.12,
  "headset": {"reachable": true, "via": "pc", "read_age": 1.4, "battery": 40,
              "noise": {"level": 10, "enabled": true}, "product": "Bose 700",
              "controllers": [{"id": "pc", "state": "here"}, {"id": "phone", "state": "available"},
                              {"id": "mac", "state": "offline", "reason": "Headset is not connected to this Mac"}]},
  "slots": [{"address": "…", "role": "phone", "label": "Phone", "name": "Yarden's S22 Ultra", "state": "connected"},
            {"address": "…", "role": "pc", "label": "PC", "name": "yarden-omarchy", "state": "connecting"}],
  "devices": [{"address": "…", "role": "mac", "label": "Mac", "name": "…", "state": "disconnected"}],
  "audio": {"sink": "bluez_output.….1", "default": true},
  "operation": {
    "id": "k3f9a2", "source": "desk", "target": "pc", "phase": "connecting",
    "started_at": 1794324998.0, "deadline": 150,
    "steps": [{"name": "reading", "label": "Checking the headphones", "state": "done", "seconds": 0.4},
              {"name": "releasing", "label": "Releasing the Mac", "state": "done", "seconds": 1.4},
              {"name": "connecting", "label": "Connecting this PC", "state": "active", "since": 1794324999.9},
              {"name": "audio", "label": "Starting audio", "state": "pending"}],
    "result": null
  }
}
```

- `slots` always has two entries; a free slot is `{"state": "free"}`.
- `operation` is `null` when idle. `result` on finish: `{"ok": true, "text": "Playing on Bose 700",
  "seconds": 4.1}` or `{"ok": false, "error_key": "…", "text": "…", "step": "releasing", "detail": "…"}`;
  a `choose` phase carries `"choices": [{"address", "label"}]`.
- Step labels and result texts come from `tests/switch-contract.json` (`messages` and a new `steps` table);
  front ends show them verbatim.

`POST /api/switch` `{source, request_id?, target?: "pc"|"mac"|"phone" (default: this controller),
replace?}` — starts an operation and returns `{"accepted": true, "operation": {…}, "seq": n}` at once (no
longer blocks until done). A tap while one runs returns `{"accepted": false, "operation": <running>}`.
Front ends then follow `GET /api/state`. `POST /api/switch/cancel` ends a `choose` phase.

Compatibility: `?wait=1` on `POST /api/switch` keeps the old blocking reply shape (contract tests, the
current Mac and Android builds).

## 4. Watchers

- BlueZ: `busctl --system monitor` / `dbus-monitor` on the headset's `Device1` `PropertiesChanged`
  (Connected) → immediate state change, no polling.
- PipeWire: `pactl subscribe` sink events → `audio` field.
- Headset read: on start, after every operation, on BlueZ link change, and every 20 s while any client
  long-polls in the last 60 s (every 120 s otherwise). Reads never run concurrently with an operation's own
  reads.

## 5. Logs and timing

One `bose.switch` line per operation (unchanged format) plus one
`bose.timing id=… reading=… releasing=… connecting=… audio=… total=…`. Targets: Mac→PC tap to audio
p50 ≤ 5 s; already on PC ≤ 0.5 s; state change visible in every UI ≤ 0.5 s after it happens.
