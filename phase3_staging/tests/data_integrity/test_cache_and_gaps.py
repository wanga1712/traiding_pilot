from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from crypto_trading_bot.research_v2.dinapoli_when_reconstruction.signals_ext import (
    dma_signals,
    stoch_obos_signals,
)
from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.cache import fingerprint_bars
from crypto_trading_bot.research_v2.indicator_engine.dma import compute_dma_series
from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample
from crypto_trading_bot.research_v2.market_data import bars_service


def _shift_gap(bars: list[dict], gap_index: int, hours: int = 5) -> list[dict]:
    out = copy.deepcopy(bars)
    for bar in out[gap_index:]:
        open_time = datetime.fromisoformat(bar["open_time"]) + timedelta(hours=hours)
        close_time = datetime.fromisoformat(bar["close_time"]) + timedelta(hours=hours)
        bar["open_time"] = open_time.isoformat()
        bar["close_time"] = close_time.isoformat()
    return out


def test_middle_bar_mutation_invalidates_indicator_cache() -> None:
    bars = make_bars([float(i) for i in range(1, 20)], minutes=60)
    first = compute_series(bars, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=True)
    mutated = copy.deepcopy(bars)
    mutated[-2]["close"] = 999.0
    second = compute_series(mutated, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=True)
    assert fingerprint_bars(bars) != fingerprint_bars(mutated)
    assert first.samples[-1].values["dma"] != second.samples[-1].values["dma"]


def test_dma_does_not_emit_cross_across_gap() -> None:
    bars = _shift_gap(make_bars([1.0, 2.0, 3.0, 5.0, 4.0, 6.0], minutes=60), 3)
    arrays = bars_to_arrays(bars, timeframe="1H")
    samples = compute_dma_series(arrays, period=3, display_shift=0)
    assert samples[5].valid
    assert samples[5].signal_primitives["PRICE_CROSS_UP_DMA"] is False
    rows = dma_signals(
        bars,
        candidate_id="gap-test",
        period=3,
        display_shift=0,
        decision_tf="1H",
    )
    assert rows == []


def test_stochastic_obos_state_resets_after_gap(monkeypatch) -> None:
    bars = _shift_gap(make_bars([10.0] * 6, minutes=60), 3)
    times = [bar["close_time"] for bar in bars]

    def sample(i: int, k: float, d: float) -> IndicatorSample:
        return IndicatorSample(
            calculated_at=datetime.fromisoformat(times[i]),
            available_at=datetime.fromisoformat(times[i]),
            displayed_at=None,
            values={"k": k, "d": d},
            signal_primitives={},
            valid=True,
        )

    samples = [
        sample(0, 30.0, 25.0),
        sample(1, 30.0, 25.0),
        sample(2, 10.0, 15.0),
        sample(3, 25.0, 30.0),
        sample(4, 35.0, 30.0),
        sample(5, 40.0, 35.0),
    ]
    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.dinapoli_when_reconstruction.signals_ext.compute_stochastic_series",
        lambda *args, **kwargs: samples,
    )
    rows = stoch_obos_signals(
        bars,
        candidate_id="gap-state",
        k_period=3,
        k_smooth=1,
        d_period=1,
        display_shift=0,
        oversold=20.0,
        overbought=80.0,
        decision_tf="1H",
        require_obos_state=True,
    )
    assert rows == []


def test_atomic_cache_write_preserves_last_valid_file(monkeypatch, tmp_path) -> None:
    path = tmp_path / "cache.parquet"
    original = pa.table({"value": [1, 2, 3]})
    pq.write_table(original, path)
    before = path.read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(bars_service.pq, "write_table", fail_write)
    with pytest.raises(OSError, match="simulated"):
        bars_service._atomic_write_parquet(pa.table({"value": [9]}), path)
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
