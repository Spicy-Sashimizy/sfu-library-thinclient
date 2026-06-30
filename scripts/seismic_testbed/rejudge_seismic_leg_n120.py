#!/usr/bin/env python3
"""Re-judge the SEISMIC SPLADE leg's STORED top-10 on the matched n=120 parity
queries, with the IDENTICAL NeuralWatt/Kimi judge + isolated cache that produced
the SEISMIC 0.944 quality number and the Qdrant/OpenSearch rejudge numbers.

WHY THIS EXISTS — the SEISMIC-vs-Qdrant head-to-head was never apples-to-apples:
  - The SEISMIC 0.944 number (`seismic_quality_kimi_20260630_084905.json`) was
    judged on `data/sfu_eval_queries.json`, whose 120 queries overlap the parity
    record's 120 by only 40. → a 40-common tie, not a powered verdict.
  - The Qdrant SPLADE leg (`rejudge_kimi_qdrant_n120_20260630_2041.json`) WAS
    judged on the full matched parity-120. → ndcg@10 = 0.9065, n=120, Kimi.

This closes that gap from the SEISMIC side WITHOUT needing the served shards.
`seismic_g6_rrf_fullcorpus_n120_20260629.json` already stores SEISMIC's retrieved
`seismic_top10` W-ids per query — run on the EXACT same 120 parity queries the
Qdrant record uses (120/120 identical, verified). Re-judging those stored IDs with
the same Kimi judge + isolated cache yields the matched, powered SEISMIC leg that
slots directly next to the Qdrant 0.9065 and the SEISMIC 0.944.

Shard-independent: no ParallelSeismicBackend import, no .mmap artifacts. If the
served shards are gone (the /tmp wipe), this still runs — it reads stored IDs.

NDCG ideal is within SEISMIC's own top-k (no cross-method pool) — IDENTICAL
definition to seismic_quality_eval.py and rejudge_stored_records.py, so the three
numbers are directly comparable.

Run (in container, repo root):
  .venv/bin/python3 scripts/seismic_testbed/rejudge_seismic_leg_n120.py \
      --g6-record data/eval_results/seismic_g6_rrf_fullcorpus_n120_20260629.json \
      --engine-label "SEISMIC 8-shard 150M SPLADE (n120 stored top10)"
"""
import argparse, json, os, sys, time
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
    """bare W-id -> {title, abstract}, batched via OpenAlex (identical to the
    SEISMIC eval / rejudge_stored_records so metadata coverage is consistent)."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--g6-record", type=Path, required=True,
                    help="seismic_g6_rrf_fullcorpus_n120 record (stores seismic_top10)")
    ap.add_argument("--engine-label", required=True)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--limit", type=int, default=0, help="0 = all queries")
    ap.add_argument("--result-file", type=Path, default=None)
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("rejudge_seismic")

    # ── judge: NeuralWatt/Kimi, the SAME isolated cache as the SEISMIC + Qdrant runs ──
    H._JUDGE_BACKEND = "neuralwatt"
    if not getattr(H, "_NEURALWATT_API_KEY", ""):
        raise SystemExit("NEURALWATT_API_KEY empty (check .env) — needed for the Kimi judge")
    kimi_cache = ROOT / "data" / "eval_results" / "seismic_kimi_judge_cache.json"
    H.JUDGE_CACHE_FILE = kimi_cache
    H.JUDGE_CACHE = json.loads(kimi_cache.read_text()) if kimi_cache.exists() else {}
    cache_before = len(H.JUDGE_CACHE)
    log.info("judge=neuralwatt model=%s  Kimi cache=%s (%d entries)",
             getattr(H, "_NEURALWATT_MODEL", "?"), kimi_cache.name, cache_before)

    g6 = json.loads(args.g6_record.read_text())
    rows = g6["per_query"]
    if args.limit:
        rows = rows[:args.limit]
    log.info("G6 record: %d queries; seismic_top10 present for %d/%d",
             len(rows),
             sum(1 for r in rows if len(r.get("seismic_top10", [])) >= args.top_k),
             len(rows))

    # ── per-query SEISMIC SPLADE leg = seismic_top10, capped to top-k ──
    per_query = []
    all_ids = []
    for row in rows:
        jk = row.get("judge_key", row["query"])
        leg = row.get("seismic_top10", [])[:args.top_k]
        per_query.append({"query": row["query"], "judge_key": jk, "seismic": leg})
        all_ids += leg

    log.info("fetching OpenAlex metadata for %d unique ids…", len(set(all_ids)))
    meta = fetch_metadata(all_ids, log)
    log.info("metadata coverage: %d/%d", len(meta), len(set(all_ids)))

    # ── judge each doc once per query (the leg's own top-k pool), then score ──
    ndcgs, mrrs, precs, grades_all = [], [], [], []
    api_calls = 0
    for n, qrow in enumerate(per_query, 1):
        jk, leg = qrow["judge_key"], qrow["seismic"]
        papers = [{"openalex_id": wid,
                   "title": meta.get(wid, {}).get("title", ""),
                   "abstract": meta.get(wid, {}).get("abstract", "")} for wid in leg]
        rel_map = H.judge_query(jk, papers)                    # {wid: 0-3}
        ranked = [float(rel_map.get(wid, 0)) for wid in leg]   # in SEISMIC order
        qrow["grades"] = ranked
        ndcgs.append(H.ndcg_at_k(ranked, args.top_k))
        mrrs.append(H.mrr_at_k(ranked, args.top_k))
        precs.append(H.precision_at_k(ranked, args.top_k, threshold=2.0))
        grades_all += ranked
        if n % 20 == 0:
            log.info("  judged %d/%d (cache now %d, +%d since start)", n, len(per_query),
                     len(H.JUDGE_CACHE), len(H.JUDGE_CACHE) - cache_before)
        kimi_cache.write_text(json.dumps(H.JUDGE_CACHE))       # checkpoint each query

    api_calls = len(H.JUDGE_CACHE) - cache_before
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judge": "neuralwatt/" + getattr(H, "_NEURALWATT_MODEL", "?"),
            "engine": args.engine_label,
            "source_record": str(args.g6_record),
            "n_queries": len(per_query), "top_k": args.top_k,
            "metadata_coverage": f"{len(meta)}/{len(set(all_ids))}",
            "kimi_cache_entries_before": cache_before,
            "kimi_cache_entries_after": len(H.JUDGE_CACHE),
            "api_calls_this_run": api_calls,
            "note": "Kimi-judged with the SAME isolated cache + scorers as "
                    "seismic_quality_kimi (SEISMIC 0.944) and rejudge_kimi_qdrant "
                    "(Qdrant 0.9065), so directly comparable. NDCG ideal is within "
                    "SEISMIC's own retrieved top-k (no cross-method pool). The "
                    "seismic_top10 IDs come from the G6 full-corpus run on the exact "
                    "same 120 parity queries the Qdrant record uses.",
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
    out = args.result_file or (ROOT / "data" / "eval_results" /
          f"rejudge_kimi_seismic_n120_{time.strftime('%Y%m%d_%H%M')}.json")
    out.write_text(json.dumps(summary, indent=2))
    log.info("=== %s — Kimi-judged (n=%d) ===", args.engine_label, len(per_query))
    log.info("  ndcg@%d=%s  mrr@%d=%s  p@%d(>=2)=%s  mean_grade=%s",
             args.top_k, summary["scores"]["ndcg@%d" % args.top_k],
             args.top_k, summary["scores"]["mrr@%d" % args.top_k],
             args.top_k, summary["scores"]["p@%d(>=2)" % args.top_k],
             summary["scores"]["mean_grade"])
    log.info("  api_calls_this_run=%d  (cache %d -> %d)", api_calls, cache_before, len(H.JUDGE_CACHE))
    log.info("result: %s", out)


if __name__ == "__main__":
    main()
