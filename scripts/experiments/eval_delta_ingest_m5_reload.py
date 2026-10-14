#!/usr/bin/env python3
"""Delta-ingest M5: reload cost after a delta publish
(docs/delta_ingest/03_SPIKE_PLAN.md M5; the A1 side of the in-place spike's
B5 bar).

PRE-REGISTERED (bar copied verbatim from 03_SPIKE_PLAN.md M5, written into
this header 2026-09-29 before any M5 number existed; operational definitions
below were fixed before the run):

  metric : `reload()` wall time and the first-query latency after it, with
           the SEISMIC backend dropped, 5 reps
  bar    : reload <= 15 s; first-query p50 <= 2x warm p50 (page cache stays warm)

Operational definitions (fixed before the run):
  roots        : private COPIES of the M4 roots root_n1 and root_n8
                 (/home/vscode/work/inplace_update/m4/, built by
                 eval_delta_ingest_m4_read_amp.py) at .../m5/root_n1, root_n8,
                 repointed with the supported CLI `publish`. The M4 roots are
                 never touched.
  process      : one fresh process per root (flock /tmp/sfu_latency_measure.lock),
                 SFU_DELTA_ROOT=<copy>, SFU_SEISMIC_FEDERATION=parallel (served
                 default on this host), SFU_SEISMIC_SHARD_MANIFEST and
                 SFU_SEISMIC_STAGE_DIR blank (see the M4 header for why blank).
                 Health asserted before the first timed query exactly as in M4
                 (SPLADE encoder, SEISMIC backend class and shard count, delta
                 layer generations, cross-encoder, embedding model; warnings
                 scanned for fallback / ENOMEM signatures).
  warm p50     : one warm-up pass over the 120 natural topics
                 (dense_ablation_qrels_20260817.json, as M1/M4), then one
                 measured warm pass; warm p50 = p50 of `search_rrf(q, 50)` over
                 that pass.
  one rep      : (1) `python -m spike.delta_ingest.cli publish` on the copy in a
                 subprocess (the operator's publish; it rotates the stamp,
                 generations unchanged) - not timed as reload; (2) t0;
                 `retriever.reload()`; reload_s = wall of that call; assert
                 `retriever._seismic is None` (backend dropped = issue S4 path);
                 (3) first query = topic (rep-1)*24 of the 120 (5 distinct
                 topics), `search_rrf`, timed; the lazy SEISMIC re-open inside
                 it is timed separately by wrapping `_seismic_backend`;
                 (4) the next 9 topics timed as the recovery curve.
  bars         : reload PASS iff max over 5 reps of reload_s <= 15 s (also
                 reported: reload_s + backend re-open, the full S4 cost).
                 first-query PASS iff median over 5 reps of first-query ms
                 <= 2 x warm p50. Paired: each first query vs the same
                 topic's warm latency.
  controls     : 2 reps of reload() WITHOUT a publish (stamp unchanged,
                 backend kept) after the 5 reps; recorded, no bar.
  O1/O2        : the buffer is empty in these roots, so O1 (SPLADE buffer leg
                 not refreshed) and O2 (publish-to-reload gap) cannot change
                 results here; every publish is followed by reload() before
                 any query (the supported flow).

Run:
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m5_reload.py drive
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "experiments"))
import eval_delta_ingest_m4_read_amp as m4  # noqa: E402

WORK = m4.WORK.parent / "m5"
REPS = 5
CONTROL_REPS = 2
RECOVERY = 9


def copy_root(n: int) -> Path:
    src, dst = m4.WORK / f"root_n{n}", WORK / f"root_n{n}"
    if not dst.exists():
        shutil.copytree(src, dst, symlinks=True)
        rc = cli_publish(dst)
        if rc["rc"] != 0:
            raise RuntimeError(f"publish on copy failed: {rc}")
    return dst


def cli_publish(root: Path) -> dict:
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "spike.delta_ingest.cli", "publish", "--delta-root", str(root),
                        "--base-shard-manifest", str(m4.BASE_MANIFEST)], cwd=str(REPO),
                       capture_output=True, text=True, timeout=600)
    stamp = None
    try:
        stamp = json.loads((root / "generations.json").read_text()).get("stamp")
    except Exception:
        pass
    return {"rc": p.returncode, "s": round(time.perf_counter() - t, 2), "stamp": stamp,
            "stderr_tail": p.stderr[-600:] if p.returncode else "",
            "enomem": "Cannot allocate memory" in (p.stderr + p.stdout)}


def child(args) -> int:
    import logging
    t_start = time.time()
    host0 = m4.host_state()
    sys.path.insert(0, args.src)
    cap = m4._WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": []}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    from lib.embedding import _load_model
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    retriever = tools._get_thinclient_retriever()
    root = Path(args.root)
    n_gen = args.n
    out = {"root": str(root), "n_gen": n_gen, "pid": os.getpid(), "host_start": host0, "health": health,
           "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                   not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))}}
    if retriever is None or os.environ.get("SFU_SEISMIC_STAGE_DIR") or os.environ.get("SFU_META_STAGE_DIR"):
        bad("not thinclient, or a stage dir is set in the child env")
        Path(args.rows_out).write_text(json.dumps(out) + "\n")
        return 3
    retriever._fetch_remote_abstracts = lambda ids: {}
    retriever._load()
    if not encode_splade("warm up query for sparse encoder", retriever.splade_model_path):
        bad("encode_splade empty")
    if _get_cross_encoder() is None:
        bad("cross-encoder not loaded")
    if _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None) is None:
        bad("embedding model not loaded")

    def check_backend(tag: str):
        b = retriever._seismic
        if b is None:
            bad(f"{tag}: backend not loaded")
            return
        if type(b).__name__ != "ParallelSeismicBackend":
            bad(f"{tag}: backend {type(b).__name__}")
        if len(b.shards) != m4.N_BASE_SHARDS + n_gen or any(s is None for s in b.shards):
            bad(f"{tag}: shards {len(b.shards)} != {m4.N_BASE_SHARDS + n_gen}")
        d = retriever._delta
        if d is None or len(d.generations) != n_gen:
            bad(f"{tag}: delta layer generations wrong")
        elif getattr(retriever, "_seismic_manifest", None) != d.shard_manifest_path():
            bad(f"{tag}: served manifest is not the delta composed manifest")

    retriever._seismic_backend()
    check_backend("initial")
    if any(any(s in w for s in m4.SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    out["warnings_at_load"] = list(cap.records)
    if not health["ok"]:
        out["host_end"] = m4.host_state()
        Path(args.rows_out).write_text(json.dumps(out) + "\n")
        return 3

    orig_backend = type(retriever)._seismic_backend
    reopen: dict = {}

    def timed_backend(self=retriever):
        was_none = self._seismic is None
        t = time.perf_counter()
        r = orig_backend(self)
        if was_none:
            reopen["s"] = time.perf_counter() - t
        return r
    retriever._seismic_backend = timed_backend

    items = m4.load_topics()

    def run(q):
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        fused = retriever.search_rrf(q, top_k=m4.TOP_K)
        ms = (time.perf_counter() - t) * 1000
        return round(ms, 2), resource.getrusage(resource.RUSAGE_SELF).ru_majflt - ru0.ru_majflt, len(fused)

    out["quiet_gate"] = m4.quiet_gate(args.quiet_wait)
    warm = {}
    for p in range(2):
        rows = []
        for key, q in items:
            ms, mf, n = run(q)
            rows.append({"topic": key, "ms": ms, "majflt": mf, "n": n})
        if p == 1:
            warm = {r["topic"]: r["ms"] for r in rows}
            out["warm_pass"] = {"p50_ms": m4.pct([r["ms"] for r in rows], 50),
                                "p95_ms": m4.pct([r["ms"] for r in rows], 95),
                                "majflt_mean": round(statistics.fmean([r["majflt"] for r in rows]), 1)}
        else:
            out["warmup_pass"] = {"p50_ms": m4.pct([r["ms"] for r in rows], 50)}
        print(f"[m5 n{n_gen}] pass {p+1} p50={m4.pct([r['ms'] for r in rows], 50)}", flush=True)
    n_warn = len(cap.records)
    reps = []
    for rep in range(REPS + CONTROL_REPS):
        control = rep >= REPS
        pub = None
        if not control:
            time.sleep(1.1)
            pub = cli_publish(root)
            if pub["rc"] != 0:
                bad(f"rep {rep+1}: publish rc={pub['rc']}")
                break
        old_stamp = retriever._delta.stamp if retriever._delta else None
        reopen.clear()
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        retriever.reload()
        reload_s = time.perf_counter() - t
        dropped = retriever._seismic is None
        new_stamp = retriever._delta.stamp if retriever._delta else None
        if not control and not dropped:
            bad(f"rep {rep+1}: backend not dropped after a stamp change")
        base = (rep % REPS) * 24
        seq = [items[(base + i) % len(items)] for i in range(1 + RECOVERY)]
        after = []
        for i, (key, q) in enumerate(seq):
            ms, mf, n = run(q)
            after.append({"topic": key, "ms": ms, "majflt": mf, "n": n, "warm_ms": warm.get(key)})
            if i == 0:
                check_backend(f"rep {rep+1}")
        reps.append({"rep": rep + 1, "control_no_publish": control, "publish": pub,
                     "stamp_before": old_stamp, "stamp_after": new_stamp,
                     "reload_s": round(reload_s, 3), "backend_dropped": dropped,
                     "backend_reopen_s": round(reopen["s"], 3) if "s" in reopen else None,
                     "reload_plus_reopen_s": round(reload_s + reopen.get("s", 0.0), 3),
                     "majflt_reload": resource.getrusage(resource.RUSAGE_SELF).ru_majflt - ru0.ru_majflt,
                     "first_query": after[0], "recovery": after[1:]})
        print(f"[m5 n{n_gen}] rep {rep+1} control={control} reload={reload_s:.2f}s "
              f"reopen={reopen.get('s')} first={after[0]['ms']}ms warm={after[0]['warm_ms']}", flush=True)
    warn_meas = cap.records[n_warn:]
    if any(any(s in w for s in m4.SIGNATURES) for w in warn_meas):
        bad("failure signature in warnings during reps")
    out["warnings_during_reps"] = warn_meas[:50]
    out["reps"] = reps
    out["host_end"] = m4.host_state()
    out["wall_s"] = round(time.time() - t_start, 1)
    Path(args.rows_out).write_text(json.dumps(out) + "\n")
    return 0 if health["ok"] else 3


def drive(args) -> int:
    commit = args.commit or m4.git_commit()
    snap = m4.snapshot_src(commit)
    WORK.mkdir(parents=True, exist_ok=True)
    runs = WORK / f"runs_{args.tag}"
    runs.mkdir(exist_ok=True)
    results = {}
    for n in [int(x) for x in args.ns.split(",")]:
        root = copy_root(n)
        rows_out, logp = runs / f"n{n}.json", runs / f"n{n}.log"
        env = m4.arm_env("n1", "parallel")
        env["SFU_DELTA_ROOT"] = str(root)
        for attempt in range(1, args.retries + 2):
            cmd = ["flock", m4.LOCK, sys.executable, str(Path(__file__).resolve()), "child", "--root", str(root),
                   "--n", str(n), "--rows-out", str(rows_out), "--src", str(snap / "source"),
                   "--quiet-wait", str(args.quiet_wait)]
            with open(logp, "a") as fh:
                fh.write(f"=== attempt {attempt} {m4.utc()} ===\n")
                fh.flush()
                rc = subprocess.call(cmd, env=env, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT,
                                     timeout=args.child_timeout)
            rec = json.loads(rows_out.read_text()) if rows_out.exists() else {}
            ok = rec.get("health", {}).get("ok") and rec.get("reps")
            print(f"n{n} attempt {attempt} rc={rc} ok={bool(ok)}", flush=True)
            if ok:
                break
            if rows_out.exists():
                rows_out.rename(runs / f"n{n}.degraded{attempt}.json")
        results[n] = rec
    return summarize(args, commit, snap, runs)


def summarize(args, commit, snap, runs) -> int:
    per = {}
    degraded = [str(p) for p in sorted(runs.glob("*.degraded*.json"))]
    for p in sorted(runs.glob("n*.json")):
        if ".degraded" in p.name:
            continue
        rec = json.loads(p.read_text())
        main = [r for r in rec.get("reps", []) if not r["control_no_publish"]]
        ctrl = [r for r in rec.get("reps", []) if r["control_no_publish"]]
        if not rec.get("health", {}).get("ok") or len(main) < REPS:
            degraded.append(str(p))
            continue
        warm_p50 = rec["warm_pass"]["p50_ms"]
        first = [r["first_query"]["ms"] for r in main]
        first_p50 = statistics.median(first)
        rl = [r["reload_s"] for r in main]
        paired = [r["first_query"]["ms"] / r["first_query"]["warm_ms"] for r in main if r["first_query"]["warm_ms"]]
        per[f"n{rec['n_gen']}"] = {
            "root": rec["root"], "n_gen": rec["n_gen"], "shards_served": m4.N_BASE_SHARDS + rec["n_gen"],
            "warm_p50_ms": warm_p50, "warm_p95_ms": rec["warm_pass"]["p95_ms"],
            "warmup_pass_p50_ms": rec["warmup_pass"]["p50_ms"],
            "reload_s": rl, "reload_s_max": max(rl), "reload_s_median": statistics.median(rl),
            "backend_reopen_s": [r["backend_reopen_s"] for r in main],
            "reload_plus_reopen_s": [r["reload_plus_reopen_s"] for r in main],
            "backend_dropped_all": all(r["backend_dropped"] for r in main),
            "first_query_ms": first, "first_query_p50_ms": round(first_p50, 2),
            "first_query_ratio_vs_warm_p50": round(first_p50 / warm_p50, 3),
            "first_query_paired_ratio_vs_same_topic_warm": [round(x, 3) for x in paired],
            "first_query_paired_ratio_median": round(statistics.median(paired), 3) if paired else None,
            "recovery_p50_ms_queries_2_to_10": m4.pct([x["ms"] for r in main for x in r["recovery"]], 50),
            "majflt_first_query": [r["first_query"]["majflt"] for r in main],
            "publish_cli_s": [r["publish"]["s"] for r in main],
            "controls_no_publish": [{"reload_s": r["reload_s"], "backend_dropped": r["backend_dropped"],
                                     "first_query_ms": r["first_query"]["ms"]} for r in ctrl],
            "verdict_reload_le_15s": "PASS" if max(rl) <= 15.0 else "FAIL",
            "verdict_first_query_le_2x_warm": "PASS" if first_p50 <= 2 * warm_p50 else "FAIL",
            "quiet_gate": {k: v for k, v in rec.get("quiet_gate", {}).items() if k != "samples"},
            "host_start": {k: rec["host_start"].get(k) for k in ("utc", "loadavg", "mem_gb", "gpu", "busy_procs_gt20pct")},
            "host_end": {k: rec["host_end"].get(k) for k in ("utc", "loadavg", "mem_gb", "gpu", "busy_procs_gt20pct")},
            "reps": rec["reps"],
        }
    log_scan = {p.name: m4.scan_log(p) for p in sorted(runs.glob("*.log"))}
    res = {
        "measurement": "M5 reload cost after a delta publish (docs/delta_ingest/03_SPIKE_PLAN.md)",
        "bar_preregistered": ("03_SPIKE_PLAN.md M5: reload() wall time and the first-query latency after it, "
                              "with the SEISMIC backend dropped, 5 reps -> reload <= 15 s; first-query p50 <= "
                              "2x warm p50 (page cache stays warm)"),
        "operational_definitions": "see the script header (fixed before the run)",
        "script": "scripts/experiments/eval_delta_ingest_m5_reload.py",
        "git_commit_measured_code": commit, "code_snapshot": str(snap),
        "date_utc": time.strftime("%Y-%m-%d", time.gmtime()), "roots": per,
        "degraded_or_retried": degraded, "log_scan": log_scan, "runs_dir": str(runs),
    }
    out = Path(args.out) if args.out else REPO / f"data/eval_results/delta_ingest_M5_{time.strftime('%Y%m%d', time.gmtime())}.json"
    out.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("reps",)} for k, v in per.items()}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drive")
    d.add_argument("--ns", default="1,8")
    d.add_argument("--tag", default="main")
    d.add_argument("--retries", type=int, default=1)
    d.add_argument("--child-timeout", type=int, default=5400)
    d.add_argument("--quiet-wait", type=int, default=600)
    d.add_argument("--commit", default="")
    d.add_argument("--out", default="")
    s = sub.add_parser("summarize")
    s.add_argument("--tag", default="main")
    s.add_argument("--commit", default="")
    s.add_argument("--out", default="")
    c = sub.add_parser("child")
    c.add_argument("--root", required=True)
    c.add_argument("--n", type=int, required=True)
    c.add_argument("--rows-out", required=True)
    c.add_argument("--src", required=True)
    c.add_argument("--quiet-wait", type=int, default=600)
    args = ap.parse_args()
    if args.cmd == "summarize":
        commit = args.commit or m4.git_commit()
        return summarize(args, commit, m4.WORK / f"code_{commit[:8]}", WORK / f"runs_{args.tag}")
    return {"drive": drive, "child": child}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
