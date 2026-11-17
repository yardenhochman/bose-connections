import QtQuick
import QtQuick.Shapes

// Rounded action button. "ghost" = hairline ink outline; "accent" = outlined
// ochre that fills while pressed or while its action is pending.
// spinning: a request in flight, drawn lighter than a result (ochre wash, a
// turning arc, no fill). dotted: a queued intent (dotted outline, hollow ring).
Item {
  id: b

  required property BoseTheme theme
  property string text: ""
  property string variant: "ghost"
  property bool busy: false
  property bool compact: false
  property string iconName: ""
  property bool spinning: false
  property bool dotted: false
  property bool animate: true
  signal clicked()

  readonly property bool accent: variant === "accent"
  readonly property bool filled: accent && (area.pressed || busy) && !spinning && !dotted
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
    color: b.filled ? b.theme.accent : (b.spinning || b.hot ? (b.accent ? b.theme.alpha(b.theme.accent, 0.12) : b.theme.hover) : "transparent")
    border.width: b.dotted ? 0 : b.activeFocus ? 2 : 1
    border.color: b.activeFocus ? b.theme.ink : (b.accent ? b.theme.accent : b.theme.lineStrong)
    Behavior on color { ColorAnimation { duration: 120; easing.type: Easing.OutCubic } }
  }
  Shape {
    visible: b.dotted
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
      strokeColor: b.activeFocus ? b.theme.ink : b.theme.accent
      strokeWidth: b.activeFocus ? 2 : 1.2
      strokeStyle: ShapePath.DashLine
      dashPattern: [1.2, 2]
      fillColor: "transparent"
      PathRectangle { x: 0.5; y: 0.5; width: b.width - 1; height: b.height - 1; radius: (b.height - 1) / 2 }
    }
  }

  Row {
    anchors.centerIn: parent
    spacing: b.theme.sp(6)
    // In flight: a turning three-quarter arc. Queued: a hollow ring. An icon-only button turns its icon instead and
    // shows queued by its dotted outline alone.
    Item {
      visible: (b.spinning || b.dotted) && b.text !== ""
      width: b.theme.sp(11); height: width
      anchors.verticalCenter: parent.verticalCenter
      Shape {
        id: arc
        visible: b.spinning
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: label.color
          strokeWidth: Math.max(1.5, b.theme.sp(1.8))
          fillColor: "transparent"
          capStyle: ShapePath.RoundCap
          PathAngleArc { centerX: arc.width / 2; centerY: arc.height / 2; radiusX: arc.width / 2 - 1; radiusY: radiusX; startAngle: 0; sweepAngle: 270 }
        }
        RotationAnimator on rotation { running: b.spinning && b.animate; from: 0; to: 360; duration: 900; loops: Animation.Infinite }
      }
      Rectangle {
        visible: b.dotted
        anchors.centerIn: parent
        width: b.theme.sp(8); height: width; radius: width / 2
        color: "transparent"
        border.width: Math.max(1, b.theme.sp(1.4)); border.color: label.color
      }
    }
    BoseIcon {
      id: icon
      visible: b.iconName !== ""
      name: b.iconName
      size: b.theme.sp(15)
      color: label.color
      anchors.verticalCenter: parent.verticalCenter
      RotationAnimator on rotation { running: b.spinning && b.text === "" && b.animate; from: 0; to: 360; duration: 900; loops: Animation.Infinite }
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
    enabled: b.enabled && !b.busy && !b.spinning
    cursorShape: Qt.PointingHandCursor
    onClicked: b.clicked()
  }
}
