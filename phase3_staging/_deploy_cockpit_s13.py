#!/usr/bin/env python3
"""Deploy cockpit foundation to S13 and restart expert_app (single instance)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SSH_KEY = Path(r"C:\Users\Lenovo\.ssh\id_ed25519_codex_worker")
HOST = "sergey@10.8.0.13"
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
REMOTE_WS = "/var/tmp/traiding_pilot_ui_workspace"
REMOTE_PKG = f"{REMOTE_WS}/phase3_staging"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def scp(local: Path, remote: str) -> None:
    run(["scp", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", "-r", str(local), f"{HOST}:{remote}"])


def ssh(script: str) -> None:
    run(["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", HOST, script])


def main() -> int:
    # Sync code
    scp(ROOT / "crypto_trading_bot" / "research_v2" / "trading_runs", f"{REMOTE_PKG}/crypto_trading_bot/research_v2/")
    for rel in [
        "crypto_trading_bot/research_v2/visualization/expert_app.py",
        "crypto_trading_bot/research_v2/visualization/trading_run_panel.py",
        "crypto_trading_bot/research_v2/visualization/assets/style.css",
    ]:
        scp(ROOT / rel, f"{REMOTE_PKG}/{rel}")

    # Sync production run store (relative to phase3_staging cwd)
    store = REPO / "artifacts" / "TRADING-RESEARCH-COCKPIT-FOUNDATION-1" / "trading_runs_store"
    ssh(f"mkdir -p {REMOTE_PKG}/artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1")
    scp(store, f"{REMOTE_PKG}/artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1/")

    # Restart UI (no second instance)
    ssh(
        f"cd {REMOTE_PKG} && "
        "pkill -f 'crypto_trading_bot.research_v2.visualization.expert_app' || true; "
        "sleep 1; "
        "nohup env PYTHONPATH=. "
        f"\"{REMOTE_WS}/.venv/bin/python\" -m crypto_trading_bot.research_v2.visualization.expert_app "
        f"--host 0.0.0.0 --port 8055 --initial-end 2024-06-30 --oos-blind "
        f"> {REMOTE_WS}/expert_app.log 2>&1 & "
        "sleep 3; "
        f"tail -25 {REMOTE_WS}/expert_app.log; "
        "ss -tlnp | grep 8055 || true"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
