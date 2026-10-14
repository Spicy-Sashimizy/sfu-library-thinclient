#!/usr/bin/env python3
"""SEISMIC testbed — E1: query_cut × k' sweep on one 150M mmap shard, and a
labeled negative control that KILLS the naive df-aware-subset idea.

`docs/seismic_150m_testbed/09_CROSS_SHARD_MMAP_AUDIT.md` §4 E1. Running this
CORRECTED the audit's §2.1 mechanism claim, so read this header, not §2.1.

**The mechanism, verified in-run (2026-07-02):** SEISMIC's `query_cut` is a
candidate-**gather** cut, NOT a scoring cut. `search_raw` (mmap_io.rs:640-670)
builds the forward-scoring evaluator from the FULL query vector you pass, then
visits only the top-`query_cut` posting lists (by weight, `k_largest_by`,
mmap_io.rs:651) to GATHER candidates; every gathered candidate is re-scored
against the full query. So:
  - pass ALL terms + small query_cut  → fewer lists traversed, full-query
    scoring preserved → recall ~unchanged (measured overlap@10 = 1.00 down to
    query_cut=5 on the 18.8M shard).
  - pass a pre-CUT term subset          → the scoring vector is truncated too →
    ranking changes (measured overlap@10 ≈ 0.6 for a top-10-weight subset).

**Consequence for the audit's df idea:** df-aware term *selection* done from
Python is the WRONG lever — it can only shrink the passed vector, which corrupts
scoring. A df-aware GATHER (choose which lists to visit by weight×idf instead of
weight) lives INSIDE the engine's `k_largest_by` and is not a query-time knob;
it would need an engine change. The naive subset is kept here only as a
NEGATIVE CONTROL that demonstrates the degradation, so the kill is on record.

The two levers that ARE query-time and free:
1. **query_cut (all terms passed).** {5,10,15,20,all} — fewer posting lists
   traversed → fewer summary/block reads → fewer forward candidate faults.
2. **k' (heap size / per-shard over-fetch).** {50,100,200}; served default 4×k
   = 200 (`_prepare_query`, sharded_seismic_backend.py:195). Smaller k' fills
   the heap sooner → k-th score rises → the `heap_factor` block-skip test
   (mmap_index.rs:313) rejects more blocks → fewer faults. Audit §2.2: under
   uniform hash sharding the global top-50 spreads ~Binomial(50,1/8)/shard, so
   200 is generously oversized.

**Pages-touched measured directly per cell**: before each cell's first pass we
call the C2.5 `release_pages()` hook (`MADV_DONTNEED` on every slab, mechanism
B, shipped 2026-06-30), so the first pass re-faults from disk and the process
`majflt` delta is a real pages proxy; warm traverse p50 then comes from
WARM_REPEATS repeats per query (mirrors the C1 harness). Same query order in
every cell → majflt deltas comparable.

Overlap@10 is vs the recall-max baseline (all terms, query_cut=all, hf=0.8,
k'=200) — self-relative recall, same convention as the C1 sweep, single shard,
NOT vs a live Qdrant.

**Pre-registered kill criterion (audit §4 E1):** the lever pair is DEAD unless
some cell beats the reference (all terms, query_cut=10, hf=0.8, k'=200) by
≥1.3× warm traversal at overlap@10 ≥ 0.99.

**DOI-grouping piggyback (audit §1.3-iii):** the baseline top-50 per query is
joined against the global meta.sqlite `docs.doi`; we report how often ≥2 docs
in a top-50 share a DOI (the version-grouping prevalence that was UNMEASURED).

RAM discipline (audit rules): ONE shard, load_mode mmap only, ≤100 queries,
RssAnon/RssFile/VmRSS/VmSwap recorded before load / after load / at end.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/e1_kprime_df_sweep.py \
        --mmap-dir data/seismic_150m/index/plan01/global_shard0of8.mmap \
        --queries 40 \
        --result-file data/eval_results/seismic_e1_kprime_df_sweep.json
"""
import argparse
import json
import logging
import math
import sqlite3
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("e1_sweep")

TOP_K = 50                 # served leg fetch depth (RRF fetch @50)
OVERLAP_K = 10
WARM_REPEATS = 5           # per-query warm traverse repeats (p50) — mirrors C1
HEAP_FACTOR = 0.8          # fixed: C1 measured the 0.6–0.8 band inert-to-mild
K_PRIMES = [50, 100, 200]  # {k, 2k, 4k} for top_k=50; 200 = the served default
QUERY_CUTS = [5, 10, 15, 20]   # gather-cut (ALL terms passed); vs the all-terms baseline
SPLADE_QUERY_TERMS = 64    # serving constant (retriever.py:101)


# ── df table: pure file reads off the shard's own mmap dir ──────────────────

def load_token_df(mmap_dir: Path) -> tuple[dict[str, int], int]:
    """token string -> pruned df (packed_postings_words) for ONE shard.

    token_to_id_map.bin is bincode 2.x serde fixed-int little-endian:
    u64 count, then per entry (u64 strlen, utf8 bytes, u64 id). Verified
    byte-exact against the manifest (28,702 entries == n_posting_lists,
    ids 0..28,701) on shard0, 2026-07-02. The manifest's posting_lists array
    is indexed by that id; packed_postings_words = pruned posting count.

    Under blake2b hash sharding every shard is a uniform 1/8 sample (audit
    §1.1), so shard0's df ordering ≈ the global ordering; and shard0's df IS
    the exact per-list cost this sweep's shard pays."""
    raw = (mmap_dir / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off); off += 8
    tok2id: dict[str, int] = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off); off += 8
        s = raw[off:off + slen].decode("utf-8"); off += slen
        (v,) = struct.unpack_from("<Q", raw, off); off += 8
        tok2id[s] = v
    assert off == len(raw), f"token map trailing bytes ({off} != {len(raw)})"
    man = json.loads((mmap_dir / "manifest.json").read_text())
    pls = man["posting_lists"]
    assert len(pls) == count, "manifest/token-map cardinality mismatch"
    df = {tok: pls[i]["packed_postings_words"] for tok, i in tok2id.items()}
    return df, man["n_docs"]


# ── term selection modes (Python-side; engine sees only the chosen subset) ──

def select_terms(q64: dict[str, float], mode: str, qc: int | None,
                 df: dict[str, int], n_docs: int) -> dict[str, float]:
    """Return the term subset a cell searches with. Only vocab-present tokens
    are considered (the engine's resolve_query_tokens drops unknowns BEFORE its
    own weight cut, mmap_io.rs:619-623, so this is symmetric with the engine).
    mode=weight reproduces the engine's own k_largest_by-weight cut exactly."""
    known = {t: w for t, w in q64.items() if t in df}
    if qc is None or qc >= len(known):
        return known
    if mode == "weight":
        ranked = sorted(known.items(), key=lambda x: (-x[1], x[0]))
    elif mode == "idf":
        ranked = sorted(known.items(),
                        key=lambda x: (-x[1] * math.log(n_docs / (1 + df[x[0]])), x[0]))
    else:
        raise ValueError(mode)
    return dict(ranked[:qc])


# ── /proc probes ─────────────────────────────────────────────────────────────

def read_rss() -> dict[str, float]:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for key in ("RssAnon", "RssFile", "VmRSS", "VmSwap"):
            if line.startswith(key + ":"):
                out[key.lower() + "_gb"] = round(int(line.split()[1]) / 1e6, 3)
    return out


def read_majflt() -> int:
    # /proc/self/stat: majflt is field 12 (1-indexed); comm==(python3), no spaces.
    return int(Path("/proc/self/stat").read_text().split()[11])


# ── the sweep ────────────────────────────────────────────────────────────────

def load_queries(n: int, qpath: Path) -> list[str]:
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        if rec["paraphrase"] not in seen:
            seen.add(rec["paraphrase"])
            out.append(rec["paraphrase"])
        if len(out) >= n:
            break
    return out


def search_once(idx, string_dtype, terms: dict[str, float], kp: int, qc: int | None):
    """One search. `terms` is the term vector PASSED to the engine (full-query
    scoring uses it); `qc` is the gather cut (None → len(terms) = visit all
    passed lists). The negative-control cells pass a shrunken `terms`; the real
    lever cells pass the full vector and shrink `qc`."""
    qcomp = np.array(list(terms.keys()), dtype=string_dtype)
    qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
    qcut = qc if qc is not None else len(terms)
    t0 = time.perf_counter()
    res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                     k=kp, query_cut=qcut, heap_factor=HEAP_FACTOR)
    ms = (time.perf_counter() - t0) * 1000
    return [doc_id for (_q, _d, doc_id) in res], ms


def run_cell(idx, string_dtype, per_query_terms: list[dict[str, float]],
             kp: int, qc: int | None, base_top10: list[list[str]] | None):
    """One cell: release pages → cold pass (majflt + cold traverse) → warm
    repeats (p50). `per_query_terms` is the term vector passed per query; `qc`
    the gather cut. Returns the cell dict (+ per-query top10 when this IS the
    baseline, i.e. base_top10 is None)."""
    released = idx.release_pages()
    assert released > 0, "release_pages covered no ranges (older .so?)"
    mj0 = read_majflt()
    cold_ms, tops = [], []
    for terms in per_query_terms:
        top, ms = search_once(idx, string_dtype, terms, kp, qc)
        cold_ms.append(ms)
        tops.append(top)
    mj_cold = read_majflt() - mj0
    warm_ms = []
    for terms in per_query_terms:
        reps = []
        for _ in range(WARM_REPEATS):
            _, ms = search_once(idx, string_dtype, terms, kp, qc)
            reps.append(ms)
        warm_ms.append(statistics.median(reps))
    cell = {
        "cold_traverse_ms_p50": round(statistics.median(cold_ms), 2),
        "cold_traverse_ms_mean": round(statistics.mean(cold_ms), 2),
        "warm_traverse_ms_p50": round(statistics.median(warm_ms), 3),
        "warm_traverse_ms_mean": round(statistics.mean(warm_ms), 3),
        "majflt_cold_pass": mj_cold,
        "n_queries": len(per_query_terms),
    }
    if base_top10 is not None:
        ovs = [len(set(t[:OVERLAP_K]) & set(b[:OVERLAP_K])) / max(min(len(b), OVERLAP_K), 1)
               for t, b in zip(tops, base_top10)]
        cell["overlap@10_vs_base"] = round(statistics.mean(ovs), 4)
        cell["overlap@10_min"] = round(min(ovs), 4)
    return cell, tops


def doi_grouping(top50_by_q: list[list[str]], meta_path: Path) -> dict:
    """Audit §1.3-iii piggyback: duplicate-DOI prevalence in baseline top-50."""
    db = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True)
    q_with_dup, total_groups, docs_in_groups = 0, 0, 0
    for ids in top50_by_q:
        ints = [int(d[1:]) for d in ids if d.startswith("W") and d[1:].isdigit()]
        rows = db.execute(
            f"SELECT doi FROM docs WHERE id IN ({','.join('?' * len(ints))})",
            ints).fetchall() if ints else []
        seen: dict[str, int] = {}
        for (doi,) in rows:
            if doi:
                seen[doi.lower()] = seen.get(doi.lower(), 0) + 1
        groups = [c for c in seen.values() if c >= 2]
        if groups:
            q_with_dup += 1
            total_groups += len(groups)
            docs_in_groups += sum(groups)
    db.close()
    return {"n_queries": len(top50_by_q),
            "queries_with_dup_doi_in_top50": q_with_dup,
            "dup_doi_groups_total": total_groups,
            "docs_in_dup_groups_total": docs_in_groups}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmap-dir",
                    default="data/seismic_150m/index/plan01/global_shard0of8.mmap")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--meta-sqlite", default="data/thinclient_index/meta.sqlite")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()
    assert args.queries <= 100, "audit rule: ≤100 queries"

    mmap_dir = Path(args.mmap_dir)
    assert mmap_dir.is_dir(), f"mmap dir missing: {mmap_dir}"
    queries = load_queries(args.queries, Path(args.query_workload))
    log.info("loaded %d queries", len(queries))

    rss_pre = read_rss()
    df, n_docs = load_token_df(mmap_dir)
    log.info("df table: %d tokens, n_docs=%d", len(df), n_docs)

    import seismic
    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    string_dtype = seismic.get_seismic_string()
    rss_loaded = read_rss()
    log.info("mmap shard loaded len=%d dim=%d nnz=%d  rss=%s",
             idx.len, idx.dim, idx.nnz, rss_loaded)

    # Encode every query ONCE (top-64 shaping, the serving constant); encoding
    # is config-independent so it never contaminates cell timing.
    from lib.opensearch_retriever import encode_splade
    log.info("encoding %d queries (cold SPLADE model load amortized here)...", len(queries))
    t0 = time.perf_counter()
    q64s = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        q64s.append(dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))
    log.info("encoded in %.1fs", time.perf_counter() - t0)

    # The FULL vocab-known term vector, passed to every real-lever cell so
    # forward scoring stays full-query (the mechanism this experiment corrected).
    full_terms = [select_terms(q, "weight", None, df, n_docs) for q in q64s]

    # ── baseline: recall-max reference (all terms, query_cut=all, k'=200) ──
    log.info("baseline: all terms, query_cut=all, hf=%.1f, k'=200", HEAP_FACTOR)
    base_cell, base_tops = run_cell(idx, string_dtype, full_terms, 200, None, None)
    base_top10 = [t[:OVERLAP_K] for t in base_tops]
    log.info("baseline cold p50=%.0fms warm p50=%.2fms majflt=%d",
             base_cell["cold_traverse_ms_p50"], base_cell["warm_traverse_ms_p50"],
             base_cell["majflt_cold_pass"])

    # ── grid ──
    grid = []
    # (a) THE real levers: full term vector, vary query_cut (gather) × k'.
    for qc in QUERY_CUTS:
        for kp in K_PRIMES:
            cell, _ = run_cell(idx, string_dtype, full_terms, kp, qc, base_top10)
            cell.update(kind="gather_cut", term_vector="full", query_cut=qc, k_prime=kp)
            grid.append(cell)
            log.info("[gather] qc=%-2d k'=%-3d  ov=%.4f  warm=%.2fms cold=%.0fms majflt=%d",
                     qc, kp, cell["overlap@10_vs_base"], cell["warm_traverse_ms_p50"],
                     cell["cold_traverse_ms_p50"], cell["majflt_cold_pass"])
    # k'-only at all terms (isolates k' with no gather cut).
    for kp in [50, 100]:
        cell, _ = run_cell(idx, string_dtype, full_terms, kp, None, base_top10)
        cell.update(kind="gather_cut", term_vector="full", query_cut="all", k_prime=kp)
        grid.append(cell)
        log.info("[gather] qc=all k'=%-3d  ov=%.4f  warm=%.2fms cold=%.0fms majflt=%d",
                 kp, cell["overlap@10_vs_base"], cell["warm_traverse_ms_p50"],
                 cell["cold_traverse_ms_p50"], cell["majflt_cold_pass"])

    # (b) NEGATIVE CONTROL: naive df/weight term-SUBSET cut (shrinks the passed
    # vector → corrupts scoring). Documents WHY Python-side df selection is the
    # wrong lever. k'=200 fixed; qc=len(subset) (visit all passed lists).
    neg = []
    for mode in ["weight", "idf"]:
        for cut in [10, 15]:
            per_q = [select_terms(q, mode, cut, df, n_docs) for q in q64s]
            cell, _ = run_cell(idx, string_dtype, per_q, 200, None, base_top10)
            cell.update(kind="subset_control", term_vector=f"{mode}_top{cut}",
                        query_cut=cut, k_prime=200)
            neg.append(cell)
            log.info("[subset-CTRL] %s top%d  ov=%.4f  warm=%.2fms  (negative control)",
                     mode, cut, cell["overlap@10_vs_base"], cell["warm_traverse_ms_p50"])

    # ── verdict: the pre-registered kill criterion (audit §4 E1) ──
    # Reference = full terms, query_cut=10, k'=200 (the audit's proposed default).
    ref = next(c for c in grid if c["query_cut"] == 10 and c["k_prime"] == 200)
    winners = [c for c in grid
               if c["overlap@10_vs_base"] >= 0.99
               and c["warm_traverse_ms_p50"] <= ref["warm_traverse_ms_p50"] / 1.3
               and c is not ref]
    # Also report the cheapest cell that still holds overlap ≥ 0.99 (the tunable
    # recommendation even if it doesn't clear the strict 1.3× bar vs the ref).
    safe = [c for c in grid if c["overlap@10_vs_base"] >= 0.99]
    cheapest_safe = min(safe, key=lambda c: c["warm_traverse_ms_p50"]) if safe else None
    verdict = ("E1_LEVER_LIVE" if winners else "E1_NO_1.3x_WIN") + \
        f" — ref (full/qc10/k'200) warm p50 {ref['warm_traverse_ms_p50']}ms, ov {ref['overlap@10_vs_base']}; " + \
        (f"{len(winners)} cell(s) beat it ≥1.3× at overlap ≥0.99"
         if winners else "no cell beats it ≥1.3× at overlap ≥0.99") + \
        (f"; cheapest overlap≥0.99 cell = qc{cheapest_safe['query_cut']}/k'"
         f"{cheapest_safe['k_prime']} @ {cheapest_safe['warm_traverse_ms_p50']}ms"
         if cheapest_safe else "")

    doi = doi_grouping([t[:TOP_K] for t in base_tops], Path(args.meta_sqlite))
    rss_end = read_rss()

    summary = {
        "meta": {
            "purpose": "09_CROSS_SHARD_MMAP_AUDIT.md §4 E1: k' × df-aware-cut sweep, 1×150M mmap shard",
            "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "shard": {"mmap_dir": str(mmap_dir), "docs": idx.len, "dim": idx.dim,
                      "nnz": idx.nnz},
            "df_table": {"source": "shard0 manifest packed_postings_words (pruned df)",
                         "tokens": len(df),
                         "cap_note": "hot lists saturate at n_postings*max_fraction=5250"},
            "model": args.model_path, "n_queries": len(queries),
            "top_k": TOP_K, "overlap_k": OVERLAP_K, "heap_factor": HEAP_FACTOR,
            "warm_repeats": WARM_REPEATS,
            "cold_method": "release_pages() (MADV_DONTNEED, mechanism B) before each "
                           "cell's first pass; majflt delta = pages-touched proxy",
            "mechanism_note": "query_cut is a candidate-GATHER cut, not a scoring cut: "
                    "the forward evaluator scores against the FULL passed vector "
                    "(mmap_io.rs:640-670). So gather_cut cells pass all terms + small "
                    "query_cut (recall-preserving); subset_control cells shrink the "
                    "passed vector (corrupts scoring) — the negative control that kills "
                    "Python-side df term selection. This CORRECTS audit §2.1.",
            "note": "overlap@10 is vs the all-terms/query_cut=all/hf=0.8/k'=200 recall-max "
                    "baseline (self-relative), single shard — NOT federated or vs-Qdrant.",
            "rss": {"pre_load": rss_pre, "post_load": rss_loaded, "end": rss_end},
        },
        "baseline": {**base_cell, "kind": "baseline", "term_vector": "full",
                     "query_cut": "all", "k_prime": 200},
        "grid": grid,
        "subset_control": neg,
        "kill_criterion": "beat full/qc10/hf0.8/k'200 by ≥1.3× warm traverse at overlap@10 ≥0.99",
        "verdict": verdict,
        "doi_grouping_top50": doi,
    }
    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_e1_kprime_df_sweep_{time.strftime('%Y%m%d_%H%M')}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"verdict": verdict, "doi_grouping": doi,
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
