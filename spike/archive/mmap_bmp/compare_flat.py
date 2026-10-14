#!/usr/bin/env python3
"""
> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

mmap-BMP spike — STEP 3 (R3 flat layout): the actual G2 cure.

Transcodes each stock `.bmp` shard into the flat `.bmflat` layout via
`bmp.transcode_to_flat` (reuses the stock loader as the transcode source — no
corpus re-encode), then runs the FORKED flat `bmp.Searcher` (`BMP_LOAD=flat`,
mmap'd + lazy per-block decode) over the saved P0 query vectors and checks:

  G1 CORRECTNESS  flat top-k (ids, scores) == stock baseline, byte-identical. [HARD]
  G2 RAM          RssAnon ~0 after flat load (page-cache only).                [HARD]  <- the cure
  G3 LATENCY      cold p50/p95 vs warm; warm <= the stock baseline.            [signal]

Run from repo root (uses the throwaway forked-venv that has the R3 wheel):

    BMP_LOAD=flat MMAP_BMP_SITE=<throwaway-venv>/lib/python3.11/site-packages \
      <throwaway-venv>/bin/python3 spike/mmap_bmp/compare_flat.py \
        --shards 'data/thinclient_1m/sections/*/splade_000.bmp' \
        --baseline spike/mmap_bmp/out
"""
import argparse, glob, json, os, sys, time

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="data/thinclient_1m/sections/*/splade_000.bmp")
    ap.add_argument("--baseline", default="spike/mmap_bmp/out")
    ap.add_argument("--flat-dir", default="spike/mmap_bmp/flat")
    ap.add_argument("--passes", type=int, default=3, help="latency passes (1st = cold)")
    args = ap.parse_args()
    os.makedirs(args.flat_dir, exist_ok=True)

    qvecs = json.load(open(f"{args.baseline}/qvecs.json"))
    base = json.load(open(f"{args.baseline}/baseline.json"))
    k = base["meta"]["k"]
    ALPHA, BETA = 0.8, 1.0

    shards = sorted(glob.glob(args.shards))
    assert shards, f"no shards matched {args.shards}"
    print(f"transcoding {len(shards)} shard(s) -> {args.flat_dir} …", flush=True)

    flat_paths = {}
    disk_report = []
    for sp in shards:
        # Namespne by section dir so co-located `splade_000.bmp` shards don't
        # clobber each other in the flat dir (they all share that basename).
        section = os.path.basename(os.path.dirname(sp))
        fp = os.path.join(args.flat_dir, f"{section}__{os.path.basename(sp).replace('.bmp', '.bmflat')}")
        if not os.path.exists(fp):
            fbmp.transcode_to_flat(sp, fp)
        flat_paths[sp] = fp
        d_bmp = os.path.getsize(sp) / 1e6
        d_flat = os.path.getsize(fp) / 1e6
        disk_report.append((sp, d_bmp, d_flat))
        print(f"  {os.path.basename(sp)}: bmp {d_bmp:.0f}MB -> flat {d_flat:.0f}MB "
              f"({d_flat / d_bmp:.2f}x)", flush=True)

    print(f"\nRssAnon before flat load: {rssanon_gb():.3f} GB", flush=True)

    mismatches, checked = 0, 0
    anon_peak = 0.0
    cold_lat, warm_lat = [], []

    for sp in shards:
        fp = flat_paths[sp]
        s = fbmp.Searcher(fp)  # BMP_LOAD=flat -> mmap'd lazy reader
        anon_peak = max(anon_peak, rssanon_gb())
        if sp not in base["shards"]:
            print(f"  (no baseline for {os.path.basename(sp)} — skipping G1)", flush=True)
            continue
        base_res = base["shards"][sp].get("results", {})
        for p in range(args.passes):
            for q, qv in qvecs.items():
                bq = base_res.get(q, {})
                if "ids" not in bq:
                    continue
                qv = {t: int(w) for t, w in qv.items()}
                t0 = time.perf_counter()
                ids, scores = s.search(qv, k=k, alpha=ALPHA, beta=BETA)
                dt = (time.perf_counter() - t0) * 1000
                (cold_lat if p == 0 else warm_lat).append(dt)
                if p == 0:
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

    print("\n──────── GATES (R3 flat) ────────")
    g1 = mismatches == 0 and checked > 0
    print(f"G1 CORRECTNESS  {'PASS' if g1 else 'FAIL'}  ({checked - mismatches}/{checked} identical)")
    g2 = anon_peak is not None and anon_peak < 1.0
    print(f"G2 RAM          {'PASS' if g2 else 'FAIL'}  (RssAnon peak during flat load = {anon_peak:.3f} GB; want ~0)")
    print(f"G3 LATENCY      cold p50 {pct(cold_lat,50)} / p95 {pct(cold_lat,95)} ms | "
          f"warm p50 {pct(warm_lat,50)} / p95 {pct(warm_lat,95)} ms")
    print(f"   (baseline stock p50 ≈ {min((v.get('lat_ms_p50') or 9e9) for v in base['shards'].values())} ms)")
    print(f"   VmRSS (incl page cache) peak ≈ {rss_gb():.3f} GB")
    print(f"   disk  bmp {sum(d[1] for d in disk_report):.0f}MB -> flat {sum(d[2] for d in disk_report):.0f}MB")
    print("\nVERDICT:", "GREEN — G2 cured; proceed to cold-p95 at section scale"
          if (g1 and g2) else "RED — G1/G2 not both green")


if __name__ == "__main__":
    main()
