import QtQuick

// State machine for the Bose popup and bar icon. Renders from the last
// confirmed snapshot plus at most one pending mutation and one queued intent
// drawn on top of it. Pending changes settle only on a verified read-back;
// failures revert to the last confirmed state and name the reason. Mutations
// are never retried. Input is never dropped for work in progress: a connection
// tap queues (latest wins, the same tap again cancels), a noise value is held
// until the change ends. The machines and their tables are shared with the
// dashboard (tests/machine-tables.json; docs/state-machines.md 5, 6).
QtObject {
  id: m

  property string baseUrl: "http://127.0.0.1:8847"
  // Optional function(method, path, body, done(error, json)) replacing XHR
  // (used by the offscreen harness with fixtures).
  property var transport: null
  property int requestTimeoutMs: 160000  // default deadline: outlasts the 150 s switch deadline; reads and noise use less

  property var snapshot: ({reachable: false, cached: true, devices: [], roles: {}, controllers: []})
  property bool loaded: false
  property bool helperDown: false
  property bool loading: false
  property bool savingRoles: false
  // Interaction (interactNext, the dashboard's interact): idle | choosing{address} (both slots full: pick one to replace)
  // | offer{slots} (Use here was busy: Replace per slot) | mutating{action, address, replace, label, here} (the change
  // in flight). Written only by uiSend; pending, replacing and busySlots are its readers.
  property var ui: ({kind: "idle"})
  readonly property var pending: ui.kind === "mutating" ? ui : null
  readonly property var replacing: ui.kind === "choosing" ? (deviceFor(ui.address) || {address: ui.address, name: ui.address}) : null
  readonly property var busySlots: ui.kind === "offer" ? ui.slots : null
  property int changes: 0          // connection changes started or ended: an overview or cache read sent before the latest is stale
  property bool refreshWanted: false   // Refresh pressed while work runs: read once it ends
  property var rolesWanted: null       // {roles, done}: Save pressed while work runs, sent once it ends
  readonly property bool refreshing: loading || refreshWanted
  readonly property bool saving: savingRoles || rolesWanted !== null
  property var notice: null        // {text, tone: "ok" | "error" | "pending"}
  property var slotOrder: [null, null]
  property var anc: ({kind: "idle"})   // noise writer (noiseNext): idle | waiting | held | sending; written only by noiseSend
  property var queue: ({kind: "idle"}) // intent queue (intentNext): idle | queued{intent}; written only by queueSend
  property real ancLastStart: 0
  readonly property var queuedIntent: queue.kind === "queued" ? queue.intent : null
  readonly property bool queuedHere: !!queuedIntent && queuedIntent.action === "here"
  readonly property bool ancHeld: anc.kind === "held"

  readonly property var roleNames: ({pc: "PC", mac: "Mac", phone: "Phone"})
  // Tap-to-switch texts from tests/switch-contract.json (tests/bose_model.qml keeps them equal).
  readonly property var messages: ({
    pending: "Connecting…", replacing: "Replacing {label}…", ok: "Playing on Bose 700",
    busy: "Both slots busy · choose one to replace", replace: "Replace {label}", retry_hint: " · tap to retry",
    errors: {unreachable: "Couldn’t reach the headphones", timeout: "Took too long to switch",
             unverified: "The headphones didn’t confirm the switch", keep_one: "Can’t replace that one: keep a phone, PC or Mac connected",
             no_audio: "Connected, but no sound from the headphones", audio_not_moved: "Headphones connected, but PC audio didn’t switch",
             forgotten: "The headphones forgot this PC · hold their Bluetooth button until “Ready to connect”"}
  })
  readonly property string hereAddress: (snapshot.roles || {})[snapshot.here] || ""
  // Use here works from cached state too: the controller reads the headset itself first.
  // Only its own Use here in flight disables it (a request cannot be taken back); during other work a tap queues.
  readonly property bool canUseHere: loaded && !helperDown && hereAddress !== "" && !(pending && pending.here)
  readonly property bool live: !!snapshot.reachable && !snapshot.cached
  readonly property bool ancBusy: anc.kind !== "idle"
  readonly property bool changeRunning: pending !== null || savingRoles
  readonly property bool workRunning: changeRunning || anc.kind === "sending"
  readonly property bool busy: changeRunning || ancBusy || queuedIntent !== null
  readonly property bool canMutate: live || changeRunning
  readonly property bool canNoise: !!snapshot.noise && (live || changeRunning)
  readonly property var devices: snapshot.devices || []
  readonly property var noiseShown: anc.kind === "idle" ? (snapshot.noise || null) : (anc.queued || anc.sent)
  readonly property int connectedCount: devices.filter(function(d) { return d.connected }).length
  readonly property bool barReachable: loaded && !helperDown && !!snapshot.reachable

  // The verified slots with the change in flight and the queued intent drawn over them (overlaySlots).
  readonly property var slots: {
    var base = []
    for (var i = 0; i < 2; i++) {
      var d = deviceFor(slotOrder[i])
      base.push(d && d.connected ? {address: d.address, st: "connected"} : {address: null, st: "free"})
    }
    var p = pending, q = queuedIntent
    var over = overlaySlots(base, p, q)
    return over.map(function(s) {
      var intent = s.pend === "queued" ? q : p
      var dev = s.address ? (deviceFor(s.address) || {address: s.address, name: intent && intent.name ? intent.name : s.address}) : null
      return {device: dev, state: s.st === "free" ? "empty" : s.st, queued: s.pend === "queued", here: s.here,
              replaced: s.replacing ? (nameOf(deviceFor(s.replacing)) || (intent && (intent.replaceName || intent.label)) || "") : ""}
    })
  }
  readonly property var savedDevices: {
    var drawn = slots.filter(function(s) { return s.state === "connecting" && s.device }).map(function(s) { return s.device.address })
    return devices.filter(function(d) {
      if (d.connected) return false
      if (m.pending && m.pending.action === "connect" && m.pending.address === d.address) return false
      return drawn.indexOf(d.address) < 0
    })
  }

  signal snapshotApplied()

  // ---------------------------------------------------------------- labels
  function deviceFor(address) {
    if (!address) return null
    for (var i = 0; i < devices.length; i++) if (devices[i].address === address) return devices[i]
    return null
  }
  function roleOf(address) {
    var roles = snapshot.roles || {}
    for (var r in roles) if (roles[r] === address) return r
    return ""
  }
  function nameOf(d) { return d ? (d.name || d.address) : "" }
  function tagOf(d) {
    var r = d ? roleOf(d.address) : ""
    if (!r) return ""
    if (r === snapshot.here) return r === "phone" ? "This phone" : "This " + roleNames[r]
    return roleNames[r] || r
  }
  function isHere(d) { return !!d && !!snapshot.here && roleOf(d.address) === snapshot.here }
  function kindOf(d) {
    var r = d ? roleOf(d.address) : ""
    if (r === "pc") return "desktop"
    if (r === "mac") return "laptop"
    if (r === "phone") return "phone"
    var n = String(d ? d.name : "").toLowerCase()
    if (/\btv\b|television/.test(n)) return "tv"
    if (/phone|pixel|galaxy|android/.test(n)) return "phone"
    if (/desktop|\bpc\b|tower/.test(n)) return "desktop"
    return "laptop"
  }
  function controllerLine() {
    var list = snapshot.controllers || []
    var parts = []
    for (var i = 0; i < list.length; i++) {
      var c = list[i]
      var who = roleNames[c.controller] || "Controller"
      var live = snapshot.reachable && !snapshot.cached
      var role = (snapshot.roles || {})[c.controller]
      var held = (snapshot.devices || []).some(function(d) { return d.address === role && d.connected })
      // A controller still checking whose own device holds a slot is shown as connected.
      var how = c.controller === snapshot.here && (c.reachable || live) ? "here"
              : c.reachable ? "available" : c.checking ? (held ? "connected" : "checking…") : "offline"
      parts.push("<b>" + who + "</b> " + how)
    }
    return parts.length ? "Controllers: " + parts.join(" · ") : ""
  }

  // ------------------------------------------------------------- transport
  property var inflight: []
  property Timer deadlineTicker: Timer {
    interval: 1000
    repeat: true
    running: m.inflight.length > 0
    onTriggered: {
      var now = Date.now(), keep = []
      for (var i = 0; i < m.inflight.length; i++) {
        var r = m.inflight[i]
        if (now < r.deadline) { keep.push(r); continue }
        r.dead = true
        try { r.xhr.abort() } catch (e) {}
        r.done({timeout: true, message: "No answer from the Bose helper."}, null)
      }
      m.inflight = keep
    }
  }
  function request(method, path, body, done, timeoutMs) {
    if (transport) { transport(method, path, body, done); return }
    var xhr = new XMLHttpRequest()
    var rec = {xhr: xhr, deadline: Date.now() + (timeoutMs || requestTimeoutMs), done: done, dead: false}
    inflight = inflight.concat([rec])
    xhr.onreadystatechange = function() {
      if (xhr.readyState !== XMLHttpRequest.DONE || rec.dead) return
      rec.dead = true
      m.inflight = m.inflight.filter(function(r) { return r !== rec })
      if (xhr.status === 0) { done({network: true, message: "The Bose helper on this PC isn't answering."}, null); return }
      var json = null
      try { json = JSON.parse(xhr.responseText) } catch (e) { done({message: "The helper sent an unreadable reply."}, null); return }
      if (xhr.status !== 200 || json.error) { done({message: String(json.error || ("Helper error " + xhr.status))}, json); return }
      done(null, json)
    }
    xhr.open(method, baseUrl + path)
    if (body) xhr.setRequestHeader("Content-Type", "application/json")
    xhr.send(body ? JSON.stringify(body) : "")
  }

  // ----------------------------------------------------------------- reads
  function stabilizeSlots(state) {
    var connected = (state.devices || []).filter(function(d) { return d.connected }).map(function(d) { return d.address })
    var next = [null, null]
    for (var i = 0; i < 2; i++) if (slotOrder[i] && connected.indexOf(slotOrder[i]) >= 0) next[i] = slotOrder[i]
    for (var j = 0; j < connected.length; j++) {
      if (next.indexOf(connected[j]) >= 0) continue
      var free = next.indexOf(null)
      if (free >= 0) next[free] = connected[j]
    }
    slotOrder = next
  }
  function applySnapshot(state) {
    if (!state) return
    stabilizeSlots(state)
    snapshot = state
    loaded = true
    helperDown = false
    if (ui.kind === "choosing" && (!live || connectedCount < 2)) uiSend({type: "drop-choice"})
    if (ui.kind === "offer" && connectedCount < 2) uiSend({type: "cancel"})
    snapshotApplied()
  }
  // Noise read-backs can carry an empty device list when the controller has no
  // earlier overview: merge noise/battery, and devices only when present.
  function mergeNoiseState(state) {
    if (!state) return
    var next = Object.assign({}, snapshot)
    if (state.noise) next.noise = state.noise
    if (state.battery !== undefined && state.battery !== null) next.battery = state.battery
    if (state.observed) next.observed = state.observed
    if (state.devices && state.devices.length) {
      next.devices = state.devices
      if (state.controllers) next.controllers = state.controllers
      if (state.roles) next.roles = state.roles
      stabilizeSlots(next)
    }
    snapshot = next
  }
  function loadCached(thenRefresh) {
    var gen = changes
    request("GET", "/api/cached", null, function(err, json) {
      if (err) { if (err.network) { m.helperDown = true; m.loaded = true } }
      else if (gen !== m.changes) {}
      else if (!m.loaded || m.snapshot.cached || (json.observed || 0) > (m.snapshot.observed || 0)) m.applySnapshot(json)
      if (thenRefresh) m.refresh()
    }, 30000)
  }
  // Refresh while work runs is not sent then (it would read a half-made change): it shows at once and runs when the
  // work ends (drain).
  function refresh() {
    if (loading) return
    if (workRunning || queuedIntent) { refreshWanted = true; return }
    refreshWanted = false
    loading = true
    var gen = changes
    request("GET", "/api/overview", null, function(err, json) {
      m.loading = false
      if (err) {
        if (err.network) m.helperDown = true
        m.loaded = true
        m.notice = {tone: "error", text: err.message + (err.network ? " Start the Bose Connections helper, then refresh." : "")}
        return
      }
      if (gen === m.changes) m.applySnapshot(json)
    }, 30000)
  }
  function opened() {
    notice = null
    uiSend({type: "drop-choice"})
    loadCached(true)
  }

  // -------------------------------------------------------------- machines
  // Pure transitions, the same as web/app.js (interact, noiser, intents, schedule, overlaySlots); tests/bose_model.qml
  // runs the shared tables of tests/machine-tables.json against these. An event a state does not take returns the same
  // state.
  function interactNext(s, e) {
    switch (e.type) {
    case "pick": if (s.kind === "mutating") return s
      return s.kind === "choosing" && s.address === e.address ? {kind: "idle"} : {kind: "choosing", address: e.address}
    case "cancel": return s.kind === "choosing" || s.kind === "offer" ? {kind: "idle"} : s
    case "drop-choice": return s.kind === "choosing" ? {kind: "idle"} : s   // a refresh or a tap ends a slot choice, not an offer
    case "start": if (s.kind === "mutating") return s
      return {kind: "mutating", action: e.action, address: e.address, replace: e.replace || null, label: e.label || null, here: !!e.here}
    case "busy": return s.kind === "mutating" && s.here ? {kind: "offer", slots: Array.isArray(e.slots) ? e.slots : []} : s
    case "settled": return s.kind === "mutating" ? {kind: "idle"} : s
    }
    return s
  }
  function noiseNext(s, e) {
    switch (e.type) {
    case "input": return s.kind === "sending" ? {kind: "sending", sent: s.sent, queued: e.value}
                       : s.kind === "held" ? {kind: "held", queued: e.value} : {kind: "waiting", queued: e.value}
    case "hold": return s.kind === "waiting" ? {kind: "held", queued: s.queued} : s
    case "resume": return s.kind === "held" ? {kind: "waiting", queued: s.queued} : s
    case "drop": return s.kind === "held" ? {kind: "idle"} : s
    case "send": return s.kind === "waiting" ? {kind: "sending", sent: s.queued, queued: null} : s
    case "ok": return s.kind !== "sending" ? s : s.queued ? {kind: "waiting", queued: s.queued} : {kind: "idle"}
    case "fail": return {kind: "idle"}
    }
    return s
  }
  function intentKey(i) { return i ? [i.action, i.address || "", i.replace || "", i.target || ""].join("|") : "" }
  function intentNext(s, e) {
    switch (e.type) {
    case "hold": return s.kind === "queued" && intentKey(s.intent) === intentKey(e.intent) ? {kind: "idle"} : {kind: "queued", intent: e.intent}
    case "cancel": case "release": return {kind: "idle"}
    }
    return s
  }
  function schedule(w) {
    if (w.change) return w.noise.kind === "waiting" ? "hold-noise" : "wait"
    if (w.noise.kind === "sending") return "wait"
    if (w.intent.kind === "queued") return "intent"
    if (w.noise.kind === "held") return w.live ? "resume-noise" : "drop-noise"
    if (w.noise.kind === "waiting") return "noise"
    return "idle"
  }
  function overlaySlots(slots, flight, queued) {
    var out = slots.map(function(s) { return {address: s.address || null, st: s.st, was: s.address || null, pend: null, replacing: null, here: false} })
    var layers = [[flight, "flight"], [queued, "queued"]]
    for (var l = 0; l < layers.length; l++) {
      var a = layers[l][0], how = layers[l][1]
      if (!a || !a.address) continue
      if (a.action === "disconnect") {
        for (var k = 0; k < out.length; k++) if (out[k].address === a.address && out[k].st === "connected" && !out[k].pend) { out[k].st = "disconnecting"; out[k].pend = how; break }
        continue
      }
      if (a.action !== "connect" && a.action !== "here") continue
      if (out.some(function(s) { return s.address === a.address && (s.st === "connected" || s.st === "connecting") })) continue
      var i = -1
      for (var j = 0; j < out.length && i < 0; j++)
        if (a.replace ? (out[j].address === a.replace && out[j].st !== "free") : (out[j].st === "free" && !out[j].pend)) i = j
      for (var n = 0; n < out.length && i < 0 && !a.replace; n++) if (out[n].st === "disconnecting") i = n
      if (i < 0) continue
      var old = out[i]
      out[i] = {address: a.address, st: "connecting", was: old.was, pend: how, here: !!a.here,
                replacing: a.replace || (old.st === "disconnecting" ? old.address : null)}
    }
    return out
  }
  function uiSend(e) { ui = interactNext(ui, e) }
  function noiseSend(e) { anc = noiseNext(anc, e) }
  function queueSend(e) { queue = intentNext(queue, e) }

  // The one scheduler, called whenever work ends or input arrives: the queued intent first, then the noise writer.
  readonly property string droppedNoiseText: "Noise change not sent: the headphones aren’t reachable now"
  function drain() {
    for (var n = 0; n < 4; n++) {
      var d = schedule({change: changeRunning, noise: anc, intent: queue, live: live})
      if (d === "hold-noise") { noiseSend({type: "hold"}); ancGap.stop(); return }
      if (d === "resume-noise") { noiseSend({type: "resume"}); continue }
      if (d === "drop-noise") { noiseSend({type: "drop"}); notice = {tone: "error", text: droppedNoiseText}; return }
      if (d === "intent") {
        var i = queuedIntent
        queueSend({type: "release"})
        runIntent(i, true)
        if (workRunning) return
        continue
      }
      if (d === "noise") { pumpNoise(); return }
      if (d !== "idle") return
      // Nothing else to run: the deferred Save, then the deferred Refresh.
      if (rolesWanted) { var r = rolesWanted; rolesWanted = null; saveRoles(r.roles, r.done); return }
      if (refreshWanted) refresh()
      return
    }
  }

  // ------------------------------------------------------------- mutations
  // Every connection input goes through act: at once when nothing else runs, else the one queued intent.
  function act(intent) {
    if (workRunning) { uiSend({type: "drop-choice"}); queueSend({type: "hold", intent: intent}); return }
    if (queuedIntent) queueSend({type: "cancel"})
    runIntent(intent, false)
  }
  function cancelQueued() { queueSend({type: "cancel"}) }
  // A released intent is checked against the verified state first: the slots may have changed while it waited.
  function runIntent(i, fromQueue) {
    if (i.action === "here") { switchHereNow(i.replace || "", i.replaceName || ""); return }
    var d = deviceFor(i.address)
    if (!d || !live) { if (fromQueue) notice = {tone: "error", text: (i.action === "connect" ? "Connect" : "Disconnect") + " not sent: the headphones aren’t reachable now"}; return }
    if (i.action === "disconnect") {
      if (!d.connected) { notice = {tone: "ok", text: nameOf(d) + " is already disconnected"}; return }
      mutate({action: "disconnect", address: d.address}, {action: "disconnect", address: d.address, name: nameOf(d)})
      return
    }
    if (d.connected) { notice = {tone: "ok", text: nameOf(d) + " is already connected"}; return }
    var rep = i.replace && deviceFor(i.replace) && deviceFor(i.replace).connected ? deviceFor(i.replace) : null
    if (connectedCount >= 2 && !rep) { uiSend({type: "pick", address: d.address}); return }   // the slots filled meanwhile: ask, never guess
    if (rep) mutate({action: "connect", address: d.address, replace: rep.address},
                    {action: "connect", address: d.address, name: nameOf(d), replace: rep.address, replaceName: nameOf(rep)})
    else mutate({action: "connect", address: d.address}, {action: "connect", address: d.address, name: nameOf(d)})
  }
  function connectDevice(d) {
    if (!canMutate || !d) return
    notice = null
    // A slot that a disconnect in flight frees counts as open: the connect queues behind it. With both slots full and
    // a change running, the connect queues too and asks for the slot when it is released (the slots may change).
    var leaving = pending && pending.action === "disconnect" ? 1 : 0
    if (connectedCount - leaving >= 2 && !changeRunning) { uiSend({type: "pick", address: d.address}); return }
    act({action: "connect", address: d.address, name: nameOf(d)})
  }
  function replaceSlot(slotDevice) {
    var d = replacing
    uiSend({type: "cancel"})
    if (!canMutate || !d || !slotDevice) return
    act({action: "connect", address: d.address, name: nameOf(d), replace: slotDevice.address, replaceName: nameOf(slotDevice)})
  }
  function cancelReplace() { uiSend({type: "cancel"}) }
  function disconnectDevice(d) {
    if (!canMutate || !d) return
    notice = null
    uiSend({type: "drop-choice"})
    act({action: "disconnect", address: d.address, name: nameOf(d)})
  }
  function successText(p) {
    if (p.action === "disconnect") return p.name + " disconnected"
    return p.replace ? p.name + " connected in place of " + p.replaceName : p.name + " connected"
  }
  // Contract text for a failed connection change: the controller's error_key, else the transport failure.
  function errorText(err, json) {
    var key = json && json.error_key
    if (key === "busy") return messages.busy
    if (key && messages.errors[key]) return messages.errors[key]
    if (err && err.timeout) return messages.errors.timeout
    if (err && err.network) return messages.errors.unreachable
    return String((json && (json.error || json.message)) || messages.errors.unreachable)
  }
  function replaceText(slot) { return messages.replace.replace("{label}", slot ? slot.label : "") }
  // One tap: move the headset to this PC (POST /api/switch). Busy offers a Replace per slot; never guesses.
  function switchHere(replace) {
    if (!canUseHere) return
    if (!replace && queuedHere) { cancelQueued(); return }   // the same tap again cancels the queued Use here
    var label = ""
    for (var i = 0; replace && busySlots && i < busySlots.length; i++) if (busySlots[i].address === replace) label = busySlots[i].label
    uiSend({type: "cancel"})
    act({action: "here", address: hereAddress, name: nameOf(deviceFor(hereAddress)) || "This PC", replace: replace || "", replaceName: label, here: true})
  }
  function switchHereNow(replace, label) {
    var here = hereAddress
    if (!here) return
    changes++
    uiSend({type: "start", action: "connect", address: here, replace: replace || null, label: label || null, here: true})
    notice = {tone: "pending", text: replace ? messages.replacing.replace("{label}", label || "device") : messages.pending}
    var body = {source: "omarchy", request_id: Math.random().toString(36).slice(2, 10)}
    if (replace) body.replace = replace
    request("POST", "/api/switch", body, function(err, json) {
      m.changes++
      m.uiSend(json && json.busy ? {type: "busy", slots: json.slots || []} : {type: "settled"})
      if (json && json.ok && json.verified) {
        var order = m.slotOrder.slice()
        var at = replace ? order.indexOf(replace) : order.indexOf(null)
        if (at >= 0 && order.indexOf(here) < 0) { order[at] = here; m.slotOrder = order }
        if (json.state) m.applySnapshot(json.state)
        m.notice = {tone: "ok", text: m.messages.ok}
      } else if (json && json.busy) {
        m.notice = null
      } else {
        m.notice = {tone: "error", text: m.errorText(err, json && json.error_key ? json : null) + m.messages.retry_hint}
      }
      m.drain()
    }, 160000)
  }
  function mutate(body, p) {
    changes++
    uiSend({type: "start", action: body.action, address: body.address, replace: body.replace || null})
    function done(n) { m.changes++; m.uiSend({type: "settled"}); m.notice = n; m.drain() }
    request("POST", "/api/override", body, function(err, json) {
      if (err || !json || json.ok === false) { done({tone: "error", text: m.errorText(err, json)}); return }
      if (!json.verified) {
        if (json.state) m.applySnapshot(json.state)
        done({tone: "error", text: m.messages.errors.unverified})
        return
      }
      // Keep the confirmed device in the cup it was drawn in.
      if (p.action === "connect") {
        var order = m.slotOrder.slice()
        var at = p.replace ? order.indexOf(p.replace) : order.indexOf(null)
        if (at >= 0) { order[at] = p.address; m.slotOrder = order }
      }
      if (json.state) {
        m.applySnapshot(json.state)
        done({tone: "ok", text: m.successText(p)})
        return
      }
      // Older peer without `state`: one read-back, pending stays until it lands.
      m.request("GET", "/api/overview", null, function(err2, json2) {
        if (!err2) m.applySnapshot(json2)
        done(err2 ? {tone: "error", text: "Change confirmed, but the new state could not be read. Refresh."}
                  : {tone: "ok", text: m.successText(p)})
      }, 30000)
    }, 160000)
  }

  // Noise: at most one write in flight plus one newest value, writes start at least 250 ms apart, intermediate values
  // are dropped. During a connection change the value is held and sent when the change ends; if the headset is out of
  // reach then, it is dropped and the notice says so. Never dropped silently.
  property Timer ancGap: Timer { onTriggered: m.drain() }
  function setNoise(level, enabled) {
    if (!snapshot.noise) return
    if (!canNoise) { notice = {tone: "error", text: droppedNoiseText}; return }
    notice = null
    noiseSend({type: "input", value: {level: Math.max(0, Math.min(10, Math.round(level))), enabled: !!enabled}})
    drain()
  }
  function pumpNoise() {
    if (anc.kind !== "waiting" || changeRunning) return
    var wait = 250 - (Date.now() - ancLastStart)
    if (wait > 0) { ancGap.interval = wait; ancGap.restart(); return }
    var q = anc.queued
    var c = snapshot.noise
    noiseSend({type: "send"})
    if (c && c.level === q.level && c.enabled === q.enabled) { noiseSend({type: "ok"}); drain(); return }   // already so: nothing to send
    ancLastStart = Date.now()
    request("POST", "/api/override", {action: "noise", level: q.level, enabled: q.enabled}, function(err, json) {
      var ok = !err && json && json.ok !== false && json.verified
      if (ok) {
        if (json.state) m.mergeNoiseState(json.state)
        else m.mergeNoiseState({noise: {level: q.level, enabled: q.enabled}})
      }
      m.noiseSend({type: ok ? "ok" : "fail"})
      if (m.anc.kind === "idle" || !ok) {
        m.notice = ok ? {tone: "ok", text: "Noise cancellation updated"}
                      : {tone: "error", text: err ? err.message : String((json && (json.error || json.message)) || "Noise change not verified.")}
      }
      m.drain()
    }, 20000)
  }

  // ------------------------------------------------------------- settings
  // Save while other work runs is kept and sent when it ends (drain): never a settings write alongside a change.
  function saveRoles(roles, done) {
    if (savingRoles || workRunning || queuedIntent || anc.kind !== "idle") { rolesWanted = {roles: roles, done: done}; notice = null; return }
    savingRoles = true
    notice = null
    request("POST", "/api/roles", {roles: roles}, function(err) {
      m.savingRoles = false
      if (err) { m.notice = {tone: "error", text: err.message}; m.drain(); return }
      m.notice = {tone: "ok", text: "Controller settings saved"}
      if (done) done()
      m.refresh()
      m.drain()
    }, 30000)
  }
}
