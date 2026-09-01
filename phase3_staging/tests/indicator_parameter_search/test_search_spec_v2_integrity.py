"""V2 search spec route authority integrity tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_registry import (
    INVERSE_EXECUTION_MAP,
    audit_registry_semantic_consistency,
    build_candidate_registry,
    load_frozen_registry,
    registry_deserialization_stats,
    registry_family_counts,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
    discovery_fixture_bars_by_tf,
    run_inverse_route_preflight,
    run_mandatory_reference_sanity,
    run_silent_zero_audit,
    run_v2_integrity_gates,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.config import ARTIFACT_ROOT, split_bounds
from crypto_trading_bot.research_v2.indicator_parameter_search.run_search import _load_frozen_registry
from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import (
    is_quantile_control_row,
    resolve_candidate_route,
    row_parameters,
)
from crypto_trading_bot.research_v2.inverse_predictors.registry import PARAMETER_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_CSV_V2 = REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1" / "candidate_registry_snapshot_v2.csv"


@pytest.fixture(scope="module")
def built_registry() -> list[dict]:
    return build_candidate_registry()


@pytest.fixture(scope="module")
def frozen_registry_v2(built_registry) -> list[dict]:
    if FROZEN_CSV_V2.is_file():
        return load_frozen_registry(FROZEN_CSV_V2)
    return built_registry


@pytest.fixture(scope="module")
def fixture_bars():
    return discovery_fixture_bars_by_tf()


def test_v2_registry_deserialization(frozen_registry_v2):
    stats = registry_deserialization_stats(frozen_registry_v2)
    assert stats["FROZEN_REGISTRY_PARAMETERS_STRING_COUNT"] == 0
    assert stats["FROZEN_REGISTRY_PARAMETERS_DICT_COUNT"] == stats["FROZEN_REGISTRY_ROW_COUNT"]


def test_pure_dno_reference_route(frozen_registry_v2):
    rows = [r for r in frozen_registry_v2 if r["family"] == "PURE_DNO"]
    assert len(rows) == 20
    assert all(r["parameter_set_id"] == "DNO_PERIOD_7_REFERENCE" for r in rows)
    assert all(resolve_candidate_route(r) == "PURE_DNO" for r in rows)
    assert all(r["event_primitive"] in ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN") for r in rows)
    assert all(r["execution_route"] == "compute_dno_feature_series" for r in rows)


def test_dno_quantile_control_separate(frozen_registry_v2):
    rows = [r for r in frozen_registry_v2 if r["family"] == "DNO_QUANTILE"]
    assert rows
    assert all(is_quantile_control_row(r) for r in rows)
    assert all(resolve_candidate_route(r) == "DNO_QUANTILE_CONTROL" for r in rows)


def test_osc_predictor_separate_from_pure_dno(frozen_registry_v2):
    osc = [r for r in frozen_registry_v2 if r["family"] == "OSC_PREDICTOR"]
    pure = [r for r in frozen_registry_v2 if r["family"] == "PURE_DNO"]
    assert osc and pure
    assert not any(r["parameter_set_id"] == "DNO_PERIOD_7_REFERENCE" for r in osc)


def test_inverse_routes_use_registry_ids(frozen_registry_v2):
    inv = [r for r in frozen_registry_v2 if r["family"] == "INVERSE_PREDICTOR"]
    assert len(inv) == 120
    for row in inv:
        pred_id = row_parameters(row)["inverse_parameter_set_id"]
        assert pred_id in PARAMETER_REGISTRY
        assert resolve_candidate_route(row) == pred_id


def test_inverse_execution_map_authority():
    for spec in INVERSE_EXECUTION_MAP:
        assert spec["up_parameter_set_id"] in PARAMETER_REGISTRY
        assert spec["down_parameter_set_id"] in PARAMETER_REGISTRY


def test_semantic_consistency(frozen_registry_v2):
    audit = audit_registry_semantic_consistency(frozen_registry_v2)
    assert audit["SEARCH_SPEC_REGISTRY_SEMANTIC_CONSISTENCY"] == "PASS"
    assert audit["DNO_ZERO_CROSS_CANDIDATE_COUNT"] > 0
    assert audit["DNO_ONLY_OSC_PRIMITIVE_COUNT"] == 0


def test_v2_integrity_gates(frozen_registry_v2, fixture_bars):
    gates = run_v2_integrity_gates(frozen_registry_v2, bars_by_tf=fixture_bars)
    assert gates["PURE_DNO_REFERENCE_IMPLEMENTED"] == "PASS"
    assert gates["DNO_REFERENCE_USES_DYNAMIC_PREDICTOR"] == "NO"
    assert gates["DNO_QUANTILE_CONTROL_ROUTE"] == "PASS"
    assert gates["INVERSE_PARAMETER_SET_EXISTS"] == "PASS"
    assert gates["INVERSE_DIRECT_PREDICT_CALL"] == "PASS"
    assert gates["INVERSE_DIRECTION_PURITY"] == "PASS"
    assert gates["INVERSE_ROUTE_EXCEPTION_COUNT"] == 0
    assert gates["INVERSE_VALID_PREDICTION_LOST_TO_EXTRACTION_COUNT"] == 0
    assert gates["INVERSE_DEAD_EXTRACTION_ROUTE_COUNT"] == 0
    assert gates["PREDICTOR_RESULT_OBJECT_TRIGGER_EXTRACTION"] == "PASS"
    assert gates["SEARCH_SPEC_V2_IMMUTABLE"] == "PASS"
    assert gates["CANDIDATE_REGISTRY_V2_IMMUTABLE"] == "PASS"
    assert gates["PREFLIGHT_EVALUATION_BARS_AFTER_SCAN_START_GE_500"] == "PASS"
    assert gates["CANDIDATE_ROUTING_PREFLIGHT_EXCEPTION_COUNT"] == 0
    assert gates["CANDIDATE_ROUTING_PREFLIGHT_UNRESOLVED_COUNT"] == 0
    assert gates["SILENT_DEAD_ROUTE_COUNT"] == 0


def test_mandatory_reference_routes(frozen_registry_v2, fixture_bars):
    report = run_mandatory_reference_sanity(frozen_registry_v2, bars_by_tf=fixture_bars)
    assert report["MANDATORY_REFERENCE_ROUTE_FAILURE_COUNT"] == 0


def test_production_loader_v2(monkeypatch, frozen_registry_v2):
    if not FROZEN_CSV_V2.is_file():
        pytest.skip("v2 csv not frozen yet")
    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.indicator_parameter_search.run_search.ARTIFACT_ROOT",
        FROZEN_CSV_V2.parent,
    )
    prod = _load_frozen_registry()
    assert len(prod) == len(frozen_registry_v2)


def test_v2_family_counts(built_registry):
    counts = registry_family_counts(built_registry)
    total = sum(counts.values())
    assert total == len(built_registry)
    assert counts["INVERSE_PREDICTOR_CANDIDATES"] == 120
    assert counts["PURE_DNO_CANDIDATES"] == 20
