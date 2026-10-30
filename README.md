# Bose Connections

A minimal connection dashboard for the **Bose Noise Cancelling Headphones 700**.
See the headset's saved devices, connect or disconnect them, and choose which
connection to replace when both Bluetooth slots are occupied.

- Shared dashboard for Linux, macOS and Android, with a new app icon. It follows
  the system light/dark setting.
- Pending states appear instantly and settle only after the headset confirms;
  a failed or unconfirmed change reverts to the verified state.
- Noise cancellation levels 0–10 and Off, with verified headset state. The slider
  applies on release, and a switch turns noise cancellation on or off.
- Android Quick Settings tile and a native dialog with connections and ANC controls.
- Omarchy top-bar popup that uses the active Omarchy theme's colours.
- macOS menu-bar icon that opens a compact popover; right-click for the native menu.
- Optional authenticated controller-to-controller relay over Tailscale: an
  unconnected computer can send a request through a controller that reaches the headset.
- Immediate last-known device list, followed by a live refresh. When no controller can read the
  headset, the dashboard says so and gives each controller's reason (not connected, app not
  running, no answer); a controller with no Bluetooth link never shows in a last-known slot.
- Connection changes reread headset state, preserve a known control device, and
  verify the result. An ambiguous command is never retried through another peer.

## Screenshots

Device and network names are anonymized; unrelated phone content is removed.

<table>
  <tr>
    <th>Phone, light</th><th>Phone, dark</th><th>Desktop</th>
  </tr>
  <tr>
    <td><img src="docs/screenshots/phone-light.png" width="260" alt="Web dashboard in the phone layout, light theme: two connected slot cards, noise cancellation switch and slider, saved devices"></td>
    <td><img src="docs/screenshots/phone-dark.png" width="260" alt="Web dashboard in the phone layout, dark theme"></td>
    <td><img src="docs/screenshots/desktop.png" width="420" alt="Web dashboard in the desktop layout with slot cards beside the saved devices list"></td>
  </tr>
  <tr>
    <th>Android dialog, light</th><th>Android dialog, dark</th><th>Android Quick Settings tile</th>
  </tr>
  <tr>
    <td><img src="docs/screenshots/quick-settings-light.png" width="260" alt="Native Android Quick Settings dialog, light theme, with slot cards, ANC controls and saved devices"></td>
    <td><img src="docs/screenshots/quick-settings-dark.png" width="260" alt="Native Android Quick Settings dialog, dark theme"></td>
    <td><img src="docs/screenshots/tile.png" width="260" alt="Quick Settings panel with the Bose tile showing 2 of 2 connected and ANC 7"></td>
  </tr>
  <tr>
    <th>Omarchy popup</th><th>macOS menu-bar popover</th><th></th>
  </tr>
  <tr>
    <td><img src="docs/screenshots/omarchy-popup.png" width="260" alt="Omarchy top-bar popup in the Tokyo Night theme"></td>
    <td><img src="docs/screenshots/mac-popover.png" width="260" alt="Compact macOS menu-bar popover with slot cards, ANC controls and saved devices"></td>
    <td></td>
  </tr>
</table>

Independent community project; not affiliated with Bose. **Experimental:**
macOS reads and disconnect/reconnect have been verified on one NC700 running
firmware 1.8.2. Linux direct reads and phone disconnect/reconnect are also verified,
as are ANC levels 9 and 10. Relay switching has succeeded but repeated recovery
checks have been inconsistent. Android installs/builds and its Quick Settings tile
is registered, and its dialog appearance has been checked on Samsung Android.
Android direct Bluetooth and recovery behavior still need validation.
Sleep/reboot recovery and automatic controller retention remain experimental.
This does not support other Bose models.

Noise cancellation offers levels **0–10** and **Off**. Unknown packet layouts
refuse writes. Changes are read back from the headset; missing acknowledgements
trigger verification, never a blind repeat. Enabling ANC may reset the NC700 to
maximum, so a second write occurs only after a confirmed read of that transition.

## What is authoritative?

The headset owns saved devices and active connections. Each controller keeps a
private timestamped `snapshot.json` for display. Menus load that list immediately,
then query the headset directly or through a peer. Cached data never replaces the
fresh checks performed before/after a connection change.

Controller roles, peer addresses and the shared relay token live in each
controller's private `config.json`. **Role/settings edits are not synchronized.**
Provision the same role mappings and token on each controller. Live snapshots may
briefly differ between refreshes; this is not a distributed database or a promise
of continuous connectivity. If every controller loses headset access, reconnect
one through system Bluetooth settings or the Bose app.

## Desktop setup

Requires Python 3.12+; Linux direct access uses BlueZ/RFCOMM. On macOS, the
installer creates a private venv, installs the included MIT `pybmap` package and
PyObjC when needed, and builds a native application using Xcode Command Line Tools.
Pair your NC700 in system Bluetooth settings first. Obtain its Bluetooth address.

Create a **local-only** controller config (replace the example address):

```sh
python3 configure.py --id pc --headset AA:BB:CC:DD:EE:FF
python3 controller.py
```

Open `http://127.0.0.1:8847`. The config and cache are stored under
`~/.local/state/bose-control/`, outside the repository. Existing configs are not
overwritten by `configure.py`. The default NC700 RFCOMM channel is 8; it may need
verification on your headset/firmware.

For macOS, create a config with `--id mac`, then run:

```sh
python3 install_mac.py --config ~/.local/state/bose-control/config.json
```

This installs `~/Applications/Bose Connections.app` and a per-user LaunchAgent
`local.bose.connections`. The background helper adds a headphones icon to the menu
bar; click it for the compact popover (right-click for the native menu, whose first item
**Use on this Mac** moves the headphones here and offers **Replace <device>** when both
slots are busy), which opens the full dashboard. Allow Bluetooth when macOS asks.
IOBluetooth calls run on the Python main thread under the native app for proper
privacy attribution. Running the backend directly through SSH is not equivalent.

### Optional Tailscale relay

Use each controller's actual Tailscale IPv4 address. The addresses below are **illustrative placeholders**, not real device addresses.
Replace every headset, adapter and Tailscale address with your own:

```sh
python3 configure.py --id pc --headset AA:BB:CC:DD:EE:FF \
  --bind 100.64.0.1 --peer mac=100.64.0.2 --peer phone=100.64.0.3 \
  --role pc=11:22:33:44:55:66 --role mac=22:33:44:55:66:77 \
  --role phone=33:44:55:66:77:88
```

The first config generates a random token without printing it. Transfer a copy
privately to another machine and use `--token-from /private/path/config.json` when
creating that machine's config; swap its ID, bind address and peer list. Keep all
configs private. Do not put them in this repo. Settings can identify controller
roles from the headset's saved-device list.

Dashboard: loopback port **8847**, with Host/Origin checks. Mesh: configured
Tailscale IPv4 port **8848**, tailnet source checks and shared bearer token.
HTTP is used inside Tailscale's encrypted network; there is no public server or
cloud API. Do not expose these listeners through public port forwarding.

### Linux top-bar popup (Omarchy)

The widget uses Omarchy's Quickshell plugin system. Start the Python helper at
login using your preferred user service, then copy `linux/` to
`~/.config/omarchy/plugins/local.bose/`. Validate and enable it:

```sh
omarchy plugin validate ~/.config/omarchy/plugins/local.bose
omarchy plugin enable local.bose right
```

Back up your shell config before layout changes. Copy the whole `linux/` folder:
it holds several QML files and a `fonts/` directory. Click the headphones icon to
open the popup. Two slot cups show the connected devices, each with Disconnect;
saved devices have Connect. When both slots are full, choose which device to
replace in place. The ANC switch and slider apply on release, and **Open dashboard**
opens a compact app window through `omarchy-launch-webapp`. Colours follow the
active Omarchy theme. The same backend protections apply to popup and
dashboard actions. Other Linux desktops can use the web dashboard; a generic
system-tray implementation is not included.

On Linux, preparing a connection briefly enables BlueZ discovery for up to 30
seconds and restores the previous setting, allowing incoming connections to a
powered but non-connectable adapter. Status checks do not dial disconnected PC/Mac
hosts. Actions select the first eligible controller and always check actual headset
state before changing connections. Linux requires the `busctl` utility (systemd);
`adapter` in private config defaults to `hci0` for the paired headset.

## Android

Requires Android 8+; build target is Android 15 (API 35). Install JDK 17+ and the
Android SDK platform 35/build-tools. Set `ANDROID_HOME`, then run:

```sh
python3 build_android.py
adb install -r dist/bose-connections.apk
```

This builds a personally signed, debuggable APK. Signing material stays in your
private state directory; preserve it for compatible updates. No credentials or
headset address are embedded in the APK. No prebuilt APK release is published yet.

Open **Bose Connections** and allow Nearby devices and notifications. In Settings
→ Set up controller links, enter the paired headset's Bluetooth address. For relay,
enter the private token and PC/Mac Tailscale addresses; those fields may be left
empty for phone-only Bluetooth access.

Alternatively, create a private config with `configure.py --id phone` and
provision it into the installed app's `files/config.json` using Android `run-as`.
The app's foreground service listens on its detected Tailscale interface while
running and retains a notification. No boot receiver is installed. VPN rebinding,
screen-off behavior and direct Bluetooth control remain experimental.

### Android Quick Settings

Add **Bose** using the Quick Settings panel's edit button after installation. One
tap moves the headphones to this phone: the subtitle shows "Connecting…" at once, then
"Playing on Bose 700" or the reason (with " · tap to retry"). If both slots are busy the
tile says so and opens the compact panel with the replacement choice already asked
(a tile cannot show two buttons). The panel also has connect/disconnect, ANC level and
Off controls, sharing the app's private config and cached state. A locked phone must be
unlocked first. Long-press opens the app.

The app and tile share `Core.switchHere` (rules and texts in `tests/switch-contract.json`,
logic in `android/Switcher.java`): already connected is a success with no command; a
connect that is not confirmed is resent once after a fresh read; 150 s is the deadline;
one `bose.switch …` line per request goes to logcat tag `BoseSwitch` (roles only, no
addresses). The in-app web page reaches it as `/api/switch` through the same
`Android.request` bridge as every other call, with the controller's reply shape.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The 44 protocol/controller tests use simulated transports and have no hardware
side effects. They cover packet fragmentation, rejected commands, slot/anchor
protection, mutation verification, ambiguous-command handling and private cache
persistence, ANC handling and avoiding competing background connections. CI runs them on Python 3.12 and 3.13.

`tests/test_android_contract.py` compiles `android/Switcher.java` with a test-only
`org.json` stand-in and runs every scenario of `tests/switch-contract.json` against a
fake headset (skipped without a JDK); `tests/test_mac_contract.py` statically checks that
`mac/Launcher.m` posts `/api/switch` with the contract body and texts.

For GUI checks, start the local helper, install Node dependencies (`npm install`)
and Chromium, then run `npm run test:gui`. Set `CHROMIUM_PATH` or `BOSE_URL` if
needed. The runner intercepts API responses with synthetic data and verifies
mobile/desktop layouts, settings and the replacement dialog. It creates ignored
screenshots under `artifacts/`; it sends no connection mutations. Set
`SCREENSHOT_SCALE=2` for 2x captures, as used for the images above. The design
system is described in [DESIGN.md](DESIGN.md).

## Remove

- Linux: stop your helper service; disable/remove the `local.bose` plugin.
- Mac: unload/remove `~/Library/LaunchAgents/local.bose.connections.plist` and
  remove `~/Applications/Bose Connections.app`.
- Android: stop the relay in controller-link settings or uninstall the app.

Retain private configuration/signing files if reinstalling. The controller does
not delete pairings or update firmware. ANC settings change only on explicit actions.

## License and credits

GPL-3.0; see [LICENSE](LICENSE). BMAP protocol references and the vendored MIT Mac
transport are credited in [THIRD_PARTY.md](THIRD_PARTY.md), with revisions in
[upstream-revisions.json](upstream-revisions.json).
