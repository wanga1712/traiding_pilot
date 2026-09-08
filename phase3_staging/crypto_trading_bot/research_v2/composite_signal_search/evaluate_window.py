"""Evaluate signals vs reversal events over arbitrary DEVELOPMENT windows."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_parameter_search.config import (
    MAX_DELAY_SECONDS as PARENT_MAX_DELAY,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.config import (
    TF_BAR_SECONDS as PARENT_TF_BAR_SECONDS,
)
from crypto_trading_bot.research_v2.reversal_signal_study.match import (
    enrich_matches_with_path_excursion,
    match_signals_to_events,
)
from crypto_trading_bot.research_v2.reversal_signal_study.metrics import compute_directional_metrics
from crypto_trading_bot.research_v2.reversal_signal_study.signals import years_covered

from .config import SAMPLE_LOW_MIN, SAMPLE_NORMAL_MIN
from .oos_guard import assert_events_exclude_oos


def _patch_match_config() -> None:
    import crypto_trading_bot.research_v2.reversal_signal_study.config as rc

    rc.MAX_DELAY_SECONDS.update(PARENT_MAX_DELAY)
    rc.TF_BAR_SECONDS.update(PARENT_TF_BAR_SECONDS)


def sample_class(total_signals: int) -> str:
    if total_signals >= SAMPLE_NORMAL_MIN:
        return "NORMAL"
    if total_signals >= SAMPLE_LOW_MIN:
        return "LOW_SAMPLE"
    return "INSUFFICIENT"


def _empty_metrics(
    *,
    candidate_id: str,
    decision_tf: str,
    direction: str,
    family: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "family": family,
        "role": "DIRECTIONAL",
        "decision_tf": decision_tf,
        "direction": direction,
        "TOTAL_SIGNALS": 0,
        "PRECISION": None,
        "EVENT_RECALL": None,
        "FALSE_POSITIVE_RATE": None,
        "MEDIAN_DELAY_SECONDS": None,
        "MEDIAN_MAE_AFTER_SIGNAL": None,
        "MEDIAN_MFE_AFTER_SIGNAL": None,
        "PRE_C_SIGNAL_RATE": None,
        "sample_flag": "INSUFFICIENT",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "partition_filter": "DISCOVERY+VALIDATION",
    }


def evaluate_signals_window(
    signals: list[dict[str, Any]],
    events: pd.DataFrame,
    *,
    candidate_id: str,
    decision_tf: str,
    direction: str,
    family: str = "COMPOSITE",
    start: datetime | str,
    end: datetime | str,
    valid_bars: int = 0,
    bars: list[dict[str, Any]] | None = None,
    parameter_set_id: str = "",
    event_primitive: str = "COMPOSITE",
    is_reference: bool = False,
) -> dict[str, Any]:
    """
    Evaluate signals against DISCOVERY+VALIDATION events in [start, end).

    Does NOT filter to a single partition label — both DISCOVERY and VALIDATION
    event rows that fall inside the time window are eligible. OOS is refused.
    """
    assert_events_exclude_oos(events, context="evaluate_signals_window")
    _patch_match_config()

    fs = parse_ts(start) if not isinstance(start, datetime) else start
    fe = parse_ts(end) if not isinstance(end, datetime) else end

    if events is None or events.empty:
        return _empty_metrics(
            candidate_id=candidate_id,
            decision_tf=decision_tf,
            direction=direction,
            family=family,
            start=fs,
            end=fe,
        )

    ev = events
    if "partition" in ev.columns:
        bad = ev["partition"].astype(str).str.upper() == "OOS"
        if bool(bad.any()):
            from .oos_guard import assert_oos_locked

            assert_oos_locked(context="evaluate_signals_window saw OOS events")
        # Avoid mandatory full DataFrame.copy when already DISCOVERY+VALIDATION-only.
        if not ev["partition"].isin(["DISCOVERY", "VALIDATION"]).all():
            ev = ev[ev["partition"].isin(["DISCOVERY", "VALIDATION"])]

    # Time-window filter on events — NOT single-partition-only.
    pivot = pd.to_datetime(ev["true_pivot_time"], utc=True)
    ev = ev[(pivot >= fs) & (pivot < fe)]
    if "source_wave_tf" in ev.columns:
        ev = ev[ev["source_wave_tf"] == decision_tf]

    sig_df = pd.DataFrame(signals) if signals else pd.DataFrame()
    if not sig_df.empty:
        st = pd.to_datetime(sig_df["signal_time"], utc=True)
        sig_df = sig_df[(st >= fs) & (st < fe)]
        if "signal_direction" in sig_df.columns:
            sig_df = sig_df[sig_df["signal_direction"] == direction]

    if sig_df.empty:
        return _empty_metrics(
            candidate_id=candidate_id,
            decision_tf=decision_tf,
            direction=direction,
            family=family,
            start=fs,
            end=fe,
        )

    matches = match_signals_to_events(sig_df, ev, decision_tf=decision_tf)
    if bars is not None:
        matches = enrich_matches_with_path_excursion(matches, {decision_tf: bars})

    year_inputs = (
        sig_df["signal_time"].astype(str).tolist()
        if not sig_df.empty
        else ev["true_pivot_time"].astype(str).tolist()
    )
    years = years_covered(year_inputs)
    m = compute_directional_metrics(
        matches,
        ev,
        candidate_id=candidate_id,
        family=family,
        role="DIRECTIONAL",
        decision_tf=decision_tf,
        scanned_from=fs.isoformat(),
        scanned_to=fe.isoformat(),
        valid_decision_bars=valid_bars,
        partition="DEVELOPMENT",
        years=years,
        source_wave_tf=decision_tf,
        pivot_type="LOW" if direction == "UP" else "HIGH",
    )
    n = int(m.get("TOTAL_SIGNALS") or 0)
    m["sample_flag"] = sample_class(n)
    m["direction"] = direction
    m["event_primitive"] = event_primitive
    m["parameter_set_id"] = parameter_set_id
    m["is_reference"] = is_reference
    m["window_start"] = fs.isoformat()
    m["window_end"] = fe.isoformat()
    m["partition_filter"] = "DISCOVERY+VALIDATION"
    return m
