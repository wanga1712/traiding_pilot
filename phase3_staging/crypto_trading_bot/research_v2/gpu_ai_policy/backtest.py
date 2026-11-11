from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from crypto_trading_bot.research_v2.capital_growth.accounting import FuturesAccount, SpotAccount

from .config import (
    AI_VARIANTS,
    INITIAL_CAPITAL,
    LEVERAGE,
    LIQUIDATION_FEE_RATE,
    MAINTENANCE_MARGIN_RATE,
    MAX_THESIS_LOSS_FRACTION,
    RUN1_END,
    RUN1_START,
    RUN2_END,
    RUN2_START,
    SLIPPAGE_PER_SIDE,
    SPOT_FRACTIONS,
    SPOT_MODES,
    TAKER_FEE_PER_SIDE,
)
from .train import ACTION_NAMES, DatasetBundle, build_matrix, load_bundle


@dataclass
class PolicyResult:
    name: str
    split_name: str
    spot_fraction: float
    spot_mode: str
    equity: pd.DataFrame
    trades: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict[str, Any]


@dataclass
class PolicyAccount:
    spot_fraction: float
    spot_mode: str
    spot: SpotAccount = field(init=False)
    futures: FuturesAccount = field(init=False)
    peak_futures_equity: float = field(init=False)
    liquidation_count: int = 0
    averaging_count: int = 0
    hedge_count: int = 0
    spot_slippage: float = 0.0
    spot_trade_count: int = 0
    trades: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    equity_rows: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.spot = SpotAccount(cash=INITIAL_CAPITAL * self.spot_fraction)
        self.futures = FuturesAccount(
            free_collateral=INITIAL_CAPITAL * (1.0 - self.spot_fraction)
        )
        self.peak_futures_equity = self.futures.free_collateral

    def equity(self, mark: float) -> float:
        return float(self.spot.equity(mark) + self.futures.equity(mark))

    def state_features(self, mark: float, time: pd.Timestamp) -> dict[str, float]:
        primary = self.futures.primary
        hedge = self.futures.hedge
        equity = self.equity(mark)
        gross = self.futures.gross_notional(mark)
        net = self.futures.net_notional(mark)
        liquidation_distance = 0.0
        if primary is not None:
            liquidation_distance = abs(
                mark
                - primary.liquidation_price(
                    MAINTENANCE_MARGIN_RATE,
                    TAKER_FEE_PER_SIDE,
                )
            ) / mark
        futures_drawdown = max(
            0.0,
            self.peak_futures_equity - self.futures.equity(mark),
        )
        remaining = max(
            0.0,
            MAX_THESIS_LOSS_FRACTION - futures_drawdown / max(equity, 1e-9),
        )
        return {
            "spot_fraction": self.spot_fraction,
            "spot_mode_code": 1.0 if self.spot_mode == "HOLD" else 0.0,
            "spot_exposure_fraction": self.spot.eth * mark / max(equity, 1e-9),
            "primary_side": float(primary.side) if primary is not None else 0.0,
            "primary_margin_fraction": primary.margin / max(equity, 1e-9) if primary else 0.0,
            "primary_quantity_fraction": primary.quantity * mark / max(equity, 1e-9) if primary else 0.0,
            "primary_unrealized_fraction": primary.unrealized(mark) / max(equity, 1e-9) if primary else 0.0,
            "hedge_side": float(hedge.side) if hedge is not None else 0.0,
            "hedge_margin_fraction": hedge.margin / max(equity, 1e-9) if hedge else 0.0,
            "hedge_quantity_fraction": hedge.quantity * mark / max(equity, 1e-9) if hedge else 0.0,
            "hedge_unrealized_fraction": hedge.unrealized(mark) / max(equity, 1e-9) if hedge else 0.0,
            "gross_exposure_fraction": gross / max(equity, 1e-9),
            "net_exposure_fraction": net / max(equity, 1e-9),
            "free_margin_fraction": self.futures.free_collateral / max(equity, 1e-9),
            "liquidation_distance_pct": liquidation_distance,
            "averaging_count": float(primary.additions) if primary else 0.0,
            "holding_hours": (
                (time - primary.entry_time).total_seconds() / 3600.0
                if primary is not None
                else 0.0
            ),
            "fees_cumulative": self.futures.entry_fees + self.futures.exit_fees,
            "funding_cumulative": self.futures.funding_costs,
            "remaining_thesis_risk_fraction": remaining,
        }

    def _spot_swing(self, time: pd.Timestamp, mark: float, direction: int) -> None:
        if self.spot_mode != "SWING":
            return
        target = self.equity(mark) * self.spot_fraction if direction > 0 else 0.0
        if target > self.spot.equity(mark):
            spent = self.spot.buy_to_target(
                mark,
                target,
                fee_rate=TAKER_FEE_PER_SIDE,
                slippage=SLIPPAGE_PER_SIDE,
            )
            self.spot_slippage += spent * SLIPPAGE_PER_SIDE
            self.spot_trade_count += int(spent > 0)
        elif target < self.spot.equity(mark):
            proceeds = self.spot.sell_to_target(
                mark,
                target,
                fee_rate=TAKER_FEE_PER_SIDE,
                slippage=SLIPPAGE_PER_SIDE,
            )
            self.spot_slippage += proceeds * SLIPPAGE_PER_SIDE
            self.spot_trade_count += int(proceeds > 0)

    def _open(self, side: int, time: pd.Timestamp, mark: float, volume: float) -> None:
        if self.futures.primary is not None:
            return
        total = self.equity(mark)
        risk_cap = total * MAX_THESIS_LOSS_FRACTION / (0.15 * LEVERAGE)
        budget = INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.40
        margin = min(
            risk_cap,
            budget,
            self.futures.free_collateral / (1.0 + LEVERAGE * TAKER_FEE_PER_SIDE),
        )
        capacity = min(1_000.0, max(0.0, volume) * mark * 0.001)
        if margin * LEVERAGE < 5.0 or capacity < 5.0:
            return
        self.futures.open_position(
            "PRIMARY",
            side=side,
            time=time,
            price=mark,
            margin=margin,
            slippage=SLIPPAGE_PER_SIDE,
            fee_rate=TAKER_FEE_PER_SIDE,
            leverage=LEVERAGE,
            max_notional=capacity,
            min_notional=5.0,
        )
        self._spot_swing(time, mark, side)

    def _close(self, role: str, time: pd.Timestamp, mark: float, reason: str) -> None:
        if (role == "PRIMARY" and self.futures.primary is None) or (
            role == "HEDGE" and self.futures.hedge is None
        ):
            return
        trade = self.futures.close_position(
            role,
            time=time,
            price=mark,
            slippage=SLIPPAGE_PER_SIDE,
            fee_rate=TAKER_FEE_PER_SIDE,
            reason=reason,
        )
        self.trades.append(trade)
        if role == "PRIMARY":
            self._spot_swing(time, mark, 0)

    def execute(
        self,
        action: str,
        *,
        time: pd.Timestamp,
        mark: float,
        volume: float,
    ) -> None:
        if action == "OPEN_LONG":
            self._open(1, time, mark, volume)
        elif action == "OPEN_SHORT":
            self._open(-1, time, mark, volume)
        elif action == "OPEN_HEDGE" and self.futures.primary is not None:
            if self.futures.hedge is None:
                side = -self.futures.primary.side
                margin = min(
                    INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20,
                    self.futures.primary.margin,
                    self.futures.free_collateral
                    / (1.0 + LEVERAGE * TAKER_FEE_PER_SIDE),
                )
                if margin * LEVERAGE >= 5.0:
                    self.futures.open_position(
                        "HEDGE",
                        side=side,
                        time=time,
                        price=mark,
                        margin=margin,
                        slippage=SLIPPAGE_PER_SIDE,
                        fee_rate=TAKER_FEE_PER_SIDE,
                        leverage=LEVERAGE,
                    )
                    self.hedge_count += 1
        elif action == "CLOSE_HEDGE":
            self._close("HEDGE", time, mark, "AI_CLOSE_HEDGE")
        elif action == "AVERAGE_PRIMARY" and self.futures.primary is not None:
            if self.futures.primary.additions < 2:
                margin = min(
                    INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20,
                    self.futures.free_collateral
                    / (1.0 + LEVERAGE * TAKER_FEE_PER_SIDE),
                )
                if margin * LEVERAGE >= 5.0:
                    self.futures.average_primary(
                        time=time,
                        price=mark,
                        margin=margin,
                        slippage=SLIPPAGE_PER_SIDE,
                        fee_rate=TAKER_FEE_PER_SIDE,
                        leverage=LEVERAGE,
                    )
                    self.averaging_count += 1
        elif action == "REDUCE_POSITION":
            if self.futures.primary is not None:
                trade = self.futures.reduce_position(
                    "PRIMARY",
                    time=time,
                    price=mark,
                    fraction=0.5,
                    slippage=SLIPPAGE_PER_SIDE,
                    fee_rate=TAKER_FEE_PER_SIDE,
                    reason="AI_REDUCE",
                )
                self.trades.append(trade)
        elif action == "EXIT":
            self._close("HEDGE", time, mark, "AI_EXIT_HEDGE")
            self._close("PRIMARY", time, mark, "AI_EXIT")

    def apply_funding(self, mark: float, rate: float) -> None:
        if self.futures.primary is not None or self.futures.hedge is not None:
            self.futures.apply_funding(mark, rate)

    def enforce_liquidation(self, time: pd.Timestamp, high: float, low: float, close: float) -> None:
        roles: list[str] = []
        for role in ("PRIMARY", "HEDGE"):
            position = self.futures.primary if role == "PRIMARY" else self.futures.hedge
            if position is None:
                continue
            liquidation_price = position.liquidation_price(
                MAINTENANCE_MARGIN_RATE,
                TAKER_FEE_PER_SIDE,
            )
            if (position.side > 0 and low <= liquidation_price) or (
                position.side < 0 and high >= liquidation_price
            ):
                roles.append(role)
        for role in roles:
            position = self.futures.primary if role == "PRIMARY" else self.futures.hedge
            if position is None:
                continue
            liquidation_price = position.liquidation_price(
                MAINTENANCE_MARGIN_RATE,
                TAKER_FEE_PER_SIDE,
            )
            self.trades.append(
                self.futures.liquidate(
                    role,
                    time=time,
                    liquidation_price=liquidation_price,
                    liquidation_fee_rate=LIQUIDATION_FEE_RATE,
                )
            )
            self.liquidation_count += 1
        if roles:
            self._close("HEDGE", time, close, "PRIMARY_LIQUIDATION_EXIT")
            self._close("PRIMARY", time, close, "HEDGE_LIQUIDATION_EXIT")

    def record_equity(self, time: pd.Timestamp, mark: float) -> None:
        self.futures_peak = max(
            self.peak_futures_equity,
            self.futures.equity(mark),
        )
        self.peak_futures_equity = self.futures_peak
        self.equity_rows.append(
            {
                "time": time,
                "equity": self.equity(mark),
                "spot_equity": self.spot.equity(mark),
                "futures_equity": self.futures.equity(mark),
                "free_collateral": self.futures.free_collateral,
                "used_margin": self.futures.margin_used(),
            }
        )


def _indicator_score(row: pd.Series) -> float:
    score = 0.0
    mappings = (
        ("1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT", 1.0),
        ("4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT", 1.5),
        ("1H.MACD_12_26_9_V1.histogram", 2.0),
        ("4H.MACD_12_26_9_V1.histogram", 3.0),
    )
    for column, weight in mappings:
        value = row.get(column)
        if pd.notna(value):
            score += weight * np.tanh(float(value))
    for timeframe, weight in (("1H", 0.1), ("4H", 0.15)):
        k = row.get(f"{timeframe}.STOCH_14_3_3_V1.k")
        d = row.get(f"{timeframe}.STOCH_14_3_3_V1.d")
        if pd.notna(k) and pd.notna(d):
            score += weight * np.tanh(float(k) - float(d))
    adx = row.get("1H.ADX_14_V1.adx")
    if pd.notna(adx) and float(adx) < 18.0:
        score *= 0.25
    return score


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = (peak - equity) / peak.replace(0, np.nan)
    return float(drawdown.max()) if drawdown.notna().any() else 0.0


def _run_policy(
    *,
    name: str,
    split_name: str,
    frame: pd.DataFrame,
    spot_fraction: float,
    spot_mode: str,
    funding_by_time: dict[pd.Timestamp, float],
    entry_probabilities: np.ndarray | None,
    risk_predictions: np.ndarray | None,
    management_general: np.ndarray | None,
    management_model: CatBoostClassifier | None,
    management_feature_names: list[str] | None,
    management_state_columns: list[str] | None,
) -> PolicyResult:
    account = PolicyAccount(spot_fraction, spot_mode)
    first = frame.iloc[0]
    if spot_mode == "HOLD":
        spent = account.spot.buy_to_target(
            float(first["open"]),
            account.spot.cash,
            fee_rate=TAKER_FEE_PER_SIDE,
            slippage=SLIPPAGE_PER_SIDE,
        )
        account.spot_slippage += spent * SLIPPAGE_PER_SIDE
        account.spot_trade_count += int(spent > 0)
    pending_action = "SKIP"
    for index, row in frame.reset_index(drop=True).iterrows():
        time = pd.Timestamp(row["open_time"])
        open_price = float(row["open"])
        close_price = float(row["close"])
        if pending_action != "SKIP":
            account.execute(
                pending_action,
                time=time,
                mark=open_price,
                volume=float(row["volume"]),
            )
            account.decisions.append(
                {
                    "time": time,
                    "action": pending_action,
                    "decision_price": close_price,
                    "execution_price": open_price,
                    "strategy": name,
                }
            )
        funding = funding_by_time.get(time)
        if funding is not None:
            account.apply_funding(open_price, funding)
        account.enforce_liquidation(
            time,
            float(row["high"]),
            float(row["low"]),
            close_price,
        )
        account.record_equity(time, close_price)

        state = account.state_features(close_price, time)
        futures_drawdown = max(
            0.0,
            account.peak_futures_equity - account.futures.equity(close_price),
        ) / max(account.equity(close_price), 1e-9)
        if (
            account.futures.primary is not None
            and (
                futures_drawdown > MAX_THESIS_LOSS_FRACTION
                or state["liquidation_distance_pct"] < 0.02
            )
        ):
            pending_action = "EXIT"
            continue

        if name == "SMA_BASELINE":
            direction = 0
            if pd.notna(row.get("sma20")) and pd.notna(row.get("sma50")):
                if close_price > row["sma20"] > row["sma50"]:
                    direction = 1
                elif close_price < row["sma20"] < row["sma50"]:
                    direction = -1
            if account.futures.primary is None and direction:
                pending_action = "OPEN_LONG" if direction > 0 else "OPEN_SHORT"
            elif account.futures.primary is not None and direction == -account.futures.primary.side:
                pending_action = "EXIT"
            else:
                pending_action = "SKIP"
        elif name == "INDICATORS_ONLY":
            score = _indicator_score(row)
            if account.futures.primary is None:
                pending_action = (
                    "OPEN_LONG"
                    if score > 0.35
                    else "OPEN_SHORT"
                    if score < -0.35
                    else "SKIP"
                )
            else:
                pending_action = (
                    "EXIT"
                    if score * account.futures.primary.side < -0.35
                    else "SKIP"
                )
        elif entry_probabilities is not None and account.futures.primary is None:
            long_probability = float(entry_probabilities[index, 1])
            short_probability = float(entry_probabilities[index, 2])
            downside, upside = risk_predictions[index]
            if long_probability > 0.55 and downside > -0.08:
                pending_action = "OPEN_LONG"
            elif short_probability > 0.55 and upside < 0.08:
                pending_action = "OPEN_SHORT"
            else:
                pending_action = "SKIP"
        elif management_model is not None and account.futures.primary is not None:
            state_vector = np.array(
                [state[column] for column in management_state_columns],
                dtype=np.float32,
            )
            model_input = np.concatenate(
                [management_general[index], state_vector]
            ).reshape(1, -1)
            probabilities = management_model.predict_proba(model_input)[0]
            probability_by_action = dict(zip(ACTION_NAMES, probabilities))
            allowed = {"HOLD", "REDUCE_POSITION", "EXIT"}
            if account.futures.primary is not None and account.futures.primary.additions < 2:
                allowed.add("AVERAGE_PRIMARY")
            if account.futures.hedge is None:
                allowed.add("OPEN_HEDGE")
            else:
                allowed.add("CLOSE_HEDGE")
            if name == "AI_NO_HEDGE":
                allowed -= {"OPEN_HEDGE", "CLOSE_HEDGE", "AVERAGE_PRIMARY"}
            elif name == "AI_HEDGE":
                allowed -= {"AVERAGE_PRIMARY"}
            action = max(allowed, key=lambda item: probability_by_action[item])
            pending_action = {
                "HOLD": "SKIP",
                "OPEN_HEDGE": "OPEN_HEDGE",
                "CLOSE_HEDGE": "CLOSE_HEDGE",
                "AVERAGE_PRIMARY": "AVERAGE_PRIMARY",
                "REDUCE_POSITION": "REDUCE_POSITION",
                "EXIT": "EXIT",
            }[action]
        else:
            pending_action = "SKIP"

    last = frame.iloc[-1]
    final_time = pd.Timestamp(last["open_time"])
    final_mark = float(last["close"])
    account._close("HEDGE", final_time, final_mark, "RUN_END")
    account._close("PRIMARY", final_time, final_mark, "RUN_END")
    account.record_equity(final_time, final_mark)
    equity = pd.DataFrame(account.equity_rows).drop_duplicates("time").sort_values("time")
    trades = pd.DataFrame(account.trades)
    decisions = pd.DataFrame(account.decisions)
    final_equity = float(equity.iloc[-1]["equity"])
    metrics = {
        "strategy": name,
        "split": split_name,
        "spot_fraction": spot_fraction,
        "spot_mode": spot_mode,
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": final_equity,
        "return_percent": (final_equity / INITIAL_CAPITAL - 1.0) * 100.0,
        "max_drawdown": _max_drawdown(equity["equity"]),
        "liquidations": account.liquidation_count,
        "hedges": account.hedge_count,
        "averaging_count": account.averaging_count,
        "trade_count": len(trades) + account.spot_trade_count,
        "spot_trade_count": account.spot_trade_count,
        "decision_count": len(decisions),
        "fees": (
            account.futures.entry_fees
            + account.futures.exit_fees
            + account.spot.fees_paid
        ),
        "funding": account.futures.funding_costs,
        "slippage": account.futures.slippage_costs + account.spot_slippage,
        "realized_primary": account.futures.realized_primary,
        "realized_hedge": account.futures.realized_hedge,
    }
    return PolicyResult(
        name=name,
        split_name=split_name,
        spot_fraction=spot_fraction,
        spot_mode=spot_mode,
        equity=equity,
        trades=trades,
        decisions=decisions,
        metrics=metrics,
    )


def run_backtests(dataset_root: Path, training_root: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    bundle = load_bundle(dataset_root)
    metrics = json.loads((training_root / "training_metrics_v1.json").read_text())
    policy_descriptor = {
        "entry_model_sha256": metrics["entry"]["model_sha256"],
        "risk_model_sha256": metrics["risk"]["model_sha256"],
        "management_model_sha256": metrics["management"]["model_sha256"],
        "entry_probability_threshold": 0.55,
        "max_thesis_loss_fraction": MAX_THESIS_LOSS_FRACTION,
        "leverage": LEVERAGE,
        "taker_fee_per_side": TAKER_FEE_PER_SIDE,
        "slippage_per_side": SLIPPAGE_PER_SIDE,
        "actions": list(ACTION_NAMES),
    }
    policy_sha = hashlib.sha256(
        json.dumps(policy_descriptor, sort_keys=True).encode("utf-8")
    ).hexdigest()
    policy_descriptor["policy_sha256"] = policy_sha
    (output_root / "policy_manifest_v1.json").write_text(
        json.dumps(policy_descriptor, indent=2),
        encoding="utf-8",
    )
    selection_manifest = json.loads(
        (training_root / "feature_selection_manifest_v1.json").read_text()
    )
    entry_model = CatBoostClassifier()
    entry_model.load_model(training_root / "entry_direction_gpu_v1.cbm")
    risk_model = CatBoostRegressor()
    risk_model.load_model(training_root / "entry_risk_gpu_v1.cbm")
    management_model = CatBoostClassifier()
    management_model.load_model(training_root / "position_management_gpu_v1.cbm")

    all_row_ids = bundle.rows["row_id"].to_numpy()
    entry_matrix, entry_names = build_matrix(
        bundle,
        selection_manifest["entry"],
        row_ids=all_row_ids,
    )
    if entry_names != metrics["features"]:
        # CatBoost validates feature names only when provided; positional order is
        # the frozen manifest order, so keep the matrix untouched.
        pass
    entry_probabilities = entry_model.predict_proba(entry_matrix)
    risk_predictions = risk_model.predict(entry_matrix)
    management_general, management_general_names = build_matrix(
        bundle,
        selection_manifest["management"],
        row_ids=all_row_ids,
    )
    management_features = metrics["management"]["features"]
    management_state_columns = selection_manifest["management_state_features"]

    frame = bundle.features[
        [
            "row_id",
            "decision_at",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sma20",
            "sma50",
            "1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "1H.MACD_12_26_9_V1.histogram",
            "4H.MACD_12_26_9_V1.histogram",
            "1H.STOCH_14_3_3_V1.k",
            "1H.STOCH_14_3_3_V1.d",
            "4H.STOCH_14_3_3_V1.k",
            "4H.STOCH_14_3_3_V1.d",
            "1H.ADX_14_V1.adx",
        ]
    ].copy()
    funding = pd.read_parquet(
        Path(
            "/var/tmp/traiding_pilot_ui_workspace/"
            "capital_growth_experiment_v1/data/funding_ETHUSDT.parquet"
        )
    )
    funding["funding_time"] = pd.to_datetime(funding["funding_time"], utc=True)
    funding_by_time = {
        pd.Timestamp(row.funding_time): float(row.funding_rate)
        for row in funding.itertuples(index=False)
        if pd.notna(row.funding_rate)
    }
    splits = {
        "RUN1": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN1_START))
            & (frame["decision_at"] < pd.Timestamp(RUN1_END))
        ],
        "RUN2": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN2_START))
            & (frame["decision_at"] < pd.Timestamp(RUN2_END))
        ],
    }
    results: list[PolicyResult] = []
    for split_name, split_frame in splits.items():
        row_ids = split_frame["row_id"].to_numpy()
        split_entry = entry_probabilities[row_ids]
        split_risk = risk_predictions[row_ids]
        split_management = management_general[row_ids]
        for spot_fraction in SPOT_FRACTIONS:
            results.append(
                _run_policy(
                    name="BUY_HOLD",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            results.append(
                _run_policy(
                    name="SMA_BASELINE",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            results.append(
                _run_policy(
                    name="INDICATORS_ONLY",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            for variant in AI_VARIANTS:
                for spot_mode in SPOT_MODES:
                    results.append(
                        _run_policy(
                            name=variant,
                            split_name=split_name,
                            frame=split_frame,
                            spot_fraction=spot_fraction,
                            spot_mode=spot_mode,
                            funding_by_time=funding_by_time,
                            entry_probabilities=split_entry,
                            risk_predictions=split_risk,
                            management_general=split_management,
                            management_model=management_model,
                            management_feature_names=management_features,
                            management_state_columns=management_state_columns,
                        )
                    )
    metrics_frame = pd.DataFrame([result.metrics for result in results])
    metrics_frame.to_csv(output_root / "portfolio_metrics_v1.csv", index=False)
    for result in results:
        safe = f"{result.split_name}_{result.name}_{int(result.spot_fraction * 100)}_{result.spot_mode}"
        result.equity.to_parquet(output_root / f"{safe}_equity.parquet", index=False)
        result.trades.to_csv(output_root / f"{safe}_trades.csv", index=False)
        result.decisions.to_csv(output_root / f"{safe}_decisions.csv", index=False)
    summary = {
        "status": "PASS",
        "policy_sha256": policy_sha,
        "policy_manifest": str(output_root / "policy_manifest_v1.json"),
        "run1_interval": [str(RUN1_START), str(RUN1_END)],
        "run2_interval": [str(RUN2_START), str(RUN2_END)],
        "results": metrics_frame.to_dict(orient="records"),
        "oos_opened": "NO",
        "live_trading": "NO",
    }
    (output_root / "backtest_summary_v1.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_backtests(args.dataset_root, args.training_root, args.output_root),
            indent=2,
        )
    )
