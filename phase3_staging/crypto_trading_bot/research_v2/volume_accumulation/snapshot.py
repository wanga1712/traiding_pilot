"""Multi-TF causal market context snapshot API."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from crypto_trading_bot.research_v2.reversal_events.anti_leakage import get_event_history

from .compute import compute_at_decision_time
from .version import FEATURE_ENGINE_VERSION


DEFAULT_TFS = ("5m", "15m", "1H", "4H")


def compute_market_context(
    event_bars_by_tf: Mapping[str, Sequence[dict[str, Any]]],
    *,
    event_id: str,
    decision_time: Any,
    timeframes: Sequence[str] = DEFAULT_TFS,
    parameter_set_id: str = "CONTEXT_BUNDLE_V1",
) -> dict[str, Any]:
    """
    Causal snapshot across timeframes at decision_time.

    Each TF uses only closed bars with close_time <= decision_time via get_event_history.
    """
    out: dict[str, Any] = {
        "feature_engine_version": FEATURE_ENGINE_VERSION,
        "event_id": event_id,
        "decision_time": str(decision_time),
        "parameter_set_id": parameter_set_id,
        "timeframes": {},
    }
    for tf in timeframes:
        bars = list(event_bars_by_tf.get(tf, []))
        hist = get_event_history(
            bars,
            event_id=event_id,
            timeframe=tf,
            decision_time=decision_time,
            require_closed=True,
        )
        sample = compute_at_decision_time(
            hist,
            parameter_set_id=parameter_set_id,
            source_timeframe=tf,
            decision_time=decision_time,
        )
        out["timeframes"][tf] = None if sample is None else {
            "available_at": sample.available_at.isoformat(),
            "calculated_at": sample.calculated_at.isoformat(),
            "valid": sample.valid,
            "invalid_reason": sample.invalid_reason,
            "values": sample.values,
            "history_bars": len(hist),
        }
    return out
