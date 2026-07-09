#!/usr/bin/env python3
"""E5 rollout validation + manifest writer (run after e5_rollout.sh).

1. Parity spot-check EVERY converted e5 shard vs its dv twin: N queries,
   tie-aware bit-identical contract (score bits per rank + interior tie-group
   set equality — doc 13 §2.3). Shard1/2 already have full cold+parity gates;
   this is the correctness net for shards 0,3-7 (converter byte-verify + this).
2. Write the e5 served manifest: the dv manifest with each shard's `mmap_dir`
   repointed to `.dotvbyte.e5.mmap` (existence-checked), n_shards preserved so
   the loader's partial-corpus guard holds. Provenance note added.

Refuses to write the manifest if any shard fails parity or is missing.
Rule Zero: read-only over the shard dirs; writes only the new manifest JSON.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries, SPLADE_QUERY_TERMS, K_PRIME, HEAP_FACTOR  # noqa: E402
from e5_shard_gates import tie_aware_compare  # noqa: E402

PLAN01 = REPO / "data/seismic_150m/index/plan01"
DV_MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
E5_MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
QUERY_FILE = REPO / "data/eval_results/diverse_queries.json"
MODEL_PATH = "models/splade_onnx_fp16"
SPOT_QUERIES = 25


def spotcheck(shard_name: str, encode, string_dtype, queries) -> dict:
    import seismic
    base = seismic.MmapSeismicIndex(str(PLAN01 / f"{shard_name}.dotvbyte.mmap"))
    e5 = seismic.MmapSeismicIndex(str(PLAN01 / f"{shard_name}.dotvbyte.e5.mmap"))
    assert base.len == e5.len and base.nnz == e5.nnz, f"{shard_name} cardinality drift"
    man = json.loads((PLAN01 / f"{shard_name}.dotvbyte.e5.mmap" / "manifest.json").read_text())
    assert man.get("forward_reordered") == "block_walk_canonical", \
        f"{shard_name} missing/wrong reorder provenance"
    hard = swaps = 0
    for q in queries:
        terms = dict(sorted(encode(q, MODEL_PATH).items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        qc = np.array(list(terms.keys()), dtype=string_dtype)
        qv = np.array([float(v) for v in terms.values()], dtype=np.float32)
        kw = dict(query_id="q", query_components=qc, query_values=qv,
                  k=K_PRIME, query_cut=len(terms), heap_factor=HEAP_FACTOR)
        b = [(d, float(s)) for (_q, s, d) in base.search(**kw)]
        e = [(d, float(s)) for (_q, s, d) in e5.search(**kw)]
        h, s = tie_aware_compare(b, e)
        hard += h
        swaps += s
    del base, e5
    return {"hard_mismatches": hard, "tie_swaps": swaps, "n_queries": len(queries)}


def main():
    from lib.opensearch_retriever import encode_splade  # torch first
    import seismic
    string_dtype = seismic.get_seismic_string()
    queries = load_queries(SPOT_QUERIES, QUERY_FILE)

    dv = json.loads(DV_MANIFEST.read_text())
    records = dv["shards"]
    results = {}
    all_ok = True
    for rec in records:
        name = Path(rec["mmap_dir"]).name.replace(".dotvbyte.mmap", "")
        e5_dir = PLAN01 / f"{name}.dotvbyte.e5.mmap"
        if not e5_dir.exists():
            results[name] = {"error": "e5 dir missing"}
            all_ok = False
            continue
        r = spotcheck(name, encode_splade, string_dtype, queries)
        r["ok"] = (r["hard_mismatches"] == 0)
        all_ok = all_ok and r["ok"]
        results[name] = r
        print(f"[e5-validate] {name}: hard={r['hard_mismatches']} "
              f"tie_swaps={r['tie_swaps']} {'OK' if r['ok'] else 'FAIL'}", flush=True)

    if not all_ok:
        print(json.dumps({"verdict": "PARITY_FAIL — manifest NOT written",
                          "shards": results}, indent=2))
        raise SystemExit(1)

    # Build the e5 manifest: repoint every mmap_dir; keep everything else.
    e5man = dict(dv)
    e5man["shards"] = []
    for rec in records:
        nr = dict(rec)
        nr["mmap_dir"] = rec["mmap_dir"].replace(".dotvbyte.mmap", ".dotvbyte.e5.mmap")
        assert (REPO / nr["mmap_dir"]).exists(), nr["mmap_dir"]
        e5man["shards"].append(nr)
    e5man["derived_from"] = str(DV_MANIFEST.relative_to(REPO))
    e5man["derived_utc"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    e5man["forward_reordered"] = "block_walk_canonical"
    e5man["e5_note"] = ("E5 forward-locality reorder (block_walk_canonical); "
                        "quality-identical to the dv manifest (parity bit-identical, "
                        "shard1/2 full gates + shards 0,3-7 spot-checked); "
                        "cold majflt ~0.53x, cold p50 ~1.46x. See doc 13.")
    E5_MANIFEST.write_text(json.dumps(e5man, indent=2))
    print(json.dumps({"verdict": "PARITY_OK — manifest written",
                      "manifest": str(E5_MANIFEST.relative_to(REPO)),
                      "n_shards": len(e5man["shards"]),
                      "shards": results}, indent=2))


if __name__ == "__main__":
    main()
