import QtQuick

// State machine for the Bose popup and bar icon. Renders from the last
// confirmed snapshot plus at most one pending mutation drawn on top of it.
// Pending changes settle only on a verified read-back; failures revert to the
// last confirmed state and name the reason. Mutations are never retried.
QtObject {
  id: m

  property string baseUrl: "http://127.0.0.1:8847"
  // Optional function(method, path, body, done(error, json)) replacing XHR
  // (used by the offscreen harness with fixtures).
  property var transport: null
  property int requestTimeoutMs: 120000

  property var snapshot: ({reachable: false, cached: true, devices: [], roles: {}, controllers: []})
  property bool loaded: false
  property bool helperDown: false
  property bool loading: false
  property bool savingRoles: false
  property var pending: null       // {action, address, replace, name, replaceName}
  property var replacing: null     // saved device waiting for a slot choice
  property var notice: null        // {text, tone: "ok" | "error"}
  property var slotOrder: [null, null]
  property var ancInFlight: null   // {level, enabled}
  property var ancQueued: null
  property real ancLastStart: 0

  readonly property var roleNames: ({pc: "PC", mac: "Mac", phone: "Phone"})
  readonly property bool live: !!snapshot.reachable && !snapshot.cached
  readonly property bool ancBusy: ancInFlight !== null || ancQueued !== null
  readonly property bool busy: pending !== null || ancBusy || savingRoles
  readonly property bool canMutate: live && !busy && !loading
  readonly property bool canNoise: live && !!snapshot.noise && pending === null && !savingRoles
  readonly property var devices: snapshot.devices || []
  readonly property var noiseShown: ancQueued || ancInFlight || snapshot.noise || null
  readonly property int connectedCount: devices.filter(function(d) { return d.connected }).length
  readonly property bool barReachable: loaded && !helperDown && !!snapshot.reachable

  readonly property var slots: {
    var out = []
    for (var i = 0; i < 2; i++) {
      var d = deviceFor(slotOrder[i])
      out.push(d && d.connected ? {device: d, state: "connected"} : {device: null, state: "empty"})
    }
    var p = pending
    if (p && p.action === "connect") {
      var idx = -1
      for (var j = 0; j < 2; j++)
        if (p.replace ? (out[j].device && out[j].device.address === p.replace) : out[j].state === "empty") { idx = j; break }
      if (idx >= 0) out[idx] = {device: deviceFor(p.address) || {address: p.address, name: p.name}, state: "connecting", replaced: p.replaceName || ""}
    } else if (p && p.action === "disconnect") {
      for (var k = 0; k < 2; k++)
        if (out[k].device && out[k].device.address === p.address) out[k] = {device: out[k].device, state: "disconnecting"}
    }
    return out
  }
  readonly property var savedDevices: devices.filter(function(d) {
    if (d.connected) return false
    if (m.pending && m.pending.action === "connect" && m.pending.address === d.address) return false
    return true
  })

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
        r.done({timeout: true, message: "No answer from the Bose helper after 2 minutes."}, null)
      }
      m.inflight = keep
    }
  }
  function request(method, path, body, done) {
    if (transport) { transport(method, path, body, done); return }
    var xhr = new XMLHttpRequest()
    var rec = {xhr: xhr, deadline: Date.now() + requestTimeoutMs, done: done, dead: false}
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
    if (replacing && (!live || connectedCount < 2)) replacing = null
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
    request("GET", "/api/cached", null, function(err, json) {
      if (err) { if (err.network) { m.helperDown = true; m.loaded = true } }
      else if (!m.loaded || m.snapshot.cached || (json.observed || 0) > (m.snapshot.observed || 0)) m.applySnapshot(json)
      if (thenRefresh) m.refresh()
    })
  }
  function refresh() {
    if (loading || pending) return
    loading = true
    request("GET", "/api/overview", null, function(err, json) {
      m.loading = false
      if (err) {
        if (err.network) m.helperDown = true
        m.loaded = true
        m.notice = {tone: "error", text: err.message + (err.network ? " Start the Bose Connections helper, then refresh." : "")}
        return
      }
      m.applySnapshot(json)
    })
  }
  function opened() {
    notice = null
    replacing = null
    loadCached(true)
  }

  // ------------------------------------------------------------- mutations
  function connectDevice(d) {
    if (!canMutate || !d) return
    notice = null
    if (connectedCount >= 2) { replacing = d; return }
    mutate({action: "connect", address: d.address}, {action: "connect", address: d.address, name: nameOf(d)})
  }
  function replaceSlot(slotDevice) {
    var d = replacing
    replacing = null
    if (!canMutate || !d || !slotDevice) return
    mutate({action: "connect", address: d.address, replace: slotDevice.address},
           {action: "connect", address: d.address, name: nameOf(d), replace: slotDevice.address, replaceName: nameOf(slotDevice)})
  }
  function cancelReplace() { replacing = null }
  function disconnectDevice(d) {
    if (!canMutate || !d) return
    notice = null
    replacing = null
    mutate({action: "disconnect", address: d.address}, {action: "disconnect", address: d.address, name: nameOf(d)})
  }
  function successText(p) {
    if (p.action === "disconnect") return p.name + " disconnected"
    return p.replace ? p.name + " connected in place of " + p.replaceName : p.name + " connected"
  }
  function mutate(body, p) {
    pending = p
    request("POST", "/api/override", body, function(err, json) {
      if (err || !json || json.ok === false) {
        m.pending = null
        var why = err ? err.message : String((json && (json.error || json.message)) || "The change failed.")
        m.notice = {tone: "error", text: why + (err && err.timeout ? " It may still have happened; refresh before retrying." : "")}
        return
      }
      if (!json.verified) {
        if (json.state) m.applySnapshot(json.state)
        m.pending = null
        m.notice = {tone: "error", text: json.message || "Change not verified. Refresh before retrying."}
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
        m.pending = null
        m.notice = {tone: "ok", text: m.successText(p)}
        return
      }
      // Older peer without `state`: one read-back, pending stays until it lands.
      m.request("GET", "/api/overview", null, function(err2, json2) {
        if (!err2) m.applySnapshot(json2)
        m.pending = null
        m.notice = err2 ? {tone: "error", text: "Change confirmed, but the new state could not be read. Refresh."}
                        : {tone: "ok", text: m.successText(p)}
      })
    })
  }

  // Noise: at most one write in flight plus one queued latest value, writes
  // start at least 250 ms apart, intermediate values are dropped.
  property Timer ancGap: Timer { onTriggered: m.pumpNoise() }
  function setNoise(level, enabled) {
    if (!canNoise) return
    notice = null
    ancQueued = {level: Math.max(0, Math.min(10, Math.round(level))), enabled: !!enabled}
    pumpNoise()
  }
  function pumpNoise() {
    if (ancInFlight || !ancQueued) return
    var wait = 250 - (Date.now() - ancLastStart)
    if (wait > 0) { ancGap.interval = wait; ancGap.restart(); return }
    var q = ancQueued
    var c = snapshot.noise
    ancQueued = null
    if (c && c.level === q.level && c.enabled === q.enabled) return
    ancInFlight = q
    ancLastStart = Date.now()
    request("POST", "/api/override", {action: "noise", level: q.level, enabled: q.enabled}, function(err, json) {
      var ok = !err && json && json.ok !== false && json.verified
      if (ok) {
        if (json.state) m.mergeNoiseState(json.state)
        else m.mergeNoiseState({noise: {level: q.level, enabled: q.enabled}})
      }
      m.ancInFlight = null
      if (!ok) m.ancQueued = null
      if (!m.ancQueued || !ok) {
        m.notice = ok ? {tone: "ok", text: "Noise cancellation updated"}
                      : {tone: "error", text: err ? err.message : String((json && (json.error || json.message)) || "Noise change not verified.")}
      }
      m.pumpNoise()
    })
  }

  // ------------------------------------------------------------- settings
  function saveRoles(roles, done) {
    if (savingRoles || pending || ancBusy) return
    savingRoles = true
    notice = null
    request("POST", "/api/roles", {roles: roles}, function(err) {
      m.savingRoles = false
      if (err) { m.notice = {tone: "error", text: err.message}; return }
      m.notice = {tone: "ok", text: "Controller settings saved"}
      if (done) done()
      m.refresh()
    })
  }
}
