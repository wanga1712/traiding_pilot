"""Classic ZigZag pivot detection for expert-geometry reconstruction."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


PivotKind = Literal["HIGH", "LOW"]


@dataclass(frozen=True, slots=True)
class ZigZagPivot:
    index: int
    timestamp: str
    price: float
    kind: PivotKind
    confirmation_index: int
    confirmation_timestamp: str
    deviation_used: float


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    out = [0.0] * len(closes)
    if not closes:
        return out
    trs: list[float] = []
    prev_close = closes[0]
    for i, (h, l, c) in enumerate(zip(highs, lows, closes)):
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close)) if i else (h - l)
        trs.append(tr)
        prev_close = c
    for i in range(len(trs)):
        if i + 1 < period:
            out[i] = sum(trs[: i + 1]) / (i + 1)
        else:
            out[i] = sum(trs[i + 1 - period : i + 1]) / period
    return out


def _enforce_alternation(pivots: list[ZigZagPivot]) -> list[ZigZagPivot]:
    if not pivots:
        return pivots
    out: list[ZigZagPivot] = [pivots[0]]
    for p in pivots[1:]:
        if p.kind == out[-1].kind:
            if p.kind == "HIGH" and p.price >= out[-1].price:
                out[-1] = p
            elif p.kind == "LOW" and p.price <= out[-1].price:
                out[-1] = p
            continue
        out.append(p)
    return out


def _run_threshold_zigzag(
    candles: list[dict],
    *,
    threshold_fn,
    depth: int,
    backstep: int,
    deviation_label: float,
) -> list[ZigZagPivot]:
    """
    Running-extreme ZigZag with a callable reversal threshold.

    - Alternating HIGH / LOW
    - Unconfirmed extreme replaced when a more extreme candle appears
    - Pivot locked only after reversal >= threshold AND (i - extreme_index) >= depth
    - New pivot index must be >= last.index + backstep
    - Pivot time/price = extreme; confirmation_* = locking bar
    """
    n = len(candles)
    if n < 2:
        return []
    depth = max(1, int(depth))
    backstep = max(0, int(backstep))
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    times = [str(c["open_time_utc"]) for c in candles]

    pivots: list[ZigZagPivot] = []
    ext_high_i = 0
    ext_low_i = 0
    ext_high = highs[0]
    ext_low = lows[0]
    mode: Literal["INIT", "SEEK_HIGH", "SEEK_LOW"] = "INIT"

    for i in range(1, n):
        h, l = highs[i], lows[i]
        thr = float(threshold_fn(i, ext_high, ext_low, h, l))

        if mode == "INIT":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            if (ext_high - ext_low) >= thr and (i - min(ext_high_i, ext_low_i)) >= depth:
                if ext_low_i <= ext_high_i:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_low_i,
                            timestamp=times[ext_low_i],
                            price=ext_low,
                            kind="LOW",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_label,
                        )
                    )
                    mode = "SEEK_HIGH"
                    ext_high_i, ext_high = i, h
                else:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_high_i,
                            timestamp=times[ext_high_i],
                            price=ext_high,
                            kind="HIGH",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_label,
                        )
                    )
                    mode = "SEEK_LOW"
                    ext_low_i, ext_low = i, l
            continue

        if mode == "SEEK_HIGH":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            if (ext_high - l) >= thr and (i - ext_high_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_high_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_high_i,
                        timestamp=times[ext_high_i],
                        price=ext_high,
                        kind="HIGH",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_label,
                    )
                )
                mode = "SEEK_LOW"
                ext_low_i, ext_low = i, l
            continue

        if mode == "SEEK_LOW":
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            if (h - ext_low) >= thr and (i - ext_low_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_low_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_low_i,
                        timestamp=times[ext_low_i],
                        price=ext_low,
                        kind="LOW",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_label,
                    )
                )
                mode = "SEEK_HIGH"
                ext_high_i, ext_high = i, h
            continue

    return _enforce_alternation(pivots)


def classic_percent_zigzag(
    candles: list[dict],
    *,
    deviation_percent: float,
    depth: int = 1,
    backstep: int = 0,
) -> list[ZigZagPivot]:
    if deviation_percent <= 0:
        raise ValueError("deviation_percent must be > 0")
    dev = float(deviation_percent) / 100.0

    def threshold_fn(i, ext_high, ext_low, h, l):
        # Percent of the relevant extreme for the active leg.
        ref = ext_high if ext_high > 0 else 1.0
        # During INIT use mid of range base (ext_low).
        base = ext_low if ext_low > 0 else ref
        return max(base, ref) * dev

    # More precise: SEEK_HIGH uses ext_high * dev, SEEK_LOW uses ext_low * dev.
    # Implement dedicated loop for clarity (percent is primary candidate).
    n = len(candles)
    if n < 2:
        return []
    depth = max(1, int(depth))
    backstep = max(0, int(backstep))
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    times = [str(c["open_time_utc"]) for c in candles]
    pivots: list[ZigZagPivot] = []
    ext_high_i = 0
    ext_low_i = 0
    ext_high = highs[0]
    ext_low = lows[0]
    mode: Literal["INIT", "SEEK_HIGH", "SEEK_LOW"] = "INIT"

    for i in range(1, n):
        h, l = highs[i], lows[i]
        if mode == "INIT":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            move = (ext_high - ext_low) / ext_low if ext_low > 0 else 0.0
            if move >= dev and (i - min(ext_high_i, ext_low_i)) >= depth:
                if ext_low_i <= ext_high_i:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_low_i,
                            timestamp=times[ext_low_i],
                            price=ext_low,
                            kind="LOW",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_percent,
                        )
                    )
                    mode = "SEEK_HIGH"
                    ext_high_i, ext_high = i, h
                else:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_high_i,
                            timestamp=times[ext_high_i],
                            price=ext_high,
                            kind="HIGH",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_percent,
                        )
                    )
                    mode = "SEEK_LOW"
                    ext_low_i, ext_low = i, l
            continue
        if mode == "SEEK_HIGH":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            rev = (ext_high - l) / ext_high if ext_high > 0 else 0.0
            if rev >= dev and (i - ext_high_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_high_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_high_i,
                        timestamp=times[ext_high_i],
                        price=ext_high,
                        kind="HIGH",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_percent,
                    )
                )
                mode = "SEEK_LOW"
                ext_low_i, ext_low = i, l
            continue
        if mode == "SEEK_LOW":
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            rev = (h - ext_low) / ext_low if ext_low > 0 else 0.0
            if rev >= dev and (i - ext_low_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_low_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_low_i,
                        timestamp=times[ext_low_i],
                        price=ext_low,
                        kind="LOW",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_percent,
                    )
                )
                mode = "SEEK_HIGH"
                ext_high_i, ext_high = i, h
            continue
    return _enforce_alternation(pivots)


def classic_percent_zigzag_live(
    candles: list[dict],
    *,
    deviation_percent: float,
    depth: int = 1,
    backstep: int = 0,
) -> dict:
    """
    Same as classic_percent_zigzag, plus the active unconfirmed extreme.

    Returns:
      {
        "confirmed": list[ZigZagPivot],
        "current": None | {index, timestamp, price, kind, confirmed=False},
        "mode": INIT|SEEK_HIGH|SEEK_LOW,
      }
    """
    if deviation_percent <= 0:
        raise ValueError("deviation_percent must be > 0")
    n = len(candles)
    if n < 2:
        return {"confirmed": [], "current": None, "mode": "INIT"}
    dev = float(deviation_percent) / 100.0
    depth = max(1, int(depth))
    backstep = max(0, int(backstep))
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    times = [str(c["open_time_utc"]) for c in candles]
    pivots: list[ZigZagPivot] = []
    ext_high_i = 0
    ext_low_i = 0
    ext_high = highs[0]
    ext_low = lows[0]
    mode: Literal["INIT", "SEEK_HIGH", "SEEK_LOW"] = "INIT"

    for i in range(1, n):
        h, l = highs[i], lows[i]
        if mode == "INIT":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            move = (ext_high - ext_low) / ext_low if ext_low > 0 else 0.0
            if move >= dev and (i - min(ext_high_i, ext_low_i)) >= depth:
                if ext_low_i <= ext_high_i:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_low_i,
                            timestamp=times[ext_low_i],
                            price=ext_low,
                            kind="LOW",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_percent,
                        )
                    )
                    mode = "SEEK_HIGH"
                    ext_high_i, ext_high = i, h
                else:
                    pivots.append(
                        ZigZagPivot(
                            index=ext_high_i,
                            timestamp=times[ext_high_i],
                            price=ext_high,
                            kind="HIGH",
                            confirmation_index=i,
                            confirmation_timestamp=times[i],
                            deviation_used=deviation_percent,
                        )
                    )
                    mode = "SEEK_LOW"
                    ext_low_i, ext_low = i, l
            continue
        if mode == "SEEK_HIGH":
            if h >= ext_high:
                ext_high, ext_high_i = h, i
            rev = (ext_high - l) / ext_high if ext_high > 0 else 0.0
            if rev >= dev and (i - ext_high_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_high_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_high_i,
                        timestamp=times[ext_high_i],
                        price=ext_high,
                        kind="HIGH",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_percent,
                    )
                )
                mode = "SEEK_LOW"
                ext_low_i, ext_low = i, l
            continue
        if mode == "SEEK_LOW":
            if l <= ext_low:
                ext_low, ext_low_i = l, i
            rev = (h - ext_low) / ext_low if ext_low > 0 else 0.0
            if rev >= dev and (i - ext_low_i) >= depth:
                last = pivots[-1] if pivots else None
                if last and (ext_low_i - last.index) < backstep:
                    continue
                pivots.append(
                    ZigZagPivot(
                        index=ext_low_i,
                        timestamp=times[ext_low_i],
                        price=ext_low,
                        kind="LOW",
                        confirmation_index=i,
                        confirmation_timestamp=times[i],
                        deviation_used=deviation_percent,
                    )
                )
                mode = "SEEK_HIGH"
                ext_high_i, ext_high = i, h
            continue

    confirmed = _enforce_alternation(pivots)
    current = None
    if mode == "SEEK_HIGH":
        current = {
            "index": ext_high_i,
            "timestamp": times[ext_high_i],
            "price": float(ext_high),
            "kind": "HIGH",
            "confirmed": False,
        }
    elif mode == "SEEK_LOW":
        current = {
            "index": ext_low_i,
            "timestamp": times[ext_low_i],
            "price": float(ext_low),
            "kind": "LOW",
            "confirmed": False,
        }
    elif mode == "INIT" and n > 0:
        # No confirmed pivots yet — expose provisional extreme of larger move.
        if (ext_high - lows[0]) >= (highs[0] - ext_low):
            current = {
                "index": ext_high_i,
                "timestamp": times[ext_high_i],
                "price": float(ext_high),
                "kind": "HIGH",
                "confirmed": False,
            }
        else:
            current = {
                "index": ext_low_i,
                "timestamp": times[ext_low_i],
                "price": float(ext_low),
                "kind": "LOW",
                "confirmed": False,
            }
    return {"confirmed": confirmed, "current": current, "mode": mode}


def classic_absolute_zigzag(
    candles: list[dict],
    *,
    deviation_abs: float,
    depth: int = 1,
    backstep: int = 0,
) -> list[ZigZagPivot]:
    if deviation_abs <= 0:
        raise ValueError("deviation_abs must be > 0")

    def threshold_fn(i, ext_high, ext_low, h, l):
        return deviation_abs

    return _run_threshold_zigzag(
        candles,
        threshold_fn=threshold_fn,
        depth=depth,
        backstep=backstep,
        deviation_label=deviation_abs,
    )


def classic_atr_zigzag(
    candles: list[dict],
    *,
    atr_mult: float,
    depth: int = 1,
    backstep: int = 0,
    atr_period: int = 14,
    atr_series: list[float] | None = None,
) -> list[ZigZagPivot]:
    if atr_mult <= 0:
        raise ValueError("atr_mult must be > 0")
    if atr_series is None:
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]
        atr = _atr(highs, lows, closes, atr_period)
    else:
        atr = atr_series

    def threshold_fn(i, ext_high, ext_low, h, l):
        return max(atr[i] * atr_mult, 1e-12)

    return _run_threshold_zigzag(
        candles,
        threshold_fn=threshold_fn,
        depth=depth,
        backstep=backstep,
        deviation_label=atr_mult,
    )


def classic_vol_percent_zigzag(
    candles: list[dict],
    *,
    vol_mult: float,
    depth: int = 1,
    backstep: int = 0,
    vol_period: int = 20,
) -> list[ZigZagPivot]:
    """Dynamic percent threshold = K * causal rolling realized volatility (close-to-close)."""
    if vol_mult <= 0:
        raise ValueError("vol_mult must be > 0")
    closes = [float(c["close"]) for c in candles]
    n = len(closes)
    sigma = [0.0] * n
    rets: list[float] = [0.0]
    for i in range(1, n):
        prev = closes[i - 1]
        rets.append(0.0 if prev == 0 else (closes[i] - prev) / prev)
    for i in range(n):
        start = max(1, i + 1 - vol_period)
        window = rets[start : i + 1]
        if len(window) < 2:
            sigma[i] = abs(rets[i])
        else:
            m = sum(window) / len(window)
            var = sum((x - m) ** 2 for x in window) / len(window)
            sigma[i] = var**0.5

    def threshold_fn(i, ext_high, ext_low, h, l):
        px = max(abs(ext_high), abs(ext_low), abs(h), abs(l), 1e-12)
        return max(px * vol_mult * max(sigma[i], 1e-8), 1e-12)

    return _run_threshold_zigzag(
        candles,
        threshold_fn=threshold_fn,
        depth=depth,
        backstep=backstep,
        deviation_label=vol_mult,
    )


def compute_atr_series(candles: list[dict], atr_period: int) -> list[float]:
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    return _atr(highs, lows, closes, atr_period)


def pivots_to_dicts(pivots: list[ZigZagPivot]) -> list[dict]:
    return [asdict(p) for p in pivots]
