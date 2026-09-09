"""Bounded composite finalization (post full-compose; DEVELOPMENT-only)."""
from __future__ import annotations

import gc
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .classify import (
    CANONICAL_SELECTIVE_CLASS,
    SURVIVOR_CLASSES,
    is_survivor_class,
    normalize_class_name,
)
from .config import load_atomic_bank
from .memory_guard import COMPOSITE_CHECKPOINT, FOLDS_PARTS_DIR, RESULTS_PARTS_DIR, read_rss_bytes, save_json
from .survivor_store import SURVIVOR_STREAM_DIR, SurvivorStreamStore

EXPECTED_ENUM_SHA = "397533c24eb48bd7e0c1f18dedc4d94393c5965107cc6165eb59ecad592f7b3e"
EXPECTED_TOTAL = 200829
COMPOSITE_REDUNDANCY_THRESHOLD = 0.95
COMPOSITE_FDR_STATUS = "NOT_USED"


class FinalizationGateError(RuntimeError):
    """Raised when production finalization is not allowed."""


def assert_finalization_allowed(artifact_root: Path, *, allow_partial_test: bool = False) -> dict[str, Any]:
    """
    Finalization may run ONLY when production full compose completed exactly.
    Test/dry mode sets allow_partial_test=True.
    """
    root = Path(artifact_root)
    if allow_partial_test:
        return {"FINALIZATION_ALLOWED": "YES", "mode": "DRY_TEST"}

    ckpt_path = root / COMPOSITE_CHECKPOINT
    enum_path = root / "composite_enumeration_authority_v1.json"
    if not ckpt_path.exists():
        raise FinalizationGateError("FINALIZATION_ALLOWED=NO — production checkpoint missing")
    if not enum_path.exists():
        raise FinalizationGateError("FINALIZATION_ALLOWED=NO — enumeration authority missing")
    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    enum_auth = json.loads(enum_path.read_text(encoding="utf-8"))
    enum_sha = ckpt.get("COMPOSITE_ENUMERATION_SHA256") or enum_auth.get("COMPOSITE_ENUMERATION_SHA256")
    total = int(ckpt.get("TOTAL_COMPOSITE_CANDIDATE_COUNT") or enum_auth.get("TOTAL_COMPOSITE_CANDIDATE_COUNT") or -1)
    completed = int(ckpt.get("completed_count") or -1)
    next_idx = int(ckpt.get("next_candidate_index") or -1)
    if enum_sha != EXPECTED_ENUM_SHA:
        raise FinalizationGateError("FINALIZATION_ALLOWED=NO — enumeration SHA mismatch")
    if total != EXPECTED_TOTAL or completed != EXPECTED_TOTAL or next_idx != EXPECTED_TOTAL:
        raise FinalizationGateError(
            f"FINALIZATION_ALLOWED=NO — incomplete compose completed={completed} next={next_idx} total={total}"
        )
    status_path = root / "bounded_compose_run_status_v1.json"
    if status_path.exists():
        st = json.loads(status_path.read_text(encoding="utf-8"))
        if st.get("memory_guard_stop"):
            raise FinalizationGateError("FINALIZATION_ALLOWED=NO — memory_guard_stop=true")
    return {
        "FINALIZATION_ALLOWED": "YES",
        "completed_count": completed,
        "next_candidate_index": next_idx,
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": total,
        "COMPOSITE_ENUMERATION_SHA256": enum_sha,
    }


def iter_parquet_parts(parts_dir: Path, *, batch_rows: int = 50_000) -> Iterator[pd.DataFrame]:
    """Streaming part reader — never materializes all parts as one DataFrame."""
    parts_dir = Path(parts_dir)
    if not parts_dir.exists():
        return
    for path in sorted(parts_dir.glob("part-*.parquet")):
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=batch_rows):
            yield batch.to_pandas()


def assemble_results_bounded(
    root: Path,
    *,
    out_prefix: str = "composite_results_all_v1",
) -> dict[str, Any]:
    """
    FINAL_RESULT_ASSEMBLY_BOUNDED=YES
    Write parquet+csv by appending batches; folds similarly.
    """
    root = Path(root)
    peak = read_rss_bytes() / (1024**3)
    writer = None
    n_rows = 0
    out_parquet = root / f"{out_prefix}.parquet"
    out_csv = root / f"{out_prefix}.csv"
    if out_csv.exists():
        out_csv.unlink()
    first_csv = True
    schema = None
    for batch in iter_parquet_parts(root / RESULTS_PARTS_DIR):
        peak = max(peak, read_rss_bytes() / (1024**3))
        if "composite_class" in batch.columns:
            batch = batch.copy()
            batch["composite_class"] = batch["composite_class"].map(normalize_class_name)
        n_rows += len(batch)
        table = __import__("pyarrow").Table.from_pandas(batch, preserve_index=False)
        if writer is None:
            import pyarrow.parquet as pq_w

            writer = pq_w.ParquetWriter(out_parquet, table.schema)
            schema = table.schema
        writer.write_table(table)
        batch.to_csv(out_csv, mode="w" if first_csv else "a", header=first_csv, index=False)
        first_csv = False
        del batch, table
        gc.collect()
    if writer is not None:
        writer.close()
    elif not out_parquet.exists():
        pd.DataFrame().to_parquet(out_parquet, index=False)
        pd.DataFrame().to_csv(out_csv, index=False)

    fold_out = root / "composite_fold_stability_v1.csv"
    first_fold = True
    n_folds = 0
    if fold_out.exists():
        fold_out.unlink()
    for batch in iter_parquet_parts(root / FOLDS_PARTS_DIR):
        peak = max(peak, read_rss_bytes() / (1024**3))
        n_folds += len(batch)
        batch.to_csv(fold_out, mode="w" if first_fold else "a", header=first_fold, index=False)
        first_fold = False
        del batch
        gc.collect()
    if first_fold:
        pd.DataFrame().to_csv(fold_out, index=False)

    return {
        "FINAL_RESULT_ASSEMBLY_BOUNDED": "YES",
        "n_result_rows": n_rows,
        "n_fold_rows": n_folds,
        "FINAL_RESULT_ASSEMBLY_PEAK_RSS_GB": peak,
        "results_parquet": str(out_parquet),
        "results_csv": str(out_csv),
        "folds_csv": str(fold_out),
        "schema_fields": None if schema is None else list(schema.names),
    }


def exact_duplicate_clusters(results_csv: Path, out_csv: Path) -> dict[str, Any]:
    """Cluster by COMPOSITE_STREAM_SHA256; representative = lex smallest composite_id."""
    clusters: dict[str, list[str]] = defaultdict(list)
    # Stream CSV in chunks
    for chunk in pd.read_csv(results_csv, chunksize=20_000):
        if "COMPOSITE_STREAM_SHA256" not in chunk.columns:
            continue
        for sha, sub in chunk.groupby("COMPOSITE_STREAM_SHA256", sort=False):
            clusters[str(sha)].extend(sub["composite_id"].astype(str).tolist())
    rows = []
    dup_count = 0
    cluster_count = 0
    for sha, members in sorted(clusters.items(), key=lambda x: x[0]):
        uniq = sorted(set(members))
        if len(uniq) <= 1:
            continue
        cluster_count += 1
        dup_count += len(uniq) - 1
        rep = uniq[0]  # lexicographically smallest
        rows.append(
            {
                "COMPOSITE_STREAM_SHA256": sha,
                "cluster_size": len(uniq),
                "representative_composite_id": rep,
                "alias_composite_ids": "|".join(u for u in uniq if u != rep),
                "members": "|".join(uniq),
            }
        )
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return {
        "COMPOSITE_EXACT_DUPLICATE_COUNT": dup_count,
        "COMPOSITE_EXACT_DUPLICATE_CLUSTER_COUNT": cluster_count,
        "path": str(out_csv),
    }


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _min_fold_precision_delta(fold_df: pd.DataFrame, cid: str) -> float:
    sub = fold_df[fold_df["composite_id"] == cid]
    if sub.empty or "PRECISION_DELTA_VS_TRIGGER" not in sub.columns:
        return float("-inf")
    vals = pd.to_numeric(sub["PRECISION_DELTA_VS_TRIGGER"], errors="coerce")
    if vals.isna().all():
        return float("-inf")
    return float(vals.min())


def _near_rep_key(row: pd.Series, fold_df: pd.DataFrame) -> tuple:
    """
    Near-duplicate cluster representative (predeclared):
    highest minimum fold PRECISION_DELTA_VS_TRIGGER,
    then higher RECALL_RETENTION_VS_TRIGGER,
    then lower FPR_DELTA_VS_TRIGGER,
    then higher TOTAL_SIGNALS,
    then composite_id lexical.
    """
    cid = str(row["composite_id"])
    min_fold = _min_fold_precision_delta(fold_df, cid)
    recall = row.get("RECALL_RETENTION_VS_TRIGGER")
    fpr = row.get("FPR_DELTA_VS_TRIGGER")
    signals = row.get("TOTAL_SIGNALS")
    recall_v = float(recall) if pd.notna(recall) else float("-inf")
    fpr_v = float(fpr) if pd.notna(fpr) else float("inf")
    sig_v = int(signals) if pd.notna(signals) else -1
    # Sort descending on first three metrics via negation where needed.
    return (min_fold, recall_v, -fpr_v, sig_v, cid)


def near_redundancy_survivors(
    root: Path,
    survivors: pd.DataFrame,
    fold_df: pd.DataFrame,
    *,
    threshold: float = COMPOSITE_REDUNDANCY_THRESHOLD,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, list[str]]]:
    """
    Blockwise Jaccard on disk-backed survivor streams by (direction, decision_tf).
    Returns redundancy CSV frame, exact/near alias maps.
    """
    store = SurvivorStreamStore(root)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    meta = {str(r.composite_id): r for r in survivors.itertuples(index=False)}
    for cid in survivors["composite_id"].astype(str):
        row = survivors.loc[survivors["composite_id"].astype(str) == cid].iloc[0]
        groups[(str(row["direction"]), str(row["decision_tf"]))].append(cid)

    cluster_rows: list[dict[str, Any]] = []
    replace: dict[str, str] = {}
    aliases: dict[str, list[str]] = defaultdict(list)
    cluster_id = 0
    for (direction, tf), ids in sorted(groups.items()):
        # Load only this block's timestamp sets.
        sets: dict[str, set[int]] = {}
        for cid in ids:
            try:
                ns = store.load_ns(cid)
                sets[cid] = set(int(x) for x in ns.tolist())
            except KeyError:
                sets[cid] = set()
        used: set[str] = set()
        for cid in sorted(ids):
            if cid in used:
                continue
            members = [cid]
            used.add(cid)
            for other in sorted(ids):
                if other in used:
                    continue
                if _jaccard(sets[cid], sets[other]) >= threshold:
                    members.append(other)
                    used.add(other)
            member_rows = survivors[survivors["composite_id"].astype(str).isin(members)]
            ranked = sorted(
                (r for _, r in member_rows.iterrows()),
                key=lambda r: _near_rep_key(r, fold_df),
                reverse=True,
            )
            rep = str(ranked[0]["composite_id"])
            for m in members:
                if m != rep:
                    replace[m] = rep
                    aliases[rep].append(m)
            if len(members) > 1:
                cluster_rows.append(
                    {
                        "redundancy_cluster_id": f"NR-{cluster_id:06d}",
                        "direction": direction,
                        "decision_tf": tf,
                        "size": len(members),
                        "jaccard_threshold": threshold,
                        "representative_composite_id": rep,
                        "alias_composite_ids": "|".join(sorted(m for m in members if m != rep)),
                        "members": "|".join(sorted(members)),
                        "COMPOSITE_REDUNDANCY_METHOD": "EVENT_STREAM_JACCARD",
                    }
                )
                cluster_id += 1
        del sets
        gc.collect()

    rdf = pd.DataFrame(cluster_rows)
    return rdf, replace, dict(aliases)


def build_survivor_banks(
    root: Path,
    results: pd.DataFrame,
    fold_df: pd.DataFrame,
    *,
    exact_clusters: pd.DataFrame,
    near_df: pd.DataFrame,
    near_replace: dict[str, str],
    near_aliases: dict[str, list[str]],
    config_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    survivors = results[results["composite_class"].map(is_survivor_class)].copy()
    survivors["composite_class"] = survivors["composite_class"].map(normalize_class_name)

    # Exact duplicate: map aliases -> lex smallest rep
    exact_replace: dict[str, str] = {}
    exact_aliases: dict[str, list[str]] = defaultdict(list)
    if not exact_clusters.empty:
        for _, row in exact_clusters.iterrows():
            rep = str(row["representative_composite_id"])
            for alias in str(row.get("alias_composite_ids") or "").split("|"):
                if alias:
                    exact_replace[alias] = rep
                    exact_aliases[rep].append(alias)

    def enrich(row: pd.Series, *, cluster_id: str | None, aliases: list[str]) -> dict[str, Any]:
        trig = config_by_id.get(str(row["trigger_candidate_id"]), {})
        ctx_ids = [x for x in str(row.get("context_candidate_ids") or "").split("|") if x]
        ctx_families = [config_by_id.get(c, {}).get("family") for c in ctx_ids]
        return {
            "composite_id": str(row["composite_id"]),
            "template_id": row.get("template_id"),
            "direction": row.get("direction"),
            "decision_tf": row.get("decision_tf"),
            "trigger_candidate_id": row.get("trigger_candidate_id"),
            "context_candidate_ids": ctx_ids,
            "trigger_family": trig.get("family"),
            "context_families": ctx_families,
            "tf_roles": {
                "trigger_tf": trig.get("decision_tf") or row.get("decision_tf"),
                "context_tfs": [config_by_id.get(c, {}).get("decision_tf") for c in ctx_ids],
            },
            "TOTAL_SIGNALS": row.get("TOTAL_SIGNALS"),
            "PRECISION": row.get("PRECISION"),
            "EVENT_RECALL": row.get("EVENT_RECALL"),
            "FALSE_POSITIVE_RATE": row.get("FALSE_POSITIVE_RATE"),
            "PRECISION_DELTA_VS_TRIGGER": row.get("PRECISION_DELTA_VS_TRIGGER"),
            "PRECISION_DELTA_VS_PRICE_BASELINE": row.get("PRECISION_DELTA_VS_PRICE_BASELINE"),
            "RECALL_RETENTION_VS_TRIGGER": row.get("RECALL_RETENTION_VS_TRIGGER"),
            "FPR_DELTA_VS_TRIGGER": row.get("FPR_DELTA_VS_TRIGGER"),
            "SIGNAL_RETENTION": row.get("SIGNAL_RETENTION"),
            "MEDIAN_DELAY_DELTA_VS_TRIGGER": row.get("MEDIAN_DELAY_DELTA_VS_TRIGGER"),
            "PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER": row.get("PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER"),
            "MEDIAN_MAE_AFTER_SIGNAL": row.get("MEDIAN_MAE_AFTER_SIGNAL"),
            "MEDIAN_MFE_AFTER_SIGNAL": row.get("MEDIAN_MFE_AFTER_SIGNAL"),
            "usable_folds": row.get("usable_folds"),
            "positive_delta_folds": row.get("positive_delta_folds"),
            "sample_flag": row.get("sample_flag"),
            "composite_class": normalize_class_name(str(row.get("composite_class"))),
            "COMPOSITE_STREAM_SHA256": row.get("COMPOSITE_STREAM_SHA256"),
            "redundancy_cluster_id": cluster_id,
            "alias_composite_ids": aliases,
        }

    raw_entries = [enrich(r, cluster_id=None, aliases=[]) for _, r in survivors.iterrows()]
    raw_ids = sorted(e["composite_id"] for e in raw_entries)
    raw_hash = hashlib.sha256(json.dumps(raw_ids, separators=(",", ":")).encode()).hexdigest()

    # Model bank: drop exact+near aliases; keep reps
    drop = set(exact_replace) | set(near_replace)
    model_survivors = survivors[~survivors["composite_id"].astype(str).isin(drop)].copy()

    # cluster id lookup for reps
    cluster_for: dict[str, str] = {}
    if not near_df.empty:
        for _, row in near_df.iterrows():
            cluster_for[str(row["representative_composite_id"])] = str(row["redundancy_cluster_id"])
            for m in str(row["members"]).split("|"):
                cluster_for[m] = str(row["redundancy_cluster_id"])

    model_entries = []
    for _, r in model_survivors.iterrows():
        cid = str(r["composite_id"])
        als = sorted(set(exact_aliases.get(cid, []) + near_aliases.get(cid, [])))
        model_entries.append(enrich(r, cluster_id=cluster_for.get(cid), aliases=als))
    model_ids = sorted(e["composite_id"] for e in model_entries)
    model_hash = hashlib.sha256(json.dumps(model_ids, separators=(",", ":")).encode()).hexdigest()

    raw_doc = {
        "artifact": "frozen_composite_survivor_bank_raw_v1",
        "n_survivors": len(raw_entries),
        "RAW_COMPOSITE_SURVIVOR_SET_HASH": raw_hash,
        "survivor_classes": sorted(SURVIVOR_CLASSES),
        "CANONICAL_SELECTIVE_CLASS": CANONICAL_SELECTIVE_CLASS,
        "survivors": raw_entries,
        "DEVELOPMENT_ONLY": "YES",
        "OOS_OPENED": "NO",
    }
    model_doc = {
        "artifact": "frozen_composite_survivor_bank_v1",
        "n_survivors": len(model_entries),
        "COMPOSITE_SURVIVOR_SET_HASH": model_hash,
        "RAW_COMPOSITE_SURVIVOR_SET_HASH": raw_hash,
        "survivor_classes": sorted(SURVIVOR_CLASSES),
        "CANONICAL_SELECTIVE_CLASS": CANONICAL_SELECTIVE_CLASS,
        "survivors": model_entries,
        "DEVELOPMENT_ONLY": "YES",
        "OOS_OPENED": "NO",
        "COMPOSITE_REDUNDANCY_METHOD": "EVENT_STREAM_JACCARD",
        "COMPOSITE_REDUNDANCY_THRESHOLD": COMPOSITE_REDUNDANCY_THRESHOLD,
    }
    save_json(root / "frozen_composite_survivor_bank_raw_v1.json", raw_doc)
    save_json(root / "frozen_composite_survivor_bank_v1.json", model_doc)
    return {
        "RAW_COMPOSITE_SURVIVOR_SET_HASH": raw_hash,
        "COMPOSITE_SURVIVOR_SET_HASH": model_hash,
        "n_raw": len(raw_entries),
        "n_model": len(model_entries),
        "raw": raw_doc,
        "model": model_doc,
    }


def write_summaries(root: Path, results: pd.DataFrame) -> None:
    df = results.copy()
    df["composite_class"] = df["composite_class"].map(normalize_class_name)

    def _summary(group_cols: list[str], path: Path) -> None:
        rows = []
        for keys, g in df.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            rec = dict(zip(group_cols, keys))
            rec["n"] = int(len(g))
            for cls in (
                "INCREMENTAL_BALANCED",
                "INCREMENTAL_SELECTIVE",
                "WEAK_INCREMENTAL",
                "NO_INCREMENTAL_EDGE",
                "INSUFFICIENT",
            ):
                rec[f"n_{cls}"] = int((g["composite_class"] == cls).sum())
            rows.append(rec)
        pd.DataFrame(rows).to_csv(path, index=False)

    _summary(["template_id"], root / "composite_summary_by_template_v1.csv")
    _summary(["decision_tf", "direction"], root / "composite_summary_by_tf_direction_v1.csv")
    # family proxy: trigger id prefix / leave trigger column
    if "trigger_candidate_id" in df.columns:
        df2 = df.copy()
        df2["trigger_family_proxy"] = df2["trigger_candidate_id"].astype(str).str.split("_").str[0]
        rows = []
        for keys, g in df2.groupby(["trigger_family_proxy"], dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            rec = {"trigger_family_proxy": keys[0], "n": int(len(g))}
            for cls in (
                "INCREMENTAL_BALANCED",
                "INCREMENTAL_SELECTIVE",
                "WEAK_INCREMENTAL",
                "NO_INCREMENTAL_EDGE",
                "INSUFFICIENT",
            ):
                rec[f"n_{cls}"] = int((g["composite_class"] == cls).sum())
            rows.append(rec)
        pd.DataFrame(rows).to_csv(root / "composite_summary_by_family_v1.csv", index=False)
    neg = df[df["composite_class"].isin(["NO_INCREMENTAL_EDGE", "INSUFFICIENT", "WEAK_INCREMENTAL"])]
    neg.to_csv(root / "composite_negative_results_v1.csv", index=False)


def _best_row(g: pd.DataFrame) -> dict[str, Any] | None:
    if g.empty:
        return None
    g2 = g.copy()
    g2["_pd"] = pd.to_numeric(g2.get("PRECISION_DELTA_VS_TRIGGER"), errors="coerce").fillna(-999)
    g2["_rr"] = pd.to_numeric(g2.get("RECALL_RETENTION_VS_TRIGGER"), errors="coerce").fillna(-999)
    g2["_sig"] = pd.to_numeric(g2.get("TOTAL_SIGNALS"), errors="coerce").fillna(-1)
    g2 = g2.sort_values(["_pd", "_rr", "_sig", "composite_id"], ascending=[False, False, False, True])
    r = g2.iloc[0]
    return {
        "composite_id": r["composite_id"],
        "template_id": r.get("template_id"),
        "direction": r.get("direction"),
        "decision_tf": r.get("decision_tf"),
        "PRECISION": r.get("PRECISION"),
        "PRECISION_DELTA_VS_TRIGGER": r.get("PRECISION_DELTA_VS_TRIGGER"),
        "EVENT_RECALL": r.get("EVENT_RECALL"),
        "FALSE_POSITIVE_RATE": r.get("FALSE_POSITIVE_RATE"),
        "TOTAL_SIGNALS": r.get("TOTAL_SIGNALS"),
        "RECALL_RETENTION_VS_TRIGGER": r.get("RECALL_RETENTION_VS_TRIGGER"),
        "SIGNAL_RETENTION": r.get("SIGNAL_RETENTION"),
        "MEDIAN_MFE_AFTER_SIGNAL": r.get("MEDIAN_MFE_AFTER_SIGNAL"),
        "MEDIAN_MAE_AFTER_SIGNAL": r.get("MEDIAN_MAE_AFTER_SIGNAL"),
        "usable_folds": r.get("usable_folds"),
        "positive_delta_folds": r.get("positive_delta_folds"),
        "composite_class": normalize_class_name(str(r.get("composite_class"))),
        "note": "Best-by-metrics within DEVELOPMENT survivors; small lift is not automatically useful.",
    }


def build_execution_report(
    root: Path,
    results: pd.DataFrame,
    *,
    config_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    df = results.copy()
    df["composite_class"] = df["composite_class"].map(normalize_class_name)
    survivors = df[df["composite_class"].isin(SURVIVOR_CLASSES)].copy()

    def cls_count(mask) -> dict[str, int]:
        sub = df[mask]
        return {c: int((sub["composite_class"] == c).sum()) for c in (
            "INCREMENTAL_BALANCED",
            "INCREMENTAL_SELECTIVE",
            "WEAK_INCREMENTAL",
            "NO_INCREMENTAL_EDGE",
            "INSUFFICIENT",
        )}

    t1 = df["template_id"] == "T1_DUAL_ANCHOR"
    t2 = df["template_id"] == "T2_REGIME_ANCHOR"
    t3 = df["template_id"] == "T3_ANCHOR_TRANSITION"
    t4 = df["template_id"] == "T4_REGIME_ANCHOR_TRANSITION"
    t5 = df["template_id"] == "T5_ANCHOR_MICRO"
    t6 = df["template_id"] == "T6_CROSS_FAMILY_SAME_TF"
    s_t1 = survivors["template_id"] == "T1_DUAL_ANCHOR"
    s_t2 = survivors["template_id"] == "T2_REGIME_ANCHOR"
    s_t3 = survivors["template_id"] == "T3_ANCHOR_TRANSITION"
    s_t5 = survivors["template_id"] == "T5_ANCHOR_MICRO"
    s_t6 = survivors["template_id"] == "T6_CROSS_FAMILY_SAME_TF"

    def _family(cid: Any) -> str:
        return str(config_by_id.get(str(cid), {}).get("family") or "")

    trig_fam = df["trigger_candidate_id"].map(_family) if "trigger_candidate_id" in df.columns else pd.Series([""] * len(df))
    # context families: any non-matching
    def _ctx_has_non_macd(row) -> bool:
        ids = [x for x in str(row.get("context_candidate_ids") or "").split("|") if x]
        fams = {_family(i) for i in ids}
        return bool(fams - {"MACD"}) if fams else False

    def _ctx_has_macd(row) -> bool:
        ids = [x for x in str(row.get("context_candidate_ids") or "").split("|") if x]
        return any(_family(i) == "MACD" for i in ids)

    macd_trig_non_macd_ctx = df[(trig_fam == "MACD") & df.apply(_ctx_has_non_macd, axis=1)]
    non_macd_trig_macd_ctx = df[(trig_fam != "MACD") & df.apply(_ctx_has_macd, axis=1)]

    t5_5m = survivors[s_t5 & (survivors["decision_tf"] == "5m")]
    t5_15m = survivors[s_t5 & (survivors["decision_tf"] == "15m")]

    report = {
        "artifact": "composite_execution_report_v1",
        "DEVELOPMENT_ONLY": "YES",
        "OOS_OPENED": "NO",
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "CANONICAL_SELECTIVE_CLASS": CANONICAL_SELECTIVE_CLASS,
        "DUAL_ANCHOR_INCREMENTAL_BALANCED_COUNT": int(((t1) & (df["composite_class"] == "INCREMENTAL_BALANCED")).sum()),
        "DUAL_ANCHOR_INCREMENTAL_SELECTIVE_COUNT": int(((t1) & (df["composite_class"] == "INCREMENTAL_SELECTIVE")).sum()),
        "DUAL_ANCHOR_BEST_BY_DIRECTION": {
            d: _best_row(survivors[s_t1 & (survivors["direction"] == d)]) for d in ("UP", "DOWN")
        },
        "REGIME_ANCHOR_INCREMENTAL_COUNT": int((t2 & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()),
        "REGIME_ANCHOR_BEST_BY_TF_DIRECTION": {
            f"{tf}|{d}": _best_row(
                survivors[s_t2 & (survivors["decision_tf"].astype(str) == tf) & (survivors["direction"] == d)]
            )
            for tf in sorted(set(df.loc[t2, "decision_tf"].astype(str)))
            for d in ("UP", "DOWN")
        },
        "TRANSITION_30M_INCREMENTAL_COUNT": int(
            (t3 & (df["decision_tf"].astype(str).str.upper().isin(["30M", "30m"])) & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()
        ),
        "TRANSITION_30M_BEST_BY_DIRECTION": {
            d: _best_row(
                survivors[
                    s_t3
                    & (survivors["decision_tf"].astype(str).str.upper().isin(["30M", "30m"]))
                    & (survivors["direction"] == d)
                ]
            )
            for d in ("UP", "DOWN")
        },
        "TRIPLE_COMPOSITE_INCREMENTAL_COUNT": int((t4 & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()),
        "15M_CONDITIONAL_INCREMENTAL_COUNT": int((t5 & (df["decision_tf"] == "15m") & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()),
        "5M_CONDITIONAL_INCREMENTAL_COUNT": int((t5 & (df["decision_tf"] == "5m") & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()),
        "CROSS_FAMILY_INCREMENTAL_COUNT": int((t6 & df["composite_class"].isin(SURVIVOR_CLASSES)).sum()),
        "CROSS_FAMILY_BEST_PAIRS": {
            d: _best_row(survivors[s_t6 & (survivors["direction"] == d)]) for d in ("UP", "DOWN")
        },
        "MACD_TRIGGER_WITH_NON_MACD_CONTEXT_COUNT": int(len(macd_trig_non_macd_ctx)),
        "MACD_TRIGGER_WITH_NON_MACD_INCREMENTAL_BALANCED": int(
            (macd_trig_non_macd_ctx["composite_class"] == "INCREMENTAL_BALANCED").sum()
        ),
        "MACD_TRIGGER_WITH_NON_MACD_INCREMENTAL_SELECTIVE": int(
            (macd_trig_non_macd_ctx["composite_class"] == "INCREMENTAL_SELECTIVE").sum()
        ),
        "NON_MACD_TRIGGER_WITH_MACD_CONTEXT_COUNT": int(len(non_macd_trig_macd_ctx)),
        "COMPOSITE_CLASS_COUNTS_BY_TEMPLATE": {
            str(t): cls_count(df["template_id"] == t) for t in sorted(df["template_id"].astype(str).unique())
        },
        "COMPOSITE_CLASS_COUNTS_BY_TF": {
            str(t): cls_count(df["decision_tf"] == t) for t in sorted(df["decision_tf"].astype(str).unique())
        },
        "COMPOSITE_CLASS_COUNTS_BY_DIRECTION": {
            str(d): cls_count(df["direction"] == d) for d in sorted(df["direction"].astype(str).unique())
        },
        "LOW_TF_T5_5M": {
            "incremental_count": int(len(t5_5m)),
            "best_by_direction": {d: _best_row(t5_5m[t5_5m["direction"] == d]) for d in ("UP", "DOWN")},
        },
        "LOW_TF_T5_15M": {
            "incremental_count": int(len(t5_15m)),
            "best_by_direction": {d: _best_row(t5_15m[t5_15m["direction"] == d]) for d in ("UP", "DOWN")},
        },
    }
    # Development verdict (deterministic wording only)
    n_bal = int((df["composite_class"] == "INCREMENTAL_BALANCED").sum())
    n_sel = int((df["composite_class"] == "INCREMENTAL_SELECTIVE").sum())
    n_weak = int((df["composite_class"] == "WEAK_INCREMENTAL").sum())
    if n_bal + n_sel >= 20:
        verdict = "COMPOSITE_INCREMENTAL_INFORMATION_SUPPORTED"
    elif n_bal + n_sel >= 1 or n_weak >= 50:
        verdict = "COMPOSITE_INCREMENTAL_INFORMATION_WEAK"
    else:
        verdict = "COMPOSITE_INCREMENTAL_INFORMATION_NOT_SUPPORTED"
    report["DEVELOPMENT_VERDICT"] = verdict
    report["DEVELOPMENT_VERDICT_COUNTS"] = {
        "INCREMENTAL_BALANCED": n_bal,
        "INCREMENTAL_SELECTIVE": n_sel,
        "WEAK_INCREMENTAL": n_weak,
    }
    report["PNL_TESTED"] = "NO"
    report["OOS_VALIDATED"] = "NO"
    save_json(root / "composite_execution_report_v1.json", report)
    return report


def build_model_handoff(root: Path, model_bank: dict[str, Any], config_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    survivors = model_bank.get("survivors") or []
    atomic_ids = sorted({s["trigger_candidate_id"] for s in survivors} | {c for s in survivors for c in s.get("context_candidate_ids") or []})
    composite_ids = sorted(s["composite_id"] for s in survivors)
    doc = {
        "artifact": "model_feature_handoff_v1",
        "MODEL_FEATURE_HANDOFF_READY": "YES",
        "DEVELOPMENT_ONLY": "YES",
        "OOS_VALIDATED": "NO",
        "PNL_TESTED": "NO",
        "atomic_feature_ids": atomic_ids,
        "composite_feature_ids": composite_ids,
        "features": [
            {
                "composite_id": s["composite_id"],
                "template_id": s.get("template_id"),
                "template_role": "composite_confluence",
                "direction": s.get("direction"),
                "decision_tf": s.get("decision_tf"),
                "trigger_family": s.get("trigger_family"),
                "context_families": s.get("context_families"),
                "causal_AVAILABLE_AT_semantics": "composite timestamp equals trigger available_at",
            }
            for s in survivors
        ],
        "continuous_fields_planned_for_model_dataset": [
            "context_age",
            "inverse_threshold_distance",
            "ATR_volatility_context",
            "wave_geometry_context",
        ],
        "COMPOSITE_SURVIVOR_SET_HASH": model_bank.get("COMPOSITE_SURVIVOR_SET_HASH"),
    }
    save_json(root / "model_feature_handoff_v1.json", doc)
    return doc


def run_finalization(
    root: Path,
    *,
    allow_partial_test: bool = False,
    atomic_bank_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(root)
    gate = assert_finalization_allowed(root, allow_partial_test=allow_partial_test)
    bank_root = atomic_bank_root or root
    configs = list(load_atomic_bank(root=bank_root)["configs"])
    config_by_id = {c["candidate_id"]: c for c in configs}

    assemble = assemble_results_bounded(root)
    results_csv = root / "composite_results_all_v1.csv"
    # For dry tests / modest sizes load CSV; production path still assembled bounded.
    results = pd.read_csv(results_csv) if results_csv.exists() else pd.DataFrame()
    if not results.empty and "composite_class" in results.columns:
        results["composite_class"] = results["composite_class"].map(normalize_class_name)

    exact = exact_duplicate_clusters(results_csv, root / "composite_exact_duplicate_clusters_v1.csv")
    exact_df = pd.read_csv(root / "composite_exact_duplicate_clusters_v1.csv") if exact["COMPOSITE_EXACT_DUPLICATE_CLUSTER_COUNT"] else pd.DataFrame()
    fold_path = root / "composite_fold_stability_v1.csv"
    fold_df = pd.read_csv(fold_path) if fold_path.exists() else pd.DataFrame()

    survivors = results[results["composite_class"].map(is_survivor_class)] if not results.empty else pd.DataFrame()
    near_df, near_replace, near_aliases = near_redundancy_survivors(root, survivors, fold_df) if not survivors.empty else (pd.DataFrame(), {}, {})
    near_df.to_csv(root / "composite_redundancy_v1.csv", index=False)

    banks = build_survivor_banks(
        root,
        results,
        fold_df,
        exact_clusters=exact_df,
        near_df=near_df,
        near_replace=near_replace,
        near_aliases=near_aliases,
        config_by_id=config_by_id,
    )
    if not results.empty:
        write_summaries(root, results)
        report = build_execution_report(root, results, config_by_id=config_by_id)
    else:
        report = {}
    handoff = build_model_handoff(root, banks["model"], config_by_id)

    out = {
        "gate": gate,
        "assemble": assemble,
        "exact": exact,
        "banks": {
            "RAW_COMPOSITE_SURVIVOR_SET_HASH": banks["RAW_COMPOSITE_SURVIVOR_SET_HASH"],
            "COMPOSITE_SURVIVOR_SET_HASH": banks["COMPOSITE_SURVIVOR_SET_HASH"],
            "n_raw": banks["n_raw"],
            "n_model": banks["n_model"],
        },
        "report_verdict": report.get("DEVELOPMENT_VERDICT"),
        "handoff": {"MODEL_FEATURE_HANDOFF_READY": handoff.get("MODEL_FEATURE_HANDOFF_READY")},
        "COMPOSITE_REDUNDANCY_METHOD": "EVENT_STREAM_JACCARD",
        "COMPOSITE_REDUNDANCY_THRESHOLD": COMPOSITE_REDUNDANCY_THRESHOLD,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "CANONICAL_SELECTIVE_CLASS": CANONICAL_SELECTIVE_CLASS,
        "SELECTIVE_THRESHOLD_CHANGED": "NO",
        "SURVIVOR_CLASSES": ",".join(sorted(SURVIVOR_CLASSES)),
        "FINAL_RESULT_ASSEMBLY_BOUNDED": "YES",
    }
    save_json(root / "composite_finalization_status_v1.json", out)
    return out
