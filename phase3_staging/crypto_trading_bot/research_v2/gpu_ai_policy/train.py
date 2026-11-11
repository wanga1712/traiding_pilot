from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from scipy import sparse

from .config import SELECTION_END, TRAIN_END


ACTION_NAMES = (
    "HOLD",
    "OPEN_HEDGE",
    "CLOSE_HEDGE",
    "AVERAGE_PRIMARY",
    "REDUCE_POSITION",
    "EXIT",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


class GpuSampler:
    def __init__(self) -> None:
        self.samples: list[tuple[int, int]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                ).strip().splitlines()[0]
                memory, utilization = [int(item.strip()) for item in raw.split(",")[:2]]
                self.samples.append((memory, utilization))
            except Exception:
                pass
            time.sleep(0.2)

    def __enter__(self) -> "GpuSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def summary(self) -> dict[str, int]:
        return {
            "samples": len(self.samples),
            "max_vram_mib": max((item[0] for item in self.samples), default=0),
            "max_utilization_percent": max((item[1] for item in self.samples), default=0),
        }


@dataclass
class DatasetBundle:
    output_root: Path
    rows: pd.DataFrame
    features: pd.DataFrame
    atomic: sparse.csr_matrix
    composite: sparse.csr_matrix
    atomic_names: list[str]
    composite_names: list[str]


def load_bundle(dataset_root: Path) -> DatasetBundle:
    rows = pd.read_parquet(dataset_root / "row_index_v1.parquet")
    features = pd.read_parquet(dataset_root / "market_features_v1.parquet")
    atomic = sparse.load_npz(dataset_root / "atomic_features_hourly_v1.npz").tocsr()
    composite = sparse.load_npz(dataset_root / "composite_features_hourly_v1.npz").tocsr()
    registry = json.loads((dataset_root / "feature_registry_v1.json").read_text())
    return DatasetBundle(
        output_root=dataset_root,
        rows=rows,
        features=features,
        atomic=atomic,
        composite=composite,
        atomic_names=list(registry["atomic_features"]),
        composite_names=list(registry["composite_features"]),
    )


def _safe_correlation(matrix: np.ndarray, target: np.ndarray) -> np.ndarray:
    y = np.asarray(target, dtype=np.float64)
    y_centered = y - np.nanmean(y)
    denominator_y = np.sqrt(np.nansum(y_centered**2))
    result = np.zeros(matrix.shape[1], dtype=np.float64)
    if denominator_y <= 0:
        return result
    for column in range(matrix.shape[1]):
        values = matrix[:, column].astype(np.float64)
        mask = np.isfinite(values)
        if mask.sum() < max(50, int(len(values) * 0.02)):
            continue
        xc = values[mask] - np.mean(values[mask])
        denominator_x = np.sqrt(np.sum(xc**2))
        if denominator_x > 0:
            result[column] = abs(float(np.dot(xc, y_centered[mask]) / (denominator_x * denominator_y)))
    return result


def _safe_sparse_correlation(matrix: sparse.csr_matrix, target: np.ndarray) -> np.ndarray:
    y = np.asarray(target, dtype=np.float64)
    y_centered = y - np.mean(y)
    n = matrix.shape[0]
    sums = np.asarray(matrix.sum(axis=0)).ravel()
    squares = np.asarray(matrix.power(2).sum(axis=0)).ravel()
    means = sums / max(n, 1)
    variances = np.maximum(0.0, squares - n * means**2)
    numerator = np.asarray(matrix.T @ y_centered).ravel()
    denominator = np.sqrt(variances * np.sum(y_centered**2))
    out = np.zeros(matrix.shape[1], dtype=np.float64)
    valid = denominator > 0
    out[valid] = np.abs(numerator[valid] / denominator[valid])
    return out


def select_features(
    bundle: DatasetBundle,
    *,
    train_mask: pd.Series,
    target: np.ndarray,
    dense_limit: int = 80,
    atomic_limit: int = 32,
    composite_limit: int = 16,
) -> dict[str, Any]:
    dense_candidates = [
        column
        for column in bundle.features.columns
        if column not in {"row_id", "decision_at", "open_time"}
        and pd.api.types.is_numeric_dtype(bundle.features[column])
        and not column.startswith(
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
    dense_matrix = bundle.features.loc[train_mask, dense_candidates].to_numpy(dtype=np.float64)
    dense_corr = _safe_correlation(dense_matrix, target[train_mask.to_numpy()])
    dense_order = np.argsort(np.nan_to_num(dense_corr, nan=-1.0))[::-1]
    selected_dense = [dense_candidates[index] for index in dense_order[:dense_limit]]
    selected_dense.extend(
        [
            column
            for column in dense_candidates
            if column.startswith("state_")
        ]
    )
    selected_dense = list(dict.fromkeys(selected_dense))

    atomic_corr = _safe_sparse_correlation(bundle.atomic[train_mask.to_numpy()], target[train_mask.to_numpy()])
    composite_corr = _safe_sparse_correlation(bundle.composite[train_mask.to_numpy()], target[train_mask.to_numpy()])
    selected_atomic = np.argsort(atomic_corr)[::-1][:atomic_limit].tolist()
    selected_composite = np.argsort(composite_corr)[::-1][:composite_limit].tolist()
    return {
        "dense": selected_dense,
        "atomic": selected_atomic,
        "composite": selected_composite,
        "dense_correlation": {
            name: float(dense_corr[index]) for index, name in enumerate(dense_candidates)
        },
        "atomic_correlation": {
            bundle.atomic_names[index]: float(atomic_corr[index]) for index in selected_atomic
        },
        "composite_correlation": {
            bundle.composite_names[index]: float(composite_corr[index]) for index in selected_composite
        },
    }


def build_matrix(
    bundle: DatasetBundle,
    selection: dict[str, Any],
    *,
    row_ids: np.ndarray,
    extra: pd.DataFrame | None = None,
    extra_columns: list[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    dense = bundle.features.set_index("row_id").loc[row_ids, selection["dense"]].reset_index(drop=True)
    columns = list(selection["dense"])
    parts = [dense.to_numpy(dtype=np.float32)]
    if selection["atomic"]:
        atomic = bundle.atomic[row_ids][:, selection["atomic"]].toarray().astype(np.float32)
        parts.append(atomic)
        columns.extend(bundle.atomic_names[index] for index in selection["atomic"])
    if selection["composite"]:
        composite = bundle.composite[row_ids][:, selection["composite"]].toarray().astype(np.float32)
        parts.append(composite)
        columns.extend(bundle.composite_names[index] for index in selection["composite"])
    if extra is not None and extra_columns:
        parts.append(extra[extra_columns].to_numpy(dtype=np.float32))
        columns.extend(extra_columns)
    return np.concatenate(parts, axis=1), columns


def _entry_label(features: pd.DataFrame) -> np.ndarray:
    long_net = features["long_net_return_24h"].to_numpy(dtype=float)
    short_net = features["short_net_return_24h"].to_numpy(dtype=float)
    labels = np.zeros(len(features), dtype=np.int32)
    labels[(long_net > 0) & (long_net >= short_net)] = 1
    labels[(short_net > 0) & (short_net > long_net)] = 2
    return labels


def _classification_metrics(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_true, dtype=np.int32)
    epsilon = 1e-12
    selected = probabilities[np.arange(len(y)), y]
    return {
        "accuracy": float((probabilities.argmax(axis=1) == y).mean()),
        "logloss": float(-np.log(np.clip(selected, epsilon, 1.0)).mean()),
        "mean_confidence": float(probabilities.max(axis=1).mean()),
    }


def _reliability(y_true: np.ndarray, probabilities: np.ndarray) -> list[dict[str, float]]:
    confidence = probabilities.max(axis=1)
    predicted = probabilities.argmax(axis=1)
    correct = (predicted == y_true).astype(float)
    bins = np.linspace(0.0, 1.0, 11)
    rows: list[dict[str, float]] = []
    for left, right in zip(bins[:-1], bins[1:]):
        mask = (confidence >= left) & (confidence < right if right < 1.0 else confidence <= right)
        if not mask.any():
            continue
        rows.append(
            {
                "bin_left": float(left),
                "bin_right": float(right),
                "count": int(mask.sum()),
                "mean_confidence": float(confidence[mask].mean()),
                "accuracy": float(correct[mask].mean()),
            }
        )
    return rows


def train_models(dataset_root: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    bundle = load_bundle(dataset_root)
    rows = bundle.rows.merge(
        bundle.features[["row_id", "decision_at"]],
        on="row_id",
        how="left",
        suffixes=("", "_feature"),
    )
    entry_target = _entry_label(bundle.features)
    train_mask = (
        (bundle.rows["split"] == "TRAIN")
        & bundle.rows["training_allowed"]
    )
    selection_mask = (
        (bundle.rows["split"] == "SELECTION")
        & bundle.rows["training_allowed"]
    )
    selection = select_features(
        bundle,
        train_mask=train_mask,
        target=entry_target,
    )
    train_row_ids = bundle.rows.loc[train_mask, "row_id"].to_numpy()
    selection_row_ids = bundle.rows.loc[selection_mask, "row_id"].to_numpy()
    x_train, feature_names = build_matrix(bundle, selection, row_ids=train_row_ids)
    x_selection, _ = build_matrix(bundle, selection, row_ids=selection_row_ids)
    y_train = entry_target[train_row_ids]
    y_selection = entry_target[selection_row_ids]

    gpu_summary: dict[str, Any] = {}
    with GpuSampler() as sampler:
        entry = CatBoostClassifier(
            iterations=250,
            depth=6,
            learning_rate=0.05,
            loss_function="MultiClass",
            eval_metric="MultiClass",
            classes_count=3,
            random_seed=42,
            task_type="GPU",
            devices="0",
            border_count=64,
            verbose=25,
            allow_writing_files=False,
        )
        started = time.time()
        entry.fit(
            x_train,
            y_train,
            eval_set=(x_selection, y_selection),
            use_best_model=True,
        )
        entry_seconds = time.time() - started
        entry_path = output_root / "entry_direction_gpu_v1.cbm"
        entry.save_model(entry_path)
        entry_prob = entry.predict_proba(x_selection)
        gpu_summary = sampler.summary()

    risk_model = CatBoostRegressor(
        iterations=180,
        depth=6,
        learning_rate=0.05,
        loss_function="MultiRMSE",
        random_seed=42,
        task_type="GPU",
        devices="0",
        border_count=64,
        verbose=25,
        allow_writing_files=False,
    )
    risk_train = bundle.features.loc[train_row_ids, ["mfe_down_24h", "mfe_up_24h"]].to_numpy(dtype=np.float32)
    risk_selection = bundle.features.loc[selection_row_ids, ["mfe_down_24h", "mfe_up_24h"]].to_numpy(dtype=np.float32)
    risk_train_valid = np.isfinite(risk_train).all(axis=1)
    risk_selection_valid = np.isfinite(risk_selection).all(axis=1)
    with GpuSampler() as risk_sampler:
        risk_model.fit(
            x_train[risk_train_valid],
            risk_train[risk_train_valid],
            eval_set=(
                x_selection[risk_selection_valid],
                risk_selection[risk_selection_valid],
            ),
            use_best_model=True,
        )
        risk_gpu = risk_sampler.summary()
    risk_path = output_root / "entry_risk_gpu_v1.cbm"
    risk_model.save_model(risk_path)
    risk_prediction = risk_model.predict(x_selection)
    risk_mae = float(np.nanmean(np.abs(risk_prediction - risk_selection)))

    management = pd.read_parquet(dataset_root / "management_state_samples_v1.parquet")
    management["decision_at"] = pd.to_datetime(management["decision_at"], utc=True)
    management = management[management["decision_at"].dt.hour % 4 == 0].reset_index(drop=True)
    management = management[management["best_action"].notna()].reset_index(drop=True)
    management["best_action_id"] = management["best_action"].map(
        {name: index for index, name in enumerate(ACTION_NAMES)}
    )
    management_train = management[management["decision_at"] < pd.Timestamp(TRAIN_END)].copy()
    management_selection = management[
        (management["decision_at"] >= pd.Timestamp(TRAIN_END))
        & (management["decision_at"] < pd.Timestamp(SELECTION_END))
    ].copy()
    state_columns = [
        column
        for column in management.columns
        if column
        not in {
            "row_id",
            "decision_at",
            "portfolio_variant",
            "best_action",
            "best_action_id",
        }
        and not column.startswith(("utility_", "allowed_"))
        and pd.api.types.is_numeric_dtype(management[column])
    ]
    management_target_all = np.zeros(len(bundle.rows), dtype=np.int32)
    management_target_all[management_train["row_id"].to_numpy()] = management_train[
        "best_action_id"
    ].to_numpy(dtype=np.int32)
    management_train_mask = bundle.rows["row_id"].isin(management_train["row_id"])
    management_selection_features = select_features(
        bundle,
        train_mask=management_train_mask,
        target=management_target_all,
        dense_limit=100,
        atomic_limit=32,
        composite_limit=16,
    )
    x_mgmt_train, management_feature_names = build_matrix(
        bundle,
        management_selection_features,
        row_ids=management_train["row_id"].to_numpy(),
        extra=management_train.reset_index(drop=True),
        extra_columns=state_columns,
    )
    x_mgmt_selection, _ = build_matrix(
        bundle,
        management_selection_features,
        row_ids=management_selection["row_id"].to_numpy(),
        extra=management_selection.reset_index(drop=True),
        extra_columns=state_columns,
    )
    management_model = CatBoostClassifier(
        iterations=250,
        depth=6,
        learning_rate=0.05,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        classes_count=len(ACTION_NAMES),
        random_seed=42,
        task_type="GPU",
        devices="0",
        border_count=64,
        verbose=25,
        allow_writing_files=False,
    )
    with GpuSampler() as management_sampler:
        management_model.fit(
            x_mgmt_train,
            management_train["best_action_id"].to_numpy(),
            eval_set=(
                x_mgmt_selection,
                management_selection["best_action_id"].to_numpy(),
            ),
            use_best_model=True,
        )
        management_gpu = management_sampler.summary()
    management_path = output_root / "position_management_gpu_v1.cbm"
    management_model.save_model(management_path)
    management_prob = management_model.predict_proba(x_mgmt_selection)

    predictions = bundle.features.loc[selection_row_ids, ["row_id", "decision_at"]].copy()
    predictions["long_probability"] = entry_prob[:, 1]
    predictions["skip_probability"] = entry_prob[:, 0]
    predictions["short_probability"] = entry_prob[:, 2]
    predictions["actual_entry_class"] = y_selection
    predictions["predicted_downside_24h"] = risk_prediction[:, 0]
    predictions["predicted_upside_24h"] = risk_prediction[:, 1]
    predictions.to_parquet(output_root / "entry_predictions_selection_v1.parquet", index=False)

    management_predictions = management_selection[["row_id", "decision_at", "portfolio_variant", "best_action"]].copy()
    for index, action in enumerate(ACTION_NAMES):
        management_predictions[f"prob_{action}"] = management_prob[:, index]
    management_predictions.to_parquet(
        output_root / "management_predictions_selection_v1.parquet",
        index=False,
    )
    metrics = {
        "status": "PASS",
        "dataset_sha256": _sha256(dataset_root / "dataset_manifest_v1.json"),
        "train_rows": int(train_mask.sum()),
        "selection_rows": int(selection_mask.sum()),
        "feature_count": len(feature_names),
        "features": feature_names,
        "entry": {
            "gpu": gpu_summary,
            "training_seconds": entry_seconds,
            "metrics": _classification_metrics(y_selection, entry_prob),
            "reliability": _reliability(y_selection, entry_prob),
            "model_sha256": _sha256(entry_path),
        },
        "risk": {
            "gpu": risk_gpu,
            "mae": risk_mae,
            "model_sha256": _sha256(risk_path),
        },
        "management": {
            "gpu": management_gpu,
            "train_rows": len(management_train),
            "selection_rows": len(management_selection),
            "feature_count": len(management_feature_names),
            "features": management_feature_names,
            "metrics": _classification_metrics(
                management_selection["best_action_id"].to_numpy(),
                management_prob,
            ),
            "model_sha256": _sha256(management_path),
        },
        "gpu_training_confirmed": gpu_summary.get("max_vram_mib", 0) > 0,
        "train_interval": ["2020-01-01", str(TRAIN_END)],
        "selection_interval": [str(TRAIN_END), str(SELECTION_END)],
    }
    _write_json(output_root / "training_metrics_v1.json", metrics)
    _write_json(
        output_root / "feature_selection_manifest_v1.json",
        {
            "entry": selection,
            "management": management_selection_features,
            "management_state_features": state_columns,
        },
    )
    return metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(train_models(args.dataset_root, args.output_root), indent=2))
