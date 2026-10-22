---
name: Bose Connections
description: Two headset slots, saved devices and noise cancellation for a Bose 700, on one quiet flat sleeve.
colors:
  ground: "#ffffff"
  surface: "#f2f4f5"
  cup-edge: "#dfe4e7"
  ridge: "#2c3a43"
  ink: "#1b2328"
  ink-2: "#43515a"
  ink-3: "#53606a"
  hair: "rgba(27,35,40,.15)"
  line-strong: "rgba(27,35,40,.38)"
  accent: "#ad8037"
  accent-ink: "#7a531a"
  on-accent: "#1b1408"
  accent-wash: "rgba(179,134,59,.12)"
  ok: "#2f7a6e"
  ok-halo: "rgba(47,122,110,.18)"
  bad: "#9c3a2c"
  track: "rgba(27,35,40,.18)"
  fill: "#33424c"
  thumb: "#ffffff"
  scrim: "rgba(22,30,36,.38)"
  ground-dark: "#11181d"
  surface-dark: "#1a242b"
  cup-edge-dark: "#2a3640"
  ridge-dark: "#c3d0d7"
  ink-dark: "#e3e8ea"
  ink-2-dark: "#aab5bc"
  ink-3-dark: "#929ea6"
  hair-dark: "rgba(214,226,232,.12)"
  line-strong-dark: "rgba(214,226,232,.32)"
  accent-dark: "#d6a858"
  accent-ink-dark: "#e0b46a"
  on-accent-dark: "#1d1606"
  accent-wash-dark: "rgba(214,168,88,.10)"
  ok-dark: "#7cc4b4"
  ok-halo-dark: "rgba(124,196,180,.16)"
  bad-dark: "#ee9a86"
  track-dark: "rgba(214,226,232,.16)"
  fill-dark: "#b9c6cd"
  thumb-dark: "#1a242b"
  scrim-dark: "rgba(0,0,0,.55)"
typography:
  display:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "0.005em"
  headline:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 500
    lineHeight: 1.2
  title:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 500
    lineHeight: 1.35
  body:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.35
  body-strong:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 500
    lineHeight: 1.35
  label:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.35
  caption:
    fontFamily: "Jost, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.35
rounded:
  field: "14px"
  pill: "22px"
  prompt: "28px"
  cup: "30px"
  cup-popover: "26px"
  dialog: "30px"
spacing:
  cup-gap: "14px"
  cup-inset: "16px"
  gutter: "20px"
  gutter-popover: "14px"
  column-gap: "44px"
  control: "44px"
components:
  slot-cup:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.cup}"
    padding: "16px 14px 14px"
    height: "180px"
  slot-cup-pending:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.cup}"
  slot-cup-open:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.cup}"
  slot-cup-target:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.cup}"
  button-connect:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
    width: "104px"
  button-connect-pressed:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.pill}"
    height: "44px"
  button-ghost:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
  button-solid:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ground}"
    rounded: "{rounded.pill}"
    height: "44px"
  replace-prompt:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.prompt}"
    padding: "6px 6px 6px 18px"
  anc-switch:
    backgroundColor: "{colors.fill}"
    rounded: "16px"
    width: "52px"
    height: "32px"
  device-row:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    height: "66px"
    padding: "8px 0"
---

# Design System: Bose Connections

Source of truth: `web/style.css` token block (light `:root`, dark `prefers-color-scheme`). Native companions mirror it: `android/res/values{,-night}/colors.xml`, `linux/BoseTheme.qml`. Frontmatter keys without `-dark` are the light scheme; `-dark` keys are the same role in dark.

## Overview

**Creative North Star: "The Quiet Sleeve"**

One flat record sleeve: a solid ground, a full-width ridge plot of the outside sound the headset lets through, two rounded slot cups for the headset's two Bluetooth connections, and a hairline-divided list of saved devices. The world is slate ink on a plain ground with one warm ochre voice and one teal status light. Nothing floats; nothing glows. Density is low and calm, readable in a two-second glance.

Every visible state is a confirmed state or an explicitly pending one. Ochre means "this device" or "in progress"; teal means "live and confirmed". The ridges are data, not decoration: their height is the sound let through.

**Key Characteristics:**
- Flat solid grounds (light `ground`, dark `ground-dark`); no mist, gradients or fades in the UI.
- Ridge band drawn edge to edge across the full width, occluding back ridges with the ground colour.
- Slot cups: `surface` fill, 1px `cup-edge` hairline, large radius, no shadow.
- Ochre is scarce: This-device tag, pending states, outlined Connect, Replace.
- Jost throughout, two weights (400, 500).

## Colors

Cool slate neutrals on a solid ground, one ochre accent, one teal status colour, one muted red for errors.

### Primary
- **Sleeve Ochre** (`accent` / `accent-dark`): Connect outline, pending cup border, pending LED, replace-target dashed border, pressed Connect and pending pill fill, the This-device dash. Light accent is #ad8037 on every surface (3.55:1 on white, passes 3:1 for UI strokes); `accent-wash` is the same hue at 12%.
- **Ochre Ink** (`accent-ink` / `accent-ink-dark`): ochre text. 6.82:1 on white, 6.18:1 on `surface`; dark 9.3:1 on `ground-dark`.
- **On Ochre** (`on-accent`): text on filled ochre (5.15:1 light, 8.21:1 dark).

### Secondary
- **Status Teal** (`ok` / `ok-dark`): the live LED (solid dot with a 3px `ok-halo` ring) and the success icon in the status line. 5.08:1 light, 8.88:1 dark. Never used for buttons or fills.

### Tertiary
- **Error Red** (`bad` / `bad-dark`): error text and icon in the footer status line only (6.87:1 light, 8.19:1 dark).

### Neutral
- **Ground** (`ground`, `ground-dark`): page, popover and ridge occlusion fill. Also the `theme-color` meta.
- **Cup Grey** (`surface`, `surface-dark`): slot cups and the settings dialog.
- **Cup Hairline** (`cup-edge`, `cup-edge-dark`): 1px cup and dialog border. Decorative contrast (1.28:1 light, 1.45:1 dark); the fill difference carries the shape.
- **Slate Ink** (`ink`): titles, names, values (15.9:1 light, 14.5:1 dark).
- **Ink 2** (`ink-2`): secondary text, captions, icons in rows (8.19:1 on white, 7.43:1 on `surface`).
- **Ink 3** (`ink-3`): slot numbers, idle LED ring, ticks (6.46:1 on white, 5.86:1 on `surface`).
- **Ridge Slate** (`ridge`, `ridge-dark`): ridge strokes, back ridges at alpha 0.5 (dark 0.38) rising to 1 at the front; stroke width 1.35px (dark 1.2px).
- **Hairline** (`hair`) for row dividers and hover wash; **Strong line** (`line-strong`) for ghost-button and open-cup borders.
- **Track / Fill / Thumb** (`track`, `fill`, `thumb`): switch and slider. Fill is slate, never blue.
- **Scrim** (`scrim`): settings dialog backdrop.

### Named Rules
**The Two Voices Rule.** Ochre means "this device" or "pending/acting"; teal means "live, confirmed". Neither is used for decoration or for anything else.

**The Slate Control Rule.** Switch-on and slider fill are `fill` slate. Controls are never blue and never ochre.

## Typography

**Display Font:** Jost (bundled variable woff2 300–600 on web, `jost_regular`/`jost_medium` on Android and Omarchy), fallback `system-ui, sans-serif`; on Omarchy the theme font is the fallback.

**Character:** One geometric sans in two weights; hierarchy comes from size and 400/500, never from caps or tracking.

### Hierarchy
- **Display** (500, 22px; 26px at ≥760px; 1.15): the "Bose 700" heading only.
- **Headline** (500, 19px, 1.2): device name inside a cup. Settings dialog title is 20px/500.
- **Title** (500, 17px): "Noise cancellation" row label.
- **Body-strong** (500, 16px): saved-device names, empty-state headline. Buttons and battery are 15px/500.
- **Body** (400, 15px, 1.35): base text.
- **Label** (500, 13px, `ink-2`): "Saved devices" list heading, dialog field labels; sentence case.
- **Caption** (400, 13px, `ink-2`): header status line, cup state row, row sub-lines, plot caption, Aware/Max ends, footer. Cup tag line is 14px.

Numbers that change (battery, level readout) use tabular figures.

### Named Rules
**The Sentence-Case Rule.** No uppercase, no letter-spaced labels, no eyebrow text above headings. Labels are plain words in sentence case.

## Layout

- **Phone (default):** single column, max width 1040px. Header 64px min, gutters 20px (`gutter`); ridge band 150px tall, full bleed edge to edge; cups in a two-column grid, 14px gap, 16px side inset; ANC section 22px below; saved devices 28px below; footer 20px below.
- **Desktop and Mac window (≥760px, not popover):** two-column grid `1.12fr / 1fr`, 44px column gap, max width 1000px, vertically centred. Header and ridge band (190px) span both columns; cups, replace prompt and ANC on the left; saved devices and footer on the right.
- **Mac popover (`?view=popover`):** 380pt wide, always the phone layout with tighter edges: 14px gutters, ridge band 106px, cup gap 10px, cup min-height 164px, footer 12px. The page reports its height to the native popover (clamped 320–720).
- **Touch targets:** 44px for every button, icon button and the slider.
- **Header status line** is one line: it drops words, never the time, until it fits (`2 of 2 connected · Live · just now` → `2 of 2 · Live · just now` → `2 of 2 · Live`).

## Elevation & Depth

Flat. Depth comes only from the cup fill against the ground and the ridge band's own occlusion (each ridge is filled with the ground colour below its stroke, hiding the ridges behind). Cups, rows, prompt, buttons and the ridge band carry no shadow, blur or gradient.

### Named Rules
**The Flat Sleeve Rule.** No drop shadows and no fades on in-page surfaces. A surface is distinguished by fill and a 1px hairline, nothing else. Exceptions: modal dialogs (the settings sheet) keep a soft elevation shadow because they float over the page, and the switch thumb keeps its 1px shadow so it reads as a physical knob.

## Shapes

- Cups: large soft radius (30px; 26px in the popover; 22dp in the Android QS dialog).
- Buttons and pills: fully round ends (44px tall, 22px radius).
- Replace prompt: 28px radius, dashed ochre 1.5px border.
- Select fields: 14px radius. Settings dialog: 30px radius.
- Lines: 1px hairlines for dividers; 1.5px for state borders (pending solid ochre, target dashed ochre, open/unknown dashed neutral).
- Icons: 24-unit line icons, 1.4 stroke, round caps and joins, `currentColor`, drawn at 22px.

## Components

### Header status line
Title "Bose 700", then one caption line: LED, bold count ("2 of 2"), state words. LED: teal solid with halo = live; hollow `ink-3` ring = cached/unknown; `ink-3` breathing = checking; ochre breathing = pending. Cached reads `last known HH:MM`; unreachable reads `Headset not reachable`. Battery (icon whose fill tracks the percentage, 15px/500 tabular) and the settings icon button sit right.

### Ridge band (signature)
Outside sound let through, as 15 stacked smooth ridges from a fixed seeded field (same landscape on every device and render). Caption row on top: "Outside sound" left; readout right (`Level 7 / 10`, or `Off · all through`; the bold value turns `accent-ink` while a change is in flight).
- **Amplitude:** web `0.06 + 0.94 × (10 − level)/10`: level 0 (aware) is tallest, level 10 nearly flat. ANC Off is taller than level 0 (1.18) and **dashed** (5/4).
- **Unknown/offline:** flattened (0.1) and faded to 40% alpha.
- **Live drag:** the slider previews amplitude while dragging; transitions ease over 180ms (cubic out); reduced motion jumps.
- Ridges never climb into the caption row; displacement saturates below it.

### Slot cups
Two cups side by side, always in a stable order: a connected device keeps the cup it already holds. Each cup: state row (LED, state word, "Slot N" right), device icon, name, tag line, action at the bottom.
- **Connected:** `surface` fill, 1px `cup-edge`, teal LED, ghost Disconnect.
- **This device:** tag line in `accent-ink` 500 with a 12×2px ochre dash: "This PC" / "This phone" / "This Mac".
- **Pending (connecting/disconnecting):** 1.5px solid ochre border, state row `accent-ink` 500, breathing ochre LED, bottom filled ochre pill "Connecting…" / "Disconnecting…" (`aria-busy`). Disconnecting dims name and icon to 60%. A connecting device leaves the saved list and appears in its target cup with "Replacing <name>" when replacing.
- **Open (live, empty):** transparent, 1.5px dashed `line-strong`, "Open slot", "Connect a saved device".
- **Unknown/cached-empty:** transparent, 1.5px dashed `hair`, compact; "Not known"/"Headset not reachable" or "Open slot"/"Refresh to check".
- **Replace target:** while choosing, each connected cup becomes a button with a 1.5px dashed ochre border, `accent-wash` on hover, ochre outlined "Replace" pill.

### Buttons
- **Connect:** outlined ochre (1.5px `accent`), `accent-ink` text, min width 104px; hover `accent-wash`; active/pressed (choosing a slot) filled ochre with `on-accent` text and `aria-pressed`.
- **Ghost (Disconnect, Cancel):** 1px `line-strong` border, `ink` text, hover `hair`.
- **Solid (Save devices):** `fill` background, `ground` text. **Quiet:** text-only `ink-2`.
- Disabled: 42% opacity; the busy item stays legible.
- Focus: 2px `ink` outline, 3px offset (ochre on replace targets).

### Replace prompt
Appears above the cups when both slots are full and a Connect is tapped: dashed ochre pill strip, `accent-wash` fill, "Both slots are in use. Choose which connection <name> replaces." and a Cancel ghost button. Focus moves to the first target cup; Escape cancels and returns focus to the row.

### Noise cancellation
Row: "Noise cancellation" (title) + sub-line (`On · level 7 of 10` / `Off · all through`; pending `Setting level 7…` / `Turning off…` in `accent-ink` with a pending LED). Switch: 52×32 slate track/fill. Slider 0–10 with 11 ticks and Aware/Max ends; dimmed to 40% and disabled when ANC is off.
- **Release-apply:** dragging only previews (ridges and labels); the level is written on release.
- **Coalescing:** at most one write in flight; while one is in flight only the latest requested value is queued, and the next write starts no sooner than 250ms after the previous one started. Failure clears the queue and reverts to the confirmed value.

### Saved devices
Label row "Saved devices" with a refresh icon button (spins while checking). Rows: 1px `hair` dividers, 66px min, icon (`ink-2`), name (16/500), sub-line `Saved · not connected · <role>`, Connect at right. Empty states use a bold line plus a caption.

### Footer controllers line
`Controllers: PC here · Phone available · Mac checking…`, names bold. Words, per controller: **here** (serves this page and has live state), **available** (reachable), **connected** (still checking but its own device holds a slot), **checking…**, **offline** (error or unreachable), **not set up**. Below it, the status line: check icon in teal for success, alert icon in `bad` for errors.

### Truth and interaction rules
- Pending is shown immediately, then becomes verified (headset read-back) or reverts to the confirmed state with an error message. No optimistic final state.
- One mutation in flight across the whole surface: connection changes and ANC writes block each other; other controls disable.
- No automatic retry. Errors say "Refresh before trying again."
- Cached state renders first and is read-only ("Last known", hollow LEDs); mutations need live state.

### Per-surface adaptations
- **Web phone / desktop / popover:** as Layout.
- **Android QS dialog** (`BoseTileService`): same world in native views, 28dp rounded ground card on the system scrim, 22dp cups, Jost regular/medium, colours from `qs_*` resources; header line `Live · 2 of 2 connected`; adds an App settings and Close footer. **Tile subtitle:** `2 of 2 · ANC 7`, `2 of 2 · ANC off`, `Updating…` while ANC is in flight.
- **Omarchy popup** (`linux/BoseView.qml`): ground and ink come from the active Omarchy theme; surfaces, hairlines and text tiers are mixes of theme ground and ink (ink tiers held to ≥5:1 and ≥4.5:1); ochre accent and teal LED stay the design's own. Type is scaled down to the bar (title 17, name 13, body 12). Ridge band 86px, 9 ridges.
- **Mac:** status-bar template icon (SF Symbol headphones); left click opens an NSPopover hosting the web popover view at 380pt; right click opens a native NSMenu (Connected, Saved with Replace submenus, Noise cancellation submenu, Open full window, Quit).
- **Desk bar compact panel:** lives in another repo and uses the bar's own theme; not specified here.

### App mark
`tools/icon.py`: five outside-sound ridges on a slate mist (vertical #33424b→#121a1f with a faint radial glow), light ink ridges fading in at the sides, the front ridge in ochre (#d6a858). One geometry generates the Android adaptive icon (plus monochrome), favicon and Mac AppIcon. The mist belongs to the mark only.

## Do's and Don'ts

### Do:
- **Do** keep grounds flat and solid (`ground`, `ground-dark`, or the host theme's ground on Omarchy).
- **Do** draw the ridge band edge to edge and make its height mean the outside sound let through.
- **Do** separate surfaces by `surface` fill and a 1px `cup-edge` hairline.
- **Do** show pending in ochre at once and settle only on read-back; revert on failure.
- **Do** keep one mutation in flight and queue only the latest ANC value.
- **Do** pair every colour state with a word (Connected, Connecting…, Open slot, Last known).
- **Do** use anonymized device names ("Desktop PC", "Android phone", "MacBook Pro", "Living room TV") in any public screenshot or fixture.

### Don't:
- **Don't** put mist gradients, fades or vignettes on any UI ground (the app mark is the only place mist appears).
- **Don't** add drop shadows to cups, rows, buttons, the prompt or the ridge band.
- **Don't** use blue (or any hue but slate `fill`) for switches and sliders.
- **Don't** use ochre for decoration, headings or generic buttons.
- **Don't** use Bose logos, wordmarks or trade dress; "Bose 700" appears as plain Jost text only.
- **Don't** publish real device names, Bluetooth addresses, hostnames or network names.
- **Don't** add uppercase eyebrows, kickers or letter-spaced labels.
- **Don't** auto-retry a failed change or show a state the headset has not confirmed.
