#!/usr/bin/env python3
"""Deploy feature bank to S13 and run anti-leakage gate tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
ROOT = Path(__file__).resolve().parent
REMOTE_WS = "/var/tmp/traiding_pilot_ui_workspace"
REMOTE_PKG = f"{REMOTE_WS}/phase3_staging"


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
    for pkg in ["multitf_feature_bank", "indicator_engine"]:
        scp(ROOT / "crypto_trading_bot" / "research_v2" / pkg, f"{REMOTE_PKG}/crypto_trading_bot/research_v2/")
    ssh(f"mkdir -p {REMOTE_PKG}/tests")
    scp(ROOT / "tests" / "multitf_feature_bank", f"{REMOTE_PKG}/tests/")
    ssh(
        f"cd {REMOTE_PKG} && PYTHONPATH=. {REMOTE_WS}/.venv/bin/python tests/multitf_feature_bank/test_anti_leakage.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
