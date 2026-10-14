#!/usr/bin/env python3
"""SEISMIC testbed — G6: RRF system-level parity (the load-bearing quality escape).

`docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` G6 (P3, HARD) =
"full-pipeline RRF NDCG@10 within ±0.005 of current stack (0.560), LLM-judged;
degrade paths intact." 0.560 = the qdrant-SPLADE, 34-common-subset mean
(0.5597) of `parity_record_tc_qdrant_20260625_0001.json` — VERIFIED reproduces.

G6 ≠ G2: G2 is the leg-level bar (SEISMIC-vs-Qdrant overlap@10 ≥0.95, strict,
FAILED at 0.479 and proven non-tunable on every index-time pruning lever).
G6 asks whether RRF — rank-fusion, forgiving of candidate divergence — absorbs
the 0.479 leg divergence at the SYSTEM level. A leg at 0.479 overlap can still
RRF-fuse within ±0.005 of the qdrant baseline if the relevant docs appear
somewhere in each leg's top-k. This script measures that.

Methodology (per 03_BENCHMARK_METHODOLOGY, cached-judge regime = the 0.560
regime; `benchmark_llm_judge.py` fresh-Haiku is a separate, not-comparable
regime — see the 03 §3 note this run fixes):
  treatment = RRF_k60(BM25F_leg, SEISMIC_splade_leg)   [SEISMIC over its 2M slice]
  baseline  = RRF_k60(BM25F_leg, Qdrant_splade_leg)     [stored full-corpus record]
Both scored NDCG@10 via llm_judge_cache.json (34-common where both register).

CORPUS-SCOPE HONESTY (the load-bearing caveat, measured 2026-06-27):
the SEISMIC leg is a 2M persona slice (social_sciences) holding only 163 of
3958 (4.1%) judged docs. The SEISMIC leg CAN'T return docs outside its slice.
So three lanes are reported:
  (1) FULL-corpus baseline (unscoped) — the 0.560 regime (39 judged, mean 0.5378).
  (2) SLICE-SCOPED baseline — BM25F+SPLADE filtered to the slice's 2M oaids
      (the honest matched Qdrant-as-sparse-leg-on-this-slice): under-powered
      (~11 judged), NDCG collapsed (relevant docs were outside the slice).
  (3) SEISMIC treatment — SEISMIC leg over its 2M slice + BM25F scoped to slice.
The persona-matched G6 verdict is the PAIRED delta on queries measurable on
BOTH (2) and (3) (same query set, same judge, same BM25F scope). 0.560 is
reported as a DIRECTIONAL full-corpus anchor, NOT the matched bar (persona ≠
full-corpus — scoping to 2M loses 0.83 of the judged docs).

Outputs `data/eval_results/seismic_g6_rrf_persona_2m.json` (03 §3 result-file slot).

Run from repo root (project venv):

    SFU_SPLADE_BACKEND=seismic SFU_SEISMIC_INDEX=/tmp/seismic_testbed/index/social_sciences_2m \\
        .venv/bin/python3 scripts/seismic_testbed/g6_rrf_parity.py \\
        --jsonl /tmp/seismic_testbed/jsonl/social_sciences_social_2m.jsonl \\
        --baseline-record data/eval_results/parity_record_tc_qdrant_20260625_0001.json \\
        --result-file data/eval_results/seismic_g6_rrf_persona_2m.json
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
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("g6")

TOP_K = 50       # RRF leg depth (matches eval_thinclient_parity TOP_K)
NDCG_K = 10
RRF_K = 60       # retriever.py:99
G6_BAR = 0.005   # |Δ| < 0.005 vs the matched baseline
FULL_ANCHOR = 0.560  # full-corpus 34-common qdrant-SPLADE RRF (0.5597) — directional only


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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True,
                    help="the SEISMIC build source jsonl (gives the slice oaid set)")
    ap.add_argument("--baseline-record", required=True,
                    help="stored full-corpus tc parity record (BM25F+SPLADE top-50 per query)")
    ap.add_argument("--index-path", default=None,
                    help="SEISMIC index stem; default SFU_SEISMIC_INDEX env")
    ap.add_argument("--queries", type=int, default=40, help="parity query count")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    # ── 1. slice oaid set (the corpus the SEISMIC leg can return) ────────────
    oaid_set: set[str] = set()
    with open(args.jsonl) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            did = rec.get("id")
            if did:
                oaid_set.add(did)
    log.info("slice oaid set: %d (from %s)", len(oaid_set), args.jsonl)

    # ── 2. SEISMIC treatment leg (load index once) ──────────────────────────
    idx_path = args.index_path or os.environ.get("SFU_SEISMIC_INDEX")
    if not idx_path:
        raise RuntimeError("need --index-path or SFU_SEISMIC_INDEX")
    from lib.thinclient.seismic_backend import SeismicBackend
    sb = SeismicBackend(idx_path, os.environ.get("SFU_SPLADE_MODEL_PATH", "models/splade_onnx_fp16"))
    assert sb.index.len == len(oaid_set), \
        f"SEISMIC index len {sb.index.len} != jsonl oaid set {len(oaid_set)} (wrong slice?)"

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

    # baseline record: query-text -> {bm25f, splade, judge_key} (full-corpus top-50)
    bl_rows = json.load(open(args.baseline_record))["queries"]
    bl_by_q = {r["query"]: r for r in bl_rows}

    # ── 3. run the SEISMIC leg + assemble treatment/baseline RRF per query ──
    per_query = []
    full_bl, scoped_bl, seismic_treat, paired_bl, paired_treat = [], [], [], [], []
    leg_overlap = []
    if queries:
        _ = sb.search(queries[0]["paraphrase"], TOP_K)  # warmup
    for i, rec in enumerate(queries):
        q = rec["paraphrase"]
        jk = rec.get("judge_key", q)
        bl = bl_by_q.get(q)
        if not bl:
            continue

        # SEISMIC SPLADE leg (returns slice-scoped docs by construction)
        s_res = sb.search(q, TOP_K)
        s_ids = [d for d, _ in s_res]

        # BM25F leg: slice-scoped (matched-persona: same corpus both legs see)
        bm_full = bl["bm25f"]              # full-corpus top-50
        sp_full = bl["splade"]             # full-corpus Qdrant SPLADE top-50
        bm_scoped = [d for d in bm_full if d in oaid_set]
        sp_scoped = [d for d in sp_full if d in oaid_set]  # Qdrant SPLADE on the slice

        # three lanes
        rrf_full = rrf([bm_full, sp_full])                 # (1) 0.560 regime
        rrf_scoped_bl = rrf([bm_scoped, sp_scoped])         # (2) matched scoped Qdrant
        rrf_seismic = rrf([bm_scoped, s_ids])               # (3) SEISMIC treatment

        n_full = ndcg_at_k(rrf_full, judge, jk)
        n_scoped = ndcg_at_k(rrf_scoped_bl, judge, jk)
        n_seismic = ndcg_at_k(rrf_seismic, judge, jk)

        ov = overlap(s_ids, sp_scoped, NDCG_K)  # SEISMIC-vs-scoped-Qdrant leg overlap
        leg_overlap.append(ov)

        if n_full is not None:
            full_bl.append(n_full)
        if n_scoped is not None:
            scoped_bl.append(n_scoped)
        if n_seismic is not None:
            seismic_treat.append(n_seismic)
        # paired: queries measurable on BOTH scoped-baseline AND seismic-treatment
        if n_scoped is not None and n_seismic is not None:
            paired_bl.append(n_scoped)
            paired_treat.append(n_seismic)

        per_query.append({
            "query": q, "judge_key": jk,
            "full_baseline_ndcg@10": round(n_full, 4) if n_full is not None else None,
            "scoped_baseline_ndcg@10": round(n_scoped, 4) if n_scoped is not None else None,
            "seismic_treatment_ndcg@10": round(n_seismic, 4) if n_seismic is not None else None,
            "seismic_leg_n": len(s_ids),
            "scoped_qdrant_leg_n": len(sp_scoped),
            "scoped_bm25f_leg_n": len(bm_scoped),
            "leg_overlap@10": round(ov, 4),
            "seismic_top10": s_ids[:NDCG_K],
            "scoped_qdrant_top10": sp_scoped[:NDCG_K],
        })
        if (i + 1) % 5 == 0 or i == len(queries) - 1:
            log.info("[%d/%d] seismic-measurable=%d scoped-baseline-measurable=%d paired=%d",
                     i + 1, len(queries), len(seismic_treat), len(scoped_bl), len(paired_bl))

    # ── 4. verdict ───────────────────────────────────────────────────────────
    # HONEST verdict logic — three failure modes that would otherwise ship a
    # false "PASS", all forbidden by the CLAUDE.md efficacy rule:
    #  (a) under-powered: too few paired queries; the ±0.005 bar is below the
    #      SEM of the mean delta → the delta is noise, not signal.
    #  (b) degenerate baseline: the matched-Qdrant leg is a client-side id-filter
    #      of the full-corpus top-50, NOT a real slice search. When it returns
    #      only 1-6 docs/query, SEISMIC's 50 dominate RRF and ov@10 collapses to
    #      1.0 everywhere — the comparison measures SEISMIC vs (mostly) SEISMIC.
    #  (c) a real PASS requires the bar to hold AND the comparison non-degenerate
    #      AND the noise floor below the bar.
    paired_delta = (avg(paired_treat) - avg(paired_bl)) if paired_treat and paired_bl else None
    paired_diffs = [paired_treat[i] - paired_bl[i] for i in range(len(paired_treat))]
    sem_delta = (statistics.stdev(paired_diffs) / math.sqrt(len(paired_diffs))
                 if len(paired_diffs) > 1 else 0.0)
    ci95_half = 1.96 * sem_delta

    # degenerate-baseline detector: how many paired queries have a real (>=10-doc)
    # scoped-Qdrant leg? If most are short, the "baseline" isn't a real slice search.
    paired_short_leg = 0
    for r in per_query:
        if (r.get("scoped_baseline_ndcg@10") is not None
                and r.get("seismic_treatment_ndcg@10") is not None):
            if r.get("scoped_qdrant_leg_n", 0) < 10:
                paired_short_leg += 1
    degen_frac = (paired_short_leg / len(paired_bl)) if paired_bl else 1.0
    degenerate = degen_frac > 0.5  # majority of paired legs too short to be a real baseline
    overlap_unity = all(r.get("leg_overlap@10", 0) >= 0.99 for r in [
        r for r in per_query
        if r.get("scoped_baseline_ndcg@10") is not None
        and r.get("seismic_treatment_ndcg@10") is not None]) if paired_bl else True

    within_bar = (paired_delta is not None and abs(paired_delta) < G6_BAR)
    below_noise = (sem_delta > G6_BAR) or (ci95_half > G6_BAR)

    if not paired_treat or not paired_bl:
        verdict = ("G6 UNMEASURABLE — no queries measurable on both the scoped baseline "
                  "and SEISMIC treatment; persona slice judged-doc coverage too low for NDCG.")
    elif degenerate or overlap_unity:
        verdict = ("G6 INCONCLUSIVE (degenerate baseline) — paired Δ=%.4f at n=%d, but the "
                   "matched Qdrant leg is a client-side id-filter of the full-corpus top-50 "
                   "(%.0f%% of paired queries have <10 scoped-Qdrant docs), so SEISMIC's 50 "
                   "dominate RRF (ov@10 collapses to 1.0). The comparison measures SEISMIC "
                   "vs (mostly) SEISMIC, NOT SEISMIC vs Qdrant. A real G6 verdict needs "
                   "Qdrant searching the slice collections directly (or a full-corpus run)."
                   % (paired_delta, len(paired_bl), 100 * degen_frac))
    elif below_noise:
        verdict = ("G6 INCONCLUSIVE (under-powered) — paired Δ=%.4f at n=%d, but SEM(Δ)=%.4f "
                   "(95%% CI ±%.4f) exceeds the ±%.3f bar, so the delta is noise not signal. "
                   "Persona slice (social_sciences 2M) holds ~4%% of judged docs → too few "
                   "paired queries for a ±0.005 verdict at persona scale."
                   % (paired_delta, len(paired_bl), sem_delta, ci95_half, G6_BAR))
    elif within_bar:
        verdict = ("G6 PASS — paired |Δ|=%.4f < %.3f (n=%d, non-degenerate, SEM=%.4f below bar)"
                   % (abs(paired_delta), G6_BAR, len(paired_bl), sem_delta))
    else:
        verdict = ("G6 FAIL — paired |Δ|=%.4f >= %.3f (n=%d, non-degenerate, SEM=%.4f)"
                   % (abs(paired_delta), G6_BAR, len(paired_bl), sem_delta))

    summary = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.4.0",
                 "comparison": "G6: RRF(BM25F, seismic_splade) vs RRF(BM25F, qdrant_splade), "
                               "social_sciences 2M persona slice, paired 34-common",
                 "built_utc": "2026-06-27",
                 "params": {"rrf_k": RRF_K, "top_k": TOP_K, "ndcg_k": NDCG_K,
                            "seismic_index": idx_path,
                            "slice_jsonl": args.jsonl, "queries": len(queries)},
                 "purpose": "G6 system-level RRF parity (bar |Δ|<0.005 persona-matched)",
                 "provenance": "0.560 = qdrant-SPLADE 34-common (0.5597); cached judge regime"},
        "full_corpus_baseline": {"n_judged": len(full_bl), "mean_ndcg@10": avg(full_bl),
                                 "note": "the 0.560 regime (all-39 headline 0.5378; 34-common 0.5597)"},
        "scoped_baseline": {"n_judged": len(scoped_bl), "mean_ndcg@10": avg(scoped_bl),
                            "note": "matched Qdrant-as-sparse-leg on the slice — under-powered"},
        "seismic_treatment": {"n_judged": len(seismic_treat), "mean_ndcg@10": avg(seismic_treat)},
        "paired": {"n": len(paired_bl),
                   "baseline_mean": avg(paired_bl), "treatment_mean": avg(paired_treat),
                   "delta": round(paired_delta, 4) if paired_delta is not None else None,
                   "sem_delta": round(sem_delta, 4),
                   "ci95_half": round(ci95_half, 4),
                   "bar": f"|Δ|<{G6_BAR}", "pass": within_bar and not (below_noise or degenerate or overlap_unity),
                   "degenerate_baseline": degenerate,
                   "degenerate_frac": round(degen_frac, 3),
                   "overlap_unity": overlap_unity},
        "honesty_caveats": {
            "below_noise": below_noise,
            "degenerate_baseline": degenerate,
            "overlap_unity": overlap_unity,
            "note": ("PASS only if within_bar AND non-degenerate AND noise floor below the "
                     "bar. A raw within-bar Δ at under-powered n or with a degenerate "
                     "client-filtered baseline is NOT a pass (CLAUDE.md efficacy rule).")},
        "leg_overlap@10_seismic_vs_scoped_qdrant": {"mean": avg(leg_overlap),
                                                    "note": "context: G2's 0.479 was vs full-corpus Qdrant"},
        "g6_verdict": verdict,
        "per_query": per_query,
    }
    log.info("full baseline: %s | scoped baseline: %s | seismic: %s | paired n=%d Δ=%s",
             avg(full_bl), avg(scoped_bl), avg(seismic_treat), len(paired_bl),
             round(paired_delta, 4) if paired_delta is not None else "n/a")
    log.info("G6: %s", verdict)

    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_g6_rrf_persona_{int(time.time())}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"g6_verdict": verdict,
                      "paired_n": len(paired_bl),
                      "paired_delta": round(paired_delta, 4) if paired_delta is not None else None,
                      "seismic_treatment_mean": avg(seismic_treat),
                      "scoped_baseline_mean": avg(scoped_bl),
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
