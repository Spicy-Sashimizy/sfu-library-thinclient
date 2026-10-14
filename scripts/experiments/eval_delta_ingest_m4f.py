#!/usr/bin/env python3
"""Delta-ingest M4 follow-up runs P, R1, R2, R3 of the FROZEN pre-registration
docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md (serving levers L3/L4/L5,
adopted stack X). Written 2026-10-01 by agent SERVE before any 09 number
existed. Bars are NOT restated as editable values here: `bars_r1` encodes 09
section 4 verbatim (8.0 ms/gen, 8.0 x G_max, 5 %, [-8, +8] ms, REPL 60-250 ms).

Reuses the M4 harness (`eval_delta_ingest_m4_read_amp.py`, imported as a
module) for host sampling, quiet gate, timing proxies and percentile/OLS
helpers; run logic lives here so the M4 file (also edited by agent BUILD for
L1/L2 roots) is not touched.

Process design = M4 REVISION 2 (09 section 1): one process holds one
ThinClientRetriever per arm, each loaded with its own env (SFU_DELTA_ROOT,
SFU_SEISMIC_SHARD_MANIFEST and the three lever gates are all read at `_load` /
backend construction only), plus a separate priming retriever configured like
n0; 1 warm-up + 2 measured passes; per query a prime call, then all arms in an
order shuffled with seed 20261001; quiet check before every 10th measured
query; health asserted before the first timed query and log-scanned after.
Parallel federation only. Memory abort (not a result): MemAvailable < 6 GB or
process VmSwap growth > 2 GB since process start.

Arms (string spec):
  n0                gate off, base manifest
  n8, n1, n8c ...   root_<tag> under WORK, no lever gates
  e8, s8 ...        L2 layout roots (agent BUILD)
  <arm>+L3[+L4...]  same with those lever gates set to 1
  x1 x4 x8 x8c      stack X: root_<layout prefix><N>[c] + every lever of X
  n0x               n0 + the X levers that act on the base (L4 only)

Statistics (09 section 1.1): t(a,q,p) wall ms; paired slope = per (p,q) OLS
slope over N, median, bootstrap 95% CI resampling TOPICS (all passes of a
drawn topic go together), 2,000 resamples, seed 20261001; paired difference
= median over (p,q) of t(a)-t(b), same bootstrap; pooled slope = OLS of the
arms' pooled p50 over N; p95 recorded; leg attribution recorded.

Run P (parity, SHARED lock, 1 pass, roots n8 and n1, parallel federation):
  per root an OFF retriever (no gates) and an ON retriever (L3+L4+L5). Each
  lever is compared on the only path its gate touches:
  L3 fetch_abstracts(ids) for the ids hydrated by OFF.search_rrf;
  L4 _bm25f_leg(q, 100, f) for f in (None, year 2015-2026);
  L5 _splade_leg_seismic(q, 50, None). The "all" row (every gate unset vs the
  pre-lever code) is two `rrf-dump` processes, one on the lever code and one
  on the same snapshot with the lever commits reverse-applied
  (`prelever-snapshot`), compared by `rrf-compare`.

Commands:
  ... eval_delta_ingest_m4f.py parity --roots n8,n1                (child; caller holds flock -s)
  ... eval_delta_ingest_m4f.py prelever-snapshot --levers C1,C2,C3
  ... eval_delta_ingest_m4f.py rrf-dump --src <snap>/src --roots n8,n1 --rows-out F
  ... eval_delta_ingest_m4f.py rrf-compare --a F1 --b F2
  ... eval_delta_ingest_m4f.py inproc --run R1 --layout single --levers L3,L4,L5 --rows-out F   (child; flock -x)
  ... eval_delta_ingest_m4f.py summarize --run R1 --rows F [--out data/eval_results/delta_ingest_M4F_20261001.json]
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import random
import re
import resource
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "m4h", REPO / "scripts/experiments/eval_delta_ingest_m4_read_amp.py")
M4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M4)

WORK = M4.WORK
BASE_MANIFEST = M4.BASE_MANIFEST
SERVE = Path("/home/vscode/work/delta_ingest/serve")
SEED = 20261001
TOP_K = 50
N_BASE = 8
LEVER_ENV = {"L3": "SFU_DELTA_ABS_ROUTE", "L4": "SFU_BM25F_PARSE_ONCE", "L5": "SFU_SEISMIC_DELTA_GROUP"}
LAYOUT_PREFIX = {"per_base_section": "n", "per_era": "e", "single": "s"}
RUN_ARMS = {
    "R1": ["n0", "n8", "n0x", "x1", "x4", "x8", "x8c"],
    "R2": ["n0", "n8", "n8+L3", "n8+L4", "n8+L5", "e8", "s8"],
    "R3": ["x1", "x8c", "n1", "n8c"],
}
MODEL_ENV = {
    "SFU_SPLADE_MODEL_PATH": "/home/vscode/work/models_local/splade_onnx_fused",
    "SFU_CE_MODEL_PATH": "/home/vscode/work/models_local/sfu-cross-encoder-v1",
    "SFU_EMBEDDING_MODEL_PATH": "/home/vscode/work/delta_ingest/m1/models/sfu-academic-embed-v5",
}
SIGNATURES = M4.SIGNATURES


def resolve_arm(name: str, layout: str = "per_base_section", x_levers: tuple = ()) -> dict:
    """Arm spec -> {name, tag, root, n_gen, levers}. `tag` None = gate off."""
    base, *lev = name.split("+")
    levers = list(lev)
    if base == "n0x":
        tag, levers = None, [x for x in x_levers if x == "L4"] + levers
    elif base.startswith("x"):
        tag, levers = LAYOUT_PREFIX[layout] + base[1:], list(x_levers) + levers
    elif base == "n0":
        tag = None
    else:
        tag = base
    for x in levers:
        if x not in LEVER_ENV:
            raise ValueError(f"unknown lever {x} in arm {name}")
    n_gen = 0 if tag is None else (1 if tag.endswith("c") else int(re.sub(r"\D", "", tag)))
    return {"name": name, "tag": tag, "root": None if tag is None else str(WORK / f"root_{tag}"),
            "n_gen": n_gen, "levers": sorted(set(levers))}


def child_env() -> dict:
    env = M4.arm_env("n0", "parallel")
    env.update(MODEL_ENV)
    env["SFU_META_STAGE_DIR"] = ""
    for v in LEVER_ENV.values():
        env[v] = ""
    return env


class MemGuard(threading.Thread):
    """Sets `tripped` (reason) when MemAvailable < 6 GB or this process's
    VmSwap grew > 2 GB since start (09 section 1 memory bound)."""

    def __init__(self, period_s: float = 5.0):
        super().__init__(daemon=True)
        self.period_s = period_s
        self.tripped: str | None = None
        self.swap0 = self.vmswap_gb()
        self.min_avail = 99.0
        self.max_swap_growth = 0.0

    @staticmethod
    def vmswap_gb() -> float:
        for line in open("/proc/self/status"):
            if line.startswith("VmSwap:"):
                return int(line.split()[1]) / 1024 ** 2
        return 0.0

    @staticmethod
    def avail_gb() -> float:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 ** 2
        return 99.0

    def run(self):
        while self.tripped is None:
            a, s = self.avail_gb(), self.vmswap_gb() - self.swap0
            self.min_avail = min(self.min_avail, a)
            self.max_swap_growth = max(self.max_swap_growth, s)
            if a < 6.0:
                self.tripped = f"MemAvailable {a:.2f} GB < 6 GB at {M4.utc()}"
            elif s > 2.0:
                self.tripped = f"VmSwap grew {s:.2f} GB > 2 GB at {M4.utc()}"
            time.sleep(self.period_s)

    def state(self) -> dict:
        return {"tripped": self.tripped, "min_mem_available_gb": round(self.min_avail, 2),
                "max_vmswap_growth_gb": round(self.max_swap_growth, 3), "vmswap_start_gb": round(self.swap0, 3)}


def _common_health(bad) -> dict:
    h = {}
    try:
        import onnxruntime
        h["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        bad(f"onnxruntime import failed: {exc!r}")
    import lib.tools as tools
    from lib.embedding import _load_model
    from lib.opensearch_retriever import encode_splade
    from lib.reranker import _get_cross_encoder
    cfg = tools._get_config()
    if cfg.search_backend != "thinclient":
        bad("search backend is not thinclient")
    for k in ("SFU_SEISMIC_STAGE_DIR", "SFU_META_STAGE_DIR", "SFU_SEISMIC_SHARD_MANIFEST", "SFU_DELTA_ROOT",
              *LEVER_ENV.values()):
        if os.environ.get(k):
            bad(f"{k}={os.environ.get(k)!r} set in the process env before any arm opened")
    try:
        qv = encode_splade("warm up query for sparse encoder", cfg.splade_model_path)
        h["splade_terms"] = len(qv or {})
        h["splade_model_path"] = cfg.splade_model_path
        if not qv:
            bad("encode_splade returned empty")
    except Exception as exc:
        bad(f"encode_splade raised {exc!r}")
    ce = _get_cross_encoder()
    h["cross_encoder"] = type(ce).__name__ if ce is not None else None
    if ce is None:
        bad("cross-encoder not loaded")
    em = _load_model(os.environ.get("SFU_EMBEDDING_MODEL_PATH") or None)
    h["embedding_model"] = type(em).__name__ if em is not None else None
    if em is None:
        bad("embedding model not loaded")
    return h, cfg


def open_arm(spec: dict, cfg) -> tuple:
    """Construct and load one arm with its env; return (retriever, backend, problems, info).
    Lever gates are reset to '' afterwards so the next arm starts clean."""
    from lib.thinclient.retriever import ThinClientRetriever
    probs = []
    os.environ["SFU_SEISMIC_FEDERATION"] = "parallel"
    os.environ["SFU_DELTA_ROOT"] = spec["root"] or ""
    os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = "" if spec["root"] else str(BASE_MANIFEST)
    for lv, var in LEVER_ENV.items():
        os.environ[var] = "1" if lv in spec["levers"] else ""
    try:
        r = ThinClientRetriever(index_root=cfg.thinclient_index_root, splade_model_path=cfg.splade_model_path,
                                openalex_mailto=cfg.openalex_mailto, query_log_path="",
                                openalex_api_key=cfg.openalex_api_key, remote_abstract_fetcher=None)
        r._fetch_remote_abstracts = lambda ids: {}
        t0 = time.perf_counter()
        r._load()
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        try:
            b = r._seismic_backend()
        except Exception as exc:
            return r, None, [f"{spec['name']}: backend load raised {exc!r}"], {}
    finally:
        for var in LEVER_ENV.values():
            os.environ[var] = ""
        os.environ["SFU_DELTA_ROOT"] = ""
        os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = ""
    name = spec["name"]
    if type(b).__name__ != "ParallelSeismicBackend":
        probs.append(f"{name}: backend {type(b).__name__} != ParallelSeismicBackend")
    if len(b.shards) != N_BASE + spec["n_gen"] or any(x is None for x in b.shards):
        probs.append(f"{name}: shards {len(b.shards)} != {N_BASE + spec['n_gen']}")
    d = r._delta
    delta_pos = ([i for i, o in enumerate(d.shard_origins(len(b.shards), r._seismic_manifest)) if o is not None]
                 if d is not None else [])
    info = {"spec": spec, "load_s": round(load_s, 2), "backend_load_s": round(time.perf_counter() - t0, 2),
            "backend_class": type(b).__name__, "n_shards": len(b.shards), "sections": len(r._sections),
            "abstract_stores": len(r._abstract_stores),
            "gates": {"L3": r._delta_abs_route, "L4": r._bm25f_parse_once,
                      "L5": getattr(b, "_delta_group", None)}}
    if r._delta_abs_route != ("L3" in spec["levers"]):
        probs.append(f"{name}: L3 gate {r._delta_abs_route} != spec")
    if r._bm25f_parse_once != ("L4" in spec["levers"]):
        probs.append(f"{name}: L4 gate {r._bm25f_parse_once} != spec")
    want_group = (delta_pos or None) if "L5" in spec["levers"] else None
    if getattr(b, "_delta_group", None) != want_group:
        probs.append(f"{name}: L5 group {getattr(b, '_delta_group', None)} != {want_group}")
    if spec["root"] is None:
        if d is not None:
            probs.append(f"{name}: delta layer loaded on a gate-off arm")
    elif d is None:
        probs.append(f"{name}: delta layer not loaded")
    else:
        info.update({"delta_generations": [g["gen"] for g in d.generations], "delta_stamp": d.stamp,
                     "delta_manifest": d.shard_manifest_path(), "buffer_size": d.buffer_size(),
                     "delta_sections": sum(1 for s in r._sections.values() if "delta_origin" in s),
                     "delta_shard_positions": delta_pos, "livedocs": d.livedocs is not None,
                     "deleted": len(d.deleted), "superseded": len(d.superseded)})
        if len(d.generations) != spec["n_gen"]:
            probs.append(f"{name}: generations {len(d.generations)} != {spec['n_gen']}")
        if len(delta_pos) != spec["n_gen"]:
            probs.append(f"{name}: delta shard positions {len(delta_pos)} != {spec['n_gen']}")
        if getattr(r, "_seismic_manifest", None) != d.shard_manifest_path():
            probs.append(f"{name}: served manifest is not the delta composed manifest")
    return r, b, probs, info


def _deadline_ts(s: str) -> float:
    import calendar
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) if s else 0.0


def _dump(path: str, obj: dict) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, default=str) + "\n")
    os.replace(tmp, path)


def inproc(args) -> int:
    """R1/R2/R3 measured process (caller holds the latency lock EXCLUSIVELY)."""
    t_start = time.time()
    sys.path.insert(0, args.src)
    import logging
    cap = M4._WarnCapture()
    logging.getLogger().addHandler(cap)
    guard = MemGuard()
    guard.start()
    health: dict = {"ok": True, "problems": [], "arms": {}}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    x_levers = tuple(x for x in args.levers.split(",") if x)
    arm_names = args.arms.split(",") if args.arms else RUN_ARMS[args.run]
    specs = {a: resolve_arm(a, args.layout, x_levers) for a in arm_names}
    out = {"mode": "inproc_m4f", "run": args.run, "layout": args.layout, "x_levers": list(x_levers),
           "arms": arm_names, "specs": specs, "pid": os.getpid(), "src": args.src, "seed": args.seed,
           "host_start": M4.host_state(), "health": health, "deadline": args.deadline}
    for s in specs.values():
        if s["root"] and not Path(s["root"], "generations.json").exists():
            bad(f"{s['name']}: root {s['root']} missing generations.json")
    if health["ok"]:
        h, cfg = _common_health(bad)
        health.update(h)
    rets, accs, timings = {}, {}, {}
    if health["ok"]:
        prime_spec = dict(resolve_arm("n0"), name="_prime")
        for a in list(arm_names) + ["_prime"]:
            if guard.tripped:
                bad(f"memory abort during load: {guard.tripped}")
                break
            r, b, probs, info = open_arm(specs.get(a, prime_spec), cfg)
            health["arms"][a] = info
            for pr in probs:
                bad(pr)
            if b is None:
                continue
            acc, tm = {}, {}
            oe, osrch = b.encode_query, b.search_encoded

            def enc_w(q, _o=oe, _t=tm):
                t = time.perf_counter()
                res = _o(q)
                _t["encode_ms"] = (time.perf_counter() - t) * 1000
                return res

            def srch_w(q, top_k, _o=osrch, _t=tm, **kw):
                t = time.perf_counter()
                res = _o(q, top_k, **kw)
                _t["traverse_ms"] = (time.perf_counter() - t) * 1000
                return res
            b.encode_query, b.search_encoded = enc_w, srch_w
            info["instrumented"] = M4.instrument(r, b, acc)
            if r._delta is not None:
                orig = r._delta.abstract_owner

                def own_w(*a_, _o=orig, _acc=acc, **kw):
                    t = time.perf_counter()
                    try:
                        return _o(*a_, **kw)
                    finally:
                        _acc["delta_abs_owner"] = _acc.get("delta_abs_owner", 0.0) + (time.perf_counter() - t) * 1000
                r._delta.abstract_owner = own_w
            base_idx = [i for i in range(len(b.shards)) if i not in set(info.get("delta_shard_positions", []))]
            rets[a], accs[a], timings[a] = (r, b, base_idx), acc, tm
    health["warnings_at_load"] = list(cap.records)
    if any(any(sg in w for sg in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings during load")
    health["mem_after_load"] = guard.state()
    if not health["ok"]:
        out["host_end"] = M4.host_state()
        _dump(args.rows_out, out)
        print("HEALTH FAIL", json.dumps(health["problems"]), file=sys.stderr, flush=True)
        return 3
    import lib.thinclient.retriever as rmod
    items = M4.load_topics()[:args.limit_topics or None]
    corpus_ids = set(json.loads(M4.CORPUS.read_text())["ids"])
    rng = random.Random(args.seed)
    deadline = _deadline_ts(args.deadline)

    def call(a, q):
        r, b, base_idx = rets[a]
        acc, tm = accs[a], timings[a]
        acc.clear()
        tm.clear()
        before = rmod.snapshot_leg_metrics()
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        fused = r.search_rrf(q, top_k=TOP_K)
        ms = (time.perf_counter() - t) * 1000
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        legs = rmod.leg_metrics_delta(before)
        nsh = len(b.shards)
        return {"arm": a, "ms": round(ms, 2), "bm25f_ms": legs.get("bm25f"), "splade_ms": legs.get("splade"),
                "encode_ms": round(tm["encode_ms"], 2) if "encode_ms" in tm else None,
                "traverse_ms": round(tm["traverse_ms"], 2) if "traverse_ms" in tm else None,
                "traversed": "traverse_ms" in tm, "n": len(fused),
                "n_delta_top10": sum(1 for d in fused[:10] if d.get("openalex_id") in corpus_ids),
                "majflt": ru1.ru_majflt - ru0.ru_majflt,
                "comp": {k: round(v, 2) for k, v in acc.items()},
                "shard_base_max_ms": round(max([acc.get(f"shard{i}", 0.0) for i in base_idx] or [0.0]), 2),
                "shard_delta_sum_ms": round(sum(acc.get(f"shard{i}", 0.0) for i in range(nsh)
                                                if i not in base_idx), 2),
                "top10": [d.get("openalex_id") for d in fused[:10]]}

    out["quiet_gate"] = M4.quiet_gate(args.quiet_wait)
    passes, quiet_waits, last_host = [], [], None
    n_warn_before = len(cap.records)
    stop = None
    for p in range(args.warmup + args.passes):
        kind = "warmup" if p < args.warmup else "measured"
        rows, tp = [], time.time()
        for qi, (key, q) in enumerate(items):
            if guard.tripped:
                stop = f"memory abort: {guard.tripped}"
                break
            if deadline and time.time() > deadline:
                stop = "deadline reached"
                break
            if kind == "measured" and qi % 10 == 0:
                g = M4.quiet_gate(args.inline_wait, load1_max=6.0, poll_s=10)
                last_host = {"utc": g["samples"][-1]["utc"], "load1": g["samples"][-1]["load1"],
                             "busy": g["samples"][-1]["busy_gt50pct"], "quiet": g["quiet"],
                             "waited_s": g["waited_s"], "mem_avail_gb": round(MemGuard.avail_gb(), 2),
                             "vmswap_gb": round(MemGuard.vmswap_gb(), 3)}
                quiet_waits.append({"pass": p + 1, "q": qi, **last_host})
            if kind == "warmup":
                for pos, a in enumerate(arm_names):
                    row = call(a, q)
                    row.update({"topic": key, "position": pos})
                    rows.append(row)
                continue
            prime = call("_prime", q)
            prime.update({"topic": key, "position": -1, "prime": True})
            rows.append(prime)
            order = list(arm_names)
            rng.shuffle(order)
            for pos, a in enumerate(order):
                row = call(a, q)
                row.update({"topic": key, "position": pos, "host": last_host})
                rows.append(row)
            if qi % 20 == 19:
                print(f"[m4f {args.run} pass{p + 1}] {qi + 1}/{len(items)} {time.time() - tp:.0f}s "
                      f"avail {MemGuard.avail_gb():.1f} GB", flush=True)
        passes.append({"pass": p + 1, "kind": kind, "wall_s": round(time.time() - tp, 1), "rows": rows,
                       "complete": stop is None})
        print(f"[m4f {args.run} pass{p + 1} {kind}] {'done' if stop is None else stop} in "
              f"{time.time() - tp:.0f}s", flush=True)
        _dump(args.rows_out, {**out, "passes": passes, "partial": True, "mem": guard.state()})
        if stop:
            break
    measured = [r for ps in passes if ps["kind"] == "measured" for r in ps["rows"] if not r.get("prime")]
    if any(not r["traversed"] for r in measured):
        bad(f"{sum(1 for r in measured if not r['traversed'])} measured calls never reached the SEISMIC traverse")
    warn_meas = cap.records[n_warn_before:]
    if any(any(sg in w for sg in SIGNATURES) for w in warn_meas):
        bad("failure signature in warnings during measurement")
    if stop and stop.startswith("memory"):
        bad(stop)
    health["warnings_during_passes"] = warn_meas[:50]
    health["n_warnings_during_passes"] = len(warn_meas)
    out.update({"quiet_waits": quiet_waits, "host_end": M4.host_state(), "wall_s": round(time.time() - t_start, 1),
                "maxrss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2, 2),
                "passes": passes, "partial": stop is not None, "stop": stop, "mem": guard.state()})
    _dump(args.rows_out, out)
    return 0 if health["ok"] and stop is None else (4 if stop else 3)


def _ser(x) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def parity(args) -> int:
    """Run P child (caller holds the latency lock SHARED). Timings invalid by declaration."""
    sys.path.insert(0, args.src)
    import logging
    cap = M4._WarnCapture()
    logging.getLogger().addHandler(cap)
    guard = MemGuard()
    guard.start()
    health: dict = {"ok": True, "problems": [], "arms": {}}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)

    out = {"mode": "parity_m4f", "src": args.src, "roots": args.roots, "host_start": M4.host_state(),
           "health": health, "started_utc": M4.utc()}
    h, cfg = _common_health(bad)
    health.update(h)
    if not health["ok"]:
        _dump(args.rows_out, out)
        return 3
    items = M4.load_topics()[:args.limit_topics or None]
    yf = {"year_range": (2015, 2026)}
    results = {}
    for tag in args.roots.split(","):
        off_s = resolve_arm(tag)
        on_s = resolve_arm(f"{tag}+L3+L4+L5")
        arms = {}
        for s in (off_s, on_s):
            r, b, probs, info = open_arm(s, cfg)
            health["arms"][s["name"]] = info
            for pr in probs:
                bad(pr)
            arms[s["name"]] = r
        if not health["ok"]:
            break
        off, on = arms[off_s["name"]], arms[on_s["name"]]
        rec_ids: list = []
        orig_fetch = off.fetch_abstracts

        def rec_fetch(ids, _o=orig_fetch):
            rec_ids.extend(ids)
            return _o(ids)
        off.fetch_abstracts = rec_fetch
        rows = []
        for qi, (key, q) in enumerate(items):
            if guard.tripped:
                bad(f"memory abort: {guard.tripped}")
                break
            rec_ids.clear()
            fused_off = off.search_rrf(q, top_k=TOP_K)
            ids = list(dict.fromkeys(rec_ids))
            fused_on = on.search_rrf(q, top_k=TOP_K)
            a_off, a_on = orig_fetch(ids), on.fetch_abstracts(ids)
            row = {"topic": key, "n_ids": len(ids),
                   "n_owned": len(on._delta.abstract_owner(ids)) if on._delta is not None else 0,
                   "L3": a_off == a_on, "rrf_off_vs_on": _ser(fused_off) == _ser(fused_on)}
            if not row["L3"]:
                row["L3_diff"] = sorted(k for k in set(a_off) | set(a_on) if a_off.get(k) != a_on.get(k))[:10]
            for fname, f in (("none", None), ("year", yf)):
                l_off, l_on = off._bm25f_leg(q, 100, f), on._bm25f_leg(q, 100, f)
                row[f"L4_{fname}"] = l_off == l_on
                row[f"L4_{fname}_n"] = len(l_off)
                if l_off != l_on:
                    row[f"L4_{fname}_first_diff"] = next(
                        (i, x, y) for i, (x, y) in enumerate(zip(l_off + [None] * 200, l_on + [None] * 200)) if x != y)
            s_off, s_on = off._splade_leg_seismic(q, TOP_K, None), on._splade_leg_seismic(q, TOP_K, None)
            row["L5"] = s_off == s_on
            row["L5_n"] = len(s_off)
            if s_off != s_on:
                row["L5_first_diff"] = next(
                    (i, x, y) for i, (x, y) in enumerate(zip(s_off + [None] * 200, s_on + [None] * 200)) if x != y)
            rows.append(row)
            if qi % 20 == 19:
                print(f"[parity {tag}] {qi + 1}/{len(items)}", flush=True)
        results[tag] = rows
        _dump(args.rows_out, {**out, "results": results, "partial": True})
        for r in arms.values():
            r._seismic = None
        del off, on, arms
    warn = list(cap.records)
    if any(any(sg in w for sg in SIGNATURES) for w in warn):
        bad("failure signature in warnings")
    health["warnings"] = warn[:50]
    out.update({"results": results, "partial": False, "host_end": M4.host_state(), "mem": guard.state(),
                "finished_utc": M4.utc()})
    _dump(args.rows_out, out)
    return 0 if health["ok"] else 3


def rrf_dump(args) -> int:
    """Fused top-50 + final top-10 per topic with every lever gate unset, on the
    code under --src (the 'all' row of Run P)."""
    sys.path.insert(0, args.src)
    import logging
    cap = M4._WarnCapture()
    logging.getLogger().addHandler(cap)
    health: dict = {"ok": True, "problems": [], "arms": {}}

    def bad(msg):
        health["ok"] = False
        health["problems"].append(msg)
    h, cfg = _common_health(bad)
    health.update(h)
    import lib.tools as tools
    from lib.thinclient.retriever import ThinClientRetriever
    out = {"mode": "rrf_dump", "src": args.src, "health": health, "rows": {}, "started_utc": M4.utc()}
    items = M4.load_topics()[:args.limit_topics or None]
    for tag in args.roots.split(","):
        spec = resolve_arm(tag)
        os.environ["SFU_SEISMIC_FEDERATION"] = "parallel"
        os.environ["SFU_DELTA_ROOT"] = spec["root"] or ""
        os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = "" if spec["root"] else str(BASE_MANIFEST)
        r = ThinClientRetriever(index_root=cfg.thinclient_index_root, splade_model_path=cfg.splade_model_path,
                                openalex_mailto=cfg.openalex_mailto, query_log_path="",
                                openalex_api_key=cfg.openalex_api_key, remote_abstract_fetcher=None)
        r._fetch_remote_abstracts = lambda ids: {}
        r._load()
        b = r._seismic_backend()
        info = {"backend": type(b).__name__, "n_shards": len(b.shards),
                "gens": len(r._delta.generations) if r._delta is not None else 0,
                "gates": {k: getattr(r, k, "absent") for k in ("_delta_abs_route", "_bm25f_parse_once")} |
                {"_delta_group": getattr(b, "_delta_group", "absent")}}
        health["arms"][tag] = info
        if info["n_shards"] != N_BASE + spec["n_gen"] or info["gens"] != spec["n_gen"]:
            bad(f"{tag}: shards/gens {info}")
        rows = []
        for key, q in items:
            fused = r.search_rrf(q, top_k=TOP_K)
            final = tools._maybe_rerank(copy.deepcopy(fused), q, 10)
            rows.append({"topic": key, "fused": _ser(fused), "fused10": _ser(fused[:10]), "final10": _ser(final)})
        out["rows"][tag] = rows
        _dump(args.rows_out, {**out, "partial": True})
        r._seismic = None
    if any(any(sg in w for sg in SIGNATURES) for w in cap.records):
        bad("failure signature in warnings")
    health["warnings"] = list(cap.records)[:50]
    out.update({"partial": False, "finished_utc": M4.utc()})
    _dump(args.rows_out, out)
    return 0 if health["ok"] else 3


def rrf_compare(args) -> int:
    a, b = json.loads(Path(args.a).read_text()), json.loads(Path(args.b).read_text())
    res = {"a": args.a, "b": args.b, "health_ok": [a["health"]["ok"], b["health"]["ok"]],
           "partial": [a.get("partial"), b.get("partial")], "roots": {}}
    for tag in a["rows"]:
        ra, rb = a["rows"][tag], b["rows"].get(tag, [])
        n = min(len(ra), len(rb))
        cmp_ = {k: sum(1 for x, y in zip(ra, rb) if x[k] == y[k]) for k in ("fused", "fused10", "final10")}
        first = next((x["topic"] for x, y in zip(ra, rb) if any(x[k] != y[k] for k in ("fused", "final10"))), None)
        res["roots"][tag] = {"n": n, "identical": cmp_, "first_diff_topic": first,
                             "verdict": "PASS" if n == 120 and cmp_["fused"] == n and cmp_["final10"] == n
                             else ("FAIL" if first else f"PARTIAL n={n}")}
    print(json.dumps(res, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1) + "\n")
    return 0


def prelever_snapshot(args) -> int:
    """`git archive <commit> src` + the lever commits' src diffs reverse-applied."""
    commit = args.commit or M4.git_commit()
    dst = SERVE / f"code_{commit[:8]}_prelever"
    if not (dst / "source").exists():
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(f"git -C {REPO} archive {commit} src | tar -x -C {dst}", shell=True)
        for c in reversed(args.levers.split(",")):
            diff = subprocess.check_output(["git", "-C", str(REPO), "show", "--format=", c, "--", "source"])
            subprocess.run(["patch", "-R", "-p1", "-d", str(dst), "--no-backup-if-mismatch"], input=diff,
                           check=True)
        for name in ("models", "data", ".env"):
            if not (dst / name).exists():
                (dst / name).symlink_to(REPO / name)
    left = subprocess.run(["grep", "-rln", "SFU_DELTA_ABS_ROUTE\\|SFU_BM25F_PARSE_ONCE\\|SFU_SEISMIC_DELTA_GROUP",
                           str(dst / "source")], capture_output=True, text=True).stdout.split()
    print(json.dumps({"snapshot": str(dst), "commit": commit, "levers_reverted": args.levers.split(","),
                      "gate_names_left": left}))
    return 1 if left else 0


def _units(rows: list) -> dict:
    u: dict = {}
    for r in rows:
        u.setdefault((r["pass"], r["topic"]), {})[r["arm"]] = r["ms"]
    return u


def cluster_boot(pairs: list, seed: int = SEED, n: int = 2000) -> list | None:
    """95% CI of the median over units, resampling topics (09 section 1.1)."""
    by: dict = {}
    for t, v in pairs:
        by.setdefault(t, []).append(v)
    topics = sorted(by)
    if len(topics) < 5:
        return None
    rng = random.Random(seed)
    meds = []
    for _ in range(n):
        vals = []
        for t in rng.choices(topics, k=len(topics)):
            vals.extend(by[t])
        meds.append(statistics.median(vals))
    meds.sort()
    return [round(meds[int(0.025 * n)], 3), round(meds[int(0.975 * n) - 1], 3)]


def paired_slope(units: dict, fam: dict) -> dict:
    pairs = []
    for (p, t), v in units.items():
        if all(a in v for a in fam):
            pairs.append((t, M4.ols([fam[a] for a in fam], [v[a] for a in fam])))
    vals = [x for _, x in pairs]
    return {"n": len(vals), "median": round(statistics.median(vals), 3) if vals else None,
            "ci95": cluster_boot(pairs)}


def paired_diff(units: dict, a: str, b: str) -> dict:
    pairs = [(t, v[a] - v[b]) for (p, t), v in units.items() if a in v and b in v]
    vals = [x for _, x in pairs]
    return {"n": len(vals), "median": round(statistics.median(vals), 3) if vals else None,
            "ci95": cluster_boot(pairs)}


def leg_parts(r: dict) -> dict:
    c = r.get("comp", {})
    bm, sp = r.get("bm25f_ms") or 0.0, r.get("splade_ms") or 0.0
    tr, en = r.get("traverse_ms") or 0.0, r.get("encode_ms") or 0.0
    delta_sec = c.get("bm25f_delta", 0.0) + c.get("bm25f_buffer", 0.0)
    abs_delta = c.get("abs_delta", 0.0) + c.get("delta_abs_owner", 0.0)
    hyd = c.get("abs_base", 0.0) + abs_delta + c.get("delta_meta", 0.0) + c.get("delta_buffer_abs", 0.0)
    return {"total": r["ms"], "bm25f_base_sections": c.get("bm25f_base", 0.0), "bm25f_delta_sections": delta_sec,
            "bm25f_other_parse_merge_masks": bm - c.get("bm25f_base", 0.0) - delta_sec,
            "seismic_traverse": tr, "seismic_base_max_shard": r.get("shard_base_max_ms", 0.0),
            "seismic_delta_shard_sum": r.get("shard_delta_sum_ms", 0.0), "splade_encode": en,
            "splade_other_delta_merge": sp - tr - en, "hydrate_abstracts_base": c.get("abs_base", 0.0),
            "hydrate_abstracts_delta": abs_delta, "hydrate_abs_owner_lookup": c.get("delta_abs_owner", 0.0),
            "hydrate_delta_meta": c.get("delta_meta", 0.0), "delta_masks": c.get("delta_masks", 0.0),
            "hydrate_other_base_meta_fuse": r["ms"] - bm - sp - hyd}


def bars_r1(arms: dict, units: dict, nmap: dict) -> dict:
    """09 section 4 R1 bars, applied mechanically."""
    p50 = {a: arms[a]["p50_ms"] for a in arms}
    fam = {a: nmap[a] for a in ("n0x", "x1", "x4", "x8")}
    ps = paired_slope(units, fam)
    pooled = M4.ols([fam[a] for a in fam], [p50[a] for a in fam])
    hi = ps["ci95"][1] if ps["ci95"] else None
    if ps["median"] is not None and ps["median"] > 8.0:
        v = "FAIL"
    elif hi is not None and hi <= 8.0 and pooled <= 8.0:
        v = "PASS"
    elif hi is not None and hi <= 8.0 and pooled > 8.0:
        v = "PARTIAL"
    else:
        v = "FAIL"
    out = {"F-SLOPE": {"paired_slope": ps, "pooled_slope": pooled, "threshold_ms_per_gen": 8.0, "verdict": v}}
    cad = {}
    for g in (1, 4, 8):
        d = paired_diff(units, f"x{g}", "n0x")
        pd_ = round(p50[f"x{g}"] - p50["n0x"], 2)
        ok = d["ci95"] is not None and d["ci95"][1] <= 8.0 * g and pd_ <= 8.0 * g
        cad[f"G_max={g}"] = {"paired_diff": d, "pooled_p50_diff": pd_, "threshold_ms": 8.0 * g,
                             "verdict": "PASS" if ok else "FAIL"}
    passing = [g for g in (1, 4, 8) if cad[f"G_max={g}"]["verdict"] == "PASS"]
    out["F-CAD"] = {"per_G_max": cad, "smallest_passing_G_max": passing[0] if passing else None,
                    "verdict": f"PASS at G_max={passing[0]}" if passing else "FAIL"}
    ratio = round(p50["x8c"] / p50["x1"], 4)
    d = paired_diff(units, "x8c", "x1")
    ok = abs(ratio - 1) <= 0.05 and d["ci95"] is not None and -8.0 <= d["ci95"][0] and d["ci95"][1] <= 8.0
    out["F-COMP"] = {"p50_ratio_x8c_x1": ratio, "paired_diff_x8c_minus_x1": d,
                     "rule": "|ratio-1| <= 0.05 AND CI within [-8, +8] ms", "verdict": "PASS" if ok else "FAIL"}
    r = paired_diff(units, "n8", "n0")
    flag = r["median"] is None or not (60.0 <= r["median"] <= 250.0)
    out["REPL"] = {"paired_diff_n8_minus_n0": r, "m4_reference": "+123 ms (CI 112-137)",
                   "window_ms": [60, 250], "flag": "OUTSIDE (repeat R1 once before reading verdicts)" if flag
                   else "inside"}
    return out


def summarize(args) -> int:
    rec = json.loads(Path(args.rows).read_text())
    arms_l = rec["arms"]
    specs = rec["specs"]
    mp = [ps for ps in rec.get("passes", []) if ps["kind"] == "measured"]
    rows = [dict(r, **{"pass": ps["pass"]}) for ps in mp for r in ps["rows"] if not r.get("prime")]
    units = _units(rows)
    nmap = {a: specs[a]["n_gen"] for a in arms_l}
    arms = {}
    for a in arms_l:
        ar = [r for r in rows if r["arm"] == a]
        ms = [r["ms"] for r in ar]
        parts = [leg_parts(r) for r in ar]
        arms[a] = {"spec": specs[a], "n_calls": len(ar), "p50_ms": M4.pct(ms, 50), "p95_ms": M4.pct(ms, 95),
                   "mean_ms": round(statistics.fmean(ms), 2) if ms else None,
                   "per_pass_p50_ms": [M4.pct([r["ms"] for r in ar if r["pass"] == ps["pass"]], 50) for ps in mp],
                   "legs_mean_ms": {k: round(statistics.fmean([p[k] for p in parts]), 3) for k in parts[0]} if parts else {},
                   "legs_median_ms": {k: round(statistics.median([p[k] for p in parts]), 3) for k in parts[0]} if parts else {},
                   "majflt_mean": round(statistics.fmean([r["majflt"] for r in ar]), 1) if ar else None,
                   "delta_docs_in_top10_mean": round(statistics.fmean([r["n_delta_top10"] for r in ar]), 3) if ar else None}
    complete = (rec.get("health", {}).get("ok") and not rec.get("partial") and len(mp) == args.passes
                and all(arms[a]["n_calls"] == 120 * args.passes for a in arms_l))
    res = {"run": rec["run"], "script": "scripts/experiments/eval_delta_ingest_m4f.py",
           "preregistration": "docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md",
           "rows_file": args.rows, "status": "COMPLETE" if complete else "PARTIAL/INVALID",
           "health": {k: v for k, v in rec.get("health", {}).items() if k not in ("warnings_at_load",)},
           "layout": rec.get("layout"), "x_levers": rec.get("x_levers"), "seed": rec.get("seed"),
           "src": rec.get("src"), "git_commit_measured_code": args.commit, "measured_passes": len(mp),
           "pass_wall_s": [ps["wall_s"] for ps in rec.get("passes", [])], "wall_s": rec.get("wall_s"),
           "host_start": rec.get("host_start"), "host_end": rec.get("host_end"), "quiet_gate": rec.get("quiet_gate"),
           "quiet_waits": rec.get("quiet_waits"), "mem": rec.get("mem"), "maxrss_gb": rec.get("maxrss_gb"),
           "stop": rec.get("stop"), "arms": arms,
           "prime_p50_ms": M4.pct([r["ms"] for ps in mp for r in ps["rows"] if r.get("prime")], 50),
           "p50_by_position": {str(p): M4.pct([r["ms"] for r in rows if r["position"] == p], 50)
                               for p in range(len(arms_l))},
           "date_utc": time.strftime("%Y-%m-%d", time.gmtime())}
    if args.log:
        res["log_scan"] = M4.scan_log(Path(args.log))
    if rec["run"] == "R1" and complete:
        res["bars"] = bars_r1(arms, units, nmap)
    elif rec["run"] == "R1":
        res["bars"] = "NOT READ: run not complete/healthy"
    if rec["run"] == "R2":
        diffs = {}
        for a in arms_l:
            if a.startswith("n8") and a != "n8":
                diffs[f"{a}_minus_n8"] = paired_diff(units, a, "n8")
            if a in ("e8", "s8"):
                diffs[f"{a}_minus_n8"] = paired_diff(units, a, "n8")
            if a.startswith("n0+"):
                diffs[f"{a}_minus_n0"] = paired_diff(units, a, "n0")
        diffs["n8_minus_n0"] = paired_diff(units, "n8", "n0")
        res["paired_differences"] = diffs
        res["lever_gain_rule"] = {
            k: {"median": v["median"], "ci95": v["ci95"],
                "verdict": ("KILL (median gain > -1.0 ms)" if v["median"] is not None and v["median"] > -1.0
                            else "KEEP") + (" ; CI includes 0" if v["ci95"] and v["ci95"][0] <= 0 <= v["ci95"][1]
                                            else "")}
            for k, v in diffs.items() if "+L" in k and k.endswith("minus_n8")}
    if rec["run"] == "R3":
        res["paired_differences"] = {f"{a}_minus_{b}": paired_diff(units, a, b)
                                     for a, b in (("x8c", "x1"), ("n8c", "n1"), ("x1", "n1"), ("x8c", "n8c"))
                                     if a in arms_l and b in arms_l}
    out = Path(args.out)
    full = json.loads(out.read_text()) if out.exists() else {
        "measurement": "09 M4 follow-up (docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md)",
        "results_file_rule": "one key per run: parity, R1, R2, R3"}
    full[args.key or rec["run"]] = res
    out.write_text(json.dumps(full, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k in ("status", "bars", "paired_differences",
                                                              "lever_gain_rule")}, indent=1, default=str))
    print(json.dumps({a: {k: v for k, v in d.items() if k in ("p50_ms", "p95_ms", "n_calls")}
                      for a, d in arms.items()}, indent=1))
    return 0


def summarize_parity(args) -> int:
    rec = json.loads(Path(args.rows).read_text())
    res = {"script": "scripts/experiments/eval_delta_ingest_m4f.py", "rows_file": args.rows,
           "health": {k: v for k, v in rec["health"].items() if k != "warnings"}, "src": rec.get("src"),
           "git_commit_measured_code": args.commit, "started_utc": rec.get("started_utc"),
           "finished_utc": rec.get("finished_utc"), "partial": rec.get("partial"), "mem": rec.get("mem"),
           "timings": "INVALID by declaration (shared lock)", "roots": {}}
    for tag, rows in rec.get("results", {}).items():
        d = {"n": len(rows)}
        for k in ("L3", "L4_none", "L4_year", "L5", "rrf_off_vs_on"):
            d[k] = {"identical": sum(1 for r in rows if r[k]), "first_diff_topic":
                    next((r["topic"] for r in rows if not r[k]), None)}
        d["L3_ids_total"] = sum(r["n_ids"] for r in rows)
        d["L3_ids_delta_owned"] = sum(r["n_owned"] for r in rows)
        d["L4_hits_mean"] = {k: round(statistics.fmean([r[f"L4_{k}_n"] for r in rows]), 1) for k in ("none", "year")} if rows else None
        res["roots"][tag] = d
    verdict = {}
    for lv, keys in (("L3", ("L3",)), ("L4", ("L4_none", "L4_year")), ("L5", ("L5",))):
        ok = all(res["roots"].get(t, {}).get(k, {}).get("identical") == 120 for t in ("n8", "n1") for k in keys)
        first = next((res["roots"][t][k]["first_diff_topic"] for t in res["roots"] for k in keys
                      if res["roots"][t][k]["first_diff_topic"]), None)
        verdict[lv] = ("PASS" if ok and rec["health"]["ok"] and not rec.get("partial")
                       else ("FAIL (first differing topic " + str(first) + ")" if first else "INCOMPLETE/INVALID"))
    res["verdicts"] = verdict
    if args.all_compare:
        res["all_gates_unset_vs_prelever"] = json.loads(Path(args.all_compare).read_text())
    out = Path(args.out)
    full = json.loads(out.read_text()) if out.exists() else {
        "measurement": "09 M4 follow-up (docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md)",
        "results_file_rule": "one key per run: parity, R1, R2, R3"}
    full["parity"] = res
    out.write_text(json.dumps(full, indent=1, default=str) + "\n")
    print(json.dumps({"verdicts": verdict, "roots": res["roots"]}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_out = str(REPO / "data/eval_results/delta_ingest_M4F_20261001.json")
    p = sub.add_parser("parity")
    p.add_argument("--roots", default="n8,n1")
    p.add_argument("--rows-out", required=True)
    p.add_argument("--src", default=str(REPO / "source"))
    p.add_argument("--limit-topics", type=int, default=0)
    s = sub.add_parser("prelever-snapshot")
    s.add_argument("--commit", default="")
    s.add_argument("--levers", required=True)
    d = sub.add_parser("rrf-dump")
    d.add_argument("--src", required=True)
    d.add_argument("--roots", default="n8,n1")
    d.add_argument("--rows-out", required=True)
    d.add_argument("--limit-topics", type=int, default=0)
    c = sub.add_parser("rrf-compare")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--out", default="")
    i = sub.add_parser("inproc")
    i.add_argument("--run", required=True, choices=sorted(RUN_ARMS))
    i.add_argument("--arms", default="")
    i.add_argument("--layout", default="per_base_section", choices=sorted(LAYOUT_PREFIX))
    i.add_argument("--levers", default="")
    i.add_argument("--passes", type=int, default=2)
    i.add_argument("--warmup", type=int, default=1)
    i.add_argument("--rows-out", required=True)
    i.add_argument("--limit-topics", type=int, default=0)
    i.add_argument("--src", default=str(REPO / "source"))
    i.add_argument("--quiet-wait", type=int, default=900)
    i.add_argument("--inline-wait", type=int, default=120)
    i.add_argument("--seed", type=int, default=SEED)
    i.add_argument("--deadline", default="2026-10-02T06:00:00Z")
    m = sub.add_parser("summarize")
    m.add_argument("--rows", required=True)
    m.add_argument("--out", default=default_out)
    m.add_argument("--key", default="")
    m.add_argument("--commit", default="")
    m.add_argument("--log", default="")
    m.add_argument("--passes", type=int, default=2)
    mp = sub.add_parser("summarize-parity")
    mp.add_argument("--rows", required=True)
    mp.add_argument("--out", default=default_out)
    mp.add_argument("--commit", default="")
    mp.add_argument("--all-compare", default="")
    a = ap.parse_args()
    return {"parity": parity, "prelever-snapshot": prelever_snapshot, "rrf-dump": rrf_dump,
            "rrf-compare": rrf_compare, "inproc": inproc, "summarize": summarize,
            "summarize-parity": summarize_parity}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
