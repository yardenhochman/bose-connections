import QtQuick
import QtQuick.Shapes

// Line icons drawn on a 24-unit grid, one stroke weight throughout.
Item {
  id: icon

  property string name: "laptop"
  property color color: "white"
  property real size: 20
  property real stroke: 1.5

  implicitWidth: size
  implicitHeight: size

  function rr(x, y, w, h, r) {
    return "M" + (x + r) + " " + y + "H" + (x + w - r) + "A" + r + " " + r + " 0 0 1 " + (x + w) + " " + (y + r)
      + "V" + (y + h - r) + "A" + r + " " + r + " 0 0 1 " + (x + w - r) + " " + (y + h)
      + "H" + (x + r) + "A" + r + " " + r + " 0 0 1 " + x + " " + (y + h - r)
      + "V" + (y + r) + "A" + r + " " + r + " 0 0 1 " + (x + r) + " " + y + "Z"
  }
  function circle(cx, cy, r) {
    return "M" + (cx + r) + " " + cy + "A" + r + " " + r + " 0 1 1 " + (cx - r) + " " + cy + "A" + r + " " + r + " 0 1 1 " + (cx + r) + " " + cy + "Z"
  }
  readonly property string path: {
    switch (name) {
    case "desktop": return rr(2.5, 4, 19, 12.5, 1.5) + " M12 16.5V20 M8 20.5H16"
    case "laptop": return rr(4, 5, 16, 11, 1.5) + " M2 19H22"
    case "tv": return rr(2.5, 4, 19, 13, 1.5) + " M8 20.5H16"
    case "phone": return rr(7, 2.5, 10, 19, 2) + " M11 18.5H13"
    case "refresh": return "M19.5 12A7.5 7.5 0 1 1 17.3 6.7 M19.5 3.5V7.5H15.5"
    case "settings": return "M4 7.5H13 M18 7.5H20 M4 16.5H6 M11 16.5H20 " + circle(15.5, 7.5, 2.3) + " " + circle(8.5, 16.5, 2.3)
    case "chevron": return "M7 10L12 15L17 10"
    case "check": return "M5 12.5L9.5 17L19 7.5"
    case "alert": return circle(12, 12, 8.5) + " M12 7.5V13 M12 16.2V16.6"
    case "external": return "M13.5 4.5H19.5V10.5 M19.5 4.5L11 13 M17 14V18A1.5 1.5 0 0 1 15.5 19.5H6A1.5 1.5 0 0 1 4.5 18V8.5A1.5 1.5 0 0 1 6 7H10"
    default: return ""
    }
  }

  Shape {
    width: 24
    height: 24
    scale: icon.size / 24
    transformOrigin: Item.TopLeft
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
      strokeColor: icon.color
      strokeWidth: icon.stroke
      fillColor: "transparent"
      capStyle: ShapePath.RoundCap
      joinStyle: ShapePath.RoundJoin
      PathSvg { path: icon.path }
    }
  }
}
