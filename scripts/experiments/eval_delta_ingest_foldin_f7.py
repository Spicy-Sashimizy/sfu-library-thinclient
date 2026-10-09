#!/usr/bin/env python3
r"""Delta-ingest fold-in F7: trigger default values per profile (doc 10 §6 F7).

A computation over recorded measurements; no index, no lock. Readings: doc 10
addendum "2026-10-09 — F7 implementation reading" (written before this ran).

---- doc 10 §6 row F7, verbatim (frozen 2e674773) ----
| **F7** | Trigger values per profile | choose (a), (d), (b), (c) defaults from §1 candidates | rule (fixed): the SMALLEST (a) (most frequent fold) whose F4 duty cycle ≤ 25%; if the modelled tax (F0, 09 R1) at that (a)'s fold moment > 8 ms × the adopted `G_max`, the profile is flagged (no default ships ON); (d) = the smallest candidate ≥ the (d) value reached when (a) fires; (c) = 30 days unless F4 duty cycle at (c)-driven folds > 25%; (b) = 8 ms | none |
---- end verbatim ----

Usage: python3 scripts/experiments/eval_delta_ingest_foldin_f7.py [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "data" / "eval_results"

A_CANDIDATES = [0.02, 0.05, 0.10, 0.20]
D_CANDIDATES = [0.05, 0.10, 0.20]
C_DAYS = 30
B_MS = 8.0
DUTY_MAX = 0.25
SHARDS = 8
N_SHARD = 18_799_322
UPSERTS_PER_DAY_CODED = 87_692          # doc 10 §2, per shard, as coded
UPSERTS_PER_DAY_FILTERED = 45_394       # doc 10 §2, per shard, text-filtered (not built)
DEAD_PER_DAY_CODED = 0.00367            # doc 10 §2, fraction of shard per day
DEAD_PER_DAY_FILTERED = 0.00142
D_X1_M = 0.160347
PROFILES = {"laptop": {"fold_enabled": False, "g_max": 8},
            "desktop_gpu": {"fold_enabled": True, "g_max": 8},
            "server": {"fold_enabled": True, "g_max": 8}}


def load(name: str, key: str) -> dict:
    return json.loads((RES / name).read_text())[key]


def inputs() -> dict:
    f4 = load("delta_ingest_foldin_20261004.json", "F4_build_fold3")
    f4d = load("delta_ingest_foldin_20261008.json", "F4_build_fold_del")
    f8 = load("delta_ingest_foldin_f3f8_20261008.json", "F8")
    f0 = load("delta_ingest_foldin_f0_20261008.json", "F0")
    r1 = json.loads((RES / "delta_ingest_M4F_20261001.json").read_text())
    b = f0["model_inputs"]["b_ms_per_gen_from_09_R1_F_SLOPE"]["R1_per_base_section_repeat"]["median"]
    return {
        "fold_wall_s": max(f4["wall_s"], f4d["wall_s"]),
        "fold_wall_sources": {"F4_build_fold3": f4["wall_s"], "F4_build_fold_del": f4d["wall_s"]},
        "publish_s": f8["publish_fold_cli_s"],
        "dx1_ms": f0["paired_differences"]["x1_minus_n0x"]["median"],
        "c_ms_per_M": f0["bar"]["coefficient_c"]["median_ms_per_M_docs"],
        "c_ci": f0["bar"]["coefficient_c"]["ci95_ms_per_M_docs"],
        "b_ms_per_gen": b,
        "r1_key_present": "R1_per_base_section_repeat" in r1,
    }


def tax(inp: dict, d_m: float, g: int, c: float | None = None) -> float:
    c = inp["c_ms_per_M"] if c is None else c
    return inp["dx1_ms"] + inp["b_ms_per_gen"] * (g - 1) + c * (d_m - D_X1_M)


def evaluate(inp: dict, upserts_per_day: int, dead_per_day: float) -> dict:
    sum_wall_h = SHARDS * (inp["fold_wall_s"] + inp["publish_s"]) / 3600
    rows = []
    for a in A_CANDIDATES:
        period_d = a * N_SHARD / upserts_per_day
        rows.append({"a": a, "period_days": round(period_d, 2),
                     "duty_cycle": round(sum_wall_h / (24 * period_d), 4),
                     "D_first_fold_M": round(SHARDS * a * N_SHARD / 1e6, 3),
                     "dead_frac_at_fire": round(dead_per_day * period_d, 4)})
    return {"sum_fold_wall_8_shards_h": round(sum_wall_h, 3), "a_rows": rows}


def choose(inp: dict, stream: dict, g_max: int) -> dict:
    ok = [r for r in stream["a_rows"] if r["duty_cycle"] <= DUTY_MAX]
    if not ok:
        return {"a": None, "flag": True, "why": "no (a) candidate within the 25 % duty cycle"}
    r = ok[0]
    d_m = r["D_first_fold_M"]
    t = tax(inp, d_m, g_max)
    limit = 8.0 * g_max
    d_pick = next((d for d in D_CANDIDATES if d >= r["dead_frac_at_fire"]), None)
    c_duty = stream["sum_fold_wall_8_shards_h"] / (24 * C_DAYS)
    rounds = {k: round(tax(inp, d_m * k, g_max), 2) for k in (1, 2, 4)}
    return {
        "a": r["a"], "a_period_days": r["period_days"], "a_duty_cycle": r["duty_cycle"],
        "d": d_pick, "d_reached_at_a": r["dead_frac_at_fire"],
        "c_days": C_DAYS if c_duty <= DUTY_MAX else None, "c_duty_cycle": round(c_duty, 4),
        "b_ms": B_MS,
        "D_at_first_fold_M": d_m, "G_max": g_max,
        "tax_ms_at_first_fold": round(t, 2), "tax_limit_ms": limit,
        "flag": t > limit,
        "recorded_no_verdict": {
            "tax_at_fold_round_k": rounds,
            "tax_c_ci_low": round(tax(inp, d_m, g_max, inp["c_ci"][0]), 2),
            "tax_c_ci_high": round(tax(inp, d_m, g_max, inp["c_ci"][1]), 2),
            "tax_G_max_1_vs_limit_8": round(tax(inp, d_m, 1), 2),
            "tax_G_max_4_vs_limit_32": round(tax(inp, d_m, 4), 2),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RES / f"delta_ingest_foldin_f7_{time.strftime('%Y%m%d', time.gmtime())}.json"))
    a = ap.parse_args()
    inp = inputs()
    coded = evaluate(inp, UPSERTS_PER_DAY_CODED, DEAD_PER_DAY_CODED)
    filt = evaluate(inp, UPSERTS_PER_DAY_FILTERED, DEAD_PER_DAY_FILTERED)
    per_profile = {}
    for name, p in PROFILES.items():
        if not p["fold_enabled"]:
            per_profile[name] = {"verdict": "NOT APPLICABLE", "why": "fold disabled for shards above *est.* ~6 M docs (doc 10 §7)"}
            continue
        ch = choose(inp, coded, p["g_max"])
        ch["text_filtered_recorded"] = choose(inp, filt, p["g_max"])
        ch["verdict"] = "FLAGGED (no default ships ON)" if ch["flag"] else "DEFAULTS CHOSEN"
        if name == "server":
            ch["note"] = "fold wall not measured on a server; desktop_gpu wall used (*est.*, upper bound)"
        per_profile[name] = ch
    rec = {"item": "doc 10 §6 F7 trigger values per profile", "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "script": "scripts/experiments/eval_delta_ingest_foldin_f7.py",
           "reading": "doc 10 addendum 2026-10-09 — F7 implementation reading",
           "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "inputs": inp, "stream_as_coded": coded, "stream_text_filtered": filt, "profiles": per_profile}
    out = Path(a.out)
    full = json.loads(out.read_text()) if out.exists() else {}
    full["F7"] = rec
    out.write_text(json.dumps(full, indent=1) + "\n")
    print(json.dumps(per_profile, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
