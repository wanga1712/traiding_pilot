"""Statistics helpers — Wilson intervals and bootstrap CIs."""
from __future__ import annotations

import math

import numpy as np


def sample_flag(n: int) -> str:
    if n < 30:
        return "N_LT_30"
    if n < 100:
        return "N_30_99"
    return "N_GE_100"


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def bootstrap_ci(
    values: np.ndarray,
    *,
    seed: int = 42,
    n_boot: int = 2000,
    alpha: float = 0.05,
) -> tuple[float | None, float | None, float | None]:
    arr = values[np.isfinite(values)]
    if arr.size == 0:
        return None, None, None
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n_boot):
        sample = rng.choice(arr, size=arr.size, replace=True)
        means.append(float(np.mean(sample)))
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return float(np.mean(arr)), lo, hi


def classify_stability(
    discovery_lift: float | None,
    validation_lift: float | None,
    *,
    min_n_discovery: int,
    min_n_validation: int,
) -> str:
    if min_n_discovery < 30 or min_n_validation < 30:
        return "INSUFFICIENT_SAMPLE"
    if discovery_lift is None or validation_lift is None:
        return "INSUFFICIENT_SAMPLE"
    if discovery_lift <= 0 and validation_lift <= 0:
        return "NEGATIVE"
    if discovery_lift > 0 and validation_lift > 0:
        if abs(discovery_lift - validation_lift) <= max(0.05, 0.5 * abs(discovery_lift)):
            return "STABLE_POSITIVE"
        return "WEAK_POSITIVE"
    return "UNSTABLE"


def distance_bin_label(value: float | None) -> str | None:
    if value is None or not np.isfinite(value):
        return None
    abs_v = abs(float(value))
    edges = (0.0, 0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
    for i in range(len(edges) - 1):
        if edges[i] <= abs_v < edges[i + 1]:
            return f"{edges[i]:.2f}-{edges[i+1]:.2f}"
    if abs_v >= 2.00:
        return ">2.00"
    return None
