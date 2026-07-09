#!/usr/bin/env python3
"""M7 Stage-0 sim: query-hits per 8-lane pack on real candidate sets (lane accounting).

Roadmap: docs/seismic_150m_testbed/12_EXECUTION_ROADMAP.md Q2; candidate spec
docs/math_optimization/08_FURTHER_MATH_CANDIDATES.md §M7. Decides GO/KILL on
moving the query-membership test BEFORE the gather.

Kernel model (dotvbyte_fixedu8.rs `push_vector` / `DotVbyteFixedu8`): a doc's
component ids are term-sorted, the first n - n%8 ids are processed in 8-lane
SIMD packs (N = u8::BITS = 8), the n%8 tail goes through the scalar remainder
path (bytes_remaining/values_remaining) which M7's pack-skip cannot elide.
The dv converter preserves f16 component order byte-exact (its sanity check
asserts decoded components == f16 source), so the f16 forward is an exact
proxy for dv pack composition.

Per scored (query, doc) pair — the engine's returned top-k' per query, the
same scoring-side proxy as the 06 zero-gather inventory — we chunk the doc's
sorted ids into 8-lane packs and count how many lanes hit the query id set.

Bars (pre-registered, 08 §M7): all-miss-pack rate >= 0.5 -> GO (Rust spike);
< 0.3 -> KILL; between -> build only the bitmap-gather variant.

Sanity anchor: per-lane zero rate should land near the 06 inventory's 76.7%
(that ran shard0 n=40; this runs shards 1-2 n=100, so drift is expected but
should be same-order). Rule Zero: read-only over the shard dirs.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import K_PRIME  # noqa: E402
from stage0_candidates import gather_candidates, open_forward  # noqa: E402

SHARDS = ["global_shard1of8.mmap", "global_shard2of8.mmap"]
PLAN01 = REPO / "data/seismic_150m/index/plan01"
N_QUERIES = 100
LANES = 8  # N = u8::BITS in dotvbyte_fixedu8.rs
RESULT = REPO / f"data/eval_results/m7_pack_membership_sim_{time.strftime('%Y%m%d')}.json"


def run_shard(name: str) -> dict:
    mmap_dir = PLAN01 / name
    per_q = gather_candidates(mmap_dir, N_QUERIES)
    offs, comps, vals = open_forward(mmap_dir)

    hist = np.zeros(LANES + 1, dtype=np.int64)   # query-hits per full pack
    total_packs = all_miss_packs = 0
    tail_lanes = tail_zero = 0
    total_slots = zero_slots = 0                 # per-lane, incl. tail (06 anchor)
    scored_pairs = 0

    for pq in per_q:
        qids = np.array(pq["qids"], dtype=np.int64)
        for row in pq["rows"]:
            s, e = int(offs[row]), int(offs[row + 1])
            c = np.asarray(comps[s:e], dtype=np.int64)
            m = np.searchsorted(qids, c)
            hit = (m < len(qids)) & (qids[np.minimum(m, len(qids) - 1)] == c)

            n = len(c)
            n_full = n - n % LANES
            packs = hit[:n_full].reshape(-1, LANES)
            hits_per_pack = packs.sum(axis=1)
            hist += np.bincount(hits_per_pack, minlength=LANES + 1)
            total_packs += len(packs)
            all_miss_packs += int((hits_per_pack == 0).sum())
            tail = hit[n_full:]
            tail_lanes += len(tail)
            tail_zero += int((~tail).sum())
            total_slots += n
            zero_slots += int(n - hit.sum())
            scored_pairs += 1

    return {"scored_query_doc_pairs": scored_pairs,
            "total_full_packs": int(total_packs),
            "all_miss_pack_rate": round(all_miss_packs / total_packs, 4),
            "hits_per_pack_hist": {str(i): int(hist[i]) for i in range(LANES + 1)},
            "tail_lane_fraction": round(tail_lanes / total_slots, 4),
            "tail_zero_rate": round(tail_zero / tail_lanes, 4) if tail_lanes else None,
            "per_lane_zero_rate_all_slots": round(zero_slots / total_slots, 4),
            "skippable_slot_fraction": round(all_miss_packs * LANES / total_slots, 4)}


def main():
    t0 = time.time()
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/m7_pack_membership_sim.py",
                    "n_queries": N_QUERIES, "k_prime": K_PRIME, "lanes": LANES,
                    "shards": SHARDS,
                    "candidate_proxy": "engine returned top-k' per query (06 convention); "
                                       "traversal-scored non-returned candidates not captured",
                    "bars": "all-miss-pack rate >=0.5 GO / <0.3 KILL / between -> "
                            "bitmap-gather variant only (08 §M7)"},
           "shards": {}}
    for name in SHARDS:
        res["shards"][name] = run_shard(name)
        print(f"{name}: {json.dumps(res['shards'][name])}", flush=True)

    packs = sum(res["shards"][s]["total_full_packs"] for s in SHARDS)
    miss = sum(round(res["shards"][s]["all_miss_pack_rate"]
                     * res["shards"][s]["total_full_packs"]) for s in SHARDS)
    rate = miss / packs
    res["combined_all_miss_pack_rate"] = round(rate, 4)
    res["verdict"] = {"m7_stage0": "GO" if rate >= 0.5
                      else ("KILL" if rate < 0.3 else "BITMAP_GATHER_ONLY")}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps({"combined_all_miss_pack_rate": res["combined_all_miss_pack_rate"],
                      **res["verdict"]}))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
