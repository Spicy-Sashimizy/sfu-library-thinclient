#!/usr/bin/env python3
"""Q6b — E5 ordering-method sweep (pre-implementation research).

Q6 (q6_e5_coaccess_sim.py, 2026-07-09) proved GO on ONE buildable order
(canonical pack-walk, 0.376-0.400x pages). Before building the converter,
rank the buildable ordering families on the same cached real candidate
sets, with special weight on APPEND-FRIENDLINESS: whether a new doc's
position key is computable from the doc alone at ingest time (no global
walk), so incremental adds between the monthly rebuilds
(THIN_CLIENT_SWAP.md "Monthly rebuilds") can slot in without a full
re-convert.

Orders swept (all index-derived, no query logs, no external metadata):
  block_walk_canonical  — Q6's GO cell: first-touch over lists in token-id
                          order. Global property -> NOT append-friendly
                          (new docs go to the tail until next re-convert).
  block_walk_hotfirst   — lists visited in DESC packed-words order (heavy
                          lists claim contiguity first). Global.
  block_walk_coldfirst  — ASC control (if hot/cold barely differ, list
                          order is a free parameter). Global.
  home_component        — per-doc key = argmax-VALUE component id (stable
                          within key by original row). PER-DOC KEY ->
                          append-friendly: an ingested doc's slot region
                          is known from its own SPLADE vector.
  home_component_val    — (home component, value desc): within a term's
                          region, strongest docs adjacent — a cheap proxy
                          for SEISMIC's within-list block clustering.
                          Per-doc key -> append-friendly.
  coaccess_sig          — log-driven ceiling (from Q6, held-out) for
                          reference only; not buildable in production.

Selection rule (pre-registered): pick the best append-friendly order if
its worst-shard f16 page ratio is within +0.03 of the best global order;
else pick the best global order. Random/identity controls validated in Q6.
Rule Zero: read-only over the shard dirs.
"""
import gc
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

SHARDS = ["global_shard1of8", "global_shard2of8"]
SELECT_MARGIN = 0.03
RESULT = REPO / f"data/eval_results/q6b_order_sweep_{time.strftime('%Y%m%d')}.json"


def walk_pack_rows_per_list(mmap_dir: Path, offs: np.ndarray) -> list[np.ndarray]:
    """Per-posting-list candidate rows in pack order (q6 walk, un-concatenated)."""
    man = json.loads((mmap_dir / "manifest.json").read_text())
    pl = np.memmap(mmap_dir / "posting_lists.bin", dtype=np.uint8, mode="r")
    # posting_lists.bin may end with a sub-8-byte tail (last list's u8/u16
    # slices), so the file length need not be 8-divisible; the packed_postings
    # walk only indexes u64 words that sit fully within the file, so view the
    # 8-aligned prefix (the final assert still checks the full uint8 length).
    pl_u64 = pl[:len(pl) // 8 * 8].view(np.uint64)

    def align(cur, a):
        return cur + (a - (cur % a)) % a

    per_list = []
    cursor = 0
    for plm in man["posting_lists"]:
        cursor = align(cursor, 8)
        n = plm["packed_postings_words"]
        packs = np.asarray(pl_u64[cursor // 8: cursor // 8 + n])
        starts = (packs >> np.uint64(16)).astype(np.uint64)
        rows = (np.searchsorted(offs, starts, side="right") - 1).astype(np.int64)
        per_list.append(rows)
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
    return per_list


def home_components(mmap_dir: Path, offs64: np.ndarray,
                    chunk_docs: int = 2_000_000) -> tuple[np.ndarray, np.ndarray]:
    """Per-doc (argmax-value component id, that value) from the f16 forward.
    Vectorized two-pass per chunk: reduceat row-max, then first position
    hitting it (f16 equality is exact — same stored bytes)."""
    comps = np.memmap(mmap_dir / "forward_components.bin", dtype=np.uint16, mode="r")
    vals = np.memmap(mmap_dir / "forward_values.bin", dtype=np.float16, mode="r")
    n_docs = len(offs64) - 1
    home = np.empty(n_docs, dtype=np.int64)
    home_val = np.empty(n_docs, dtype=np.float32)
    for lo in range(0, n_docs, chunk_docs):
        hi = min(lo + chunk_docs, n_docs)
        s, e = int(offs64[lo]), int(offs64[hi])
        v = np.asarray(vals[s:e], dtype=np.float32)
        seg = (offs64[lo:hi] - s).astype(np.int64)
        lens = np.diff((offs64[lo:hi + 1] - s).astype(np.int64))
        assert (lens > 0).all(), "empty doc row"
        rowmax = np.maximum.reduceat(v, seg)
        rows = np.repeat(np.arange(hi - lo, dtype=np.int64), lens)
        hitpos = np.flatnonzero(v == rowmax[rows])
        first = np.unique(rows[hitpos], return_index=True)[1]
        pos = hitpos[first]
        home[lo:hi] = np.asarray(comps[s:e], dtype=np.int64)[pos]
        home_val[lo:hi] = rowmax
        del v, rows, hitpos
        gc.collect()
    return home, home_val


def run_shard(shard: str) -> dict:
    f16_dir = PLAN01 / f"{shard}.mmap"
    per_q = capture_visited(shard)          # cache hit from Q6
    offs64 = np.memmap(f16_dir / "forward_offsets.bin", dtype=np.uint64,
                       mode="r").astype(np.uint64)
    offs = offs64.astype(np.int64)
    n_docs = len(offs) - 1
    lens = np.diff(offs)

    print(f"[q6b] {shard}: per-list pack walk ...", flush=True)
    per_list = walk_pack_rows_per_list(f16_dir, offs64)
    list_sizes = np.array([len(r) for r in per_list], dtype=np.int64)

    print(f"[q6b] {shard}: home-component scan ...", flush=True)
    home, home_val = home_components(f16_dir, offs64)

    # train-half signature order (Q6's coaccess_sig, for the ceiling column)
    t_idx = list(range(0, N_QUERIES, 2))
    e_idx = list(range(1, N_QUERIES, 2))
    all_idx = list(range(N_QUERIES))
    sig = {}
    for j, qi in enumerate(t_idx):
        for r in per_q[qi]:
            sig[r] = sig.get(r, 0) | (1 << j)
    sig_rows = np.fromiter(sig.keys(), dtype=np.int64, count=len(sig))
    sig_vals = np.fromiter(sig.values(), dtype=np.uint64, count=len(sig))
    sig_order = sig_rows[np.argsort(sig_vals, kind="stable")[::-1]]

    def cat(order_of_lists):
        return np.concatenate([per_list[i] for i in order_of_lists])

    orders = {
        "block_walk_canonical": (
            first_touch_perm(cat(range(len(per_list))), n_docs), all_idx, False),
        "block_walk_hotfirst": (
            first_touch_perm(cat(np.argsort(-list_sizes, kind="stable")), n_docs),
            all_idx, False),
        "block_walk_coldfirst": (
            first_touch_perm(cat(np.argsort(list_sizes, kind="stable")), n_docs),
            all_idx, False),
        "home_component": (
            np.argsort(home, kind="stable"), all_idx, True),
        "home_component_val": (
            np.lexsort((-home_val, home)), all_idx, True),
        "coaccess_sig_ceiling": (
            first_touch_perm(sig_order, n_docs), e_idx, False),
    }
    del per_list, sig
    gc.collect()

    # identity baselines per query subset
    ident = np.arange(n_docs, dtype=np.int64)
    base = {}
    for q_idx in (tuple(all_idx), tuple(e_idx)):
        by_row = newoff_for_perm(ident, lens)
        base[q_idx] = eval_perm(per_q, by_row, lens, 2, list(q_idx))
        del by_row

    out = {}
    for name, (perm, q_idx, append_friendly) in orders.items():
        assert len(perm) == n_docs and len(np.unique(perm)) == n_docs, name
        by_row = newoff_for_perm(np.asarray(perm, dtype=np.int64), lens)
        pages, clusters = eval_perm(per_q, by_row, lens, 2, q_idx)
        bp, bc = base[tuple(q_idx)]
        out[name] = {
            "append_friendly": append_friendly,
            "page_ratio_vs_identity": float(pages.sum() / bp.sum()),
            "cluster64k_ratio_vs_identity": float(clusters.sum() / bc.sum()),
            "mean_pages_per_query": float(pages.mean()),
        }
        del by_row
        gc.collect()
        print(f"[q6b] {shard} {name:22s} ratio "
              f"{out[name]['page_ratio_vs_identity']:.3f} "
              f"(64k {out[name]['cluster64k_ratio_vs_identity']:.3f})"
              f"{'  [append-friendly]' if append_friendly else ''}", flush=True)
    return out


def main():
    t0 = time.time()
    res = {"meta": {
        "date": time.strftime("%Y-%m-%d"),
        "script": "scripts/seismic_testbed/q6b_order_sweep.py",
        "lineage": "q6_e5_coaccess_sim.py (candidate cache + eval reused)",
        "geometry": "f16 (2 B/entry, one of two identical-structure files); "
                    "Q6 showed dv geometry tracks f16 within 0.01",
        "selection_rule": f"best append-friendly order if within "
                          f"+{SELECT_MARGIN} of best global order (worst-shard "
                          f"f16 page ratio); else best global order",
        "shards": SHARDS},
        "shards": {}}
    for shard in SHARDS:
        res["shards"][shard] = run_shard(shard)

    names = [n for n in res["shards"][SHARDS[0]] if n != "coaccess_sig_ceiling"]
    worst = {n: max(res["shards"][s][n]["page_ratio_vs_identity"] for s in SHARDS)
             for n in names}
    best_global = min((n for n in names
                       if not res["shards"][SHARDS[0]][n]["append_friendly"]),
                      key=lambda n: worst[n])
    af = [n for n in names if res["shards"][SHARDS[0]][n]["append_friendly"]]
    best_af = min(af, key=lambda n: worst[n]) if af else None
    chosen = best_af if (best_af and
                         worst[best_af] <= worst[best_global] + SELECT_MARGIN) \
        else best_global
    res["verdict"] = {
        "worst_shard_page_ratio": {n: round(worst[n], 4) for n in names},
        "best_global": best_global, "best_append_friendly": best_af,
        "chosen_order": chosen,
        "chosen_is_append_friendly":
            bool(res["shards"][SHARDS[0]][chosen]["append_friendly"]),
    }
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["verdict"], indent=2))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
