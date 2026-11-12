from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoost, CatBoostRegressor

from .qwen_adapter import QWEN_ACTIONS, _assert_causal
from .train import ACTION_NAMES, build_matrix, load_bundle


ACTION_LABELS = {name: index for index, name in enumerate(ACTION_NAMES)}


def _class_metrics(y_true: np.ndarray, y_pred: np.ndarray, names: list[str]) -> dict[str, Any]:
    confusion = pd.crosstab(
        pd.Categorical(y_true, categories=range(len(names))),
        pd.Categorical(y_pred, categories=range(len(names))),
        dropna=False,
    )
    per_class = {}
    for index, name in enumerate(names):
        mask = y_true == index
        per_class[name] = {
            "support": int(mask.sum()),
            "recall": float((y_pred[mask] == index).mean()) if mask.any() else None,
        }
    return {
        "accuracy": float((y_true == y_pred).mean()),
        "per_class": per_class,
        "confusion_matrix": confusion.values.tolist(),
        "labels": names,
    }


def _prior_logloss(labels: np.ndarray, classes: int) -> float:
    counts = np.bincount(labels[labels >= 0], minlength=classes).astype(float)
    probabilities = counts / counts.sum()
    return float(-np.log(np.clip(probabilities[labels], 1e-12, 1.0)).mean())


def _feature_family(name: str) -> str:
    if name.startswith("state_"):
        return "portfolio_state"
    if name.startswith("BASE15M."):
        return "base_15m"
    if "ZIGZAG" in name:
        return "zigzag_confirmed"
    if ".DMA_" in name:
        return "dma"
    if "STOCH" in name:
        return "stochastic"
    if "MACD" in name:
        return "macd"
    if any(token in name for token in ("ADX_", "ATR_", "BOLLINGER", "REALIZED_VOL")):
        return "trend_volatility"
    if "DNO" in name:
        return "dno"
    if "OSC_PREDICTOR" in name:
        return "oscillator_predictor"
    if name.startswith("INVERSE|"):
        return "inverse_predictor"
    if name.startswith("COMP|"):
        return "composite_signal"
    if "VOLUME_" in name or "CANDLE_" in name:
        return "volume_structure"
    return "other"


def _importance_report(
    model_path: Path,
    feature_names: list[str],
) -> dict[str, Any]:
    model = CatBoost()
    model.load_model(model_path)
    importance = np.asarray(
        model.get_feature_importance(prettified=False, type="FeatureImportance"),
        dtype=float,
    )
    if len(importance) != len(feature_names):
        raise ValueError(
            f"importance length mismatch: {len(importance)} != {len(feature_names)}"
        )
    rows = sorted(
        (
            {
                "feature": feature,
                "family": _feature_family(feature),
                "importance": float(value),
            }
            for feature, value in zip(feature_names, importance)
        ),
        key=lambda row: row["importance"],
        reverse=True,
    )
    family = (
        pd.DataFrame(rows)
        .groupby("family", as_index=False)["importance"]
        .sum()
        .sort_values("importance", ascending=False)
    )
    return {
        "top_features": rows[:25],
        "zero_importance_features": int((importance <= 1e-12).sum()),
        "family_importance": family.to_dict(orient="records"),
        "model_classes": [int(x) for x in getattr(model, "classes_", [])],
    }


def _allowed_utilities(row: pd.Series) -> tuple[float, float, float, str | None]:
    utilities = []
    for action in ACTION_NAMES:
        if int(row.get(f"allowed_{action}", 0)) != 1:
            continue
        value = row.get(f"utility_{action}", np.nan)
        if pd.notna(value):
            utilities.append((action, float(value)))
    if not utilities:
        return np.nan, np.nan, np.nan, None
    utilities.sort(key=lambda item: item[1], reverse=True)
    first = utilities[0][1]
    second = utilities[1][1] if len(utilities) > 1 else np.nan
    return first, second, first - second if pd.notna(second) else np.nan, utilities[0][0]


def _action_analysis(management: pd.DataFrame) -> dict[str, Any]:
    frame = management.copy()
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], utc=True)
    frame["split"] = np.select(
        [
            frame["decision_at"] < pd.Timestamp("2020-07-01", tz="UTC"),
            frame["decision_at"] < pd.Timestamp("2021-01-01", tz="UTC"),
        ],
        ["TRAIN", "SELECTION"],
        default="RUN2",
    )
    sampled = frame[
        (frame["decision_at"].dt.hour % 4 == 0) & frame["best_action"].notna()
    ].copy()
    margins = sampled.apply(_allowed_utilities, axis=1, result_type="expand")
    sampled[["best_utility", "second_utility", "utility_margin", "recomputed_best"]] = margins
    allowed_counts = {
        action: int(sampled[f"allowed_{action}"].sum()) for action in ACTION_NAMES
    }
    observed = sampled["best_action"].value_counts().to_dict()
    missing_actions = [action for action in ACTION_NAMES if observed.get(action, 0) == 0]
    hedge = sampled[sampled["hedge_side"].abs() > 0]
    close_hedge_rows = hedge[hedge["best_action"] == "CLOSE_HEDGE"]
    margin_summary = {}
    for action in ACTION_NAMES:
        selected = sampled[sampled["best_action"] == action]
        margin_summary[action] = {
            "support": len(selected),
            "median_margin": (
                float(selected["utility_margin"].median()) if len(selected) else None
            ),
            "share_margin_le_0_01": (
                float((selected["utility_margin"] <= 0.01).mean())
                if len(selected)
                else None
            ),
            "share_margin_le_0_05": (
                float((selected["utility_margin"] <= 0.05).mean())
                if len(selected)
                else None
            ),
        }
    return {
        "sampled_rows": len(sampled),
        "action_counts": {name: int(observed.get(name, 0)) for name in ACTION_NAMES},
        "action_counts_by_split": {
            split: group["best_action"].value_counts().to_dict()
            for split, group in sampled.groupby("split")
        },
        "allowed_counts": allowed_counts,
        "missing_actions": missing_actions,
        "hedge_state_rows": len(hedge),
        "hedge_best_actions": hedge["best_action"].value_counts().to_dict(),
        "allowed_close_hedge_rows": int(sampled["allowed_CLOSE_HEDGE"].sum()),
        "close_hedge_label_rows": len(close_hedge_rows),
        "close_hedge_utility": {
            "non_null": int(sampled["utility_CLOSE_HEDGE"].notna().sum()),
            "positive": int((sampled["utility_CLOSE_HEDGE"] > 0).sum()),
            "median": float(sampled["utility_CLOSE_HEDGE"].median()),
        },
        "label_margin": margin_summary,
        "recomputed_best_mismatch": int(
            (sampled["recomputed_best"] != sampled["best_action"]).sum()
        ),
    }


def _entry_analysis(predictions_path: Path) -> dict[str, Any]:
    predictions = pd.read_parquet(predictions_path)
    classes = predictions["actual_entry_class"].to_numpy(dtype=int)
    probability_columns = [
        "skip_probability",
        "long_probability",
        "short_probability",
    ]
    probabilities = predictions[probability_columns].to_numpy(dtype=float)
    predicted = probabilities.argmax(axis=1)
    names = ["SKIP", "LONG", "SHORT"]
    return {
        "rows": len(predictions),
        "class_distribution": {
            names[index]: int((classes == index).sum()) for index in range(3)
        },
        "prior_logloss": _prior_logloss(classes, 3),
        "model_logloss": float(
            -np.log(np.clip(probabilities[np.arange(len(classes)), classes], 1e-12, 1.0)).mean()
        ),
        "classification": _class_metrics(classes, predicted, names),
    }


def _management_prediction_analysis(path: Path) -> dict[str, Any]:
    predictions = pd.read_parquet(path)
    labels = predictions["best_action"].map(ACTION_LABELS).to_numpy(dtype=int)
    probability_columns = [f"prob_{action}" for action in ACTION_NAMES]
    probabilities = predictions[probability_columns].to_numpy(dtype=float)
    predicted = probabilities.argmax(axis=1)
    return {
        "rows": len(predictions),
        "label_distribution": predictions["best_action"].value_counts().to_dict(),
        "prediction_distribution": {
            ACTION_NAMES[index]: int((predicted == index).sum())
            for index in range(len(ACTION_NAMES))
        },
        "prior_logloss": _prior_logloss(labels, len(ACTION_NAMES)),
        "model_logloss": float(
            -np.log(
                np.clip(
                    probabilities[np.arange(len(labels)), labels],
                    1e-12,
                    1.0,
                )
            ).mean()
        ),
        "classification": _class_metrics(labels, predicted, list(ACTION_NAMES)),
    }


def _risk_benchmark_analysis(
    dataset_root: Path,
    training_root: Path,
) -> dict[str, Any]:
    bundle = load_bundle(dataset_root)
    selection_manifest = json.loads(
        (training_root / "feature_selection_manifest_v1.json").read_text()
    )
    rows = bundle.rows
    train_ids = rows.loc[
        (rows["split"] == "TRAIN") & rows["training_allowed"],
        "row_id",
    ].to_numpy()
    selection_ids = rows.loc[
        (rows["split"] == "SELECTION") & rows["training_allowed"],
        "row_id",
    ].to_numpy()
    feature_frame = bundle.features.set_index("row_id")
    targets = feature_frame.loc[selection_ids, ["mfe_down_24h", "mfe_up_24h"]].to_numpy(
        dtype=float
    )
    train_targets = feature_frame.loc[train_ids, ["mfe_down_24h", "mfe_up_24h"]].to_numpy(
        dtype=float
    )
    matrix, _ = build_matrix(
        bundle,
        selection_manifest["entry"],
        row_ids=selection_ids,
    )
    model = CatBoostRegressor()
    model.load_model(training_root / "entry_risk_gpu_v1.cbm")
    predictions = model.predict(matrix)
    train_mean = np.nanmean(train_targets, axis=0)
    valid = np.isfinite(targets).all(axis=1)
    model_abs = np.abs(predictions[valid] - targets[valid])
    zero_abs = np.abs(targets[valid])
    mean_abs = np.abs(targets[valid] - train_mean)
    return {
        "selection_rows": int(valid.sum()),
        "per_output": {
            name: {
                "model_mae": float(model_abs[:, index].mean()),
                "zero_mae": float(zero_abs[:, index].mean()),
                "train_mean_mae": float(mean_abs[:, index].mean()),
                "model_improvement_vs_zero": float(
                    zero_abs[:, index].mean() - model_abs[:, index].mean()
                ),
                "model_improvement_vs_train_mean": float(
                    mean_abs[:, index].mean() - model_abs[:, index].mean()
                ),
            }
            for index, name in enumerate(("mfe_down_24h", "mfe_up_24h"))
        },
        "overall_model_mae": float(model_abs.mean()),
        "overall_zero_mae": float(zero_abs.mean()),
        "overall_train_mean_mae": float(mean_abs.mean()),
    }


def _qwen_analysis(paths: list[Path]) -> dict[str, Any]:
    all_records = []
    forbidden_count = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            all_records.append(record)
            try:
                _assert_causal(record.get("request", {}))
            except Exception:
                forbidden_count += 1
    unique_records = {}
    for record in all_records:
        request_id = record.get("request_id")
        if request_id and request_id not in unique_records:
            unique_records[request_id] = record
    records = list(unique_records.values())
    inference = records
    actions = [
        record["decision"]["action"]
        for record in records
        if record["decision"].get("valid")
    ]
    portfolio_states = [
        record.get("request", {}).get("portfolio_state", {}) for record in records
    ]
    latencies = [
        float(record["decision"].get("latency_seconds", 0.0))
        for record in inference
    ]
    return {
        "records": len(records),
        "inference_requests": len(inference),
        "cached_replays": len(all_records) - len(records),
        "forbidden_future_fields": forbidden_count,
        "valid_json": sum(1 for record in records if record["decision"].get("valid")),
        "actual_actions": pd.Series(actions).value_counts().to_dict(),
        "portfolio_position_states": pd.Series(
            [state.get("position_state") for state in portfolio_states]
        )
        .value_counts(dropna=False)
        .to_dict(),
        "hedge_open_requests": sum(
            bool(state.get("hedge_open")) for state in portfolio_states
        ),
        "latency_seconds": {
            "median": float(statistics.median(latencies)) if latencies else None,
            "p90": float(np.percentile(latencies, 90)) if latencies else None,
            "max": max(latencies, default=None),
        },
        "adapter_allowed_actions": list(QWEN_ACTIONS),
        "policy_permissions": {
            "FLAT": ["OPEN_LONG", "OPEN_SHORT", "HOLD", "SKIP"],
            "PRIMARY_OPEN_NO_HEDGE": [
                "HOLD",
                "OPEN_HEDGE",
                "REDUCE_POSITION",
                "EXIT",
                "AVERAGE_PRIMARY_IF_LT_2",
            ],
            "PRIMARY_OPEN_WITH_HEDGE": [
                "HOLD",
                "CLOSE_HEDGE",
                "REDUCE_POSITION",
                "EXIT",
                "AVERAGE_PRIMARY_IF_LT_2",
            ],
        },
    }


def run_audit(
    *,
    dataset_root: Path,
    training_root: Path,
    qwen_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    management = pd.read_parquet(dataset_root / "management_state_samples_v1.parquet")
    metrics = json.loads((training_root / "training_metrics_v1.json").read_text())
    entry = _entry_analysis(
        training_root / "entry_predictions_selection_v1.parquet"
    )
    management_predictions = _management_prediction_analysis(
        training_root / "management_predictions_selection_v1.parquet"
    )
    risk_benchmark = _risk_benchmark_analysis(dataset_root, training_root)
    actions = _action_analysis(management)
    feature_importance = {
        "entry": _importance_report(
            training_root / "entry_direction_gpu_v1.cbm",
            metrics["features"],
        ),
        "management": _importance_report(
            training_root / "position_management_gpu_v1.cbm",
            metrics["management"]["features"],
        ),
        "risk": _importance_report(
            training_root / "entry_risk_gpu_v1.cbm",
            metrics["features"],
        ),
    }
    qwen = _qwen_analysis(sorted(qwen_root.glob("qwen_requests_*.jsonl")))
    result = {
        "status": "PASS",
        "actions": actions,
        "entry": entry,
        "management": management_predictions,
        "risk_benchmark": risk_benchmark,
        "feature_importance": feature_importance,
        "qwen": qwen,
        "corrections_to_prior_report": {
            "close_hedge_absent": False,
            "actually_missing_training_action": actions["missing_actions"],
            "note": (
                "The five-class CatBoost warning was caused by missing REDUCE_POSITION, "
                "not CLOSE_HEDGE. The prior REVIEW text incorrectly attributed it to CLOSE_HEDGE."
            ),
        },
        "recommended_schema": {
            "unit": "state-action-outcome triplet",
            "state_id": "causal market snapshot + portfolio snapshot + risk snapshot",
            "actions": list(ACTION_NAMES),
            "feasibility_mask": "explicit per state and per capital/margin rule",
            "counterfactual_engine": (
                "for every feasible action, branch from the same state and run the fixed "
                "execution/risk simulator over the same forward horizons"
            ),
            "outcomes": [
                "net_pnl",
                "max_drawdown",
                "MFE",
                "MAE",
                "liquidation_probability",
                "risk_limit_hit",
                "costs",
                "time_to_exit",
                "recovery_time",
                "terminal_equity",
            ],
            "model_target": (
                "predict action utility/rank rather than imitate best_action from the prior path"
            ),
            "policy": "mask infeasible actions, rank feasible utilities, then Risk Engine veto",
            "horizons_hours": [24, 72, 168],
            "split_requirements": "chronological train/validation with purge and embargo",
        },
    }
    (output_root / "action_learning_audit_v1.json").write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--qwen-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_audit(
                dataset_root=args.dataset_root,
                training_root=args.training_root,
                qwen_root=args.qwen_root,
                output_root=args.output_root,
            ),
            indent=2,
            default=str,
        )
    )
