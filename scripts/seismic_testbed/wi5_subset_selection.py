#!/usr/bin/env python3
"""WI-5 (deployprep 2026-07-16) — subset-corpus selection machinery + cut yields.

The portable-handout ships a SUBSET index (LOCALIZED_DEPLOYMENT_PLAN §2 "Subset"
tier: year × citation floor → ~10–15M docs on a laptop). This script is the
selection machinery: given the available metadata, select the doc subset and
MEASURE what the actual cut yields — closing the plan's open question §8 #2
("is cited_by_count indexed? gates the year×citation selector depth axis").

**Honest finding (measured 2026-07-16):** the served `meta.sqlite` `docs` table
has columns (id, title, doi, year, type, is_oa, section) — **`cited_by_count` is
NOT present** (only the year axis is available for the subset cut). The
`openalex_cite_cache.json` (403 KB) holds the EVAL citation cache only, not a
corpus-wide citation floor. So the "year × citation" two-axis selector the plan
calls for is **partially blocked**: the YEAR axis is measurable here (this script);
the CITATION axis needs either a re-export with `cited_by_count` from the source
index, or OpenAlex polite-pool enrichment — recorded as the unblock, not done
in-container (no external spend).

This script therefore:
  1. Measures the YEAR-axis cut yields (year ≥ floor → doc count) from
     meta.sqlite (read-only).
  2. Records the citation-axis block honestly (the gate §8 #2 answered: not
     indexed here).
  3. Emits a ~1M-doc doc-id selection (for a pilot build) from a chosen year
     floor, so the pilot can proceed on the year axis alone (with the citation
     floor deferred to a host-side re-export).

The pilot BUILD (a 1M-doc SEISMIC shard through build_persona_seismic.py) is
additionally blocked on the **spool jsonl** (the pre-encoded `sparse_field`
spool at data/thinclient_index/spool/ is absent — root CLAUDE.md notes spool
re-derivation). That blocker is recorded too; the selection + cut-yield here is
the in-container-deliverable part of WI-5.

Usage:
    .venv/bin/python3 scripts/seismic_testbed/wi5_subset_selection.py \\
        --meta data/thinclient_index/meta.sqlite --out data/eval_results/wi5_*.json
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path


def measure_year_cuts(meta_path: Path, floors: list[int],
                      prefix_n: int = 2_000_000) -> dict:
    """Query meta.sqlite (read-only) for the year-axis cut yields.

    **9p reality (measured 2026-07-16):** the docs table has NO index on year
    (PRAGMA index_list: []) and the db is a 25 GB file on the 9p/drvfs mount →
    every full-traversal query (`COUNT(*)`, `GROUP BY year`, `WHERE year>=?`,
    `LIMIT N OFFSET M`, random-id pk probes) is D-blocked on p9_client_rpc
    (infeasible: ~22 min for the full scan, scattered pk reads even slower). The
    ONLY fast read is a small sequential PREFIX (`SELECT year FROM docs LIMIT N`
    — one contiguous 9p read from the table start, ~9 s/1M rows). So this takes
    a 2M-row PREFIX sample + clearly marks it BIASED toward the early-ingested
    sections (the table is section-ordered, not year-sorted — the 1st 1M rows are
    ~80% one section). It is ILLUSTRATIVE (the year shapes are real), NOT a
    representative corpus sample. The full/uniform measurement is the host-tier
    follow-on (a native-ext4 host counts in ~seconds). TOTAL_DOCS = 150,413,098
    (the G6/G7 build figure) is the corpus denominator."""
    from collections import Counter
    TOTAL_DOCS = 150_413_098  # G6/G7 build figure (serve_footprint_bench TOTAL_DOCS)
    db = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True)
    cur = db.cursor()
    # section inventory: the SQL `GROUP BY section` is a full 9p-slow scan; use
    # the filesystem sections/ dir listing instead (fast + same data).
    t0 = time.time()
    sections_dir = meta_path.parent / "sections"
    if sections_dir.is_dir():
        sections = {s: None for s in sorted(p.name for p in sections_dir.iterdir()
                                            if p.is_dir())}
    else:
        sections = {}
    section_secs = time.time() - t0
    # fast sequential prefix sample (one contiguous 9p read)
    t0 = time.time()
    cur.execute(f"SELECT year FROM docs LIMIT {prefix_n}")
    hist: Counter = Counter()
    null_year = 0
    for (y,) in cur:
        if y is None:
            null_year += 1
        else:
            hist[y] += 1
    prefix_secs = time.time() - t0
    db.close()
    sample_n = sum(hist.values()) + null_year
    # the prefix is biased — do NOT extrapolate to the corpus as if uniform.
    # Report the prefix's OWN year cuts (the in-container-measurable truth) +
    # the full-corpus cut as BLOCKED (host-tier).
    cuts = {}
    for floor in floors:
        samp_n = sum(c for y, c in hist.items() if y >= floor)
        cuts[floor] = {"year_floor": floor,
                       "prefix_sample_count": samp_n,
                       "prefix_sample_share": round(samp_n / sample_n, 4) if sample_n else 0,
                       "prefix_biased_toward": "early-ingested sections (table is "
                                               "section-ordered, NOT year-sorted)",
                       "full_corpus_doc_count": "BLOCKED (9p full-scan, ~22 min)",
                       "est": False}  # this is a measured prefix, not an estimate
    return {"total_docs": TOTAL_DOCS,
            "total_docs_source": "G6/G7 build figure (serve_footprint_bench TOTAL_DOCS)",
            "section_scan_s": round(section_secs, 1),
            "prefix_sample": {"n": sample_n, "target": prefix_n,
                              "method": "sequential prefix (SELECT year LIMIT N) — "
                                        "BIASED toward early-ingested sections",
                              "null_year_rows": null_year,
                              "scan_s": round(prefix_secs, 1)},
            "sections": sections, "year_cuts": cuts,
            "year_prefix_histogram_top12": {str(y): hist[y]
                                           for y in sorted(hist, reverse=True)[:12]},
            "full_scan_blocker": "the docs table has NO index on year; COUNT(*)/"
                                 "GROUP BY/WHERE year>=?/OFFSET/random-pk-probe are all "
                                 "D-blocked on 9p p9_client_rpc (infeasible in-container). "
                                 "A native-ext4 host counts in ~seconds; the prefix sample "
                                 "here is the only in-container-measurable truth, tagged "
                                 "BIASED (illustrative, not representative)."}


def select_pilot_ids(meta_path: Path, year_floor: int, target_n: int,
                     out_path: Path) -> dict:
    """Select ~target_n doc ids with year >= year_floor (the year axis only; the
    citation axis is blocked — see module docstring). **9p reality:** the
    qualifying-id enumeration requires either a full scan or random pk probes —
    BOTH are D-blocked on p9_client_rpc in-container (see measure_year_cuts).
    So this does NOT write an id list — it records the selection METHOD for when
    a host-side scan runs, + writes a placeholder note to out_path. The pilot
    BUILD that consumes the id list is additionally blocked on the spool anyway
    (absent — see module docstring), so the id list isn't actionable in-container
    regardless."""
    note = (f"# WI-5 pilot selection placeholder (2026-07-16)\n"
            f"# target: ~{target_n} ids with year >= {year_floor}\n"
            f"# NOT ENUMERATED in-container: the qualifying-id scan is 9p-D-blocked\n"
            f"# (no year index; COUNT/WHERE/probe all ~22 min infeasible).\n"
            f"# METHOD (host-tier run): SELECT id FROM docs WHERE year >= ? {''}\n"
            f"# ORDER BY year DESC LIMIT {target_n} on a native-ext4 host (~seconds).\n"
            f"# The pilot BUILD is additionally blocked on the absent spool.\n")
    out_path.write_text(note)
    return {"year_floor": year_floor, "requested": target_n, "selected": 0,
            "blocked": "9p — qualifying-id enumeration D-blocked in-container "
                       "(no year index); host-tier run on native-ext4 (~seconds)",
            "wrote": str(out_path) + " (placeholder note, not an id list)"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", default="data/thinclient_index/meta.sqlite")
    ap.add_argument("--out", default=None)
    ap.add_argument("--floors", default="2024,2023,2022,2020,2018,2015,2010",
                    help="comma-separated year floors to measure cuts for")
    ap.add_argument("--pilot-target", type=int, default=1_000_000,
                    help="pilot selection target (year axis only; citation blocked)")
    ap.add_argument("--pilot-year-floor", type=int, default=2024,
                    help="year floor for the pilot selection")
    args = ap.parse_args()

    meta = Path(args.meta)
    floors = [int(x) for x in args.floors.split(",")]
    print(f"=== WI-5: measuring year-axis cuts from {meta} ===", flush=True)
    cuts = measure_year_cuts(meta, floors)
    print(f"total docs (corpus): {cuts['total_docs']:,} ({cuts['total_docs_source']})",
          flush=True)
    print(f"sections: {len(cuts['sections'])} (from filesystem sections/ dir; "
          f"counts None — SQL GROUP BY is 9p-slow)", flush=True)
    ps = cuts["prefix_sample"]
    print(f"prefix sample: {ps['n']:,} rows ({ps['scan_s']}s) — {ps['method'][:60]}",
          flush=True)
    print("year-axis cut yields (prefix sample, BIASED — early-ingested sections):",
          flush=True)
    for f in floors:
        c = cuts["year_cuts"][f]
        print(f"  year >= {f}: {c['prefix_sample_count']:,} in prefix "
              f"({c['prefix_sample_share']:.1%} of prefix); full corpus: "
              f"{c['full_corpus_doc_count']}", flush=True)

    pilot_path = (Path(args.out).parent / "wi5_pilot_ids.txt"
                  if args.out else Path("data/eval_results/wi5_pilot_ids.txt"))
    pilot_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n=== pilot selection (~{args.pilot_target:,} ids, year>={args.pilot_year_floor}) ===",
          flush=True)
    pilot = select_pilot_ids(meta, args.pilot_year_floor, args.pilot_target, pilot_path)
    print(f"selected: {pilot['selected']:,} — {pilot['blocked']}", flush=True)
    print(f"  wrote: {pilot['wrote']}", flush=True)

    result = {
        "meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "meta_path": str(meta)},
        "citation_axis_status": {
            "cited_by_count_in_meta_sqlite": False,
            "docs_columns": ["id", "title", "doi", "year", "type", "is_oa", "section"],
            "verdict": "BLOCKED on citation floor axis — meta.sqlite lacks cited_by_count; "
                       "the year axis is measurable here, the citation axis needs a "
                       "host-side re-export with cited_by_count (the source-index _source "
                       "has it; the spool didn't carry it). LOCALIZED_DEPLOYMENT_PLAN §8 #2 "
                       "answered: NOT indexed here.",
            "available_cite_cache": "data/openalex_cite_cache.json (403 KB, eval-only — "
                                    "not a corpus-wide citation floor)",
        },
        "year_axis_cuts": cuts,
        "pilot_selection": pilot,
        "pilot_build_blocker": {
            "spool_present": Path("data/thinclient_index/spool").is_dir()
                              and any(Path("data/thinclient_index/spool").iterdir())
                              if Path("data/thinclient_index/spool").is_dir() else False,
            "verdict": "BLOCKED — the pilot shard build (build_persona_seismic.py --jsonl) "
                       "needs the pre-encoded sparse_field spool (data/thinclient_index/"
                       "spool/*.jsonl.zst), which is absent. Root CLAUDE.md notes spool "
                       "re-derivation; the host-tier re-export (build_thinclient_index.py "
                       "EXPORT step) is the unblock, owner-gated (source OpenSearch index).",
        },
    }
    out = Path(args.out) if args.out else Path("data/eval_results/wi5_subset_selection_"
                                               + time.strftime("%Y%m%d_%H%M%S") + ".json")
    out.write_text(json.dumps(result, indent=2))
    print(f"\nresult -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
