# Runtime host map V1

Verified 2026-09-21. Exact machine-readable fields and verification limits are in
`runtime_host_map_v1.json`.

| Field | S13 | S7 |
|---|---|---|
| Role | Compute, research, backtest, UI, disposable cache | Canonical data, storage, PostgreSQL |
| IP | 10.8.0.13 | 10.8.0.7 |
| SSH user | sergey | wanga |
| Hostname | sergey-System-Product-Name | nyx |
| Route | Windows alias `mint-vpn` | From S13: `ssh -i /home/sergey/.ssh/id_to_nyx wanga@10.8.0.7` |
| Workspace/data root | /var/tmp/traiding_pilot_ui_workspace | /srv/traiding_pilot |
| Code root | /var/tmp/traiding_pilot_ui_workspace/phase3_staging | Not used for composite compute |
| Artifact root | /var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1 | Canonical data retained on S7 |
| Python | /var/tmp/traiding_pilot_ui_workspace/.venv/bin/python | Not used for finalization |
| Market path | /var/tmp/traiding_pilot_market_cache | /srv/traiding_pilot/market/binance/spot/ETHUSDT/1m |

The separate S13 Git checkout `/opt/traiding_pilot` was at
`d320702a55d219efab6d4e39271f1b0e7ff1f1af`, branch
`wip/dinapoli-rolling-geometry-eth-1`, with a deleted tracked JS file and an
untracked geometry test. It remains untouched. Deployed code has no `.git` and is
reconciled using module hashes against GitHub main.

The completed worker is `multitf-composite-search.service`, using
`/usr/local/bin/multitf-composite-search-run.sh`. Its base unit is in
`/etc/systemd/system/`; the existing `50pct-compute-today.conf` override gave it
16G/18G limits. It is audit evidence, not the approved finalization policy.
Finalization used `multitf-composite-finalize-repaired-20260921.service` with
MemoryHigh=10G, MemoryMax=12G, CPUQuota=200%, Restart=no.

S7 PostgreSQL 17/main is online on port 5432. Runtime annotation configuration
defaults to SSH host `wanga@10.8.0.7` and database `traiding_pilot`.
`SELECT current_database(), current_user` through the administrative audit route
returned `traiding_pilot|postgres`. The live application's database role was not
independently established, so POSTGRES_DETAIL_VERIFIED=PARTIAL. No password or
secret connection URI is included.

Canonical historical direction: exchange -> S7 -> S13. S13 is not the historical
collection authority. Never use `sergey@10.8.0.7` as the canonical S7 identity.
