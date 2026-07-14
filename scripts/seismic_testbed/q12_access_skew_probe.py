#!/usr/bin/env python3
"""Q12 (2026-07-13): access-skew / hot-set telemetry probe — pre-registered in
docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q12 BEFORE this run.

The cheapest validity test of the colibrì-transfer premise
(docs/disk_streaming_research/01_CROSS_PROJECT_RESEARCH.md candidate #1):
does real SPLADE query traffic touch the mmap'd dv forward index with enough
page-level SKEW that a small software-pinned hot set (colibrì `eusage`/`pin`
analog) could absorb a material share of cold faults? Read-only: uses the
existing pyo3 `search_visited` (Q6/E5 instrument) — no serving change, no new
Rust, results identical to `search`.

Method
------
- n=120 topic-independent queries (1 paraphrase per `original_query` in
  `data/eval_results/diverse_queries.json`), served shape (top_k=50 → k'=100,
  heap_factor=0.8, query_cut=all-terms), E5 dv manifest (the served default).
- Per query × shard: `search_visited` returns the traversal's scored-candidate
  forward-range starts = u64 WORD offsets into `forward_data.bin` (dv layout,
  mmap_io.rs `search_raw_visited` doc) → byte = start*8 → page = byte//4096.
  dv records average ~165 B ≪ 4 KiB, so the start page ≈ the touched page
  (recorded caveat: long records straddling a boundary undercount by ≤1 page).
- Histogram page touches across queries (a page is counted once per query —
  within-query dedup, cross-query accumulation; the colibrì-analog "would this
  page have been warm from an earlier query" statistic).
- Secondary: within-topic paraphrase overlap on the first 20 topics × 3
  paraphrases (repeat-traffic upper bound; NOT part of the decision rule).

Shards are searched serially in-process WITHOUT release_pages — the touch
pattern is traversal-determined and residency-independent, and we do not want
mechanism-B eviction distorting wall-time (wall-time is not a Q12 metric).
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

MANIFEST = REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5.json"
QUERIES = REPO / "data" / "eval_results" / "diverse_queries.json"
OUT = REPO / "data" / "eval_results" / (
    "q12_access_skew_probe_" + time.strftime("%Y%m%d") + ".json")

PAGE = 4096
WORD = 8  # dv visited starts are u64 word offsets into forward_data.bin
N_TOPICS = 120
N_PARA_TOPICS = 20  # secondary within-topic stat


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def coverage_curve(counts: np.ndarray, fracs=(0.5, 0.8, 0.9)) -> dict:
    """Pages sorted by touch count desc; how many pages (and GB) cover each
    fraction of total touches."""
    c = np.sort(counts)[::-1]
    total = int(c.sum())
    cum = np.cumsum(c)
    out = {}
    for f in fracs:
        n_pages = int(np.searchsorted(cum, f * total) + 1)
        out[f"hotset_{int(f*100)}_pages"] = n_pages
        out[f"hotset_{int(f*100)}_gb"] = round(n_pages * PAGE / 1e9, 4)
    return out


def gini(counts: np.ndarray) -> float:
    """Gini over TOUCHED pages only (untouched pages excluded — recorded)."""
    c = np.sort(counts.astype(np.float64))
    n = len(c)
    if n == 0 or c.sum() == 0:
        return 0.0
    cum = np.cumsum(c)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def main():
    from lib.thinclient.sharded_seismic_backend import (
        _load_manifest, _load_one_shard, _prepare_query, _EncoderShim)
    import seismic

    # ── queries: 1 paraphrase per topic (independent), + 20×3 paraphrase set ──
    recs = json.loads(QUERIES.read_text())
    by_topic: dict[str, list[str]] = {}
    for r in recs:
        by_topic.setdefault(r["original_query"], []).append(r["paraphrase"])
    topics = list(by_topic.keys())[:N_TOPICS]
    primary = [(t, by_topic[t][0]) for t in topics]
    para_set = [(t, p) for t in topics[:N_PARA_TOPICS] for p in by_topic[t][:3]]
    log(f"{len(primary)} primary topic queries, "
        f"{len(para_set)} paraphrase queries ({N_PARA_TOPICS} topics x3)")

    # ── shards (served E5 dv manifest, mmap) ──────────────────────────────────
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    shards = [_load_one_shard(seismic, p, "mmap") for p in paths]
    string_dtype = seismic.get_seismic_string()
    log(f"loaded {len(shards)} shards (mmap, E5 dv)")

    encoder = _EncoderShim("models/splade_onnx_fused")

    def encode(q: str) -> dict:
        from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS
        sparse = encoder.encode_splade(q)
        if not sparse:
            return {}
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def visited_pages(q: dict) -> list[set]:
        """Per-shard set of touched forward_data 4KiB page ids for one query."""
        qcomp, qvals, qc, kp = _prepare_query(q, 50, string_dtype, None, None)
        out = []
        for idx in shards:
            _res, visited = idx.search_visited(
                "q", qcomp, qvals, k=kp, query_cut=qc, heap_factor=0.8)
            pages = np.unique(np.asarray(visited, dtype=np.uint64) * WORD // PAGE)
            out.append(set(pages.tolist()))
        return out

    # ── primary pass: cross-topic page-touch histogram ────────────────────────
    per_shard_counts: list[Counter] = [Counter() for _ in shards]
    per_query_pages = []  # n unique pages per query (pooled over shards)
    t_start = time.time()
    for i, (_t, ptext) in enumerate(primary):
        q = encode(ptext)
        if not q:
            log(f"  q{i}: encode empty, skipped")
            continue
        t0 = time.time()
        shard_pages = visited_pages(q)
        n_pages = sum(len(s) for s in shard_pages)
        per_query_pages.append(n_pages)
        for c, s in zip(per_shard_counts, shard_pages):
            c.update(s)
        if i % 10 == 0 or i == len(primary) - 1:
            log(f"  q{i:3d}/{len(primary)}: {n_pages} pages touched, "
                f"{time.time()-t0:.1f}s (elapsed {time.time()-t_start:.0f}s)")

    n_q = len(per_query_pages)
    pooled = Counter()
    for si, c in enumerate(per_shard_counts):
        for page, n in c.items():
            pooled[(si, page)] = n
    counts = np.array(list(pooled.values()), dtype=np.int64)
    total_touches = int(counts.sum())
    distinct = len(counts)
    repeat_pages = int((counts >= 2).sum())
    # touch-weighted repeat fraction: share of touches landing on pages some
    # OTHER query also touched = (touches on count>=2 pages - one "first" touch
    # each) is a stricter def; the pre-registered def is touches on count>=2
    # pages / total touches.
    repeat_touch_frac = float(counts[counts >= 2].sum() / total_touches)
    curve = coverage_curve(counts)
    srt = np.sort(counts)[::-1]
    top10pct_share = float(srt[: max(1, len(srt) // 10)].sum() / total_touches)
    top1pct_share = float(srt[: max(1, len(srt) // 100)].sum() / total_touches)

    # forward_data.bin total pages across shards (denominator for uniformity)
    fwd_total_bytes = 0
    for p in paths:
        man = json.loads((Path(p) if Path(p).is_absolute() else REPO / p)
                         .joinpath("manifest.json").read_text())
        fwd_total_bytes += man["forward_data_words"] * 8
    fwd_total_pages = fwd_total_bytes // PAGE

    # ── secondary pass: within-topic paraphrase overlap (upper bound) ─────────
    log("secondary: within-topic paraphrase overlap (20 topics x 3)")
    topic_pages: dict[str, list[set]] = {}
    for (t, ptext) in para_set:
        q = encode(ptext)
        if not q:
            continue
        shard_pages = visited_pages(q)
        pool = set()
        for si, s in enumerate(shard_pages):
            pool.update((si, p) for p in s)
        topic_pages.setdefault(t, []).append(pool)
    jaccards, second_hit = [], []
    for t, plist in topic_pages.items():
        for a in range(len(plist)):
            for b in range(a + 1, len(plist)):
                inter = len(plist[a] & plist[b])
                union = len(plist[a] | plist[b])
                if union:
                    jaccards.append(inter / union)
                # "cache view": fraction of b's pages already warm from a
                if plist[b]:
                    second_hit.append(inter / len(plist[b]))

    result = {
        "probe": "q12_access_skew",
        "date": time.strftime("%Y-%m-%d"),
        "preregistration": "docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q12",
        "manifest": str(MANIFEST.relative_to(REPO)),
        "served_shape": {"top_k": 50, "k_prime": 100, "heap_factor": 0.8,
                          "query_cut": "all-terms"},
        "n_queries_primary": n_q,
        "pages_per_query_mean": float(np.mean(per_query_pages)),
        "pages_per_query_p50": float(np.median(per_query_pages)),
        "total_touches": total_touches,
        "distinct_pages_touched": distinct,
        "forward_total_pages": int(fwd_total_pages),
        "touched_frac_of_forward": round(distinct / fwd_total_pages, 6),
        "repeat_pages_ge2": repeat_pages,
        "repeat_page_frac": round(repeat_pages / distinct, 4),
        "repeat_touch_frac": round(repeat_touch_frac, 4),
        "top1pct_touch_share": round(top1pct_share, 4),
        "top10pct_touch_share": round(top10pct_share, 4),
        "gini_touched_pages": round(gini(counts), 4),
        **curve,
        "within_topic": {
            "n_topics": len(topic_pages),
            "pairwise_jaccard_mean": round(float(np.mean(jaccards)), 4) if jaccards else None,
            "pairwise_jaccard_p50": round(float(np.median(jaccards)), 4) if jaccards else None,
            "second_query_warm_hit_mean": round(float(np.mean(second_hit)), 4) if second_hit else None,
        },
        "decision_bars": {
            "live_if": "hotset_80_gb <= 4 AND repeat_touch_frac >= 0.25",
            "close_if": "hotset_80_gb > 8 OR repeat_touch_frac < 0.10",
        },
        "elapsed_s": round(time.time() - t_start, 1),
    }
    OUT.write_text(json.dumps(result, indent=2))
    log(f"wrote {OUT}")
    for k, v in result.items():
        if k not in ("decision_bars",):
            log(f"  {k}: {v}")


if __name__ == "__main__":
    main()
