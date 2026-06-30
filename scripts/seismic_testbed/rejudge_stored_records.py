#!/usr/bin/env python3
"""Re-judge STORED parity records (Qdrant / OpenSearch) with the SAME NeuralWatt
(Kimi) setup that produced the SEISMIC 0.944 quality number.

The SEISMIC quality eval (`seismic_quality_eval.py`) judged SEISMIC's own SPLADE
retrieval (`ParallelSeismicBackend.search()` top-k) with the NeuralWatt/Kimi judge
and the ISOLATED Kimi cache. This makes the Qdrant and OpenSearch numbers
comparable by judging their STORED top-k the IDENTICAL way:

  stored record --> per query: bm25f / splade ranked W-id lists (+ RRF fusion)
                --> OpenAlex metadata (title + abstract) for each id
                --> NeuralWatt/Kimi judge grades each 0-3  (SAME isolated Kimi
                    cache as the SEISMIC run -> shared docs reused, identical judge)
                --> NDCG@10 / MRR@10 / P@10(>=2) / mean-grade per LEG

The directly-comparable-to-SEISMIC number is the **splade** leg (SEISMIC is the
SPLADE engine). `rrf` is the system number; `bm25f` is context.

NDCG ideal is within each leg's own top-k (no cross-method pool) — IDENTICAL to
the SEISMIC eval, so the legs/engines are scored on one consistent definition.

Run (in container, repo root):
  .venv/bin/python3 scripts/seismic_testbed/rejudge_stored_records.py \
      --record data/eval_results/parity_record_tc_qdrant_n120_20260629.json \
      --engine-label "Qdrant on_disk SPLADE (150M, n120 stored)"
"""
import argparse, json, math, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import requests
import benchmark_llm_judge as H          # reuse judge + scorers (loads .env)

OPENALEX = "https://api.openalex.org/works"
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY", "")
TOP_K = 10


def _reconstruct_abstract(inv: dict) -> str:
    if not inv:
        return ""
    pos = [(p, w) for w, ps in inv.items() for p in ps]
    return " ".join(w for _, w in sorted(pos))


def fetch_metadata(oaids: list[str], log) -> dict[str, dict]:
    """bare W-id -> {title, abstract}, batched via OpenAlex (copied from the
    SEISMIC eval so this script has no SEISMIC-backend import dependency)."""
    meta: dict[str, dict] = {}
    uniq = sorted(set(oaids))
    for i in range(0, len(uniq), 50):
        batch = uniq[i:i + 50]
        ids = "|".join(b.split("/")[-1] for b in batch)
        params = {"filter": f"openalex_id:{ids}", "per-page": 50,
                  "select": "id,title,abstract_inverted_index"}
        if OPENALEX_KEY:
            params["api_key"] = OPENALEX_KEY
        for attempt in range(3):
            try:
                r = requests.get(OPENALEX, params=params, timeout=30)
                r.raise_for_status()
                for w in r.json().get("results", []):
                    meta[w["id"].split("/")[-1]] = {
                        "title": w.get("title") or "",
                        "abstract": _reconstruct_abstract(w.get("abstract_inverted_index"))}
                break
            except Exception as e:
                log.warning("metadata batch %d attempt %d: %s", i // 50, attempt + 1, e)
                time.sleep(2)
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


def rrf(lists: list[list[str]], k: int = 60, top: int = TOP_K) -> list[str]:
    """Identical to eval_thinclient_parity.rrf (k=60)."""
    scores: dict[str, float] = {}
    for lst in lists:
        for rank, did in enumerate(lst, start=1):
            scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)[:top]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", type=Path, required=True,
                    help="stored parity record (engine=tc/os) with per-query bm25f/splade")
    ap.add_argument("--engine-label", required=True)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--limit", type=int, default=0, help="0 = all queries")
    ap.add_argument("--result-file", type=Path, default=None)
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("rejudge")

    # ── judge: NeuralWatt/Kimi, the SAME isolated cache as the SEISMIC run ──
    H._JUDGE_BACKEND = "neuralwatt"
    if not getattr(H, "_NEURALWATT_API_KEY", ""):
        raise SystemExit("NEURALWATT_API_KEY empty (check .env) — needed for the Kimi judge")
    kimi_cache = ROOT / "data" / "eval_results" / "seismic_kimi_judge_cache.json"
    H.JUDGE_CACHE_FILE = kimi_cache
    H.JUDGE_CACHE = json.loads(kimi_cache.read_text()) if kimi_cache.exists() else {}
    log.info("judge=neuralwatt model=%s  Kimi cache=%s (%d entries)",
             getattr(H, "_NEURALWATT_MODEL", "?"), kimi_cache.name, len(H.JUDGE_CACHE))

    rec = json.loads(args.record.read_text())
    rows = rec["queries"]
    if args.limit:
        rows = rows[:args.limit]
    log.info("record engine=%s  %d queries", rec.get("engine"), len(rows))

    # ── per-query legs: bm25f / splade / rrf, each capped to top-k ──
    legs = ("bm25f", "splade", "rrf")
    per_query = []
    all_ids = []
    for row in rows:
        bm = row.get("bm25f", [])[:args.top_k]
        sp = row.get("splade", [])[:args.top_k]
        fused = rrf([row.get("bm25f", []), row.get("splade", [])], top=args.top_k)
        per_query.append({"query": row["query"], "bm25f": bm, "splade": sp, "rrf": fused})
        all_ids += bm + sp + fused

    log.info("fetching OpenAlex metadata for %d unique ids…", len(set(all_ids)))
    meta = fetch_metadata(all_ids, log)
    log.info("metadata coverage: %d/%d", len(meta), len(set(all_ids)))

    # ── judge every doc once per query (union of the 3 legs), then score per leg ──
    scores = {leg: {"ndcg": [], "mrr": [], "prec": []} for leg in legs}
    grades_all = []
    for n, qrow in enumerate(per_query, 1):
        qt = qrow["query"]
        union = list(dict.fromkeys(qrow["bm25f"] + qrow["splade"] + qrow["rrf"]))
        papers = [{"openalex_id": wid,
                   "title": meta.get(wid, {}).get("title", ""),
                   "abstract": meta.get(wid, {}).get("abstract", "")} for wid in union]
        rel_map = H.judge_query(qt, papers)                       # {wid: 0-3}
        qrow["grades"] = {wid: rel_map.get(wid, 0) for wid in union}
        for leg in legs:
            ranked = [float(rel_map.get(wid, 0)) for wid in qrow[leg]]
            scores[leg]["ndcg"].append(H.ndcg_at_k(ranked, args.top_k))
            scores[leg]["mrr"].append(H.mrr_at_k(ranked, args.top_k))
            scores[leg]["prec"].append(H.precision_at_k(ranked, args.top_k, threshold=2.0))
        grades_all += [float(rel_map.get(wid, 0)) for wid in qrow["splade"]]
        if n % 20 == 0:
            log.info("  judged %d/%d", n, len(per_query))
        kimi_cache.write_text(json.dumps(H.JUDGE_CACHE))         # checkpoint each query

    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judge": "neuralwatt/" + getattr(H, "_NEURALWATT_MODEL", "?"),
            "engine": args.engine_label,
            "source_record": str(args.record),
            "n_queries": len(per_query), "top_k": args.top_k,
            "metadata_coverage": f"{len(meta)}/{len(set(all_ids))}",
            "note": "Kimi-judged with the SAME isolated cache + scorers as "
                    "seismic_quality_kimi (so directly comparable to the SEISMIC "
                    "0.944). NDCG ideal is within each leg's own top-k. The "
                    "splade leg is the apples-to-apples vs SEISMIC's search().",
        },
        "scores_by_leg": {
            leg: {"ndcg@%d" % args.top_k: mean(scores[leg]["ndcg"]),
                  "mrr@%d" % args.top_k: mean(scores[leg]["mrr"]),
                  "p@%d(>=2)" % args.top_k: mean(scores[leg]["prec"])}
            for leg in legs
        },
        "splade_leg_grade_dist": {
            "mean_grade": mean(grades_all),
            "n_relevant_ge2": sum(1 for g in grades_all if g >= 2),
            "n_judged": len(grades_all),
        },
        "per_query": per_query,
    }
    out = args.result_file or (ROOT / "data" / "eval_results" /
          f"rejudge_kimi_{rec.get('engine','x')}_{time.strftime('%Y%m%d_%H%M')}.json")
    out.write_text(json.dumps(summary, indent=2))
    log.info("=== %s — Kimi-judged ===", args.engine_label)
    for leg in legs:
        s = summary["scores_by_leg"][leg]
        log.info("  %-7s ndcg@%d=%s  mrr@%d=%s  p@%d(>=2)=%s", leg, args.top_k,
                 s["ndcg@%d" % args.top_k], args.top_k, s["mrr@%d" % args.top_k],
                 args.top_k, s["p@%d(>=2)" % args.top_k])
    log.info("result: %s", out)


if __name__ == "__main__":
    main()
