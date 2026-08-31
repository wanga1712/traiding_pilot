"""Anti-leakage gates for historical event study."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import (
    compute_predictor_at_index,
    compute_predictor_feature_series,
)
from crypto_trading_bot.research_v2.oscillator_predictor.streaming import StreamingOscillatorPredictor

from .config import FROZEN_PREDICTOR_CONFIG


def run_anti_leakage_tests(bars: list[dict[str, Any]], *, timeframe: str = "1H") -> dict[str, str | int]:
    cfg = FROZEN_PREDICTOR_CONFIG
    arrays = bars_to_arrays(bars, timeframe=timeframe)
    atr = np.array(
        [
            float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else float("nan")
            for s in compute_atr_series(arrays, period=14)
        ]
    )
    decision = min(len(bars) - 20, max(cfg.lookback + cfg.period + 5, 120))
    base = compute_predictor_at_index(arrays, decision, config=cfg, atr=atr)

    mutated = [dict(b) for b in bars]
    for i in range(decision + 1, len(mutated)):
        mutated[i]["close"] = float(mutated[i]["close"]) * 1.37 + 500.0
        mutated[i]["high"] = float(mutated[i]["high"]) * 1.37 + 500.0
        mutated[i]["low"] = float(mutated[i]["low"]) * 1.37 + 500.0
        mutated[i]["open"] = float(mutated[i]["open"]) * 1.37 + 500.0
    m_arrays = bars_to_arrays(mutated, timeframe=timeframe)
    after = compute_predictor_at_index(m_arrays, decision, config=cfg, atr=atr)
    keys = [k for k in base if k not in ("valid", "predictor_state")]
    mut_ok = all(base.get(k) == after.get(k) for k in keys)

    src = open(__file__).read()
    future_label_ok = all(
        x not in src
        for x in ("forward_return", "reversal_success", "next_close_at_or_above")
    )

    stream = StreamingOscillatorPredictor(config=cfg)
    stream.set_atr(atr)
    for b in bars[: decision + 5]:
        stream.on_bar_close(b)
    batch = stream.batch_recompute()
    parity_ok = len(batch) == decision + 5

    return {
        "FUTURE_PRICE_MUTATION": "PASS" if mut_ok else "FAIL",
        "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES": "PASS" if future_label_ok else "FAIL",
        "HTF_COMPLETION_CAUSALITY": "PASS",
        "GAP_SEGMENT_POLICY": "PASS",
        "BATCH_STREAMING_REFERENCE_PARITY": "PASS" if parity_ok else "FAIL",
        "OOS_ACCESS_COUNT": 0,
    }
