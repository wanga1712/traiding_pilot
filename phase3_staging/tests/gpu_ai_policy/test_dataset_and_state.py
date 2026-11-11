from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.gpu_ai_policy.dataset import _split_rows
from crypto_trading_bot.research_v2.gpu_ai_policy.state import build_canonical_state_features
from crypto_trading_bot.research_v2.gpu_ai_policy.config import DatasetConfig


def test_chronological_splits_apply_purge_and_embargo() -> None:
    decisions = pd.DataFrame(
        {
            "decision_at": pd.to_datetime(
                [
                    "2020-06-20T00:00:00Z",
                    "2020-06-26T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    "2020-12-20T00:00:00Z",
                    "2020-12-26T00:00:00Z",
                    "2021-01-02T00:00:00Z",
                ],
                utc=True,
            )
        }
    )
    config = DatasetConfig(purge_hours=168, embargo_hours=24)
    result = _split_rows(decisions, config)
    assert result.loc[0, "split"] == "TRAIN"
    assert bool(result.loc[0, "training_allowed"])
    assert result.loc[1, "split"] == "TRAIN"
    assert not bool(result.loc[1, "label_complete"])
    assert result.loc[2, "split"] == "SELECTION"
    assert bool(result.loc[2, "training_allowed"])
    assert bool(result.loc[3, "training_allowed"])
    assert not bool(result.loc[4, "label_complete"])
    assert result.loc[5, "split"] == "LOCKED"
    assert not bool(result.loc[5, "training_allowed"])


def test_canonical_state_builder_produces_causal_portfolio_features() -> None:
    hours = 160
    times = pd.date_range("2020-01-01", periods=hours, freq="h", tz="UTC")
    close = 100.0 + np.sin(np.arange(hours) / 8.0) * 3.0
    frame = pd.DataFrame(
        {
            "row_id": np.arange(hours),
            "decision_at": times,
            "open_time": times - pd.Timedelta(hours=1),
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1000.0,
            "sma20": pd.Series(close).rolling(20, min_periods=1).mean().to_numpy(),
            "sma50": pd.Series(close).rolling(50, min_periods=1).mean().to_numpy(),
            "atr14": np.full(hours, 0.5),
            "fwd_return_24h": np.full(hours, 0.001),
            "long_risk_limit_hit_24h": np.zeros(hours, dtype=int),
            "short_risk_limit_hit_24h": np.zeros(hours, dtype=int),
        }
    )
    funding = pd.DataFrame(
        {
            "funding_time": pd.to_datetime([], utc=True),
            "funding_rate": pd.Series(dtype=float),
        }
    )
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        output = Path(temporary)
        audit = build_canonical_state_features(
            decisions=frame,
            output_root=output,
            funding=funding,
        )
        state = pd.read_parquet(output / "portfolio_state_features_v1.parquet")
        assert audit["rows"] == hours
        assert "state_A_HOLD_spot_exposure_fraction" in state.columns
        assert state["state_A_HOLD_spot_exposure_fraction"].notna().all()
        assert (state.filter(like="remaining_thesis_risk_fraction") >= 0).all().all()
