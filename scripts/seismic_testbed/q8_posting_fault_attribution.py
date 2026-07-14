#!/usr/bin/env python3
"""Q8 Stage 0a — posting-side cold-fault attribution (2026-07-10).

E5 reordered the FORWARD files (forward_data.bin) for locality. The POSTING-side
files (posting_lists.bin + summaries + doc-mapping floors) still fault cold.
The E5 gates measured-out the floor symmetrically via `SFU_SEISMIC_PREFLOOR=2`
(prefaulted it before the majflt baseline) — so its cost was removed from the
delta, NOT eliminated. Q8 asks: of the RESIDUAL cold faults, what SHARE is the
posting side? If it's small, reordering postings (an E5-for-postings analog) is
not worth a converter; if it's >= ~25%, Stage 0b (a co-access sim of posting
blocks) is worth running.

PRE-REGISTERED BARS (written BEFORE measurement, doc 12 §3 Q8):
  - Stage 0a: posting-side share >= ~25% of residual cold faults -> Stage 0b
  - Stage 0a: below ~25% -> KILL on paper (the share IS the finding)
  This script implements ONLY Stage 0a. Stage 0b is a separate script, only
  run on a 0a GO.

METHOD (zero Rust, per-file mincore):
  For each shard dir file, open a SHARED read-only mmap of it (a second mapping
  of the same file the index holds). `mincore(2)` on that mapping reflects the
  shared page-cache residency of the underlying file pages — which IS what the
  index's own mapping faults in. So:
    1. release_pages() + fadvise(DONTNEED) every file -> known-cold (0 resident).
    2. mincore snapshot -> confirm ~0 resident per file (the cold baseline).
    3. run ONE cold search pass (N queries) on the index.
    4. mincore snapshot -> per-file newly-resident pages = per-file fault count.
  The sum of per-file newly-resident pages ~= the process majflt_cold (a
  sanity cross-check against /proc/self/stat[11]); the SHARE per file is the
  attribution. Per-file means we can split:
    - posting side  = posting_lists.bin + manifest (the block inventory lives
                     in posting_lists.bin; summaries are in-list) [+ the
                     forward_encoder if relevant]
    - forward side  = forward_data.bin + forward_offsets.bin
    - doc-mapping   = document_mapping_offsets.bin + document_mapping_strings.bin
    - other         = config.json (tiny)
  The 'residual' cold faults (what Q8 attributes) = total minus the structural
  floor that PREFLOOR would have stripped. We do NOT run with PREFLOOR here
  (doc 12 Q8 Stage 0a: "one cold run per arm WITHOUT PREFLOOR prefaulting") —
  we measure the FULL per-file attribution and report the posting share of the
  TOTAL cold faults, which is the conservative figure (the floor's constant
  ~5,000 pages dilutes the posting share, so a >= 25% share on the full count
  is a FORTIORI >= 25% on the residual). The verdict records both shares.

PROTOCOL (container, 2026-07-09):
  fadvise-DONTNEED eviction (no drop_caches); paired ratios only; a cold cell
  counts only if VmSwap ~ 0 AND warm p50 < cold p50. Rule Zero: READ-ONLY —
  the external mmaps are O_RDONLY shared, never written.

Usage (repo root, project venv), one shard at a time:

    .venv/bin/python3 scripts/seismic_testbed/q8_posting_fault_attribution.py \
        --shard data/seismic_150m/index/plan01/global_shard1of8.dotvbyte.e5.mmap \
        --queries 40 --result-file data/eval_results/q8_posting_fault_attr_shard1_20260710.json
"""
import argparse
import ctypes
import ctypes.util
import json
import logging
import os
import statistics
import struct
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

log = logging.getLogger("q8_attr")

# libc for mincore(2) + madvise-style fadvise (posix_fadvise is in os already).
_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                           ctypes.POINTER(ctypes.c_ubyte)]
_libc.mincore.restype = ctypes.c_int
PAGESIZE = os.sysconf("SC_PAGE_SIZE")

SPLADE_QUERY_TERMS = 64


def read_majflt() -> int:
    """Process-total major faults (/proc/self/stat field 12, 0-indexed 11)."""
    return int(Path("/proc/self/stat").read_text().split()[11])


def resident_pages(mmap_addr: int, length: int) -> int:
    """Count resident pages in a mapped region via mincore(2). Returns the
    number of pages currently in the page cache."""
    n_pages = (length + PAGESIZE - 1) // PAGESIZE
    vec = (ctypes.c_ubyte * n_pages)()
    # mincore requires the addr to be page-aligned and length rounded; the
    # mmap is created page-aligned below.
    rc = _libc.mincore(ctypes.c_void_p(mmap_addr), ctypes.c_size_t(length), vec)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"mincore failed (addr={mmap_addr}, len={length})")
    # Each byte's low bit = residency of that page (mincore's bitmask, one bit
    # per page packed into the returned bytes).
    return int(sum(b & 0x01 for b in vec))


class FileResidencyTracker:
    """Open a shared read-only mmap of a file and track its resident-page count.
    A second mapping of a file shares the underlying page-cache pages with the
    index's own mapping, so mincore on THIS mapping reflects what the index
    faults in — the per-file attribution signal we need. Rule Zero: O_RDONLY,
    MAP_SHARED, never written."""

    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size
        self._fd = os.open(str(path), os.O_RDONLY)
        # mmap requires nonzero length AND length <= file size (can't map past
        # EOF). Tiny files (config.json 312 B) map their own size; mincore
        # rounds up to a page internally anyway.
        length = self.size if self.size > 0 else PAGESIZE
        self._mmap = mmap_readonly(self._fd, length)
        # Get the read-only mmap's base address for mincore(2). The robust
        # idiom for a RO mapping: numpy frombuffer + __array_interface__["data"]
        # exposes the underlying pointer without needing a writable buffer
        # (ctypes from_buffer requires writable; from_buffer_copy copies).
        import numpy as _np
        self.addr = _np.frombuffer(self._mmap, dtype=_np.uint8).__array_interface__["data"][0]

    def resident(self) -> int:
        if self.size == 0:
            return 0
        # mincore rounds the length up to a page; for tiny files (< 1 page)
        # the single returned byte covers the file's one page. The addr must
        # be page-aligned — mmap.mmap returns a page-aligned base, and
        # ctypes.addressof(from_buffer) yields that base.
        return resident_pages(self.addr, self.size)

    def close(self):
        try:
            self._mmap.close()
        except Exception:
            pass
        try:
            os.close(self._fd)
        except Exception:
            pass


def mmap_readonly(fd: int, length: int):
    import mmap
    return mmap.mmap(fd, length, prot=mmap.PROT_READ, flags=mmap.MAP_SHARED)


# Per-file classification (what Q8 attributes to each side).
def classify(fname: str) -> str:
    if fname == "posting_lists.bin" or fname == "forward_encoder.bin":
        return "posting"
    if fname == "forward_data.bin" or fname == "forward_offsets.bin":
        return "forward"
    if fname.startswith("document_mapping"):
        return "doc_mapping"
    if fname in ("config.json", "manifest.json"):
        return "meta"
    return "other"


def fadvise_dontneed_file(path: Path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard", required=True,
                    help="a shard .mmap/ dir (the e5 or dv converted dir)")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--k-prime", type=int, default=100)
    ap.add_argument("--result-file", required=True)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    shard = Path(args.shard)
    if not shard.is_absolute():
        shard = (REPO / args.shard).resolve()
    if not shard.is_dir():
        log.error("shard dir not found: %s", shard)
        return 2

    # Rule Zero inventory.
    files = sorted(f.name for f in shard.iterdir() if f.is_file())
    log.info("Rule Zero: shard %s (%d files): %s", shard.name, len(files), files)

    import seismic
    idx = seismic.MmapSeismicIndex(str(shard))
    sd = seismic.get_seismic_string()
    log.info("loaded %s: len=%d dim=%d nnz=%d", shard.name, idx.len, idx.dim, idx.nnz)

    # Load + encode queries once (encode is CPU-bound, not the fault signal).
    from lib.opensearch_retriever import encode_splade
    qrecs = json.loads((REPO / "data" / "eval_results" / "diverse_queries.json").read_text())
    queries = [r["paraphrase"] for r in qrecs][:args.queries]
    per_q_terms = []
    for qtext in queries:
        q64 = dict(sorted(encode_splade(qtext, "models/splade_onnx_fused").items(),
                          key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        per_q_terms.append(q64)

    # Open a residency tracker per file (the per-file attribution probes).
    trackers = {f: FileResidencyTracker(shard / f) for f in files
                if (shard / f).stat().st_size > 0}

    def cold_all():
        """Release + fadvise-DONTNEED every file -> known-cold baseline."""
        rel = idx.release_pages()
        for f in files:
            fadvise_dontneed_file(shard / f)

    # ── the cold attribution pass ────────────────────────────────────────────
    cold_all()
    # Baseline residency (should be ~0 per file after fadvise + release).
    base_resident = {f: t.resident() for f, t in trackers.items()}
    base_total = sum(base_resident.values())
    mj0 = read_majflt()
    log.info("cold baseline: total resident pages=%d (%.2f GB), majflt=%d",
             base_total, base_total * PAGESIZE / 1e9, mj0)
    # Sanity: if files are still resident (Windows cache not evictable), note it.
    if base_total > 1000:
        log.warning("baseline resident=%d is high — 9p/Windows cache not fully evicted; "
                    "the DELTA still attributes faults (paired-ratio protocol)", base_total)

    # The cold search pass (the faults we attribute).
    cold_ms = []
    for terms in per_q_terms:
        qcomp = np.array(list(terms.keys()), dtype=sd)
        qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
        t0 = time.perf_counter()
        idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                   k=args.k_prime, query_cut=len(terms), heap_factor=0.8)
        cold_ms.append((time.perf_counter() - t0) * 1000)
    mj_cold = read_majflt() - mj0

    # Post-pass residency = per-file newly-faulted pages.
    post_resident = {f: t.resident() for f, t in trackers.items()}
    delta = {f: max(0, post_resident[f] - base_resident[f]) for f in trackers}
    delta_total = sum(delta.values())

    # ── warm pass (for the VmSwap~0 + warm<cold validity gate) ───────────────
    warm_ms = []
    for terms in per_q_terms:
        qcomp = np.array(list(terms.keys()), dtype=sd)
        qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
        reps = []
        for _ in range(3):
            t0 = time.perf_counter()
            idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                       k=args.k_prime, query_cut=len(terms), heap_factor=0.8)
            reps.append((time.perf_counter() - t0) * 1000)
        warm_ms.append(statistics.median(reps))

    vmswap_kb = 0
    for line in open("/proc/self/status"):
        if line.startswith("VmSwap:"):
            vmswap_kb = int(line.split()[1])
            break

    # ── attribution + verdict ────────────────────────────────────────────────
    by_class = {"posting": 0, "forward": 0, "doc_mapping": 0, "meta": 0, "other": 0}
    per_file = {}
    for f in files:
        c = classify(f)
        by_class[c] += delta.get(f, 0)
        per_file[f] = {"class": c, "size_bytes": (shard / f).stat().st_size,
                       "resident_before": base_resident.get(f, 0),
                       "resident_after": post_resident.get(f, 0),
                       "faulted_pages_delta": delta.get(f, 0)}

    total = delta_total if delta_total > 0 else 1  # avoid /0
    share = {c: round(by_class[c] / total, 4) for c in by_class}
    posting_share = share["posting"] + share["doc_mapping"]  # the non-forward floor
    # Conservative: posting-side share of TOTAL cold faults (full count, residual
    # would be higher since the forward side IS the residual's main term).
    # doc_12 Q8 bar: posting-side share >= ~25% of RESIDUAL. Residual = total
    # minus the constant floor (posting+doc_mapping if those were prefaulted).
    # Since we measure attribution WITHOUT prefault, the posting share of total
    # is the lighter figure; report both.
    forward_share = share["forward"]
    # The 'residual' (what's left after stripping the structural floor) is
    # dominated by forward_data; posting-side share of residual ≈ posting/forward
    # is NOT what the bar means — the bar means posting / (posting+forward) of the
    # RESIDUAL cold faults (the ones a posting reordering could remove).
    residual = by_class["posting"] + by_class["forward"]
    posting_share_residual = (by_class["posting"] / residual) if residual else 0.0

    cell_valid = (vmswap_kb < 1024  # ~0 GB
                  and statistics.median(warm_ms) < statistics.median(cold_ms))

    bars = {"posting_share_residual_ge_0.25": 0.25, "cell_valid": "VmSwap~0 AND warm<cold"}
    verdict = {
        "posting_share_of_total": posting_share,
        "forward_share_of_total": forward_share,
        "posting_share_of_residual": round(posting_share_residual, 4),
        "bar_0.25residual": ("GO_to_stage0b" if posting_share_residual >= 0.25
                              else "KILL_on_paper"),
        "cell_valid_novswap_warm_lt_cold": cell_valid,
        "bars": bars,
    }

    out = {
        "meta": {
            "date_utc": __import__("datetime").datetime.utcnow().isoformat(),
            "benchmark": "q8 stage0a posting-side cold-fault attribution",
            "shard": str(shard.relative_to(REPO)) if str(shard).startswith(str(REPO)) else str(shard),
            "queries": args.queries,
            "k_prime": args.k_prime,
        },
        "majflt_cold_pass_process_total": mj_cold,
        "mincore_delta_total_pages": delta_total,
        "crosscheck_ratio_mincore_over_majflt": round(delta_total / mj_cold, 3) if mj_cold else None,
        "by_class": by_class,
        "share_of_total": share,
        "per_file": per_file,
        "latency": {
            "cold_p50_ms": round(statistics.median(cold_ms), 2),
            "warm_p50_ms": round(statistics.median(warm_ms), 2),
            "vmswap_kb": vmswap_kb,
        },
        "verdict": verdict,
    }
    result_file = REPO / args.result_file
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(out, f, indent=2)
    log.info("result written to %s", result_file)
    log.info("VERDICT: %s", json.dumps(verdict, indent=2))

    for t in trackers.values():
        t.close()
    return 0


# numpy is used in main; import at module level for the dtype.
import numpy as np  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
