"""Causal directional signal generation — no true-C inputs."""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.inverse_predictors.engine import predict

from .config import TF_BAR_SECONDS


def _sid(candidate_id: str, signal_time: str, direction: str) -> str:
    h = hashlib.sha1(f"{candidate_id}|{signal_time}|{direction}".encode()).hexdigest()[:20]
    return f"sig_{h}"


def _emit(
    rows: list[dict[str, Any]],
    *,
    candidate_id: str,
    signal_time: Any,
    signal_price: float,
    direction: str,
    decision_tf: str,
    calculated_at: Any,
    available_at: Any,
) -> None:
    st = signal_time if isinstance(signal_time, str) else parse_ts(signal_time).isoformat()
    ca = calculated_at if isinstance(calculated_at, str) else parse_ts(calculated_at).isoformat()
    aa = available_at if isinstance(available_at, str) else parse_ts(available_at).isoformat()
    rows.append(
        {
            "signal_id": _sid(candidate_id, st, direction),
            "candidate_id": candidate_id,
            "signal_time": st,
            "signal_price": float(signal_price),
            "signal_direction": direction,
            "decision_tf": decision_tf,
            "calculated_at": ca,
            "available_at": aa,
        }
    )


def generate_price_baseline_signals(
    bars: list[dict[str, Any]],
    *,
    candidate_id: str,
    kind: str,
    decision_tf: str,
    scan_start_iso: str | None = None,
) -> list[dict[str, Any]]:
    closes = np.array([float(b["close"]) for b in bars], dtype=float)
    highs = np.array([float(b["high"]) for b in bars], dtype=float)
    lows = np.array([float(b["low"]) for b in bars], dtype=float)
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None

    for i in range(1, len(bars)):
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        direction = None
        if kind == "ONE_BAR_DIRECTION_CHANGE":
            d0 = np.sign(closes[i - 1] - closes[i - 2]) if i >= 2 else 0
            d1 = np.sign(closes[i] - closes[i - 1])
            if d0 != 0 and d1 != 0 and d0 != d1:
                direction = "UP" if d1 > 0 else "DOWN"
        elif kind == "CLOSE_ABOVE_PREVIOUS_HIGH":
            if closes[i] > highs[i - 1]:
                direction = "UP"
            elif closes[i] < lows[i - 1]:
                direction = "DOWN"
        elif kind == "N3_BAR_EXTREME_BREAK" and i >= 3:
            if closes[i] > np.max(highs[i - 3 : i]):
                direction = "UP"
            elif closes[i] < np.min(lows[i - 3 : i]):
                direction = "DOWN"
        elif kind == "N5_BAR_EXTREME_BREAK" and i >= 5:
            if closes[i] > np.max(highs[i - 5 : i]):
                direction = "UP"
            elif closes[i] < np.min(lows[i - 5 : i]):
                direction = "DOWN"
        elif kind == "SHORT_TERM_SLOPE_SIGN_CHANGE" and i >= 3:
            s0 = closes[i - 1] - closes[i - 3]
            s1 = closes[i] - closes[i - 2]
            if s0 != 0 and s1 != 0 and np.sign(s0) != np.sign(s1):
                direction = "UP" if s1 > 0 else "DOWN"
        if direction:
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=bars[i]["close_time"],
                signal_price=closes[i],
                direction=direction,
                decision_tf=decision_tf,
                calculated_at=bars[i]["close_time"],
                available_at=bars[i]["close_time"],
            )
    return rows


def generate_indicator_pair_signals(
    bars: list[dict[str, Any]],
    *,
    candidate_id: str,
    parameter_set_id: str,
    up_primitive: str,
    down_primitive: str,
    decision_tf: str,
    scan_start_iso: str | None = None,
) -> list[dict[str, Any]]:
    result = compute_series(bars, parameter_set_id=parameter_set_id, source_timeframe=decision_tf)
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    for i, sample in enumerate(result.samples):
        if not sample.valid:
            continue
        ct = parse_ts(sample.available_at)
        if scan_start and ct < scan_start:
            continue
        prim = sample.signal_primitives or {}
        direction = None
        if prim.get(up_primitive) is True:
            direction = "UP"
        elif prim.get(down_primitive) is True:
            direction = "DOWN"
        if direction:
            price = float(bars[i]["close"])
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=sample.available_at,
                signal_price=price,
                direction=direction,
                decision_tf=decision_tf,
                calculated_at=sample.calculated_at,
                available_at=sample.available_at,
            )
    return rows


def _trigger_price(result) -> float | None:
    if result is None:
        return None
    results = result if isinstance(result, list) else [result]
    bad = {
        "UNSUPPORTED_V1",
        "REQUIRES_INTRABAR_ASSUMPTION",
        "INSUFFICIENT_HISTORY",
        "NO_REAL_SOLUTION",
        "NO_SOLUTION",
        "INVALID",
    }
    for r in results:
        tp = getattr(r, "predicted_trigger_price", None)
        status = str(getattr(r, "solution_status", ""))
        if tp is None or status in bad:
            continue
        return float(tp)
    return None


def generate_predictor_trigger_signals(
    bars: list[dict[str, Any]],
    *,
    candidate_id: str,
    up_param: str,
    down_param: str,
    decision_tf: str,
    scan_start_iso: str | None = None,
    stride: int = 1,
    start_index: int | None = None,
) -> list[dict[str, Any]]:
    """
    Versioned causal crossing:
      at bar i store threshold from predict(... decision_time=close_i)
      at bar i+1, if close crosses the PRIOR bar's threshold, emit signal.
    Never apply the latest threshold retrospectively to older prices.
    """
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    n = len(bars)
    if n < 3:
        return rows

    i_begin = max(1, start_index or 0)
    up_thr = [None] * n
    down_thr = [None] * n
    indices = list(range(max(0, i_begin - 1), n, max(1, stride)))
    if indices[-1] != n - 1:
        indices.append(n - 1)

    last_up = last_down = None
    idx_set = set(indices)
    for i in range(max(0, i_begin - 1), n):
        if i in idx_set:
            hist = bars[: i + 1]
            decision = bars[i]["close_time"]
            try:
                up_res = predict(hist, parameter_set_id=up_param, source_timeframe=decision_tf, decision_time=decision)
                last_up = _trigger_price(up_res)
            except Exception:  # noqa: BLE001
                last_up = None
            if down_param != up_param:
                try:
                    down_res = predict(
                        hist, parameter_set_id=down_param, source_timeframe=decision_tf, decision_time=decision
                    )
                    last_down = _trigger_price(down_res)
                except Exception:  # noqa: BLE001
                    last_down = None
            else:
                last_down = last_up
        up_thr[i] = last_up
        down_thr[i] = last_down

    for i in range(max(1, i_begin), n):
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        prev_close = float(bars[i - 1]["close"])
        close = float(bars[i]["close"])
        tu = up_thr[i - 1]
        if tu is not None and prev_close < tu <= close:
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=bars[i]["close_time"],
                signal_price=close,
                direction="UP",
                decision_tf=decision_tf,
                calculated_at=bars[i]["close_time"],
                available_at=bars[i]["close_time"],
            )
        td = down_thr[i - 1]
        if td is not None and prev_close > td >= close:
            if not (tu is not None and tu == td and prev_close < tu <= close):
                _emit(
                    rows,
                    candidate_id=candidate_id,
                    signal_time=bars[i]["close_time"],
                    signal_price=close,
                    direction="DOWN",
                    decision_tf=decision_tf,
                    calculated_at=bars[i]["close_time"],
                    available_at=bars[i]["close_time"],
                )
    return rows


def expected_direction_for_pivot(pivot_type: str) -> str:
    """HIGH → expect DOWN next leg; LOW → expect UP."""
    return "DOWN" if pivot_type == "HIGH" else "UP"


def years_covered(signal_times: Iterable[str]) -> float:
    times = sorted(parse_ts(t) for t in signal_times)
    if len(times) < 2:
        return 1.0 / 365.25
    sec = (times[-1] - times[0]).total_seconds()
    return max(sec / (365.25 * 24 * 3600), 1.0 / 365.25)


def bar_delay(seconds: float, decision_tf: str) -> float:
    return seconds / float(TF_BAR_SECONDS[decision_tf])
