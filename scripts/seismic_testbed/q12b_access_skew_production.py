#!/usr/bin/env python3
"""Q12b (2026-07-14): access-skew probe against a PRODUCTION-SHAPED query log
on the served E8 v2 shards. Pre-registered BEFORE the run in
docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q12b (commit e793f2b).

The Phase-0b gate (G-a) of the disk-streaming research program
(docs/disk_streaming_research/03_MIN_RAM_DESIGN_MAP.md). Q12 (2026-07-13)
measured the colibrì hot-set premise on a 120-DIVERSE query set and landed
GRAY (live-leaning: repeat 0.852 PASS, hot-set-80 4.20 GB vs the 4 GB bar —
missed by 5%). Q12's recorded caveat: the eval set is diversity-MAXIMIZED,
real library traffic repeats subjects far more, so a skew finding on the
diverse set is conservative. This probe re-tests on a query log that
EMULATES that production repeat structure.

Production shape (the documented property, made concrete)
---------------------------------------------------------
- Source: data/sfu_eval_queries.json — 120 REAL SFU queries across 49 subjects
  (the operational query catalog, not a paraphrase-generated eval set).
- Subject distribution: Zipf(s=1.0) over the 49 subjects — a few hot subjects
  dominate draws (real library traffic is subject-skewed, not uniform). This
  is the lever the diverse set suppresses.
- Within-subject repeat: once a subject is drawn, ALL its queries are eligible
  and the same query recurs (a drawn subject contributes its queries with
  replacement → intra-subject repeat, the production "same user re-searches"
  pattern). This concentrates touches onto fewer pages than the diverse set.
- N = 400 draws (≥3× Q12's 120; tightens the coverage-curve estimate).

Same instrument as Q12 (read-only, no serving change): per query × shard,
`search_visited` returns u64 WORD offsets into forward_data.bin → byte*8 →
page//4096; within-query dedup, cross-query accumulate; coverage curve =
sorted-by-touch-count pages covering 50/80/90% of touches.

Decision rule (unchanged from Q12 — pre-registered §Q12b):
  hot-set-80 <= 4 GB AND repeat_touch_frac >= 0.25  -> GO
  hot-set-80 > 8 GB OR repeat_touch_frac < 0.10     -> hard NO-GO
  between                                          -> GRAY (proceed)
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# The flipped served manifest (E8 dv-v2, 2026-07-14). Q12 used the E5 dv-v1
# manifest; the v2 reconversion invalidated any prior sidecar, hence the rerun.
MANIFEST = REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5_v2.json"
QUERIES = REPO / "data" / "sfu_eval_queries.json"
OUT = REPO / "data" / "eval_results" / (
    "q12b_access_skew_production_" + time.strftime("%Y%m%d") + ".json")

PAGE = 4096
WORD = 8  # dv visited starts are u64 word offsets into forward_data.bin
N_DRAWS = 400            # production-shaped query-log length
ZIPF_S = 1.0             # Zipf exponent over subjects (s=1 → strong skew)
SEED = 20260714          # deterministic (Date.now/random unavailable in WF scripts)


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


def build_production_log(seed: int) -> list[str]:
    """Build the production-shaped query log from sfu_eval_queries.json.

    Zipf-weighted subject draws (a few hot subjects dominate) + within-subject
    repeat (each draw picks one of that subject's queries with replacement).
    Returns a list of query strings of length N_DRAWS."""
    recs = json.loads(QUERIES.read_text())
    by_subject: dict[str, list[str]] = {}
    for r in recs:
        sub = r.get("subject") or "(none)"
        by_subject.setdefault(sub, []).append(r["query"])
    subjects = list(by_subject.keys())
    # Zipf(s) PMF over ranks 1..K: p(k) = (1/k^s) / H_K,s — s=1 → harmonic.
    ranks = np.arange(1, len(subjects) + 1)
    weights = 1.0 / np.power(ranks, ZIPF_S)
    weights = weights / weights.sum()
    rng = np.random.default_rng(seed)
    # Order subjects by their catalog size DESC so the Zipf weight lands on the
    # most populous subjects first (a hotter head than arbitrary order).
    subjects = [s for s, _ in sorted(by_subject.items(),
                                     key=lambda kv: -len(kv[1]))]
    log_ids = rng.choice(len(subjects), size=N_DRAWS, p=weights)
    queries = [by_subject[subjects[i]][rng.integers(len(by_subject[subjects[i]]))]
               for i in log_ids]
    return queries


def main():
    from lib.thinclient.sharded_seismic_backend import (
        _load_manifest, _load_one_shard, _prepare_query, _EncoderShim)
    import seismic

    # ── production-shaped query log ──────────────────────────────────────────
    queries = build_production_log(SEED)
    subj_counts = Counter()
    for q in queries:
        subj_counts[q] += 1
    # Re-derive subject of each query for reporting.
    recs = json.loads(QUERIES.read_text())
    q2subj = {r["query"]: r.get("subject", "(none)") for r in recs}
    s_counts = Counter(q2subj[q] for q in queries)
    log(f"production log: {len(queries)} draws, {len(s_counts)} subjects, "
        f"top subjects: {s_counts.most_common(5)}")
    log(f"query repeat: {sum(1 for _,c in subj_counts.items() if c>=2)} "
        f"queries drawn >=2x; max repeat {max(subj_counts.values())}")

    # ── shards (served E8 v2 manifest, mmap) ──────────────────────────────────
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    shards = [_load_one_shard(seismic, p, "mmap") for p in paths]
    string_dtype = seismic.get_seismic_string()
    log(f"loaded {len(shards)} shards (mmap, E8 v2): "
        f"{[Path(p).name for p in paths]}")

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

    # ── primary pass: cross-query page-touch histogram ───────────────────────
    per_shard_counts: list[Counter] = [Counter() for _ in shards]
    per_query_pages = []  # n unique pages per query (pooled over shards)
    t_start = time.time()
    for i, ptext in enumerate(queries):
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
        if i % 25 == 0 or i == len(queries) - 1:
            log(f"  q{i:3d}/{len(queries)}: {n_pages} pages touched, "
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
    # Q12 def: share of touches landing on pages some other query also touched.
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

    # ── verdict under the pre-registered rule ─────────────────────────────────
    hot80_gb = curve["hotset_80_gb"]
    if hot80_gb <= 4 and repeat_touch_frac >= 0.25:
        verdict = "GO"
    elif hot80_gb > 8 or repeat_touch_frac < 0.10:
        verdict = "NO-GO"
    else:
        verdict = "GRAY"

    result = {
        "probe": "q12b_access_skew_production",
        "date": time.strftime("%Y-%m-%d"),
        "preregistration": "docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q12b",
        "manifest": str(MANIFEST.relative_to(REPO)),
        "forward_format_version": 2,
        "production_shape": {
            "source": "data/sfu_eval_queries.json",
            "n_real_queries": len(recs),
            "n_subjects": len(set(r.get("subject") for r in recs)),
            "n_draws": N_DRAWS,
            "zipf_s": ZIPF_S,
            "seed": SEED,
            "repeat_emphasis": "Zipf-weighted subjects + within-subject-with-replacement",
            "rationale": "Q12's diverse set is diversity-maximized (suppresses the "
                         "subject-skew real library traffic has); this emulates it. "
                         "A skew finding on Q12 is conservative vs this probe.",
        },
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
        "decision_bars": {
            "live_if": "hotset_80_gb <= 4 AND repeat_touch_frac >= 0.25",
            "close_if": "hotset_80_gb > 8 OR repeat_touch_frac < 0.10",
        },
        "verdict": verdict,
        "vs_q12_diverse": {
            "q12_repeat_touch_frac": 0.852,
            "q12_hotset_80_gb": 4.20,
            "q12_top10pct_share": 0.342,
            "q12_gini": 0.442,
        },
        "elapsed_s": round(time.time() - t_start, 1),
    }
    OUT.write_text(json.dumps(result, indent=2))
    log(f"wrote {OUT}")
    for k, v in result.items():
        if k not in ("decision_bars", "vs_q12_diverse", "production_shape",
                     "served_shape"):
            log(f"  {k}: {v}")
    log(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
