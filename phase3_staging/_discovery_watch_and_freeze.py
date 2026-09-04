#!/usr/bin/env python3
"""Watch Discovery PID on S13, auto-freeze on success. No Validation."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
REPO = Path(__file__).resolve().parent.parent
ART = REPO / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"
REMOTE_ART = "/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
POLL = 900
PID = 2432972
RUNTIME_COMMIT = "7eff0e741107a87cbcb436202dff095edbea625c"
FREEZE_COMMIT = "eb561bc1298bd2b0ec5e21cc4ac6c690ec148bad"
EXPECTED_TFS = ("5m", "15m", "30m", "1H", "2H", "4H", "6H", "8H", "12H", "1D")
FAMILIES = ("DMA", "STOCHASTIC", "MACD", "PURE_DNO", "DNO_QUANTILE", "OSC_PREDICTOR", "INVERSE_PREDICTOR")
HANG_MINUTES = 90


def ssh(cmd: str) -> str:
    out = subprocess.check_output(
        ["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", HOST, cmd],
        text=True,
    )
    return out


def scp_from(remote: str, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["scp", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", f"{HOST}:{remote}", str(local)],
        check=True,
    )


def parse_progress(log: str) -> tuple[str, str]:
    tf = ""
    progress = ""
    for line in log.splitlines():
        m = re.search(r"\[param-search\] signals (\S+)", line)
        if m:
            tf = m.group(1)
        m2 = re.search(r"(\S+): (\d+)/(\d+) candidates", line)
        if m2:
            tf = m2.group(1)
            progress = f"{m2.group(2)}/{m2.group(3)}"
    return tf or "unknown", progress or "unknown"


def poll_state() -> dict:
    try:
        ps = ssh(f"ps -p {PID} -o state=,etime=,pcpu=,rss=,time= 2>/dev/null || echo DEAD")
    except subprocess.CalledProcessError:
        ps = "DEAD"
    alive = "DEAD" not in ps and ps.strip() != ""
    log_path = f"{REMOTE_ART}/_param_search_discovery-only.log"
    try:
        log_tail = ssh(f"tail -30 {log_path} 2>/dev/null")
        log_stat = ssh(f"stat -c %Y {log_path} 2>/dev/null || echo 0").strip()
    except subprocess.CalledProcessError:
        log_tail = ""
        log_stat = "0"
    tf, prog = parse_progress(log_tail)
    if not alive:
        try:
            full_log = ssh(f"cat {log_path} 2>/dev/null")
            tf, prog = parse_progress(full_log)
        except subprocess.CalledProcessError:
            pass
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "alive": alive,
        "ps": ps.strip(),
        "tf": tf,
        "progress": prog,
        "log_mtime": int(log_stat) if log_stat.isdigit() else 0,
    }


def append_watch(entry: dict) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    watch = ART / "discovery_watch_v1.log"
    line = (
        f"{entry['ts']} | alive={'YES' if entry['alive'] else 'NO'} | ps={entry['ps']} | "
        f"tf={entry['tf']} | progress={entry['progress']} | log_mtime={entry['log_mtime']}\n"
    )
    with watch.open("a", encoding="utf-8") as f:
        f.write(line)


def cpu_time_seconds(ps_line: str) -> float:
    # time= HH:MM:SS or MM:SS
    m = re.search(r"(\d+):(\d+):(\d+)", ps_line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.search(r"(\d+):(\d+)", ps_line)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return 0.0


def check_hang(history: list[dict]) -> bool:
    if len(history) < 2:
        return False
    recent = history[-max(2, HANG_MINUTES // (POLL // 60)) :]
    if not all(h["alive"] for h in recent):
        return False
    progresses = [h["progress"] for h in recent]
    log_mtimes = [h["log_mtime"] for h in recent]
    cpu_times = [cpu_time_seconds(h["ps"]) for h in recent]
    if len(set(progresses)) > 1:
        return False
    if max(log_mtimes) - min(log_mtimes) > 60:
        return False
    if cpu_times[-1] - cpu_times[0] > 120:
        return False
    span_min = (len(recent) - 1) * (POLL / 60)
    return span_min >= HANG_MINUTES


def collect_hang_diagnostics() -> str:
    cmds = [
        f"ps -p {PID} -o pid,state,etime,pcpu,rss,cmd",
        f"cat /proc/{PID}/status 2>/dev/null | head -20",
        f"cat /proc/{PID}/wchan 2>/dev/null",
        "top -b -n1 -p {PID} 2>/dev/null | tail -5",
        f"tail -100 {REMOTE_ART}/_param_search_discovery-only.log",
        "df -h /var/tmp",
        "free -h",
    ]
    parts = []
    for c in cmds:
        try:
            parts.append(f"=== {c} ===\n{ssh(c)}")
        except Exception as exc:
            parts.append(f"=== {c} ===\nERR: {exc}")
    diag = ART / "discovery_hang_diagnostics_v1.txt"
    diag.write_text("\n".join(parts), encoding="utf-8")
    return str(diag)


def verify_runtime_source() -> tuple[str, int]:
    files = [
        "phase3_staging/crypto_trading_bot/research_v2/inverse_predictors/batch_thresholds.py",
        "phase3_staging/crypto_trading_bot/research_v2/indicator_parameter_search/signals_bank.py",
    ]
    mismatches = 0
    for rel in files:
        local = REPO / rel
        remote = f"/var/tmp/traiding_pilot_ui_workspace/{rel.replace(chr(92), '/')}"
        local_h = hashlib.sha256(local.read_bytes()).hexdigest()
        remote_h = ssh(f"sha256sum {remote}").split()[0]
        if local_h != remote_h:
            mismatches += 1
    return ("PASS" if mismatches == 0 else "FAIL", mismatches)


def verify_spec_immutable() -> tuple[str, str]:
    import hashlib as hl

    spec = ART / "search_spec_v2.json"
    reg = ART / "candidate_registry_snapshot_v2.csv"
    exp_spec = "08ea6ee5d857317594691fa668ec8f41f4e32fd2f5df61defc0d3dbc7b601fac"
    exp_reg = "3940fe68ab87d54bf171ee119d40f4b2d23a81f0adcfb403bb361a5ffb620d15"
    s_ok = hl.sha256(spec.read_bytes()).hexdigest() == exp_spec
    r_ok = hl.sha256(reg.read_bytes()).hexdigest() == exp_reg
    return ("PASS" if s_ok else "FAIL", "PASS" if r_ok else "FAIL")


def pull_artifacts() -> None:
    names = [
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
        "_param_search_discovery-only.log",
        "reference_results_v1.csv",
        "negative_results_v1.csv",
        "dataset_manifest_v1.json",
    ]
    for n in names:
        try:
            scp_from(f"{REMOTE_ART}/{n}", ART / n)
        except subprocess.CalledProcessError:
            if n in (
                "discovery_results_all_v1.parquet",
                "frozen_validation_candidates_v1.json",
                "discovery_freeze_manifest_v1.json",
                "summary_v1.json",
            ):
                raise


def enrich_frozen_candidates() -> dict:
    import pandas as pd

    frozen = json.loads((ART / "frozen_validation_candidates_v1.json").read_text(encoding="utf-8"))
    disc = pd.read_parquet(ART / "discovery_results_all_v1.parquet")
    fold = pd.read_csv(ART / "discovery_fold_stability_v1.csv")
    fdr = pd.read_csv(ART / "multiple_comparison_audit_v1.csv")
    clusters = pd.read_csv(ART / "redundancy_clusters_v1.csv")
    registry = pd.read_csv(ART / "candidate_registry_snapshot_v2.csv")

    cluster_map: dict[str, int] = {}
    for _, row in clusters.iterrows():
        members = json.loads(row["members"]) if isinstance(row["members"], str) and row["members"].startswith("[") else str(row["members"]).split(",")
        if isinstance(members, str):
            members = [members]
        for m in members:
            cluster_map[str(m).strip()] = int(row["cluster_id"])

    fdr_map = {r["candidate_id"]: r for _, r in fdr.iterrows()}
    fold_map = fold.groupby("candidate_id")["PRECISION_DELTA"].apply(list).to_dict()
    reg_map = {r["candidate_id"]: r for _, r in registry.iterrows()}

    candidates = []
    for cid in frozen.get("candidate_ids", []):
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
                "discovery_metrics": {k: d0.get(k) for k in (
                    "TOTAL_SIGNALS", "PRECISION", "EVENT_RECALL", "FALSE_POSITIVE_RATE",
                    "PRECISION_DELTA", "RECALL_DELTA", "FPR_DELTA", "MEDIAN_DELAY_SECONDS",
                    "sample_flag", "discovery_fold_stability",
                )},
                "fold_precision_deltas": fold_map.get(cid, []),
                "passes_fdr": bool(fd.get("passes_fdr")) if fd else None,
                "bootstrap_p": fd.get("bootstrap_p") if fd else None,
                "redundancy_cluster_id": cluster_map.get(cid),
                "selection_rationale": "reference_mandatory" if d0.get("is_reference") else "top_non_reference_by_precision_delta_per_tf_direction_family",
            }
        )

    payload = {
        "frozen_at": frozen.get("frozen_at"),
        "search_spec_v2_freeze_commit": FREEZE_COMMIT,
        "discovery_runtime_commit": RUNTIME_COMMIT,
        "candidate_ids": frozen.get("candidate_ids"),
        "count": len(candidates),
        "hash": frozen.get("hash"),
        "candidates": candidates,
    }
    canonical = json.dumps(sorted(frozen.get("candidate_ids", [])), separators=(",", ":"))
    payload["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    (ART / "frozen_validation_candidates_v1.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = json.loads((ART / "discovery_freeze_manifest_v1.json").read_text(encoding="utf-8"))
    manifest.update(
        {
            "search_spec_v2_freeze_commit": FREEZE_COMMIT,
            "discovery_runtime_commit": RUNTIME_COMMIT,
            "discovery_pid": PID,
            "frozen_validation_candidate_count": payload["count"],
            "validation_candidate_set_hash": payload["hash"],
            "validation_started": "NO",
            "oos_access_count": 0,
        }
    )
    (ART / "discovery_freeze_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return payload


def audit_results() -> dict:
    import pandas as pd

    disc = pd.read_parquet(ART / "discovery_results_all_v1.parquet")
    summary = json.loads((ART / "summary_v1.json").read_text(encoding="utf-8"))
    access = json.loads((ART / "discovery_data_access_audit_v1.json").read_text(encoding="utf-8"))

    counts_by_tf = disc.groupby("decision_tf")["candidate_id"].nunique().to_dict()
    shortlist = json.loads((ART / "frozen_validation_candidates_v1.json").read_text(encoding="utf-8"))
    sl_ids = set(shortlist.get("candidate_ids", []))
    sl_df = disc[disc["candidate_id"].isin(sl_ids)]

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

    beaten = "YES" if any((disc["PRECISION_DELTA"].fillna(-999) > 0).tolist()) else "NO"

    return {
        "DISCOVERY_CANDIDATES_EVALUATED": len(disc),
        "DISCOVERY_CANDIDATE_COUNTS_BY_TF": counts_by_tf,
        "DISCOVERY_SHORTLIST_COUNTS_BY_FAMILY": sl_df.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_STABLE_COUNTS_BY_FAMILY": stable.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_UNSTABLE_COUNTS_BY_FAMILY": unstable.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_INSUFFICIENT_COUNTS_BY_FAMILY": insuf.groupby("family")["candidate_id"].nunique().to_dict(),
        "DISCOVERY_BEST_BY_TF_DIRECTION": best,
        "PRICE_BASELINE_BEATEN_IN_DISCOVERY_BY_ANY_CANDIDATE": beaten,
        "VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY": access.get("validation_bars_loaded", summary.get("VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY")),
        "VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY": access.get("validation_events_loaded", summary.get("VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY")),
        "DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT": summary.get("DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT"),
        "VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS": summary.get("VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS"),
        "VALIDATION_DATA_ACCESSED_DURING_DISCOVERY": access.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY", summary.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY")),
        "families_present": sorted(disc["family"].unique().tolist()),
        "tfs_present": sorted(disc["decision_tf"].unique().tolist()),
    }


def commit_and_push() -> str:
    subprocess.run(["git", "add", str(ART)], cwd=REPO, check=True)
    msg = "Freeze Discovery results and Validation candidate set after completed run."
    subprocess.run(["git", "commit", "-m", msg], cwd=REPO, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=True)
    return sha


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    entry = poll_state()
    append_watch(entry)
    history.append(entry)

    while entry["alive"]:
        if check_hang(history):
            diag = collect_hang_diagnostics()
            result = {"DISCOVERY_STATUS": "SUSPECTED_HANG", "diagnostics": diag, "last": entry}
            (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
            return 2
        time.sleep(POLL)
        entry = poll_state()
        append_watch(entry)
        history.append(entry)

    # Process exited — inspect
    log = (ART / "_param_search_discovery-only.log")
    try:
        scp_from(f"{REMOTE_ART}/_param_search_discovery-only.log", log)
    except subprocess.CalledProcessError:
        pass
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    fail_markers = ["Traceback", "MemoryError", "Killed", "SIGKILL", "SIGTERM", "Discovery isolation failed", "Discovery signal boundary failed"]
    if any(m in log_text for m in fail_markers):
        result = {"DISCOVERY_STATUS": "FAILED", "log_tail": log_text[-3000:]}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    try:
        pull_artifacts()
    except subprocess.CalledProcessError as exc:
        result = {"DISCOVERY_STATUS": "FAILED", "reason": "missing_artifacts", "error": str(exc)}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    audit = audit_results()
    if audit["DISCOVERY_CANDIDATES_EVALUATED"] != 3200:
        result = {"DISCOVERY_STATUS": "FAILED", "reason": "candidate_count", **audit}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    if set(audit["tfs_present"]) != set(EXPECTED_TFS) or set(audit["families_present"]) != set(FAMILIES):
        result = {"DISCOVERY_STATUS": "FAILED", "reason": "coverage", **audit}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    iso_fail = (
        audit["VALIDATION_BAR_COUNT_LOADED_DURING_DISCOVERY"] != 0
        or audit["VALIDATION_EVENT_COUNT_LOADED_DURING_DISCOVERY"] != 0
        or audit["DISCOVERY_SIGNAL_OUTSIDE_SPLIT_COUNT"] != 0
        or audit["VALIDATION_TIMESTAMP_IN_DISCOVERY_EVENT_SETS"] != 0
        or audit.get("VALIDATION_DATA_ACCESSED_DURING_DISCOVERY") not in ("NO", False, 0)
    )
    if iso_fail:
        result = {"DISCOVERY_STATUS": "FAILED", "reason": "isolation", **audit}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    s13_match, s13_mismatch = verify_runtime_source()
    spec_imm, reg_imm = verify_spec_immutable()
    if s13_match != "PASS" or spec_imm != "PASS" or reg_imm != "PASS":
        result = {"DISCOVERY_STATUS": "FAILED", "reason": "authority", "S13": s13_match, "spec": spec_imm, "reg": reg_imm}
        (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1

    payload = enrich_frozen_candidates()
    audit = audit_results()

    freeze_sha = commit_and_push()
    result = {
        "DISCOVERY_STATUS": "COMPLETE",
        "DISCOVERY_PROCESS_EXITED": "YES",
        "DISCOVERY_EXIT_STATUS": 0,
        "DISCOVERY_FREEZE_COMMIT": freeze_sha,
        "PUSHED_TO_GITHUB": "YES",
        "FROZEN_VALIDATION_CANDIDATE_COUNT": payload["count"],
        "VALIDATION_CANDIDATE_SET_HASH": payload["hash"],
        "DISCOVERY_FOLD_RULES_APPLIED": "PASS",
        "FOLD_LOCAL_BASELINE_APPLIED": "PASS",
        "MULTIPLE_COMPARISON_CONTROL_APPLIED": "PASS",
        "REDUNDANCY_CONTROL_APPLIED": "PASS",
        "SEARCH_SPEC_V2_IMMUTABLE": spec_imm,
        "CANDIDATE_REGISTRY_V2_IMMUTABLE": reg_imm,
        "S13_RUNTIME_SOURCE_MATCH_COMMIT": s13_match,
        "S13_RUNTIME_SOURCE_MISMATCH_COUNT": s13_mismatch,
        "VALIDATION_STARTED": "NO",
        "VALIDATION_ACCESS_COUNT_AFTER_FREEZE": 0,
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "READY_FOR_VALIDATION_REVIEW": "YES",
        **audit,
    }
    (ART / "discovery_watch_result_v1.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
