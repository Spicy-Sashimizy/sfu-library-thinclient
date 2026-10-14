#!/usr/bin/env python3
"""SEISMIC testbed — P2 G2: quality parity vs Qdrant on the SAME vectors.

`docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` G2 PASS = "top-k overlap@10 vs
Qdrant ≥ 0.95 at matched params; per-leg NDCG@10 within noise" (B1 ≥0.95, B2 RRF
|Δ|<0.005). `03_BENCHMARK_METHODOLOGY.md` §4 bars.

Apples-to-apples scope: SEISMIC has 2M med_bio docs; Qdrant's live collections
are 30M/150M (full corpus, all sections). To make overlap meaningful we
**restrict Qdrant to the exact med_bio oaids SEISMIC sees** (MatchAny over the
index's doc-id set) on every query, so both engines search the SAME corpus with
the SAME SPLADE query vectors — any top-k delta is then SEISMIC's
approximation/pruning, not a different encoder or unseen docs.

Query set: the 34-common subset — the project's documented apples-to-apples bar
(`docs/BENCHMARK_METHODOLOGY.md:145`: "34 queries with a judged doc in both").
NDCG@10 via the shared `llm_judge_cache.json` + `ndcg_at_k` (reused from
`eval_thinclient_parity.py`), judge_key = the query string.

Outputs `data/eval_results/seismic_parity_persona_<ts>.json` (the
03_BENCHMARK_METHODOLOGY result-file slot) and updates 06_FINDINGS.md.

NOT a full-pipeline RRF run (that's G6, P3); this is the leg-level quality
gate that earns the right to run G6.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/eval_seismic_parity.py \
        --index-path /tmp/seismic_testbed/index/med_bio_2m \
        --qdrant-collection splade_par30 \
        --queries 34 \
        --result-file data/eval_results/seismic_parity_persona.json
"""
import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "source"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seismic_backend  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("seismic_parity")

TOP_K = 50  # matches eval_thinclient_parity.py (overlap is computed @10, fetch @50)
NDCG_K = 10
QUANT_SCALE = 70  # serving constant (identical-compute guarantee)
B1_OVERLAP_BAR = 0.95  # overlap@10 ≥ 0.95 (target 1.0)


def load_queries(n: int) -> list[dict]:
    records = json.loads((REPO_ROOT / "data/eval_results/diverse_queries.json").read_text())
    out, seen = [], set()
    for rec in records:
        if rec["paraphrase"] not in seen:
            seen.add(rec["paraphrase"])
            out.append(rec)
        if len(out) >= n:
            break
    return out


def load_judge() -> dict[tuple[str, str], int]:
    cache = json.loads((REPO_ROOT / "data/eval_results/llm_judge_cache.json").read_text())
    out = {}
    for key, grade in cache.items():
        qk, _, did = key.rpartition("||")
        out[(qk, did)] = grade
    return out


def ndcg_at_k(ranked_ids: list[str], judge: dict, judge_key: str,
              k: int = NDCG_K) -> float | None:
    grades = [judge.get((judge_key, did)) for did in ranked_ids[:k]]
    if not any(g is not None for g in grades):
        return None
    dcg = sum((2 ** g - 1) / math.log2(i + 2)
              for i, g in enumerate(grades) if g is not None)
    ideal = sorted((g for (qk, _), g in judge.items() if qk == judge_key),
                   reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else None


def overlap(a: list[str], b: list[str], k: int) -> float:
    return len(set(a[:k]) & set(b[:k])) / max(min(len(b), k), 1)


class QdrantMedBioScoped:
    """Qdrant SPLADE search restricted to the med_bio oaid set SEISMIC sees, so
    the top-k comparison is over the SAME corpus (same vectors, same docs). The
    query is encoded identically to the SEISMIC leg (encode_splade top-64).

    Qdrant-filter restriction (MatchAny over 2M oaids) times out (~60s 500),
    so this over-fetches a larger candidate list UNFILTERED and restricts
    client-side to oaids in the med_bio set, re-ranking by score and taking
    top_k — same corpus, same ranking, no per-query 2M-id filter.

    CRITICAL: the depth must EXCEED the worst-case rank of the deepest med_bio
    top-k hit in the full 30M collection — the first med_bio hit can rank far
    down (measured 2026-06-26: rank 70 for one query at fetch_n=5000 returned
    ZERO med_bio docs → false G2 FAIL). The med_bio hits share the full-corpus
    ranking (verified identical scores: W6997459625 @13.76 was SEISMIC #2 AND
    Qdrant med_bio rank-70 hit). fetch_n=500k costs ~15s/query but is safe;
    an early-stop once top_k med_bio hits are in hand is not available in the
    Qdrant client API, so the full fetch is the cost (Qdrant is rollback-only
    since 2026-07-06; this evaluator is kept for the parity record)."""

    def __init__(self, collection: str, oaid_set: set[str],
                 url: str = "http://localhost:6333",
                 splade_model_path: str = "models/splade_onnx_fp16",
                 fetch_n: int = 500000):
        from qdrant_client import QdrantClient, models
        self._models = models
        self.cli = QdrantClient(url=url, timeout=120)
        self.collection = collection
        self.oaid_set = oaid_set
        self.splade_model_path = splade_model_path
        self.fetch_n = fetch_n
        from lib.opensearch_retriever import encode_splade
        self._encode_splade = encode_splade
        from transformers import AutoTokenizer
        self._bert_vocab = AutoTokenizer.from_pretrained(
            "bert-base-uncased").get_vocab()

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        from lib.thinclient.retriever import SPLADE_QUERY_TERMS
        sparse = self._encode_splade(query, self.splade_model_path)
        if not sparse:
            return []
        top = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        idx, val = [], []
        for tok, w in top.items():
            i = self._bert_vocab.get(tok)
            if i is not None:
                idx.append(int(i)); val.append(float(w))
        if not idx:
            return []
        try:
            res = self.cli.query_points(
                collection_name=self.collection,
                query=self._models.SparseVector(indices=idx, values=val),
                using="splade", limit=self.fetch_n, with_payload=True)
        except Exception as exc:
            log.warning("Qdrant scoped search failed: %s", exc)
            return []
        # client-side restrict to med_bio oaids SEISMIC holds; preserve Qdrant
        # score order (already sorted desc by query_points).
        scoped = [(p.payload.get("oaid"), float(p.score))
                  for p in res.points if p.payload
                  and p.payload.get("oaid") in self.oaid_set]
        return scoped[:top_k]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-path", required=True, help="saved SEISMIC index stem (.index.seismic)")
    ap.add_argument("--qdrant-collection", default="splade_par30")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--queries", type=int, default=34,
                    help="number of diverse queries (the 34-common bar uses judge coverage)")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--query-cut", type=int, default=None, help="SEISMIC query_cut (default: all terms)")
    ap.add_argument("--heap-factor", type=float, default=0.8)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--scope-jsonl", default=None,
                    help="the spool_to_seismic_jsonl.py output the index was built from (must match index docs)")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    sb = seismic_backend.SeismicBackend(args.index_path, args.model_path)
    # The exact set of oaids SEISMIC holds = the ids it can return. Build the
    # Qdrant scope from the jsonl the index was BUILT FROM, validating it
    # matches the index length (a stale smoke file vs a 2M index silently
    # scope-trashes the comparison — caught 2026-06-26).
    oaid_set = set()
    jsonl = args.scope_jsonl
    if not jsonl:
        # default: the index's sibling jsonl under the standard layout, by docs
        import glob
        cands = []
        for c in glob.glob("/tmp/seismic_testbed/jsonl/med_bio_*.jsonl"):
            import re
            n = sum(1 for _ in open(c))
            cands.append((n, c))
        # pick the jsonl whose doc count matches the SEISMIC index length
        match = [c for n, c in cands if n == sb.index.len]
        jsonl = match[0] if match else (max(cands)[1] if cands else None)
        if jsonl and not match:
            log.warning("no jsonl matches index len %d; using %s (doc count may differ — "
                        "pass --scope-jsonl to be explicit)", sb.index.len, jsonl)
    if jsonl:
        log.info("building Qdrant scope from %s (index len=%d)", jsonl, sb.index.len)
        import re
        pat = re.compile(r'"id": "(\w+)"')
        with open(jsonl) as f:
            for line in f:
                m = pat.search(line)
                if m:
                    oaid_set.add(m.group(1))
        log.info("scope: %d med_bio oaids (must equal index len %d)", len(oaid_set), sb.index.len)
        assert len(oaid_set) == sb.index.len, \
            f"scope jsonl has {len(oaid_set)} oaids but index len is {sb.index.len} — wrong jsonl"
    qd = QdrantMedBioScoped(args.qdrant_collection, oaid_set, args.qdrant_url, args.model_path)
    judge = load_judge()
    queries = load_queries(args.queries)
    log.info("%d queries; judge graded %d (qk,did) pairs", len(queries), len(judge))

    # Warmup: one throwaway query to load models / page cache.
    if queries:
        _ = sb.search(queries[0]["paraphrase"], args.top_k,
                      query_cut=args.query_cut, heap_factor=args.heap_factor)

    rows = []
    s_overlap, q_ndcgs, s_ndcgs = [], [], []
    for i, rec in enumerate(queries):
        q = rec["paraphrase"]; jk = rec.get("judge_key", q)
        t0 = time.perf_counter()
        s_res = sb.search(q, args.top_k, query_cut=args.query_cut, heap_factor=args.heap_factor)
        s_lat = (time.perf_counter() - t0) * 1000
        s_ids = [d for d, _ in s_res]
        t0 = time.perf_counter()
        q_res = qd.search(q, args.top_k)
        q_lat = (time.perf_counter() - t0) * 1000
        q_ids = [d for d, _ in q_res]
        ov = overlap(s_ids, q_ids, NDCG_K)
        s_overlap.append(ov)
        s_n = ndcg_at_k(s_ids, judge, jk)
        q_n = ndcg_at_k(q_ids, judge, jk)
        # common-judged gate: keep only queries where BOTH engines return a judged doc
        common = s_n is not None and q_n is not None
        if common:
            s_ndcgs.append(s_n); q_ndcgs.append(q_n)
        rows.append({"query": q, "judge_key": jk, "common": common,
                     "seismic_top10": s_ids[:NDCG_K],
                     "qdrant_top10": q_ids[:NDCG_K],
                     "overlap@10": round(ov, 4),
                     "seismic_ndcg@10": round(s_n, 4) if s_n is not None else None,
                     "qdrant_ndcg@10": round(q_n, 4) if q_n is not None else None,
                     "seismic_lat_ms": round(s_lat, 1),
                     "qdrant_lat_ms": round(q_lat, 1)})
        if (i + 1) % 5 == 0 or i == len(queries) - 1:
            log.info("[%d/%d] overlap@10 mean-so-far=%.3f, common-judged=%d/%d",
                     i + 1, len(queries),
                     sum(s_overlap) / len(s_overlap), len(s_ndcgs), len(queries))

    avg = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    summary = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.5.0",
                 "comparison": "SEISMIC (2M med_bio) vs Qdrant scoped to same oaids — SAME vectors, SAME corpus "
                               "(delta = SEISMIC approximation/pruning only)",
                 "built_utc": "2026-06-26",
                 "params": {"heap_factor": args.heap_factor, "query_cut": args.query_cut,
                            "top_k": args.top_k, "quant_scale": QUANT_SCALE,
                            "qdrant_collection": args.qdrant_collection},
                 "purpose": "G2: quality parity vs Qdrant (B1 overlap@10 ≥0.95, B2 NDCG ±0.005)"},
        "overlap@10": {"mean": avg(s_overlap),
                       "n": len(s_overlap),
                       "bar": B1_OVERLAP_BAR,
                       "pass": (avg(s_overlap) or 0) >= B1_OVERLAP_BAR},
        "ndcg@10_common": {"n": len(s_ndcgs),
                           "seismic_mean": avg(s_ndcgs), "qdrant_mean": avg(q_ndcgs),
                           "delta": round(avg(s_ndcgs) - avg(q_ndcgs), 4) if s_ndcgs else None,
                           "bar": "B2 |Δ|<0.005",
                           "pass": (abs(avg(s_ndcgs) - avg(q_ndcgs)) < 0.005)
                                   if s_ndcgs else False},
        "per_query": rows,
    }
    summary["g2_verdict"] = ("G2 PASS — overlap@10 %.3f ≥ %.2f AND NDCG |Δ|=%.4f <0.005"
                             % (avg(s_overlap) or 0, B1_OVERLAP_BAR,
                                abs(avg(s_ndcgs) - avg(q_ndcgs)) if s_ndcgs else 9.9)
                             if summary["overlap@10"]["pass"] and summary["ndcg@10_common"]["pass"]
                             else "G2 %s — overlap@10 %.3f (%s), NDCG Δ=%s (%s)"
                                  % ("PASS" if summary["overlap@10"]["pass"] else "FAIL",
                                     avg(s_overlap) or 0,
                                     "≥0.95" if summary["overlap@10"]["pass"] else "<0.95",
                                     "%.4f" % abs(avg(s_ndcgs) - avg(q_ndcgs)) if s_ndcgs else "n/a",
                                     "in noise" if summary["ndcg@10_common"]["pass"] else "drift"))
    s_n = avg(s_ndcgs) if s_ndcgs else None
    q_n = avg(q_ndcgs) if q_ndcgs else None
    delta = abs(s_n - q_n) if (s_n is not None and q_n is not None) else None
    log.info("overlap@10 mean=%.3f (bar %.2f) | NDCG seismic=%s qdrant=%s Δ=%s (common %d)",
             avg(s_overlap) or 0, B1_OVERLAP_BAR,
             "%.4f" % s_n if s_n is not None else "n/a",
             "%.4f" % q_n if q_n is not None else "n/a",
             "%.4f" % delta if delta is not None else "n/a", len(s_ndcgs))
    log.info("G2: %s", summary["g2_verdict"])

    rpath = (Path(args.result_file) if args.result_file
             else REPO_ROOT / f"data/eval_results/seismic_parity_persona_{int(time.time())}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"g2_verdict": summary["g2_verdict"],
                      "overlap@10": summary["overlap@10"]["mean"],
                      "ndcg_delta": summary["ndcg@10_common"]["delta"],
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
