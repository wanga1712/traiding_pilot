"""Null vs zero semantics for trading run economics."""
from __future__ import annotations

from typing import Any


def is_available(value: Any) -> bool:
    return value is not None


def is_unknown(value: Any) -> bool:
    return value is None


def format_currency(value: float | int | None, *, prefix: str = "$") -> str:
    if value is None:
        return "—"
    return f"{prefix}{float(value):,.2f}"


def format_pct(value: float | int | None, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    v = float(value)
    if signed and v > 0:
        return f"+{v:.1f}%"
    return f"{v:.1f}%"


def format_int(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}"


def format_signed_currency(value: float | int | None, *, prefix: str = "$") -> str:
    if value is None:
        return "—"
    v = float(value)
    sign = "+" if v > 0 else ("-" if v < 0 else "")
    return f"{sign}{prefix}{abs(v):,.2f}"


def css_class_for_number(value: float | int | None) -> str:
    if value is None:
        return "value-unknown"
    v = float(value)
    if v > 0:
        return "value-positive"
    if v < 0:
        return "value-negative"
    return "value-neutral"


def structural_only_blocks_monetary(run: dict[str, Any]) -> bool:
    exec_block = run.get("execution") or {}
    return exec_block.get("execution_realism_level") == "STRUCTURAL_ONLY"
