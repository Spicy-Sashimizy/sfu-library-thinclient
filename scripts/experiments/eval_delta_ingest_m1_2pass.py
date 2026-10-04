#!/usr/bin/env python3
"""Delta-ingest M1 rerun 2026-10-01: gate-off parity, 2 passes per arm, current code.

Bar (03_SPIKE_PLAN.md M1, frozen 2026-09-29, verbatim): "fused + final top-10,
120 topics, `SFU_DELTA_ROOT` unset vs set with an EMPTY delta root ->
byte-identical 120/120". Fixed inputs: 2 passes per arm.

Same method as eval_delta_ingest_m1_gate_off_parity.py (whose compare() is
reused unchanged); what this harness adds:
  * Reference arm = gate_off (SFU_DELTA_ROOT absent) at the SAME commit as the
    empty_root arm (one `git archive <HEAD> src` snapshot on local disk feeds
    both children). The stored aa0fc405 gate_off rows are compared only as an
    informational cross-commit view, never for the verdict.
  * Health gate before the first query (fail loudly, exit 3, no rows):
    onnxruntime imports, encode_splade returns terms, the cross-encoder loads
    (not None), the embedding model loads, the SEISMIC backend loads, no
    failure signature (ENOMEM, CE unavailable, SPLADE fallback ...) in the
    warnings logged so far, stage dirs empty, and the arm's delta state is the
    expected one (gate_off: no layer; empty_root: layer with 0 generations,
    0 deleted, 0 superseded, empty buffer, no shard manifest).
  * Warnings logged during every query are captured per row; a row with a
    failure signature is flagged `degraded` (so a silent fallback cannot pass
    as identity or masquerade as a gate effect).
  * Rows are appended to <scratch>/<arm>.rows.jsonl as they are produced (one
    line per topic per pass) and meta/health to <arm>.meta.json, so a deadline
    kill leaves a usable partial; the child also stops itself at --deadline.
  * Local mirrors: the driver can launch children with another interpreter
    (--python, e.g. /home/vscode/work/venv_local/bin/python3) and passes
    SFU_SPLADE_MODEL_PATH / SFU_CE_MODEL_PATH / SFU_EMBEDDING_MODEL_PATH from
    its own env (sha256 of the model files recorded). SFU_SEISMIC_STAGE_DIR and
    SFU_META_STAGE_DIR are set to "" (present-but-empty, so lib.config's .env
    loader cannot re-add the .env value /var/tmp/seismic_stage).
  * Arms can run concurrently (--parallel), each pinned with taskset to its
    own cores, each under `flock -s` (shared) on the latency lock. Timings are
    INVALID in that mode (marked in the results).
  * A child that dies before its first progress line with ENOMEM in its log
    (O12) is restarted up to --retries times.

Run (2026-10-01):
  SFU_SPLADE_MODEL_PATH=/home/vscode/work/models_local/splade_onnx_fused \
  SFU_CE_MODEL_PATH=/home/vscode/work/models_local/sfu-cross-encoder-v1 \
  SFU_EMBEDDING_MODEL_PATH=/home/vscode/work/delta_ingest/m1/models/sfu-academic-embed-v5 \
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m1_2pass.py drive \
     --python /home/vscode/work/venv_local/bin/python3 --parallel --lock-shared \
     --cpus gate_off=0-3,empty_root=4-7 --deadline 2026-10-01T06:40:00Z
  .venv/bin/python3 scripts/experiments/eval_delta_ingest_m1_2pass.py summarize
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = "2026-10-01"
SCRATCH = Path("/home/vscode/work/delta_ingest/m1")
OUT = REPO / "data/eval_results/delta_ingest_M1_2pass_20261001.json"
REF_ROWS = Path("/var/tmp/sfu_delta_A_20260929/gate_off.json")
LOCK = "/tmp/sfu_latency_measure.lock"
TOP_K = 50
LIMIT = 10
ENV_DROP = ("SFU_DELTA_ROOT", "SFU_SEARCH_SPECULATIVE_RERANK", "SFU_SEISMIC_SHARD_MANIFEST")
ENV_BLANK = ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR")
MODEL_ENV = ("SFU_SPLADE_MODEL_PATH", "SFU_CE_MODEL_PATH", "SFU_EMBEDDING_MODEL_PATH")
SIGNATURES = ("Cannot allocate memory", "Errno 12", "CrossEncoder unavailable",
              "Failed to load embedding model", "Reranker failed", "Traceback",
              "falling back to BM25F", "SPLADE leg failed", "SPLADE encoder failed",
              "delta layer off", "SFU_SEISMIC_SHARD_MANIFEST is set", "buffer skipped",
              "thinclient index unavailable")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def git_commit() -> str:
    return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()


def load_topics(limit: int = 0) -> list[tuple[str, str]]:
    for _ in range(20):
        try:
            topics = json.loads(TOPICS.read_text())["topics"]
            break
        except OSError:
            time.sleep(1)
    items = [(k, v["natural"]) for k, v in topics.items()]
    return items[:limit] if limit else items


def mem_state() -> dict:
    out = {}
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, v = ln.split(":", 1)
            if k in ("MemAvailable", "MemFree", "SwapFree", "SwapTotal", "Cached"):
                out[k + "_gb"] = round(int(v.split()[0]) / 1048576, 2)
    except Exception:
        pass
    return out


def proc_mem() -> dict:
    out = {}
    try:
        for ln in Path("/proc/self/status").read_text().splitlines():
            if ln.startswith(("VmRSS", "VmHWM", "VmSwap")):
                k, v = ln.split(":", 1)
                out[k + "_gb"] = round(int(v.split()[0]) / 1048576, 2)
    except Exception:
        pass
    return out


class _WarnCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        try:
            self.records.append(f"{record.name}: {record.getMessage()}"[:400])
        except Exception:
            pass


def child(args) -> int:
    t_start = time.time()
    deadline = parse_utc(args.deadline) if args.deadline else None
    scratch = Path(args.scratch)
    meta_path = scratch / f"{args.arm}.meta.json"
    rows_path = scratch / f"{args.arm}.rows.jsonl"
    rows_path.write_text("")
    cap = _WarnCapture()
    logging.getLogger().addHandler(cap)
    if logging.getLogger().level > logging.WARNING or logging.getLogger().level == logging.NOTSET:
        logging.getLogger().setLevel(logging.WARNING)
    health: dict = {"ok": True, "problems": []}
    meta: dict = {"arm": args.arm, "pid": os.getpid(), "start_utc": utc(), "python": sys.executable,
                  "src": args.src, "health": health, "timings_valid": False,
                  "env": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("SFU_") and
                          not any(s in k for s in ("KEY", "TOKEN", "AUTH", "SECRET", "PASS"))},
                  "sfu_delta_root_set": "SFU_DELTA_ROOT" in os.environ, "host_start": mem_state()}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    def flush(state: str):
        meta["state"] = state
        meta["wall_s"] = round(time.time() - t_start, 1)
        meta["proc_mem"] = proc_mem()
        meta_path.write_text(json.dumps(meta, default=str, indent=1) + "\n")

    for k in ENV_BLANK:
        if os.environ.get(k):
            bad(f"{k} is set to {os.environ.get(k)!r} in the child env; refusing to load")
    if not health["ok"]:
        flush("health_fail")
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3
    sys.path.insert(0, args.src)
    try:
        import onnxruntime
        health["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    import lib.thinclient.retriever as rmod
    import lib.thinclient.delta_layer as dmod
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    meta["code_under_test"] = {m.__name__: {"file": m.__file__, "sha256": hashlib.sha256(
        Path(m.__file__).read_bytes()).hexdigest()} for m in (tools, rmod, dmod)}
    if not all(v["file"].startswith(args.src) for v in meta["code_under_test"].values()):
        bad("lib was not imported from the snapshot --src")
    meta["features"] = dict(tools._get_features())
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        bad("search backend is not thinclient")
        flush("health_fail")
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3
    retriever._fetch_remote_abstracts = lambda ids: {}
    t0 = time.perf_counter()
    retriever._load()
    meta["load_s"] = round(time.perf_counter() - t0, 2)
    try:
        qv = encode_splade("warm up query for sparse encoder", retriever.splade_model_path)
        health["splade_model_path"] = retriever.splade_model_path
        health["splade_terms"] = len(qv or {})
        if not qv:
            bad("encode_splade returned empty")
    except Exception as exc:
        bad(f"encode_splade raised {exc!r}")
    try:
        ce = _get_cross_encoder()
        health["cross_encoder"] = type(ce).__name__ if ce is not None else None
        if ce is None:
            bad("cross-encoder not loaded")
    except Exception as exc:
        bad(f"cross-encoder load raised {exc!r}")
    try:
        from lib.embedding import _load_model
        em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
        health["embedding_model"] = type(em).__name__ if em is not None else None
        if em is None:
            bad("embedding model not loaded")
    except Exception as exc:
        bad(f"embedding model load raised {exc!r}")
    try:
        backend = retriever._seismic_backend()
        health["backend_class"] = type(backend).__name__
        health["n_shards"] = len(getattr(backend, "shards", []) or [])
        health["seismic_manifest"] = getattr(retriever, "_seismic_manifest", None)
        if backend is None:
            bad("seismic backend is None")
    except Exception as exc:
        bad(f"seismic backend load raised {exc!r}")
    delta = retriever._delta
    if args.arm.startswith("gate_off"):
        if delta is not None:
            bad("delta layer loaded in a gate-off arm")
    else:
        if delta is None:
            bad("delta layer not loaded in the empty_root arm")
        else:
            health["delta_layer"] = {
                "root": str(delta.root), "stamp": delta.stamp, "generations": len(delta.generations),
                "deleted": len(delta.deleted), "superseded": len(delta.superseded),
                "shard_manifest": delta.shard_manifest_path(), "buffer_size": delta.buffer_size(),
                "section_dirs": [s[0] for s in delta.section_dirs()],
                "livedocs": getattr(delta, "livedocs", None) is not None}
            dl = health["delta_layer"]
            if (dl["generations"] or dl["deleted"] or dl["superseded"] or dl["buffer_size"]
                    or dl["shard_manifest"] or dl["section_dirs"]):
                bad(f"empty-root delta layer is not empty: {dl}")
    try:
        import torch
        meta["torch_device"] = "cuda" if torch.cuda.is_available() else "cpu"
        meta["torch_threads"] = torch.get_num_threads()
    except Exception:
        meta["torch_device"] = "unknown"
    health["warnings_at_load"] = list(cap.records)
    if any(any(s in w for s in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    if not health["ok"]:
        flush("health_fail")
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3
    meta["health_ok_utc"] = utc()
    flush("running")
    print(f"[{args.arm}] HEALTH OK {json.dumps({k: v for k, v in health.items() if k != 'warnings_at_load'})}",
          flush=True)

    items = load_topics(args.limit_topics)
    pass_meta = []
    meta["passes"] = pass_meta
    stopped = None
    with rows_path.open("a") as fh:
        for p in range(args.passes):
            tp = time.time()
            pm = {"pass": p + 1, "start_utc": utc(), "n_rows": 0, "wall_s": None}
            pass_meta.append(pm)
            for i, (key, q) in enumerate(items):
                if deadline and time.time() >= deadline:
                    stopped = f"deadline reached at pass {p + 1} topic {i + 1}"
                    break
                n_warn = len(cap.records)
                t = time.perf_counter()
                fused = retriever.search_rrf(q, top_k=TOP_K)
                t1 = time.perf_counter()
                final = tools._maybe_rerank(copy.deepcopy(fused), q, LIMIT) if fused else []
                t2 = time.perf_counter()
                warns = cap.records[n_warn:]
                row = {"pass": p + 1, "topic": key, "query": q, "fused": dump(fused),
                       "fused_top10": dump(fused[:LIMIT]), "final": dump(final),
                       "fused_ids": [d.get("openalex_id") for d in fused],
                       "final_ids": [d.get("openalex_id") for d in final],
                       "rrf_ms": round((t1 - t) * 1000, 1), "rerank_ms": round((t2 - t1) * 1000, 1),
                       "warnings": warns[:5],
                       "degraded": any(any(s in w for s in SIGNATURES) for w in warns)}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                pm["n_rows"] = i + 1
                pm["wall_s"] = round(time.time() - tp, 1)
                print(f"[{args.arm} p{p + 1} {i + 1}/{len(items)}] rrf={row['rrf_ms']:.0f}ms "
                      f"rerank={row['rerank_ms']:.0f}ms n={len(fused)}{' DEGRADED' if row['degraded'] else ''}",
                      flush=True)
                if (i + 1) % 10 == 0:
                    flush("running")
            pm["end_utc"] = utc()
            if stopped:
                break
    meta["stopped"] = stopped
    meta["host_end"] = mem_state()
    flush("partial" if stopped else "complete")
    return 0


def snapshot(commit: str, scratch: Path) -> Path:
    snap = scratch / f"code_{commit[:8]}"
    if not (snap / "src").exists():
        snap.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {commit} src | tar -x -C {snap}", shell=True)
        for name in ("models", "data", ".env"):
            if not (snap / name).exists():
                (snap / name).symlink_to(REPO / name)
    harness = snap / "scripts" / "experiments"
    harness.mkdir(parents=True, exist_ok=True)
    for name in (Path(__file__).name, "eval_delta_ingest_m1_gate_off_parity.py"):
        (harness / name).write_bytes((Path(__file__).resolve().parent / name).read_bytes())
    return snap


def model_checksums(env: dict) -> dict:
    out = {}
    for key, default in (("SFU_SPLADE_MODEL_PATH", REPO / "models" / "splade_onnx_fused"),
                         ("SFU_CE_MODEL_PATH", REPO / "models" / "sfu-cross-encoder-v1"),
                         ("SFU_EMBEDDING_MODEL_PATH", REPO / "models" / "sfu-academic-embed-v5")):
        d = Path(env.get(key) or default)
        files = {}
        for f in sorted(d.glob("*.onnx")) + sorted(d.glob("*.safetensors")) + sorted(d.glob("tokenizer.json")):
            for _ in range(20):
                try:
                    files[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
                    break
                except OSError as exc:
                    files[f.name] = f"unreadable: {exc!r}"
                    time.sleep(1)
        out[key] = {"dir": str(d), "from_env": bool(env.get(key)), "sha256": files}
    return out


def dir_listing(p: Path) -> list[str]:
    return sorted(str(x.relative_to(p)) for x in p.rglob("*")) if p.exists() else ["<missing>"]


def run_arm(arm: str, args, snap: Path, env: dict, scratch: Path, deadline: float | None, rec: dict):
    cpus = dict(x.split("=") for x in args.cpus.split(",")).get(arm.split("#")[0], "0-7") if args.cpus else None
    log = scratch / f"{arm}.log"
    lock = [] if args.no_lock else ["flock", "-s", LOCK] if args.lock_shared else ["flock", LOCK]
    cmd = lock + ["nice", "-n", "10"] + (["taskset", "-c", cpus] if cpus else []) + [
        args.python or sys.executable, str(snap / "scripts" / "experiments" / Path(__file__).name),
        "child", "--arm", arm, "--passes", str(args.passes), "--scratch", str(scratch),
        "--limit-topics", str(args.limit_topics), "--src", str(snap / "src")] + (
        ["--deadline", args.deadline] if args.deadline else [])
    attempts = []
    rc = None
    for attempt in range(args.retries + 1):
        launched = utc()
        with open(log, "w") as fh:
            proc = subprocess.Popen(cmd, env=env, cwd=str(snap), stdout=fh, stderr=subprocess.STDOUT)
            try:
                rc = proc.wait(timeout=max(1, deadline + 90 - time.time()) if deadline else None)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                rc = "killed_after_deadline"
        text = log.read_text(errors="replace")
        early = rc != 0 and f"[{arm} p1 1/" not in text and (
            "Cannot allocate memory" in text or "Errno 12" in text)
        attempts.append({"launched_utc": launched, "ended_utc": utc(), "rc": rc, "o12_early_enomem": early})
        if early:
            (scratch / f"{arm}.attempt{attempt + 1}.log").write_text(text)
        if not early or (deadline and time.time() >= deadline):
            break
        time.sleep(20)
    rec[arm] = {"cmd": cmd, "cpus": cpus, "rc": rc, "attempts": attempts, "log": str(log)}


def drive(args) -> int:
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    empty_root = scratch / "empty_root_dir"
    if empty_root.exists():
        for x in sorted(empty_root.rglob("*"), reverse=True):
            x.rmdir() if x.is_dir() else x.unlink()
        empty_root.rmdir()
    empty_root.mkdir()
    commit = args.commit or git_commit()
    snap = snapshot(commit, scratch)
    deadline = parse_utc(args.deadline) if args.deadline else None
    arms = args.arms.split(",")
    base_env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
    base_env.update({k: "" for k in ENV_BLANK})
    base_env["PYTHONPATH"] = ""
    base_env.setdefault("OMP_NUM_THREADS", "4")
    drive_rec = {"commit": commit, "snapshot": str(snap), "start_utc": utc(), "python": args.python or sys.executable,
                 "parallel": args.parallel, "lock": "NONE (--no-lock)" if args.no_lock else ("flock -s " if args.lock_shared else "flock ") + LOCK,
                 "model_files": model_checksums(base_env),
                 "dirty_src_at_launch_not_measured": subprocess.check_output(
                     ["git", "-C", str(REPO), "status", "--short", "src"], text=True).splitlines(),
                 "empty_root": {"path": str(empty_root), "listing_before": dir_listing(empty_root)},
                 "arms": {}}
    (scratch / "drive.json").write_text(json.dumps(drive_rec, indent=1) + "\n")
    envs = {}
    for arm in arms:
        env = dict(base_env)
        if arm.startswith("empty_root"):
            env["SFU_DELTA_ROOT"] = str(empty_root)
        envs[arm] = env
    if args.parallel:
        threads = [threading.Thread(target=run_arm, args=(a, args, snap, envs[a], scratch, deadline,
                                                          drive_rec["arms"])) for a in arms]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        for a in arms:
            run_arm(a, args, snap, envs[a], scratch, deadline, drive_rec["arms"])
    drive_rec["empty_root"]["listing_after"] = dir_listing(empty_root)
    drive_rec["end_utc"] = utc()
    (scratch / "drive.json").write_text(json.dumps(drive_rec, indent=1) + "\n")
    print(json.dumps({a: {"rc": r["rc"], "attempts": len(r["attempts"])} for a, r in drive_rec["arms"].items()}))
    return 0


def load_arm(scratch: Path, arm: str) -> dict | None:
    mp = scratch / f"{arm}.meta.json"
    if not mp.exists():
        return None
    meta = json.loads(mp.read_text())
    passes: dict[int, list] = {}
    rp = scratch / f"{arm}.rows.jsonl"
    if rp.exists():
        for ln in rp.read_text().splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            passes.setdefault(r["pass"], []).append(r)
    meta["rows_by_pass"] = passes
    return meta


def summarize(args) -> int:
    from eval_delta_ingest_m1_gate_off_parity import compare
    scratch = Path(args.scratch)
    drive_rec = json.loads((scratch / "drive.json").read_text())
    arms = {a: load_arm(scratch, a) for a in args.arms.split(",")}
    n_topics = len(load_topics(args.limit_topics))

    def rows(arm, p):
        return (arms.get(arm) or {}).get("rows_by_pass", {}).get(p, [])

    def brief(c):
        return {k: v for k, v in c.items() if k != "differing_topics"} | {
            "differing_topics": [d["topic"] for d in c["differing_topics"]],
            "first_differing": c["differing_topics"][0] if c["differing_topics"] else None}

    health = {a: (m or {}).get("health", {"ok": None, "problems": ["no meta (never started)"]}) for a, m in arms.items()}
    pairs = {}
    for p in (1, 2):
        if rows("gate_off", p) and rows("empty_root", p):
            pairs[f"pass{p}"] = compare(rows("gate_off", p), rows("empty_root", p))
    self_id = {}
    for a in arms:
        if rows(a, 1) and rows(a, 2):
            self_id[a] = compare(rows(a, 1), rows(a, 2))
    degraded = {a: sum(r.get("degraded", False) for p in (1, 2) for r in rows(a, p)) for a in arms}
    cross = None
    if REF_ROWS.exists() and rows("gate_off", 1):
        ref = json.loads(REF_ROWS.read_text())["passes"][0]["rows"]
        cross = compare(ref, rows("gate_off", 1))

    healthy = all(h.get("ok") for h in health.values()) and not any(degraded.values())
    ident = {k: (c["fused_identical"] == c["n"] and c["final_identical"] == c["n"]) for k, c in pairs.items()}
    ident_top10 = {k: (c["fused_top10_identical"] == c["n"] and c["final_identical"] == c["n"]) for k, c in pairs.items()}
    n1 = pairs.get("pass1", {}).get("n", 0)
    n2 = pairs.get("pass2", {}).get("n", 0)
    if not healthy:
        verdict = "INVALID (a process failed health or produced degraded rows; see health/degraded_rows)"
    elif not all(ident_top10.values()):
        verdict = "FAIL"
    elif n1 == n_topics and n2 == n_topics:
        verdict = f"PASS ({n_topics} topics x 2 passes, byte-identical)"
    elif n1 == n_topics:
        verdict = (f"PARTIAL: pass 1 {n_topics}/{n_topics} byte-identical; pass 2 {n2}/{n_topics} topics "
                   f"compared, all identical (deadline)")
    else:
        verdict = f"INCOMPLETE: pass 1 only {n1}/{n_topics} topics compared (all identical so far); bar not decided"

    def strip(m):
        if m is None:
            return None
        r = {k: v for k, v in m.items() if k != "rows_by_pass"}
        r["rows_per_pass"] = {p: len(v) for p, v in m["rows_by_pass"].items()}
        for p, v in m["rows_by_pass"].items():
            r[f"pass{p}_rrf_ms_p50_INVALID"] = sorted(x["rrf_ms"] for x in v)[len(v) // 2] if v else None
        return r

    out = {
        "what": "Delta-ingest M1 rerun: gate-off parity, 2 passes per arm, on current code",
        "bar_preregistered": ("03_SPIKE_PLAN.md M1 (frozen 2026-09-29): fused + final top-10, 120 topics, "
                              "SFU_DELTA_ROOT unset vs set with an EMPTY delta root -> byte-identical 120/120; "
                              "fixed inputs: 2 passes"),
        "verdict": verdict,
        "verdict_basis": ("identity of full fused list (50) and final top-10 per topic (json.dumps sort_keys, "
                          "every field incl. scores) per pass; fused top-10 also reported. Health of every "
                          "process asserted before measuring; rows with a failure-signature warning flagged."),
        "date": DATE, "git_commit_measured": drive_rec["commit"],
        "script": "scripts/experiments/eval_delta_ingest_m1_2pass.py",
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n_topics,
        "timings_valid": False,
        "timings_note": ("INVALID: arms ran concurrently (cores 0-3 / 4-7) under a SHARED latency lock while "
                         "Agent B built SEISMIC shards on cores 8-15; latency fields are not measurements"),
        "reference_arm": "gate_off (SFU_DELTA_ROOT absent) at the same commit and same snapshot as empty_root",
        "pairs_gate_off_vs_empty_root": {k: brief(v) for k, v in pairs.items()},
        "pass_to_pass_self_identity": {k: brief(v) for k, v in self_id.items()},
        "full_fused_list_and_final_identical_per_pass": ident,
        "fused_top10_and_final_identical_per_pass": ident_top10,
        "health": health, "degraded_rows": degraded,
        "log_scan": {a: {s: (scratch / f"{a}.log").read_text(errors="replace").count(s) for s in SIGNATURES}
                     if (scratch / f"{a}.log").exists() else None for a in arms},
        "cross_commit_informational_vs_aa0fc405_gate_off_pass1": brief(cross) if cross else None,
        "cross_commit_note": ("NOT part of the bar: stored gate_off rows from 2026-09-29 (code aa0fc405, shards "
                              "served from the /var/tmp/seismic_stage copy) vs today's gate_off pass 1 (code "
                              f"{drive_rec['commit'][:8]}, shards served from data/seismic_150m with the stage "
                              "dir empty)"),
        "drive": drive_rec,
        "arms": {a: strip(m) for a, m in arms.items()},
        "scratch": str(scratch),
        "notes": args.note,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": verdict,
                      "pairs": {k: {kk: vv for kk, vv in v.items() if kk != "differing_topics"} for k, v in pairs.items()},
                      "self": {k: {kk: vv for kk, vv in v.items() if kk != "differing_topics"} for k, v in self_id.items()},
                      "cross": {kk: vv for kk, vv in cross.items() if kk != "differing_topics"} if cross else None,
                      "degraded": degraded,
                      "health_ok": {a: h.get("ok") for a, h in health.items()}}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drive")
    d.add_argument("--passes", type=int, default=2)
    d.add_argument("--arms", default="gate_off,empty_root")
    d.add_argument("--limit-topics", type=int, default=0)
    d.add_argument("--scratch", default=str(SCRATCH))
    d.add_argument("--commit", default="")
    d.add_argument("--deadline", default="")
    d.add_argument("--python", default="")
    d.add_argument("--parallel", action="store_true")
    d.add_argument("--lock-shared", action="store_true")
    d.add_argument("--cpus", default="")
    d.add_argument("--no-lock", action="store_true")
    d.add_argument("--retries", type=int, default=3)
    c = sub.add_parser("child")
    c.add_argument("--arm", required=True)
    c.add_argument("--passes", type=int, default=2)
    c.add_argument("--scratch", required=True)
    c.add_argument("--limit-topics", type=int, default=0)
    c.add_argument("--src", required=True)
    c.add_argument("--deadline", default="")
    s = sub.add_parser("summarize")
    s.add_argument("--scratch", default=str(SCRATCH))
    s.add_argument("--arms", default="gate_off,empty_root")
    s.add_argument("--limit-topics", type=int, default=0)
    s.add_argument("--out", default=str(OUT))
    s.add_argument("--note", action="append", default=[])
    args = ap.parse_args()
    return {"drive": drive, "child": child, "summarize": summarize}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
