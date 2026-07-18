#!/usr/bin/env python3
"""
mmap-BMP spike — STEP 2: run the FORKED mmap BMP build and gate it.

Loads the forked `bmp` (built per FORK_BMP.md into a THROWAWAY venv — never the
serving .venv), replays the SAVED query vectors from STEP 1, and checks the gates:

  G1 CORRECTNESS  mmap top-k (ids+scores) == stock baseline, byte-identical.  [HARD]
  G2 RAM          RssAnon stays ~0 after loading shards (page-cache only).     [HARD]
  G3 LATENCY      cold p50/p95 vs warm; warm should be <= the stock baseline.  [signal]

Point it at the forked build with MMAP_BMP_SITE (the throwaway venv's
site-packages dir that contains the forked `bmp`):

    MMAP_BMP_SITE=/tmp/.../mmapbmp-venv/lib/python3.11/site-packages \
    /tmp/.../mmapbmp-venv/bin/python3 spike/mmap_bmp/compare_fork.py \
        --shards 'data/thinclient_1m/sections/*/splade_000.bmp' \
        --baseline spike/mmap_bmp/out

Cold cache: either `sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'` before a run,
or use a shard large enough not to fit page cache. See FORK_BMP.md §cold.
"""
import argparse, glob, json, os, sys, time

# Load the FORKED bmp first, from the throwaway build — NOT the serving venv.
site = os.environ.get("MMAP_BMP_SITE")
if site:
    sys.path.insert(0, site)
import bmp as mbmp  # forked mmap build

ALPHA, BETA = 0.8, 1.0


def _proc_kb(key):
    for line in open("/proc/self/status"):
        if line.startswith(key):
            return int(line.split()[1])
    return -1


def rssanon_gb():
    return _proc_kb("RssAnon:") / 1024 / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="data/thinclient_1m/sections/*/splade_000.bmp")
    ap.add_argument("--baseline", default="spike/mmap_bmp/out")
    ap.add_argument("--passes", type=int, default=3, help="latency passes (1st = cold)")
    args = ap.parse_args()

    qvecs = json.load(open(f"{args.baseline}/qvecs.json"))
    base = json.load(open(f"{args.baseline}/baseline.json"))
    k = base["meta"]["k"]
    print(f"forked bmp from: {getattr(mbmp, '__file__', '?')}", flush=True)
    print(f"RssAnon before load: {rssanon_gb():.3f} GB", flush=True)

    shards = sorted(glob.glob(args.shards))
    mismatches, checked = 0, 0
    anon_after = None
    cold_lat, warm_lat = [], []

    skipped_shards = []
    for sp in shards:
        s = mbmp.Searcher(sp)
        anon_after = rssanon_gb()  # G2: should stay ~0 if truly mmap'd
        if sp not in base["shards"]:
            # The P0 baseline didn't record this shard — skip it entirely rather
            # than fabricate mismatches (queries with no ground truth can't be
            # checked, and counting them as FAIL is a false negative).
            skipped_shards.append(sp)
            continue
        base_res = base["shards"][sp].get("results", {})
        for p in range(args.passes):
            for q, qv in qvecs.items():
                bq = base_res.get(q, {})
                if "error" in bq or "ids" not in bq:
                    continue  # no ground truth for this (shard, query)
                qv = {t: int(w) for t, w in qv.items()}
                t0 = time.perf_counter()
                ids, scores = s.search(qv, k=k, alpha=ALPHA, beta=BETA)
                dt = (time.perf_counter() - t0) * 1000
                (cold_lat if p == 0 else warm_lat).append(dt)
                if p == 0:  # correctness check once per (shard,query)
                    checked += 1
                    got = {"ids": list(ids), "scores": [round(float(x), 6) for x in scores]}
                    if got["ids"] != bq.get("ids") or got["scores"] != bq.get("scores"):
                        mismatches += 1
                        if mismatches <= 5:
                            print(f"  MISMATCH {os.path.basename(sp)} | {q[:40]!r}", flush=True)

    def pct(xs, p):
        if not xs:
            return None
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(len(xs) * p / 100))], 2)

    print("\n──────── GATES ────────")
    g1 = mismatches == 0 and checked > 0
    print(f"G1 CORRECTNESS  {'PASS' if g1 else 'FAIL'}  ({checked - mismatches}/{checked} identical)")
    g2 = anon_after is not None and anon_after < 1.0  # ~0; <1GB = page-cache only, not load-into-RAM
    print(f"G2 RAM          {'PASS' if g2 else 'FAIL'}  (RssAnon after load = {anon_after:.3f} GB; want ~0)")
    print(f"G3 LATENCY      cold p50 {pct(cold_lat,50)} / p95 {pct(cold_lat,95)} ms | "
          f"warm p50 {pct(warm_lat,50)} / p95 {pct(warm_lat,95)} ms")
    print(f"   (baseline stock p50 ≈ {min((v.get('lat_ms_p50') or 9e9) for v in base['shards'].values())} ms)")
    if skipped_shards:
        print(f"   NOTE: {len(skipped_shards)} shard(s) absent from baseline.json "
              f"(P0 incomplete) — skipped, not counted as G1 mismatches:")
        for sp in skipped_shards:
            print(f"     - {os.path.basename(os.path.dirname(sp))}/{os.path.basename(sp)}")
    print("\nVERDICT:", "GREEN — proceed to cold-p95 at section scale"
          if (g1 and g2) else "RED — fix fork (correctness/RAM) before latency matters")


if __name__ == "__main__":
    main()
