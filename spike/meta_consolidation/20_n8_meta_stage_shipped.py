#!/usr/bin/env python3
"""N8 — does the SHIPPED `meta.sqlite` staging path buy N7's filter-stage win?

Doc 18 §14 (2026-08-03) measured the filesystem lever by hand: it `cp`-ed
`meta.sqlite` to `/var/tmp` and rebound `retriever._meta` to a second
`sqlite3.connect` on the copy. `_post_filter` went **222.2 ms -> 4.0 ms** at
~500 candidates. That was a MEASURED LEVER, not a shipped one.

2026-08-17 `retriever._stage_meta_local` + `_connect_meta` ship it
(`SFU_META_STAGE_DIR`, atomic tmp+rename, verified copy, `.staged_ok` marker,
`mode=ro&immutable=1` on the staged handle, no-op unless the source FS is
9p/virtiofs/NFS/...). Doc 18 §14 "Not settled" #1 records it as **IMPLEMENTED,
EFFICACY UNMEASURED at full size** — no 24.9 GB copy had been run. This script
is that measurement, and it differs from N7 in exactly one way that matters:

    N7            hand-made `cp` + a hand-made sqlite3.connect
    N8 (here)     the retriever's OWN staging path, opened by `_connect_meta`
                  with the immutable read-only URI it ships

so what is timed is the code that actually serves, including the `immutable=1`
open (which takes no locks and needs no -wal, and could plausibly differ from
N7's plain connect).

**Two arms, one variable.** The 4-arm 2x2 of N7 is not re-run: the ordinal
lever is a separate question and needs `/var/tmp/ordinals_stage`, which this
container does not currently hold.

    arm         `_meta` connection                       filesystem
    unstaged    plain connect on the index root file     9p
    staged      `_connect_meta(staged=True)` on the      overlay (local)
                copy `_stage_meta_local` made

**Method, inherited from doc 18 §13/§14 (each item was learned by getting it
wrong there).** The candidate lists are captured ONCE per query from a real
`search()` (by recording what the shipped `_post_filter` is handed), then the
same list is replayed against both arms — so the arms differ only in the
`_meta` connection, and no SPLADE/SEISMIC variance leaks into the stage timing.
Arms are interleaved and their order is randomised per rep, because running all
of A then all of B lets the later arm reuse the earlier's page faults. Both
arms are warmed. Parity is the gate: both arms must return identical
`(id, score)` lists or the numbers are meaningless (the staged file is a byte
copy, so any difference is a bug, not a tradeoff). `SFU_DENSE_WARMCACHE=0` so
the benchmark cannot mutate production state.

**What this does NOT measure:** whole-query latency (N7 has it: 332.3 ->
117.3 ms at splade k=50), the ordinal lever, or anything on a droplet — where
the source FS is local, `_stage_meta_local` is a no-op by construction, and the
staged arm IS the baseline (doc 18 §14 "Not settled" #3).

Run (the copy must already exist or this makes it, ~25 GB, minutes on 9p):

    SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage SFU_DENSE_WARMCACHE=0 \
    SFU_META_STAGE_DIR=/var/tmp/meta_stage SFU_META_STAGE_VERIFY=fingerprint \
    .venv/bin/python3 spike/meta_consolidation/20_n8_meta_stage_shipped.py \
        --out data/eval_results/n8_meta_stage_shipped_<date>.json

Read-only against the index. `remote_abstracts=False` so no network call can
land inside a measurement.
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
sys.path.insert(0, str(ROOT / "source"))

QUERIES = ROOT / "data" / "sfu_eval_queries.json"
log = logging.getLogger("n8")

ARMS = ["unstaged", "staged"]


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 3),
            "mean_ms": round(statistics.fmean(s), 3),
            "min_ms": round(s[0], 3), "max_ms": round(s[-1], 3),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 3)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=int, default=12)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--top-k", type=int, default=50,
                    help="10x over-fetch => ~500 candidates reach _post_filter")
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    from lib.thinclient.retriever import (ThinClientRetriever, _connect_meta,
                                          _fstype_for_path)

    if not os.environ.get("SFU_META_STAGE_DIR") and \
            os.environ.get("SFU_STAGE_META") != "1":
        raise SystemExit("set SFU_META_STAGE_DIR — this script measures the "
                         "shipped staging path, so the staged arm must come "
                         "from it, not from a hand-made copy")

    t_load = time.perf_counter()
    r = ThinClientRetriever(index_root="", remote_abstracts=False)
    r._load()                      # stages meta.sqlite if it is not already
    load_s = time.perf_counter() - t_load
    if r._meta is None:
        raise SystemExit("no meta.sqlite on the retriever — nothing to measure")
    info = r.metrics() if hasattr(r, "metrics") else r.info()
    if not info.get("meta_staged"):
        raise SystemExit(f"the retriever did NOT stage meta.sqlite "
                         f"(meta_path={info.get('meta_path')!r}) — the staged "
                         f"arm would be identical to the unstaged one")
    src = ROOT / "data" / "thinclient_index" / "meta.sqlite"
    staged_path = Path(info["meta_path"])
    log.info("load %.1fs | staged -> %s (%s) | source %s (%s)", load_s,
             staged_path, _fstype_for_path(str(staged_path)), src,
             _fstype_for_path(str(src)))

    meta_staged = r._meta                                  # the shipped handle
    meta_unstaged = _connect_meta(src, staged=False)        # the 9p baseline
    n_staged = meta_staged.execute("SELECT count(*) FROM docs").fetchone()[0]
    n_src = meta_unstaged.execute("SELECT count(*) FROM docs").fetchone()[0]
    if n_staged != n_src:
        raise SystemExit(f"staged copy has {n_staged:,} docs, source has "
                         f"{n_src:,} — not a byte copy, arms incomparable")
    log.info("both arms see %s docs", f"{n_src:,}")

    def set_arm(name: str) -> None:
        r._meta = meta_staged if name == "staged" else meta_unstaged

    raw = json.loads(QUERIES.read_text())
    rng = random.Random(args.seed)
    queries = [q["query"] for q in raw if q.get("query")]
    rng.shuffle(queries)
    queries = queries[:args.queries]
    FILTERS = {"year_range": (2010, 2025), "type": "article"}

    # ── capture the candidate lists once, from real searches ────────────────
    # Replaying identical inputs is what makes this a one-variable experiment:
    # the SPLADE leg's own variance would otherwise dominate a 4 ms stage.
    real_pf = r._post_filter
    captured: dict[str, list] = {}
    cur = [None]

    def capture_pf(ranked, f):
        if cur[0] is not None and cur[0] not in captured:
            captured[cur[0]] = list(ranked)
        return real_pf(ranked, f)

    r._post_filter = capture_pf
    try:
        for q in queries:
            cur[0] = q
            r.search(q, top_k=args.top_k, mode="splade", filters=dict(FILTERS))
    finally:
        r._post_filter = real_pf
        cur[0] = None
    cand = {q: captured[q] for q in queries if q in captured}
    if not cand:
        raise SystemExit("no candidate lists captured — did the SPLADE leg run?")
    sizes = [len(v) for v in cand.values()]
    log.info("captured %d candidate lists, %d..%d candidates (mean %.0f)",
             len(cand), min(sizes), max(sizes), statistics.fmean(sizes))

    # ── warmup: both arms ───────────────────────────────────────────────────
    for i in range(args.warmup):
        for arm in ARMS:
            set_arm(arm)
            t0 = time.perf_counter()
            for q in queries:
                r._post_filter(cand[q], dict(FILTERS))
            log.info("  warmup %d %-9s %.0f ms for %d queries", i, arm,
                     (time.perf_counter() - t0) * 1000, len(queries))

    # ── measure ─────────────────────────────────────────────────────────────
    samples: dict[str, list[float]] = {a: [] for a in ARMS}
    mismatches = 0
    for q in queries:
        ranked = cand[q]
        for _ in range(args.reps):
            order = list(ARMS)
            rng.shuffle(order)                 # order randomised per rep
            got = {}
            for arm in order:                  # interleaved within the rep
                set_arm(arm)
                t0 = time.perf_counter()
                kept = r._post_filter(ranked, dict(FILTERS))
                samples[arm].append((time.perf_counter() - t0) * 1000)
                got[arm] = kept
            if got["staged"] != got["unstaged"]:
                mismatches += 1

    stats = {a: _stat(samples[a]) for a in ARMS}
    speedup = (round(stats["unstaged"]["p50_ms"] / stats["staged"]["p50_ms"], 2)
               if stats["staged"]["p50_ms"] else None)

    rep = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": ("does the SHIPPED _stage_meta_local/_connect_meta path "
                     "reproduce doc 18 §14's hand-copied filter-stage win "
                     "(222.2 -> 4.0 ms) on the real 24.9 GB meta.sqlite?"),
        "design": "2 arms, one variable: retriever._meta staged vs unstaged",
        "n7_expectation_ms": {"unstaged_9p": 222.2, "staged_local": 4.0,
                              "source": "doc 18 §14, 2026-08-03, hand copy"},
        "filters": FILTERS,
        "queries": queries,
        "reps_per_query": args.reps,
        "top_k": args.top_k,
        "candidates_per_query": {"min": min(sizes), "max": max(sizes),
                                 "mean": round(statistics.fmean(sizes), 1)},
        "docs_in_meta": n_src,
        "retriever_load_s": round(load_s, 1),
        "env": {
            "meta_source_path": str(src),
            "meta_source_fstype": _fstype_for_path(str(src)),
            "meta_staged_path": str(staged_path),
            "meta_staged_fstype": _fstype_for_path(str(staged_path)),
            "meta_stage_dir": os.environ.get("SFU_META_STAGE_DIR"),
            "meta_stage_verify": os.environ.get("SFU_META_STAGE_VERIFY"),
            "seismic_stage_dir": os.environ.get("SFU_SEISMIC_STAGE_DIR"),
            "dense_warmcache": os.environ.get("SFU_DENSE_WARMCACHE"),
            "splade_backend": r._splade_backend,
            "meta_schema": info.get("meta_schema"),
        },
        "method": ("candidate lists captured once per query from real "
                   "search() calls, then replayed against both arms; arms "
                   "interleaved, order randomised per rep; both warmed"),
        "stage_ms": stats,
        "speedup_staged_vs_unstaged": speedup,
        "parity": {"pairs": len(samples["staged"]), "mismatches": mismatches,
                   "pass": mismatches == 0},
    }
    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n8_meta_stage_shipped_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("_post_filter p50: unstaged %.1f ms | staged %.2f ms | %sx | "
             "parity %s", stats["unstaged"]["p50_ms"], stats["staged"]["p50_ms"],
             speedup, "PASS" if mismatches == 0 else f"FAIL({mismatches})")
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
