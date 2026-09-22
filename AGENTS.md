# Project operating rules

Read `docs/architecture/TRADING_PROJECT_HANDOFF_V2.md`, `RUNTIME_HOST_MAP_V2.md`,
`CURRENT_RESEARCH_STATE_V2.md`, and `OPERATIONS_RUNBOOK_V2.md` first. V1 documents
are historical evidence and remain available for provenance only.
Read `ROADMAP.md` for research governance. These instructions apply to Codex,
Antigravity, Cursor, and future IDE agents.

- Never confuse S13 and S7: S13 is compute/research/model/UI and disposable cache;
  S7 is the source of truth for market data, storage, and PostgreSQL.
- Begin every SSH connection with `hostname`, `whoami`, `pwd`; verify the expected
  identity and stop on mismatch. Never guess credentials or output secrets.
- Historical data flows exchange -> S7 -> S13. Do not collect historical data
  directly from exchanges onto S13.
- Git is implementation authority. Reconcile runtime hashes with committed Git.
  Never overwrite unexplained runtime drift or create an S13-only production fix.
- Never open OOS without an explicit WIP. Never change frozen research methodology
  after seeing results. DEVELOPMENT findings are not profitability evidence.
- One ACTIVE primary WIP at a time. REVIEW requires independent review/user
  acceptance before CLOSED. Never launch the next WIP automatically.
- The composite compose is complete. Never rerun compose/compose-bounded/all/atomic
  for this completed run. Preserve checkpoints, parts, shards, units, and logs.
- Shared-host finalization limits are MemoryHigh=10G and MemoryMax=12G; monitor RSS.
  Do not inherit the obsolete compose service's 16G/18G resource override.
