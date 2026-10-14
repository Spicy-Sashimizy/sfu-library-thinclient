#!/usr/bin/env python3
"""J1 — SERVING efficacy of the PUBLISHED flat abstract sidecar, at 150M.

Doc 18 §22 "Still not settled" #1: the production flat sidecar for
`social_sciences__recent` was built, gate-PASSED and published 2026-08-17
(commit f55ce5f, 11.57 GB,
`data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat/`)
— but **no serving A/B has ever been run against that directory.** §16/§17's
1.18-1.19x warm and -1.90 GB are *spike* measurements (stores built under
`/var/tmp`, read by a spike harness); they were carried forward into §22 as if
they described the published artifact. This harness closes that gap.

WHAT IS DIFFERENT FROM §17's C9 SPIKE (`15_c9_shipped_locator_reader.py`)
------------------------------------------------------------------------
1. **The published directory is the subject.** No sidecar is built here. Arm B
   reads the exact bytes the retriever serves today.
2. **Real query result sets, not random ids.** §17 fetched
   `SELECT id FROM docs ORDER BY random()`. Production fetches the *ranked
   top-k of a real query* — `_hydrate()` passes `[d for d, _ in ranked]` to
   `fetch_abstracts()`. Ranked ids are correlated (co-topical works cluster in
   the store's script buckets and therefore in its blocks), so a random-id
   benchmark measures a different block-locality regime than the serving path.
   `collect` runs the shipped `_bm25f_leg` and freezes its output.
3. **Cold as well as warm.** §16 measured 5.53x cold-ish, §17 measured 1.18x
   warm and attributed the collapse to the `docs` B-tree being page-cached.
   That attribution has never been tested on one store in one place: here the
   same arms are run after `drop_caches` and again warm.
4. **A miss regime.** Only `social_sciences__recent` is live in this container,
   so every ranked id resolves in-section and the natural miss rate is ~0. In a
   federated deployment most top-k ids belong to *other* sections and miss this
   store. The two arms are NOT symmetric on a miss: the sqlite arm's miss costs
   one `docs` B-tree probe that returns nothing, while the flat arm's miss costs
   a `searchsorted` **and then the same `docs` probe** as fallback
   (`_fetch_via_locator` -> `_fetch_via_docs`, hazard 2). `synthetic_miss50`
   makes that asymmetry visible instead of assuming it away.

HOW THE ARMS ARE SWITCHED (no published file is moved, renamed or written)
--------------------------------------------------------------------------
`AbstractStore` has **no env gate**: it serves flat iff
`<name>.flat/` `is_dir()` (abstracts.py, `AbstractStore.__init__`). The arms are
therefore built the way `build_flat_blocks.py`'s own gate and §17's harness
build theirs — **symlink views in a temp directory outside the index tree**:

    arm sqlite      <work>/sqlite/abstracts.sqlite      -> published .sqlite
                    (no `.flat` sibling -> `_flat is None`, `_locator is None`)
    arm flat        <work>/flat/abstracts.sqlite        -> published .sqlite
                    <work>/flat/abstracts.sqlite.flat   -> published .flat/
    arm sqlite_ctrl a second sqlite view — the per-run noise floor (doc 18 §14)

The published inodes are the ones read in every arm. `journal_mode=delete`
(verified 2026-08-17), so opening the db read-write — exactly as
`retriever.py:627` does — writes nothing. Each arm asserts its own wiring
before any timing; a silently mis-wired arm would void the comparison.

FILESYSTEM CAVEAT (doc 18 §14, and §16's own qualification)
-----------------------------------------------------------
`data/thinclient_index/` is **9p** in this container. §16 measured the identical
payload move at **2.89x on 9p and 1.21x on local disk** — a ~2.4x inflation,
because on 9p SQLite's B-tree costs several ~0.5 ms faults where the flat store
costs one `pread`. Any multiple this harness reports for a *cold* or
fault-bound regime is therefore an upper bound on what a droplet with local disk
would see. The warm regime, where both arms are page-cache resident, is the one
that transfers. Both are reported; neither is quoted alone.

USAGE (the driver `j1_flat_sidecar_serving_ab.sh` sequences these)
    collect      real bm25f top-k id sets, frozen to JSON
    bench        ONE arm, fresh process (the cold measurement)
    interleaved  all arms in one process, order-randomised (the warm measurement
                 + the byte-parity gate)
    verdict      merge, apply the pre-registered bars below
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import shutil
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "scripts"))

log = logging.getLogger("j1")

SECTION = "social_sciences__recent"
SRC = ROOT / "data" / "thinclient_index" / "sections" / SECTION / "abstracts.sqlite"
SRC_FLAT = SRC.with_suffix(SRC.suffix + ".flat")

# ─────────────────────────────────────────────────────────────────────────────
# PRE-REGISTRATION — written into the harness SOURCE and committed BEFORE any
# arm was run, so git history, not this file's own honesty, is the timestamp.
# Every bar is falsifiable and every one is copied verbatim into each results
# JSON. Doc 18 §4.3's lesson: a bar chosen after seeing the number is not a bar.
# ─────────────────────────────────────────────────────────────────────────────
PREREG = {
    "registered": "in-source, committed before the first run (see git log for "
                  "this file's add commit vs the results files' commit)",
    "subject": ("the PUBLISHED sidecar at "
                "data/thinclient_index/sections/social_sciences__recent/"
                "abstracts.sqlite.flat/ (built + gate-PASSED 2026-08-17, "
                "commit f55ce5f), read through the shipped AbstractStore"),
    "claims_under_test": {
        "doc18_s17_warm_p50": "flat_ordinal 1.18x mainline p50 (3.547 -> 3.012 ms), "
                              "spike, local disk, 50 random ids/fetch",
        "doc18_s17_all_percentiles": "flat faster at p50, mean AND p90; slower in "
                                     "no percentile (the operator no-regression gate)",
        "doc18_s16_cold_vs_warm": "the `docs` B-tree costs ~4 ms cold and ~0.24 ms "
                                  "hot; that is the whole 5.53x -> 1.18x collapse",
        "doc18_s22_bytes": "11,573,201,974 B flat vs 13,470,433,280 B sqlite = "
                           "-1,897,231,306 B (-1.90 GB)",
    },
    "bars": {
        "B1_parity": {
            "hard_gate": True,
            "statement": "every abstract fetched by the flat arm is BYTE-IDENTICAL "
                         "to the sqlite arm's, for every sampled doc, in every "
                         "trial, plus a windowed 20,000-id gate",
            "on_fail": "STOP. No latency number from this run is valid or "
                       "publishable; report the mismatch and do not touch the "
                       "serving default.",
        },
        "B2_warm_no_regression": {
            "statement": "flat warm per-batch p50 <= sqlite warm per-batch p50",
            "why": "the operator constraint recorded in doc 18 §16/§17 — faster is "
                   "a bonus, slower is a failure",
        },
        "B3_warm_p50_ge_1_18x": {
            "statement": "flat warm p50 multiple >= 1.18x (doc 18 §17's shipped-path "
                         "number) once the noise floor is subtracted",
            "predicted": "MET OR EXCEEDED. §17 measured on local disk; this is 9p, "
                         "where §16 measured the same payload move 2.4x higher "
                         "(2.89x vs 1.21x).",
            "interpretation_rule": "a warm multiple > 1.5x is a 9p artifact and must "
                                   "NOT be quoted as production-realisable; the "
                                   "transferable figure stays ~1.18x.",
        },
        "B4_warm_p95_no_regression": {
            "statement": "flat warm per-batch p95 <= sqlite warm per-batch p95",
            "predicted": "MET but thin. §16 measured p90 at only 1.19x because the "
                         "tail is block decompression, which both arms share.",
        },
        "B5_cold_multiple_gt_warm": {
            "statement": "flat cold p50 multiple > flat warm p50 multiple",
            "why": "this is the direct test of §16/§17's cold-B-tree explanation. "
                   "If cold <= warm, that explanation is wrong and §17's 'C8's "
                   "5.53x was a cold-cache artifact' needs rewriting.",
        },
        "B6_bytes": {
            "statement": "published flat total is 11,573,201,974 B and the sqlite it "
                         "replaces is 13,470,433,280 B (-1,897,231,306 B), "
                         "re-confirmed by stat of the published directory",
        },
        "B7_miss_asymmetry": {
            "directional_only": True,
            "statement": "on synthetic_miss50 the flat arm's advantage SHRINKS "
                         "relative to the hits-only regime, because a locator miss "
                         "pays searchsorted AND the `docs` fallback while a sqlite "
                         "miss pays only `docs`",
            "why": "not a pass/fail bar — this container has one live section so the "
                   "true production miss rate is unknown. It bounds the risk of "
                   "generalising the hits-only number to a federated deploy.",
        },
    },
    "n": "120 real bm25f queries; top_k 50 (production default) and 100; "
         "cold = 2 reps x 120 batches per arm with drop_caches before each; "
         "warm = 300 order-randomised interleaved trials per arm per regime",
    "if_slower": "record the number, leave the serving default exactly as it is "
                 "(the sidecar is already published and serving), and flag it.",
}

_ARMS = {"sqlite": False, "flat": True, "sqlite_ctrl": False}


# ── helpers ─────────────────────────────────────────────────────────────────

def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    if not s:
        return {"n": 0}
    def q(p): return s[min(len(s) - 1, int(p * len(s)))]
    return {"n": len(s),
            "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(q(0.90), 4),
            "p95_ms": round(q(0.95), 4),
            "p99_ms": round(q(0.99), 4)}


def _mem() -> dict:
    """VmRSS/VmHWM for this process and the host's page-cache size. Cheap
    (`/proc` reads), so it can bracket every phase."""
    out: dict = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            for k in ("VmRSS:", "VmHWM:"):
                if line.startswith(k):
                    out[k.strip(":").lower()] = int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            for k in ("Cached:", "MemAvailable:"):
                if line.startswith(k):
                    out[k.strip(":").lower()] = int(line.split()[1]) * 1024
    except OSError:
        pass
    return out


def _evict(paths: list[Path]) -> dict:
    """Drop the page cache for exactly these files, via
    `posix_fadvise(POSIX_FADV_DONTNEED)`.

    MEASURED 2026-08-17: `/proc/sys/vm/drop_caches` is **read-only** in this
    WSL2 container — `sudo` succeeds and the write still fails
    (`cannot create /proc/sys/vm/drop_caches: Read-only file system`), so the
    prior harnesses' `echo 3 > drop_caches` cannot run here at all. fadvise is
    the honest substitute and is in one respect *better*: it evicts only the
    store under test, so the two arms cannot evict each other, and the 9p mount's
    other residents (meta.sqlite, tantivy) are left alone rather than being
    dragged back in and confounding the next arm.

    The measured `Cached:` delta is recorded so the results file can be judged
    on whether eviction actually happened rather than on the call succeeding."""
    before = _mem().get("cached", 0)
    n = 0
    for p in paths:
        try:
            fd = os.open(str(p), os.O_RDONLY)
        except OSError:
            continue
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            n += 1
        except OSError:
            pass
        finally:
            os.close(fd)
    after = _mem().get("cached", 0)
    return {"method": "posix_fadvise(POSIX_FADV_DONTNEED)",
            "drop_caches_available": False,
            "drop_caches_note": "/proc/sys/vm/drop_caches is read-only in this "
                                "container (measured 2026-08-17)",
            "files": n, "cached_before": before, "cached_after": after,
            "cached_freed_bytes": before - after}


def _store_files(arm: str) -> list[Path]:
    """Every file the arm can read, so eviction is complete for that arm."""
    files = [SRC]
    if _ARMS[arm]:
        files += sorted(SRC_FLAT.iterdir())
    return files


def _arm_store(work: Path, arm: str):
    """Build the arm's symlink view and open the SHIPPED AbstractStore on it.

    Nothing under data/thinclient_index is created, renamed or written: the view
    is symlinks in `work`, and the store opens the published inodes through
    them. Asserts the wiring the arm's name claims."""
    from lib.thinclient.abstracts import AbstractStore

    want_flat = _ARMS[arm]
    d = work / arm
    d.mkdir(parents=True, exist_ok=True)
    link = d / "abstracts.sqlite"
    if not link.is_symlink():
        os.symlink(SRC, link)
    flat_link = d / "abstracts.sqlite.flat"
    if want_flat and not flat_link.is_symlink():
        os.symlink(SRC_FLAT, flat_link)
    if not want_flat and flat_link.exists():
        raise RuntimeError(f"{flat_link} exists — arm {arm} would serve flat")

    st = AbstractStore(link)
    if want_flat:
        if st._flat is None or st._locator is None:
            raise RuntimeError(f"arm {arm}: flat={st._flat is not None} "
                               f"locator={st._locator is not None} — not the "
                               f"published serving path")
    elif st._flat is not None or st._locator is not None:
        raise RuntimeError(f"arm {arm}: attached a flat sidecar it must not see")
    return st


def _digest(out: dict[str, str]) -> str:
    """Order-independent content hash of a fetch result, so two *processes* can
    be compared for byte-parity without shipping abstracts between them."""
    h = hashlib.sha256()
    for k in sorted(out):
        h.update(k.encode())
        h.update(b"\0")
        h.update(out[k].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _fstype(path: Path) -> str:
    from lib.thinclient.retriever import _fstype_for_path
    return _fstype_for_path(str(path))


def _published_bytes() -> dict:
    flat = {p.name: p.stat().st_size for p in sorted(SRC_FLAT.iterdir())}
    total = sum(flat.values())
    sq = SRC.stat().st_size
    return {"sqlite_bytes": sq, "flat_total_bytes": total,
            "saved_bytes": sq - total,
            "saved_gb": round((sq - total) / 1e9, 3),
            "flat_files": flat}


def _regimes(idsets: dict, top_k: int, miss_frac: float, seed: int) -> dict:
    """{regime -> [id list per query]}. `synthetic_miss50` swaps a fraction of
    each real list for well-formed W-ids past the store's maximum, so they are
    guaranteed absent yet still addressable by the ordinal locator (i.e. they
    exercise the found=False fallback, not the non-W-id skip path)."""
    real = [q["ids"][:top_k] for q in idsets["queries"] if q["ids"]]
    rng = random.Random(seed)
    mx = int(idsets["max_wid"])
    miss = []
    for ids in real:
        n_miss = int(round(len(ids) * miss_frac))
        keep = ids[:len(ids) - n_miss]
        fake = [f"W{mx + rng.randint(1, 5_000_000)}" for _ in range(n_miss)]
        miss.append(keep + fake)
    return {f"real_top{top_k}": real, f"synthetic_miss50_top{top_k}": miss}


# ── collect ─────────────────────────────────────────────────────────────────

def cmd_collect(args) -> None:
    """Freeze REAL ranked result sets from the shipped bm25f leg.

    `_bm25f_leg` returns exactly the `ranked` list `_hydrate` turns into the id
    list `fetch_abstracts` receives, so this is the serving path's own input —
    without paying `_hydrate`'s meta.sqlite lookups, which are irrelevant here
    and would add ~25 GB of 9p traffic to a collection step."""
    os.environ.setdefault("SFU_SKIP_BMP", "1")
    os.environ.setdefault("SFU_DENSE_LEG", "0")
    from lib.thinclient.retriever import ThinClientRetriever

    queries = [q["query"] for q in json.loads(
        (ROOT / "data" / "sfu_eval_queries.json").read_text())][:args.queries]

    r = ThinClientRetriever(remote_abstracts=False)
    r._load()
    log.info("sections loaded: %s", sorted(r._sections))

    db = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    max_wid = db.execute(
        "SELECT max(CAST(substr(id,2) AS INTEGER)) FROM docs "
        "WHERE id GLOB 'W[0-9]*'").fetchone()[0]

    rows, t0 = [], time.perf_counter()
    for i, q in enumerate(queries):
        t = time.perf_counter()
        ranked = r._bm25f_leg(q, args.top_k, None)
        ids = [d for d, _ in ranked]
        rows.append({"query": q, "ids": ids,
                     "leg_ms": round((time.perf_counter() - t) * 1000, 2)})
        if (i + 1) % 20 == 0:
            log.info("  %d/%d queries, %.0f s", i + 1, len(queries),
                     time.perf_counter() - t0)

    # How many of those ranked ids does this store actually hold? In this
    # container every other section is PACKED, so the answer should be ~100% —
    # and that is exactly why synthetic_miss50 exists.
    flat_ids = [i for row in rows for i in row["ids"]]
    present = 0
    for s in range(0, len(flat_ids), 500):
        chunk = flat_ids[s:s + 500]
        marks = ",".join("?" * len(chunk))
        present += db.execute(
            f"SELECT count(*) FROM docs WHERE id IN ({marks})", chunk).fetchone()[0]
    db.close()

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "harness": "j1 collect", "prereg": PREREG,
           "top_k": args.top_k, "queries": rows,
           "n_queries": len(rows), "n_ids": len(flat_ids),
           "ids_present_in_section": present,
           "hit_rate": round(present / max(1, len(flat_ids)), 4),
           "max_wid": max_wid,
           "sections_live": sorted(r._sections),
           "collect_seconds": round(time.perf_counter() - t0, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=1))
    log.info("collected %d queries / %d ids, hit_rate %.4f -> %s",
             len(rows), len(flat_ids), rep["hit_rate"], args.out)


# ── bench (one arm, fresh process — the COLD measurement) ───────────────────

def cmd_bench(args) -> None:
    idsets = json.loads(args.ids.read_text())
    regimes = _regimes(idsets, args.top_k, 0.5, args.seed)
    batches = regimes[f"real_top{args.top_k}"]

    # Evict BOTH arms' files, not just this arm's, so every cold run starts
    # from the same page-cache state for the section however the arms are
    # ordered — the ordering confound §14 exists to catch, removed by
    # construction rather than by randomisation.
    evict = _evict(_store_files("flat")) if args.evict else {"method": "none"}

    mem0 = _mem()
    t_open = time.perf_counter()
    st = _arm_store(args.work, args.arm)
    open_ms = (time.perf_counter() - t_open) * 1000
    mem_open = _mem()

    passes, digests = [], []
    for p in range(args.passes):
        samples, ndocs = [], []
        for i, ids in enumerate(batches):
            t = time.perf_counter()
            out = st.fetch(ids)
            samples.append((time.perf_counter() - t) * 1000)
            ndocs.append(len(out))
            if p == 0:
                digests.append(_digest(out))
        per_doc = [s / max(1, n) for s, n in zip(samples, ndocs)]
        passes.append({"pass": p, "phase": "cold" if p == 0 else "warm",
                       "per_batch": _stat(samples), "per_doc": _stat(per_doc),
                       "docs_returned": sum(ndocs),
                       "wall_s": round(sum(samples) / 1000, 2)})
        log.info("arm=%s pass=%d (%s) per-batch p50 %.3f ms p95 %.3f ms "
                 "| per-doc p50 %.4f ms | %d docs", args.arm, p,
                 passes[-1]["phase"], passes[-1]["per_batch"]["p50_ms"],
                 passes[-1]["per_batch"]["p95_ms"],
                 passes[-1]["per_doc"]["p50_ms"], sum(ndocs))

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "harness": "j1 bench",
           "prereg": PREREG, "arm": args.arm, "top_k": args.top_k,
           "caches_dropped_before": bool(args.evict),
           "eviction": evict,
           "store_open_ms": round(open_ms, 2),
           "flat_attached": st._flat is not None,
           "locator_attached": st._locator is not None,
           "src": str(SRC), "src_fstype": _fstype(SRC), "batches": len(batches),
           "passes": passes,
           "result_digests_pass0": digests,
           "mem": {"before_open": mem0, "after_open": mem_open, "after": _mem()}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=1))
    log.info("results -> %s", args.out)


# ── interleaved (all arms, one process — the WARM measurement + parity) ─────

def cmd_interleaved(args) -> None:
    idsets = json.loads(args.ids.read_text())
    rng = random.Random(args.seed)
    stores = {a: _arm_store(args.work, a) for a in _ARMS}
    log.info("arms wired: %s", {a: (s._flat is not None, s._locator is not None)
                                for a, s in stores.items()})

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "harness": "j1 interleaved (warm)", "prereg": PREREG,
           "src": str(SRC), "src_fstype": _fstype(SRC), "seed": args.seed,
           "sizes": _published_bytes(), "regimes": {}, "parity": {},
           "mem_start": _mem()}

    # ── B1, part 1: the windowed 20,000-id gate (doc 18 §22's sampler) ──────
    import build_flat_blocks as bfb
    gate_ids = bfb.sample_ids(SRC, args.parity_sample, seed=17)
    mism = {a: 0 for a in stores}
    got = {a: 0 for a in stores}
    for s in range(0, len(gate_ids), 500):
        chunk = gate_ids[s:s + 500]
        base = stores["sqlite"].fetch(chunk)
        got["sqlite"] += len(base)
        for a, st in stores.items():
            if a == "sqlite":
                continue
            o = st.fetch(chunk)
            got[a] += len(o)
            if o != base:
                mism[a] += 1
    rep["parity"]["windowed_gate"] = {
        "ids_requested": args.parity_sample, "ids_checked": len(gate_ids),
        "docs_returned": got, "mismatched_chunks": mism,
        "pass": all(v == 0 for v in mism.values())}
    log.info("windowed gate: %d ids, mismatches %s", len(gate_ids), mism)

    # ── the timed regimes ───────────────────────────────────────────────────
    for top_k in args.top_k:
        for name, batches in _regimes(idsets, top_k, 0.5, args.seed).items():
            trials = [batches[rng.randrange(len(batches))]
                      for _ in range(args.trials)]
            for st in stores.values():          # warm every arm equally
                for t in trials[:args.warmup]:
                    st.fetch(t)
            samples = {a: [] for a in stores}
            ndocs = {a: [] for a in stores}
            par_mism = {a: 0 for a in stores}
            for t in trials:
                order = list(stores)
                rng.shuffle(order)
                res = {}
                for a in order:
                    t0 = time.perf_counter()
                    res[a] = stores[a].fetch(t)
                    samples[a].append((time.perf_counter() - t0) * 1000)
                    ndocs[a].append(len(res[a]))
                # B1, part 2: byte-parity on EVERY timed trial, not a sample.
                for a in order:
                    if a != "sqlite" and res[a] != res["sqlite"]:
                        par_mism[a] += 1
            base = statistics.median(samples["sqlite"])
            reg = {"trials": args.trials, "ids_per_fetch": len(trials[0]),
                   "docs_returned_median": {
                       a: statistics.median(ndocs[a]) for a in stores},
                   "parity_mismatched_trials": par_mism,
                   "parity_pass": all(v == 0 for v in par_mism.values()),
                   "arms": {}}
            for a in stores:
                sst = _stat(samples[a])
                sst["per_doc"] = _stat([s / max(1, n) for s, n
                                        in zip(samples[a], ndocs[a])])
                m = statistics.median(samples[a])
                sst["vs_sqlite_p50"] = round(base / m, 3) if m else None
                sst["regression_vs_sqlite"] = bool(m > base)
                reg["arms"][a] = sst
            ctrl = statistics.median(samples["sqlite_ctrl"])
            reg["noise_floor_pct"] = round(abs(ctrl - base) / base * 100, 2)
            rep["regimes"][name] = reg
            log.info("%-26s flat %.3fx sqlite p50 (%.3f -> %.3f ms), p95 "
                     "%.3f -> %.3f, noise %.2f%%, parity %s", name,
                     reg["arms"]["flat"]["vs_sqlite_p50"],
                     reg["arms"]["sqlite"]["p50_ms"], reg["arms"]["flat"]["p50_ms"],
                     reg["arms"]["sqlite"]["p95_ms"], reg["arms"]["flat"]["p95_ms"],
                     reg["noise_floor_pct"],
                     "PASS" if reg["parity_pass"] else "FAIL")

    rep["parity"]["overall_pass"] = (
        rep["parity"]["windowed_gate"]["pass"]
        and all(r["parity_pass"] for r in rep["regimes"].values()))
    rep["mem_end"] = _mem()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=1))
    log.info("PARITY OVERALL %s -> %s",
             "PASS" if rep["parity"]["overall_pass"] else "FAIL", args.out)


# ── verdict ─────────────────────────────────────────────────────────────────

def cmd_stage(args) -> None:
    """Byte-copy the published section to LOCAL DISK and re-point the arms at it.

    Doc 18 §14/§16: the index mount is 9p, where SQLite's B-tree pays several
    ~0.5 ms faults that the flat store's single `pread` does not — §16 measured
    the identical payload move at 2.89x on 9p and 1.21x on local disk. A 9p-only
    result therefore cannot answer "what does the droplet get?". This copies the
    *published bytes* (not a rebuild — no builder runs, the `flat_store_id`
    pairing is carried along untouched) to an overlay directory so the same
    arms can be run again with the filesystem variable removed.

    Additive and read-only w.r.t. data/thinclient_index: `shutil.copy2` reads."""
    args.dest.mkdir(parents=True, exist_ok=True)
    dst_sq = args.dest / SRC.name
    dst_flat = args.dest / SRC_FLAT.name
    t0 = time.perf_counter()
    todo = [(SRC, dst_sq)] + [(p, dst_flat / p.name) for p in sorted(SRC_FLAT.iterdir())]
    dst_flat.mkdir(exist_ok=True)
    copied = 0
    for s, d in todo:
        if d.exists() and d.stat().st_size == s.stat().st_size:
            continue
        log.info("  copy %s (%.2f GB)", s.name, s.stat().st_size / 1e9)
        shutil.copy2(s, d)
        copied += 1
    log.info("staged %d/%d files to %s (%s) in %.0f s", copied, len(todo),
             args.dest, _fstype(args.dest), time.perf_counter() - t0)
    # The identity gate must still hold on the copy — if it does not, the stage
    # is corrupt and every number from it is void.
    from lib.thinclient.abstracts import AbstractStore
    st = AbstractStore(dst_sq)
    if st._flat is None or st._locator is None:
        raise SystemExit("staged copy does not serve flat+ordinal — stage is bad")
    log.info("staged copy opens flat+ordinal OK (%d locator rows)", st._locator.rows)


def cmd_verdict(args) -> None:
    warm = json.loads(args.interleaved.read_text())
    colds = {p.stem: json.loads(p.read_text()) for p in args.cold}

    v: dict = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "harness": "j1 verdict", "prereg": PREREG,
               "inputs": {"interleaved": str(args.interleaved),
                          "cold": [str(p) for p in args.cold]},
               "src_fstype": warm["src_fstype"], "sizes": warm["sizes"],
               "bars": {}}

    # B1 — the hard gate, including cross-process digest equality.
    dig = {}
    for name, rep in colds.items():
        dig.setdefault(rep["arm"], []).append(rep["result_digests_pass0"])
    cross = None
    if "sqlite" in dig and "flat" in dig:
        cross = all(a == b for a in dig["sqlite"] for b in dig["flat"])
    v["bars"]["B1_parity"] = {
        "windowed_gate": warm["parity"]["windowed_gate"],
        "per_trial": {k: r["parity_mismatched_trials"]
                      for k, r in warm["regimes"].items()},
        "cross_process_digests_equal": cross,
        "verdict": "PASS" if (warm["parity"]["overall_pass"]
                              and cross is not False) else "FAIL"}

    key = [k for k in warm["regimes"] if k.startswith("real_")]
    primary = f"real_top{args.primary_top_k}"
    reg = warm["regimes"].get(primary) or warm["regimes"][key[0]]
    fl, sq = reg["arms"]["flat"], reg["arms"]["sqlite"]
    v["bars"]["B2_warm_no_regression"] = {
        "sqlite_p50_ms": sq["p50_ms"], "flat_p50_ms": fl["p50_ms"],
        "verdict": "PASS" if fl["p50_ms"] <= sq["p50_ms"] else "FAIL"}
    v["bars"]["B3_warm_p50_ge_1_18x"] = {
        "multiple": fl["vs_sqlite_p50"], "noise_floor_pct": reg["noise_floor_pct"],
        "verdict": "PASS" if (fl["vs_sqlite_p50"] or 0) >= 1.18 else "FAIL",
        "nine_p_flag": bool((fl["vs_sqlite_p50"] or 0) > 1.5)}
    v["bars"]["B4_warm_p95_no_regression"] = {
        "sqlite_p95_ms": sq["p95_ms"], "flat_p95_ms": fl["p95_ms"],
        "multiple": round(sq["p95_ms"] / fl["p95_ms"], 3) if fl["p95_ms"] else None,
        "verdict": "PASS" if fl["p95_ms"] <= sq["p95_ms"] else "FAIL"}

    cold_p50 = {}
    for rep in colds.values():
        p0 = [p for p in rep["passes"] if p["pass"] == 0][0]
        cold_p50.setdefault(rep["arm"], []).append(p0["per_batch"]["p50_ms"])
    cold_mult = None
    if cold_p50.get("sqlite") and cold_p50.get("flat"):
        cold_mult = round(statistics.fmean(cold_p50["sqlite"])
                          / statistics.fmean(cold_p50["flat"]), 3)
    v["bars"]["B5_cold_multiple_gt_warm"] = {
        "cold_p50_ms": {k: [round(x, 3) for x in vv] for k, vv in cold_p50.items()},
        "cold_multiple": cold_mult, "warm_multiple": fl["vs_sqlite_p50"],
        "verdict": ("PASS" if (cold_mult or 0) > (fl["vs_sqlite_p50"] or 0)
                    else "FAIL") if cold_mult else "NOT MEASURED"}

    s = warm["sizes"]
    v["bars"]["B6_bytes"] = {
        "sqlite_bytes": s["sqlite_bytes"], "flat_total_bytes": s["flat_total_bytes"],
        "saved_bytes": s["saved_bytes"], "saved_gb": s["saved_gb"],
        "doc18_s22_claim_bytes": -1_897_231_306,
        "verdict": "PASS" if s["saved_bytes"] == 1_897_231_306 else "DIFFERS"}

    miss = [k for k in warm["regimes"] if k.startswith("synthetic_miss50")]
    if miss:
        mreg = warm["regimes"][miss[0]]
        v["bars"]["B7_miss_asymmetry"] = {
            "hits_only_multiple": fl["vs_sqlite_p50"],
            "miss50_multiple": mreg["arms"]["flat"]["vs_sqlite_p50"],
            "shrinks_as_predicted": bool(
                (mreg["arms"]["flat"]["vs_sqlite_p50"] or 0) < (fl["vs_sqlite_p50"] or 0)),
            "flat_regresses_on_miss50": mreg["arms"]["flat"]["regression_vs_sqlite"]}

    v["headline"] = {
        "primary_regime": primary,
        "warm_p50_ms": {"sqlite": sq["p50_ms"], "flat": fl["p50_ms"]},
        "warm_p95_ms": {"sqlite": sq["p95_ms"], "flat": fl["p95_ms"]},
        "warm_per_doc_p50_ms": {"sqlite": sq["per_doc"]["p50_ms"],
                                "flat": fl["per_doc"]["p50_ms"]},
        "warm_multiple_p50": fl["vs_sqlite_p50"],
        "cold_multiple_p50": cold_mult,
        "parity": v["bars"]["B1_parity"]["verdict"],
        "fs_caveat": ("index mount is %s; doc 18 §16 measured this payload move "
                      "2.89x on 9p vs 1.21x on local disk, so any fault-bound "
                      "multiple here is an upper bound for a local-disk droplet"
                      % warm["src_fstype"])}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(v, indent=1))
    for k, b in v["bars"].items():
        log.info("%-28s %s", k, b.get("verdict", b))
    log.info("verdict -> %s", args.out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = ROOT / "data" / "eval_results"

    c = sub.add_parser("collect")
    c.add_argument("--queries", type=int, default=120)
    c.add_argument("--top-k", type=int, default=100)
    c.add_argument("--out", type=Path, default=ev / "j1_flat_idsets_20260817.json")
    c.set_defaults(fn=cmd_collect)

    b = sub.add_parser("bench")
    b.add_argument("--arm", required=True, choices=sorted(_ARMS))
    b.add_argument("--ids", type=Path, default=ev / "j1_flat_idsets_20260817.json")
    b.add_argument("--work", type=Path, default=Path("/var/tmp/j1_flat_ab"))
    b.add_argument("--top-k", type=int, default=50)
    b.add_argument("--passes", type=int, default=3)
    b.add_argument("--seed", type=int, default=17)
    b.add_argument("--evict", action="store_true",
                   help="posix_fadvise(DONTNEED) the whole section's files "
                        "before opening the store — this container's "
                        "/proc/sys/vm/drop_caches is read-only")
    b.add_argument("--out", type=Path, required=True)
    b.set_defaults(fn=cmd_bench)

    i = sub.add_parser("interleaved")
    i.add_argument("--ids", type=Path, default=ev / "j1_flat_idsets_20260817.json")
    i.add_argument("--work", type=Path, default=Path("/var/tmp/j1_flat_ab"))
    i.add_argument("--top-k", type=int, nargs="+", default=[50, 100])
    i.add_argument("--trials", type=int, default=300)
    i.add_argument("--warmup", type=int, default=20)
    i.add_argument("--parity-sample", type=int, default=20_000)
    i.add_argument("--seed", type=int, default=17)
    i.add_argument("--out", type=Path,
                   default=ev / "j1_flat_serving_warm_20260817.json")
    i.set_defaults(fn=cmd_interleaved)

    s = sub.add_parser("stage")
    s.add_argument("--dest", type=Path, default=Path("/var/tmp/j1_abs_stage"))
    s.set_defaults(fn=cmd_stage)

    v = sub.add_parser("verdict")
    v.add_argument("--interleaved", type=Path,
                   default=ev / "j1_flat_serving_warm_20260817.json")
    v.add_argument("--cold", type=Path, nargs="+", required=True)
    v.add_argument("--primary-top-k", type=int, default=50)
    v.add_argument("--out", type=Path,
                   default=ev / "j1_flat_serving_verdict_20260817.json")
    v.set_defaults(fn=cmd_verdict)

    for p in (b, i):
        p.add_argument("--src", type=Path, default=None,
                       help="serve the arms from this abstracts.sqlite instead "
                            "of the published one — used only to re-run the "
                            "SAME published bytes from LOCAL DISK (see `stage`), "
                            "so the 9p variable can be removed (doc 18 §14)")

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    if getattr(args, "src", None):
        global SRC, SRC_FLAT
        SRC = args.src.resolve()
        SRC_FLAT = SRC.with_suffix(SRC.suffix + ".flat")
        log.info("SRC overridden -> %s (%s)", SRC, _fstype(SRC))
    if not SRC.exists() or not SRC_FLAT.is_dir():
        raise SystemExit(f"{SRC} / {SRC_FLAT}: the published section is not here")
    args.fn(args)


if __name__ == "__main__":
    main()
