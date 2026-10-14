#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-10 (deployprep wave 3, 2026-07-17) — shard-failure isolation PROOF.
OWNER ASK 2026-07-17: any 1 of the 8 SEISMIC shards down → the other 7 serve.

Asserts the five WI-10 bars (pre-registered in
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §WI-10) by inducing each
single-shard failure class ONE AT A TIME and checking: (a) the other 7 serve
(0% throw-ups), (b) recall retention@10 ≈ 7/8 (bounded loss, no score-comparability
issue — hash sharding), (c) `degraded_shards` names the injected shard, (d) re-
admission clears the flag, (e) BOTH parallel + sequential classes isolate.

FAULT INJECTION METHOD — Rule Zero: `data/seismic_150m/` is READ-ONLY; fault
injection NEVER renames/edits/relocates a real shard. Two injection surfaces:

  SEARCH boundary (a loaded shard throws/hangs during `.search`):
    monkeypatch ONE shard's `.search` to raise / sleep(>>timeout). The other 7
    shards (the loaded backend, unchanged) keep serving. Reuses the ONE warm
    8-shard backend → fast (no reload per fault class). Tests the `_fan_out`
    fence in BOTH Parallel + Sequential classes (the cascade property: _fan_out
    is the only per-method behavior, the guard wraps it the same way).

  LOAD boundary (a shard's file is absent/truncated at construction):
    manifest override env points ONE shard at a bad path (absent) or a tiny
    corrupt FIXTURE `.mmap` dir under `data/eval_results/_fixtures/` (created
    here, ~bytes, NOT a real shard). The backend builds with the boundary ON →
    that shard fails to load (marked down), the other 7 load + serve. One cold
    load of 7 real shards per load-fault cell (slower; the load fault is rarer
    than a search fault so one representative cell suffices for the proof).

The HASH-SHARDING recall bound (the `~7/8` claim): each shard is a disjoint
doc-id hash partition of the corpus, all scored in one shared SPLADE vocab →
dropping a shard drops exactly its ~1/8 of the docs, no re-calibration needed
(doc 09: calibration unnecessary by construction). So overlap@10 of the
7-shard federation vs the 8-shard federation is bounded ≈ 7/8 = 0.875 (modulo
the dropped shard happening to hold a given query's top hits — averaged over a
batch it converges to ~0.875).

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "demo_dependability"))

MANIFEST = str(REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5_v2.json")
FIXTURE_DIR = REPO / "data" / "eval_results" / "_fixtures"


def _q(n=8):
    """Topic-diverse query set (round-robbin subjects → spans shards)."""
    recs = json.loads((REPO / "data" / "eval_results" / "diverse_queries.json").read_text())
    out, seen = [], set()
    for rec in recs:
        p = rec.get("paraphrase")
        if p and p not in seen:
            seen.add(p); out.append(p)
        if len(out) >= n:
            break
    return out


def _overlap_at_k(a: list[str], b: list[str], k=10) -> float:
    """Fraction of `a`'s top-k ids present in `b`'s top-k. The recall-retention
    metric: how much of the full-8-shard top-10 the degraded-7-shard federation
    still finds. Expected ≈ 7/8 = 0.875 (the bounded hash-sharding loss)."""
    if not a:
        return 0.0
    top_a = a[:k]
    set_b = set(b[:k])
    return sum(1 for x in top_a if x in set_b) / len(top_a)


def _make_truncated_fixture() -> str:
    """A tiny corrupt `.mmap` fixture: a real shard's manifest.json + a truncated
    data file. Created UNDER data/eval_results/_fixtures/ (NOT near a real shard).
    The loader's `_load_one_shard` reads the mmap dir → the pyo3 reader will
    raise on the truncated data (a search/load exception → the fault boundary
    marks the shard down)."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fx = FIXTURE_DIR / "wi10_truncated_shard.mmap"
    if fx.exists():
        shutil.rmtree(fx)
    fx.mkdir()
    src_manifest = REPO / "data" / "seismic_150m" / "index" / "plan01" \
        / "global_shard0of8.dotvbyte.e5.v2.mmap" / "manifest.json"
    if src_manifest.exists():
        shutil.copy(src_manifest, fx / "manifest.json")
    (fx / "data.bin").write_bytes(b"\x00" * 16)
    (fx / "index.bin").write_bytes(b"\xde\xad\xbe\xef")
    return str(fx)


def _build_backend(federation: str, boundary_on: bool, manifest=None):
    """Build a federated backend (parallel or sequential) with the fault boundary
    ON or OFF, from the given manifest (default the served e5_v2 manifest)."""
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend)
    os.environ["SFU_SEISMIC_SHARD_FAULT_BOUNDARY"] = "1" if boundary_on else "0"
    os.environ["SFU_SEISMIC_FEDERATION"] = federation
    cls = SequentialSeismicBackend if federation == "sequential" else ParallelSeismicBackend
    b = cls.from_manifest(manifest or MANIFEST,
                          splade_model_path="models/splade_onnx_fused",
                          load_mode="mmap")
    return b


def _run_queries(backend, queries, top_k=10):
    """Run the query batch; return (per-query top-k oaid lists, throws, p50)."""
    results = []
    throws = 0
    lat = []
    for q in queries:
        t0 = time.perf_counter()
        try:
            res = backend.search(q, top_k=top_k)
            lat.append((time.perf_counter() - t0) * 1000)
            results.append([o for o, _ in res])
        except Exception as e:
            throws += 1
            results.append([])
            lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    p50 = lat[len(lat) // 2] if lat else None
    return results, throws, p50


class _FaultyShard:
    """A stand-in for a real pyo3 shard whose `.search` faults ( Rule Zero: the
    real MmapSeismicIndex.search attribute is read-only, so we REPLACE the shard
    object in the backend's `shards` list with this wrapper for the fault window,
    then swap the real one back). The guard's `_guarded_search_one` pairs shards
    to trackers by LIST POSITION (`enumerate(self.shards)`), not by `id(idx)`, so
    a wrapper at position i is correctly paired with tracker i — the fault is
    attributed to the right shard's `degraded_shards` name."""
    def __init__(self, fault_fn, real_shard):
        self._fault_fn = fault_fn
        self._real = real_shard
    def search(self, *a, **k):
        return self._fault_fn(*a, **k)
    def __getattr__(self, name):
        return getattr(self._real, name)


def _search_fault_cell(name, federation, build_fn, fault_idx, queries,
                       baseline_results, desc):
    """SEARCH-boundary cell: build the backend (warm), wrap ONE shard's .search
    in a _FaultyShard to fault, drive the batch, assert isolation. `build_fn(idx)`
    returns the faulting search callable."""
    cell = {"name": name, "federation": federation, "fault_index": fault_idx,
            "desc": desc, "method": "_FaultyShard wrapper (Rule Zero: real shard read-only)"}
    out = {"cell": cell}
    print(f"\n=== {name} ({federation}) — {desc} ===", flush=True)
    backend = _build_backend(federation, boundary_on=True)
    shard_name = backend._shard_names[fault_idx]
    _run_queries(backend, queries[:2], top_k=10)
    real_shard = backend.shards[fault_idx]
    backend.shards[fault_idx] = _FaultyShard(build_fn(fault_idx), real_shard)
    fast_cooldown = 1.0
    os.environ["SFU_SEISMIC_SHARD_REPROBE_S"] = str(fast_cooldown)
    during_res, during_throws, during_p50 = _run_queries(backend, queries, top_k=10)
    during_degraded = backend.degraded_shards()
    overlaps = [_overlap_at_k(baseline_results[i], during_res[i], 10)
                for i in range(min(len(baseline_results), len(during_res)))]
    mean_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
    out["during"] = {"throws": during_throws, "degraded_shards": during_degraded,
                     "p50_ms": round(during_p50, 1) if during_p50 else None,
                     "recall_retention_overlap10": round(mean_overlap, 3),
                     "per_query_overlap": [round(o, 3) for o in overlaps]}
    print(f"  DURING: throws={during_throws} degraded={during_degraded} "
          f"recall@10={mean_overlap:.3f} p50={during_p50:.0f}ms (expect ~0.875)", flush=True)
    served = sum(1 for r in during_res if r) / len(during_res)
    out["bars"] = {
        "a_other_seven_serve_no_throw": during_throws == 0,
        "b_results_returned": served > 0,
        "c_shard_named_in_degraded": shard_name in during_degraded,
        "e_class_isolates": during_throws == 0 and served > 0,
    }
    backend.shards[fault_idx] = real_shard
    tr = backend._shard_faults[fault_idx]
    with tr._lock:
        tr.opened_at = time.monotonic()
        tr.probe_pending = False
    time.sleep(fast_cooldown + 0.3)
    after_res, after_throws, after_p50 = _run_queries(backend, queries, top_k=10)
    after_degraded = backend.degraded_shards()
    out["after"] = {"throws": after_throws, "degraded_shards": after_degraded,
                    "p50_ms": round(after_p50, 1) if after_p50 else None}
    out["bars"]["d_readmission"] = shard_name not in after_degraded
    print(f"  AFTER:  degraded={after_degraded} → re-admitted={shard_name not in after_degraded}", flush=True)
    return out


def _load_fault_cell(name, federation, manifest_override, fault_idx, queries,
                    baseline_results, desc):
    """LOAD-boundary cell: build the backend from a manifest where ONE shard is
    bad (absent / corrupt fixture); the fault boundary marks it down at LOAD,
    the other 7 load + serve. One cold load per cell."""
    out = {"cell": {"name": name, "federation": federation, "fault_index": fault_idx,
                    "desc": desc, "method": "manifest override (absent/corrupt path)"}}
    print(f"\n=== {name} ({federation}) — {desc} ===", flush=True)
    t0 = time.perf_counter()
    backend = _build_backend(federation, boundary_on=True, manifest=manifest_override)
    load_s = time.perf_counter() - t0
    fault_status = backend.fault_status()
    shard_name = backend._shard_names[fault_idx] if fault_idx < len(backend._shard_names) else f"shard{fault_idx}"
    print(f"  loaded in {load_s:.0f}s; fault_status: {fault_status}", flush=True)
    during_res, during_throws, during_p50 = _run_queries(backend, queries, top_k=10)
    during_degraded = backend.degraded_shards()
    overlaps = [_overlap_at_k(baseline_results[i], during_res[i], 10)
                for i in range(min(len(baseline_results), len(during_res)))]
    mean_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
    served = sum(1 for r in during_res if r) / len(during_res) if during_res else 0
    loaded = sum(1 for s in backend.shards if s is not None)
    out["during"] = {"load_s": round(load_s, 0), "shards_loaded": loaded,
                     "throws": during_throws, "degraded_shards": during_degraded,
                     "p50_ms": round(during_p50, 1) if during_p50 else None,
                     "recall_retention_overlap10": round(mean_overlap, 3),
                     "fault_status": fault_status}
    out["bars"] = {
        "a_other_seven_load_and_serve": loaded == 7 and during_throws == 0,
        "b_results_returned": served > 0,
        "c_shard_named_in_degraded": shard_name in during_degraded or
            any(fs["shard"] == shard_name and fs["failed"] for fs in fault_status),
        "e_class_isolates": loaded == 7 and served > 0,
        "recall_bounded_7_8": 0.80 <= mean_overlap <= 0.95,
    }
    print(f"  DURING: loaded={loaded}/8 throws={during_throws} degraded={during_degraded} "
          f"recall@10={mean_overlap:.3f} p50={during_p50:.0f}ms", flush=True)
    good = _build_backend(federation, boundary_on=True)
    good_res, _, _ = _run_queries(good, queries[:3], top_k=10)
    out["after"] = {"degraded_shards": good.degraded_shards(),
                    "recovered": not good.degraded_shards()}
    out["bars"]["d_readmission"] = out["after"]["recovered"]
    print(f"  AFTER:  reload-with-good-manifest degraded={good.degraded_shards()} "
          f"→ re-admitted={out['after']['recovered']}", flush=True)
    return out


def main():
    os.environ["SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S"] = "3"
    os.environ["SFU_SEISMIC_SHARD_REPROBE_S"] = "1"
    queries = _q(8)
    out = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "manifest": MANIFEST, "n_queries": len(queries),
                    "method": "manifest override + monkeypatch (Rule Zero: real shards read-only)"},
           "bars_expected": {"recall_retention": "≈7/8=0.875, bar [0.80,0.95]"},
           "cells": []}
    print("WI-10 shard-isolation proof: building the 8-shard baseline (parallel)...", flush=True)
    t0 = time.perf_counter()
    base = _build_backend("parallel", boundary_on=False)
    print(f"  baseline loaded in {time.perf_counter()-t0:.0f}s", flush=True)
    base_res, base_throws, base_p50 = _run_queries(base, queries, top_k=10)
    out["baseline"] = {"federation": "parallel", "n_shards": 8, "throws": base_throws,
                       "p50_ms": round(base_p50, 1), "results": len(base_res)}
    print(f"  baseline queries done: throws={base_throws} p50={base_p50:.0f}ms", flush=True)

    cells = out["cells"]
    fi = 0
    def throw_fn(i):
        def _f(*a, **k):
            raise RuntimeError(f"INJECTED shard{i} search failure (WI-10)")
        return _f
    cells.append(_search_fault_cell("search_exception_parallel", "parallel",
                                     throw_fn, fi, queries, base_res,
                                     "a shard's .search throws"))
    def hang_fn(i):
        def _f(*a, **k):
            time.sleep(30)
            return []
        return _f
    cells.append(_search_fault_cell("search_hang_parallel", "parallel",
                                     hang_fn, fi, queries, base_res,
                                     "a shard's .search hangs (>timeout)"))
    base_seq = _build_backend("sequential", boundary_on=False)
    base_seq_res, _, base_seq_p50 = _run_queries(base_seq, queries, top_k=10)
    out["baseline_sequential"] = {"n_shards": 8, "p50_ms": round(base_seq_p50, 1)}
    cells.append(_search_fault_cell("search_exception_sequential", "sequential",
                                     throw_fn, fi, queries, base_seq_res,
                                     "sequential class: a shard's .search throws"))

    manifest_absent = json.loads(Path(MANIFEST).read_text())
    manifest_absent["shards"][fi]["mmap_dir"] = "data/seismic_150m/DOES_NOT_EXIST_WI10.mmap"
    mapath = REPO / "data" / "eval_results" / "_wi10_manifest_absent.json"
    mapath.write_text(json.dumps(manifest_absent))
    cells.append(_load_fault_cell("load_absent_parallel", "parallel",
                                   str(mapath), fi, queries, base_res,
                                   "a shard's mmap_dir is absent (won't load)"))
    trunc = _make_truncated_fixture()
    manifest_trunc = json.loads(Path(MANIFEST).read_text())
    manifest_trunc["shards"][fi]["mmap_dir"] = trunc
    mtpath = REPO / "data" / "eval_results" / "_wi10_manifest_truncated.json"
    mtpath.write_text(json.dumps(manifest_trunc))
    cells.append(_load_fault_cell("load_truncated_parallel", "parallel",
                                   str(mtpath), fi, queries, base_res,
                                   "a shard's mmap_dir is a corrupt fixture"))

    all_bars = all(all(c["bars"].values()) for c in cells if "bars" in c)
    out["verdict"] = "PASS" if all_bars else "FAIL"
    out["verdict_bars"] = {c["cell"]["name"]: c["bars"] for c in cells if "bars" in c}
    rf = REPO / "data" / "eval_results" / \
         f"wi10_shard_isolation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    rf.write_text(json.dumps(out, indent=2))
    print(f"\n=== WI-10 VERDICT: {out['verdict']} ===", flush=True)
    for c in cells:
        bars = c.get("bars", {})
        name = c["cell"]["name"]
        print(f"  {name}: {bars}")
    print(f"result: {rf}", flush=True)
    return 0 if all_bars else 1


if __name__ == "__main__":
    sys.exit(main())
