"""VOLUME_ACCUMULATION_ENGINE_V1 — causal market-context features."""
from .version import FEATURE_ENGINE_VERSION
from .types import FeatureSample, FeatureResult
from .snapshot import compute_market_context
from .compute import compute_feature_series
from .registry import FEATURE_REGISTRY, PARAMETER_REGISTRY

__all__ = [
    "FEATURE_ENGINE_VERSION",
    "FeatureSample",
    "FeatureResult",
    "compute_feature_series",
    "compute_market_context",
    "FEATURE_REGISTRY",
    "PARAMETER_REGISTRY",
]
