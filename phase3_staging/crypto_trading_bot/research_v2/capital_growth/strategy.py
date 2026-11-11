from __future__ import annotations

import numpy as np
import pandas as pd


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def build_decision_frame(
    bars: pd.DataFrame,
    *,
    fast_period: int = 20,
    slow_period: int = 50,
    atr_period: int = 14,
    rule: str = "4h",
) -> pd.DataFrame:
    frame = bars.set_index("open_time").sort_index()
    grouped = frame.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    grouped = grouped.dropna(subset=["open", "high", "low", "close"]).copy()
    grouped["fast"] = grouped["close"].rolling(fast_period, min_periods=fast_period).mean()
    grouped["slow"] = grouped["close"].rolling(slow_period, min_periods=slow_period).mean()
    grouped["atr"] = _atr(grouped, atr_period)
    long_ok = (grouped["close"] > grouped["fast"]) & (grouped["fast"] > grouped["slow"])
    short_ok = (grouped["close"] < grouped["fast"]) & (grouped["fast"] < grouped["slow"])
    grouped["direction"] = np.select([long_ok, short_ok], [1, -1], default=0).astype(int)
    grouped["decision_at"] = grouped.index + pd.Timedelta(rule)
    return grouped.reset_index().rename(columns={"index": "bar_open"})


def execution_events(
    decisions: pd.DataFrame,
    base_times: pd.Series,
) -> list[tuple[int, dict]]:
    times = pd.DatetimeIndex(pd.to_datetime(base_times, utc=True))
    rows: list[tuple[int, dict]] = []
    for row in decisions.itertuples(index=False):
        decision_at = pd.Timestamp(row.decision_at)
        index = int(times.searchsorted(decision_at, side="right"))
        if index >= len(times):
            continue
        rows.append(
            (
                index,
                {
                    "decision_at": decision_at,
                    "direction": int(row.direction),
                    "atr": float(row.atr) if np.isfinite(row.atr) else None,
                    "fast": float(row.fast) if np.isfinite(row.fast) else None,
                    "slow": float(row.slow) if np.isfinite(row.slow) else None,
                    "close": float(row.close),
                    "volume": float(row.volume) if np.isfinite(row.volume) else 0.0,
                },
            )
        )
    return rows
