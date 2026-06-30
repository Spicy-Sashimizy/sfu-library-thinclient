#!/usr/bin/env python3
"""SEISMIC testbed — Plan 01: federated query over K sharded indices.

The serving layer for the sharded build (Plan 01). Loads K SEISMIC shards and
federates a query across all of them in parallel, merging by raw score.

**Why merge by raw score (no normalization):** SEISMIC scores are inner products
on a *shared* SPLADE vocabulary. Every shard was built from the same token space
(BERT subword tokens stored as `seismic.get_seismic_string()` U30), and the query
is the identical encoded SPLADE qvec issued to each shard. So per-shard scores
live in the same dot-product space → directly comparable → a global top-k is just
"merge all per-shard top-k' by score, take the top-k." This is the property that
makes federation result-safe (modulo per-shard pruning — gated separately in
`g_federation_overlap.py`).

**Over-fetch.** Each shard returns its local top-`k'` (default `4×k`). Too-small
`k'` truncates the global top-k; the overlap gate verifies stability. SEISMIC's
own scoring already prunes per-list, so `k'=4k` is generous for a global top-50.

**Concurrency.** One thread per shard (K small, e.g. 8). The pyseismic `.so`
releases the GIL during C-level search, so a `ThreadPoolExecutor` gets real
parallelism despite the GIL. Building more shards than cores just queues — no
 RSS stacking (shards are loaded once at startup, the build-RAM wall is the
 build, not this).

NOTE on stock `.load()` (measured 2026-06-28): `SeismicIndex.load()` deserializes
into *owned anonymous RAM* (1.7 GB → RssAnon 1.706 GB, RssFile flat) — Path A,
NOT mmap. At persona scale (K×~1.7 GB) that fits the 32 GB box. At full 150M
scale, stock `.load()` would put the ~137 GB Path-A floor × the sharded total in
RAM → unaffordable on 32 GB. **C2.5 (2026-06-28, MMAP_SERVE_READY) shipped the
pyo3 mmap reader (`seismic.MmapSeismicIndex`): anon Δ 0.0 GB, 96% file-resident,
parity bit-identical.** `--load-mode mmap` (or `SFU_SEISMIC_LOAD_MODE=mmap`) loads
each shard from a converted sibling `X.mmap/` dir (produced by
`convert_shard_to_mmap.py`); it raises a clean RuntimeError if a dir is absent
— never a silent Path-A fallback (which would silently re-introduce the floor).
Default stays `stock` so the persona federation-overlap gate + all prior results
remain reproducible bit-for-bit; the 150M serve run uses `mmap`.

Plug-in shape mirrors `SeismicBackend.search() -> [(oaid, score)]`, so it drops
into the G2/G6 harnesses via the `SFU_SPLADE_BACKEND=seismic` shim with a
manifest path (Piece C wires it; the served retriever stays Qdrant).

Run from repo root (project venv):

    # standalone federation probe
    .venv/bin/python3 scripts/seismic_testbed/seismic_federated.py \
        --manifest /tmp/seismic_testbed/jsonl/shards/med_bio_shards2_manifest.json \
        --query "machine learning for drug discovery" --top-k 10 --k-prime 40
"""
import argparse
import concurrent.futures as cf
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

# Canonical implementation lives in the served package so the live retriever's
# `SFU_SPLADE_BACKEND=seismic` branch can import it without depending on
# `scripts/`. This module re-exports it (mirrors `seismic_backend.py` shim) so
# all testbed harnesses keep `from seismic_federated import ShardedSeismicBackend`
# unchanged. Canonical: src/lib/thinclient/sharded_seismic_backend.py.
# The two concrete serving classes are also exported for new code; the
# ShardedSeismicBackend selector remains for back-compat (defaults to parallel).
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402,F401
    ShardedSeismicBackend,
    ParallelSeismicBackend,
    SequentialSeismicBackend,
    _EncoderShim,
    _load_manifest,
)

log = logging.getLogger("seismic_federated")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True,
                    help="built-index manifest (shard_indexes key), JSON list, or "
                         "comma-separated .index.seismic paths")
    ap.add_argument("--splade-model", default="models/splade_onnx_fp16")
    ap.add_argument("--query", required=True)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--k-prime", type=int, default=None, help="per-shard over-fetch (default 4×k)")
    ap.add_argument("--query-cut", type=int, default=None)
    ap.add_argument("--heap-factor", type=float, default=0.8)
    ap.add_argument("--load-mode", choices=("stock", "mmap"), default=None,
                    help="shard load path: 'stock' (Path-A owned anon, default) or "
                         "'mmap' (Path-C, needs converted X.mmap/ dirs). "
                         "Env SFU_SEISMIC_LOAD_MODE overrides the default.")
    ap.add_argument("--federation", choices=("parallel", "sequential"), default=None,
                    help="serving method over the K shards: 'parallel' (default — "
                         "ThreadPoolExecutor fan-out, latency ~= max shard) or "
                         "'sequential' (one shard at a time, latency ~= sum of "
                         "shards, bounded resident set; bit-identical results; "
                         "docs/seismic_sequential_serving/). "
                         "Env SFU_SEISMIC_FEDERATION overrides the default.")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    load_mode = args.load_mode or os.environ.get("SFU_SEISMIC_LOAD_MODE", "stock")
    federation = args.federation or os.environ.get("SFU_SEISMIC_FEDERATION", "parallel")
    index_paths = _load_manifest(args.manifest)
    assert index_paths, f"no shard indexes from --manifest {args.manifest}"
    log.info("federated: %d shards (load_mode=%s, federation=%s)",
             len(index_paths), load_mode, federation)
    # Pick the concrete serving class directly (two distinct methods; the env
    # default 'parallel' is the historical server-side fan-out).
    cls = SequentialSeismicBackend if federation == "sequential" else ParallelSeismicBackend
    sb = cls(index_paths, splade_model_path=args.splade_model, load_mode=load_mode)
    t0 = time.perf_counter()
    res = sb.search(args.query, args.top_k, query_cut=args.query_cut,
                    heap_factor=args.heap_factor, k_prime=args.k_prime)
    dt = (time.perf_counter() - t0) * 1000
    log.info("federated search: %d results in %.1f ms (k_prime=%s)", len(res), dt, args.k_prime)
    for oaid, score in res:
        print(f"  {score:.4f}  {oaid}")
    print(json.dumps({"results": [{"oaid": o, "score": s} for o, s in res],
                      "ms": round(dt, 2), "n_shards": len(index_paths)}))


if __name__ == "__main__":
    main()
