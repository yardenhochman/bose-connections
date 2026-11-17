import QtQuick
import "../linux"

// Offscreen contract check for the Omarchy popup model (run by tests/test_omarchy_contract.py):
//   QML_XHR_ALLOW_FILE_READ=1 QT_QPA_PLATFORM=offscreen qml6 tests/bose_model.qml
// Every scenario of tests/switch-contract.json goes through BoseModel.switchHere with a scripted
// transport that answers like the XHR path (error replies arrive as err + json). Prints PASS/FAIL lines.
Item {
  id: harness
  property var contract: null
  property int failures: 0
  property int checks: 0
  readonly property var devs: ({pc: "AA:AA:AA:AA:AA:AA", phone: "CC:CC:CC:CC:CC:CC", mac: "BB:BB:BB:BB:BB:BB", tv: "DD:DD:DD:DD:DD:DD"})
  readonly property var names: ({pc: "Desktop PC", phone: "Android phone", mac: "MacBook Pro", tv: "Living room TV"})
  readonly property var roleOf: ({here: "pc", other1: "phone", other2: "mac"})

  function check(ok, what) { checks++; if (!ok) { failures++; console.log("FAIL " + what) } }
  function addr(role) { return devs[roleOf[role]] }
  function label(role) { return contract.labels[roleOf[role]] }
  function textOf(key) { var v = contract; key.split(".").forEach(function(k) { v = v[k] }); return v }
  function overview(connected) {
    return {here: "pc", reachable: true, cached: false, observed: 1, battery: 80, noise: {level: 7, enabled: true},
            roles: {pc: devs.pc, phone: devs.phone, mac: devs.mac}, controllers: [{controller: "pc", reachable: true}],
            devices: ["pc", "phone", "mac", "tv"].map(function(k) { return {address: devs[k], name: names[k], connected: connected.indexOf(devs[k]) >= 0, current: false} })}
  }
  function reply(sc, body) {
    var e = sc.expect
    if (e.outcome === "busy" || (sc.replace && !body.replace))
      return {ok: false, busy: true, error_key: "busy", error: contract.messages.busy, slots: sc.start.map(function(r) { return {address: addr(r), label: label(r)} })}
    if (e.outcome === "ok") return {ok: true, verified: true, message: contract.messages.ok, state: overview((e.connected || []).map(addr))}
    return {ok: false, error_key: e.error_key, error: contract.messages.errors[e.error_key], detail: "scripted"}
  }

  Component { id: modelComponent; BoseModel {} }

  function runScenario(sc) {
    var posts = [], waiting = null
    const model = modelComponent.createObject(harness, {transport: function(method, path, body, done) {
      if (path === "/api/switch") { posts.push(body); waiting = done; return }
      done(null, overview(sc.start.map(addr)))
    }}) as BoseModel
    // Like the XHR path: a reply carrying `error` arrives as (err, json).
    function deliver(json) { var d = waiting; waiting = null; d(json.error ? {message: json.error} : null, json) }
    model.refresh()
    var name = sc.name
    check(model.canUseHere, name + ": Use here available")
    model.switchHere()
    check(posts.length === 1 && model.notice && model.notice.tone === "pending" && model.notice.text === contract.messages.pending, name + ": pending text before the reply")
    check(!model.canUseHere && model.pending && model.pending.here, name + ": one request in flight")
    var first = posts[0]
    check(first.source === "omarchy" && /^[a-z0-9]{1,32}$/.test(first.request_id) && !("replace" in first) && Object.keys(first).length === 2, name + ": payload " + JSON.stringify(first))
    deliver(reply(sc, first))
    if (sc.expect.outcome === "busy" || sc.replace) {
      let offered = (model.busySlots || []).map(function(s) { return model.replaceText(s) })
      let want = (sc.expect.offered || sc.start.map(function(r) { return "Replace {" + r + "}" })).map(function(o) { return o.replace(/\{(other\d)\}/, function(_, r) { return label(r) }) })
      check(JSON.stringify(offered) === JSON.stringify(want), name + ": offered " + JSON.stringify(offered) + " want " + JSON.stringify(want))
      check(JSON.stringify(want) === JSON.stringify(sc.start.map(function(r) { return contract.messages.replace.replace("{label}", label(r)) })), name + ": offers are messages.replace per slot")
      check(model.pending === null && model.notice === null, name + ": busy is not an error")
      if (!sc.replace) { model.cancelReplace(); check(model.busySlots === null, name + ": cancel clears the offer"); model.destroy(); return }
      model.switchHere(addr(sc.replace))
      check(model.notice && model.notice.tone === "pending" && model.notice.text === contract.messages.replacing.replace("{label}", label(sc.replace)), name + ": replacing text before the reply")
      check(posts.length === 2 && posts[1].replace === addr(sc.replace) && posts[1].request_id !== first.request_id, name + ": replace payload " + JSON.stringify(posts[1]))
      deliver(reply(sc, posts[1]))
    }
    if (sc.expect.outcome === "ok") {
      check(model.notice.tone === "ok" && model.notice.text === textOf(sc.expect.text), name + ": ok text " + JSON.stringify(model.notice))
      let held = model.devices.filter(function(d) { return d.connected }).map(function(d) { return d.address }).sort()
      check(JSON.stringify(held) === JSON.stringify(sc.expect.connected.map(addr).sort()), name + ": connected " + JSON.stringify(held))
    } else if (sc.expect.outcome === "error") {
      check(model.notice.tone === "error" && model.notice.text === textOf(sc.expect.text) + contract.messages.retry_hint, name + ": error text " + JSON.stringify(model.notice))
    }
    check(model.pending === null && model.canUseHere, name + ": tappable again")
    model.destroy()
  }

  // The shared transition tables (tests/machine-tables.json): the popup's machines must equal the dashboard's.
  function resolve(t, o) {
    if (typeof o === "string" && t.values && o in t.values) return t.values[o]
    if (Array.isArray(o)) return o.map(function(x) { return resolve(t, x) })
    if (o && typeof o === "object") { var r = {}; for (var k in o) r[k] = resolve(t, o[k]); return r }
    return o
  }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }
  function canon(o) { return JSON.parse(JSON.stringify(o, function(k, v) { return v && typeof v === "object" && !Array.isArray(v) ? Object.keys(v).sort().reduce(function(r, x) { r[x] = v[x]; return r }, {}) : v })) }
  function runTables() {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", Qt.resolvedUrl("machine-tables.json"), false)
    xhr.send()
    var tables = JSON.parse(xhr.responseText)
    const mm = modelComponent.createObject(harness) as BoseModel
    var fns = {interact: mm.interactNext, noiser: mm.noiseNext, intents: mm.intentNext}
    for (var name in fns) {
      var t = tables[name]
      t.rows.forEach(function(r) {
        var got = fns[name](resolve(t, t.states[r[0]]), resolve(t, t.events[r[1]]))
        check(same(canon(got), canon(resolve(t, t.states[r[2]]))), "table " + name + " " + r[0] + " --" + r[1] + "-> " + JSON.stringify(got))
      })
    }
    tables.schedule.rows.forEach(function(r) {
      var got = mm.schedule({change: r[0], noise: {kind: r[1]}, intent: {kind: r[2]}, live: r[3]})
      check(got === r[4], "table schedule " + JSON.stringify(r) + " got " + got)
    })
    mm.destroy()
  }

  // Instant input (docs/state-machines.md 5-6): queue, latest wins, cancel, noise held behind a switch, failure revert,
  // stale read, one request at a time toward the controller.
  function runInstant() {
    var held = [], open = 0, maxOpen = 0, cur = overview([devs.pc, devs.phone])
    function apply(b) {
      var on = cur.devices.filter(function(d) { return d.connected }).map(function(d) { return d.address })
      if (b.action === "disconnect") on = on.filter(function(a) { return a !== b.address })
      else if (b.action === "connect") on = on.filter(function(a) { return a !== b.replace }).concat([b.address])
      var noise = b.action === "noise" ? {level: b.level, enabled: b.enabled} : cur.noise
      cur = overview(on); cur.noise = noise
      return {ok: true, verified: true, state: cur}
    }
    const im = modelComponent.createObject(harness, {transport: function(method, path, body, done) {
      if (method === "POST") { open++; maxOpen = Math.max(maxOpen, open); held.push({path: path, body: body, done: function(err, json) { open--; done(err, json) }}); return }
      done(null, cur)
    }}) as BoseModel
    // The 250 ms gap between noise writes is real time; the harness is synchronous, so it starts each answer past it.
    function answer(fn) { var h = held.shift(); im.ancLastStart = 0; h.done(null, fn ? fn(h.body) : apply(h.body)) }
    function slotStates() { return im.slots.map(function(s) { return (s.device ? im.nameOf(s.device) : "-") + ":" + s.state + (s.queued ? ":queued" : "") }).join(",") }
    im.refresh()
    var phone = im.deviceFor(devs.phone), pc = im.deviceFor(devs.pc), mac = im.deviceFor(devs.mac)
    // Latest wins.
    im.disconnectDevice(phone)
    check(held.length === 1 && im.pending && im.pending.address === devs.phone, "instant: disconnect phone in flight")
    check(im.canMutate && im.canNoise, "instant: controls stay enabled during a change")
    im.disconnectDevice(pc)
    check(held.length === 1 && im.queuedIntent && im.queuedIntent.address === devs.pc, "instant: a second tap is queued, not sent")
    check(slotStates() === "Desktop PC:disconnecting:queued,Android phone:disconnecting", "instant: queued drawn apart from in flight: " + slotStates())
    im.setNoise(4, true)
    check(im.anc.kind === "held" && im.noiseShown.level === 4 && held.length === 1, "instant: noise during a change is held, shown, not sent")
    im.connectDevice(mac)
    check(im.queuedIntent && im.queuedIntent.action === "connect" && im.queuedIntent.address === devs.mac, "instant: latest wins (connect replaces the queued disconnect)")
    check(slotStates() === "Desktop PC:connected,MacBook Pro:connecting:queued", "instant: the queued connect takes the slot the disconnect frees: " + slotStates())
    check(im.savedDevices.every(function(d) { return d.address !== devs.mac }), "instant: a queued connect leaves the saved list")
    answer()
    check(held.length === 1 && held[0].body.action === "connect" && held[0].body.address === devs.mac && !im.queuedIntent, "instant: the queued intent goes when the change ends")
    check(im.anc.kind === "held", "instant: noise still held behind the released connect")
    answer()
    check(held.length === 1 && held[0].body.action === "noise" && held[0].body.level === 4, "instant: then the held noise value is sent")
    answer()
    check(im.anc.kind === "idle" && im.snapshot.noise.level === 4 && maxOpen === 1, "instant: settled, one request at a time (max open " + maxOpen + ")")
    // Cancel: the same tap again.
    im.disconnectDevice(mac)
    im.disconnectDevice(pc); im.disconnectDevice(pc)
    check(!im.queuedIntent && slotStates().indexOf("queued") < 0, "instant: the same tap again cancels the queued intent")
    im.disconnectDevice(pc); im.cancelQueued()
    check(!im.queuedIntent, "instant: cancelQueued")
    answer()
    check(held.length === 0, "instant: nothing sent for a cancelled intent")
    // A queued intent that fails reverts and says so.
    im.connectDevice(phone)
    im.disconnectDevice(pc)
    answer()
    answer(function() { return {ok: false, error_key: "keep_one", error: contract.messages.errors.keep_one} })
    check(im.notice && im.notice.tone === "error" && im.notice.text === contract.messages.errors.keep_one && slotStates() === "Desktop PC:connected,Android phone:connected", "instant: failed queued disconnect reverts: " + slotStates() + " " + JSON.stringify(im.notice))
    // Noise queued behind a switch (setNoise while !canNoise used to drop it).
    im.switchHere()
    check(im.pending && im.pending.here && !im.canUseHere, "instant: Use here in flight")
    im.setNoise(2, false)
    check(im.anc.kind === "held" && held.length === 1 && held[0].path === "/api/switch", "instant: noise during a switch is held")
    im.setNoise(3, true)
    check(im.anc.queued.level === 3 && im.anc.queued.enabled, "instant: newest held value wins")
    answer(function() { return {ok: true, verified: true, message: contract.messages.ok, state: cur} })
    check(held.length === 1 && held[0].body.action === "noise" && held[0].body.level === 3, "instant: sent when the switch ends")
    answer()
    // Held noise whose change ends with the headset out of reach: dropped, and the notice says so.
    im.disconnectDevice(phone)
    im.setNoise(1, true)
    var off = overview([devs.pc]); off.reachable = false; off.cached = true
    answer(function() { return {ok: true, verified: false, state: off} })
    check(im.anc.kind === "idle" && im.notice && im.notice.text === im.droppedNoiseText && held.length === 0, "instant: held noise dropped when the headset is out of reach: " + JSON.stringify(im.notice))
    // Not live and nothing running: setNoise says so instead of dropping silently.
    im.setNoise(5, true)
    check(im.notice && im.notice.text === im.droppedNoiseText && held.length === 0, "instant: setNoise while unreachable says so")
    // Use here during a noise write: queued, cancel by tapping again, then sent after the write.
    cur = overview([devs.phone]); im.refresh()
    im.setNoise(8, true)
    check(held.length === 1 && held[0].body.action === "noise", "instant: noise write in flight")
    im.switchHere()
    check(im.queuedHere && held.length === 1 && im.canUseHere, "instant: Use here during a noise write is queued")
    check(slotStates() === "Android phone:connected,Desktop PC:connecting:queued", "instant: queued Use here drawn in the free slot: " + slotStates())
    im.switchHere()
    check(!im.queuedHere, "instant: Use here again cancels it")
    im.switchHere()
    answer()
    check(held.length === 1 && held[0].path === "/api/switch", "instant: queued Use here sent after the write")
    answer(function() { return {ok: true, verified: true, message: contract.messages.ok, state: overview([devs.phone, devs.pc])} })
    // Stale read after an optimistic change: an overview sent before a queued intent lands after it; the intent stays.
    var late = null
    im.transport = function(method, path, body, done) {
      if (method === "POST") { open++; held.push({path: path, body: body, done: function(err, json) { open--; done(err, json) }}); return }
      if (path === "/api/overview" && !late) { late = done; return }
      done(null, cur)
    }
    cur = overview([devs.pc, devs.phone]); im.refresh()
    im.disconnectDevice(im.deviceFor(devs.phone))
    im.disconnectDevice(im.deviceFor(devs.pc))
    late(null, overview([devs.pc, devs.phone]))
    check(im.queuedIntent && im.queuedIntent.address === devs.pc && slotStates().indexOf("Desktop PC:disconnecting:queued") >= 0, "instant: a stale read keeps the queued intent drawn: " + slotStates())
    answer(); answer()
    check(slotStates() === "-:empty,-:empty" && maxOpen === 1, "instant: both disconnects ran in order: " + slotStates())
    var gets = []
    im.transport = function(method, path, body, done) {
      if (method === "POST") { open++; held.push({path: path, body: body, done: function(err, json) { open--; done(err, json) }}); return }
      gets.push(path); done(null, cur)
    }
    // One interaction value (machine 2): a Use here offer and a slot choice can no longer be open at once.
    cur = overview([devs.phone, devs.mac]); im.refresh()
    im.switchHere()
    answer(function() { return {ok: false, busy: true, error_key: "busy", error: contract.messages.busy, slots: [{address: devs.phone, label: "Phone"}, {address: devs.mac, label: "Mac"}]} })
    check(im.ui.kind === "offer" && im.busySlots.length === 2, "interaction: busy Use here offers Replace per slot")
    im.connectDevice(im.deviceFor(devs.tv))
    check(im.ui.kind === "choosing" && im.replacing && im.replacing.address === devs.tv && im.busySlots === null, "interaction: picking a device closes the Use here offer: " + JSON.stringify(im.ui))
    im.cancelReplace()
    check(im.ui.kind === "idle" && !im.replacing && !im.busySlots && !im.pending, "interaction: cancel closes the slot choice")
    // Connect with both slots full while a change runs: queued, the slot is asked for when it is released.
    im.switchHere()
    im.connectDevice(im.deviceFor(devs.tv))
    check(im.queuedIntent && im.queuedIntent.address === devs.tv && im.ui.kind === "mutating", "interaction: a connect into full slots during a change is queued, not dropped: " + JSON.stringify(im.queue))
    answer(function() { return {ok: true, verified: true, message: contract.messages.ok, state: cur} })
    check(im.ui.kind === "choosing" && im.replacing && im.replacing.address === devs.tv && held.length === 0, "interaction: released into full slots it asks which to replace: " + JSON.stringify(im.ui))
    im.cancelReplace()
    // Refresh during work (formerly disabled): shown at once, read once the work ends, so it cannot undo the change.
    im.disconnectDevice(im.deviceFor(devs.mac))
    gets = []
    im.refresh(); im.refresh()
    check(im.refreshWanted && gets.length === 0 && im.refreshing, "refresh during a change: wanted and shown, not sent: " + JSON.stringify(gets))
    answer()
    check(gets.length === 1 && gets[0] === "/api/overview" && !im.refreshWanted, "refresh during a change: one read after it ends: " + JSON.stringify(gets))
    // Save in settings during work (formerly disabled): kept and sent when the change ends, never alongside it.
    im.disconnectDevice(im.deviceFor(devs.phone))
    var saved = false
    im.saveRoles({pc: devs.pc, phone: devs.phone, mac: devs.mac}, function() { saved = true })
    check(held.length === 1 && held[0].path === "/api/override" && im.rolesWanted && im.saving && !im.savingRoles, "save during a change: shown as saving, not sent yet")
    answer()
    check(held.length === 1 && held[0].path === "/api/roles" && !im.rolesWanted, "save during a change: sent once the change ends")
    held.shift().done(null, {ok: true})
    check(saved && im.notice && im.notice.text === "Controller settings saved" && maxOpen === 1, "save during a change: saved, one request at a time (max open " + maxOpen + ")")
    im.destroy()
  }

  Component.onCompleted: Qt.callLater(function() {
    try { run() } catch (e) { console.log("FAIL omarchy contract: " + e + "\n" + e.stack); Qt.exit(1) }  // an exception must not hang the run
  })
  function run() {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", Qt.resolvedUrl("switch-contract.json"), false)
    xhr.send()
    contract = JSON.parse(xhr.responseText)
    const probe = modelComponent.createObject(harness) as BoseModel
    check(JSON.stringify(probe.messages) === JSON.stringify(contract.messages), "BoseModel.messages equals the contract's messages")
    // Row Connect/Replace failures use the contract texts as well.
    probe.transport = function(method, path, body, done) {
      if (path === "/api/override") done({message: "x"}, {ok: false, error_key: "keep_one", error: contract.messages.errors.keep_one})
      else done(null, overview([devs.pc, devs.phone]))
    }
    probe.refresh()
    probe.connectDevice(probe.deviceFor(devs.mac))
    probe.replaceSlot(probe.deviceFor(devs.phone))
    check(probe.notice && probe.notice.text === contract.messages.errors.keep_one, "row replace shows the contract text: " + JSON.stringify(probe.notice))
    probe.transport = function(method, path, body, done) { if (path === "/api/override") done({timeout: true, message: "x"}, null); else done(null, overview([devs.pc])) }
    probe.refresh()
    probe.connectDevice(probe.deviceFor(devs.mac))
    check(probe.notice && probe.notice.text === contract.messages.errors.timeout, "row connect timeout shows the contract text")
    probe.destroy()
    // An overview requested before a Use here and answered after it must not undo the switch (state-machines.md 6).
    var held = null, sw = null
    const late = modelComponent.createObject(harness, {transport: function(method, path, body, done) {
      if (path === "/api/switch") sw = done; else if (path === "/api/overview" && late.loaded) held = done; else done(null, overview([devs.phone, devs.mac]))
    }}) as BoseModel
    late.refresh(); late.refresh()
    check(held !== null && late.canUseHere, "late refresh: an overview is in flight and Use here stays available")
    late.switchHere()
    sw(null, {ok: true, verified: true, message: contract.messages.ok, state: overview([devs.phone, devs.pc])})
    held(null, overview([devs.phone, devs.mac]))
    check(late.devices.filter(function(d) { return d.connected }).map(function(d) { return d.address }).sort().join() === [devs.pc, devs.phone].sort().join(),
          "late refresh: the older overview does not bring back the old slots")
    late.destroy()
    contract.scenarios.forEach(runScenario)
    runTables()
    runInstant()
    console.log((failures ? "FAIL" : "PASS") + " omarchy contract: " + contract.scenarios.length + " scenarios, " + checks + " checks, " + failures + " failures")
    Qt.exit(failures ? 1 : 0)
  }
}
