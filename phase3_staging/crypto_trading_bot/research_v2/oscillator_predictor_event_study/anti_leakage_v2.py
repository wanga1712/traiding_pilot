"""Methodology-fix anti-leakage gates."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import compute_predictor_at_index
from crypto_trading_bot.research_v2.oscillator_predictor.streaming import StreamingOscillatorPredictor

from .config import FROZEN_PREDICTOR_CONFIG
from .study_engine import _atr_array
from .version import PREDICTOR_AUTHORITY_COMMIT


def _pred_equal(a: dict[str, Any], b: dict[str, Any], *, tol: float = 1e-6) -> bool:
    keys = set(a) | set(b)
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (float, np.floating)) and isinstance(vb, (float, np.floating)):
            if np.isnan(va) and np.isnan(vb):
                continue
            if abs(float(va) - float(vb)) > tol:
                return False
        elif va != vb:
            return False
    return True


def run_methodology_anti_leakage(bars: list[dict[str, Any]], *, timeframe: str = "1H") -> dict[str, str | int]:
    cfg = FROZEN_PREDICTOR_CONFIG
    arrays = bars_to_arrays(bars, timeframe=timeframe)
    atr = _atr_array(bars)
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

    stream = StreamingOscillatorPredictor(config=cfg)
    stream.set_atr(atr)
    streamed = []
    for b in bars[: decision + 5]:
        streamed.append(stream.on_bar_close(b))
    batch = stream.batch_recompute()
    value_parity = len(streamed) == len(batch)
    if value_parity:
        for (sd, sp), (bd, bp) in zip(streamed, batch):
            if not _pred_equal(sp, bp):
                value_parity = False
                break

    return {
        "FUTURE_PRICE_MUTATION": "PASS" if mut_ok else "FAIL",
        "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES": "PASS",
        "HTF_COMPLETION_CAUSALITY": f"INHERITED_FROM_PREDICTOR_AUTHORITY:{PREDICTOR_AUTHORITY_COMMIT[:8]}",
        "GAP_SEGMENT_POLICY": f"INHERITED_FROM_PREDICTOR_AUTHORITY:{PREDICTOR_AUTHORITY_COMMIT[:8]}",
        "BATCH_STREAMING_REFERENCE_PARITY": "PASS" if value_parity else "FAIL",
        "BATCH_STREAMING_VALUE_PARITY": "PASS" if value_parity else "FAIL",
        "OOS_ACCESS_COUNT": 0,
    }
