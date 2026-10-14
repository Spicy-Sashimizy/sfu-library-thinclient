#!/usr/bin/env python3
"""SEISMIC retrieval quality, judged by NeuralWatt (Kimi).

Wires the neuralwatt judge (from scripts/experiments/benchmark_llm_judge.py) onto the SEISMIC
150M mmap serving path instead of the deprecated OpenSearch SPLADE path:

  query --> ParallelSeismicBackend.search() -> [(openalex_id, score)]   (the
            SAME 8-shard mmap path the latency bench measures)
        --> OpenAlex metadata (title + abstract) for each returned id
        --> NeuralWatt/Kimi judge grades each 0-3  (ISOLATED Kimi cache; the
            Haiku llm_judge_cache.json is never touched)
        --> NDCG@10 / MRR@10 / P@10(>=2) / mean-grade over SEISMIC's own top-k

Quality is RAM-INVARIANT (SEISMIC returns the same ids regardless of page-cache
state), so this is a one-time absolute number, not a per-RAM-level curve.

Run (in container, repo root):
  .venv/bin/python3 scripts/seismic_testbed/seismic_quality_eval.py \
      --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
      [--limit N] [--top-k 10] [--query-cut 10]
"""
import argparse, json, math, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "seismic_testbed"))
sys.path.insert(0, str(ROOT / "source"))

import requests
import benchmark_llm_judge as H          # reuse judge + scorers (loads .env)
from seismic_federated import ParallelSeismicBackend, _load_manifest

OPENALEX = "https://api.openalex.org/works"
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY", "")


def _reconstruct_abstract(inv: dict) -> str:
    if not inv:
        return ""
    pos = [(p, w) for w, ps in inv.items() for p in ps]
    return " ".join(w for _, w in sorted(pos))


def fetch_metadata(oaids: list[str], log) -> dict[str, dict]:
    """openalex_id -> {title, abstract}, batched via the OpenAlex API."""
    meta: dict[str, dict] = {}
    uniq = sorted(set(oaids))
    for i in range(0, len(uniq), 50):
        batch = uniq[i:i + 50]
        ids = "|".join(b.split("/")[-1] for b in batch)   # W-id only
        params = {"filter": f"openalex_id:{ids}", "per-page": 50,
                  "select": "id,title,abstract_inverted_index"}
        if OPENALEX_KEY:
            params["api_key"] = OPENALEX_KEY
        for attempt in range(3):
            try:
                r = requests.get(OPENALEX, params=params, timeout=30)
                r.raise_for_status()
                for w in r.json().get("results", []):
                    # SEISMIC returns BARE ids (W123); OpenAlex w["id"] is the full
                    # URL — key by the bare id so the lookup matches.
                    meta[w["id"].split("/")[-1]] = {
                        "title": w.get("title") or "",
                        "abstract": _reconstruct_abstract(w.get("abstract_inverted_index"))}
                break
            except Exception as e:
                log.warning("metadata batch %d attempt %d: %s", i // 50, attempt + 1, e)
                time.sleep(2)
    # single-id fallback for misses: /works/{id} follows OpenAlex merge redirects
    # that the batch openalex_id: filter drops (keeps missing!=irrelevant honest).
    missing = [b.split("/")[-1] for b in uniq if b.split("/")[-1] not in meta]
    for wid in missing:
        try:
            p = {"select": "id,title,abstract_inverted_index"}
            if OPENALEX_KEY:
                p["api_key"] = OPENALEX_KEY
            r = requests.get(f"{OPENALEX}/{wid}", params=p, timeout=20)
            if r.status_code == 200:
                w = r.json()
                meta[wid] = {"title": w.get("title") or "",
                             "abstract": _reconstruct_abstract(w.get("abstract_inverted_index"))}
        except Exception:
            pass
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-manifest", required=True)
    ap.add_argument("--queries", type=Path, default=ROOT / "data" / "sfu_eval_queries.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--query-cut", type=int,
                    default=int(os.environ.get("SFU_SEISMIC_QUERY_CUT", "10")))
    ap.add_argument("--heap-factor", type=float, default=0.8)
    ap.add_argument("--limit", type=int, default=0, help="0 = all queries")
    ap.add_argument("--result-file", type=Path,
                    default=ROOT / "data" / "eval_results" /
                            f"seismic_quality_kimi_{time.strftime('%Y%m%d_%H%M')}.json")
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("seismic_quality")

    # ── judge: NeuralWatt/Kimi, ISOLATED cache (never touch the Haiku cache) ──
    H._JUDGE_BACKEND = "neuralwatt"
    if not getattr(H, "_NEURALWATT_API_KEY", ""):
        raise SystemExit("NEURALWATT_API_KEY empty (check .env) — needed for the Kimi judge")
    kimi_cache = ROOT / "data" / "eval_results" / "seismic_kimi_judge_cache.json"
    H.JUDGE_CACHE_FILE = kimi_cache
    H.JUDGE_CACHE = json.loads(kimi_cache.read_text()) if kimi_cache.exists() else {}
    log.info("judge=neuralwatt model=%s  Kimi cache=%s (%d entries)",
             getattr(H, "_NEURALWATT_MODEL", "?"), kimi_cache.name, len(H.JUDGE_CACHE))

    # ── load queries + SEISMIC backend (the 8-shard 150M mmap path) ──
    queries = json.loads(args.queries.read_text())
    if args.limit:
        queries = queries[:args.limit]
    index_paths = _load_manifest(args.shard_manifest, load_mode="mmap")
    log.info("loading %d SEISMIC shards (mmap)…", len(index_paths))
    t0 = time.perf_counter()
    backend = ParallelSeismicBackend(index_paths, load_mode="mmap")
    log.info("backend loaded in %.1fs; running %d queries", time.perf_counter() - t0, len(queries))

    # ── retrieve top-k per query via SEISMIC ──
    per_query = []   # {query, results:[(oaid,score)]}
    all_oaids = []
    for n, q in enumerate(queries, 1):
        qt = q["query"] if isinstance(q, dict) else q
        res = backend.search(qt, args.top_k, query_cut=args.query_cut,
                             heap_factor=args.heap_factor)
        per_query.append({"query": qt, "results": res})
        all_oaids += [oid for oid, _ in res]
        if n % 20 == 0:
            log.info("  retrieved %d/%d", n, len(queries))

    # ── metadata for everything SEISMIC returned ──
    log.info("fetching OpenAlex metadata for %d unique ids…", len(set(all_oaids)))
    meta = fetch_metadata(all_oaids, log)
    log.info("metadata coverage: %d/%d", len(meta), len(set(all_oaids)))

    # ── judge (Kimi) + score ──
    ndcgs, mrrs, precs, grades_all = [], [], [], []
    for qrow in per_query:
        qt, res = qrow["query"], qrow["results"]
        papers = [{"openalex_id": oid,
                   "title": meta.get(oid, {}).get("title", ""),
                   "abstract": meta.get(oid, {}).get("abstract", "")}
                  for oid, _ in res]
        rel_map = H.judge_query(qt, papers)                       # {oaid: 0-3}
        ranked = [float(rel_map.get(oid, 0)) for oid, _ in res]   # in SEISMIC order
        qrow["grades"] = ranked
        ndcgs.append(H.ndcg_at_k(ranked, args.top_k))
        mrrs.append(H.mrr_at_k(ranked, args.top_k))
        precs.append(H.precision_at_k(ranked, args.top_k, threshold=2.0))
        grades_all += ranked

    kimi_cache.write_text(json.dumps(H.JUDGE_CACHE))
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judge": "neuralwatt/" + getattr(H, "_NEURALWATT_MODEL", "?"),
            "engine": "SEISMIC 8-shard 150M mmap (ParallelSeismicBackend)",
            "n_queries": len(per_query), "top_k": args.top_k,
            "query_cut": args.query_cut, "heap_factor": args.heap_factor,
            "metadata_coverage": f"{len(meta)}/{len(set(all_oaids))}",
            "note": "Kimi-judged (stricter than the Haiku llm_judge_cache by ~0.27 "
                    "grade; not directly comparable to Haiku-judged numbers). NDCG "
                    "ideal is within SEISMIC's own retrieved top-k (no cross-method pool).",
        },
        "scores": {
            "ndcg@%d" % args.top_k: mean(ndcgs),
            "mrr@%d" % args.top_k: mean(mrrs),
            "p@%d(>=2)" % args.top_k: mean(precs),
            "mean_grade": mean(grades_all),
            "n_relevant_ge2": sum(1 for g in grades_all if g >= 2),
            "n_judged": len(grades_all),
        },
        "per_query": per_query,
    }
    args.result_file.write_text(json.dumps(summary, indent=2))
    log.info("=== SEISMIC QUALITY (Kimi-judged) ===")
    for k, v in summary["scores"].items():
        log.info("  %-14s %s", k, v)
    log.info("result: %s", args.result_file)


if __name__ == "__main__":
    main()
