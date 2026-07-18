#!/usr/bin/env python3
"""Off-BMP quality gate: does BMP's 8-bit ×70 quantization change SPLADE ranking
vs Qdrant's raw f32?

This isolates the ONLY thing that differs between the two sparse engines when they
score the same precomputed SPLADE vectors over the same docs:

  - BMP (`bmp.Searcher`):   doc impact  = min(255, max(1, round(w*70)))   [builder.py:213]
                            query impact = max(1, round(w*70)) over top-64 [retriever.py:475-476]
  - Qdrant (on_disk sparse): doc value   = raw f32 weight
                            query value  = raw f32 weight (same top-64 term set)

Everything else favors Qdrant: its sparse search is an EXACT posting-list dot
product, while BMP is block-max *approximate* (WAND pruning) — so on recall Qdrant
can only match or beat BMP. The residual risk is therefore purely "does ×70 8-bit
rounding reorder the top-k?", and that is corpus-size-independent: proving it on a
real N-doc sample generalizes to 150M.

Method: load N real docs (sparse_field) from spool_backup into two CSR matrices
sharing one sparsity pattern (f32 values vs ×70-clamped int values). Score the 40
diverse eval queries against the pool both ways, top-50 each, and compare:
  - overlap@10 / overlap@50          (set agreement of the returned ids)
  - Kendall-tau over the union top-50 (ordering agreement)
  - NDCG@10 under each scoring, from the LLM-judge cache, where judged W-ids land
    in the pool (the DELTA is valid even when absolute coverage is low, since both
    scorings see the identical pool).

Token space matches the Qdrant ingest exactly: every token -> its bert-base-uncased
vocab id (the same bijection scripts/archive/spike_qdrant_sparse.py uses).

Usage:
  scripts/eval_quant_fidelity.py --n 500000 --queries 40 \
      --output data/eval_results/quant_fidelity.json

  # Workstream B1: score the f32 (Qdrant) leg against the LIVE production index
  # (the exact serving collection) instead of an in-memory recompute, so the gate
  # uses the real index. TRUE head-to-head: Qdrant returns the live top-cand hits
  # with their STORED f32 vectors (with_vectors=True); we score the query against
  # those SAME docs BOTH as raw f32 (Qdrant's exact scoring) AND as BMP ×70 8-bit
  # (min(255,max(1,round(w*70))) doc + max(1,round(w*70)) query) — isolating the
  # quantization-reordering risk on the live index's own retrieved set.
  # Corpus-size-independent, so a 30M-style pool scan is NOT required; --n is
  # unused in live mode (kept for arg compatibility). Requires a running Qdrant.
  scripts/eval_quant_fidelity.py --live-qdrant \
      --qdrant-collection splade_150m --queries 40 \
      --output data/eval_results/quant_fidelity_live_150m.json
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("quant_fidelity")

QUANT_SCALE = 70          # builder.QUANT_SCALE / retriever.QUANT_SCALE
BMP_IMPACT_MAX = 255      # builder.BMP_IMPACT_MAX (8-bit cap)
SPLADE_QUERY_TERMS = 64   # retriever.SPLADE_QUERY_TERMS
SPOOL = REPO_ROOT / "data" / "thinclient_index" / "spool_backup"
QUERIES_JSON = REPO_ROOT / "data" / "eval_results" / "diverse_queries.json"
JUDGE_CACHE = REPO_ROOT / "data" / "eval_results" / "llm_judge_cache.json"
SPLADE_MODEL = str(REPO_ROOT / "models" / "splade_onnx")


def _vocab():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("bert-base-uncased")
    v = tok.get_vocab()
    logger.info("loaded bert-base-uncased vocab (%d tokens)", len(v))
    return v


def _load_pool(n: int, vocab: dict, judged_wids: set, harvest_scan: int):
    """Stream spool_backup -> (wids, CSR f32, CSR quant) sharing one sparsity
    pattern. quant = min(255, max(1, round(w*70))), matching the BMP build.

    The pool = the first `n` docs (a realistic competition set) PLUS every doc
    whose W-id is in the LLM-judge cache encountered within the first
    `harvest_scan` docs — so judged docs actually compete in the ranking and the
    head-to-head NDCG@10 is meaningful, not coverage-starved."""
    import zstandard
    slices = sorted(glob.glob(str(SPOOL / "*" / "slice_*.jsonl.zst")))
    if not slices:
        raise SystemExit(f"no spool slices under {SPOOL}")
    V = max(vocab.values()) + 1
    wids: list[str] = []
    indptr = [0]
    indices: list[int] = []
    data_f32: list[float] = []
    data_q: list[int] = []
    dctx = zstandard.ZstdDecompressor()
    scanned = kept = harvested = 0
    added: set[str] = set()
    t0 = time.perf_counter()
    for sl in slices:
        for_break = False
        with open(sl, "rb") as fh, dctx.stream_reader(fh) as r:
            for line in io.TextIOWrapper(r, encoding="utf-8"):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                sf = rec.get("sparse_field")
                wid = rec.get("openalex_id") or rec.get("id")
                if not sf or not wid:
                    continue
                scanned += 1
                is_random = kept < n
                is_judged = wid in judged_wids and wid not in added
                if not (is_random or is_judged):
                    if scanned >= harvest_scan and kept >= n:
                        for_break = True
                        break
                    continue
                row_n = 0
                for tok, w in sf.items():
                    if w <= 0:
                        continue
                    i = vocab.get(tok)
                    if i is None:
                        continue
                    indices.append(i)
                    data_f32.append(float(w))
                    data_q.append(min(BMP_IMPACT_MAX, max(1, int(round(float(w) * QUANT_SCALE)))))
                    row_n += 1
                if row_n == 0:
                    continue
                wids.append(wid)
                added.add(wid)
                indptr.append(len(indices))
                kept += 1
                if is_judged:
                    harvested += 1
                if kept % 100000 == 0:
                    logger.info("  kept %d docs (scanned %d, %d judged-harvested, %.0f/s)",
                                kept, scanned, harvested, scanned / (time.perf_counter() - t0))
                if scanned >= harvest_scan and kept >= n:
                    for_break = True
                    break
        if for_break:
            break
    logger.info("harvested %d judged docs into pool", harvested)
    indptr = np.asarray(indptr, dtype=np.int64)
    indices = np.asarray(indices, dtype=np.int32)
    D_f32 = sp.csr_matrix((np.asarray(data_f32, dtype=np.float32), indices, indptr),
                          shape=(len(wids), V))
    D_q = sp.csr_matrix((np.asarray(data_q, dtype=np.float32), indices, indptr),
                        shape=(len(wids), V))
    logger.info("pool: %d docs, %d nnz, vocab dim %d, %.1fs",
                len(wids), len(indices), V, time.perf_counter() - t0)
    return np.asarray(wids), D_f32, D_q, V


def _load_queries(n: int):
    recs = json.loads(QUERIES_JSON.read_text())
    seen, qs = set(), []
    for rec in recs:
        p = rec["paraphrase"]
        if p in seen:
            continue
        seen.add(p)
        qs.append(p)
        if len(qs) >= n:
            break
    return qs


def _load_judge():
    """cache key 'query[:80]||W-id' -> grade. Return {qprefix: {wid: grade}}."""
    cache = json.loads(JUDGE_CACHE.read_text())
    by_q: dict[str, dict[str, int]] = {}
    for k, g in cache.items():
        pre, _, wid = k.rpartition("||")
        if not wid:
            continue
        by_q.setdefault(pre, {})[wid] = int(g)
    return by_q


def _ndcg_at_k(ranked_wids, judged: dict[str, int], k: int = 10):
    """Exponential-gain NDCG@k (TREC), matching eval_thinclient_parity.ndcg_at_k:
    unjudged docs contribute 0 but hold their slot; iDCG from the judged pool."""
    if not judged:
        return None
    dcg = 0.0
    for i, wid in enumerate(ranked_wids[:k]):
        g = judged.get(wid)
        if g:
            dcg += (2 ** g - 1) / math.log2(i + 2)
    ideal = sorted(judged.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal) if g)
    if idcg == 0:
        return None
    return dcg / idcg


def _kendall_tau_union(rank_a, rank_b):
    """Kendall-tau over the union of the two top-k lists; missing docs get rank=len."""
    from scipy.stats import kendalltau
    union = list(dict.fromkeys(list(rank_a) + list(rank_b)))
    pa = {w: i for i, w in enumerate(rank_a)}
    pb = {w: i for i, w in enumerate(rank_b)}
    big = len(union)
    a = [pa.get(w, big) for w in union]
    b = [pb.get(w, big) for w in union]
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None
    tau, _ = kendalltau(a, b)
    return tau


def _qdrant_top_live(client, collection, idx, val, topk):
    """Query the LIVE Qdrant collection (the exact production index) for the f32
    top-k ranking AND fetch each hit's stored f32 vector (with_vectors=True), so
    the in-memory BMP-quant scoring and the Qdrant f32 scoring run over the
    IDENTICAL doc universe (the live hits). No full-collection scroll: the f32
    leg is scored by the real index and its stored weights are fetched per-hit
    (≤ topk point retrievals per query, O(1) in corpus size).

    Returns (ranked_wids, scored, f32vec) where f32vec is {oaid: {tok: weight}}."""
    from qdrant_client import models
    res = client.query_points(
        collection_name=collection,
        query=models.SparseVector(indices=idx, values=val),
        using="splade", limit=topk, with_payload=True, with_vectors=True)
    wids, scored, f32vec = [], [], {}
    for p in res.points:
        oaid = (p.payload or {}).get("oaid")
        if not oaid:
            continue
        wids.append(oaid)
        scored.append((oaid, float(p.score)))
        vec = (p.vector or {}).get("splade")
        if vec:
            f32vec[oaid] = dict(zip(vec.indices, vec.values))
    return wids, scored, f32vec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500_000, help="random docs in the pool")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--topk", type=int, default=50)
    ap.add_argument("--harvest-scan", type=int, default=5_000_000,
                    help="scan this many docs to harvest judged docs into the pool")
    ap.add_argument("--output", default=str(REPO_ROOT / "data/eval_results/quant_fidelity.json"))
    ap.add_argument("--live-qdrant", action="store_true",
                    help="score the f32 (Qdrant) leg against the LIVE production "
                         "collection instead of an in-memory recompute — uses the "
                         "exact serving index (Workstream B1). Requires --qdrant-url.")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--qdrant-collection", default="splade_150m")
    args = ap.parse_args()

    from lib.opensearch_retriever import encode_splade
    live_client = None
    live_pts = 0
    if args.live_qdrant:
        from qdrant_client import QdrantClient
        live_client = QdrantClient(url=args.qdrant_url, timeout=120)
        info = live_client.get_collection(args.qdrant_collection)
        live_pts = int(info.points_count or 0)
        logger.info("LIVE QDRANT mode: collection=%s points=%s status=%s "
                    "(f32 leg = exact production index, not in-memory recompute)",
                    args.qdrant_collection, info.points_count, info.status)

    vocab = _vocab()
    queries = _load_queries(args.queries)
    judge = _load_judge()
    # union of judged W-ids across the selected queries -> harvest these into the pool
    judged_wids: set[str] = set()
    for q in queries:
        judged_wids |= set(judge.get(q[:80], {}).keys())
    logger.info("queries=%d judge-prefixes=%d judged-wids-for-these-queries=%d",
                len(queries), len(judge), len(judged_wids))
    # The in-memory pool is only needed for the non-live f32 path. Live mode
    # scores against the LIVE index's own retrieved set, so skip the (multi-GB,
    # minutes-long) spool scan entirely.
    if args.live_qdrant:
        V = max(vocab.values()) + 1
        wids, D_f32, D_q = np.asarray([]), None, None
        wid_set = set()
        logger.info("live mode: skipping in-memory pool scan (V=%d)", V)
    else:
        wids, D_f32, D_q, V = _load_pool(args.n, vocab, judged_wids, args.harvest_scan)
        wid_set = set(wids.tolist())

    per_q = []
    for q in queries:
        wt = encode_splade(q, SPLADE_MODEL)
        if not wt:
            continue
        top = sorted(wt.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]
        qf = np.zeros(V, dtype=np.float32)
        qq = np.zeros(V, dtype=np.float32)
        qidx, qval = [], []   # raw f32 query terms (for the live Qdrant call)
        for tok, w in top:
            i = vocab.get(tok)
            if i is None:
                continue
            qf[i] = float(w)
            qq[i] = max(1, int(round(float(w) * QUANT_SCALE)))
            qidx.append(int(i)); qval.append(float(w))

        kk = args.topk
        if args.live_qdrant:
            # TRUE head-to-head on the LIVE index's own retrieved set: fetch the
            # live top-kk hits' stored f32 vectors, score the query against them
            # BOTH as raw f32 (Qdrant's exact scoring) AND as BMP ×70 8-bit-quant
            # (min(255,max(1,round(w*70))) on doc + max(1,round(w*70)) on query
            # top-64 — the BMP build path). Same docs, same sparsity → the
            # comparison isolates EXACTLY the quantization-reordering risk on the
            # live production index's hits (corpus-size-independent by construction).
            cand = max(kk * 4, 200)   # over-fetch so quant-reordered docs compete
            live_wids, _, f32vec = _qdrant_top_live(
                live_client, args.qdrant_collection, qidx, qval, cand)
            if not live_wids:
                logger.warning("live Qdrant returned no hits for query — skipping")
                continue
            # universe = the live hits that returned a stored vector.
            uni = np.asarray([w for w in live_wids if w in f32vec], dtype=object)
            if len(uni) == 0:
                logger.warning("no live f32 vectors fetched for query — skipping")
                continue
            indptr_u, indices_u, data_f32, data_q = [0], [], [], []
            for w in uni:
                fv_map = f32vec[w]
                for tok, fv in fv_map.items():
                    i = vocab.get(tok)
                    if i is None:
                        continue
                    indices_u.append(i)
                    data_f32.append(float(fv))
                    data_q.append(min(BMP_IMPACT_MAX, max(1.0, round(float(fv) * QUANT_SCALE))))
                indptr_u.append(len(indices_u))
            indptr_u = np.asarray(indptr_u, dtype=np.int64)
            idx_u = np.asarray(indices_u, dtype=np.int32)
            Du_f32 = sp.csr_matrix(
                (np.asarray(data_f32, dtype=np.float32), idx_u, indptr_u),
                shape=(len(uni), V))
            Du_q = sp.csr_matrix(
                (np.asarray(data_q, dtype=np.float32), idx_u, indptr_u),
                shape=(len(uni), V))
            s_f = Du_f32.dot(qf)          # Qdrant exact f32 scoring
            s_q = Du_q.dot(qq)            # BMP ×70 8-bit scoring, SAME docs
            top_f = uni[np.argsort(-s_f, kind="stable")[:kk]].tolist()
            top_q = uni[np.argsort(-s_q, kind="stable")[:kk]].tolist()
        else:
            s_f = D_f32.dot(qf)
            s_q = D_q.dot(qq)
            top_f = wids[np.argsort(-s_f, kind="stable")[:kk]].tolist()
            top_q = wids[np.argsort(-s_q, kind="stable")[:kk]].tolist()
        sf, sq = set(top_f), set(top_q)
        ov10 = len(set(top_f[:10]) & set(top_q[:10])) / 10.0
        ov50 = len(sf & sq) / float(kk)
        tau = _kendall_tau_union(list(top_f), list(top_q))
        judged = judge.get(q[:80], {})
        if args.live_qdrant:
            # In live mode the competition universe is the union (live f32 ∪ pool),
            # not just the spool pool — so judged docs the live index surfaced but
            # that were never in the pool still count toward the head-to-head NDCG.
            judged_in_comp = {w: g for w, g in judged.items()
                              if w in sf or w in sq}
        else:
            judged_in_comp = {w: g for w, g in judged.items() if w in wid_set}
        # NDCG is meaningful only where judged docs actually compete; the
        # f32-vs-quant DELTA is the parity signal.
        ndcg_f = _ndcg_at_k(list(top_f), judged_in_comp, 10)
        ndcg_q = _ndcg_at_k(list(top_q), judged_in_comp, 10)
        per_q.append({
            "query": q[:80], "overlap@10": ov10, "overlap@50": ov50,
            "kendall_tau": tau, "ndcg@10_f32": ndcg_f, "ndcg@10_quant": ndcg_q,
            "n_judged": len(judged), "n_judged_in_pool": len(judged_in_comp),
        })

    def _mean(key, sub=per_q):
        vals = [r[key] for r in sub if r.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else None

    ndcg_sub = [r for r in per_q if r["ndcg@10_f32"] is not None and r["ndcg@10_quant"] is not None]
    summary = {
        "pool_docs": int(len(wids)), "queries": len(per_q),
        "mean_overlap@10": _mean("overlap@10"),
        "mean_overlap@50": _mean("overlap@50"),
        "mean_kendall_tau": _mean("kendall_tau"),
        "ndcg_queries_with_coverage": len(ndcg_sub),
        "mean_ndcg@10_f32": _mean("ndcg@10_f32", ndcg_sub),
        "mean_ndcg@10_quant": _mean("ndcg@10_quant", ndcg_sub),
    }
    if summary["mean_ndcg@10_f32"] is not None:
        summary["ndcg_delta_f32_minus_quant"] = summary["mean_ndcg@10_f32"] - summary["mean_ndcg@10_quant"]
    # Gate (PLAN.md Workstream B1): overlap@10>=0.98, Kendall-τ>=0.97, |NDCGΔ|<=0.005
    gate = {
        "overlap@10": summary["mean_overlap@10"],
        "kendall_tau": summary["mean_kendall_tau"],
        "ndcg_delta": summary.get("ndcg_delta_f32_minus_quant"),
        "thresholds": {"overlap@10_min": 0.98, "kendall_tau_min": 0.97,
                       "ndcg_abs_delta_max": 0.005},
    }
    def _ge(v, thr): return v is not None and v >= thr
    def _le_abs(v, thr): return v is not None and abs(v) <= thr
    gate["pass"] = bool(
        _ge(summary["mean_overlap@10"], 0.98)
        and _ge(summary["mean_kendall_tau"], 0.97)
        and _le_abs(summary.get("ndcg_delta_f32_minus_quant"), 0.005))
    summary["gate"] = gate
    import datetime as _dt
    import subprocess as _sp
    try:
        git_commit = _sp.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True,
                             cwd=str(REPO_ROOT)).stdout.strip()
    except Exception:
        git_commit = None
    # Provenance per the metrics-cataloging procedure (PLAN.md §"Cataloging").
    provenance = {
        "metric": "bmp_vs_qdrant_quant_fidelity",
        "backend": "qdrant-live" if args.live_qdrant else "qdrant-f32-inmemory",
        "scale": ("150m-live" if args.live_qdrant else "%d-pool" % len(wids)),
        "corpus_size": live_pts if args.live_qdrant else int(len(wids)),
        "query_set": "data/eval_results/diverse_queries.json (%d paraphrases)" % len(per_q),
        "eval_script": "scripts/eval_quant_fidelity.py",
        "judge": "data/eval_results/llm_judge_cache.json (reused, no re-judge)",
        "baseline_ref": "data/eval_results/quant_fidelity_30mscan.json",
        "git_commit": git_commit,
        "timestamp": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    out = {"config": vars(args), "provenance": provenance,
           "summary": summary, "per_query": per_q}
    Path(args.output).write_text(json.dumps(out, indent=2))

    logger.info("=" * 64)
    logger.info("QUANT FIDELITY — f32 (Qdrant) vs ×70 8-bit (BMP), %d docs, %d queries",
                len(wids), len(per_q))
    logger.info("rank agreement: overlap@10=%.3f overlap@50=%.3f kendall_tau=%.3f",
                summary["mean_overlap@10"], summary["mean_overlap@50"],
                summary["mean_kendall_tau"] or float("nan"))
    if summary["mean_ndcg@10_f32"] is not None:
        logger.info("NDCG@10 (%d judged-coverage queries): f32=%.4f quant=%.4f delta=%.4f",
                    summary["ndcg_queries_with_coverage"], summary["mean_ndcg@10_f32"],
                    summary["mean_ndcg@10_quant"], summary["ndcg_delta_f32_minus_quant"])
    else:
        logger.info("NDCG@10: no judged docs landed in the pool (rank-agreement is the signal)")
    logger.info("wrote %s", args.output)
    logger.info("=" * 64)


if __name__ == "__main__":
    main()
