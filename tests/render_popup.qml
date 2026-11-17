import QtQuick
import "../linux"

// Offscreen captures of the Omarchy popup's pending and queued looks (no shell, synthetic devices):
//   QT_QPA_PLATFORM=offscreen qml6 tests/render_popup.qml -- <output folder>
// Writes popup-<light|dark>-<scene>.png and exits. Scenes: inflight (a Disconnect in flight, a Disconnect queued, a noise
// value held), connect (a Connect queued into the slot the Disconnect frees), here (a Use here queued behind a noise
// write), refresh and save (Refresh and the settings Save pressed during a Disconnect: kept, drawn queued).
Item {
  id: root
  width: 360
  height: 900
  property string out: {
    var a = Qt.application.arguments, i = a.indexOf("--")
    return i >= 0 && i + 1 < a.length ? a[i + 1] : "."
  }
  readonly property var devs: ({pc: "AA:AA:AA:AA:AA:AA", phone: "CC:CC:CC:CC:CC:CC", mac: "BB:BB:BB:BB:BB:BB", tv: "DD:DD:DD:DD:DD:DD"})
  readonly property var names: ({pc: "Desktop PC", phone: "Android phone", mac: "MacBook Pro", tv: "Living room TV"})
  function overview(connected) {
    return {here: "pc", reachable: true, cached: false, observed: Date.now() / 1000, battery: 80, noise: {level: 7, enabled: true},
            roles: {pc: devs.pc, phone: devs.phone, mac: devs.mac},
            controllers: [{controller: "pc", reachable: true}, {controller: "phone", reachable: true}, {controller: "mac", reachable: false, checking: true}],
            devices: ["pc", "phone", "mac", "tv"].map(function(k) { return {address: devs[k], name: names[k], connected: connected.indexOf(devs[k]) >= 0} })}
  }

  BoseTheme { id: dark; background: "#1a1b26"; foreground: "#c0caf5" }
  BoseTheme { id: light; background: "#f5f5f0"; foreground: "#2a2b33" }
  property BoseTheme theme: dark
  property var held: []
  BoseModel {
    id: model
    transport: function(method, path, body, done) {
      if (method === "POST") { root.held.push(done); return }
      done(null, root.overview([root.devs.pc, root.devs.phone]))
    }
  }
  Rectangle {
    id: card
    width: 360
    height: view.implicitHeight + 32
    color: root.theme.ground
    BoseView {
      id: view
      x: 16; y: 16
      width: parent.width - 32
      theme: root.theme
      model: model
      animate: false
    }
  }

  function grab(name, next) {
    card.grabToImage(function(r) { r.saveToFile(root.out + "/popup-" + (root.theme === dark ? "dark" : "light") + "-" + name + ".png"); next() })
  }
  function fresh(connected) {
    held = []
    model.transport = function(method, path, body, done) {
      if (method === "POST") { root.held.push(done); return }
      done(null, root.overview(connected))
    }
    model.ui = {kind: "idle"}; model.queue = {kind: "idle"}; model.anc = {kind: "idle"}; model.notice = null; model.slotOrder = [null, null]
    model.refreshWanted = false; model.rolesWanted = null; view.showSettings = false
    model.refresh()
  }
  property var steps: []
  function run(list) { steps = list; nextStep() }
  function nextStep() { if (!steps.length) { Qt.exit(0); return } var f = steps.shift(); f() }
  function after(f) { return function() { f(); Qt.callLater(function() { tick.start() }) } }
  Timer { id: tick; interval: 120; onTriggered: root.nextStep() }

  Component.onCompleted: {
    var scenes = []
    ;[dark, light].forEach(function(t) {
      scenes.push(after(function() { root.theme = t; fresh([devs.pc, devs.phone]); model.disconnectDevice(model.deviceFor(devs.phone)); model.disconnectDevice(model.deviceFor(devs.pc)); model.setNoise(4, true) }))
      scenes.push(function() { grab("inflight", nextStep) })
      scenes.push(after(function() { model.connectDevice(model.deviceFor(devs.mac)) }))
      scenes.push(function() { grab("connect", nextStep) })
      scenes.push(after(function() { fresh([devs.phone]); model.setNoise(3, true); model.switchHere() }))
      scenes.push(function() { grab("here", nextStep) })
      // Refresh and settings Save pressed during a change: drawn queued, sent when the change ends.
      scenes.push(after(function() { fresh([devs.pc, devs.phone]); model.disconnectDevice(model.deviceFor(devs.phone)); model.refresh() }))
      scenes.push(function() { grab("refresh", nextStep) })
      scenes.push(after(function() { view.showSettings = true; model.saveRoles({pc: devs.pc, phone: devs.phone, mac: devs.mac}, null) }))
      scenes.push(function() { grab("save", nextStep) })
    })
    run(scenes)
  }
}
