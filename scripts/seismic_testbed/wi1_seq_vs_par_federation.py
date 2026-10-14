#!/usr/bin/env python3
"""WI-1 (deployprep 2026-07-16) — clean sequential-vs-parallel federation A/B.

The `SequentialSeismicBackend` efficacy at 150M is UNMEASURED — the only prior
attempt was G8 swap-contaminated (docs/seismic_sequential_serving/README.md).
This script is the clean head-to-head the README owes: sequential vs parallel
federation over the served e5_v2 shards, warm AND cold, reporting p50/p95
latency (+ encode/traverse split), peak RssFile bound per mode, per-pass
majflt, and T1 result parity. Pre-registered in
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` (### WI-1).

Method = the E5 A/B cold protocol (doc 13 §5):
  - fresh-process mmap = naturally Linux-cold on 9p (the E5 finding);
  - `release_pages()` (mechanism B) then `posix_fadvise(DONTNEED)` per shard
    dir forces REAL faults (madvise alone only drops mapping residency →
    re-faults stay MINOR and majflt reads 0 — the E5 confound, e5_shard_gates);
  - pass 0 = COLD (first-fault), passes ≥1 = WARM (steady state);
  - arms alternate ×2 reps (deterministic majflt is the parity-of-conditions
    signal; e5_shard_gates REPS=3 lineage).

This is NOT the 31.6 GB swap-storm case. This 64 GB container (54.8 GB
MemAvailable) fits the ~15.5 GB file-backed working set in BOTH modes swap-free,
so the VmSwap==0 mechanism check (H2 of 04_BENCHMARKING.md) is trivially true
here — the measured deliverables are the CLEAN swap-free latency/RSS/parity
shapes. The swap-avoidance story stays literature+prior-evidence, clearly marked.

Usage (repo root, project venv, ONE arm per invocation — cold cell stays clean):

    SFU_SEISMIC_PREFLOOR=2 .venv/bin/python3 \\
        scripts/seismic_testbed/wi1_seq_vs_par_federation.py \\
        --federation sequential --rep 1 --result-file data/eval_results/...

Then the same with --federation parallel, alternating, rep 1 then 2. A
parity-only mode (--parity) runs BOTH classes in one process to assert T1
bit-identical top-50 against a held parallel reference (no cold eviction — warm
only; parity is a correctness check, not a latency cell).
"""
import argparse
import json
import logging
import os
import statistics
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("wi1")

TOP_K = 50
K_PRIME = 100          # served default G8f (max(2×top_k, 100))
HEAP_FACTOR = 0.8      # served default
SPLADE_QUERY_TERMS = 64
REPS = 2               # alternating reps (E5 lineage used 2 for the cold A/B)
N_QUERIES = 40


# ── RAM / fault helpers (e5_shard_gates + e6_forward_codec_proto lineage) ──────

def read_majflt() -> int:
    """Major faults (disk I/O) from /proc/self/stat field 10 (index 11)."""
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_rss() -> dict:
    """RssAnon/RssFile/VmRSS/VmSwap in GB from /proc/self/status."""
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for key in ("RssAnon", "RssFile", "VmRSS", "VmSwap"):
            if line.startswith(key + ":"):
                out[key.lower() + "_gb"] = round(int(line.split()[1]) / 1e6, 3)
    return out


def rss_peak_gb() -> float:
    """Current RssFile (resident file-backed pages) in GB — the working-set bound."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("RssFile:"):
            return int(line.split()[1]) / 1e6
    return 0.0


def fadvise_dontneed_dir(d: Path) -> int:
    """Evict a shard dir's CLEAN pages from the kernel page cache
    (posix_fadvise(POSIX_FADV_DONTNEED) per file). Runs AFTER release_pages()
    (mapped-resident pages aren't evictable); required on top of madvise
    whenever the shard fits free RAM so re-faults are MAJOR not minor
    (the E5 confound: majflt 0 = cache hit, not a cold verdict)."""
    total = 0
    for f in sorted(os.listdir(d)):
        p = d / f
        if not p.is_file():
            continue
        fd = os.open(p, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            total += os.path.getsize(p)
        finally:
            os.close(fd)
    return total


def cold_evict_all_shards(backend) -> int:
    """release_pages() (mechanism B drops mapping residency) THEN fadvise
    DONTNEED per shard dir (drops the clean page-cache pages) — the full cold
    sequence so the next search's faults are real disk I/O. Returns bytes
    advised. Sequential's .release_pages lives on each shard; parallel's shards
    share the same pyo3 index objects, so this works for BOTH classes."""
    total = 0
    for idx, mdir in zip(backend.shards, backend._shard_mmap_dirs):
        rel = getattr(idx, "release_pages", None)
        if rel is not None:
            rel()
        if mdir and Path(mdir).is_dir():
            total += fadvise_dontneed_dir(Path(mdir))
    return total


# ── query encoding (shared; the encoder is symmetric across both arms) ─────────

def encode_queries(queries, model_path):
    """Encode all queries ONCE (top-64 terms). Returning the sparse dicts lets
    the bench replay the IDENTICAL qvec across both arms (parity) and isolates
    the encode cost from the traversal cell (the 08 §A1 / G8 encode-traverse
    split). torch imports before seismic (the ENOMEM lesson)."""
    from lib.opensearch_retriever import encode_splade  # noqa: F401  (triggers torch load)
    out = []
    for q in queries:
        try:
            sparse = encode_splade(q, model_path)
        except Exception as e:
            log.warning("encode failed for %r: %s", q[:40], e)
            sparse = {}
        if sparse:
            sparse = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        out.append(sparse)
    return out


def load_queries(n, qpath):
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        p = rec["paraphrase"]
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= n:
            break
    return out


# ── stats ──────────────────────────────────────────────────────────────────────

def percentile(data, p):
    if not data:
        return None
    s = sorted(data)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def lat_stats(vals):
    if not vals:
        return None
    return {
        "p50_ms": round(percentile(vals, 50), 2),
        "p95_ms": round(percentile(vals, 95), 2),
        "mean_ms": round(sum(vals) / len(vals), 2),
        "min_ms": round(min(vals), 2),
        "max_ms": round(max(vals), 2),
        "n": len(vals),
    }


TIE_BITS = struct.Struct("<f")


def held_topk(results, top_k):
    """Build the held result snapshot (top_k oaids + f32 score bits) for T1."""
    out = []
    for oaid, score in results[:top_k]:
        out.append((oaid, TIE_BITS.pack(float(score))))
    return out


def parity_mismatch(ref, cand):
    """T1: hard mismatch count on exact-score (f32 bits) top-k order. A
    mismatch is a real bug (off-by-one / dropped shard), not an approximation.
    Returns (hard, n_compared). Ties across the k boundary are legitimate
    (order-undefined); counted via the e5 tie-aware rule only if you pass
    k_prime — here we compare the merged top_k directly."""
    hard = 0
    n = 0
    for (oa, sb), (oa2, sb2) in zip(ref, cand):
        n += 1
        if oa != oa2 or sb != sb2:
            hard += 1
    return hard, n


# ── the A/B cell ─────────────────────────────────────────────────────────────────

def run_cell(federation, query_strings, per_q_terms, index_paths, load_mode,
                rep, parity_ref=None):
    """One arm: construct the concrete backend, run cold-then-warm, return the
    cell dict + the held per-query top-k (for T1 against the parallel reference).

    We keep BOTH the query strings and the pre-encoded sparse qvec so:
      - T1 parity feeds the SAME pre-encoded qvec to both arms (encode is
        deterministic; passing the string to search_with_timing re-encodes the
        identical dict, so the arms are comparable), and
      - encode_ms + traverse_ms are a clean split (search_with_timing times
        encode_query and the fan-out separately).
    parity_ref is the held top-k from a prior parallel-arm run (sequential arm
    only); T1 asserts bit-identical oaid order + f32 score bits."""
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend)
    cls = (SequentialSeismicBackend if federation == "sequential"
           else ParallelSeismicBackend)
    log.info("=== ARM: %s (rep %d) — constructing %s over %d shards ===",
             federation, rep, cls.__name__, len(index_paths))

    rss_pre = read_rss()
    t0 = time.perf_counter()
    backend = cls(index_paths, load_mode=load_mode)
    load_secs = time.perf_counter() - t0
    rss_post_load = read_rss()
    log.info("loaded in %.1fs; RssFile %.2f→%.2f GB (RssAnon %.2f)",
             load_secs, rss_pre.get("rssfile_gb", 0),
             rss_post_load.get("rssfile_gb", 0),
             rss_post_load.get("rssanon_gb", 0))

    # Eager-warm the SPLADE ONNX session on one query so the cold pass's
    # encode_ms is steady-state, not one-time model load (the F6 / pin-tier
    # lesson; clean attribution).
    first_q = next((s for s, t in zip(query_strings, per_q_terms) if t), "")
    if first_q:
        backend.encode_query(first_q)

    # ── COLD pass ──
    evicted_bytes = cold_evict_all_shards(backend)
    mj0 = read_majflt()
    rss_peak = rss_peak_gb()

    cold_lat, cold_enc, cold_trv, cold_tops = [], [], [], []

    # search_with_timing(string) re-encodes internally; we want encode_ms +
    # traverse_ms split AND the identical pre-encoded qvec feeding both arms for
    # T1 parity. The backend's search_with_timing calls encode_query(string)
    # then search_encoded(q) — the encode is deterministic, so passing the query
    # STRING yields the same qvec as our pre-encode (we pass k_prime the served
    # default uses). Use it for the clean split + correct encode attribution.
    for s, terms in zip(query_strings, per_q_terms):
        if not terms:
            cold_lat.append(0.0); cold_enc.append(0.0); cold_trv.append(0.0)
            cold_tops.append([])
            continue
        t0 = time.perf_counter()
        res, enc, trv = backend.search_with_timing(
            s, TOP_K, k_prime=K_PRIME, heap_factor=HEAP_FACTOR)
        cold_lat.append((time.perf_counter() - t0) * 1000)
        cold_enc.append(enc)
        cold_trv.append(trv)
        cold_tops.append(held_topk(res, TOP_K))
        peak = rss_peak_gb()
        if peak > rss_peak:
            rss_peak = peak
    mj_cold = read_majflt() - mj0
    vmswap_after_cold = read_rss().get("vmswap_gb", 0)

    # ── WARM passes (steady-state serving) ──
    warm_lat, warm_enc, warm_trv = [], [], []
    WARM_PASSES = 2
    mj0w = read_majflt()
    for _ in range(WARM_PASSES):
        for s, terms in zip(query_strings, per_q_terms):
            if not terms:
                continue
            t0 = time.perf_counter()
            res, enc, trv = backend.search_with_timing(
                s, TOP_K, k_prime=K_PRIME, heap_factor=HEAP_FACTOR)
            warm_lat.append((time.perf_counter() - t0) * 1000)
            warm_enc.append(enc)
            warm_trv.append(trv)
            peak = rss_peak_gb()
            if peak > rss_peak:
                rss_peak = peak
    mj_warm = read_majflt() - mj0w
    rss_final = read_rss()

    cache_confounded = mj_cold == 0  # majflt 0 on cold = page-cache hit (E5 confound)

    cell = {
        "federation": federation,
        "backend_class": cls.__name__,
        "rep": rep,
        "load_secs": round(load_secs, 2),
        "load_mode": load_mode,
        "n_shards": len(index_paths),
        "top_k": TOP_K, "k_prime": K_PRIME, "heap_factor": HEAP_FACTOR,
        "n_queries": len([t for t in per_q_terms if t]),
        "cold": {
            "latency_ms": lat_stats(cold_lat),
            "encode_ms": lat_stats(cold_enc),
            "traverse_ms": lat_stats(cold_trv),
            "majflt_pass": mj_cold,
        },
        "warm": {
            "latency_ms": lat_stats(warm_lat),
            "encode_ms": lat_stats(warm_enc),
            "traverse_ms": lat_stats(warm_trv),
            "majflt_pass": mj_warm,
            "n_warm_passes": WARM_PASSES,
        },
        "rss": {
            "peak_rssfile_gb": round(rss_peak, 3),
            "rssfile_gb_final": rss_final.get("rssfile_gb"),
            "rssanon_gb_final": rss_final.get("rssanon_gb"),
            "vmswap_gb_after_cold": vmswap_after_cold,
            "vmswap_gb_final": rss_final.get("vmswap_gb"),
            "rssfile_gb_post_load": rss_post_load.get("rssfile_gb"),
        },
        "cold_evict_bytes": evicted_bytes,
        "cache_confounded": cache_confounded,
        "latency_by_pass_ms": {"cold": [round(x, 1) for x in cold_lat],
                               "warm": [round(x, 1) for x in warm_lat]},
    }

    # T1 parity vs the parallel reference (sequential arm only; parallel arm IS
    # the reference). bit-identical top-50: hard mismatch (oaid OR score-bits
    # differ) must be 0.
    if parity_ref is not None:
        hard_total = 0
        n_cmp = 0
        per_q = []
        for ref, cand in zip(parity_ref, cold_tops):
            hard, n = parity_mismatch(ref, cand)
            hard_total += hard
            n_cmp += n
            per_q.append(hard)
        cell["t1_parity"] = {
            "hard_mismatches": hard_total,
            "queries_compared": len(per_q),
            "tuples_compared": n_cmp,
            "hard_per_query": per_q,
            "verdict": "BIT_IDENTICAL" if hard_total == 0 else "PARITY_FAIL",
        }

    return cell, cold_tops


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--federation", choices=["parallel", "sequential"],
                    default="parallel")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--shard-manifest",
                    default="data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json",
                    help="served e5 dv-v2 manifest (default)")
    ap.add_argument("--queries", type=int, default=N_QUERIES)
    ap.add_argument("--splade-model", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data" / "eval_results" / "diverse_queries.json"))
    ap.add_argument("--parity-ref", default=None,
                    help="path to a parallel-arm cell JSON (cold_tops) to T1-compare "
                         "this sequential arm against")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    from lib.thinclient.sharded_seismic_backend import _load_manifest
    load_mode = "mmap"
    index_paths = _load_manifest(args.shard_manifest, load_mode=load_mode)
    if not index_paths:
        raise RuntimeError(f"no shard paths from {args.shard_manifest}")
    if len(index_paths) != 8:
        raise RuntimeError(f"expected 8 shards, got {len(index_paths)}")

    queries = load_queries(args.queries, Path(args.query_workload))
    log.info("encoding %d queries (model=%s)...", len(queries), args.splade_model)
    per_q_terms = encode_queries(queries, args.splade_model)
    n_empty = sum(1 for t in per_q_terms if not t)
    if n_empty:
        raise RuntimeError(f"{n_empty}/{len(queries)} queries failed to encode — "
                           "the encoder path is broken; refusing to bench")

    parity_ref = None
    if args.parity_ref:
        ref = json.loads(Path(args.parity_ref).read_text())
        # held top-k stored as [[oaid, score_hex], ...] per query
        parity_ref = []
        for q in ref["cold_tops"]:
            parity_ref.append([(oaid, bytes.fromhex(hx)) for oaid, hx in q])

    cell, cold_tops = run_cell(args.federation, queries, per_q_terms,
                               index_paths, load_mode, args.rep, parity_ref)

    # stash the held top-k for the parity ref (compact: oaid + score f32 hex)
    cold_tops_ser = [[ [oaid, sb.hex()] for (oaid, sb) in q] for q in cold_tops]

    result = {
        "meta": {
            "date_utc": datetime.utcnow().isoformat(timespec="seconds"),
            "experiment": "WI-1 sequential-vs-parallel federation A/B (deployprep)",
            "shard_manifest": args.shard_manifest,
            "container_memavailable_gb": _memavailable_gb(),
            "prefloor_env": os.environ.get("SFU_SEISMIC_PREFLOOR", "0"),
        },
        **cell,
        "cold_tops": cold_tops_ser,
    }
    if args.result_file:
        rf = Path(args.result_file)
    else:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        rf = REPO / "data" / "eval_results" / f"wi1_seq_vs_par_{args.federation}_rep{args.rep}_{ts}.json"
    rf.parent.mkdir(parents=True, exist_ok=True)
    rf.write_text(json.dumps(result, indent=2))
    log.info("result written to %s", rf)

    # Headline summary
    log.info("=== %s rep %d SUMMARY ===", args.federation, args.rep)
    log.info("  COLD p50/p95: %s / %s ms (encode %s / traverse %s) majflt=%d",
             cell["cold"]["latency_ms"]["p50_ms"],
             cell["cold"]["latency_ms"]["p95_ms"],
             cell["cold"]["encode_ms"]["p50_ms"],
             cell["cold"]["traverse_ms"]["p50_ms"],
             cell["cold"]["majflt_pass"])
    log.info("  WARM p50/p95: %s / %s ms (encode %s / traverse %s) majflt=%d",
             cell["warm"]["latency_ms"]["p50_ms"],
             cell["warm"]["latency_ms"]["p95_ms"],
             cell["warm"]["encode_ms"]["p50_ms"],
             cell["warm"]["traverse_ms"]["p50_ms"],
             cell["warm"]["majflt_pass"])
    log.info("  peak RssFile %.2f GB; VmSwap after-cold %s GB; confounded=%s",
             cell["rss"]["peak_rssfile_gb"],
             cell["rss"]["vmswap_gb_after_cold"], cell["cache_confounded"])
    if "t1_parity" in cell:
        log.info("  T1 parity: %s (%d hard mismatches / %d tuples)",
                 cell["t1_parity"]["verdict"],
                 cell["t1_parity"]["hard_mismatches"],
                 cell["t1_parity"]["tuples_compared"])

    # Confound guard: a cache-confounded cold cell is NOT a cold verdict.
    if cell["cache_confounded"]:
        log.error("COLD majflt=0 → page-cache confound (the E5 trap). The cold "
                  "latency is a cache-hit number, NOT a disk-cold verdict. "
                  "Re-run after confirming posix_fadvise(DONTNEED) covered the "
                  "shard dirs (cold_evict_bytes=%d).",
                  cell["cold_evict_bytes"])

    return 0


def _memavailable_gb():
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return round(int(ln.split()[1]) / (1024 ** 2), 2)
    except OSError:
        pass
    return None


if __name__ == "__main__":
    sys.exit(main())
