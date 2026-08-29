"""Schema registry: every column classified as causal / retrospective / outcome / identity / diagnostic."""
from __future__ import annotations

from typing import Literal

ColumnClass = Literal[
    "IDENTITY",
    "CAUSAL_RAW_INPUT",
    "RETROSPECTIVE_LABEL",
    "OUTCOME",
    "DIAGNOSTIC",
]

# event-level columns
EVENT_SCHEMA: list[tuple[str, ColumnClass, str]] = [
    ("event_id", "IDENTITY", "Stable event identity"),
    ("symbol", "IDENTITY", "Trading symbol"),
    ("wave_engine_version", "IDENTITY", "Immutable wave engine"),
    ("wave_dataset_version", "IDENTITY", "Immutable wave dataset"),
    ("event_dataset_version", "IDENTITY", "This event dataset version"),
    ("source_wave_tf", "IDENTITY", "TF of source ZigZag pivot"),
    ("pivot_index", "IDENTITY", "Pivot index in WAVE_DATASET_V1"),
    ("pivot_type", "RETROSPECTIVE_LABEL", "HIGH|LOW true pivot type"),
    ("true_pivot_time", "RETROSPECTIVE_LABEL", "True pivot timestamp"),
    ("true_pivot_price", "RETROSPECTIVE_LABEL", "True pivot price"),
    ("confirmation_time", "RETROSPECTIVE_LABEL", "ZigZag confirmation time"),
    ("confirmation_delay_bars", "RETROSPECTIVE_LABEL", "Bars from pivot to confirmation"),
    ("previous_pivot_time", "RETROSPECTIVE_LABEL", "Prior pivot time"),
    ("previous_pivot_price", "RETROSPECTIVE_LABEL", "Prior pivot price"),
    ("next_pivot_time", "OUTCOME", "Next pivot time (after C)"),
    ("next_pivot_price", "OUTCOME", "Next pivot price"),
    ("NEXT_LEG_DIRECTION", "OUTCOME", "UP|DOWN of leg C→next"),
    ("NEXT_LEG_MOVE_ABS", "OUTCOME", "Signed price change C→next"),
    ("NEXT_LEG_MOVE_PCT", "OUTCOME", "Percent move C→next"),
    ("NEXT_LEG_DURATION_BARS", "OUTCOME", "Bars C→next on source TF"),
    ("NEXT_LEG_DURATION_SECONDS", "OUTCOME", "Seconds C→next"),
    ("R", "OUTCOME", "Rolling geometry R for window ending at next as D when available"),
    ("R_MINUS_1", "OUTCOME", "R - 1.0 vs LEG_PERSISTENCE_BASELINE"),
    ("NEXT_LEG_MAE_FROM_C", "OUTCOME", "Max adverse excursion from C during next leg"),
    ("NEXT_LEG_MFE_FROM_C", "OUTCOME", "Max favorable excursion from C during next leg"),
    ("prev_leg_direction", "CAUSAL_RAW_INPUT", "Previous completed leg direction (known at C)"),
    ("prev_leg_move_pct", "CAUSAL_RAW_INPUT", "Previous leg move %"),
    ("prev_leg_duration_bars", "CAUSAL_RAW_INPUT", "Previous leg duration bars"),
    ("atr_at_pivot_source_tf", "CAUSAL_RAW_INPUT", "ATR on source TF at pivot bar if available"),
    ("calendar_year", "CAUSAL_RAW_INPUT", "UTC year of true_pivot_time"),
    ("calendar_month", "CAUSAL_RAW_INPUT", "UTC month of true_pivot_time"),
    ("partition", "DIAGNOSTIC", "DISCOVERY|VALIDATION|OOS|PARTITION_CROSS_PURGED"),
    ("partition_usable", "DIAGNOSTIC", "Whether event is usable in its partition for training"),
    ("CONTEXT_5M", "DIAGNOSTIC", "COMPLETE|PARTIAL|MISSING"),
    ("CONTEXT_15M", "DIAGNOSTIC", "COMPLETE|PARTIAL|MISSING"),
    ("CONTEXT_1H", "DIAGNOSTIC", "COMPLETE|PARTIAL|MISSING"),
    ("CONTEXT_4H", "DIAGNOSTIC", "COMPLETE|PARTIAL|MISSING"),
    ("CONTEXT_COMPLETE", "DIAGNOSTIC", "True if all context TFs COMPLETE"),
    ("quality_flag_source_tf", "DIAGNOSTIC", "Wave quality flag from WAVE_ENGINE_V1"),
]

# per-bar columns in event windows
BAR_SCHEMA: list[tuple[str, ColumnClass, str]] = [
    ("event_id", "IDENTITY", "Parent event"),
    ("timeframe", "IDENTITY", "Context TF"),
    ("bar_index_relative_to_pivot", "DIAGNOSTIC", "Alignment index; NOT a causal feature"),
    ("open_time", "CAUSAL_RAW_INPUT", "Bar open time"),
    ("close_time", "CAUSAL_RAW_INPUT", "Bar close time"),
    ("open", "CAUSAL_RAW_INPUT", "Open"),
    ("high", "CAUSAL_RAW_INPUT", "High"),
    ("low", "CAUSAL_RAW_INPUT", "Low"),
    ("close", "CAUSAL_RAW_INPUT", "Close"),
    ("volume", "CAUSAL_RAW_INPUT", "Volume"),
    ("is_before_true_pivot", "RETROSPECTIVE_LABEL", "Evaluation metadata only"),
    ("is_true_pivot_bar", "RETROSPECTIVE_LABEL", "Evaluation metadata only"),
    ("is_after_true_pivot", "RETROSPECTIVE_LABEL", "Evaluation metadata only"),
    ("seconds_from_true_pivot", "DIAGNOSTIC", "Research alignment only"),
    ("bars_from_true_pivot", "DIAGNOSTIC", "Research alignment only; NOT causal"),
    ("price_relative_to_C_pct", "DIAGNOSTIC", "RETROSPECTIVE_ANALYSIS_ONLY"),
    ("price_relative_to_C_ATR", "DIAGNOSTIC", "RETROSPECTIVE_ANALYSIS_ONLY"),
    ("distance_from_previous_pivot_pct", "DIAGNOSTIC", "Uses previous pivot; diagnostic"),
]


def schema_rows() -> list[dict]:
    rows = []
    for name, klass, note in EVENT_SCHEMA:
        rows.append({"table": "reversal_events", "column": name, "class": klass, "note": note})
    for name, klass, note in BAR_SCHEMA:
        rows.append({"table": "event_bars", "column": name, "class": klass, "note": note})
    return rows


def columns_by_class(klass: ColumnClass) -> list[str]:
    return [n for n, k, _ in EVENT_SCHEMA + BAR_SCHEMA if k == klass]
