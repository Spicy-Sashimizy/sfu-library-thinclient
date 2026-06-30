#!/usr/bin/env python3
"""SEISMIC testbed — Plan 01: hash-partition the spool into K deterministic shards.

OpenSearch serves SEISMIC at billion-scale by building small immutable segments and
federating queries. This is the pure-Rust, no-JVM port of just that one idea: build
the corpus as K independent SEISMIC shards (each small enough to build in RAM on the
32 GB host), then federate at query time. Lossless per shard — no quantization, no
nnz pruning; the only quality variable (per-shard vs global pruning) is gated
separately in `g_federation_overlap.py`.

**Determinism is load-bearing.** A doc must always land in the same shard so re-runs
are reproducible and so a 2-shard federated query is comparable to a 1-shard single
index over the same docs. `shard_id = blake2b(oaid + seed, 8 bytes) % K`. `blake2b`
is seeded and stable across processes (unlike the built-in `hash()`); xxhash is not
in the serving venv, so this is dependency-free. Hash-partition (not range) keeps
shards balanced in nnz → even build-RAM (gate-zero for the per-shard build budget).

Reuses `spool_to_seismic_jsonl.iter_slice` (the streaming zstd reader, never holds a
full slice in RAM — a 2.86 GB compressed med_bio slice decompresses far past the ~7 GB
free on the 31 GB host). Writes all K shards in ONE pass over the spool: each doc is
routed to its shard's open writer by hash. (K parallel writers; one read of the spool.)

Mirrors the isolation convention of `spool_to_seismic_jsonl.py`: writes to an EXTERNAL
ext4 dir, NOT the serving `data/` path; never deletes spool slices.

Run from repo root (project venv — has zstandard + orjson):

    .venv/bin/python3 scripts/seismic_testbed/shard_spool.py \\
        --section med_bio \\
        --out-dir /tmp/seismic_testbed/jsonl/shards \\
        --n-shards 2 --limit 4000000       # the 2x2M federation-overlap split

The full 150M build (Plan 01 step 2) uses --n-shards 8 with no --limit.
"""
import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

# Reuse the streaming reader + orjson/json fallback from the sibling converter.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spool_to_seismic_jsonl import iter_slice  # noqa: E402

log = logging.getLogger("shard_spool")


def shard_id(oaid: str, seed: str, n_shards: int) -> int:
    """Deterministic shard routing. blake2b is seeded + stable across processes
    (unlike builtin hash()); xxhash isn't in the venv, so this is dependency-free.
    The seed lets a future re-key without colliding with a prior partitioning."""
    h = hashlib.blake2b((seed + str(oaid)).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % n_shards


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", default="med_bio")
    ap.add_argument("--spool-root", default="data/thinclient_index/spool_backup")
    ap.add_argument("--out-dir", required=True,
                    help="external ext4 dir (NOT the serving data/ path)")
    ap.add_argument("--n-shards", type=int, required=True, help="K (partition count)")
    ap.add_argument("--hash-seed", default="sfu-seismic-plan01",
                    help="seed mixed into the oaid hash (re-key without colliding)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap docs across all shards (persona / federation-gate scale; "
                         "None = full section)")
    ap.add_argument("--slices", type=int, default=None,
                    help="optional: only first N slices (None=all)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    spool_dir = Path(args.spool_root) / args.section
    slices = sorted(spool_dir.glob("slice_*.jsonl.zst"))
    assert slices, f"no slices at {spool_dir}"
    if args.slices:
        slices = slices[:args.slices]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    K = args.n_shards
    # One writer per shard. Each emits SEISMIC native jsonl {"id","vector"} — same
    # format build_persona_seismic.build() consumes — so a shard IS a build input.
    shard_paths = [out_dir / f"{args.section}_shard{i}of{K}.jsonl" for i in range(K)]
    fouts = [open(p, "w") for p in shard_paths]

    # Per-shard counters for the manifest.
    n_per = [0] * K
    n_terms_per = [0] * K
    max_terms_per = [0] * K
    n_empty = 0
    n = 0
    t0 = time.perf_counter()
    log.info("shard_spool: section=%s slices=%d K=%d seed=%s limit=%s -> %s",
             args.section, len(slices), K, args.hash_seed, args.limit, out_dir)
    try:
        for sp in slices:
            if args.limit is not None and n >= args.limit:
                break
            log.info("  %s", sp.name)
            for rec in iter_slice(sp):
                if args.limit is not None and n >= args.limit:
                    break
                sparse = rec.get("sparse_field")
                if not sparse:
                    n_empty += 1
                    continue
                doc_id = rec.get("openalex_id") or rec.get("id")
                if doc_id is None:
                    n_empty += 1
                    continue
                sid = shard_id(doc_id, args.hash_seed, K)
                # NO re-encode: the stored sparse_field IS the SPLADE vector.
                fouts[sid].write(json.dumps({"id": doc_id, "vector": sparse}))
                fouts[sid].write("\n")
                n_per[sid] += 1
                nt = len(sparse)
                n_terms_per[sid] += nt
                if nt > max_terms_per[sid]:
                    max_terms_per[sid] = nt
                n += 1
            if args.limit is not None and n >= args.limit:
                break
            log.info("    running docs=%d (per-shard: %s)", n, n_per)
    finally:
        for f in fouts:
            f.close()

    dt = time.perf_counter() - t0
    sizes_gb = [p.stat().st_size / 1e9 for p in shard_paths]
    avg_terms = [(n_terms_per[i] / n_per[i] if n_per[i] else 0) for i in range(K)]
    log.info("sharded %d docs into %d shards in %.1fs (%.0f docs/s, %d empty/skipped)",
             n, K, dt, n / dt if dt else 0, n_empty)
    for i in range(K):
        log.info("  shard%d: %d docs, %.3f GB, avg_terms=%.1f", i, n_per[i], sizes_gb[i], avg_terms[i])

    # Balance check (gate-zero for even build-RAM): max/min per-shard docs.
    if all(x > 0 for x in n_per):
        ratio = max(n_per) / min(n_per)
        log.info("balance: max/min docs per shard = %.3f (want ~1.0)", ratio)

    manifest = {
        "section": args.section,
        "n_shards": K,
        "hash_seed": args.hash_seed,
        "hash_fn": "blake2b(seed+oaid, digest_size=8) int % K",
        "shards": [{
            "shard": i, "jsonl": str(shard_paths[i]),
            "docs": n_per[i], "on_disk_gb": round(sizes_gb[i], 4),
            "avg_terms_per_doc": round(avg_terms[i], 2),
            "max_terms_per_doc": max_terms_per[i],
        } for i in range(K)],
        "docs_total": n, "empty_skipped": n_empty,
        "limit": args.limit,
        "slices_used": [s.name for s in slices],
        "built_utc": "2026-06-28",
        "source": "spool_backup sparse_field (NO re-encode), Plan 01 hash-partition",
        "purpose": "Plan 01: K shards each build in RAM on 32 GB; federated query merges",
    }
    mpath = out_dir / f"{args.section}_shards{K}_manifest.json"
    json.dump(manifest, open(mpath, "w"), indent=2)
    log.info("wrote manifest %s", mpath)
    print(json.dumps({"docs_total": n, "n_shards": K, "per_shard": n_per,
                      "manifest": str(mpath), "max_min_ratio":
                       (max(n_per) / min(n_per)) if all(x > 0 for x in n_per) else None}))


if __name__ == "__main__":
    main()
