"""Execution integrity tests — frozen registry CSV roundtrip and routing preflight."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_registry import (
    build_candidate_registry,
    compare_registry_semantics,
    load_frozen_registry,
    registry_deserialization_stats,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
    run_candidate_routing_preflight,
    run_mandatory_reference_sanity,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.config import ARTIFACT_ROOT, split_bounds
from crypto_trading_bot.research_v2.indicator_parameter_search.frozen_spec import verify_frozen_artifacts
from crypto_trading_bot.research_v2.indicator_parameter_search.run_search import _load_frozen_registry
from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import (
    generate_signals_for_row,
    is_quantile_control_row,
    resolve_candidate_route,
    row_parameters,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_CSV = REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1" / "candidate_registry_snapshot_v1.csv"


@pytest.fixture(scope="module")
def frozen_registry() -> list[dict]:
    return load_frozen_registry(FROZEN_CSV)


@pytest.fixture(scope="module")
def built_registry() -> list[dict]:
    return build_candidate_registry()


def test_frozen_registry_deserialization(frozen_registry):
    stats = registry_deserialization_stats(frozen_registry)
    assert stats["FROZEN_REGISTRY_ROW_COUNT"] == 3220
    assert stats["FROZEN_REGISTRY_PARAMETERS_DICT_COUNT"] == 3220
    assert stats["FROZEN_REGISTRY_PARAMETERS_STRING_COUNT"] == 0


def test_frozen_registry_semantic_roundtrip(frozen_registry, built_registry):
    mismatch_count, mismatches = compare_registry_semantics(built_registry, frozen_registry)
    assert mismatch_count == 0, mismatches[:10]


def test_production_loader_uses_frozen_csv(monkeypatch, frozen_registry):
    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.indicator_parameter_search.run_search.ARTIFACT_ROOT",
        FROZEN_CSV.parent,
    )
    prod = _load_frozen_registry()
    assert len(prod) == 3220
    assert all(isinstance(r["parameters"], dict) for r in prod)
    mismatch_count, _ = compare_registry_semantics(prod, frozen_registry)
    assert mismatch_count == 0


def test_inverse_predictor_rows(frozen_registry):
    inv = [r for r in frozen_registry if r["family"] == "INVERSE_PREDICTOR"]
    assert len(inv) == 120
    for row in inv:
        params = row_parameters(row)
        assert isinstance(params, dict)
        assert params.get("inverse_route")
        assert resolve_candidate_route(row) == "INVERSE"


def test_dno_quantile_control_route(frozen_registry):
    rows = [r for r in frozen_registry if r["parameter_set_id"] == "CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1"]
    assert rows
    assert all(is_quantile_control_row(r) for r in rows)
    assert all(resolve_candidate_route(r) == "DNO_QUANTILE_CONTROL" for r in rows)


def test_dno_period_7_reference_semantics(frozen_registry):
    row = next(r for r in frozen_registry if r["parameter_set_id"] == "DNO_PERIOD_7_REFERENCE" and r["decision_tf"] == "1H")
    params = row_parameters(row)
    assert params == {"period": 7, "family": "DNO_ONLY"}
    assert resolve_candidate_route(row) == "PREDICTOR"


def test_candidate_routing_preflight_all_rows(frozen_registry):
    from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import representative_bars_by_tf

    report = run_candidate_routing_preflight(frozen_registry, bars_by_tf=representative_bars_by_tf())
    assert report["CANDIDATE_ROUTING_PREFLIGHT_TOTAL"] == 3220
    assert report["CANDIDATE_ROUTING_PREFLIGHT_EXCEPTION_COUNT"] == 0
    assert report["CANDIDATE_ROUTING_PREFLIGHT_UNRESOLVED_COUNT"] == 0


def test_mandatory_reference_routes_executable(frozen_registry):
    from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import representative_bars_by_tf

    report = run_mandatory_reference_sanity(frozen_registry, bars_by_tf=representative_bars_by_tf())
    assert report["MANDATORY_REFERENCE_ROUTE_FAILURE_COUNT"] == 0
    assert report["MANDATORY_REFERENCE_ROUTE_EXECUTABLE_COUNT"] == report["MANDATORY_REFERENCE_ROUTE_COUNT"]


def test_production_frozen_registry_integration_by_family(frozen_registry):
    from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import representative_bars_by_tf

    bars_by_tf = representative_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    families = sorted({r["family"] for r in frozen_registry})
    for family in families:
        row = next(r for r in frozen_registry if r["family"] == family)
        sigs = generate_signals_for_row(
            bars_by_tf[row["decision_tf"]],
            row,
            scan_start_iso=disc_start.isoformat(),
            scan_end_iso=disc_end.isoformat(),
        )
        assert isinstance(sigs, list)


def test_frozen_spec_immutable():
    hashes = verify_frozen_artifacts(REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1")
    assert hashes["SEARCH_SPEC_SHA256"]
    assert hashes["CANDIDATE_REGISTRY_SHA256"]
