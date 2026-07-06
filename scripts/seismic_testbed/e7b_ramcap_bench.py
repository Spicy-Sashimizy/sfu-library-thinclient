#!/usr/bin/env python3
"""SEISMIC testbed — E7b: the RAM-capped f16-vs-dotvbyte re-bench (single codec
per process; run TWICE, once per --index-dir, under the SAME external memory
cap). This is the decisive experiment the E7 gate-c track exists for
(`10_FORWARD_COMPRESSION_DESIGN.md` §7 "E7b"): at a cap where the f16 forward
no longer fits page cache, dotvbyte's −41% fault mass should dominate and its
+~2% warm-CPU cost should vanish next to re-fault stalls.

DESIGN — why this is NOT the e7 gates harness:
  * ONE index per process. The gates harness loads both codecs into one
    process; under a shared cap they would fight for the same page cache and
    the ratio would be confounded. Parity (gate a, 0.995) is already settled —
    E7b only needs per-codec sustained throughput under pressure.
  * NO release_pages(). The cap itself is the eviction mechanism — that is the
    regime being measured. Passes run back-to-back; pass 1 is the cold fill,
    later passes measure the steady re-fault state (does the working set fit?).
  * NO torch inside the capped process. SPLADE encoding costs ~1.5 GB anon RSS
    which would eat the cap. Encode ONCE, uncapped, with --encode-only; the
    capped runs then load the tiny json (--encoded-queries) and never import
    torch.

USAGE (from repo root):
  # once, uncapped — writes the encoded-queries json:
  .venv/bin/python3 scripts/seismic_testbed/e7b_ramcap_bench.py --encode-only

  # per codec, under the external cap (host: systemd-run -p MemoryMax=…,
  # docker run --memory=…, or any cgroup wrapper — see HOST_PROMPT_E7B_RAMCAP.md):
  .venv/bin/python3 scripts/seismic_testbed/e7b_ramcap_bench.py \
      --index-dir data/seismic_150m/index/plan01/global_shard0of8.mmap \
      --passes 4 --result-file data/eval_results/e7b_f16_cap6g.json

Interpretation: compare per-pass traverse p50 + majflt between the two codecs
at the same cap. The promotion hypothesis is TRUE iff, at a cap where f16 has
cliffed (pass≥2 p50 ≫ its uncapped warm p50, majflt/pass stays high) and
dotvbyte has not (pass≥2 p50 near its uncapped warm), dotvbyte's sustained p50
beats f16's. Record swap: if vmswap_kb > 0 the run is swap-confounded and the
number is recorded-not-concluded (the G8 §A1 lesson).
"""
import argparse
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("e7b")

K_PRIME = 200
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
ENCODED_DEFAULT = REPO / "data/eval_results/e7b_encoded_queries.json"


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_vm() -> dict:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for k in ("VmRSS", "VmSwap", "RssFile", "RssAnon"):
            if line.startswith(k + ":"):
                out[k.lower() + "_kb"] = int(line.split()[1])
    return out


def encode_queries(n_queries: int, workload: Path, model_path: str, out: Path):
    from e6_forward_codec_proto import load_queries  # noqa: E402
    from lib.opensearch_retriever import encode_splade  # noqa: E402
    queries = load_queries(n_queries, workload)
    enc = []
    for q in queries:
        sparse = encode_splade(q, model_path)
        enc.append(dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"n_queries": len(enc), "terms": enc}, open(out, "w"))
    log.info("wrote %d encoded queries -> %s", len(enc), out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-dir", default=None,
                    help="ONE shard dir (f16 or dotvbyte — the loader dispatches)")
    ap.add_argument("--passes", type=int, default=4,
                    help="back-to-back full-workload passes (pass 1 = cold fill)")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--k-prime", type=int, default=K_PRIME)
    ap.add_argument("--encoded-queries", default=str(ENCODED_DEFAULT))
    ap.add_argument("--encode-only", action="store_true",
                    help="encode the query workload (uncapped, torch) and exit")
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--cap-label", default="uncapped",
                    help="recorded in meta; state the external cap (e.g. 6G)")
    args = ap.parse_args()

    if args.encode_only:
        encode_queries(args.queries, Path(args.query_workload),
                       args.model_path, Path(args.encoded_queries))
        return
    assert args.index_dir, "--index-dir required (or --encode-only)"

    enc = json.load(open(args.encoded_queries))
    per_q_terms = enc["terms"][: args.queries]
    log.info("loaded %d pre-encoded queries (torch never imported)", len(per_q_terms))

    import numpy as np
    import seismic
    string_dtype = seismic.get_seismic_string()
    idx = seismic.MmapSeismicIndex(args.index_dir)
    log.info("index: %s docs=%d format=%s vm=%s",
             args.index_dir, idx.len, idx.forward_format, read_vm())

    passes = []
    for p in range(args.passes):
        mj0 = read_majflt()
        lat_ms = []
        t_pass = time.perf_counter()
        for terms in per_q_terms:
            qcomp = np.array(list(terms.keys()), dtype=string_dtype)
            qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
            t0 = time.perf_counter()
            idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                       k=args.k_prime, query_cut=len(terms), heap_factor=HEAP_FACTOR)
            lat_ms.append((time.perf_counter() - t0) * 1000)
        cell = {
            "pass": p,
            "traverse_ms_p50": round(statistics.median(lat_ms), 3),
            "traverse_ms_p95": round(sorted(lat_ms)[int(0.95 * (len(lat_ms) - 1))], 3),
            "pass_wall_s": round(time.perf_counter() - t_pass, 2),
            "majflt": read_majflt() - mj0,
            "vm": read_vm(),
        }
        passes.append(cell)
        log.info("pass %d: p50 %.2f ms, p95 %.2f ms, majflt %d, vm %s",
                 p, cell["traverse_ms_p50"], cell["traverse_ms_p95"],
                 cell["majflt"], cell["vm"])

    summary = {
        "meta": {
            "purpose": "E7b RAM-capped re-bench — one codec per capped process "
                       "(10_FORWARD_COMPRESSION_DESIGN.md §7 E7b)",
            "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "index_dir": args.index_dir,
            "forward_format": idx.forward_format,
            "n_queries": len(per_q_terms), "k_prime": args.k_prime,
            "heap_factor": HEAP_FACTOR, "passes": args.passes,
            "cap_label": args.cap_label,
            "swap_confounded": passes[-1]["vm"].get("vmswap_kb", 0) > 0,
        },
        "passes": passes,
    }
    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/e7b_ramcap_{idx.forward_format}_{args.cap_label}_{time.strftime('%Y%m%d_%H%M')}.json")
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"forward_format": idx.forward_format, "cap": args.cap_label,
                      "passes": [{k: c[k] for k in ("pass", "traverse_ms_p50", "majflt")}
                                 for c in passes],
                      "swap_confounded": summary["meta"]["swap_confounded"],
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
