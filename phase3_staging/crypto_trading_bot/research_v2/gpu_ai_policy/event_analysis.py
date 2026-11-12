from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def build_event_comparison(
    *,
    control_root: Path,
    qwen_336h_root: Path,
    event_root: Path,
    output_root: Path,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    control = pd.read_csv(control_root / "policy_metrics_v1.csv")
    calendar = pd.read_csv(qwen_336h_root / "portfolio_metrics_v1.csv")
    event = pd.read_csv(event_root / "policy_metrics_v1.csv")
    rows = []
    for split in ("RUN1", "RUN2"):
        for fraction in (0.60, 0.40):
            control_row = control[
                (control["split"] == split)
                & (control["spot_fraction"] == fraction)
            ].iloc[0]
            calendar_row = calendar[
                (calendar["split"] == split)
                & (calendar["spot_fraction"] == fraction)
                & (calendar["strategy"] == "CATBOOST_PLUS_QWEN")
                & (calendar["spot_mode"] == "HOLD")
            ].iloc[0]
            event_row = event[
                (event["split"] == split)
                & (event["spot_fraction"] == fraction)
            ].iloc[0]
            rows.append(
                {
                    "split": split,
                    "spot_fraction": fraction,
                    "catboost_only_equity": float(control_row["final_equity"]),
                    "qwen_336h_equity": float(calendar_row["final_equity"]),
                    "qwen_event_equity": float(event_row["final_equity"]),
                    "qwen_336h_added_value": float(
                        calendar_row["final_equity"] - control_row["final_equity"]
                    ),
                    "qwen_event_added_value": float(
                        event_row["final_equity"] - control_row["final_equity"]
                    ),
                    "event_qwen_calls": int(event_row.get("qwen_requests", 0)),
                    "event_action_changes": int(
                        event_row.get("qwen_action_changes", 0)
                    ),
                    "event_fallbacks": int(event_row.get("qwen_fallbacks", 0)),
                    "event_liquidations": int(event_row.get("liquidations", 0)),
                    "event_max_drawdown": float(event_row.get("max_drawdown", 0)),
                    "event_hedges": int(event_row.get("hedges", 0)),
                }
            )
    comparison = pd.DataFrame(rows)
    comparison.to_csv(output_root / "event_policy_comparison_v1.csv", index=False)
    for split in ("RUN1", "RUN2"):
        for fraction in (0.60, 0.40):
            safe_fraction = int(fraction * 100)
            control_equity = pd.read_parquet(
                control_root / f"{split}_{safe_fraction}_equity.parquet"
            )
            event_equity = pd.read_parquet(
                event_root / f"{split}_{safe_fraction}_equity.parquet"
            )
            calendar_equity = pd.read_parquet(
                qwen_336h_root
                / f"{split}_CATBOOST_PLUS_QWEN_{safe_fraction}_HOLD_equity.parquet"
            )
            fig, axis = plt.subplots(figsize=(13, 7))
            for frame, label in (
                (control_equity, "CATBOOST_ONLY"),
                (calendar_equity, "CATBOOST_QWEN_336H"),
                (event_equity, "CATBOOST_QWEN_EVENT_DRIVEN"),
            ):
                axis.plot(
                    pd.to_datetime(frame["time"], utc=True),
                    frame["equity"],
                    label=label,
                    linewidth=1.5,
                )
            axis.set_title(
                f"{split} Qwen control comparison - spot {safe_fraction}/futures {100-safe_fraction}"
            )
            axis.set_ylabel("Equity, USDT")
            axis.grid(alpha=0.25)
            axis.legend()
            fig.tight_layout()
            fig.savefig(
                output_root / f"{split}_{safe_fraction}_comparison.png",
                dpi=140,
            )
            plt.close(fig)
    summary = {
        "status": "PASS",
        "comparisons": comparison.to_dict(orient="records"),
        "total_event_qwen_added_value": float(
            comparison["qwen_event_added_value"].sum()
        ),
        "total_336h_qwen_added_value": float(
            comparison["qwen_336h_added_value"].sum()
        ),
        "oos_opened": "NO",
        "live_trading": "NO",
    }
    (output_root / "event_policy_comparison_v1.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--qwen-336h-root", type=Path, required=True)
    parser.add_argument("--event-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_event_comparison(
                control_root=args.control_root,
                qwen_336h_root=args.qwen_336h_root,
                event_root=args.event_root,
                output_root=args.output_root,
            ),
            indent=2,
        )
    )
