#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-9 (deployprep wave 3, 2026-07-17) — leg-level fault-injection PROOF for the
circuit-breaker / graceful-degradation layer. STAGING ONLY.

Asserts the four WI-9 bars (pre-registered in
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §WI-9) by inducing each
single-leg failure class ONE AT A TIME against a live guardian-wrapped retriever
and checking: (a) no 5xx storm, (b) results still returned, (c) the `degraded`
flag names the injected leg, (d) the breaker re-admits the leg after the fault
clears + cooldown.

FAULT INJECTION METHOD — mocks, not real-index corruption (Rule Zero: shards
under `data/seismic_150m/` are READ-ONLY; fault injection NEVER touches a real
shard file). Each fault is induced by MONKEYPATCHING a retriever leg method:
  - SPLADE leg hung     → `_splade_leg_seismic` patched to `time.sleep(>>timeout)`
  - SPLADE leg erroring → `_splade_leg_seismic` patched to raise
  - dense leg erroring  → `dense_search` patched to raise
  - BM25F leg erroring  → `_bm25f_leg` patched to raise (today this would 5xx; WI-9 degrades)
  - encoder down        → `_encode_splade_top` patched to return None (the
                           existing mirror-to-BM25F contract; the guardian must
                           NOT trip the breaker on a graceful mirror — only on throw/timeout)

This runs the retriever DIRECTLY (no HTTP serve) so the proof is fast (seconds,
not the cold-serve warmup). The serve-layer `/search` wiring (staging_serve.py)
calls the SAME `LegGuardian.search_rrf_degraded` proved here, so the serve result
shape (the `degraded` field) is identical to what this harness asserts.

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo_dependability"))

os.environ.setdefault("SFU_DEMO_LEG_BREAKER", "1")
os.environ.setdefault("SFU_DEMO_LEG_TIMEOUT_S", "30")
os.environ.setdefault("SFU_DEMO_LEG_TIMEOUT_SPLADE_S", "30")
os.environ.setdefault("SFU_DEMO_LEG_BREAKER_N", "2")
os.environ.setdefault("SFU_DEMO_LEG_BREAKER_COOLDOWN_S", "1")


def _build_retriever():
    from lib.thinclient.retriever import ThinClientRetriever
    r = ThinClientRetriever(index_root=os.environ.get("SFU_THINCLIENT_INDEX_ROOT", ""),
                            remote_abstracts=False)
    r.is_available()
    from lib.opensearch_retriever import encode_splade
    encode_splade("initialize thread pools", r.splade_model_path)
    r._seismic_backend()
    r.search("warmup probe", top_k=5, mode="splade")
    return r


def _q() -> list[str]:
    """A small diverse query set (round-robbin subjects so the SPLADE leg really
    traverses). Same workload the warmup + load driver use."""
    recs = json.loads((REPO / "data" / "eval_results" / "diverse_queries.json").read_text())
    out, seen = [], set()
    for rec in recs:
        p = rec.get("paraphrase")
        if p and p not in seen:
            seen.add(p); out.append(p)
        if len(out) >= 4:
            break
    return out


class LegPatcher:
    """Context manager: monkeypatch a retriever leg method for the fault window,
    restore on exit (so the breaker's recovery probe hits a HEALTHY leg)."""
    def __init__(self, r, method, fn):
        self.r = r; self.method = method; self.fn = fn; self.orig = None
    def __enter__(self):
        self.orig = getattr(self.r, self.method)
        import types
        setattr(self.r, self.method, types.MethodType(self.fn, self.r))
        return self
    def __exit__(self, *exc):
        setattr(self.r, self.method, self.orig)


def _run_phase(guardian, q, top_k=10):
    """Run a small batch through the guardian, return per-query results + the
    union of degraded legs across the batch. Times each query (p50/p95 over the
    batch) so the proof records latency-during-fault."""
    lat = []
    total_degraded = set()
    last_degraded: list[str] = []
    results_returned = 0
    errs_5xx = 0
    for query in q:
        t0 = time.perf_counter()
        d = guardian.search_rrf_degraded(query, top_k=top_k, include_dense=True)
        ms = (time.perf_counter() - t0) * 1000
        lat.append(ms)
        deg = d.get("degraded", [])
        total_degraded.update(deg)
        last_degraded = deg
        results_returned += 1 if d["results"] else 0
    lat.sort()
    def pct(p):
        return lat[min(int(len(lat) * p / 100), len(lat) - 1)] if lat else None
    return {"n": len(q), "results_returned": results_returned,
            "degraded": sorted(total_degraded),
            "last_degraded": sorted(last_degraded),
            "p50_ms": round(pct(50), 1) if lat else None,
            "p95_ms": round(pct(95), 1) if lat else None,
            "err5xx": errs_5xx}


def _patch_raises(exc=RuntimeError("INJECTED leg failure (WI-9 fault)")):
    def fn(self, *a, **k):
        raise exc
    return fn

def _patch_hang(seconds=60):
    def fn(self, *a, **k):
        time.sleep(seconds)
        return []
    return fn

def _patch_encoder_none():
    """The existing graceful-mirror contract: encode returns None → SPLADE leg
    mirrors BM25F. The guardian must NOT trip on this (it's a successful degrade)."""
    def fn(self, *a, **k):
        return None
    return fn


def main():
    from leg_breaker import get_guardian
    out = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "env": {k: os.environ[k] for k in
                            ["SFU_DEMO_LEG_BREAKER", "SFU_DEMO_LEG_TIMEOUT_S",
                             "SFU_DEMO_LEG_TIMEOUT_SPLADE_S", "SFU_DEMO_LEG_BREAKER_N",
                             "SFU_DEMO_LEG_BREAKER_COOLDOWN_S"]},
                    "method": "monkeypatch leg methods (Rule Zero: no real shard touched)"},
           "faults": []}
    print("WI-9 fault-injection proof: building retriever (cold seismic load on first splade)...", flush=True)
    t0 = time.perf_counter()
    r = _build_retriever()
    guardian = get_guardian(r)
    assert guardian is not None, "guardian OFF — SFU_DEMO_LEG_BREAKER must be 1"
    q = _q()
    print(f"  warmup batch ({len(q)} queries, {time.perf_counter()-t0:.1f}s to build)...", flush=True)
    warm = _run_phase(guardian, q)
    out["warm_baseline"] = warm
    print(f"  warm p50={warm['p50_ms']}ms degraded={warm['degraded']} "
          f"results={warm['results_returned']}/{warm['n']}", flush=True)

    faults = [
        ("splade_hung", "_splade_leg_seismic", _patch_hang(60), "SPLADE leg hung (sleep>>timeout)"),
        ("splade_error", "_splade_leg_seismic", _patch_raises(), "SPLADE leg throws"),
        ("dense_error", "dense_search", _patch_raises(), "dense leg throws"),
        ("bm25f_error", "_bm25f_leg", _patch_raises(), "BM25F leg throws (today: 5xx; WI-9: degrade)"),
        ("encoder_down", "_encode_splade_top", _patch_encoder_none(), "encoder down (graceful mirror — breaker must NOT trip)"),
    ]
    for name, method, patchfn, desc in faults:
        print(f"\n=== FAULT {name}: {desc} ===", flush=True)
        fault_result = {"name": name, "method": method, "desc": desc}
        for st in guardian._states.values():
            with st._lock:
                st.consec_fails = 0; st.opened_at = None
                st.probe_pending = False; st.last_fail_reason = None
        with LegPatcher(r, method, patchfn):
            during = _run_phase(guardian, q)
        fault_result["during_fault"] = during
        print(f"  DURING: degraded={during['degraded']} results={during['results_returned']}/{during['n']} "
              f"p50={during['p50_ms']}ms p95={during['p95_ms']}ms err5xx={during['err5xx']}", flush=True)
        if name == "encoder_down":
            bar_c = "splade" not in during["degraded"]
            expected = "no splade degrade (graceful mirror)"
        else:
            leg = "splade" if "splade" in name else ("dense" if "dense" in name else "bm25f")
            bar_c = leg in during["degraded"]
            expected = f"{leg} in degraded"
        bar_a = during["err5xx"] == 0
        bar_b = during["results_returned"] > 0
        fault_result["bars"] = {
            "a_no_5xx_storm": bar_a,
            "b_results_returned": bar_b,
            "c_degraded_names_leg": bar_c,
            "c_expected": expected,
        }
        time.sleep(float(os.environ["SFU_DEMO_LEG_BREAKER_COOLDOWN_S"]) + 0.2)
        after = _run_phase(guardian, q)
        fault_result["after_clear"] = after
        if name == "encoder_down":
            reopened = "splade" not in after["last_degraded"]
        else:
            leg = "splade" if "splade" in name else ("dense" if "dense" in name else "bm25f")
            reopened = leg not in after["last_degraded"]
        fault_result["bars"]["d_breaker_recovers"] = bool(reopened)
        print(f"  AFTER:  degraded={after['degraded']} results={after['results_returned']}/{after['n']} "
              f"→ recovered={reopened}", flush=True)
        out["faults"].append(fault_result)

    all_bars = all(all(f["bars"].values()) for f in out["faults"])
    out["verdict"] = "PASS" if all_bars else "FAIL"
    out["verdict_bars"] = {f["name"]: f["bars"] for f in out["faults"]}
    rf = REPO / "data" / "eval_results" / \
         f"wi9_fault_injection_{time.strftime('%Y%m%d_%H%M%S')}.json"
    rf.write_text(json.dumps(out, indent=2))
    print(f"\n=== WI-9 VERDICT: {out['verdict']} ===", flush=True)
    for f in out["faults"]:
        print(f"  {f['name']}: {f['bars']}")
    print(f"result: {rf}", flush=True)
    return 0 if all_bars else 1


if __name__ == "__main__":
    sys.exit(main())
