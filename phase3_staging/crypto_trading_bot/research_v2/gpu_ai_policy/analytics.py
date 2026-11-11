from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _safe_name(split: str, strategy: str, spot_fraction: float, spot_mode: str) -> str:
    return f"{split}_{strategy}_{int(spot_fraction * 100)}_{spot_mode}"


def build_analytics(backtest_root: Path) -> dict:
    metrics = pd.read_csv(backtest_root / "portfolio_metrics_v1.csv")
    impacts: list[dict] = []
    for split in ("RUN1", "RUN2"):
        for fraction in (0.60, 0.40):
            for mode in ("HOLD", "SWING"):
                selected = metrics[
                    (metrics["split"] == split)
                    & (metrics["spot_fraction"] == fraction)
                    & (metrics["spot_mode"] == mode)
                ].set_index("strategy")
                if not {"AI_NO_HEDGE", "AI_HEDGE", "AI_HEDGE_AVG"}.issubset(selected.index):
                    continue
                indicators = metrics[
                    (metrics["split"] == split)
                    & (metrics["spot_fraction"] == fraction)
                    & (metrics["spot_mode"] == "HOLD")
                    & (metrics["strategy"] == "INDICATORS_ONLY")
                ].iloc[0]
                no_hedge = selected.loc["AI_NO_HEDGE"]
                hedge = selected.loc["AI_HEDGE"]
                hedge_avg = selected.loc["AI_HEDGE_AVG"]
                impacts.append(
                    {
                        "split": split,
                        "spot_fraction": fraction,
                        "spot_mode": mode,
                        "indicators_final_equity": float(indicators["final_equity"]),
                        "ai_no_hedge_final_equity": float(no_hedge["final_equity"]),
                        "ai_hedge_final_equity": float(hedge["final_equity"]),
                        "ai_hedge_avg_final_equity": float(hedge_avg["final_equity"]),
                        "ai_added_value": float(
                            no_hedge["final_equity"] - indicators["final_equity"]
                        ),
                        "hedge_added_value": float(
                            hedge["final_equity"] - no_hedge["final_equity"]
                        ),
                        "averaging_added_value": float(
                            hedge_avg["final_equity"] - hedge["final_equity"]
                        ),
                        "ai_liquidations": int(no_hedge["liquidations"]),
                        "hedge_liquidations": int(hedge["liquidations"]),
                        "avg_liquidations": int(hedge_avg["liquidations"]),
                    }
                )

    for split in ("RUN1", "RUN2"):
        for mode in ("HOLD", "SWING"):
            for fraction in (0.60, 0.40):
                names = [
                    (_safe_name(split, strategy, fraction, mode), strategy)
                    for strategy in (
                        "BUY_HOLD",
                        "SMA_BASELINE",
                        "INDICATORS_ONLY",
                        "AI_NO_HEDGE",
                        "AI_HEDGE",
                        "AI_HEDGE_AVG",
                    )
                ]
                available = [
                    (path, label)
                    for path, label in names
                    if (backtest_root / f"{path}_equity.parquet").exists()
                ]
                if not available:
                    continue
                fig, axis = plt.subplots(figsize=(13, 7))
                for path, label in available:
                    equity = pd.read_parquet(backtest_root / f"{path}_equity.parquet")
                    axis.plot(
                        pd.to_datetime(equity["time"], utc=True),
                        equity["equity"],
                        label=label,
                        linewidth=1.5,
                    )
                axis.set_title(f"{split} equity curves, spot {int(fraction * 100)}/futures {int((1-fraction) * 100)}, {mode}")
                axis.set_ylabel("Equity, USDT")
                axis.grid(alpha=0.25)
                axis.legend(fontsize=8)
                fig.tight_layout()
                fig.savefig(
                    backtest_root / f"{split}_{'A' if fraction == 0.60 else 'B'}_{mode}_equity.png",
                    dpi=140,
                )
                plt.close(fig)

    impact_payload = {
        "status": "PASS",
        "development_only": True,
        "independent_oos": "NO",
        "impacts": impacts,
        "best_ai_by_split": {
            split: {
                "final_equity": float(
                    metrics[
                        (metrics["split"] == split)
                        & metrics["strategy"].str.startswith("AI_")
                    ]["final_equity"].max()
                )
            }
            for split in ("RUN1", "RUN2")
        },
        "best_buy_hold_by_split": {
            split: {
                "final_equity": float(
                    metrics[
                        (metrics["split"] == split)
                        & (metrics["strategy"] == "BUY_HOLD")
                    ]["final_equity"].max()
                )
            }
            for split in ("RUN1", "RUN2")
        },
    }
    (backtest_root / "impact_summary_v1.json").write_text(
        json.dumps(impact_payload, indent=2),
        encoding="utf-8",
    )
    return impact_payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_analytics(args.backtest_root), indent=2))
