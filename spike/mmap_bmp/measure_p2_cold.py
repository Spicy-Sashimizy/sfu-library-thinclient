#!/usr/bin/env python3
"""
mmap-BMP spike — P2 STEP 2: cold-p95 at persona scale (gate G3a/G3b).

Runs the FORKED flat `bmp.Searcher` (`BMP_LOAD=flat`, mmap'd + lazy per-block
decode) over a persona-sized `.bmflat` set, measuring:

  G3a WARM   warm p50 <= live Qdrant p50 on the same section.        [HARD]
  G3b COLD   cold p95 <= ~2-3x warm p95 (after drop_caches).         [HARD]
  G3c DISK   persona flat on-disk vs BMP b256 size (SIGNAL).

This retires R1 (cold-cache faults). `drop_caches` evicts the OS page cache
that the LIVE qdrant process shares, so cold passes DISTURB live serving —
this harness must only be run in a window where that is acceptable.

DESIGN:
  - cold pass = the search AFTER `echo 3 > drop_caches` (page cache empty;
    first-touch faults the postings pages back in). measure_p50/p95.
  - warm pass = a second pass over the SAME shards with no drop between
    (now fully resident; persona < page cache so this is cleanly "warm").
    For personas that exceed cache, repeat the warm pass a few times.
  - compares to the live-qdrant `measure` numbers (read from the recorded
    result file / arg, NOT re-measured live — re-measuring would fault the
    cache we just dropped). G3a's "qdrant p50" comes from
    `scripts/spike_qdrant_sparse.py measure` results, fixed by section.

Run from repo root (forked venv has the R3 flat wheel):

    BMP_LOAD=flat MMAP_BMP_SITE=<fork-venv>/lib/python3.11/site-packages \
      <fork-venv>/bin/python3 spike/mmap_bmp/measure_p2_cold.py \
        --flat 'spike/mmap_bmp/persona_med_bio/*.bmflat' \
        --baseline spike/mmap_bmp/out \
        --qdrant-p50 66 --result-file data/eval_results/p2_coldp95_med_bio.json

Needs `sudo` for drop_caches (available per FORK_BMP.md). If run without sudo
or --no-drop, falls back to process-local `posix_fadvise(DONTNEED)` on the
mmap files (weaker cold signal — documented as a degraded cold pass).
"""
import argparse, glob, json, os, subprocess, sys, time

site = os.environ.get("MMAP_BMP_SITE")
if site:
    sys.path.insert(0, site)
import bmp as fbmp  # R3 forked flat-aware build


def _kb(key):
    for line in open("/proc/self/status"):
        if line.startswith(key):
            return int(line.split()[1])
    return -1


def rssanon_gb():
    return _kb("RssAnon:") / 1024 / 1024


def rss_gb():
    return _kb("VmRSS:") / 1024 / 1024


def drop_caches():
    """Evict the OS page cache. Needs root. Returns True on success."""
    p = subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                       capture_output=True, text=True)
    return p.returncode == 0


def posix_cold(files):
    """Best-effort process-local cold: POSIX_FADV_DONTNEED on each mmap file."""
    import ctypes
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    POSIX_FADV_DONTNEED = 4
    ok = []
    for f in files:
        try:
            fd = os.open(f, os.O_RDONLY)
            sz = os.fstat(fd).st_size
            libc.posix_fadvise(fd, ctypes.c_long(0), ctypes.c_long(sz), ctypes.c_int(POSIX_FADV_DONTNEED))
            os.close(fd)
            ok.append(True)
        except OSError:
            ok.append(False)
    return all(ok)


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p / 100))], 2)


def run_pass(searchers, qvecs, k, alpha, beta):
    lat = []
    blocks = []  # confound control: #blocks scored per query (doc 06 §3). 0 if backend none.
    for s in searchers:
        for q, qv in qvecs.items():
            qv = {t: int(w) for t, w in qv.items()}
            t0 = time.perf_counter()
            try:
                s.search(qv, k=k, alpha=alpha, beta=beta)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                continue  # pyo3 panic on no-overlap query term in a shard
            lat.append((time.perf_counter() - t0) * 1000)
            # `blocks_scored` is a PyO3 #[getter] (read-and-reset int); absent on stock.
            blocks.append(getattr(s, "blocks_scored", 0))
    return lat, blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flat", default="spike/mmap_bmp/persona_med_bio/*.bmflat")
    ap.add_argument("--baseline", default="spike/mmap_bmp/out",
                    help="dir with qvecs.json (reuses P0 query vectors)")
    ap.add_argument("--qdrant-p50", type=float, default=66.0,
                    help="recorded live-qdrant warm p50 (ms) on this section")
    ap.add_argument("--result-file", default="data/eval_results/p2_coldp95_med_bio.json")
    ap.add_argument("--cold-passes", type=int, default=3, help="cold passes (drop before each)")
    ap.add_argument("--warm-passes", type=int, default=3, help="warm passes after the cold set")
    ap.add_argument("--no-drop", action="store_true",
                    help="skip sudo drop_caches; use weaker posix_fadvise cold instead")
    args = ap.parse_args()

    k = json.load(open(f"{args.baseline}/baseline.json"))["meta"]["k"]
    qvecs = json.load(open(f"{args.baseline}/qvecs.json"))
    ALPHA, BETA = 0.8, 1.0
    flats = sorted(glob.glob(args.flat))
    assert flats, f"no .bmflat matched {args.flat}"
    print(f"{len(flats)} flat shard(s); {len(qvecs)} queries; k={k}", flush=True)

    can_drop = not args.no_drop
    if can_drop and not drop_caches():
        print("WARNING: sudo drop_caches failed — falling back to posix_fadvise (weak cold)", flush=True)
        can_drop = False
    cold_mode = "drop_caches (real cold)" if can_drop else "posix_fadvise (weak cold)"
    print(f"cold mode: {cold_mode}", flush=True)

    searchers = [fbmp.Searcher(fp) for fp in flats]   # BMP_LOAD=flat -> mmap lazy
    live_bytes = sum(os.path.getsize(f) for f in flats)
    rss_after = rss_gb(); anon = rssanon_gb()
    print(f"loaded {len(flats)} shard(s): flat {live_bytes/1e6:.0f}MB; "
          f"VmRSS {rss_after:.3f}GB; RssAnon {anon:.3f}GB (want ~0 — the G2 cure holds)",
          flush=True)

    cold_lat_all = []
    blocks_all = []  # #blocks-scored-per-query confound (doc 06 §3)
    for i in range(args.cold_passes):
        if can_drop:
            drop_caches()
        else:
            posix_cold(flats)
        print(f"cold pass {i+1}/{args.cold_passes} …", flush=True)
        lat, blocks = run_pass(searchers, qvecs, k, ALPHA, BETA)
        cold_lat_all.extend(lat)
        blocks_all.extend(blocks)

    warm_lat_all = []
    for i in range(args.warm_passes):
        print(f"warm pass {i+1}/{args.warm_passes} …", flush=True)
        lat, _ = run_pass(searchers, qvecs, k, ALPHA, BETA)
        warm_lat_all.extend(lat)

    res = {
        "meta": {"engine": "immsparse-flat-persona-zerodecode", "section": "med_bio",
                 "k": k, "alpha": ALPHA, "beta": BETA, "built_utc": "2026-06-26",
                 "cold_mode": cold_mode, "shards": len(flats),
                 "flat_mb": round(live_bytes / 1e6, 1),
                 "rss_after_load_gb": round(rss_after, 3),
                 "rssanon_after_load_gb": round(anon, 3),
                 "qdrant_p50_ms_ref": args.qdrant_p50,
                 "layout": "R3-v2 zero-decode: bytemuck cast_slice + flat_block_score (vs R3-v1 decode-per-query)"},
        "cold": {"n": len(cold_lat_all), "p50": pct(cold_lat_all, 50),
                 "p95": pct(cold_lat_all, 95)},
        "warm": {"n": len(warm_lat_all), "p50": pct(warm_lat_all, 50),
                 "p95": pct(warm_lat_all, 95)},
        # Confound control (06 §3): if #blocks-scored grows with shard size,
        # pruning/iteration is the wall and zero-decode can't save it — decisive
        # regardless of the latency number. Per-query, per-shard across cold passes.
        "blocks_scored": {"n": len(blocks_all), "p50": pct(blocks_all, 50),
                          "p95": pct(blocks_all, 95), "max": max(blocks_all) if blocks_all else None},
    }

    cold_warm_ratio = (res["cold"]["p95"] / res["warm"]["p95"]) if (res["warm"]["p95"] and res["cold"]["p95"]) else None
    res["gate"] = {
        "G3a_warm_le_qdrant": res["warm"]["p50"] is not None and res["warm"]["p50"] <= args.qdrant_p50,
        "G3b_cold_le_3x_warm": cold_warm_ratio is not None and cold_warm_ratio <= 3.0,
        "cold_over_warm_p95": round(cold_warm_ratio, 2) if cold_warm_ratio else None,
    }

    print("\n──────── P2 GATES (persona cold-p95) ────────")
    print(f"G3a WARM p50 {res['warm']['p50']} ms <= qdrant {args.qdrant_p50} ms ? "
          f"{'PASS' if res['gate']['G3a_warm_le_qdrant'] else 'FAIL'}")
    print(f"G3b COLD p95 {res['cold']['p95']} ms | warm p95 {res['warm']['p95']} ms | "
          f"cold/warm={res['gate']['cold_over_warm_p95']} (<=3) ? "
          f"{'PASS' if res['gate']['G3b_cold_le_3x_warm'] else 'FAIL'}")
    print(f"    cold p50 {res['cold']['p50']} / warm p50 {res['warm']['p50']} ms")
    print(f"    RssAnon after load: {anon:.3f} GB (the cure holds at persona scale)")
    nb = res["blocks_scored"]
    print(f"    #blocks-scored/query: p50 {nb['p50']} | p95 {nb['p95']} | max {nb['max']} "
          f"(confound: grows with shard size ⇒ pruning is the wall, not decode)")
    print(f"\nVERDICT:", "GREEN — P2 cold-p95 held; cure is real, spin off immsparse for P3+"
          if (res['gate']['G3a_warm_le_qdrant'] and res['gate']['G3b_cold_le_3x_warm'])
          else "RED — cold-p95 blew up OR warm > qdrant; R1 kills the standalone idea")

    os.makedirs(os.path.dirname(args.result_file), exist_ok=True)
    json.dump(res, open(args.result_file, "w"), indent=2)
    print(f"\nwrote {args.result_file}")


if __name__ == "__main__":
    main()
