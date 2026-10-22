import QtQuick

// A saved device that is not holding a slot, with an outlined Connect.
Item {
  id: row

  required property BoseTheme theme
  property string name: ""
  property string tag: ""
  property string kind: "laptop"
  property bool cached: false
  property bool busy: false
  property bool selected: false      // waiting for a slot to replace
  property bool actionEnabled: false
  signal connectRequested()

  implicitHeight: theme.sp(50)

  Rectangle { width: parent.width; height: 1; color: row.theme.hair }

  BoseIcon {
    id: glyph
    name: row.kind
    size: row.theme.sp(20)
    color: row.theme.ink2
    anchors.left: parent.left
    anchors.leftMargin: row.theme.sp(2)
    anchors.verticalCenter: parent.verticalCenter
  }

  Column {
    anchors.left: glyph.right
    anchors.leftMargin: row.theme.sp(12)
    anchors.right: button.left
    anchors.rightMargin: row.theme.sp(10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: row.theme.sp(1)
    Text {
      width: parent.width
      text: row.name
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: row.theme.ink
      font.family: row.theme.family
      font.pixelSize: row.theme.fName
      font.weight: Font.Medium
    }
    Text {
      width: parent.width
      text: row.selected ? "Choose a slot above to replace"
          : (row.tag ? row.tag + " · " : "") + (row.cached ? "last known: not connected" : "Saved · not connected")
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: row.selected ? row.theme.accentInk : row.theme.ink2
      font.family: row.theme.family
      font.pixelSize: row.theme.fSmall
    }
  }

  PillButton {
    id: button
    theme: row.theme
    compact: true
    width: Math.max(implicitWidth, row.theme.sp(92))
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    text: "Connect"
    variant: "accent"
    busy: row.busy || row.selected
    enabled: row.actionEnabled
    onClicked: row.connectRequested()
  }
}
