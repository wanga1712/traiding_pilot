# Runtime host map V2

This is the current network authority as of 2026-09-22. S13 (`s13`, user
`sergey`, Tailscale `100.113.185.90`) is the compute and UI host. S7 (`s7`,
user `wanga`, Tailscale `100.80.226.124`) is the market-data and PostgreSQL
authority. The canonical workstation SSH config is
`C:\Users\Lenovo\Documents\customization_windows\ssh-config-s7-s13.conf`.

Use the aliases with that config and begin each connection with
`hostname; whoami; pwd`. The workstation key is `~/.ssh/id_vpn_home`. From
S13 to S7, the verified existing route uses `/home/sergey/.ssh/id_to_nyx` and
`wanga@s7`; no key material is recorded here.

Both nodes report `RouteAll=false` and no exit node. The old 10.8.x addresses,
Amnezia, and `mint-vpn` are historical references only. Runtime defaults use
`wanga@s7` and `sergey@s13` so Tailscale DNS remains the source of truth.
