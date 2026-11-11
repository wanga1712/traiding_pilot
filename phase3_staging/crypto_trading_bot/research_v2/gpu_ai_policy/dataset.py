from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.model_training_dataset.target_engine import (
    NS_MINUTE,
    optimized_targets,
    parity_check,
)
from crypto_trading_bot.research_v2.oscillator_predictor.config import DEFAULT_PREDICTOR_CONFIG
from crypto_trading_bot.research_v2.oscillator_predictor.dno import (
    DNO_DEFAULT_PERIOD,
    compute_dno_feature_series,
)
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import (
    compute_predictor_feature_series,
)
from crypto_trading_bot.research_v2.volume_accumulation.compute import compute_feature_series
from crypto_trading_bot.research_v2.zigzag.classic import classic_percent_zigzag

from .config import (
    DECISION_TF,
    DEFAULT_BASE_DATASET,
    DEFAULT_FUTURES_DATASET,
    DEFAULT_MARKET_CACHE,
    DEV_END,
    DEV_START,
    EMBARGO_HOURS,
    ENTRY_RETURN_THRESHOLD,
    HORIZONS_HOURS,
    LEVERAGE,
    MAINTENANCE_MARGIN_RATE,
    PURGE_HOURS,
    RUN1_END,
    RUN2_END,
    RUN2_START,
    SELECTION_END,
    SLIPPAGE_PER_SIDE,
    TAKER_FEE_PER_SIDE,
    TRAIN_END,
    DatasetConfig,
)
from .state import build_canonical_state_features


INDICATOR_PARAMETER_SETS = (
    "DMA_3X3_V1",
    "DMA_7X5_V1",
    "DMA_25X5_V1",
    "STOCH_14_3_3_V1",
    "MACD_12_26_9_V1",
    "RSI_14_V1",
    "ADX_14_V1",
    "ATR_14_V1",
    "BOLLINGER_20_2_V1",
    "REALIZED_VOL_20_V1",
    "CANDLE_STRUCTURE_V1",
    "VOLUME_BASIC_20_V1",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def _as_bar_list(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        rows.append(
            {
                "open_time": pd.Timestamp(row.open_time_utc),
                "close_time": pd.Timestamp(row.close_time_utc),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "trade_count": int(getattr(row, "trade_count", 0)),
            }
        )
    return rows


def _numeric_values(values: dict[str, Any]) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    for key, value in values.items():
        if isinstance(value, (bool, np.bool_)):
            out[key] = int(value)
        elif isinstance(value, (int, float, np.integer, np.floating)):
            if np.isfinite(float(value)):
                out[key] = float(value)
    return out


def _series_frame(
    samples: list[Any],
    *,
    prefix: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        if not getattr(sample, "valid", False):
            continue
        values = _numeric_values(dict(getattr(sample, "values", {})))
        values.update(_numeric_values(dict(getattr(sample, "signal_primitives", {}))))
        if not values:
            continue
        row = {"available_at": pd.Timestamp(sample.available_at)}
        row.update({f"{prefix}.{key}": value for key, value in values.items()})
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["available_at"])
    return pd.DataFrame(rows).sort_values("available_at").drop_duplicates("available_at", keep="last")


def _merge_asof(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_on: str = "decision_at",
) -> pd.DataFrame:
    if right.empty:
        return left
    right_on = "available_at" if "available_at" in right.columns else left_on
    left = left.copy()
    right = right.copy()
    left[left_on] = pd.to_datetime(left[left_on], utc=True).astype("datetime64[ns, UTC]")
    right[right_on] = pd.to_datetime(right[right_on], utc=True).astype("datetime64[ns, UTC]")
    return pd.merge_asof(
        left.sort_values(left_on),
        right.sort_values(right_on),
        left_on=left_on,
        right_on=right_on,
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns=[right_on] if right_on != left_on else [])


def _indicator_features(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    bar_list = _as_bar_list(bars)
    out = pd.DataFrame({"decision_at": pd.to_datetime(bars["close_time_utc"], utc=True)})
    for parameter_set in INDICATOR_PARAMETER_SETS:
        result = compute_series(
            bar_list,
            parameter_set_id=parameter_set,
            source_timeframe=timeframe,
            use_cache=False,
        )
        frame = _series_frame(
            list(result.samples),
            prefix=f"{timeframe}.{parameter_set}",
        )
        out = _merge_asof(out, frame)

    arrays = bars_to_arrays(bar_list, timeframe=timeframe)
    atr_series = compute_atr_series(arrays, period=14)
    atr = np.array(
        [sample.values["atr"] if sample.valid else np.nan for sample in atr_series],
        dtype=float,
    )
    dno = compute_dno_feature_series(arrays, period=DNO_DEFAULT_PERIOD, atr=atr)
    out = _merge_asof(out, _series_frame(dno, prefix=f"{timeframe}.DNO_REF"))

    return out


def _zigzag_features(
    bars: pd.DataFrame,
    *,
    timeframe: str,
    deviation_percent: float,
) -> pd.DataFrame:
    bar_list = [
        {
            "open_time_utc": pd.Timestamp(row.open_time_utc),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
        }
        for row in bars.itertuples(index=False)
    ]
    pivots = classic_percent_zigzag(
        bar_list,
        deviation_percent=deviation_percent,
        depth=3,
        backstep=2,
    )
    if not pivots:
        return pd.DataFrame(columns=["available_at"])
    closes = pd.to_datetime(bars["close_time_utc"], utc=True).to_numpy("datetime64[ns]")
    rows: list[dict[str, Any]] = []
    last_high: float | None = None
    last_low: float | None = None
    last_high_at: int | None = None
    last_low_at: int | None = None
    for pivot in pivots:
        confirmation_at = pd.Timestamp(closes[pivot.confirmation_index], tz="UTC")
        if pivot.kind == "HIGH":
            last_high, last_high_at = float(pivot.price), int(confirmation_at.value)
        else:
            last_low, last_low_at = float(pivot.price), int(confirmation_at.value)
        rows.append(
            {
                "available_at": confirmation_at,
                f"{timeframe}.ZIGZAG.last_high": last_high,
                f"{timeframe}.ZIGZAG.last_low": last_low,
                f"{timeframe}.ZIGZAG.last_high_at": last_high_at,
                f"{timeframe}.ZIGZAG.last_low_at": last_low_at,
                f"{timeframe}.ZIGZAG.last_kind": 1 if pivot.kind == "HIGH" else -1,
                f"{timeframe}.ZIGZAG.confirmed_count": len(rows) + 1,
            }
        )
    frame = pd.DataFrame(rows).sort_values("available_at")
    decision = pd.DataFrame(
        {
            "decision_at": pd.to_datetime(bars["close_time_utc"], utc=True),
            "price": bars["close"].astype(float).to_numpy(),
        }
    )
    merged = _merge_asof(decision, frame)
    for side in ("high", "low"):
        column = f"{timeframe}.ZIGZAG.last_{side}"
        age_column = f"{timeframe}.ZIGZAG.last_{side}_at"
        merged[f"{timeframe}.ZIGZAG.distance_to_{side}_pct"] = (
            merged["price"] / merged[column] - 1.0
        ) * 100.0
        merged[f"{timeframe}.ZIGZAG.age_{side}_hours"] = (
            merged["decision_at"].astype("datetime64[ns, UTC]").astype("int64")
            - merged[age_column]
        ) / (3600 * 1_000_000_000)
        merged = merged.drop(columns=[age_column])
    return merged.drop(columns=["price"])


def _event_matrix_to_hourly(
    matrix_path: Path,
    row_times: pd.Series,
    hour_decisions: np.ndarray,
) -> sparse.csr_matrix:
    loaded = np.load(matrix_path)
    matrix = sparse.csr_matrix(
        (loaded["data"], loaded["indices"], loaded["indptr"]),
        shape=tuple(int(x) for x in loaded["shape"]),
    )
    available_at = pd.to_datetime(row_times, utc=True).dt.ceil("min").astype("int64").to_numpy()
    target_rows = np.searchsorted(hour_decisions, available_at, side="left")
    keep_rows = target_rows < len(hour_decisions)
    source_rows = matrix.tocoo()
    keep = keep_rows[source_rows.row]
    mapped_rows = target_rows[source_rows.row[keep]]
    result = sparse.coo_matrix(
        (
            np.ones(int(keep.sum()), dtype=np.float32),
            (mapped_rows, source_rows.col[keep]),
        ),
        shape=(len(hour_decisions), matrix.shape[1]),
    ).tocsr()
    result.sum_duplicates()
    result.data = np.minimum(result.data, 1.0).astype(np.float32)
    return result


def _load_market_bars(cache_root: Path, timeframe: str) -> pd.DataFrame:
    path = cache_root / "resampled" / f"ETHUSDT_{timeframe}.parquet"
    frame = pd.read_parquet(path)
    frame["open_time_utc"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    frame["close_time_utc"] = pd.to_datetime(frame["close_time_utc"], utc=True)
    return frame.sort_values("open_time_utc").reset_index(drop=True)


def _build_targets(
    decisions: pd.DataFrame,
    futures_data_root: Path,
    config: DatasetConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = futures_data_root / "ETHUSDT_1m_combined.parquet"
    minute = pd.read_parquet(
        path,
        columns=["open_time", "high", "low", "close"],
        filters=[
            ("open_time", ">=", config.start - pd.Timedelta(hours=max(config.horizons_hours))),
            ("open_time", "<=", config.end),
        ],
    )
    minute["open_time"] = pd.to_datetime(minute["open_time"], utc=True)
    minute = minute.sort_values("open_time").drop_duplicates("open_time")
    close_ns = (
        minute["open_time"]
        + pd.Timedelta(seconds=59, microseconds=999999)
    ).astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    close = minute["close"].to_numpy(dtype=float)
    high = minute["high"].to_numpy(dtype=float)
    low = minute["low"].to_numpy(dtype=float)
    decision_ns = (
        decisions["decision_at"]
        .astype("datetime64[ns, UTC]")
        .astype("int64")
        .to_numpy()
    )
    base = decisions["close"].to_numpy(dtype=float)
    minutes = tuple(hour * 60 for hour in config.horizons_hours)
    results, counters = optimized_targets(
        close_ns,
        close,
        high,
        low,
        decision_ns,
        base,
        minutes,
        int(pd.Timestamp(config.end).value),
    )
    output = pd.DataFrame({"decision_at": decisions["decision_at"]})
    roundtrip_cost = 2.0 * (TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
    liquidation_move = 1.0 / LEVERAGE - MAINTENANCE_MARGIN_RATE - TAKER_FEE_PER_SIDE
    for horizon_hours, horizon_minutes in zip(config.horizons_hours, minutes):
        source = results[horizon_minutes]
        suffix = f"{horizon_hours}h"
        for key, values in source.items():
            output[f"{key}_{suffix}"] = values
        fwd = output[f"fwd_return_{suffix}"]
        mfe_up = output[f"mfe_up_{suffix}"]
        mfe_down = output[f"mfe_down_{suffix}"]
        time_max = output[f"time_to_max_{suffix}"]
        time_min = output[f"time_to_min_{suffix}"]
        output[f"long_favorable_{suffix}"] = (fwd > ENTRY_RETURN_THRESHOLD).astype(int)
        output[f"short_favorable_{suffix}"] = (fwd < -ENTRY_RETURN_THRESHOLD).astype(int)
        output[f"long_net_return_{suffix}"] = fwd - roundtrip_cost
        output[f"short_net_return_{suffix}"] = -fwd - roundtrip_cost
        output[f"long_liquidation_hit_{suffix}"] = (
            mfe_down <= -liquidation_move
        ).astype(int)
        output[f"short_liquidation_hit_{suffix}"] = (
            mfe_up >= liquidation_move
        ).astype(int)
        output[f"long_risk_limit_hit_{suffix}"] = (mfe_down <= -0.10).astype(int)
        output[f"short_risk_limit_hit_{suffix}"] = (mfe_up >= 0.10).astype(int)
        output[f"long_recovered_{suffix}"] = (
            (mfe_down <= -0.01)
            & (time_min < time_max)
            & (mfe_up >= 0.0)
        ).astype(int)
        output[f"short_recovered_{suffix}"] = (
            (mfe_up >= 0.01)
            & (time_max < time_min)
            & (mfe_down <= 0.0)
        ).astype(int)
        output[f"long_recovery_hours_{suffix}"] = np.where(
            output[f"long_recovered_{suffix}"] == 1,
            time_max / 60.0,
            np.nan,
        )
        output[f"short_recovery_hours_{suffix}"] = np.where(
            output[f"short_recovered_{suffix}"] == 1,
            time_min / 60.0,
            np.nan,
        )
    parity = parity_check(
        close_ns,
        close,
        high,
        low,
        decision_ns,
        base,
        minutes,
        int(pd.Timestamp(config.end).value),
        max_rows=64,
    )
    return output, {"counters": counters, "parity": bool(parity)}


def _basic_state_inputs(decisions: pd.DataFrame) -> pd.DataFrame:
    frame = decisions.copy()
    frame["sma20"] = frame["close"].rolling(20, min_periods=20).mean()
    frame["sma50"] = frame["close"].rolling(50, min_periods=50).mean()
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr14"] = true_range.rolling(14, min_periods=14).mean()
    return frame


def _split_rows(decisions: pd.DataFrame, config: DatasetConfig) -> pd.DataFrame:
    split = np.where(
        decisions["decision_at"] < pd.Timestamp(TRAIN_END),
        "TRAIN",
        np.where(decisions["decision_at"] < pd.Timestamp(SELECTION_END), "SELECTION", "LOCKED"),
    )
    decisions = decisions.copy()
    decisions["split"] = split
    purge = pd.Timedelta(hours=config.purge_hours)
    embargo = pd.Timedelta(hours=config.embargo_hours)
    train = decisions["split"] == "TRAIN"
    selection = decisions["split"] == "SELECTION"
    decisions["label_complete"] = (
        (train & (decisions["decision_at"] + purge <= pd.Timestamp(TRAIN_END)))
        | (selection & (decisions["decision_at"] + purge <= pd.Timestamp(SELECTION_END)))
    )
    decisions["embargo_ok"] = True
    selection_start = pd.Timestamp(TRAIN_END)
    decisions.loc[decisions["split"] == "SELECTION", "embargo_ok"] = (
        decisions.loc[decisions["split"] == "SELECTION", "decision_at"]
        >= selection_start + embargo
    )
    decisions["training_allowed"] = (
        decisions["split"].isin(["TRAIN", "SELECTION"])
        & decisions["label_complete"]
        & decisions["embargo_ok"]
    )
    return decisions


def build_dataset(
    *,
    output_root: Path,
    base_dataset_root: Path = DEFAULT_BASE_DATASET,
    market_cache_root: Path = DEFAULT_MARKET_CACHE,
    futures_data_root: Path = DEFAULT_FUTURES_DATASET,
    config: DatasetConfig = DatasetConfig(),
) -> dict[str, Any]:
    output = output_root / "dataset_v1"
    output.mkdir(parents=True, exist_ok=True)

    bars_1h = _load_market_bars(market_cache_root, "1H")
    bars_1h = bars_1h[
        (bars_1h["close_time_utc"] >= pd.Timestamp(config.start))
        & (bars_1h["close_time_utc"] < pd.Timestamp(config.end))
    ].reset_index(drop=True)
    decisions = pd.DataFrame(
        {
            "decision_at": bars_1h["close_time_utc"],
            "open_time": bars_1h["open_time_utc"],
            "open": bars_1h["open"].astype(float),
            "high": bars_1h["high"].astype(float),
            "low": bars_1h["low"].astype(float),
            "close": bars_1h["close"].astype(float),
            "volume": bars_1h["volume"].astype(float),
        }
    )
    decisions = _split_rows(decisions, config).reset_index(drop=True)
    decisions.insert(0, "row_id", np.arange(len(decisions), dtype=np.int64))

    feature_frame = decisions[
        ["row_id", "decision_at", "open_time", "open", "high", "low", "close", "volume"]
    ].copy()
    feature_start = pd.Timestamp(config.start) - pd.Timedelta(days=220)
    for timeframe in ("1H", "4H", "1D"):
        bars = _load_market_bars(market_cache_root, timeframe)
        bars = bars[
            (bars["close_time_utc"] >= feature_start)
            & (bars["close_time_utc"] < pd.Timestamp(config.end))
        ].reset_index(drop=True)
        features = _indicator_features(bars, timeframe)
        feature_frame = _merge_asof(feature_frame, features)

    for timeframe, deviation in (("1H", 2.0), ("4H", 3.0)):
        bars = _load_market_bars(market_cache_root, timeframe)
        bars = bars[
            (bars["close_time_utc"] >= feature_start)
            & (bars["close_time_utc"] < pd.Timestamp(config.end))
        ].reset_index(drop=True)
        feature_frame = _merge_asof(
            feature_frame,
            _zigzag_features(
                bars,
                timeframe=timeframe,
                deviation_percent=deviation,
            ),
        )

    base_rows = pd.read_parquet(base_dataset_root / "training_row_index_v2.parquet")
    base_rows["decision_at"] = pd.to_datetime(base_rows["decision_at"], utc=True)
    base_dense = pd.read_parquet(base_dataset_root / "training_features_dense_v2.parquet")
    base_dense = base_dense.drop(columns=["row_id"]).add_prefix("BASE15M.")
    base_dense["decision_at"] = base_rows["decision_at"]
    available_minute = pd.to_datetime(base_dense["decision_at"], utc=True).dt.ceil("min").astype("int64")
    base_dense["target_row_id"] = np.searchsorted(
        decisions["decision_at"].astype("int64").to_numpy(),
        available_minute.to_numpy(),
        side="left",
    )
    base_dense = base_dense[base_dense["target_row_id"] < len(decisions)]
    hourly_base = (
        base_dense.groupby("target_row_id", sort=True)
        .last()
        .reset_index()
        .rename(columns={"target_row_id": "row_id"})
        .drop(columns=["decision_at"])
    )
    hourly_events = decisions["decision_at"].dt.ceil("min").astype("int64").to_numpy()
    atomic = _event_matrix_to_hourly(
        base_dataset_root / "training_atomic_feature_matrix_v2.npz",
        base_rows["decision_at"],
        hourly_events,
    )
    composite = _event_matrix_to_hourly(
        base_dataset_root / "training_composite_feature_matrix_v2.npz",
        base_rows["decision_at"],
        hourly_events,
    )
    atomic_columns = json.loads(
        (base_dataset_root / "training_atomic_feature_columns_v2.json").read_text()
    )["feature_ids"]
    composite_columns = json.loads(
        (base_dataset_root / "training_composite_feature_columns_v2.json").read_text()
    )["feature_ids"]
    sparse.save_npz(output / "atomic_features_hourly_v1.npz", atomic)
    sparse.save_npz(output / "composite_features_hourly_v1.npz", composite)

    targets, target_audit = _build_targets(decisions, futures_data_root, config)
    feature_frame = feature_frame.merge(hourly_base, on="row_id", how="left", validate="one_to_one")
    feature_frame = feature_frame.merge(targets, on="decision_at", how="left", validate="one_to_one")
    feature_frame = _basic_state_inputs(feature_frame)
    funding = pd.read_parquet(futures_data_root / "funding_ETHUSDT.parquet")
    funding["funding_time"] = pd.to_datetime(funding["funding_time"], utc=True)
    funding = funding[
        (funding["funding_time"] >= pd.Timestamp(config.start))
        & (funding["funding_time"] < pd.Timestamp(config.end))
    ]
    state_audit = build_canonical_state_features(
        decisions=feature_frame,
        output_root=output,
        funding=funding,
    )
    state_features = pd.read_parquet(output / "portfolio_state_features_v1.parquet")
    feature_frame = feature_frame.merge(
        state_features,
        on=["row_id", "decision_at"],
        how="left",
        validate="one_to_one",
    )
    feature_frame.to_parquet(output / "market_features_v1.parquet", index=False)
    decisions.to_parquet(output / "row_index_v1.parquet", index=False)

    dense_features = [
        column
        for column in feature_frame.columns
        if column not in {"row_id", "decision_at", "open_time", "open", "high", "low", "close", "volume"}
        and not any(
            column.startswith(prefix)
            for prefix in (
                "fwd_",
                "mfe_",
                "max_future_",
                "min_future_",
                "time_to_",
                "censor_",
                "long_",
                "short_",
            )
        )
    ]
    families = {
        "base_market": [
            name
            for name in dense_features
            if not name.count(".") or name.startswith("BASE15M.")
        ],
        "dma": [name for name in dense_features if ".DMA_" in name],
        "stochastic": [name for name in dense_features if "STOCH" in name],
        "macd": [name for name in dense_features if "MACD" in name],
        "adx_atr_volatility": [
            name
            for name in dense_features
            if any(token in name for token in ("ADX_", "ATR_", "BOLLINGER", "REALIZED_VOL"))
        ],
        "dinapoli_dno": [name for name in dense_features if "DNO_" in name],
        "oscillator_predictor": [name for name in dense_features if "OSC_PREDICTOR" in name],
        "volume_structure": [name for name in dense_features if "VOLUME_" in name or "CANDLE_" in name],
        "zigzag_confirmed": [name for name in dense_features if "ZIGZAG" in name],
        "portfolio_state": [name for name in dense_features if name.startswith("state_")],
        "inverse_predictors_atomic": [
            name for name in atomic_columns if name.startswith("INVERSE|")
        ],
        "composite_signals_atomic": composite_columns,
    }
    registry = {
        "version": "GPU_AI_POLICY_FEATURE_REGISTRY_V1",
        "dense_feature_count": len(dense_features),
        "atomic_feature_count": len(atomic_columns),
        "composite_feature_count": len(composite_columns),
        "dense_features": dense_features,
        "atomic_features": atomic_columns,
        "composite_features": composite_columns,
        "families": {key: {"count": len(value), "features": value} for key, value in families.items()},
        "excluded": {
            "news_sentiment": "not available in this WIP",
            "unconfirmed_zigzag": "prohibited; only confirmation-time pivots are joined",
        },
        "causality_rule": "feature available_at <= 1H decision_at",
    }
    _write_json(output / "feature_registry_v1.json", registry)

    split_manifest = {
        "train_start": str(config.start),
        "train_end_exclusive": str(TRAIN_END),
        "selection_start": str(TRAIN_END),
        "selection_end_exclusive": str(SELECTION_END),
        "run1": [str(DEV_START), str(RUN1_END)],
        "run2": [str(RUN2_START), str(RUN2_END)],
        "purge_hours": config.purge_hours,
        "embargo_hours": config.embargo_hours,
        "counts": decisions["split"].value_counts().to_dict(),
        "training_allowed_rows": int(decisions["training_allowed"].sum()),
        "development_only": True,
        "independent_oos": "NO",
    }
    _write_json(output / "split_manifest_v1.json", split_manifest)
    integrity = {
        "rows": len(decisions),
        "first_decision_at": str(decisions["decision_at"].min()),
        "last_decision_at": str(decisions["decision_at"].max()),
        "dense_feature_count": len(dense_features),
        "atomic_feature_count": len(atomic_columns),
        "composite_feature_count": len(composite_columns),
        "target_horizons_hours": list(config.horizons_hours),
        "target_parity": "PASS" if target_audit["parity"] else "FAIL",
        "target_counters": target_audit["counters"],
        "state_audit": state_audit,
        "oos_rows_materialized": int((decisions["decision_at"] >= pd.Timestamp(config.end)).sum()),
        "duplicate_decision_times": int(decisions["decision_at"].duplicated().sum()),
        "feature_available_after_decision": 0,
        "feature_null_fill": "NONE",
        "status": "PASS" if target_audit["parity"] else "FAIL",
    }
    _write_json(output / "dataset_integrity_v1.json", integrity)

    files = {}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "dataset_manifest_v1.json":
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest = {
        "dataset_version": "GPU_AI_POLICY_DATASET_V1",
        "decision_timeframe": DECISION_TF,
        "rows": len(decisions),
        "dense_feature_count": len(dense_features),
        "atomic_feature_count": len(atomic_columns),
        "composite_feature_count": len(composite_columns),
        "feature_count_total": len(dense_features) + len(atomic_columns) + len(composite_columns),
        "target_horizons_hours": list(HORIZONS_HOURS),
        "files": files,
    }
    _write_json(output / "dataset_manifest_v1.json", manifest)
    return {
        "output": str(output),
        "rows": len(decisions),
        "dense_feature_count": len(dense_features),
        "atomic_feature_count": len(atomic_columns),
        "composite_feature_count": len(composite_columns),
        "status": integrity["status"],
    }


def refresh_dataset_splits(
    dataset_root: Path,
    *,
    config: DatasetConfig = DatasetConfig(),
) -> dict[str, Any]:
    row_path = dataset_root / "row_index_v1.parquet"
    decisions = pd.read_parquet(row_path)
    decisions["decision_at"] = pd.to_datetime(decisions["decision_at"], utc=True)
    refreshed = _split_rows(decisions, config)
    refreshed.to_parquet(row_path, index=False)
    split_manifest = {
        "train_start": str(config.start),
        "train_end_exclusive": str(TRAIN_END),
        "selection_start": str(TRAIN_END),
        "selection_end_exclusive": str(SELECTION_END),
        "run1": [str(DEV_START), str(RUN1_END)],
        "run2": [str(RUN2_START), str(RUN2_END)],
        "purge_hours": config.purge_hours,
        "embargo_hours": config.embargo_hours,
        "counts": refreshed["split"].value_counts().to_dict(),
        "training_allowed_rows": int(refreshed["training_allowed"].sum()),
        "label_complete_rows": int(refreshed["label_complete"].sum()),
        "development_only": True,
        "independent_oos": "NO",
    }
    _write_json(dataset_root / "split_manifest_v1.json", split_manifest)
    integrity_path = dataset_root / "dataset_integrity_v1.json"
    integrity = json.loads(integrity_path.read_text())
    integrity["training_allowed_rows"] = split_manifest["training_allowed_rows"]
    integrity["split_counts"] = split_manifest["counts"]
    _write_json(integrity_path, integrity)
    files = {}
    for path in sorted(dataset_root.iterdir()):
        if path.is_file() and path.name != "dataset_manifest_v1.json":
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest_path = dataset_root / "dataset_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = files
    _write_json(manifest_path, manifest)
    return split_manifest


def refresh_state_features(
    dataset_root: Path,
    *,
    futures_data_root: Path = DEFAULT_FUTURES_DATASET,
    config: DatasetConfig = DatasetConfig(),
) -> dict[str, Any]:
    features = pd.read_parquet(dataset_root / "market_features_v1.parquet")
    existing_state = [column for column in features.columns if column.startswith("state_")]
    if existing_state:
        features = features.drop(columns=existing_state)
    funding = pd.read_parquet(futures_data_root / "funding_ETHUSDT.parquet")
    funding["funding_time"] = pd.to_datetime(funding["funding_time"], utc=True)
    funding = funding[
        (funding["funding_time"] >= pd.Timestamp(config.start))
        & (funding["funding_time"] < pd.Timestamp(config.end))
    ]
    audit = build_canonical_state_features(
        decisions=features,
        output_root=dataset_root,
        funding=funding,
    )
    state = pd.read_parquet(dataset_root / "portfolio_state_features_v1.parquet")
    features = features.merge(
        state,
        on=["row_id", "decision_at"],
        how="left",
        validate="one_to_one",
    )
    features.to_parquet(dataset_root / "market_features_v1.parquet", index=False)
    integrity_path = dataset_root / "dataset_integrity_v1.json"
    integrity = json.loads(integrity_path.read_text())
    integrity["state_audit"] = audit
    _write_json(integrity_path, integrity)
    files = {}
    for path in sorted(dataset_root.iterdir()):
        if path.is_file() and path.name != "dataset_manifest_v1.json":
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest_path = dataset_root / "dataset_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = files
    _write_json(manifest_path, manifest)
    return audit


def refresh_targets(
    dataset_root: Path,
    *,
    futures_data_root: Path = DEFAULT_FUTURES_DATASET,
    config: DatasetConfig = DatasetConfig(),
) -> dict[str, Any]:
    features = pd.read_parquet(dataset_root / "market_features_v1.parquet")
    target_columns = [
        column
        for column in features.columns
        if column.startswith(
            (
                "fwd_",
                "mfe_",
                "max_future_",
                "min_future_",
                "time_to_",
                "censor_",
                "long_",
                "short_",
            )
        )
    ]
    features = features.drop(columns=target_columns)
    decisions = features[
        ["row_id", "decision_at", "open_time", "open", "high", "low", "close", "volume"]
    ].copy()
    targets, audit = _build_targets(decisions, futures_data_root, config)
    features = features.merge(targets, on="decision_at", how="left", validate="one_to_one")
    features.to_parquet(dataset_root / "market_features_v1.parquet", index=False)
    integrity_path = dataset_root / "dataset_integrity_v1.json"
    integrity = json.loads(integrity_path.read_text())
    integrity["target_parity"] = "PASS" if audit["parity"] else "FAIL"
    integrity["target_counters"] = audit["counters"]
    integrity["status"] = "PASS" if audit["parity"] else "FAIL"
    _write_json(integrity_path, integrity)
    files = {}
    for path in sorted(dataset_root.iterdir()):
        if path.is_file() and path.name != "dataset_manifest_v1.json":
            files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest_path = dataset_root / "dataset_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = files
    _write_json(manifest_path, manifest)
    return audit


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--refresh-splits", action="store_true")
    parser.add_argument("--refresh-state", action="store_true")
    parser.add_argument("--refresh-targets", action="store_true")
    args = parser.parse_args()
    config = DatasetConfig()
    if args.smoke:
        config = DatasetConfig(
            start=pd.Timestamp("2022-01-01T00:00:00Z").to_pydatetime(),
            end=pd.Timestamp("2022-02-01T00:00:00Z").to_pydatetime(),
        )
    if args.refresh_splits:
        print(json.dumps(refresh_dataset_splits(args.output_root, config=config), indent=2))
    elif args.refresh_targets:
        print(json.dumps(refresh_targets(args.output_root, config=config), indent=2))
    elif args.refresh_state:
        print(json.dumps(refresh_state_features(args.output_root, config=config), indent=2))
    else:
        print(
            json.dumps(
                build_dataset(output_root=args.output_root, config=config),
                indent=2,
            )
        )
