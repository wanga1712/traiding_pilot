from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, log_loss, roc_auc_score


@dataclass(frozen=True)
class MetricResult:
    rows: int
    logloss: float
    prior_logloss: float
    delta_logloss: float
    brier: float
    prior_brier: float
    delta_brier: float
    roc_auc: float
    balanced_accuracy_at_0_5: float
    ece_10_bin: float
    positive_rate: float
    mean_predicted_probability: float
    std_predicted_probability: float
    constant_0_5_logloss: float
    constant_0_5_brier: float

    def as_dict(self) -> dict[str, float | int]:
        return self.__dict__.copy()


def binary_metrics(y: np.ndarray, p: np.ndarray, prior: float) -> MetricResult:
    y = np.asarray(y, dtype=np.int8)
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-15, 1 - 1e-15)
    if y.ndim != 1 or p.ndim != 1 or len(y) != len(p) or not len(y):
        raise ValueError("y and p must be non-empty aligned vectors")
    prior_p = np.full(len(y), float(prior), dtype=np.float64)
    half_p = np.full(len(y), 0.5, dtype=np.float64)
    ll = float(log_loss(y, p, labels=[0, 1]))
    pll = float(log_loss(y, prior_p, labels=[0, 1]))
    br = float(np.mean((p - y) ** 2))
    pbr = float(np.mean((prior_p - y) ** 2))
    auc = float(roc_auc_score(y, p)) if np.unique(y).size == 2 else float("nan")
    bal = float(balanced_accuracy_score(y, p >= 0.5)) if np.unique(y).size == 2 else float("nan")
    return MetricResult(
        rows=len(y),
        logloss=ll,
        prior_logloss=pll,
        delta_logloss=ll - pll,
        brier=br,
        prior_brier=pbr,
        delta_brier=br - pbr,
        roc_auc=auc,
        balanced_accuracy_at_0_5=bal,
        ece_10_bin=ece(y, p, bins=10),
        positive_rate=float(y.mean()),
        mean_predicted_probability=float(p.mean()),
        std_predicted_probability=float(p.std(ddof=0)),
        constant_0_5_logloss=float(log_loss(y, half_p, labels=[0, 1])),
        constant_0_5_brier=float(np.mean((half_p - y) ** 2)),
    )


def ece(y: np.ndarray, p: np.ndarray, *, bins: int = 10) -> float:
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    assignment = np.minimum(np.searchsorted(edges, p, side="right") - 1, bins - 1)
    assignment = np.maximum(assignment, 0)
    total = float(len(y))
    value = 0.0
    for b in range(bins):
        mask = assignment == b
        if mask.any():
            value += float(mask.sum()) / total * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(value)


def classify(delta_logloss: float, delta_brier: float, block_logloss_deltas: Iterable[float]) -> str:
    if delta_logloss >= 0 or delta_brier >= 0:
        return "OOS_NOT_SUPPORTED"
    stable = sum(float(x) < 0 for x in block_logloss_deltas) >= 2
    return "OOS_SUPPORTED" if stable else "OOS_WEAK"


def assign_frozen_blocks(decision_at: pd.Series, blocks: list[dict]) -> np.ndarray:
    ts = pd.to_datetime(decision_at, utc=True)
    out = np.full(len(ts), -1, dtype=np.int8)
    for idx, block in enumerate(blocks, 1):
        start = pd.Timestamp(block["start"])
        end = pd.Timestamp(block["end"])
        out[(ts >= start) & (ts <= end)] = idx
    if np.any(out < 0):
        raise ValueError("one or more decision timestamps fall outside frozen blocks")
    return out


def time_block_bootstrap(
    decision_at: pd.Series,
    y: np.ndarray,
    p: np.ndarray,
    prior: float,
    *,
    block_days: int = 7,
    repetitions: int = 2000,
    seed: int = 20260925,
) -> dict[str, float | int]:
    ts = pd.to_datetime(decision_at, utc=True)
    y = np.asarray(y, dtype=np.int8)
    p = np.asarray(p, dtype=np.float64)
    if len(ts) != len(y) or len(y) != len(p) or not len(y):
        raise ValueError("bootstrap inputs must be non-empty and aligned")
    anchor = ts.iloc[0].floor("D")
    labels = ((ts - anchor) // timedelta(days=block_days)).to_numpy(dtype=np.int64)
    groups = [np.flatnonzero(labels == label) for label in np.unique(labels)]
    rng = np.random.default_rng(seed)
    dll = np.empty(repetitions, dtype=np.float64)
    dbr = np.empty(repetitions, dtype=np.float64)
    for rep in range(repetitions):
        picked: list[np.ndarray] = []
        count = 0
        while count < len(y):
            g = groups[int(rng.integers(0, len(groups)))]
            picked.append(g)
            count += len(g)
        idx = np.concatenate(picked)[: len(y)]
        m = binary_metrics(y[idx], p[idx], prior)
        dll[rep] = m.delta_logloss
        dbr[rep] = m.delta_brier
    return {
        "block_length_calendar_days": block_days,
        "repetitions": repetitions,
        "random_seed": seed,
        "delta_logloss_ci_low": float(np.quantile(dll, 0.025)),
        "delta_logloss_ci_high": float(np.quantile(dll, 0.975)),
        "delta_brier_ci_low": float(np.quantile(dbr, 0.025)),
        "delta_brier_ci_high": float(np.quantile(dbr, 0.975)),
    }
