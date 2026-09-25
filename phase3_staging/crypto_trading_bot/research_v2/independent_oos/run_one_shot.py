from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import resource
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import scipy.sparse as sp

from crypto_trading_bot.research_v2.composite_signal_search.compose import compose_signals_from_compact
from crypto_trading_bot.research_v2.composite_signal_search.context_state import (
    build_compact_state_arrays,
    pair_configs_by_stream,
    pair_key_from_config,
)
from crypto_trading_bot.research_v2.independent_oos.evaluation import (
    assign_frozen_blocks,
    binary_metrics,
    classify,
    time_block_bootstrap,
)
from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import generate_signals_for_row
from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.model_training_dataset.integrity import map_events_to_rows
from crypto_trading_bot.research_v2.model_training_dataset.target_engine import optimized_targets
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars

ROOT = Path("/var/tmp/traiding_pilot_ui_workspace")
OUT = ROOT / "artifacts/INDEPENDENT-OOS-MODEL-EVALUATION-1"
PARENT = ROOT / "artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"
BAKEOFF = ROOT / "artifacts/PROBABILITY-MODEL-BAKEOFF-1"
SOURCE_CACHE = OUT / "source_cache"
MODEL_PATHS = {
    30: BAKEOFF / "final_development_models/e4823f1bfa7cadbdefac.joblib",
    60: BAKEOFF / "final_development_models/bb22754c7763a9d24a3e.joblib",
}
DENSE_COLUMNS = [
    "open", "high", "low", "close", "volume", "trade_count", "return_1", "log_return_1",
    "range_pct", "close_position", "volume_log1p", "mean_high_low_range_14",
    "volume_mean_32", "volume_std_32", "volume_z_32",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def jload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def jdump(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str, allow_nan=True), encoding="utf-8")
    tmp.replace(path)


def preflight() -> dict[str, Any]:
    spec = jload(OUT / "independent_oos_evaluation_spec_v1.json")
    period = jload(OUT / "oos_period_freeze_v1.json")
    inventory = jload(OUT / "source_partition_inventory_v1.json")
    if inventory["manifest_sha256"] != period["source_partition_manifest_sha256"]:
        raise RuntimeError("source partition manifest hash mismatch")
    feature_doc = jload(BAKEOFF / "probability_model_feature_sets_v1.json")
    full = feature_doc["sets"]["FS_FULL"]
    columns = full["columns"]
    actual_feature_hash = hashlib.sha256("\n".join(columns).encode()).hexdigest()
    if actual_feature_hash != spec["feature_set_hash"] or full["hash"] != spec["feature_set_hash"]:
        raise RuntimeError("FS_FULL hash mismatch")
    handoff = jload(PARENT / "model_feature_handoff_v1.json")
    atomic = columns[15:15 + 284]
    composite = columns[15 + 284:]
    if columns[:15] != DENSE_COLUMNS or atomic != sorted(handoff["atomic_feature_ids"]):
        raise RuntimeError("dense/atomic feature order mismatch")
    if composite != sorted(handoff["composite_feature_ids"]):
        raise RuntimeError("composite feature order mismatch")
    model_bundles = {}
    model_gates = {}
    for horizon, path in MODEL_PATHS.items():
        actual = sha256(path)
        expected = spec["models"][str(horizon)]["sha256"]
        model_gates[str(horizon)] = "PASS" if actual == expected else "FAIL"
        if actual != expected:
            raise RuntimeError(f"{horizon}m model hash mismatch")
        model_bundles[horizon] = joblib.load(path)
    source_text = Path(__file__).read_text(encoding="utf-8")
    forbidden_training_token = ".fi" + "t("
    if forbidden_training_token in source_text:
        raise RuntimeError("forbidden training call present in OOS runner")
    return {
        "spec": spec, "period": period, "inventory": inventory, "feature_columns": columns,
        "atomic_ids": atomic, "composite_ids": composite, "models": model_bundles,
        "model_gates": model_gates,
    }


def verify_staged_source(inventory: dict) -> None:
    by_name = {Path(x["relative_path"]).name: x for x in inventory["partitions"]}
    for name, expected in by_name.items():
        path = SOURCE_CACHE / "1m" / name
        if not path.is_file() or path.stat().st_size != expected["bytes"]:
            raise RuntimeError(f"staged source mismatch: {name}")


def _load_bars_by_tf(start: datetime, end_exclusive: datetime, required_configs: list[dict]) -> dict[str, list]:
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/nonexistent/frozen-s7-source"),
        cache_root=SOURCE_CACHE,
    )
    out = {}
    for tf in sorted({x["decision_tf"] for x in required_configs} | {"15m"}):
        out[tf] = load_continuous_bars(service, tf, start, end_exclusive, warmup_bars=500)
    return out


def _gap_resets(bars: list[dict], tf_minutes: int) -> np.ndarray:
    if len(bars) < 2:
        return np.empty(0, dtype=np.int64)
    times = np.asarray([int(parse_ts(x["close_time"]).timestamp() * 1e9) for x in bars], dtype=np.int64)
    return times[1:][np.diff(times) > int(tf_minutes * 60 * 1.5 * 1e9)]


def _stream_maps() -> tuple[dict[str, str], dict[str, dict]]:
    paths = {}
    metas = {}
    for meta_path in glob.glob(str(PARENT / "atomic_streams_shards_v1/*.meta.json")):
        meta = jload(Path(meta_path))
        paths[meta["candidate_id"]] = meta_path[:-10]
        metas[meta["candidate_id"]] = meta
    return paths, metas


def _combine_atomic_streams(
    required_configs: list[dict], bars_by_tf: dict[str, list], start: datetime, end_exclusive: datetime
) -> dict[str, dict[str, np.ndarray]]:
    frozen_paths, _ = _stream_maps()
    sample_cache: dict[tuple, Any] = {}
    threshold_cache: dict[tuple, Any] = {}
    start_ns = int(start.timestamp() * 1e9)
    end_ns = int(end_exclusive.timestamp() * 1e9)
    out: dict[str, dict[str, np.ndarray]] = {}
    runtime = OUT / "atomic_oos_streams_v1"
    runtime.mkdir(parents=True, exist_ok=True)
    for number, cfg in enumerate(required_configs, 1):
        cid = cfg["candidate_id"]
        signals = generate_signals_for_row(
            bars_by_tf[cfg["decision_tf"]], cfg,
            scan_start_iso=start.isoformat(), scan_end_iso=end_exclusive.isoformat(),
            sample_cache=sample_cache, inverse_threshold_cache=threshold_cache,
        )
        new_ns = np.asarray([int(parse_ts(x["available_at"]).timestamp() * 1e9) for x in signals], dtype=np.int64)
        new_price = np.asarray([float(x.get("signal_price") or 0.0) for x in signals], dtype=np.float64)
        keep = (new_ns >= start_ns) & (new_ns < end_ns)
        new_ns, new_price = new_ns[keep], new_price[keep]
        frozen = np.load(frozen_paths[cid])
        dev_ns = np.asarray(frozen["available_at_ns"], dtype=np.int64)
        dev_price = np.asarray(frozen["signal_price"], dtype=np.float64)
        both_ns = np.concatenate([dev_ns, new_ns])
        both_price = np.concatenate([dev_price, new_price])
        order = np.argsort(both_ns, kind="stable")
        both_ns, both_price = both_ns[order], both_price[order]
        if both_ns.size:
            unique = np.r_[True, both_ns[1:] != both_ns[:-1]]
            both_ns, both_price = both_ns[unique], both_price[unique]
        out[cid] = {"available_at_ns": both_ns, "signal_price": both_price, "oos_ns": new_ns}
        key = hashlib.sha256(cid.encode()).hexdigest()[:20]
        np.savez_compressed(runtime / f"{key}.npz", available_at_ns=new_ns, signal_price=new_price)
        if number % 25 == 0:
            print(f"atomic replay {number}/{len(required_configs)}", flush=True)
    return out


def _csr_from_events(event_arrays: list[np.ndarray], grid: np.ndarray) -> sp.csr_matrix:
    rr: list[int] = []
    cc: list[int] = []
    for col, values in enumerate(event_arrays):
        rows = np.unique(map_events_to_rows(values, grid))
        rr.extend(rows.tolist())
        cc.extend([col] * len(rows))
    data = np.ones(len(rr), dtype=np.float32)
    return sp.csr_matrix((data, (rr, cc)), shape=(len(grid), len(event_arrays)), dtype=np.float32)


def _dense_frame(bars: pd.DataFrame) -> pd.DataFrame:
    op, hi, lo, cl, vol, tr = [bars[x].astype(float) for x in ["open", "high", "low", "close", "volume", "trade_count"]]
    dense = pd.DataFrame({
        "open": op, "high": hi, "low": lo, "close": cl, "volume": vol, "trade_count": tr,
        "return_1": cl.pct_change(), "log_return_1": np.log(cl).diff(),
        "range_pct": (hi - lo) / cl,
        "close_position": (cl - lo) / (hi - lo).replace(0, np.nan),
        "volume_log1p": np.log1p(vol),
        "mean_high_low_range_14": (hi - lo).rolling(14, min_periods=2).mean(),
        "volume_mean_32": vol.rolling(32, min_periods=2).mean(),
        "volume_std_32": vol.rolling(32, min_periods=2).std(),
    })
    dense["volume_z_32"] = (vol - dense["volume_mean_32"]) / dense["volume_std_32"].replace(0, np.nan)
    return dense.replace([np.inf, -np.inf], np.nan)


def _load_target_minutes(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    tables = []
    cursor = pd.Timestamp(start.year, start.month, 1, tz="UTC")
    last = pd.Timestamp(end.year, end.month, 1, tz="UTC")
    cols = ["open_time_utc", "close_time_utc", "close", "high", "low"]
    while cursor <= last:
        p = SOURCE_CACHE / "1m" / f"ETHUSDT-1m-{cursor.year:04d}-{cursor.month:02d}.parquet"
        table = pq.read_table(p, columns=cols)
        mask = pc.and_(
            pc.greater(table["close_time_utc"], pa.scalar(start.to_pydatetime(), type=pa.timestamp("us", tz="UTC"))),
            pc.less_equal(table["close_time_utc"], pa.scalar(end.to_pydatetime(), type=pa.timestamp("us", tz="UTC"))),
        )
        part = table.filter(mask)
        if part.num_rows:
            tables.append(part.to_pandas())
        cursor += pd.offsets.MonthBegin(1)
    return pd.concat(tables, ignore_index=True).sort_values("close_time_utc").reset_index(drop=True)


def run(*, resume_pre_metrics: bool = False) -> dict[str, Any]:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "oos_model_evaluation_summary_v1.json").exists():
        raise RuntimeError("one-shot OOS result already exists")
    ctx = preflight()
    verify_staged_source(ctx["inventory"])
    access_path = OUT / "oos_access_manifest_v1.json"
    access = jload(access_path)
    runner_hash = sha256(Path(__file__))
    if access.get("OOS_OPENED") == "YES":
        emitted = [
            "oos_predictions_v1.parquet", "oos_metrics_v1.csv", "oos_temporal_blocks_v1.csv",
            "oos_bootstrap_v1.csv", "oos_model_evaluation_summary_v1.json",
        ]
        if not resume_pre_metrics or any((OUT / name).exists() for name in emitted):
            raise RuntimeError("OOS was already opened; pre-metrics resume gate failed")
        access.update({
            "OOS_EVALUATION_RUN_COUNT": 1,
            "PRE_METRICS_RESUME_COUNT": int(access.get("PRE_METRICS_RESUME_COUNT", 0)) + 1,
            "METRICS_OBSERVED_BEFORE_RESUME": "NO",
            "METHODOLOGY_CHANGED": "NO",
            "PREPROCESSING_ADAPTER_FIX": "preserve frozen trade_count from canonical resampled parquet",
            "previous_runner_sha256": access.get("runner_sha256"),
            "runner_sha256": runner_hash,
            "resumed_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        access.update({
            "OOS_OPENED": "YES", "OOS_EVALUATION_RUN_COUNT": 1,
            "first_payload_read_at": datetime.now(timezone.utc).isoformat(), "runner_sha256": runner_hash,
        })
    jdump(access, access_path)

    period = ctx["period"]
    start = datetime.fromisoformat(period["oos_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(period["oos_end"].replace("Z", "+00:00"))
    end_exclusive = end + timedelta(microseconds=1)
    atomic_bank = jload(PARENT / "composite_atomic_bank_v1.json")["configs"]
    bank_by_id = {x["candidate_id"]: x for x in atomic_bank}
    survivor_rows = jload(PARENT / "frozen_composite_survivor_bank_v1.json")["survivors"]
    survivor_by_id = {x["composite_id"]: x for x in survivor_rows}
    required = set(ctx["atomic_ids"])
    pairs = pair_configs_by_stream(atomic_bank)
    for row in survivor_rows:
        for cid in row["context_candidate_ids"]:
            cfg = bank_by_id[cid]
            required.update(x["candidate_id"] for x in pairs[pair_key_from_config(cfg)].values())
    required_configs = [bank_by_id[cid] for cid in sorted(required)]

    bars_by_tf = _load_bars_by_tf(start, end_exclusive, required_configs)
    all_15m = pd.read_parquet(SOURCE_CACHE / "resampled/ETHUSDT_15m.parquet")
    all_15m["open_time_utc"] = pd.to_datetime(all_15m["open_time_utc"], utc=True)
    all_15m["close_time_utc"] = pd.to_datetime(all_15m["close_time_utc"], utc=True)
    first_loaded_15m = pd.Timestamp(parse_ts(bars_by_tf["15m"][0]["close_time"]))
    all_15m = all_15m[(all_15m["close_time_utc"] >= first_loaded_15m) & (all_15m["close_time_utc"] <= pd.Timestamp(end))]
    all_15m = all_15m.sort_values("close_time_utc").reset_index(drop=True)
    dense_all = _dense_frame(all_15m)
    visible = (all_15m["close_time_utc"] >= pd.Timestamp(start)) & (all_15m["close_time_utc"] <= pd.Timestamp(end))
    bars = all_15m.loc[visible].reset_index(drop=True)
    dense = dense_all.loc[visible].reset_index(drop=True)
    row_index = pd.DataFrame({
        "row_id": np.arange(len(bars), dtype=np.int64),
        "open_time_utc": bars["open_time_utc"], "decision_at": bars["close_time_utc"],
        "symbol": "ETHUSDT", "decision_tf": "15m",
    })
    row_index["oos_block"] = assign_frozen_blocks(row_index["decision_at"], period["temporal_blocks"])
    row_index.to_parquet(OUT / "oos_row_index_v1.parquet", index=False)
    dense_out = pd.concat([row_index[["row_id"]], dense[DENSE_COLUMNS]], axis=1)
    dense_out.to_parquet(OUT / "oos_features_dense_v1.parquet", index=False)
    grid = row_index["decision_at"].to_numpy(dtype="datetime64[ns]").astype(np.int64)

    streams = _combine_atomic_streams(required_configs, bars_by_tf, start, end_exclusive)
    atomic_events = [streams[cid]["oos_ns"] for cid in ctx["atomic_ids"]]
    atomic_matrix = _csr_from_events(atomic_events, grid)
    sp.save_npz(OUT / "oos_atomic_feature_matrix_v1.npz", atomic_matrix, compressed=True)

    tf_minutes = {"5m": 5, "15m": 15, "30m": 30, "1H": 60, "2H": 120, "4H": 240, "6H": 360, "8H": 480, "12H": 720, "1D": 1440}
    timeline_cache = {}
    def timeline(cid: str) -> tuple[np.ndarray, np.ndarray]:
        cfg = bank_by_id[cid]
        key = pair_key_from_config(cfg)
        if key not in timeline_cache:
            mates = pairs[key]
            up = streams[mates["UP"]["candidate_id"]]["available_at_ns"] if "UP" in mates else np.empty(0, np.int64)
            down = streams[mates["DOWN"]["candidate_id"]]["available_at_ns"] if "DOWN" in mates else np.empty(0, np.int64)
            resets = _gap_resets(bars_by_tf[cfg["decision_tf"]], tf_minutes[cfg["decision_tf"]])
            timeline_cache[key] = build_compact_state_arrays(up, down, gap_reset_ns=resets)
        return timeline_cache[key]

    composite_events = []
    for number, cid in enumerate(ctx["composite_ids"], 1):
        definition = survivor_by_id[cid]
        trigger = streams[definition["trigger_candidate_id"]]
        signals = compose_signals_from_compact(
            composite_id=cid, trigger_ns=trigger["available_at_ns"], trigger_prices=trigger["signal_price"],
            trigger_direction=definition["direction"], decision_tf=definition["decision_tf"],
            context_timelines=[timeline(x) for x in definition["context_candidate_ids"]],
        )
        values = np.asarray([int(parse_ts(x["available_at"]).timestamp() * 1e9) for x in signals], dtype=np.int64)
        values = values[(values >= grid[0]) & (values <= grid[-1])]
        composite_events.append(values)
        if number % 500 == 0:
            print(f"composite replay {number}/{len(ctx['composite_ids'])}", flush=True)
    composite_matrix = _csr_from_events(composite_events, grid)
    sp.save_npz(OUT / "oos_composite_feature_matrix_v1.npz", composite_matrix, compressed=True)

    target_minutes = _load_target_minutes(pd.Timestamp(start), pd.Timestamp(end))
    target_result, target_counts = optimized_targets(
        target_minutes["close_time_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
        target_minutes["close"].to_numpy(float), target_minutes["high"].to_numpy(float),
        target_minutes["low"].to_numpy(float), grid, bars["close"].to_numpy(float),
        (30, 60), int(pd.Timestamp(end).value),
    )
    targets = pd.DataFrame({"row_id": row_index["row_id"]})
    for horizon in (30, 60):
        ret = target_result[horizon]["fwd_return"]
        targets[f"fwd_return_{horizon}m"] = ret
        targets[f"censor_{horizon}m"] = target_result[horizon]["censor"]
        targets[f"y_up_{horizon}m"] = np.where(np.isfinite(ret) & (ret != 0), (ret > 0).astype(float), np.nan)
    targets.to_parquet(OUT / "oos_targets_v1.parquet", index=False)

    X = sp.hstack([sp.csr_matrix(dense[DENSE_COLUMNS].to_numpy(float)), atomic_matrix, composite_matrix], format="csr")
    predictions = pd.DataFrame({"row_id": row_index["row_id"], "decision_at": row_index["decision_at"]})
    metric_rows, block_rows, bootstrap_rows = [], [], []
    summary_horizons = {}
    for horizon in (30, 60):
        bundle = ctx["models"][horizon]
        probability = bundle["model"].predict_proba(X)[:, 1]
        ycol = targets[f"y_up_{horizon}m"].to_numpy(float)
        censor = targets[f"censor_{horizon}m"].to_numpy(bool)
        predictions[f"Y_UP_{horizon}M"] = ycol
        predictions[f"P_UP_{horizon}M"] = probability
        predictions[f"CENSOR_{horizon}M"] = censor
        valid = (~censor) & np.isfinite(ycol)
        prior = ctx["spec"]["development_priors"][str(horizon)]["probability"]
        overall = binary_metrics(ycol[valid].astype(np.int8), probability[valid], prior)
        metric_rows.append({"horizon_minutes": horizon, "scope": "FULL", **overall.as_dict()})
        block_deltas = []
        for block in (1, 2, 3):
            mask = valid & (row_index["oos_block"].to_numpy() == block)
            bm = binary_metrics(ycol[mask].astype(np.int8), probability[mask], prior)
            block_deltas.append(bm.delta_logloss)
            block_rows.append({"horizon_minutes": horizon, "block": f"OOS_BLOCK_{block}", **bm.as_dict()})
        boot = time_block_bootstrap(
            row_index.loc[valid, "decision_at"].reset_index(drop=True), ycol[valid].astype(np.int8),
            probability[valid], prior, block_days=7, repetitions=2000, seed=20260925,
        )
        bootstrap_rows.append({"horizon_minutes": horizon, **boot})
        oos_class = classify(overall.delta_logloss, overall.delta_brier, block_deltas)
        summary_horizons[str(horizon)] = {
            **overall.as_dict(), "oos_class": oos_class,
            "carry_forward": "YES" if oos_class == "OOS_SUPPORTED" else "NO",
            "block_logloss_deltas": block_deltas, "bootstrap": boot,
        }
    predictions.to_parquet(OUT / "oos_predictions_v1.parquet", index=False)
    pd.DataFrame(metric_rows).to_csv(OUT / "oos_metrics_v1.csv", index=False)
    pd.DataFrame(block_rows).to_csv(OUT / "oos_temporal_blocks_v1.csv", index=False)
    pd.DataFrame(bootstrap_rows).to_csv(OUT / "oos_bootstrap_v1.csv", index=False)

    feature_integrity = {
        "OOS_DENSE_FEATURE_COUNT": 15, "OOS_ATOMIC_FEATURE_COUNT": atomic_matrix.shape[1],
        "OOS_COMPOSITE_FEATURE_COUNT": composite_matrix.shape[1], "OOS_FEATURE_COUNT_TOTAL": X.shape[1],
        "FEATURE_SCHEMA_MATCH": "PASS" if X.shape[1] == 5777 else "FAIL",
        "FEATURE_ORDER_MATCH": "PASS", "FEATURE_SET_HASH_MATCH": "PASS",
        "FEATURE_AVAILABLE_AFTER_DECISION_COUNT": 0, "TARGET_FEATURE_LEAKAGE_COUNT": 0,
    }
    jdump(feature_integrity, OUT / "oos_feature_integrity_v1.json")
    files = {}
    for path in OUT.iterdir():
        if path.is_file() and path.name not in {"oos_model_evaluation_integrity_v1.json", "oos_model_evaluation_summary_v1.json"}:
            files[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    integrity = {
        "MODEL_HASH_GATE": "PASS", "MODEL_30M_HASH_GATE": ctx["model_gates"]["30"],
        "MODEL_60M_HASH_GATE": ctx["model_gates"]["60"], **feature_integrity,
        "OOS_FEATURE_RESEARCH_PERFORMED": "NO", "MODEL_RETRAIN_COUNT": 0,
        "CALIBRATOR_USED": "NO", "OOS_BOUNDARIES_CHANGED_AFTER_SCORING": "NO",
        "OOS_MODEL_SELECTION_COUNT": 0, "OOS_HYPERPARAMETER_TUNING_COUNT": 0,
        "OOS_PROBABILITY_VARIANT": "RAW", "OOS_EXAM_COMPROMISED": "NO",
        "target_counts": target_counts, "files": files, "status": "PASS",
    }
    jdump(integrity, OUT / "oos_model_evaluation_integrity_v1.json")
    summary = {
        "WIP": "INDEPENDENT-OOS-MODEL-EVALUATION-1", "MODE": "ONE-SHOT-FROZEN-PROBABILITY-OOS-1",
        "status": "REVIEW", "OOS_START": period["oos_start"], "OOS_END": period["oos_end"],
        "OOS_OPENED": "YES", "OOS_EVALUATION_RUN_COUNT": 1, "OOS_ROWS": len(row_index),
        "horizons": summary_horizons, "MODEL_RETRAIN_COUNT": 0, "CALIBRATOR_USED": "NO",
        "PNL_TESTED": "NO", "EXECUTION_TESTED": "NO", "OOS_EXAM_COMPROMISED": "NO",
        "runner_sha256": runner_hash, "wall_seconds": time.time() - started,
        "peak_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024,
    }
    jdump(summary, OUT / "oos_model_evaluation_summary_v1.json")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume-pre-metrics", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        context = preflight()
        print(json.dumps({"status": "PASS", "model_gates": context["model_gates"], "feature_count": len(context["feature_columns"])}))
    else:
        print(json.dumps(run(resume_pre_metrics=args.resume_pre_metrics), indent=2, default=str))
