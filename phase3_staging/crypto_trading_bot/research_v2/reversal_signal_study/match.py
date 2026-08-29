"""Retrospective signal↔event matching — separate from causal generation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

from .config import MAX_DELAY_SECONDS, TIMELINESS_BARS, TIMELINESS_SECONDS, TF_BAR_SECONDS
from .signals import expected_direction_for_pivot


def match_signals_to_events(
    signals: pd.DataFrame,
    events: pd.DataFrame,
    *,
    decision_tf: str,
) -> pd.DataFrame:
    """
    Call once per candidate_id (first-signal claim is candidate-local).

    MATCHED_POST_C / REPEAT_POST_C / PRE_C_WARNING / UNMATCHED — see WIP.
    """
    if signals.empty:
        return pd.DataFrame()

    max_delay = float(MAX_DELAY_SECONDS[decision_tf])
    bar_sec = float(TF_BAR_SECONDS[decision_tf])
    ev = events.copy()
    for col in ("true_pivot_time", "next_pivot_time", "previous_pivot_time"):
        ev[col] = pd.to_datetime(ev[col], utc=True)
    ev["expected_dir"] = ev["pivot_type"].map(expected_direction_for_pivot)
    ev["event_id"] = ev["event_id"].astype(str)

    sig = signals.copy()
    sig["signal_time"] = pd.to_datetime(sig["signal_time"], utc=True)

    frames: list[pd.DataFrame] = []
    first_claimed: set[str] = set()

    for direction, sdir in sig.groupby("signal_direction", sort=False):
        edir = ev[ev["expected_dir"] == direction].sort_values("true_pivot_time")
        if edir.empty:
            frames.append(_finalize(_unmatched_base(sdir), decision_tf, bar_sec))
            continue

        left = sdir.sort_values("signal_time")
        post = pd.merge_asof(
            left,
            edir,
            left_on="signal_time",
            right_on="true_pivot_time",
            direction="backward",
        )
        delay = (post["signal_time"] - post["true_pivot_time"]).dt.total_seconds()
        post_ok = (
            post["event_id"].notna()
            & post["next_pivot_time"].notna()
            & (post["signal_time"] < post["next_pivot_time"])
            & (delay >= 0)
            & (delay <= max_delay)
        )

        hit = post.loc[post_ok].copy()
        rem = post.loc[~post_ok, list(sdir.columns)]

        if not hit.empty:
            hit["_delay"] = delay.loc[hit.index]
            hit = hit.sort_values("signal_time")
            mtypes = []
            firsts = []
            for eid in hit["event_id"].astype(str):
                if eid not in first_claimed:
                    first_claimed.add(eid)
                    mtypes.append("MATCHED_POST_C")
                    firsts.append(True)
                else:
                    mtypes.append("REPEAT_POST_C")
                    firsts.append(False)
            hit["match_type"] = mtypes
            hit["is_first_for_event"] = firsts
            hit["delay_seconds"] = hit["_delay"]
            hit["pre_c_lead_seconds"] = np.nan
            frames.append(_finalize(_matched_base(hit), decision_tf, bar_sec))

        if rem.empty:
            continue

        pre = pd.merge_asof(
            rem.sort_values("signal_time"),
            edir,
            left_on="signal_time",
            right_on="true_pivot_time",
            direction="forward",
        )
        lead = (pre["true_pivot_time"] - pre["signal_time"]).dt.total_seconds()
        prev_ok = pre["previous_pivot_time"].isna() | (pre["signal_time"] > pre["previous_pivot_time"])
        pre_ok = pre["event_id"].notna() & (lead > 0) & (lead <= max_delay) & prev_ok

        pre_hit = pre.loc[pre_ok].copy()
        pre_miss = pre.loc[~pre_ok]
        if not pre_hit.empty:
            pre_hit["match_type"] = "PRE_C_WARNING"
            pre_hit["is_first_for_event"] = False
            pre_hit["delay_seconds"] = np.nan
            pre_hit["pre_c_lead_seconds"] = lead.loc[pre_hit.index]
            frames.append(_finalize(_matched_base(pre_hit), decision_tf, bar_sec))
        if not pre_miss.empty:
            frames.append(_finalize(_unmatched_base(pre_miss), decision_tf, bar_sec))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _unmatched_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["signal_id", "candidate_id", "signal_time", "signal_price", "signal_direction", "decision_tf"]].copy()
    out["event_id"] = None
    out["match_type"] = "UNMATCHED"
    out["is_first_for_event"] = False
    out["delay_seconds"] = np.nan
    out["pre_c_lead_seconds"] = np.nan
    out["pivot_type"] = None
    out["source_wave_tf"] = None
    out["true_pivot_time"] = pd.NaT
    out["true_pivot_price"] = np.nan
    out["next_pivot_time"] = pd.NaT
    out["next_pivot_price"] = np.nan
    out["atr_at_pivot_source_tf"] = np.nan
    out["calendar_year"] = np.nan
    return out


def _matched_base(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "signal_id",
        "candidate_id",
        "signal_time",
        "signal_price",
        "signal_direction",
        "decision_tf",
        "event_id",
        "match_type",
        "is_first_for_event",
        "delay_seconds",
        "pre_c_lead_seconds",
        "pivot_type",
        "source_wave_tf",
        "true_pivot_time",
        "true_pivot_price",
        "next_pivot_time",
        "next_pivot_price",
        "atr_at_pivot_source_tf",
        "calendar_year",
    ]
    return df[cols].copy()


def _finalize(df: pd.DataFrame, decision_tf: str, bar_sec: float) -> pd.DataFrame:
    out = df.copy()
    out["direction_match"] = out["match_type"] != "UNMATCHED"
    out["delay_bars"] = out["delay_seconds"].abs() / bar_sec
    sp = out["signal_price"].astype(float)
    cp = out["true_pivot_price"].astype(float)
    np_ = out["next_pivot_price"].astype(float)
    atr = out["atr_at_pivot_source_tf"].astype(float)
    out["price_distance_from_c_abs"] = (sp - cp).abs()
    out["price_distance_from_c_pct"] = ((sp - cp).abs() / cp * 100.0).where(cp != 0)
    out["price_distance_from_c_atr"] = ((sp - cp).abs() / atr).where((atr != 0) & atr.notna())
    total = np_ - cp
    remaining = np_ - sp
    out["next_leg_total_move"] = total
    out["move_already_completed_at_signal"] = sp - cp
    out["remaining_move_at_signal"] = remaining
    out["remaining_wave_fraction"] = (remaining / total).where(total.abs() > 1e-12)
    # adverse pre-C extension
    adv = np.where(
        out["signal_direction"].eq("UP"),
        (sp - cp).clip(lower=0),
        (cp - sp).clip(lower=0),
    )
    out["adverse_extension_after_pre_c"] = np.where(out["match_type"].eq("PRE_C_WARNING"), adv, np.nan)
    out["mae_after_signal_abs"] = np.nan
    out["mfe_after_signal_abs"] = np.nan
    out["mae_after_signal_pct"] = np.nan
    out["mfe_after_signal_pct"] = np.nan
    out["mfe_mae_ratio"] = np.nan
    # Timeliness derived from delay_seconds in metrics; avoid O(n) flag strings.
    out["timeliness_flags"] = None
    for col in ("signal_time", "true_pivot_time", "next_pivot_time"):
        out[col] = out[col].map(
            lambda x: x.isoformat() if pd.notna(x) and hasattr(x, "isoformat") else (None if pd.isna(x) else str(x))
        )
    out["decision_tf"] = decision_tf
    return out


def enrich_matches_with_path_excursion(
    matches: pd.DataFrame,
    bars_by_tf: dict[str, list[dict]],
) -> pd.DataFrame:
    if matches.empty:
        return matches
    out = matches.copy()
    indexed = {}
    for tf, bars in bars_by_tf.items():
        times = np.array([pd.Timestamp(parse_ts(b["close_time"])).value for b in bars], dtype=np.int64)
        highs = np.array([float(b["high"]) for b in bars], dtype=float)
        lows = np.array([float(b["low"]) for b in bars], dtype=float)
        indexed[tf] = (times, highs, lows)

    post = out["match_type"] == "MATCHED_POST_C"
    for i in out.index[post]:
        row = out.loc[i]
        tf = row["decision_tf"]
        if tf not in indexed or not row["next_pivot_time"]:
            continue
        times, highs, lows = indexed[tf]
        st = pd.Timestamp(parse_ts(row["signal_time"])).value
        nt = pd.Timestamp(parse_ts(row["next_pivot_time"])).value
        mask = (times > st) & (times <= nt)
        if not mask.any():
            continue
        px = float(row["signal_price"])
        if row["signal_direction"] == "UP":
            mfe = float(highs[mask].max()) - px
            mae = px - float(lows[mask].min())
        else:
            mfe = px - float(lows[mask].min())
            mae = float(highs[mask].max()) - px
        out.at[i, "mfe_after_signal_abs"] = max(0.0, mfe)
        out.at[i, "mae_after_signal_abs"] = max(0.0, mae)
        out.at[i, "mfe_after_signal_pct"] = max(0.0, mfe) / px * 100.0 if px else np.nan
        out.at[i, "mae_after_signal_pct"] = max(0.0, mae) / px * 100.0 if px else np.nan
        out.at[i, "mfe_mae_ratio"] = (mfe / mae) if mae > 1e-12 else np.nan
    return out
