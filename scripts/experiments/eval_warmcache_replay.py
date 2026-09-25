#!/usr/bin/env python3
"""Measure the dense warm cache's four pre-registered success metrics.

Pre-registration: docs/DENSE_WARMCACHE_RESEARCH.md "Success metrics (all four
UNMEASURED as of 2026-09-01)":

  1. Cross-query recall growth on a replayed query log.
  2. Delta-vs-exact recall >= 0.97 (trivially exact in v1: brute force).
  3. p95 `search_rrf` unchanged with cache on.
  4. Cache-hit fraction of the dense leg vs query count.

METRIC 1 CANNOT BE COMPUTED ON THE SERVED QUERY LOG AS PRE-REGISTERED.
`data/eval_results/serve_query_log.jsonl` is PII-safe by construction
(`src/lib/serve_query_log.py`: `query_norm` is stored only when
`SFU_SERVE_QUERY_LOG_RAW=1`, which was never set) — all 2,254 entries carry
`query_norm == ""` and only `query_hash = sha1(query_norm)[:16]`, which is not
invertible. 733 distinct hashes, zero recoverable query strings. The served log
is therefore recorded as UNMEASURABLE-AS-PRE-REGISTERED, and the replay uses a
SURROGATE stream (the 2026-08-18 judged 120-topic / 240-query set, which has
graded qrels so recall is measurable against real judgments rather than
self-referentially). The surrogate is labelled as such everywhere it is
reported; it is not a reinterpretation of the bar, it is a different stream.

Phases (one process, one index load):

  replay  — fresh EMPTY delta in a scratch dir; the 240 queries are replayed in
            a seeded shuffle (so a topic's keyword and natural forms are far
            apart and any gain is genuinely CROSS-query); after every query the
            background encoder is drained so the delta state is deterministic.
            Records, per query: delta size before, the dense leg's top-k, which
            of those came from the delta, per-leg wall ms.
  metrics — offline over the recorded prefixes: metric 1 (recall@k against the
            judged qrels vs query count, cache-on prefix state versus the
            seed-only baseline; plus a self-referential prefix-vs-final overlap
            curve), metric 2 (delta Hamming+rescore top-k vs exact int8 top-k
            over the same delta), metric 4 (cache-hit fraction vs query count).
  latency — metric 3: p95 `search_rrf` with the cache attached versus detached,
            same query set, arms INTERLEAVED per query with the order flipped
            every rep. Ingest stays live in the cache-on arm (the production
            behaviour being measured), and delta drift is recorded.

The real `dense/delta.sqlite` is never opened: the cache is constructed against
a scratch directory and attached to the loaded retriever, so serving state is
untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

DEFAULT_QUERIES = REPO / "data/eval_results/dense_ablation_queries.json"
DEFAULT_QRELS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DEFAULT_SERVE_LOG = REPO / "data/eval_results/serve_query_log.jsonl"
INDEX_ROOT = REPO / "data/thinclient_index"


def loadavg() -> dict:
    a, b, c, procs, _ = Path("/proc/loadavg").read_text().split()
    return {"load1": float(a), "load5": float(b), "load15": float(c),
            "running": procs, "t": time.strftime("%Y-%m-%dT%H:%M:%S")}


def other_benchmarks() -> list[str]:
    """Python processes on this host other than this one (the coordinator's
    quiet-host gate: another agent's Qdrant/ONNX bench contaminates metric 3)."""
    me = os.getpid()
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\x00", b" ").decode()
        except OSError:
            continue
        if "python" not in cmd or "claude" in cmd.lower():
            continue
        if any(x in cmd for x in ("supervisord", "eval_warmcache_replay")):
            continue
        out.append(cmd.strip()[:160])
    return out


def wait_quiet(max_load1: float, timeout_s: float) -> dict:
    """Block until the 1-minute load is below `max_load1` and no other python
    benchmark is running. Records what it waited for, and never lies: if it
    times out it returns quiet=False and the caller records the run as noisy."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        la, others = loadavg(), other_benchmarks()
        if la["load1"] <= max_load1 and not others:
            return {"quiet": True, "waited_s": round(time.time() - t0, 1),
                    "loadavg": la, "other_python": []}
        time.sleep(20)
    la, others = loadavg(), other_benchmarks()
    return {"quiet": False, "waited_s": round(time.time() - t0, 1),
            "loadavg": la, "other_python": others}


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def audit_serve_log(path: Path) -> dict:
    """Prove metric 1's pre-registered input is unusable, rather than asserting it."""
    total = empty = 0
    hashes = set()
    if not path.exists():
        return {"exists": False}
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            total += 1
            if not rec.get("query_norm"):
                empty += 1
            if rec.get("query_hash"):
                hashes.add(rec["query_hash"])
    return {"exists": True, "path": str(path), "entries": total,
            "entries_with_empty_query_norm": empty,
            "distinct_query_hashes": len(hashes),
            "replayable": empty < total}


def load_stream(queries_path: Path, seed: int, limit: int) -> list[dict]:
    rows = json.loads(queries_path.read_text())
    stream = [{"q": r["paraphrase"], "judge_key": r["judge_key"],
               "query_type": r["query_type"], "subject": r.get("subject", ""),
               "stratum": r.get("stratum", "")} for r in rows]
    random.Random(seed).shuffle(stream)
    return stream[:limit] if limit else stream


def load_qrels(path: Path) -> dict[str, set[str]]:
    blob = json.loads(path.read_text())
    thr = int(blob.get("relevant_grade_threshold", 2))
    out = {}
    for key, topic in blob["topics"].items():
        docs = topic["docs"]
        if isinstance(docs, str):
            import ast
            docs = ast.literal_eval(docs)
        out[key] = {d["openalex_id"] for d in docs
                    if int(d.get("grade", 0)) >= thr}
    return out


def make_retriever(remote_abstracts: bool = True):
    """`remote_abstracts=False` for any LATENCY arm: `_hydrate` otherwise calls
    the live OpenAlex API for cold-section ids, and a 429 inside a timed section
    measures the internet. Same precedent as
    `spike/meta_consolidation/12_n7_fs_control.py`."""
    os.environ["SFU_DENSE_LEG"] = "1"
    os.environ["SFU_DENSE_WARMCACHE"] = "0"
    from lib.thinclient.retriever import ThinClientRetriever
    r = ThinClientRetriever(index_root=str(INDEX_ROOT),
                            remote_abstracts=remote_abstracts)
    if not r.is_available():
        raise SystemExit("thinclient index unavailable")
    if not r._dense:
        raise SystemExit("dense seed not loaded — SFU_DENSE_LEG gate or missing dense/")
    return r


def fresh_cache(retriever, scratch: Path, reuse: bool):
    from lib.thinclient.dense_cache import DenseWarmCache
    if not reuse and scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    cache = DenseWarmCache(scratch, seed_ids=retriever._dense["ids"],
                           model_path=retriever.dense_model_path)
    return cache


def drain(cache, timeout: float) -> dict:
    """Block until the background encoder is idle, so the delta prefix after
    query i is deterministic. Returns what it waited for."""
    t0 = time.perf_counter()
    last_n, stable = -1, 0
    while time.perf_counter() - t0 < timeout:
        info = cache.info()
        if info["queue"] == 0 and info["docs"] == last_n:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last_n = info["docs"]
        time.sleep(0.25)
    return {"drain_s": round(time.perf_counter() - t0, 2), **cache.info()}


def phase_replay(args) -> dict:
    r = make_retriever()
    cache = fresh_cache(r, Path(args.scratch), args.reuse_delta)
    r._dense_cache = cache
    stream = load_stream(Path(args.queries), args.seed, args.limit)

    records = []
    for i, item in enumerate(stream):
        with cache._lock:
            n_before = cache._n
            ids_before = set(cache._ids[:n_before])
        t0 = time.perf_counter()
        det = r.search_rrf_detailed(item["q"], top_k=args.top_k,
                                    include_dense=True)
        wall = (time.perf_counter() - t0) * 1000.0
        dense_ids = det["legs"].get("dense", [])
        hits = [d for d in dense_ids if d in ids_before]
        d = drain(cache, args.drain_timeout)
        records.append({
            "i": i, "query": item["q"], "judge_key": item["judge_key"],
            "query_type": item["query_type"], "stratum": item["stratum"],
            "n_delta_before": n_before, "n_delta_after": d["docs"],
            "dense_topk": dense_ids,
            "n_dense_topk": len(dense_ids),
            "n_dense_from_delta": len(hits),
            "rrf_ms": round(wall, 2),
            "leg_latency_ms": det["leg_latency_ms"],
            "drain_s": d["drain_s"], "dropped": d["dropped"],
            "errors": d["errors"],
        })
        if (i + 1) % 10 == 0:
            print(f"[replay] {i+1}/{len(stream)} delta={d['docs']} "
                  f"hit={len(hits)}/{len(dense_ids)} rrf={wall:.0f}ms",
                  flush=True)
    return {"records": records, "final_delta_docs": cache.info()["docs"],
            "cache_stats": cache.info(), "retriever": r, "cache": cache,
            "stream": stream}


def _delta_search(codes, int8, qbits, q, fetch):
    """Byte-identical reimplementation of DenseWarmCache.search's ranking, run
    over an arbitrary prefix of the delta arrays."""
    import numpy as np
    from lib.thinclient.dense_cache import _POPCNT
    n = codes.shape[0]
    if n == 0:
        return []
    dists = _POPCNT[np.bitwise_xor(codes, qbits.ravel())].sum(axis=1)
    take = min(fetch, n)
    cand = np.argpartition(dists, take - 1)[:take]
    scores = (int8[cand].astype(np.float32) / 127.0) @ q
    order = np.argsort(-scores)
    return [(int(cand[i]), float(scores[i])) for i in order]


def phase_metrics(args, replay: dict) -> dict:
    import numpy as np

    from lib.opensearch_retriever import encode_dense
    from lib.thinclient.retriever import OVERFETCH

    r = replay["retriever"]
    cache = replay["cache"]
    qrels = load_qrels(Path(args.qrels))
    with cache._lock:
        n_full = cache._n
        codes = cache._codes[:n_full].copy()
        int8 = cache._int8[:n_full].copy()
        delta_ids = list(cache._ids[:n_full])
    seed_ids = r._dense["ids"]
    seed_rescore = r._dense["rescore"]
    k = args.top_k
    fetch = k * OVERFETCH

    m1, m1b, m2, m4 = [], [], [], []
    for rec in replay["records"]:
        q = np.asarray(encode_dense(rec["query"], r.dense_model_path),
                       dtype=np.float32)
        qbits = np.packbits((q > 0).astype(np.uint8))
        hits = r._dense["index"].search(qbits, fetch)
        keys = np.asarray(hits.keys, dtype=np.int64).ravel()
        seed_scores = {}
        if keys.size:
            sc = (seed_rescore[keys].astype(np.float32) / 127.0) @ q
            for j in range(keys.size):
                seed_scores[seed_ids[int(keys[j])]] = float(sc[j])

        def merged_topk(n_prefix):
            merged = dict(seed_scores)
            for idx, score in _delta_search(codes[:n_prefix], int8[:n_prefix],
                                            qbits, q, fetch):
                did = delta_ids[idx]
                if score > merged.get(did, float("-inf")):
                    merged[did] = score
            return [d for d, _ in sorted(merged.items(), key=lambda t: -t[1])[:k]]

        n_i = rec["n_delta_before"]
        top_prefix = merged_topk(n_i)
        top_full = merged_topk(n_full)
        top_seed = merged_topk(0)

        rel = qrels.get(rec["judge_key"], set())
        denom = len(rel)
        m1.append({
            "i": rec["i"], "n_delta_before": n_i, "judge_key": rec["judge_key"],
            "n_relevant": denom,
            "recall_cache_on": (len(set(top_prefix) & rel) / denom) if denom else None,
            "recall_seed_only": (len(set(top_seed) & rel) / denom) if denom else None,
            "rel_hits_cache_on": len(set(top_prefix) & rel),
            "rel_hits_seed_only": len(set(top_seed) & rel),
        })
        m1b.append({"i": rec["i"], "n_delta_before": n_i,
                    "overlap_prefix_vs_final": len(set(top_prefix) & set(top_full)) / k})

        exact = (int8.astype(np.float32) / 127.0) @ q
        ex_top = set(np.argsort(-exact)[:k].tolist())
        approx = [idx for idx, _ in _delta_search(codes, int8, qbits, q, fetch)[:k]]
        ex10 = set(np.argsort(-exact)[:10].tolist())
        ap10 = [idx for idx, _ in _delta_search(codes, int8, qbits, q, fetch)[:10]]
        m2.append({"i": rec["i"],
                   "recall_at_k": len(ex_top & set(approx)) / k if n_full else None,
                   "recall_at_10": len(ex10 & set(ap10)) / 10 if n_full else None})

        m4.append({"i": rec["i"], "n_delta_before": n_i,
                   "hit_fraction": (rec["n_dense_from_delta"] / rec["n_dense_topk"])
                   if rec["n_dense_topk"] else None})

    def bucket(rows, key, field, edges):
        out = []
        for lo, hi in edges:
            vals = [x[field] for x in rows
                    if x[field] is not None and lo <= x[key] < hi]
            out.append({"queries_seen": f"{lo}-{hi - 1}", "n": len(vals),
                        "mean": round(statistics.fmean(vals), 4) if vals else None})
        return out

    edges = [(0, 10), (10, 25), (25, 50), (50, 100), (100, 160), (160, 10 ** 9)]
    on = [x["recall_cache_on"] for x in m1 if x["recall_cache_on"] is not None]
    off = [x["recall_seed_only"] for x in m1 if x["recall_seed_only"] is not None]
    r2k = [x["recall_at_k"] for x in m2 if x["recall_at_k"] is not None]
    r210 = [x["recall_at_10"] for x in m2 if x["recall_at_10"] is not None]
    hf = [x["hit_fraction"] for x in m4 if x["hit_fraction"] is not None]

    return {
        "metric1_cross_query_recall": {
            "definition": ("dense-leg recall@%d against the judged qrels "
                           "(grade>=2), cache-on prefix state vs the seed-only "
                           "baseline, bucketed by how many queries had already "
                           "been replayed" % k),
            "stream": "SURROGATE (judged 240-query set) — see module docstring",
            "per_query": m1,
            "by_queries_seen_cache_on": bucket(m1, "i", "recall_cache_on", edges),
            "by_queries_seen_seed_only": bucket(m1, "i", "recall_seed_only", edges),
            "mean_recall_cache_on": round(statistics.fmean(on), 4) if on else None,
            "mean_recall_seed_only": round(statistics.fmean(off), 4) if off else None,
            "delta": round(statistics.fmean(on) - statistics.fmean(off), 4)
            if on and off else None,
        },
        "metric1b_prefix_vs_final_overlap": {
            "definition": "self-referential saturation: |topk(prefix) & topk(final)| / k",
            "by_queries_seen": bucket(m1b, "i", "overlap_prefix_vs_final", edges),
            "per_query": m1b,
        },
        "metric2_delta_vs_exact": {
            "definition": ("DenseWarmCache.search (Hamming prefilter, fetch=%d, "
                           "+ int8 rescore) vs exact int8 top-k over the SAME "
                           "delta (%d docs)" % (fetch, n_full)),
            "bar": 0.97, "n_queries": len(r2k),
            "mean_recall_at_k": round(statistics.fmean(r2k), 6) if r2k else None,
            "min_recall_at_k": round(min(r2k), 6) if r2k else None,
            "mean_recall_at_10": round(statistics.fmean(r210), 6) if r210 else None,
            "min_recall_at_10": round(min(r210), 6) if r210 else None,
            "pass": (min(r2k) >= 0.97) if r2k else None,
        },
        "metric4_cache_hit_fraction": {
            "definition": ("fraction of the dense leg's top-%d that came from "
                           "the warm delta rather than the static seed, at the "
                           "delta state in force when the query ran" % k),
            "by_queries_seen": bucket(m4, "i", "hit_fraction", edges),
            "mean": round(statistics.fmean(hf), 4) if hf else None,
            "final": hf[-1] if hf else None,
            "per_query": m4,
        },
    }


def phase_delta_recall(args) -> dict:
    """Metric 2's full per-query distribution, opening nothing but the scratch
    delta and the encoder: the delta search's Hamming prefilter is NOT exact,
    so how often it misses matters as much as the mean."""
    import sqlite3

    import numpy as np

    from lib.opensearch_retriever import encode_dense
    from lib.thinclient.retriever import OVERFETCH

    db = sqlite3.connect(str(Path(args.scratch) / "delta.sqlite"))
    rows = db.execute("SELECT id, vec FROM delta ORDER BY key").fetchall()
    int8 = np.stack([np.frombuffer(b, dtype=np.int8) for _, b in rows])
    codes = np.packbits(int8 > 0, axis=1)
    n = int8.shape[0]
    k, fetch = args.top_k, args.top_k * OVERFETCH
    model = os.environ.get("SFU_EMBEDDING_MODEL_PATH") or str(
        REPO / "models/sfu-academic-embed-v5")
    stream = load_stream(Path(args.queries), args.seed, args.limit)
    per = []
    for item in stream:
        q = np.asarray(encode_dense(item["q"], model), dtype=np.float32)
        qbits = np.packbits((q > 0).astype(np.uint8))
        exact = (int8.astype(np.float32) / 127.0) @ q
        approx = [i for i, _ in _delta_search(codes, int8, qbits, q, fetch)]
        row = {"query": item["q"]}
        for kk in (10, k):
            ex = set(np.argsort(-exact)[:kk].tolist())
            row[f"recall_at_{kk}"] = len(ex & set(approx[:kk])) / kk
        per.append(row)
    r_k = [x[f"recall_at_{k}"] for x in per]
    r_10 = [x["recall_at_10"] for x in per]
    return {
        "definition": ("DenseWarmCache.search (Hamming prefilter, fetch=%d) vs "
                       "exact int8 top-k over the same %d-doc delta" % (fetch, n)),
        "bar": 0.97, "delta_docs": n, "n_queries": len(per),
        "mean_recall_at_k": round(statistics.fmean(r_k), 6),
        "min_recall_at_k": round(min(r_k), 6),
        "frac_queries_below_bar_at_k": round(
            sum(1 for x in r_k if x < 0.97) / len(r_k), 4),
        "n_queries_below_bar_at_k": sum(1 for x in r_k if x < 0.97),
        "frac_queries_exact_at_k": round(
            sum(1 for x in r_k if x == 1.0) / len(r_k), 4),
        "mean_recall_at_10": round(statistics.fmean(r_10), 6),
        "min_recall_at_10": round(min(r_10), 6),
        "n_queries_below_bar_at_10": sum(1 for x in r_10 if x < 0.97),
        "mean_pass": statistics.fmean(r_k) >= 0.97,
        "worst_case_pass": min(r_k) >= 0.97,
        "per_query": per,
    }


def phase_latency(args, retriever, cache, stream) -> dict:
    r = retriever
    if args.latency_queries:
        stream = stream[:args.latency_queries]
    trials = {"on": [], "off": []}
    order_log = []
    n_before = cache.info()["docs"]
    load_samples = [loadavg()]
    for item in stream[:args.warmup]:
        r._dense_cache = None
        r.search_rrf(item["q"], top_k=args.top_k, include_dense=True)
    for rep in range(args.reps):
        for i, item in enumerate(stream):
            arms = ["on", "off"] if (rep + i) % 2 == 0 else ["off", "on"]
            for arm in arms:
                r._dense_cache = cache if arm == "on" else None
                t0 = time.perf_counter()
                r.search_rrf(item["q"], top_k=args.top_k, include_dense=True)
                trials[arm].append((time.perf_counter() - t0) * 1000.0)
            order_log.append(arms[0])
            if i % 20 == 0:
                load_samples.append(loadavg())
        print(f"[latency] rep {rep+1}/{args.reps} done "
              f"n_on={len(trials['on'])}", flush=True)
    r._dense_cache = cache
    out = {"definition": ("p95 search_rrf(include_dense=True) wall ms, cache "
                          "attached vs detached, arms interleaved per query "
                          "with the order flipped every rep"),
           "reps": args.reps, "queries": len(stream),
           "subsampled_from": args.latency_queries and len(stream),
           "delta_docs_before": n_before,
           "delta_docs_after": cache.info()["docs"],
           "loadavg_samples": load_samples + [loadavg()],
           "loadavg_max_load1": max(x["load1"] for x in load_samples),
           "first_arm_on_fraction": round(
               sum(1 for a in order_log if a == "on") / len(order_log), 3)
           if order_log else None}
    for arm in ("on", "off"):
        xs = trials[arm]
        out[arm] = {"n": len(xs), "p50": round(_pct(xs, 50), 2),
                    "p95": round(_pct(xs, 95), 2), "p99": round(_pct(xs, 99), 2),
                    "mean": round(statistics.fmean(xs), 2),
                    "min": round(min(xs), 2), "max": round(max(xs), 2)}
    out["p95_delta_ms"] = round(out["on"]["p95"] - out["off"]["p95"], 2)
    out["p95_ratio"] = round(out["on"]["p95"] / out["off"]["p95"], 4)
    out["p50_delta_ms"] = round(out["on"]["p50"] - out["off"]["p50"], 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=str(DEFAULT_QUERIES))
    ap.add_argument("--qrels", default=str(DEFAULT_QRELS))
    ap.add_argument("--serve-log", default=str(DEFAULT_SERVE_LOG))
    ap.add_argument("--scratch", default="/var/tmp/warmcache_replay_delta")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260925)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--latency-queries", type=int, default=0,
                    help="subsample the replay stream for metric 3 (0 = all)")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--drain-timeout", type=float, default=180.0)
    ap.add_argument("--reuse-delta", action="store_true")
    ap.add_argument("--skip-latency", action="store_true")
    ap.add_argument("--phase", choices=("all", "latency", "delta_recall"),
                    default="all",
                    help="latency: metric 3 only; delta_recall: metric 2's full "
                         "per-query distribution, no index load")
    ap.add_argument("--require-quiet", type=float, default=0.0,
                    help="block until 1-min loadavg <= this and no other python "
                         "benchmark runs (0 = do not gate)")
    ap.add_argument("--quiet-timeout", type=float, default=3600.0)
    ap.add_argument("--remote-abstracts", action="store_true",
                    help="latency phase: allow live OpenAlex hydration "
                         "(default OFF - a 429 inside a timed section measures "
                         "the internet, not the cache)")
    args = ap.parse_args()

    started = time.time()
    result = {
        "what": "dense warm cache — the four pre-registered success metrics",
        "date": "2026-09-25",
        "script": "scripts/experiments/eval_warmcache_replay.py",
        "pre_registration": "docs/DENSE_WARMCACHE_RESEARCH.md",
        "index_root": str(INDEX_ROOT),
        "top_k": args.top_k, "seed": args.seed,
        "served_query_log_audit": audit_serve_log(Path(args.serve_log)),
        "loadavg_at_start": loadavg(),
        "other_python_at_start": other_benchmarks(),
    }
    print("[audit]", json.dumps(result["served_query_log_audit"]), flush=True)

    if args.phase == "delta_recall":
        result["metric2_delta_vs_exact"] = phase_delta_recall(args)
        result["total_wall_s"] = round(time.time() - started, 1)
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
        print(json.dumps({k: v for k, v in
                          result["metric2_delta_vs_exact"].items()
                          if k != "per_query"}, indent=1), flush=True)
        return

    if args.phase == "latency":
        r = make_retriever(remote_abstracts=args.remote_abstracts)
        result["remote_abstracts"] = args.remote_abstracts
        cache = fresh_cache(r, Path(args.scratch), True)
        r._dense_cache = cache
        stream = load_stream(Path(args.queries), args.seed, args.limit)
        result["phase"] = "latency-only (metric 3 re-run in isolation)"
        result["delta_docs_restored"] = cache.info()["docs"]
        if args.require_quiet:
            result["quiet_gate"] = wait_quiet(args.require_quiet,
                                              args.quiet_timeout)
            print("[quiet]", json.dumps(result["quiet_gate"]), flush=True)
        t0 = time.time()
        result["metric3_latency"] = phase_latency(args, r, cache, stream)
        result["metric3_latency"]["wall_s"] = round(time.time() - t0, 1)
        result["loadavg_at_end"] = loadavg()
        result["other_python_at_end"] = other_benchmarks()
        result["total_wall_s"] = round(time.time() - started, 1)
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
        print("WROTE", args.out, flush=True)
        print("metric3_latency", json.dumps(result["metric3_latency"], indent=1),
              flush=True)
        return

    t0 = time.time()
    replay = phase_replay(args)
    print(f"[replay] done in {time.time()-t0:.0f}s "
          f"delta={replay['final_delta_docs']}", flush=True)
    result["replay"] = {
        "stream": "data/eval_results/dense_ablation_queries.json (seeded shuffle)",
        "n_queries": len(replay["records"]),
        "final_delta_docs": replay["final_delta_docs"],
        "cache_stats": replay["cache_stats"],
        "wall_s": round(time.time() - t0, 1),
        "records": replay["records"],
    }
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")

    t0 = time.time()
    result["metrics"] = phase_metrics(args, replay)
    result["metrics"]["wall_s"] = round(time.time() - t0, 1)
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    print("[metrics] done", flush=True)

    if not args.skip_latency:
        t0 = time.time()
        result["metric3_latency"] = phase_latency(
            args, replay["retriever"], replay["cache"], replay["stream"])
        result["metric3_latency"]["wall_s"] = round(time.time() - t0, 1)

    result["loadavg_at_end"] = loadavg()
    result["other_python_at_end"] = other_benchmarks()
    result["total_wall_s"] = round(time.time() - started, 1)
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    print("WROTE", args.out, flush=True)
    for key in ("metric1_cross_query_recall", "metric2_delta_vs_exact",
                "metric4_cache_hit_fraction"):
        blob = dict(result["metrics"][key])
        blob.pop("per_query", None)
        print(key, json.dumps(blob, indent=1), flush=True)
    if "metric3_latency" in result:
        print("metric3_latency", json.dumps(result["metric3_latency"], indent=1),
              flush=True)


if __name__ == "__main__":
    main()
