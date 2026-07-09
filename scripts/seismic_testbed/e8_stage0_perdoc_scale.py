#!/usr/bin/env python3
"""E8 Stage-0 pre-gate: per-doc linear u8 value scale vs FixedU8Q, shards 1-2, n=100.

Roadmap: docs/seismic_150m_testbed/12_EXECUTION_ROADMAP.md Q1 (Stage 0, zero
Rust). Lineage: e6b_fixedu8_quality.py / e6_forward_codec_proto.phase_c_quality
— real engine top-k' candidates on the f16 mmap shard, re-scored in Python
under each value quantizer, overlap@10 of the re-ranked lists vs exact f16.

Quantizer models (identical to e6b):
  fixedu8 (dv v1, served): v' = clip(round(v*64), 0, 255) / 64      (global 1/64)
  perdoc  (SFR1 / dv-v2):  vmax = f16(max v);
                           v' = clip(round(v/vmax*255), 0, 255) / 255 * vmax

Bars (pre-registered, 12 Q1): perdoc overlap@10 >= fixedu8's on the same
queries AND >= 0.99 on BOTH shards -> GO (build the v2 encoder/loader);
below fixedu8 -> KILL.

Worst-case-shard rule: shards 1 and 2 (G8d's sub-gate shards), never shard0.
Rule Zero: read-only; verify with `find <shard dirs> -newermt <start>`.
"""
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import OVERLAP_K, TOP_K, K_PRIME  # noqa: E402
from stage0_candidates import gather_candidates, open_forward  # noqa: E402

SHARDS = ["global_shard1of8.mmap", "global_shard2of8.mmap"]
PLAN01 = REPO / "data/seismic_150m/index/plan01"
N_QUERIES = 100
RESULT = REPO / f"data/eval_results/e8_stage0_perdoc_scale_{time.strftime('%Y%m%d')}.json"


def dot(offs, comps, vals, row, qids, qw, mode):
    s, e = int(offs[row]), int(offs[row + 1])
    c = np.asarray(comps[s:e], dtype=np.int64)
    v = np.asarray(vals[s:e], dtype=np.float32)
    if mode == "perdoc":
        vmax = np.float32(np.float16(v.max()))
        v = np.clip(np.round(v / vmax * 255.0), 0, 255).astype(np.float32) / 255.0 * vmax
    elif mode == "fixedu8":
        v = np.clip(np.round(v * 64.0), 0, 255).astype(np.float32) / 64.0
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    return float(sum(qw[int(q)] * v[mm] for q, mm in zip(qids[ok], m[ok])))


def run_shard(name: str) -> dict:
    mmap_dir = PLAN01 / name
    per_q = gather_candidates(mmap_dir, N_QUERIES)
    offs, comps, vals = open_forward(mmap_dir)

    out = {}
    for mode in ["perdoc", "fixedu8"]:
        ov10, ov50 = [], []
        for pq in per_q:
            qids = np.array(pq["qids"], dtype=np.int64)
            exact = [dot(offs, comps, vals, r, qids, pq["qw"], "exact")
                     for r in pq["rows"]]
            quant = [dot(offs, comps, vals, r, qids, pq["qw"], mode)
                     for r in pq["rows"]]
            br = [pq["docs"][i] for i in np.argsort(-np.array(exact), kind="stable")]
            qr = [pq["docs"][i] for i in np.argsort(-np.array(quant), kind="stable")]
            ov10.append(len(set(br[:OVERLAP_K]) & set(qr[:OVERLAP_K])) / OVERLAP_K)
            ov50.append(len(set(br[:TOP_K]) & set(qr[:TOP_K])) / TOP_K)
        out[mode] = {"overlap@10_mean": round(statistics.mean(ov10), 4),
                     "overlap@10_min": round(min(ov10), 4),
                     "overlap@50_mean": round(statistics.mean(ov50), 4)}
        print(f"{name} {mode}: {out[mode]}", flush=True)
    return out


def main():
    t0 = time.time()
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/e8_stage0_perdoc_scale.py",
                    "lineage": "e6b_fixedu8_quality.py (E6 phase C method)",
                    "n_queries": N_QUERIES, "k_prime": K_PRIME,
                    "shards": SHARDS,
                    "bars": "perdoc ov@10 >= fixedu8 AND >= 0.99 on both shards -> GO; "
                            "below fixedu8 -> KILL (12_EXECUTION_ROADMAP.md Q1)"},
           "shards": {}}
    for name in SHARDS:
        res["shards"][name] = run_shard(name)

    per_ge_fixed = all(res["shards"][s]["perdoc"]["overlap@10_mean"]
                       >= res["shards"][s]["fixedu8"]["overlap@10_mean"] for s in SHARDS)
    per_ge_99 = all(res["shards"][s]["perdoc"]["overlap@10_mean"] >= 0.99 for s in SHARDS)
    res["verdict"] = {"perdoc_ge_fixedu8_both_shards": per_ge_fixed,
                      "perdoc_ge_0.99_both_shards": per_ge_99,
                      "e8_stage0": "GO" if (per_ge_fixed and per_ge_99)
                                   else ("KILL" if not per_ge_fixed else "MARGINAL")}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["verdict"]))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
