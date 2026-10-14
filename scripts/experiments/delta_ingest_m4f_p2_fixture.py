#!/usr/bin/env python3
"""09 P2 fixture: corpus (a) re-laid-out with a 09 L2 generation layout.

docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md section 6 P2 asks for the
M3 re-check "on a corpus (a) fixture built with that layout". Corpus (a) is
the M2 agent's fixture (/home/vscode/work/delta_ingest/corpus_a/, READY.json;
one generation g0001 of 50,000 updated `social_sciences__recent` docs, a
livedocs bitset masking their base ordinals). It is READ-ONLY here.

This script builds a NEW root /home/vscode/work/delta_ingest/BUILD/corpus_a_<layout>/root:
  1. ledger.sqlite = sqlite backup of the fixture ledger (opened read-only);
     buffer/ = copy of the fixture's empty-but-present buffer section;
  2. g0001 rebuilt by `generation.build_generation(..., layout=<layout>,
     seismic_from=<fixture g0001>)` from the ledger's stored records of
     generation 1 (the same 50,000 records the fixture froze): tantivy
     sections + abstract sidecars + meta.sqlite in the new layout, the SEISMIC
     dir copied byte-identical (doc-id set asserted) -- L2 does not touch
     SEISMIC, so no GPU and no re-encode;
  3. `generation.publish` with the frozen M4 base manifest and the fixture's
     ordinal dir (livedocs bitset rebuilt the same way the fixture's was);
  4. verify: one generation of 50,000 docs, the expected section names, the
     livedocs popcount / superseded / deleted counts equal the fixture's,
     every copied SEISMIC file `cmp`-identical to the fixture's;
  5. READY.json next to the root in the fixture's schema (root and gate-on
     SFU_DELTA_ROOT repointed; ids / title sample paths unchanged), so the
     M3 harness runs on it with `--ready`.

Run (light: no GPU, <= 4 cores, no served-index load beyond BaseIndex's
meta handle used by publish):
  nice -n 19 taskset -c 12-15 .venv/bin/python3 scripts/experiments/delta_ingest_m4f_p2_fixture.py --layout single
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO))

FIX = Path("/home/vscode/work/delta_ingest/corpus_a")
FIX_ROOT = FIX / "root"
OUT_BASE = Path("/home/vscode/work/delta_ingest/BUILD")
BASE_MANIFEST = Path("/home/vscode/work/inplace_update/m4/base_manifest.json")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_commit() -> str:
    return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", choices=["per_base_section", "per_era", "single"], required=True)
    ap.add_argument("--seismic-threads", type=int, default=4)
    args = ap.parse_args()

    from spike.delta_ingest.base import DEFAULT_INDEX_ROOT, BaseIndex
    from spike.delta_ingest.generation import build_generation, publish
    from spike.delta_ingest.ledger import IngestLedger
    from spike.delta_ingest.profiles import PROFILES

    ready_src = json.loads((FIX / "READY.json").read_text())
    gj_src = json.loads((FIX_ROOT / "generations.json").read_text())
    ordinal_dir = gj_src["livedocs"]["ordinal_dir"]
    out_dir = OUT_BASE / f"corpus_a_{args.layout}"
    root = out_dir / "root"
    if root.exists():
        print(f"{root} exists; refusing", file=sys.stderr)
        return 2
    root.mkdir(parents=True)
    rec = {"layout": args.layout, "fixture": str(FIX), "fixture_commit": ready_src.get("fixture_commit"),
           "commit": git_commit(), "started": utc(), "root": str(root), "ordinal_dir": ordinal_dir,
           "base_manifest": str(BASE_MANIFEST)}
    t0 = time.time()
    src = sqlite3.connect(f"file:{FIX_ROOT / 'ledger.sqlite'}?mode=ro", uri=True)
    dst = sqlite3.connect(root / "ledger.sqlite")
    src.backup(dst)
    dst.close()
    src.close()
    shutil.copytree(FIX_ROOT / "buffer", root / "buffer")
    rec["copy_s"] = round(time.time() - t0, 1)

    ledger = IngestLedger(root / "ledger.sqlite")
    gens = ledger.published_generations()
    assert gens == [1], gens
    records = ledger.records_for([1])
    assert len(records) == 50_000, len(records)
    profile = PROFILES["desktop_gpu"].with_overrides(layout=args.layout, seismic_threads=args.seismic_threads)
    t0 = time.time()
    build_generation(root, 1, records, profile, seismic=True, layout=args.layout,
                     seismic_from=FIX_ROOT / "g0001")
    rec["build_generation_s"] = round(time.time() - t0, 1)
    base = BaseIndex(DEFAULT_INDEX_ROOT)
    t0 = time.time()
    pub = publish(root, ledger, base, str(BASE_MANIFEST), ordinal_dir)
    rec["publish_s"] = round(time.time() - t0, 1)
    base.close()
    ledger.close()

    gi = json.loads((root / "g0001" / "generation.json").read_text())
    want_sections = sorted({r.section(args.layout) for r in records})
    checks = {
        "generations": [(g["gen"], g["docs"], g["docs_with_vectors"], g["seismic"]) for g in pub["generations"]],
        "sections": sorted(gi["sections"]), "sections_expected": want_sections,
        "sections_fixture": json.loads((FIX_ROOT / "g0001" / "generation.json").read_text())["sections"]
        and sorted(json.loads((FIX_ROOT / "g0001" / "generation.json").read_text())["sections"]),
        "mask_counts": {k: len(v) for k, v in pub["mask"].items()},
        "mask_counts_fixture": {k: len(v) for k, v in gj_src["mask"].items()},
        "livedocs": {k: pub["livedocs"].get(k) for k in ("popcount", "superseded_in_base", "deleted_in_base",
                                                          "nbits", "ordinal_space_id")},
        "livedocs_fixture": {k: gj_src["livedocs"].get(k) for k in ("popcount", "superseded_in_base",
                                                                     "deleted_in_base", "nbits",
                                                                     "ordinal_space_id")},
        "seismic_reused_from": gi["seismic"].get("reused_from"),
        "seismic_ids_checked": gi["seismic"].get("reuse_ids_checked"),
    }
    a, b = FIX_ROOT / "g0001" / "seismic", root / "g0001" / "seismic"
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    diff = [str(f) for f in files if not filecmp.cmp(a / f, b / f, shallow=False)]
    checks["seismic_files_compared"] = len(files)
    checks["seismic_files_differing"] = diff
    ok = (checks["generations"] == [(1, 50_000, 50_000, "served")] and checks["sections"] == want_sections
          and checks["mask_counts"] == checks["mask_counts_fixture"]
          and checks["livedocs"] == checks["livedocs_fixture"] and not diff and files)
    checks["ok"] = bool(ok)
    rec["verify"] = checks
    rec["finished"] = utc()
    (out_dir / "build_fixture.json").write_text(json.dumps(rec, indent=1, default=str))
    if not ok:
        print(json.dumps(rec, indent=1, default=str))
        return 3
    ready = json.loads(json.dumps(ready_src))
    ready["root"] = str(root)
    ready["fixture_dir"] = str(out_dir)
    ready["env_gate_on"]["SFU_DELTA_ROOT"] = str(root)
    ready["published_utc"] = utc()
    ready["layout"] = args.layout
    ready["relayout_of"] = {"ready_json": str(FIX / "READY.json"), "fixture_commit": ready_src.get("fixture_commit"),
                            "builder": "scripts/experiments/delta_ingest_m4f_p2_fixture.py", "commit": rec["commit"]}
    ready["verify"] = {"gens": [[1, 50_000, 50_000, "served"]], "relayout_checks": checks}
    ready["rule"] = "built by agent BUILD for 09 P2; do not modify; corpus_a/ itself was only read"
    (out_dir / "READY.json").write_text(json.dumps(ready, indent=1, default=str))
    print(json.dumps({k: rec[k] for k in ("layout", "root", "copy_s", "build_generation_s", "publish_s")}
                     | {"sections": checks["sections"], "ok": bool(ok)}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
