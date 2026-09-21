# Trading project handoff V1

This is IDE-neutral project memory for Antigravity, Cursor, Codex, and future agents.
It records the 2026-09-21 takeover of `wanga1712/traiding_pilot` and the completed
DEVELOPMENT composite search. Consult the companion current-state file for exact
counts, hashes, result authority, and review status.

## Authority

Implementation authority is GitHub `origin/main`. At takeover it was exactly
`092103991a18d0044289def6b67c8774f195baf6`, matching the supplied handoff.
The clone's default branch was `master`; select `main` explicitly.
Frozen methodology is `476927817e21ef6869261a0114b27864fdf2d789`.
Implementation history includes `e6e663f` (performance/finalizer integrity),
`d0201b1e0d58afd419bbeef8e1c953200909ae2a` (boot/resume durability), and `0921039`
(full DEVELOPMENT execution authority).

The actual deployed source is a file deployment, without `.git`, at
`/var/tmp/traiding_pilot_ui_workspace/phase3_staging` on S13. A separate checkout
at `/opt/traiding_pilot` is on an older WIP branch with local changes; it was
preserved untouched. Do not infer deployed authority from that checkout's HEAD.
All 24 audited composite modules/wrappers initially matched main. The installed
wrapper and base unit matched their repository versions. An uncommitted resource
override raised the old compose service to 16G/18G; the finalizer used its own
10G/12G containment and did not inherit this override.

## Repairs and evidence

Two concrete reporting/finalization defects were reproduced and repaired:

1. `71ce2ecf6d53e8dd18c7edd073b5cc4eb963f39e` preserves IDs containing `|` in
   exact/near cluster lists, reconstructs legacy context lists from frozen IDs,
   runs exact dedup before near dedup, and preserves transitive aliases.
2. `b280bfa49a0337c541386f689f654b5002a7fe26` maps family reports through the
   frozen atomic bank instead of guessing family from an ID prefix.

Repairs were tested, committed, and pushed before deployment. Regression tests
and the full composite suite passed (46 tests after both repairs). No candidate,
threshold, fold, matching, or AVAILABLE_AT definition changed. Compose was not
rerun. The first finalizer attempt was stopped after the ID defect was found;
its partial outputs and previous source remain in the S13 audit directory.

Final output and survivor audits, runtime reconciliation, deployment evidence,
publication manifests, and reports live in
`artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1/`. Large canonical files remain on S13;
the Git publication contains deterministic gzip chunks with canonical and chunk
hashes, sizes, row counts, and schemas. Concatenating decompressed chunks in
manifest order reconstructs the exact canonical bytes.

## Infrastructure and governance

Read `RUNTIME_HOST_MAP_V1.md` and its JSON companion for verified host identities.
S7 owns canonical market data and PostgreSQL; S13 consumes it for research and UI.
Secrets are not project memory. Key paths are references only.

The composite WIP ends in REVIEW, not CLOSED. Independent review/user acceptance
is still required. `PROBABILITY-MODEL-TRAINING-DATASET-1` remains PLANNED. Do not
train models, open OOS, run a PnL simulator, or begin Bybit collection here.
