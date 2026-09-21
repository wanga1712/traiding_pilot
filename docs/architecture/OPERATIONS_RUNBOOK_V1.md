# Operations runbook V1

Use the verified identities below. Stop if any identity differs. Paths and key
paths are not credentials; never display or copy private key contents.

## Read-only commands

From the verified Windows SSH configuration:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes mint-vpn 'hostname; whoami; pwd'
```

Expected: `sergey-System-Product-Name`, `sergey`, `/home/sergey`.
The alias points to `sergey@10.8.0.13` using the configured `id_vpn_home` key.
On S13, after identity verification:

```sh
git -C /opt/traiding_pilot rev-parse --show-toplevel
git -C /opt/traiding_pilot rev-parse HEAD
git -C /opt/traiding_pilot status --short
systemctl show multitf-composite-search.service -p ActiveState -p SubState -p UnitFileState -p Restart -p MemoryHigh -p MemoryMax
systemctl cat multitf-composite-search.service
journalctl -u multitf-composite-search.service --no-pager -n 30
cat /var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1/composite_execution_checkpoint_v1.json
cat /var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1/composite_finalization_status_v1.json
cat /var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1/composite_search_DONE
```

The `/opt` Git checkout is separate from the deployed source and was dirty at
takeover. Do not reset it. Compare deployed module SHA256 values against the
committed runtime reconciliation instead.

From S13, connect to S7:

```sh
ssh -i /home/sergey/.ssh/id_to_nyx -o BatchMode=yes -o StrictHostKeyChecking=yes wanga@10.8.0.7 'hostname; whoami; pwd'
```

Expected: `nyx`, `wanga`, `/home/wanga`. Then on S7:

```sh
ls -ld /srv/traiding_pilot/market/binance/spot/ETHUSDT/1m
pg_lsclusters
systemctl is-active postgresql
sudo -n -u postgres psql -d traiding_pilot -Atc 'SELECT current_database(), current_user;'
```

This query checks metadata only. Do not read locked OOS market rows. PostgreSQL
17/main listens on 5432; the audit query role is `postgres`. The live application
role remains only partially verified; do not invent a password or connection URI.

## Mutating commands — require ACTIVE WIP

The completed composite WIP is in REVIEW. Do not run the following merely to
resume an IDE session. Require a specifically authorized active repair WIP or
explicit user authorization, and repeat all fail-closed integrity gates.

The only permitted finalization phase for this completed compose is:

```sh
cd /var/tmp/traiding_pilot_ui_workspace/phase3_staging
export COMPOSITE_SIGNAL_SEARCH_ARTIFACT_ROOT=/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1
export INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT=/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1
export PYTHONPATH=.
# Execute inside a dedicated systemd unit with MemoryHigh=10G, MemoryMax=12G,
# Restart=no, restricted CPU, captured logs, and monitored RSS.
/var/tmp/traiding_pilot_ui_workspace/.venv/bin/python -B -m crypto_trading_bot.research_v2.composite_signal_search.run_search --phase finalize-bounded
```

Do not use compose, compose-bounded, all, or atomic. The source result parts are
complete. Do not raise memory limits. Stop near unsafe RSS and repair the bounded
implementation in Git before redeployment. Never patch production only on S13.

After successful audits and publication, the completed-worker operation is:

```sh
sudo -n systemctl disable multitf-composite-search.service
systemctl is-active multitf-composite-search.service
systemctl is-enabled multitf-composite-search.service
```

Keep the unit, resource override, logs, checkpoints, result parts, and shards as
audit evidence. The DONE marker must name the results commit and survivor hash.
