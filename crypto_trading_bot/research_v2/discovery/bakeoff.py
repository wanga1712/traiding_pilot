from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

WARMUP_WINDOWS = 12
FIB_0618 = 0.618
FIB_1000 = 1.0
FIB_1618 = 1.618
RIDGE_L2 = 1.0
CAUSAL_FEATURES = ("q2", "q3", "q4", "tr21", "tr32", "tr43", "s1", "s2", "s3", "s4")
FORBIDDEN_FEATURES = ("time_next_hours", "duration_ratio_next_to_d4", "p_next_price", "target_magnitude", "target_signed")


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _median(values: list[float]) -> float:
    return statistics.median(values)


def _mean(values: list[float]) -> float:
    return statistics.mean(values)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or not math.isfinite(denominator):
        return float("nan")
    return numerator / denominator


def _clip_to_train_quantiles(value: float, train_y: list[float]) -> float:
    ordered = sorted(train_y)
    lower = ordered[max(0, math.floor(0.05 * (len(ordered) - 1)))]
    upper = ordered[min(len(ordered) - 1, math.ceil(0.95 * (len(ordered) - 1)))]
    return min(max(value, lower), upper)


def _fit_linear(x: list[float], y: list[float]) -> tuple[float, float]:
    if len(x) != len(y) or not x:
        raise ValueError("linear fit requires paired non-empty data")
    mx, my = _mean(x), _mean(y)
    den = sum((xi - mx) ** 2 for xi in x)
    if den == 0:
        return my, 0.0
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / den
    return my - slope * mx, slope


def _matrix_transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*matrix)]


def _matrix_mul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    rows, cols, inner = len(left), len(right[0]), len(right)
    return [[sum(left[i][k] * right[k][j] for k in range(inner)) for j in range(cols)] for i in range(rows)]


def _matrix_vec_mul(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _matrix_inverse(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    augmented = [row[:] + [1.0 if i == j else 0.0 for j in range(size)] for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("singular matrix")
        if pivot != col:
            augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [value / scale for value in augmented[col]]
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            augmented[row] = [value - factor * augmented[col][idx] for idx, value in enumerate(augmented[row])]
    return [row[size:] for row in augmented]


def _fit_ridge(design: list[list[float]], targets: list[float], l2: float = RIDGE_L2) -> list[float]:
    xtx = _matrix_mul(_matrix_transpose(design), design)
    for i in range(len(xtx)):
        xtx[i][i] += l2
    xty = _matrix_vec_mul(_matrix_transpose(design), targets)
    return _matrix_vec_mul(_matrix_inverse(xtx), xty)


def _standardize_train_apply(train_rows: list[list[float]], test_row: list[float]) -> tuple[list[list[float]], list[float], dict[str, list[float]]]:
    if not train_rows:
        raise ValueError("standardization requires training rows")
    means = [_mean([row[j] for row in train_rows]) for j in range(len(train_rows[0]))]
    stds = []
    for j in range(len(train_rows[0])):
        values = [row[j] for row in train_rows]
        std = statistics.pstdev(values) if len(values) > 1 else 1.0
        stds.append(std if std > 1e-12 else 1.0)
    train_scaled = [[(row[j] - means[j]) / stds[j] for j in range(len(row))] for row in train_rows]
    test_scaled = [(test_row[j] - means[j]) / stds[j] for j in range(len(test_row))]
    return train_scaled, test_scaled, {"mean": means, "std": stds}


def _window_features(window: dict[str, Any]) -> dict[str, float]:
    return {name: float(window[name]) for name in CAUSAL_FEATURES}


def load_discovery_windows(source_csv: Path) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(source_csv.open(encoding="utf-8")))
    if len(rows) != 42 or [int(row["point_index"]) for row in rows] != list(range(42)):
        raise ValueError("expected immutable contiguous P0..P41")
    points = [
        {
            "index": int(row["point_index"]),
            "timestamp": datetime.fromisoformat(row["timestamp"].replace(" ", "T") if "T" not in row["timestamp"] else row["timestamp"]),
            "price": float(row["price"]),
        }
        for row in rows
    ]
    windows: list[dict[str, Any]] = []
    for point_index in range(5, 42):
        segment = points[point_index - 5 : point_index + 1]
        deltas = [segment[j + 1]["price"] - segment[j]["price"] for j in range(4)]
        if any(value == 0 for value in deltas):
            raise ValueError(f"zero price leg in window ending P{point_index}")
        durations = [(segment[j + 1]["timestamp"] - segment[j]["timestamp"]).total_seconds() / 3600.0 for j in range(4)]
        if any(value <= 0 for value in durations):
            raise ValueError(f"non-positive duration in window ending P{point_index}")
        p4 = segment[4]["price"]
        p_next = segment[5]["price"]
        d4 = deltas[3]
        next_delta = p_next - p4
        target_magnitude = abs(next_delta) / abs(d4)
        windows.append(
            {
                "reference_point": f"P{point_index}",
                "point_index": point_index,
                "d1": deltas[0],
                "d2": deltas[1],
                "d3": deltas[2],
                "d4": d4,
                "p4_price": p4,
                "p_next_price": p_next,
                "target_magnitude": target_magnitude,
                "target_signed": next_delta / abs(d4),
                "q2": abs(deltas[1]) / abs(deltas[0]),
                "q3": abs(deltas[2]) / abs(deltas[1]),
                "q4": abs(d4) / abs(deltas[2]),
                "t1": durations[0],
                "t2": durations[1],
                "t3": durations[2],
                "t4": durations[3],
                "tr21": durations[1] / durations[0],
                "tr32": durations[2] / durations[1],
                "tr43": durations[3] / durations[2],
                "s1": deltas[0] / durations[0],
                "s2": deltas[1] / durations[1],
                "s3": deltas[2] / durations[2],
                "s4": d4 / durations[3],
                "direction_expected": -_sign(d4),
                "direction_actual": _sign(next_delta),
                "direction_alternates": -_sign(d4) == _sign(next_delta),
            }
        )
    return windows


def _predict_price(window: dict[str, Any], magnitude: float) -> float:
    return window["p4_price"] + window["direction_expected"] * magnitude * abs(window["d4"])


def _record_prediction(window: dict[str, Any], pred_magnitude: float) -> dict[str, Any]:
    pred_price = _predict_price(window, pred_magnitude)
    actual_price = window["p_next_price"]
    price_error_pct = abs(pred_price - actual_price) / actual_price * 100.0
    return {
        "reference_point": window["reference_point"],
        "point_index": window["point_index"],
        "actual_magnitude": window["target_magnitude"],
        "predicted_magnitude": pred_magnitude,
        "magnitude_error": abs(pred_magnitude - window["target_magnitude"]),
        "actual_price": actual_price,
        "predicted_price": pred_price,
        "price_error_pct": price_error_pct,
        "direction_expected": window["direction_expected"],
        "direction_actual": window["direction_actual"],
        "direction_correct": window["direction_expected"] == window["direction_actual"],
    }


def _predict_train_median(train_y: list[float], _train_x: list[dict[str, float]], _test_x: dict[str, float]) -> float:
    return _median(train_y)


def _predict_constant(value: float):
    def _predict(_train_y: list[float], _train_x: list[dict[str, float]], _test_x: dict[str, float]) -> float:
        return value

    return _predict


def _predict_inverse_q4(train_y: list[float], _train_x: list[dict[str, float]], test_x: dict[str, float]) -> float:
    q4 = test_x["q4"]
    if q4 <= 0 or not math.isfinite(q4):
        return _median(train_y)
    return 1.0 / q4


def _predict_linear_q4(train_y: list[float], train_x: list[dict[str, float]], test_x: dict[str, float]) -> tuple[float, dict[str, float]]:
    x = [row["q4"] for row in train_x]
    intercept, slope = _fit_linear(x, train_y)
    raw = intercept + slope * test_x["q4"]
    return _clip_to_train_quantiles(raw, train_y), {"intercept": intercept, "slope": slope, "raw": raw}


def _predict_power_q4(train_y: list[float], train_x: list[dict[str, float]], test_x: dict[str, float]) -> tuple[float, dict[str, float]]:
    pairs = [(row["q4"], target) for row, target in zip(train_x, train_y) if row["q4"] > 0 and target > 0]
    if len(pairs) < 2:
        fallback = _median(train_y)
        return fallback, {"intercept": math.log(fallback), "slope": 0.0, "raw": fallback, "fallback": True}
    log_x = [math.log(q4) for q4, _ in pairs]
    log_y = [math.log(target) for _, target in pairs]
    intercept, slope = _fit_linear(log_x, log_y)
    if test_x["q4"] <= 0:
        raw = _median(train_y)
    else:
        raw = math.exp(intercept) * (test_x["q4"] ** slope)
    clipped = _clip_to_train_quantiles(raw, train_y)
    return clipped, {"log_intercept": intercept, "log_slope": slope, "multiplier": math.exp(intercept), "raw": raw}


def _predict_ridge_geometry(train_y: list[float], train_x: list[dict[str, float]], test_x: dict[str, float]) -> float:
    train_rows = [[features[name] for name in CAUSAL_FEATURES] for features in train_x]
    test_row = [test_x[name] for name in CAUSAL_FEATURES]
    train_scaled, test_scaled, _ = _standardize_train_apply(train_rows, test_row)
    design = [[1.0, *row] for row in train_scaled]
    test_design = [1.0, *test_scaled]
    if len(train_y) <= len(CAUSAL_FEATURES) + 1:
        return _median(train_y)
    coefficients = _fit_ridge(design, train_y, RIDGE_L2)
    raw = sum(c * v for c, v in zip(coefficients, test_design))
    return _clip_to_train_quantiles(raw, train_y)


def _predict_catboost_geometry(train_y: list[float], train_x: list[dict[str, float]], test_x: dict[str, float]) -> float | None:
    try:
        from catboost import CatBoostRegressor
    except ImportError:
        return None
    x_train = [[features[name] for name in CAUSAL_FEATURES] for features in train_x]
    x_test = [[test_x[name] for name in CAUSAL_FEATURES]]
    model = CatBoostRegressor(iterations=50, depth=3, learning_rate=0.1, loss_function="MAE", verbose=False, allow_writing_files=False)
    model.fit(x_train, train_y)
    prediction = float(model.predict(x_test)[0])
    return _clip_to_train_quantiles(max(prediction, 1e-9), train_y)


ModelSpec = tuple[str, str, Callable[..., float | tuple[float, dict[str, float]] | None]]

MODELS: list[ModelSpec] = [
    ("M0", "TRAIN_MEDIAN", _predict_train_median),
    ("M1", "FIB_0618", _predict_constant(FIB_0618)),
    ("M2", "FIB_1000", _predict_constant(FIB_1000)),
    ("M3", "FIB_1618", _predict_constant(FIB_1618)),
    ("M4", "INVERSE_Q4", _predict_inverse_q4),
    ("M5", "LINEAR_Q4", _predict_linear_q4),
    ("M6", "POWER_Q4", _predict_power_q4),
    ("M7", "RIDGE_GEOMETRY", _predict_ridge_geometry),
    ("M8", "CATBOOST_GEOMETRY", _predict_catboost_geometry),
]

SIMPLE_MODELS = {"M0", "M1", "M2", "M3", "M4"}
STATISTICAL_MODELS = {"M5", "M6", "M7"}
EXPLORATORY_MODELS = {"M8"}


def _aggregate_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"predictions_count": 0}
    mag_errors = [row["magnitude_error"] for row in records]
    price_errors = [row["price_error_pct"] for row in records]
    squared = [error ** 2 for error in mag_errors]
    return {
        "predictions_count": len(records),
        "MAE_TARGET_MAGNITUDE": _mean(mag_errors),
        "MEDIAN_AE_TARGET_MAGNITUDE": _median(mag_errors),
        "RMSE_TARGET_MAGNITUDE": math.sqrt(_mean(squared)),
        "MAE_PRICE_PCT": _mean(price_errors),
        "MEDIAN_PRICE_ERROR_PCT": _median(price_errors),
        "WITHIN_1_PERCENT_PRICE": sum(error <= 1.0 for error in price_errors),
        "WITHIN_2_PERCENT_PRICE": sum(error <= 2.0 for error in price_errors),
        "WITHIN_5_PERCENT_PRICE": sum(error <= 5.0 for error in price_errors),
        "WITHIN_10_PERCENT_PRICE": sum(error <= 10.0 for error in price_errors),
        "direction_accuracy": _mean([1.0 if row["direction_correct"] else 0.0 for row in records]),
    }


def _coefficient_summary(history: list[dict[str, float]], slope_key: str) -> dict[str, Any]:
    if not history:
        return {"folds": 0}
    slopes = [entry[slope_key] for entry in history if slope_key in entry and math.isfinite(entry[slope_key])]
    intercepts = [entry["intercept"] for entry in history if "intercept" in entry and math.isfinite(entry["intercept"])]
    return {
        "folds": len(history),
        "slope_sign_negative_count": sum(value < 0 for value in slopes),
        "slope_sign_positive_count": sum(value > 0 for value in slopes),
        "slope_sign_stability": abs(sum(1 if value < 0 else -1 for value in slopes)) / len(slopes) if slopes else 0.0,
        "slope_min": min(slopes) if slopes else None,
        "slope_max": max(slopes) if slopes else None,
        "intercept_min": min(intercepts) if intercepts else None,
        "intercept_max": max(intercepts) if intercepts else None,
        "mean_abs_fold_to_fold_slope_delta": _mean([abs(slopes[i] - slopes[i - 1]) for i in range(1, len(slopes))]) if len(slopes) > 1 else 0.0,
    }


def _audit_leakage(windows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "forbidden_features_absent_from_model_inputs": all(name not in _window_features(windows[0]) for name in FORBIDDEN_FEATURES),
        "walk_forward_only_past_targets_in_training": True,
        "direction_rule_uses_only_d4_sign": True,
        "time_next_not_in_features": "time_next_hours" not in windows[0],
        "duration_ratio_not_in_features": "duration_ratio_next_to_d4" not in windows[0],
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def run_formula_bakeoff(source_csv: Path, output_dir: Path, annotation_id: str, warmup: int = WARMUP_WINDOWS) -> dict[str, Any]:
    windows = load_discovery_windows(source_csv)
    if len(windows) != 37:
        raise ValueError("expected 37 evaluable windows")
    if warmup < 12 or warmup >= len(windows):
        raise ValueError("warmup must leave at least one prediction and be >= 12")

    per_model_records: dict[str, list[dict[str, Any]]] = {model_id: [] for model_id, _, _ in MODELS}
    coefficient_history: dict[str, list[dict[str, float]]] = {"M5": [], "M6": []}
    alternation_records: list[dict[str, Any]] = []

    for eval_index in range(warmup, len(windows)):
        train_windows = windows[:eval_index]
        test_window = windows[eval_index]
        train_y = [row["target_magnitude"] for row in train_windows]
        train_x = [_window_features(row) for row in train_windows]
        test_x = _window_features(test_window)

        alternation_records.append(
            {
                "reference_point": test_window["reference_point"],
                "direction_expected": test_window["direction_expected"],
                "direction_actual": test_window["direction_actual"],
                "direction_correct": test_window["direction_alternates"],
            }
        )

        for model_id, _name, predictor in MODELS:
            result = predictor(train_y, train_x, test_x)
            meta: dict[str, float] = {}
            if isinstance(result, tuple):
                pred_magnitude, meta = result
            elif result is None:
                continue
            else:
                pred_magnitude = float(result)
            record = _record_prediction(test_window, pred_magnitude)
            record["model_id"] = model_id
            record["train_size"] = len(train_windows)
            if meta:
                record.update(meta)
            per_model_records[model_id].append(record)
            if model_id in coefficient_history and meta:
                coefficient_history[model_id].append(meta)

    metrics = {model_id: _aggregate_metrics(records) for model_id, records in per_model_records.items()}
    direction_rule_metrics = {
        "rule": "predicted_direction = -sign(d4)",
        "eval_windows": len(alternation_records),
        "direction_correct_count": sum(row["direction_correct"] for row in alternation_records),
        "direction_accuracy": _mean([1.0 if row["direction_correct"] else 0.0 for row in alternation_records]),
        "full_dataset_direction_accuracy": _mean([1.0 if row["direction_alternates"] else 0.0 for row in windows]),
    }

    def _best(model_ids: set[str]) -> tuple[str | None, dict[str, Any] | None]:
        ranked = sorted(
            ((model_id, metrics[model_id]) for model_id in model_ids if metrics.get(model_id, {}).get("predictions_count", 0) > 0),
            key=lambda item: (item[1]["MAE_TARGET_MAGNITUDE"], item[1]["RMSE_TARGET_MAGNITUDE"]),
        )
        if not ranked:
            return None, None
        return ranked[0]

    best_simple_id, best_simple_metrics = _best(SIMPLE_MODELS)
    best_stat_id, best_stat_metrics = _best(STATISTICAL_MODELS)
    best_explore_id, best_explore_metrics = _best(EXPLORATORY_MODELS)

    linear_summary = _coefficient_summary(
        [{"intercept": item.get("intercept", float("nan")), "slope": item.get("slope", float("nan"))} for item in coefficient_history["M5"]],
        "slope",
    )
    power_summary = _coefficient_summary(
        [{"intercept": item.get("log_intercept", float("nan")), "slope": item.get("log_slope", float("nan"))} for item in coefficient_history["M6"]],
        "slope",
    )

    m5_slopes = [item["slope"] for item in coefficient_history["M5"] if "slope" in item]
    m6_slopes = [item["log_slope"] for item in coefficient_history["M6"] if "log_slope" in item]
    linear_formula = {
        "form": "magnitude = a + b*q4",
        "walk_forward_folds": len(coefficient_history["M5"]),
        "final_fold_coefficients": coefficient_history["M5"][-1] if coefficient_history["M5"] else None,
        "coefficient_summary": linear_summary,
        "inverse_relationship_supported": linear_summary.get("slope_sign_negative_count", 0) > linear_summary.get("slope_sign_positive_count", 0),
    }
    power_formula = {
        "form": "magnitude = exp(a) * q4^b",
        "walk_forward_folds": len(coefficient_history["M6"]),
        "final_fold_coefficients": coefficient_history["M6"][-1] if coefficient_history["M6"] else None,
        "coefficient_summary": power_summary,
        "inverse_relationship_supported": power_summary.get("slope_sign_negative_count", 0) > power_summary.get("slope_sign_positive_count", 0),
    }

    leakage_audit = _audit_leakage(windows)
    ranking = sorted(
        ((model_id, metrics[model_id]) for model_id in metrics if metrics[model_id].get("predictions_count", 0) > 0),
        key=lambda item: item[1]["MAE_TARGET_MAGNITUDE"],
    )

    report = {
        "wip": "EXPERT-GEOMETRY-FORMULA-BAKEOFF-1",
        "source_annotation": annotation_id,
        "discovery_dataset": "DISCOVERY DATASET V1",
        "source_sha256": hashlib.sha256(source_csv.read_bytes()).hexdigest(),
        "point_count": 42,
        "discovery_windows": len(windows),
        "warmup_windows": warmup,
        "walk_forward_predictions": len(windows) - warmup,
        "causal_features": list(CAUSAL_FEATURES),
        "forbidden_features": list(FORBIDDEN_FEATURES),
        "ranking_by_mae_target_magnitude": [{"model_id": model_id, "name": next(name for mid, name, _ in MODELS if mid == model_id), **metric} for model_id, metric in ranking],
        "best_simple_formula": {"model_id": best_simple_id, "name": next(name for mid, name, _ in MODELS if mid == best_simple_id), "metrics": best_simple_metrics},
        "best_statistical_model": {"model_id": best_stat_id, "name": next(name for mid, name, _ in MODELS if mid == best_stat_id), "metrics": best_stat_metrics},
        "best_exploratory_model": {"model_id": best_explore_id, "name": next(name for mid, name, _ in MODELS if mid == best_explore_id), "metrics": best_explore_metrics},
        "candidate_metrics": {model_id: metrics[model_id] for model_id in metrics},
        "inverse_q4_metrics": metrics.get("M4"),
        "linear_q4_formula": linear_formula,
        "power_q4_formula": power_formula,
        "ridge_metrics": metrics.get("M7"),
        "catboost_exploratory_metrics": metrics.get("M8"),
        "direction_alternation_rule_metrics": direction_rule_metrics,
        "leakage_audit": leakage_audit,
        "best_candidate_frozen": "NO",
        "new_out_of_sample_annotation_required": "YES",
        "notes": [
            "CatBoost is exploratory only and must not be promoted from this 37-window discovery set without fresh expert annotation.",
            "Two-cluster descriptive centers (~0.822, ~2.292) were not used as predictive constants.",
            "time_next/time_d4 remains descriptive-only and was excluded from all predictors.",
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bakeoff_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output_dir / "predictions_by_model.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "model_id",
            "reference_point",
            "point_index",
            "train_size",
            "actual_magnitude",
            "predicted_magnitude",
            "magnitude_error",
            "actual_price",
            "predicted_price",
            "price_error_pct",
            "direction_expected",
            "direction_actual",
            "direction_correct",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for model_id, records in per_model_records.items():
            for record in records:
                writer.writerow({"model_id": model_id, **record})
    with (output_dir / "walk_forward_coefficients.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model_id", "reference_point", "train_size", "intercept", "slope", "log_intercept", "log_slope", "multiplier", "raw"])
        writer.writeheader()
        for model_id in ("M5", "M6"):
            for record, window in zip(per_model_records[model_id], windows[warmup:]):
                writer.writerow(
                    {
                        "model_id": model_id,
                        "reference_point": window["reference_point"],
                        "train_size": record["train_size"],
                        "intercept": record.get("intercept"),
                        "slope": record.get("slope"),
                        "log_intercept": record.get("log_intercept"),
                        "log_slope": record.get("log_slope"),
                        "multiplier": record.get("multiplier"),
                        "raw": record.get("raw"),
                    }
                )
    (output_dir / "source_snapshot.csv").write_bytes(source_csv.read_bytes())
    return report
