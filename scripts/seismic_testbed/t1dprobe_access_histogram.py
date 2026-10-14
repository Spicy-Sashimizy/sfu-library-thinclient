#!/usr/bin/env python3
"""T1d-probe (2026-09-12): the real 150M SEISMIC index's page-access histogram,
in the form Tier-1d's S-realprofile and the T1d-12 clustering arm need.

Pre-registered in spike/convergence_repro/PREREGISTRATION_T1D_PROBE.md (frozen
section 7). Prior measurement of the same quantity: Q12 (2026-07-13) and Q12b
(2026-07-14, scripts/seismic_testbed/q12b_access_skew_production.py) — this
script is Q12b's method with three additions the probe needs and Q12b did not
keep: (1) the FULL mass-vs-fraction curve (Q12b stored three points), (2) the
per-shard page ranking export (page id -> access rank, the S-realprofile
input), (3) the run-length clustering statistic of the measured hot set in
file order (the T1d-12 `hotsetc:h:m:E` comparison). Plus a determinism
fingerprint so two identical replays can be diffed exactly.

Method (unchanged from Q12b; counting, not timing — host/9p-independent)
------
- Query log: Zipf(s=1.0) over the 49 subjects of data/sfu_eval_queries.json,
  within-subject repeat with replacement, N draws from a pinned seed.
- Per query x shard: `MmapSeismicIndex.search_visited` (the read-only Q6/E5
  instrument in the served binding) returns the traversal's scored-candidate
  forward-record starts as u64 WORD offsets into forward_data.bin;
  byte = start*8, page = byte//4096. Served shape: top_k=50 -> k'=100,
  heap_factor=0.8, query_cut=all-terms, E8 dv-v2 manifest.
- A page is counted once per query (within-query dedup), accumulated across
  queries. Forward pages only (posting-list side is not in the count —
  q8_posting_fault_attribution.py covers that split).

Read-only over data/seismic_150m/ (IRREPLACEABLE). No serving-path change.

Usage (repo root, project venv):

    .venv/bin/python3 scripts/seismic_testbed/t1dprobe_access_histogram.py \
        --draws 1000 --seed 20260912 --run-tag run1
    .venv/bin/python3 scripts/seismic_testbed/t1dprobe_access_histogram.py \
        --draws 1000 --seed 20260912 --run-tag run2 --no-ranking

Outputs (under --out-dir, default data/eval_results):
    t1dprobe_querylog_<date>.json        the pinned query log (run1 writes it)
    t1dprobe_hist_<date>_<tag>.json      summary + full curves + clustering
    t1dprobe_ranking_<date>_<tag>.npz    per-shard (pages, counts) sorted by
                                         count desc (omitted with --no-ranking)
"""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

MANIFEST = REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5_v2.json"
QUERIES = REPO / "data" / "sfu_eval_queries.json"

PAGE = 4096
WORD = 8
ZIPF_S = 1.0
MASS_GRID = (0.50, 0.80, 0.90, 0.95, 0.99, 1.00)
SYNTHETIC_H_GRID = (0.05, 0.10, 0.20)
HOT_MASS_DEF = 0.80
RUN_BINS = (1, 2, 4, 8, 16, 64, 256)


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_production_log(seed: int, n_draws: int) -> tuple[list[str], dict]:
    """Q12b's builder, verbatim in semantics: Zipf(s) over subjects ordered by
    catalog size desc, then a uniform pick (with replacement) inside the drawn
    subject."""
    recs = json.loads(QUERIES.read_text())
    by_subject: dict[str, list[str]] = {}
    for r in recs:
        sub = r.get("subject") or "(none)"
        by_subject.setdefault(sub, []).append(r["query"])
    subjects = [s for s, _ in sorted(by_subject.items(),
                                     key=lambda kv: -len(kv[1]))]
    ranks = np.arange(1, len(subjects) + 1)
    weights = ranks ** (-ZIPF_S)
    weights = weights / weights.sum()
    rng = np.random.default_rng(seed)
    log_ids = rng.choice(len(subjects), size=n_draws, p=weights)
    queries = [by_subject[subjects[i]][rng.integers(len(by_subject[subjects[i]]))]
               for i in log_ids]
    subj_counts = Counter(subjects[i] for i in log_ids)
    q_counts = Counter(queries)
    meta = {
        "source": str(QUERIES.relative_to(REPO)),
        "n_real_queries": len(recs),
        "n_subjects": len(subjects),
        "zipf_s": ZIPF_S,
        "seed": seed,
        "n_draws": n_draws,
        "distinct_queries_drawn": len(q_counts),
        "queries_drawn_ge2": sum(1 for c in q_counts.values() if c >= 2),
        "max_query_repeat": max(q_counts.values()),
        "top_subjects": subj_counts.most_common(8),
    }
    return queries, meta


def lorenz(counts_desc: np.ndarray, total_pages: int) -> dict:
    """Mass-vs-fraction curve. `counts_desc` = touch counts sorted desc over
    the touched pages; `total_pages` = the denominator population (all forward
    pages of the shard/index). Pages beyond the touched set carry 0."""
    total = int(counts_desc.sum())
    cum = np.cumsum(counts_desc, dtype=np.int64)
    n_touched = int(counts_desc.size)

    def mass_at_pages(n: int) -> float:
        if n <= 0:
            return 0.0
        if n >= n_touched:
            return 1.0
        return float(cum[n - 1] / total)

    def pages_for_mass(m: float) -> int:
        if m >= 1.0:
            return n_touched
        return int(np.searchsorted(cum, m * total) + 1)

    fr_grid = np.unique(np.concatenate([
        np.logspace(-4, 0, 241),
        np.linspace(0.0, 1.0, 101),
        np.array(SYNTHETIC_H_GRID, dtype=np.float64),
    ]))
    curve_frac = [float(f) for f in fr_grid]
    curve_mass = [mass_at_pages(int(round(f * total_pages))) for f in fr_grid]
    ft_grid = np.unique(np.concatenate([np.logspace(-4, 0, 241),
                                        np.linspace(0.0, 1.0, 101)]))
    curve_ft_frac = [float(f) for f in ft_grid]
    curve_ft_mass = [mass_at_pages(int(round(f * n_touched))) for f in ft_grid]

    at_mass = {}
    for m in MASS_GRID:
        n = pages_for_mass(m)
        at_mass[f"{m:.2f}"] = {
            "pages": n,
            "gb": round(n * PAGE / 1e9, 4),
            "frac_of_forward": round(n / total_pages, 6),
            "frac_of_touched": round(n / n_touched, 6),
        }
    at_h = {}
    for h in SYNTHETIC_H_GRID:
        at_h[f"{h:.2f}"] = {
            "mass_top_h_of_forward": round(mass_at_pages(int(round(h * total_pages))), 6),
            "mass_top_h_of_touched": round(mass_at_pages(int(round(h * n_touched))), 6),
        }
    return {
        "curve_frac_of_forward": curve_frac,
        "curve_mass_forward": curve_mass,
        "curve_frac_of_touched": curve_ft_frac,
        "curve_mass_touched": curve_ft_mass,
        "at_mass": at_mass,
        "at_synthetic_h": at_h,
    }


def gini(counts: np.ndarray) -> float:
    c = np.sort(counts.astype(np.float64))
    n = len(c)
    if n == 0 or c.sum() == 0:
        return 0.0
    cum = np.cumsum(c)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def run_lengths(sorted_pages: np.ndarray) -> np.ndarray:
    """Lengths of maximal runs of consecutive page ids."""
    if sorted_pages.size == 0:
        return np.zeros(0, dtype=np.int64)
    breaks = np.flatnonzero(np.diff(sorted_pages) != 1)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [sorted_pages.size]))
    return (ends - starts).astype(np.int64)


def clustering(hot_pages_sorted: np.ndarray, total_pages: int) -> dict:
    rl = run_lengths(hot_pages_sorted)
    n_hot = int(hot_pages_sorted.size)
    if rl.size == 0:
        return {"n_hot_pages": 0}
    gaps = np.diff(hot_pages_sorted)
    gaps = gaps[gaps > 1] - 1
    share_in_runs_ge = {}
    for b in RUN_BINS:
        share_in_runs_ge[str(b)] = round(float(rl[rl >= b].sum() / n_hot), 6)
    hist = {}
    edges = list(RUN_BINS) + [10**9]
    for lo, hi in zip(edges[:-1], edges[1:]):
        hist[f"{lo}-{hi - 1 if hi < 10**9 else 'inf'}"] = int(((rl >= lo) & (rl < hi)).sum())
    return {
        "n_hot_pages": n_hot,
        "hot_frac_of_forward": round(n_hot / total_pages, 6),
        "n_extents": int(rl.size),
        "run_len_mean": round(float(rl.mean()), 4),
        "run_len_p50": int(np.percentile(rl, 50)),
        "run_len_p90": int(np.percentile(rl, 90)),
        "run_len_p99": int(np.percentile(rl, 99)),
        "run_len_max": int(rl.max()),
        "share_hot_pages_in_runs_ge": share_in_runs_ge,
        "run_len_hist": hist,
        "gap_pages_p50": int(np.percentile(gaps, 50)) if gaps.size else None,
        "gap_pages_mean": round(float(gaps.mean()), 2) if gaps.size else None,
        "uniform_random_expected_extents": round(
            n_hot * (1.0 - n_hot / total_pages), 1),
    }


def touches_hist(counts: np.ndarray, cap: int = 32) -> dict:
    hc = np.bincount(counts)
    out = {str(i): int(c) for i, c in enumerate(hc[:cap]) if c}
    tail = int(hc[cap:].sum()) if hc.size > cap else 0
    if tail:
        out[f"{cap}+"] = tail
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260912)
    ap.add_argument("--run-tag", default="run1")
    ap.add_argument("--date", default=time.strftime("%Y%m%d"))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "eval_results"))
    ap.add_argument("--shards", type=int, default=0,
                    help="limit to the first N shards (smoke only; 0 = all)")
    ap.add_argument("--no-ranking", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = args.run_tag

    from lib.thinclient.sharded_seismic_backend import (
        _load_manifest, _load_one_shard, _prepare_query, _EncoderShim)
    import seismic

    queries, qmeta = build_production_log(args.seed, args.draws)
    qlog_sha = hashlib.sha256("\n".join(queries).encode()).hexdigest()
    qmeta["querylog_sha256"] = qlog_sha
    log(f"query log: {len(queries)} draws, {qmeta['n_subjects']} subjects, "
        f"{qmeta['distinct_queries_drawn']} distinct, max repeat "
        f"{qmeta['max_query_repeat']}, sha256 {qlog_sha[:12]}")
    if not args.no_ranking:
        (out_dir / f"t1dprobe_querylog_{args.date}.json").write_text(
            json.dumps({**qmeta, "queries": queries}, indent=1))

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    if args.shards:
        paths = paths[: args.shards]
    shards = [_load_one_shard(seismic, p, "mmap") for p in paths]
    string_dtype = seismic.get_seismic_string()
    log(f"loaded {len(shards)} shards (mmap, E8 dv-v2)")

    fwd_pages = []
    version_keys = []
    for p in paths:
        man = json.loads((Path(p) if Path(p).is_absolute() else REPO / p)
                         .joinpath("manifest.json").read_text())
        fwd_pages.append(int(man["forward_data_words"]) * WORD // PAGE)
        version_keys.append({
            "forward_format": man.get("forward_format"),
            "forward_format_version": man.get("forward_format_version"),
            "forward_reordered": man.get("forward_reordered"),
            "forward_data_words": man.get("forward_data_words"),
        })

    encoder = _EncoderShim("models/splade_onnx_fused")

    def encode(q: str) -> dict:
        from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS
        sparse = encoder.encode_splade(q)
        if not sparse:
            return {}
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def visited_pages(q: dict) -> list[np.ndarray]:
        qcomp, qvals, qc, kp = _prepare_query(q, 50, string_dtype, None, None)
        out = []
        for idx in shards:
            _res, visited = idx.search_visited(
                "q", qcomp, qvals, k=kp, query_cut=qc, heap_factor=0.8)
            out.append(np.unique(np.asarray(visited, dtype=np.uint64) * WORD // PAGE))
        return out

    per_shard_counts = [np.zeros(n, dtype=np.uint32) for n in fwd_pages]
    per_query_pages = []
    n_skipped = 0
    t_start = time.time()
    for i, ptext in enumerate(queries):
        q = encode(ptext)
        if not q:
            n_skipped += 1
            continue
        pages = visited_pages(q)
        per_query_pages.append(int(sum(p.size for p in pages)))
        for arr, p in zip(per_shard_counts, pages):
            arr[p.astype(np.int64)] += 1
        if i % 50 == 0 or i == len(queries) - 1:
            log(f"  q{i:4d}/{len(queries)}: {per_query_pages[-1]} pages, "
                f"elapsed {time.time() - t_start:.0f}s")
    elapsed = time.time() - t_start

    h = hashlib.sha256()
    for arr in per_shard_counts:
        h.update(arr.tobytes())
    counts_sha = h.hexdigest()
    log(f"counts fingerprint sha256 {counts_sha[:16]} ({elapsed:.0f}s)")

    shard_out = []
    hot_sorted_per_shard = []
    rankings = {}
    for si, (arr, n_fwd) in enumerate(zip(per_shard_counts, fwd_pages)):
        touched = np.flatnonzero(arr)
        c = arr[touched].astype(np.int64)
        order = np.lexsort((touched, -c))
        pages_desc = touched[order]
        counts_desc = c[order]
        cum = np.cumsum(counts_desc)
        n_hot = int(np.searchsorted(cum, HOT_MASS_DEF * cum[-1]) + 1) if cum.size else 0
        hot_sorted = np.sort(pages_desc[:n_hot])
        hot_sorted_per_shard.append(hot_sorted)
        cl = clustering(hot_sorted, n_fwd)
        lz = lorenz(counts_desc, n_fwd)
        shard_out.append({
            "shard": si,
            "mmap_dir": str(paths[si]),
            "version_keys": version_keys[si],
            "forward_total_pages": n_fwd,
            "distinct_pages_touched": int(touched.size),
            "touched_frac_of_forward": round(touched.size / n_fwd, 6),
            "total_touches": int(c.sum()),
            "gini_touched_pages": round(gini(c), 4),
            "hot80_pages": n_hot,
            "hot80_gb": round(n_hot * PAGE / 1e9, 4),
            "hot80_frac_of_forward": round(n_hot / n_fwd, 6),
            "at_mass": lz["at_mass"],
            "at_synthetic_h": lz["at_synthetic_h"],
            "curve_frac_of_forward": lz["curve_frac_of_forward"],
            "curve_mass_forward": lz["curve_mass_forward"],
            "clustering_hot80": cl,
        })
        rankings[f"shard{si}_pages"] = pages_desc.astype(np.uint32)
        rankings[f"shard{si}_counts"] = counts_desc.astype(np.uint32)

    all_counts = np.concatenate([arr[arr > 0].astype(np.int64) for arr in per_shard_counts])
    all_desc = np.sort(all_counts)[::-1]
    total_fwd = int(sum(fwd_pages))
    total_touches = int(all_desc.sum())
    distinct = int(all_desc.size)
    pooled_lz = lorenz(all_desc, total_fwd)
    pooled_rl = np.concatenate([run_lengths(hs) for hs in hot_sorted_per_shard])
    n_hot_pooled = int(sum(hs.size for hs in hot_sorted_per_shard))
    pooled_cl = {
        "n_hot_pages": n_hot_pooled,
        "hot_frac_of_forward": round(n_hot_pooled / total_fwd, 6),
        "n_extents": int(pooled_rl.size),
        "run_len_mean": round(float(pooled_rl.mean()), 4),
        "run_len_p50": int(np.percentile(pooled_rl, 50)),
        "run_len_p90": int(np.percentile(pooled_rl, 90)),
        "run_len_p99": int(np.percentile(pooled_rl, 99)),
        "run_len_max": int(pooled_rl.max()),
        "share_hot_pages_in_runs_ge": {
            str(b): round(float(pooled_rl[pooled_rl >= b].sum() / n_hot_pooled), 6)
            for b in RUN_BINS},
        "run_len_hist": {
            f"{lo}-{hi - 1 if hi < 10**9 else 'inf'}": int(((pooled_rl >= lo) & (pooled_rl < hi)).sum())
            for lo, hi in zip(list(RUN_BINS) + [10**9], (list(RUN_BINS) + [10**9])[1:])},
        "uniform_random_expected_extents": round(
            n_hot_pooled * (1.0 - n_hot_pooled / total_fwd), 1),
        "note": "per-shard hot80 sets (each shard's own 0.80-mass prefix), "
                "run lengths pooled; extents never span shard files",
    }

    result = {
        "probe": "t1dprobe_access_histogram",
        "date": args.date,
        "run_tag": tag,
        "preregistration": "spike/convergence_repro/PREREGISTRATION_T1D_PROBE.md section 7",
        "prior_measurement": "Q12b data/eval_results/q12b_access_skew_production_20260714.json",
        "manifest": str(MANIFEST.relative_to(REPO)),
        "n_shards": len(shards),
        "served_shape": {"top_k": 50, "k_prime": 100, "heap_factor": 0.8,
                         "query_cut": "all-terms"},
        "query_log": qmeta,
        "n_queries_executed": len(per_query_pages),
        "n_queries_skipped_empty_encode": n_skipped,
        "counts_sha256": counts_sha,
        "pages_per_query_mean": round(float(np.mean(per_query_pages)), 2),
        "pages_per_query_p50": float(np.median(per_query_pages)),
        "forward_total_pages": total_fwd,
        "forward_total_gb": round(total_fwd * PAGE / 1e9, 3),
        "total_touches": total_touches,
        "distinct_pages_touched": distinct,
        "touched_frac_of_forward": round(distinct / total_fwd, 6),
        "repeat_pages_ge2": int((all_desc >= 2).sum()),
        "repeat_touch_frac": round(float(all_desc[all_desc >= 2].sum() / total_touches), 4),
        "top1pct_touch_share": round(float(all_desc[: max(1, distinct // 100)].sum() / total_touches), 4),
        "top10pct_touch_share": round(float(all_desc[: max(1, distinct // 10)].sum() / total_touches), 4),
        "gini_touched_pages": round(gini(all_counts), 4),
        "hotset_50_gb": pooled_lz["at_mass"]["0.50"]["gb"],
        "hotset_80_gb": pooled_lz["at_mass"]["0.80"]["gb"],
        "hotset_90_gb": pooled_lz["at_mass"]["0.90"]["gb"],
        "pooled": {
            "at_mass": pooled_lz["at_mass"],
            "at_synthetic_h": pooled_lz["at_synthetic_h"],
            "curve_frac_of_forward": pooled_lz["curve_frac_of_forward"],
            "curve_mass_forward": pooled_lz["curve_mass_forward"],
            "curve_frac_of_touched": pooled_lz["curve_frac_of_touched"],
            "curve_mass_touched": pooled_lz["curve_mass_touched"],
            "touches_per_page_hist": touches_hist(all_counts),
            "clustering_hot80": pooled_cl,
        },
        "shards": shard_out,
        "elapsed_s": round(elapsed, 1),
    }
    hist_path = out_dir / f"t1dprobe_hist_{args.date}_{tag}.json"
    hist_path.write_text(json.dumps(result, indent=1))
    log(f"wrote {hist_path}")
    if not args.no_ranking:
        rk_path = out_dir / f"t1dprobe_ranking_{args.date}_{tag}.npz"
        np.savez_compressed(rk_path, forward_total_pages=np.array(fwd_pages, dtype=np.int64),
                            **rankings)
        log(f"wrote {rk_path}")
    for k in ("n_queries_executed", "pages_per_query_p50", "distinct_pages_touched",
              "touched_frac_of_forward", "repeat_touch_frac", "gini_touched_pages",
              "hotset_50_gb", "hotset_80_gb", "hotset_90_gb", "counts_sha256", "elapsed_s"):
        log(f"  {k}: {result[k]}")
    am = pooled_lz["at_mass"]
    log(f"  h at 0.80 mass: {am['0.80']['frac_of_forward']} of forward / "
        f"{am['0.80']['frac_of_touched']} of touched")
    log(f"  mass at synthetic h: {pooled_lz['at_synthetic_h']}")
    log(f"  clustering hot80: extents {pooled_cl['n_extents']}, run p50 "
        f"{pooled_cl['run_len_p50']}, p90 {pooled_cl['run_len_p90']}, max "
        f"{pooled_cl['run_len_max']}")


if __name__ == "__main__":
    main()
