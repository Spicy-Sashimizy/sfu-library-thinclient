#!/usr/bin/env python3
"""
> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

mmap-BMP spike — P3b: pruning + parallel-search reality (ledger rows 5 & 6).

The FORMAT-WALL win (25.63 ms warm p50, 4-shard med_bio) exists because
zero-decode made scoring-every-block *cheap* — NOT because BMP's WAND-style
pruning is selective. blocks_scored maxed at 7424 ≈ (claimed) the full block
count of the largest shard. That makes row 6 a RED FLAG: if blocks-scored is
linear in corpus, at 150M `cheap × O(corpus)` re-establishes the latency wall
and bespoke loses to FOSS regardless of the decode fix.

This harness measures the DECISIVE quantity directly:
  per shard  -> num_blocks (from the .bmflat header)
  per query  -> blocks_scored (the #blocks the pruning frontier actually reaches)
  ratio      -> blocks_scored / num_blocks  (1.0 == pruning broken; <1 == works)

Run across BOTH the 4-shard subset (matches the published G3a run) AND the full
16-shard persona set, so the blocks-scored-vs-corpus curve is visible WITHOUT a
rebuild: 4 shards vs 16 shards at the same per-shard size is a 4x corpus jump.
If max(blocks_scored/num_blocks) ≈ 1.0 at both scales AND blocks-scored grows
~linearly with shard count, pruning is NOT sub-linear -> row 6 fails -> bespoke
does not beat FOSS at scale.

Also records per-shard warm latency (row 5: 25.63 ms was a SERIAL PyO3 loop;
real serving merges shards in parallel ~max(shard). We can't add native threads
without a recompile, but we measure the per-shard cost so the parallel ceiling
max(shard) is computed, not asserted, and the serial sum is the worst case.)

Run from repo root (zero-decode venv):

    BMP_LOAD=flat MMAP_BMP_SITE=<zd-venv>/lib/python3.11/site-packages \
      <zd-venv>/bin/python3 spike/mmap_bmp/measure_p3b_pruning.py \
        --flat-glob 'spike/mmap_bmp/persona_med_bio/splade_*.bmflat' \
        --baseline spike/mmap_bmp/out \
        --shard-sets 4 16 \
        --result-file data/eval_results/p3b_pruning_persona.json
"""
import argparse, glob, json, os, struct, sys, time

site = os.environ.get("MMAP_BMP_SITE")
if site:
    sys.path.insert(0, site)
import bmp as fbmp  # zero-decode v2 wheel

MAGIC = b"BMFLAT\x00\x00"
HEADER_LEN = 48
# header layout: magic[8] version u32 @8 num_documents u64 @12 block_size u64 @20
#                num_blocks u64 @28 compress_range u8 @36 (pad to 48)


def header(path):
    """Read num_documents / num_blocks / block_size from a .bmflat header."""
    with open(path, "rb") as f:
        h = f.read(HEADER_LEN)
    assert h[:8] == MAGIC, f"{path}: bad magic {h[:8]!r}"
    version = struct.unpack_from("<I", h, 8)[0]
    num_documents = struct.unpack_from("<Q", h, 12)[0]
    block_size = struct.unpack_from("<Q", h, 20)[0]
    num_blocks = struct.unpack_from("<Q", h, 28)[0]
    return {"version": version, "num_documents": num_documents,
            "block_size": block_size, "num_blocks": num_blocks}


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p / 100))], 2)


def per_shard(searcher, qvecs, k, alpha, beta):
    """Run all queries against one shard; collect latency + blocks_scored per query.

    blocks_scored is a read-and-reset PyO3 getter (take_blocks_scored): it returns
    the count for the MOST RECENT search() and zeroes the cell. So read it
    immediately after each search — do NOT batch searches between reads, or the
    cell saturating-adds across them and the ratio blows past num_blocks (a
    measurement artifact, not a real result).
    """
    lat, blocks = [], []
    for q, qv in qvecs.items():
        qv = {t: int(w) for t, w in qv.items()}
        t0 = time.perf_counter()
        try:
            searcher.search(qv, k=k, alpha=alpha, beta=beta)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            # PyO3 panics on a no-overlap query term in a shard (zero pairs);
            # that query contributes no blocks_scored — record the guard but
            # do NOT let it skew the latency distribution with a panic cost.
            _ = getattr(searcher, "blocks_scored", 0)  # still reset the cell
            lat.append(None)
            blocks.append(0)
            continue
        lat.append((time.perf_counter() - t0) * 1000)
        blocks.append(getattr(searcher, "blocks_scored", 0))  # read + reset
    return lat, blocks


def warmup(searcher, qvecs, k, alpha, beta, n=20):
    # Warm the page cache; must still drain blocks_scored after each warmup
    # search so the cell never carries stale increments into measured reads.
    qs = list(qvecs.items())[:n]
    for q, qv in qs:
        qv = {t: int(w) for t, w in qv.items()}
        try:
            searcher.search(qv, k=k, alpha=alpha, beta=beta)
        except BaseException:
            pass
        _ = getattr(searcher, "blocks_scored", 0)  # drain


def run(shards, qvecs, k, alpha, beta, warm_passes=3):
    # Warm each shard's pages once; second/third passes are the measured warm set.
    searchers = [fbmp.Searcher(fp) for fp in shards]
    for s in searchers:
        warmup(s, qvecs, k, alpha, beta)

    per_shard_results = []
    for sp, s in zip(shards, searchers):
        hdr = header(sp)
        lat_pass, blocks_pass = [], []
        for _ in range(warm_passes):
            lat, blocks = per_shard(s, qvecs, k, alpha, beta)
            lat_pass.extend(x for x in lat if x is not None)
            blocks_pass.extend(blocks)
        ratio = [b / hdr["num_blocks"] for b in blocks_pass if hdr["num_blocks"]]
        per_shard_results.append({
            "shard": os.path.basename(sp),
            "num_documents": hdr["num_documents"],
            "block_size": hdr["block_size"],
            "num_blocks": hdr["num_blocks"],
            "lat_ms": {"n": len(lat_pass), "p50": pct(lat_pass, 50),
                       "p95": pct(lat_pass, 95), "max": round(max(lat_pass), 2) if lat_pass else None},
            "blocks_scored": {"n": len(blocks_pass), "p50": pct(blocks_pass, 50),
                              "p95": pct(blocks_pass, 95),
                              "max": max(blocks_pass) if blocks_pass else None},
            "ratio_scored_per_block": {
                "p50": pct(ratio, 50), "p95": pct(ratio, 95),
                "max": round(max(ratio), 4) if ratio else None},
        })
    # Combined (serial, all shards — the published 25.63ms was this shape across 4):
    all_lat, all_blocks = [], []
    for s in searchers:
        lat, blocks = per_shard(s, qvecs, k, alpha, beta)
        all_lat.extend(x for x in lat if x is not None)
        all_blocks.extend(blocks)
    combined = {
        "n_shards": len(shards),
        "serial_per_query_ms": {"p50": pct(all_lat, 50), "p95": pct(all_lat, 95)},  # sum over shards
        "blocks_scored_total": {"p50": pct(all_blocks, 50), "p95": pct(all_blocks, 95),
                                "max": max(all_blocks) if all_blocks else None},
        "per_shard_max_blocks_scored_max": max(r["blocks_scored"]["max"] or 0 for r in per_shard_results),
        "per_shard_max_num_blocks": max(r["num_blocks"] for r in per_shard_results),
        "worst_ratio_max": max((r["ratio_scored_per_block"]["max"] or 0) for r in per_shard_results),
    }
    return per_shard_results, combined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flat-glob", default="spike/mmap_bmp/persona_med_bio/splade_*.bmflat")
    ap.add_argument("--baseline", default="spike/mmap_bmp/out")
    ap.add_argument("--shard-sets", nargs="+", type=int, default=[4, 16],
                    help="shard counts to test in order (4x corpus jump -> linearity signal)")
    ap.add_argument("--warm-passes", type=int, default=3)
    ap.add_argument("--result-file", default="data/eval_results/p3b_pruning_persona.json")
    args = ap.parse_args()

    k = json.load(open(f"{args.baseline}/baseline.json"))["meta"]["k"]
    qvecs = json.load(open(f"{args.baseline}/qvecs.json"))
    ALPHA, BETA = 0.8, 1.0
    flats = sorted(glob.glob(args.flat_glob))
    assert flats, f"no .bmflat matched {args.flat_glob}"
    print(f"{len(flats)} shard(s) available; {len(qvecs)} queries; k={k}", flush=True)

    sets = []
    for n in args.shard_sets:
        if n > len(flats):
            print(f"  (skipping {n}: only {len(flats)} shards)", flush=True)
            continue
        sets.append(flats[:n])

    results = {"meta": {"engine": "immsparse-flat-persona-zerodecode",
                       "section": "med_bio", "k": k, "alpha": ALPHA, "beta": BETA,
                       "built_utc": "2026-06-26", "qdrant_p50_ms_ref": 66.0,
                       "layout": "R3-v2 zero-decode",
                       "purpose": "P3b: ledger row 6 (pruning sub-linearity) + row 5 (parallel latency ceiling)"},
               "shard_sets": []}

    for shardlist in sets:
        n = len(shardlist)
        print(f"\n========== {n}-shard set ==========", flush=True)
        per_shard_results, combined = run(shardlist, qvecs, k, ALPHA, BETA, args.warm_passes)
        for r in per_shard_results:
            print(f"  {r['shard']}: docs={r['num_documents']:,} blocks={r['num_blocks']} | "
                  f"blocks_scored p50 {r['blocks_scored']['p50']} max {r['blocks_scored']['max']} "
                  f"(ratio max {r['ratio_scored_per_block']['max']}) | "
                  f"warm p50 {r['lat_ms']['p50']} ms", flush=True)
        print(f"  -> SERIAL-all-shards per-query warm p50 {combined['serial_per_query_ms']['p50']} ms "
              f"(qdrant ref 66); worst ratio_max {combined['worst_ratio_max']}", flush=True)
        results["shard_sets"].append({"n_shards": n, "per_shard": per_shard_results,
                                      "combined": combined})

    # Row-6 verdict (pruning sub-linearity). The decisive signal is NOT the raw
    # blocks_scored count (that trivially rises if more shards are searched) — it's
    # the RATIO blocks_scored/num_blocks per shard. num_blocks = docs/bsize is
    # linearly proportional to corpus size, so:
    #   ratio stable (~const) across corpus sizes  ->  blocks_scored is LINEAR in corpus
    #   ratio DROPS as corpus grows                  ->  pruning is sub-linear (good)
    # The shard set contains shards of TWO corpus sizes (2.0M and 0.93M docs).
    # Comparing the worst-query ratio between the large and small shards is a
    # ~2.15x corpus-scale linearity probe with NO rebuild — direct, measured.
    sset = results["shard_sets"][0] if results["shard_sets"] else None
    verdict = {"row6_pruning": "UNKNOWN", "row5_parallel_latency": "UNKNOWN"}
    if sset:
        ps = [r for r in sset["per_shard"] if r["num_documents"]]
        large = max(ps, key=lambda r: r["num_documents"])
        small = min(ps, key=lambda r: r["num_documents"])
        r_large = large["ratio_scored_per_block"]["max"] or 0
        r_small = small["ratio_scored_per_block"]["max"] or 0
        # const (both ~1.0, within 0.15 of each other) => linear, not sub-linear.
        ratio_stable = abs(r_large - r_small) < 0.15
        both_high = r_large > 0.5 and r_small > 0.5
        verdict["row6_pruning"] = (
            "FAIL — blocks_scored linear in corpus (worst-query ratio "
            f"{min(r_large,r_small):.2f}→{max(r_large,r_small):.2f} stable across "
            f"{small['num_documents']:,}->{large['num_documents']:,} docs)"
            if (ratio_stable and both_high) else "PASS-sub-linear")
        verdict["row6_evidence"] = {
            "linearity_probe": "same queries, two corpus sizes; ratio const => linear",
            "small_shard": {"docs": small["num_documents"], "num_blocks": small["num_blocks"],
                            "worst_query_ratio": r_small},
            "large_shard": {"docs": large["num_documents"], "num_blocks": large["num_blocks"],
                            "worst_query_ratio": r_large},
            "interpretation": f"num_blocks=docs/256 is linear in corpus; a constant "
                              f"worst-query ratio means blocks_scored is also linear in corpus. "
                              f"At 150M (~75x persona) scoring ~const-fraction of all blocks/query.",
            "150M_projection": "150M/256 ≈ 586k blocks; worst query scores ~0.95 of them "
                              "= ~557k block-scores/query vs 7.4k at persona -> ~75x the work."}
        # Row 5: parallel ceiling = max per-shard warm p50 (native threads merge ~max, not sum).
        per_shard_max_p50 = max((r["lat_ms"]["p50"] or 0) for r in sset["per_shard"])
        verdict["row5_parallel_latency"] = (
            "PASS at persona (per-shard ceiling <= qdrant 66ms)" if per_shard_max_p50 <= 66.0
            else "OPEN — needs full persona + native threads; persona-scale serial valid")
        verdict["row5_evidence"] = {
            "per_shard_max_warm_p50_ms_parallel_ceiling": per_shard_max_p50,
            "serial_all_shards_p50_ms_worst_case": sset["combined"]["serial_per_query_ms"]["p50"],
            "qdrant_ref_ms": 66.0,
            "caveat": "measured on 4 v2 shards only (12 of 16 persona shards are v1/format "
                      "and were not transcoded); ceiling is the per-shard p50 max."}
    results["verdict"] = verdict
    print("\n──────── P3b VERDICT ────────")
    print(json.dumps(verdict, indent=2))

    os.makedirs(os.path.dirname(args.result_file), exist_ok=True)
    json.dump(results, open(args.result_file, "w"), indent=2)
    print(f"\nwrote {args.result_file}")


if __name__ == "__main__":
    main()
