CONFLUENCE_ENGINE_VERSION = "PREDICTOR_CONFLUENCE_ENGINE_V1"
PREDICTOR_ENGINE_VERSION_REQUIRED = "INVERSE_PREDICTOR_ENGINE_V1"

# Valid trigger prices may participate in confluence clustering.
VALID_SOLUTION_STATUSES = frozenset({"EXACT_ANALYTIC", "NUMERIC_UNIQUE"})

# Signed distance convention: positive = trigger ABOVE current price.
SIGNED_DISTANCE_CONVENTION = "positive_means_trigger_above_market"

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

FAMILY_BY_PREDICTOR_PREFIX = {
    "DMA_": "DMA",
    "RSI_": "RSI",
    "MACD_": "MACD",
    "STOCH_": "STOCHASTIC",
    "SMA_": "MA",
    "EMA_": "MA",
    "WMA_": "MA",
    "PROJECT_OSCILLATOR": "PROJECT_OSCILLATOR",
    "BOLLINGER_": "BOLLINGER",
}
