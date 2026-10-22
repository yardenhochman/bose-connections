import QtQuick
import qs.Ui as Ui
import qs.Commons

// Omarchy bar widget + popup for Bose Connections. The bar shows a headphones
// glyph with the number of occupied slots, dims when the headset or helper is
// unreachable, and breathes an ochre dot while a change is being verified.
Ui.Panel {
  id: root
  moduleName: "local.bose"
  ipcTarget: "local.bose"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property BoseModel model: BoseModel {}
  readonly property BoseTheme theme: BoseTheme {
    background: Color.popups.background
    foreground: Color.popups.text
    urgent: Color.urgent
    themeFont: Style.font.family
    fontScale: Style.font.body / 12
    spaceScale: Style.space(100) / 100
  }

  // Let the bar finish loading before the first read.
  Component.onCompleted: Qt.callLater(function() { root.model.loadCached(false) })
  onOpenedChanged: if (opened) model.opened(); else view.showSettings = false

  // Keep the badge current from the stored snapshot while the popup is closed.
  Timer {
    interval: 30000
    repeat: true
    running: !root.opened
    onTriggered: if (!root.model.busy && !root.model.loading) root.model.loadCached(false)
  }

  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰋋"
    slotSize: Style.bar.iconSlot + Style.space(5)
    dimmed: !root.model.barReachable
    tooltipText: root.model.helperDown ? "Bose 700: helper not running"
      : !root.model.loaded ? "Bose 700"
      : !root.model.snapshot.reachable ? "Bose 700: unavailable"
      : root.model.busy ? "Bose 700: applying a change…"
      : "Bose 700: " + root.model.connectedCount + " of 2 connected" + (root.model.snapshot.cached ? " (last known)" : "")
    onPressed: function(b) { if (b === Qt.RightButton) root.model.refresh(); else root.toggle() }

    Text {
      visible: root.model.barReachable && root.model.connectedCount > 0 && !root.model.busy
      anchors.right: parent.right
      anchors.rightMargin: Style.space(2)
      anchors.bottom: parent.verticalCenter
      anchors.bottomMargin: -Style.space(9)
      text: String(root.model.connectedCount)
      textFormat: Text.PlainText
      color: button.foreground
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Math.round(Style.font.caption * 0.9)
      font.bold: true
    }
    Rectangle {
      visible: root.model.busy
      width: Style.space(5); height: width; radius: width / 2
      anchors.right: parent.right
      anchors.rightMargin: Style.space(3)
      anchors.bottom: parent.verticalCenter
      anchors.bottomMargin: -Style.space(7)
      color: root.theme.accent
      SequentialAnimation on opacity {
        running: root.model.busy
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { to: 0.25; duration: 650; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1; duration: 650; easing.type: Easing.InOutSine }
      }
    }
  }

  Ui.KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    focusTarget: view
    contentWidth: popup.fittedContentWidth(Style.space(340))
    contentHeight: popup.fittedContentHeight(view.implicitHeight)

    Flickable {
      id: flick
      anchors.fill: parent
      contentHeight: view.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      clip: contentHeight > height
      BoseView {
        id: view
        width: flick.width
        focus: true
        theme: root.theme
        model: root.model
        bleed: Math.max(0, popup.padding - Style.space(2))
        onCloseRequested: root.close()
        onDashboardRequested: { root.close(); if (root.bar) root.bar.run("omarchy-launch-webapp 'http://127.0.0.1:8847/?view=popover' --window-size=420,780") }
      }
    }
  }
}
