from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd


EVENT_PRIORITIES = {
    "LIQUIDATION_BUFFER_EMERGENCY": 0,
    "RISK_DRAWDOWN_EMERGENCY": 0,
    "RISK_LOSS_WARNING": 1,
    "LIQUIDATION_BUFFER_WARNING": 1,
    "PRIMARY_ADVERSE_1ATR": 2,
    "HEDGE_CLOSE_FAVORABLE": 2,
    "AVERAGE_READY": 3,
    "ENTRY_SIGNAL_STRONG": 4,
    "CATBOOST_ACTION_CHANGE": 4,
    "CATBOOST_PROBABILITY_SHIFT": 4,
    "REGIME_CHANGE": 4,
    "VOLATILITY_THRESHOLD": 4,
    "MARGIN_LIQUIDITY_SHIFT": 3,
}


@dataclass(frozen=True, order=True)
class MarketEvent:
    priority: int
    time: str
    event_type: str
    status: str
    crossed_level: float | None
    position_state: str
    features: dict[str, Any]
    catboost: dict[str, Any]
    risk: dict[str, Any]
    signature: str
    requires_qwen: bool
    suppression_reason: str | None = None

    @property
    def emergency(self) -> bool:
        return self.priority == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "time": self.time,
            "event_type": self.event_type,
            "status": self.status,
            "crossed_level": self.crossed_level,
            "position_state": self.position_state,
            "features": self.features,
            "catboost": self.catboost,
            "risk": self.risk,
            "signature": self.signature,
            "requires_qwen": self.requires_qwen,
            "suppression_reason": self.suppression_reason,
        }


@dataclass
class EventConfig:
    noncritical_cooldown_hours: float = 4.0
    dedup_hours: float = 24.0
    primary_adverse_atr: float = 1.0
    primary_rearm_atr: float = 0.5
    averaging_atr_levels: tuple[float, ...] = (2.0, 4.0)
    hedge_close_profit_fraction: float = 0.005
    probability_shift: float = 0.30
    entry_probability_threshold: float = 0.80
    volatility_threshold: float = 0.02
    risk_loss_warning: float = 0.03
    risk_loss_emergency: float = 0.05
    liquidation_warning: float = 0.05
    liquidation_emergency: float = 0.03
    free_margin_shift: float = 0.20
    liquidation_distance_shift: float = 0.03


@dataclass
class EventMonitor:
    config: EventConfig = field(default_factory=EventConfig)
    last_probabilities: dict[str, float] = field(default_factory=dict)
    last_candidate_action: str = "SKIP"
    last_regime: int = 0
    last_volatility_state: bool = False
    last_entry_signal_strong: bool = False
    last_strong_entry_direction: str | None = None
    last_position_state: str = "FLAT"
    last_free_margin: float | None = None
    last_liquidation_distance: float | None = None
    adverse_armed: bool = True
    _last_event_seen: dict[str, pd.Timestamp] = field(default_factory=dict)
    _last_noncritical_call: dict[str, pd.Timestamp] = field(default_factory=dict)

    def _event(
        self,
        *,
        time: pd.Timestamp,
        event_type: str,
        level: float | None,
        position_state: str,
        features: dict[str, Any],
        catboost: dict[str, Any],
        risk: dict[str, Any],
        signature_parts: tuple[Any, ...],
        requires_qwen: bool,
    ) -> MarketEvent:
        signature = "|".join(str(part) for part in (event_type, *signature_parts))
        priority = EVENT_PRIORITIES[event_type]
        last_seen = self._last_event_seen.get(signature)
        status = "TRIGGERED"
        reason = None
        if priority > 0 and last_seen is not None:
            if time - last_seen < pd.Timedelta(hours=self.config.dedup_hours):
                status = "SUPPRESSED"
                reason = "DEDUPLICATED"
        if status == "TRIGGERED" and priority > 0:
            last_call = self._last_noncritical_call.get(event_type)
            if last_call is not None and time - last_call < pd.Timedelta(
                hours=self.config.noncritical_cooldown_hours
            ):
                status = "SUPPRESSED"
                reason = "COOLDOWN"
        if status == "TRIGGERED":
            self._last_event_seen[signature] = time
            if priority > 0:
                self._last_noncritical_call[event_type] = time
        return MarketEvent(
            priority=priority,
            time=time.isoformat(),
            event_type=event_type,
            status=status,
            crossed_level=level,
            position_state=position_state,
            features=features,
            catboost=catboost,
            risk=risk,
            signature=signature,
            requires_qwen=requires_qwen,
            suppression_reason=reason,
        )

    def observe(
        self,
        *,
        time: pd.Timestamp,
        row: pd.Series,
        position_state: str,
        primary_side: int,
        primary_entry: float | None,
        primary_unrealized_fraction: float,
        averaging_count: int,
        hedge_side: int,
        hedge_unrealized_fraction: float,
        pending_action: str,
        catboost: dict[str, Any],
        risk: dict[str, Any],
        free_margin_fraction: float,
        liquidation_distance_fraction: float,
        futures_drawdown_fraction: float,
    ) -> list[MarketEvent]:
        events: list[MarketEvent] = []
        atr = float(row.get("1H.ATR_14_V1.atr") or 0.0)
        current_price = float(row["close"])
        minute_high = float(row.get("minute_high") or current_price)
        minute_low = float(row.get("minute_low") or current_price)
        features = {
            "close": current_price,
            "minute_high": minute_high,
            "minute_low": minute_low,
            "atr": atr,
            "atr_norm": (
                float(row.get("1H.ATR_14_V1.atr_norm") or 0.0)
            ),
            "adx": float(row.get("1H.ADX_14_V1.adx") or 0.0),
            "dma_4h": float(
                row.get("4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT") or 0.0
            ),
        }
        risk_payload = {
            **risk,
            "free_margin_fraction": free_margin_fraction,
            "liquidation_distance_fraction": liquidation_distance_fraction,
            "futures_drawdown_fraction": futures_drawdown_fraction,
            "primary_unrealized_fraction": primary_unrealized_fraction,
            "hedge_unrealized_fraction": hedge_unrealized_fraction,
        }

        def add(
            event_type: str,
            level: float | None,
            *signature: Any,
            requires_qwen: bool,
        ) -> None:
            events.append(
                self._event(
                    time=time,
                    event_type=event_type,
                    level=level,
                    position_state=position_state,
                    features=features,
                    catboost=catboost,
                    risk=risk_payload,
                    signature_parts=(position_state, primary_side, *signature),
                    requires_qwen=requires_qwen,
                )
            )

        if position_state != "FLAT":
            if liquidation_distance_fraction < self.config.liquidation_emergency:
                add(
                    "LIQUIDATION_BUFFER_EMERGENCY",
                    liquidation_distance_fraction,
                    round(liquidation_distance_fraction, 4),
                    requires_qwen=False,
                )
            elif liquidation_distance_fraction < self.config.liquidation_warning:
                add(
                    "LIQUIDATION_BUFFER_WARNING",
                    liquidation_distance_fraction,
                    round(liquidation_distance_fraction, 3),
                    requires_qwen=True,
                )
            if futures_drawdown_fraction >= self.config.risk_loss_emergency:
                add(
                    "RISK_DRAWDOWN_EMERGENCY",
                    futures_drawdown_fraction,
                    round(futures_drawdown_fraction, 4),
                    requires_qwen=False,
                )
            elif primary_unrealized_fraction <= -self.config.risk_loss_warning:
                add(
                    "RISK_LOSS_WARNING",
                    primary_unrealized_fraction,
                    round(primary_unrealized_fraction, 3),
                    requires_qwen=True,
                )

        if (
            position_state != "FLAT"
            and primary_side != 0
            and primary_entry is not None
            and atr > 0
        ):
            adverse_price = (
                primary_entry - minute_low
                if primary_side > 0
                else minute_high - primary_entry
            )
            adverse_atr = adverse_price / atr
            if adverse_atr >= self.config.primary_adverse_atr and self.adverse_armed:
                self.adverse_armed = False
                add(
                    "PRIMARY_ADVERSE_1ATR",
                    primary_entry + primary_side * atr,
                    round(adverse_atr, 2),
                    requires_qwen=True,
                )
            elif (
                not self.adverse_armed
                and adverse_atr <= self.config.primary_rearm_atr
            ):
                self.adverse_armed = True
            if (
                averaging_count < len(self.config.averaging_atr_levels)
                and adverse_atr
                >= self.config.averaging_atr_levels[averaging_count]
            ):
                add(
                    "AVERAGE_READY",
                    primary_entry + primary_side * atr * self.config.averaging_atr_levels[averaging_count],
                    averaging_count,
                    round(adverse_atr, 2),
                    requires_qwen=True,
                )

        if hedge_side != 0 and (
            pending_action == "CLOSE_HEDGE"
            or hedge_unrealized_fraction >= self.config.hedge_close_profit_fraction
            or pending_action == "EXIT"
        ):
            add(
                "HEDGE_CLOSE_FAVORABLE",
                current_price,
                hedge_side,
                pending_action,
                round(hedge_unrealized_fraction, 4),
                requires_qwen=True,
            )

        if pending_action != self.last_candidate_action:
            action_change_significant = (
                position_state != "FLAT"
                and pending_action
                in {
                    "OPEN_HEDGE",
                    "CLOSE_HEDGE",
                    "AVERAGE_PRIMARY",
                    "REDUCE_POSITION",
                    "EXIT",
                }
            )
            add(
                "CATBOOST_ACTION_CHANGE",
                None,
                self.last_candidate_action,
                pending_action,
                requires_qwen=action_change_significant,
            )
            self.last_candidate_action = pending_action

        probability_values = {
            key: float(value)
            for key, value in catboost.items()
            if isinstance(value, (int, float)) and key.endswith("probability")
        }
        if probability_values and self.last_probabilities:
            max_shift = max(
                abs(probability_values[key] - self.last_probabilities.get(key, probability_values[key]))
                for key in probability_values
            )
            if max_shift >= self.config.probability_shift:
                add(
                    "CATBOOST_PROBABILITY_SHIFT",
                    max_shift,
                    round(
                        probability_values.get("long_probability", 0.0),
                        2,
                    ),
                        round(
                            probability_values.get("short_probability", 0.0),
                            2,
                        ),
                    requires_qwen=position_state != "FLAT",
                )
        self.last_probabilities = probability_values

        entry_signal_strength = max(
            probability_values.get("long_probability", 0.0),
            probability_values.get("short_probability", 0.0),
        )
        entry_signal_strong = (
            position_state == "FLAT"
            and pending_action in {"OPEN_LONG", "OPEN_SHORT"}
            and entry_signal_strength >= self.config.entry_probability_threshold
        )
        if self.last_position_state != "FLAT" and position_state == "FLAT":
            self.last_strong_entry_direction = None
        if (
            entry_signal_strong
            and pending_action != self.last_strong_entry_direction
        ):
            add(
                "ENTRY_SIGNAL_STRONG",
                entry_signal_strength,
                pending_action,
                round(entry_signal_strength, 3),
                requires_qwen=True,
            )
            self.last_strong_entry_direction = pending_action
        self.last_entry_signal_strong = entry_signal_strong
        self.last_position_state = position_state

        regime = 1 if features["dma_4h"] > 0 else -1 if features["dma_4h"] < 0 else 0
        if regime != 0 and self.last_regime != 0 and regime != self.last_regime:
            add(
                "REGIME_CHANGE",
                features["dma_4h"],
                self.last_regime,
                regime,
                requires_qwen=position_state != "FLAT",
            )
        if regime != 0:
            self.last_regime = regime

        volatility_state = features["atr_norm"] >= self.config.volatility_threshold
        if volatility_state != self.last_volatility_state:
            add(
                "VOLATILITY_THRESHOLD",
                features["atr_norm"],
                int(volatility_state),
                requires_qwen=position_state != "FLAT",
            )
            self.last_volatility_state = volatility_state

        if self.last_free_margin is not None and self.last_liquidation_distance is not None:
            if (
                abs(free_margin_fraction - self.last_free_margin)
                >= self.config.free_margin_shift
                or abs(
                    liquidation_distance_fraction
                    - self.last_liquidation_distance
                )
                >= self.config.liquidation_distance_shift
            ):
                add(
                    "MARGIN_LIQUIDITY_SHIFT",
                    liquidation_distance_fraction,
                    round(free_margin_fraction, 3),
                    round(liquidation_distance_fraction, 3),
                    requires_qwen=position_state != "FLAT",
                )
        self.last_free_margin = free_margin_fraction
        self.last_liquidation_distance = liquidation_distance_fraction
        return sorted(events)

    @staticmethod
    def triggered(events: list[MarketEvent]) -> list[MarketEvent]:
        return [event for event in events if event.status == "TRIGGERED"]

    @staticmethod
    def triggered_for_qwen(events: list[MarketEvent]) -> list[MarketEvent]:
        return [
            event
            for event in events
            if event.status == "TRIGGERED" and event.requires_qwen
        ]

    @staticmethod
    def emergency(events: list[MarketEvent]) -> list[MarketEvent]:
        return [event for event in events if event.status == "TRIGGERED" and event.emergency]
