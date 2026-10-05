import QtQuick
import QtQuick.Controls as Controls
import qs.Ui as Ui
import qs.Commons

Ui.Panel {
  id: root
  moduleName: "local.bose"
  ipcTarget: "local.bose"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var snapshot: ({reachable:false,devices:[],roles:{}})
  property bool busy: false
  property string notice: ""
  property var replacementTarget: null
  property var request: null
  property bool showSettings: false
  property var editedRoles: ({})
  readonly property var connected: (snapshot.devices || []).filter(d => d.connected)
  readonly property var devices: (snapshot.devices || []).slice().sort((a,b) => Number(b.connected)-Number(a.connected))

  function label(d) {
    const names = {pc:"PC",mac:"Mac",phone:"Phone"}
    for (const role in snapshot.roles) if (snapshot.roles[role] === d.address) return names[role] || d.name
    return d.name || d.address
  }
  function query(path, data, done) {
    if (busy) return
    busy = true
    const xhr = new XMLHttpRequest()
    request = xhr
    xhr.onreadystatechange = function() {
      if (xhr.readyState !== XMLHttpRequest.DONE || root.request !== xhr) return
      root.request = null; deadline.stop(); root.busy = false
      try {
        const json = JSON.parse(xhr.responseText)
        if (xhr.status !== 200 || json.error) throw new Error(json.error || "Controller unavailable")
        done(json)
      } catch(e) { root.notice = String(e.message || e); if (!data) root.snapshot = {reachable:false,devices:[],roles:{}} }
    }
    xhr.open(data ? "POST" : "GET", "http://127.0.0.1:8847" + path)
    if(data) xhr.setRequestHeader("Content-Type", "application/json")
    deadline.start()
    xhr.send(data ? JSON.stringify(data) : "")
  }
  Component.onCompleted: query("/api/cached", null, json => { root.snapshot = json; if(root.opened) root.refresh() })
  function refresh() {
    replacementTarget = null
    query("/api/overview", null, json => { root.snapshot = json })
  }
  function changeNoise(level,enabled) {
    notice=""
    query("/api/override",{action:"noise",level:level,enabled:enabled},json => {
      root.notice=json.ok && json.verified ? "Noise cancellation updated" : "Change not verified. Refresh before retrying."
      root.refresh()
    })
  }
  function change(action, address, replace) {
    notice = ""
    replacementTarget = null
    const data = {action:action,address:address}
    if(replace) data.replace = replace
    query("/api/override", data, json => {
      root.notice = json.ok && json.verified ? "Connection updated" : "Change not verified. Refresh before retrying."
      root.refresh()
    })
  }
  function saveRoles() {
    query("/api/roles", {roles:editedRoles}, json => { root.notice = "Controller settings saved"; root.showSettings = false; root.refresh() })
  }
  function setRole(id,address) { const roles=Object.assign({},editedRoles); if(address) roles[id]=address; else delete roles[id]; editedRoles=roles }
  function choose(d) {
    if (d.connected) change("disconnect", d.address, "")
    else if (connected.length >= 2) replacementTarget = d
    else change("connect", d.address, "")
  }
  onOpenedChanged: if(opened) { notice = ""; query("/api/cached", null, json => { root.snapshot = json; root.refresh() }) }
  Timer {
    id: deadline
    interval: 120000
    onTriggered: {
      const xhr = root.request; root.request = null
      if (xhr) xhr.abort()
      root.busy = false; root.notice = "Timed out. Refresh before retrying."
    }
  }
  Ui.WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰋋"
    tooltipText: "Bose 700 connections"
    onPressed: root.toggle()
  }
  Ui.PopupCard {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    contentWidth: fittedContentWidth(Style.space(320))
    contentHeight: fittedContentHeight(column.implicitHeight)
    Flickable {
      anchors.fill: parent
      contentHeight: column.implicitHeight
      clip: true
      Controls.ScrollBar.vertical: Controls.ScrollBar {}
    Column {
      id: column
      width: parent.width
      spacing: Style.space(6)
      Text { text: "Bose 700"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
      Text {
        width: parent.width
        text: root.busy ? "Checking…" : root.replacementTarget ? "Connect " + root.label(root.replacementTarget) + " — disconnect:" : root.snapshot.cached ? "Last known device list" : root.snapshot.reachable ? root.connected.length + " / 2 connected" : "Headset unavailable"
        color: Color.muted; font.pixelSize: Style.font.body; wrapMode: Text.Wrap; textFormat: Text.PlainText
      }
      Text {
        visible: !!root.snapshot.observed
        text: "Updated " + new Date((root.snapshot.observed || 0)*1000).toLocaleTimeString(Qt.locale(), "hh:mm")
        color: Color.muted; font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        visible: !root.busy && !root.snapshot.reachable
        text: "No controller can reach the headset. Turn it on and connect it through Bluetooth settings. The saved list is not current."
        color: Color.muted; wrapMode: Text.Wrap; font.pixelSize: Style.font.body
      }
      Text {
        visible: root.snapshot.battery !== undefined && root.snapshot.battery !== null
        text: "Battery: " + root.snapshot.battery + "%" + (root.snapshot.cached ? " (last known)" : "")
        color: Color.muted; font.pixelSize: Style.font.body
      }
      Repeater {
        model: root.snapshot.controllers || []
        delegate: Text {
          required property var modelData
          width: column.width
          text: modelData.node + ": " + (modelData.reachable ? "Available" : modelData.checking ? "Checking…" : "Unavailable")
          color: Color.muted; font.pixelSize: Style.font.body
        }
      }
      Column {
        width: parent.width; spacing: Style.space(4)
        visible: !!root.snapshot.noise
        Text { text: "Noise cancellation"; color: Color.foreground; font.bold: true; font.pixelSize: Style.font.body }
        Text { text: root.snapshot.noise && root.snapshot.noise.enabled ? "Level " + root.snapshot.noise.level + " / 10" : "Off"; color: Color.muted; font.pixelSize: Style.font.body }
        Controls.Slider {
          id: noiseSlider; width: parent.width; from:0; to:10; stepSize:1
          value: root.snapshot.noise ? root.snapshot.noise.level : 10
          enabled: !root.busy && root.snapshot.reachable && !root.snapshot.cached
          onMoved: noiseChoice.text = "Apply level " + Math.round(value)
        }
        Text { text: "0 = aware · 10 = maximum"; color: Color.muted; font.pixelSize: Style.font.body }
        Ui.Button { id: noiseChoice; width: parent.width; text: "Apply level " + Math.round(noiseSlider.value); enabled: noiseSlider.enabled; focusable:true; onClicked: root.changeNoise(Math.round(noiseSlider.value),true) }
        Ui.Button { width: parent.width; text: "Turn noise cancellation off"; enabled: noiseSlider.enabled; focusable:true; onClicked: root.changeNoise(Math.round(noiseSlider.value),false) }
      }
      Repeater {
        model: root.replacementTarget ? root.connected : root.devices
        delegate: Ui.Button {
          required property var modelData
          width: column.width
          text: (root.replacementTarget ? "Disconnect " : modelData.connected ? "✓  " : "    ") + root.label(modelData) + (!root.replacementTarget && !root.snapshot.cached ? modelData.connected ? " — Disconnect" : " — Connect" : "")
          leftAlign: true
          focusable: true
          enabled: !root.busy && root.snapshot.reachable && !root.snapshot.cached
          tooltipText: root.replacementTarget || modelData.connected ? "Disconnect" : "Connect"
          onClicked: root.replacementTarget ? root.change("connect",root.replacementTarget.address,modelData.address) : root.choose(modelData)
        }
      }
      Ui.Button { width: parent.width; visible: !!root.replacementTarget; text: "Cancel"; focusable: true; onClicked: root.replacementTarget = null }
      Text { width: parent.width; visible: root.notice !== ""; text: root.notice; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.foreground; font.pixelSize: Style.font.body }
      Ui.Button {
        width: parent.width; text: root.showSettings ? "Close settings" : "Controller settings"; leftAlign:true; focusable:true; enabled: !root.busy
        onClicked: { root.editedRoles=Object.assign({},root.snapshot.roles || {}); root.showSettings = !root.showSettings }
      }
      Column {
        visible: root.showSettings; width: parent.width; spacing: Style.space(4)
        Repeater {
          model: ["pc","mac","phone"]
          delegate: Column {
            required property string modelData
            width: column.width
            Text { text: parent.modelData.toUpperCase(); color: Color.foreground; font.pixelSize: Style.font.body }
            Controls.ComboBox {
              width: parent.width
              model: [{name:"Not identified",address:""}].concat(root.devices)
              textRole: "name"; valueRole: "address"
              currentIndex: { for(let i=0;i<model.length;i++) if(model[i].address === (root.editedRoles[parent.modelData] || "")) return i; return 0 }
              onActivated: root.setRole(parent.modelData,currentValue)
            }
          }
        }
        Ui.Button { width: parent.width; text: "Save controller settings"; enabled: !root.busy; focusable:true; onClicked: root.saveRoles() }
      }
      Rectangle { width: parent.width; height: 1; color: Color.muted; opacity: 0.4 }
      Ui.Button { width: parent.width; text: "Refresh"; leftAlign: true; focusable: true; enabled: !root.busy; onClicked: { root.notice = ""; root.refresh() } }
      Ui.Button { width: parent.width; text: "Open dashboard…"; leftAlign: true; focusable: true; onClicked: { root.close(); root.bar.run("xdg-open http://127.0.0.1:8847") } }
    }
    }
  }
}
