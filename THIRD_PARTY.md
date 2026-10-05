# Protocol sources

The packet implementation in `protocol.py` and `android/Core.java` is based on
published Bose BMAP DeviceManagement packets in these projects:

- [Denton-L/based-connect](https://github.com/Denton-L/based-connect), vendored
  through [bosefirmware's fork](https://github.com/bosefirmware/BoseConnect-Linux_based-connect),
  GPL-3.0. Preserve its license when redistributing derived implementations.
- [aaronsb/bosectl](https://github.com/aaronsb/bosectl), MIT. The Mac transport
  directly imports the vendored `pybmap.transport` module. Preserve its MIT license.

This controller is distributed under GPL-3.0; see LICENSE. The Mac transport
retains its MIT license at vendor/bosectl/LICENSE.
Upstream does not claim verified NC700 connection-list support. This controller
has now verified NC700 reads and phone disconnect/reconnect on one NC700 headset;
other platforms/scenarios still require their own validation. The vendored Mac
transport has a local patch that skips a new baseband callback wait for a device
that is already connected. The patch also skips fixed SDP/startup delays for
connected devices and waits briefly for asynchronous channel close.
The upstream revisions are recorded in upstream-revisions.json. Only the
MIT Python package is included; the GPL protocol reference is linked above.
No Bose firmware, account login, or cloud authentication is used or modified.

NC700 noise-control packet layout (Settings/CNC 1.5, inverted 0–10 level
and enabled flag) is documented by [danielgjackson/noisecancel](https://github.com/danielgjackson/noisecancel), MIT. Packet handling is independently implemented here.
