"""Discovery isolation integrity tests (FIX 1-8, 10)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_parameter_search.config import split_bounds
from crypto_trading_bot.research_v2.indicator_parameter_search.data_isolation import (
    build_discovery_access_audit,
    count_valid_bars,
    discovery_event_set,
    filter_signals_to_window,
    in_scan_window,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.evaluation import (
    add_baseline_deltas,
    price_baseline_metrics,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.run_search import (
    _load_events,
    _require_discovery_freeze_manifest,
)
from crypto_trading_bot.research_v2.reversal_signal_study.signals import generate_price_baseline_signals


def _bars(start: str, n: int, step_hours: int = 1) -> list[dict]:
    t0 = parse_ts(start)
    out = []
    for i in range(n):
        ct = datetime.fromtimestamp(t0.timestamp() + i * step_hours * 3600, tz=timezone.utc)
        out.append(
            {
                "open_time": ct.isoformat(),
                "close_time": ct.isoformat(),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.0 + i,
                "volume": 1.0,
            }
        )
    return out


def test_discovery_events_exclude_validation_partition(monkeypatch, tmp_path):
    ev = pd.DataFrame(
        [
            {"partition": "DISCOVERY", "partition_usable": True, "source_wave_tf": "1H", "true_pivot_time": "2020-01-01T00:00:00+00:00"},
            {"partition": "VALIDATION", "partition_usable": True, "source_wave_tf": "1H", "true_pivot_time": "2022-07-01T00:00:00+00:00"},
        ]
    )
    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.indicator_parameter_search.run_search.EVENT_DIR",
        tmp_path,
    )
    (tmp_path / "reversal_events_v1.parquet").parent.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(tmp_path / "reversal_events_v1.parquet")
    disc = _load_events(partitions=("DISCOVERY",))
    assert len(disc) == 1
    assert set(disc["partition"]) == {"DISCOVERY"}


def test_scan_end_excludes_post_discovery_signals():
    disc_start, disc_end = split_bounds("DISCOVERY")
    bars = _bars("2019-05-10T00:00:00+00:00", 200)
    sigs = generate_price_baseline_signals(
        bars,
        candidate_id="PRICE_ONE_BAR_DIRECTION_CHANGE_1H",
        kind="ONE_BAR_DIRECTION_CHANGE",
        decision_tf="1H",
        scan_start_iso=disc_start.isoformat(),
        scan_end_iso=disc_end.isoformat(),
    )
    assert sigs
    assert all(parse_ts(s["available_at"]) < disc_end for s in sigs)
    assert all(parse_ts(s["available_at"]) >= disc_start for s in sigs)


def test_fold_baseline_differs_from_full_discovery_baseline():
    disc_start, disc_end = split_bounds("DISCOVERY")
    folds = [
        (disc_start, datetime(2020, 6, 10, tzinfo=timezone.utc)),
        (datetime(2020, 6, 10, tzinfo=timezone.utc), datetime(2021, 6, 10, tzinfo=timezone.utc)),
        (datetime(2021, 6, 10, tzinfo=timezone.utc), disc_end),
    ]
    bars = _bars("2019-05-10T00:00:00+00:00", 4000, step_hours=6)
    baselines = generate_price_baseline_signals(
        bars,
        candidate_id="PRICE_ONE_BAR_DIRECTION_CHANGE_1H",
        kind="ONE_BAR_DIRECTION_CHANGE",
        decision_tf="1H",
        scan_start_iso=disc_start.isoformat(),
        scan_end_iso=disc_end.isoformat(),
    )
    events = pd.DataFrame(
        [
            {
                "partition": "DISCOVERY",
                "partition_usable": True,
                "source_wave_tf": "1H",
                "true_pivot_time": "2020-01-01T00:00:00+00:00",
                "pivot_type": "LOW",
            }
        ]
    )
    full = price_baseline_metrics(
        baselines,
        events,
        decision_tf="1H",
        direction="UP",
        partition="DISCOVERY",
        valid_bars=count_valid_bars(bars, disc_start, disc_end),
    )
    fold1 = price_baseline_metrics(
        baselines,
        events,
        decision_tf="1H",
        direction="UP",
        partition="DISCOVERY",
        fold_start=folds[0][0].isoformat(),
        fold_end=folds[0][1].isoformat(),
        valid_bars=count_valid_bars(bars, folds[0][0], folds[0][1]),
    )
    assert full.get("PRECISION") != fold1.get("PRECISION") or full.get("TOTAL_SIGNALS") != fold1.get("TOTAL_SIGNALS")


def test_valid_bar_denominator_excludes_warmup_and_validation():
    disc_start, disc_end = split_bounds("DISCOVERY")
    val_start = split_bounds("VALIDATION")[0]
    bars = _bars("2019-05-10T00:00:00+00:00", 100) + _bars(val_start.isoformat(), 50)
    assert count_valid_bars(bars, disc_start, disc_end) < len(bars)


def test_validation_future_mutation_discovery_independence():
    disc_start, disc_end = split_bounds("DISCOVERY")
    bars = _bars("2019-05-10T00:00:00+00:00", 120)
    sigs_a = generate_price_baseline_signals(
        bars,
        candidate_id="PRICE_ONE_BAR_DIRECTION_CHANGE_1H",
        kind="ONE_BAR_DIRECTION_CHANGE",
        decision_tf="1H",
        scan_start_iso=disc_start.isoformat(),
        scan_end_iso=disc_end.isoformat(),
    )
    events_a = pd.DataFrame(
        [{"partition": "DISCOVERY", "partition_usable": True, "source_wave_tf": "1H", "true_pivot_time": "2020-01-01T00:00:00+00:00"}]
    )
    events_b = pd.concat(
        [
            events_a,
            pd.DataFrame(
                [
                    {
                        "partition": "VALIDATION",
                        "partition_usable": True,
                        "source_wave_tf": "1H",
                        "true_pivot_time": "2025-01-01T00:00:00+00:00",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    row = {
        "candidate_id": "PRICE_ONE_BAR_DIRECTION_CHANGE_1H",
        "family": "PRICE_ONLY",
        "decision_tf": "1H",
        "direction": "UP",
        "event_primitive": "ONE_BAR_DIRECTION_CHANGE",
        "parameter_set_id": "ONE_BAR_DIRECTION_CHANGE",
    }
    from crypto_trading_bot.research_v2.indicator_parameter_search.evaluation import evaluate_candidate

    m_a = evaluate_candidate(sigs_a, events_a, row, partition="DISCOVERY", valid_bars=count_valid_bars(bars, disc_start, disc_end))
    m_b = evaluate_candidate(sigs_a, events_b, row, partition="DISCOVERY", valid_bars=count_valid_bars(bars, disc_start, disc_end))
    assert m_a == m_b
    set_a = discovery_event_set(sigs_a, scan_start=disc_start, scan_end=disc_end)
    set_b = discovery_event_set(sigs_a, scan_start=disc_start, scan_end=disc_end)
    assert set_a == set_b


def test_validation_before_discovery_freeze_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "crypto_trading_bot.research_v2.indicator_parameter_search.run_search.ARTIFACT_ROOT",
        tmp_path,
    )
    with pytest.raises(RuntimeError, match="VALIDATION_BEFORE_DISCOVERY_FREEZE_BLOCKED"):
        _require_discovery_freeze_manifest()


def test_access_audit_flags_validation_leakage():
    disc_start, disc_end = split_bounds("DISCOVERY")
    val_start = split_bounds("VALIDATION")[0]
    bars_by_tf = {"1H": _bars("2019-05-10T00:00:00+00:00", 50) + _bars(val_start.isoformat(), 10)}
    events = pd.DataFrame(
        [
            {"partition": "DISCOVERY", "partition_usable": True},
            {"partition": "VALIDATION", "partition_usable": True},
        ]
    )
    audit = build_discovery_access_audit(
        bars_by_tf=bars_by_tf,
        events=events,
        discovery_start=disc_start,
        discovery_end=disc_end,
    )
    assert audit["validation_events_loaded"] == 1
    assert audit["validation_bars_loaded"] > 0
