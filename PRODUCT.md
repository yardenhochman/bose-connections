# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The dashboard is one static web app (`web/`) served by the Python controller on Linux and macOS and embedded in an Android WebView. The Android Quick Settings dialog (`android/BoseTileService.java`), the macOS menu-bar menu (`mac/Launcher.m`) and the Omarchy top-bar popup (`linux/Panel.qml`) are native companions to it.

## Users

The owner of a Bose Noise Cancelling Headphones 700 who moves the headset between several of their own devices (a desktop PC, a Mac, a phone, sometimes a TV) during the day. They open the dashboard or the Quick Settings tile for a few seconds at a time, usually while putting the headphones on or switching to another device, and want to see at a glance which devices hold the headset and move it with one tap. Secondary audience: people reading the public GitHub README and deciding whether to try it. (Inferred from the README and the 2026-10-23 brief; to be confirmed.)

## Product Purpose

Show the headset's saved devices, which two currently hold its Bluetooth slots, and move a connection: connect, disconnect, or choose which connection to replace when both slots are full. Set noise cancellation 0–10 or Off. Success: switching the headset to another device takes one glance and one tap, and the screen never claims a state the headset has not confirmed.

## Positioning

The NC700 holds two simultaneous connections. Bose's own app only manages the phone it runs on. This tool shows both slots from any of the owner's devices and can relay a request through another controller over Tailscale, verifying every change by reading the headset back.

## Operating Context

- Glanced at on a phone (Quick Settings tile or app), on a Mac menu bar, on an Omarchy Linux top bar, or in a desktop browser at `127.0.0.1:8847`.
- Cached state shows immediately; a live refresh follows. Cached entries are read-only; mutations need live state.
- Controllers (PC, Mac, phone) may be reachable, offline, or still checking.

## Capabilities and Constraints

- Exactly two connection slots. When both are full, connecting another device requires choosing which one to replace.
- Noise cancellation: levels 0 (aware) to 10 (maximum) and Off. Writes are read back; unknown layouts refuse writes.
- Battery percentage is shown when known.
- Experimental status is stated honestly; no claims beyond what has been verified.
- Public repository: screenshots and fixtures must use anonymized device names and no real addresses, network names or hostnames.
- Not affiliated with Bose. Must not use Bose logos or trade dress as its own branding.

## Brand Commitments

Name: "Bose Connections"; in-app heading "Bose 700". Voice: plain, factual, short labels ("Connect", "Disconnect", "Replace"). No marketing tone.

## Evidence on Hand

Anonymized screenshots in `docs/screenshots/`. Synthetic fixtures in `tests/gui-fixtures.cjs`. No real device names may be published.

## Product Principles

1. Truth over optimism: show what the headset confirmed, mark what is cached or unknown.
2. One glance, one tap: the slot state and the switch action dominate; settings stay out of the way.
3. Explicit replacement: never silently drop a connection.
4. Same mental model on every surface: two slots, saved devices, noise level.

## Accessibility & Inclusion

Usable one-handed on a phone, in light and dark system themes; controls reachable by keyboard on desktop; state never conveyed by color alone.
