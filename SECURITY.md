# Security

Keep controller configuration, tokens, snapshots and Android signing keys outside
the repository. The mesh token grants connection-control access to every linked
controller. Use your own trusted Tailscale devices; do not publish or forward the
HTTP listeners. The desktop GUI is loopback-only; mesh requests require a bearer
token and a tailnet source address. Android is a personal debug build, not a
hardened app-store release.

The cache is a last-known display snapshot. All mutations reread and verify actual
headset state. The backend preserves a known control device where possible and
never retries an ambiguous mutation through a different peer.

Report a security issue privately through GitHub's vulnerability reporting for
this repository. Do not include tokens, private configs or device snapshots in
public issues.
