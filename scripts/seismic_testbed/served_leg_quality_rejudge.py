#!/usr/bin/env python3
"""Absolute SPLADE-leg quality of the SEISMIC shard set that is SERVED TODAY.

Why: the last SEISMIC-leg quality numbers (0.944 on sfu_eval_queries, 0.9262 on
the matched parity-120, both 2026-06-30, both Kimi-judged) scored IDs retrieved
by the 2026-06-29 f16/plain build. The served shards have since moved dv -> E5
-> E8 dv-v2 (2026-07-14). This harness re-retrieves the parity-120 queries on
the served manifest and judges them, with a PAIRED comparison against the
2026-06-29 stored `seismic_top10` judged under the SAME judge + cache regime.

Two phases so the retrieval (index load, page cache) holds the shared-host
latency lock only while it runs, and the LLM judging runs outside it:

  flock /tmp/sfu_latency_measure.lock .venv/bin/python3 \
      scripts/seismic_testbed/served_leg_quality_rejudge.py retrieve \
      --out data/eval_results/seismic_served_e8dvv2_leg_top50_2026-09-27.json

  .venv/bin/python3 scripts/seismic_testbed/served_leg_quality_rejudge.py judge \
      --dump data/eval_results/seismic_served_e8dvv2_leg_top50_2026-09-27.json \
      --judge claude --out data/eval_results/seismic_quality_haiku_e8dvv2_2026-09-27.json

Retrieval replicates `Retriever._splade_leg_seismic` with no filters and the
served defaults: manifest = SFU_SEISMIC_SHARD_MANIFEST or the e5_v2 code default,
mmap, leg top_k = 50 (Retriever.search default), k_prime/query_cut from env or
None (-> backend defaults), heap_factor 0.8. Parallel vs sequential federation
return bit-identical top-k (shared _merge_topk), so Parallel is used.

Judge cache regime (never mutates the canonical caches):
  claude     -> seed = llm_judge_cache.json (Haiku, READ-ONLY) + overlay
                seismic_haiku_judge_overlay.json (new Haiku judgments land here)
  neuralwatt -> seed = seismic_kimi_judge_cache.json (Kimi, READ-ONLY) + overlay
                seismic_kimi_judge_overlay.json
Cache key, prompt, batching and scorers are `benchmark_llm_judge`'s, so numbers
are comparable with that judge's other SEISMIC-leg rows. Unlike
`benchmark_llm_judge.judge_query`, a pair whose judge call fails is NOT cached
as grade 0: it is counted as unjudged, scored 0 in the metric, and reported.
"""
import argparse, json, math, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "experiments"))
sys.path.insert(0, str(ROOT / "scripts" / "seismic_testbed"))

EVAL = ROOT / "data" / "eval_results"
G6_RECORD = EVAL / "seismic_g6_rrf_fullcorpus_n120_20260629.json"
DEFAULT_MANIFEST = EVAL / "seismic_c25_shards_150m_mmap_e5_v2.json"
NDCG_K = 10


def cmd_retrieve(args):
    from lib.thinclient.sharded_seismic_backend import ParallelSeismicBackend
    manifest = os.environ.get("SFU_SEISMIC_SHARD_MANIFEST") or str(DEFAULT_MANIFEST)
    splade = os.environ.get("SFU_SPLADE_MODEL_PATH") or str(ROOT / "models" / "splade_onnx_fused")
    kp = os.environ.get("SFU_SEISMIC_K_PRIME")
    kp = int(kp) if kp else None
    qc = os.environ.get("SFU_SEISMIC_QUERY_CUT")
    qc = int(qc) if qc else None
    hf = float(os.environ.get("SFU_SEISMIC_HEAP_FACTOR", "0.8"))
    g6 = json.loads(G6_RECORD.read_text())
    rows = g6["per_query"][: args.limit or None]
    t0 = time.perf_counter()
    be = ParallelSeismicBackend.from_manifest(manifest, splade_model_path=splade, load_mode="mmap")
    load_s = time.perf_counter() - t0
    out_rows = []
    t1 = time.perf_counter()
    for n, r in enumerate(rows, 1):
        res = be.search(r["query"], args.top_k, query_cut=qc, heap_factor=hf, k_prime=kp)
        ids = [str(oid).split("/")[-1] for oid, _ in res]
        old = r.get("seismic_top10", [])[:NDCG_K]
        out_rows.append({"query": r["query"], "judge_key": r.get("judge_key", r["query"]),
                         "served_top": ids, "served_scores": [float(s) for _, s in res],
                         "g6_20260629_top10": old,
                         "overlap@10_vs_g6": len(set(ids[:NDCG_K]) & set(old)) / NDCG_K if old else None,
                         "exact_top10_order_vs_g6": ids[:NDCG_K] == old})
        if n % 20 == 0:
            print(f"retrieved {n}/{len(rows)}", flush=True)
    ov = [r["overlap@10_vs_g6"] for r in out_rows if r["overlap@10_vs_g6"] is not None]
    dump = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                     "script": "scripts/seismic_testbed/served_leg_quality_rejudge.py retrieve",
                     "manifest": os.path.relpath(manifest, ROOT) if manifest.startswith(str(ROOT)) else manifest,
                     "backend": "ParallelSeismicBackend (mmap)", "splade_model": os.path.relpath(splade, ROOT),
                     "leg_top_k": args.top_k, "k_prime": kp, "query_cut": qc, "heap_factor": hf,
                     "n_shards": len(be._shards) if hasattr(be, "_shards") else None,
                     "load_seconds": round(load_s, 2),
                     "retrieve_seconds": round(time.perf_counter() - t1, 2),
                     "query_source": str(G6_RECORD.relative_to(ROOT)),
                     "n_queries": len(out_rows),
                     "mean_overlap@10_vs_g6_20260629": round(sum(ov) / len(ov), 4) if ov else None,
                     "exact_top10_order_vs_g6": sum(r["exact_top10_order_vs_g6"] for r in out_rows)},
            "per_query": out_rows}
    Path(args.out).write_text(json.dumps(dump, indent=1))
    print(json.dumps(dump["meta"], indent=1))


def _metrics(grades):
    import benchmark_llm_judge as H
    return (H.ndcg_at_k(grades, NDCG_K), H.mrr_at_k(grades, NDCG_K),
            H.precision_at_k(grades, NDCG_K, threshold=2.0))


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = _mean(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    sem = sd / math.sqrt(n) if n else 0.0
    return {"n": n, "mean_a": round(_mean(a), 4), "mean_b": round(_mean(b), 4),
            "delta_a_minus_b": round(m, 4), "sem": round(sem, 4),
            "ci95": [round(m - 1.96 * sem, 4), round(m + 1.96 * sem, 4)],
            "a_ge_b": sum(1 for x in d if x >= 0), "a_gt_b": sum(1 for x in d if x > 0),
            "a_lt_b": sum(1 for x in d if x < 0)}


def cmd_judge(args):
    import benchmark_llm_judge as H
    from rejudge_seismic_leg_n120 import fetch_metadata
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("served_leg_quality")

    if args.judge == "claude":
        seed_file, overlay_file, judge_label = (EVAL / "llm_judge_cache.json",
                                                EVAL / "seismic_haiku_judge_overlay.json",
                                                "claude-haiku-4-5-20251001 via claude -p")
    else:
        seed_file, overlay_file, judge_label = (EVAL / "seismic_kimi_judge_cache.json",
                                                EVAL / "seismic_kimi_judge_overlay.json",
                                                "neuralwatt/" + H._NEURALWATT_MODEL)
        if not H._NEURALWATT_API_KEY:
            raise SystemExit("NEURALWATT_API_KEY empty")
    H._JUDGE_BACKEND = args.judge
    H.JUDGE_CACHE_FILE = overlay_file
    seed = json.loads(seed_file.read_text())
    overlay = json.loads(overlay_file.read_text()) if overlay_file.exists() else {}
    cache = dict(seed)
    cache.update(overlay)
    overlay_before = len(overlay)
    lock = threading.Lock()

    dump = json.loads(Path(args.dump).read_text())
    rows = dump["per_query"][: args.limit or None]
    arms = {"served": lambda r: r["served_top"][:NDCG_K],
            "g6_20260629": lambda r: r["g6_20260629_top10"][:NDCG_K]}
    all_ids = sorted({w for r in rows for a in arms.values() for w in a(r)})
    log.info("judge=%s seed=%s (%d) overlay=%s (%d); %d queries, %d unique ids",
             args.judge, seed_file.name, len(seed), overlay_file.name, overlay_before, len(rows), len(all_ids))
    meta = fetch_metadata(all_ids, log)
    log.info("metadata coverage %d/%d", len(meta), len(all_ids))

    stats = {"calls": 0, "new_judged": 0, "failed": 0, "cache_hits": 0}
    failed_pairs = []

    def judge_row(r):
        jk = r["judge_key"]
        ids = sorted({w for a in arms.values() for w in a(r)})
        todo = []
        with lock:
            for w in ids:
                if H._cache_key(jk, w) in cache:
                    stats["cache_hits"] += 1
                else:
                    todo.append(w)
        papers = [{"openalex_id": w, "title": meta.get(w, {}).get("title", ""),
                   "abstract": meta.get(w, {}).get("abstract", "")} for w in todo]
        for i in range(0, len(papers), 12):
            batch = papers[i:i + 12]
            got = H._batch_judge_subprocess(jk, batch)
            calls = 1
            missed = [p for p in batch if p["openalex_id"] not in got]
            for p in missed:
                got.update(H._batch_judge_subprocess(jk, [p]))
                calls += 1
            with lock:
                stats["calls"] += calls
                for p in batch:
                    w = p["openalex_id"]
                    if w in got:
                        k = H._cache_key(jk, w)
                        cache[k] = got[w]
                        overlay[k] = got[w]
                        stats["new_judged"] += 1
                    else:
                        stats["failed"] += 1
                        failed_pairs.append([jk, w])
                overlay_file.write_text(json.dumps(overlay, indent=1))

    t0 = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for _ in ex.map(judge_row, rows):
            done += 1
            if done % 10 == 0:
                log.info("judged %d/%d  calls=%d new=%d failed=%d", done, len(rows),
                         stats["calls"], stats["new_judged"], stats["failed"])
    judge_s = time.perf_counter() - t0

    per_query, res = [], {}
    for arm, pick in arms.items():
        nd, mr, pr, grades_all, unjudged = [], [], [], [], 0
        for r in rows:
            ids = pick(r)
            g = []
            for w in ids:
                k = H._cache_key(r["judge_key"], w)
                if k in cache:
                    g.append(float(cache[k]))
                else:
                    g.append(0.0)
                    unjudged += 1
            n_, m_, p_ = _metrics(g)
            nd.append(n_); mr.append(m_); pr.append(p_); grades_all += g
            r.setdefault("grades", {})[arm] = g
            r.setdefault("ndcg@10", {})[arm] = round(n_, 4)
        n_pairs = sum(len(pick(r)) for r in rows)
        res[arm] = {"ndcg@10": round(_mean(nd), 4), "mrr@10": round(_mean(mr), 4),
                    "p@10(>=2)": round(_mean(pr), 4), "mean_grade": round(_mean(grades_all), 3),
                    "n_relevant_ge2": sum(1 for g in grades_all if g >= 2),
                    "n_pairs": n_pairs, "n_unjudged_pairs": unjudged,
                    "judged_pair_coverage": round(1 - unjudged / n_pairs, 4) if n_pairs else None,
                    "_ndcg": nd}
    paired = _paired(res["served"].pop("_ndcg"), res["g6_20260629"].pop("_ndcg"))

    kimi_paired = None
    if args.judge == "neuralwatt":
        prev = json.loads((EVAL / "rejudge_kimi_seismic_n120_20260630_2137.json").read_text())
        pmap = {p["query"]: p for p in prev["per_query"]}
        a, b = [], []
        for r in rows:
            p = pmap.get(r["query"])
            if p:
                a.append(_metrics(r["grades"]["served"])[0]); b.append(_metrics(p["grades"])[0])
        kimi_paired = _paired(a, b)
        kimi_paired["vs"] = "rejudge_kimi_seismic_n120_20260630_2137.json per-query grades (0.9262)"

    out = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                    "script": "scripts/seismic_testbed/served_leg_quality_rejudge.py judge",
                    "judge": judge_label, "judge_backend": args.judge,
                    "cache_seed_read_only": str(seed_file.relative_to(ROOT)),
                    "cache_overlay_written": str(overlay_file.relative_to(ROOT)),
                    "overlay_entries_before": overlay_before, "overlay_entries_after": len(overlay),
                    "retrieval_dump": args.dump, "retrieval_meta": dump["meta"],
                    "n_queries": len(rows), "ndcg_k": NDCG_K,
                    "metadata_coverage": f"{len(meta)}/{len(all_ids)}",
                    "judge_seconds": round(judge_s, 1), "judge_calls": stats["calls"],
                    "new_pairs_judged": stats["new_judged"], "failed_pairs": stats["failed"],
                    "cache_hit_pairs": stats["cache_hits"],
                    "ndcg_definition": "ideal within the arm's own top-10 (no cross-method pool), "
                                       "identical to seismic_quality_eval.py / rejudge_seismic_leg_n120.py",
                    "note": "Arm 'served' = E8 dv-v2 served shards retrieved now; arm 'g6_20260629' = "
                            "the 2026-06-29 build's stored seismic_top10 on the same 120 queries, "
                            "judged in the same regime -> paired delta isolates the shard-set change."},
           "scores": res, "paired_served_minus_g6_20260629": paired,
           "paired_served_minus_kimi_20260630_record": kimi_paired,
           "failed_pairs": failed_pairs, "per_query": rows}
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("scores", "paired_served_minus_g6_20260629",
                                          "paired_served_minus_kimi_20260630_record")}, indent=1))
    print(json.dumps({k: out["meta"][k] for k in ("metadata_coverage", "judge_calls", "new_pairs_judged",
                                                  "failed_pairs", "cache_hit_pairs", "judge_seconds",
                                                  "overlay_entries_before", "overlay_entries_after")}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("retrieve")
    r.add_argument("--out", required=True)
    r.add_argument("--top-k", type=int, default=50)
    r.add_argument("--limit", type=int, default=0)
    j = sp.add_parser("judge")
    j.add_argument("--dump", required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--judge", choices=["claude", "neuralwatt"], default="claude")
    j.add_argument("--workers", type=int, default=4)
    j.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cmd_retrieve(a) if a.cmd == "retrieve" else cmd_judge(a)


if __name__ == "__main__":
    main()
