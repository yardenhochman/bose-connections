---
version: 1
slug: "web-index-html"
primary_target: "web/index.html"
related_targets: ["linux/Panel.qml","android/BoseTileService.java"]
---

Scope: Bose Connections dashboard (web/, shared by Linux, macOS app window, Android app) plus its native companions (Android Quick Settings dialog, Omarchy popup, macOS menu). Mode: Operate.
Audience/job: the NC700 owner glancing for seconds to see which two devices hold the headset and move it with one tap; set ANC.
Constraints: public repo, anonymized content; truth over optimism (pending is visibly pending until the headset read-back confirms); never blindly retry.

## Direction contract
THESIS: The headset's two slots and the outside sound it lets through, shown as one quiet record sleeve: misty slate ground, two slot cups, and a live ridge plot of outside sound. Refuses the stack of white rounded cards with grey text and a blue slider.
OWN-WORLD: Flat grounds, no mist or fades (2026-10-23 owner revision): light solid #ffffff ground, #f2f4f5 cups with a 1px #dfe4e7 hairline and no shadow, #1b2328 ink; dark solid #11181d ground / #1a242b cups with a subtle hairline. Ridges drawn full width on the clean ground. Ochre (#ad8037, text #7a531a; dark #d6a858) only for This PC, pending and pressed Connect; teal status light. Jost. Rounded cups, hairline-divided rows, outlined ochre Connect.
STORY: The user sees 2/2 and who holds the slots at once, taps Connect/Disconnect and sees the pending state immediately, then sees it settle once the headset confirms. Dragging ANC flattens the ridges live; the level applies on release.
FIRST VIEWPORT: Header (Bose 700, live status, battery, settings); outside-sound ridge band about 140px tall; two slot cups side by side with Disconnect; the ANC switch and slider; saved devices with Connect. On desktop the cups and the ANC section sit left, and saved devices sit in a right column.
FORM: Hybrid of grounded candidate 4 (quiet sleeve world), the pick's slot-cup structure and the pulse challenger's ridge plot, chosen over two rounds. seed:24977df15d6fa040
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
