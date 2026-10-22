import QtQuick

// "Outside sound" ridge plot: stacked smooth ridges whose height is the sound
// the headset lets through. Level 0 (aware) draws tall ridges, level 10 nearly
// flat; with noise cancellation off the ridges are tallest and dashed.
Canvas {
  id: band

  required property BoseTheme theme
  property real level: 7          // 0..10, follows the slider live
  property bool ancEnabled: true
  property bool known: true
  property bool animate: true
  property int lines: 9

  readonly property real targetAmp: !known ? 0.1 : (!ancEnabled ? 1.22 : 0.07 + 0.93 * Math.pow(1 - level / 10, 1.15))
  property real amp: targetAmp
  Behavior on amp {
    enabled: band.animate
    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
  }

  onAmpChanged: requestPaint()
  onAncEnabledChanged: requestPaint()
  onKnownChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()
  onVisibleChanged: if (visible) requestPaint()
  onAvailableChanged: if (available) requestPaint()
  Connections {
    target: band.theme
    function onGroundChanged() { band.requestPaint() }
    function onRidgeChanged() { band.requestPaint() }
  }

  // Deterministic pseudo-random in [0, 1).
  function rnd(seed) { var x = Math.sin(seed * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x) }

  function profile(i, u) {
    var v = 0
    for (var k = 0; k < 3; k++) {
      var c = 0.34 + 0.32 * rnd(i * 7 + k * 3 + 1)
      var w = 0.035 + 0.07 * rnd(i * 11 + k * 5 + 2)
      var a = 0.35 + 0.65 * rnd(i * 13 + k * 7 + 3)
      v += a * Math.exp(-Math.pow((u - c) / w, 2))
    }
    v += 0.10 * Math.sin(u * 23 + i * 1.7) * Math.exp(-Math.pow((u - 0.5) / 0.22, 2))
    return v * Math.exp(-Math.pow((u - 0.5) / 0.24, 2))
  }

  onPaint: {
    var ctx = getContext("2d")
    var W = width, H = height
    ctx.reset()
    ctx.clearRect(0, 0, W, H)
    if (W <= 0 || H <= 0) return
    var ground = theme.ground, ridge = theme.ridge
    var top = H * 0.34, bottom = H * 0.94, minY = H * 0.27
    var gap = (bottom - top) / (lines - 1)
    var maxRise = gap * 3.0
    var steps = 48
    ctx.lineWidth = Math.max(1, theme.sp(1.2))
    ctx.lineJoin = "round"
    ctx.setLineDash(ancEnabled || !known ? [] : [theme.sp(4), theme.sp(3)])
    for (var i = 0; i < lines; i++) {
      var base = top + gap * i
      var pts = []
      for (var s = 0; s <= steps; s++) {
        var u = s / steps
        pts.push([u * W, Math.max(minY, base - maxRise * amp * profile(i, u))])
      }
      ctx.beginPath()
      ctx.moveTo(pts[0][0], pts[0][1])
      for (var p = 1; p < pts.length - 1; p++) {
        var mx = (pts[p][0] + pts[p + 1][0]) / 2, my = (pts[p][1] + pts[p + 1][1]) / 2
        ctx.quadraticCurveTo(pts[p][0], pts[p][1], mx, my)
      }
      ctx.lineTo(pts[steps][0], pts[steps][1])
      // Occlude the ridges behind, then stroke.
      ctx.save()
      ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath()
      ctx.globalAlpha = 1
      ctx.fillStyle = theme.css(ground, 1)
      ctx.fill()
      ctx.restore()
      ctx.beginPath()
      ctx.moveTo(pts[0][0], pts[0][1])
      for (var q = 1; q < pts.length - 1; q++) {
        var nx = (pts[q][0] + pts[q + 1][0]) / 2, ny = (pts[q][1] + pts[q + 1][1]) / 2
        ctx.quadraticCurveTo(pts[q][0], pts[q][1], nx, ny)
      }
      ctx.lineTo(pts[steps][0], pts[steps][1])
      var back = theme.ridgeBackAlpha * (known ? 1 : 0.7)
      ctx.strokeStyle = theme.css(ridge, back + (1 - back) * i / (lines - 1) * (known ? 1 : 0.6))
      ctx.stroke()
    }
    ctx.setLineDash([])
  }
}
