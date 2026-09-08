#!/usr/bin/env python3
"""Quick probe of repair-2 acceptance progress."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ART = Path(
    os.environ.get(
        "COMPOSITE_SIGNAL_SEARCH_ARTIFACT_ROOT",
        "/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
    )
)
pid_path = ART / "_repair2.pid"
ck = ART / "composite_execution_checkpoint_v1.json"
log = ART / "_repair2_acceptance.log"

for i in range(6):
    print(f"---{i+1}---", flush=True)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)
    if pid_path.exists():
        pid = pid_path.read_text().strip()
        rss = "?"
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss = line.split()[1]
                        break
            alive = os.path.exists(f"/proc/{pid}")
        except OSError:
            alive = False
        print(f"pid={pid} alive={alive} rss_kb={rss}", flush=True)
    if ck.exists():
        d = json.loads(ck.read_text())
        ids = d.get("completed_composite_ids") or []
        print(
            f"n_completed={d.get('n_completed')} next={d.get('next_candidate_index')} "
            f"parts={d.get('next_result_part')} updated={d.get('updated_at')}",
            flush=True,
        )
        if ids:
            print("last=", ids[-1], flush=True)
    if log.exists():
        lines = log.read_text(errors="replace").strip().splitlines()
        print("log_tail=", lines[-1] if lines else "", flush=True)
    # acceptance summary if present
    for name in (
        "repair2_acceptance_summary_v1.json",
        "stratified_memory_smoke_acceptance_v1.json",
        "composite_old_new_parity_summary_v1.json",
    ):
        p = ART / name
        if p.exists():
            print(f"found {name}", flush=True)
    time.sleep(30)

print("DONE_PROBE", flush=True)
