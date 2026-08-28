from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DmaPoint:
    computed_at: str
    display_at: str
    value: Decimal


DMA_SPECS = (("DMA 3x3", 3, 3), ("DMA 7x5", 7, 5), ("DMA 25x5", 25, 5))


def displaced_moving_average(candles: list[dict], length: int, displacement: int) -> list[DmaPoint]:
    """Compute a trailing SMA and move only its display coordinate forward."""
    closes = [Decimal(candle["close"]) for candle in candles]
    result: list[DmaPoint] = []
    for index in range(length - 1, len(candles) - displacement):
        value = sum(closes[index - length + 1:index + 1], Decimal(0)) / Decimal(length)
        result.append(DmaPoint(
            computed_at=candles[index]["close_time_utc"],
            display_at=candles[index + displacement]["open_time_utc"],
            value=value,
        ))
    return result


def dma_state(candles: list[dict], length: int, displacement: int) -> str:
    points = displaced_moving_average(candles, length, displacement)
    if not points:
        return "INSUFFICIENT_DATA"
    close = Decimal(candles[-1]["close"])
    return "PRICE_ABOVE" if close > points[-1].value else "PRICE_BELOW" if close < points[-1].value else "PRICE_EQUAL"
