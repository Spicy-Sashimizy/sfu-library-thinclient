#!/usr/bin/env python3
"""
> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

mmap-BMP spike — STEP 1: record the load-into-RAM BMP baseline.

Runs the CURRENT (stock, load-into-memory) `bmp.Searcher` over the existing test
`.bmp` shards, encoding real SPLADE queries the same way the serving retriever
does, and records per-(shard, query) top-k (ids, scores) + RSS + latency to JSON.

STEP 2 (`compare_fork.py`) runs the SAME saved query vectors through the
*forked mmap* BMP build and asserts the top-k is byte-identical (correctness gate)
while RssAnon stays ~0 (the RAM gate) and measures cold/warm latency.

Run from repo root:
    .venv/bin/python3 spike/mmap_bmp/record_baseline.py \
        --shards 'data/thinclient_1m/sections/*/splade_000.bmp' \
        --out spike/mmap_bmp/out

Notes:
- Self-contained: it persists the encoded query vectors (`qvecs.json`) so STEP 2
  needs no SPLADE encoder (and no GPU) — only the forked bmp wheel.
- Uses the serving constants: QUANT_SCALE=70, alpha=0.8, beta=1.0.
"""
import argparse, glob, json, os, sys, time

sys.path.insert(0, "src")  # so `import bmp` + `lib.opensearch_retriever` resolve
import bmp  # stock load-into-memory engine

QUANT_SCALE = 70
ALPHA, BETA = 0.8, 1.0
TOP_K = 50
SPLADE_QUERY_TERMS = 64

DEFAULT_QUERIES = [
    "northern gateway pipeline environmental assessment british columbia",
    "indigenous land rights canada supreme court",
    "machine learning sparse retrieval splade",
    "covid 19 vaccine mrna efficacy",
    "climate change ocean acidification coral reef",
    "labour union collective bargaining canada",
    "quantum error correction surface code",
    "documentary film indigenous representation canada",
    "protein folding alphafold structure prediction",
    "latin american social movements neoliberalism",
]


def _proc_kb(key):
    for line in open("/proc/self/status"):
        if line.startswith(key):
            return int(line.split()[1])
    return -1


def rss_gb():
    return _proc_kb("VmRSS:") / 1024 / 1024


def rssanon_gb():
    return _proc_kb("RssAnon:") / 1024 / 1024


def encode_qvecs(queries, model_path):
    """text -> {bert_token_str: int_weight}, the serving qvec. Requires the encoder."""
    from lib.opensearch_retriever import encode_splade  # emits wordpiece token strings
    out = {}
    for q in queries:
        sparse = encode_splade(q, model_path)  # {token: float_weight}
        top = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        out[q] = {t: max(1, int(round(w * QUANT_SCALE))) for t, w in top.items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="data/thinclient_1m/sections/*/splade_000.bmp")
    ap.add_argument("--queries-file", default=None, help="one query per line; else built-in set")
    ap.add_argument("--out", default="spike/mmap_bmp/out")
    ap.add_argument("--k", type=int, default=TOP_K)
    ap.add_argument("--model", default="models/splade_onnx_fp16",
                    help="SPLADE ONNX dir (fp16 = fast cold load)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    queries = DEFAULT_QUERIES
    if args.queries_file:
        queries = [l.strip() for l in open(args.queries_file) if l.strip()]

    print(f"encoding {len(queries)} queries via SPLADE ({args.model})…", flush=True)
    qvecs = encode_qvecs(queries, args.model)
    json.dump(qvecs, open(f"{args.out}/qvecs.json", "w"))

    shards = sorted(glob.glob(args.shards))
    assert shards, f"no shards matched {args.shards}"
    print(f"{len(shards)} shard(s); k={args.k}", flush=True)

    baseline = {"meta": {"engine": "stock-bmp-load", "k": args.k,
                         "quant_scale": QUANT_SCALE, "alpha": ALPHA, "beta": BETA,
                         "rss_before_gb": round(rss_gb(), 3)}, "shards": {}}
    t_all = time.perf_counter()
    for sp in shards:
        s = bmp.Searcher(sp)
        rss_after = rss_gb()
        disk_mb = os.path.getsize(sp) / 1e6
        per_q = {}
        lat = []
        for q, qv in qvecs.items():
            try:
                t0 = time.perf_counter()
                ids, scores = s.search(qv, k=args.k, alpha=ALPHA, beta=BETA)
                lat.append((time.perf_counter() - t0) * 1000)
                per_q[q] = {"ids": list(ids), "scores": [round(float(x), 6) for x in scores]}
            except BaseException as exc:  # pyo3 PanicException (no query term in shard)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                per_q[q] = {"error": str(exc)}
        lat.sort()
        baseline["shards"][sp] = {
            "disk_mb": round(disk_mb, 1),
            "rss_after_load_gb": round(rss_after, 3),
            "resident_ratio_est": round((rss_after - baseline["meta"]["rss_before_gb"]) / (disk_mb / 1024), 2) if disk_mb else None,
            "lat_ms_p50": round(lat[len(lat) // 2], 2) if lat else None,
            "lat_ms_max": round(lat[-1], 2) if lat else None,
            "results": per_q,
        }
        print(f"  {sp}: {disk_mb:.0f}MB disk, rss {rss_after:.2f}GB, "
              f"p50 {baseline['shards'][sp]['lat_ms_p50']}ms", flush=True)
    baseline["meta"]["wall_s"] = round(time.perf_counter() - t_all, 1)
    json.dump(baseline, open(f"{args.out}/baseline.json", "w"), indent=1)
    print(f"\nwrote {args.out}/baseline.json + qvecs.json\n"
          f"RssAnon now {rssanon_gb():.2f} GB (stock BMP = load-into-RAM)\n"
          f"BASELINE_OK", flush=True)


if __name__ == "__main__":
    main()
