#!/usr/bin/env python3
"""Q11-C4 step 2: build the distillation query set (doc 11 §Q11-C4).

Pseudo-queries = doc titles from `data/thinclient_index/meta.sqlite`, sampled
by random-rowid run probing (rowids are sparse OpenAlex-style ids up to
~7.1e9; each probe is one B-tree seek + a short sequential run — no full
scans over 9p). Real queries = the WI-18 speculation bench pool + demo seed
queries. HOLDOUT (excluded, normalized-exact): every string in
`diverse_queries.json` (original/paraphrase/judge_key — the §4 gate set is
drawn from it) and the 120 `sfu_eval_queries` (LLM-judge lineage).

Output: `data/eval_results/_q11_c4_distill_set.jsonl` (untracked; one
{"q": ...} per line, shuffled; last DEV_N lines are the held-out dev split)
+ a small stats print for the doc row.

Rule Zero: meta.sqlite opened read-only (mode=ro); writes only the jsonl.
"""
import json
import random
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
META = REPO / "data/thinclient_index/meta.sqlite"
OUT = REPO / "data/eval_results/_q11_c4_distill_set.jsonl"

TARGET_TITLES = 480_000
RUN_LEN = 400          # rows per probe (locality over 9p)
MAX_ROWID = 7_143_276_021
DEV_N = 2_000
SEED = 20260728


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip()
    return " ".join(s.split())


def load_holdout() -> set:
    hold = set()
    for rec in json.loads((REPO / "data/eval_results/diverse_queries.json").read_text()):
        for k in ("original_query", "paraphrase", "judge_key"):
            if rec.get(k):
                hold.add(norm(rec[k]))
    for rec in json.loads((REPO / "data/sfu_eval_queries.json").read_text()):
        hold.add(norm(rec["query"]))
    return hold


def load_real_queries(hold: set) -> list:
    out = []
    for f in (REPO / "data/eval_results/speculation_bench_queries.txt",
              REPO / "data/eval_results/demo_seed_queries.txt"):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and norm(line) not in hold:
                out.append(line)
    return out


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    hold = load_holdout()
    real = load_real_queries(hold)
    print(f"holdout {len(hold)} strings; real queries kept {len(real)}")

    con = sqlite3.connect(f"file:{META}?mode=ro", uri=True)
    con.execute("pragma query_only=1")
    seen, titles = set(), []
    probes = 0
    while len(titles) < TARGET_TITLES:
        start = rng.randrange(1, MAX_ROWID)
        rows = con.execute(
            "select title from docs where rowid >= ? limit ?",
            (start, RUN_LEN)).fetchall()
        probes += 1
        for (t,) in rows:
            if not t or len(t) < 12:
                continue
            n = norm(t)
            if len(n.split()) < 3 or n in seen or n in hold:
                continue
            seen.add(n)
            titles.append(" ".join(t.split()))
        if probes % 200 == 0:
            print(f"  probes {probes}, titles {len(titles)}, "
                  f"{time.time() - t0:.0f}s", flush=True)
    con.close()

    corpus = titles[:TARGET_TITLES] + real
    rng.shuffle(corpus)
    with OUT.open("w") as f:
        for q in corpus:
            f.write(json.dumps({"q": q}) + "\n")
    stats = {"titles": min(len(titles), TARGET_TITLES), "real": len(real),
             "total": len(corpus), "dev_tail_n": DEV_N, "probes": probes,
             "run_len": RUN_LEN, "seed": SEED,
             "holdout_strings": len(hold),
             "wall_seconds": round(time.time() - t0, 1),
             "out": str(OUT.relative_to(REPO))}
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
