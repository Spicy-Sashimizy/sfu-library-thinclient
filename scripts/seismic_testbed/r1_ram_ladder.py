#!/usr/bin/env python3
"""R1: RAM-ladder stress bench — the capped-cell driver (2026-07-14).

E7b's method (`e7b_ramcap_bench.py`, `HOST_PROMPT_E7B_RAMCAP.md`) applied to
today's serving stack: the full 8-shard E8 v2 hybrid federation, run inside an
externally memory-capped sibling container (`docker run --memory=Xg
--memory-swap=Xg`, one cell per cap) at descending caps until the thrash
floor. This process does NOT cap itself — the orchestrator wraps it.

E7b lessons kept:
  * Queries are PRE-ENCODED (reuses `e7b_encoded_queries.json`) — no torch/ORT
    inside the capped process (~1 GB anon that would eat small caps).
  * Pass 1 = cold fill; passes >=2 = the steady re-fault regime (does the
    working set fit under this cap?). No manual eviction — the cap IS the
    eviction mechanism.
  * VmSwap > 0 => the cell is swap-confounded: recorded-not-concluded
    (the G8 §A1 lesson). With --memory-swap == --memory this should stay 0.
  * Empty results => broken serving path => exit 3, never a latency record
    (the F6 lesson, 2026-07-14).

Usage (inside the capped container, from repo root):
  .venv/bin/python3 scripts/seismic_testbed/r1_ram_ladder.py \
      --cap-label 16g --passes 3 --result-file data/eval_results/r1_cap16g.json
"""
import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("r1")

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_vm() -> dict:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for k in ("VmRSS", "VmSwap", "RssFile", "RssAnon"):
            if line.startswith(k + ":"):
                out[k.lower() + "_kb"] = int(line.split()[1])
    return out


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap-label", required=True,
                    help="external cap this cell runs under (e.g. 16g) — "
                         "recorded, not enforced here")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--dump-results", default=None,
                    help="also write the LAST pass's top-10 (oaid,score) per "
                         "query to this path — for capped-vs-uncapped quality "
                         "parity (squeeze must be latency-only)")
    ap.add_argument("--release-except-hotset", action="store_true",
                    help="F5 cell: after load(+prefault), call the .so "
                         "release_pages_except(hot extents) per shard — drop "
                         "the load residue so the cache starts pre-sorted "
                         "(skips the kernel's observation passes)")
    args = ap.parse_args()

    from lib.thinclient.sharded_seismic_backend import HybridSeismicBackend

    terms = json.loads((REPO / ENCODED).read_text())["terms"][:args.queries]
    log.info("R1 cell cap=%s: %d pre-encoded queries x %d passes",
             args.cap_label, len(terms), args.passes)

    t0 = time.perf_counter()
    sb = HybridSeismicBackend.from_manifest(str(REPO / MANIFEST),
                                            load_mode="mmap")
    load_s = time.perf_counter() - t0
    log.info("loaded in %.1fs  vm=%s", load_s, read_vm())

    released_gb = 0.0
    if args.release_except_hotset:
        # F5: keep the hot-50 extents (gap-coalesced, same discipline as the
        # F6 prefault), DONTNEED the rest of each shard's forward_data.
        budget_bytes = int(1.6e9 / max(1, len(sb.shards)))
        for idx, shard_dir in zip(sb.shards, sb._shard_mmap_dirs):
            rel_fn = getattr(idx, "release_pages_except", None)
            if rel_fn is None or not shard_dir:
                continue
            sc = json.loads((Path(shard_dir) / "hotset_hot50_1.6gb.json"
                             ).read_text())
            keep, acc = [], 0
            for s, ln in sc.get("extents", []):
                nb = ln * 4096
                if acc + nb > budget_bytes and acc > 0:
                    break
                keep.append([s, ln])
                acc += nb
            gap, merged = 32, keep
            while True:
                out_m = []
                for s, ln in merged:
                    if out_m and s <= out_m[-1][0] + out_m[-1][1] + gap:
                        out_m[-1][1] = max(out_m[-1][0] + out_m[-1][1],
                                           s + ln) - out_m[-1][0]
                    else:
                        out_m.append([s, ln])
                merged = out_m
                if len(merged) <= 2048 or gap > 4096:
                    break
                gap *= 4
            freed = int(rel_fn([tuple(e) for e in merged]))
            released_gb += freed / 1e9
        log.info("F5 release_pages_except done: released %.2f GB of load "
                 "residue (hot extents kept)", released_gb)
        log.info("post-release vm=%s", read_vm())

    passes = []
    empty = 0
    last_results = {}
    for p in range(args.passes):
        lat, mf0 = [], read_majflt()
        t_pass = time.perf_counter()
        for qi, q in enumerate(terms):
            t = time.perf_counter()
            res = sb.search_encoded(q, args.top_k)
            lat.append((time.perf_counter() - t) * 1000.0)
            if not res:
                empty += 1
            if p == args.passes - 1:
                last_results[str(qi)] = [
                    [oaid, round(float(s), 6)] for oaid, s in res[:10]]
        rec = {"pass": p + 1,
               "p50_ms": round(statistics.median(lat), 2),
               "p95_ms": round(pctl(lat, 95), 2),
               "mean_ms": round(statistics.mean(lat), 2),
               "max_ms": round(max(lat), 2),
               "majflt": read_majflt() - mf0,
               "wall_s": round(time.perf_counter() - t_pass, 1),
               "vm": read_vm()}
        passes.append(rec)
        log.info("pass %d/%d: p50 %.0f ms p95 %.0f ms majflt %d wall %.0fs "
                 "swap %d kB", p + 1, args.passes, rec["p50_ms"],
                 rec["p95_ms"], rec["majflt"], rec["wall_s"],
                 rec["vm"].get("vmswap_kb", -1))

    if empty:
        log.error("%d empty results — serving path broken under this cap; "
                  "refusing to write a latency record (F6 lesson)", empty)
        sys.exit(3)

    swap_kb = max(p["vm"].get("vmswap_kb", 0) for p in passes)
    out = {"probe": "r1_ram_ladder", "date": time.strftime("%Y-%m-%d"),
           "cap": args.cap_label, "manifest": MANIFEST,
           "queries": len(terms), "passes": args.passes,
           "top_k": args.top_k, "load_s": round(load_s, 1),
           "prefault_gate": __import__("os").environ.get(
               "SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
           "per_pass": passes,
           "steady": {  # passes >= 2 pooled — the sustained regime
               "p50_ms": round(statistics.median(
                   [x for p in passes[1:] for x in [p["p50_ms"]]]), 2),
               "p95_ms": round(max(p["p95_ms"] for p in passes[1:]), 2),
               "majflt_per_pass": round(statistics.mean(
                   [p["majflt"] for p in passes[1:]]), 0),
           } if len(passes) > 1 else None,
           "pin_budget_gb": __import__("os").environ.get(
               "SFU_SEISMIC_PIN_BUDGET_GB", "0"),
           "hotset_pinned_gb": round(getattr(sb, "_hotset_pinned_gb", 0.0), 3),
           "release_except_hotset": args.release_except_hotset,
           "released_gb": round(released_gb, 3),
           "swap_confounded": swap_kb > 0,
           "vmswap_kb_max": swap_kb}
    Path(args.result_file).write_text(json.dumps(out, indent=2))
    log.info("wrote %s%s", args.result_file,
             "  ** SWAP-CONFOUNDED **" if swap_kb else "")
    if args.dump_results:
        Path(args.dump_results).write_text(json.dumps(last_results, indent=1))
        log.info("dumped last-pass top-10 results -> %s", args.dump_results)


if __name__ == "__main__":
    main()
