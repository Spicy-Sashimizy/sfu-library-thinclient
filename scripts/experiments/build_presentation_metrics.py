#!/usr/bin/env python3
"""Aggregate every measured thin-client metric into one presentation-ready
suite, comparable to the sfu-library-mcp-training baselines. (BMP-decommission
plan Workstream C1.)

What it does:
  1. Parses the relevant result files under data/eval_results/ (+ a couple of
     Qdrant latency logs) into a flat row schema:
       metric, k, scale, backend, value, baseline_value, delta,
       eval_script, result_file, date, git_commit, status, comparable_to_training
     status ∈ {measured, est, unmeasured}.
  2. Appends/updates that ledger at data/eval_results/METRICS_CATALOG.json
     (idempotent: re-running with the same result files updates, not duplicates).
  3. Renders:
       - data/eval_results/presentation_metrics_<date>.json (machine-readable), and
       - docs/archive/bmp_decommission_plan/PRESENTATION_METRICS.md (tables + narrative).
       - docs/archive/bmp_decommission_plan/METRICS_CATALOG.md (human-readable catalog).

Metric definitions are kept identical to training (PLAN.md "Cataloging" §5):
NDCG@10 (gain 2^g-1, full-judged-pool IDCG), MRR@10/P@10 (grade≥2 relevant),
RRF k=60, LLM judge = claude-haiku-4-5-20251001, 0-3 rubric, TREC-pooled. The
LLM-judge cache is reused (no re-judging cost). Numbers are tagged
`comparable-to-training` only when they share these definitions; parity/ops
metrics with no training equivalent are tagged `new`.

Usage:
  scripts/experiments/build_presentation_metrics.py            # render from existing catalog
  scripts/experiments/build_presentation_metrics.py --rebuild  # re-parse all source files
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "data" / "eval_results"
CATALOG_JSON = EVAL / "METRICS_CATALOG.json"
PRESENTATION_JSON_TMPL = "presentation_metrics_{date}.json"
PRESENTATION_MD = REPO_ROOT / "docs" / "archive" / "bmp_decommission_plan" / "PRESENTATION_METRICS.md"
CATALOG_MD = REPO_ROOT / "docs" / "archive" / "bmp_decommission_plan" / "METRICS_CATALOG.md"


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=str(REPO_ROOT)).stdout.strip() or None
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"  ! could not parse {path.name}: {e}")
        return None


def _lat_from_log(path: Path) -> dict | None:
    """Pull ALL 'latency ms: p50=.. p95=.. max=..' + RSS lines from a
    spike_qdrant_sparse.py measure log. Reports the p50/p95 RANGE across passes
    (steady-state spread), per docs/THIN_CLIENT_SWAP.md which quotes ranges
    like 'p50 545.8–861.5' and 'p50 ~66 ms (65.6–67.4)'."""
    if not path.exists():
        return None
    txt = path.read_text(errors="ignore")
    lat_lines = re.findall(r"latency ms: p50=([\d.]+) p95=([\d.]+) max=([\d.]+) mean=([\d.]+)", txt)
    rss_rest = re.findall(r"RSS at rest: ([\d.]+) MB", txt)
    rss_load = re.findall(r"RSS during query load: ([\d.]+) MB", txt)
    count = re.findall(r"collection points=([\d]+)", txt)
    if not lat_lines:
        return None
    p50s = [float(a) for a, _, _, _ in lat_lines]
    p95s = [float(b) for _, b, _, _ in lat_lines]
    out = {"p50_ms": round(sum(p50s) / len(p50s), 1),
           "p95_ms": round(sum(p95s) / len(p95s), 1),
           "max_ms": float(lat_lines[-1][2]),
           "mean_ms": float(lat_lines[-1][3]),
           "p50_range": (min(p50s), max(p50s)),
           "p95_range": (min(p95s), max(p95s)),
           "n_passes": len(p50s),
           "points": int(count[-1]) if count else None,
           "rss_rest_mb": float(rss_rest[-1]) if rss_rest else None,
           "rss_load_mb": float(rss_load[-1]) if rss_load else None,
           "all_p50": p50s}
    return out


def _date_from_path(name: str) -> str:
    """Pull YYYY-MM-DD from a dated filename; fall back to file mtime."""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m2 = re.search(r"(20\d{2})-(\d{2})-(\d{2})", name)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
    return None


def rows_llm_judge(path: Path) -> list[dict]:
    """benchmark_llm_judge_final.json — the training-comparable quality suite."""
    d = _load_json(path)
    if not d:
        return []
    s = d.get("summary", {})
    date = d.get("timestamp", "")[:10] or _date_from_path(path.name) or "2026-05-16"
    baseline = "training/benchmark_llm_judge_final.json (this IS the baseline)"
    rows = []
    for method, label, comparable in [
        ("bm25", "BM25F (local)", True),
        ("splade", "SPLADE (local)", True),
        ("rrf", "BM25F+SPLADE RRF (local)", True),
        ("openalex_relevance", "OpenAlex relevance sort", True),
    ]:
        m = s.get(method) or {}
        if not m:
            continue
        for metric_key, k in [("ndcg", 10), ("mrr", 10), ("p_at_k", 10)]:
            val = m.get(f"mean_{metric_key}")
            if val is None:
                continue
            metric_name = {"ndcg": "NDCG", "mrr": "MRR", "p_at_k": "P"}[metric_key]
            rows.append(_row(
                metric=f"{metric_name}@{k}", k=k, scale="120q-judged",
                backend="thinclient (BMP SPLADE)", value=round(val, 4),
                eval_script="scripts/experiments/benchmark_llm_judge.py",
                result_file=str(path.relative_to(REPO_ROOT)),
                date=date, baseline_ref=baseline, delta=None,
                status="measured", comparable=comparable,
                extra={"method": method, "label": label, "num_queries": d.get("num_queries"),
                       "judge": d.get("judge")}))
    return rows


def rows_parity_waves(path: Path) -> list[dict]:
    """thinclient_parity_waves_150m.json — 150M tc-vs-OpenSearch parity."""
    d = _load_json(path)
    if not d:
        return []
    rows = []
    date = _date_from_path(path.name) or "2026-06-18"
    ndcg = d.get("ndcg@10", {})
    tc = (ndcg.get("tc_rrf") or {}).get("mean")
    oss = (ndcg.get("os_rrf") or {}).get("mean")
    if tc is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale="150M (40q judged-subset)",
                        backend="thinclient RRF", value=round(tc, 4),
                        eval_script="scripts/eval_parity_section_waves.py + eval_thinclient_parity.py compare",
                        result_file=str(path.relative_to(REPO_ROOT)),
                        date=date, baseline_ref="OpenSearch 150M RRF (same run)",
                        delta=round(tc - oss, 4) if oss is not None else None,
                        status="measured", comparable=True,
                        extra={"judged_queries": (ndcg.get("tc_rrf") or {}).get("judged_queries")}))
    if oss is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale="150M (34q judged-subset)",
                        backend="OpenSearch 150M RRF (baseline)", value=round(oss, 4),
                        eval_script="scripts/eval_thinclient_parity.py record-os + compare",
                        result_file=str(path.relative_to(REPO_ROOT)),
                        date=date, baseline_ref="thinclient RRF (same run)",
                        delta=round(oss - tc, 4) if tc is not None else None,
                        status="measured", comparable=True))
    ov = d.get("overlap_vs_baseline@50", {})
    for leg in ["bm25f", "splade", "rrf"]:
        v = ov.get(leg)
        if v is not None:
            rows.append(_row(metric="overlap@50", k=50, scale="150M (40q)",
                            backend=f"thinclient {leg}", value=round(v, 3),
                            eval_script="scripts/eval_parity_section_waves.py + compare",
                            result_file=str(path.relative_to(REPO_ROOT)),
                            date=date, baseline_ref="OpenSearch 150M",
                            delta=None, status="measured", comparable=False,
                            extra={"note": "per-leg set agreement vs OpenSearch"}))
    return rows


def rows_parity_qdrant(path: Path) -> list[dict]:
    """thinclient_parity_qdrant_<date>.json — 150M tc(qdrant backend)-vs-OpenSearch
    RRF quality (BMP-decommission plan Workstream B2). Same query set, corpus,
    judge cache, RRF k=60 as the BMP baseline rows_parity_waves, so the qdrant
    tc_rrf NDCG@10 is directly comparable to the BMP tc_rrf number."""
    d = _load_json(path)
    if not d:
        return []
    rows = []
    prov = d.get("provenance", {})
    date = prov.get("timestamp", "")[:10] or _date_from_path(path.name) or "2026-06-25"
    ndcg = d.get("ndcg@10", {})
    tc = (ndcg.get("tc_rrf") or {}).get("mean")
    oss = (ndcg.get("os_rrf") or {}).get("mean")
    if tc is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale="150M-live (39q judged)",
                        backend="thinclient RRF (qdrant)", value=round(tc, 4),
                        eval_script="scripts/eval_thinclient_parity.py compare (record-tc SFU_SPLADE_BACKEND=qdrant)",
                        result_file=str(path.relative_to(REPO_ROOT)),
                        date=date, baseline_ref="thinclient RRF (BMP) 0.5368 + OpenSearch 0.4487 (same run)",
                        delta=round(tc - oss, 4) if oss is not None else None,
                        status="measured", comparable=True,
                        extra={"judged_queries": (ndcg.get("tc_rrf") or {}).get("judged_queries"),
                               "backend": "qdrant", "vs_bmp_delta_39q": round(tc - 0.5368, 4),
                               "common_34_subset_mean": 0.5597,
                               "vs_bmp_delta_common34": round(0.5597 - 0.5606, 4),
                               "common_34_wins": "29/34 (same as BMP baseline)",
                               "note": "B2 gate: qdrant RRF vs BMP RRF |Δ|<0.002 on both subsets → indistinguishable; still beats OS +0.111"}))
    if oss is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale="150M (34q judged-subset)",
                        backend="OpenSearch 150M RRF (baseline)", value=round(oss, 4),
                        eval_script="scripts/eval_thinclient_parity.py record-os + compare",
                        result_file=str(path.relative_to(REPO_ROOT)),
                        date=date, baseline_ref="thinclient RRF (qdrant) (same run)",
                        delta=round(oss - tc, 4) if tc is not None else None,
                        status="measured", comparable=True))
    ov = d.get("overlap_vs_baseline@50", {})
    for leg in ["bm25f", "splade", "rrf"]:
        v = ov.get(leg)
        if v is not None:
            rows.append(_row(metric="overlap@50", k=50, scale="150M-live (40q)",
                            backend=f"thinclient {leg} (qdrant)", value=round(v, 3),
                            eval_script="scripts/eval_thinclient_parity.py compare",
                            result_file=str(path.relative_to(REPO_ROOT)),
                            date=date, baseline_ref="OpenSearch 150M",
                            delta=None, status="measured", comparable=False,
                            extra={"note": "per-leg set agreement vs OpenSearch (parity axis, not quality)"}))
    return rows


def rows_quant_fidelity(path: Path) -> list[dict]:
    """quant_fidelity*.json — BMP-vs-Qdrant exactness parity."""
    d = _load_json(path)
    if not d:
        return []
    s = d.get("summary", {})
    prov = d.get("provenance", {})
    rows = []
    date = _date_from_path(path.name) or prov.get("timestamp", "")[:10] or "2026-06-19"
    backend = prov.get("backend", "qdrant-f32-inmemory")
    scale = prov.get("scale") or f"{s.get('pool_docs', '?')}-pool"
    is_live = "live" in backend
    base = "data/eval_results/quant_fidelity_30mscan.json (in-memory)"
    for metric, key in [("overlap@10", "mean_overlap@10"),
                        ("overlap@50", "mean_overlap@50"),
                        ("Kendall-τ", "mean_kendall_tau")]:
        v = s.get(key)
        if v is not None:
            rows.append(_row(metric=metric, k=50 if "50" in metric else 10,
                            scale=("150M-LIVE" if is_live else scale),
                            backend=f"BMP-8bit vs Qdrant-{'live-f32' if is_live else 'f32'}",
                            value=round(v, 4),
                            eval_script="scripts/experiments/eval_quant_fidelity.py",
                            result_file=str(path.relative_to(REPO_ROOT)),
                            date=date, baseline_ref=base if is_live else None,
                            delta=None, status="measured", comparable=False,
                            extra={"gate": s.get("gate", {}) if metric == "overlap@10" else {}}))
    nf, nq = s.get("mean_ndcg@10_f32"), s.get("mean_ndcg@10_quant")
    if nf is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale=("150M-LIVE" if is_live else scale),
                        backend="Qdrant f32 (leg)", value=round(nf, 4),
                        eval_script="scripts/experiments/eval_quant_fidelity.py",
                        result_file=str(path.relative_to(REPO_ROOT)), date=date,
                        baseline_ref=base if is_live else None,
                        delta=round(nf - nq, 4) if nq is not None else None,
                        status="measured", comparable=False,
                        extra={"n_judged_coverage": s.get("ndcg_queries_with_coverage")}))
    if nq is not None:
        rows.append(_row(metric="NDCG@10", k=10, scale=("150M-LIVE" if is_live else scale),
                        backend="BMP quant (leg)", value=round(nq, 4),
                        eval_script="scripts/experiments/eval_quant_fidelity.py",
                        result_file=str(path.relative_to(REPO_ROOT)), date=date,
                        baseline_ref="Qdrant f32 (same pool)",
                        delta=round(nq - nf, 4) if nf is not None else None,
                        status="measured", comparable=False))
    return rows


def rows_storage(path: Path) -> list[dict]:
    """storage_levers_eval.json — on-disk budget."""
    d = _load_json(path)
    if not d:
        return []
    rows = []
    date = _date_from_path(path.name) or "2026-06-15"
    g = d.get("all_levers_150M_gb") or {}
    if isinstance(g, dict):
        for label, key in [("on-disk GB (all-levers total)", "total_before"),
                           ("on-disk GB (all-levers after levers)", "total_after")]:
            v = g.get(key)
            if isinstance(v, (int, float)):
                rows.append(_row(metric=label, k=None, scale="150M all-levers",
                                backend="thinclient", value=round(v, 1),
                                eval_script="scripts/experiments/eval_storage_levers.py",
                                result_file=str(path.relative_to(REPO_ROOT)),
                                date=date, baseline_ref="OpenSearch 150M",
                                delta=round(g.get("total_after", 0) - g.get("total_before", 0), 1) if key == "total_after" else None,
                                status="measured", comparable=False,
                                extra={"unit": "GB", "saved_pct": g.get("saved_pct")}))
    return rows


def rows_latency(path: Path, scale: str, backend: str, date: str, kind: str) -> list[dict]:
    """Parse a Qdrant measure log into p50/p95/RSS rows."""
    lat = _lat_from_log(path)
    if not lat:
        return []
    rows = []
    for metric, val in [("latency p50", lat["p50_ms"]), ("latency p95", lat["p95_ms"])]:
        rows.append(_row(metric=metric, k=None, scale=scale, backend=backend,
                        value=round(val, 1), eval_script="scripts/archive/spike_qdrant_sparse.py measure",
                        result_file=str(path.relative_to(REPO_ROOT)),
                        date=date, baseline_ref=None, delta=None,
                        status="measured", comparable=False,
                        extra={"kind": kind, "points": lat.get("points")}))
    if lat.get("rss_rest_mb") is not None:
        rows.append(_row(metric="resident RSS rest", k=None, scale=scale, backend=backend,
                        value=round(lat["rss_rest_mb"]), eval_script="scripts/archive/spike_qdrant_sparse.py measure",
                        result_file=str(path.relative_to(REPO_ROOT)), date=date,
                        baseline_ref="BMP ~211 GB resident at 150M", delta=None,
                        status="measured", comparable=False,
                        extra={"note": "MB; BMP is load-into-RAM only"}))
    return rows


def rows_static() -> list[dict]:
    return [
        _row(metric="resident RAM", k=None, scale="150M", backend="BMP (8-bit)",
             value=211.0, eval_script="docs/THIN_CLIENT_SWAP.md (measured 2026-06-17)",
             result_file="docs/THIN_CLIENT_SWAP.md", date="2026-06-17",
             baseline_ref=None, delta=None, status="measured", comparable=False,
             extra={"note": "GB resident; unservable on real hardware", "unit": "GB"}),
        _row(metric="resident RAM rest", k=None, scale="30M", backend="Qdrant on_disk sparse",
             value=1.44, eval_script="scripts/archive/spike_qdrant_sparse.py measure",
             result_file="data/qdrant_spike/measure_par30.log", date="2026-06-19",
             baseline_ref="BMP ~tens of GB at 30M", delta=None,
             status="measured", comparable=False, extra={"unit": "GB", "note": "page-cache backed"}),
        _row(metric="on-disk size", k=None, scale="150M", backend="BMP SPLADE shards",
             value=68.6, eval_script="docs/THIN_CLIENT_SWAP.md (measured)",
             result_file="docs/THIN_CLIENT_SWAP.md", date="2026-06-17",
             baseline_ref=None, delta=None, status="measured", comparable=False, extra={"unit": "GB"}),
        _row(metric="on-disk size", k=None, scale="150M", backend="Qdrant on_disk index",
             value=205.0, eval_script="docs/THIN_CLIENT_SWAP.md (measured 2026-06-21)",
             result_file="docs/THIN_CLIENT_SWAP.md", date="2026-06-21",
             baseline_ref="BMP 68.6 GB", delta=round(205.0 - 68.6, 1),
             status="measured", comparable=False, extra={"unit": "GB",
             "note": "surprise: Qdrant 205 > BMP 68.6 — matters for droplet disk cost"}),
        _row(metric="ingest throughput", k=None, scale="30M gate", backend="Qdrant (8 workers, wait=True)",
             value=4234.0, eval_script="scripts/archive/spike_qdrant_sparse.py build-spool-par",
             result_file="data/qdrant_spike/measure_par30.log", date="2026-06-19",
             baseline_ref=None, delta=None, status="measured", comparable=False, extra={"unit": "docs/s"}),
    ]


def _row(metric, k, scale, backend, value, eval_script, result_file, date,
         baseline_ref, delta, status, comparable, extra=None) -> dict:
    return {"metric": metric, "k": k, "scale": scale, "backend": backend,
            "value": value, "baseline_value": None, "delta": delta,
            "baseline_ref": baseline_ref, "eval_script": eval_script,
            "result_file": result_file, "date": date, "git_commit": _git_commit(),
            "status": status, "comparable_to_training": comparable,
            "extra": extra or {}}


def _catalog_key(r: dict) -> str:
    return "|".join([str(r.get("metric")), str(r.get("k")), str(r.get("scale")),
                     str(r.get("backend")), str(r.get("result_file"))])


def load_catalog() -> dict:
    if CATALOG_JSON.exists():
        return json.loads(CATALOG_JSON.read_text())
    return {"schema_version": 1, "generated": None, "metrics": []}


def merge_into_catalog(new_rows: list[dict]) -> tuple[dict, int]:
    """Idempotent upsert by key. Returns (catalog, n_added_or_updated)."""
    cat = load_catalog()
    by_key = {_catalog_key(r): r for r in cat.get("metrics", [])}
    n = 0
    for r in new_rows:
        key = _catalog_key(r)
        r2 = dict(r)
        r2["catalog_key"] = key
        if key not in by_key:
            n += 1
        elif by_key[key].get("value") != r2.get("value") or by_key[key].get("date") != r2.get("date"):
            n += 1
        by_key[key] = r2
    cat["metrics"] = list(by_key.values())
    cat["generated"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    cat["git_commit"] = _git_commit()
    return cat, n


def _section_of(r: dict) -> str:
    m = r.get("metric", "")
    if any(x in m for x in ["NDCG", "MRR", "P@", "overlap"]):
        return "Parity" if ("overlap" in m.lower() or "Kendall" in m) else "Quality"
    if any(x in m.lower() for x in ["latency", "resident", "on-disk", "ingest"]):
        return "Ops"
    if "GB" in m:
        return "Ops"
    return "Other"


def render_catalog_md(cat: dict) -> str:
    lines = ["# METRICS CATALOG — thin-client BMP→Qdrant decommission\n",
             "One row per measured metric: **metric → script → result file → "
             "training baseline → delta**, with the absolute date and a "
             "`measured`/`est.`/`unmeasured` tag. Generated from "
             "`data/eval_results/METRICS_CATALOG.json` (canonical ledger). "
             "This is the index a presenter reads to find any number's provenance.\n",
             f"_Generated {_label(cat.get('generated'))}, git commit `{cat.get('git_commit')}`. "
             f"{len(cat['metrics'])} metrics._\n"]
    sections = {"Quality": [], "Parity": [], "Ops": [], "Other": []}
    for r in cat["metrics"]:
        sections[_section_of(r)].append(r)
    for sec in ["Quality", "Parity", "Ops", "Other"]:
        rows = sections[sec]
        if not rows:
            continue
        lines.append(f"\n## {sec}\n")
        lines.append("| metric | k | scale | backend | value | δ vs baseline | "
                     "script → result file | training baseline | date | tag | comparable |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted(rows, key=lambda x: (x.get("scale", ""), x.get("backend", ""), x.get("metric", ""))):
            k = r.get("k") if r.get("k") is not None else "—"
            delta = f"{r['delta']:+.4f}" if isinstance(r.get("delta"), (int, float)) else "—"
            bl = r.get("baseline_ref") or "—"
            if bl and len(bl) > 48:
                bl = bl[:45] + "…"
            comp = "yes" if r.get("comparable_to_training") else "new"
            rf = r.get("result_file", "—")
            lines.append(
                f"| {r.get('metric','—')} | {k} | {r.get('scale','—')} | "
                f"{r.get('backend','—')} | {r['value'] if r.get('value') is not None else '—'} | "
                f"{delta} | `{r.get('eval_script','—')}` → `{rf}` | {bl} | "
                f"{r.get('date','—')} | {r.get('status','—')} | {comp} |")
    notes = ("\n## Tags & comparability\n",
             "- **measured** = run against real data/infra this session or a prior one, "
             "result file on disk. **est.** = design estimate. **unmeasured** = the "
             "module shipped before its eval (CLAUDE.md new-module rule).\n"
             "- **comparable-to-training (yes)** = same NDCG@10/MRR@10/P@10 definitions, "
             "RRF k=60, same `claude-haiku-4-5-20251001` judge + cache. **new** = has no "
             "training-project equivalent (parity/ops), so never imply a false "
             "apples-to-apples vs the training charts.\n")
    lines.extend(notes)
    return "\n".join(lines)


def _label(x):
    return x or "—"


def render_presentation_md(cat: dict, pres: dict) -> str:
    L = ["# Presentation Metrics Suite — thin-client (BMP→Qdrant)\n",
         "Presentation-ready numbers comparable to the `sfu-library-mcp-training` "
         "baselines (same LLM-judge methodology, same metric definitions). Every "
         "number below is sourced — see `METRICS_CATALOG.md` for the metric → "
         "script → result-file → training-baseline → delta provenance.\n",
         f"_Generated {_label(cat.get('generated'))}, git commit `{cat.get('git_commit')}`._\n"]

    q = [r for r in cat["metrics"] if _section_of(r) == "Quality"]
    p = [r for r in cat["metrics"] if _section_of(r) == "Parity"]
    o = [r for r in cat["metrics"] if _section_of(r) == "Ops"]

    L.append("## 1. Quality (training-comparable)\n")
    L.append("NDCG@10 / MRR@10 / P@10 per retrieval method, LLM-judged "
             "(`claude-haiku-4-5-20251001`, 0-3 rubric, TREC-pooled; judge cache reused, "
             "$0). The thin-client numbers sit beside the OpenAlex-live baseline:\n")
    L.append("| method | NDCG@10 | MRR@10 | P@10 | date | source |")
    L.append("|---|---|---|---|---|---|")
    by_method = {}
    for r in q:
        m = (r.get("extra") or {}).get("label") or r.get("backend")
        by_method.setdefault(m, {})[r["metric"]] = (r["value"], r["date"], r["result_file"])
    for m, vals in by_method.items():
        ndcg = vals.get("NDCG@10", ("—", "—", ""))
        mrr = vals.get("MRR@10", ("—", "—", ""))
        p10 = vals.get("P@10", ("—", "—", ""))
        L.append(f"| {m} | {ndcg[0]} | {mrr[0]} | {p10[0]} | {ndcg[1]} | `{ndcg[2]}` |")

    L.append("\n## 2. BMP↔Qdrant parity (150M where measured)\n")
    L.append("| metric | scale | backend | value | δ | gate | date | source |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in p:
        gate = (r.get("extra") or {}).get("gate", {})
        gp = ("PASS" if gate.get("pass") else ("—" if not gate else "FAIL")) if gate else "—"
        delta = f"{r['delta']:+.4f}" if isinstance(r.get("delta"), (int, float)) else "—"
        L.append(f"| {r['metric']} | {r.get('scale','—')} | {r.get('backend','—')} | "
                 f"{r['value']} | {delta} | {gp} | {r.get('date','—')} | `{r.get('result_file','—')}` |")
    L.append("\n**Gate (PLAN.md B1):** overlap@10 ≥ 0.98, Kendall-τ ≥ 0.97, "
             "|NDCG@10 Δ| ≤ 0.005. Qdrant sparse search is exact; BMP is block-max "
             "approximate (WAND), so recall(qdrant) ≥ recall(bmp) by construction.\n")

    L.append("\n## 3. Ops envelope (latency, RAM, storage, ingest)\n")
    L.append("| metric | scale | backend | value | unit | date | source |")
    L.append("|---|---|---|---|---|---|---|")
    for r in o:
        ex = r.get("extra") or {}
        m = r.get("metric", "")
        if "unit" in ex:
            unit = ex["unit"]
        elif "latency" in m:
            unit = "ms"
        elif "RSS" in m or "resident" in m.lower():
            unit = "MB"
        elif "throughput" in m.lower():
            unit = ex.get("unit", "")
        else:
            unit = ""
        val = r["value"]
        L.append(f"| {m} | {r.get('scale','—')} | {r.get('backend','—')} | "
                 f"{val} | {unit} | {r.get('date','—')} | `{r.get('result_file','—')}` |")
    L.append("\n> ⚠ **On-disk ≠ resident RAM.** At 150M the Qdrant index is 205 GB on "
             "disk but RAM-bound (~7% page-cacheable on 23 GB host → p50 ~546–861 ms). "
             "The **30M fitting-tier (p50 ~66 ms, 1.44 GB resident)** is what a "
             "correctly-sized DO droplet delivers — see `DO_SIZING.md`.\n")

    flagged = [r for r in cat["metrics"] if r.get("status") in ("est", "unmeasured")]
    if flagged:
        L.append("\n## Estimated / unmeasured (explicitly flagged)\n")
        for r in flagged:
            L.append(f"- **{r['metric']}** ({r.get('backend')}): *{r.get('status')}* — {r.get('result_file')}")
    return "\n".join(L)


def collect_all_rows() -> list[dict]:
    rows = []
    for name in ["benchmark_llm_judge_final.json", "benchmark_llm_judge_full.json"]:
        p = EVAL / name
        if p.exists():
            rows += rows_llm_judge(p)
            break
    p = EVAL / "thinclient_parity_waves_150m.json"
    if p.exists():
        rows += rows_parity_waves(p)
    qdrant_parity = sorted(EVAL.glob("thinclient_parity_qdrant_*.json"),
                           key=lambda x: x.name)
    if qdrant_parity:
        rows += rows_parity_qdrant(qdrant_parity[-1])
    for p in sorted(EVAL.glob("quant_fidelity*.json")):
        rows += rows_quant_fidelity(p)
    p = EVAL / "storage_levers_eval.json"
    if p.exists():
        rows += rows_storage(p)
    rows += rows_latency(EVAL / "measure_150m_red_baseline.log", "150M (OOM-churn, red)",
                         "Qdrant on_disk", "2026-06-21", "red-baseline")
    rows += rows_latency(EVAL / "measure_150m_postfix_20260620_230514.log", "150M (warm, post-fix)",
                         "Qdrant on_disk", "2026-06-21", "postfix-warm")
    p30_warm = REPO_ROOT / "data" / "qdrant_spike" / "measure_par30_warm.log"
    rows += rows_latency(p30_warm, "30M fitting-tier (warm steady-state)",
                         "Qdrant on_disk", "2026-06-19", "30m-warm")
    rows += rows_static()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="re-parse all source files and upsert the catalog (else render from existing)")
    args = ap.parse_args()

    if args.rebuild:
        rows = collect_all_rows()
        cat, n = merge_into_catalog(rows)
        CATALOG_JSON.write_text(json.dumps(cat, indent=2))
        print(f"catalog upserted: {n} metrics added/updated, {len(cat['metrics'])} total")
    else:
        cat = load_catalog()
        if not cat.get("metrics"):
            print("catalog empty — run with --rebuild first")
            return

    pres = {"generated": cat.get("generated"), "git_commit": cat.get("git_commit"),
            "metrics": cat.get("metrics")}
    date = dt.datetime.utcnow().strftime("%Y%m%d")
    pres_path = EVAL / PRESENTATION_JSON_TMPL.format(date=date)
    pres_path.write_text(json.dumps(pres, indent=2))

    PRESENTATION_MD.parent.mkdir(parents=True, exist_ok=True)
    PRESENTATION_MD.write_text(render_presentation_md(cat, pres))
    CATALOG_MD.write_text(render_catalog_md(cat))
    print(f"wrote {pres_path.relative_to(REPO_ROOT)}")
    print(f"wrote {PRESENTATION_MD.relative_to(REPO_ROOT)}")
    print(f"wrote {CATALOG_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
