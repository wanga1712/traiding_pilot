"""Compute confluence feature dict from trigger points (+ optional prior snapshot)."""
from __future__ import annotations

import math
from typing import Any

from .cluster import Cluster, cluster_triggers, densest_cluster, nearest_cluster
from .types import TriggerPoint


def _median(xs: list[float]) -> float:
    ys = sorted(xs)
    n = len(ys)
    if n == 0:
        return float("nan")
    if n % 2:
        return ys[n // 2]
    return 0.5 * (ys[n // 2 - 1] + ys[n // 2])


def _mad(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    m = _median(xs)
    return _median([abs(x - m) for x in xs])


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))


def _count_within(triggers: list[TriggerPoint], *, pct: float | None = None, atr_mult: float | None = None, atr: float | None = None, side: str = "ALL") -> int:
    c = 0
    for t in triggers:
        if side == "ABOVE" and t.signed_distance_abs <= 0:
            continue
        if side == "BELOW" and t.signed_distance_abs >= 0:
            continue
        ok = False
        if pct is not None and abs(t.signed_distance_pct) <= pct:
            ok = True
        if atr_mult is not None and atr and t.signed_distance_atr is not None and abs(t.signed_distance_atr) <= atr_mult:
            ok = True
        if ok:
            c += 1
    return c


def compute_static_features(
    triggers: list[TriggerPoint],
    *,
    current_price: float,
    atr: float | None,
    threshold_pct: float,
    threshold_atr: float,
    status_counts: dict[str, int],
) -> dict[str, Any]:
    feats: dict[str, Any] = dict(status_counts)
    total = max(status_counts.get("TOTAL_PREDICTORS", 0), 1)
    feats["VALID_TRIGGER_FRACTION"] = status_counts.get("VALID_TRIGGER_COUNT", 0) / total

    # proximity
    for p in (0.10, 0.25, 0.50, 1.00):
        key = f"COUNT_WITHIN_{str(p).replace('.', '_')}_PCT".replace("_10_", "_0_10_").replace("_25_", "_0_25_").replace("_50_", "_0_50_").replace("_1_0_", "_1_00_")
        # normalize keys explicitly
    feats["COUNT_WITHIN_0_10_PCT"] = _count_within(triggers, pct=0.10)
    feats["COUNT_WITHIN_0_25_PCT"] = _count_within(triggers, pct=0.25)
    feats["COUNT_WITHIN_0_50_PCT"] = _count_within(triggers, pct=0.50)
    feats["COUNT_WITHIN_1_00_PCT"] = _count_within(triggers, pct=1.00)
    feats["COUNT_WITHIN_0_25_ATR"] = _count_within(triggers, atr_mult=0.25, atr=atr)
    feats["COUNT_WITHIN_0_50_ATR"] = _count_within(triggers, atr_mult=0.50, atr=atr)
    feats["COUNT_WITHIN_1_00_ATR"] = _count_within(triggers, atr_mult=1.00, atr=atr)
    feats["COUNT_WITHIN_2_00_ATR"] = _count_within(triggers, atr_mult=2.00, atr=atr)
    feats["ABOVE_MARKET_COUNT_0_25_PCT"] = _count_within(triggers, pct=0.25, side="ABOVE")
    feats["BELOW_MARKET_COUNT_0_25_PCT"] = _count_within(triggers, pct=0.25, side="BELOW")
    feats["ABOVE_MARKET_COUNT_0_50_ATR"] = _count_within(triggers, atr_mult=0.50, atr=atr, side="ABOVE")
    feats["BELOW_MARKET_COUNT_0_50_ATR"] = _count_within(triggers, atr_mult=0.50, atr=atr, side="BELOW")

    above = [t for t in triggers if t.signed_distance_abs > 0]
    below = [t for t in triggers if t.signed_distance_abs < 0]
    feats["TRIGGERS_ABOVE_COUNT"] = len(above)
    feats["TRIGGERS_BELOW_COUNT"] = len(below)
    n = max(len(triggers), 1)
    feats["TRIGGERS_ABOVE_FRACTION"] = len(above) / n
    feats["TRIGGERS_BELOW_FRACTION"] = len(below) / n
    feats["ABOVE_BELOW_COUNT_IMBALANCE"] = len(above) - len(below)
    feats["NEAREST_ABOVE_DISTANCE"] = min((t.signed_distance_pct for t in above), default=None)
    feats["NEAREST_BELOW_DISTANCE"] = max((t.signed_distance_pct for t in below), default=None)  # most negative mag as signed
    if feats["NEAREST_ABOVE_DISTANCE"] is not None and feats["NEAREST_BELOW_DISTANCE"] is not None:
        feats["ABOVE_BELOW_DISTANCE_ASYMMETRY"] = abs(feats["NEAREST_ABOVE_DISTANCE"]) - abs(feats["NEAREST_BELOW_DISTANCE"])
    else:
        feats["ABOVE_BELOW_DISTANCE_ASYMMETRY"] = None

    # nearest trigger
    if triggers:
        nearest = min(triggers, key=lambda t: abs(t.signed_distance_pct))
        feats["NEAREST_TRIGGER_PRICE"] = nearest.price
        feats["NEAREST_TRIGGER_DISTANCE_PCT"] = nearest.signed_distance_pct
        feats["NEAREST_TRIGGER_DISTANCE_ATR"] = nearest.signed_distance_atr
        feats["NEAREST_TRIGGER_DIRECTION"] = "UP" if nearest.signed_distance_abs > 0 else "DOWN" if nearest.signed_distance_abs < 0 else "AT"
        feats["NEAREST_TRIGGER_PREDICTOR_ID"] = nearest.predictor_id
        feats["NEAREST_TRIGGER_FAMILY"] = nearest.family
    else:
        for k in (
            "NEAREST_TRIGGER_PRICE",
            "NEAREST_TRIGGER_DISTANCE_PCT",
            "NEAREST_TRIGGER_DISTANCE_ATR",
            "NEAREST_TRIGGER_DIRECTION",
            "NEAREST_TRIGGER_PREDICTOR_ID",
            "NEAREST_TRIGGER_FAMILY",
        ):
            feats[k] = None

    # clusters (use active parameter thresholds)
    clusters = cluster_triggers(
        triggers,
        threshold_pct=threshold_pct,
        threshold_atr=threshold_atr,
        atr=atr,
        current_price=current_price,
    )
    feats["CLUSTER_COUNT"] = len(clusters)
    feats["CLUSTER_ABOVE_COUNT"] = sum(1 for c in clusters if c.center > current_price)
    feats["CLUSTER_BELOW_COUNT"] = sum(1 for c in clusters if c.center < current_price)
    nc = nearest_cluster(clusters, current_price)
    dc = densest_cluster(clusters)
    sizes = [c.size for c in clusters]
    feats["LARGEST_CLUSTER_SIZE"] = max(sizes) if sizes else 0
    feats["MEAN_CLUSTER_SIZE"] = (sum(sizes) / len(sizes)) if sizes else 0
    feats["MAX_CLUSTER_SIZE"] = feats["LARGEST_CLUSTER_SIZE"]

    def _cluster_feats(prefix: str, c: Cluster | None) -> None:
        if c is None:
            for k in (
                f"{prefix}_SIZE",
                f"{prefix}_CENTER_PRICE",
                f"{prefix}_DISTANCE_PCT",
                f"{prefix}_DISTANCE_ATR",
                f"{prefix}_WIDTH_PCT",
                f"{prefix}_WIDTH_ATR",
                f"{prefix}_DISTINCT_FAMILIES",
            ):
                feats[k] = None
            return
        feats[f"{prefix}_SIZE"] = c.size
        feats[f"{prefix}_CENTER_PRICE"] = c.center
        dist = c.center - current_price
        feats[f"{prefix}_DISTANCE_PCT"] = dist / current_price * 100.0 if current_price else None
        feats[f"{prefix}_DISTANCE_ATR"] = dist / atr if atr else None
        feats[f"{prefix}_WIDTH_PCT"] = c.width_abs / current_price * 100.0 if current_price else None
        feats[f"{prefix}_WIDTH_ATR"] = c.width_abs / atr if atr else None
        feats[f"{prefix}_DISTINCT_FAMILIES"] = len(c.families)

    _cluster_feats("NEAREST_CLUSTER", nc)
    # alias required baseline names
    feats["NEAREST_CLUSTER_SIZE"] = feats.get("NEAREST_CLUSTER_SIZE")
    feats["DENSEST_CLUSTER_SIZE"] = dc.size if dc else 0
    feats["DENSEST_CLUSTER_WIDTH"] = dc.width_abs if dc else None
    feats["DENSEST_CLUSTER_CENTER_DISTANCE"] = (
        (dc.center - current_price) / current_price * 100.0 if dc and current_price else None
    )
    feats["DENSEST_CLUSTER_DISTINCT_FAMILIES"] = len(dc.families) if dc else 0

    # family diversity
    families = {t.family for t in triggers}
    feats["DISTINCT_FAMILY_COUNT"] = len(families)
    fam_counts: dict[str, int] = {}
    for t in triggers:
        fam_counts[t.family] = fam_counts.get(t.family, 0) + 1
    max_fam = max(fam_counts.values()) if fam_counts else 0
    feats["MAX_TRIGGERS_FROM_SINGLE_FAMILY"] = max_fam
    feats["FAMILY_CONCENTRATION_RATIO"] = max_fam / n
    feats["FAMILY_DIVERSITY_RATIO"] = len(families) / n
    feats["NEAREST_CLUSTER_DISTINCT_FAMILIES"] = feats.get("NEAREST_CLUSTER_DISTINCT_FAMILIES")

    # spread
    prices = [t.price for t in triggers]
    if prices:
        feats["MIN_TRIGGER_PRICE"] = min(prices)
        feats["MAX_TRIGGER_PRICE"] = max(prices)
        feats["TRIGGER_RANGE_ABS"] = max(prices) - min(prices)
        feats["TRIGGER_RANGE_PCT"] = feats["TRIGGER_RANGE_ABS"] / current_price * 100.0 if current_price else None
        feats["TRIGGER_RANGE_ATR"] = feats["TRIGGER_RANGE_ABS"] / atr if atr else None
        pcts = [t.signed_distance_pct for t in triggers]
        feats["TRIGGER_STD_PCT"] = _std(pcts)
        feats["TRIGGER_DISPERSION_PCT"] = feats["TRIGGER_STD_PCT"]
        atrs = [t.signed_distance_atr for t in triggers if t.signed_distance_atr is not None]
        feats["TRIGGER_STD_ATR"] = _std(atrs) if atrs else None
        qs = sorted(pcts)
        if len(qs) >= 4:
            q1 = qs[len(qs) // 4]
            q3 = qs[(3 * len(qs)) // 4]
            feats["TRIGGER_IQR_PCT"] = q3 - q1
        else:
            feats["TRIGGER_IQR_PCT"] = None
        feats["TRIGGER_MAD_PCT"] = _mad(pcts)
        feats["TRIGGER_MEDIAN_PRICE"] = _median(prices)
        feats["TRIGGER_MEAN_PRICE"] = sum(prices) / len(prices)
        feats["DIST_MARKET_TO_TRIGGER_MEDIAN"] = (feats["TRIGGER_MEDIAN_PRICE"] - current_price) / current_price * 100.0
        feats["DIST_MARKET_TO_TRIGGER_MEAN"] = (feats["TRIGGER_MEAN_PRICE"] - current_price) / current_price * 100.0
        # pairwise
        pair = []
        for i in range(len(prices)):
            for j in range(i + 1, len(prices)):
                pair.append(abs(prices[i] - prices[j]) / current_price * 100.0)
        feats["PAIRWISE_DISTANCE_MEAN"] = sum(pair) / len(pair) if pair else 0.0
    else:
        for k in (
            "MIN_TRIGGER_PRICE",
            "MAX_TRIGGER_PRICE",
            "TRIGGER_RANGE_ABS",
            "TRIGGER_RANGE_PCT",
            "TRIGGER_RANGE_ATR",
            "TRIGGER_STD_PCT",
            "TRIGGER_DISPERSION_PCT",
            "TRIGGER_STD_ATR",
            "TRIGGER_IQR_PCT",
            "TRIGGER_MAD_PCT",
            "TRIGGER_MEDIAN_PRICE",
            "TRIGGER_MEAN_PRICE",
            "DIST_MARKET_TO_TRIGGER_MEDIAN",
            "DIST_MARKET_TO_TRIGGER_MEAN",
            "PAIRWISE_DISTANCE_MEAN",
        ):
            feats[k] = None

    # direction
    up = sum(1 for t in triggers if t.direction_required == "UP")
    down = sum(1 for t in triggers if t.direction_required == "DOWN")
    feats["UP_REQUIRED_COUNT"] = up
    feats["DOWN_REQUIRED_COUNT"] = down
    feats["UP_REQUIRED_FAMILY_COUNT"] = len({t.family for t in triggers if t.direction_required == "UP"})
    feats["DOWN_REQUIRED_FAMILY_COUNT"] = len({t.family for t in triggers if t.direction_required == "DOWN"})
    feats["DIRECTION_AGREEMENT_RATIO"] = max(up, down) / n
    # simple entropy of up/down/either
    either = sum(1 for t in triggers if t.direction_required == "EITHER")
    probs = [x / n for x in (up, down, either) if x]
    feats["DIRECTION_ENTROPY"] = -sum(p * math.log(p + 1e-15) for p in probs) if probs else None

    # already triggered from status counts
    feats["COUNT_ALREADY_TRIGGERED"] = status_counts.get("ALREADY_TRIGGERED_COUNT", 0)

    # convergence score deterministic: inverse of dispersion (bounded)
    disp = feats.get("TRIGGER_DISPERSION_PCT")
    if disp is None:
        feats["CONVERGENCE_SCORE"] = None
    else:
        feats["CONVERGENCE_SCORE"] = 1.0 / (1.0 + float(disp))

    return feats


def add_temporal_features(
    feats: dict[str, Any],
    triggers: list[TriggerPoint],
    *,
    prior_feats: dict[str, Any] | None,
    prior_triggers: list[TriggerPoint] | None,
    current_price: float,
) -> dict[str, Any]:
    """Compare to prior bar snapshot; deterministic deltas only."""
    if prior_feats is None or prior_triggers is None:
        for k in (
            "APPROACHING_TRIGGER_COUNT",
            "RECEDING_TRIGGER_COUNT",
            "APPROACHING_FAMILY_COUNT",
            "MEAN_TRIGGER_APPROACH_SPEED",
            "NEAREST_CLUSTER_APPROACH_SPEED",
            "CLUSTER_WIDTH_CHANGE",
            "CLUSTER_CENTER_CHANGE",
            "CLUSTER_SIZE_CHANGE",
            "TRIGGER_DISPERSION_DELTA",
            "TRIGGER_DISPERSION_SLOPE",
            "PAIRWISE_DISTANCE_DELTA",
            "COUNT_TRIGGERED_LAST_N_BARS",
        ):
            feats[k] = None
        return feats

    # map prior by parameter_set_id
    prior_map = {t.parameter_set_id: t for t in prior_triggers}
    approaching = 0
    receding = 0
    speeds = []
    approaching_fams = set()
    for t in triggers:
        p = prior_map.get(t.parameter_set_id)
        if p is None:
            continue
        prev_abs = abs(p.signed_distance_pct)
        now_abs = abs(t.signed_distance_pct)
        delta = now_abs - prev_abs  # negative => approaching
        speeds.append(-delta)  # approach speed positive when approaching
        if delta < -1e-12:
            approaching += 1
            approaching_fams.add(t.family)
        elif delta > 1e-12:
            receding += 1
        # crossing events
        if p.signed_distance_abs > 0 and t.signed_distance_abs < 0:
            feats.setdefault("TRIGGER_WAS_ABOVE_NOW_BELOW_COUNT", 0)
            feats["TRIGGER_WAS_ABOVE_NOW_BELOW_COUNT"] += 1
        if p.signed_distance_abs < 0 and t.signed_distance_abs > 0:
            feats.setdefault("TRIGGER_WAS_BELOW_NOW_ABOVE_COUNT", 0)
            feats["TRIGGER_WAS_BELOW_NOW_ABOVE_COUNT"] += 1
        if abs(p.signed_distance_pct) > 0.25 and abs(t.signed_distance_pct) <= 0.25:
            feats.setdefault("TRIGGER_ENTERED_0_25PCT_ZONE_COUNT", 0)
            feats["TRIGGER_ENTERED_0_25PCT_ZONE_COUNT"] += 1

    feats["APPROACHING_TRIGGER_COUNT"] = approaching
    feats["RECEDING_TRIGGER_COUNT"] = receding
    feats["APPROACHING_FAMILY_COUNT"] = len(approaching_fams)
    feats["MEAN_TRIGGER_APPROACH_SPEED"] = sum(speeds) / len(speeds) if speeds else 0.0

    # cluster temporal
    def _g(name: str):
        return prior_feats.get(name)

    feats["CLUSTER_WIDTH_CHANGE"] = None
    if feats.get("NEAREST_CLUSTER_WIDTH_PCT") is not None and _g("NEAREST_CLUSTER_WIDTH_PCT") is not None:
        feats["CLUSTER_WIDTH_CHANGE"] = feats["NEAREST_CLUSTER_WIDTH_PCT"] - _g("NEAREST_CLUSTER_WIDTH_PCT")
    feats["CLUSTER_CENTER_CHANGE"] = None
    if feats.get("NEAREST_CLUSTER_DISTANCE_PCT") is not None and _g("NEAREST_CLUSTER_DISTANCE_PCT") is not None:
        feats["CLUSTER_CENTER_CHANGE"] = feats["NEAREST_CLUSTER_DISTANCE_PCT"] - _g("NEAREST_CLUSTER_DISTANCE_PCT")
        feats["NEAREST_CLUSTER_APPROACH_SPEED"] = -abs(feats["NEAREST_CLUSTER_DISTANCE_PCT"]) + abs(_g("NEAREST_CLUSTER_DISTANCE_PCT"))
    else:
        feats["NEAREST_CLUSTER_APPROACH_SPEED"] = None
    feats["CLUSTER_SIZE_CHANGE"] = None
    if feats.get("NEAREST_CLUSTER_SIZE") is not None and _g("NEAREST_CLUSTER_SIZE") is not None:
        feats["CLUSTER_SIZE_CHANGE"] = feats["NEAREST_CLUSTER_SIZE"] - _g("NEAREST_CLUSTER_SIZE")

    if feats.get("TRIGGER_DISPERSION_PCT") is not None and _g("TRIGGER_DISPERSION_PCT") is not None:
        feats["TRIGGER_DISPERSION_DELTA"] = feats["TRIGGER_DISPERSION_PCT"] - _g("TRIGGER_DISPERSION_PCT")
        feats["TRIGGER_DISPERSION_SLOPE"] = feats["TRIGGER_DISPERSION_DELTA"]
    else:
        feats["TRIGGER_DISPERSION_DELTA"] = None
        feats["TRIGGER_DISPERSION_SLOPE"] = None
    if feats.get("PAIRWISE_DISTANCE_MEAN") is not None and _g("PAIRWISE_DISTANCE_MEAN") is not None:
        feats["PAIRWISE_DISTANCE_DELTA"] = feats["PAIRWISE_DISTANCE_MEAN"] - _g("PAIRWISE_DISTANCE_MEAN")
    else:
        feats["PAIRWISE_DISTANCE_DELTA"] = None

    prev_trig = _g("COUNT_ALREADY_TRIGGERED") or 0
    feats["COUNT_TRIGGERED_LAST_N_BARS"] = max(0, int(feats.get("COUNT_ALREADY_TRIGGERED", 0)) - int(prev_trig))
    return feats
