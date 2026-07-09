#!/usr/bin/env python3
"""E5 — derive a forward-reorder permutation file for `reorder_mmap_shard`.

Writes perm.bin (u64[n_docs] native-endian, perm[new_row] = old_row) for one
shard + ordering method, using the EXACT Q6/Q6b machinery that measured the
ordering's simulated win — then re-computes the unique-page ratio of the
derived perm on the cached candidate sets as a cross-check that the converter
input IS the measured cell (printed, and refused if it drifts >0.005 from a
supplied --expect-ratio).

Usage:
  .venv/bin/python3 scripts/seismic_testbed/e5_derive_order.py \
      --shard global_shard1of8 [--order block_walk_canonical] \
      [--expect-ratio 0.376]

Output: data/seismic_150m/index/plan01/e5_perms/<shard>.<order>.perm.bin
Rule Zero: read-only over the shard dirs; perms land in a NEW subdir.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from q6_e5_coaccess_sim import (  # noqa: E402
    PLAN01, N_QUERIES, capture_visited, first_touch_perm, newoff_for_perm,
    eval_perm)
from q6b_order_sweep import walk_pack_rows_per_list  # noqa: E402

PERM_DIR = PLAN01 / "e5_perms"


def derive(shard: str, order: str) -> tuple[np.ndarray, Path]:
    f16_dir = PLAN01 / f"{shard}.mmap"
    offs64 = np.memmap(f16_dir / "forward_offsets.bin", dtype=np.uint64,
                       mode="r").astype(np.uint64)
    n_docs = len(offs64) - 1
    if order == "block_walk_canonical":
        per_list = walk_pack_rows_per_list(f16_dir, offs64)
        walk = np.concatenate(per_list)
        perm = first_touch_perm(walk, n_docs)
    else:
        raise SystemExit(f"unknown order {order!r} — only the Q6b-chosen "
                         f"block_walk_canonical is derivable (add others only "
                         f"with a measured sim cell)")
    assert len(perm) == n_docs and len(np.unique(perm)) == n_docs, "not a bijection"
    PERM_DIR.mkdir(exist_ok=True)
    out = PERM_DIR / f"{shard}.{order}.perm.bin"
    perm.astype(np.uint64).tofile(out)
    return perm, out


def crosscheck_ratio(shard: str, perm: np.ndarray) -> float:
    f16_dir = PLAN01 / f"{shard}.mmap"
    per_q = capture_visited(shard)
    lens = np.diff(np.memmap(f16_dir / "forward_offsets.bin", dtype=np.uint64,
                             mode="r").astype(np.int64))
    all_idx = list(range(N_QUERIES))
    bp, _ = eval_perm(per_q, newoff_for_perm(
        np.arange(len(lens), dtype=np.int64), lens), lens, 2, all_idx)
    pages, _ = eval_perm(per_q, newoff_for_perm(
        perm.astype(np.int64), lens), lens, 2, all_idx)
    return float(pages.sum() / bp.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True)
    ap.add_argument("--order", default="block_walk_canonical")
    ap.add_argument("--expect-ratio", type=float, default=None)
    args = ap.parse_args()

    t0 = time.time()
    perm, out = derive(args.shard, args.order)
    report = {"shard": args.shard, "order": args.order,
              "perm_file": str(out), "n_docs": int(len(perm)),
              "wall_seconds": round(time.time() - t0, 1)}
    # The page-ratio crosscheck needs a cached/generated candidate set — only
    # meaningful for the simulated shards (1,2). Run it only when a target
    # ratio is supplied; otherwise the perm's correctness rests on the
    # converter's byte-verify + parity gate, and its efficacy on the
    # shard-independent block-co-access mechanism (Q6b, both shards ~0.39).
    if args.expect_ratio is not None:
        ratio = crosscheck_ratio(args.shard, perm)
        report["crosscheck_page_ratio"] = round(ratio, 4)
        if abs(ratio - args.expect_ratio) > 0.005:
            report["verdict"] = "RATIO_DRIFT — perm does not reproduce the sim cell"
            print(json.dumps(report, indent=2))
            raise SystemExit(1)
    report["verdict"] = "OK"
    report["wall_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
