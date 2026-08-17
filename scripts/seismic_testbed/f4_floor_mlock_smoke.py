#!/usr/bin/env python3
"""F4-RESCOPED floor-mlock smoke test (2026-08-17).

Measures what `SFU_SEISMIC_MLOCK_FLOOR=1` actually locks after the 2026-08-17
rescope (`sharded_seismic_backend.mlock_structural_floor`: the posting-list
NAVIGATION runs only — block_offsets + Elias-Fano offsets + DArray inventories
— budget-capped, instead of the 2026-07-14 whole-slab pin of 1.67 GB/shard).

It is deliberately LIGHT: it loads the shards mmap-mode (lazy — no forward-data
faults), locks the budgeted floor, and reports
  - the shard's total navigation floor (bytes, from the manifest layout walk),
  - the bytes actually locked (return value of `mlock_structural_floor`),
  - the process `VmLck` delta (kernel's own accounting — the independent check),
  - wall time.
It runs NO queries and NO benchmark; pair it with
`seismic_result_parity.py` (gate OFF vs ON) for the bit-identity check.

Usage (1 shard, the 20 MB/shard default budget):

  SFU_SEISMIC_LOAD_MODE=mmap SFU_SEISMIC_MLOCK_FLOOR_MB=20 \
    .venv/bin/python3 scripts/seismic_testbed/f4_floor_mlock_smoke.py \
      --manifest /tmp/wsc_shard0_manifest.json

Full 8-shard register (160 MB total = the shipped default) — only on an idle
host: drop `--manifest` to use the served e5-v2 manifest.
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"


def _vmlck_kb() -> int:
    for ln in Path("/proc/self/status").read_text().splitlines():
        if ln.startswith("VmLck:"):
            return int(ln.split()[1])
    return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--budget-mb", type=float, default=None,
                    help="override SFU_SEISMIC_MLOCK_FLOOR_MB (total across shards)")
    ap.add_argument("--out", default=None, help="write a result JSON here")
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.path.insert(0, str(REPO / "src"))
    from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
        ParallelSeismicBackend, _postings_nav_runs)

    man = args.manifest if Path(args.manifest).is_absolute() else str(REPO / args.manifest)
    # Construct with the gate OFF (default) so the load path is the untouched
    # one, then lock explicitly — this isolates the locking cost from the load.
    sb = ParallelSeismicBackend.from_manifest(man, load_mode="mmap")
    nav_total = 0
    for d in sb._shard_mmap_dirs:
        if d:
            runs, _ = _postings_nav_runs(d)
            nav_total += sum(ln for _, ln in runs)
    lck0 = _vmlck_kb()
    t0 = time.perf_counter()
    locked = sb.mlock_structural_floor(budget_mb=args.budget_mb)
    dt = time.perf_counter() - t0
    lck1 = _vmlck_kb()
    rec = {
        "date": "2026-08-17",
        "manifest": man,
        "n_shards": len(sb.shards),
        "nav_floor_bytes_total": nav_total,
        "locked_bytes": locked,
        "vmlck_delta_bytes": (lck1 - lck0) * 1024,
        "seconds": round(dt, 2),
    }
    print(json.dumps(rec, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(rec, indent=1))
    # The kernel's accounting must agree with our byte count (±1 page/range
    # rounding is impossible here — the ranges are page-aligned by construction).
    if locked and abs((lck1 - lck0) * 1024 - locked) > 4096:
        print("FAIL: VmLck delta disagrees with the reported locked bytes")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
