#!/usr/bin/env python3
"""Same-day gate-OFF baseline cells for the F6 paired A/B (2026-07-14).

The valid gate-ON cells were measured on the natively rebuilt .so; the
2026-07-13 Q7 baseline predates that rebuild, so it can't attribute the
gain. These two hybrid cells (identical protocol, gate OFF) close that
confound."""
import json
import sys

sys.path.insert(0, "scripts/seismic_testbed")
from q7_hybrid_federation_bench import run_cell  # noqa: E402

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"

cells = []
for rep in (1, 2):
    c = run_cell(MANIFEST, "hybrid", 100, 3, rep,
                 {"SFU_SEISMIC_LOAD_MODE": "mmap"})
    s = c["seismic"]
    lm = s["latency_ms"]
    cold, warm = lm["cold"], lm["warm"]
    print("OFF rep%d: cold p50 %.0f p95 %.0f | warm p50 %.0f p95 %.0f | empty %s"
          % (rep, cold["p50_ms"], cold["p95_ms"], warm["p50_ms"],
             warm["p95_ms"], s.get("empty_results")), flush=True)
    cells.append({"cell_file": c["_cell_file"],
                  "cold_p50": cold["p50_ms"], "cold_p95": cold["p95_ms"],
                  "warm_p50": warm["p50_ms"], "warm_p95": warm["p95_ms"],
                  "empty_results": s.get("empty_results")})

json.dump({"purpose": "F6 paired gate-OFF baseline (same day, same .so)",
           "date": "2026-07-14", "manifest": MANIFEST,
           "queries": 100, "passes": 3, "cells": cells},
          open("data/eval_results/f6_gateoff_baseline_20260714.json", "w"),
          indent=2)
print("wrote f6_gateoff_baseline_20260714.json")
