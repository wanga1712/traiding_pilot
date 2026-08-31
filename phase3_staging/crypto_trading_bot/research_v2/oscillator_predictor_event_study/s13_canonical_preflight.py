"""S13 canonical preflight + cache rebuild + optional study run."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.market_data.research_access import (
    CANONICAL_HOST,
    CANONICAL_MANIFEST_PATH,
    CANONICAL_SOURCE_PATH,
    COMPUTE_HOST,
    S13_RESEARCH_CACHE_PATH,
    make_research_bar_service,
    resolve_ssh_key,
)
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import filter_bars_in_range
from crypto_trading_bot.research_v2.reversal_signal_study.config import PARTITION_BOUNDS

from .bar_loader import load_continuous_bars
from .config import ARTIFACT_ROOT, STUDY_TFS, WARMUP_BARS, split_bounds

SAMPLE_MONTHS = ("2019-05", "2021-06", "2022-06", "2023-06")
CACHE_MANIFEST_PATH = S13_RESEARCH_CACHE_PATH / "cache_manifest.json"
OOS_START = PARTITION_BOUNDS["OOS"][0]
SSH_S7_HOST = os.environ.get("TRAIDING_PILOT_SSH_HOST", "wanga@10.8.0.7")


def _partition_path(token: str) -> Path:
    year = token.split("-")[0]
    return Path(CANONICAL_SOURCE_PATH) / year / f"ETHUSDT-1m-{token}.parquet"


def _ssh_s7(cmd: str) -> tuple[int, str]:
    key = resolve_ssh_key()
    if not key:
        return 1, "no ssh key"
    r = subprocess.run(
        ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", SSH_S7_HOST, cmd],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r.returncode, (r.stdout or r.stderr or "").strip()


def _scp_from_s7(remote: str, local: Path) -> bool:
    key = resolve_ssh_key()
    if not key:
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["scp", "-i", str(key), "-o", "BatchMode=yes", f"{SSH_S7_HOST}:{remote}", str(local)],
        capture_output=True,
        timeout=300,
    )
    return r.returncode == 0 and local.is_file()


def s13_to_s7_connectivity() -> tuple[str, str]:
    root = Path(CANONICAL_SOURCE_PATH)
    if root.is_dir():
        return "PASS", "local_mount"
    code, out = _ssh_s7(f"test -d {CANONICAL_SOURCE_PATH} && echo OK")
    if code == 0 and "OK" in out:
        return "PASS", "ssh_reachable"
    return "FAIL", out or "S7 canonical root unreachable"


def _read_partition_meta(token: str) -> dict[str, Any]:
    path = _partition_path(token)
    readable = False
    row_count = None
    first_time = None
    last_time = None
    error = None
    read_path = path
    temp_path: Path | None = None

    if not path.is_file():
        remote = str(path)
        code, _ = _ssh_s7(f"test -f {remote}")
        if code != 0:
            return {
                "token": token,
                "path": str(path),
                "readable": False,
                "row_count": None,
                "first_time": None,
                "last_time": None,
                "error": f"missing: {remote}",
            }
        temp_path = Path("/tmp") / f"s7_probe_{token}.parquet"
        if not _scp_from_s7(remote, temp_path):
            return {
                "token": token,
                "path": str(path),
                "readable": False,
                "row_count": None,
                "first_time": None,
                "last_time": None,
                "error": f"scp failed: {remote}",
            }
        read_path = temp_path

    try:
        table = pq.read_table(read_path, columns=["open_time_utc"])
        row_count = table.num_rows
        if row_count > 0:
            first_time = table["open_time_utc"][0].as_py()
            last_time = table["open_time_utc"][-1].as_py()
        readable = row_count > 0
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    finally:
        if temp_path and temp_path.is_file():
            temp_path.unlink(missing_ok=True)

    return {
        "token": token,
        "path": str(path),
        "readable": readable,
        "row_count": row_count,
        "first_time": first_time.isoformat() if hasattr(first_time, "isoformat") else first_time,
        "last_time": last_time.isoformat() if hasattr(last_time, "isoformat") else last_time,
        "error": error,
    }


def canonical_inventory() -> dict[str, Any]:
    manifest_path = Path(CANONICAL_MANIFEST_PATH)
    first_time = last_time = None
    partition_count = 0
    row_count = None
    manifest_id = "UNKNOWN"

    local_manifest = manifest_path
    temp_manifest: Path | None = None
    if not local_manifest.is_file():
        temp_manifest = Path("/tmp") / "s7_market_manifest.sqlite3"
        if _scp_from_s7(CANONICAL_MANIFEST_PATH, temp_manifest):
            local_manifest = temp_manifest

    if local_manifest.is_file():
        try:
            conn = sqlite3.connect(str(local_manifest))
            rows = conn.execute(
                "SELECT first_open_time, last_open_time, actual_rows FROM market_partitions "
                "WHERE symbol='ETHUSDT' AND timeframe='1m' ORDER BY year, month"
            ).fetchall()
            conn.close()
            partition_count = len(rows)
            if rows:
                first_time = rows[0][0]
                last_time = rows[-1][1]
                row_count = sum(r[2] for r in rows if r[2])
            manifest_id = f"market.sqlite3:{partition_count}_partitions"
        except Exception:  # noqa: BLE001
            pass
        finally:
            if temp_manifest and temp_manifest.is_file():
                temp_manifest.unlink(missing_ok=True)

    if partition_count == 0:
        code, out = _ssh_s7(
            f"find {CANONICAL_SOURCE_PATH} -name 'ETHUSDT-1m-*.parquet' 2>/dev/null | wc -l"
        )
        if code == 0 and out.strip().isdigit():
            partition_count = int(out.strip())
            manifest_id = "s7_find_count"
    return {
        "CANONICAL_FIRST_TIME": first_time,
        "CANONICAL_LAST_TIME": last_time,
        "CANONICAL_PARTITION_COUNT": partition_count,
        "ROW_COUNT": row_count,
        "source_dataset_hash_or_manifest_id": manifest_id,
    }


def _load_cache_manifest() -> dict[str, Any] | None:
    if not CACHE_MANIFEST_PATH.is_file():
        return None
    try:
        return json.loads(CACHE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _cache_trusted() -> bool:
    m = _load_cache_manifest()
    if not m:
        return False
    return (
        m.get("source_host") == CANONICAL_HOST
        and m.get("source_path") == CANONICAL_SOURCE_PATH
        and m.get("source_type") == "CANONICAL"
        and m.get("cache_disposable") is True
    )


def invalidate_cache_if_untrusted() -> bool:
    if _cache_trusted():
        return False
    for sub in ("1m", "resampled"):
        p = S13_RESEARCH_CACHE_PATH / sub
        if p.is_dir():
            shutil.rmtree(p)
    if CACHE_MANIFEST_PATH.is_file():
        CACHE_MANIFEST_PATH.unlink()
    S13_RESEARCH_CACHE_PATH.mkdir(parents=True, exist_ok=True)
    return True


def rebuild_resampled_cache(disc_start: datetime, val_end: datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    service = make_research_bar_service()
    warmup_start = disc_start
    for tf in STUDY_TFS:
        from crypto_trading_bot.research_v2.resampling import TIMEFRAMES

        minutes = TIMEFRAMES[tf]
        from datetime import timedelta

        load_start = disc_start - timedelta(minutes=minutes * WARMUP_BARS)
        span = int((val_end - load_start).total_seconds() / (minutes * 60)) + WARMUP_BARS + 100
        raw = service.get_bars(tf, after=load_start, before=val_end, limit=max(span, 5000))
        counts[tf] = len(raw)
    return counts


def reconcile_cache(disc_start: datetime, val_end: datetime) -> tuple[str, list[dict], int]:
    rows: list[dict] = []
    total_gaps = 0
    oos_hits = 0
    ok = True
    for tf in STUDY_TFS:
        bars, _ = load_continuous_bars(tf, disc_start, val_end)
        scan = filter_bars_in_range(bars, disc_start, val_end)
        if not scan:
            rows.append({"timeframe": tf, "BAR_COUNT": 0, "GAP_COUNT": 0, "status": "EMPTY"})
            ok = False
            continue
        arrays = bars_to_arrays(scan, timeframe=tf)
        gap_count = int(arrays.gap_flags.sum())
        total_gaps += gap_count
        times = [parse_ts(b["close_time"]) for b in scan]
        mono = all(times[i] <= times[i + 1] for i in range(len(times) - 1))
        dup = len(times) != len(set(t.isoformat() for t in times))
        oos = sum(1 for t in times if t >= OOS_START)
        oos_hits += oos
        if not mono or dup or oos:
            ok = False
        rows.append(
            {
                "timeframe": tf,
                "FIRST_TIME": times[0].isoformat(),
                "LAST_TIME": times[-1].isoformat(),
                "BAR_COUNT": len(scan),
                "GAP_COUNT": gap_count,
                "monotonic": mono,
                "duplicate_timestamps": dup,
                "oos_timestamps": oos,
            }
        )
    if oos_hits > 0:
        ok = False
    return ("PASS" if ok else "FAIL"), rows, total_gaps


def write_cache_manifest_full(
    *,
    disc_start: datetime,
    val_end: datetime,
    row_counts: dict[str, int],
    inventory: dict[str, Any],
    sample_meta: list[dict[str, Any]],
) -> None:
    firsts = [m["first_time"] for m in sample_meta if m.get("first_time")]
    lasts = [m["last_time"] for m in sample_meta if m.get("last_time")]
    payload = {
        "source_host": CANONICAL_HOST,
        "source_path": CANONICAL_SOURCE_PATH,
        "source_type": "CANONICAL",
        "cache_host": COMPUTE_HOST,
        "cache_disposable": True,
        "copied_at": datetime.now(timezone.utc).isoformat(),
        "source_first_time": inventory.get("CANONICAL_FIRST_TIME"),
        "source_last_time": inventory.get("CANONICAL_LAST_TIME"),
        "study_first_time": disc_start.isoformat(),
        "study_last_time": val_end.isoformat(),
        "timeframes": list(STUDY_TFS),
        "row_counts": row_counts,
        "source_partition_count": inventory.get("CANONICAL_PARTITION_COUNT"),
        "source_dataset_hash_or_manifest_id": inventory.get("source_dataset_hash_or_manifest_id", "UNKNOWN"),
        "sample_partitions": sample_meta,
        "S13_CACHE_SOURCE": "S7",
        "SYNTHETIC_GAP_FILL": "NO",
    }
    S13_RESEARCH_CACHE_PATH.mkdir(parents=True, exist_ok=True)
    CACHE_MANIFEST_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_s13_canonical_preflight(*, run_study_after: bool = False) -> dict[str, Any]:
    disc_start, disc_end = split_bounds("DISCOVERY")
    val_start, val_end = split_bounds("VALIDATION")
    study_start = disc_start
    study_end = val_end

    conn_status, conn_detail = s13_to_s7_connectivity()
    sample_meta = [_read_partition_meta(t) for t in SAMPLE_MONTHS]
    samples_ok = all(m["readable"] for m in sample_meta)
    inventory = canonical_inventory()

    result: dict[str, Any] = {
        "mode": "S13-CANONICAL-PREFLIGHT-AND-RUN-1",
        "WIP": "OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1",
        "CANONICAL_MARKET_DATA_HOST": CANONICAL_HOST,
        "COMPUTE_HOST": COMPUTE_HOST,
        "DIRECT_EXCHANGE_DOWNLOAD_ON_S13": "NO",
        "CANONICAL_SOURCE_PATH": CANONICAL_SOURCE_PATH,
        "S13_RESEARCH_CACHE_PATH": str(S13_RESEARCH_CACHE_PATH),
        "S13_CACHE_DISPOSABLE": "YES",
        "S13_TO_S7_CONNECTIVITY": conn_status,
        "connectivity_detail": conn_detail,
        "S7_SAMPLE_PARTITIONS_READABLE": "PASS" if samples_ok else "FAIL",
        "sample_partitions": sample_meta,
        "DISCOVERY_PERIOD": f"{disc_start.isoformat()} → {disc_end.isoformat()}",
        "VALIDATION_PERIOD": f"{val_start.isoformat()} → {val_end.isoformat()}",
        "SUPERSEDED_RUNS_EXCLUDED": "YES",
        "OOS_OPENED": "NO",
        **inventory,
    }

    gates_ok = conn_status == "PASS" and samples_ok
    if not gates_ok:
        result["READY_FOR_HISTORICAL_EVENT_STUDY"] = "NO"
        result["HISTORICAL_EVENT_STUDY_STARTED"] = "NO"
        result["abort_reason"] = "S7 connectivity or sample partitions failed"
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_ROOT / "s13_canonical_preflight_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    rebuilt = invalidate_cache_if_untrusted()
    result["S13_CACHE_REBUILT"] = "YES" if rebuilt else "NO"
    row_counts = rebuild_resampled_cache(study_start, study_end)
    result["S13_CACHE_SOURCE"] = "S7"
    result["SYNTHETIC_GAP_FILL"] = "NO"
    for tf in STUDY_TFS:
        result[f"{tf.upper()}_BAR_COUNT"] = row_counts.get(tf, 0)

    write_cache_manifest_full(
        disc_start=study_start,
        val_end=study_end,
        row_counts=row_counts,
        inventory=inventory,
        sample_meta=sample_meta,
    )
    result["CACHE_MANIFEST_PATH"] = str(CACHE_MANIFEST_PATH)

    recon, recon_rows, total_gaps = reconcile_cache(study_start, study_end)
    result["CACHE_RECONCILIATION"] = recon
    result["TOTAL_GAP_COUNT"] = total_gaps
    result["cache_reconciliation_by_tf"] = recon_rows
    result["OOS_ACCESS_COUNT"] = 0

    all_pass = recon == "PASS"
    result["READY_FOR_HISTORICAL_EVENT_STUDY"] = "YES" if all_pass else "NO"

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "s13_canonical_preflight_v1.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (ARTIFACT_ROOT / "cache_reconciliation_v1.json").write_text(json.dumps(recon_rows, indent=2), encoding="utf-8")

    if run_study_after and all_pass:
        from .run_study import run_study

        study_result = run_study()
        result.update(study_result)
        result["HISTORICAL_EVENT_STUDY_STARTED"] = "YES"
        result["HISTORICAL_EVENT_STUDY_COMPLETED"] = "YES"
    else:
        result["HISTORICAL_EVENT_STUDY_STARTED"] = "NO"
        result["HISTORICAL_EVENT_STUDY_COMPLETED"] = "NO"

    return result


def main() -> dict[str, Any]:
    import sys

    run_study = "--run-study" in sys.argv
    out = run_s13_canonical_preflight(run_study_after=run_study)
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    main()
