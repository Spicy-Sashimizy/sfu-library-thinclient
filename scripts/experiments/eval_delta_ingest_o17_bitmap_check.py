#!/usr/bin/env python3
"""O17 (a): check the assembled is_oa bitmap against the raw scan unit files
through the SERVING read path (W-id -> OAOverlay.states), and, optionally,
check every OA-filtered id returned by the gate-on eval arm.

Raw truth = the per-partition unit files (ordinal, is_oa) written by the scan
(regex == json.loads on 464,260 works of two partitions, findings §2.1).
Usage:
  python eval_delta_ingest_o17_bitmap_check.py --bitmap B --work W [--sample N]
         [--rows on.rows.jsonl] --out J
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from lib.thinclient.oa_overlay import OAOverlay  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bitmap", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--meta", default=str(REPO / "data/thinclient_index/meta.sqlite"))
    ap.add_argument("--sample", type=int, default=100000)
    ap.add_argument("--rows", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    ov = OAOverlay(a.bitmap, meta_path=a.meta)
    n = ov.rows
    known = np.zeros(n, np.uint8)
    oa = np.zeros(n, np.uint8)
    for p in sorted(Path(a.work, "units").glob("*.npz")):
        with np.load(p) as z:
            known[z["ord"]] = 1
            oa[z["ord"]] = z["oa"]
    rng = np.random.default_rng(20261001)
    ords = rng.choice(n, size=a.sample, replace=False)
    ids = [f"W{int(ov.wids[o])}" for o in ords]
    st = ov.states(ids)
    truth = [None if not known[o] else bool(oa[o]) for o in ords]
    agree = sum(s == t for s, t in zip(st, truth))
    res = {"date": "2026-10-01", "bitmap_id": ov.bitmap_id, "coverage": ov.stamp["coverage"],
           "random_base_sample": {"n": a.sample, "agree": agree,
                                  "known_oa": sum(t is True for t in truth),
                                  "known_not_oa": sum(t is False for t in truth),
                                  "unknown": sum(t is None for t in truth)},
           "raw_units_totals": {"known": int(known.sum()), "oa": int((oa & known).sum())}}
    if a.rows and Path(a.rows).exists():
        ret, bad, notbase = 0, [], 0
        for ln in open(a.rows):
            r = json.loads(ln)
            for d in r["fused_oa_ids"]:
                ret += 1
                pos, found = ov.lookup([d])
                if not found[0]:
                    notbase += 1
                elif not (known[pos[0]] and oa[pos[0]]):
                    bad.append(d)
        res["gate_on_returned_oa"] = {"returned": ret, "not_base": notbase,
                                      "base_known_oa_in_scan": ret - notbase - len(bad),
                                      "disagree": bad[:50], "disagree_n": len(bad)}
    res["wall_s"] = round(time.time() - t0, 1)
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
