pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes

// One of the headset's two connection slots.
// slotState: connected | connecting | disconnecting | empty | checking
Item {
  id: cup

  required property BoseTheme theme
  property int slotNumber: 1
  property string slotState: "empty"
  property string name: ""
  property string tag: ""
  property bool here: false
  property bool cached: false
  property string replacedName: ""
  property string actionText: ""      // "Disconnect" | "Replace" | ""
  property bool actionEnabled: false
  signal action()

  readonly property bool pending: slotState === "connecting" || slotState === "disconnecting"
  readonly property bool empty: slotState === "empty" || slotState === "checking"
  readonly property real radius: theme.sp(18)

  implicitHeight: body.implicitHeight + theme.sp(24)

  Rectangle {
    anchors.fill: parent
    radius: cup.radius
    color: cup.empty ? "transparent" : cup.theme.surface
    border.width: cup.pending ? 1.5 : (cup.empty ? 0 : 1)
    border.color: cup.pending ? cup.theme.accent : cup.theme.cupEdge
  }

  Shape {
    visible: cup.empty
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
      strokeColor: cup.theme.lineStrong
      strokeWidth: 1
      strokeStyle: ShapePath.DashLine
      dashPattern: [4, 3]
      fillColor: "transparent"
      PathRectangle { x: 0.5; y: 0.5; width: cup.width - 1; height: cup.height - 1; radius: cup.radius }
    }
  }

  Column {
    id: body
    anchors { left: parent.left; right: parent.right; top: parent.top; margins: cup.theme.sp(12) }
    spacing: cup.theme.sp(2)

    Row {
      spacing: cup.theme.sp(7)
      width: parent.width
      Item {
        width: cup.theme.sp(13); height: cup.theme.sp(13)
        anchors.verticalCenter: parent.verticalCenter
        Rectangle {
          anchors.centerIn: parent
          width: parent.width; height: width; radius: width / 2
          color: cup.theme.alpha(led.color, 0.2)
          visible: !cup.empty || cup.slotState === "checking"
        }
        Rectangle {
          id: led
          anchors.centerIn: parent
          width: cup.theme.sp(7); height: width; radius: width / 2
          color: cup.pending || cup.slotState === "checking" ? cup.theme.accent
               : cup.empty ? "transparent" : (cup.cached ? cup.theme.ink3 : cup.theme.ok)
          border.width: cup.empty && cup.slotState !== "checking" ? 1 : 0
          border.color: cup.theme.ink3
          SequentialAnimation on opacity {
            running: cup.pending || cup.slotState === "checking"
            loops: Animation.Infinite
            alwaysRunToEnd: true
            NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
          }
        }
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: (cup.slotState === "connecting" ? "Connecting…"
              : cup.slotState === "disconnecting" ? "Disconnecting…"
              : cup.slotState === "checking" ? "Checking…"
              : cup.empty ? "Free"
              : cup.cached ? "Last known" : "Connected") + (cup.pending ? "" : " · Slot " + cup.slotNumber)
        textFormat: Text.PlainText
        color: cup.pending ? cup.theme.accentInk : cup.theme.ink2
        font.family: cup.theme.family
        font.pixelSize: cup.theme.fCaption
        font.weight: cup.pending ? Font.Medium : Font.Normal
      }
    }

    Item { width: 1; height: cup.theme.sp(4) }

    Text {
      width: parent.width
      text: cup.empty ? (cup.slotState === "checking" ? " " : "Open slot") : cup.name
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: cup.empty ? cup.theme.ink3 : cup.theme.ink
      opacity: cup.slotState === "disconnecting" ? 0.6 : 1
      font.family: cup.theme.family
      font.pixelSize: cup.theme.fName
      font.weight: Font.Medium
    }

    Row {
      spacing: cup.theme.sp(6)
      width: parent.width
      Rectangle {
        visible: cup.here && !cup.empty
        width: cup.theme.sp(11); height: 2; radius: 1
        color: cup.theme.accent
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        width: parent.width - (cup.here && !cup.empty ? cup.theme.sp(17) : 0)
        text: cup.empty ? "Ready for a device"
            : cup.slotState === "connecting" && cup.replacedName ? "Replacing " + cup.replacedName
            : (cup.tag || "Saved device")
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: cup.here && !cup.empty && !cup.replacedName ? cup.theme.accentInk : cup.theme.ink2
        font.family: cup.theme.family
        font.pixelSize: cup.theme.fSmall
        font.weight: cup.here && !cup.empty ? Font.Medium : Font.Normal
      }
    }

    Item { width: 1; height: cup.theme.sp(6) }

    PillButton {
      theme: cup.theme
      width: parent.width
      compact: true
      visible: cup.actionText !== "" || cup.pending
      text: cup.slotState === "connecting" ? "Connecting…" : cup.slotState === "disconnecting" ? "Disconnecting…" : cup.actionText
      variant: cup.actionText === "Replace" || cup.pending ? "accent" : "ghost"
      busy: cup.pending
      enabled: cup.actionEnabled && !cup.pending
      onClicked: cup.action()
    }
    Item {
      visible: !(cup.actionText !== "" || cup.pending)
      width: 1
      height: cup.theme.sp(30)
    }
  }
}
