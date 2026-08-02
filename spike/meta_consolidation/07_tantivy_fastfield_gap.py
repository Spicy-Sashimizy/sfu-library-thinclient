#!/usr/bin/env python3
"""C6 gap #1 — is reading an ordinal out of tantivy per hit actually cheap?

§13's ordinal design is load-bearing on one unmeasured assumption: that after a
tantivy hit, getting that doc's ORDINAL is cheap. §11's addendum suggested
fast-field reads are not the bottleneck (only the term dictionary is), but that
run was ordering-confounded and its absolute numbers were explicitly marked
unquotable. This closes the gap properly.

The production schema (`builder.py:129-134`) already declares
`year` as `add_integer_field(..., fast=True)`. Reading a u64 fast field for a
batch of DocAddresses is the SAME mechanism an `ordinal` fast field would use,
at the SAME production scale — so `year` is an exact proxy and no rebuild is
needed to answer the question.

Two arms, on the REAL production index, over REAL eval queries:

  stored_id   [searcher.doc(a)["id"][0] for a in addrs]   <- production today
  fast_field  searcher.fast_field_values("year", addrs)   <- the ordinal path

Methodology note: §11's addendum ran all of arm A then all of arm B, so A
absorbed the cold page faults and B reused them — which made the arm doing MORE
work look FASTER and rendered the absolute numbers meaningless. Here the arms
are **interleaved within each repetition** and their order is **randomised per
rep**, so neither can systematically warm the other.

Read-only: `tantivy.Index.open` is the same call `retriever._load:378` makes.

    .venv/bin/python3 spike/meta_consolidation/07_tantivy_fastfield_gap.py
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("c6gap")

SECTION = "social_sciences__recent"
TANTIVY_DIR = ROOT / "data" / "thinclient_index" / "sections" / SECTION / "tantivy"
QUERIES = ROOT / "data" / "sfu_eval_queries.json"

# retriever._bm25f_leg scrubs non-alphanumerics before parse_query (retriever.py:682).
# Omitting it is what broke the §3 harness — a hyphen builds a PHRASE query
# against index_option="freq" fields and raises. Reproduced here deliberately.
_SCRUB = re.compile(r"[^0-9A-Za-z\s]+")


def scrub(q: str) -> str:
    return _SCRUB.sub(" ", q).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, nargs="+", default=[10, 50, 100, 500])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    import tantivy

    idx = tantivy.Index.open(str(TANTIVY_DIR))
    idx.reload()
    searcher = idx.searcher()
    schema = idx.schema
    log.info("opened %s (%d docs)", SECTION, searcher.num_docs)

    raw = json.loads(QUERIES.read_text())
    queries = [scrub(q["query"]) for q in raw if q.get("query")]
    log.info("%d eval queries", len(queries))

    rng = random.Random(args.seed)
    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "section": SECTION,
              "num_docs": searcher.num_docs, "results": {},
              "method": "arms interleaved per rep, order randomised per rep"}

    for k in args.k:
        # Pre-resolve hit addresses so neither arm pays for the search itself.
        addr_sets, search_ms = [], []
        for i in range(args.reps + args.warmup):
            q = idx.parse_query(queries[(i * 7) % len(queries)], ["title", "abstract"])
            t0 = time.perf_counter()
            hits = searcher.search(q, k).hits
            search_ms.append((time.perf_counter() - t0) * 1000)
            addr_sets.append([a for _s, a in hits])

        def arm_stored(addrs):
            return [searcher.doc(a)["id"][0] for a in addrs]

        def arm_fast(addrs):
            return searcher.fast_field_values("year", addrs)

        for i in range(args.warmup):
            arm_stored(addr_sets[i])
            arm_fast(addr_sets[i])

        s_ms, f_ms = [], []
        for i in range(args.warmup, args.warmup + args.reps):
            addrs = addr_sets[i]
            if not addrs:
                continue
            order = [arm_stored, arm_fast]
            rng.shuffle(order)          # neither arm is systematically first
            timings = {}
            for fn in order:
                t0 = time.perf_counter()
                fn(addrs)
                timings[fn.__name__] = (time.perf_counter() - t0) * 1000
            s_ms.append(timings["arm_stored"])
            f_ms.append(timings["arm_fast"])

        s_ms.sort()
        f_ms.sort()
        hits_n = statistics.median(len(a) for a in addr_sets)
        e = {"requested_k": k, "median_hits": hits_n,
             "search_p50_ms": round(statistics.median(search_ms), 3),
             "stored_id_p50_ms": round(statistics.median(s_ms), 4),
             "fast_field_p50_ms": round(statistics.median(f_ms), 4),
             "stored_over_fast": (round(statistics.median(s_ms)
                                        / statistics.median(f_ms), 1)
                                  if statistics.median(f_ms) else None)}
        e["fast_field_us_per_doc"] = (round(1000 * statistics.median(f_ms) / hits_n, 2)
                                      if hits_n else None)
        report["results"][str(k)] = e
        log.info("k=%-5d hits=%-5s search %.2f ms | stored-id %.4f ms | "
                 "fast-field %.4f ms (%.2f us/doc) -> stored is %sx the fast path",
                 k, hits_n, e["search_p50_ms"], e["stored_id_p50_ms"],
                 e["fast_field_p50_ms"], e["fast_field_us_per_doc"],
                 e["stored_over_fast"])

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c6_tantivy_fastfield_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
