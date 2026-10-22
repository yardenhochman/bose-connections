pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Controls

// Popup content: header, outside-sound ridge band, two slot cups, saved
// devices, noise cancellation, status line, settings. Pure presentation over
// BoseModel; Panel.qml hosts it inside the shell's KeyboardPanel.
FocusScope {
  id: view

  required property BoseTheme theme
  required property BoseModel model
  property real bleed: 0                // card padding, so the band can run edge to edge
  property bool animate: true
  property bool showSettings: false
  property var editedRoles: ({})
  signal closeRequested()
  signal dashboardRequested()

  readonly property var snap: model.snapshot
  readonly property bool cached: !!snap.cached
  readonly property bool unavailable: model.loaded && !model.loading && !snap.reachable && !(snap.devices || []).length
  readonly property var noise: model.noiseShown
  readonly property real liveLevel: slider.pressed ? slider.value : (noise ? noise.level : 5)
  readonly property bool ancOn: noise ? !!noise.enabled : true

  implicitHeight: content.implicitHeight
  Keys.onEscapePressed: function(e) {
    if (view.model.replacing) view.model.cancelReplace()
    else if (view.showSettings) view.showSettings = false
    else view.closeRequested()
    e.accepted = true
  }

  function statusText() {
    if (model.helperDown) return "Helper not running"
    if (!model.loaded) return "Checking…"
    var n = model.connectedCount + " of 2 connected"
    if (cached) return (model.loading ? "Checking… · last known " : "Last known · ") + n
    if (!snap.reachable) return model.loading ? "Checking…" : "Headset unavailable"
    return (model.loading ? "Refreshing · " : "Live · ") + n
  }
  function openSettings() {
    editedRoles = Object.assign({}, snap.roles || {})
    showSettings = true
  }

  Column {
    id: content
    width: parent.width
    spacing: 0

    // ------------------------------------------------------------ header
    Item {
      width: parent.width
      height: Math.max(titleCol.implicitHeight, view.theme.sp(34))
      Column {
        id: titleCol
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: view.theme.sp(1)
        Text {
          text: "Bose 700"
          textFormat: Text.PlainText
          color: view.theme.ink
          font.family: view.theme.family
          font.pixelSize: view.theme.fTitle
          font.weight: Font.Medium
        }
        Row {
          spacing: view.theme.sp(7)
          Rectangle {
            id: liveLed
            width: view.theme.sp(7); height: width; radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            readonly property bool breathing: view.model.loading || !view.model.loaded
            color: breathing ? view.theme.accent
                 : (view.snap.reachable && !view.cached && !view.model.helperDown) ? view.theme.ok : view.theme.ink3
            Rectangle {
              anchors.centerIn: parent
              width: parent.width + view.theme.sp(6); height: width; radius: width / 2
              color: view.theme.alpha(parent.color, 0.2)
            }
            SequentialAnimation on opacity {
              running: liveLed.breathing && view.animate
              loops: Animation.Infinite
              alwaysRunToEnd: true
              NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
              NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
            }
          }
          Text {
            text: view.statusText()
            textFormat: Text.PlainText
            color: view.theme.ink2
            font.family: view.theme.family
            font.pixelSize: view.theme.fSmall
          }
        }
      }
      Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: view.theme.sp(8)
        Row {
          visible: view.snap.battery !== undefined && view.snap.battery !== null
          spacing: view.theme.sp(5)
          anchors.verticalCenter: parent.verticalCenter
          Item {
            width: view.theme.sp(19); height: view.theme.sp(10)
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
              width: parent.width - view.theme.sp(2); height: parent.height
              radius: view.theme.sp(2.5)
              color: "transparent"
              border.width: Math.max(1, view.theme.sp(1.2)); border.color: view.theme.ink
              Rectangle {
                x: view.theme.sp(2); y: view.theme.sp(2)
                height: parent.height - view.theme.sp(4)
                width: Math.max(1, (parent.width - view.theme.sp(4)) * Math.max(0, Math.min(100, view.snap.battery || 0)) / 100)
                radius: 1
                color: (view.snap.battery || 0) <= 15 ? view.theme.error : view.theme.ink
              }
            }
            Rectangle {
              anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
              width: Math.max(1, view.theme.sp(1.5)); height: view.theme.sp(4); radius: 1
              color: view.theme.ink
            }
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: (view.snap.battery || 0) + "%"
            textFormat: Text.PlainText
            color: view.theme.ink
            opacity: view.cached ? 0.7 : 1
            font.family: view.theme.family
            font.pixelSize: view.theme.fBody
            font.weight: Font.Medium
          }
        }
        PillButton {
          theme: view.theme
          width: height
          compact: true
          iconName: "settings"
          variant: view.showSettings ? "accent" : "ghost"
          busy: view.showSettings
          anchors.verticalCenter: parent.verticalCenter
          onClicked: view.showSettings ? view.showSettings = false : view.openSettings()
        }
      }
    }

    // ----------------------------------------------- outside-sound band
    Item {
      visible: !view.showSettings && !view.unavailable
      width: parent.width
      height: view.theme.sp(86)
      RidgeBand {
        x: -view.bleed
        width: parent.width + view.bleed * 2
        height: parent.height
        theme: view.theme
        level: view.liveLevel
        ancEnabled: view.ancOn
        known: !!view.noise
        animate: view.animate
      }
      Text {
        anchors.left: parent.left
        y: view.theme.sp(6)
        text: "Outside sound"
        textFormat: Text.PlainText
        color: view.theme.ink2
        font.family: view.theme.family
        font.pixelSize: view.theme.fCaption
      }
      Text {
        anchors.right: parent.right
        y: view.theme.sp(6)
        textFormat: Text.StyledText
        text: !view.noise ? "Level unknown"
            : !view.ancOn ? "<b>Off</b> · all through"
            : "<b>Level " + Math.round(view.liveLevel) + "</b> / 10"
        color: view.theme.ink
        font.family: view.theme.family
        font.pixelSize: view.theme.fCaption
      }
    }

    // ---------------------------------------------------- replace prompt
    Item {
      visible: !!view.model.replacing && !view.showSettings
      width: parent.width
      height: visible ? view.theme.sp(40) : 0
      Text {
        anchors.left: parent.left
        anchors.right: cancelReplace.left
        anchors.rightMargin: view.theme.sp(8)
        anchors.verticalCenter: parent.verticalCenter
        text: view.model.replacing ? "Both slots are full. Replace which one with " + view.model.nameOf(view.model.replacing) + "?" : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        color: view.theme.ink
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
      }
      PillButton {
        id: cancelReplace
        theme: view.theme
        compact: true
        text: "Cancel"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        onClicked: view.model.cancelReplace()
      }
    }

    // ------------------------------------------------------------- cups
    Item { width: 1; height: view.theme.sp(8); visible: !view.showSettings }
    Item {
      visible: !view.showSettings && !view.unavailable
      width: parent.width
      height: visible ? cupRow.height + view.theme.sp(6) : 0
      Row {
        id: cupRow
        width: parent.width
        spacing: view.theme.sp(10)
        Repeater {
          model: view.model.slots
          delegate: SlotCup {
            required property var modelData
            required property int index
            theme: view.theme
            width: (cupRow.width - cupRow.spacing) / 2
            slotNumber: index + 1
            slotState: !view.model.loaded && modelData.state === "empty" ? "checking" : modelData.state
            name: view.model.nameOf(modelData.device)
            tag: view.model.tagOf(modelData.device)
            here: view.model.isHere(modelData.device)
            cached: view.cached
            replacedName: modelData.replaced || ""
            actionText: modelData.state !== "connected" ? ""
                      : view.model.replacing ? "Replace" : "Disconnect"
            actionEnabled: view.model.canMutate
            onAction: view.model.replacing ? view.model.replaceSlot(modelData.device) : view.model.disconnectDevice(modelData.device)
          }
        }
      }
    }

    // -------------------------------------------------- unavailable note
    Column {
      visible: view.unavailable && !view.showSettings
      width: parent.width
      spacing: view.theme.sp(4)
      topPadding: view.theme.sp(4)
      bottomPadding: view.theme.sp(8)
      Text {
        text: view.model.helperDown ? "Bose helper not running" : "Headset unavailable"
        textFormat: Text.PlainText
        color: view.theme.ink
        font.family: view.theme.family
        font.pixelSize: view.theme.fName
        font.weight: Font.Medium
      }
      Text {
        width: parent.width
        wrapMode: Text.Wrap
        text: view.model.helperDown
          ? "Start the Bose Connections helper on this PC, then refresh."
          : "No controller can reach the headset. Turn it on and connect it through Bluetooth settings, then refresh."
        textFormat: Text.PlainText
        color: view.theme.ink2
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
      }
    }

    // ------------------------------------------------ noise cancellation
    Column {
      visible: !view.showSettings && !!view.snap.noise
      width: parent.width
      topPadding: view.theme.sp(12)
      spacing: 0
      Item {
        width: parent.width
        height: Math.max(ncText.implicitHeight, ancSwitch.height)
        Column {
          id: ncText
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          Text {
            text: "Noise cancellation"
            textFormat: Text.PlainText
            color: view.theme.ink
            font.family: view.theme.family
            font.pixelSize: view.theme.fName
            font.weight: Font.Medium
          }
          Text {
            text: !view.noise ? "Unknown"
                : view.ancOn ? "On · level " + Math.round(view.liveLevel) + " of 10" + (view.model.ancBusy ? " · applying…" : "")
                : "Off · outside sound passes through" + (view.model.ancBusy ? " · applying…" : "")
            textFormat: Text.PlainText
            color: view.model.ancBusy ? view.theme.accentInk : view.theme.ink2
            font.family: view.theme.family
            font.pixelSize: view.theme.fSmall
          }
        }
        // Switch: on = noise cancellation on.
        Item {
          id: ancSwitch
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: view.theme.sp(44); height: view.theme.sp(26)
          enabled: view.model.canNoise
          opacity: enabled ? 1 : 0.4
          activeFocusOnTab: enabled
          readonly property bool on: view.ancOn
          function flip() { view.model.setNoise(slider.value, !on) }
          Keys.onPressed: function(e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return) { flip(); e.accepted = true } }
          Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: ancSwitch.on ? view.theme.fill : "transparent"
            border.width: ancSwitch.activeFocus ? 2 : (ancSwitch.on ? 0 : 1)
            border.color: ancSwitch.activeFocus ? view.theme.accent : view.theme.lineStrong
            Behavior on color { ColorAnimation { duration: 140 } }
          }
          Rectangle {
            width: parent.height - view.theme.sp(8); height: width; radius: width / 2
            y: view.theme.sp(4)
            x: ancSwitch.on ? parent.width - width - view.theme.sp(4) : view.theme.sp(4)
            color: ancSwitch.on ? view.theme.ground : view.theme.ink2
            Behavior on x { enabled: view.animate; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: ancSwitch.flip()
          }
        }
      }
      Controls.Slider {
        id: slider
        width: parent.width
        height: view.theme.sp(34)
        from: 0; to: 10; stepSize: 1; snapMode: Controls.Slider.SnapAlways
        enabled: view.model.canNoise && view.ancOn
        opacity: enabled ? 1 : 0.4
        padding: view.theme.sp(10)
        Binding on value { value: view.noise ? view.noise.level : 5; when: !slider.pressed }
        onPressedChanged: if (!pressed) view.model.setNoise(value, true)
        onMoved: if (!pressed) view.model.setNoise(value, true)
        background: Item {
          x: slider.leftPadding
          y: slider.topPadding + slider.availableHeight / 2 - height / 2
          width: slider.availableWidth
          height: view.theme.sp(4)
          Rectangle { anchors.fill: parent; radius: height / 2; color: view.theme.track }
          Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: height / 2; color: view.theme.fill }
          Repeater {
            model: 11
            delegate: Rectangle {
              required property int index
              x: index * (slider.availableWidth / 10) - width / 2
              y: parent.height + view.theme.sp(5)
              width: 1; height: view.theme.sp(4)
              color: view.theme.ink3
              opacity: 0.6
            }
          }
        }
        handle: Rectangle {
          x: slider.leftPadding + slider.visualPosition * slider.availableWidth - width / 2
          y: slider.topPadding + slider.availableHeight / 2 - height / 2
          width: view.theme.sp(18); height: width; radius: width / 2
          color: view.theme.surface
          border.width: slider.activeFocus ? 3 : 2
          border.color: slider.activeFocus ? view.theme.accent : view.theme.fill
        }
      }
      Item {
        width: parent.width
        height: view.theme.sp(16)
        opacity: slider.enabled ? 1 : 0.4
        Text { anchors.left: parent.left; text: "Aware"; color: view.theme.ink2; font.family: view.theme.family; font.pixelSize: view.theme.fCaption }
        Text { anchors.right: parent.right; text: "Max"; color: view.theme.ink2; font.family: view.theme.family; font.pixelSize: view.theme.fCaption }
      }
    }

    // --------------------------------------------------- saved devices
    Item {
      visible: !view.showSettings && !view.unavailable
      width: parent.width
      height: visible ? view.theme.sp(36) : 0
      Text {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.bottomMargin: view.theme.sp(6)
        text: "Saved devices"
        textFormat: Text.PlainText
        color: view.theme.ink2
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
        font.weight: Font.Medium
      }
      PillButton {
        theme: view.theme
        compact: true
        width: height
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: view.theme.sp(1)
        iconName: "refresh"
        enabled: !view.model.loading && !view.model.pending
        onClicked: { view.model.notice = null; view.model.refresh() }
      }
    }
    Column {
      visible: !view.showSettings && !view.unavailable
      width: parent.width
      Repeater {
        model: view.model.savedDevices
        delegate: DeviceRow {
          required property var modelData
          theme: view.theme
          width: parent ? parent.width : 0
          name: view.model.nameOf(modelData)
          tag: view.model.tagOf(modelData)
          kind: view.model.kindOf(modelData)
          cached: view.cached
          selected: !!view.model.replacing && view.model.replacing.address === modelData.address
          actionEnabled: view.model.canMutate && !view.model.replacing
          onConnectRequested: view.model.connectDevice(modelData)
        }
      }
      Text {
        visible: view.model.savedDevices.length === 0 && view.model.loaded
        width: parent.width
        topPadding: view.theme.sp(10)
        bottomPadding: view.theme.sp(10)
        text: "No other saved devices."
        textFormat: Text.PlainText
        color: view.theme.ink2
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
      }
      Rectangle { width: parent.width; height: 1; color: view.theme.hair }
    }

    // ------------------------------------------------------- settings
    Column {
      visible: view.showSettings
      width: parent.width
      topPadding: view.theme.sp(10)
      spacing: view.theme.sp(8)
      Text {
        text: "Controller settings"
        textFormat: Text.PlainText
        color: view.theme.ink
        font.family: view.theme.family
        font.pixelSize: view.theme.fName
        font.weight: Font.Medium
      }
      Text {
        width: parent.width
        wrapMode: Text.Wrap
        text: "Pick the saved device that is each controller, so the headset keeps a path back to it."
        textFormat: Text.PlainText
        color: view.theme.ink2
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
      }
      Repeater {
        model: ["pc", "mac", "phone"]
        delegate: Item {
          id: roleRow
          required property string modelData
          width: parent ? parent.width : 0
          height: view.theme.sp(34)
          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: view.model.roleNames[roleRow.modelData]
            color: view.theme.ink
            font.family: view.theme.family
            font.pixelSize: view.theme.fBody
          }
          Controls.ComboBox {
            id: combo
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.68
            height: view.theme.sp(30)
            font.family: view.theme.family
            font.pixelSize: view.theme.fSmall
            model: [{name: "Not identified", address: ""}].concat(view.snap.devices || [])
            textRole: "name"
            valueRole: "address"
            currentIndex: {
              var want = view.editedRoles[roleRow.modelData] || ""
              for (var i = 0; i < model.length; i++) if (model[i].address === want) return i
              return 0
            }
            onActivated: {
              var roles = Object.assign({}, view.editedRoles)
              if (currentValue) roles[roleRow.modelData] = currentValue
              else delete roles[roleRow.modelData]
              view.editedRoles = roles
            }
            background: Rectangle {
              radius: height / 2
              color: combo.hovered ? view.theme.hover : "transparent"
              border.width: combo.activeFocus ? 2 : 1
              border.color: combo.activeFocus ? view.theme.accent : view.theme.lineStrong
            }
            contentItem: Text {
              leftPadding: view.theme.sp(12)
              rightPadding: combo.indicator.width
              text: combo.displayText
              font: combo.font
              color: view.theme.ink
              elide: Text.ElideRight
              verticalAlignment: Text.AlignVCenter
            }
            indicator: BoseIcon {
              x: combo.width - width - view.theme.sp(10)
              anchors.verticalCenter: parent.verticalCenter
              name: "chevron"
              size: view.theme.sp(14)
              color: view.theme.ink2
            }
          }
        }
      }
      Row {
        spacing: view.theme.sp(8)
        layoutDirection: Qt.RightToLeft
        width: parent.width
        PillButton {
          theme: view.theme
          compact: true
          text: view.model.savingRoles ? "Saving…" : "Save"
          variant: "accent"
          busy: view.model.savingRoles
          enabled: !view.model.busy
          onClicked: view.model.saveRoles(view.editedRoles, function() { view.showSettings = false })
        }
        PillButton {
          theme: view.theme
          compact: true
          text: "Cancel"
          onClicked: view.showSettings = false
        }
      }
    }

    // --------------------------------------------------------- footer
    Item { width: 1; height: view.theme.sp(12) }
    Rectangle { width: parent.width; height: 1; color: view.theme.hair }
    Item { width: 1; height: view.theme.sp(8) }
    Text {
      visible: text !== "" && !view.showSettings
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.StyledText
      text: view.model.controllerLine()
      color: view.theme.ink2
      font.family: view.theme.family
      font.pixelSize: view.theme.fCaption
      bottomPadding: view.theme.sp(4)
    }
    Row {
      visible: !!view.model.notice && !(view.unavailable && view.model.helperDown)
      width: parent.width
      spacing: view.theme.sp(8)
      bottomPadding: view.theme.sp(4)
      BoseIcon {
        id: noticeIcon
        name: view.model.notice && view.model.notice.tone === "error" ? "alert" : "check"
        size: view.theme.sp(16)
        color: view.model.notice && view.model.notice.tone === "error" ? view.theme.error : view.theme.ok
      }
      Text {
        width: parent.width - noticeIcon.width - parent.spacing
        wrapMode: Text.Wrap
        text: view.model.notice ? view.model.notice.text : ""
        textFormat: Text.PlainText
        color: view.theme.ink
        font.family: view.theme.family
        font.pixelSize: view.theme.fSmall
      }
    }
    Item { width: 1; height: view.theme.sp(4) }
    Row {
      anchors.right: parent.right
      PillButton {
        theme: view.theme
        compact: true
        text: "Open dashboard"
        iconName: "external"
        onClicked: view.dashboardRequested()
      }
    }
  }
}
