#!/usr/bin/env python3
"""Delta-ingest M3 at full N (2026-10-01, agent EVAL): stitch Part A rows
0-349 (2026-09-30 processes base:A / delta:A) with rows 350-599 (2026-10-01
continuation processes, same src snapshot code_e0e3a8f4, `drive --a-start
350`), and compare the 2026-09-30 base:B with a second gate-off base:B
process (the gate-off vs gate-off noise control for Part B).

Statistics are computed by the M3 harness's own `summarize()` (imported, not
copied) on a merged runs directory, so the stitched Part A uses exactly the
pre-registered definitions; this script only builds the merged inputs and
adds the stitch record and the control comparison. Bars unchanged:
median rank change 0; displaced <= 60 of 1,200 slots.

Noise control (no bar of its own; reported beside Part B): the same Part B
statistics (fused top-10 / top-50 id-list identity, displaced count with the
same definition, per-leg top-10 identity, final top-10 changes) between two
gate-off processes on the same code.

Run:
  /home/vscode/work/venv_local/bin/python3 scripts/experiments/eval_delta_ingest_m3_fulln_stitch.py \
    --old-runs /home/vscode/work/delta_ingest/eval_w3/m3_runs_20260930_copy \
    --new-runs /home/vscode/work/delta_ingest/m3/runs_20261001 \
    --out data/eval_results/delta_ingest_M3_fullN_20261001.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts/experiments/eval_delta_ingest_m3_bm25f_drift.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("m3h", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-runs", required=True)
    ap.add_argument("--new-runs", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    h = load_harness()
    old, new = Path(args.old_runs), Path(args.new_runs)
    stitch: dict = {"old_runs": str(old), "new_runs": str(new), "arms": {}}
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        runs = work / "runs"
        runs.mkdir()
        for p in old.glob("drive*.json"):
            shutil.copy(p, runs / p.name)
        for p in new.glob("drive*.json"):
            shutil.copy(p, runs / f"drive_20261001_{p.name}")
        for name in ("base_B", "delta_B"):
            shutil.copy(old / f"{name}.json", runs / f"{name}.json")
            shutil.copy(old / f"{name}.log", runs / f"{name}.log")
        for name in ("base_A", "delta_A"):
            a = json.loads((old / f"{name}.json").read_text())
            b = json.loads((new / f"{name}.json").read_text()) if (new / f"{name}.json").exists() else None
            rows_old = [r for r in a["part_a"] if r["i"] < 350]
            rows_new = [r for r in (b or {}).get("part_a", []) if r["i"] >= 350]
            idx = [r["i"] for r in rows_old + rows_new]
            contiguous = idx == list(range(len(idx)))
            merged = dict(a)
            merged["part_a"] = rows_old + rows_new
            ok_old = a["health"].get("ok")
            ok_new = None if b is None else b["health"].get("ok")
            merged["health"] = dict(a["health"])
            merged["health"]["ok"] = bool(ok_old) and bool(ok_new)
            merged["health"]["problems"] = (a["health"].get("problems") or []) + \
                ([] if b is None else (b["health"].get("problems") or [])) + ([] if b else ["continuation not run"])
            merged["partial"] = bool(a.get("partial")) or (b is None) or bool(b.get("partial"))
            (runs / f"{name}.json").write_text(json.dumps(merged, default=str))
            logs = [(old / f"{name}.log"), (new / f"{name}.log")]
            (runs / f"{name}.log").write_text("".join(p.read_text(errors="replace") for p in logs if p.exists()))
            stitch["arms"][name] = {
                "rows_from_20260930": len(rows_old), "rows_from_20261001": len(rows_new),
                "indices_contiguous_from_0": contiguous,
                "health_20260930": a["health"], "health_20261001": None if b is None else b["health"],
                "env_20261001": None if b is None else b.get("env"),
                "host_20261001": None if b is None else {k: b.get(k) for k in ("host_start", "host_end", "maxrss_gb",
                                                                                "wall_s", "partial")},
                "stopped_at_deadline_20261001": None if b is None else b.get("part_a_stopped_at_deadline")}
        h.WORK = work
        out_tmp = work / "summary.json"
        h.OUT = out_tmp
        h.summarize(argparse.Namespace())
        res = json.loads(out_tmp.read_text())

    res["date"] = "2026-10-01"
    res["item"] = "M3 BM25F score drift (T1), Part A at full N (stitched) + Part B gate-off noise control"
    res["stitch"] = stitch
    res["stitch"]["kind"] = ("STITCHED: Part A rows 0-349 from the 2026-09-30 processes, rows 350-599 from the "
                             "2026-10-01 continuation processes; both on src snapshot code_e0e3a8f4 (src identical "
                             "to dfc06e6e); Part B = the 2026-09-30 base:B / delta:B processes unchanged")
    res["stitch_script"] = "scripts/experiments/eval_delta_ingest_m3_fulln_stitch.py"

    ob = json.loads((old / "base_B.json").read_text())
    cb_path = new / "base_B.json"
    ctl = {"definition": "Part B statistics between two gate-off processes (2026-09-30 base:B vs 2026-10-01 "
                         "base:B, same src snapshot), same displaced definition; no bar (noise floor for Part B)"}
    if cb_path.exists():
        cb = json.loads(cb_path.read_text())
        bb, cc = ob.get("part_b", []), cb.get("part_b", [])
        m = min(len(bb), len(cc))
        assert all(x["query"] == y["query"] for x, y in zip(bb[:m], cc[:m]))
        upd = set(h.load_ready()["updated_ids"])
        fb, fc = [r["fused_ids"] for r in bb[:m]], [r["fused_ids"] for r in cc[:m]]
        disp, per = h.top10_displaced(fb, fc, upd)
        disp_all, _ = h.top10_displaced(fb, fc, set())
        ctl.update({
            "health_control": cb.get("health"), "control_env": cb.get("env"),
            "control_host": {k: cb.get(k) for k in ("host_start", "host_end", "maxrss_gb", "wall_s", "partial")},
            "n_topics": m, "partial": m < 120,
            "displaced_fused_top10_excl_updated": disp,
            "displaced_fused_top10_all_ids": disp_all,
            "fused_top10_idlist_identical": sum(1 for x, y in zip(fb, fc) if x[:h.LIMIT] == y[:h.LIMIT]),
            "fused_top50_idlist_identical": sum(1 for x, y in zip(fb, fc) if x == y),
            "fused_scores_identical": sum(1 for x, y in zip(bb[:m], cc[:m]) if x["fused_scores"] == y["fused_scores"]),
            "bm25f_leg_top10_identical": sum(1 for x, y in zip(bb[:m], cc[:m])
                                             if x["bm25f_ids"][:h.LIMIT] == y["bm25f_ids"][:h.LIMIT]),
            "splade_leg_top10_identical": sum(1 for x, y in zip(bb[:m], cc[:m])
                                              if x["splade_ids"][:h.LIMIT] == y["splade_ids"][:h.LIMIT]),
            "bm25f_leg_full_identical": sum(1 for x, y in zip(bb[:m], cc[:m]) if x["bm25f_ids"] == y["bm25f_ids"]),
            "splade_leg_full_identical": sum(1 for x, y in zip(bb[:m], cc[:m]) if x["splade_ids"] == y["splade_ids"]),
            "final_top10_changed_topics": sum(1 for x, y in zip(bb[:m], cc[:m]) if x["final_ids"] != y["final_ids"]),
            "displaced_examples": [{"query": bb[i]["query"], "displaced": p} for i, p in enumerate(per) if p][:20],
            "log_scan": h.scan_log(new / "base_B.log"),
        })
    else:
        ctl["verdict"] = "NOT RUN"
    res["part_b_noise_control"] = ctl
    res["timings_valid"] = False
    Path(args.out).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res["verdict"], indent=1))
    print(json.dumps({k: v for k, v in res["part_a"].items() if k not in ("worst_20", "query_errors")}, indent=1,
                     default=str))
    print(json.dumps({k: v for k, v in ctl.items() if k not in ("health_control", "control_env",
                                                                "displaced_examples")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
