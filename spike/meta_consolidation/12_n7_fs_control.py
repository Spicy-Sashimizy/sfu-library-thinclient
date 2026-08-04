#!/usr/bin/env python3
"""N7 — is N6's 3.20x the ADDRESSING change, or the FILESYSTEM under it?

Doc 18 §13 reports whole-query **3.20x at top_k=50** (344.6 -> 107.6 ms) for the
ordinal filter path. That run staged the ordinal arrays to `/var/tmp` (overlay)
because §13 itself established residency as a precondition -- unstaged, the
ordinal arm measured 8x SLOWER than SQLite.

**But the production arm's `meta.sqlite` was never staged.** It sat at
`data/thinclient_index/meta.sqlite`, which is **9p** in this container (`df -T`
2026-08-03). So N6's two arms differed in *two* ways at once:

    arm            filter addressing      meta.sqlite filesystem
    production     SQLite B-tree          9p       (~0.5 ms/fault, cache leaks)
    ordinal        mmap'd columns         (overlay, for the arrays)

A two-variable experiment cannot attribute its result to one variable. The
3.20x is therefore an upper bound on the addressing win, and how much of it is
addressing versus filesystem was **not measured**. §13 does not disclose this.

This is the control that decomposes it: a **2x2 factorial** over the two levers,
run as four interleaved arms on the real retriever.

    arm               `_ordinals`   `meta.sqlite`   what it isolates
    prod_9p           off           9p             = N6's production baseline
    sqlite_staged     off           overlay        the FILESYSTEM lever alone
    ordinal_9p        on            9p             = N6's ordinal arm
    ordinal_staged    on            overlay        both levers (real deployment)

Reading the result:

  * `sqlite_staged` ~= `prod_9p`  -> meta.sqlite is already effectively cached;
    9p is a non-issue and §13's 3.20x is purely the addressing win. §13 stands.
  * `sqlite_staged` ~= `ordinal_staged` -> the win was the filesystem. Staging a
    file is vastly cheaper than adopting a second addressing scheme with a
    silent-wrong-answer failure mode, and §13's headline needs a correction.
  * in between -> the two levers decompose, and BOTH numbers must be reported.

`_meta` is swapped by rebinding `retriever._meta` to a second `sqlite3.connect`
on the staged copy, opened exactly as `retriever.py:414` opens the original
(`check_same_thread=False`, no PRAGMAs). `_meta_numeric` is left alone: the
staged file is a byte copy, so the v1/v2 detection stays valid. The shipped
`_post_filter` / `_post_filter_sqlite` / `_meta_rows` code runs unmodified in
every arm -- no harness reimplementation, per doc 18's standing method rule.

**`_meta` affects `_hydrate` too**, not just the filter (`retriever.py:1088`).
That is deliberate and is the honest framing: "where does meta.sqlite live" is
ONE deployment decision, and it prices both stages it touches.

**Method, inherited from §13 (each item was learned by getting it wrong here).**
Arms interleaved within each rep, order randomised per rep -- running all of A
then all of B lets the later arm reuse the earlier's page faults. Parity is the
gate: all four arms must return identical `(id, score)` lists, or the numbers
are meaningless. `mode=bm25f` is the negative control -- `_bm25f_leg` pushes
filters into tantivy and never calls `_post_filter`, so its arms must not
separate; whatever spread it shows IS this run's noise floor, re-derived here
rather than inherited from §13's 1.09x. `SFU_DENSE_WARMCACHE=0` so the benchmark
cannot mutate production state. SEISMIC shards staged, as §13 requires.

**One warmup change from N6, which warmed only the production arm.** That warms
SQLite's page cache specifically and mildly favours the SQLite arms. Here every
arm is warmed, so each starts from a comparably faulted state.

**Cache pressure is real and is reported, not hidden.** Staged SEISMIC (42 GB) +
staged meta.sqlite (24.9 GB) = ~67 GB against 56 GB of RAM, so the staged arms
cannot hold their whole working set resident and will evict each other. That is
what a real host with this data would also do.

Prereq (~25 GB, one-time):

    mkdir -p /var/tmp/meta_stage
    cp data/thinclient_index/meta.sqlite /var/tmp/meta_stage/meta.sqlite

    SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage SFU_DENSE_WARMCACHE=0 \
    .venv/bin/python3 spike/meta_consolidation/12_n7_fs_control.py \
        --work /var/tmp/ordinals_stage --staged-meta /var/tmp/meta_stage/meta.sqlite

Read-only against the index. `remote_abstracts=False` so `_hydrate` never makes
a network call inside a latency measurement.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

QUERIES = ROOT / "data" / "sfu_eval_queries.json"
log = logging.getLogger("n7")

# (label, ordinals_on, meta_staged)
ARMS = [
    ("prod_9p", False, False),
    ("sqlite_staged", False, True),
    ("ordinal_9p", True, False),
    ("ordinal_staged", True, True),
]


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 2),
            "mean_ms": round(statistics.fmean(s), 2),
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 2)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/ordinals_stage"),
                    help="ordinal arrays (must be on local disk, doc 18 §13)")
    ap.add_argument("--staged-meta", type=Path,
                    default=Path("/var/tmp/meta_stage/meta.sqlite"))
    ap.add_argument("--modes", nargs="+", default=["splade", "bm25f"],
                    help="bm25f is the negative control (it never post-filters)")
    ap.add_argument("--top-k", type=int, nargs="+", default=[50, 100],
                    help="§13's two cases that cleared the noise floor")
    ap.add_argument("--queries", type=int, default=12)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    from lib.thinclient.ordinals import OrdinalSpace
    from lib.thinclient.retriever import ThinClientRetriever, _fstype_for_path

    if not args.staged_meta.exists():
        raise SystemExit(f"{args.staged_meta} missing — copy meta.sqlite there "
                         f"first (see this file's docstring)")

    r = ThinClientRetriever(index_root="", remote_abstracts=False)
    r._load()
    if r._meta is None:
        raise SystemExit("no meta.sqlite on the retriever — nothing to control")
    log.info("retriever: %d sections, splade backend=%r, meta_numeric=%s",
             len(r._sections), r._splade_backend, r._meta_numeric)

    # ── the two switchable resources ─────────────────────────────────────────
    meta_9p = r._meta
    meta_staged = sqlite3.connect(str(args.staged_meta), check_same_thread=False)
    # The staged file is a byte copy, so the v1/v2 schema detection made at load
    # still applies. Assert it rather than assume: a truncated or wrong-schema
    # copy would otherwise filter against a table that does not exist, and the
    # arms would differ by more than the filesystem.
    cols = {row[1]: (row[2] or "").upper()
            for row in meta_staged.execute("PRAGMA table_info(docs)")}
    if cols.get("id", "").startswith("INT") != r._meta_numeric:
        raise SystemExit("staged meta.sqlite schema disagrees with the served one")
    n_staged = meta_staged.execute("SELECT count(*) FROM docs").fetchone()[0]
    log.info("staged meta.sqlite: %s docs, schema matches", f"{n_staged:,}")

    stamp = json.loads((args.work / "ordinal_space.json").read_text())
    ordinal = OrdinalSpace(args.work,
                           {"ordinal_space_id": stamp["ordinal_space_id"]})
    log.info("ordinal space %s: %d docs", ordinal.space_id, ordinal.rows)

    def set_arm(ordinals_on: bool, meta_staged_on: bool) -> None:
        # `_ordinals` is exactly what SFU_THINCLIENT_ORDINALS sets, so the
        # ordinal arms run the shipped _post_filter including its SQLite
        # fallback for ids with no ordinal.
        r._ordinals = ordinal if ordinals_on else None
        r._meta = meta_staged if meta_staged_on else meta_9p

    raw = json.loads(QUERIES.read_text())
    rng = random.Random(args.seed)
    queries = [q["query"] for q in raw if q.get("query")]
    rng.shuffle(queries)
    queries = queries[:args.queries]

    FILTERS = {"year_range": (2010, 2025), "type": "article"}

    rep = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": ("decompose doc 18 §13's 3.20x into the addressing lever "
                     "and the meta.sqlite filesystem lever, which N6 varied "
                     "together"),
        "design": "2x2 factorial: _ordinals {off,on} x meta.sqlite {9p,overlay}",
        "ordinal_space_id": ordinal.space_id,
        "ordinal_docs_covered": ordinal.rows,
        "filters": FILTERS, "queries": queries, "reps_per_query": args.reps,
        "overfetch_filtered": 10,
        "env": {
            "splade_backend": r._splade_backend,
            "seismic_stage_dir": os.environ.get("SFU_SEISMIC_STAGE_DIR"),
            "seismic_federation": os.environ.get("SFU_SEISMIC_FEDERATION"),
            "shard_fstype_served": _fstype_for_path(
                os.environ.get("SFU_SEISMIC_STAGE_DIR")
                or str(ROOT / "data" / "seismic_150m" / "index" / "plan01")),
            "ordinal_dir": str(args.work),
            "ordinal_dir_fstype": _fstype_for_path(str(args.work)),
            # The variable under test.
            "meta_9p_path": str(ROOT / "data" / "thinclient_index" / "meta.sqlite"),
            "meta_9p_fstype": _fstype_for_path(
                str(ROOT / "data" / "thinclient_index" / "meta.sqlite")),
            "meta_staged_path": str(args.staged_meta),
            "meta_staged_fstype": _fstype_for_path(str(args.staged_meta)),
            "dense_warmcache": os.environ.get("SFU_DENSE_WARMCACHE"),
            "cache_pressure_note": (
                "staged SEISMIC ~42 GB + staged meta.sqlite ~24.9 GB against "
                "56 GB RAM: the staged arms cannot hold their full working set "
                "resident and evict each other, as a real host would"),
        },
        "method": ("real ThinClientRetriever.search(); 4 arms interleaved "
                   "within each rep, order randomised per rep; every arm "
                   "warmed; only _ordinals and _meta differ between arms"),
        "results": {}, "parity": {}, "stage_profile": {},
    }

    def run(arm: tuple, q: str, k: int, mode: str):
        set_arm(arm[1], arm[2])
        t0 = time.perf_counter()
        out = r.search(q, top_k=k, mode=mode, filters=dict(FILTERS))
        ms = (time.perf_counter() - t0) * 1000
        return ms, [(d["openalex_id"], d["score"]) for d in out]

    # ── warmup: every arm, not just production (N6 warmed only production) ───
    log.info("warmup: %d queries x %d arms x %d modes", args.warmup,
             len(ARMS), len(args.modes))
    for mode in args.modes:
        for i in range(args.warmup):
            for arm in ARMS:
                t0 = time.perf_counter()
                run(arm, queries[i % len(queries)], 50, mode)
                log.info("  warmup %s %-14s %d: %.0f ms", mode, arm[0], i,
                         (time.perf_counter() - t0) * 1000)

    # ── measure ─────────────────────────────────────────────────────────────
    for mode in args.modes:
        for k in args.top_k:
            samples: dict[str, list[float]] = {a[0]: [] for a in ARMS}
            mismatches = 0
            for q in queries:
                for _ in range(args.reps):
                    order = list(ARMS)
                    rng.shuffle(order)            # order randomised per rep
                    got = {}
                    for arm in order:             # interleaved within the rep
                        ms, res = run(arm, q, k, mode)
                        samples[arm[0]].append(ms)
                        got[arm[0]] = res
                    # Parity gate: every arm against the N6 baseline arm.
                    base = got["prod_9p"]
                    if any(got[a] != base for a in got):
                        mismatches += 1

            key = f"{mode}_k{k}"
            stats = {name: _stat(samples[name]) for name in samples}
            base_p50 = stats["prod_9p"]["p50_ms"]
            rep["results"][key] = {
                "arms": stats,
                "speedup_vs_prod_9p": {
                    name: (round(base_p50 / s["p50_ms"], 3) if s["p50_ms"] else None)
                    for name, s in stats.items()},
                "candidates_post_filtered": k * 10,
            }
            rep["parity"][key] = {"pairs": len(samples["prod_9p"]),
                                  "mismatches": mismatches,
                                  "pass": mismatches == 0}
            log.info("%-12s %s | parity %s", key,
                     " | ".join(f"{n} {stats[n]['p50_ms']:7.1f}ms "
                                f"({base_p50 / stats[n]['p50_ms']:.2f}x)"
                                if stats[n]["p50_ms"] else f"{n} n/a"
                                for n, _, _ in ARMS),
                     "PASS" if mismatches == 0 else f"FAIL({mismatches})")

    # ── per-arm stage profile at k=50: where the time actually goes ─────────
    # The whole-query number hides which stage moved. `_meta` touches BOTH
    # _post_filter and _hydrate, so the profile is what shows the filesystem
    # lever paying off in two places while the ordinal lever pays in one.
    log.info("stage profile per arm (%d queries x %d reps, splade k=50)",
             len(queries), args.reps)
    for arm in ARMS:
        acc = {"post_filter": 0.0, "hydrate_meta": 0.0,
               "hydrate_abstracts": 0.0, "total": 0.0, "n": 0}
        real_pf, real_meta = r._post_filter, r._meta_rows
        real_abs, real_hydrate = r.fetch_abstracts, r._hydrate
        in_hydrate = [False]

        def timed_pf(ranked, f):
            t = time.perf_counter()
            try:
                return real_pf(ranked, f)
            finally:
                acc["post_filter"] += (time.perf_counter() - t) * 1000

        def timed_meta(ids):
            t = time.perf_counter()
            try:
                return real_meta(ids)
            finally:
                # _meta_rows is called from _post_filter AND _hydrate; only
                # attribute the _hydrate calls, or it double-counts.
                if in_hydrate[0]:
                    acc["hydrate_meta"] += (time.perf_counter() - t) * 1000

        def timed_abs(ids):
            t = time.perf_counter()
            try:
                return real_abs(ids)
            finally:
                acc["hydrate_abstracts"] += (time.perf_counter() - t) * 1000

        def timed_hydrate(ranked, source):
            in_hydrate[0] = True
            try:
                return real_hydrate(ranked, source)
            finally:
                in_hydrate[0] = False

        r._post_filter, r._meta_rows = timed_pf, timed_meta
        r.fetch_abstracts, r._hydrate = timed_abs, timed_hydrate
        try:
            for q in queries:
                for _ in range(args.reps):
                    set_arm(arm[1], arm[2])
                    t0 = time.perf_counter()
                    r.search(q, top_k=50, mode="splade", filters=dict(FILTERS))
                    acc["total"] += (time.perf_counter() - t0) * 1000
                    acc["n"] += 1
        finally:
            r._post_filter, r._meta_rows = real_pf, real_meta
            r.fetch_abstracts, r._hydrate = real_abs, real_hydrate

        n = max(acc["n"], 1)
        prof = {k2: round(v / n, 2) for k2, v in acc.items() if k2 != "n"}
        prof["other_ms"] = round(prof["total"] - prof["post_filter"]
                                 - prof["hydrate_meta"]
                                 - prof["hydrate_abstracts"], 2)
        prof["samples"] = acc["n"]
        rep["stage_profile"][arm[0]] = prof
        log.info("  %-14s post_filter %7.1f | hydrate_meta %6.1f | "
                 "abstracts %6.1f | other %6.1f | total %7.1f",
                 arm[0], prof["post_filter"], prof["hydrate_meta"],
                 prof["hydrate_abstracts"], prof["other_ms"], prof["total"])

    rep["parity_overall_pass"] = all(v["pass"] for v in rep["parity"].values())

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n7_fs_control_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s (parity %s)", out,
             "PASS" if rep["parity_overall_pass"] else "FAIL")


if __name__ == "__main__":
    main()
