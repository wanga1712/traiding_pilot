"""PREDICTOR_CONFLUENCE_ENGINE_V1 — causal trigger-landscape features."""
from .version import CONFLUENCE_ENGINE_VERSION
from .engine import compute_predictor_confluence
from .registry import FEATURE_REGISTRY, PARAMETER_REGISTRY

__all__ = [
    "CONFLUENCE_ENGINE_VERSION",
    "compute_predictor_confluence",
    "FEATURE_REGISTRY",
    "PARAMETER_REGISTRY",
]
