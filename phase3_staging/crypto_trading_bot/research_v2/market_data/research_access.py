"""S7 canonical market data access for S13 research — no direct exchange downloads."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.market_data.bars_service import TimeframeBarService

CANONICAL_HOST = "S7"
CANONICAL_SOURCE_PATH = "/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"
CANONICAL_MANIFEST_PATH = "/srv/traiding_pilot/manifests/market.sqlite3"
COMPUTE_HOST = "S13"
S13_RESEARCH_CACHE_PATH = Path(
    os.environ.get(
        "TRAIDING_PILOT_MARKET_CACHE",
        "/var/tmp/traiding_pilot_market_cache" if os.name != "nt" else "C:/var/tmp/traiding_pilot_market_cache",
    )
)
SSH_HOST = os.environ.get("TRAIDING_PILOT_SSH_HOST", "wanga@10.8.0.7")
SSH_KEY_CANDIDATES = (
    Path(os.environ.get("TRAIDING_PILOT_SSH_KEY", "")),
    Path.home() / ".ssh" / "id_to_nyx",
    Path("/home/sergey/.ssh/id_to_nyx"),
)


def resolve_ssh_key() -> Path | None:
    for candidate in SSH_KEY_CANDIDATES:
        if str(candidate) and candidate.exists():
            return candidate
    return None


def make_research_bar_service() -> TimeframeBarService:
    """TimeframeBarService reading S7 canonical 1m into S13 disposable cache."""
    canonical = Path(CANONICAL_SOURCE_PATH)
    if canonical.is_dir():
        return TimeframeBarService(
            symbol="ETHUSDT",
            canonical_root=canonical,
            cache_root=S13_RESEARCH_CACHE_PATH,
            ssh_host=None,
            ssh_key=None,
        )
    key = resolve_ssh_key()
    if key is None:
        raise RuntimeError(
            "S7 research data access requires local mount or SSH key for "
            f"{SSH_HOST}:{CANONICAL_SOURCE_PATH} (set TRAIDING_PILOT_SSH_KEY)"
        )
    return TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=canonical,
        cache_root=S13_RESEARCH_CACHE_PATH,
        ssh_host=SSH_HOST,
        ssh_key=key,
    )


def _ssh_probe() -> tuple[bool, str]:
    key = resolve_ssh_key()
    if key is None:
        return False, "SSH key not found for S7 access"
    probe = f"{CANONICAL_SOURCE_PATH}/2019/ETHUSDT-1m-2019-05.parquet"
    cmd = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST, f"test -f {probe}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, probe
        return False, f"S7 probe file missing or unreachable: {probe}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def check_s7_required_months(start: datetime, end: datetime) -> dict[str, Any]:
    """Verify representative S7 partitions exist for [start, end). Does not download."""
    key = resolve_ssh_key()
    ok, detail = _ssh_probe()
    months_needed = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months_needed.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    # spot-check first, middle, last month
    samples = list(dict.fromkeys([months_needed[0], months_needed[len(months_needed) // 2], months_needed[-1]]))
    missing: list[str] = []
    if key:
        for token in samples:
            year, mon = token.split("-")
            remote = f"{CANONICAL_SOURCE_PATH}/{year}/ETHUSDT-1m-{token}.parquet"
            cmd = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST, f"test -f {remote}"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30)
                if r.returncode != 0:
                    missing.append(remote)
            except Exception:  # noqa: BLE001
                missing.append(remote)
    return {
        "s7_reachable": ok,
        "probe_detail": detail,
        "months_in_range": len(months_needed),
        "sample_months_checked": samples,
        "missing_on_s7": missing,
        "required_range_start": start.isoformat(),
        "required_range_end": end.isoformat(),
    }


def write_cache_manifest(
    manifest_path: Path,
    *,
    time_range: tuple[datetime, datetime],
    timeframes: list[str],
    row_counts: dict[str, int],
    source_dataset_version: str | None = None,
) -> dict[str, Any]:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_host": CANONICAL_HOST,
        "source_path": CANONICAL_SOURCE_PATH,
        "source_manifest_path": CANONICAL_MANIFEST_PATH,
        "source_dataset_version": source_dataset_version,
        "copied_at": datetime.now(timezone.utc).isoformat(),
        "time_range": {
            "start": time_range[0].isoformat(),
            "end": time_range[1].isoformat(),
        },
        "timeframes": timeframes,
        "row_counts": row_counts,
        "cache_disposable": True,
        "compute_host": COMPUTE_HOST,
        "cache_path": str(S13_RESEARCH_CACHE_PATH),
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def run_data_location_preflight(
    *,
    required_start: datetime,
    required_end: datetime,
    artifact_root: Path,
) -> dict[str, Any]:
    month_check = check_s7_required_months(required_start, required_end)
    ready = month_check["s7_reachable"] and not month_check["missing_on_s7"]
    result = {
        "mode": "DATA-LOCATION-PREFLIGHT",
        "CANONICAL_MARKET_DATA_HOST": CANONICAL_HOST,
        "COMPUTE_HOST": COMPUTE_HOST,
        "DIRECT_EXCHANGE_DOWNLOAD_ON_S13": "NO",
        "CANONICAL_SOURCE_PATH": CANONICAL_SOURCE_PATH,
        "S13_RESEARCH_CACHE_PATH": str(S13_RESEARCH_CACHE_PATH),
        "S13_CACHE_DISPOSABLE": "YES",
        "VISUAL_AUDIT_USES_CANONICAL_DATA": "YES",
        "HISTORICAL_EVENT_STUDY_STARTED": "NO",
        "READY_FOR_HISTORICAL_EVENT_STUDY": "YES" if ready else "NO",
        **month_check,
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "data_provenance_preflight_v1.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if ready:
        write_cache_manifest(
            artifact_root / "s13_cache_manifest_v1.json",
            time_range=(required_start, required_end),
            timeframes=[],
            row_counts={},
        )
    return result
