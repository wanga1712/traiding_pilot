PREDICTOR_ENGINE_VERSION = "INVERSE_PREDICTOR_ENGINE_V1"
HYPOTHETICAL_INPUT_TYPE = "NEXT_BAR_CLOSE"

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

SOLUTION_STATUSES = (
    "EXACT_ANALYTIC",
    "NUMERIC_UNIQUE",
    "ALREADY_TRIGGERED",
    "NO_FINITE_SOLUTION",
    "AMBIGUOUS",
    "REQUIRES_INTRABAR_ASSUMPTION",
    "INSUFFICIENT_HISTORY",
    "INVALID_GAP",
    "UNSUPPORTED_V1",
)
