import QtQuick

// Palette and type scale for the Bose popup. Ground, ink and the surfaces
// derived from them come from the active Omarchy theme (fed in by Panel.qml),
// so the popup sits in the bar's world. The ridge band, slot cups and the ochre
// "this device / pending" accent are the design's own material.
// No qs.* imports here so the offscreen harness can construct it directly.
QtObject {
  id: theme

  property color background: "#1a1b26"
  property color foreground: "#a9b1d6"
  property color urgent: "#f7768e"
  property string themeFont: "monospace"
  property real fontScale: 1.0
  property real spaceScale: 1.0

  // Jost ships with the plugin (linux/fonts, OFL); the theme font is the fallback.
  property FontLoader jostRegular: FontLoader { source: Qt.resolvedUrl("fonts/jost_regular.ttf") }
  property FontLoader jostMedium: FontLoader { source: Qt.resolvedUrl("fonts/jost_medium.ttf") }
  readonly property bool hasJost: jostRegular.status === FontLoader.Ready || Qt.fontFamilies().indexOf("Jost") >= 0
  readonly property string family: jostRegular.status === FontLoader.Ready ? jostRegular.name : (hasJost ? "Jost" : themeFont)
  readonly property bool dark: luminance(background) < 0.35

  function channel(v) { return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
  function luminance(c) { return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b) }
  function contrast(a, b) {
    var la = luminance(a), lb = luminance(b)
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
  }
  function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1) }
  function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
  // Quietest blend of ink into ground that still reaches `ratio` against ground.
  function readable(start, ratio) {
    for (var t = start; t < 1; t += 0.02)
      if (contrast(mix(ground, ink, t), ground) >= ratio) return mix(ground, ink, t)
    return ink
  }
  function css(c, a) {
    return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + (a === undefined ? c.a : a) + ")"
  }
  function sp(px) { return Math.round(px * spaceScale) }
  function fs(px) { return Math.max(8, Math.round(px * fontScale)) }

  // Theme-derived ground and ink.
  readonly property color ground: background
  readonly property color ink: contrast(foreground, background) >= 7 ? foreground : mix(foreground, dark ? Qt.rgba(1, 1, 1, 1) : Qt.rgba(0, 0, 0, 1), 0.35)
  readonly property color ink2: readable(0.74, 5.0)
  readonly property color ink3: readable(0.62, 4.5)
  readonly property color surface: mix(ground, ink, dark ? 0.065 : 0.045)
  readonly property color cupEdge: alpha(ink, dark ? 0.12 : 0.14)
  readonly property color hair: alpha(ink, dark ? 0.13 : 0.16)
  readonly property color lineStrong: alpha(ink, dark ? 0.34 : 0.40)
  readonly property color hover: alpha(ink, 0.07)
  readonly property color track: alpha(ink, dark ? 0.18 : 0.20)
  readonly property color fill: mix(ground, ink, dark ? 0.82 : 0.86)
  readonly property color error: urgent

  // Design material: ochre accent and the teal status light.
  readonly property color accent: dark ? "#d6a858" : "#ad8037"
  readonly property color accentInk: dark ? "#e0b46a" : "#7a531a"
  readonly property color onAccent: dark ? "#1d1606" : "#1b1408"
  readonly property color ok: dark ? "#7cc4b4" : "#2f7a6e"
  readonly property color ridge: mix(ground, ink, dark ? 0.92 : 1.0)
  readonly property real ridgeBackAlpha: dark ? 0.36 : 0.55

  // Type scale: the mock's 15px body maps to the shell's 12px body.
  readonly property int fTitle: fs(17)
  readonly property int fName: fs(13)
  readonly property int fBody: fs(12)
  readonly property int fSmall: fs(10.5)
  readonly property int fCaption: fs(10)
}
