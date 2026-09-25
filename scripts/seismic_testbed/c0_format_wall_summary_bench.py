#!/usr/bin/env python3
"""SEISMIC testbed — G3 Path C / Step C0: FORMAT-WALL micro-benchmark on the
summary structure alone.

`docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md` §3 Step C0 — "the cheapest
*nformative* next run": a FORMAT-WALL micro-bench on the summary structure
(44% of the floor, the hardest zero-decode surface). It decides Path C
(eibecability before paying the full fork: "can the traversal touch the
731 MB of summaries each query, zero-decode, at the serving latency target?"

WHY THIS BENCH IS THE GATE (not assumed from BMP)
-------------------------------------------------
The project already proved zero-decode cures the wall once — on BMP's forward
index: `memmap2` + `bytemuck::cast_slice` over `#[repr(C)]` POD flipped
696 ms → 25.63 ms (`docs/archive/sparse_engine_project` G1 / `R3v2_delta.patch`,
re-expressed in `01_ARCHITECTURE.md:82-133`). But SEISMIC's summary structure
is NOT a flat POD blob the way BMP's forward block was. Upstream
`QuantizedSummary<C>` (`spike/seismic_upstream/src/quantized_summary.rs:14`)
is:

    pub struct QuantizedSummary<C> {
        n_summaries: usize, dim: usize,
        component_ids: Option<Box<[C]>>,
        offsets:       EliasFano,        // <- compressed; select() per query term
        summaries_ids: BitField,         // <- compressed; per-pos fetch
        values:        Box<[u8]>,         // <- the only flat POD slab
        minimums: Box<[f32]>, quants: Box<[f32]>,   // dequant LUTs, random access
    }

and its hot loop `distances()` does, per query term:
`offsets.select(i)` → `values[off..next]` → `summaries_ids[pos]` →
`v * quants[s_id] + minimums[s_id]` → accumulate. TWO of the four structures
(offsets.select, summaries_ids) are compressed formats that decode per query —
exactly the "encoded bytes that transform on read" the FORMAT-WALL warning
(`01_ARCHITECTURE.md:92`) says rebuilds the 696 ms wall on the 44% slab.

So C0's question is sharp and not derivable from the BMP win: **can the per-
query summary scan be served from a flat mmap'd POD layout zero-decode (no
per-query select/BitField materialize), holding latency?** This bench answers
that for the *layout axis in isolation*, on a fixed work budget so the G4
pruning confound can't hide behind corpus growth.

WHAT IT MEASURES
----------------
Two readers over an identical summary slab, SAME total work (N_terms queries ×
M slabs touched), so the latency delta isolates to FORMAT, not corpus size:

  * TREATMENT (zero-decode, the Path-C cure): read the slab as a `numpy`
    view re-cast over the mmap (`np.frombuffer(..., dtype=POD).view(...)`),
    the Python analogue of `bytemuck::cast_slice` over the mmap. No per-query
    allocation, no copy, no decode — bytes are read straight from page cache.
  * CONTROL (FORMAT-WALL, the re-creator of 696 ms): the same scan done
    `take()`/materialize-style: copy the touched bytes into a fresh array per
    query, then re-index — reproducing a per-query decode/materialize.

Cold vs warm (per `03_BENCHMARK_METHODOLOGY.md:42` "warm p50/p95, cold p95"):
  * WARM  = touch every page once before timing (page cache hot).
  * COLD  = `posix_fadvise(POSIX_FADV_DONTNEED)` over the mmap before each
            timed query, so the first touch is a real page fault (best-effort;
            needs the slab on disk, not tmpfs — see --slab-dir).

VERDICT (against `07` §6 latency budget, within ~20% of in-RAM Path A):
  PATH_C_FEASIBLE  if cold zero-decode p50 is within 1.2× of warm materialize
                   AND ≫ faster than cold materialize (the FORMAT-WALL gap).
  FORMAT_WALL      if cold zero-decode ≈ cold materialize (no format win) or
                   if zero-decode regresses — Path C must be re-scoped before
                   the fork; trust the C1 reader design to the bench, not hope.

NOTE on provenance: this bench operates on a FAITHFUL-SHAPE summary slab, not
real SEISMIC summary bytes (pyseismic exposes no per-block summary dump). The
slab reproduces QuantizedSummary's hot fields at the right widths and access
pattern (u8 values + u32 summary_ids + u32 term_offsets over a values vec) so
the FORMAT delta is honest; it is NOT a recall/quality bench (that is G2, §5).
See "Faithfulness" below for the exact shape pinned to the upstream struct.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/c0_format_wall_summary_bench.py \\
        --slab-dir /tmp/seismic_testbed/c0 \\
        --result-file data/eval_results/seismic_c0_formatwall_<ts>.json
"""
import argparse
import gc
import json
import logging
import mmap
import os
import struct
import tempfile
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("seismic_c0")

# Faithfulness to upstream QuantizedSummary<C> (quantized_summary.rs:14-23).
# The hot fields and their widths:
#   values:        Box<[u8]>   -> 8-bit quantized sketch values      (the slab)
#   summaries_ids: BitField    -> we model as u32 (>= n_summaries)     (random idx into LUT)
#   offsets:       EliasFano   -> we model as u32 term_offsets        (select(i) → range into values)
#   minimums/quants: [f32]    -> dequant LUT, random access by s_id
# n.b. the REAL compressed offsets/BitField are *smaller* but decode-per-query;
# modeling them as flat u32 here is the BEST CASE for zero-decode (no decode
# cost at all). If even this best-case slab can't hold latency zero-decode,
# the real compressed form (which must also pay select/BitField) can't either.
VALUE_DTYPE = "u1"          # u8  — the values slab
SID_DTYPE = "u4"            # u32 — summary_id (>= n_summaries, modeled flat = best case)
OFFSET_DTYPE = "u4"         # u32 — term offset into VALUES (EliasFano, modeled flat = best case)
F32 = "f4"                  # f32 — minimums / quants LUT

# The POD record the zero-decode reader casts each (s_id, value) pair to.
# `#[repr(C)]`-equivalent on disk: struct SummaryPair { s_id: u32, value: u8, _pad: [u8;3] }.
# 8 bytes, naturally aligned — bytemuck::cast_slice would yield the same stride.
POD_DTYPE = [("s_id", SID_DTYPE), ("value", VALUE_DTYPE), ("_pad", "u1", 3)]


def gb(kb):
    return round(kb / 1024 / 1024, 4) if kb else None


def rssanon_kb():
    for line in open("/proc/self/status"):
        if line.startswith("RssAnon:"):
            return int(line.split()[1])
    return None


def rssfile_kb():
    for line in open("/proc/self/status"):
        if line.startswith("RssFile:"):
            return int(line.split()[1])
    return None


# --------------------------------------------------------------------------- //
# Slab builder. Produces a flat mmap'd file reproducing QuantizedSummary's
# VALUES slab + the index structures a query touches, at faithful widths.
# Layout (one file, all little-endian, absolute offsets):
#   [0]    header:  magic u32 | n_terms u32 | n_summaries u32 | n_values u32
#   [16]   term_offsets: u32[n_terms+1]      (select(i) → values[off..next])
#   [..]   summary_ids: u32[n_values]       (s_id per value — modeled flat)
#   [..]   values:  u8[n_values]             (the 44%-slab, the bytes scored)
#   [..]   minimums: f32[n_summaries]        (dequant LUT)
#   [..]   quants:   f32[n_summaries]        (dequant LUT)
# The zero-decode reader casts `values` + `summary_ids` as POD pairs; the
# control reader materializes them per query.

MAGIC = 0x5A45524F  # "ZERO"
HEADER = struct.Struct("<IIII")   # magic, n_terms, n_summaries, n_values
U32 = struct.Struct("<I")


def build_slab(path: Path, n_terms: int, n_summaries: int, avg_values_per_term: int,
               seed: int = 20260626) -> dict:
    """Write a faithful-shape summary slab to `path`; return its geometry."""
    import numpy as np
    rng = np.random.default_rng(seed)

    # Per-term value counts (≡ postings-per-block spread). Sum = n_values.
    counts = rng.integers(low=avg_values_per_term // 2,
                          high=avg_values_per_term * 3 // 2 + 1,
                          size=n_terms, dtype=np.uint64)
    # Guard against empty slabs (a term with 0 values is legal upstream).
    counts = np.maximum(counts, 1)
    n_values = int(counts.sum())
    offsets = np.zeros(n_terms + 1, dtype=np.uint32)
    offsets[1:] = np.cumsum(counts).astype(np.uint32)

    # The slab bytes (50% sparse sparsity for the random s_ids: each value
    # belongs to a summary block; model uniform over n_summaries).
    summary_ids = rng.integers(low=0, high=n_summaries, size=n_values,
                               dtype=np.uint32)
    values = rng.integers(low=0, high=256, size=n_values, dtype=np.uint8)
    minimums = rng.uniform(-1.0, 0.0, size=n_summaries).astype(np.float32)
    quants = rng.uniform(0.0, 0.1, size=n_summaries).astype(np.float32)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_TRUNC)
    try:
        header = HEADER.pack(MAGIC, n_terms, n_summaries, n_values)
        os.write(fd, header)
        os.write(fd, offsets.tobytes())
        os.write(fd, summary_ids.tobytes())
        os.write(fd, values.tobytes())
        os.write(fd, minimums.tobytes())
        os.write(fd, quants.tobytes())
        os.fsync(fd)
    finally:
        os.close(fd)

    return {"path": str(path), "n_terms": n_terms, "n_summaries": n_summaries,
            "n_values": n_values, "bytes": 16 + offsets.nbytes +
            summary_ids.nbytes + values.nbytes + minimums.nbytes + quants.nbytes,
            "values_bytes": values.nbytes}


def parse_slab(fd: int) -> dict:
    """Read the header + section offsets (the index a reader builds once)."""
    import numpy as np
    os.lseek(fd, 0, os.SEEK_SET)
    magic, n_terms, n_summaries, n_values = HEADER.unpack(os.read(fd, 16))
    assert magic == MAGIC, f"bad magic {magic:#x} (not a C0 slab)"
    off_offsets = 16
    off_sids = off_offsets + (n_terms + 1) * 4
    off_values = off_sids + n_values * 4
    off_mins = off_values + n_values
    off_quants = off_mins + n_summaries * 4
    # term offsets read once, kept in RAM (small: (n_terms+1)*4B).
    os.lseek(fd, off_offsets, os.SEEK_SET)
    offsets = np.frombuffer(os.read(fd, (n_terms + 1) * 4), dtype=OFFSET_DTYPE)
    return {"n_terms": n_terms, "n_summaries": n_summaries, "n_values": n_values,
            "off_sids": off_sids, "off_values": off_values,
            "off_mins": off_mins, "off_quants": off_quants,
            "term_offsets": offsets}


# --------------------------------------------------------------------------- //
# Readers. Both take a workload = list of query-term indexes (which cells of the
# values slab to score), and accumulate dequantized dot products into an
# n_summaries-length accumulator — the exact shape of QuantizedSummary::distances.

SUMMARY_ACC_DTYPE = "f4"   # f32 accumulator, mirrors upstream Vec<f32>


def reader_zero_decode(mm: mmap.mmap, slab: dict, workload, acc):
    """Path-C cure: `bytemuck::cast_slice` analogue over the mmap. Casts the
    values + s_ids region as a combined POD array once, then per query term
    slices it with NO per-query allocation/decode. Reads straight from page
    cache."""
    import numpy as np
    # The POD cast over the mmap sub-slice (values + s_ids interleaved is NOT
    # how upstream stores them, but they are contiguous as paired columns; we
    # view them as two flat arrays side by side and slice in lockstep — zero
    # decode). Cast once, reuse across all queries.
    values = np.frombuffer(mm, dtype=VALUE_DTYPE, count=slab["n_values"],
                           offset=slab["off_values"])
    sids = np.frombuffer(mm, dtype=SID_DTYPE, count=slab["n_values"],
                        offset=slab["off_sids"])
    mins = np.frombuffer(mm, dtype=F32, count=slab["n_summaries"],
                        offset=slab["off_mins"])
    quants = np.frombuffer(mm, dtype=F32, count=slab["n_summaries"],
                          offset=slab["off_quants"])
    toff = slab["term_offsets"]
    acc.fill(0.0)
    # A workload query is a list of query term indexes + a scalar weight each;
    # we use weight=1.0 (the FORMAT delta is independent of the weight).
    for qlist in workload:
        for ti, qw in qlist:
            lo = toff[ti]; hi = toff[ti + 1]
            v = values[lo:hi]              # zero-decode slice over the mmap
            s = sids[lo:hi]
            # dequant + scatter-add into accumulator: acc[s] += v*quants[s]+mins[s]
            np.add.at(acc, s, v.astype(np.float32) * quants[s] + mins[s])


def reader_materialize(mm: mmap.mmap, slab: dict, workload, acc):
    """FORMAT-WALL control: the `take()`/materialize style — per query term,
    COPY the touched bytes into a fresh array (the per-query decode/materialize
    that recreates the BMP 696 ms wall). Same arithmetic, same result, but the
    bytes are materialized per query rather than viewed zero-copy."""
    import numpy as np
    toff = slab["term_offsets"]
    mins = np.frombuffer(mm, dtype=F32, count=slab["n_summaries"],
                        offset=slab["off_mins"])
    quants = np.frombuffer(mm, dtype=F32, count=slab["n_summaries"],
                          offset=slab["off_quants"])
    acc.fill(0.0)
    for qlist in workload:
        for ti, qw in qlist:
            lo = toff[ti]; hi = toff[ti + 1]
            # MATERIALIZE: read bytes off the mmap into a fresh buffer per term.
            # values are u1 (byte-offset == element-offset); sids are u4 so the
            # byte offset into the sids region is off_sids + lo*4. np.copy()
            # forces the per-query materialize (decode+copy) the FORMAT-WALL
            # control must reproduce.
            raw_v = np.frombuffer(mm, dtype=VALUE_DTYPE, count=hi - lo,
                                  offset=slab["off_values"] + lo)
            raw_s = np.frombuffer(mm, dtype=SID_DTYPE, count=hi - lo,
                                 offset=slab["off_sids"] + lo * np.dtype(SID_DTYPE).itemsize)
            v = np.copy(raw_v)          # materialize: per-query decode+copy
            s = np.copy(raw_s)          # materialize: per-query decode+copy
            np.add.at(acc, s, v.astype(np.float32) * quants[s] + mins[s])


# --------------------------------------------------------------------------- //

def drop_pages(fd: int, off: int, length: int):
    """Best-effort COLD: evict the slab's pages so the next touch faults.
    Needs the file on a real FS (not tmpfs); POSIX_FADV_DONTNEED is a no-op
    on tmpfs, which we detect + flag."""
    import ctypes, ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    POSIX_FADV_DONTNEED = 4  # platform Linux
    rc = libc.posix_fadvise(ctypes.c_int(fd), ctypes.c_long(off),
                            ctypes.c_long(length), ctypes.c_int(POSIX_FADV_DONTNEED))
    return rc == 0


def is_tmpfs(path: Path) -> bool:
    try:
        import subprocess
        out = subprocess.run(["df", "--output=fstype", str(path)],
                             capture_output=True, text=True, check=False)
        return "tmpfs" in out.stdout
    except Exception:
        return False


def timed_run(reader, mm, slab, workload, acc):
    gc.collect()
    t0 = time.perf_counter()
    reader(mm, slab, workload, acc)
    return (time.perf_counter() - t0) * 1000.0   # ms


def build_workload(slab: dict, n_queries: int, terms_per_query: int, seed: int):
    """N queries, each touching `terms_per_query` random term indexes — the
    work budget. FIXED regardless of slab size so the FORMAT delta is isolated
    from the G4 pruning confound (corpus growth)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    n_terms = slab["n_terms"]
    workload = []
    for _ in range(n_queries):
        tis = rng.integers(0, n_terms, size=terms_per_query)
        wts = rng.uniform(0.5, 1.5, size=terms_per_query)
        workload.append([(int(ti), float(wt)) for ti, wt in zip(tis, wts)])
    return workload


def percentile(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = int(round((p / 100.0) * (len(s) - 1)))
    return s[k]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slab-dir", default="/tmp/seismic_testbed/c0",
                    help="where to build the slab (use a REAL FS, not tmpfs, for cold runs)")
    ap.add_argument("--slab-file", default=None,
                    help="reuse an existing slab instead of building")
    ap.add_argument("--n-terms", type=int, default=6_000,
                    help="query-term count mapping to summary blocks (≈ dense vocab slice)")
    ap.add_argument("--n-summaries", type=int, default=200_000,
                    help="summary blocks (= docs in the persona index projection)")
    ap.add_argument("--avg-values-per-term", type=int, default=60,
                    help="mean #u8 values per term (= postings per block in QuantizedSummary)")
    ap.add_argument("--n-queries", type=int, default=50)
    ap.add_argument("--terms-per-query", type=int, default=64,
                    help="SPLADE_QUERY_TERMS (mirror the serving retriever)")
    ap.add_argument("--latency-budget-mult", type=float, default=1.2,
                    help="the ~20%% Path-A-parity budget from 07 §6 (zero-decode cold p50 "
                         "must be within this multiple of warm materialize)")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    slab_path = Path(args.slab_file) if args.slab_file \
        else Path(args.slab_dir) / f"c0_slab_t{args.n_terms}_s{args.n_summaries}.bin"

    # --- build or reuse the slab ---
    if slab_path.exists():
        log.info("reusing slab %s", slab_path)
    else:
        log.info("building faithful-shape summary slab -> %s", slab_path)
        geo = build_slab(slab_path, args.n_terms, args.n_summaries,
                         args.avg_values_per_term)
        log.info("slab: n_terms=%d n_summaries=%d n_values=%d values=%.2f MB total=%.2f MB",
                 geo["n_terms"], geo["n_summaries"], geo["n_values"],
                 geo["values_bytes"] / 1e6, geo["bytes"] / 1e6)

    on_tmpfs = is_tmpfs(slab_path)
    log.info("slab fs is tmpfs=%s (cold runs %s)", on_tmpfs,
             "WILL NOT evict (use --slab-dir on a real FS)" if on_tmpfs else "ok")

    # --- open + mmap the slab (read-only) ---
    fd = os.open(str(slab_path), os.O_RDONLY)
    slab = parse_slab(fd)
    fsize = os.fstat(fd).st_size
    mm = mmap.mmap(fd, fsize, access=mmap.ACCESS_READ)
    log.info("mapped slab: values_offset=%d n_values=%d (values slab %.2f MB)",
             slab["off_values"], slab["n_values"],
             slab["n_values"] / 1e6)

    workload = build_workload(slab, args.n_queries, args.terms_per_query, seed=98765)
    acc = __import__("numpy").zeros(slab["n_summaries"], dtype=SUMMARY_ACC_DTYPE)

    # Sanity: both readers must produce the SAME accumulator (correctness floor;
    # the FORMAT delta isolates layout, not arithmetic — mirrors R3-v2 G1 parity).
    reader_zero_decode(mm, slab, workload[:1], acc)
    acc_zd = acc.copy()
    reader_materialize(mm, slab, workload[:1], acc)
    assert __import__("numpy").array_equal(acc, acc_zd), \
        "C0 parity FAILED: zero-decode and materialize disagree — readers are not arithmetic twins"
    log.info("parity OK: zero-decode == materialize (arithmetic twins, like R3-v2 G1)")

    # --- WARM runs (page cache hot; touch all pages first) ---
    # Warm by running each reader once over the full slab before timing.
    scale = max(1, fsize // (4 * 1024 * 1024))   # touch every 4 MiB
    mm.madvise(mmap.MADV_SEQUENTIAL) if hasattr(mmap, "MADV_SEQUENTIAL") else None
    reader_zero_decode(mm, slab, workload, acc)
    reader_materialize(mm, slab, workload, acc)

    warm_zd = [timed_run(reader_zero_decode, mm, slab, workload, acc)
               for _ in range(args.n_queries)]
    warm_mat = [timed_run(reader_materialize, mm, slab, workload, acc)
                for _ in range(args.n_queries)]

    # --- COLD runs (evict pages before each timed query) ---
    cold_zd, cold_mat = [], []
    for _ in range(args.n_queries):
        if not on_tmpfs:
            drop_pages(fd, slab["off_values"], slab["n_values"])
            drop_pages(fd, slab["off_sids"], slab["n_values"] * 4)
        cold_zd.append(timed_run(reader_zero_decode, mm, slab, workload, acc))
        if not on_tmpfs:
            drop_pages(fd, slab["off_values"], slab["n_values"])
            drop_pages(fd, slab["off_sids"], slab["n_values"] * 4)
        cold_mat.append(timed_run(reader_materialize, mm, slab, workload, acc))

    rss_anon = rssanon_kb()
    rss_file = rssfile_kb()
    log.info("after bench: RssAnon=%.3f GB RssFile=%.3f GB (RssAnon should be ~0; "
             "RssFile carries the slab, reclaimable)", gb(rss_anon), gb(rss_file))

    # --- verdict (07 §6: zero-decode cold p50 within 1.2× of warm materialize) ---
    z_p50 = percentile(cold_zd, 50); z_p95 = percentile(cold_zd, 95)
    m_warm_p50 = percentile(warm_mat, 50); m_cold_p50 = percentile(cold_mat, 50)
    format_wall_gap = ((m_cold_p50 or 0) / (z_p50 or 1)) if (z_p50 or 0) > 0 else None
    feasible = (z_p50 is not None and m_warm_p50 is not None
                and z_p50 <= args.latency_budget_mult * m_warm_p50)
    cures_anon = (rss_anon or 0) < (fsize / 1024 / 1024) * 0.1   # anon ≪ slab (page-cache carries)

    if feasible and (format_wall_gap or 0) > 1.0:
        verdict = ("C0 PATH_C_FEASIBLE — warm zero-decode holds the ~20%% budget vs warm "
                  "materialize, and cold zero-decode beats cold materialize "
                  "(FORMAT-WALL gap %.2fx). Proceed to C1: build the mmap writer/reader "
                  "for all 4 SEISMIC components." % (format_wall_gap or 1))
    elif feasible and (format_wall_gap or 0) <= 1.0:
        verdict = ("C0 FORMAT_WALL — zero-decode held the budget but did NOT beat "
                  "materialize cold (gap %.2fx): no format decoupling on this slab "
                  "shape. Re-scope before the fork (POD may need restructuring, not "
                  "just mmap'ing; remember upstream offsets/summaries_ids are compressed "
                  "and add per-query decode — model those next)." % (format_wall_gap or 1))
    else:
        verdict = ("C0 FORMAT_WALL — cold zero-decode p50 %.2f ms exceeds %.1fx of warm "
                  "materialize %.2f ms. Zero-decode over this summary layout cannot hold "
                  "the serving latency target; Path C must be re-scoped (do NOT pay the "
                  "fork on this evidence)." % (z_p50 or 0, args.latency_budget_mult, m_warm_p50 or 0))

    result = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.4.0", "built_utc": "2026-06-26",
                 "purpose": "G3 Path C / Step C0 FORMAT-WALL micro-bench on the summary "
                            "structure (44%% of the resident floor, hardest zero-decode surface)",
                 "doc_refs": ["07_G3_RAM_FIX_PLAN.md §3 Step C0",
                              "01_ARCHITECTURE.md:82-133 (FORMAT-WALL precedent, R3v2)",
                              "03_BENCHMARK_METHODOLOGY.md:42 (warm/cold)",
                              "quantized_summary.rs:14-160 (upstream struct + distances())"],
                 "slab_provenance": ("FAITHFUL-SHAPE (not real SEISMIC bytes; pyseismic exposes "
                                     "no per-block summary dump). Reproduces QuantizedSummary hot "
                                     "fields at faithful widths + access pattern; NOT a G2/recall bench."),
                 "on_tmpfs": on_tmpfs, "cold_valid": not on_tmpfs},
        "config": {"n_terms": args.n_terms, "n_summaries": args.n_summaries,
                   "avg_values_per_term": args.avg_values_per_term,
                   "n_queries": args.n_queries, "terms_per_query": args.terms_per_query,
                   "latency_budget_mult": args.latency_budget_mult,
                   "slab_path": str(slab_path), "slab_bytes": fsize,
                   "values_slab_mb": round(slab["n_values"] / 1e6, 3)},
        "latency_ms": {
            "warm_zero_decode": {"p50": percentile(warm_zd, 50), "p95": percentile(warm_zd, 95),
                                  "min": min(warm_zd), "max": max(warm_zd)},
            "warm_materialize": {"p50": percentile(warm_mat, 50), "p95": percentile(warm_mat, 95),
                                  "min": min(warm_mat), "max": max(warm_mat)},
            "cold_zero_decode": {"p50": z_p50, "p95": z_p95,
                                  "min": min(cold_zd), "max": max(cold_zd)},
            "cold_materialize": {"p50": m_cold_p50, "p95": percentile(cold_mat, 95),
                                  "min": min(cold_mat), "max": max(cold_mat)},
        },
        "format_wall_gap_x": round(format_wall_gap, 3) if format_wall_gap else None,
        "rss_after_gb": {"rssanon": gb(rss_anon), "rssfile": gb(rss_file)},
        "cures_anon_estimate": cures_anon,
        "c0_verdict": verdict,
    }
    rpath = (Path(args.result_file) if args.result_file
             else Path(f"data/eval_results/seismic_c0_formatwall_{int(time.time())}.json"))
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)

    mm.close(); os.close(fd)
    print(json.dumps({"c0_verdict": verdict,
                      "cold_zero_decode_p50_ms": z_p50,
                      "cold_materialize_p50_ms": m_cold_p50,
                      "warm_materialize_p50_ms": percentile(warm_mat, 50),
                      "format_wall_gap_x": result["format_wall_gap_x"],
                      "on_tmpfs": on_tmpfs, "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
