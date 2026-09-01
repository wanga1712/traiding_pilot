"""Inverse trigger extraction integrity tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_registry import load_frozen_registry
from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
    INVERSE_PARAMETER_SET_ROUTES,
    discovery_fixture_bars_by_tf,
    run_inverse_parameter_set_authority_test,
    run_inverse_threshold_audit,
)
from crypto_trading_bot.research_v2.inverse_predictors.types import PredictorResult
from crypto_trading_bot.research_v2.reversal_signal_study.signals import _trigger_price

REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_CSV_V2 = REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1" / "candidate_registry_snapshot_v2.csv"


def _sample_result(*, price: float | None, status: str) -> PredictorResult:
    now = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return PredictorResult(
        predictor_engine_version="TEST",
        predictor_id="TEST",
        parameter_set_id="TEST",
        source_timeframe="1H",
        decision_time=now,
        calculated_at=now,
        available_at=now,
        predicted_trigger_price=price,
        current_price=100.0,
        distance_abs=None,
        distance_pct=None,
        distance_atr=None,
        signed_trigger_distance=None,
        direction_required="UP",
        trigger_definition="test",
        solution_status=status,
        hypothetical_input_type="NEXT_BAR_CLOSE",
    )


def test_trigger_price_predictor_result_object_regression():
    valid = _sample_result(price=123.45, status="EXACT_ANALYTIC")
    assert _trigger_price(valid) == 123.45

    invalid = _sample_result(price=123.45, status="INSUFFICIENT_HISTORY")
    assert _trigger_price(invalid) is None


def test_trigger_price_dict_parity():
    assert _trigger_price({"predicted_trigger_price": 123.45, "solution_status": "EXACT_ANALYTIC"}) == 123.45
    assert _trigger_price({"predicted_trigger_price": 123.45, "solution_status": "INSUFFICIENT_HISTORY"}) is None
    assert _trigger_price({"predicted_trigger_price": None, "solution_status": "EXACT_ANALYTIC"}) is None


@pytest.fixture(scope="module")
def fixture_bars():
    return discovery_fixture_bars_by_tf()


@pytest.fixture(scope="module")
def frozen_registry_v2():
    return load_frozen_registry(FROZEN_CSV_V2)


def test_inverse_parameter_set_authority(fixture_bars):
    report = run_inverse_parameter_set_authority_test(bars_by_tf=fixture_bars)
    assert report["PREDICTOR_RESULT_OBJECT_TRIGGER_EXTRACTION"] == "PASS"
    assert report["PREDICTOR_RESULT_DICT_TRIGGER_EXTRACTION"] == "PASS"
    assert report["INVERSE_PARAMETER_SET_ROUTE_COUNT"] == len(INVERSE_PARAMETER_SET_ROUTES)
    for route in report["route_reports"]:
        assert route["extracted_threshold_count"] == route["non_null_predicted_trigger_price_count"]


def test_inverse_threshold_audit_all_candidates(frozen_registry_v2, fixture_bars):
    report = run_inverse_threshold_audit(frozen_registry_v2, bars_by_tf=fixture_bars)
    assert report["INVERSE_CANDIDATE_COUNT"] == 120
    assert report["INVERSE_VALID_PREDICTION_LOST_TO_EXTRACTION_COUNT"] == 0
    assert report["INVERSE_DEAD_EXTRACTION_ROUTE_COUNT"] == 0
    assert report["INVERSE_DIRECTION_PURITY"] == "PASS"
