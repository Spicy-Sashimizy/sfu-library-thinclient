#!/usr/bin/env python3
"""Dense-leg eval driver — does the dense-ANN leg change the FINAL ranking?

Two engines, one harness:

  --engine thinclient  (DEFAULT, 2026-08-17)
      Drives the SERVED path: `lib.thinclient.retriever.ThinClientRetriever`
      over `data/thinclient_index` (BM25F + SPLADE + dense, RRF k=60). This is
      the arm-runner for the pre-registered dense ablation in
      docs/DENSE_PARTITION_AND_ABLATION.md §7:

          arm A  SFU_DENSE_LEG=0 SFU_DENSE_WARMCACHE=0   RRF(bm25f + splade)
          arm B  SFU_DENSE_LEG=1 SFU_DENSE_WARMCACHE=0   RRF(bm25f + splade + dense)

      ⚠ Since 2026-08-18 the dense leg is DEFAULT OFF in the retriever (the
      ablation's DROP verdict), so arm B MUST set SFU_DENSE_LEG=1 explicitly —
      the 2026-08-18 arms ran under the old default-on. Unset now gives arm A.

      The env gates are honored by the retriever itself (`_load`), so an arm is
      selected purely by environment — this script never forces a leg on or off.
      It RECORDS what it observed (`config.env`, `config.dense_leg_enabled`,
      `config.dense_vectors`) so an arm file proves which arm it is.

  --engine opensearch  (the pre-2026-08 behavior, DEPRECATED for this
      container — the OpenSearch cluster is not part of the thin-client stack.
      Kept because the recorded `pipeline_dense_comparison.json` was produced
      by it; it needs a reachable SFU_OPENSEARCH_URL and an
      `openalex_works_dense` index.)

WHAT THE OUTPUT CARRIES (thinclient engine)
───────────────────────────────────────────
Per query, enough to compute nDCG@10, recall@50, dense-vote share and
leg-overlap@50 OFFLINE, without re-running retrieval (per-query key style
follows data/eval_results/parity_record_tc_*.json):

    query, judge_key, query_type
    bm25f / splade / dense      each leg's own ranked openalex_ids (top_k)
    lat_bm25f_ms / lat_splade_ms / lat_dense_ms
    rrf                         fused ranked ids (top_k)
    rrf_scores                  fused RRF score, aligned with `rrf`
    rrf_legs                    per fused doc {leg: 1-based rank in that leg}
                                — the leg provenance `search_rrf` used to throw
                                away (§5 of the doc); dense-vote share = the
                                fraction of the top-10 whose only key is "dense"
    final / lat_final_ms        post-rerank top-10 ids (only when --rerank != none)
    lat_total_ms

A leg key is ABSENT when that leg did not run (dense under SFU_DENSE_LEG=0, or
an index root with no dense/) — absence is the arm's signature, not a null.

The `summary` block is a convenience recomputation of the same numbers from
those lists; the lists are the source of truth.

Usage
─────
    # arm A — dense leg off
    SFU_DENSE_LEG=0 SFU_DENSE_WARMCACHE=0 \
      .venv/bin/python3 scripts/experiments/eval_pipeline.py \
        --queries data/eval_results/dense_ablation_queries.json \
        --index-root data/thinclient_index --top-k 50 --rerank embed+ce \
        --out data/eval_results/dense_ablation_A_nodense_<date>.json

    # arm B — dense leg on (default), FRESH PROCESS
    SFU_DENSE_WARMCACHE=0 \
      .venv/bin/python3 scripts/experiments/eval_pipeline.py \
        --queries data/eval_results/dense_ablation_queries.json \
        --index-root data/thinclient_index --top-k 50 --rerank embed+ce \
        --out data/eval_results/dense_ablation_B_dense_<date>.json

`--rerank` defaults to `none` (retrieval-only record — cheap, no model loads).
§7's PRIMARY metric is post-rerank nDCG@10, so the decisive arms must pass
`--rerank embed+ce`; retrieval-only is the secondary metric.

CAVEATS (also written into the output)
  1. The dense leg covers a 600K SUBSET built as "judged docs + distractors"
     (measured 90.3% ground-truth coverage, 226x enrichment vs a random subset
     of the same size — data/eval_results/dense_pool_contamination_20260817.json)
     while BM25F/SPLADE search all ~150M. Deltas on an IN-POOL stratum are an
     OPTIMISTIC upper bound, NOT production magnitudes. Only the HELD-OUT
     stratum decides keep/drop.
  2. Paraphrase ground-truth reuse assumes a paraphrase preserves relevance.
  3. The keyword-seeded judge cache likely UNDERSTATES a natural-language
     advantage.
"""
import argparse
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_pipeline")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "source"))

DEFAULT_JUDGE_CACHE = REPO_ROOT / "data/eval_results/llm_judge_cache.json"
DEFAULT_DIVERSE = REPO_ROOT / "data/eval_results/diverse_queries.json"
DEFAULT_INDEX_ROOT = REPO_ROOT / "data/thinclient_index"
DEFAULT_OUTPUT = REPO_ROOT / "data/eval_results/pipeline_dense_comparison.json"

# v5 dense bi-encoder — the dense retrieval leg AND the Stage-1 embedding
# rerank both use it (docs/DENSE_PARTITION_AND_ABLATION.md §1: the model is
# SHARED, so dropping the dense leg does not drop the model).
DENSE_MODEL = str(REPO_ROOT / "models/sfu-academic-embed-v5")
SPLADE_ONNX = str(REPO_ROOT / "models/splade_onnx")

RELEVANT_THRESHOLD = 2
K_NDCG = 10
K_RECALL = 50
RRF_K = 60          # matches retriever.RRF_K, eval_dense_poc.py, federated_search
JUDGE_KEY_LEN = 80
LEGS = ("bm25f", "splade", "dense")


def opensearch_url() -> str:
    return os.environ.get(
        "SFU_OPENSEARCH_URL",
        "http://claudebox-sfu-library-mcp-training-opensearch:9200",
    ).rstrip("/")


# ── Metrics ─────────────────────────────────────────────────────────────────

def dcg(gains: list[int], k: int) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg_at_k(ranked_grades: list[int], ideal_grades: list[int], k: int) -> float:
    """NDCG@k. ideal_grades = ALL judged grades for the query (the true ideal set)."""
    idcg = dcg(sorted(ideal_grades, reverse=True), k)
    if idcg == 0.0:
        return 0.0
    return dcg(ranked_grades, k) / idcg


def mrr_at_k(ranked_grades: list[int], k: int) -> float:
    for i, g in enumerate(ranked_grades[:k]):
        if g >= RELEVANT_THRESHOLD:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked_ids: list[str], gradebook: dict[str, int], k: int) -> float:
    rel = {d for d, g in gradebook.items() if g >= RELEVANT_THRESHOLD}
    if not rel:
        return 0.0
    return len(rel & set(ranked_ids[:k])) / len(rel)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# ── RRF over DOC OBJECTS (k=60) — the OpenSearch engine's fuser ─────────────
# (The thinclient engine uses the retriever's OWN fusion, so the arm measures
# the shipped code path rather than a re-implementation of it.)

def doc_id(doc: dict) -> str:
    """Stable id for fusion/grading (matches the judge-cache key suffix)."""
    return doc.get("openalex_id") or doc.get("doi") or doc.get("title") or ""


def rrf_fuse_docs(ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion of N ranked lists. Returns fused DOC OBJECTS (top_k),
    deduped by doc_id, in fused-score order."""
    scores: dict[str, float] = defaultdict(float)
    first_doc: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, doc in enumerate(lst, start=1):
            k = doc_id(doc)
            if not k:
                continue
            scores[k] += 1.0 / (RRF_K + rank)
            first_doc.setdefault(k, doc)
    ranked_ids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [first_doc[i] for i in ranked_ids[:top_k]]


# ── Ground truth ────────────────────────────────────────────────────────────

def load_judge_grades(path: Path) -> dict[str, dict[str, int]]:
    """{judge_key: {openalex_id: grade}} from the LLM-judge cache."""
    cache = json.loads(path.read_text())
    grades: dict[str, dict[str, int]] = defaultdict(dict)
    for key, grade in cache.items():
        qkey, did = key.rsplit("||", 1)
        if isinstance(grade, int):
            grades[qkey][did] = grade
    return grades


def score_top10(ranked_docs: list[dict], gradebook: dict[str, int]) -> tuple[float, float]:
    """(NDCG@10, MRR@10) for a ranked list of doc OBJECTS."""
    ranked_grades = [gradebook.get(doc_id(d), 0) for d in ranked_docs]
    return (ndcg_at_k(ranked_grades, list(gradebook.values()), K_NDCG),
            mrr_at_k(ranked_grades, K_NDCG))


def score_ids(ranked_ids: list[str], gradebook: dict[str, int]) -> tuple[float, float]:
    """(NDCG@10, MRR@10) for a ranked list of openalex ids."""
    ranked_grades = [gradebook.get(d, 0) for d in ranked_ids]
    return (ndcg_at_k(ranked_grades, list(gradebook.values()), K_NDCG),
            mrr_at_k(ranked_grades, K_NDCG))


# ── Query sets ──────────────────────────────────────────────────────────────

def load_query_records(path: Path, limit: int = 0) -> list[dict]:
    """Accepts, in this order of preference:
      - [{"paraphrase"|"query": ..., "judge_key": ..., "query_type": ...}, ...]
        (the diverse_queries.json / dense_ablation_queries.json shape; a
        "stratum" key — HELD-OUT / IN-POOL from dense_pool_contamination.py —
        is carried through untouched when present)
      - ["a bare query string", ...]
      - {"queries": [<either of the above>]}
    Deduped by query text, order preserved."""
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("queries", [])
    out, seen = [], set()
    for rec in data:
        if isinstance(rec, str):
            rec = {"query": rec}
        q = rec.get("paraphrase") or rec.get("query") or rec.get("original_query")
        if not q or q in seen:
            continue
        seen.add(q)
        row = {"query": q,
               "judge_key": rec.get("judge_key",
                                    rec.get("original_query", q)[:JUDGE_KEY_LEN]),
               "query_type": rec.get("query_type", "unspecified")}
        if rec.get("stratum"):
            row["stratum"] = rec["stratum"]
        out.append(row)
        if limit and len(out) >= limit:
            break
    return out


# ── Production rerank path (mirrors tools.py::_maybe_rerank) ────────────────

def apply_rerank(docs: list[dict], query: str, limit: int, rerank: str,
                 embed_model_path: str) -> list[dict]:
    """Mirror tools.py::_maybe_rerank for rerank in {none, embed, embed+ce}.

    none    -> fused order, truncated to `limit`.
    embed   -> Stage-1 embedding rerank only (use_embedding=True, use_rrf=True
               to match production SFU_FEATURE_RRF_ENABLED=true).
    embed+ce-> Stage-1 embedding rerank (widened to >= _CE_CANDIDATE_POOL so the
               CE can promote docs from rank 11-20), THEN cross-encoder Stage 2.
    """
    if rerank == "none" or not docs:
        return docs[:limit]

    from lib.reranker import (_CE_CANDIDATE_POOL, rerank_results,
                              rerank_with_crossencoder)

    ce_enabled = rerank == "embed+ce"
    stage1_limit = max(limit, _CE_CANDIDATE_POOL) if ce_enabled else limit
    reranked = rerank_results(
        docs,
        query,
        stage1_limit,
        use_embedding=True,
        use_rrf=True,                       # SFU_FEATURE_RRF_ENABLED=true in prod
        embedding_model_path=embed_model_path,
    )
    if ce_enabled:
        reranked = rerank_with_crossencoder(reranked, query, limit)
    return reranked[:limit]


CAVEATS = [
    "The dense leg covers a 600K SUBSET built as 'judged docs + distractors' "
    "(90.3% ground-truth coverage, 226x enrichment vs a random same-size subset "
    "- dense_pool_contamination_20260817.json) while BM25F/SPLADE search all "
    "~150M docs. Deltas on an IN-POOL stratum are an OPTIMISTIC upper bound, "
    "NOT production magnitudes; only the HELD-OUT stratum decides keep/drop.",
    "Paraphrase ground-truth reuse assumes a paraphrase preserves relevance.",
    "The keyword-seeded judge cache likely UNDERSTATES a natural-language "
    "advantage.",
]


# ── engine: thinclient (the served path; the §7 arm runner) ─────────────────

def run_thinclient(args) -> None:
    from lib.thinclient.retriever import ThinClientRetriever

    env = {v: os.environ.get(v) for v in
           ("SFU_DENSE_LEG", "SFU_DENSE_WARMCACHE", "SFU_SPLADE_BACKEND",
            "SFU_SEISMIC_FEDERATION")}
    if env["SFU_DENSE_WARMCACHE"] != "0":
        logger.warning("SFU_DENSE_WARMCACHE is not '0' — the query-driven warm "
                       "cache will grow DURING this run, so the arm is not "
                       "reproducible. §7 pins it off in BOTH arms.")

    r = ThinClientRetriever(index_root=args.index_root, remote_abstracts=False)
    if not r.is_available():
        raise SystemExit(f"thin-client index at {args.index_root} not available")
    m = r.metrics()
    dense_live = bool(m["dense_leg_enabled"]) and m["dense_vectors"] > 0
    arm = "B_dense" if dense_live else "A_nodense"
    logger.info("engine=thinclient arm=%s sections=%d dense_vectors=%d "
                "dense_leg_enabled=%s", arm, len(m["live_sections"]),
                m["dense_vectors"], m["dense_leg_enabled"])

    gradebooks = load_judge_grades(Path(args.judge_cache)) \
        if Path(args.judge_cache).exists() else {}
    queries = load_query_records(Path(args.queries), args.limit)
    if not queries:
        raise SystemExit(f"no queries loaded from {args.queries}")

    rows: list[dict] = []
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        out_path.write_text(json.dumps(build_output(rows), indent=2))

    def build_output(rows: list[dict]) -> dict:
        return {
            "engine": "thinclient",
            "arm": arm,
            "config": {
                "index_root": str(Path(args.index_root).resolve()),
                "queries_file": str(Path(args.queries).resolve()),
                "judge_cache": args.judge_cache,
                "top_k_per_leg": args.top_k,
                "rrf_k": RRF_K,
                "ndcg_k": K_NDCG,
                "recall_k": K_RECALL,
                "rerank_path": args.rerank,
                "rerank_model_embed": DENSE_MODEL if args.rerank != "none" else None,
                "rerank_model_crossencoder": (
                    str(REPO_ROOT / "models/sfu-cross-encoder-v1")
                    if args.rerank == "embed+ce" else None),
                "relevant_threshold": RELEVANT_THRESHOLD,
                "gain": "2^grade - 1",
                "env": env,
                "dense_leg_enabled": m["dense_leg_enabled"],
                "dense_vectors": m["dense_vectors"],
                "live_sections": m["live_sections"],
                "recorded": len(rows),
                "requested": len(queries),
            },
            "summary": summarize_thinclient(rows, gradebooks),
            "caveats": CAVEATS,
            "queries": rows,
        }

    for i, rec in enumerate(queries):
        q, jk = rec["query"], rec["judge_key"]
        t_all = time.perf_counter()
        det = r.search_rrf_detailed(q, top_k=args.top_k, include_dense=True)
        fused = det["results"]
        row = {"query": q, "judge_key": jk, "query_type": rec["query_type"]}
        if rec.get("stratum"):
            row["stratum"] = rec["stratum"]
        for leg in LEGS:
            if leg in det["legs"]:
                row[leg] = det["legs"][leg]
                row[f"lat_{leg}_ms"] = det["leg_latency_ms"][leg]
        row["rrf"] = [d["openalex_id"] for d in fused]
        row["rrf_scores"] = [round(d["score"], 8) for d in fused]
        row["rrf_legs"] = [d["rrf_legs"] for d in fused]
        if args.rerank != "none":
            t0 = time.perf_counter()
            final = apply_rerank(fused, q, K_NDCG, args.rerank, DENSE_MODEL)
            row["lat_final_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            row["final"] = [doc_id(d) for d in final]
        row["lat_total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
        rows.append(row)
        if (i + 1) % 5 == 0:
            logger.info("  %d/%d queries", i + 1, len(queries))
            flush()          # partial record survives an interrupted arm

    flush()
    report_thinclient(build_output(rows))
    logger.info("Wrote %d query records -> %s", len(rows), out_path)


def summarize_thinclient(rows: list[dict], gradebooks: dict) -> dict:
    """Recompute the §7 metrics from the recorded lists. Convenience only —
    the per-query lists are the source of truth and a later analysis can
    recompute all of this (and the paired bootstrap) offline."""
    strata: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        gb = gradebooks.get(row["judge_key"], {})
        judged = any(g >= RELEVANT_THRESHOLD for g in gb.values())
        buckets = ["overall", row.get("query_type", "unspecified")]
        if row.get("stratum"):
            buckets.append(row["stratum"])
        for b in buckets:
            a = strata[b]
            if judged:
                nd, mr = score_ids(row["rrf"][:K_NDCG], gb)
                a["retrieval_ndcg@10"].append(nd)
                a["retrieval_mrr@10"].append(mr)
                a["retrieval_recall@50"].append(recall_at_k(row["rrf"], gb, K_RECALL))
                if "final" in row:
                    fnd, fmr = score_ids(row["final"][:K_NDCG], gb)
                    a["final_ndcg@10"].append(fnd)
                    a["final_mrr@10"].append(fmr)
            # Leg-shape metrics need no judgments.
            top = row["rrf_legs"][:K_NDCG]
            if top:
                a["dense_vote_share@10"].append(
                    sum(1 for p in top if list(p) == ["dense"]) / len(top))
                a["dense_any_share@10"].append(
                    sum(1 for p in top if "dense" in p) / len(top))
            for x, y in (("bm25f", "splade"), ("dense", "bm25f"), ("dense", "splade")):
                if x in row and y in row:
                    a[f"{x}_{y}_overlap@50"].append(
                        len(set(row[x][:K_RECALL]) & set(row[y][:K_RECALL])))
            for leg in LEGS:
                if f"lat_{leg}_ms" in row:
                    a[f"lat_{leg}_ms"].append(row[f"lat_{leg}_ms"])
            a["lat_total_ms"].append(row["lat_total_ms"])

    def pct(xs: list[float], p: float) -> float:
        s = sorted(xs)
        return s[min(len(s) - 1, int(p * len(s)))]

    out: dict[str, dict] = {}
    for name, a in strata.items():
        s: dict = {"n_queries": len(a["lat_total_ms"]),
                   "n_judged": len(a["retrieval_ndcg@10"])}
        for k, xs in a.items():
            if not xs:
                continue
            if k.startswith("lat_"):
                s[k.replace("_ms", "_p50_ms")] = round(pct(xs, 0.50), 2)
                s[k.replace("_ms", "_p95_ms")] = round(pct(xs, 0.95), 2)
            else:
                s[k] = round(mean(xs), 4)
        out[name] = s
    return out


def report_thinclient(out: dict) -> None:
    cfg, summ = out["config"], out["summary"]
    print("\n" + "=" * 88)
    print(f"THIN-CLIENT RETRIEVAL RECORD  —  arm={out['arm']}  "
          f"rerank={cfg['rerank_path']}")
    print("=" * 88)
    print(f"index_root={cfg['index_root']}")
    print(f"dense_leg_enabled={cfg['dense_leg_enabled']}  "
          f"dense_vectors={cfg['dense_vectors']}  "
          f"env={ {k: v for k, v in cfg['env'].items() if v is not None} }")
    print(f"queries recorded={cfg['recorded']}/{cfg['requested']}  "
          f"top_k/leg={cfg['top_k_per_leg']}  RRF_k={cfg['rrf_k']}")
    print("-" * 88)
    for name in sorted(summ):
        s = summ[name]
        print(f"  [{name}] n={s['n_queries']} judged={s['n_judged']}")
        for k in sorted(s):
            if k in ("n_queries", "n_judged"):
                continue
            print(f"      {k:<28} {s[k]}")
    print("-" * 88)
    print("Per-query lists (bm25f/splade/dense/rrf/rrf_legs/final) are the "
          "source of truth;\nthe summary above is recomputed from them.")
    print("=" * 88)


# ── engine: opensearch (pre-2026-08 behavior; DEPRECATED) ───────────────────

def run_opensearch(args) -> None:
    import importlib.util as _ilu
    # class archived 2026-10-11 to scripts/archive/opensearch_era; load it by path
    _osp = __import__('pathlib').Path(__file__).resolve().parents[1] / 'archive' / 'opensearch_era' / 'opensearch_retriever.py'
    _osspec = _ilu.spec_from_file_location('opensearch_retriever_archived', _osp)
    _osmod = _ilu.module_from_spec(_osspec)
    _osspec.loader.exec_module(_osmod)
    OpenSearchRetriever = _osmod.OpenSearchRetriever

    logger.warning("engine=opensearch is the DEPRECATED pre-2026-08 path "
                   "(the OpenSearch cluster is not part of the thin-client "
                   "stack). Use --engine thinclient for the §7 ablation.")
    url = opensearch_url()
    retriever = OpenSearchRetriever(url=url, index="openalex_works",
                                    splade_model_path=args.splade_onnx, timeout=60)

    gradebooks = load_judge_grades(Path(args.judge_cache))
    records = json.loads(Path(args.queries).read_text())
    if args.limit:
        records = records[: args.limit]

    CONFIGS = {
        "A_current":  {"legs": ["bm25f", "splade"],          "label": "bm25f+splade (current)"},
        "B_plusdense": {"legs": ["bm25f", "splade", "dense"], "label": "bm25f+splade+dense"},
    }
    slices = ("keyword", "natural", "overall")
    acc = {cfg: {s: defaultdict(list) for s in slices} for cfg in CONFIGS}
    per_query: list[dict] = []
    skipped_no_gt = 0

    for i, rec in enumerate(records):
        qtext = rec["paraphrase"]
        qtype = rec["query_type"]
        key = rec.get("judge_key", rec["original_query"][:JUDGE_KEY_LEN])
        gradebook = gradebooks.get(key, {})
        if not any(g >= RELEVANT_THRESHOLD for g in gradebook.values()):
            skipped_no_gt += 1
            continue

        legs = {
            "bm25f": retriever.search(qtext, top_k=args.top_k, mode="bm25f"),
            "splade": retriever.search(qtext, top_k=args.top_k, mode="splade"),
            "dense": retriever.dense_search(qtext, top_k=args.top_k,
                                            dense_index=args.dense_index,
                                            dense_model_path=DENSE_MODEL),
        }

        q_record: dict = {"paraphrase": qtext, "query_type": qtype, "judge_key": key}
        for cfg, spec in CONFIGS.items():
            fused = rrf_fuse_docs([legs[le] for le in spec["legs"]], args.top_k)
            retr_ndcg, retr_mrr = score_top10(fused[:K_NDCG], gradebook)
            final_docs = apply_rerank(fused, qtext, K_NDCG, args.rerank, DENSE_MODEL)
            final_ndcg, final_mrr = score_top10(final_docs, gradebook)
            for s in (qtype, "overall"):
                acc[cfg][s]["final_ndcg"].append(final_ndcg)
                acc[cfg][s]["final_mrr"].append(final_mrr)
                acc[cfg][s]["retr_ndcg"].append(retr_ndcg)
                acc[cfg][s]["retr_mrr"].append(retr_mrr)
            q_record[f"{cfg}_final_ndcg"] = round(final_ndcg, 4)
            q_record[f"{cfg}_final_mrr"] = round(final_mrr, 4)
            q_record[f"{cfg}_retr_ndcg"] = round(retr_ndcg, 4)

        per_query.append(q_record)
        if (i + 1) % 10 == 0:
            logger.info("  processed %d/%d records (%d scored)",
                        i + 1, len(records), len(per_query))

    def summarize(cfg: str, s: str) -> dict:
        a = acc[cfg][s]
        return {
            "n_queries": len(a["final_ndcg"]),
            "final_ndcg@10": round(mean(a["final_ndcg"]), 4),
            "final_mrr@10": round(mean(a["final_mrr"]), 4),
            "retrieval_ndcg@10": round(mean(a["retr_ndcg"]), 4),
            "retrieval_mrr@10": round(mean(a["retr_mrr"]), 4),
        }

    summary = {cfg: {s: summarize(cfg, s) for s in slices} for cfg in CONFIGS}
    deltas = {}
    for s in slices:
        a, b = summary["A_current"][s], summary["B_plusdense"][s]
        deltas[s] = {
            "final_ndcg@10_delta": round(b["final_ndcg@10"] - a["final_ndcg@10"], 4),
            "final_mrr@10_delta": round(b["final_mrr@10"] - a["final_mrr@10"], 4),
            "retrieval_ndcg@10_delta": round(b["retrieval_ndcg@10"] - a["retrieval_ndcg@10"], 4),
            "retrieval_mrr@10_delta": round(b["retrieval_mrr@10"] - a["retrieval_mrr@10"], 4),
        }

    out = {
        "engine": "opensearch",
        "config": {
            "judge_cache": args.judge_cache,
            "queries_file": args.queries,
            "dense_index": args.dense_index,
            "splade_query_onnx": args.splade_onnx,
            "dense_embed_model": DENSE_MODEL,
            "rerank_model_embed": DENSE_MODEL,
            "rerank_model_crossencoder": str(REPO_ROOT / "models/sfu-cross-encoder-v1"),
            "opensearch_url": url,
            "top_k_per_leg": args.top_k,
            "rrf_k": RRF_K,
            "ndcg_k": K_NDCG,
            "rerank_path": args.rerank,
            "use_rrf_in_embed_stage": True,
            "relevant_threshold": RELEVANT_THRESHOLD,
            "gain": "2^grade - 1",
            "configs": {cfg: CONFIGS[cfg]["label"] for cfg in CONFIGS},
            "comparison": ("A=RRF(bm25f+splade) vs B=RRF(bm25f+splade+dense), "
                           "BOTH through production rerank (embed -> cross-encoder); "
                           "headline = FINAL reranked top-10."),
        },
        "dataset": {
            "records_in_file": len(records),
            "scored": len(per_query),
            "skipped_no_ground_truth": skipped_no_gt,
        },
        "summary": summary,
        "delta_B_minus_A": deltas,
        "caveats": CAVEATS,
        "per_query": per_query,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 96)
    print("FULL-PIPELINE DENSE EVAL (OpenSearch, DEPRECATED)  —  "
          f"A=RRF(bm25f+splade)  vs  B=RRF(+dense)  [rerank={args.rerank}]")
    print("=" * 96)
    print(f"Records scored: {len(per_query)}   skipped (no relevant ground truth): {skipped_no_gt}")
    hdr = (f"  {'slice':<9} {'A_NDCG':>8} {'B_NDCG':>8} {'dNDCG':>8}   "
           f"{'A_MRR':>8} {'B_MRR':>8} {'dMRR':>8}")
    for label, pre in (("FINAL reranked top-10", "final"),
                       ("RETRIEVAL-ONLY fused top-10", "retrieval")):
        print("-" * 96)
        print(label + ":")
        print(hdr)
        for s in slices:
            a, b, d = summary["A_current"][s], summary["B_plusdense"][s], deltas[s]
            print(f"  {s:<9} {a[pre + '_ndcg@10']:>8.4f} {b[pre + '_ndcg@10']:>8.4f} "
                  f"{d[pre + '_ndcg@10_delta']:>+8.4f}   "
                  f"{a[pre + '_mrr@10']:>8.4f} {b[pre + '_mrr@10']:>8.4f} "
                  f"{d[pre + '_mrr@10_delta']:>+8.4f}")
    print("=" * 96)
    logger.info("Wrote results -> %s", args.out)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Dense-leg eval driver (thin-client arms / legacy OpenSearch A-vs-B)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=["thinclient", "opensearch"],
                   default="thinclient",
                   help="thinclient (default) drives the SERVED retriever; "
                        "opensearch is the deprecated pre-2026-08 path")
    p.add_argument("--queries", default=str(DEFAULT_DIVERSE),
                   help="query-set JSON (see load_query_records for accepted shapes)")
    p.add_argument("--diverse-queries", dest="queries",
                   help="deprecated alias for --queries")
    p.add_argument("--index-root", default=str(DEFAULT_INDEX_ROOT),
                   help="thin-client index root (engine=thinclient)")
    p.add_argument("--judge-cache", default=str(DEFAULT_JUDGE_CACHE))
    p.add_argument("--out", default=str(DEFAULT_OUTPUT))
    p.add_argument("--output", dest="out", help="deprecated alias for --out")
    p.add_argument("--top-k", type=int, default=50,
                   help="hits retrieved per leg before fusion")
    p.add_argument("--rerank", choices=["none", "embed", "embed+ce"], default=None,
                   help="rerank path; default 'none' for thinclient "
                        "(retrieval-only record), 'embed+ce' for opensearch")
    p.add_argument("--dense-index", default="openalex_works_dense",
                   help="engine=opensearch only")
    p.add_argument("--splade-onnx", default=SPLADE_ONNX,
                   help="engine=opensearch only: ONNX export used to encode "
                        "SPLADE QUERIES; must match the model the index's "
                        "sparse_field was encoded with.")
    p.add_argument("--limit", type=int, default=0, help="limit #queries (0=all)")
    args = p.parse_args()
    if args.rerank is None:
        args.rerank = "none" if args.engine == "thinclient" else "embed+ce"

    if args.engine == "thinclient":
        run_thinclient(args)
    else:
        run_opensearch(args)


if __name__ == "__main__":
    main()
