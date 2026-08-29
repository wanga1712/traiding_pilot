"""Display-aligned signals including Stoch OB/OS composite semantics."""
from __future__ import annotations

import hashlib
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.dma import compute_dma_series
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.stochastic import compute_stochastic_series


def _sid(candidate_id: str, signal_time: str, direction: str) -> str:
    h = hashlib.sha1(f"{candidate_id}|{signal_time}|{direction}".encode()).hexdigest()[:20]
    return f"sig_{h}"


def _emit(rows, *, candidate_id, signal_time, signal_price, direction, decision_tf, calculated_at, available_at, family, meta=None):
    st = signal_time if isinstance(signal_time, str) else parse_ts(signal_time).isoformat()
    ca = calculated_at if isinstance(calculated_at, str) else parse_ts(calculated_at).isoformat()
    aa = available_at if isinstance(available_at, str) else parse_ts(available_at).isoformat()
    row = {
        "signal_id": _sid(candidate_id, st, direction),
        "candidate_id": candidate_id,
        "signal_time": st,
        "signal_price": float(signal_price),
        "signal_direction": direction,
        "decision_tf": decision_tf,
        "calculated_at": ca,
        "available_at": aa,
        "family": family,
    }
    if meta:
        row.update(meta)
    rows.append(row)


def _src(i: int, shift: int) -> int:
    return i - max(0, int(shift))


def dma_signals(bars, *, candidate_id, period, display_shift, decision_tf, scan_start_iso=None):
    arrays = bars_to_arrays(bars, timeframe=decision_tf)
    samples = compute_dma_series(arrays, period=period, display_shift=display_shift)
    rows = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    shift = int(display_shift)
    for i in range(1, len(bars)):
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        src, src_prev = _src(i, shift), _src(i - 1, shift)
        if src < 0 or src_prev < 0:
            continue
        if not samples[src].valid or not samples[src_prev].valid:
            continue
        dma, dma_prev = samples[src].values.get("dma"), samples[src_prev].values.get("dma")
        if dma is None or dma_prev is None:
            continue
        price, prev = float(arrays.close[i]), float(arrays.close[i - 1])
        direction = None
        if prev <= float(dma_prev) and price > float(dma):
            direction = "UP"
        elif prev >= float(dma_prev) and price < float(dma):
            direction = "DOWN"
        if direction:
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=bars[i]["close_time"],
                signal_price=price,
                direction=direction,
                decision_tf=decision_tf,
                calculated_at=samples[src].calculated_at,
                available_at=bars[i]["close_time"],
                family="DMA",
                meta={"source_index": src, "display_shift": shift, "period": period},
            )
    return rows


def stoch_obos_signals(
    bars,
    *,
    candidate_id,
    k_period,
    k_smooth,
    d_period,
    display_shift,
    oversold,
    overbought,
    decision_tf,
    scan_start_iso=None,
    require_obos_state: bool = True,
):
    """
    LOW/UP: was oversold (K<=OS recently or prior) AND (K cross up D OR K exits OS).
    HIGH/DOWN: was overbought AND (K cross down D OR K exits OB).
    If require_obos_state=False: plain K×D cross (display-aligned).
    """
    arrays = bars_to_arrays(bars, timeframe=decision_tf)
    samples = compute_stochastic_series(
        arrays,
        k_period=k_period,
        k_smooth=k_smooth,
        d_period=d_period,
        display_shift=display_shift,
        overbought=overbought,
        oversold=oversold,
    )
    rows = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    shift = int(display_shift)
    was_os = False
    was_ob = False
    for i in range(1, len(bars)):
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        src, src_prev = _src(i, shift), _src(i - 1, shift)
        if src < 0 or src_prev < 0:
            continue
        if not samples[src].valid or not samples[src_prev].valid:
            continue
        k = samples[src].values.get("k")
        d = samples[src].values.get("d")
        k_prev = samples[src_prev].values.get("k")
        d_prev = samples[src_prev].values.get("d")
        if None in (k, d, k_prev, d_prev):
            continue
        kv, dv = float(k), float(d)
        kpv, dpv = float(k_prev), float(d_prev)
        if kv <= oversold:
            was_os = True
        if kv >= overbought:
            was_ob = True
        # clear when opposite extreme
        if kv >= overbought:
            was_os = False
        if kv <= oversold:
            was_ob = False

        cross_up = kpv <= dpv and kv > dv
        cross_dn = kpv >= dpv and kv < dv
        exit_os = kpv <= oversold and kv > oversold
        exit_ob = kpv >= overbought and kv < overbought

        direction = None
        if require_obos_state:
            if was_os and (cross_up or exit_os):
                direction = "UP"
                was_os = False
            elif was_ob and (cross_dn or exit_ob):
                direction = "DOWN"
                was_ob = False
        else:
            if cross_up:
                direction = "UP"
            elif cross_dn:
                direction = "DOWN"
        if direction:
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=bars[i]["close_time"],
                signal_price=float(bars[i]["close"]),
                direction=direction,
                decision_tf=decision_tf,
                calculated_at=samples[src].calculated_at,
                available_at=bars[i]["close_time"],
                family="STOCH",
                meta={
                    "obos_mode": require_obos_state,
                    "oversold": oversold,
                    "overbought": overbought,
                    "display_shift": shift,
                },
            )
    return rows


def macd_signals(bars, *, candidate_id, fast, slow, signal, display_shift, decision_tf, scan_start_iso=None):
    arrays = bars_to_arrays(bars, timeframe=decision_tf)
    samples = compute_macd_series(arrays, fast=fast, slow=slow, signal=signal, display_shift=display_shift)
    rows = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    shift = int(display_shift)
    for i in range(1, len(bars)):
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        src, src_prev = _src(i, shift), _src(i - 1, shift)
        if src < 0 or src_prev < 0:
            continue
        if not samples[src].valid or not samples[src_prev].valid:
            continue
        macd = samples[src].values.get("macd")
        sig = samples[src].values.get("signal")
        macd_prev = samples[src_prev].values.get("macd")
        sig_prev = samples[src_prev].values.get("signal")
        if None in (macd, sig, macd_prev, sig_prev):
            continue
        direction = None
        if float(macd_prev) <= float(sig_prev) and float(macd) > float(sig):
            direction = "UP"
        elif float(macd_prev) >= float(sig_prev) and float(macd) < float(sig):
            direction = "DOWN"
        if direction:
            _emit(
                rows,
                candidate_id=candidate_id,
                signal_time=bars[i]["close_time"],
                signal_price=float(bars[i]["close"]),
                direction=direction,
                decision_tf=decision_tf,
                calculated_at=samples[src].calculated_at,
                available_at=bars[i]["close_time"],
                family="MACD",
                meta={"display_shift": shift, "preset_class": "PROJECT_EXPERIMENTAL" if display_shift else "STANDARD"},
            )
    return rows
