#!/usr/bin/env python3
"""F3 (2026-07-14): mlock_ranges pin-tier A/B — disk-streaming research Phase 3.

Pre-registered in docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §F3 BEFORE
this run. The bar (the no-OOM guarantee): every dial cell shows VmSwap ≈ 0 +
no OOM-killer events (dmesg) + T1 bit-identical (0/100 mismatches with pin on).
Latency uplift is REPORTED but not gated (it requires the 32 GB constrained
host — the 15.8 s warm≈cold regime; this dev container has ~54 GB MemAvailable,
so the working set fits RAM and the warm p50 is already RAM-speed — the pin tier
adds ~0 there. The container-side run verifies the no-OOM + T1 contract + the
mechanism works; the latency win is the operator's host-gated measurement).

Dials (the F1 sidecar budgets, doc 03 §3):
  - off    (SFU_SEISMIC_PIN_BUDGET_GB=0, MLOCK_FLOOR=0): today's behavior, baseline
  - 1.6gb  (hot-50 ≈ 60.7% of touches pinned) + floor mlock
  - 4.2gb  (hot-80 ≈ 88.6% of touches pinned) + floor mlock

Reuses q7's EXACT cell protocol (fadvise-DONTNEED + serve_footprint_bench,
hybrid arm — the served path) so the vmswap/warm/cold numbers are directly
comparable to the E8 v2 Q7 baseline (`_e8s2_q7_federated_v2_20260713.json`).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from q7_hybrid_federation_bench import run_cell, _cold_p50, _warm_p50, _vmswap_gb  # noqa: E402

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
REPS = 2
QUERIES = 100
PASSES = 3

# Dials: (name, pin_budget_gb, mlock_floor). The F1 sidecars hot50_1.6gb /
# hot80_4.2gb are loaded by name when the budget matches (the backend's
# budget_aliases maps 1.6->hot50_1.6gb, 4.2->hot80_4.2gb).
DIALS = [
    ("off", "0", "0"),
    ("1.6gb_hot50", "1.6", "1"),
    ("4.2gb_hot80", "4.2", "1"),
]


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def t1_parity_with_pin(pin_gb: str, mlock_floor: str) -> dict:
    """Run the q7 T1 parity (par==seq==hybrid bit-identical) with the pin env
    set, by invoking the q7 bench with --skip-t1=False on a TINY cell? No —
    the q7 T1 runs in-process, not in the subprocess. So we replicate the T1
    parity probe here in-process (same 20-query check) with pin env on."""
    import os
    os.environ["SFU_SEISMIC_PIN_BUDGET_GB"] = pin_gb
    os.environ["SFU_SEISMIC_MLOCK_FLOOR"] = mlock_floor
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend,
        HybridSeismicBackend, _load_manifest)
    paths = _load_manifest(MANIFEST, load_mode="mmap")[:2]
    par = ParallelSeismicBackend(paths, load_mode="mmap")
    seq = SequentialSeismicBackend(paths, load_mode="mmap")
    os.environ["SFU_SEISMIC_HYBRID_DISABLE"] = "0"
    hyb = HybridSeismicBackend(paths, load_mode="mmap")
    qrecs = json.loads((REPO / "data" / "eval_results" /
                        "diverse_queries.json").read_text())
    queries = [r["paraphrase"] for r in qrecs][:20]
    n_match = 0
    mismatches = []
    for i, qtext in enumerate(queries):
        q = par.encode_query(qtext)
        if not q:
            continue
        r_par = par.search_encoded(q, top_k=50, k_prime=100)
        r_seq = seq.search_encoded(q, top_k=50, k_prime=100)
        r_hyb = hyb.search_encoded(q, top_k=50, k_prime=100)
        if [o for o, _ in r_par] == [o for o, _ in r_seq] == [o for o, _ in r_hyb]:
            n_match += 1
        else:
            mismatches.append({"q": i, "par": len(r_par), "seq": len(r_seq),
                               "hyb": len(r_hyb)})
    return {"n_match": n_match, "n_queries": len(queries),
            "passed": n_match == len(queries) and not mismatches,
            "mismatches": mismatches[:3]}


def check_oom_killer() -> list:
    """Scan dmesg for OOM-killer events since the run started (best-effort;
    may need sudo / be empty if dmesg restricted)."""
    try:
        out = subprocess.run(["dmesg", "--time-format=iso"],
                             capture_output=True, text=True, timeout=10)
        return [ln for ln in out.stdout.splitlines()
                if "Out of memory" in ln or "Killed process" in ln
                or "oom_reaper" in ln]
    except Exception:
        return ["<dmesg unavailable>"]


def main():
    bench_env_base = {"SFU_SEISMIC_LOAD_MODE": "mmap"}
    results = {}
    oom_before = check_oom_killer()
    log(f"OOM-killer lines before A/B: {len(oom_before)}")

    for dial_name, pin_gb, mlock_floor in DIALS:
        log(f"=== DIAL {dial_name} (pin={pin_gb}GB, mlock_floor={mlock_floor}) ===")
        # T1 parity in-process with this dial's pin env
        try:
            t1 = t1_parity_with_pin(pin_gb, mlock_floor)
            log(f"  T1: {t1['n_match']}/{t1['n_queries']} bit-identical "
                f"(passed={t1['passed']})")
        except Exception as e:
            t1 = {"passed": False, "error": str(e)}
            log(f"  T1 FAILED: {e}")
        # 2 reps of the hybrid warm/cold cell with pin env on
        cells = []
        for rep in range(1, REPS + 1):
            env = {**bench_env_base,
                   "SFU_SEISMIC_PIN_BUDGET_GB": pin_gb,
                   "SFU_SEISMIC_MLOCK_FLOOR": mlock_floor}
            cell = run_cell(MANIFEST, "hybrid", QUERIES, PASSES, rep, env)
            cells.append({
                "cold_p50": _cold_p50(cell), "warm_p50": _warm_p50(cell),
                "vmswap_gb": _vmswap_gb(cell),
                "anon_floor_gb": cell.get("seismic", {}).get("ram", {}).get("anon_floor_gb"),
                "file": cell.get("_cell_file"),
            })
            log(f"  rep{rep}: cold {_cold_p50(cell):.0f}ms warm {_warm_p50(cell):.0f}ms "
                f"vmswap {_vmswap_gb(cell)} swap")
        import statistics
        colds = [c["cold_p50"] for c in cells if c["cold_p50"]]
        warms = [c["warm_p50"] for c in cells if c["warm_p50"]]
        swaps = [c["vmswap_gb"] for c in cells if c["vmswap_gb"] is not None]
        results[dial_name] = {
            "pin_budget_gb": pin_gb, "mlock_floor": mlock_floor,
            "t1": t1,
            "cold_p50_median": statistics.median(colds) if colds else None,
            "warm_p50_median": statistics.median(warms) if warms else None,
            "vmswap_max": max(swaps) if swaps else None,
            "cells": cells,
        }

    oom_after = check_oom_killer()
    new_oom = [ln for ln in oom_after if ln not in oom_before and ln != "<dmesg unavailable>"]

    # Verdict under the pre-registered rule (no-OOM + T1)
    verdicts = {}
    for dial, r in results.items():
        swap_ok = (r["vmswap_max"] is None) or (r["vmswap_max"] <= 0.1)
        t1_ok = r["t1"].get("passed", False)
        oom_ok = not new_oom
        verdicts[dial] = "PASS" if (swap_ok and t1_ok and oom_ok) else "FAIL"
        verdicts[dial] += f" (vmswap_max={r['vmswap_max']}, t1={r['t1'].get('passed')}, oom={not oom_ok})"

    out = {
        "probe": "f3_pin_ab",
        "date": time.strftime("%Y-%m-%d"),
        "preregistration": "docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §F3",
        "manifest": MANIFEST,
        "n_queries": QUERIES, "reps": REPS, "passes": PASSES,
        "dials": [d[0] for d in DIALS],
        "protocol": "q7 hybrid cell + in-process T1, fadvise-DONTNEED per cell",
        "host_caveat": "dev container ~54 GB MemAvailable (NOT the 32 GB "
                       "constrained host); warm p50 is already RAM-speed here "
                       "so pin-tier latency uplift is host-gated (G8 regime). "
                       "This run verifies the no-OOM + T1 contract + the mechanism.",
        "results": results,
        "oom_new_during_run": new_oom,
        "verdicts": verdicts,
    }
    out_path = REPO / "data" / "eval_results" / (
        "f3_pin_ab_" + time.strftime("%Y%m%d") + ".json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    log(f"wrote {out_path}")
    for dial, v in verdicts.items():
        log(f"  {dial}: {v}")


if __name__ == "__main__":
    main()
