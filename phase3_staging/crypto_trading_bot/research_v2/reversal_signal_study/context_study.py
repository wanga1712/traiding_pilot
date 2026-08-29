"""Context / enrichment event study — non-directional features."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.predictor_confluence.engine import compute_predictor_confluence
from crypto_trading_bot.research_v2.volume_accumulation.compute import compute_feature_series

from .metrics import simple_lift_pvalue


def _feature_series_values(
    bars: list[dict[str, Any]],
    *,
    parameter_set_id: str,
    feature_id: str,
    decision_tf: str,
    event_times: list | None = None,
) -> tuple[list[Any], list[float | None]]:
    times = []
    vals = []
    if parameter_set_id.startswith("CONF_"):
        # Event-centered + random baseline sampling (confluence is expensive).
        sample_idx = set()
        n = len(bars)
        if event_times:
            bar_ts = [parse_ts(b["close_time"]) for b in bars]
            for et in event_times:
                et2 = et.to_pydatetime() if hasattr(et, "to_pydatetime") else parse_ts(et)
                # nearest bar index
                best_i, best_d = None, 1e18
                for i, bt in enumerate(bar_ts):
                    d = abs((bt - et2).total_seconds())
                    if d < best_d:
                        best_d, best_i = d, i
                if best_i is not None and best_d <= 2 * 3600:
                    for j in range(max(0, best_i - 2), min(n, best_i + 3)):
                        sample_idx.add(j)
        rng = np.random.default_rng(42)
        k = min(800, max(100, n // 50))
        sample_idx.update(int(i) for i in rng.choice(n, size=min(k, n), replace=False))
        bars_by_tf = {decision_tf: bars}
        for i in sorted(sample_idx):
            b = bars[i]
            try:
                snap = compute_predictor_confluence(
                    bars_by_tf,
                    decision_time=b["close_time"],
                    timeframes=[decision_tf],
                    confluence_parameter_set=parameter_set_id,
                )
                feats = snap["within_tf"]["RAW"][decision_tf]["features"]
                if feature_id.startswith("CROSS_TF_"):
                    feats = snap.get("cross_tf", {}).get("RAW") or {}
                v = feats.get(feature_id)
                times.append(b["close_time"])
                vals.append(float(v) if v is not None and v == v else None)
            except Exception:  # noqa: BLE001
                times.append(b["close_time"])
                vals.append(None)
        return times, vals

    series = compute_feature_series(bars, parameter_set_id=parameter_set_id, source_timeframe=decision_tf)
    for s in series.samples:
        times.append(s.available_at.isoformat() if hasattr(s.available_at, "isoformat") else str(s.available_at))
        if not s.valid:
            vals.append(None)
            continue
        v = s.values.get(feature_id)
        if isinstance(v, bool):
            vals.append(1.0 if v else 0.0)
        elif v is None:
            vals.append(None)
        else:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals.append(None)
    return times, vals


def discovery_thresholds(values: list[float | None], method: str) -> dict[str, float]:
    arr = np.array([v for v in values if v is not None], dtype=float)
    if len(arr) == 0:
        return {}
    out = {}
    if "NATURAL_TRUE" in method:
        out["NATURAL_TRUE"] = 0.5  # treat >0.5 as true for 0/1
        return out
    for tag in method.replace("DISCOVERY_", "").split("|"):
        if tag.startswith("P"):
            q = float(tag[1:]) / 100.0
            out[tag] = float(np.quantile(arr, q))
    return out


def evaluate_context_candidate(
    bars: list[dict[str, Any]],
    events: pd.DataFrame,
    *,
    candidate_id: str,
    family: str,
    feature_id: str,
    parameter_set_id: str,
    decision_tf: str,
    partition: str,
    threshold_method: str,
    frozen_thresholds: dict[str, float] | None,
    proximity_seconds: float = 3600.0,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """
    Enrichment: rate of feature-tail bars near any true C vs baseline rate.
    Thresholds selected on DISCOVERY only; VALIDATION uses frozen values.
    """
    times, vals = _feature_series_values(
        bars,
        parameter_set_id=parameter_set_id,
        feature_id=feature_id,
        decision_tf=decision_tf,
        event_times=pd.to_datetime(events["true_pivot_time"], utc=True).tolist(),
    )
    if frozen_thresholds is None:
        frozen_thresholds = discovery_thresholds(vals, threshold_method)

    event_times = pd.to_datetime(events["true_pivot_time"], utc=True)
    event_ns = np.sort(event_times.astype("int64").to_numpy())
    prox_ns = int(proximity_seconds * 1e9)

    def _near_any(ts_ns: int) -> bool:
        import bisect

        i = bisect.bisect_left(event_ns, ts_ns)
        for j in (i - 1, i):
            if 0 <= j < len(event_ns) and abs(int(event_ns[j]) - ts_ns) <= prox_ns:
                return True
        return False

    rows = []
    for thr_name, thr in frozen_thresholds.items():
        flags = []
        near = []
        for t, v in zip(times, vals):
            if v is None:
                flags.append(False)
                near.append(False)
                continue
            if thr_name.startswith("P") and int(thr_name[1:]) >= 50:
                active = v >= thr
            elif thr_name.startswith("P"):
                active = v <= thr
            else:
                active = v >= thr
            flags.append(active)
            if not active:
                near.append(False)
                continue
            tt = parse_ts(t)
            near.append(_near_any(int(pd.Timestamp(tt).value)))

        n = len(flags)
        n_active = sum(flags)
        n_near = sum(1 for a, n_ in zip(flags, near) if a and n_)
        all_near = sum(1 for t in times if _near_any(int(pd.Timestamp(parse_ts(t)).value)))
        base_rate = all_near / n if n else 0.0
        hit_rate = n_near / n_active if n_active else 0.0
        lift = (hit_rate / base_rate) if base_rate > 0 else None
        p = simple_lift_pvalue(hit_rate, base_rate, n_active)
        rows.append(
            {
                "candidate_id": candidate_id,
                "family": family,
                "feature_id": feature_id,
                "parameter_set_id": parameter_set_id,
                "decision_tf": decision_tf,
                "partition": partition,
                "threshold_name": thr_name,
                "threshold_value": thr,
                "n_bars": n,
                "n_active": n_active,
                "n_near_c": n_near,
                "hit_rate_near_c": hit_rate,
                "baseline_near_rate": base_rate,
                "event_rate_lift": lift,
                "p_value": p,
                "false_state_prevalence": 1.0 - hit_rate if n_active else None,
            }
        )
    return frozen_thresholds, rows
