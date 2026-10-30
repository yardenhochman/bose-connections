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

  Component.onCompleted: Qt.callLater(run)
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
    contract.scenarios.forEach(runScenario)
    console.log((failures ? "FAIL" : "PASS") + " omarchy contract: " + contract.scenarios.length + " scenarios, " + checks + " checks, " + failures + " failures")
    Qt.exit(failures ? 1 : 0)
  }
}
