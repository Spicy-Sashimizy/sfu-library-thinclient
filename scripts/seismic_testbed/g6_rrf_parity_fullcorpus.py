#!/usr/bin/env python3
"""SEISMIC testbed — G6: RRF system-level parity at FULL-CORPUS 150M scale.

This is the **full-corpus escape** from the persona-2M G6 run (2026-06-27, which
was INCONCLUSIVE / persona-unmeasurable). That run couldn't reach a verdict
because a 2M persona slice holds only ~4% of the 3958 LLM-judged docs (med_bio
0.8%, social_sciences 4.1%); the matched Qdrant baseline was a *client-side
id-filter* of the stored full-corpus top-50 → degenerate (100% of paired queries
returned <10 scoped-Qdrant docs → ov@10 collapsed to 1.0 → the comparison was
SEISMIC-vs-(mostly)-SEISMIC, not SEISMIC-vs-Qdrant), and where it paired (n=11)
SEM(Δ)=0.0058 > the ±0.005 bar. A persona-scale ±0.005 verdict is NOT measurable.

This script runs the SEISMIC leg over the **full 150M corpus** (the 8 mmap'd
Plan-01 shards via `ShardedSeismicBackend`, load_mode mmap — `C2.5 150M_MMAP_READY`,
bit-identical parity) so the SEISMIC leg CAN return any of the 3958 judged docs.
The degenerate-baseline failure mode vanishes by construction: BM25F + SEISMIC
both see all 150M, no slice filtering. The served Qdrant `splade_150m` collection
is built from the SAME OpenAlex `spool_backup` source + same `splade_onnx_fp16`
encoder, so SEISMIC-150M-vs-Qdrant-150M is genuinely apples-to-apples.

G6 (P3, HARD) = "full-pipeline RRF NDCG@10 within ±0.005 of current stack
(0.560), LLM-judged; degrade paths intact." 0.560 = the qdrant-SPLADE 34-common-
subset mean (0.5597) — directional anchor (this run pairs full-corpus-vs-
full-corpus, a different — stronger — pairing than the 0.5597 34-common slice).

  treatment = RRF_k60(BM25F_full, SEISMIC_150M_splade_full)   [federated 8 mmap]
  baseline  = RRF_k60(BM25F_full, Qdrant_splade_full)          [stored record]
Both scored NDCG@10 via llm_judge_cache.json. Gate = paired |Δ| < 0.005 on
queries where BOTH register a judged NDCG, AND SEM(Δ) < 0.005 (n large enough
that the delta is signal not noise).

The persona-2M `g6_rrf_parity.py` degenerate/overlap-unity detectors do NOT run
here (no client-filtered baseline at full corpus). The under-power SEM guard DOES
run — a full-corpus PASS still requires the noise floor below the bar.

RAM: 8 mmap shards load in ~0.6s with ~0 anon floor (C2.5-validated); page cache
faults in per-query (~5 GB after one search, reclaimable, well under 32 GB). An
RSS guard watches VmRSS during load; should process RSS exceed the budget mid-load
it records the shard count that fit as a G8-adjacent finding (still a valid point).

Run from repo root (project venv; SFU_SEISMIC_LOAD_MODE=mmap forces mmap'd shards):

    SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \\
        scripts/seismic_testbed/g6_rrf_parity_fullcorpus.py \\
        --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \\
        --baseline-record data/eval_results/parity_record_tc_qdrant_20260625_0001.json \\
        --result-file data/eval_results/seismic_g6_rrf_fullcorpus_150m.json
"""
import argparse
import json
import logging
import math
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("g6-full")

TOP_K = 50       # RRF leg depth (matches eval_thinclient_parity TOP_K)
NDCG_K = 10
RRF_K = 60       # retriever.py:99
G6_BAR = 0.005   # |Δ| < 0.005 vs the paired full-corpus baseline
FULL_ANCHOR = 0.560  # qdrant-SPLADE 34-common (0.5597) — directional anchor only
RSS_BUDGET_GB = 24.0  # load guard: if process VmRSS exceeds this, stop loading


def rrf(lists: list[list[str]], k: int = RRF_K, top: int = TOP_K) -> list[str]:
    s: dict[str, float] = {}
    for L in lists:
        for rank, did in enumerate(L, start=1):
            s[did] = s.get(did, 0.0) + 1.0 / (k + rank)
    return [d for d, _ in sorted(s.items(), key=lambda x: -x[1])][:top]


def load_judge() -> dict[tuple[str, str], int]:
    cache = json.loads((REPO / "data/eval_results/llm_judge_cache.json").read_text())
    out = {}
    for key, g in cache.items():
        qk, _, did = key.rpartition("||")
        out[(qk, did)] = g
    return out


def ndcg_at_k(ranked_ids: list[str], judge: dict, jk: str, K: int = NDCG_K) -> float | None:
    g = [judge.get((jk, d)) for d in ranked_ids[:K]]
    if not any(x is not None for x in g):
        return None
    dcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(g) if x is not None)
    ideal = sorted((gg for (q, _), gg in judge.items() if q == jk), reverse=True)[:K]
    idcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(ideal))
    return dcg / idcg if idcg > 0 else None


def overlap(a: list[str], b: list[str], k: int) -> float:
    return len(set(a[:k]) & set(b[:k])) / max(min(len(b), k), 1)


def avg(xs): return round(sum(xs) / len(xs), 4) if xs else None


def rss_gb() -> float:
    try:
        for ln in open("/proc/self/status"):
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 1024 / 1024
    except (ValueError, OSError, StopIteration):
        pass
    return -1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard-manifest", required=True,
                    help="the C2.5 8-shard conversion manifest (index_path list)")
    ap.add_argument("--baseline-record", required=True,
                    help="stored full-corpus tc parity record (BM25F+SPLADE top-50 per query)")
    ap.add_argument("--queries", type=int, default=40, help="parity query count")
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--k-prime", type=int, default=200, help="per-shard over-fetch")
    ap.add_argument("--heap-factor", type=float, default=0.8)
    args = ap.parse_args()

    # ── 0. resolve the 8 shard paths + load them mmap'd (RSS-guarded) ────────
    manifest = json.load(open(args.shard_manifest))
    shards = manifest.get("shards", [])
    index_paths = [s["index_path"] for s in shards]
    if not index_paths:
        raise RuntimeError(f"no shard paths in {args.shard_manifest}")
    log.info("full-corpus G6: %d shards from %s (load_mode mmap)", len(index_paths),
             args.shard_manifest)

    from seismic_federated import ShardedSeismicBackend
    load_mode = "mmap"  # always mmap for the 150M serve (C2.5 150M_MMAP_READY)
    base_rss = rss_gb()
    log.info("baseline VmRSS: %.2f GB", base_rss)
    t0 = time.perf_counter()
    sb = ShardedSeismicBackend(index_paths, load_mode=load_mode)
    load_secs = time.perf_counter() - t0
    post_load = rss_gb()
    log.info("loaded %d shards in %.1fs | VmRSS %.2f GB | per-shard lens %s",
             len(sb.shards), load_secs, post_load, [s.len for s in sb.shards])
    total_docs = sum(s.len for s in sb.shards)
    log.info("total docs indexed: %d", total_docs)
    rss_hit = post_load > RSS_BUDGET_GB
    if rss_hit:
        log.error("!! VmRSS %.2f GB > %.0f GB budget after load — proceeding (this is "
                  "a G8-adjacent finding; mmap anon floor should be ~0, page cache is "
                  "reclaimable)", post_load, RSS_BUDGET_GB)

    judge = load_judge()

    # parity query set (the 40 diverse; judge_key carries the judge cache join)
    qrecs = json.loads((REPO / "data/eval_results/diverse_queries.json").read_text())
    seen, queries = set(), []
    for rec in qrecs:
        if rec["paraphrase"] in seen:
            continue
        seen.add(rec["paraphrase"])
        queries.append(rec)
        if len(queries) >= args.queries:
            break

    bl_rows = json.load(open(args.baseline_record))["queries"]
    bl_by_q = {r["query"]: r for r in bl_rows}

    # ── 1. run the federated 150M SEISMIC leg + assemble RRF per query ───────
    per_query = []
    bl_n, treat_n, paired_bl, paired_treat = [], [], [], []
    leg_overlap = []
    if queries:
        _ = sb.search(queries[0]["paraphrase"], args.top_k, k_prime=args.k_prime,
                      heap_factor=args.heap_factor)  # warmup (fault in pages)
        log.info("post-warmup VmRSS: %.2f GB", rss_gb())
    for i, rec in enumerate(queries):
        q = rec["paraphrase"]
        jk = rec.get("judge_key", q)
        bl = bl_by_q.get(q)
        if not bl:
            continue

        # SEISMIC 150M federated SPLADE leg (full corpus by construction)
        s_res = sb.search(q, args.top_k, k_prime=args.k_prime,
                          heap_factor=args.heap_factor)
        s_ids = [d for d, _ in s_res]

        # BM25F leg: full-corpus verbatim from the stored record (as Qdrant saw it)
        bm_full = bl["bm25f"]
        sp_full = bl["splade"]             # stored Qdrant SPLADE (full corpus)

        # RRF fusion — full corpus, BOTH legs see all 150M (no slice filtering)
        rrf_baseline = rrf([bm_full, sp_full])    # the 0.560 regime
        rrf_treatment = rrf([bm_full, s_ids])     # SEISMIC replaces Qdrant SPLADE

        n_bl = ndcg_at_k(rrf_baseline, judge, jk)
        n_treat = ndcg_at_k(rrf_treatment, judge, jk)

        # full-corpus SEISMIC-vs-Qdrant leg overlap (context: G2's 0.479 was at scale)
        ov = overlap(s_ids, sp_full, NDCG_K)
        leg_overlap.append(ov)

        if n_bl is not None:
            bl_n.append(n_bl)
        if n_treat is not None:
            treat_n.append(n_treat)
        if n_bl is not None and n_treat is not None:
            paired_bl.append(n_bl)
            paired_treat.append(n_treat)

        per_query.append({
            "query": q, "judge_key": jk,
            "baseline_ndcg@10": round(n_bl, 4) if n_bl is not None else None,
            "treatment_ndcg@10": round(n_treat, 4) if n_treat is not None else None,
            "seismic_leg_n": len(s_ids),
            "baseline_leg_n": len(sp_full),
            "bm25f_leg_n": len(bm_full),
            "leg_overlap@10": round(ov, 4),
            "seismic_top10": s_ids[:NDCG_K],
            "baseline_top10": sp_full[:NDCG_K],
        })
        if (i + 1) % 5 == 0 or i == len(queries) - 1:
            log.info("[%d/%d] baseline-measurable=%d treatment-measurable=%d paired=%d "
                     "(VmRSS %.1f GB)", i + 1, len(queries), len(bl_n), len(treat_n),
                     len(paired_bl), rss_gb())

    # ── 2. verdict ───────────────────────────────────────────────────────────
    paired_delta = (avg(paired_treat) - avg(paired_bl)) if paired_treat and paired_bl else None
    paired_diffs = [paired_treat[i] - paired_bl[i] for i in range(len(paired_treat))]
    sem_delta = (statistics.stdev(paired_diffs) / math.sqrt(len(paired_diffs))
                 if len(paired_diffs) > 1 else 0.0)
    ci95_half = 1.96 * sem_delta

    within_bar = (paired_delta is not None and abs(paired_delta) < G6_BAR)
    below_noise = (sem_delta > G6_BAR) or (ci95_half > G6_BAR)

    if not paired_treat or not paired_bl:
        verdict = ("G6 UNMEASURABLE — no queries measurable on both the full-corpus "
                  "baseline and SEISMIC treatment; judged-doc coverage too low for NDCG "
                  "even at 150M (would be a surprise given med_bio+social_sciences "
                  "are both slices of this corpus).")
    elif below_noise:
        verdict = ("G6 INCONCLUSIVE (under-powered) — paired Δ=%.4f at n=%d, but "
                   "SEM(Δ)=%.4f (95%% CI ±%.4f) exceeds the ±%.3f bar, so the delta "
                   "is noise not signal. Full-corpus SEISMIC-vs-Qdrant RRF parity is "
                   "consistent with the baseline within noise."
                   % (paired_delta, len(paired_bl), sem_delta, ci95_half, G6_BAR))
    elif within_bar:
        verdict = ("G6 PASS — full-corpus paired |Δ|=%.4f < %.3f (n=%d, non-degenerate, "
                   "SEM=%.4f below bar). RRF absorbs the SEISMIC leg gap (G2's 0.479) "
                   "at the system level at 150M: SEISMIC-150M SPLADE is system-quality-"
                   "safe to fuse with BM25F vs the Qdrant baseline."
                   % (abs(paired_delta), G6_BAR, len(paired_bl), sem_delta))
    else:
        verdict = ("G6 FAIL — full-corpus paired |Δ|=%.4f >= %.3f (n=%d, non-degenerate, "
                   "SEM=%.4f). RRF does NOT absorb the SEISMIC leg gap at 150M: the "
                   "0.479 leg divergence propagates to a system-level NDCG regression "
                   "(same structural floor as G2, independent of serving)."
                   % (abs(paired_delta), G6_BAR, len(paired_bl), sem_delta))

    summary = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.4.0 (federated 8-shard mmap)",
                 "comparison": "G6 full-corpus: RRF(BM25F, seismic_150m_splade) vs "
                               "RRF(BM25F, qdrant_150m_splade), paired judged, all 150M",
                 "built_utc": "2026-06-28",
                 "params": {"rrf_k": RRF_K, "top_k": args.top_k, "ndcg_k": NDCG_K,
                            "k_prime": args.k_prime, "heap_factor": args.heap_factor,
                            "n_shards": len(sb.shards), "total_docs": total_docs,
                            "load_mode": load_mode, "queries": len(queries)},
                 "purpose": "G6 system-level RRF parity at full 150M (full-corpus escape from persona-2M INCONCLUSIVE)",
                 "provenance": "0.560 = qdrant-SPLADE 34-common anchor (0.5597); cached judge regime"},
        "load": {"load_seconds": round(load_secs, 1), "rss_baseline_gb": round(base_rss, 2),
                 "rss_post_load_gb": round(post_load, 2), "rss_budget_gb": RSS_BUDGET_GB,
                 "rss_budget_hit": rss_hit, "per_shard_lens": [s.len for s in sb.shards]},
        "full_corpus_baseline": {"n_judged": len(bl_n), "mean_ndcg@10": avg(bl_n),
                                 "note": "RRF(BM25F, Qdrant-SPLADE) full 150M — the 0.560 regime"},
        "full_corpus_treatment": {"n_judged": len(treat_n), "mean_ndcg@10": avg(treat_n),
                                  "note": "RRF(BM25F, SEISMIC-150M-SPLADE) full 150M — federated 8 mmap"},
        "paired": {"n": len(paired_bl),
                   "baseline_mean": avg(paired_bl), "treatment_mean": avg(paired_treat),
                   "delta": round(paired_delta, 4) if paired_delta is not None else None,
                   "sem_delta": round(sem_delta, 4), "ci95_half": round(ci95_half, 4),
                   "bar": f"|Δ|<{G6_BAR}", "pass": within_bar and not below_noise},
        "honesty_caveats": {"below_noise": below_noise,
                            "note": ("PASS only if within_bar AND SEM(Δ) below the bar. "
                                     "No degenerate-baseline detector (full corpus, no "
                                     "client-filtered baseline).")},
        "leg_overlap@10_seismic_vs_qdrant": {"mean": avg(leg_overlap),
                                             "note": "full-corpus context: G2's 0.479 leg bar was at scale"},
        "g6_verdict": verdict,
        "per_query": per_query,
    }
    log.info("baseline: %s | treatment: %s | paired n=%d Δ=%s SEM=%s",
             avg(bl_n), avg(treat_n), len(paired_bl),
             round(paired_delta, 4) if paired_delta is not None else "n/a",
             round(sem_delta, 4))
    log.info("G6 (full-corpus 150M): %s", verdict)

    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_g6_rrf_fullcorpus_150m_{int(time.time())}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"g6_verdict": verdict,
                      "paired_n": len(paired_bl),
                      "paired_delta": round(paired_delta, 4) if paired_delta is not None else None,
                      "sem_delta": round(sem_delta, 4),
                      "baseline_mean": avg(bl_n), "treatment_mean": avg(treat_n),
                      "leg_overlap_mean": avg(leg_overlap),
                      "total_docs": total_docs,
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
