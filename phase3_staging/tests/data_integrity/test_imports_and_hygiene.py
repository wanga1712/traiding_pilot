from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from crypto_trading_bot.research_v2.annotations.persistence import S7PostgresAnnotationStore

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "module",
    [
        "crypto_trading_bot.research_v2.resampling",
        "crypto_trading_bot.research_v2.annotations",
        "crypto_trading_bot.research_v2.zigzag.classic",
        "crypto_trading_bot.research_v2.visualization.chart_engine",
        "crypto_trading_bot.research_v2.visualization.dinapoli_live",
        "crypto_trading_bot.research_v2.visualization.zigzag_live",
        "crypto_trading_bot.research_v2.market_data.bars_service",
        "crypto_trading_bot.research_v2.visualization.expert_app",
    ],
)
def test_restored_modules_import(module: str) -> None:
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize(
    "path",
    [
        "api_keys.env",
        "crypto_trading_bot/private_key.pem",
        "data/training_dataset.parquet",
        "logs/checkpoint.pt",
        "app.log",
        ".repair_stage_s13/resampling/resampler.py",
    ],
)
def test_secret_and_runtime_paths_are_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "--", path],
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not ignored"


def test_dependency_manifests_are_versioned() -> None:
    core = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    tests = (REPO_ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    for package in ("numpy==", "pandas==", "pyarrow==", "dash==", "plotly==", "Flask=="):
        assert package in core
    assert "pytest==" in tests


def test_annotation_transport_is_bounded_and_verified(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Mock()

    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.annotations.persistence.subprocess.run",
        fake_run,
    )
    store = S7PostgresAnnotationStore(
        host="wanga@s7",
        key=tmp_path / "id_key",
        timeout_seconds=17,
    )
    store.save(
        {
            "annotation_id": "a1",
            "symbol": "ETHUSDT",
            "timeframe": "4H",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-01-02T00:00:00Z",
            "created_at": "2024-01-02T01:00:00Z",
            "notes": "",
            "points": [
                {
                    "point_index": 0,
                    "timestamp": "2024-01-01T00:00:00Z",
                    "price": "100",
                    "snap_source": "NONE",
                }
            ],
        }
    )
    command, kwargs = calls[0]
    assert command[:3] == ["ssh", "-i", str(tmp_path / "id_key")]
    assert "BatchMode=yes" in command
    assert "ConnectTimeout=15" in command
    assert "StrictHostKeyChecking=no" not in command
    assert kwargs["timeout"] == 17


def test_restored_code_has_no_legacy_ssh_endpoint_or_host_bypass() -> None:
    roots = [
        REPO_ROOT / "phase3_staging/crypto_trading_bot/research_v2/annotations",
        REPO_ROOT / "phase3_staging/crypto_trading_bot/research_v2/dinapoli",
        REPO_ROOT / "phase3_staging/crypto_trading_bot/research_v2/visualization",
        REPO_ROOT / "phase3_staging/crypto_trading_bot/research_v2/zigzag",
    ]
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "10.8.0." not in text, path
            assert "StrictHostKeyChecking=no" not in text, path
