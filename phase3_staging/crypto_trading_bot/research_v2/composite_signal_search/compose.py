"""Boolean composite emission: CONTEXT_STATE ∧ TRIGGER_EVENT."""
from __future__ import annotations

import hashlib
import itertools
from typing import Any, Iterator, Sequence

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.reversal_signal_study.signals import _emit

from .config import MAX_COMPOSITE_COMPONENTS, TF_BAR_SECONDS, load_templates
from .context_state import (
    build_state_timeline,
    context_aligned,
    detect_gap_reset_times,
    pair_key_from_config,
    state_at,
)


def _stream_events(stream: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stream is None:
        return []
    if isinstance(stream, dict):
        return list(stream.get("events") or stream.get("signals") or [])
    return list(stream)


def compose_signals(
    *,
    composite_id: str,
    trigger_signals: Sequence[dict[str, Any]],
    trigger_direction: str,
    decision_tf: str,
    context_timelines: Sequence[Sequence[Any]],
    context_ages: bool = False,
) -> list[dict[str, Any]]:
    """
    Emit composite signals at trigger available_at when all context states align.

    Composite timestamp MUST equal the trigger available_at (subset of trigger times).
    """
    out: list[dict[str, Any]] = []
    for sig in trigger_signals:
        if sig.get("signal_direction") not in (None, trigger_direction) and sig.get("signal_direction") != trigger_direction:
            continue
        direction = sig.get("signal_direction") or trigger_direction
        if direction != trigger_direction:
            continue
        t = sig["available_at"]
        if not all(context_aligned(tl, t, trigger_direction) for tl in context_timelines):  # type: ignore[arg-type]
            continue
        price = float(sig.get("signal_price") or sig.get("price") or 0.0)
        row_buf: list[dict[str, Any]] = []
        _emit(
            row_buf,
            candidate_id=composite_id,
            signal_time=t,
            signal_price=price,
            direction=trigger_direction,
            decision_tf=decision_tf,
            calculated_at=sig.get("calculated_at", t),
            available_at=t,
        )
        if context_ages and row_buf:
            # Diagnostic only — age of each context state at trigger time.
            ages = []
            for tl in context_timelines:
                st = state_at(tl, t)  # type: ignore[arg-type]
                last = None
                target = parse_ts(t)
                for ev in tl:
                    if ev.available_at <= target:
                        last = ev
                    else:
                        break
                ages.append(
                    {
                        "state": st,
                        "age_seconds": None
                        if last is None
                        else (target - last.available_at).total_seconds(),
                    }
                )
            row_buf[0]["context_age_diagnostic"] = ages
        out.extend(row_buf)
    return out


def assert_timestamps_subset_of_trigger(
    composite_signals: Sequence[dict[str, Any]],
    trigger_signals: Sequence[dict[str, Any]],
) -> None:
    trigger_times = {str(s["available_at"]) for s in trigger_signals}
    for sig in composite_signals:
        if str(sig["available_at"]) not in trigger_times:
            raise AssertionError(
                "COMPOSITE_SIGNAL_TIMESTAMP_SUBSET_OF_TRIGGER_TIMESTAMPS failed: "
                f"{sig['available_at']}"
            )
        if str(sig["signal_time"]) != str(sig["available_at"]):
            raise AssertionError("composite signal_time must equal available_at (trigger time)")


def _configs_for_tf_direction(
    reps: Sequence[dict[str, Any]],
    *,
    tfs: Sequence[str],
    direction: str,
) -> list[dict[str, Any]]:
    tf_set = set(tfs)
    return [r for r in reps if r["decision_tf"] in tf_set and r["direction"] == direction]


def _timeline_for_config(
    config: dict[str, Any],
    streams_by_id: dict[str, Any],
    pair_mates: dict[tuple, dict[str, dict[str, Any]]],
    bars_by_tf: dict[str, list[dict[str, Any]]] | None,
) -> list[Any]:
    key = pair_key_from_config(config)
    mates = pair_mates.get(key, {})
    up_row = mates.get("UP")
    down_row = mates.get("DOWN")
    up_events = _stream_events(streams_by_id.get(up_row["candidate_id"]) if up_row else None)
    down_events = _stream_events(streams_by_id.get(down_row["candidate_id"]) if down_row else None)
    gap_resets: list[Any] = []
    tf = config["decision_tf"]
    if bars_by_tf and tf in bars_by_tf:
        closes = [b["close_time"] for b in bars_by_tf[tf]]
        gap_resets = detect_gap_reset_times(
            closes,
            expected_bar_seconds=float(TF_BAR_SECONDS.get(tf, 3600)),
        )
    return build_state_timeline(up_events, down_events, gap_reset_times=gap_resets)


def expand_template_composites(
    template: dict[str, Any],
    *,
    representatives: Sequence[dict[str, Any]],
    streams_by_id: dict[str, Any],
    all_configs_for_pairs: Sequence[dict[str, Any]] | None = None,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    directions: Sequence[str] = ("UP", "DOWN"),
) -> list[dict[str, Any]]:
    """
    Expand one frozen template into concrete composite definitions + signals.

    Returns list of result dicts with keys:
      composite_id, template_id, direction, decision_tf, components, signals, diagnostic
    """
    from .context_state import pair_configs_by_stream

    pair_source = list(all_configs_for_pairs) if all_configs_for_pairs is not None else list(representatives)
    pair_mates = pair_configs_by_stream(pair_source)
    tid = template["template_id"]
    diagnostic = bool(template.get("diagnostic", False))
    results: list[dict[str, Any]] = []

    for direction in directions:
        if template.get("same_tf") and template.get("cross_family"):
            for tf in template.get("tfs", []):
                pool = _configs_for_tf_direction(representatives, tfs=[tf], direction=direction)
                # Context and trigger from different families on same TF.
                for ctx, trig in itertools.permutations(pool, 2):
                    if ctx["family"] == trig["family"]:
                        continue
                    components = [
                        {"role": "context", "candidate_id": ctx["candidate_id"], "tf": tf, "family": ctx["family"]},
                        {"role": "trigger", "candidate_id": trig["candidate_id"], "tf": tf, "family": trig["family"]},
                    ]
                    if len(components) > MAX_COMPOSITE_COMPONENTS:
                        continue
                    tl = _timeline_for_config(ctx, streams_by_id, pair_mates, bars_by_tf)
                    trig_stream = _stream_events(streams_by_id.get(trig["candidate_id"]))
                    cid = _composite_id(tid, direction, components)
                    sigs = compose_signals(
                        composite_id=cid,
                        trigger_signals=trig_stream,
                        trigger_direction=direction,
                        decision_tf=tf,
                        context_timelines=[tl],
                    )
                    assert_timestamps_subset_of_trigger(sigs, trig_stream)
                    results.append(
                        {
                            "composite_id": cid,
                            "template_id": tid,
                            "direction": direction,
                            "decision_tf": tf,
                            "trigger_candidate_id": trig["candidate_id"],
                            "context_candidate_ids": [ctx["candidate_id"]],
                            "components": components,
                            "signals": sigs,
                            "diagnostic": diagnostic,
                        }
                    )
            continue

        n_context = int(template.get("n_context", 1))
        trigger_tfs = list(template.get("trigger_tfs", []))
        if n_context == 1:
            context_tfs = list(template.get("context_tfs", []))
            ctx_pool = _configs_for_tf_direction(representatives, tfs=context_tfs, direction=direction)
            trig_pool = _configs_for_tf_direction(representatives, tfs=trigger_tfs, direction=direction)
            for ctx, trig in itertools.product(ctx_pool, trig_pool):
                components = [
                    {
                        "role": "context",
                        "candidate_id": ctx["candidate_id"],
                        "tf": ctx["decision_tf"],
                        "family": ctx["family"],
                    },
                    {
                        "role": "trigger",
                        "candidate_id": trig["candidate_id"],
                        "tf": trig["decision_tf"],
                        "family": trig["family"],
                    },
                ]
                tl = _timeline_for_config(ctx, streams_by_id, pair_mates, bars_by_tf)
                trig_stream = _stream_events(streams_by_id.get(trig["candidate_id"]))
                cid = _composite_id(tid, direction, components)
                sigs = compose_signals(
                    composite_id=cid,
                    trigger_signals=trig_stream,
                    trigger_direction=direction,
                    decision_tf=trig["decision_tf"],
                    context_timelines=[tl],
                )
                assert_timestamps_subset_of_trigger(sigs, trig_stream)
                results.append(
                    {
                        "composite_id": cid,
                        "template_id": tid,
                        "direction": direction,
                        "decision_tf": trig["decision_tf"],
                        "trigger_candidate_id": trig["candidate_id"],
                        "context_candidate_ids": [ctx["candidate_id"]],
                        "components": components,
                        "signals": sigs,
                        "diagnostic": diagnostic,
                    }
                )
        elif n_context == 2:
            ctx1_tfs = list(template.get("context_tfs_1", []))
            ctx2_tfs = list(template.get("context_tfs_2", []))
            ctx1_pool = _configs_for_tf_direction(representatives, tfs=ctx1_tfs, direction=direction)
            ctx2_pool = _configs_for_tf_direction(representatives, tfs=ctx2_tfs, direction=direction)
            trig_pool = _configs_for_tf_direction(representatives, tfs=trigger_tfs, direction=direction)
            for c1, c2, trig in itertools.product(ctx1_pool, ctx2_pool, trig_pool):
                components = [
                    {
                        "role": "context",
                        "candidate_id": c1["candidate_id"],
                        "tf": c1["decision_tf"],
                        "family": c1["family"],
                    },
                    {
                        "role": "context",
                        "candidate_id": c2["candidate_id"],
                        "tf": c2["decision_tf"],
                        "family": c2["family"],
                    },
                    {
                        "role": "trigger",
                        "candidate_id": trig["candidate_id"],
                        "tf": trig["decision_tf"],
                        "family": trig["family"],
                    },
                ]
                if len(components) > MAX_COMPOSITE_COMPONENTS:
                    continue
                tls = [
                    _timeline_for_config(c1, streams_by_id, pair_mates, bars_by_tf),
                    _timeline_for_config(c2, streams_by_id, pair_mates, bars_by_tf),
                ]
                trig_stream = _stream_events(streams_by_id.get(trig["candidate_id"]))
                cid = _composite_id(tid, direction, components)
                sigs = compose_signals(
                    composite_id=cid,
                    trigger_signals=trig_stream,
                    trigger_direction=direction,
                    decision_tf=trig["decision_tf"],
                    context_timelines=tls,
                )
                assert_timestamps_subset_of_trigger(sigs, trig_stream)
                results.append(
                    {
                        "composite_id": cid,
                        "template_id": tid,
                        "direction": direction,
                        "decision_tf": trig["decision_tf"],
                        "trigger_candidate_id": trig["candidate_id"],
                        "context_candidate_ids": [c1["candidate_id"], c2["candidate_id"]],
                        "components": components,
                        "signals": sigs,
                        "diagnostic": diagnostic,
                    }
                )
        else:
            raise ValueError(f"unsupported n_context={n_context} for {tid}")

    return results


def expand_all_templates(
    *,
    representatives: Sequence[dict[str, Any]],
    streams_by_id: dict[str, Any],
    all_configs_for_pairs: Sequence[dict[str, Any]] | None = None,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    templates_doc: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    doc = templates_doc if templates_doc is not None else load_templates()
    out: list[dict[str, Any]] = []
    for tmpl in doc["templates"]:
        out.extend(
            expand_template_composites(
                tmpl,
                representatives=representatives,
                streams_by_id=streams_by_id,
                all_configs_for_pairs=all_configs_for_pairs,
                bars_by_tf=bars_by_tf,
            )
        )
    return out


def _composite_id(template_id: str, direction: str, components: Sequence[dict[str, Any]]) -> str:
    parts = [template_id, direction]
    for c in components:
        parts.append(f"{c['role']}:{c['candidate_id']}")
    raw = "|".join(parts)
    digest = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return f"COMP|{template_id}|{direction}|{digest}"


def iter_template_definitions(
    template: dict[str, Any],
    *,
    representatives: Sequence[dict[str, Any]],
    all_configs_for_pairs: Sequence[dict[str, Any]] | None = None,
    directions: Sequence[str] = ("UP", "DOWN"),
) -> Iterator[dict[str, Any]]:
    """
    Deterministic generator of composite *definitions* (no signal arrays).

    COMPOSITE_DEFINITION_GENERATOR=YES
    ALL_COMPOSITE_DEFINITIONS_IN_RAM=NO
    IDs/count identical to expand_template_composites combinatorics.
    """
    pair_source = list(all_configs_for_pairs) if all_configs_for_pairs is not None else list(representatives)
    _ = pair_source  # pairing is resolved later at compose time
    tid = template["template_id"]
    diagnostic = bool(template.get("diagnostic", False))

    for direction in directions:
        if template.get("same_tf") and template.get("cross_family"):
            for tf in template.get("tfs", []):
                pool = _configs_for_tf_direction(representatives, tfs=[tf], direction=direction)
                for ctx, trig in itertools.permutations(pool, 2):
                    if ctx["family"] == trig["family"]:
                        continue
                    components = [
                        {"role": "context", "candidate_id": ctx["candidate_id"], "tf": tf, "family": ctx["family"]},
                        {"role": "trigger", "candidate_id": trig["candidate_id"], "tf": tf, "family": trig["family"]},
                    ]
                    if len(components) > MAX_COMPOSITE_COMPONENTS:
                        continue
                    yield {
                        "composite_id": _composite_id(tid, direction, components),
                        "template_id": tid,
                        "direction": direction,
                        "decision_tf": tf,
                        "trigger_candidate_id": trig["candidate_id"],
                        "context_candidate_ids": [ctx["candidate_id"]],
                        "components": components,
                        "diagnostic": diagnostic,
                    }
            continue

        n_context = int(template.get("n_context", 1))
        trigger_tfs = list(template.get("trigger_tfs", []))
        if n_context == 1:
            context_tfs = list(template.get("context_tfs", []))
            ctx_pool = _configs_for_tf_direction(representatives, tfs=context_tfs, direction=direction)
            trig_pool = _configs_for_tf_direction(representatives, tfs=trigger_tfs, direction=direction)
            for ctx, trig in itertools.product(ctx_pool, trig_pool):
                components = [
                    {
                        "role": "context",
                        "candidate_id": ctx["candidate_id"],
                        "tf": ctx["decision_tf"],
                        "family": ctx["family"],
                    },
                    {
                        "role": "trigger",
                        "candidate_id": trig["candidate_id"],
                        "tf": trig["decision_tf"],
                        "family": trig["family"],
                    },
                ]
                yield {
                    "composite_id": _composite_id(tid, direction, components),
                    "template_id": tid,
                    "direction": direction,
                    "decision_tf": trig["decision_tf"],
                    "trigger_candidate_id": trig["candidate_id"],
                    "context_candidate_ids": [ctx["candidate_id"]],
                    "components": components,
                    "diagnostic": diagnostic,
                }
        elif n_context == 2:
            ctx1_tfs = list(template.get("context_tfs_1", []))
            ctx2_tfs = list(template.get("context_tfs_2", []))
            ctx1_pool = _configs_for_tf_direction(representatives, tfs=ctx1_tfs, direction=direction)
            ctx2_pool = _configs_for_tf_direction(representatives, tfs=ctx2_tfs, direction=direction)
            trig_pool = _configs_for_tf_direction(representatives, tfs=trigger_tfs, direction=direction)
            for c1, c2, trig in itertools.product(ctx1_pool, ctx2_pool, trig_pool):
                components = [
                    {
                        "role": "context",
                        "candidate_id": c1["candidate_id"],
                        "tf": c1["decision_tf"],
                        "family": c1["family"],
                    },
                    {
                        "role": "context",
                        "candidate_id": c2["candidate_id"],
                        "tf": c2["decision_tf"],
                        "family": c2["family"],
                    },
                    {
                        "role": "trigger",
                        "candidate_id": trig["candidate_id"],
                        "tf": trig["decision_tf"],
                        "family": trig["family"],
                    },
                ]
                if len(components) > MAX_COMPOSITE_COMPONENTS:
                    continue
                yield {
                    "composite_id": _composite_id(tid, direction, components),
                    "template_id": tid,
                    "direction": direction,
                    "decision_tf": trig["decision_tf"],
                    "trigger_candidate_id": trig["candidate_id"],
                    "context_candidate_ids": [c1["candidate_id"], c2["candidate_id"]],
                    "components": components,
                    "diagnostic": diagnostic,
                }
        else:
            raise ValueError(f"unsupported n_context={n_context} for {tid}")


def iter_all_template_definitions(
    *,
    representatives: Sequence[dict[str, Any]],
    all_configs_for_pairs: Sequence[dict[str, Any]] | None = None,
    templates_doc: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    doc = templates_doc if templates_doc is not None else load_templates()
    for tmpl in doc["templates"]:
        yield from iter_template_definitions(
            tmpl,
            representatives=representatives,
            all_configs_for_pairs=all_configs_for_pairs,
        )


def compose_signals_from_compact(
    *,
    composite_id: str,
    trigger_ns: Any,
    trigger_prices: Any,
    trigger_direction: str,
    decision_tf: str,
    context_timelines: Sequence[tuple[Any, Any]],
) -> list[dict[str, Any]]:
    """Compose using compact int64 trigger times + searchsorted context timelines."""
    import numpy as np

    from .context_state import context_aligned_ns

    t_ns = np.asarray(trigger_ns, dtype=np.int64)
    prices = np.asarray(trigger_prices, dtype=np.float64)
    out: list[dict[str, Any]] = []
    for i in range(int(t_ns.size)):
        ts = int(t_ns[i])
        if not all(context_aligned_ns(times, codes, ts, trigger_direction) for times, codes in context_timelines):
            continue
        from datetime import datetime, timezone

        iso = datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc).isoformat()
        row_buf: list[dict[str, Any]] = []
        _emit(
            row_buf,
            candidate_id=composite_id,
            signal_time=iso,
            signal_price=float(prices[i]) if i < len(prices) else 0.0,
            direction=trigger_direction,
            decision_tf=decision_tf,
            calculated_at=iso,
            available_at=iso,
        )
        out.extend(row_buf)
    return out
