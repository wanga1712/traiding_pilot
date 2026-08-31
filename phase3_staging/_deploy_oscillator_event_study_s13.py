#!/usr/bin/env python3
"""Deploy oscillator event study to S13 and run canonical preflight + study."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
ROOT = Path(__file__).resolve().parent
REMOTE_WS = "/var/tmp/traiding_pilot_ui_workspace"
REMOTE_PKG = f"{REMOTE_WS}/phase3_staging"
REMOTE_ART = f"{REMOTE_WS}/artifacts/OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1"
PY = f"{REMOTE_WS}/.venv/bin/python"

PACKAGES = (
    "market_data",
    "indicator_engine",
    "resampling",
    "oscillator_predictor",
    "oscillator_predictor_event_study",
    "reversal_signal_study",
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def scp(local: Path, remote: str) -> None:
    run(["scp", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", "-r", str(local), f"{HOST}:{remote}"])


def ssh(script: str) -> str:
    out = subprocess.check_output(
        ["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", HOST, script],
        text=True,
    )
    print(out)
    return out


def main() -> int:
    run_study = "--run-study" in sys.argv
    ssh(f"mkdir -p {REMOTE_PKG}/crypto_trading_bot/research_v2 {REMOTE_ART}")
    for pkg in PACKAGES:
        src = ROOT / "crypto_trading_bot" / "research_v2" / pkg
        scp(src, f"{REMOTE_PKG}/crypto_trading_bot/research_v2/")
    flag = " --run-study" if run_study else ""
    ssh(
        f"cd {REMOTE_PKG} && "
        f"export OSCILLATOR_EVENT_STUDY_ARTIFACT_ROOT={REMOTE_ART} && "
        f"export TRAIDING_PILOT_MARKET_CACHE=/var/tmp/traiding_pilot_market_cache && "
        f"export TRAIDING_PILOT_SSH_KEY=/home/sergey/.ssh/id_to_nyx && "
        f"PYTHONPATH=. {PY} -m crypto_trading_bot.research_v2.oscillator_predictor_event_study.s13_canonical_preflight{flag}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
