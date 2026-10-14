#!/usr/bin/env python3
"""Build the E8 dv-v2 served manifest as a NEW file (never touch the served one).

Repoints every shard mmap_dir in the v1 e5 manifest from `.dotvbyte.e5.mmap`
to `.dotvbyte.e5.v2.mmap`. Correctness net (v2 is NOT bit-identical to dv1 by
design — it improves overlap — so the e5 tie-identity check does NOT apply):
per shard assert the v2.e5 dir exists, forward_format == dotvbyte_fixedu8_v2,
and len/nnz match the v1.e5 twin (cardinality invariant). Rule Zero: read-only
over shard dirs; writes only the new manifest JSON.
"""
import json, sys, time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
PLAN01 = REPO / "data/seismic_150m/index/plan01"
V1 = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
OUT = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"

import seismic

m = json.loads(V1.read_text())
assert not OUT.exists() or OUT != V1, "refuse to overwrite served manifest"
new = dict(m)
new["shards"] = []
for rec in m["shards"]:
    v1_dir = rec["mmap_dir"]
    assert v1_dir.endswith(".dotvbyte.e5.mmap"), v1_dir
    v2_dir = v1_dir.replace(".dotvbyte.e5.mmap", ".dotvbyte.e5.v2.mmap")
    assert (REPO / v2_dir).exists(), f"missing v2 dir: {v2_dir}"
    v1ix = seismic.MmapSeismicIndex(str(REPO / v1_dir))
    v2ix = seismic.MmapSeismicIndex(str(REPO / v2_dir))
    assert v2ix.forward_format == "dotvbyte_fixedu8_v2", (v2_dir, v2ix.forward_format)
    assert v1ix.len == v2ix.len and v1ix.nnz == v2ix.nnz, f"cardinality drift {v2_dir}"
    print(f"[v2-manifest] {Path(v2_dir).name}: fmt={v2ix.forward_format} "
          f"len={v2ix.len} nnz={v2ix.nnz} OK", flush=True)
    del v1ix, v2ix
    nr = dict(rec)
    nr["mmap_dir"] = v2_dir
    new["shards"].append(nr)

new["forward_format"] = "dotvbyte_fixedu8_v2"
new["derived_from"] = str(V1.relative_to(REPO))
new["derived_utc"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
new["e8_note"] = ("E8 dv-v2 per-doc value scale over the block_walk_canonical e5 "
                  "layout. Quality-IMPROVED vs dv1/e5 (per-shard overlap@10 vs f16 "
                  "0.993-0.997, corpus-mean ~0.9955 vs e5/dv1 ~0.9906); size +0.67%, "
                  "warm p50 <=1.05x, T1 0/0 all 8 shards. NOT served yet — flip held "
                  "for operator sign-off. See e8_stage2_shard*_20260713.json.")
OUT.write_text(json.dumps(new, indent=2))
print(json.dumps({"verdict": "V2_MANIFEST_WRITTEN", "manifest": str(OUT.relative_to(REPO)),
                  "n_shards": len(new["shards"]), "forward_format": new["forward_format"]}, indent=2))
