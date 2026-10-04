#!/usr/bin/env python3
"""Delta-ingest M9 follow-up (2026-10-01): SEISMIC build-vs-build drift baseline.

M9 (scripts/experiments/eval_delta_ingest_twin_rebuild.py, 2026-09-29) rebuilt
served shard 0 from its f16 twin and FAILED its parity bar: overlap@10
rebuilt-vs-served 0.9858 (120 topics) / 0.9870 (100 diverse) vs 0.99. Question:
is that gap SEISMIC build non-determinism? Answer it by building the SAME jsonl
(/var/tmp/sfu_delta_D_20260929/twin_shard0.jsonl) a second time with the same
parameters and measuring overlap@10 rebuilt-vs-rebuilt on the same queries.

PRE-REGISTRATION (written 2026-10-01 before any build or comparison ran;
full text in spike/delta_ingest/TWIN_DRIFT_BASELINE_FINDINGS.md):
  build 1        : M9's existing stock index
                   /var/tmp/sfu_delta_D_20260929/rebuilt_shard0.index.seismic
                   (+ its c1a mmap dir and dv-v2 dir), NOT rebuilt.
  build 2        : SeismicIndex.build(same jsonl, num_threads=8, M9 SEISMIC_PARAMS),
                   saved to /home/vscode/work/delta_ingest/twin_drift/rebuilt2_shard0.
  queries        : M9's two sets (120 topics, first 100 distinct diverse
                   paraphrases), encode_splade(q, "models/splade_onnx_fp16"),
                   top-64 terms by weight, encoded ONCE (subcommand `encode`) and
                   reused by every arm, so both sides see bit-identical queries.
  search         : k=200, query_cut=len(terms), heap_factor=0.8,
                   SFU_SEISMIC_PREFLOOR=2 (M9's params).
  primary metric : overlap@10 build2-vs-build1 on the stock f16 SeismicIndex
                   (in-memory) per query, mean / min / distribution, per set.
                   DEVIATION from M9 (stated before the run): M9 compared the
                   dv-v2 MmapSeismicIndex outputs; the stock level isolates the
                   build itself and saves c1a+dotvbyte (~10 min). The M9-exact
                   dv-v2 comparison runs afterwards only if time remains
                   (subcommand `dvparity`).
  control        : build 1 queried twice in one process (search-path noise floor).
  decision rule  : let m = min over the two sets of mean overlap@10 build2-vs-build1.
                   m >= 0.998 and identical top-10 on >= 99% of queries -> builds are
                     reproducible: M9's gap is NOT build noise (REAL fidelity loss of
                     the twin route as run).
                   m <= 0.9915 (i.e. within ~0.005 of M9's 0.9858/0.9870, or lower)
                     -> M9's gap is build noise; the 0.99 bar needs a noise-aware
                     restatement (recommended, not changed here).
                   0.9915 < m < 0.998 -> MIXED: part noise, part real loss;
                     report both numbers.
  arm choice     : FULL (whole shard, 18,799,322 docs) iff the shared latency lock
                   is acquired (or abandoned at 06:15Z) by 05:50Z; otherwise
                   PREFIX: the first --prefix-docs (default 3,000,000) jsonl lines
                   built TWICE with the same params and compared to each other,
                   verdict marked PARTIAL (N docs). Hard stop 06:40Z.
  timings        : INVALID by construction (Agent C's index-loading parity eval
                   runs on cores 0-7 concurrently; this run is pinned to 8-15).
"""
from __future__ import annotations

import argparse
import calendar
import fcntl
import hashlib
import json
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_delta_ingest_twin_rebuild import C1A_BIN, DOTVBYTE_BIN, REPO, SEISMIC_PARAMS, jnow, load_token_to_id, twin_dir  # noqa: E402

PY = Path("/home/vscode/work/venv_local/bin/python3")

E = os.environ.get
M9WORK = Path("/var/tmp/sfu_delta_D_20260929")
JSONL = Path(E("SFU_DRIFT_JSONL", str(M9WORK / "twin_shard0.jsonl")))
B1_STOCK = Path(E("SFU_DRIFT_B1_STOCK", str(M9WORK / "rebuilt_shard0.index.seismic")))
B1_MMAP = Path(E("SFU_DRIFT_B1_MMAP", str(M9WORK / "rebuilt_shard0.mmap")))
B1_DV = Path(E("SFU_DRIFT_B1_DV", str(M9WORK / "rebuilt_shard0.dotvbyte.v2.mmap")))
TWIN = Path(E("SFU_DRIFT_TWIN", str(twin_dir(0))))
WORK = Path(E("SFU_DRIFT_WORK", "/home/vscode/work/delta_ingest/twin_drift"))
RESULT = Path(E("SFU_DRIFT_RESULT", str(REPO / "data/eval_results/delta_ingest_twin_drift_baseline_20261001.json")))
LOCK = E("SFU_DRIFT_LOCK", "/tmp/sfu_latency_measure.lock")
NOT_BEFORE = E("SFU_DRIFT_NOT_BEFORE", "2026-10-01T04:35:00Z")
LOCK_GIVEUP = E("SFU_DRIFT_LOCK_GIVEUP", "2026-10-01T06:15:00Z")
LOCK_MODE = E("SFU_DRIFT_LOCK_MODE", "shared")
RUN_DATE = E("SFU_DRIFT_DATE", "2026-10-01")
TIMINGS_NOTE = E("SFU_DRIFT_TIMINGS_NOTE", "INVALID: Agent C's index-loading parity eval ran concurrently on cores 0-7; "
                 "this run pinned to cores 8-15 at nice 10")
SERVED = Path(E("SFU_DRIFT_SERVED", str(REPO / "data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap")))
ABORT_SWAP_GB = 2.0
ABORT_MEMAVAIL_GB = 6.0
ABORT: dict = {}
FULL_CUTOFF = E("SFU_DRIFT_FULL_CUTOFF", "2026-10-01T05:50:00Z")
DEADLINE = E("SFU_DRIFT_DEADLINE", "2026-10-01T06:40:00Z")
SEARCH = dict(k=200, heap_factor=0.8)


def ts(s: str) -> float:
    return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))


def log(msg: str):
    print(f"{jnow()} {msg}", flush=True)


def cmd_encode(a):
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO / "scripts/seismic_testbed"))
    os.chdir(REPO)
    from e6_forward_codec_proto import load_queries
    from lib.opensearch_retriever import encode_splade
    sets = {"topics120": [r["query"] for r in json.loads((REPO / "data/sfu_eval_queries.json").read_text())],
            "diverse100": load_queries(100, REPO / "data/eval_results/diverse_queries.json")}
    assert len(sets["topics120"]) == 120 and len(sets["diverse100"]) == 100
    enc = {}
    for name, qs in sets.items():
        rows = []
        for q in qs:
            d = dict(sorted(encode_splade(q, "models/splade_onnx_fp16").items(), key=lambda x: -x[1])[:64])
            rows.append([[t, float(np.float32(v))] for t, v in d.items()])
        enc[name] = rows
    nterms = [len(r) for rs in enc.values() for r in rs]
    assert min(nterms) > 0, "SPLADE produced an empty query: model not loaded"
    out = {"created_utc": jnow(), "model": "models/splade_onnx_fp16", "top_terms": 64, "texts": sets,
           "encoded": enc, "n_terms_min": min(nterms), "n_terms_max": max(nterms)}
    blob = json.dumps(out, sort_keys=True)
    out["sha256"] = hashlib.sha256(json.dumps(enc, sort_keys=True).encode()).hexdigest()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "queries.json").write_text(json.dumps(out, indent=0))
    print(json.dumps({k: out[k] for k in ("created_utc", "n_terms_min", "n_terms_max", "sha256")}), len(blob))


def load_enc():
    return json.loads((WORK / "queries.json").read_text())["encoded"]


def run_queries(idx, enc) -> dict:
    import seismic
    sd = seismic.get_seismic_string()
    res = {}
    for name, qs in enc.items():
        out = []
        for terms in qs:
            r = idx.search(query_id="q", query_components=np.array([t for t, _ in terms], dtype=sd),
                           query_values=np.array([v for _, v in terms], dtype=np.float32),
                           query_cut=len(terms), **SEARCH)
            out.append([[d, float(s)] for (_q, s, d) in r])
        res[name] = out
    return res


def cmd_child_build(a):
    import seismic
    enc = load_enc()
    info = {"jsonl": a.jsonl, "threads": a.threads, "params": SEISMIC_PARAMS, "start_utc": jnow(),
            "token_map": a.token_map or "none (ids assigned by the build)"}
    kw = {}
    if a.token_map == "twin":
        kw["input_token_to_id_map"] = {k: int(v) for k, v in load_token_to_id(TWIN).items()}
    t0 = time.perf_counter()
    idx = seismic.SeismicIndex.build(a.jsonl, num_threads=a.threads, **SEISMIC_PARAMS, **kw)
    info.update(docs=int(idx.len), dim=int(idx.dim), nnz=int(idx.nnz), build_seconds=round(time.perf_counter() - t0, 1))
    if a.stem:
        t1 = time.perf_counter()
        idx.save(a.stem)
        info["save_seconds"] = round(time.perf_counter() - t1, 1)
        info["stock_path"] = f"{a.stem}.index.seismic"
    t2 = time.perf_counter()
    info["results"] = [run_queries(idx, enc)]
    info["query_seconds"] = round(time.perf_counter() - t2, 1)
    info["ru_maxrss_gb_self"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    info["finished_utc"] = jnow()
    Path(a.out).write_text(json.dumps(info))
    log(f"child-build done docs={info['docs']} build={info['build_seconds']}s")


def cmd_child_load(a):
    import seismic
    enc = load_enc()
    info = {"stock_path": a.stock, "start_utc": jnow()}
    t0 = time.perf_counter()
    idx = seismic.SeismicIndex.load(a.stock)
    info.update(docs=int(idx.len), dim=int(idx.dim), nnz=int(idx.nnz), load_seconds=round(time.perf_counter() - t0, 1))
    info["results"] = []
    for _ in range(a.reps):
        info["results"].append(run_queries(idx, enc))
    info["ru_maxrss_gb_self"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    info["finished_utc"] = jnow()
    Path(a.out).write_text(json.dumps(info))
    log(f"child-load done docs={info['docs']}")


def cmd_child_mmap(a):
    import seismic
    enc = load_enc()
    info = {"mmap_dir": a.stock, "start_utc": jnow()}
    idx = seismic.MmapSeismicIndex(a.stock)
    info.update(forward_format=idx.forward_format, docs=int(idx.len), nnz=int(idx.nnz))
    info["results"] = [run_queries(idx, enc)]
    info["finished_utc"] = jnow()
    Path(a.out).write_text(json.dumps(info))
    log(f"child-mmap done {a.stock}")


def _memavail_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1048576
    return float("inf")


def _poll(proc, box, stop):
    p = Path(f"/proc/{proc.pid}/status")
    while not stop.is_set():
        try:
            for line in p.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    box["rss_gb"] = max(box["rss_gb"], int(line.split()[1]) / 1048576)
                elif line.startswith("VmSwap:"):
                    box["swap_gb"] = max(box["swap_gb"], int(line.split()[1]) / 1048576)
        except OSError:
            pass
        ma = _memavail_gb()
        box["min_memavail_gb"] = min(box["min_memavail_gb"], ma)
        reason = None
        if box["swap_gb"] > ABORT_SWAP_GB:
            reason = f"child VmSwap {box['swap_gb']:.2f} GB > {ABORT_SWAP_GB} GB"
        elif ma < ABORT_MEMAVAIL_GB:
            reason = f"host MemAvailable {ma:.2f} GB < {ABORT_MEMAVAIL_GB} GB"
        if reason and not ABORT:
            ABORT.update(reason=reason, at_utc=jnow(), argv=box["argv"])
            log(f"ABORT: {reason}")
            proc.kill()
        stop.wait(2)


def spawn_raw(cmd: list[str], deadline: float, env: dict, capture: bool = False) -> tuple[dict, str]:
    if ABORT:
        return {"argv": cmd, "rc": "SKIPPED_AFTER_ABORT"}, ""
    t0 = time.time()
    p = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE if capture else None, text=True)
    box, stop = {"rss_gb": 0.0, "swap_gb": 0.0, "min_memavail_gb": float("inf"), "argv": cmd}, threading.Event()
    threading.Thread(target=_poll, args=(p, box, stop), daemon=True).start()
    err = ""
    try:
        if capture:
            _, err = p.communicate(timeout=max(1.0, deadline - time.time()))
            rc = p.returncode
        else:
            rc = p.wait(timeout=max(1.0, deadline - time.time()))
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        rc = "KILLED_AT_DEADLINE"
    stop.set()
    if ABORT and ABORT.get("argv") == cmd:
        rc = f"ABORTED ({ABORT['reason']})"
    return {"argv": cmd, "rc": rc, "wall_seconds": round(time.time() - t0, 1),
            "peak_vmrss_gb_poll": round(box["rss_gb"], 3), "peak_vmswap_gb_poll": round(box["swap_gb"], 3),
            "min_host_memavail_gb_poll": round(box["min_memavail_gb"], 3)}, err or ""


def spawn(argv: list[str], deadline: float) -> dict:
    env = dict(os.environ, RAYON_NUM_THREADS="8", OMP_NUM_THREADS="1", SFU_SEISMIC_PREFLOOR="2",
               SFU_SEISMIC_STAGE_DIR="")
    out, _ = spawn_raw([str(PY), __file__] + argv, deadline, env)
    out["argv"] = argv
    return out


def overlap_stats(xs: dict, ys: dict) -> dict:
    out = {}
    for name in xs:
        ov, ov200, ident_o, ident_s, maxdiff = [], [], 0, 0, 0.0
        for x, y in zip(xs[name], ys[name]):
            a10, b10 = [d for d, _ in x[:10]], [d for d, _ in y[:10]]
            ov.append(len(set(a10) & set(b10)) / 10)
            ov200.append(len({d for d, _ in x} & {d for d, _ in y}) / max(1, len(y)))
            ident_o += a10 == b10
            ident_s += set(a10) == set(b10)
            if [d for d, _ in x] == [d for d, _ in y]:
                maxdiff = max([maxdiff] + [abs(s - t) for (_, s), (_, t) in zip(x, y)])
        hist = {f"{v:.1f}": sum(1 for o in ov if abs(o - v) < 1e-9) for v in np.arange(0, 1.01, 0.1) if
                any(abs(o - v) < 1e-9 for o in ov)}
        out[name] = {"n": len(ov), "overlap10_mean": round(float(np.mean(ov)), 4), "overlap10_min": min(ov),
                     "overlap10_hist": hist, "identical_top10_ordered": ident_o, "identical_top10_set": ident_s,
                     "identical_top200_ordered": sum(1 for x, y in zip(xs[name], ys[name])
                                                     if [d for d, _ in x] == [d for d, _ in y]),
                     "overlap200_mean": round(float(np.mean(ov200)), 4),
                     "max_abs_score_diff_on_identical_top200": maxdiff,
                     "per_query_overlap10": ov}
    return out


def verdict(stats: dict, partial_n: int | None) -> str:
    m = min(s["overlap10_mean"] for s in stats.values())
    ident = sum(s["identical_top10_set"] for s in stats.values()) / sum(s["n"] for s in stats.values())
    if m >= 0.998 and ident >= 0.99:
        v = "REPRODUCIBLE (M9 gap is NOT build noise: real fidelity loss of the twin route as run)"
    elif m <= 0.9915:
        v = "NOISE (build-vs-build drift explains M9's gap)"
    else:
        v = "MIXED"
    return v + (f" — PARTIAL (prefix {partial_n} docs)" if partial_n else "")


def file_cmp(a: Path, b: Path) -> dict:
    if not (a.exists() and b.exists()):
        return {"a": str(a), "b": str(b), "result": "missing"}
    p = subprocess.run(["cmp", str(a), str(b)], capture_output=True, text=True)
    return {"a": str(a), "b": str(b), "a_bytes": a.stat().st_size, "b_bytes": b.stat().st_size,
            "identical": p.returncode == 0, "cmp_out": (p.stdout + p.stderr).strip()[:300]}


def acquire_lock(rec: dict):
    while time.time() < ts(NOT_BEFORE):
        time.sleep(10)
    fh = open(LOCK, "a+")
    t0 = time.time()
    rec["lock"] = {"wait_start_utc": jnow()}
    flag = fcntl.LOCK_EX if LOCK_MODE == "exclusive" else fcntl.LOCK_SH
    while True:
        try:
            fcntl.flock(fh, flag | fcntl.LOCK_NB)
            rec["lock"].update(mode=LOCK_MODE, acquired_utc=jnow(), waited_seconds=round(time.time() - t0),
                               host_memavail_gb_at_acquire=round(_memavail_gb(), 2))
            return fh
        except BlockingIOError:
            if time.time() >= ts(LOCK_GIVEUP):
                rec["lock"].update(mode="NOT ACQUIRED (exclusive holder overran 06:15Z; ran anyway under nice/taskset)",
                                   acquired_utc=None, gave_up_utc=jnow())
                return fh
            time.sleep(15)


def cmd_run(a):
    WORK.mkdir(parents=True, exist_ok=True)
    rec = {"item": "delta-ingest M9 follow-up: twin-rebuild build-vs-build drift baseline", "date": RUN_DATE,
           "script": "scripts/experiments/eval_delta_ingest_twin_drift_baseline.py",
           "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                      text=True).stdout.strip(),
           "queries_sha256": json.loads((WORK / "queries.json").read_text())["sha256"],
           "params": SEISMIC_PARAMS, "threads": 8, "search": dict(SEARCH, query_cut="len(terms)", query_terms=64),
           "timings_valid": False,
           "timings_note": TIMINGS_NOTE, "abort_rule": {"child_vmswap_gb_gt": ABORT_SWAP_GB,
                                                         "host_memavail_gb_lt": ABORT_MEMAVAIL_GB},
           "m9_reference": {"topics120_overlap10_mean": 0.9858, "diverse100_overlap10_mean": 0.987}}
    fh = acquire_lock(rec)
    deadline = ts(DEADLINE)
    rec["arm"] = "FULL" if time.time() <= ts(FULL_CUTOFF) else "PREFIX"
    log(f"arm={rec['arm']} lock={rec['lock']}")
    (WORK / "run_state.json").write_text(json.dumps(rec, indent=1))
    if rec["arm"] == "FULL":
        stem = WORK / "rebuilt2_shard0"
        q2 = WORK / "q_build2_stock.json"
        rec["build2"] = spawn(["child-build", "--jsonl", str(JSONL), "--stem", str(stem), "--threads", "8",
                               "--out", str(q2)], deadline)
        q1 = WORK / "q_build1_stock.json"
        rec["build1_load"] = spawn(["child-load", "--stock", str(B1_STOCK), "--reps", "2", "--out", str(q1)], deadline)
        if q2.exists() and q1.exists():
            r2, r1 = json.loads(q2.read_text()), json.loads(q1.read_text())
            rec["build2"]["child"] = {k: v for k, v in r2.items() if k != "results"}
            rec["build1_load"]["child"] = {k: v for k, v in r1.items() if k != "results"}
            rec["primary_stock_build2_vs_build1"] = overlap_stats(r2["results"][0], r1["results"][0])
            rec["control_build1_rep1_vs_rep2"] = overlap_stats(r1["results"][0], r1["results"][1])
            rec["verdict"] = verdict(rec["primary_stock_build2_vs_build1"], None)
            rec["stock_file_cmp"] = file_cmp(B1_STOCK, Path(f"{stem}.index.seismic"))
            save(rec)
            ot = WORK / "q_twin_f16_mmap.json"
            rec["twin_f16_query"] = spawn(["child-mmap", "--stock", str(TWIN), "--out", str(ot)], deadline)
            if ot.exists():
                rt = json.loads(ot.read_text())["results"][0]
                rec["link_build1_stock_vs_twin_f16"] = overlap_stats(r1["results"][0], rt)
                rec["link_build2_stock_vs_twin_f16"] = overlap_stats(r2["results"][0], rt)
            save(rec)
            if time.time() + 38 * 60 <= deadline:
                rec["armB_twin_token_map"] = arm_b(deadline)
                save(rec)
            else:
                rec["armB_twin_token_map"] = {"status": "NOT RUN (< 38 min left after arm A)", "at_utc": jnow()}
            save(rec)
            if time.time() + 15 * 60 <= deadline:
                rec["dvparity"] = dvparity(stem, deadline)
            else:
                rec["dvparity"] = {"status": "NOT RUN (< 15 min left)", "at_utc": jnow()}
            save(rec)
            rec["served_level"] = served_level(deadline)
        else:
            rec["verdict"] = "NOT RUN (full build or build-1 query did not finish by the deadline)"
    else:
        n = a.prefix_docs
        pj = WORK / f"prefix_{n}.jsonl"
        t0 = time.time()
        with open(pj, "wb") as w:
            subprocess.run(["head", "-n", str(n), str(JSONL)], stdout=w, check=True)
        rec["prefix"] = {"docs": n, "path": str(pj), "bytes": pj.stat().st_size, "head_seconds": round(time.time() - t0, 1)}
        outs = []
        for i in (1, 2):
            o = WORK / f"q_prefix_p{i}.json"
            rec[f"prefix_build{i}"] = spawn(["child-build", "--jsonl", str(pj), "--stem", str(WORK / f"prefix_p{i}"),
                                             "--threads", "8", "--out", str(o)], deadline)
            outs.append(o)
        if all(o.exists() for o in outs):
            r1, r2 = (json.loads(o.read_text()) for o in outs)
            rec["prefix_build1"]["child"] = {k: v for k, v in r1.items() if k != "results"}
            rec["prefix_build2"]["child"] = {k: v for k, v in r2.items() if k != "results"}
            rec["primary_prefix_build2_vs_build1"] = overlap_stats(r2["results"][0], r1["results"][0])
            rec["verdict"] = verdict(rec["primary_prefix_build2_vs_build1"], n)
            rec["stock_file_cmp"] = file_cmp(WORK / "prefix_p1.index.seismic", WORK / "prefix_p2.index.seismic")
            save(rec)
            per_build = max(r1["build_seconds"], r2["build_seconds"]) + 120
            if time.time() + 2 * per_build <= deadline:
                tb = []
                for i in (1, 2):
                    o = WORK / f"q_prefix_t{i}.json"
                    rec[f"prefix_twinmap_build{i}"] = spawn(["child-build", "--jsonl", str(pj), "--threads", "8",
                                                             "--token-map", "twin", "--out", str(o)], deadline)
                    tb.append(o)
                if all(o.exists() for o in tb):
                    t1, t2 = (json.loads(o.read_text())["results"][0] for o in tb)
                    rec["supp_prefix_twinmap_build2_vs_build1"] = overlap_stats(t2, t1)
            else:
                rec["supp_prefix_twinmap"] = "NOT RUN (time)"
        else:
            rec["verdict"] = "NOT RUN (prefix builds did not finish by the deadline)"
    if ABORT:
        rec["abort"] = dict(ABORT)
        rec["verdict_note"] = "run ABORTED by the swap/MemAvailable rule; later steps NOT RUN"
    rec["finished_utc"] = jnow()
    (WORK / "run_state.json").write_text(json.dumps(rec, indent=1))
    RESULT.write_text(json.dumps(rec, indent=1))
    fh.close()
    log(f"verdict={rec['verdict']}")


def save(rec: dict):
    (WORK / "run_state.json").write_text(json.dumps(rec, indent=1))
    RESULT.write_text(json.dumps(rec, indent=1))


def arm_b(deadline: float) -> dict:
    """Supplementary: rebuild with the twin's token_to_id_map (= the original served build's component ids;
    byte-identical to the served dv-v2 token_to_id_map.bin) and compare to the original build's f16 c1a dir
    (the twin), to the two unpinned rebuilds (stock level), and, after c1a + dotvbyte perdoc, to the
    SERVED dv-v2 shard (M9's level; see served_level)."""
    out = {"start_utc": jnow()}
    stemb = WORK / "rebuiltB_twinmap_shard0"
    ob, ot = WORK / "q_buildB_stock.json", WORK / "q_twin_f16_mmap.json"
    out["build"] = spawn(["child-build", "--jsonl", str(JSONL), "--stem", str(stemb), "--threads", "8",
                          "--token-map", "twin", "--out", str(ob)], deadline)
    if not ot.exists():
        out["twin_query"] = spawn(["child-mmap", "--stock", str(TWIN), "--out", str(ot)], deadline)
    if ob.exists() and ot.exists():
        rb, rt = json.loads(ob.read_text()), json.loads(ot.read_text())
        out["build"]["child"] = {k: v for k, v in rb.items() if k != "results"}
        out["overlap_buildB_stock_vs_twin_f16"] = overlap_stats(rb["results"][0], rt["results"][0])
        for nm in ("build1", "build2"):
            oq = WORK / f"q_{nm}_stock.json"
            if oq.exists():
                out[f"overlap_buildB_stock_vs_{nm}_stock"] = overlap_stats(
                    rb["results"][0], json.loads(oq.read_text())["results"][0])
    if Path(f"{stemb}.index.seismic").exists() and time.time() + 12 * 60 <= deadline:
        out["convert"] = convert(stemb, deadline)
        out["file_cmp_f16_mmap_vs_twin"] = {f: file_cmp(TWIN / f, Path(f"{stemb}.mmap") / f) for f in
                                            ("posting_lists.bin", "forward_offsets.bin", "forward_components.bin",
                                             "forward_values.bin", "token_to_id_map.bin",
                                             "document_mapping_strings.bin")}
    out["finished_utc"] = jnow()
    return out


def convert(stem: Path, deadline: float) -> dict:
    """c1a (stock -> f16 mmap dir) then convert_f16_to_dotvbyte --value-scale perdoc (-> dv-v2 dir), as M9 ran."""
    out = {}
    mm, dv = Path(f"{stem}.mmap"), Path(f"{stem}.dotvbyte.v2.mmap")
    for name, argv in (("c1a", [str(C1A_BIN), "--index-book", f"{stem}.index.seismic", "--mmap-dir", str(mm),
                                "--n-queries", "5"]),
                       ("dotvbyte", [str(DOTVBYTE_BIN), "--src-mmap-dir", str(mm), "--dst-mmap-dir", str(dv),
                                     "--value-scale", "perdoc", "--sanity-docs", "500"])):
        info, err = spawn_raw(argv, deadline, dict(os.environ, RAYON_NUM_THREADS="8"), capture=True)
        info["stderr_tail"] = err[-300:]
        out[name] = info
        if info["rc"] != 0:
            out["ok"] = False
            return out
    out["ok"] = True
    return out


def served_level(deadline: float) -> dict:
    """M9's level: MmapSeismicIndex on each dv-v2 dir vs the SERVED dv-v2 shard 0 (read-only)."""
    out = {"served": str(SERVED), "start_utc": jnow()}
    osv = WORK / "q_served_dv.json"
    if not osv.exists():
        out["run_served"] = spawn(["child-mmap", "--stock", str(SERVED), "--out", str(osv)], deadline)
    if not osv.exists():
        return out
    rs = json.loads(osv.read_text())["results"][0]
    cands = {"build1_dv_vs_served (M9 rerun, unpinned)": WORK / "q_build1_dv.json",
             "build2_dv_vs_served (unpinned)": WORK / "q_build2_dv.json",
             "twin_f16_vs_served (E8 level)": WORK / "q_twin_f16_mmap.json"}
    dvb = WORK / "rebuiltB_twinmap_shard0.dotvbyte.v2.mmap"
    obd = WORK / "q_buildB_dv.json"
    if dvb.exists() and not obd.exists():
        out["run_buildB_dv"] = spawn(["child-mmap", "--stock", str(dvb), "--out", str(obd)], deadline)
    cands["buildB_twinmap_dv_vs_served (pinned)"] = obd
    for k, f in cands.items():
        if f.exists():
            out[k] = overlap_stats(json.loads(f.read_text())["results"][0], rs)
    if obd.exists():
        rbd = json.loads(obd.read_text())["results"][0]
        for nm in ("build1", "build2"):
            f = WORK / f"q_{nm}_dv.json"
            if f.exists():
                out[f"buildB_dv_vs_{nm}_dv"] = overlap_stats(rbd, json.loads(f.read_text())["results"][0])
    out["finished_utc"] = jnow()
    return out


def dvparity(stem: Path, deadline: float) -> dict:
    """M9-exact comparison: c1a + dotvbyte perdoc on build 2, then MmapSeismicIndex dv-v2 of both builds."""
    out = {"start_utc": jnow()}
    mm, dv = Path(f"{stem}.mmap"), Path(f"{stem}.dotvbyte.v2.mmap")
    out["convert"] = convert(stem, deadline)
    if not out["convert"]["ok"]:
        return out
    out["file_cmp_f16_mmap"] = {f: file_cmp(B1_MMAP / f, mm / f) for f in
                                ("posting_lists.bin", "forward_offsets.bin", "forward_components.bin",
                                 "forward_values.bin", "token_to_id_map.bin", "document_mapping_strings.bin")}
    out["file_cmp_dv_v2"] = {f: file_cmp(B1_DV / f, dv / f) for f in
                             ("posting_lists.bin", "forward_data.bin", "forward_encoder.bin", "token_to_id_map.bin")}
    o1, o2 = WORK / "q_build1_dv.json", WORK / "q_build2_dv.json"
    out["run_b1"] = spawn(["child-mmap", "--stock", str(B1_DV), "--out", str(o1)], deadline)
    out["run_b2"] = spawn(["child-mmap", "--stock", str(dv), "--out", str(o2)], deadline)
    if o1.exists() and o2.exists():
        out["overlap_dv_v2_build2_vs_build1"] = overlap_stats(json.loads(o2.read_text())["results"][0],
                                                              json.loads(o1.read_text())["results"][0])
    out["finished_utc"] = jnow()
    return out


def cmd_finalize(a):
    """Recompute served_level from the saved query outputs into RESULT (used 2026-10-01 after the run
    was stopped before its own served_level save; see the findings file)."""
    rec = json.loads(RESULT.read_text())
    rec["served_level"] = served_level(time.time() + 600)
    rec["served_level"]["computed_by"] = "finalize (offline, from saved q_*.json query outputs)"
    rec["finished_utc"] = jnow()
    RESULT.write_text(json.dumps(rec, indent=1))
    print(json.dumps({k: {s: {x: y for x, y in v.items() if x != "per_query_overlap10"} for s, v in d.items()}
                      for k, d in rec["served_level"].items() if isinstance(d, dict) and "topics120" in d}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("encode", "run", "child-build", "child-load", "child-mmap", "finalize"):
        s = sub.add_parser(name)
        s.add_argument("--jsonl")
        s.add_argument("--stem")
        s.add_argument("--stock")
        s.add_argument("--out")
        s.add_argument("--threads", type=int, default=8)
        s.add_argument("--reps", type=int, default=1)
        s.add_argument("--prefix-docs", type=int, default=3_000_000)
        s.add_argument("--token-map", choices=["twin"])
    a = ap.parse_args()
    {"encode": cmd_encode, "run": cmd_run, "child-build": cmd_child_build, "child-load": cmd_child_load,
     "child-mmap": cmd_child_mmap, "finalize": cmd_finalize}[a.cmd](a)


if __name__ == "__main__":
    main()
