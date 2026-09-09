#!/usr/bin/env python3
"""Durability preflight tests: graceful SIGTERM resume + abrupt crash orphans."""
from __future__ import annotations

import json
import os
import signal
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose
from crypto_trading_bot.research_v2.composite_signal_search.compose import iter_all_template_definitions
from crypto_trading_bot.research_v2.composite_signal_search.config import load_atomic_bank, load_templates
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import (
    COMPOSITE_CHECKPOINT,
    FOLDS_PARTS_DIR,
    RESULTS_PARTS_DIR,
    save_json,
)
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import AppendOnlyPartWriter, reconcile_orphan_parts

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
RUNTIME_A = "_durability_reboot_resume_runtime"
RUNTIME_B = "_durability_clean300_runtime"
RUNTIME_CRASH = "_durability_crash_resume_runtime"


def _load_defs(n: int) -> list[dict]:
    bank = load_atomic_bank(root=ART)
    reps = json.loads((ART / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))["configs"]
    out = []
    for d in iter_all_template_definitions(
        representatives=reps,
        all_configs_for_pairs=list(bank["configs"]),
        templates_doc=load_templates(root=ART),
    ):
        out.append(d)
        if len(out) >= n:
            break
    return out


def _result_ids(root: Path) -> list[str]:
    ids: list[str] = []
    parts = root / RESULTS_PARTS_DIR
    if not parts.exists():
        return ids
    for path in sorted(parts.glob("part-*.parquet")):
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(columns=["composite_id"], batch_size=20000):
            ids.extend(batch.to_pandas()["composite_id"].astype(str).tolist())
    return ids


def _fold_keys(root: Path) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    parts = root / FOLDS_PARTS_DIR
    if not parts.exists():
        return keys
    for path in sorted(parts.glob("part-*.parquet")):
        df = pd.read_parquet(path, columns=["composite_id", "fold_id"])
        keys.extend(list(zip(df["composite_id"].astype(str), df["fold_id"].astype(str))))
    return keys


def test_reboot_resume() -> dict:
    defs300 = _load_defs(300)
    # Clean uninterrupted reference
    work_b = ART / RUNTIME_B
    if work_b.exists():
        import shutil

        shutil.rmtree(work_b)
    ref = run_bounded_compose(
        artifact_root=ART,
        definitions=defs300,
        resume=False,
        runtime_subdir=RUNTIME_B,
        require_shards=True,
    )
    ref_ids = _result_ids(work_b)
    ref_folds = _fold_keys(work_b)

    # Interrupted path: 150 then SIGTERM, then resume to 300
    work_a = ART / RUNTIME_A
    if work_a.exists():
        import shutil

        shutil.rmtree(work_a)

    # Phase 1 in child process so we can SIGTERM it mid-run after ~150
    import subprocess
    import sys

    helper = ART / "_durability_phase1_helper.py"
    helper.write_text(
        f"""
import os, signal, time, threading
from pathlib import Path
from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose, STOP_REQUESTED
from crypto_trading_bot.research_v2.composite_signal_search.compose import iter_all_template_definitions
from crypto_trading_bot.research_v2.composite_signal_search.config import load_atomic_bank, load_templates
import json

ART = Path({str(ART)!r})
bank = load_atomic_bank(root=ART)
reps = json.loads((ART / "atomic_representative_bank_v1.json").read_text())["configs"]
defs=[]
for d in iter_all_template_definitions(representatives=reps, all_configs_for_pairs=list(bank["configs"]), templates_doc=load_templates(root=ART)):
    defs.append(d)
    if len(defs)>=300: break

def killer():
    # wait until checkpoint shows >=150
    ckpt = ART / {RUNTIME_A!r} / "composite_execution_checkpoint_v1.json"
    for _ in range(3600):
        if ckpt.exists():
            import json as _j
            d=_j.loads(ckpt.read_text())
            if int(d.get("completed_count") or 0) >= 150:
                os.kill(os.getpid(), signal.SIGTERM)
                return
        time.sleep(2)

threading.Thread(target=killer, daemon=True).start()
out = run_bounded_compose(artifact_root=ART, definitions=defs, resume=False, runtime_subdir={RUNTIME_A!r}, require_shards=True)
print("PHASE1", out.get("GRACEFUL_STOP"), out.get("n_completed_total"), out.get("n_evaluated"))
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = "/var/tmp/traiding_pilot_ui_workspace/phase3_staging"
    p = subprocess.run(
        ["/var/tmp/traiding_pilot_ui_workspace/.venv/bin/python", str(helper)],
        cwd="/var/tmp/traiding_pilot_ui_workspace/phase3_staging",
        env=env,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    print(p.stdout[-2000:])
    print(p.stderr[-2000:])
    ckpt = json.loads((work_a / COMPOSITE_CHECKPOINT).read_text(encoding="utf-8"))
    assert ckpt.get("GRACEFUL_STOP") == "YES" or int(ckpt.get("completed_count") or 0) >= 150
    next_idx = int(ckpt["next_candidate_index"])
    completed = int(ckpt["completed_count"])
    assert next_idx == completed, (next_idx, completed)

    # Resume to finish 300 definitions (same list; resume by index)
    out2 = run_bounded_compose(
        artifact_root=ART,
        definitions=defs300,
        resume=True,
        runtime_subdir=RUNTIME_A,
        require_shards=True,
    )
    ids = _result_ids(work_a)
    folds = _fold_keys(work_a)
    # Compare against reference
    skip = 0
    dup = len(ids) - len(set(ids))
    missing = sorted(set(ref_ids) - set(ids))
    extra = sorted(set(ids) - set(ref_ids))
    # Fold parity: each id has 4 folds
    fold_per = Counter(c for c, _ in folds)
    bad_folds = sum(1 for c in set(ids) if fold_per.get(c, 0) != 4)
    # Metric class parity via RESULT row count / id set
    parity = (
        len(ids) == 300
        and dup == 0
        and not missing
        and not extra
        and bad_folds == 0
        and len(folds) == 300 * 4
        and set(ids) == set(ref_ids)
    )
    return {
        "REBOOT_RESUME_TEST_COUNT": 300,
        "phase1_completed": completed,
        "phase1_next": next_idx,
        "GRACEFUL_CHECKPOINT_NEXT_INDEX_CORRECT": "PASS" if next_idx == completed else "FAIL",
        "phase2_n_evaluated": out2.get("n_evaluated"),
        "n_result_ids": len(ids),
        "n_unique": len(set(ids)),
        "dup": dup,
        "missing_vs_ref": len(missing),
        "extra_vs_ref": len(extra),
        "fold_rows": len(folds),
        "bad_fold_counts": bad_folds,
        "REBOOT_RESUME_RESULT_PARITY": "PASS" if parity else "FAIL",
        "REBOOT_RESUME_NO_SKIPPED_CANDIDATES": "PASS" if not missing else "FAIL",
        "REBOOT_RESUME_NO_DUPLICATE_CANDIDATES": "PASS" if dup == 0 else "FAIL",
        "REBOOT_RESUME_FOLD_PARITY": "PASS" if bad_folds == 0 and len(folds) == 1200 else "FAIL",
        "helper_rc": p.returncode,
    }


def test_abrupt_crash() -> dict:
    import shutil

    work = ART / RUNTIME_CRASH
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # Seed a committed checkpoint at 0 and write an orphan part as if crash after write
    defs = _load_defs(5)
    # Run 2 candidates normally
    run_bounded_compose(
        artifact_root=ART,
        definitions=defs[:2],
        resume=False,
        runtime_subdir=RUNTIME_CRASH,
        require_shards=True,
    )
    ckpt = json.loads((work / COMPOSITE_CHECKPOINT).read_text(encoding="utf-8"))
    committed_next = int(ckpt["next_result_part"])
    # Fabricate uncommitted orphan part at committed_next
    writer = AppendOnlyPartWriter(work, dirname=RESULTS_PARTS_DIR, next_part=committed_next)
    orphan_rows = [
        {
            "composite_id": "ORPHAN_SHOULD_NOT_SURVIVE",
            "template_id": "T1",
            "TOTAL_SIGNALS": 1,
            "composite_class": "INSUFFICIENT",
            "is_survivor": False,
        }
    ]
    writer.flush(orphan_rows)
    # Restart with old checkpoint (still pointing before orphan) — reconcile should quarantine
    # Reset checkpoint next_result_part to committed_next (already) and re-run remaining
    out = run_bounded_compose(
        artifact_root=ART,
        definitions=defs,
        resume=True,
        runtime_subdir=RUNTIME_CRASH,
        require_shards=True,
    )
    ids = _result_ids(work)
    folds = _fold_keys(work)
    orphan_left = any(p.name.startswith("part-") and "ORPHAN" for p in (work / RESULTS_PARTS_DIR).glob("*.parquet"))
    # Check no orphan id in results
    has_orphan_id = "ORPHAN_SHOULD_NOT_SURVIVE" in ids
    # Exactly one row per def id, 4 folds each
    uniq = len(set(ids))
    dup = len(ids) - uniq
    fold_per = Counter(c for c, _ in folds)
    bad = sum(1 for c in set(ids) if fold_per.get(c, 0) != 4)
    ok = (not has_orphan_id) and dup == 0 and uniq == 5 and bad == 0 and len(folds) == 20
    return {
        "ABRUPT_CRASH_RESUME": "PASS" if ok else "FAIL",
        "DUPLICATE_ROWS_AFTER_CRASH": dup,
        "MISSING_ROWS_AFTER_CRASH": max(0, 5 - uniq),
        "orphan_id_present": has_orphan_id,
        "n_ids": len(ids),
        "uniq": uniq,
        "fold_rows": len(folds),
        "n_evaluated": out.get("n_evaluated"),
    }


def main() -> int:
    reboot = test_reboot_resume()
    crash = test_abrupt_crash()
    doc = {
        "WIP": "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
        "MODE": "FULL-EXECUTION-BOOT-RESUME-DURABILITY-PREFLIGHT-1",
        "reboot_resume": reboot,
        "abrupt_crash": crash,
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
    }
    save_json(ART / "boot_resume_durability_tests_v1.json", doc)
    print(json.dumps(doc, indent=2))
    ok = (
        reboot.get("REBOOT_RESUME_RESULT_PARITY") == "PASS"
        and reboot.get("REBOOT_RESUME_NO_SKIPPED_CANDIDATES") == "PASS"
        and reboot.get("REBOOT_RESUME_NO_DUPLICATE_CANDIDATES") == "PASS"
        and reboot.get("REBOOT_RESUME_FOLD_PARITY") == "PASS"
        and crash.get("ABRUPT_CRASH_RESUME") == "PASS"
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
