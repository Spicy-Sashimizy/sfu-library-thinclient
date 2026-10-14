#!/usr/bin/env python3
"""F1 (2026-07-14): offline hot-set generator — disk-streaming research Phase 1.

Pre-registered in docs/disk_streaming_research/03_MIN_RAM_DESIGN_MAP.md §5
(build order step 1) + 11_EXPERIMENT_BACKLOG.md §Q12b. Script-only: NO Rust
changes, NO serving-path change (read-only `search_visited` instrument, same
as Q12). Produces the F2 sidecar (`<shard>.mmap/hotset.json`) the F3 pin tier
will consume at load.

What it does
------------
- Over a production-shaped query log (reuses the Q12b Zipf+repeat builder over
  data/sfu_eval_queries.json), run `search_visited` per query × shard.
- Per shard: aggregate the touched forward_data.bin 4KiB PAGE ids into a
  Counter (touch counts = the Q12 "would this page be warm from an earlier
  query" statistic; the colibrì `eusage` analog).
- Greedy by touch count (the Q12 counter IS the ranking, per doc 03 §2 F3):
  sort touched pages desc, take pages until each target RAM budget is reached,
  coalesce ADJACENT taken pages into (page_start, page_len) EXTENTS (E5's
  block_walk_canonical reorder made co-accessed docs contiguous → few, large
  extents, not scattered single pages; doc 03 §2 F2).
- Emit per shard × per budget: `<shard>.mmap/hotset_<budget>.json` with the
  F2 schema (sorted extents + forward_format_version + forward_reordered +
  generation date). The loader (added with F3) refuses-and-logs on key mismatch.

Budget dials emitted (the Phase-3 A/B cells, doc 03 §3):
  - 1.6 GB  (hot-50 ≈ 50% of touches, Q12 curve)
  - 4.2 GB  (hot-80 ≈ 80% of touches)
Plus a full-touched sidecar (every touched page = the coverage ceiling).

Kill-switch discipline: nothing here ships to the served path until F3 loads
it behind SFU_SEISMIC_PIN_BUDGET_GB (=0 → today's behavior, byte-identical).
This script is read-only over the served shards (Rule Zero).
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

MANIFEST = REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5_v2.json"
# Reuse the Q12b production-shaped query log builder (same source, same shape)
# + its coverage_curve (the global pooled hotset_50/80/90 GB computation).
from q12b_access_skew_production import build_production_log, coverage_curve  # noqa: E402

PAGE = 4096
WORD = 8  # dv visited starts are u64 word offsets into forward_data.bin
N_DRAWS = 400
SEED = 20260714

# Budget dials (bytes) the Phase-3 A/B will request. Greedy-by-touch-count
# pages up to this byte budget; the Q12 curve maps ~1.6GB→50%, ~4.2GB→80%.
BUDGET_BYTES = [
    ("hot50_1.6gb", int(1.6 * 1e9)),
    ("hot80_4.2gb", int(4.2 * 1e9)),
    ("full_touched", None),  # every page touched (the coverage ceiling)
]


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def coalesce_extents(pages_sorted: list[int]) -> list[list[int]]:
    """Coalesce a sorted (asc) list of page ids into (page_start, page_len)
    extents. Adjacent pages (n, n+1, n+2) merge into one extent [n, 3]."""
    if not pages_sorted:
        return []
    extents = []
    start = prev = pages_sorted[0]
    run_len = 1
    for p in pages_sorted[1:]:
        if p == prev + 1:
            run_len += 1
        else:
            extents.append([start, run_len])
            start = p
            run_len = 1
        prev = p
    extents.append([start, run_len])
    return extents


def greedy_extent_budget(counts_by_page: dict[int, int], budget_bytes) -> list[int]:
    """Greedy: take pages in DESC touch-count order until the byte budget is
    reached (None = take every touched page). Returns the taken page ids
    (sorted asc, ready for coalescing)."""
    items = sorted(counts_by_page.items(), key=lambda kv: (-kv[1], kv[0]))
    if budget_bytes is None:
        taken = [p for p, _ in items]
    else:
        taken = []
        acc = 0
        for p, _c in items:
            if acc >= budget_bytes:
                break
            taken.append(p)
            acc += PAGE
    return sorted(taken)


def main():
    from lib.thinclient.sharded_seismic_backend import (
        _load_manifest, _load_one_shard, _prepare_query, _EncoderShim)
    import seismic

    queries = build_production_log(SEED)
    log(f"production log: {len(queries)} draws (Zipf subjects + within-subject repeat)")

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    shards = [_load_one_shard(seismic, p, "mmap") for p in paths]
    string_dtype = seismic.get_seismic_string()
    log(f"loaded {len(shards)} shards (mmap, E8 v2)")

    encoder = _EncoderShim("models/splade_onnx_fused")

    def encode(q: str) -> dict:
        from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS
        sparse = encoder.encode_splade(q)
        if not sparse:
            return {}
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def visited_pages(q: dict) -> list[set]:
        qcomp, qvals, qc, kp = _prepare_query(q, 50, string_dtype, None, None)
        out = []
        for idx in shards:
            _res, visited = idx.search_visited(
                "q", qcomp, qvals, k=kp, query_cut=qc, heap_factor=0.8)
            pages = np.unique(np.asarray(visited, dtype=np.uint64) * WORD // PAGE)
            out.append(set(pages.tolist()))
        return out

    # ── accumulate per-shard touch counters ───────────────────────────────────
    per_shard_counts: list[Counter] = [Counter() for _ in shards]
    t_start = time.time()
    for i, ptext in enumerate(queries):
        q = encode(ptext)
        if not q:
            continue
        shard_pages = visited_pages(q)
        for c, s in zip(per_shard_counts, shard_pages):
            c.update(s)
        if i % 25 == 0 or i == len(queries) - 1:
            log(f"  q{i:3d}/{len(queries)}: elapsed {time.time()-t_start:.0f}s")

    # ── pooled coverage curve (the Q12b methodology: across ALL shards) ───────
    # The Q12 curve's "1.6GB→50%, 4.2GB→80%" is a GLOBAL 8-shard coverage curve
    # (pages ranked by touch count ACROSS the pooled touch set), NOT per-shard.
    # A per-shard budget equal to the global budget is wrong — each shard's
    # total touched set is only ~0.94 GB (smaller than even the 1.6 GB dial),
    # so a naive per-shard 1.6 GB would take 100% of every shard. Instead the
    # global budget is split per-shard proportionally and pages are taken by
    # descending LOCAL touch count up to each shard's share — greedy on the
    # per-shard counter IS the local proxy for the global greedy (the shards
    # are independent forward files; a page in shard 0 cannot serve a touch in
    # shard 1, so ranking is intrinsically per-shard).
    n_shards = len(shards)
    pooled_counts = Counter()
    for c in per_shard_counts:
        pooled_counts.update(c)
    pooled_arr = np.array(list(pooled_counts.values()), dtype=np.int64)
    pooled_total_touches = int(pooled_arr.sum())
    pooled_curve = coverage_curve(pooled_arr)  # global hotset_50/80/90 in GB

    # ── per shard: read manifest version keys, emit sidecars at each budget ───
    summary = []
    gen_date = time.strftime("%Y-%m-%d")  # date only (no wall-clock in sidecar)
    # Global budget bytes split PER SHARD (proportional; shards are ~equal-size
    # v2 shards). The sidecar records BOTH the global budget_bytes (the dial)
    # and the per_shard_budget_bytes actually applied.
    for si, (p, counts) in enumerate(zip(paths, per_shard_counts)):
        mmap_dir = Path(p) if Path(p).is_absolute() else REPO / p
        shard_man_path = mmap_dir / "manifest.json"
        shard_man = json.loads(shard_man_path.read_text())
        # Keys the loader will check — a mismatch (e.g. E8 reconversion) MUST
        # fail loud, not pin garbage (doc 03 §2 F2).
        version_keys = {
            "forward_format": shard_man.get("forward_format"),
            "forward_format_version": shard_man.get("forward_format_version"),
            "forward_reordered": shard_man.get("forward_reordered"),
            "forward_data_words": shard_man.get("forward_data_words"),
        }
        # dv visited starts are word offsets into forward_data.bin.
        fwd_total_pages = int(shard_man["forward_data_words"]) * WORD // PAGE

        counts_by_page = dict(counts)
        distinct = len(counts_by_page)
        total_touches = int(sum(counts_by_page.values()))

        for budget_name, budget_bytes in BUDGET_BYTES:
            if budget_bytes is None:
                per_shard_budget = None  # full_touched = every touched page
            else:
                per_shard_budget = budget_bytes // n_shards
            taken = greedy_extent_budget(counts_by_page, per_shard_budget)
            extents = coalesce_extents(taken)
            n_pages = sum(e[1] for e in extents)
            covered_touches = sum(counts_by_page[pg] for pg in taken)
            gb = round(n_pages * PAGE / 1e9, 4)
            # Effective extent count = how many (page_start, page_len) ranges.
            sidecar = {
                "schema": "seismic.hotset.v1",
                "shard_dir": str(mmap_dir.relative_to(REPO)) if str(mmap_dir).startswith(str(REPO)) else str(mmap_dir),
                "budget_name": budget_name,
                "budget_bytes_global": budget_bytes,
                "budget_bytes_per_shard": per_shard_budget,
                "page_size": PAGE,
                "forward_data_total_pages": fwd_total_pages,
                "version_keys": version_keys,
                "generated_utc_date": gen_date,
                "source": "scripts/seismic_testbed/f1_hotset_generator.py",
                "query_log": "q12b production-shaped (Zipf subjects + within-subject repeat, N=400 over data/sfu_eval_queries.json)",
                "stats": {
                    "n_touched_pages_input": distinct,
                    "total_touches_input": total_touches,
                    "n_pages_pinned": n_pages,
                    "n_extents": len(extents),
                    "pinned_gb": gb,
                    "coverage_of_touched_pages_frac": round(n_pages / distinct, 4) if distinct else 0.0,
                    "coverage_of_touches_frac": round(covered_touches / total_touches, 4) if total_touches else 0.0,
                },
                "extents": extents,  # list of [page_start, page_len], sorted by page_start
            }
            out_path = mmap_dir / f"hotset_{budget_name}.json"
            out_path.write_text(json.dumps(sidecar, indent=2))
            summary.append({
                "shard": si, "budget": budget_name, "pinned_gb": gb,
                "n_extents": len(extents), "n_pages": n_pages,
                "coverage_touches_frac": sidecar["stats"]["coverage_of_touches_frac"],
                "coverage_touched_pages_frac": sidecar["stats"]["coverage_of_touched_pages_frac"],
                "_shard_total_touches": total_touches,
                "file": str(out_path.relative_to(REPO)),
            })
            log(f"  shard{si} {budget_name}: {gb}GB, {len(extents)} extents, "
                f"covers {sidecar['stats']['coverage_of_touches_frac']*100:.1f}% of touches "
                f"({n_pages} pages)")

    # Global per-budget totals (sum of all shards' pinned GB + covered touches).
    global_by_budget = {}
    for budget_name, _ in BUDGET_BYTES:
        rows = [s for s in summary if s["budget"] == budget_name]
        global_by_budget[budget_name] = {
            "pinned_gb_global": round(sum(s["pinned_gb"] for s in rows), 4),
            "n_extents_global": sum(s["n_extents"] for s in rows),
            "n_pages_global": sum(s["n_pages"] for s in rows),
            # Pooled: fraction of GLOBAL touches covered by this budget's pin
            # set = Σ(shard covered_touches) / pooled_total_touches.
            "coverage_touches_global_frac": round(
                sum(s["coverage_touches_frac"] * s.get("_shard_total_touches", 0)
                    for s in rows) / pooled_total_touches, 4)
            if pooled_total_touches else 0.0,
        }

    # top-level inventory
    inv = {
        "probe": "f1_hotset_generator",
        "date": gen_date,
        "manifest": str(MANIFEST.relative_to(REPO)),
        "forward_format_version": 2,
        "n_queries": N_DRAWS,
        "budgets": [b for b, _ in BUDGET_BYTES],
        "pooled_coverage_curve": pooled_curve,  # global hotset_50/80/90 in GB
        "pooled_total_touches": pooled_total_touches,
        "pooled_distinct_pages": len(pooled_counts),
        "global_by_budget": global_by_budget,
        "shards": summary,
    }
    inv_path = REPO / "data" / "eval_results" / (
        "f1_hotset_sidecars_inventory_" + gen_date.replace("-", "") + ".json")
    inv_path.write_text(json.dumps(inv, indent=2))
    log(f"wrote inventory {inv_path}")
    log(f"pooled coverage: hotset50 {pooled_curve['hotset_50_gb']}GB / "
        f"hotset80 {pooled_curve['hotset_80_gb']}GB / "
        f"hotset90 {pooled_curve['hotset_90_gb']}GB "
        f"({len(pooled_counts)} distinct pages, {pooled_total_touches} touches)")
    for bn, g in global_by_budget.items():
        log(f"  {bn}: global {g['pinned_gb_global']}GB pinned, "
            f"covers {g['coverage_touches_global_frac']*100:.1f}% of pooled touches")


if __name__ == "__main__":
    main()
