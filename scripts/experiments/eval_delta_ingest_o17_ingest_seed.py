#!/usr/bin/env python3
"""O17 option (a), ingest side: does the base is_oa bitmap stop is_oa-only
differences from forcing an in-base delta copy?

Same inputs and slice rule as the M7-seed run (eval_delta_ingest_m7_seed.py,
data/eval_results/delta_ingest_M7seed_20260930.json): the M7 primary
partition (updated_date=2026-09-15 part_0001), min_year=2015 and 2010 arms,
seed set = in-slice in-base ids in social_sciences__recent (the one section
with a local abstract sidecar). Two fresh ledgers, seeded with
`BaseSeeder(oa_overlay=False)` (pre-bitmap behaviour) and with the bitmap given
by --bitmap; every in-slice record is classified against each; reported per
arm: updated / unchanged on the seeded subset, content-only updates and their
field attribution. Expectation (design, not pre-registered as a bar): the
is_oa-only combo goes to ~0 with the bitmap; any residue is reported.

Run:
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_o17_ingest_seed.py \
      --bitmap /home/vscode/work/delta_ingest/oa/bitmap --out <json>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import eval_delta_ingest_m7_seed as m7  # noqa: E402

from lib.thinclient.oa_overlay import OAOverlay  # noqa: E402
from spike.delta_ingest.base import BaseIndex  # noqa: E402
from spike.delta_ingest.seed import BaseSeeder, resolve_meta  # noqa: E402

WORK = Path("/home/vscode/work/delta_ingest/oa/ingest")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bitmap", required=True)
    ap.add_argument("--index-root", default=str(m7.REPO_ROOT / "data" / "thinclient_index"))
    ap.add_argument("--part", default="primary")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    index_root = Path(args.index_root)
    meta_path = resolve_meta(index_root)
    overlay = OAOverlay(args.bitmap, meta_path=index_root / "meta.sqlite")
    path, ref = m7.PARTS[args.part]
    meta_db = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True, timeout=60)
    base = BaseIndex(index_root)
    t0 = time.time()
    p1 = m7.pass1(path, base, meta_db)
    seed_ids = sorted(w for w, r in p1["rows"].items() if r[6] == m7.HOT)
    states = overlay.states(seed_ids)
    out = {"date": "2026-10-01",
           "script": str(Path(__file__).relative_to(m7.REPO_ROOT)),
           "git_commit_at_run": subprocess.check_output(
               ["git", "-C", str(m7.REPO_ROOT), "rev-parse", "HEAD"], text=True).strip(),
           "file": path, "bitmap": str(args.bitmap), "bitmap_id": overlay.bitmap_id,
           "bitmap_coverage": overlay.stamp.get("coverage"),
           "bitmap_source": overlay.stamp.get("source"),
           "seed_set": len(seed_ids),
           "seed_set_bitmap_states": {"oa": sum(s is True for s in states),
                                      "not_oa": sum(s is False for s in states),
                                      "unknown": sum(s is None for s in states)},
           "m7seed_reference": ref, "timings_valid": False, "arms": {}}
    for tag, ov in (("bitmap_off", False), ("bitmap_on", overlay)):
        led = m7.fresh(WORK / f"ledger_{args.part}_{tag}.sqlite")
        seeder = BaseSeeder(index_root, led, meta_path=meta_path, oa_overlay=ov)
        rep = seeder.seed_ids(seed_ids)
        base_recs = {r.id: r for r in seeder.records_for_rows([p1["rows"][w] for w in seed_ids])}
        seeder.close()
        seeded = set(seed_ids)
        out["arms"][tag] = {"seed_stats": rep["stats"],
                            "classify": {str(my): m7.classify_arm(path, my, p1, led, seeded, base_recs)
                                         for my in (2015, 2010)}}
        led.close()
    for my in ("2015", "2010"):
        a = out["arms"]["bitmap_off"]["classify"][my]
        b = out["arms"]["bitmap_on"]["classify"][my]
        out[f"summary_min_year_{my}"] = {
            "seeded_updated": [a["seeded_subset"].get("updated", 0), b["seeded_subset"].get("updated", 0)],
            "seeded_unchanged": [a["seeded_subset"].get("unchanged", 0), b["seeded_subset"].get("unchanged", 0)],
            "seeded_content_only_updates": [a["seeded_subset"].get("updated_content_only", 0),
                                            b["seeded_subset"].get("updated_content_only", 0)],
            "content_only_combo_is_oa": [a["content_only_field_attribution"].get("content_only_combo:is_oa", 0),
                                         b["content_only_field_attribution"].get("content_only_combo:is_oa", 0)],
            "content_only_is_oa_differs": [a["content_only_field_attribution"].get("content_only_is_oa_differs", 0),
                                           b["content_only_field_attribution"].get("content_only_is_oa_differs", 0)],
            "order": "[bitmap_off, bitmap_on]"}
    out["wall_s"] = round(time.time() - t0, 1)
    Path(args.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k.startswith("summary") or k.startswith("seed_set")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
