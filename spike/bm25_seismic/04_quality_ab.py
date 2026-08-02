#!/usr/bin/env python3
"""BM25-through-SEISMIC spike — step 4: LLM-judged no-degradation A/B.

Step 3 answers "does SEISMIC return the same documents exact BM25F would?".
This step answers the question that actually matters — "if we swapped the
lexical leg to SEISMIC, would a user's results get worse?" — by grading the
returned documents for topical relevance, TREC-style, with an LLM judge.

Arms (all three over the identical spike corpus, top-10 each):
  * `tantivy`      — the production lexical leg (`retriever._bm25f_leg` shape)
  * `exact_vec`    — brute-force exact BM25F over the decomposed vectors
  * `seismic_<v>`  — BM25 vectors through SEISMIC at production params

`exact_vec` sits between the other two so a quality delta can be attributed:
tantivy→exact_vec is the decomposition/tokenizer, exact_vec→seismic is the
engine's approximation.

**Pooling.** Judgments are made on the UNION of all arms' top-10 per query, so
no arm is penalised for surfacing a document the others missed, and each
(query, doc) pair is graded exactly once and shared across arms. NDCG is
reported two ways: `pooled_ideal` (ideal DCG over the whole judged pool — the
fair cross-arm number, use this one) and `self_ideal` (ideal within an arm's own
top-k, the convention `seismic_quality_eval.py` used, kept for continuity).

**Judge (`--judge`, default `haiku`).** `haiku` shells out to `claude -p --model
claude-haiku-4-5-20251001` through the Claude Code session: **$0**, and it is
the same judge regime every prior canonical number in this repo was graded
under, so the grading scale is the familiar one. `neuralwatt` (Kimi
`kimi-k2.7-code-flex`) is the paid alternative — it grades ~0.27 stricter than
Haiku (`BENCHMARK_METHODOLOGY.md`, 2026-06-29), and its spend is metered per
call from the API's `usage` block with a hard `--max-judge-calls` stop. Both go
through the shared prompt and scorers in
`scripts/experiments/benchmark_llm_judge.py`. Titles and abstracts come from the
LOCAL spike corpus — no OpenAlex API, no OpenSearch, no network but the judge.

**Cache isolation.** Writes a spike-local cache
(`work/spike_judge_cache.json`). The canonical `llm_judge_cache.json` and
`seismic_kimi_judge_cache.json` are never read or written: this spike judges a
different corpus and a different pool, so folding its grades into either would
corrupt numbers other docs cite. These results are internally comparable only.

    .venv/bin/python3 spike/bm25_seismic/04_quality_ab.py --dry-run
    .venv/bin/python3 spike/bm25_seismic/04_quality_ab.py               # free Haiku
    .venv/bin/python3 spike/bm25_seismic/04_quality_ab.py --judge neuralwatt
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import pickle
import sys
import threading
import time
from pathlib import Path

import numpy as np

import bm25_lib as BL
from importlib import import_module

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "experiments"))
H = import_module("benchmark_llm_judge")     # judge prompt + scorers (loads .env)

log = logging.getLogger("bm25seismic.quality")

# NeuralWatt kimi-k2.7-code-flex list price, USD per 1M tokens. Used only to
# report an estimated spend; the authority is the NeuralWatt dashboard.
PRICE_IN_PER_MTOK = 0.15
PRICE_OUT_PER_MTOK = 0.60


class JudgeBudgetExceeded(BaseException):
    """Derives from BaseException ON PURPOSE. `H._batch_judge_subprocess` wraps
    every judge call in `except Exception: retry`, so an ordinary exception from
    the budget guard would be swallowed, retried three times, and then return an
    empty score dict — which `judge_query` records as **grade 0 for every
    paper**. A silent floor of zeros is the one failure mode that would look
    like a real quality result. BaseException escapes that handler."""


class JudgeMeter:
    """Meters judge calls and enforces a hard cap.

    Two backends: `haiku` shells out to `claude -p --model
    claude-haiku-4-5-20251001` (the Claude Code session — **$0**, and the same
    judge regime every prior canonical number in this repo was graded under),
    and `neuralwatt` posts to the OpenAI-compatible Kimi endpoint, which costs
    real credit and is metered per call from the API's `usage` block."""

    def __init__(self, max_calls: int, backend: str):
        self.max_calls = max_calls
        self.backend = backend
        self.calls = 0
        self.tok_in = 0
        self.tok_out = 0
        self._lock = threading.Lock()
        self._inner_haiku = H._call_haiku

    @property
    def label(self) -> str:
        return ("claude-haiku-4-5-20251001 via `claude -p` (free)"
                if self.backend == "haiku"
                else f"neuralwatt/{getattr(H, '_NEURALWATT_MODEL', '?')}")

    def install(self) -> None:
        if self.backend == "haiku":
            H._call_haiku = self._call_haiku
        else:
            H._call_neuralwatt = self._call

    def _call_haiku(self, prompt: str, timeout: int = 90) -> str:
        with self._lock:
            self.calls += 1
        return self._inner_haiku(prompt, timeout=timeout)

    def _call(self, prompt: str, timeout: int = 120) -> str:
        if self.calls >= self.max_calls:
            raise JudgeBudgetExceeded(
                f"judge-call budget exhausted ({self.max_calls} calls, "
                f"~${self.est_cost_usd:.3f}); raise --max-judge-calls to continue")
        import requests
        resp = requests.post(
            f"{H._NEURALWATT_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {H._NEURALWATT_API_KEY}"},
            json={"model": H._NEURALWATT_MODEL,
                  "messages": [{"role": "system", "content": H.JUDGE_SYSTEM},
                               {"role": "user", "content": prompt}],
                  "max_tokens": H._NEURALWATT_MAX_TOKENS,
                  "temperature": 0},
            timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        self.calls += 1
        usage = data.get("usage") or {}
        self.tok_in += int(usage.get("prompt_tokens") or 0)
        self.tok_out += int(usage.get("completion_tokens") or 0)
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        if not content or not content.strip():
            raise RuntimeError(
                f"NeuralWatt empty content (finish_reason="
                f"{choice.get('finish_reason')}); raise NEURALWATT_MAX_TOKENS")
        return content.strip()

    @property
    def est_cost_usd(self) -> float:
        if self.backend == "haiku":
            return 0.0
        return (self.tok_in / 1e6 * PRICE_IN_PER_MTOK
                + self.tok_out / 1e6 * PRICE_OUT_PER_MTOK)

    def to_json(self) -> dict:
        if self.backend == "haiku":
            return {"judge_backend": self.label, "judge_calls": self.calls,
                    "estimated_cost_usd": 0.0,
                    "price_basis": "$0 — Claude Code session, no API key billed"}
        return {"judge_backend": self.label, "judge_calls": self.calls,
                "prompt_tokens": self.tok_in, "completion_tokens": self.tok_out,
                "estimated_cost_usd": round(self.est_cost_usd, 4),
                "price_basis": f"${PRICE_IN_PER_MTOK}/Mtok in, "
                               f"${PRICE_OUT_PER_MTOK}/Mtok out (list)"}


def ndcg_pooled(ranked_ids: list[str], rel: dict[str, float], k: int) -> float:
    """NDCG@k whose ideal ranking is drawn from the whole judged pool."""
    def dcg(gains):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
    got = [rel.get(d, 0.0) for d in ranked_ids[:k]]
    ideal = sorted(rel.values(), reverse=True)
    idcg = dcg(ideal)
    return dcg(got) / idcg if idcg > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--variant", choices=[BL.VARIANT_A, BL.VARIANT_B],
                    default=BL.VARIANT_A)
    ap.add_argument("--queries", type=Path,
                    default=ROOT / "data" / "sfu_eval_queries.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="0 = all queries")
    ap.add_argument("--query-cut", type=int, default=10)
    ap.add_argument("--heap-factor", type=float, default=0.8)
    ap.add_argument("--judge", choices=["haiku", "neuralwatt"], default="haiku",
                    help="haiku = `claude -p` subprocess via the Claude Code "
                         "session ($0, the regime prior canonical numbers used); "
                         "neuralwatt = Kimi, costs credit")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel judge workers (haiku backend only)")
    ap.add_argument("--max-judge-calls", type=int, default=400,
                    help="hard cap on judge calls (budget guard)")
    ap.add_argument("--dry-run", action="store_true",
                    help="retrieve + pool + report pair counts and cost estimate, no judging")
    ap.add_argument("--result-file", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    # ── corpus text (local; no OpenAlex/OpenSearch) ───────────────────────────
    text: dict[str, dict] = {}
    with open(args.work / "corpus.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            text[r["id"]] = {"title": r["title"], "abstract": r["abstract"]}
    log.info("corpus text loaded: %d docs", len(text))

    with open(args.work / "stats.pkl", "rb") as fh:
        stats: BL.BM25FStats = pickle.load(fh)
    queries = [q["query"] if isinstance(q, dict) else q
               for q in json.loads(args.queries.read_text())]
    if args.limit:
        queries = queries[:args.limit]

    # ── engines ───────────────────────────────────────────────────────────────
    sys.path.insert(0, str(here))
    from importlib import import_module as _im
    gate = _im("03_fidelity_gate") if (here / "03_fidelity_gate.py").exists() else None
    exact = gate.ExactVectorIndex(args.work / f"vectors_{args.variant}.jsonl")

    import seismic
    import tantivy
    idx_glob = sorted((args.work / f"seismic_{args.variant}").glob("*.index.seismic"))
    assert idx_glob, f"no built index in {args.work / f'seismic_{args.variant}'}"
    try:
        sidx = seismic.SeismicIndexLV.load(str(idx_glob[0]))
    except Exception:
        sidx = seismic.SeismicIndex.load(str(idx_glob[0]))
    sdtype = seismic.get_seismic_string()
    tindex = tantivy.Index.open(str(args.work / "tantivy"))
    tindex.reload()

    seismic_arm = f"seismic_{args.variant}"
    arms = ["tantivy", "exact_vec", seismic_arm]

    # ── retrieve ──────────────────────────────────────────────────────────────
    per_query = []
    n_pairs = 0
    for n, qt in enumerate(queries, 1):
        qvec = BL.query_vector(qt, stats, args.variant)
        res = {"tantivy": [d for d, _ in gate.tantivy_search(tindex, qt, args.top_k)],
               "exact_vec": [d for d, _ in exact.search(qvec, args.top_k)]}
        if qvec:
            comps = np.array(list(qvec.keys()), dtype=sdtype)
            vals = np.array(list(qvec.values()), dtype=np.float32)
            sres = sidx.search(query_id="q", query_components=comps,
                               query_values=vals, k=args.top_k,
                               query_cut=max(args.query_cut, len(comps)),
                               heap_factor=args.heap_factor)
            res[seismic_arm] = [doc_id for (_q, _d, doc_id) in sres]
        else:
            res[seismic_arm] = []
        pool = sorted({d for lst in res.values() for d in lst})
        n_pairs += len(pool)
        per_query.append({"query": qt, "results": res, "pool_size": len(pool),
                          "pool": pool})
        if n % 20 == 0:
            log.info("  retrieved %d/%d (pool so far %d pairs)", n, len(queries), n_pairs)

    # ── judge (isolated cache) ────────────────────────────────────────────────
    cache_file = args.work / "spike_judge_cache.json"
    H._JUDGE_BACKEND = "claude" if args.judge == "haiku" else "neuralwatt"
    H.JUDGE_CACHE_FILE = cache_file
    H.JUDGE_CACHE = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    cached = sum(1 for q in per_query for d in q["pool"]
                 if H._cache_key(q["query"], d) in H.JUDGE_CACHE)
    to_judge = n_pairs - cached
    est_calls = math.ceil(to_judge / 12)
    log.info("pool: %d pairs across %d queries (%d cached, %d to judge "
             "→ ~%d judge calls, batch 12)",
             n_pairs, len(per_query), cached, to_judge, est_calls)

    if args.dry_run:
        print(json.dumps({"queries": len(per_query), "pairs": n_pairs,
                          "cached": cached, "to_judge": to_judge,
                          "estimated_judge_calls": est_calls,
                          "estimated_cost_usd_at_2k_in_500_out":
                              round(est_calls * (2000 / 1e6 * PRICE_IN_PER_MTOK
                                                 + 500 / 1e6 * PRICE_OUT_PER_MTOK), 4)},
                         indent=2))
        return

    meter = JudgeMeter(args.max_judge_calls, args.judge)
    meter.install()
    if args.judge == "neuralwatt" and not getattr(H, "_NEURALWATT_API_KEY", ""):
        raise SystemExit("NEURALWATT_API_KEY empty (check .env)")
    log.info("judge=%s  cache=%s  cap=%d calls",
             meter.label, cache_file.name, args.max_judge_calls)

    t0 = time.perf_counter()
    aborted = None

    def papers_for(q):
        return [{"openalex_id": d, "title": text.get(d, {}).get("title", ""),
                 "abstract": text.get(d, {}).get("abstract", "")}
                for d in q["pool"]]

    if args.judge == "haiku":
        # `claude -p` is a subprocess round-trip (~5-10 s), so 120 queries serially
        # would be ~30 min. Fan out over queries the way benchmark_llm_judge does.
        # No budget stop is needed: the CLI judge costs $0 (Claude Code session).
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(H.judge_query, q["query"], papers_for(q)): q
                    for q in per_query}
            done = 0
            for fut in concurrent.futures.as_completed(futs):
                q = futs[fut]
                try:
                    q["grades"] = fut.result()
                except Exception as e:
                    log.error("query %r failed to judge: %s", q["query"][:40], e)
                    q.pop("grades", None)
                done += 1
                if done % 10 == 0:
                    cache_file.write_text(json.dumps(H.JUDGE_CACHE))
                    log.info("  judged %d/%d  (%d judge calls)",
                             done, len(per_query), meter.calls)
    else:
        for n, q in enumerate(per_query, 1):
            # Stop cleanly BETWEEN queries rather than mid-query: a query judged
            # halfway would score its unjudged half as grade 0 for every arm.
            need = math.ceil(sum(1 for d in q["pool"]
                                 if H._cache_key(q["query"], d) not in H.JUDGE_CACHE) / 12)
            if meter.calls + need > args.max_judge_calls:
                aborted = (f"stopped before query {n}/{len(per_query)}: would need "
                           f"{need} more calls, {meter.calls}/{args.max_judge_calls} used")
                log.warning("%s", aborted)
                break
            try:
                q["grades"] = H.judge_query(q["query"], papers_for(q))
            except (JudgeBudgetExceeded, Exception) as e:
                aborted = f"{type(e).__name__}: {e}"
                q.pop("grades", None)   # never score a partially-judged query
                log.error("judging stopped at query %d/%d: %s",
                          n, len(per_query), aborted)
                break
            if n % 10 == 0:
                cache_file.write_text(json.dumps(H.JUDGE_CACHE))
                log.info("  judged %d/%d  (%d calls, ~$%.3f)",
                         n, len(per_query), meter.calls, meter.est_cost_usd)

    cache_file.write_text(json.dumps(H.JUDGE_CACHE))
    log.info("judging done in %.0fs: %s", time.perf_counter() - t0, meter.to_json())

    # ── score ─────────────────────────────────────────────────────────────────
    judged = [q for q in per_query if "grades" in q]
    scores = {a: {"ndcg_pooled": [], "ndcg_self": [], "mrr": [], "p_at_k": [],
                  "mean_grade": []} for a in arms}
    for q in judged:
        rel = {d: float(g) for d, g in q["grades"].items()}
        for a in arms:
            ranked = q["results"][a]
            gains = [rel.get(d, 0.0) for d in ranked[:args.top_k]]
            scores[a]["ndcg_pooled"].append(ndcg_pooled(ranked, rel, args.top_k))
            scores[a]["ndcg_self"].append(H.ndcg_at_k(gains, args.top_k))
            scores[a]["mrr"].append(H.mrr_at_k(gains, args.top_k))
            scores[a]["p_at_k"].append(
                H.precision_at_k(gains, args.top_k, threshold=2.0))
            scores[a]["mean_grade"] += gains

    def mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    k = args.top_k
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "variant": args.variant,
            "corpus_docs": stats.n_docs,
            "corpus_source": "social_sciences__recent (spike subset, block-sequential)",
            "n_queries_retrieved": len(per_query),
            "n_queries_judged": len(judged),
            "top_k": k, "query_cut": args.query_cut, "heap_factor": args.heap_factor,
            "judge": meter.label,
            "judge_cache": str(cache_file),
            "pooling": "TREC-style union of all arms' top-k; each (query,doc) "
                       "graded once and shared",
            "aborted": aborted,
            "note": "Kimi-judged and pooled within this spike only — NOT "
                    "comparable to the Haiku llm_judge_cache numbers or to the "
                    "seismic_kimi_judge_cache 150M numbers (different corpus, "
                    "different pool).",
            **meter.to_json(),
        },
        "scores": {a: {f"ndcg@{k}_pooled_ideal": mean(v["ndcg_pooled"]),
                       f"ndcg@{k}_self_ideal": mean(v["ndcg_self"]),
                       f"mrr@{k}": mean(v["mrr"]),
                       f"p@{k}(>=2)": mean(v["p_at_k"]),
                       "mean_grade": mean(v["mean_grade"]),
                       "n_graded": len(v["mean_grade"])}
                   for a, v in scores.items()},
        "per_query": judged,
    }
    base = summary["scores"]["tantivy"][f"ndcg@{k}_pooled_ideal"]
    got = summary["scores"][seismic_arm][f"ndcg@{k}_pooled_ideal"]
    summary["verdict"] = {
        "baseline_arm": "tantivy", "candidate_arm": seismic_arm,
        f"delta_ndcg@{k}_pooled": round(got - base, 4),
        "relative_pct": round((got - base) / base * 100, 2) if base else None,
    }
    out = args.result_file or (ROOT / "data" / "eval_results" /
                               f"bm25_seismic_spike_quality_{args.variant}_"
                               f"{time.strftime('%Y%m%d_%H%M')}.json")
    out.write_text(json.dumps(summary, indent=2))
    log.info("=== LLM-judged quality A/B (%s) ===", args.variant)
    for a in arms:
        log.info("  %-24s %s", a, summary["scores"][a])
    log.info("  verdict: %s", summary["verdict"])
    log.info("  judge spend: %s", meter.to_json())
    log.info("result: %s", out)


if __name__ == "__main__":
    main()
