#!/usr/bin/env python3
"""TIER-1d convergence-repro cell — t1c_cell.py + ACCESS SKEW in the repeat pass.

Why this exists (PREREGISTRATION_TIER1D.md sections 1-2): Tier-1c seeded R's
residency directly on a real MGLRU kernel and still produced NO arm asymmetry —
classic and MGLRU thrashed to near-identical majflt floors at every sub-|R| cap.
The cause was localised to ACCESS STRUCTURE: a uniform one-touch-per-page repeat
has no hot subset for classic's refault-activation to protect, so once R exceeds
the cap the shortfall must miss on every pass no matter which LRU arm runs.

Tier-1d changes exactly one thing: the repeat pass draws its touches from a
SKEWED distribution over R.

  * --skew hotset:h:m (primary) — partition R's pages into a hot fraction h and
    a cold tail 1-h (over a seeded ranking) and draw so the hot set receives
    mass m of the touches (hotset:0.20:0.80 = 20% of pages take 80% of touches).
  * --skew hotsetc:h:m[:E] (clustered variant, T1d-12 / amplification chain) —
    same h/m and the same draw, but the hot set is laid out as E contiguous
    file extents (default 8) at seeded non-overlapping offsets instead of a
    random scatter. This is the spatial-clustering ingredient the real index
    has and hotset lacks: hot postings live in runs, which is exactly what
    kernel readahead amplifies — so hotsetc under --fault-around (spec tail
    fa:hotsetc:h:m) is the cell that tests whether clustering + readahead
    compounds the hot-set advantage. Under MADV_RANDOM, hotsetc vs hotset
    isolates any pure layout effect in reclaim. JSON records the extent table.
  * --skew zipf:s (alternative) — touches ~ Zipf(s) over the same seeded
    ranking, weight(rank) proportional to rank**-s, sampled by inverse CDF.
  * no --skew — byte-identical behaviour to Tier-1c (fixed seeded permutation,
    one touch per page).

Everything else is inherited from t1c_cell.py unchanged: non-sparse R/L laydown,
residency seeded DIRECTLY to --resident-frac by warming a seeded-random subset of
a cold file, MADV_RANDOM (one major fault per missing 4 KiB page, no readahead),
per-pass MAJFLT from /proc/self/stat field 12 (RESULTS.md section 11: majflt is
the graded, kernel-measured metric), and the launcher — not this file — setting
the memory cap and the LRU arm.

PER-PASS TOUCH COUNT IS FIXED at |R| pages' worth of touches (section 2 of the
pre-reg) so a Tier-1d pass costs what a Tier-1c pass costs; skew redistributes
those touches, it does not add any. The draw is WITH REPLACEMENT, so a skewed
pass does not cover every page.

DETERMINISM: the ranking derives from the cell seed (seed ^ 0x5EAB1D); each
pass's draw derives from (seed, pass) so the whole cell replays exactly from the
seed, while successive passes are not the same touch multiset. Independent
per-pass draws are deliberate: a single fixed skewed draw reused every pass would
shrink the effective working set to that draw's support (~37% of R for
hotset:0.20:0.80) and silently move the cap regimes the pre-reg's situations are
defined over (hot-set < cap < |R|).

SOUNDNESS IDENTITY under skew. Tier-1c's identity (uncapped pass-1 majflt ==
seeded deficit) assumes pass 1 touches every page, which a fixed-count skewed
draw CANNOT do: covering all N pages needs N touches, so any hot mass m > 0
concentration leaves the cold tail with fewer than 1 expected touch per page
(hotset:0.20:0.80 gives the cold tail 0.25 touches/page). The identity is
therefore evaluated over the pages pass 1 actually reaches:

    pass-1 majflt == |{missing pages} intersect {distinct pages drawn in pass 1}|

recorded as `pass1_reachable_deficit_pages`, with the strict Tier-1c form kept
alongside as `soundness_pass1_majflt_eq_full_deficit` (informational under skew).
With no --skew the draw is a permutation, reachable == full deficit, and the
check is exactly Tier-1c's. `--self-check` exits nonzero on a mismatch of the
reachable identity.

FAULT-AROUND ARM (pre-reg section 3.4, gap 2): `--fault-around` maps R with
MADV_NORMAL instead of MADV_RANDOM, i.e. kernel readahead / fault-around ON --
what the real stack gets, since it issues no fadvise. One touch then pulls in a
cluster of neighbouring pages, so neither the residency seed nor pass-1 majflt
is one-fault-per-page any more; such a cell is judged on its floor trajectory,
and the JSON says so (`madvise`, `fault_around`,
`soundness_identity_applicable: false`). `--self-check` does not fail a
fault-around cell for that reason.

RESIDUE POPULATION (--warm-l, T1d-15): all of L is sequentially touched
before R is seeded and its mapping stays alive for the whole cell, so under
a cap there is a load-time residue the kernel must sort out while R is
re-touched — the real stack's inversion mechanism (RESULTS.md section 22).
The T1d-13 cap-bracket cells measured why this flag must exist: with L cold,
every cap > |R| produced bit-identical trajectories (no residue, no
transient, no possible inversion). Per-pass `l_resident_pct` records the
sort as it happens. Off by default; no other path changes.

HOT-SET RESIDENCY (T1d-7 readout 4; added 2026-09-05 after the SEC-4
calibration window, whose cells carried only whole-R resident_pct): every pass
of a skew cell also records `hot_resident_pages` / `hot_resident_pct` — the
mincore(2) residency of the hot set (hotset: the h-fraction ranking prefix;
zipf: the effective prefix carrying HOT_MASS_DEF of the mass) — and the
post-seed hot residency lands top-level as `hot_resident_pages_after_seed` /
`hot_resident_pct_after_seed`. This makes "measured hot-set residency under
each cap" directly extractable, which is what places the critical cap
(hot-set < cap < |R|) from data instead of arithmetic. Uniform cells record
null (no hot set exists).

MID-RUN HOT-SET SWITCH (--hotset-switch-pass, added 2026-09-06): the
WORKLOAD half of situation E8 in spike/ebpf_pagecache/TEST_SITUATIONS.md.
The eBPF battery can already rewrite a policy's pinned hot table at pass N
(load_hotset.py refresh), but with the draw's ranking fixed at construction
that only measured "the table goes wrong at pass N" (a timed E6). With
--hotset-switch-pass N the cell builds a SECOND SkewDraw from an independent
seed and draws passes N..end from it, so the workload's hot set genuinely
moves mid-run and a policy refresh at the same pass can be scored on whether
it tracks the move. OFF by default (0) and inert unless requested: with the
switch off every draw, log line and JSON field is bit-identical to before.
Determinism is unchanged in form — the second draw replays from
--hotset-switch-seed exactly as the first replays from --seed, and both seeds
(plus the derived ranking seeds, the new hot-set size and its overlap with
the old one) land in the result JSON's `hotset_switch` block. Passes then
also carry `hot_set_epoch` and the residency of BOTH hot sets, so the old
set's decay and the new set's warm-up are separately readable.
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
# Default derivation for the mid-run hot-set switch's second seed: distinct
# from the ranking XOR (0x5EAB1D) and the residency-seed XOR (0x5EED) so the
# switched draw shares no state with either.
HOTSET_SWITCH_SEED_XOR = 0x5717C8
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


def mincore_vec(addr, nbytes):
    """Per-page residency bitmap of a mapping via mincore(2) (bit 0 = resident)."""
    npages = (nbytes + PAGE - 1) // PAGE
    vec = ctypes.create_string_buffer(npages)
    rc = libc.mincore(ctypes.c_void_p(addr), ctypes.c_size_t(nbytes), vec)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, "mincore failed: " + os.strerror(err))
    return np.frombuffer(vec.raw, dtype=np.uint8, count=npages) & 1


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


def map_ro(path, madvise_mode):
    fd = os.open(path, os.O_RDONLY)
    size = os.fstat(fd).st_size
    mm = mmap.mmap(fd, size, prot=mmap.PROT_READ)
    mm.madvise(madvise_mode)
    arr = np.frombuffer(mm, dtype=np.uint8)
    addr = arr.ctypes.data
    return fd, mm, arr, addr, size


def touch_pages(arr, page_indices):
    """Fault the given pages by reading one byte from each (page head).
    Random-order gather at C speed; order does not change the fault COUNT but
    does drive random-access LRU behaviour under a cap, matching randread.
    Duplicate indices (the skewed draw touches hot pages many times) are fine:
    the repeats are minor/no faults once the page is resident."""
    heads = arr[:: PAGE]  # view of one byte per page
    # int64 reduction forces every gathered byte to be read (=> the page faults)
    return int(heads[page_indices].astype(np.int64).sum())


def parse_skew(spec):
    """--skew hotset:h:m | hotsetc:h:m[:E] | zipf:s  ->  dict, or None (uniform)."""
    if not spec:
        return None
    parts = spec.split(":")
    kind = parts[0].strip().lower()
    if kind in ("hotset", "hotsetc"):
        want = "hotset:h:m" if kind == "hotset" else "hotsetc:h:m[:E]"
        if not (len(parts) == 3 or (kind == "hotsetc" and len(parts) == 4)):
            raise SystemExit("bad --skew: expected %s, got %r" % (want, spec))
        h, m = float(parts[1]), float(parts[2])
        if not (0.0 < h < 1.0):
            raise SystemExit("--skew %s h must be in (0,1), got %r" % (kind, h))
        if not (0.0 < m < 1.0):
            raise SystemExit("--skew %s m must be in (0,1), got %r" % (kind, m))
        extents = None
        if kind == "hotsetc":
            extents = int(parts[3]) if len(parts) == 4 else 8
            if extents < 1:
                raise SystemExit("--skew hotsetc E must be >= 1, got %r" % extents)
        return {"spec": spec, "kind": kind, "h": h, "m": m, "s": None,
                "extents": extents}
    if kind == "zipf":
        if len(parts) != 2:
            raise SystemExit("bad --skew: expected zipf:s, got %r" % spec)
        s = float(parts[1])
        if s <= 0.0:
            raise SystemExit("--skew zipf s must be > 0, got %r" % s)
        return {"spec": spec, "kind": "zipf", "h": None, "m": None, "s": s,
                "extents": None}
    raise SystemExit("unknown --skew kind %r (expected hotset:h:m, "
                     "hotsetc:h:m[:E] or zipf:s)" % kind)


class SkewDraw:
    """Seeded skewed touch generator over R's pages.

    ranking      : seeded permutation of page ids; rank 0 is the hottest page.
    hot_set_pages: hotset -> round(h*N); zipf -> the shortest ranking prefix
                   carrying HOT_MASS_DEF of the Zipf mass (an *effective* hot
                   set, so the JSON reports one comparable quantity for both
                   parameterisations).
    Every pass draws `ntouch` = N touches with replacement from the same
    distribution, seeded by (seed, pass), then shuffles them so hot touches are
    interleaved in time rather than blocked (blocking would hand any LRU arm a
    trivially protectable run)."""

    HOT_MASS_DEF = 0.80

    def __init__(self, skew, npages, seed):
        self.skew = skew
        self.npages = npages
        self.seed = seed
        self.extent_table = None
        rank_rng = np.random.default_rng(seed ^ 0x5EAB1D)
        if skew["kind"] == "hotsetc":
            # Clustered hot set: same size as hotset, laid out as E contiguous
            # extents at seeded offsets (adjacent extents may touch; the actual
            # table is recorded). The ranking is hot extents first, then the
            # permuted cold remainder, so every downstream consumer (draw,
            # draw_stats, hot residency) works unchanged off ranking[:n_hot].
            self.n_hot = max(1, int(round(skew["h"] * npages)))
            n_ext = min(skew["extents"], self.n_hot)
            base = self.n_hot // n_ext
            sizes = np.full(n_ext, base, dtype=np.int64)
            sizes[: self.n_hot - base * n_ext] += 1
            free = npages - self.n_hot
            cuts = np.sort(rank_rng.integers(0, free + 1, size=n_ext))
            starts = cuts + np.concatenate(([0], np.cumsum(sizes[:-1])))
            self.extent_table = [[int(s), int(l)] for s, l in zip(starts, sizes)]
            hot = np.concatenate([np.arange(s, s + l, dtype=np.int64)
                                  for s, l in zip(starts, sizes)])
            mask = np.ones(npages, dtype=bool)
            mask[hot] = False
            cold = rank_rng.permutation(np.flatnonzero(mask)).astype(np.int64)
            self.ranking = np.concatenate([hot, cold])
            self.hot = self.ranking[:self.n_hot]
            self.cold = self.ranking[self.n_hot:]
            self.cdf = None
            return
        self.ranking = rank_rng.permutation(npages).astype(np.int64)
        if skew["kind"] == "hotset":
            self.n_hot = max(1, int(round(skew["h"] * npages)))
            self.hot = self.ranking[:self.n_hot]
            self.cold = self.ranking[self.n_hot:]
            self.cdf = None
        else:
            ranks = np.arange(1, npages + 1, dtype=np.float64)
            w = ranks ** (-skew["s"])
            cdf = np.cumsum(w)
            cdf /= cdf[-1]
            self.cdf = cdf
            self.n_hot = int(np.searchsorted(cdf, self.HOT_MASS_DEF) + 1)
            self.hot = self.ranking[:self.n_hot]
            self.cold = None

    def draw(self, p, ntouch):
        """(touches, hot_touch_frac) for pass p — deterministic in (seed, p)."""
        rng = np.random.default_rng([self.seed, 0xD8A9, p])
        if self.skew["kind"] in ("hotset", "hotsetc"):
            is_hot = rng.random(ntouch) < self.skew["m"]
            n_hot_draw = int(np.count_nonzero(is_hot))
            touches = np.empty(ntouch, dtype=np.int64)
            touches[is_hot] = self.hot[rng.integers(0, self.hot.size, n_hot_draw)]
            touches[~is_hot] = self.cold[
                rng.integers(0, self.cold.size, ntouch - n_hot_draw)]
            hot_frac = n_hot_draw / float(ntouch)
            del is_hot
        else:
            pos = np.searchsorted(self.cdf, rng.random(ntouch))
            np.clip(pos, 0, self.npages - 1, out=pos)
            hot_frac = float(np.count_nonzero(pos < self.n_hot)) / float(ntouch)
            touches = self.ranking[pos]
            del pos
        rng.shuffle(touches)
        return touches, hot_frac


def draw_stats(touches, npages, n_hot, ranking):
    """Pass-1 draw evidence: distinct pages reached, the touches-per-page
    histogram, and the hot/cold mean touch rates the target h/m implies.
    Computed for pass 1 only — the temporary per-page count array is ~8 bytes
    per page of R and is freed before the next pass, so it does not sit in the
    cell's anon footprint while a cap is binding."""
    counts = np.bincount(touches, minlength=npages)
    distinct = int(np.count_nonzero(counts))
    hist_counts = np.bincount(counts)
    hist = {str(i): int(c) for i, c in enumerate(hist_counts[:16]) if c}
    tail = int(hist_counts[16:].sum()) if hist_counts.size > 16 else 0
    if tail:
        hist["16+"] = tail
    hot_ids = ranking[:n_hot] if n_hot else None
    if hot_ids is not None and n_hot < npages:
        hot_mean = float(counts[hot_ids].mean())
        cold_sum = int(counts.sum()) - int(counts[hot_ids].sum())
        cold_mean = cold_sum / float(npages - n_hot)
        hot_distinct = int(np.count_nonzero(counts[hot_ids]))
    else:
        hot_mean = cold_mean = None
        hot_distinct = None
    del counts, hist_counts
    return {"distinct_pages_touched": distinct,
            "touch_count_histogram": hist,
            "hot_mean_touches_per_page": hot_mean,
            "cold_mean_touches_per_page": cold_mean,
            "hot_distinct_pages_touched": hot_distinct}


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
    ap.add_argument("--fault-around", action="store_true",
                    help="map R with MADV_NORMAL (readahead / fault-around ON, "
                         "what the real stack gets) instead of MADV_RANDOM")
    ap.add_argument("--warm-l", action="store_true",
                    help="touch every page of L before seeding R and keep its "
                         "mapping alive: a load-time RESIDUE population the cap "
                         "must sort out (the real stack's inversion mechanism; "
                         "without it, caps above |R| are measured trajectory-"
                         "invariant). Per-pass l_resident_pct records the sort.")
    ap.add_argument("--skew", default=None,
                    help="hotset:h:m (e.g. hotset:0.20:0.80) or zipf:s; "
                         "omitted = uniform one-touch-per-page (Tier-1c)")
    ap.add_argument("--hotset-switch-pass", type=int, default=0,
                    help="situation E8 (workload half): from this pass onward "
                         "draw from a SECOND, independently seeded hot set — "
                         "i.e. the workload's hot set moves mid-run. Needs "
                         "--skew; must be in [2, --passes]. 0 = off (default), "
                         "in which case the cell is bit-identical to before "
                         "this flag existed.")
    ap.add_argument("--hotset-switch-seed", type=int, default=None,
                    help="seed for the post-switch draw (default: "
                         "--seed ^ 0x%X). The switched ranking and every "
                         "post-switch pass replay from this alone."
                         % HOTSET_SWITCH_SEED_XOR)
    ap.add_argument("--hotset-switch-skew", default=None,
                    help="skew spec for the post-switch draw (default: the "
                         "same spec as --skew, so only the hot set moves). "
                         "Give e.g. hotset:0.30:0.80 to also change h/m.")
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
                    help="exit nonzero if pass-1 majflt != reachable deficit")
    args = ap.parse_args()

    skew = parse_skew(args.skew)

    # --- mid-run hot-set switch (E8 workload half). Every check below is
    # reachable only when --hotset-switch-pass > 0, so the default path is
    # untouched. A switch that would draw the SAME hot set is rejected rather
    # than run: it looks like an E8 cell in the log and silently is not one.
    switch_pass = args.hotset_switch_pass
    skew2 = None
    switch_seed = None
    if switch_pass:
        if skew is None:
            raise SystemExit("--hotset-switch-pass needs --skew (a uniform "
                             "cell has no hot set to switch)")
        if not (2 <= switch_pass <= args.passes):
            raise SystemExit("--hotset-switch-pass must be in [2, --passes=%d]"
                             ", got %d (pass 1 carries the soundness identity)"
                             % (args.passes, switch_pass))
        switch_seed = (args.hotset_switch_seed if args.hotset_switch_seed
                       is not None else args.seed ^ HOTSET_SWITCH_SEED_XOR)
        skew2 = parse_skew(args.hotset_switch_skew or skew["spec"])
        if switch_seed == args.seed and skew2["spec"] == skew["spec"]:
            raise SystemExit("--hotset-switch-pass with the cell's own seed "
                             "and spec is a no-op (identical hot set); give "
                             "--hotset-switch-seed or --hotset-switch-skew")

    os.makedirs(args.data_dir, exist_ok=True)
    r_path = os.path.join(args.data_dir, "R.bin")
    l_path = os.path.join(args.data_dir, "L.bin")
    r_bytes = args.r_size_mib * 1024 * 1024
    l_bytes = args.l_size_mib * 1024 * 1024

    def log(msg):
        print("[t1d] %s" % msg, flush=True)

    log("cell arm=%s cap=%s resident_frac=%.4f passes=%d seed=%d R=%dMiB L=%dMiB skew=%s"
        % (args.arm, args.cap_label, args.resident_frac, args.passes,
           args.seed, args.r_size_mib, args.l_size_mib, args.skew or "uniform"))

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

    # S-faultaround arm (pre-reg section 3.4): MADV_NORMAL leaves readahead /
    # fault-around ON -- what the real stack gets, since it issues no fadvise --
    # so one touch can bring in a whole cluster of neighbouring pages. That
    # breaks the one-major-fault-per-missing-page property BOTH the residency
    # seed and the soundness identity rest on, deliberately: the identity is
    # defined for MADV_RANDOM cells, and a --fault-around cell is judged on its
    # floor trajectory (see soundness_identity_applicable in the JSON).
    madv = mmap.MADV_NORMAL if args.fault_around else mmap.MADV_RANDOM
    madv_name = "MADV_NORMAL" if args.fault_around else "MADV_RANDOM"
    r_fd, r_mm, r_arr, r_addr, r_size = map_ro(r_path, madv)
    npages = r_size // PAGE
    log("R mapped with %s (fault-around %s)"
        % (madv_name, "ON" if args.fault_around else "OFF"))

    # Residue population (--warm-l): sequentially touch all of L BEFORE seeding
    # R and keep the mapping alive for the whole cell. Under a cap this is the
    # load-time residue the kernel must sort out while R is being re-touched --
    # the real stack's inversion mechanism (RESULTS.md section 22: a no-residue
    # load kills the artifact at every cap, and the T1d-13 cap-bracket cells
    # measured the synthetic to be trajectory-invariant at every cap > |R|
    # precisely because no residue existed). Touch order is sequential, like a
    # load; the mapping is MADV_RANDOM so the warm is one fault per page.
    l_fd = l_mm = l_arr = None
    l_addr = l_size_b = l_npages = None
    l_res_after_warm = None
    if args.warm_l:
        l_fd, l_mm, l_arr, l_addr, l_size_b = map_ro(l_path, mmap.MADV_RANDOM)
        l_npages = l_size_b // PAGE
        touch_pages(l_arr, np.arange(l_npages, dtype=np.int64))
        l_res_after_warm = int(np.count_nonzero(mincore_vec(l_addr, l_size_b)))
        log("L warmed as residue: %d/%d pages resident (%.4f%%)"
            % (l_res_after_warm, l_npages,
               100.0 * l_res_after_warm / l_npages))

    # ---- Initial-state seed: warm ONLY the target-resident subset, leaving the
    # rest never-loaded. MADV_RANDOM disables readahead, so faulting the chosen
    # pages brings in exactly those pages and the untouched (1 - frac) remain
    # non-resident => a MAJOR fault on their first touch in pass 1. (Evicting an
    # already-warm subset does NOT work here: MADV_DONTNEED only drops PTEs while
    # the clean file pages stay in the page cache, so mincore still counts them
    # resident and re-access is a minor fault -- no deficit. Warming a subset of
    # a cold file is the direct, cache-honest way to set residency.) Inherited
    # from Tier-1c unchanged: the seed is INDEPENDENT of the skew ranking, so
    # initial residency carries no hot/cold correlation of its own.
    n_resident = int(round(args.resident_frac * npages))
    rng = np.random.default_rng(args.seed ^ 0x5EED)
    resident_idx = rng.choice(npages, size=n_resident, replace=False).astype(np.int64)
    if n_resident:
        touch_pages(r_arr, resident_idx)
    res_bits = mincore_vec(r_addr, r_size)
    res_after_seed = int(np.count_nonzero(res_bits))
    missing_mask = res_bits == 0
    seed_deficit = npages - res_after_seed
    log("seeded: warmed %d target-resident, R resident %d/%d pages (%.4f%%), deficit=%d"
        % (n_resident, res_after_seed, npages,
           100.0 * res_after_seed / npages, seed_deficit))

    # ---- Repeat passes. Uniform mode: the Tier-1c fixed seeded permutation
    # (one touch per page, same order every pass). Skew mode: N touches per pass
    # drawn with replacement from the hot-set/Zipf distribution, seeded by
    # (seed, pass).
    if skew is None:
        perm_rng = np.random.default_rng(args.seed)
        perm = perm_rng.permutation(npages).astype(np.int64)
        drawer = None
        n_hot = npages
        hot_bytes = r_size
    else:
        perm = None
        drawer = SkewDraw(skew, npages, args.seed)
        n_hot = drawer.n_hot
        hot_bytes = n_hot * PAGE
        log("skew %s: hot set %d/%d pages (%.4f%% of R, %.1f MiB)%s"
            % (skew["spec"], n_hot, npages, 100.0 * n_hot / npages,
               hot_bytes / (1024.0 * 1024.0),
               "" if skew["kind"] in ("hotset", "hotsetc")
               else " [effective: prefix carrying %.2f of Zipf mass]"
                    % SkewDraw.HOT_MASS_DEF))
    if drawer is not None and drawer.extent_table is not None:
        log("hot layout CLUSTERED: %d extents %s"
            % (len(drawer.extent_table),
               " ".join("@%d+%d" % (s, l) for s, l in drawer.extent_table)))

    # Second (post-switch) draw. Built up front, not lazily at the switch pass,
    # so a bad spec fails before the cell burns a window and so the overlap
    # with the epoch-0 hot set is recorded whatever happens later in the run.
    drawer2 = None
    n_hot2 = hot_bytes2 = switch_overlap = None
    if switch_pass:
        drawer2 = SkewDraw(skew2, npages, switch_seed)
        n_hot2 = drawer2.n_hot
        hot_bytes2 = n_hot2 * PAGE
        switch_overlap = int(np.intersect1d(drawer.hot, drawer2.hot).size)
        log("hot-set SWITCH armed at pass %d: seed %d, skew %s, hot set "
            "%d/%d pages (%.1f MiB), overlap with the original hot set "
            "%d pages (%.4f%% of the new set)"
            % (switch_pass, switch_seed, skew2["spec"], n_hot2, npages,
               hot_bytes2 / (1024.0 * 1024.0), switch_overlap,
               100.0 * switch_overlap / n_hot2))
        if drawer2.extent_table is not None:
            log("switched hot layout CLUSTERED: %d extents %s"
                % (len(drawer2.extent_table),
                   " ".join("@%d+%d" % (s, l) for s, l in drawer2.extent_table)))

    # Hot-set residency after the seed (T1d-7 readout 4). The seed is drawn
    # independently of the skew ranking, so this should sit near resident_frac;
    # recording it makes that assumption checkable per cell.
    if drawer is None:
        hot_res_seed = None
    else:
        hot_res_seed = int(np.count_nonzero(res_bits[drawer.hot]))
        log("hot-set residency after seed: %d/%d pages (%.4f%%)"
            % (hot_res_seed, n_hot, 100.0 * hot_res_seed / n_hot))
    hot_res_seed2 = None
    if drawer2 is not None:
        hot_res_seed2 = int(np.count_nonzero(res_bits[drawer2.hot]))
        log("switched hot-set residency after seed: %d/%d pages (%.4f%%)"
            % (hot_res_seed2, n_hot2, 100.0 * hot_res_seed2 / n_hot2))

    passes = []
    converged_pass = None
    pass1_stats = None
    reachable_deficit = None
    for p in range(1, args.passes + 1):
        # `active` is the drawer this pass draws from: epoch 0 until the switch
        # pass, epoch 1 from it onward. Without --hotset-switch-pass drawer2 is
        # None and active is drawer for every pass, as before.
        if drawer2 is not None and p >= switch_pass:
            active, epoch, active_n_hot = drawer2, 1, n_hot2
            if p == switch_pass:
                log("hot-set SWITCH: pass %d onward draws from the epoch-1 hot "
                    "set (seed %d)" % (switch_pass, switch_seed))
        else:
            active, epoch, active_n_hot = drawer, 0, n_hot
        if drawer is None:
            touches, hot_frac = perm, None
        else:
            touches, hot_frac = active.draw(p, npages)
        if p == 1:
            if drawer is None:
                pass1_stats = {"distinct_pages_touched": npages,
                               "touch_count_histogram": {"1": npages},
                               "hot_mean_touches_per_page": None,
                               "cold_mean_touches_per_page": None,
                               "hot_distinct_pages_touched": None}
                reachable_deficit = seed_deficit
            else:
                pass1_stats = draw_stats(touches, npages, n_hot, drawer.ranking)
                # Reachable deficit = the missing pages pass 1 actually reaches.
                # A fixed-count skewed draw cannot cover every page, so this --
                # not the full seeded deficit -- is what pass-1 majflt must equal.
                touched_mask = np.zeros(npages, dtype=bool)
                touched_mask[touches] = True
                reachable_deficit = int(np.count_nonzero(missing_mask & touched_mask))
                del touched_mask
        mf0 = read_majflt()
        w0 = time.monotonic()
        touch_pages(r_arr, touches)
        w1 = time.monotonic()
        mf1 = read_majflt()
        res_bits_now = mincore_vec(r_addr, r_size)
        res_now = int(np.count_nonzero(res_bits_now))
        if drawer is None:
            hot_res_now = None
        else:
            hot_res_now = int(np.count_nonzero(res_bits_now[active.hot]))
        if drawer2 is None:
            hot_res_e0 = hot_res_e1 = None
        else:
            # Both hot sets every pass, so the abandoned set's decay and the
            # new set's warm-up are separately readable across the switch.
            hot_res_e0 = int(np.count_nonzero(res_bits_now[drawer.hot]))
            hot_res_e1 = int(np.count_nonzero(res_bits_now[drawer2.hot]))
        del res_bits_now
        if args.warm_l:
            l_res_now = int(np.count_nonzero(mincore_vec(l_addr, l_size_b)))
        else:
            l_res_now = None
        majflt = mf1 - mf0
        rec = {"pass": p, "majflt": majflt,
               "wall_s": round(w1 - w0, 3),
               "touches": int(npages),
               "hot_touch_frac": None if hot_frac is None else round(hot_frac, 6),
               "resident_pages": res_now,
               "resident_pct": round(100.0 * res_now / npages, 4),
               "hot_resident_pages": hot_res_now,
               "hot_resident_pct": None if hot_res_now is None
                                   else round(100.0 * hot_res_now
                                              / active_n_hot, 4),
               "l_resident_pages": l_res_now,
               "l_resident_pct": None if l_res_now is None
                                 else round(100.0 * l_res_now / l_npages, 4)}
        if p == 1:
            rec.update(pass1_stats)
        if drawer2 is not None:
            # Switch-only keys: a cell run without --hotset-switch-pass keeps
            # exactly the per-pass schema it had before this knob existed.
            rec.update({
                "hot_set_epoch": epoch,
                "hot_resident_pages_epoch0": hot_res_e0,
                "hot_resident_pct_epoch0": round(100.0 * hot_res_e0 / n_hot, 4),
                "hot_resident_pages_epoch1": hot_res_e1,
                "hot_resident_pct_epoch1": round(100.0 * hot_res_e1 / n_hot2, 4),
            })
        passes.append(rec)
        log("pass %d: majflt %d  wall %.3fs  R_resident %.2f%%%s%s%s"
            % (p, majflt, rec["wall_s"], rec["resident_pct"],
               "" if hot_frac is None
               else "  hot_resident %.2f%%  hot_touch_frac %.4f"
                    % (rec["hot_resident_pct"], hot_frac),
               "" if l_res_now is None
               else "  L_resident %.2f%%" % rec["l_resident_pct"],
               "" if drawer2 is None
               else "  epoch %d  hot_e0 %.2f%%  hot_e1 %.2f%%"
                    % (epoch, rec["hot_resident_pct_epoch0"],
                       rec["hot_resident_pct_epoch1"])))
        if drawer is not None:
            del touches
        if majflt <= args.near_zero and converged_pass is None:
            converged_pass = p
            # keep going to record the steady tail, but note first-zero pass

    self_check_ok = (passes[0]["majflt"] == reachable_deficit)
    full_identity_ok = (passes[0]["majflt"] == seed_deficit)
    out = {
        "protocol": "tier1d",
        "arm": args.arm,
        "cap_label": args.cap_label,
        "resident_frac_target": args.resident_frac,
        "resident_frac_actual": round(res_after_seed / npages, 6),
        "seed": args.seed,
        "r_size_mib": args.r_size_mib,
        "l_size_mib": args.l_size_mib,
        "r_pages": npages,
        "madvise": madv_name,
        "fault_around": bool(args.fault_around),
        "skew": None if skew is None else {
            "spec": skew["spec"], "kind": skew["kind"],
            "h": skew["h"], "m": skew["m"], "s": skew["s"],
            "hot_set_pages": n_hot,
            "hot_set_bytes": hot_bytes,
            "hot_set_mib": round(hot_bytes / (1024.0 * 1024.0), 3),
            "hot_mass_definition": None if skew["kind"] in ("hotset", "hotsetc")
                                   else SkewDraw.HOT_MASS_DEF,
            "hot_layout": "clustered" if skew["kind"] == "hotsetc"
                          else "scattered",
            "extents": skew["extents"],
            "hot_extents": drawer.extent_table,
            "touches_per_pass": npages,
            "draw_with_replacement": True,
            "draw_per_pass_seeded": True,
            "ranking_seed": args.seed ^ 0x5EAB1D,
        },
        "seed_deficit_pages": seed_deficit,
        "warm_l": bool(args.warm_l),
        "l_pages": l_npages,
        "l_resident_after_warm_pages": l_res_after_warm,
        "l_resident_after_warm_pct": None if l_res_after_warm is None
                                     else round(100.0 * l_res_after_warm
                                                / l_npages, 4),
        "hot_resident_pages_after_seed": hot_res_seed,
        "hot_resident_pct_after_seed": None if hot_res_seed is None
                                       else round(100.0 * hot_res_seed / n_hot, 4),
        "pass1_reachable_deficit_pages": reachable_deficit,
        "near_zero": args.near_zero,
        "converged_first_pass": converged_pass,
        "converged": converged_pass is not None,
        "soundness_identity_kind": "uniform_full_deficit" if skew is None
                                   else "skew_reachable_deficit",
        "soundness_identity_applicable": not args.fault_around,
        "soundness_pass1_majflt_eq_deficit": self_check_ok,
        "soundness_pass1_majflt_eq_full_deficit": full_identity_ok,
        "passes": passes,
    }
    if drawer2 is not None:
        # Present ONLY on a switched cell (an unswitched result JSON keeps its
        # exact key set). Shaped like the `skew` block above — same field names
        # for kind/hot_set_pages/ranking_seed/hot_extents — so a consumer can
        # rebuild the epoch-1 hot set with the epoch-0 code path
        # (load_hotset.py chunks --epoch 1 does exactly that).
        out["hotset_switch"] = {
            "switch_pass": switch_pass,
            "switch_seed": switch_seed,
            "spec": skew2["spec"], "kind": skew2["kind"],
            "h": skew2["h"], "m": skew2["m"], "s": skew2["s"],
            "hot_set_pages": n_hot2,
            "hot_set_bytes": hot_bytes2,
            "hot_set_mib": round(hot_bytes2 / (1024.0 * 1024.0), 3),
            "hot_mass_definition": None if skew2["kind"] in ("hotset", "hotsetc")
                                   else SkewDraw.HOT_MASS_DEF,
            "hot_layout": "clustered" if skew2["kind"] == "hotsetc"
                          else "scattered",
            "extents": skew2["extents"],
            "hot_extents": drawer2.extent_table,
            "draw_per_pass_seeded": True,
            "ranking_seed": switch_seed ^ 0x5EAB1D,
            "overlap_with_epoch0_pages": switch_overlap,
            "overlap_frac_of_epoch1_hot": round(switch_overlap
                                                / float(n_hot2), 6),
            "hot_resident_pages_after_seed": hot_res_seed2,
            "hot_resident_pct_after_seed": round(100.0 * hot_res_seed2
                                                 / n_hot2, 4),
        }
    with open(args.result_file, "w") as fh:
        json.dump(out, fh, indent=2)
    log("wrote %s  converged=%s (first pass %s)  soundness=%s (reachable deficit %d of %d missing)"
        % (args.result_file, out["converged"], converged_pass, self_check_ok,
           reachable_deficit, seed_deficit))

    del r_arr, perm, resident_idx, res_bits, missing_mask
    r_mm.close()
    os.close(r_fd)
    if l_mm is not None:
        del l_arr
        l_mm.close()
        os.close(l_fd)
    if args.self_check and args.fault_around and not self_check_ok:
        log("self-check SKIPPED: --fault-around (MADV_NORMAL) breaks the "
            "one-fault-per-missing-page identity by design; pass1 majflt %d vs "
            "reachable deficit %d — judged on the floor trajectory"
            % (passes[0]["majflt"], reachable_deficit))
    elif args.self_check and not self_check_ok:
        log("SELF-CHECK FAILED: pass1 majflt %d != reachable deficit %d"
            % (passes[0]["majflt"], reachable_deficit))
        sys.exit(3)


if __name__ == "__main__":
    main()
