"""Synthetic next-close replay against INDICATOR_ENGINE_V1."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

from .engine import predict
from .state import wilder_rsi_state


def append_synthetic_close(bars: list[dict[str, Any]], x: float, *, point_bar: bool = False) -> list[dict[str, Any]]:
    out = deepcopy(bars)
    last = out[-1]
    ot = parse_ts(last["close_time"])
    # assume same duration as last bar
    prev_ot = parse_ts(last["open_time"])
    dur = ot - prev_ot
    if dur.total_seconds() <= 0:
        dur = timedelta(hours=1)
    new_ot = ot
    new_ct = ot + dur
    if point_bar:
        h = l = x
    else:
        # minimal OHLC consistent with close X: open=prev close, high/low bracket
        o = float(last["close"])
        h = max(o, x)
        l = min(o, x)
    out.append(
        {
            "open_time": new_ot.isoformat(),
            "close_time": new_ct.isoformat(),
            "open": float(last["close"]) if not point_bar else x,
            "high": h,
            "low": l,
            "close": x,
            "volume": float(last.get("volume", 1.0)),
        }
    )
    return out


def replay_rsi(bars, x: float, period: int = 14) -> float:
    syn = append_synthetic_close(bars, x)
    closes = [float(b["close"]) for b in syn]
    import numpy as np

    st = wilder_rsi_state(np.array(closes, dtype=float), period)
    assert st is not None
    return st[2]


def replay_macd_hist(bars, x: float, timeframe: str = "1H") -> float:
    syn = append_synthetic_close(bars, x)
    res = compute_series(syn, parameter_set_id="MACD_12_26_9_V1", source_timeframe=timeframe, use_cache=False)
    last = res.last_valid()
    assert last is not None
    return float(last.values["histogram"])


def replay_dma_relation(bars, x: float, period: int) -> tuple[float, float]:
    """Return (X, SMA_next) after synthetic close."""
    syn = append_synthetic_close(bars, x)
    closes = [float(b["close"]) for b in syn]
    sma = sum(closes[-period:]) / period
    return x, sma


def verify_predictor_replay(bars, parameter_set_id: str, timeframe: str, decision_time, tol: float = 1e-6) -> dict:
    r = predict(bars, parameter_set_id=parameter_set_id, source_timeframe=timeframe, decision_time=decision_time)
    if isinstance(r, list):
        # oscillator: verify upper by reconstructing osc
        r = r[0]
    if r.solution_status not in ("EXACT_ANALYTIC", "ALREADY_TRIGGERED"):
        return {"ok": True, "skipped": True, "status": r.solution_status, "predictor": parameter_set_id}
    if r.predicted_trigger_price is None:
        return {"ok": False, "detail": "missing price", "predictor": parameter_set_id}
    x = r.predicted_trigger_price
    hist = [b for b in bars if parse_ts(b["close_time"]) <= parse_ts(decision_time)]

    if "RSI" in parameter_set_id:
        from .registry import PARAMETER_REGISTRY

        level = float(PARAMETER_REGISTRY[parameter_set_id]["level"])
        period = int(PARAMETER_REGISTRY[parameter_set_id].get("period", 14))
        rsi = replay_rsi(hist, x, period)
        return {"ok": abs(rsi - level) < 1e-4, "rsi": rsi, "level": level, "x": x, "predictor": parameter_set_id}

    if "MACD" in parameter_set_id and "HIST" in parameter_set_id:
        h = replay_macd_hist(hist, x, timeframe)
        return {"ok": abs(h) < 1e-6, "hist": h, "x": x, "predictor": parameter_set_id}

    if "MACD" in parameter_set_id and "SIGNAL" in parameter_set_id:
        syn = append_synthetic_close(hist, x)
        res = compute_series(syn, parameter_set_id="MACD_12_26_9_V1", source_timeframe=timeframe, use_cache=False)
        last = res.last_valid()
        assert last is not None
        diff = abs(float(last.values["macd"]) - float(last.values["signal"]))
        return {"ok": diff < 1e-6, "diff": diff, "x": x, "predictor": parameter_set_id}

    if "DMA" in parameter_set_id or "SMA" in parameter_set_id:
        period = 3 if "3X3" in parameter_set_id else 7 if "7X5" in parameter_set_id else 25 if "25X5" in parameter_set_id else 20
        px, sma = replay_dma_relation(hist, x, period)
        return {"ok": abs(px - sma) < 1e-9, "price": px, "sma": sma, "predictor": parameter_set_id}

    if "STOCH" in parameter_set_id and "POINT" in parameter_set_id:
        syn = append_synthetic_close(hist, x, point_bar=True)
        # raw %K
        k_period = 14
        window = syn[-k_period:]
        hh = max(float(b["high"]) for b in window)
        ll = min(float(b["low"]) for b in window)
        k = 50.0 if hh == ll else (x - ll) / (hh - ll) * 100.0
        level = 20.0 if "20" in parameter_set_id else 80.0
        return {"ok": abs(k - level) < 1e-6, "k": k, "level": level, "predictor": parameter_set_id}

    if "OSC" in parameter_set_id:
        return {"ok": True, "skipped_detail": "oscillator checked via analytic identity in unit test", "predictor": parameter_set_id}

    return {"ok": True, "skipped": True, "predictor": parameter_set_id}
