#!/usr/bin/env python3
"""SEISMIC testbed — G2 index-time param sweep (reclaim overlap@10).

The follow-up the G2 FAIL (06_FINDINGS.md, overlap@10 = 0.479 @ default params)
named: "rebuild with n_postings/max_fraction sweep." The 06 diagnosis was
**static index-time pruning**, NOT query-time heap (the heap_factor sweep held
0.517 stable across {0.8, 0.5, 0.0}). C2's floor cure (07 §4.4) made the
G2/G3 tension (§5) moot on the floor axis — bigger-index-for-quality no longer
threatens RAM — so this sweep is unblocked. It answers the dispositive G2
question: is 0.479 the ceiling, or pruning that's too aggressive?

The lever semantics (inverted_index.rs:401-434, `global_threshold_pruning`):
the top `n_postings * dim` postings are selected GLOBALLY, then each
inverted list is capped at `n_postings * max_fraction` docs. Default cap =
3500*1.5 = 5,250 docs/list. Raising `max_fraction` raises the per-list cap
→ fewer hot-list drops → higher recall ceiling. `doc_cut` is the per-block
document-approximation threshold; lowering it forces exact in-block scoring.

**Why max_fraction is INERT (sweep #1, 2026-06-27, bfe6628):** max_fraction only
raises the *per-list cap* while leaving the *global budget* `dim*n_postings`
unchanged → the SAME postings are selected → bit-identical top-10 across configs
(0.4794, peak RSS 2.8→7.9 GB, 3× index-size, zero per-query change). So G2 is NOT
a per-list-cap tuning gap. `n_postings` is the ONLY lever that raises the global
budget itself — it changes *which postings exist at all* — so it's the only lever
that can change which docs get scored into the top-10. This is the n_postings
sweep (sweep #2). The ceiling: measured total corpus postings = idx.nnz =
152,996,652 (2.0M docs × 76.5 nnz/doc, the unpruned forward index), so n_postings
=14,000 → global budget 27,896×14,000 = 390.5M > 153M total → the GLOBAL selection
saturates (every posting selected); the only remaining loss is the per-list cap
(14,000×1.5=21,000) clipping the heaviest lists — which max_fraction already
proved is irrelevant to top-10. So N3 is "as unpruned as any index knob can make
the SEISMIC retriever." If overlap still freezes bit-identical there, the
server-side pruning hypothesis is fully dead and the 0.479 gap is
query-time summary/quantization, not retrievable by any index knob.

**Qdrant memoization (the cost saver):** the Qdrant side is CONSTANT across
configs — same corpus, same SPLADE query vectors, same encoder — so the
top-10 per query is reused from the baseline `seismic_parity_persona_2m.json`
(`qdrant_top10` + `qdrant_ndcg@10` fields). This turns each config point from
a ~8.5-min live-Qdrant run (500k over-fetch @ ~15s/q) into a build (~3 min)
+ 34 SEISMIC-only searches (~5 s). The cached Qdrant numbers came from the
identical scope/filter the live `eval_seismic_parity.py` applies, so they are
directly comparable — no double measurement.

Reuses `eval_seismic_parity.py`'s `load_queries`/`load_judge`/`ndcg_at_k`/
`overlap` so the numbers are bit-comparable to the baseline (R-PARAM:
never tuned to a flattering number — same judge cache, same 34-common bar,
same NDCG_K=10, same SPLADE_QUERY_TERMS=64). Builds with the STANDARD
`SeismicIndex` variant (persona vocab 27,896 < 65K). G2 is a quality gate,
not a RAM gate; the owned Path-A index is the honest measurement surface
here (the mmap move preserves bytes/arithmetic, C2 parity ✓).

Run from repo root (project venv). Background: each rebuild ~3-4 min, the
sweep wall-clock ≈ N_configs × ~4 min. Default lever is max_fraction (sweep #1,
the neg result). Add `--lever n_postings` for sweep #2.

    # sweep #1 (max_fraction, the registered neg result bfe6628)
    .venv/bin/python3 scripts/seismic_testbed/g2_param_sweep.py \
        --jsonl /tmp/seismic_testbed/jsonl/med_bio_2000000.jsonl \
        --baseline data/eval_results/seismic_parity_persona_2m.json \
        --result-file data/eval_results/seismic_g2_param_sweep.json

    # sweep #2 (n_postings — the global-budget lever, the one that can move top-10)
    .venv/bin/python3 scripts/seismic_testbed/g2_param_sweep.py --lever n_postings \
        --jsonl /tmp/seismic_testbed/jsonl/med_bio_2000000.jsonl \
        --baseline data/eval_results/seismic_parity_persona_2m.json \
        --result-file data/eval_results/seismic_g2_npostings_sweep.json
"""
import argparse
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seismic_backend  # noqa: E402
from eval_seismic_parity import (  # noqa: E402
    load_queries, load_judge, ndcg_at_k, overlap, NDCG_K)
SPLADE_QUERY_TERMS = seismic_backend.SPLADE_QUERY_TERMS  # 64, the serving constant

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("seismic_g2_sweep")

B1_OVERLAP_BAR = 0.95  # overlap@10 ≥ 0.95 (matches eval_seismic_parity.py)
TOP_K = 50  # fetch @50, overlap computed @10 (matches baseline)
# SEISMIC MS MARCO best_configs (the G2-baseline defaults). P0 is the anchor
# that reproduces 0.479 to prove the harness is faithful before we trust deltas.
DEFAULTS = dict(n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
                summary_energy=0.4, max_fraction=1.5, doc_cut=15)

# The minimal decisive grid (cheapest informative sweep). Rationale in the
# docstring + 07 §5: max_fraction is THE static-pruning lever; a wide step
# (1.5→5.0, ~3.3× less pruning) tests the single-variable hypothesis cheaply,
# then an aggressive multi-lever point bounds the reachable ceiling (if even
# minimal-loss can't reach 0.95, 0.479 is a fundamental approximation ceiling,
# not a tuning gap). Interpolate only if P3 clears the bar.
SWEEP_GRID = [
    {"name": "P0_baseline", "comment": "anchor — reproduce 0.479 (harness-faithful check)", **DEFAULTS},
    {"name": "P1_mf5.0", "comment": "single diagnosed lever: max_fraction 1.5→5.0 (~3.3× less per-list pruning)",
     "max_fraction": 5.0},
    {"name": "P3_ceiling", "comment": "minimal-loss frontier: max_fraction×6.7 + doc_cut→1 (exact in-block) + summary_energy→0.9 (bigger summaries)",
     "max_fraction": 10.0, "doc_cut": 1, "summary_energy": 0.9},
]

# Sweep #2 (2026-06-27): n_postings. max_fraction proved inert on its own lever
# axis (per-list cap, SAME postings selected → bit-identical 0.4794). n_postings
# is the OTHER axis — it raises the GLOBAL budget `dim*n_postings` and so changes
# which postings exist at all. Two points bracket the reachable: N1 doubles the
# global budget (3500→7000), N3 (14000 → global budget 390.5M) exceeds the measured
# 153M total corpus postings (idx.nnz, the unpruned forward index) → the GLOBAL
# selection saturates (every posting selected); only the per-list cap 14,000*1.5
# =21,000 still clips the heaviest lists — which max_fraction already proved is
# irrelevant to top-10. So N3 is "as unpruned as any index knob can make it."
# P0 anchors harness faithfulness again (must reproduce 0.479). All other params
# held at DEFAULTS (isolates the single lever).
MED_BIO_TOTAL_POSTINGS = 152_996_652  # idx.nnz, the unpruned forward index (2.0M docs × 76.5 nnz/doc)
N_POSTINGS_GRID = [
    {"name": "P0_np3500", "comment": "anchor — reproduce 0.479 n_postings=3500 (= max_fraction-sweep P0; harness-faithful check)", **DEFAULTS},
    {"name": "N1_np7000", "comment": "2× global budget: n_postings 3500→7000 (~2× less global pruning, rest at default)",
     "n_postings": 7000},
    {"name": "N3_np14000", "comment": "ceiling: n_postings 14000 → global budget 390.5M > 153M total postings = GLOBAL selection saturated (unpruned on the selection axis); only per-list cap 21,000 still binds hot lists (proven irrelevant by max_fraction sweep)",
     "n_postings": 14000},
]

GRIDS = {"max_fraction": SWEEP_GRID, "n_postings": N_POSTINGS_GRID}


def load_cached_qdrant(baseline_path: Path) -> dict[str, dict]:
    """{paraphrase: {"qdrant_top10": [...], "qdrant_ndcg": float_or_None}} from
    the baseline run, KEYED BY PARAPHRASE TEXT (the unique per-row id).

    CRITICAL (the 0.309-vs-0.479 drift fix): the baseline ran Qdrant FRESH per
    paraphrase — each of the 34 rows has its OWN qdrant_top10, even the 3
    paraphrases sharing a judge_key (they encode to different SPLADE vectors →
    different Qdrant results). The first sweep attempt keyed the cache by
    judge_key (only 12 entries), pairing rows 1&2 of a group with row 0's
    Qdrant result → systematic overlap collapse (0.309). Keying by paraphrase
    pairs each SEISMIC result with its own Qdrant reference → faithful 0.479.

    The Qdrant side is constant across CONFIGS (same corpus + same query
    vectors), so it's reused across configs instead of re-fetching 500k/q —
    the cost saver. load_queries(34) returns the same 34 paraphrases in the
    same order as the baseline rows (verified 34/34 positional match)."""
    d = json.loads(baseline_path.read_text())
    cache = {}
    for r in d["per_query"]:
        cache[r["query"]] = {
            "qdrant_top10": r["qdrant_top10"],
            "qdrant_ndcg": r.get("qdrant_ndcg@10"),
        }
    assert cache, "baseline had no per-query rows"
    log.info("cached Qdrant top10 for %d paraphrases (keyed by query text) from %s",
             len(cache), baseline_path)
    return cache


def build_index(jsonl: str, params: dict, out_path: str):
    """Build a standard SeismicIndex with the swept params, save to out_path,
    return (idx, build_s, peak_rss_gb, on_disk_gb). Mirrors build_persona_seismic
    params without its G3 space-breakdown capture (this is the G2 quality path)."""
    import seismic
    import resource
    build_cls = seismic.SeismicIndex  # persona vocab 27,896 < 65K → standard
    t0 = time.perf_counter()
    idx = build_cls.build(
        str(jsonl), n_postings=params["n_postings"],
        centroid_fraction=params["centroid_fraction"],
        min_cluster_size=params["min_cluster_size"],
        summary_energy=params["summary_energy"],
        max_fraction=params["max_fraction"], doc_cut=params["doc_cut"],
        num_threads=min(8, os.cpu_count() or 4))
    build_s = time.perf_counter() - t0
    peak_rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    t0 = time.perf_counter()
    idx.save(out_path)
    save_s = time.perf_counter() - t0
    actual = out_path if out_path.endswith(".index.seismic") \
        else out_path + ".index.seismic"
    on_disk_gb = os.path.getsize(actual) / 1e9
    log.info("  build %.1fs + save %.1fs -> %.3f GB | peak RSS %.3f GB",
             build_s, save_s, on_disk_gb, peak_rss_gb)
    return idx, build_s, save_s, peak_rss_gb, on_disk_gb


def eval_one_config(idx, params, queries, judge, qd_cache,
                    heap_factor: float, query_cut) -> dict:
    """Run the 34 SEISMIC-only searches, compute overlap@10 + NDCG vs the
    cached Qdrant top-10. Reusable seismic_backend for identical-compute."""
    class _Be:
        def __init__(self, index, splade_model_path="models/splade_onnx_fp16"):
            import seismic
            import numpy as np
            self._seismic = seismic
            self._np = np
            self.index = index
            self._string_dtype = seismic.get_seismic_string()

        def search(self, query, top_k, query_cut=None, heap_factor=0.8):
            from lib.opensearch_retriever import encode_splade
            sparse = encode_splade(query, "models/splade_onnx_fp16")
            if not sparse:
                return []
            top = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
            tokens = list(top.keys()); values = [float(v) for v in top.values()]
            qc = query_cut if query_cut is not None else len(tokens)
            qcomp = self._np.array(tokens, dtype=self._string_dtype)
            qvals = self._np.array(values, dtype=self._np.float32)
            res = self.index.search(query_id="q", query_components=qcomp,
                                    query_values=qvals, k=top_k, query_cut=qc,
                                    heap_factor=heap_factor)
            return [(doc_id, float(dist)) for (_qid, dist, doc_id) in res]

    be = _Be(idx)
    if queries:
        _ = be.search(queries[0]["paraphrase"], TOP_K,
                     query_cut=query_cut, heap_factor=heap_factor)  # warmup

    rows, s_overlap, s_ndcgs, q_ndcgs, s_lats = [], [], [], [], []
    for i, rec in enumerate(queries):
        q = rec["paraphrase"]; jk = rec.get("judge_key", q)
        t0 = time.perf_counter()
        s_res = be.search(q, TOP_K, query_cut=query_cut, heap_factor=heap_factor)
        s_lat = (time.perf_counter() - t0) * 1000
        s_ids = [d for d, _ in s_res]
        # Qdrant reference is keyed by PARAPHRASE (each row has its own live
        # Qdrant result), not judge_key — see load_cached_qdrant.
        qc_entry = qd_cache.get(q, {"qdrant_top10": [], "qdrant_ndcg": None})
        q_ids = qc_entry["qdrant_top10"]
        ov = overlap(s_ids, q_ids, NDCG_K)
        s_overlap.append(ov)
        s_n = ndcg_at_k(s_ids, judge, jk)
        q_n = qc_entry["qdrant_ndcg"]
        s_lats.append(s_lat)
        common = s_n is not None and q_n is not None
        if common:
            s_ndcgs.append(s_n); q_ndcgs.append(q_n)
        rows.append({"query": q, "judge_key": jk, "common": common,
                     "seismic_top10": s_ids[:NDCG_K], "qdrant_top10": q_ids,
                     "overlap@10": round(ov, 4),
                     "seismic_ndcg@10": round(s_n, 4) if s_n is not None else None,
                     "qdrant_ndcg@10": round(q_n, 4) if q_n is not None else None,
                     "seismic_lat_ms": round(s_lat, 1)})
        if (i + 1) % 8 == 0 or i == len(queries) - 1:
            log.info("    [%d/%d] overlap mean=%.3f", i + 1, len(queries),
                     sum(s_overlap) / len(s_overlap))

    avg = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {
        "overlap@10": {"mean": avg(s_overlap), "n": len(s_overlap), "bar": B1_OVERLAP_BAR,
                       "pass": (avg(s_overlap) or 0) >= B1_OVERLAP_BAR},
        "ndcg@10_common": {"n": len(s_ndcgs), "seismic_mean": avg(s_ndcgs),
                            "qdrant_mean": avg(q_ndcgs),
                            "delta": round(avg(s_ndcgs) - avg(q_ndcgs), 4) if s_ndcgs else None,
                            "bar": "B2 |Δ|<0.005",
                            "pass": (abs(avg(s_ndcgs) - avg(q_ndcgs)) < 0.005) if s_ndcgs else False},
        "seismic_lat_ms": {"p50": avg(sorted(s_lats)[len(s_lats) // 2:]) if len(s_lats) > 1 else (avg(s_lats) if s_lats else None)},
        "per_query": rows,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True, help="spool jsonl the 2M index is built from")
    ap.add_argument("--baseline", required=True,
                    help="seismic_parity_persona_2m.json (Qdrant top-10 reuse cache)")
    ap.add_argument("--index-dir", default="/tmp/seismic_testbed/index",
                    help="where to write the per-config rebuilt indexes")
    ap.add_argument("--heap-factor", type=float, default=0.8,
                    help="SEISMIC query-time heap_factor (baseline=0.8; the FAIL "
                         "was attributed to static pruning, NOT query heap)")
    ap.add_argument("--query-cut", type=int, default=None,
                    help="SEISMIC query_cut (default all 64 — recall-first)")
    ap.add_argument("--lever", choices=("max_fraction", "n_postings"),
                    default="max_fraction",
                    help="which single lever to sweep. max_fraction=#1 (proven inert "
                         "2026-06-27): raises per-list cap, SAME postings selected → "
                         "bit-identical 0.4794. n_postings=#2: raises the GLOBAL budget "
                         "`dim*n_postings` (changes which postings exist at all) — the "
                         "only knob that can move the top-10. N3 saturates the global "
                         "selection (budget > total postings).")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    jsonl = Path(args.jsonl)
    assert jsonl.exists(), f"missing {jsonl}"
    index_dir = Path(args.index_dir); index_dir.mkdir(parents=True, exist_ok=True)
    qd_cache = load_cached_qdrant(Path(args.baseline))
    judge = load_judge()
    queries = load_queries(34)
    sweep_grid = GRIDS[args.lever]
    log.info("lever=%s (%d configs), %d queries, judge has %d (qk,did) pairs; heap_factor=%s query_cut=%s",
             args.lever, len(sweep_grid), len(queries), len(judge),
             args.heap_factor, args.query_cut)

    configs_out = []
    for cfg in sweep_grid:
        name = cfg["name"]
        params = {**DEFAULTS, **{k: v for k, v in cfg.items() if k not in ("name", "comment")}}
        log.info("==== CONFIG %s ==== %s", name, cfg.get("comment", ""))
        log.info("  params: %s", params)
        out_path = str(index_dir / f"med_bio_2m_{name}")
        # clean any stale index so save() can't pick up a partial file
        for suff in ("", ".index.seismic"):
            if os.path.exists(out_path + suff):
                os.remove(out_path + suff)
        idx, build_s, save_s, peak_rss_gb, on_disk_gb = build_index(
            str(jsonl), params, out_path)
        ev = eval_one_config(idx, params, queries, judge, qd_cache,
                             heap_factor=args.heap_factor, query_cut=args.query_cut)
        ov = ev["overlap@10"]["mean"]
        log.info("  %s result: overlap@10=%.3f (bar %.2f) %s", name, ov or 0,
                 B1_OVERLAP_BAR, "PASS" if ev["overlap@10"]["pass"] else "")
        configs_out.append({
            "name": name, "comment": cfg.get("comment", ""), "params": params,
            "build_seconds": round(build_s, 2), "save_seconds": round(save_s, 2),
            "peak_rss_gb": round(peak_rss_gb, 3), "on_disk_gb": round(on_disk_gb, 4),
            "index_path": out_path + ".index.seismic",
            "overlap@10": ev["overlap@10"], "ndcg@10_common": ev["ndcg@10_common"],
            "seismic_lat_ms": ev["seismic_lat_ms"], "per_query": ev["per_query"]})
        # Free the index + GC before the next rebuild keeps peak RAM honest.
        del idx; gc.collect()

    # Verdict logic: the sweep is decisive on its own (don't over-claim).
    # Lever-aware: the n_postings grid only changes which postings exist (a
    # global-budget lever), so unlike max_fraction a real per-query change IS
    # expected if it can move results — bit-identical across N1/N3 is the strong
    # "ceiling, no tuning path" signal there (not just a frozen mean).
    def _bit_identical_to_p0(cfg, p0_cfg):
        """True if cfg's per-query top-10 are identical to the anchor config's.
        A real global-budget change would perturb at least one query's set."""
        if not p0_cfg or not cfg.get("per_query"):
            return False
        p0p = {r["query"]: r["seismic_top10"] for r in p0_cfg.get("per_query", [])}
        if len(p0p) != len(cfg["per_query"]):
            return False
        return all(r["seismic_top10"] == p0p.get(r["query"])
                   for r in cfg["per_query"])

    def _verdict(cfgs):
        by = {c["name"]: c for c in cfgs}
        if args.lever == "n_postings":
            p0 = by.get("P0_np3500", {}).get("overlap@10", {}).get("mean")
            n1 = by.get("N1_np7000", {}).get("overlap@10", {}).get("mean")
            n3 = by.get("N3_np14000", {}).get("overlap@10", {}).get("mean")
            if p0 is not None and abs(p0 - 0.479) > 0.03:
                return (f"HARNESS DRIFT — P0 anchor {p0:.3f} ≠ 0.479; re-check before "
                        "trusting the n_postings deltas.")
            p0c = by.get("P0_np3500", {})
            n3c = by.get("N3_np14000", {})
            if n3 is not None and n3 >= B1_OVERLAP_BAR:
                return (f"G2 RECOVERABLE via n_postings — ceiling N3 overlap@10 {n3:.3f} ≥ "
                        f"{B1_OVERLAP_BAR} (P0 {p0:.3f}); bisect n_postings to the minimal "
                        "config that clears the bar.")
            n3_identical = _bit_identical_to_p0(n3c, p0c)
            n1_identical = _bit_identical_to_p0(by.get("N1_np7000", {}), p0c)
            if n3 is not None:
                if n3_identical and (n1 is None or n1_identical):
                    return (f"G2 CEILING (server-side pruning is NOT the gap) — n_postings "
                            f"raised the global budget to the SELECTION-SATURATED ceiling "
                            f"(N3 budget 390.5M > 153M total postings → every posting selected) "
                            f"yet every per-query top-10 is BIT-IDENTICAL to P0 "
                            f"(P0 {p0:.3f} / N1 {n1:.3f} / N3 {n3:.3f}). The only remaining loss "
                            "is the per-list cap, which the max_fraction sweep already proved is "
                            "irrelevant to top-10. 0.479 is the query-time approximation floor "
                            "(summary-skip + in-block coordinate traversal); no index knob reclaims it.")
                if n3 > (p0 or 0) or (n1 is not None and n1 > (p0 or 0)):
                    return (f"G2 TUNABLE via n_postings — overlap rose (P0 {p0:.3f}→N1 {n1:.3f}"
                            f"→N3 {n3:.3f}, not monotonic-identical) but N3 < "
                            f"{B1_OVERLAP_BAR}: extrapolate n_postings further (deeper budget).")
                return (f"G2 CEILING — n_postings {p0:.3f}→{n1:.3f}→{n3:.3f} frozen < "
                        f"{B1_OVERLAP_BAR} but per-query NOT all identical to P0; 0.479 is a "
                        "local floor on this budget axis but not a bit-identical structural "
                        "ceiling — query-time summary/quantization still the prime suspect.")
            return "G2 INCONCLUSIVE (n_postings) — missing a config result."
        # max_fraction branch (sweep #1, retained): single-lever, monotonically-identical expected
        p0 = by.get("P0_baseline", {}).get("overlap@10", {}).get("mean")
        p1 = by.get("P1_mf5.0", {}).get("overlap@10", {}).get("mean")
        p3 = by.get("P3_ceiling", {}).get("overlap@10", {}).get("mean")
        if p0 is not None and abs(p0 - 0.479) > 0.03:
            return f"HARNESS DRIFT — P0 baseline {p0:.3f} ≠ 0.479; re-check before trusting deltas."
        if p3 is not None and p3 >= B1_OVERLAP_BAR:
            return (f"G2 RECOVERABLE — ceiling config P3 overlap@10 {p3:.3f} ≥ {B1_OVERLAP_BAR}; "
                    "bisect to minimal-loss config (max_fraction/α/doc_cut interpolation).")
        if p3 is not None and p3 > (p1 or 0) and (p1 or 0) > (p0 or 0):
            return (f"G2 TUNABLE-NOT-REACHED — monotonic up (P0 {p0:.3f}→P1 {p1:.3f}→P3 {p3:.3f}) "
                    f"but P3 < {B1_OVERLAP_BAR}; extrapolate max_fraction further (still budget-capped growth).")
        if p3 is not None:
            return (f"G2 CEILING — aggressive minimal-loss P3 ({p3:.3f}) still < {B1_OVERLAP_BAR} "
                    f"(P0 {p0:.3f}), and not monotonic-improving → 0.479 is a structural approximation "
                    "ceiling, not a tuning gap (the SEISMIC-at-2M quality ceiling).")
        return "G2 INCONCLUSIVE — missing a config result."

    verdict = _verdict(configs_out)
    p0_name = "P0_np3500" if args.lever == "n_postings" else "P0_baseline"
    p0_mean = next((c["overlap@10"]["mean"] for c in configs_out if c["name"] == p0_name), None)
    result = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.4.0",
                 "built_utc": "2026-06-27",
                 "comparison": "SEISMIC (2M med_bio, swept index-time params) vs Qdrant top-10 "
                               "CACHED from seismic_parity_persona_2m.json (same corpus/encoder → "
                               "Qdrant side constant across configs). Delta = SEISMIC pruning only.",
                 "params": {"lever": args.lever, "heap_factor": args.heap_factor, "query_cut": args.query_cut,
                            "top_k": TOP_K, "ndcg_k": NDCG_K, "overlap_bar": B1_OVERLAP_BAR,
                            "baseline_overlap": 0.479, "spade_query_terms": SPLADE_QUERY_TERMS},
                 "purpose": {"max_fraction":
                             "G2 sweep #1: per-list-cap lever. PROVEN INERT 2026-06-27 (bfe6628) — "
                             "raising max_fraction changes the SAME-selected postings → bit-identical "
                             "0.4794. Retained as the harness-faithfulness anchor + the negative evidence.",
                             "n_postings":
                             "G2 sweep #2: global-budget lever `dim*n_postings` (the ONLY knob that "
                             "changes which postings exist). Follow-up to the max_fraction inert result. "
                             "N3 hits the unpruned ceiling (budget > total corpus postings). If overlap "
                             "still freezes bit-identical, server-side pruning is NOT the gap "
                             "(query-time summary/quantization is)."}[args.lever]},
        "configs": configs_out,
        "g2_verdict": verdict,
    }
    default_name = (f"data/eval_results/seismic_g2_npostings_sweep.json"
                    if args.lever == "n_postings"
                    else f"data/eval_results/seismic_g2_param_sweep.json")
    rpath = (Path(args.result_file) if args.result_file
             else REPO_ROOT / default_name)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"g2_verdict": verdict,
                      "overlaps": {c["name"]: c["overlap@10"]["mean"] for c in configs_out},
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
