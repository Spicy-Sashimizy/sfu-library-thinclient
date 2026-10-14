#!/usr/bin/env python3
r"""Delta-ingest doc 11: P2 on a multi-section fixture -- BM25F drift of layout
`single` (and `per_era`, recorded) vs `per_base_section` on corpus (b).

Spec: docs/delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md (frozen bc83761e,
owner decision 2026-10-04: gate eligibility waits for this check). Its §2 is
copied verbatim below, before the first run (doc 11 §4). Written 2026-10-04,
before any number existed.

Subcommands (/home/vscode/work/venv_local/bin/python3, cwd = repo):
  sample     the 600 stratified title queries -> WORK/sample.json
  measure    one process for one contrast: --contrast 1 opens G0, N1, S1, E1;
             --contrast 8 opens N8, S8, E8. Fixture assertions, health, then
             Part A (600 titles, `_bm25f_leg(title, 100, None)`), Part B (120
             topics, `search_rrf_detailed(q, top_k=50)` + rerank to 10) and
             Part C (600 titles, same call) on every arm, query by query.
  summarize  bars A, A2, B, C, D per contrast -> results JSON.
  run        measure for both contrasts (child processes, gates blanked,
             shared latency lock) then summarize.

Stopping (added 2026-10-04 before the 8-generation contrast started; no bar,
sample or statistic involved): a measure process stops cleanly BEFORE its
next query on SIGTERM / SIGINT or when the file <rows-out>.STOP exists,
writes its rows with the stop reason and exits 4 (the verdict is then NOT
READ). Rows are also written atomically every 20 queries, so a hard kill
loses at most 20 queries. Nothing is ever written under a fixture root.
`--resume` continues from an existing rows file of the same contrast, sample
and code snapshot, skipping the queries already done (each session is listed
in `sessions`); `run --resume` skips a contrast whose rows are complete.

Operational definitions fixed here before the first run (none changes a bar):
  * rank = 1-based position of the doc's own id in the returned list; absent
    = not in the leg's top-100 (A) / not in the fused top-50 (C).
  * Part A/A2 use the post-mask leg output. Part D reads the pre-mask hit
    list handed to DeltaLayer.filter_hits ((id, score, origin), captured by a
    wrapper as M3 did): a corpus (b) id whose origin is not its ledger
    generation is a wrong-origin hit; an id occurring twice in one post-mask
    leg list or fused list is a duplicate.
  * B/C displacement is counted on the fused top-10 (the bar), and recorded
    on the BM25F leg's own top-10 and on the final (reranked) top-10.
  * The E arms and G0 are recorded; the §3 fallback reading for `per_era`
    applies the same rule to E vs N.

---- doc 11 §2, verbatim ----
## 2. Measurements and frozen bars

Code under test: `git archive <HEAD at drive time> src`. Serving levers
L3–L5 unset in every arm (L2 is the only variable). One process per
contrast, arms opened in-process as in `eval_delta_ingest_m4f.py`
(`open_arm`), same health assertions; shared latency lock, **timings
invalid by declaration**. Queries run on both arms of a contrast in the
same order.

**Sample (Parts A and C):** 600 corpus (b) docs with a non-empty title:
120 from each of the five `__recent` sections, drawn with
`numpy.default_rng(20261003)` (one `permutation` per section, sections in
alphabetical order, first 120 with `title.strip() != ""` and at least 4
whitespace-separated tokens). The same 600 for every arm.

| # | Question | Metric | Bar (frozen) |
|---|---|---|---|
| **A** | Does pooling subjects into one section move a delta doc's BM25F rank? | `_bm25f_leg(title, 100, None)` (M3 Part A's entry point), rank of the doc's own id, per doc: `rank_S − rank_N` over docs present in both arms | **median = 0 overall AND in each of the 5 strata**, on BOTH contrasts (S1 vs N1, S8 vs N8) |
| **A2** | Does it lose docs from the leg? | own-recall@100 (share of the 600 whose id is in the leg's top-100) | `recall(S) ≥ recall(N) − 0.01` on both contrasts |
| **B** | Control on the 120 topics (M3 Part B's definition, layout vs layout) | `search_rrf_detailed(q, top_k=50)`; displaced = a doc in the N-arm fused top-10 absent from the S-arm fused top-10, summed over 120 topics | **≤ 60** of 1,200 slots (5 %, the M3 bar) on both contrasts |
| **C** | Does the fused result change when the query targets a delta doc? | `search_rrf_detailed(title, top_k=50)` for the 600 titles; displaced as in B; and the rank of the doc's own id in the fused list | displaced **≤ 5 %** of 6,000 slots (≤ 300) on both contrasts; own-id fused-rank median change **0** |
| **D** | Mask and plumbing integrity | any id returned twice in one leg list; any id of corpus (b) served from a section not of its generation | **0** |

PASS = A, A2, B, C, D all hold on both contrasts. Recorded without a bar:
the rank-change quantiles and better/same/worse shares per stratum; the
S/N raw-score ratio of the own doc; the same numbers for E1 vs N1 and E8 vs
N8; B and C computed on the BM25F leg's own top-10 and on the final
(reranked) top-10; B against G0 (base docs leaving the fused top-10 when
the layer is on, per layout).

N: 600 titles and 120 topics, 1 pass per arm; no partial pass (a run that
stops early is NOT READ).
---- end of doc 11 §2 ----
"""
from __future__ import annotations

import argparse
import calendar
import copy
import fcntl
import filecmp
import importlib.util
import json
import os
import signal
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
E = os.environ.get
ROOTS = Path(E("SFU_P2MS_ROOTS", "/home/vscode/work/inplace_update/m4"))
WORK = Path(E("SFU_P2MS_WORK", "/home/vscode/work/delta_ingest/p2_multisection"))
TOPICS = REPO / "data/sfu_eval_queries.json"
LOCK = E("SFU_P2MS_LOCK", "/tmp/sfu_latency_measure.lock")
SEED = 20261003
PER_STRATUM = 120
MIN_TOKENS = 4
STRATA = ("cs_math__recent", "med_bio__recent", "other__recent", "phys_eng__recent", "social_sciences__recent")
CONTRASTS = {"1": {"ref": "n1", "test": "s1", "recorded": "e1", "control": "n0"},
             "8": {"ref": "n8", "test": "s8", "recorded": "e8", "control": None}}
SECTIONS_PER_GEN = {"n": (8, 10), "s": (1, 1), "e": (1, 2)}
LEG_K = 100
TOP_K = 50
LIMIT = 10
BARS = {"A_median": 0, "A2_recall_drop": 0.01, "B_displaced": 60, "C_displaced": 300, "C_rank_median": 0, "D": 0}
BLANK_ENV = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_SEISMIC_SHARD_MANIFEST", "SFU_DELTA_ROOT",
             "SFU_THINCLIENT_ORDINALS", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_DELTA_ABS_ROUTE",
             "SFU_BM25F_PARSE_ONCE", "SFU_SEISMIC_DELTA_GROUP", "SFU_OA_BITMAP", "SFU_SEISMIC_SHARD_FAULT_BOUNDARY")
UNSET_ENV = ("SFU_SEISMIC_K_PRIME", "SFU_SEISMIC_QUERY_CUT", "SFU_SEISMIC_HEAP_FACTOR")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    print(f"{utc()} {msg}", flush=True)


def dump_json(path: Path, obj) -> None:
    tmp = Path(str(path) + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, default=str) + "\n")
    os.replace(tmp, path)


def git_head() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def load_m4f():
    spec = importlib.util.spec_from_file_location("m4f", REPO / "scripts/experiments/eval_delta_ingest_m4f.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ledger(root: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{root / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)


# ── sample ──────────────────────────────────────────────────────────────────
def draw_sample(rows_by_section: dict, seed: int = SEED, per: int = PER_STRATUM) -> list:
    """`rows_by_section[s]` = [(id, title)] sorted by id. One permutation per
    stratum, strata in alphabetical order, one generator for all."""
    rng = np.random.default_rng(seed)
    out = []
    for s in sorted(STRATA):
        rows = rows_by_section.get(s) or []
        kept = 0
        for j in rng.permutation(len(rows)):
            i, t = rows[int(j)]
            if (t or "").strip() and len(t.split()) >= MIN_TOKENS:
                out.append({"id": i, "title": t, "stratum": s})
                kept += 1
                if kept == per:
                    break
        if kept != per:
            raise SystemExit(f"stratum {s}: only {kept} eligible titles")
    return out


def cmd_sample(a) -> int:
    db = ledger(ROOTS / "root_n1")
    by: dict = {}
    for s in STRATA:
        by[s] = [(i, json.loads(rec).get("title") or "") for i, rec in db.execute(
            "SELECT d.id, r.record FROM docs d JOIN records r ON r.id=d.id WHERE d.status='live' AND d.section=? "
            "ORDER BY d.id", (s,))]
    db.close()
    sample = draw_sample(by)
    WORK.mkdir(parents=True, exist_ok=True)
    dump_json(WORK / "sample.json", {"created_utc": utc(), "seed": SEED, "per_stratum": PER_STRATUM,
                                    "min_tokens": MIN_TOKENS, "source": str(ROOTS / "root_n1/ledger.sqlite"),
                                    "population": {s: len(v) for s, v in by.items()}, "sample": sample})
    print(json.dumps({"n": len(sample), "population": {s: len(v) for s, v in by.items()}}))
    return 0


# ── fixture assertions ──────────────────────────────────────────────────────
def root_facts(tag: str) -> dict:
    root = ROOTS / f"root_{tag}"
    gj = json.loads((root / "generations.json").read_text())
    db = ledger(root)
    gen = {i: int(g) for i, g in db.execute("SELECT id, generation FROM docs WHERE status='live'")}
    tomb = db.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]
    db.close()
    man = json.loads(Path(gj["shard_manifest"]).read_text())["shards"]
    return {"root": str(root), "generations": [(g["gen"], g["docs"], len(g["sections"])) for g in gj["generations"]],
            "mask": {"deleted": len(gj["mask"].get("deleted") or []), "superseded": len(gj["mask"].get("superseded") or {}),
                     "tombstones": tomb}, "livedocs": bool(gj.get("livedocs")), "gen": gen,
            "seismic_dirs": [r["mmap_dir"] for r in man if r.get("delta_generation") is not None]}


def check_fixture(tags: list, bad) -> dict:
    facts = {t: root_facts(t) for t in tags}
    ref = facts[tags[0]]
    for t, f in facts.items():
        lo, hi = SECTIONS_PER_GEN[t[0]]
        if any(not (lo <= n <= hi) for _g, _d, n in f["generations"]):
            bad(f"{t}: sections per generation {[n for _g, _d, n in f['generations']]} outside {lo}-{hi}")
        if f["mask"] != {"deleted": 0, "superseded": 0, "tombstones": 0} or f["livedocs"]:
            bad(f"{t}: masks not empty {f['mask']} livedocs={f['livedocs']}")
        if f["gen"] != ref["gen"]:
            bad(f"{t}: live ids / generations differ from {tags[0]}")
        if len(f["seismic_dirs"]) != len(ref["seismic_dirs"]):
            bad(f"{t}: {len(f['seismic_dirs'])} delta shards vs {len(ref['seismic_dirs'])}")
            continue
        for da, db_ in zip(ref["seismic_dirs"], f["seismic_dirs"]):
            names = sorted(p.name for p in Path(da).iterdir())
            if names != sorted(p.name for p in Path(db_).iterdir()):
                bad(f"{t}: SEISMIC dir listing differs ({db_})")
                continue
            _m, mism, err = filecmp.cmpfiles(da, db_, names, shallow=False)
            if mism or err:
                bad(f"{t}: SEISMIC files differ from {tags[0]}: {mism + err}")
    return {t: {k: v for k, v in f.items() if k != "gen"} | {"live_docs": len(f["gen"])} for t, f in facts.items()}


# ── measure ─────────────────────────────────────────────────────────────────
def rank_of(ids: list, doc: str):
    try:
        return ids.index(doc) + 1
    except ValueError:
        return None


def wrong_origin(hits: list, gen: dict) -> int:
    return sum(1 for d, _s, o in hits if d in gen and o != gen[d])


def cmd_measure(a) -> int:
    t_start = time.time()
    sys.path.insert(0, a.src or str(REPO / "source"))
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    import logging
    m4f = load_m4f()
    cap = m4f.M4._WarnCapture()
    logging.getLogger().addHandler(cap)
    guard = m4f.MemGuard()
    guard.start()
    health = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)
        log(f"HEALTH: {msg}")

    fh = None
    lock = {"mode": a.lock}
    if a.lock != "none":
        fh = open(LOCK, "a+")
        t0 = time.time()
        fcntl.flock(fh, fcntl.LOCK_SH)
        lock.update(acquired_utc=utc(), waited_s=round(time.time() - t0))
    c = CONTRASTS[a.contrast]
    delta_tags = [c["ref"], c["test"], c["recorded"]]
    names = ([c["control"]] if c["control"] else []) + delta_tags
    fixture = check_fixture(delta_tags, bad)
    gen = root_facts(c["ref"])["gen"]
    sample = json.loads((WORK / "sample.json").read_text())["sample"][: a.limit or None]
    topics = [r["query"] for r in json.loads(TOPICS.read_text())][: a.limit or None]
    if any(s["id"] not in gen for s in sample):
        bad("a sample id is not a live corpus (b) doc")
    h, cfg = m4f._common_health(bad)
    health.update(h)
    import lib.tools as tools
    prior = None
    if a.resume and Path(a.rows_out).exists():
        prior = json.loads(Path(a.rows_out).read_text())
        same = (prior.get("contrast") == a.contrast and prior.get("limit") == a.limit
                and prior.get("src") == (a.src or "working tree") and prior.get("arms_order") == names
                and [r["id"] for r in prior.get("A") or []] == [x["id"] for x in sample[: len(prior.get("A") or [])]])
        if not same:
            bad("--resume: the existing rows file is from another contrast, sample, limit or code snapshot")
            prior = None
    stop_file = Path(str(a.rows_out) + ".STOP")
    sig = {"name": None}
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, lambda n, _f: sig.update(name=signal.Signals(n).name))
    out = {"run": "P2MS", "contrast": a.contrast, "script": "scripts/experiments/eval_delta_ingest_p2_multisection.py",
           "git_head": git_head(), "src": a.src or "working tree", "start_utc": utc(), "lock": lock, "arms_order": names,
           "fixture": fixture, "limit": a.limit, "health": health, "arms": {},
           "A": list((prior or {}).get("A") or []), "B": list((prior or {}).get("B") or []),
           "C": list((prior or {}).get("C") or []),
           "sessions": list((prior or {}).get("sessions") or []) + [{"start_utc": utc(), "pid": os.getpid(),
                                                                      "resumed_at": {k: len((prior or {}).get(k) or []) for k in "ABC"}}]}
    arms, captured = {}, {}
    for n in names:
        try:
            r, b, probs, info = m4f.open_arm(m4f.resolve_arm(n), cfg)
        except Exception as exc:
            bad(f"{n}: open raised {exc!r}")
            continue
        for p in probs:
            bad(p)
        arms[n] = r
        out["arms"][n] = info
        if r._delta is not None:
            if r._delta.buffer_size() != 0:
                bad(f"{n}: delta buffer not empty")
            box = captured.setdefault(n, {"hits": []})
            orig = r._delta.filter_hits

            def wrapped(hits, _orig=orig, _box=box):
                _box["hits"] = list(hits)
                return _orig(hits)
            r._delta.filter_hits = wrapped
        log(f"arm {n}: {info}")
    if any(any(s in w for s in m4f.SIGNATURES) for w in cap.records):
        bad("failure signature logged at load")
    if prior is None or not health["ok"]:
        dump_json(Path(a.rows_out) if prior is None else Path(str(a.rows_out) + ".health_fail"), out)
    if not health["ok"] or len(arms) != len(names):
        log(f"HEALTH FAIL {health['problems']}")
        return 3
    deadline = float(calendar.timegm(time.strptime(a.deadline, "%Y-%m-%dT%H:%M:%SZ"))) if a.deadline else None
    stop = None

    def halted():
        if sig["name"]:
            return f"stop requested by {sig['name']}"
        if stop_file.exists():
            return f"stop requested by {stop_file.name}"
        if guard.tripped:
            return f"memory abort: {guard.tripped}"
        if deadline and time.time() > deadline:
            return "deadline reached"
        return None

    def progress(part, i, n):
        if (i + 1) % 20 == 0:
            log(f"{part} {i + 1}/{n} avail {guard.avail_gb():.1f} GB")
            dump_json(Path(a.rows_out), {**out, "partial": True, "mem": guard.state()})

    def fused_call(r, q, n):
        det = r.search_rrf_detailed(q, top_k=TOP_K)
        hits = list(captured.get(n, {}).get("hits") or [])
        fused = [{k: v for k, v in d.items() if k != "rrf_legs"} for d in det["results"]]
        final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
        fids = [d.get("openalex_id") for d in fused]
        return {"fused_ids": fids, "bm25f10": det["legs"].get("bm25f", [])[:10],
                "final_ids": [d.get("openalex_id") for d in final], "dup": len(fids) - len(set(fids)),
                "wrong_origin": wrong_origin(hits, gen)}

    for i, s in enumerate(sample):
        if i < len(out["A"]):
            continue
        stop = halted()
        if stop:
            break
        row = {"i": i, "id": s["id"], "stratum": s["stratum"]}
        for n in delta_tags:
            res = arms[n]._bm25f_leg(s["title"], LEG_K, None)
            hits = list(captured[n]["hits"])
            ids = [d for d, _ in res]
            rk = rank_of(ids, s["id"])
            row[n] = {"rank": rk, "score": float(res[rk - 1][1]) if rk else None, "n": len(ids),
                      "dup": len(ids) - len(set(ids)), "wrong_origin": wrong_origin(hits, gen),
                      "delta_in_top100": sum(1 for d in ids if d in gen)}
        out["A"].append(row)
        progress("A", i, len(sample))
    if not stop:
        for i, q in enumerate(topics):
            if i < len(out["B"]):
                continue
            stop = halted()
            if stop:
                break
            out["B"].append({"i": i, "query": q} | {n: fused_call(arms[n], q, n) for n in names})
            progress("B", i, len(topics))
    if not stop:
        for i, s in enumerate(sample):
            if i < len(out["C"]):
                continue
            stop = halted()
            if stop:
                break
            row = {"i": i, "id": s["id"], "stratum": s["stratum"]}
            for n in delta_tags:
                res = fused_call(arms[n], s["title"], n)
                row[n] = {"rank": rank_of(res["fused_ids"], s["id"]), "fused10": res["fused_ids"][:10],
                          "bm25f10": res["bm25f10"], "final_ids": res["final_ids"], "dup": res["dup"],
                          "wrong_origin": res["wrong_origin"]}
            out["C"].append(row)
            progress("C", i, len(sample))
    found = [w for w in cap.records if any(x in w for x in m4f.SIGNATURES)]
    if found:
        bad(f"failure signatures during the run: {found[:5]}")
    out.update(stop=stop, mem=guard.state(), wall_s=round(time.time() - t_start, 1), end_utc=utc(), warnings=len(cap.records))
    dump_json(Path(a.rows_out), out)
    log(f"done stop={stop} health_ok={health['ok']} wall={out['wall_s']}s")
    return 4 if stop else (0 if health["ok"] else 3)


# ── summarize ───────────────────────────────────────────────────────────────
def _quant(v: list) -> dict:
    if not v:
        return {"n": 0}
    q = np.percentile(v, [0, 5, 25, 50, 75, 95, 100])
    return {"n": len(v), "min": float(q[0]), "p5": float(q[1]), "p25": float(q[2]), "p50": float(q[3]),
            "p75": float(q[4]), "p95": float(q[5]), "max": float(q[6]),
            "better": sum(1 for x in v if x < 0), "same": sum(1 for x in v if x == 0), "worse": sum(1 for x in v if x > 0)}


def displaced(rows: list, ref: str, test: str, key: str) -> int:
    return sum(len([d for d in r[ref][key][:10] if d not in set(r[test][key][:10])]) for r in rows)


def compare(rows: dict, ref: str, test: str, planned: dict) -> dict:
    A, B, C = rows.get("A") or [], rows.get("B") or [], rows.get("C") or []
    both = [(r["stratum"], r[test]["rank"] - r[ref]["rank"]) for r in A if r[ref]["rank"] and r[test]["rank"]]
    overall = [d for _s, d in both]
    strata = {s: [d for st, d in both if st == s] for s in STRATA}
    med = {s: (statistics.median(v) if v else None) for s, v in strata.items()}
    a_pass = bool(overall) and statistics.median(overall) == BARS["A_median"] and all(m == BARS["A_median"] for m in med.values())
    rec_ref = sum(1 for r in A if r[ref]["rank"]) / len(A) if A else None
    rec_test = sum(1 for r in A if r[test]["rank"]) / len(A) if A else None
    ratio = [r[test]["score"] / r[ref]["score"] for r in A if r[ref]["score"] and r[test]["score"]]
    cboth = [r[test]["rank"] - r[ref]["rank"] for r in C if r[ref]["rank"] and r[test]["rank"]]
    b_disp, c_disp = displaced(B, ref, test, "fused_ids"), displaced(C, ref, test, "fused10")
    dup = sum(r[n]["dup"] for part in (A, B, C) for r in part for n in (ref, test))
    wrong = sum(r[n]["wrong_origin"] for part in (A, B, C) for r in part for n in (ref, test))
    res = {
        "A": {"median_overall": statistics.median(overall) if overall else None, "median_by_stratum": med,
              "present_in_both": len(overall), "absent_ref_only": sum(1 for r in A if not r[ref]["rank"] and r[test]["rank"]),
              "absent_test_only": sum(1 for r in A if r[ref]["rank"] and not r[test]["rank"]),
              "absent_both": sum(1 for r in A if not r[ref]["rank"] and not r[test]["rank"]),
              "quantiles_overall": _quant(overall), "quantiles_by_stratum": {s: _quant(v) for s, v in strata.items()},
              "score_ratio_test_over_ref": _quant(ratio),
              "delta_docs_in_leg_top100_mean": {n: (float(np.mean([r[n].get("delta_in_top100", 0) for r in A])) if A else None)
                                                for n in (ref, test)}, "pass": a_pass},
        "A2": {"recall100_ref": rec_ref, "recall100_test": rec_test,
               "pass": bool(A) and rec_test >= rec_ref - BARS["A2_recall_drop"]},
        "B": {"displaced_fused_top10": b_disp, "slots": 10 * len(B), "bar": BARS["B_displaced"],
              "identical_fused_top10": sum(1 for r in B if r[ref]["fused_ids"][:10] == r[test]["fused_ids"][:10]),
              "displaced_bm25f_leg_top10": displaced(B, ref, test, "bm25f10"),
              "displaced_final_top10": displaced(B, ref, test, "final_ids"),
              "pass": bool(B) and b_disp <= BARS["B_displaced"]},
        "C": {"displaced_fused_top10": c_disp, "slots": 10 * len(C), "bar": BARS["C_displaced"],
              "own_rank_median_change": statistics.median(cboth) if cboth else None, "own_rank_quantiles": _quant(cboth),
              "own_in_fused50_ref": sum(1 for r in C if r[ref]["rank"]), "own_in_fused50_test": sum(1 for r in C if r[test]["rank"]),
              "displaced_bm25f_leg_top10": displaced(C, ref, test, "bm25f10"),
              "displaced_final_top10": displaced(C, ref, test, "final_ids"),
              "pass": bool(C) and c_disp <= BARS["C_displaced"] and bool(cboth) and statistics.median(cboth) == BARS["C_rank_median"]},
        "D": {"duplicates": dup, "wrong_origin_hits": wrong, "pass": dup == 0 and wrong == 0}}
    done = {"A": len(A), "B": len(B), "C": len(C)}
    res.update(done=done, complete=done == planned and not rows.get("stop") and not rows.get("partial"),
               healthy=bool((rows.get("health") or {}).get("ok")))
    res["all_bars"] = all(res[k]["pass"] for k in ("A", "A2", "B", "C", "D"))
    return res


def cmd_summarize(a) -> int:
    planned = {"A": 600, "B": 120, "C": 600}
    rec = {"item": "doc 11 P2 on a multi-section fixture", "date_utc": utc(),
           "script": "scripts/experiments/eval_delta_ingest_p2_multisection.py",
           "preregistration": "docs/delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md §2", "bars": BARS,
           "contrasts": {}, "timings_valid": False}
    ok = {"s": True, "e": True}
    read = True
    for c, spec in CONTRASTS.items():
        p = Path(a.rows_dir) / f"rows_c{c}.json"
        if not p.exists():
            rec["contrasts"][c] = {"status": "MISSING"}
            read = False
            continue
        rows = json.loads(p.read_text())
        entry = {"rows_file": str(p), **{k: rows.get(k) for k in ("git_head", "src", "start_utc", "end_utc", "wall_s", "lock",
                                                                  "fixture", "health", "mem", "stop", "limit", "arms")},
                 "single_vs_per_base_section": compare(rows, spec["ref"], spec["test"], planned),
                 "per_era_vs_per_base_section_recorded": compare(rows, spec["ref"], spec["recorded"], planned)}
        if spec["control"]:
            B = rows.get("B") or []
            entry["B_vs_gate_off_recorded"] = {
                n: {"base_docs_leaving_fused_top10": displaced(B, spec["control"], n, "fused_ids"),
                    "identical_fused_top10": sum(1 for r in B if r[spec["control"]]["fused_ids"][:10] == r[n]["fused_ids"][:10])}
                for n in (spec["ref"], spec["test"], spec["recorded"])}
        s = entry["single_vs_per_base_section"]
        read = read and s["complete"] and s["healthy"]
        ok["s"] = ok["s"] and s["all_bars"]
        ok["e"] = ok["e"] and entry["per_era_vs_per_base_section_recorded"]["all_bars"]
        log_p = Path(a.rows_dir) / f"measure_c{c}.log"
        if log_p.exists():
            entry["log_scan"] = load_m4f().M4.scan_log(log_p)
        rec["contrasts"][c] = entry
    rec["verdict"] = ("NOT READ: run not complete/healthy on both contrasts" if not read
                      else ("PASS" if ok["s"] else "FAIL"))
    rec["per_era_same_rule_recorded"] = None if not read else ("holds" if ok["e"] else "does not hold")
    res = Path(a.out or REPO / f"data/eval_results/delta_ingest_P2_multisection_{time.strftime('%Y%m%d', time.gmtime())}.json")
    res.write_text(json.dumps(rec, indent=1, default=str) + "\n")
    brief = {c: ({k: ({x: y for x, y in v.items() if not x.startswith("quantiles") and x != "own_rank_quantiles"
                       and x != "score_ratio_test_over_ref"} if isinstance(v, dict) else v)
                  for k, v in e["single_vs_per_base_section"].items()} if "single_vs_per_base_section" in e else e)
             for c, e in rec["contrasts"].items()}
    print(json.dumps({"verdict": rec["verdict"], "per_era": rec["per_era_same_rule_recorded"], "single": brief}, indent=1))
    return 0


def cmd_run(a) -> int:
    m4f = load_m4f()
    env = {k: v for k, v in os.environ.items() if k not in UNSET_ENV}
    env.update({k: "" for k in (*m4f.M4.ENV_DROP, *BLANK_ENV)})
    env.update(m4f.MODEL_ENV)
    env["SFU_SEISMIC_FEDERATION"] = "parallel"
    out_dir = Path(a.rows_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    head = git_head()
    snap = WORK / f"code_{head}"
    if not (snap / "source").is_dir():
        snap.mkdir(parents=True, exist_ok=True)
        tar = subprocess.run(["git", "-C", str(REPO), "archive", head, "source"], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(snap)], input=tar, check=True)
        for n in ("models", "data", ".env"):
            if not (snap / n).exists():
                (snap / n).symlink_to(REPO / n)
    rcs = {}
    for c in a.contrasts.split(","):
        rp = out_dir / f"rows_c{c}.json"
        if a.resume and rp.exists():
            old = json.loads(rp.read_text())
            if not old.get("stop") and not old.get("partial") and old.get("end_utc") and (old.get("health") or {}).get("ok"):
                rcs[c] = 0
                log(f"contrast {c} already complete, skipped")
                continue
        argv = [sys.executable, __file__, "measure", "--contrast", c, "--rows-out", str(out_dir / f"rows_c{c}.json"),
                "--lock", a.lock, "--limit", str(a.limit), "--src", str(snap / "source")]
        if a.deadline:
            argv += ["--deadline", a.deadline]
        if a.resume:
            argv += ["--resume"]
        with open(out_dir / f"measure_c{c}.log", "a") as fh:
            rcs[c] = subprocess.run(argv, cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
        log(f"contrast {c} rc={rcs[c]}")
    cmd_summarize(a)
    return max(rcs.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="doc 11: P2 on a multi-section fixture")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    m = sub.add_parser("measure")
    m.add_argument("--contrast", choices=list(CONTRASTS), required=True)
    m.add_argument("--rows-out", required=True)
    m.add_argument("--src", default="")
    for p in (m, sub.add_parser("run")):
        p.add_argument("--lock", choices=["shared", "none"], default="shared")
        p.add_argument("--deadline", default="")
        p.add_argument("--limit", type=int, default=0, help="first N titles/topics (smoke; verdict NOT READ)")
        p.add_argument("--resume", action="store_true", help="continue from existing rows of the same contrast/sample/code")
        if p is not m:
            p.add_argument("--contrasts", default="1,8")
            p.add_argument("--rows-dir", default=str(WORK))
            p.add_argument("--out", default="")
    s = sub.add_parser("summarize")
    s.add_argument("--rows-dir", default=str(WORK))
    s.add_argument("--out", default="")
    a = ap.parse_args()
    return {"sample": cmd_sample, "measure": cmd_measure, "run": cmd_run, "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
