import QtQuick

// Rounded action button. "ghost" = hairline ink outline; "accent" = outlined
// ochre that fills while pressed or while its action is pending.
Item {
  id: b

  required property BoseTheme theme
  property string text: ""
  property string variant: "ghost"
  property bool busy: false
  property bool compact: false
  property string iconName: ""
  signal clicked()

  readonly property bool accent: variant === "accent"
  readonly property bool filled: accent && (area.pressed || busy)
  readonly property bool hot: area.containsMouse && enabled

  activeFocusOnTab: enabled && visible
  implicitHeight: theme.sp(compact ? 30 : 34)
  implicitWidth: label.implicitWidth + (iconName ? icon.width + theme.sp(6) : 0) + theme.sp(compact ? 28 : 36)
  opacity: enabled || busy ? 1 : 0.4

  Keys.onPressed: function(e) {
    if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { b.clicked(); e.accepted = true }
  }

  Rectangle {
    anchors.fill: parent
    radius: height / 2
    color: b.filled ? b.theme.accent : (b.hot ? (b.accent ? b.theme.alpha(b.theme.accent, 0.12) : b.theme.hover) : "transparent")
    border.width: b.activeFocus ? 2 : 1
    border.color: b.activeFocus ? b.theme.ink : (b.accent ? b.theme.accent : b.theme.lineStrong)
    Behavior on color { ColorAnimation { duration: 120; easing.type: Easing.OutCubic } }
  }

  Row {
    anchors.centerIn: parent
    spacing: b.theme.sp(6)
    BoseIcon {
      id: icon
      visible: b.iconName !== ""
      name: b.iconName
      size: b.theme.sp(15)
      color: label.color
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      id: label
      text: b.text
      textFormat: Text.PlainText
      color: b.filled ? b.theme.onAccent : (b.accent ? b.theme.accentInk : b.theme.ink)
      font.family: b.theme.family
      font.pixelSize: b.compact ? b.theme.fSmall : b.theme.fBody
      font.weight: Font.Medium
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    enabled: b.enabled && !b.busy
    cursorShape: Qt.PointingHandCursor
    onClicked: b.clicked()
  }
}
