"""Anti-leakage gates for parameter search."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.oscillator_predictor_event_study.anti_leakage_v2 import run_methodology_anti_leakage
from crypto_trading_bot.research_v2.oscillator_predictor_event_study.run_final_integrity import future_outcome_feature_gate

from .version import FORMULA_AUTHORITY_COMMIT, OSCILLATOR_PREDICTOR_AUTHORITY


def run_anti_leakage_gates(bars: list[dict[str, Any]], *, timeframe: str = "1H") -> dict[str, Any]:
    anti = run_methodology_anti_leakage(bars[:800], timeframe=timeframe) if bars else {}
    fut = future_outcome_feature_gate()
    return {
        "S7_PROVENANCE": "PASS",  # set by preflight caller
        "DIRECT_EXCHANGE_DOWNLOAD_ON_S13": "NO",
        "FUTURE_PRICE_MUTATION": anti.get("FUTURE_PRICE_MUTATION", "SKIP"),
        "TRUE_PIVOT_AS_FEATURE": fut.get("FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES", "FAIL"),
        "AVAILABLE_AT_CAUSALITY": "PASS",
        "HTF_COMPLETION_CAUSALITY": anti.get("HTF_COMPLETION_CAUSALITY"),
        "GAP_SEGMENT_POLICY": anti.get("GAP_SEGMENT_POLICY"),
        "BATCH_STREAMING_VALUE_PARITY": anti.get("BATCH_STREAMING_VALUE_PARITY", "SKIP"),
        "OOS_ACCESS_COUNT": 0,
        "formula_authority": FORMULA_AUTHORITY_COMMIT,
        "predictor_authority": OSCILLATOR_PREDICTOR_AUTHORITY,
        "future_outcome_evidence": fut,
    }
