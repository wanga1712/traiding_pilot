"""COP / OP / XOP geometry from consecutive A-B-C pivots."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COP_RATIO = 0.618
OP_RATIO = 1.0
XOP_RATIO = 1.618

COP_FORMULA = "COP = C_price + AB * 0.618"
OP_FORMULA = "OP = C_price + AB * 1.000"
XOP_FORMULA = "XOP = C_price + AB * 1.618"


from .geometry_stage import stage_from_normalized_r


@dataclass(frozen=True)
class ABCGeometry:
    a_price: float
    b_price: float
    c_price: float

    @property
    def ab_length(self) -> float:
        return self.b_price - self.a_price

    def cop(self) -> float:
        return self.c_price + self.ab_length * COP_RATIO

    def op(self) -> float:
        return self.c_price + self.ab_length * OP_RATIO

    def xop(self) -> float:
        return self.c_price + self.ab_length * XOP_RATIO


def geometry_stage(current_price: float, geo: ABCGeometry) -> str:
    ab = geo.ab_length
    if ab == 0:
        return "UNKNOWN"
    r = (current_price - geo.c_price) / ab
    return stage_from_normalized_r(r)


def compute_geometry_features(
    *,
    a_price: float,
    b_price: float,
    c_price: float,
    current_price: float,
    atr: float | None = None,
    prev_same_direction_leg: float | None = None,
) -> dict[str, Any]:
    """Causal geometry features from known A, B, confirmed C — no future D."""
    geo = ABCGeometry(a_price, b_price, c_price)
    ab = geo.ab_length
    ab_abs = abs(ab)
    cop, op, xop = geo.cop(), geo.op(), geo.xop()

    r_current = (current_price - c_price) / ab if ab != 0 else None
    r_minus_1 = r_current - 1.0 if r_current is not None else None
    dist_r1 = abs(r_current - 1.0) if r_current is not None else None

    leg_ratio = None
    if prev_same_direction_leg is not None and prev_same_direction_leg != 0:
        # C→price progress magnitude / prior same-direction leg magnitude
        leg_ratio = abs(current_price - c_price) / abs(prev_same_direction_leg)

    def _dist(level: float) -> dict[str, float | None]:
        d = current_price - level
        return {
            "abs": d,
            "pct": (d / current_price * 100.0) if current_price else None,
            "atr": (d / atr) if atr and atr != 0 else None,
        }

    dc, do, dx = _dist(cop), _dist(op), _dist(xop)
    reached = lambda level: (current_price >= level) if ab > 0 else (current_price <= level)

    return {
        "AB_LENGTH": ab,
        "AB_LENGTH_PCT": (ab / c_price * 100.0) if c_price else None,
        "AB_LENGTH_ATR": (ab / atr) if atr and atr != 0 else None,
        "CURRENT_PROGRESS_FROM_C": r_current,
        "R_CURRENT": r_current,
        "R_MINUS_1": r_minus_1,
        "DIST_TO_R1": dist_r1,
        "PREV_SAME_DIRECTION_LEG": prev_same_direction_leg,
        "CURRENT_VS_PREV_LEG_RATIO": leg_ratio,
        "COP": cop,
        "OP": op,
        "XOP": xop,
        "DIST_TO_COP": dc["abs"],
        "DIST_TO_OP": do["abs"],
        "DIST_TO_XOP": dx["abs"],
        "DIST_TO_COP_PCT": dc["pct"],
        "DIST_TO_OP_PCT": do["pct"],
        "DIST_TO_XOP_PCT": dx["pct"],
        "DIST_TO_COP_ATR": dc["atr"],
        "DIST_TO_OP_ATR": do["atr"],
        "DIST_TO_XOP_ATR": dx["atr"],
        "COP_REACHED": reached(cop),
        "OP_REACHED": reached(op),
        "XOP_REACHED": reached(xop),
        "GEOMETRY_STAGE": geometry_stage(current_price, geo),
    }
