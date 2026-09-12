#!/usr/bin/env python3
"""TIER-1c convergence-repro cell — native (docker-free) residency-seeded synthetic.

Why this exists (RESULTS.md sections 14, 16): Tier-1b proved that LOAD ORDER
selects the pass-1 initial state (L->R => R 100% resident / no transient;
interleaved => R ~92% / decaying; R->L => R ~90% / rising), yet the real
system's non-monotonic INVERSION still did not appear under any metric, because
on a classic-LRU host with uniform-random repeat the fixed-window outcome is
DEFICIT-DOMINATED (trajectories self-similar, scaled by initial deficit;
pressure-scaled aging only ~10%/pass, second order). The recommended next
experiment (section 16) is NOT another load-order guess: it is to set the
synthetic's initial state DIRECTLY from a measured target residency profile,
and to run it where the WSL2 synthetic never has -- on a real Linux host with
MGLRU available (publication-gate items 2-3).

This cell does exactly that:
  * It lays down R (repeat set) + L (residue) as non-sparse files.
  * It seeds R's initial residency to a TARGET FRACTION directly, decoupled
    from load order: fault all of R in, then MADV_DONTNEED a seeded-random
    subset so exactly (1 - frac) of R's pages are evicted. The target fraction
    comes from --resident-frac (parameterised from the real-stack measurement).
  * It then runs N repeat passes (seeded-random one-touch-per-page over R,
    MADV_RANDOM so exactly one major fault per missing 4 KiB page -- the same
    property jobs/repeat.fio documents) and records per-pass MAJFLT.

Metric: MAJFLT, read from /proc/self/stat field 12. RESULTS.md section 11
established majflt as the clean graded metric (single-percentile latency is a
threshold detector on fault fraction) and it is KERNEL-measured, so Python
interpreter overhead does not touch it. Per-pass wall time is recorded as a
secondary and is explicitly NOT the fio clat (it includes interpreter cost).

Separation of concerns (matches jobs/*.fio + the docker/systemd launcher):
this Python sets NEITHER the memory cap NOR the LRU arm. The launcher wraps the
process in a systemd scope (`-p MemoryMax=...`) and sets
/sys/kernel/mm/lru_gen/enabled, exactly as sml_host_orchestrator.sh does for the
real stack. This file only builds the initial state and counts faults.

Soundness identity (self-check, always recorded): with an uncapped run, pass-1
majflt MUST equal the evicted-page count (the seeded deficit), because
MADV_RANDOM gives one major fault per missing page and nothing evicts resident
pages when the cap is absent. `seed_deficit_pages` vs `pass[0].majflt` in the
JSON is that check; --self-check makes the mismatch a non-zero exit.
"""
import argparse
import ctypes
import ctypes.util
import json
import mmap
import os
import sys
import time

import numpy as np

PAGE = 4096
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
libc.mincore.restype = ctypes.c_int


def read_majflt():
    """Major faults of THIS process from /proc/self/stat field 12 (0-based 11).

    The stat line's comm field can contain spaces/parens, so split after the
    trailing ')' of comm, then index from there (the canonical parse)."""
    with open("/proc/self/stat", "rb") as fh:
        data = fh.read()
    rparen = data.rindex(b")")
    fields = data[rparen + 2:].split()
    # after comm, fields[0]=state ... majflt is field 12 (1-based) => index 9 here
    return int(fields[9])


def resident_pages(addr, nbytes):
    """Count resident pages of a mapping via mincore(2). Replaces vmtouch."""
    npages = (nbytes + PAGE - 1) // PAGE
    vec = ctypes.create_string_buffer(npages)
    rc = libc.mincore(ctypes.c_void_p(addr), ctypes.c_size_t(nbytes), vec)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, "mincore failed: " + os.strerror(err))
    raw = np.frombuffer(vec.raw, dtype=np.uint8, count=npages)
    return int(np.count_nonzero(raw & 1)), npages


def lay_down(path, size_bytes, seed):
    """Create a non-sparse file of incompressible bytes (fallocate would leave
    it sparse => faults from the zero page => vacuous, per laydown.fio)."""
    rng = np.random.default_rng(seed)
    chunk = 64 * 1024 * 1024
    written = 0
    with open(path, "wb", buffering=0) as fh:
        while written < size_bytes:
            n = min(chunk, size_bytes - written)
            buf = rng.integers(0, 256, size=n, dtype=np.uint8).tobytes()
            fh.write(buf)
            written += n
        fh.flush()
        os.fsync(fh.fileno())


def map_ro(path):
    fd = os.open(path, os.O_RDONLY)
    size = os.fstat(fd).st_size
    mm = mmap.mmap(fd, size, prot=mmap.PROT_READ)
    mm.madvise(mmap.MADV_RANDOM)
    arr = np.frombuffer(mm, dtype=np.uint8)
    addr = arr.ctypes.data
    return fd, mm, arr, addr, size


def touch_pages(arr, page_indices):
    """Fault the given pages by reading one byte from each (page head).
    Random-order gather at C speed; order does not change the fault COUNT but
    does drive random-access LRU behaviour under a cap, matching randread."""
    heads = arr[:: PAGE]  # view of one byte per page
    # int64 reduction forces every gathered byte to be read (=> the page faults)
    return int(heads[page_indices].astype(np.int64).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--r-size-mib", type=int, default=5120)
    ap.add_argument("--l-size-mib", type=int, default=1792)
    ap.add_argument("--resident-frac", type=float, required=True,
                    help="target fraction of R resident at pass-1 start (0..1)")
    ap.add_argument("--passes", type=int, default=12)
    ap.add_argument("--near-zero", type=int, default=2500,
                    help="majflt at/below which a pass counts as converged")
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--arm", default="unset",
                    help="informational; the launcher sets lru_gen, not this")
    ap.add_argument("--cap-label", default="uncapped",
                    help="informational; the launcher sets MemoryMax, not this")
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--skip-laydown", action="store_true",
                    help="reuse existing R/L files in --data-dir")
    ap.add_argument("--laydown-only", action="store_true",
                    help="create R/L files and exit (orchestrator lays down once)")
    ap.add_argument("--self-check", action="store_true",
                    help="exit nonzero if pass-1 majflt != seed deficit")
    args = ap.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    r_path = os.path.join(args.data_dir, "R.bin")
    l_path = os.path.join(args.data_dir, "L.bin")
    r_bytes = args.r_size_mib * 1024 * 1024
    l_bytes = args.l_size_mib * 1024 * 1024

    def log(msg):
        print("[t1c] %s" % msg, flush=True)

    log("cell arm=%s cap=%s resident_frac=%.4f passes=%d seed=%d R=%dMiB L=%dMiB"
        % (args.arm, args.cap_label, args.resident_frac, args.passes,
           args.seed, args.r_size_mib, args.l_size_mib))

    if args.laydown_only or not args.skip_laydown:
        t0 = time.monotonic()
        lay_down(r_path, r_bytes, args.seed)
        lay_down(l_path, l_bytes, args.seed + 1)
        log("laydown done in %.1fs (R=%dMiB L=%dMiB, non-sparse)"
            % (time.monotonic() - t0, args.r_size_mib, args.l_size_mib))
    if args.laydown_only:
        log("laydown-only: R/L created, exiting")
        return

    # Start from a known-cold cache for both files so the seed is exact.
    for p in (r_path, l_path):
        fd = os.open(p, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)

    r_fd, r_mm, r_arr, r_addr, r_size = map_ro(r_path)
    npages = r_size // PAGE

    # ---- Initial-state seed: warm ONLY the target-resident subset, leaving the
    # rest never-loaded. MADV_RANDOM disables readahead, so faulting the chosen
    # pages brings in exactly those pages and the untouched (1 - frac) remain
    # non-resident => a MAJOR fault on their first touch in pass 1. (Evicting an
    # already-warm subset does NOT work here: MADV_DONTNEED only drops PTEs while
    # the clean file pages stay in the page cache, so mincore still counts them
    # resident and re-access is a minor fault -- no deficit. Warming a subset of
    # a cold file is the direct, cache-honest way to set residency.) This IS the
    # Tier-1c move: initial state set from a target fraction, not a load order.
    n_resident = int(round(args.resident_frac * npages))
    rng = np.random.default_rng(args.seed ^ 0x5EED)
    resident_idx = rng.choice(npages, size=n_resident, replace=False).astype(np.int64)
    if n_resident:
        touch_pages(r_arr, resident_idx)
    res_after_seed, _ = resident_pages(r_addr, r_size)
    seed_deficit = npages - res_after_seed
    log("seeded: warmed %d target-resident, R resident %d/%d pages (%.4f%%), deficit=%d"
        % (n_resident, res_after_seed, npages,
           100.0 * res_after_seed / npages, seed_deficit))

    # ---- Repeat passes: same seeded-random one-touch-per-page sequence every
    # pass (fixed perm => the fio norandommap+randseed determinism analogue).
    perm_rng = np.random.default_rng(args.seed)
    perm = perm_rng.permutation(npages).astype(np.int64)

    passes = []
    converged_pass = None
    for p in range(1, args.passes + 1):
        mf0 = read_majflt()
        w0 = time.monotonic()
        touch_pages(r_arr, perm)
        w1 = time.monotonic()
        mf1 = read_majflt()
        res_now, _ = resident_pages(r_addr, r_size)
        majflt = mf1 - mf0
        rec = {"pass": p, "majflt": majflt,
               "wall_s": round(w1 - w0, 3),
               "resident_pages": res_now,
               "resident_pct": round(100.0 * res_now / npages, 4)}
        passes.append(rec)
        log("pass %d: majflt %d  wall %.3fs  R_resident %.2f%%"
            % (p, majflt, rec["wall_s"], rec["resident_pct"]))
        if majflt <= args.near_zero and converged_pass is None:
            converged_pass = p
            # keep going to record the steady tail, but note first-zero pass

    self_check_ok = (passes[0]["majflt"] == seed_deficit)
    out = {
        "protocol": "tier1c",
        "arm": args.arm,
        "cap_label": args.cap_label,
        "resident_frac_target": args.resident_frac,
        "resident_frac_actual": round(res_after_seed / npages, 6),
        "seed": args.seed,
        "r_size_mib": args.r_size_mib,
        "l_size_mib": args.l_size_mib,
        "r_pages": npages,
        "seed_deficit_pages": seed_deficit,
        "near_zero": args.near_zero,
        "converged_first_pass": converged_pass,
        "converged": converged_pass is not None,
        "soundness_pass1_majflt_eq_deficit": self_check_ok,
        "passes": passes,
    }
    with open(args.result_file, "w") as fh:
        json.dump(out, fh, indent=2)
    log("wrote %s  converged=%s (first pass %s)  soundness=%s"
        % (args.result_file, out["converged"], converged_pass, self_check_ok))

    heads = None
    del r_arr, perm, resident_idx
    r_mm.close()
    os.close(r_fd)
    if args.self_check and not self_check_ok:
        log("SELF-CHECK FAILED: pass1 majflt %d != seed deficit %d"
            % (passes[0]["majflt"], seed_deficit))
        sys.exit(3)


if __name__ == "__main__":
    main()
