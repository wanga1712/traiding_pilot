"""Mandatory anti-leakage tests — HTF and pivot fixtures."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.multitf_feature_bank.pivots import PivotRecord
from crypto_trading_bot.research_v2.multitf_feature_bank.snapshot import FeatureBank


def _bar(open_time: datetime, minutes: int, o: float, h: float, l: float, c: float) -> dict:
    ct = open_time + timedelta(minutes=minutes)
    return {
        "open_time": open_time.isoformat(),
        "close_time": ct.isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 100.0,
    }


def _assert_chronological(bars: list[dict], label: str) -> None:
    times = [b["open_time"] for b in bars]
    assert times == sorted(times), f"{label} bar stream not chronologically sorted"


def build_htf_leakage_fixture() -> tuple[datetime, dict[str, list[dict]], dict[str, list[dict]]]:
    """
    Decision at 10:30 UTC falls inside unfinished 1H [10:00,11:00) and 4H [08:00,12:00).
    Snapshot must use last closed 1H (09:00-10:00) and 4H (04:00-08:00).
    Bar streams are strictly chronological: closed bars, then one in-progress HTF candle.
    """
    t0 = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    decision = datetime(2022, 6, 10, 10, 30, tzinfo=timezone.utc)

    n_5m = int((decision - t0).total_seconds() / 300) + 1
    bars_5m = make_bars([100 + i * 0.01 for i in range(n_5m)], start=t0, minutes=5)

    bars_1h: list[dict] = []
    ot = t0
    while ot + timedelta(hours=1) <= decision:
        h = int((ot - t0).total_seconds() / 3600)
        c = 100 + h * 0.5
        bars_1h.append(_bar(ot, 60, c - 1, c + 2, c - 2, c))
        ot += timedelta(hours=1)
    ot_live = decision.replace(minute=0, second=0, microsecond=0)
    bars_1h.append(_bar(ot_live, 60, 118, 130, 110, 119))

    bars_4h: list[dict] = []
    ot = t0
    while ot + timedelta(hours=4) <= decision:
        b = int((ot - t0).total_seconds() / 14400)
        c = 90 + b * 2
        bars_4h.append(_bar(ot, 240, c - 1, c + 3, c - 3, c))
        ot += timedelta(hours=4)
    ot_live_4h = decision.replace(hour=(decision.hour // 4) * 4, minute=0, second=0, microsecond=0)
    bars_4h.append(_bar(ot_live_4h, 240, 150, 200, 140, 155))

    _assert_chronological(bars_1h, "1H")
    _assert_chronological(bars_4h, "4H")

    baseline = {"5m": bars_5m, "1H": bars_1h, "4H": bars_4h}
    return decision, baseline, baseline


def test_higher_tf_leakage() -> None:
    decision, baseline, _ = build_htf_leakage_fixture()
    snap_base = FeatureBank(baseline).snapshot(decision)
    h1_keys = [k for k in snap_base.features if k.startswith("1H.")]
    h4_keys = [k for k in snap_base.features if k.startswith("4H.")]
    assert h1_keys, "expected 1H features at decision inside live 1H candle"
    assert h4_keys, "expected 4H features at decision inside live 4H candle"

    mutated = copy.deepcopy(baseline)
    for tf, mins in (("1H", 60), ("4H", 240)):
        live = mutated[tf][-1]
        live["open"] = 1e6
        live["high"] = 2e6
        live["low"] = -1e6
        live["close"] = 3e6
        live_close = datetime.fromisoformat(live["close_time"].replace("Z", "+00:00"))
        mutated[tf].append(_bar(live_close, mins, 1e6, 2e6, -1e6, 3e6))
        _assert_chronological(mutated[tf], tf)

    snap_mut = FeatureBank(mutated).snapshot(decision)
    for k in h1_keys + h4_keys:
        assert snap_base.features.get(k) == snap_mut.features.get(k), f"HTF leak at {k}"


def test_sorted_htf_causality() -> None:
    """Sorted HTF streams; mutating in-progress + future bars must not change pre-decision snapshot."""
    decision, baseline, _ = build_htf_leakage_fixture()
    snap_before = FeatureBank(baseline).snapshot(decision)

    mutated = copy.deepcopy(baseline)
    for tf, mins in (("1H", 60), ("4H", 240)):
        live = mutated[tf][-1]
        live["close"] = 99999.0
        live_close = datetime.fromisoformat(live["close_time"].replace("Z", "+00:00"))
        for j in range(2):
            mutated[tf].append(_bar(live_close + timedelta(minutes=mins * j), mins, 888, 999, 777, 888))

    snap_after = FeatureBank(mutated).snapshot(decision)
    for k, v in snap_before.features.items():
        if k.startswith("1H.") or k.startswith("4H."):
            assert snap_after.features.get(k) == v, k


def build_pivot_leakage_fixture() -> tuple[datetime, dict[str, list[dict]], list[PivotRecord], list[PivotRecord]]:
    t0 = datetime(2022, 6, 10, 0, 0, tzinfo=timezone.utc)
    bars_1h = make_bars([150 + i for i in range(30)], start=t0, minutes=60)
    decision = datetime.fromisoformat(bars_1h[20]["close_time"].replace("Z", "+00:00"))

    base_pivots = [
        PivotRecord("P0", 100.0, t0 + timedelta(hours=5), timeframe="1H"),
        PivotRecord("P1", 200.0, t0 + timedelta(hours=10), timeframe="1H"),
        PivotRecord("P2", 150.0, t0 + timedelta(hours=15), timeframe="1H"),
    ]
    mutated_pivots = [
        p.retrospective_mutated_copy(
            true_pivot_time=t0 + timedelta(days=99),
            true_pivot_price=1e9,
            next_pivot_id="FUTURE_PIVOT",
            future_d_price=2e9,
            outcome_label="RETRO_LABEL",
        )
        for p in base_pivots
    ]
    return decision, {"1H": bars_1h}, base_pivots, mutated_pivots


def test_true_pivot_leakage() -> None:
    decision, bars, base_pivots, mut_pivots = build_pivot_leakage_fixture()
    snap_base = FeatureBank(bars, pivots_by_tf={"1H": base_pivots}).snapshot(decision)
    snap_mut = FeatureBank(bars, pivots_by_tf={"1H": mut_pivots}).snapshot(decision)
    geo_keys = [k for k in snap_base.features if "GEOMETRY_ABC" in k]
    assert geo_keys, "expected geometry features from causal pivots"
    for k in geo_keys:
        assert snap_base.features[k] == snap_mut.features[k], f"pivot label leak at {k}"


def test_future_d_leakage() -> None:
    """Future D price in retrospective field must not affect geometry."""
    decision, bars, base_pivots, _ = build_pivot_leakage_fixture()
    with_d = [p.retrospective_mutated_copy(future_d_price=99999.0) for p in base_pivots]
    s0 = FeatureBank(bars, pivots_by_tf={"1H": base_pivots}).snapshot(decision)
    s1 = FeatureBank(bars, pivots_by_tf={"1H": with_d}).snapshot(decision)
    for k in s0.features:
        if "GEOMETRY" in k:
            assert s0.features[k] == s1.features[k]


if __name__ == "__main__":
    test_higher_tf_leakage()
    test_sorted_htf_causality()
    test_true_pivot_leakage()
    test_future_d_leakage()
    print("ALL ANTI-LEAKAGE TESTS PASS")
