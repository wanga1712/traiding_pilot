FEATURE_ENGINE_VERSION = "VOLUME_ACCUMULATION_ENGINE_V1"

# Forbidden retrospective / outcome fields — must never enter feature calc inputs.
FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "true_pivot_time",
        "true_pivot_price",
        "pivot_type",
        "is_true_pivot_bar",
        "is_before_true_pivot",
        "is_after_true_pivot",
        "next_pivot_time",
        "next_pivot_price",
        "NEXT_LEG_DIRECTION",
        "NEXT_LEG_MOVE_ABS",
        "NEXT_LEG_MOVE_PCT",
        "R",
        "R_MINUS_1",
        "NEXT_LEG_MAE_FROM_C",
        "NEXT_LEG_MFE_FROM_C",
        "price_relative_to_C_pct",
        "price_relative_to_C_ATR",
        "bars_from_true_pivot",
        "seconds_from_true_pivot",
    }
)
