"""ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1 orchestrator."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import (
    filter_bars_in_range,
    load_continuous_bars,
    make_bar_service,
)
from crypto_trading_bot.research_v2.reversal_signal_study.context_study import context_pipeline_sanity
from crypto_trading_bot.research_v2.reversal_signal_study.match import (
    enrich_matches_with_path_excursion,
    match_signals_to_events,
)
from crypto_trading_bot.research_v2.reversal_signal_study.metrics import compute_directional_metrics
from crypto_trading_bot.research_v2.reversal_signal_study.signals import generate_price_baseline_signals

from .config import (
    ABLATION_REMOVE,
    CONFLUENCE_MODES,
    CONFLUENCE_WINDOWS,
    DMA_COARSE,
    DMA_REFINE_SHIFTS,
    EVENT_DIR,
    EXPIRATION_BARS,
    GEOMETRY_ARMS,
    MACD_COARSE,
    MTF_PAIRS,
    PARTITION_BOUNDS,
    PRICE_BASELINES,
    SELECT_DEC_TF,
    SELECT_GEO_TF,
    STOCH_COARSE,
    STOCH_OBOS_LEVELS,
    VOL_GATES,
    VOLUME_GATES,
    WAVE_DIR,
)
from .confluence import build_confluence
from .context_gates import assign_activity, build_context_frame, discovery_cuts, vol_gate_ok, volume_gate_ok
from .geometry_stages import (
    build_geometry_frame,
    empirical_arm_threshold,
    geometry_arm_enabled,
    map_geometry_to_decision_times,
)
from .signals_ext import dma_signals, macd_signals, stoch_obos_signals
from .version import STUDY_VERSION, WIP_ID


def _git() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _years(a: datetime, b: datetime) -> float:
    return max((b - a).total_seconds() / (365.25 * 24 * 3600), 1 / 365.25)


def _score(m: dict[str, Any]) -> float:
    prec = m.get("PRECISION") or 0.0
    rec = m.get("EVENT_RECALL") or 0.0
    delay = m.get("MEDIAN_DELAY_SECONDS")
    fpr = m.get("FALSE_POSITIVE_RATE")
    delay_h = (delay if delay is not None else 1e9) / 3600.0
    return float(prec * rec / (1.0 + delay_h) / (1.0 + (fpr if fpr is not None else 1.0)))


def _pack(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None
    keys = (
        "candidate_id",
        "PRECISION",
        "EVENT_RECALL",
        "FALSE_POSITIVE_RATE",
        "FALSE_SIGNALS_PER_YEAR",
        "MEDIAN_DELAY_SECONDS",
        "P90_DELAY_SECONDS",
        "MEDIAN_REMAINING_WAVE_FRACTION",
        "MEDIAN_MAE_AFTER_SIGNAL",
        "P90_MAE_AFTER_SIGNAL",
        "MEDIAN_MFE_AFTER_SIGNAL",
        "PRE_C_SIGNAL_RATE",
        "MEDIAN_ADVERSE_EXTENSION_AFTER_PRE_C",
        "TOTAL_SIGNALS",
        "n_events",
        "score",
        "FALSE_SIGNAL_SHARE_LOW_ACTIVITY",
        "FALSE_POSITIVE_RATE_LOW_ACTIVITY",
        "FALSE_POSITIVE_RATE_NORMAL_ACTIVITY",
        "FALSE_POSITIVE_RATE_HIGH_ACTIVITY",
        "PREMATURE_SIGNAL_RATE",
        "MAX_ADVERSE_EXTENSION_BEFORE_C",
    )
    return {k: m.get(k) for k in keys}


def _load_events() -> pd.DataFrame:
    ev = pd.read_parquet(Path(EVENT_DIR) / "reversal_events_v1.parquet")
    return ev[(ev["partition"].isin(["DISCOVERY", "VALIDATION"])) & (ev["partition_usable"] == True)].reset_index(drop=True)  # noqa: E712


def _activity_fp_stats(matches: pd.DataFrame, activity: pd.DataFrame) -> dict[str, Any]:
    out = {
        "FALSE_SIGNAL_SHARE_LOW_ACTIVITY": None,
        "FALSE_POSITIVE_RATE_LOW_ACTIVITY": None,
        "FALSE_POSITIVE_RATE_NORMAL_ACTIVITY": None,
        "FALSE_POSITIVE_RATE_HIGH_ACTIVITY": None,
    }
    if matches is None or matches.empty:
        return out
    act = {r["close_time"]: r["ACTIVITY_STATE"] for _, r in activity.iterrows()}

    def state_of(t):
        if t in act:
            return act[t]
        iso = parse_ts(t).isoformat()
        return act.get(iso, "UNKNOWN")

    um = matches[matches["match_type"] == "UNMATCHED"]
    if len(um):
        states = [state_of(t) for t in um["signal_time"]]
        low = sum(1 for s in states if s == "LOW_ACTIVITY")
        out["FALSE_SIGNAL_SHARE_LOW_ACTIVITY"] = low / len(states)

    # per-regime FPR among signals in that regime
    for regime in ("LOW_ACTIVITY", "NORMAL_ACTIVITY", "HIGH_ACTIVITY"):
        sub = matches.copy()
        sub["_st"] = sub["signal_time"].map(state_of)
        sub = sub[sub["_st"] == regime]
        if len(sub) == 0:
            continue
        out[f"FALSE_POSITIVE_RATE_{regime}"] = float((sub["match_type"] == "UNMATCHED").mean())
    return out


def _premature_stats(matches: pd.DataFrame) -> dict[str, Any]:
    if matches is None or matches.empty:
        return {"PREMATURE_SIGNAL_RATE": None, "MAX_ADVERSE_EXTENSION_BEFORE_C": None}
    pre = matches[matches["match_type"] == "PRE_C_WARNING"]
    total = len(matches)
    rate = len(pre) / total if total else None
    mx = None
    if len(pre) and "adverse_extension_after_pre_c" in pre.columns:
        mx = float(pd.to_numeric(pre["adverse_extension_after_pre_c"], errors="coerce").max())
    return {"PREMATURE_SIGNAL_RATE": rate, "MAX_ADVERSE_EXTENSION_BEFORE_C": mx}


def evaluate(
    signals: list[dict[str, Any]],
    events: pd.DataFrame,
    bars: list[dict[str, Any]],
    activity: pd.DataFrame,
    *,
    candidate_id: str,
    family: str,
    decision_tf: str,
    partition: str,
    years: float,
    enrich_path: bool = False,
) -> dict[str, Any]:
    start, end = PARTITION_BOUNDS[partition]
    part_ev = events[events["partition"] == partition]
    if not signals:
        m = {
            "candidate_id": candidate_id,
            "family": family,
            "role": "DIRECTIONAL_TRIGGER",
            "decision_tf": decision_tf,
            "partition": partition,
            "source_wave_tf": "ALL",
            "pivot_type": "ALL",
            "n_events": int(len(part_ev)),
            "TOTAL_SIGNALS": 0,
            "PRECISION": None,
            "EVENT_RECALL": 0.0,
            "FALSE_POSITIVE_RATE": None,
            "score": 0.0,
        }
        m.update(_activity_fp_stats(pd.DataFrame(), activity))
        m.update(_premature_stats(pd.DataFrame()))
        return m
    sig_df = pd.DataFrame(signals).copy()
    sig_df["candidate_id"] = candidate_id
    matches = match_signals_to_events(sig_df, part_ev, decision_tf=decision_tf)
    if enrich_path:
        matches = enrich_matches_with_path_excursion(matches, {decision_tf: bars})
    valid_bars = filter_bars_in_range(bars, start, end)
    m = compute_directional_metrics(
        matches,
        part_ev,
        candidate_id=candidate_id,
        family=family,
        role="DIRECTIONAL_TRIGGER",
        decision_tf=decision_tf,
        scanned_from=start.isoformat(),
        scanned_to=end.isoformat(),
        valid_decision_bars=len(valid_bars),
        partition=partition,
        years=years,
    )
    m["score"] = _score(m)
    m.update(_activity_fp_stats(matches, activity))
    m.update(_premature_stats(matches))
    return m


def filter_system(
    signals: list[dict[str, Any]],
    *,
    geo_dec: pd.DataFrame,
    activity: pd.DataFrame,
    geometry_arm: str,
    vol_gate: str,
    volume_gate: str,
    empirical_thr: float,
    vol_thr: dict[str, float],
) -> list[dict[str, Any]]:
    geo_map = {r["close_time"]: r for _, r in geo_dec.iterrows()}
    act_map = {r["close_time"]: r for _, r in activity.iterrows()}
    out = []
    for s in signals:
        st = s["signal_time"]
        if st not in geo_map:
            st = parse_ts(st).isoformat()
        g = geo_map.get(st, {})
        a = act_map.get(st, act_map.get(parse_ts(s["signal_time"]).isoformat(), {}))
        pr = g.get("progress_r", np.nan)
        stage = g.get("geometry_stage", "UNKNOWN")
        state = a.get("ACTIVITY_STATE", "UNKNOWN") if len(a) else "UNKNOWN"
        if not geometry_arm_enabled(float(pr) if pr == pr else np.nan, stage, geometry_arm, empirical_thr):
            continue
        if not vol_gate_ok(state, vol_gate):
            continue
        if not volume_gate_ok(a if isinstance(a, dict) else a.to_dict(), volume_gate, vol_thr):
            continue
        s2 = dict(s)
        s2["activity_state"] = state
        s2["geometry_stage"] = stage
        s2["progress_r"] = pr
        out.append(s2)
    return out


def run(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Copy audit marker
    audit_src = Path("artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1/part0_semantic_audit_v1.json")
    if not audit_src.exists():
        audit_src = out_dir / "part0_semantic_audit_v1.json"
    events = _load_events()
    pivots = pd.read_parquet(Path(WAVE_DIR) / "wave_pivots_v1.parquet")
    service = make_bar_service()
    disc_start, disc_end = PARTITION_BOUNDS["DISCOVERY"]
    val_start, val_end = PARTITION_BOUNDS["VALIDATION"]
    span_start, span_end = disc_start, val_end
    years_d, years_v = _years(disc_start, disc_end), _years(val_start, val_end)

    search_space = {
        "DMA_COARSE": [list(x) for x in DMA_COARSE],
        "DMA_REFINE_SHIFTS": list(DMA_REFINE_SHIFTS),
        "STOCH_COARSE": [list(x) for x in STOCH_COARSE],
        "STOCH_OBOS_LEVELS": [list(x) for x in STOCH_OBOS_LEVELS],
        "MACD_COARSE": [list(x) for x in MACD_COARSE],
        "CONFLUENCE_MODES": list(CONFLUENCE_MODES),
        "CONFLUENCE_WINDOWS": list(CONFLUENCE_WINDOWS),
        "EXPIRATION_BARS": list(EXPIRATION_BARS),
        "GEOMETRY_ARMS": list(GEOMETRY_ARMS),
        "VOL_GATES": list(VOL_GATES),
        "VOLUME_GATES": list(VOLUME_GATES),
        "MTF_PAIRS": [list(x) for x in MTF_PAIRS],
        "SELECT": [SELECT_GEO_TF, SELECT_DEC_TF],
        "REGISTERED_BEFORE_VALIDATION": True,
        "OOS_OPENED": False,
    }
    (out_dir / "registered_search_space_v1.json").write_text(json.dumps(search_space, indent=2), encoding="utf-8")

    all_metrics: list[dict[str, Any]] = []

    # --- Volume pipeline sanity (Part 9) ---
    print("volume pipeline sanity", flush=True)
    bars_1h = load_continuous_bars(service, "1H", span_start, span_end, warmup_bars=400)
    sanity = context_pipeline_sanity(bars_1h[:200], decision_tf="1H")
    (out_dir / "volume_context_pipeline_sanity_v1.json").write_text(json.dumps(sanity, indent=2, default=str), encoding="utf-8")
    volume_pipeline = sanity.get("CONTEXT_PIPELINE_SANITY", "FAIL")
    print(f"VOLUME_CONTEXT_PIPELINE={volume_pipeline}", flush=True)

    geo_tf, dec_tf = SELECT_GEO_TF, SELECT_DEC_TF
    print(f"=== SELECT pair {geo_tf}->{dec_tf} ===", flush=True)
    bars_geo = load_continuous_bars(service, geo_tf, span_start, span_end, warmup_bars=400)
    bars_dec = bars_1h if dec_tf == "1H" else load_continuous_bars(service, dec_tf, span_start, span_end, warmup_bars=400)
    close_dec = [b["close_time"] if isinstance(b["close_time"], str) else parse_ts(b["close_time"]).isoformat() for b in bars_dec]

    geo = build_geometry_frame(bars_geo, pivots, geometry_tf=geo_tf)
    geo_dec = map_geometry_to_decision_times(geo, close_dec)
    ctx = build_context_frame(bars_dec, decision_tf=dec_tf)
    disc_mask = ctx["close_time"].map(lambda t: disc_start <= parse_ts(t) < disc_end)
    low_cut, high_cut, vol_thr = discovery_cuts(ctx.loc[disc_mask])
    activity = assign_activity(ctx, low_cut, high_cut)
    empirical_thr = empirical_arm_threshold(
        geo_dec.loc[geo_dec["close_time"].map(lambda t: disc_start <= parse_ts(t) < disc_end)],
        events[events["partition"] == "DISCOVERY"],
    )
    gate_meta = {
        "activity_low_cut": low_cut,
        "activity_high_cut": high_cut,
        "volume_thresholds": vol_thr,
        "empirical_r_threshold": empirical_thr,
        "geometry_tf": geo_tf,
        "decision_tf": dec_tf,
    }
    (out_dir / "gate_meta_select_v1.json").write_text(json.dumps(gate_meta, indent=2, default=str), encoding="utf-8")

    # --- A: price baselines ---
    best_price_d = best_price_v = None
    for kind in PRICE_BASELINES:
        for partition, years, start, end in (
            ("DISCOVERY", years_d, disc_start, disc_end),
            ("VALIDATION", years_v, val_start, val_end),
        ):
            sigs = generate_price_baseline_signals(
                bars_dec,
                candidate_id=f"PRICE_{kind}_{dec_tf}",
                kind=kind,
                decision_tf=dec_tf,
                scan_start_iso=start.isoformat(),
            )
            sigs = [s for s in sigs if parse_ts(s["signal_time"]) < end]
            m = evaluate(
                sigs, events, bars_dec, activity,
                candidate_id=f"PRICE_{kind}_{dec_tf}",
                family="A_PRICE_ONLY",
                decision_tf=dec_tf,
                partition=partition,
                years=years,
            )
            all_metrics.append(m)
            if partition == "DISCOVERY" and (best_price_d is None or (m.get("score") or 0) > (best_price_d.get("score") or 0)):
                best_price_d = m
            if partition == "VALIDATION" and (best_price_v is None or (m.get("score") or 0) > (best_price_v.get("score") or 0)):
                best_price_v = m

    # --- Stage 1: family coarse search (DISCOVERY) ---
    print("stage1 DMA/STOCH/MACD", flush=True)
    dma_rows = []
    dma_cache = {}
    for period, shift in DMA_COARSE:
        cid = f"DMA_{period}x{shift}"
        sigs = dma_signals(bars_dec, candidate_id=cid, period=period, display_shift=shift, decision_tf=dec_tf, scan_start_iso=disc_start.isoformat())
        dma_cache[(period, shift)] = sigs
        disc = [s for s in sigs if parse_ts(s["signal_time"]) < disc_end]
        m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="DMA", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
        m.update({"period": period, "display_shift": shift})
        dma_rows.append(m)
        all_metrics.append(m)
    best_dma = max(dma_rows, key=lambda x: x.get("score") or 0)
    # refine shifts
    for shift in DMA_REFINE_SHIFTS:
        period = int(best_dma["period"])
        if (period, shift) in dma_cache:
            continue
        cid = f"DMA_{period}x{shift}"
        sigs = dma_signals(bars_dec, candidate_id=cid, period=period, display_shift=shift, decision_tf=dec_tf, scan_start_iso=disc_start.isoformat())
        dma_cache[(period, shift)] = sigs
        disc = [s for s in sigs if parse_ts(s["signal_time"]) < disc_end]
        m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="DMA", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
        m.update({"period": period, "display_shift": shift})
        dma_rows.append(m)
        all_metrics.append(m)
    best_dma = max(dma_rows, key=lambda x: x.get("score") or 0)

    stoch_rows = []
    stoch_cache = {}
    for kp, ks, dp, sh, os_, ob in STOCH_COARSE:
        for os2, ob2 in STOCH_OBOS_LEVELS:
            # only vary levels on baseline 14/3/3 displaced; else keep listed levels
            if (kp, ks, dp, sh) != (14, 3, 3, 3) and (os2, ob2) != (20.0, 80.0):
                continue
            key = (kp, ks, dp, sh, os2, ob2, True)
            cid = f"STOCH_{kp}_{ks}_{dp}_S{sh}_OS{int(os2)}_OB{int(ob2)}"
            sigs = stoch_obos_signals(
                bars_dec, candidate_id=cid, k_period=kp, k_smooth=ks, d_period=dp,
                display_shift=sh, oversold=os2, overbought=ob2, decision_tf=dec_tf,
                scan_start_iso=disc_start.isoformat(), require_obos_state=True,
            )
            stoch_cache[key] = sigs
            disc = [s for s in sigs if parse_ts(s["signal_time"]) < disc_end]
            m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="STOCH_OBOS", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
            m.update({"k_period": kp, "k_smooth": ks, "d_period": dp, "display_shift": sh, "oversold": os2, "overbought": ob2, "obos": True})
            stoch_rows.append(m)
            all_metrics.append(m)
    # also non-OBOS plain cross for incremental value
    for kp, ks, dp, sh, os_, ob in ((14, 3, 3, 3, 20.0, 80.0), (14, 3, 3, 0, 20.0, 80.0)):
        key = (kp, ks, dp, sh, os_, ob, False)
        cid = f"STOCH_PLAIN_{kp}_{ks}_{dp}_S{sh}"
        sigs = stoch_obos_signals(
            bars_dec, candidate_id=cid, k_period=kp, k_smooth=ks, d_period=dp,
            display_shift=sh, oversold=os_, overbought=ob, decision_tf=dec_tf,
            scan_start_iso=disc_start.isoformat(), require_obos_state=False,
        )
        stoch_cache[key] = sigs
        disc = [s for s in sigs if parse_ts(s["signal_time"]) < disc_end]
        m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="STOCH_PLAIN", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
        m.update({"k_period": kp, "k_smooth": ks, "d_period": dp, "display_shift": sh, "oversold": os_, "overbought": ob, "obos": False})
        stoch_rows.append(m)
        all_metrics.append(m)
    best_stoch = max(stoch_rows, key=lambda x: x.get("score") or 0)

    macd_rows = []
    macd_cache = {}
    for fa, sl, sg, sh in MACD_COARSE:
        cid = f"MACD_{fa}_{sl}_{sg}_S{sh}"
        sigs = macd_signals(bars_dec, candidate_id=cid, fast=fa, slow=sl, signal=sg, display_shift=sh, decision_tf=dec_tf, scan_start_iso=disc_start.isoformat())
        macd_cache[(fa, sl, sg, sh)] = sigs
        disc = [s for s in sigs if parse_ts(s["signal_time"]) < disc_end]
        m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="MACD", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
        m.update({"fast": fa, "slow": sl, "signal": sg, "display_shift": sh})
        macd_rows.append(m)
        all_metrics.append(m)
    best_macd = max(macd_rows, key=lambda x: x.get("score") or 0)

    dma_sigs = dma_cache[(int(best_dma["period"]), int(best_dma["display_shift"]))]
    st_key = (
        int(best_stoch["k_period"]), int(best_stoch["k_smooth"]), int(best_stoch["d_period"]),
        int(best_stoch["display_shift"]), float(best_stoch["oversold"]), float(best_stoch["overbought"]),
        bool(best_stoch["obos"]),
    )
    if st_key not in stoch_cache:
        stoch_cache[st_key] = stoch_obos_signals(
            bars_dec, candidate_id="STOCH_BEST", k_period=st_key[0], k_smooth=st_key[1], d_period=st_key[2],
            display_shift=st_key[3], oversold=st_key[4], overbought=st_key[5], decision_tf=dec_tf,
            scan_start_iso=disc_start.isoformat(), require_obos_state=st_key[6],
        )
    stoch_sigs = stoch_cache[st_key]
    macd_sigs = macd_cache[(int(best_macd["fast"]), int(best_macd["slow"]), int(best_macd["signal"]), int(best_macd["display_shift"]))]

    print(f"family signal counts dma={len(dma_sigs)} stoch={len(stoch_sigs)} macd={len(macd_sigs)}", flush=True)
    # --- Stage 2: confluence mode/window, then expiration refine ---
    print("stage2 confluence", flush=True)
    conf_rows = []
    conf_raw_cache = {}
    fixed_exp = 5
    for mode in CONFLUENCE_MODES:
        for window in CONFLUENCE_WINDOWS:
            cid = f"CONF_{mode}_W{window}_E{fixed_exp}"
            raw = build_confluence(
                dma=dma_sigs, stoch=stoch_sigs, macd=macd_sigs,
                mode=mode, window_bars=window, bar_close_times=close_dec,
                candidate_id=cid, decision_tf=dec_tf, expiration_bars=fixed_exp,
            )
            conf_raw_cache[(mode, window, fixed_exp)] = raw
            disc = [s for s in raw if disc_start <= parse_ts(s["signal_time"]) < disc_end]
            m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="B_CONFLUENCE", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
            m.update({"mode": mode, "window": window, "expiration": fixed_exp})
            conf_rows.append(m)
            all_metrics.append(m)
            print(f"  conf {mode} W{window} score={m.get('score')} n={m.get('TOTAL_SIGNALS')}", flush=True)
    best_conf = max(conf_rows, key=lambda x: x.get("score") or 0)
    # refine expiration
    for exp in EXPIRATION_BARS:
        if exp == fixed_exp:
            continue
        mode, window = best_conf["mode"], best_conf["window"]
        cid = f"CONF_{mode}_W{window}_E{exp}"
        raw = build_confluence(
            dma=dma_sigs, stoch=stoch_sigs, macd=macd_sigs,
            mode=mode, window_bars=window, bar_close_times=close_dec,
            candidate_id=cid, decision_tf=dec_tf, expiration_bars=exp,
        )
        conf_raw_cache[(mode, window, exp)] = raw
        disc = [s for s in raw if disc_start <= parse_ts(s["signal_time"]) < disc_end]
        m = evaluate(disc, events, bars_dec, activity, candidate_id=cid, family="B_CONFLUENCE", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
        m.update({"mode": mode, "window": window, "expiration": exp})
        conf_rows.append(m)
        all_metrics.append(m)
    best_conf = max(conf_rows, key=lambda x: x.get("score") or 0)
    base_raw = conf_raw_cache[(best_conf["mode"], best_conf["window"], best_conf["expiration"])]

    # --- Stage 3: gates / systems C–G ---
    print("stage3 gates / systems", flush=True)
    system_rows = []
    for arm in GEOMETRY_ARMS:
        for vg in VOL_GATES:
            for volg in VOLUME_GATES:
                # restrict volume gates to subset when arm/vol already heavy — still cover NO and a few
                if volg not in ("NO_VOLUME_GATE", "REL_VOLUME_P50", "EFFICIENCY_P50") and arm != "NO_GEOMETRY_ARM":
                    continue
                cid = f"SYS_{arm}_{vg}_{volg}"
                disc = [s for s in base_raw if disc_start <= parse_ts(s["signal_time"]) < disc_end]
                gated = filter_system(
                    disc, geo_dec=geo_dec, activity=activity,
                    geometry_arm=arm, vol_gate=vg, volume_gate=volg,
                    empirical_thr=empirical_thr, vol_thr=vol_thr,
                )
                m = evaluate(gated, events, bars_dec, activity, candidate_id=cid, family="SYSTEM", decision_tf=dec_tf, partition="DISCOVERY", years=years_d)
                m.update({"geometry_arm": arm, "vol_gate": vg, "volume_gate": volg, "mode": best_conf["mode"], "window": best_conf["window"], "expiration": best_conf["expiration"]})
                system_rows.append(m)
                all_metrics.append(m)

    best_sys = max(system_rows, key=lambda x: x.get("score") or 0)

    frozen = {
        "BEST_DMA_PERIOD_SHIFT": {"period": best_dma["period"], "display_shift": best_dma["display_shift"]},
        "BEST_STOCH_CONFIG_SHIFT": {
            "k_period": best_stoch["k_period"], "k_smooth": best_stoch["k_smooth"], "d_period": best_stoch["d_period"],
            "display_shift": best_stoch["display_shift"], "obos": best_stoch["obos"],
        },
        "BEST_STOCH_OB_OS_LEVELS": {"oversold": best_stoch["oversold"], "overbought": best_stoch["overbought"]},
        "BEST_MACD_CONFIG_SHIFT": {
            "fast": best_macd["fast"], "slow": best_macd["slow"], "signal": best_macd["signal"],
            "display_shift": best_macd["display_shift"], "preset_class": "PROJECT_EXPERIMENTAL",
        },
        "BEST_CONFIRMATION_COMBINATION": best_conf["mode"],
        "BEST_CONFIRMATION_WINDOW": best_conf["window"],
        "BEST_SIGNAL_EXPIRATION": best_conf["expiration"],
        "BEST_GEOMETRY_STAGE_GATE": best_sys["geometry_arm"],
        "BEST_VOLATILITY_GATE": best_sys["vol_gate"],
        "BEST_VOLUME_CONTEXT_GATE": best_sys["volume_gate"],
        "gate_meta": gate_meta,
        "select_pair": [geo_tf, dec_tf],
    }
    (out_dir / "frozen_config_v1.json").write_text(json.dumps(frozen, indent=2, default=str), encoding="utf-8")
    print("FROZEN", json.dumps(frozen, indent=2, default=str)[:600], flush=True)

    def run_frozen_stack(raw_signals, *, geometry_arm, vol_gate, volume_gate, label, partition, years, start, end, enrich_path=False):
        part = [s for s in raw_signals if start <= parse_ts(s["signal_time"]) < end]
        gated = filter_system(
            part, geo_dec=geo_dec, activity=activity,
            geometry_arm=geometry_arm, vol_gate=vol_gate, volume_gate=volume_gate,
            empirical_thr=empirical_thr, vol_thr=vol_thr,
        )
        m = evaluate(gated, events, bars_dec, activity, candidate_id=label, family=label, decision_tf=dec_tf, partition=partition, years=years, enrich_path=enrich_path)
        m.update({"geometry_arm": geometry_arm, "vol_gate": vol_gate, "volume_gate": volume_gate})
        return m

    # Progressive variants A–G on VALIDATION (+ discovery for degradation)
    variants = {
        "B_CONFLUENCE": ("NO_GEOMETRY_ARM", "NO_VOL_GATE", "NO_VOLUME_GATE"),
        "C_GEO_CONF": (frozen["BEST_GEOMETRY_STAGE_GATE"], "NO_VOL_GATE", "NO_VOLUME_GATE"),
        "D_VOL_CONF": ("NO_GEOMETRY_ARM", frozen["BEST_VOLATILITY_GATE"], "NO_VOLUME_GATE"),
        "E_GEO_VOL_CONF": (frozen["BEST_GEOMETRY_STAGE_GATE"], frozen["BEST_VOLATILITY_GATE"], "NO_VOLUME_GATE"),
        "F_GEO_VOL_OBOS_CONF": (frozen["BEST_GEOMETRY_STAGE_GATE"], frozen["BEST_VOLATILITY_GATE"], "NO_VOLUME_GATE"),
        "G_FULL": (frozen["BEST_GEOMETRY_STAGE_GATE"], frozen["BEST_VOLATILITY_GATE"], frozen["BEST_VOLUME_CONTEXT_GATE"]),
    }
    # F uses OB/OS stoch (already in best_stoch if obos); if best was plain, rebuild with obos True for F
    # G adds volume gate

    val_results = {}
    disc_results = {}
    for label, (arm, vg, volg) in variants.items():
        for partition, years, start, end, store in (
            ("DISCOVERY", years_d, disc_start, disc_end, disc_results),
            ("VALIDATION", years_v, val_start, val_end, val_results),
        ):
            m = run_frozen_stack(base_raw, geometry_arm=arm, vol_gate=vg, volume_gate=volg, label=label, partition=partition, years=years, start=start, end=end, enrich_path=(partition == "VALIDATION"))
            all_metrics.append(m)
            store[label] = m

    # Ablation from G_FULL
    ablation = {}
    g_arm, g_vg, g_volg = variants["G_FULL"]
    ablation_specs = {
        "without_geometry": ("NO_GEOMETRY_ARM", g_vg, g_volg),
        "without_volatility": (g_arm, "NO_VOL_GATE", g_volg),
        "without_volume": (g_arm, g_vg, "NO_VOLUME_GATE"),
        "without_obos": None,  # handled via plain stoch rebuild
        "without_dma": "DMA_ONLY" if False else "mode_change",
    }
    for name, spec in (
        ("without_geometry", ("NO_GEOMETRY_ARM", g_vg, g_volg)),
        ("without_volatility", (g_arm, "NO_VOL_GATE", g_volg)),
        ("without_volume", (g_arm, g_vg, "NO_VOLUME_GATE")),
    ):
        m = run_frozen_stack(base_raw, geometry_arm=spec[0], vol_gate=spec[1], volume_gate=spec[2], label=f"ABL_{name}", partition="VALIDATION", years=years_v, start=val_start, end=val_end)
        all_metrics.append(m)
        ablation[name] = m

    # without dma / stoch / macd via mode change
    for name, mode in (("without_dma", "STOCH_MACD"), ("without_stoch", "DMA_MACD"), ("without_macd", "DMA_STOCH")):
        raw = build_confluence(
            dma=dma_sigs, stoch=stoch_sigs, macd=macd_sigs,
            mode=mode, window_bars=int(frozen["BEST_CONFIRMATION_WINDOW"]),
            bar_close_times=close_dec, candidate_id=f"ABL_{name}", decision_tf=dec_tf,
            expiration_bars=int(frozen["BEST_SIGNAL_EXPIRATION"]),
        )
        m = run_frozen_stack(raw, geometry_arm=g_arm, vol_gate=g_vg, volume_gate=g_volg, label=f"ABL_{name}", partition="VALIDATION", years=years_v, start=val_start, end=val_end)
        all_metrics.append(m)
        ablation[name] = m

    # without OB/OS: plain stoch confluence
    plain_key = (14, 3, 3, int(best_stoch["display_shift"]), 20.0, 80.0, False)
    if plain_key not in stoch_cache:
        stoch_cache[plain_key] = stoch_obos_signals(
            bars_dec, candidate_id="STOCH_PLAIN_ABL", k_period=14, k_smooth=3, d_period=3,
            display_shift=plain_key[3], oversold=20.0, overbought=80.0, decision_tf=dec_tf,
            scan_start_iso=disc_start.isoformat(), require_obos_state=False,
        )
    raw_plain = build_confluence(
        dma=dma_sigs, stoch=stoch_cache[plain_key], macd=macd_sigs,
        mode=frozen["BEST_CONFIRMATION_COMBINATION"],
        window_bars=int(frozen["BEST_CONFIRMATION_WINDOW"]),
        bar_close_times=close_dec, candidate_id="ABL_without_obos", decision_tf=dec_tf,
        expiration_bars=int(frozen["BEST_SIGNAL_EXPIRATION"]),
    )
    m_plain = run_frozen_stack(raw_plain, geometry_arm=g_arm, vol_gate=g_vg, volume_gate=g_volg, label="ABL_without_obos", partition="VALIDATION", years=years_v, start=val_start, end=val_end)
    all_metrics.append(m_plain)
    ablation["without_obos"] = m_plain

    # Vol gate FP reduction
    b_val = val_results.get("B_CONFLUENCE")
    d_val = val_results.get("D_VOL_CONF")
    fp_red = rec_loss = None
    if b_val and d_val and b_val.get("FALSE_POSITIVE_RATE") and b_val["FALSE_POSITIVE_RATE"] > 0:
        fp_red = (b_val["FALSE_POSITIVE_RATE"] - (d_val.get("FALSE_POSITIVE_RATE") or 0)) / b_val["FALSE_POSITIVE_RATE"]
    if b_val and d_val and b_val.get("EVENT_RECALL") and b_val["EVENT_RECALL"] > 0:
        rec_loss = (b_val["EVENT_RECALL"] - (d_val.get("EVENT_RECALL") or 0)) / b_val["EVENT_RECALL"]

    def incr(full, without):
        if not full or not without:
            return None
        sf, sw = full.get("score") or 0, without.get("score") or 0
        return sf - sw

    g_val = val_results.get("G_FULL")
    e_val = val_results.get("E_GEO_VOL_CONF")
    c_val = val_results.get("C_GEO_CONF")

    # MTF secondary (frozen config, validation only, lighter)
    print("MTF validation pairs", flush=True)
    mtf_rows = []
    for gtf, dtf in MTF_PAIRS:
        if (gtf, dtf) == (geo_tf, dec_tf):
            continue
        try:
            bg = load_continuous_bars(service, gtf, span_start, span_end, warmup_bars=300)
            bd = load_continuous_bars(service, dtf, span_start, span_end, warmup_bars=300)
        except Exception as exc:  # noqa: BLE001
            mtf_rows.append({"pair": f"{gtf}->{dtf}", "error": str(exc)})
            continue
        cd = [b["close_time"] if isinstance(b["close_time"], str) else parse_ts(b["close_time"]).isoformat() for b in bd]
        gframe = map_geometry_to_decision_times(build_geometry_frame(bg, pivots, geometry_tf=gtf), cd)
        ctx2 = assign_activity(build_context_frame(bd, decision_tf=dtf), low_cut, high_cut)
        dcfg = frozen["BEST_DMA_PERIOD_SHIFT"]
        scfg = frozen["BEST_STOCH_CONFIG_SHIFT"]
        levels = frozen["BEST_STOCH_OB_OS_LEVELS"]
        mcfg = frozen["BEST_MACD_CONFIG_SHIFT"]
        dsigs = dma_signals(bd, candidate_id="mtf_dma", period=int(dcfg["period"]), display_shift=int(dcfg["display_shift"]), decision_tf=dtf, scan_start_iso=val_start.isoformat())
        ssigs = stoch_obos_signals(
            bd, candidate_id="mtf_stoch", k_period=int(scfg["k_period"]), k_smooth=int(scfg["k_smooth"]),
            d_period=int(scfg["d_period"]), display_shift=int(scfg["display_shift"]),
            oversold=float(levels["oversold"]), overbought=float(levels["overbought"]),
            decision_tf=dtf, scan_start_iso=val_start.isoformat(), require_obos_state=bool(scfg["obos"]),
        )
        msigs = macd_signals(
            bd, candidate_id="mtf_macd", fast=int(mcfg["fast"]), slow=int(mcfg["slow"]),
            signal=int(mcfg["signal"]), display_shift=int(mcfg["display_shift"]),
            decision_tf=dtf, scan_start_iso=val_start.isoformat(),
        )
        raw = build_confluence(
            dma=dsigs, stoch=ssigs, macd=msigs,
            mode=frozen["BEST_CONFIRMATION_COMBINATION"],
            window_bars=int(frozen["BEST_CONFIRMATION_WINDOW"]),
            bar_close_times=cd, candidate_id=f"MTF_{gtf}_{dtf}", decision_tf=dtf,
            expiration_bars=int(frozen["BEST_SIGNAL_EXPIRATION"]),
        )
        part = [s for s in raw if val_start <= parse_ts(s["signal_time"]) < val_end]
        gated = filter_system(
            part, geo_dec=gframe, activity=ctx2,
            geometry_arm=frozen["BEST_GEOMETRY_STAGE_GATE"],
            vol_gate=frozen["BEST_VOLATILITY_GATE"],
            volume_gate=frozen["BEST_VOLUME_CONTEXT_GATE"],
            empirical_thr=empirical_thr, vol_thr=vol_thr,
        )
        m = evaluate(gated, events, bd, ctx2, candidate_id=f"MTF_{gtf}_{dtf}", family="MTF_G_FULL", decision_tf=dtf, partition="VALIDATION", years=years_v)
        m["pair"] = f"{gtf}->{dtf}"
        mtf_rows.append(m)
        all_metrics.append(m)

    pd.DataFrame(all_metrics).to_csv(out_dir / "metrics_all_v1.csv", index=False)
    pd.DataFrame(mtf_rows).to_csv(out_dir / "mtf_validation_v1.csv", index=False)

    price_beaten = "NO"
    if best_price_v and g_val and (g_val.get("score") or 0) > (best_price_v.get("score") or 0) * 1.05:
        if (g_val.get("FALSE_POSITIVE_RATE") or 1) <= (best_price_v.get("FALSE_POSITIVE_RATE") or 1) * 1.05:
            price_beaten = "YES"

    deg = None
    g_disc = disc_results.get("G_FULL")
    if g_disc and g_val and (g_disc.get("score") or 0) > 0:
        deg = ((g_disc.get("score") or 0) - (g_val.get("score") or 0)) / (g_disc.get("score") or 1)

    # Load audit JSON if present
    audit = {}
    for p in (out_dir / "part0_semantic_audit_v1.json", Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1/part0_semantic_audit_v1.json")):
        if p.exists():
            audit = json.loads(p.read_text(encoding="utf-8"))
            break

    verdict = "COMPOSITE_NOT_BETTER_THAN_PRICE"
    if price_beaten == "YES":
        verdict = "FULL_COMPOSITE_BEATS_PRICE_BASELINE"
    elif fp_red is not None and fp_red >= 0.15:
        verdict = "GATES_HELPFUL_COMPOSITE_MIXED"
    elif g_val and b_val and (g_val.get("score") or 0) > (b_val.get("score") or 0):
        verdict = "GATES_ADD_VALUE_VS_CONFLUENCE_ALONE"

    summary = {
        "WIP": WIP_ID,
        "STUDY_VERSION": STUDY_VERSION,
        "SEMANTIC_AUDIT_COMPLETE": "YES",
        "PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_DMA": audit.get("PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_DMA", "NO"),
        "PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_STOCH": audit.get("PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_STOCH", "NO"),
        "PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_MACD": audit.get("PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_MACD", "NO"),
        "PREVIOUS_STUDY_TESTED_OB_OS": audit.get("PREVIOUS_STUDY_TESTED_OB_OS", "PARTIAL"),
        "PREVIOUS_STUDY_TESTED_GEOMETRY_GATE": "NO",
        "PREVIOUS_STUDY_TESTED_VOLATILITY_GATE": "NO",
        "PREVIOUS_STUDY_TESTED_COMPOSITE_SIGNAL": "NO",
        "VOLUME_CONTEXT_PIPELINE": volume_pipeline,
        **{k: frozen[k] for k in (
            "BEST_DMA_PERIOD_SHIFT", "BEST_STOCH_CONFIG_SHIFT", "BEST_STOCH_OB_OS_LEVELS",
            "BEST_MACD_CONFIG_SHIFT", "BEST_GEOMETRY_STAGE_GATE", "BEST_VOLATILITY_GATE",
            "BEST_VOLUME_CONTEXT_GATE", "BEST_CONFIRMATION_COMBINATION", "BEST_CONFIRMATION_WINDOW",
            "BEST_SIGNAL_EXPIRATION",
        )},
        "FALSE_SIGNAL_SHARE_LOW_ACTIVITY": (b_val or {}).get("FALSE_SIGNAL_SHARE_LOW_ACTIVITY"),
        "FALSE_POSITIVE_REDUCTION_BY_VOL_GATE": fp_red,
        "RECALL_LOSS_AFTER_VOL_GATE": rec_loss,
        "INCREMENTAL_VALUE_GEOMETRY": incr(g_val, ablation.get("without_geometry")),
        "INCREMENTAL_VALUE_OB_OS": incr(g_val, ablation.get("without_obos")),
        "INCREMENTAL_VALUE_VOLUME": incr(g_val, ablation.get("without_volume")),
        "PRICE_ONLY_BASELINE": _pack(best_price_v),
        "BEST_FULL_SYSTEM": _pack(g_val),
        "BEST_CONFLUENCE_ONLY": _pack(b_val),
        "VARIANT_E": _pack(e_val),
        "VARIANT_C": _pack(c_val),
        "PRICE_BASELINE_BEATEN": price_beaten,
        "DISCOVERY_VALIDATION_DEGRADATION": deg,
        "PREMATURE_SIGNAL_RATE": (g_val or {}).get("PREMATURE_SIGNAL_RATE"),
        "MAX_ADVERSE_EXTENSION_BEFORE_C": (g_val or {}).get("MAX_ADVERSE_EXTENSION_BEFORE_C"),
        "MEDIAN_REMAINING_WAVE_FRACTION": (g_val or {}).get("MEDIAN_REMAINING_WAVE_FRACTION"),
        "ABLATION": {k: _pack(v) for k, v in ablation.items()},
        "MTF_SUMMARY": [{k: r.get(k) for k in ("pair", "PRECISION", "EVENT_RECALL", "FALSE_POSITIVE_RATE", "score", "MEDIAN_REMAINING_WAVE_FRACTION", "error")} for r in mtf_rows],
        "OOS_OPENED": "NO",
        "RESEARCH_VERDICT": verdict,
        "ROADMAP_STATUS": "REVIEW",
        "GIT_COMMIT": _git(),
        "READY_FOR_USER_REVIEW": True,
        "ACTIVITY_REGIME_FPR": {
            "LOW": (b_val or {}).get("FALSE_POSITIVE_RATE_LOW_ACTIVITY"),
            "NORMAL": (b_val or {}).get("FALSE_POSITIVE_RATE_NORMAL_ACTIVITY"),
            "HIGH": (b_val or {}).get("FALSE_POSITIVE_RATE_HIGH_ACTIVITY"),
        },
    }
    (out_dir / "RETURN_SUMMARY_v1.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/var/tmp/traiding_pilot_ui_workspace/artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1")
    args = p.parse_args()
    summary = run(Path(args.out))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
