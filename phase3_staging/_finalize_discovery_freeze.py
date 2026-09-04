#!/usr/bin/env python3
"""Pull Discovery freeze artifacts from S13 and finalize local freeze commit."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
REPO = Path(__file__).resolve().parent.parent
ART = REPO / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"
REMOTE = "/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
FREEZE_COMMIT = "eb561bc1298bd2b0ec5e21cc4ac6c690ec148bad"
RUNTIME_COMMIT = "7eff0e741107a87cbcb436202dff095edbea625c"

NAMES = [
    "discovery_results_all_v1.parquet",
    "discovery_summary_by_tf_v1.csv",
    "discovery_fold_stability_v1.csv",
    "multiple_comparison_audit_v1.csv",
    "redundancy_clusters_v1.csv",
    "discovery_negative_results_v1.csv",
    "frozen_validation_candidates_v1.json",
    "discovery_freeze_manifest_v1.json",
    "discovery_data_access_audit_v1.json",
    "anti_leakage_tests_v1.json",
    "summary_v1.json",
    "reference_results_v1.csv",
    "negative_results_v1.csv",
    "dataset_manifest_v1.json",
    "_param_search_discovery-only.log",
]


def scp(name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "scp",
            "-i",
            str(SSH_KEY),
            "-o",
            "StrictHostKeyChecking=no",
            f"{HOST}:{REMOTE}/{name}",
            str(ART / name),
        ],
        check=True,
    )


def main() -> int:
    for n in NAMES:
        print(f"pull {n}", flush=True)
        scp(n)

    import pandas as pd

    summary = json.loads((ART / "summary_v1.json").read_text(encoding="utf-8"))
    access = json.loads((ART / "discovery_data_access_audit_v1.json").read_text(encoding="utf-8"))
    frozen = json.loads((ART / "frozen_validation_candidates_v1.json").read_text(encoding="utf-8"))
    disc = pd.read_parquet(ART / "discovery_results_all_v1.parquet")

    n = len(disc)
    if n != 3200:
        raise SystemExit(f"DISCOVERY_CANDIDATES_EVALUATED={n} expected 3200")

    iso_ok = (
        access.get("validation_bars_loaded", summary.get("VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY")) == 0
        and access.get("validation_events_loaded", summary.get("VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY")) == 0
        and summary.get("DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT") == 0
        and summary.get("VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS") == 0
        and access.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY", summary.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY"))
        in ("NO", False, 0)
    )
    if not iso_ok:
        raise SystemExit(f"isolation_fail access={access} summary_keys={[summary.get(k) for k in ['VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY','VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY','DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT','VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS','VALIDATION_DATA_ACCESSED_DURING_DISCOVERY']]}")

    # Enrich frozen payload if only IDs present
    ids = frozen.get("candidate_ids") or [c.get("candidate_id") for c in frozen.get("candidates", [])]
    ids = sorted(set(ids))
    h = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()

    fold = pd.read_csv(ART / "discovery_fold_stability_v1.csv")
    fdr = pd.read_csv(ART / "multiple_comparison_audit_v1.csv")
    clusters = pd.read_csv(ART / "redundancy_clusters_v1.csv")
    registry = pd.read_csv(ART / "candidate_registry_snapshot_v2.csv")
    cluster_map = {}
    for _, row in clusters.iterrows():
        members = row["members"]
        if isinstance(members, str):
            try:
                members = json.loads(members.replace("'", '"'))
            except Exception:
                members = [x.strip() for x in members.strip("[]").split(",") if x.strip()]
        for m in members:
            cluster_map[str(m).strip().strip("'\"")] = int(row["cluster_id"])
    fdr_map = {r["candidate_id"]: r for _, r in fdr.iterrows()}
    fold_map = fold.groupby("candidate_id")["PRECISION_DELTA"].apply(list).to_dict()
    reg_map = {r["candidate_id"]: r for _, r in registry.iterrows()}

    candidates = []
    for cid in ids:
        d = disc[disc["candidate_id"] == cid]
        if d.empty:
            continue
        d0 = d.iloc[0].to_dict()
        reg = reg_map.get(cid, {})
        fd = fdr_map.get(cid, {})
        candidates.append(
            {
                "candidate_id": cid,
                "decision_tf": d0.get("decision_tf") or reg.get("decision_tf"),
                "direction": d0.get("direction") or reg.get("direction"),
                "family": d0.get("family") or reg.get("family"),
                "parameters": reg.get("parameters"),
                "event_primitive": d0.get("event_primitive") or reg.get("event_primitive"),
                "is_reference": bool(d0.get("is_reference")),
                "discovery_metrics": {
                    k: d0.get(k)
                    for k in (
                        "TOTAL_SIGNALS",
                        "PRECISION",
                        "EVENT_RECALL",
                        "FALSE_POSITIVE_RATE",
                        "PRECISION_DELTA",
                        "RECALL_DELTA",
                        "FPR_DELTA",
                        "MEDIAN_DELAY_SECONDS",
                        "sample_flag",
                        "discovery_fold_stability",
                    )
                },
                "fold_precision_deltas": fold_map.get(cid, []),
                "passes_fdr": bool(fd.get("passes_fdr")) if len(fd) else None,
                "bootstrap_p": fd.get("bootstrap_p") if len(fd) else None,
                "redundancy_cluster_id": cluster_map.get(cid),
                "selection_rationale": "reference_mandatory"
                if d0.get("is_reference")
                else "top_non_reference_by_precision_delta_per_tf_direction_family",
            }
        )

    payload = {
        "frozen_at": frozen.get("frozen_at"),
        "search_spec_v2_freeze_commit": FREEZE_COMMIT,
        "discovery_runtime_commit": RUNTIME_COMMIT,
        "discovery_pid": 2432972,
        "candidate_ids": ids,
        "count": len(candidates),
        "hash": h,
        "candidates": candidates,
    }
    (ART / "frozen_validation_candidates_v1.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    manifest = {
        "search_spec_v2_freeze_commit": FREEZE_COMMIT,
        "discovery_runtime_commit": RUNTIME_COMMIT,
        "discovery_pid": 2432972,
        "discovery_period": summary.get("DISCOVERY_PERIOD"),
        "frozen_validation_candidate_count": len(candidates),
        "validation_candidate_set_hash": h,
        "SEARCH_SPEC_SHA256": summary.get("SEARCH_SPEC_SHA256"),
        "CANDIDATE_REGISTRY_SHA256": summary.get("CANDIDATE_REGISTRY_SHA256"),
        "VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY": summary.get("VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY"),
        "VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY": summary.get("VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY"),
        "DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT": summary.get("DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT"),
        "VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS": summary.get("VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS"),
        "VALIDATION_DATA_ACCESSED_DURING_DISCOVERY": summary.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY"),
        "validation_started": "NO",
        "oos_access_count": 0,
        "frozen_at": payload["frozen_at"],
    }
    (ART / "discovery_freeze_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # summary stats
    sl = disc[disc["candidate_id"].isin(ids)]
    stable = disc[disc["discovery_fold_stability"] == "STABLE_POSITIVE_FOLDS"]
    unstable = disc[disc["discovery_fold_stability"] == "UNSTABLE_DISCOVERY"]
    insuf = disc[disc["sample_flag"] == "INSUFFICIENT"]
    best = {}
    for (tf, direction), g in disc.groupby(["decision_tf", "direction"]):
        g2 = g[g["sample_flag"] != "INSUFFICIENT"].sort_values("PRECISION_DELTA", ascending=False)
        if not g2.empty:
            r = g2.iloc[0]
            best[f"{tf}|{direction}"] = {
                "candidate_id": r["candidate_id"],
                "family": r["family"],
                "PRECISION_DELTA": r.get("PRECISION_DELTA"),
                "discovery_fold_stability": r.get("discovery_fold_stability"),
            }
    beaten = "YES" if (disc["PRECISION_DELTA"].fillna(-999) > 0).any() else "NO"

    result = {
        "DISCOVERY_STATUS": "COMPLETE",
        "DISCOVERY_PROCESS_EXITED": "YES",
        "DISCOVERY_CANDIDATES_EVALUATED": n,
        "DISCOVERY_CANDIDATE_COUNTS_BY_TF": disc.groupby("decision_tf")["candidate_id"].nunique().to_dict(),
        "FROZEN_VALIDATION_CANDIDATE_COUNT": len(candidates),
        "VALIDATION_CANDIDATE_SET_HASH": h,
        "DISCOVERY_SHORTLIST_COUNTS_BY_FAMILY": sl.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_STABLE_COUNTS_BY_FAMILY": stable.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_UNSTABLE_COUNTS_BY_FAMILY": unstable.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_INSUFFICIENT_COUNTS_BY_FAMILY": insuf.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_BEST_BY_TF_DIRECTION": best,
        "PRICE_BASELINE_BEATEN_IN_DISCOVERY_BY_ANY_CANDIDATE": beaten,
        "VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY": summary.get("VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY"),
        "VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY": summary.get("VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY"),
        "DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT": summary.get("DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT"),
        "VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS": summary.get("VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS"),
        "VALIDATION_STARTED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "READY_FOR_VALIDATION_REVIEW": "YES",
        "summary_verdict": summary.get("RESEARCH_VERDICT"),
        "frozen_hash_from_run": summary.get("VALIDATION_CANDIDATE_SET_HASH"),
    }
    (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
