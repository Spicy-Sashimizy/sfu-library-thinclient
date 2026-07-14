#!/usr/bin/env python3
"""Result-parity harness: assert two serving configurations return IDENTICAL
results (top-k ids + scores). The no-silent-breakage contract for
residency-only levers (mlock/prefault/release — doc 03 §5 step 5), promoted
from the F6 corrections pass (2026-07-14).

Residency-only levers are bit-identical *by construction* — assert it anyway:
the invalid F6 "cold p95 30 ms" record happened precisely because a
"can't-affect-results" gate broke the serving path in three ways (encoder
ImportError, VMA-table saturation, dead parallel arm) and nothing checked the
results. See `11_EXPERIMENT_BACKLOG.md` F6 CORRECTION + fix commit 2203d9b.

Because env gates (SFU_SEISMIC_*) are read at backend __init__, each arm runs
in its own process:

  # arm A (e.g. lever OFF)
  SFU_SEISMIC_LOAD_MODE=mmap \
    python3 scripts/seismic_testbed/seismic_result_parity.py capture /tmp/off.json
  # arm B (e.g. lever ON)
  SFU_SEISMIC_LOAD_MODE=mmap SFU_SEISMIC_PREFLOOR_HOTSET=1 \
    python3 scripts/seismic_testbed/seismic_result_parity.py capture /tmp/on.json
  # compare (exit 0 = parity, exit 1 = mismatch)
  python3 scripts/seismic_testbed/seismic_result_parity.py compare /tmp/off.json /tmp/on.json

Options: --queries N (default 10), --top-k K (default 10), --manifest PATH,
--backend hybrid|parallel (default hybrid). Queries come from
`data/eval_results/diverse_queries.json` (paraphrase field), same source as
the q7 bench.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"


def capture(args) -> None:
    sys.path.insert(0, str(REPO / "src"))
    from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
        HybridSeismicBackend, ParallelSeismicBackend)
    cls = {"hybrid": HybridSeismicBackend,
           "parallel": ParallelSeismicBackend}[args.backend]
    qrecs = json.loads((REPO / "data" / "eval_results" /
                        "diverse_queries.json").read_text())
    queries = [r["paraphrase"] for r in qrecs][:args.queries]
    sb = cls.from_manifest(str(REPO / args.manifest), load_mode="mmap")
    out = {}
    for q in queries:
        res = sb.search(q, args.top_k)
        out[q] = [[oaid, round(float(score), 6)] for oaid, score in res]
        if not out[q]:
            print("FATAL: empty result for %r — serving path broken, "
                  "capture is not a valid parity arm" % q[:60])
            sys.exit(2)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("captured %d queries (top-%d) -> %s"
          % (len(out), args.top_k, args.out))


def compare(args) -> None:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())
    if a.keys() != b.keys():
        print("FATAL: query sets differ between arms")
        sys.exit(1)
    mismatches = 0
    for q in a:
        if a[q] != b[q]:
            mismatches += 1
            print("MISMATCH: %r" % q[:60])
            print("  A:", [x[0] for x in a[q]][:5], [x[1] for x in a[q]][:3])
            print("  B:", [x[0] for x in b[q]][:5], [x[1] for x in b[q]][:3])
    print("PARITY: %d/%d identical (ids+scores)" % (len(a) - mismatches, len(a)))
    sys.exit(1 if mismatches else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="run one arm, write results JSON")
    cap.add_argument("out")
    cap.add_argument("--queries", type=int, default=10)
    cap.add_argument("--top-k", type=int, default=10)
    cap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    cap.add_argument("--backend", choices=("hybrid", "parallel"),
                     default="hybrid")
    cmp_ = sub.add_parser("compare", help="diff two capture files")
    cmp_.add_argument("a")
    cmp_.add_argument("b")
    args = ap.parse_args()
    capture(args) if args.cmd == "capture" else compare(args)


if __name__ == "__main__":
    main()
