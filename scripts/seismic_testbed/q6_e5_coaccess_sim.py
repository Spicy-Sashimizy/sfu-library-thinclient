#!/usr/bin/env python3
"""Q6 — E5 co-access forward-reordering page-touch simulation (cold-pages lever).

Roadmap: docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md Q6 ("the one
remaining fault-COUNT lever"); design docs/seismic_150m_testbed/
09_CROSS_SHARD_MMAP_AUDIT.md §3.4 (E5) + 10_FORWARD_COMPRESSION_DESIGN.md
§7.4 item 2. Decides whether the E5 converter (forward permute + 48-bit
pack-offset remap) is worth building.

Method (pack-walk lineage, e7_straddle_analysis.py): capture the REAL
per-query scored-candidate set via the Q6 `search_visited` fork hook (fork
commit 8af7088 — the traversal's `visited` dedup keys, NOT the top-k'
winners), then count unique 4 KiB forward pages each query touches under
candidate permutations of forward doc order. Cold majflt ≈ unique pages
touched (fault-around makes clustered layouts strictly better than this
model — the Fix #5A lesson, so ratios here are conservative for clustered
orders; the 64 KiB-cluster metric is the fault-around-side proxy).

Permutations:
  identity       — shipped layout (denominator).
  random         — control; expect ~>=1.0 (any incidental locality destroyed).
  block_walk     — BUILDABLE, query-independent: first-touch order over the
                   canonical posting-list walk (list 0..V, block/pack order).
                   Co-block docs become adjacent — exactly §3.4's mechanism.
  coaccess_sig   — log-driven: docs sorted by their train-query membership
                   bit-signature; evaluated on held-out test queries only.
  coaccess_walk  — log-driven greedy first-touch over train queries;
                   held-out evaluation. (ceiling estimate, needs query logs)

Bar (pre-registered, doc 12 Q6): the buildable cell (block_walk) must clear
simulated page ratio <= ~0.45 before any converter/id-indirection is built.
GO iff block_walk mean per-query page ratio <= 0.45 on BOTH shards
(worst-case-shard rule); else record and stop.

Geometries: f16 (2 files x 2 B/component; identical page structure -> one
file simulated, x2) and dotvbyte (forward_data.bin, 8 B words). Candidate
rows are captured on the f16 shard (dv preserves doc order byte-exact, so
rows transfer). Forward_offsets/doc-mapping slabs excluded — symmetric
floor (Fix #4/#5B). Rule Zero: read-only over the shard dirs.
"""
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import (load_queries,  # noqa: E402
                                    SPLADE_QUERY_TERMS, K_PRIME, HEAP_FACTOR)

SHARDS = ["global_shard1of8", "global_shard2of8"]
PLAN01 = REPO / "data/seismic_150m/index/plan01"
N_QUERIES = 100
PAGE = 4096
CLUSTER_PAGES = 16          # fault-around window proxy (64 KiB)
GO_BAR = 0.45               # doc 12 Q6 pre-registered
CACHE_DIR = REPO / "data/eval_results/_stage0_cache"
QUERY_FILE = REPO / "data/eval_results/diverse_queries.json"
MODEL_PATH = "models/splade_onnx_fp16"
RESULT = REPO / f"data/eval_results/q6_e5_coaccess_sim_{time.strftime('%Y%m%d')}.json"


def capture_visited(shard: str) -> list[list[int]]:
    """Per-query scored-candidate forward rows on the f16 shard (cached)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"visited_{shard}_n{N_QUERIES}_k{K_PRIME}.json"
    if cache.exists():
        rows = json.loads(cache.read_text())
        print(f"[q6] visited cache hit: {cache.name} ({len(rows)} queries)")
        return rows

    from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)
    import seismic

    mmap_dir = PLAN01 / f"{shard}.mmap"
    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    sd = seismic.get_seismic_string()
    offs = np.memmap(mmap_dir / "forward_offsets.bin", dtype=np.uint64, mode="r")
    queries = load_queries(N_QUERIES, QUERY_FILE)
    assert len(queries) == N_QUERIES, f"query pool exhausted at {len(queries)}"

    per_q = []
    for q in queries:
        q64 = dict(sorted(encode_splade(q, MODEL_PATH).items(),
                          key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        qcomp = np.array(list(q64.keys()), dtype=sd)
        qvals = np.array([float(v) for v in q64.values()], dtype=np.float32)
        _res, starts = idx.search_visited(
            query_id="q", query_components=qcomp, query_values=qvals,
            k=K_PRIME, query_cut=len(q64), heap_factor=HEAP_FACTOR)
        starts = np.asarray(starts, dtype=np.uint64)
        rows = np.searchsorted(offs, starts, side="right") - 1
        assert (offs[rows] == starts).all(), "visited start not a doc boundary"
        per_q.append(sorted(int(r) for r in rows))
    del idx
    gc.collect()
    cache.write_text(json.dumps(per_q))
    print(f"[q6] captured + cached: {cache.name}")
    return per_q


def walk_pack_rows(mmap_dir: Path, offs: np.ndarray) -> np.ndarray:
    """Canonical posting-list walk -> forward rows, order preserved
    (e7_straddle_analysis.py layout walk, verbatim alignment rules)."""
    man = json.loads((mmap_dir / "manifest.json").read_text())
    pl = np.memmap(mmap_dir / "posting_lists.bin", dtype=np.uint8, mode="r")
    # 8-aligned prefix: the file may carry a sub-8-byte tail (last list's
    # u8/u16 slices); the pack walk only reads fully-in-bounds u64 words.
    pl_u64 = pl[:len(pl) // 8 * 8].view(np.uint64)

    def align(cur, a):
        return cur + (a - (cur % a)) % a

    packs = []
    cursor = 0
    for plm in man["posting_lists"]:
        cursor = align(cursor, 8)
        n = plm["packed_postings_words"]
        packs.append(np.asarray(pl_u64[cursor // 8: cursor // 8 + n]))
        cursor += n * 8
        cursor = align(cursor, 8); cursor += plm["block_offsets_len"] * 8
        cursor = align(cursor, 8); cursor += plm["ef_high_bits_n_words"] * 8
        cursor = align(cursor, 8); cursor += plm["inv_block_inventory_len"] * 8
        cursor = align(cursor, 2); cursor += plm["inv_subblock_inventory_len"] * 2
        cursor = align(cursor, 8); cursor += plm["inv_overflow_positions_len"] * 8
        cursor = align(cursor, 8); cursor += plm["ef_low_bits_n_words"] * 8
        cursor = align(cursor, 8); cursor += plm["summaries_ids_n_words"] * 8
        cursor += plm["values_len"]
        cursor = align(cursor, 4); cursor += plm["minimums_len"] * 4
        cursor = align(cursor, 4); cursor += plm["quants_len"] * 4
        if plm["has_component_ids"]:
            cursor = align(cursor, 2); cursor += plm["component_ids_len"] * 2
    assert cursor <= len(pl) and len(pl) - cursor < 8, (cursor, len(pl))
    packs = np.concatenate(packs)
    starts = (packs >> np.uint64(16)).astype(np.uint64)
    rows = np.searchsorted(offs, starts, side="right") - 1
    return rows.astype(np.int64)


def first_touch_perm(touch_rows: np.ndarray, n_docs: int) -> np.ndarray:
    """Full permutation: docs in first-touch order, untouched docs appended
    in original order."""
    u, first = np.unique(touch_rows, return_index=True)
    touched = u[np.argsort(first)]
    mask = np.ones(n_docs, dtype=bool)
    mask[u] = False
    return np.concatenate([touched, np.flatnonzero(mask)])


def newoff_for_perm(perm: np.ndarray, lens: np.ndarray) -> np.ndarray:
    """Per-row start offset (entry units) under permuted layout."""
    starts = np.zeros(len(perm), dtype=np.int64)
    np.cumsum(lens[perm][:-1], out=starts[1:])
    by_row = np.empty(len(perm), dtype=np.int64)
    by_row[perm] = starts
    return by_row


def pages_for_query(rows, by_row, lens, entry_bytes):
    s = by_row[rows] * entry_bytes
    e = s + lens[rows] * entry_bytes
    p0, p1 = s // PAGE, (e - 1) // PAGE
    pages = np.unique(np.concatenate([p0, p1]))
    clusters = np.unique(pages // CLUSTER_PAGES)
    return len(pages), len(clusters)


def eval_perm(per_q_rows, by_row, lens, entry_bytes, q_idx):
    pages = np.empty(len(q_idx), dtype=np.int64)
    clusters = np.empty(len(q_idx), dtype=np.int64)
    for i, qi in enumerate(q_idx):
        rows = np.asarray(per_q_rows[qi], dtype=np.int64)
        pages[i], clusters[i] = pages_for_query(rows, by_row, lens, entry_bytes)
    return pages, clusters


def run_shard(shard: str) -> dict:
    f16_dir = PLAN01 / f"{shard}.mmap"
    dv_dir = PLAN01 / f"{shard}.dotvbyte.mmap"
    per_q = capture_visited(shard)
    n_cands = [len(r) for r in per_q]

    offs_f16 = np.memmap(f16_dir / "forward_offsets.bin", dtype=np.uint64,
                         mode="r").astype(np.int64)
    n_docs = len(offs_f16) - 1
    lens_f16 = np.diff(offs_f16)
    assert int(lens_f16.max()) * 2 <= PAGE, "record > 1 page breaks the span-2 model"

    geoms = {"f16": (lens_f16, 2)}
    if dv_dir.exists():
        offs_dv = np.memmap(dv_dir / "forward_offsets.bin", dtype=np.uint64,
                            mode="r").astype(np.int64)
        assert len(offs_dv) - 1 == n_docs
        lens_dv = np.diff(offs_dv)
        assert int(lens_dv.max()) * 8 <= PAGE, "dv record > 1 page"
        geoms["dotvbyte"] = (lens_dv, 8)

    # --- permutations (row spaces are shared across geometries) ---
    rng = np.random.default_rng(0)
    print(f"[q6] {shard}: walking posting packs for block_walk ...", flush=True)
    walk_rows = walk_pack_rows(f16_dir, np.asarray(offs_f16, dtype=np.uint64))
    t_idx = list(range(0, N_QUERIES, 2))   # train = even, interleaved split
    e_idx = list(range(1, N_QUERIES, 2))   # test  = odd
    all_idx = list(range(N_QUERIES))

    train_rows = np.concatenate([np.asarray(per_q[i], dtype=np.int64) for i in t_idx])
    # bit-signature: for each doc touched by train queries, which queries hit it
    sig = {}
    for j, qi in enumerate(t_idx):
        for r in per_q[qi]:
            sig[r] = sig.get(r, 0) | (1 << j)
    sig_rows = np.fromiter(sig.keys(), dtype=np.int64, count=len(sig))
    sig_vals = np.fromiter(sig.values(), dtype=np.uint64, count=len(sig))
    sig_order = sig_rows[np.argsort(sig_vals, kind="stable")[::-1]]

    perms = {
        "identity": (np.arange(n_docs, dtype=np.int64), all_idx),
        "random": (rng.permutation(n_docs).astype(np.int64), all_idx),
        "block_walk": (first_touch_perm(walk_rows, n_docs), all_idx),
        "block_walk_testhalf": (None, e_idx),   # same perm, held-out queries
        "coaccess_sig": (first_touch_perm(sig_order, n_docs), e_idx),
        "coaccess_walk": (first_touch_perm(train_rows, n_docs), e_idx),
    }
    perms["block_walk_testhalf"] = (perms["block_walk"][0], e_idx)
    del walk_rows, train_rows, sig
    gc.collect()

    out = {"n_docs": int(n_docs),
           "candidates_per_query": {
               "mean": float(np.mean(n_cands)), "p50": int(np.median(n_cands)),
               "min": int(min(n_cands)), "max": int(max(n_cands))},
           "geometries": {}}
    for gname, (lens, entry_bytes) in geoms.items():
        cells = {}
        base_pages = {}
        for pname, (perm, q_idx) in perms.items():
            by_row = newoff_for_perm(perm, lens)
            pages, clusters = eval_perm(per_q, by_row, lens, entry_bytes, q_idx)
            key = tuple(q_idx)
            if pname.startswith("identity") or key not in base_pages:
                bp, bc = eval_perm(per_q, newoff_for_perm(
                    np.arange(n_docs, dtype=np.int64), lens), lens, entry_bytes, q_idx) \
                    if pname != "identity" else (pages, clusters)
                base_pages[key] = (bp, bc)
            bp, bc = base_pages[key]
            cells[pname] = {
                "queries": len(q_idx),
                "mean_pages_per_query": float(pages.mean()),
                "page_ratio_vs_identity": float(pages.sum() / bp.sum()),
                "page_ratio_perquery_mean": float((pages / bp).mean()),
                "cluster64k_ratio_vs_identity": float(clusters.sum() / bc.sum()),
            }
            del by_row
            gc.collect()
            print(f"[q6] {shard} {gname:9s} {pname:20s} "
                  f"ratio {cells[pname]['page_ratio_vs_identity']:.3f} "
                  f"(64k {cells[pname]['cluster64k_ratio_vs_identity']:.3f})",
                  flush=True)
        out["geometries"][gname] = cells
    return out


def main():
    t0 = time.time()
    res = {"meta": {
        "date": time.strftime("%Y-%m-%d"),
        "script": "scripts/seismic_testbed/q6_e5_coaccess_sim.py",
        "fork_hook": "search_visited (fork commit 8af7088)",
        "n_queries": N_QUERIES, "k_prime": K_PRIME, "heap_factor": HEAP_FACTOR,
        "query_cut": "all-terms (E1 verdict)", "shards": SHARDS,
        "candidate_capture": "f16 traversal visited set; dv shares doc order",
        "excluded_slabs": "forward_offsets + doc mapping (symmetric floor, Fix #4/#5B)",
        "model_note": "unique 4KiB pages ~ cold majflt; fault-around favors "
                      "clustered orders beyond this model (Fix #5A), so "
                      "clustered-order ratios are conservative (upper bounds)",
        "bar": f"GO iff block_walk page_ratio <= {GO_BAR} on BOTH shards "
               "(doc 12 Q6; worst-case-shard rule)"},
        "shards": {}}
    for shard in SHARDS:
        res["shards"][shard] = run_shard(shard)

    worst = max(res["shards"][s]["geometries"]["f16"]["block_walk"]
                ["page_ratio_vs_identity"] for s in SHARDS)
    res["verdict"] = {
        "buildable_cell_worst_shard_page_ratio_f16": round(worst, 4),
        "q6_e5": "GO" if worst <= GO_BAR else "RECORD_AND_STOP",
    }
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["verdict"]))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
