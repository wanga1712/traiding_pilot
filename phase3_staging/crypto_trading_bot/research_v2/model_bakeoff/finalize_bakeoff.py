from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss


OUT = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/PROBABILITY-MODEL-BAKEOFF-1")
CODE_COMMIT = "409ef678a96d23fb6e133e9606016c1d9df179d8"
WFV_ORDER = ("WFV_1", "WFV_2", "WFV_3")


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(value, path: Path):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def logits(probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability.astype(float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def ece(y_true: np.ndarray, probability: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    assignments = np.minimum(np.digitize(probability, edges[1:-1]), bins - 1)
    total = len(y_true)
    result = 0.0
    for index in range(bins):
        mask = assignments == index
        if mask.any():
            result += mask.sum() / total * abs(y_true[mask].mean() - probability[mask].mean())
    return float(result)


def score(prefix: str, y_true: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    return {
        f"{prefix}_log_loss": float(log_loss(y_true, probability, labels=[0, 1])),
        f"{prefix}_brier_score": float(brier_score_loss(y_true, probability)),
        f"{prefix}_ece_10_bin": ece(y_true, probability),
    }


def main() -> None:
    selected = load_json(OUT / "selected_model_candidates_v1.json")
    predictions = pd.read_parquet(OUT / "walkforward_predictions_v1.parquet")
    target_spec = load_json(OUT / "probability_model_target_spec_v1.json")
    feature_sets = load_json(OUT / "probability_model_feature_sets_v1.json")
    config = load_json(OUT / "probability_model_config_freeze_v1.json")
    authority = load_json(OUT / "dataset_authority_gate_v1.json")
    model_manifest = load_json(OUT / "final_model_manifest_v1.json")

    calibrator_dir = OUT / "final_development_calibrators"
    calibrator_dir.mkdir(exist_ok=True)
    result_rows: list[dict] = []
    calibrators: dict[str, dict] = {}

    for horizon_text, choice in sorted(selected.items(), key=lambda pair: int(pair[0])):
        if not choice.get("selected"):
            continue
        horizon = int(horizon_text)
        mask = (
            (predictions["horizon_minutes"] == horizon)
            & (predictions["family"] == choice["family"])
            & (predictions["feature_set"] == choice["feature_set"])
        )
        candidate = predictions.loc[mask].copy()
        previous = []
        for wfv in WFV_ORDER:
            evaluation = candidate[candidate["wfv"] == wfv]
            if evaluation.empty:
                raise RuntimeError(f"Missing OOF predictions for {horizon}m {wfv}")
            y_eval = evaluation["y"].to_numpy(dtype=np.int8)
            p_eval = evaluation["p_up"].to_numpy(dtype=float)
            row = {
                "horizon_minutes": horizon,
                "model_family": choice["family"],
                "feature_set": choice["feature_set"],
                "wfv": wfv,
                "evaluation_rows": len(evaluation),
                "calibration_training_rows": sum(len(block) for block in previous),
                **score("raw", y_eval, p_eval),
            }
            if previous:
                calibration = pd.concat(previous, ignore_index=True)
                calibrator = LogisticRegression(solver="lbfgs", random_state=config["random_seed"])
                calibrator.fit(logits(calibration["p_up"].to_numpy()), calibration["y"].to_numpy())
                calibrated = calibrator.predict_proba(logits(p_eval))[:, 1]
                row.update(score("calibrated", y_eval, calibrated))
                row["calibration_status"] = "EVALUATED_WITH_PRIOR_OOF_ONLY"
            else:
                row.update(
                    {
                        "calibrated_log_loss": np.nan,
                        "calibrated_brier_score": np.nan,
                        "calibrated_ece_10_bin": np.nan,
                        "calibration_status": "NOT_AVAILABLE_NO_PRIOR_OOF",
                    }
                )
            result_rows.append(row)
            previous.append(evaluation[["y", "p_up"]])

        all_oof = pd.concat(previous, ignore_index=True)
        final_calibrator = LogisticRegression(solver="lbfgs", random_state=config["random_seed"])
        final_calibrator.fit(logits(all_oof["p_up"].to_numpy()), all_oof["y"].to_numpy())
        calibrator_path = calibrator_dir / f"platt_{horizon}m.joblib"
        joblib.dump(
            {
                "calibrator": final_calibrator,
                "input_transform": "logit(clipped_probability, 1e-6)",
                "horizon_minutes": horizon,
                "model_family": choice["family"],
                "feature_set": choice["feature_set"],
                "training_source": "all chronological DEVELOPMENT OOF predictions",
            },
            calibrator_path,
        )
        joblib.load(calibrator_path)
        calibrators[horizon_text] = {
            "path": str(calibrator_path),
            "bytes": calibrator_path.stat().st_size,
            "sha256": sha256(calibrator_path),
            "training_oof_rows": len(all_oof),
            "reloadable": True,
        }

    calibration_results = pd.DataFrame(result_rows)
    calibration_results.to_csv(OUT / "calibration_results_v1.csv", index=False)
    evaluated = calibration_results[calibration_results["calibrated_log_loss"].notna()]
    calibration_improved_all = bool(
        (evaluated["calibrated_log_loss"] < evaluated["raw_log_loss"]).all()
        and (evaluated["calibrated_brier_score"] < evaluated["raw_brier_score"]).all()
    )
    dump_json(
        {
            "method": "Platt sigmoid on logit(raw_probability)",
            "chronological_protocol": "WFV_2 uses WFV_1 OOF; WFV_3 uses WFV_1+WFV_2 OOF",
            "final_calibrator_training": "all DEVELOPMENT OOF predictions; frozen only for later independent OOS",
            "status": "PASS",
            "oos_probability_variant": "CALIBRATED" if calibration_improved_all else "RAW",
            "calibration_improved_all_evaluable_folds": calibration_improved_all,
            "oos_touched": "NO",
            "calibrators": calibrators,
        },
        OUT / "calibration_manifest_v1.json",
    )

    dataset_hashes = {name: values["actual"] for name, values in authority["files"].items()}
    target_hash = target_spec["target_spec_hash"]
    for model_entry in model_manifest["models"]:
        model_path = Path(model_entry["path"])
        joblib.load(model_path)
        horizon_text = str(model_entry["horizon_minutes"])
        model_entry.update(
            {
                "feature_set_hash": feature_sets["sets"][model_entry["feature_set"]]["hash"],
                "target_spec_hash": target_hash,
                "dataset_file_hashes": dataset_hashes,
                "code_commit": CODE_COMMIT,
                "library_versions": config["versions"],
                "reloadable": True,
                "calibrator": calibrators[horizon_text],
            }
        )
    dump_json(model_manifest, OUT / "final_model_manifest_v1.json")

    integrity = load_json(OUT / "probability_model_bakeoff_integrity_v1.json")
    integrity.update(
        {
            "chronological_cross_calibration": "PASS",
            "selected_candidates_frozen_and_reloadable": True,
            "final_model_lineage_complete": True,
            "completion_gate": "PASS",
        }
    )
    dump_json(integrity, OUT / "probability_model_bakeoff_integrity_v1.json")

    summary = load_json(OUT / "probability_model_bakeoff_summary_v1.json")
    summary.update(
        {
            "calibration_status": "PASS",
            "selected_probability_variant_for_oos": "CALIBRATED" if calibration_improved_all else "RAW",
            "selected_horizons_minutes": sorted(int(value) for value in calibrators),
            "final_models_reloadable": True,
        }
    )
    dump_json(summary, OUT / "probability_model_bakeoff_summary_v1.json")


if __name__ == "__main__":
    main()
