#!/usr/bin/env python3
"""Q6c — E5 BESPOKE ordering cell: meta.sqlite-derived doc order (user request
2026-07-09: "test against a bespoke ordering method using db [metadata] rather
than general ordering methods").

Orders the forward index by corpus-domain keys from the global metadata DB
(`data/thinclient_index/meta.sqlite` v2, docs(id, title, doi, year, type,
is_oa, section) — doc 09 §1 table) instead of index-structure keys:

  meta_section_year       — (section, year): doc 09 §3.4's original E5
                            proposal's cheap semantic key. Fully
                            append-friendly: key exists BEFORE indexing.
  meta_section_year_home  — (section, year, argmax-SPLADE-term): the full
                            section‖year‖top-term proposal.

Evaluated with the exact Q6/Q6b machinery (cached real candidate sets,
unique 4KiB f16 forward pages vs identity). Compared against Q6b's
block_walk cells in the verdict. Rule Zero: read-only; meta.sqlite opened
ro (its WAL is live serving state).
"""
import gc
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from q6_e5_coaccess_sim import (  # noqa: E402
    PLAN01, N_QUERIES, capture_visited, newoff_for_perm, eval_perm)
from q6b_order_sweep import home_components  # noqa: E402

SHARDS = ["global_shard1of8", "global_shard2of8"]
META_DB = REPO / "data/thinclient_index/meta.sqlite"
RESULT = REPO / f"data/eval_results/q6c_meta_order_sim_{time.strftime('%Y%m%d')}.json"


def shard_doc_ids(mmap_dir: Path) -> np.ndarray:
    """Row-aligned numeric OpenAlex ids from the doc-mapping slabs."""
    moffs = np.memmap(mmap_dir / "document_mapping_offsets.bin",
                      dtype=np.uint64, mode="r").astype(np.int64)
    blob = (mmap_dir / "document_mapping_strings.bin").read_bytes()
    n = len(moffs) - 1
    ids = np.empty(n, dtype=np.int64)
    for i in range(n):
        s = blob[moffs[i]:moffs[i + 1]].decode()
        assert s[0] == "W", f"unexpected doc id format: {s!r}"
        ids[i] = int(s[1:])
    del blob
    gc.collect()
    return ids


def meta_keys(ids: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """(section_code, year) per row from meta.sqlite; missing -> (-1, -1).

    ONE sequential full-table scan with vectorized membership (searchsorted
    against the shard's sorted id array) — the chunked-IN variant was killed
    2026-07-09 after 50 min of random B-tree lookups on drvfs; a 150M-row
    sequential scan is minutes."""
    order = np.argsort(ids, kind="stable")
    sorted_ids = ids[order]
    sec = np.full(len(ids), -1, dtype=np.int32)
    year = np.full(len(ids), -1, dtype=np.int32)
    sections: dict[str, int] = {}
    hits = 0
    db = sqlite3.connect(f"file:{META_DB}?mode=ro", uri=True)
    cur = db.execute("SELECT id, year, section FROM docs")
    scanned = 0
    while True:
        rows = cur.fetchmany(1_000_000)
        if not rows:
            break
        scanned += len(rows)
        rid = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
        pos = np.searchsorted(sorted_ids, rid)
        pos_c = np.minimum(pos, len(sorted_ids) - 1)
        hit = sorted_ids[pos_c] == rid
        for bi in np.flatnonzero(hit):
            i = int(order[pos_c[bi]])
            y, s = rows[bi][1], rows[bi][2]
            if s is not None:
                sec[i] = sections.setdefault(s, len(sections))
            if y is not None:
                year[i] = int(y)
        hits += int(hit.sum())
        if scanned % 20_000_000 == 0:
            print(f"[q6c]   scanned {scanned/1e6:.0f}M rows, matched "
                  f"{hits/1e6:.1f}M", flush=True)
    db.close()
    return sec, year, {"distinct_sections": len(sections),
                       "rows_missing_from_meta": int(len(ids) - hits),
                       "table_rows_scanned": scanned}


def run_shard(shard: str) -> dict:
    f16_dir = PLAN01 / f"{shard}.mmap"
    per_q = capture_visited(shard)      # Q6 cache hit
    offs64 = np.memmap(f16_dir / "forward_offsets.bin", dtype=np.uint64,
                       mode="r").astype(np.uint64)
    lens = np.diff(offs64.astype(np.int64))
    n_docs = len(lens)
    all_idx = list(range(N_QUERIES))

    print(f"[q6c] {shard}: doc-mapping scan ...", flush=True)
    ids = shard_doc_ids(f16_dir)
    assert len(ids) == n_docs
    print(f"[q6c] {shard}: meta.sqlite join ({n_docs:,} ids) ...", flush=True)
    t0 = time.time()
    sec, year, meta_stats = meta_keys(ids)
    print(f"[q6c] {shard}: join done in {time.time()-t0:.0f}s "
          f"({meta_stats})", flush=True)
    print(f"[q6c] {shard}: home-component scan ...", flush=True)
    home, _hv = home_components(f16_dir, offs64)

    orders = {
        "meta_section_year": np.lexsort((year, sec)),
        "meta_section_year_home": np.lexsort((home, year, sec)),
    }

    ident = np.arange(n_docs, dtype=np.int64)
    by_row = newoff_for_perm(ident, lens)
    bp, bc = eval_perm(per_q, by_row, lens, 2, all_idx)
    del by_row

    out = {"meta_stats": meta_stats}
    for name, perm in orders.items():
        perm = np.asarray(perm, dtype=np.int64)
        assert len(np.unique(perm)) == n_docs
        by_row = newoff_for_perm(perm, lens)
        pages, clusters = eval_perm(per_q, by_row, lens, 2, all_idx)
        out[name] = {
            "append_friendly": True,
            "page_ratio_vs_identity": float(pages.sum() / bp.sum()),
            "cluster64k_ratio_vs_identity": float(clusters.sum() / bc.sum()),
            "mean_pages_per_query": float(pages.mean()),
        }
        del by_row
        gc.collect()
        print(f"[q6c] {shard} {name:24s} ratio "
              f"{out[name]['page_ratio_vs_identity']:.3f} "
              f"(64k {out[name]['cluster64k_ratio_vs_identity']:.3f})", flush=True)
    return out


def main():
    t0 = time.time()
    res = {"meta": {
        "date": time.strftime("%Y-%m-%d"),
        "script": "scripts/seismic_testbed/q6c_meta_order_sim.py",
        "lineage": "q6/q6b machinery on the same cached candidate sets",
        "orders": "bespoke meta.sqlite keys (section,year[,home-term])",
        "shards": SHARDS},
        "shards": {}}
    for shard in SHARDS:
        res["shards"][shard] = run_shard(shard)
    worst = {n: max(res["shards"][s][n]["page_ratio_vs_identity"]
                    for s in SHARDS)
             for n in ("meta_section_year", "meta_section_year_home")}
    res["verdict"] = {"worst_shard_page_ratio": {k: round(v, 4)
                                                 for k, v in worst.items()},
                      "note": "compare against q6b_order_sweep block_walk cells"}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["verdict"], indent=2))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
