"""Mathematically derived warmup metadata — must match runtime first-valid indices."""
from __future__ import annotations

from typing import Any

ATR_PERIOD_DEFAULT = 14


def warmup_bars_from_first_valid(first_valid_index: int) -> int:
    """Registry convention: bar count until first mature index (1-based count)."""
    return first_valid_index + 1


def dma_first_valid_index(*, period: int, display_shift: int, atr_period: int = ATR_PERIOD_DEFAULT) -> int:
    """All DMA outputs including slopes and ATR-normalized distance features."""
    slope_ready = (period + 2) + display_shift
    atr_ready = atr_period - 1  # ATR evaluated at decision bar t
    source_ready = (period - 1) + display_shift
    return max(source_ready, slope_ready, atr_ready)


def standard_stoch_first_valid_index(*, k_period: int, k_smooth: int, d_period: int, display_shift: int) -> int:
    # Slopes/crosses need prior smoothed K/D bar (one bar after core warmup)
    return (k_period + k_smooth + d_period - 2) + display_shift


def dinapoli_stoch_first_valid_index(*, k_period: int, slowing: int, d_period: int, display_shift: int) -> int:
    from crypto_trading_bot.research_v2.indicator_engine.dinapoli_stochastic import dinapoli_stoch_warmup_indices

    return dinapoli_stoch_warmup_indices(k_period=k_period, slowing=slowing, d_period=d_period)[
        "first_full_feature_index"
    ] + display_shift


def standard_macd_first_valid_index(*, slow: int, signal: int, display_shift: int) -> int:
    return (slow + signal - 1) + display_shift


def dinapoli_macd_first_valid_index(*, display_shift: int) -> int:
    return 1 + display_shift


def dma_warmup_bars(*, period: int, display_shift: int, atr_period: int = ATR_PERIOD_DEFAULT) -> int:
    return warmup_bars_from_first_valid(
        dma_first_valid_index(period=period, display_shift=display_shift, atr_period=atr_period)
    )


def standard_stoch_warmup_bars(*, k_period: int, k_smooth: int, d_period: int, display_shift: int) -> int:
    return warmup_bars_from_first_valid(
        standard_stoch_first_valid_index(
            k_period=k_period, k_smooth=k_smooth, d_period=d_period, display_shift=display_shift
        )
    )


def dinapoli_stoch_warmup_bars(*, k_period: int, slowing: int, d_period: int, display_shift: int) -> int:
    return warmup_bars_from_first_valid(
        dinapoli_stoch_first_valid_index(
            k_period=k_period, slowing=slowing, d_period=d_period, display_shift=display_shift
        )
    )


def standard_macd_warmup_bars(*, slow: int, signal: int, display_shift: int) -> int:
    return warmup_bars_from_first_valid(
        standard_macd_first_valid_index(slow=slow, signal=signal, display_shift=display_shift)
    )


def dinapoli_macd_warmup_bars(*, display_shift: int) -> int:
    return warmup_bars_from_first_valid(dinapoli_macd_first_valid_index(display_shift=display_shift))


def registry_warmup_bars(meta: dict[str, Any]) -> int:
    family = meta["family"]
    shift = int(meta.get("display_shift", 0))
    if family == "DMA":
        return dma_warmup_bars(period=int(meta["period"]), display_shift=shift)
    if family == "STOCHASTIC":
        if meta.get("formula_version") == "DINAPOLI_PREFERRED_STOCH_REFERENCE_V1":
            return dinapoli_stoch_warmup_bars(
                k_period=int(meta["k_period"]),
                slowing=int(meta["slowing"]),
                d_period=int(meta["d_period"]),
                display_shift=shift,
            )
        return standard_stoch_warmup_bars(
            k_period=int(meta["k_period"]),
            k_smooth=int(meta["k_smooth"]),
            d_period=int(meta["d_period"]),
            display_shift=shift,
        )
    if family == "MACD":
        if meta.get("formula_version") == "DINAPOLI_MACD_REFERENCE_V1":
            return dinapoli_macd_warmup_bars(display_shift=shift)
        return standard_macd_warmup_bars(
            slow=int(meta["slow"]), signal=int(meta["signal"]), display_shift=shift
        )
    if family == "GEOMETRY":
        return 3
    raise KeyError(family)
