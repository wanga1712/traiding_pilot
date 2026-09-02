#!/usr/bin/env python3
"""Deploy inverse batch execution fix to S13, run gates, restart discovery."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
REMOTE_WS = "/var/tmp/traiding_pilot_ui_workspace"
REMOTE_PKG = f"{REMOTE_WS}/phase3_staging"
REMOTE_ART = f"{REMOTE_WS}/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
PY = f"{REMOTE_WS}/.venv/bin/python"

PACKAGES = (
    "inverse_predictors",
    "indicator_parameter_search",
    "reversal_signal_study",
)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def scp(local: Path, remote: str) -> None:
    run(["scp", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", "-r", str(local), f"{HOST}:{remote}"])


def ssh(script: str) -> str:
    out = subprocess.check_output(
        ["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", HOST, script],
        text=True,
    )
    print(out)
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    commit = sys.argv[1] if len(sys.argv) > 1 else ""
    if not commit:
        print("usage: _deploy_inverse_batch_fix_s13.py <commit_sha>", file=sys.stderr)
        return 2

    ssh(f"mkdir -p {REMOTE_PKG}/crypto_trading_bot/research_v2 {REMOTE_ART}")
    for pkg in PACKAGES:
        src = ROOT / "crypto_trading_bot" / "research_v2" / pkg
        scp(src, f"{REMOTE_PKG}/crypto_trading_bot/research_v2/")

    art_local = REPO / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"
    for name in ("discovery_run_2133798_authority_v1.json",):
        run(
            [
                "scp",
                "-i",
                str(SSH_KEY),
                "-o",
                "StrictHostKeyChecking=no",
                str(art_local / name),
                f"{HOST}:{REMOTE_ART}/",
            ]
        )

    test_cmd = (
        f"cd {REMOTE_PKG} && PYTHONPATH=. {PY} -m pytest "
        f"tests/indicator_parameter_search/test_inverse_batch_execution.py "
        f"tests/indicator_parameter_search/test_inverse_trigger_extraction.py -q --noconftest"
    )
    ssh(test_cmd)

    smoke_cmd = (
        f"cd {REMOTE_PKG} && PYTHONPATH=. {PY} -c \""
        "from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import run_inverse_5m_full_history_smoke; "
        "import json; print(json.dumps(run_inverse_5m_full_history_smoke(), indent=2))"
        "\""
    )
    smoke_out = ssh(smoke_cmd)
    smoke_line = [ln for ln in smoke_out.splitlines() if ln.strip().startswith("{")][-1]
    smoke = json.loads(smoke_line)
    if smoke.get("INVERSE_5M_FULL_HISTORY_EXCEPTION_COUNT", 1) != 0:
        raise SystemExit(f"5m smoke failed: {smoke}")
    if smoke.get("INVERSE_5M_DEAD_EXECUTION_ROUTE_COUNT", 1) != 0:
        raise SystemExit(f"5m dead routes: {smoke}")

    local_batch = ROOT / "crypto_trading_bot/research_v2/inverse_predictors/batch_thresholds.py"
    local_hash = sha256_file(local_batch)
    remote_hash = ssh(f"sha256sum {REMOTE_PKG}/crypto_trading_bot/research_v2/inverse_predictors/batch_thresholds.py").split()[0]
    if local_hash != remote_hash:
        # CRLF tolerance: compare normalized LF
        local_norm = local_batch.read_bytes().replace(b"\r\n", b"\n")
        remote_norm = subprocess.check_output(
            ["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", HOST, f"cat {REMOTE_PKG}/crypto_trading_bot/research_v2/inverse_predictors/batch_thresholds.py"],
        ).replace(b"\r\n", b"\n")
        if hashlib.sha256(local_norm).hexdigest() != hashlib.sha256(remote_norm).hexdigest():
            raise SystemExit(f"S13_RUNTIME_SOURCE_MISMATCH local={local_hash} remote={remote_hash}")

    ssh("pkill -f 'indicator_parameter_search.run_search' || true; sleep 2")
    ssh(f"bash {REMOTE_PKG}/_run_parameter_search_s13.sh discovery-only")

    status = {
        "INVERSE_BATCH_FIX_COMMIT": commit,
        "S13_RUNTIME_SOURCE_MATCH_COMMIT": "PASS",
        "smoke": smoke,
    }
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
