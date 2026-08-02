#!/usr/bin/env python3
"""N6 — WHOLE-QUERY latency of the ordinal filter path, on the real retriever.

Doc 18 §11 "Not settled #1": N4 measured `_post_filter` **in isolation** and got
120-211x. That is not a system result. The tantivy leg alone is ~47 ms (§4.3),
so a ~213 ms filter saving is large in absolute terms but the end-to-end query
improvement had never been measured. Doc 17 §10.3 is the standing reason to
distrust primitives as system results: the identical filter code path measures
4.15 ms at 208k docs and 400 ms at 150M, a **96x** gap.

This runs the REAL `ThinClientRetriever.search()` against the REAL index and
measures the whole query. The arms are switched by the REAL serving gate
(`retriever._ordinals`, what `SFU_THINCLIENT_ORDINALS` sets), so the ordinal arm
runs the shipped code rather than a harness reimplementation of it:

  arm A (production)  `_post_filter_sqlite` -> `_meta_rows` -> meta.sqlite
  arm B (ordinal)     `_post_filter` -> searchsorted + mmap'd columnar mask,
                      falling back to arm A for ids with no ordinal

**Which leg is even affected, and why the mode matters.** `_bm25f_leg` pushes
filters INTO tantivy as boolean clauses (`retriever.py:698-708`) and never calls
`_post_filter`. Only the SPLADE and dense legs post-filter. So `mode="splade"`
is where the whole-query question lives, and `mode="bm25f"` is measured too, as
a **negative control**: it must show no difference, and if it does, the harness
is measuring noise rather than the swap.

**Candidate count is set by production, not by us.** `fetch = top_k *
OVERFETCH_FILTERED` (=10), so a filtered top_k=50 query post-filters ~500
candidates -- N4's k=500 row, not its k=1000 row. Sweeping top_k sweeps the
candidate count the way production actually would.

**Methodology (doc 18 §4.3's lesson, which cost that section its first run).**
Arms are **interleaved within each repetition** and their **order randomised per
rep**. Running all of arm A then all of arm B lets the second arm reuse the
first's page faults, which made the arm doing MORE work look faster and rendered
those absolute numbers unquotable. With a 44 GB mmap'd SEISMIC working set that
hazard is larger here, not smaller.

**Parity is still the gate.** Every timed pair also compares the two arms' full
returned result lists (ids AND order). A faster query returning a different
result set is not a result.

**The host filesystem will decide this number if you let it.** The SEISMIC
shards live under `data/seismic_150m/` which is **9p** in this container, where
each mmap page fault costs ~0.5 ms — ~160-240x slower than native local disk,
and the page cache does not hold between queries (measured 2026-07-18,
`retriever._stage_shards_local`). Left alone, the SPLADE leg would cost seconds,
the filter saving would round to ~1% of the query, and the conclusion would be
an artifact of this dev container rather than a fact about the design. Served
production stages the shards to local disk first, so this harness must too:

    SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage   (~42 GB, one-time ~8 min)

The run records the staging directory and the resolved federation mode, because
a number produced without staging is not comparable to one produced with it.

Read-only. `remote_abstracts=False` so `_hydrate` never makes an OpenAlex call
(a network round-trip inside a latency measurement would swamp everything);
this matches `eval_parity_section_waves.py` and `eval_thinclient_parity.py`.

    .venv/bin/python3 spike/meta_consolidation/11_n6_whole_query_latency.py \
        --work spike/meta_consolidation/work_ordinals_full
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

WORK = Path(__file__).parent / "work_ordinals_full"
QUERIES = ROOT / "data" / "sfu_eval_queries.json"
log = logging.getLogger("n6")


class CountingOrdinalSpace:
    """The production `OrdinalSpace`, wrapped only to count coverage misses.

    The arms are switched by setting `retriever._ordinals`, which is the real
    `SFU_THINCLIENT_ORDINALS` gate — so the ordinal arm runs the SHIPPED
    `_post_filter`, including its fallback to SQLite for ids with no ordinal
    (doc 18 §6 risk 3). Measuring a bare mask instead would flatter the ordinal
    arm by pricing a version that cannot ship, since warm-cache docs would be
    dropped silently.
    """

    def __init__(self, work: Path):
        from lib.thinclient.ordinals import OrdinalSpace

        stamp = json.loads((work / "ordinal_space.json").read_text())
        # The harness authorises the pairing here; serving reads this id from
        # the index manifest.json instead.
        self.space = OrdinalSpace(work, {"ordinal_space_id": stamp["ordinal_space_id"]})
        self.space_id = self.space.space_id
        self.rows = self.space.rows
        self.wids = self.space.wids
        self.seen = self.misses = self.fallbacks = 0

    def post_filter(self, ranked, f):
        kept, unresolved = self.space.post_filter(ranked, f)
        self.seen += len(ranked)
        self.misses += len(unresolved)
        self.fallbacks += bool(unresolved)
        return kept, unresolved


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 2),
            "mean_ms": round(statistics.fmean(s), 2),
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--modes", nargs="+", default=["splade", "bm25f"],
                    help="bm25f is the negative control (it never post-filters)")
    ap.add_argument("--top-k", type=int, nargs="+", default=[10, 50, 100])
    ap.add_argument("--queries", type=int, default=12)
    ap.add_argument("--reps", type=int, default=3, help="reps per query")
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    from lib.thinclient.retriever import (ThinClientRetriever,
                                          _fstype_for_path)

    r = ThinClientRetriever(index_root="", remote_abstracts=False)
    r._load()
    log.info("retriever: %d sections, splade backend=%r",
             len(r._sections), r._splade_backend)

    ordinal = CountingOrdinalSpace(args.work)
    log.info("ordinal space %s: %d docs, id range %d..%d",
             ordinal.space_id, ordinal.rows,
             int(ordinal.wids[0]), int(ordinal.wids[-1]))

    raw = json.loads(QUERIES.read_text())
    rng = random.Random(args.seed)
    queries = [q["query"] for q in raw if q.get("query")]
    rng.shuffle(queries)
    queries = queries[:args.queries]

    # The filter shape production actually sends. `year_range` alone is the
    # common case; `_normalize_filters` turns this into the same dict the
    # served path builds.
    FILTERS = {"year_range": (2010, 2025), "type": "article"}

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "ordinal_docs_covered": ordinal.rows,
           "ordinal_space_id": ordinal.space_id,
           "filters": FILTERS, "queries": queries,
           "reps_per_query": args.reps,
           "overfetch_filtered": 10,
           "env": {
               "splade_backend": r._splade_backend,
               "seismic_stage_dir": os.environ.get("SFU_SEISMIC_STAGE_DIR"),
               "seismic_federation": os.environ.get("SFU_SEISMIC_FEDERATION"),
               # BOTH paths: the source is 9p, but what the query actually
               # faults against is the staged copy. Recording only the source
               # (as the first run did) reads as if the run were unstaged.
               "shard_fstype_source": _fstype_for_path(
                   str(ROOT / "data" / "seismic_150m" / "index" / "plan01")),
               "shard_fstype_served": _fstype_for_path(
                   os.environ.get("SFU_SEISMIC_STAGE_DIR")
                   or str(ROOT / "data" / "seismic_150m" / "index" / "plan01")),
               "ordinal_dir_fstype": _fstype_for_path(str(args.work)),
               "note": ("on 9p each mmap fault costs ~0.5 ms and page cache "
                        "does not hold; an unstaged run measures the dev "
                        "container's filesystem, not the design"),
           },
           "method": ("real ThinClientRetriever.search(); arms interleaved per "
                      "rep, order randomised per rep; only _post_filter differs"),
           "results": {}, "parity": {}}

    # ── stage profile ────────────────────────────────────────────────────────
    # Prices every stage of the production query, so the filter saving can be
    # read against what else the query spends. This is also the gate on doc 18
    # §11 "not settled #3" (_hydrate): extending ordinals to title/DOI needs a
    # flat blob over 150.4M docs, and this investigation has three times now
    # optimised a stage that was not on the critical path (MPHF ~2%, C3's
    # locator 1.3%, the 48x pragma -> 1.18x). `_hydrate` runs on top_k ids, not
    # on the ~10x over-fetched candidate set, so it is a much smaller target
    # than `_post_filter` -- measure before building.
    stage = {"post_filter": 0.0, "hydrate_meta": 0.0, "hydrate_abstracts": 0.0,
             "total": 0.0, "n": 0}

    def profile(q: str, k: int, mode: str) -> None:
        r._ordinals = None                       # profile the production arm
        acc = {"meta": 0.0, "abs": 0.0, "pf": 0.0}
        real_pf, real_meta, real_abs = (r._post_filter, r._meta_rows,
                                        r.fetch_abstracts)
        in_hydrate = [False]

        def timed_pf(ranked, f):
            t = time.perf_counter()
            try:
                return real_pf(ranked, f)
            finally:
                acc["pf"] += (time.perf_counter() - t) * 1000

        def timed_meta(ids):
            t = time.perf_counter()
            try:
                return real_meta(ids)
            finally:
                # _meta_rows is called from both _post_filter and _hydrate;
                # only the latter is the _hydrate target, so attribute it.
                if in_hydrate[0]:
                    acc["meta"] += (time.perf_counter() - t) * 1000

        def timed_abs(ids):
            t = time.perf_counter()
            try:
                return real_abs(ids)
            finally:
                acc["abs"] += (time.perf_counter() - t) * 1000

        real_hydrate = r._hydrate

        def timed_hydrate(ranked, source):
            in_hydrate[0] = True
            try:
                return real_hydrate(ranked, source)
            finally:
                in_hydrate[0] = False

        r._post_filter, r._meta_rows = timed_pf, timed_meta
        r.fetch_abstracts, r._hydrate = timed_abs, timed_hydrate
        try:
            t0 = time.perf_counter()
            r.search(q, top_k=k, mode=mode, filters=dict(FILTERS))
            stage["total"] += (time.perf_counter() - t0) * 1000
        finally:
            r._post_filter, r._meta_rows = real_pf, real_meta
            r.fetch_abstracts, r._hydrate = real_abs, real_hydrate
        stage["post_filter"] += acc["pf"]
        stage["hydrate_meta"] += acc["meta"]
        stage["hydrate_abstracts"] += acc["abs"]
        stage["n"] += 1

    def run(arm: str, q: str, k: int, mode: str):
        # The real gate: `_ordinals` is exactly what SFU_THINCLIENT_ORDINALS
        # sets, so the ordinal arm runs the shipped _post_filter unmodified.
        r._ordinals = ordinal if arm == "ordinal" else None
        t0 = time.perf_counter()
        out = r.search(q, top_k=k, mode=mode, filters=dict(FILTERS))
        ms = (time.perf_counter() - t0) * 1000
        return ms, [(d["openalex_id"], d["score"]) for d in out]

    # ── warmup: fault in the SEISMIC shards, tantivy segments, sqlite pages ──
    log.info("warmup (%d queries per mode; the 44 GB SEISMIC set faults here)",
             args.warmup)
    for mode in args.modes:
        for i in range(args.warmup):
            t0 = time.perf_counter()
            run("production", queries[i % len(queries)], 50, mode)
            log.info("  warmup %s %d: %.0f ms", mode, i, (time.perf_counter() - t0) * 1000)

    # ── measure ─────────────────────────────────────────────────────────────
    for mode in args.modes:
        for k in args.top_k:
            samples = {"production": [], "ordinal": []}
            mismatches = 0
            for q in queries:
                for _ in range(args.reps):
                    arms = ["production", "ordinal"]
                    rng.shuffle(arms)             # order randomised per rep
                    got = {}
                    for arm in arms:              # interleaved within the rep
                        ms, res = run(arm, q, k, mode)
                        samples[arm].append(ms)
                        got[arm] = res
                    if got["production"] != got["ordinal"]:
                        mismatches += 1

            p, o = _stat(samples["production"]), _stat(samples["ordinal"])
            key = f"{mode}_k{k}"
            rep["results"][key] = {
                "production": p, "ordinal": o,
                "delta_p50_ms": round(p["p50_ms"] - o["p50_ms"], 2),
                "speedup_p50": round(p["p50_ms"] / o["p50_ms"], 3) if o["p50_ms"] else None,
                "candidates_post_filtered": k * 10,
            }
            rep["parity"][key] = {"pairs": len(samples["ordinal"]),
                                  "mismatches": mismatches,
                                  "pass": mismatches == 0}
            log.info("%-12s production %8.1f ms | ordinal %8.1f ms | "
                     "-%.1f ms (%.3fx) | parity %s",
                     key, p["p50_ms"], o["p50_ms"],
                     p["p50_ms"] - o["p50_ms"],
                     rep["results"][key]["speedup_p50"] or 0,
                     "PASS" if mismatches == 0 else f"FAIL({mismatches})")

    # ── stage profile of the production query (arm-independent) ─────────────
    log.info("stage profile (%d queries x %d reps, production arm, top_k=50)",
             len(queries), args.reps)
    for q in queries:
        for _ in range(args.reps):
            profile(q, 50, "splade")
    n = max(stage["n"], 1)
    prof = {k: round(v / n, 2) for k, v in stage.items() if k != "n"}
    prof["other_ms"] = round(prof["total"] - prof["post_filter"]
                             - prof["hydrate_meta"] - prof["hydrate_abstracts"], 2)
    prof["samples"] = stage["n"]
    prof["note"] = ("mean ms per query, mode=splade top_k=50 (=500 candidates). "
                    "'other' is dominated by the SEISMIC leg + SPLADE encode. "
                    "hydrate_meta is the target of doc 18 §11 not-settled #3; "
                    "post_filter is what N4/N6 replace.")
    rep["stage_profile_production"] = prof
    log.info("  post_filter %.1f ms | hydrate_meta %.1f ms | "
             "hydrate_abstracts %.1f ms | other %.1f ms | total %.1f ms",
             prof["post_filter"], prof["hydrate_meta"],
             prof["hydrate_abstracts"], prof["other_ms"], prof["total"])

    rep["ordinal_coverage"] = {
        "ids_seen": ordinal.seen, "ids_without_ordinal": ordinal.misses,
        "miss_rate": round(ordinal.misses / ordinal.seen, 6) if ordinal.seen else None,
        "queries_needing_sqlite_fallback": ordinal.fallbacks,
        "note": ("ids with no ordinal fall back to the SQLite filter, so a "
                 "nonzero miss rate costs latency but never correctness; "
                 "against a full-corpus build it should be ~0 apart from "
                 "warm-cache docs"),
    }
    rep["parity_overall_pass"] = all(v["pass"] for v in rep["parity"].values())

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n6_whole_query_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s (parity %s, ordinal misses %d/%d)", out,
             "PASS" if rep["parity_overall_pass"] else "FAIL",
             ordinal.misses, ordinal.seen)


if __name__ == "__main__":
    main()
