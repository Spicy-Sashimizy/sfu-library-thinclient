#!/usr/bin/env python3
"""Portable stack §(d) row 6: the serve path end-to-end with CUDA absent.

docs/infrastructure/PORTABLE_STACK_MANIFEST.md §(d) row 6. Replays the served
search sequence of ``tools.search_academic_structured`` (same as
scripts/experiments/eval_speculative_multipass_ab.py, live objects, serving
env/flags, no query-log side effects) on the 120 ``natural`` topics of
data/eval_results/dense_ablation_qrels_20260817.json:

    router.search(q, {}, top_k=_retrieval_top_k(10), force_source=LOCAL_RRF)
    tools._cache_works(fused); tools._maybe_rerank(fused, q, 10)

Arms (each pass is a fresh subprocess of this script in ``--worker`` mode):
  gpu          serving defaults, unchanged env
  cpu          CUDA_VISIBLE_DEVICES="" (torch.cuda.is_available() False)
  cpu_onnx_ce  CUDA_VISIBLE_DEVICES="" + SFU_CE_ONNX=1 (int8 ONNX CE opt-in)
  cpu_wheels   (only with --cpu-venv) the torch-CE CPU arm run by a separate
               venv holding CPU wheels (torch 2.6.0+cpu, onnxruntime 1.26.0,
               no CUDA/TensorRT/RAPIDS packages), built outside the repo; the
               repo venv's cu124/gpu wheels are untouched

Inside every worker the device state is asserted and recorded: in the CPU
arms torch.cuda.is_available() must be False, the embedder and the torch CE
must sit on cpu, and every live ORT session (SPLADE query encoder, and the
int8 CE when enabled) must report providers == ["CPUExecutionProvider"].
A failed assertion aborts that worker and is recorded as the finding.

Order: one warm-up pass (gpu arm; discarded; builds the remote-abstract memo,
the only pass allowed to call OpenAlex), then ``--rounds`` rounds of
gpu / cpu / cpu_onnx_ce, the arm order rotating each round. Each round runs
under flock(/tmp/sfu_latency_measure.lock) (shared-host measurement lock),
so the three arms of a round see the same page-cache state. Each worker also
runs 3 off-set warm-up queries (model load, lazy SEISMIC load) before its
measured pass.

Per topic the worker records: fused list (byte dump), final top-10 ids and
byte dump, stage-1 semantic scores per candidate id, CE scores per candidate
id, the stage-1 order handed to the CE, and stage ms: SPLADE query encode,
SEISMIC traverse, SPLADE leg (encode + traverse), BM25F leg, hydrate (both
legs), retrieval wall, stage-1 (embed rerank) and its embed part, CE stage,
_maybe_rerank wall, total. Per worker: load ms, peak RSS (VmHWM), sampled
peak RssAnon, torch threads, CUDA peak allocated (gpu arm).

Parity (parent): every pass vs the first measured gpu pass: fused byte
identity, final top-10 exact order / set, max |stage-1 score delta| and max
|CE score delta| over shared candidate ids, stage-1 top-20 order identity.

Run:  .venv/bin/python3 scripts/experiments/eval_cpu_only_serve_path.py [--rounds 2]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import statistics as st
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = "2026-09-27"
OUT = REPO / f"data/eval_results/cpu_only_serve_path_{DATE}.json"
LOCK = "/tmp/sfu_latency_measure.lock"
LIMIT = 10
ARMS = {
    "gpu": {},
    "cpu": {"CUDA_VISIBLE_DEVICES": ""},
    "cpu_onnx_ce": {"CUDA_VISIBLE_DEVICES": "", "SFU_CE_ONNX": "1"},
    "cpu_wheels": {"CUDA_VISIBLE_DEVICES": ""},
}
CPU_VENV_PY = "/tmp/claude-1000/cpu_venv/bin/python"
WARM_QUERIES = [
    "effects of social media use on adolescent mental health",
    "machine learning for protein structure prediction",
    "carbon pricing and emissions reduction policy",
]
STAGES = ["total_ms", "retrieval_ms", "splade_encode_ms", "seismic_traverse_ms",
          "splade_leg_ms", "bm25f_leg_ms", "hydrate_ms", "maybe_rerank_ms",
          "stage1_ms", "stage1_embed_ms", "ce_ms"]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))]


def summ(xs):
    if not xs:
        return None
    return {"n": len(xs), "p50": round(pct(xs, 50), 1), "p95": round(pct(xs, 95), 1),
            "mean": round(st.fmean(xs), 1)}


def dump(docs):
    return json.dumps(docs, sort_keys=True, default=str)


def proc_status():
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmHWM", "VmRSS", "RssAnon", "RssFile", "RssShmem"):
            out[k] = int(v.split()[0]) // 1024
    return out


def cuda_libs_mapped():
    names = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        p = line.split()[-1] if len(line.split()) >= 6 else ""
        base = os.path.basename(p)
        if base.startswith(("libcuda.", "libcudart", "libcublas", "libcudnn", "libnvrtc",
                            "libonnxruntime_providers_cuda", "libtorch_cuda")):
            names.add(base)
    return sorted(names)


def worker(args) -> int:
    arm = args.worker
    os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
    peak = {"RssAnon": 0}
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            try:
                peak["RssAnon"] = max(peak["RssAnon"], proc_status().get("RssAnon", 0))
            except Exception:
                pass
            stop.wait(0.1)

    threading.Thread(target=sampler, daemon=True).start()

    t_import = time.perf_counter()
    import torch
    import lib.tools as tools
    import lib.reranker as rr
    import lib.embedding as emb
    import lib.opensearch_retriever as osr
    from lib.federated_search import SearchSource

    cuda_avail = torch.cuda.is_available()
    device_info = {"arm": arm, "python": sys.executable, "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
                   "SFU_CE_ONNX": os.environ.get("SFU_CE_ONNX"),
                   "torch_version": torch.__version__, "torch_cuda_available": cuda_avail,
                   "torch_threads": torch.get_num_threads(),
                   "torch_interop_threads": torch.get_num_interop_threads()}
    try:
        import onnxruntime as ort
        device_info["ort_version"] = ort.__version__
        device_info["ort_available_providers"] = ort.get_available_providers()
    except Exception as e:
        device_info["ort_import_error"] = repr(e)
    if arm != "gpu" and cuda_avail:
        raise SystemExit(f"[{arm}] torch.cuda.is_available() is True in a CPU arm")

    feats = dict(tools._get_features())
    router = tools._get_federated_router()
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        raise SystemExit("search backend is not thinclient")
    fetch_k = tools._retrieval_top_k(LIMIT)
    t0 = time.perf_counter()
    retriever._load()
    backend = retriever._seismic_backend()
    load_index_s = time.perf_counter() - t0

    memo: dict = {}
    memo_path = Path(args.memo)
    if memo_path.exists():
        for k, v in json.loads(memo_path.read_text()):
            memo[tuple(k)] = v
    rstats = {"preloaded_keys": len(memo), "memo_hits": 0, "misses": 0, "remote_calls": 0,
              "allow_remote_calls": args.allow_remote_calls}
    orig_remote = retriever._fetch_remote_abstracts

    def remote(id_list):
        key = tuple(id_list)
        if key in memo:
            rstats["memo_hits"] += 1
            return dict(memo[key])
        rstats["misses"] += 1
        if not args.allow_remote_calls:
            memo[key] = {}
            return {}
        rstats["remote_calls"] += 1
        out = orig_remote(id_list)
        memo[key] = dict(out)
        return out

    retriever._fetch_remote_abstracts = remote

    cur: dict = {}

    def timed(name, fn):
        def w(*a, **kw):
            t = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                cur[name] = cur.get(name, 0.0) + (time.perf_counter() - t) * 1000
        return w

    backend.encode_query = timed("splade_encode_ms", backend.encode_query)
    backend.search_encoded = timed("seismic_traverse_ms", backend.search_encoded)
    retriever._splade_leg = timed("splade_leg_ms", retriever._splade_leg)
    retriever._bm25f_leg = timed("bm25f_leg_ms", retriever._bm25f_leg)
    retriever._hydrate = timed("hydrate_ms", retriever._hydrate)
    tools.rerank_results = timed("stage1_ms", tools.rerank_results)
    tools.rerank_with_crossencoder = timed("ce_ms", tools.rerank_with_crossencoder)

    orig_sem = rr._compute_semantic_scores

    def sem(query, docs, model_path=None):
        t = time.perf_counter()
        out = orig_sem(query, docs, model_path)
        cur["stage1_embed_ms"] = cur.get("stage1_embed_ms", 0.0) + (time.perf_counter() - t) * 1000
        cur["stage1_scores"] = {d.get("openalex_id"): float(s) for d, s in zip(docs, out or [])}
        return out

    rr._compute_semantic_scores = sem

    orig_ce_stage = tools.rerank_with_crossencoder

    def ce_stage(docs, query, limit):
        cur["ce_input_ids"] = [d.get("openalex_id") for d in docs[:rr._CE_CANDIDATE_POOL]]
        return orig_ce_stage(docs, query, limit)

    tools.rerank_with_crossencoder = ce_stage
    orig_ce_pairs = rr._ce_score_pairs

    def ce_pairs(ce, pairs):
        out = orig_ce_pairs(ce, pairs)
        cur.setdefault("ce_raw", []).extend(float(x) for x in out)
        return out

    rr._ce_score_pairs = ce_pairs

    def serve(q):
        cur.clear()
        t0 = time.perf_counter()
        fused = router.search(q, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
        t1 = time.perf_counter()
        fused_dump = dump(fused)
        final = []
        t2 = time.perf_counter()
        if fused:
            tools._cache_works(fused)
            final = tools._maybe_rerank(fused, q, LIMIT)
        t3 = time.perf_counter()
        row = {k: round(cur.get(k, 0.0), 3) for k in STAGES
               if k not in ("total_ms", "retrieval_ms", "maybe_rerank_ms")}
        row.update({"total_ms": round((t3 - t0) * 1000, 3),
                    "retrieval_ms": round((t1 - t0) * 1000, 3),
                    "maybe_rerank_ms": round((t3 - t2) * 1000, 3)})
        ce_ids = cur.get("ce_input_ids", [])
        row["fused_dump"] = fused_dump
        row["fused_ids"] = [d.get("openalex_id") for d in fused]
        row["final_ids"] = [d.get("openalex_id") for d in final]
        row["final_dump"] = dump(final)
        row["stage1_scores"] = cur.get("stage1_scores", {})
        row["ce_input_ids"] = ce_ids
        row["ce_scores"] = dict(zip(ce_ids, cur.get("ce_raw", [])))
        return row

    t_w = time.perf_counter()
    for q in WARM_QUERIES:
        serve(q)
    warm_s = time.perf_counter() - t_w

    ce = rr._get_cross_encoder()
    ce_info = {"type": f"{type(ce).__module__}.{type(ce).__name__}" if ce is not None else None}
    if ce is not None and hasattr(ce, "model"):
        ce_info["device"] = str(ce.model.device)
    if ce is not None and hasattr(ce, "_session"):
        ce_info["ort_providers"] = ce._session.get_providers()
    emb_model = emb._model
    device_info["embedder_device"] = str(getattr(emb_model, "device", None)) if emb_model is not None else None
    device_info["cross_encoder"] = ce_info
    splade_sess = getattr(osr, "_SPLADE_SESSION", None)
    device_info["splade_ort_providers"] = splade_sess.get_providers() if splade_sess is not None else None
    device_info["cuda_libs_mapped"] = cuda_libs_mapped()
    device_info["torch_cuda_initialized"] = bool(torch.cuda.is_initialized())
    if arm != "gpu":
        problems = []
        if device_info["embedder_device"] != "cpu":
            problems.append(f"embedder on {device_info['embedder_device']}")
        if ce_info.get("device") not in (None, "cpu"):
            problems.append(f"CE on {ce_info['device']}")
        if device_info["splade_ort_providers"] != ["CPUExecutionProvider"]:
            problems.append(f"SPLADE ORT providers {device_info['splade_ort_providers']}")
        if arm == "cpu_onnx_ce":
            if ce_info.get("ort_providers") != ["CPUExecutionProvider"]:
                problems.append(f"CE ONNX not active or not CPU: {ce_info}")
        elif "ort_providers" in ce_info:
            problems.append("int8 ONNX CE active in the torch-CE arm")
        if torch.cuda.is_initialized():
            problems.append("torch CUDA initialized")
        if problems:
            raise SystemExit(f"[{arm}] device assertion failed: {problems}")
    else:
        if device_info["embedder_device"] is None or not device_info["embedder_device"].startswith("cuda"):
            device_info["gpu_arm_note"] = "embedder not on cuda"

    topics = json.loads(TOPICS.read_text())["topics"]
    items = [(tid, t["natural"]) for tid, t in topics.items()]
    if args.limit_topics:
        items = items[:args.limit_topics]
    if cuda_avail:
        torch.cuda.reset_peak_memory_stats()
    rows = []
    t_pass = time.perf_counter()
    for i, (tid, q) in enumerate(items):
        r = serve(q)
        r["topic"] = tid
        rows.append(r)
        if (i + 1) % 20 == 0:
            print(f"  [{arm}] {i+1}/{len(items)} total={r['total_ms']:.0f} ms", flush=True)
    pass_s = time.perf_counter() - t_pass
    stop.set()
    if args.allow_remote_calls or rstats["misses"]:
        memo_path.write_text(json.dumps([[list(k), v] for k, v in memo.items()]))
    status = proc_status()
    out = {"arm": arm, "device": device_info, "features": feats, "fetch_k": fetch_k,
           "load_index_s": round(load_index_s, 2), "import_to_ready_s": round(time.perf_counter() - t_import - pass_s, 2),
           "warm_queries_s": round(warm_s, 2), "pass_s": round(pass_s, 1),
           "peak_rss_mb": status.get("VmHWM"), "final_rss": status,
           "peak_rss_anon_mb_sampled": peak["RssAnon"],
           "cuda_max_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if cuda_avail else None,
           "remote_abstract_memo": rstats, "rows": rows}
    Path(args.out).write_text(json.dumps(out))
    return 0


def run_worker(arm, pass_dir, tag, memo, allow_remote, limit_topics, cpu_venv=None):
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    env.pop("SFU_CE_ONNX", None)
    env.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
    env.update(ARMS[arm])
    out = pass_dir / f"{tag}.json"
    py = cpu_venv if arm == "cpu_wheels" else sys.executable
    cmd = [py, str(Path(__file__).resolve()), "--worker", arm, "--out", str(out),
           "--memo", str(memo)]
    if allow_remote:
        cmd.append("--allow-remote-calls")
    if limit_topics:
        cmd += ["--limit-topics", str(limit_topics)]
    print(f"== {tag} ({arm})", flush=True)
    t = time.perf_counter()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - t
    sys.stdout.write(p.stdout)
    if p.returncode != 0:
        tail = p.stderr[-4000:]
        print(f"!! {tag} rc={p.returncode}\n{tail}", flush=True)
        return {"tag": tag, "arm": arm, "rc": p.returncode, "stderr_tail": tail, "wall_s": round(wall, 1)}
    d = json.loads(out.read_text())
    d["tag"], d["rc"], d["wall_s"] = tag, 0, round(wall, 1)
    return d


def compare(ref_rows, rows):
    n = len(ref_rows)
    fused_same = final_bytes = final_order = final_set = s1_order = 0
    top10_overlap = []
    max_s1 = max_ce = 0.0
    ce_deltas = []
    s1_deltas = []
    order_diff_topics = []
    for a, b in zip(ref_rows, rows):
        fused_same += a["fused_dump"] == b["fused_dump"]
        final_bytes += a["final_dump"] == b["final_dump"]
        final_order += a["final_ids"] == b["final_ids"]
        final_set += set(a["final_ids"]) == set(b["final_ids"])
        s1_order += a["ce_input_ids"] == b["ce_input_ids"]
        top10_overlap.append(len(set(a["final_ids"]) & set(b["final_ids"])) / max(1, len(a["final_ids"])))
        if a["final_ids"] != b["final_ids"]:
            order_diff_topics.append(a["topic"])
        for k, v in a["stage1_scores"].items():
            if k in b["stage1_scores"]:
                d = abs(v - b["stage1_scores"][k])
                s1_deltas.append(d)
                max_s1 = max(max_s1, d)
        for k, v in a["ce_scores"].items():
            if k in b["ce_scores"]:
                d = abs(v - b["ce_scores"][k])
                ce_deltas.append(d)
                max_ce = max(max_ce, d)
    return {
        "fused_byte_identical": f"{fused_same}/{n}",
        "final_top10_byte_identical": f"{final_bytes}/{n}",
        "final_top10_exact_order": f"{final_order}/{n}",
        "final_top10_same_set": f"{final_set}/{n}",
        "final_top10_overlap_mean": round(st.fmean(top10_overlap), 4) if top10_overlap else None,
        "stage1_top20_order_identical": f"{s1_order}/{n}",
        "stage1_score_max_abs_delta": max_s1,
        "stage1_score_p50_abs_delta": pct(s1_deltas, 50) if s1_deltas else None,
        "ce_score_max_abs_delta": max_ce,
        "ce_score_p50_abs_delta": pct(ce_deltas, 50) if ce_deltas else None,
        "n_stage1_scores_compared": len(s1_deltas),
        "n_ce_scores_compared": len(ce_deltas),
        "topics_with_top10_order_change": order_diff_topics,
    }


def orchestrate(args) -> int:
    pass_dir = Path(args.pass_dir)
    pass_dir.mkdir(parents=True, exist_ok=True)
    memo = pass_dir / "remote_abstract_memo.json"
    lockf = open(LOCK, "a")

    def locked(fn):
        t = time.perf_counter()
        fcntl.flock(lockf, fcntl.LOCK_EX)
        waited = time.perf_counter() - t
        try:
            return fn(), round(waited, 1)
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)

    arm_names = [a for a in ARMS if a != "cpu_wheels" or args.cpu_venv]
    results = []
    lock_waits = []
    if not args.skip_warmup:
        w, lw = locked(lambda: run_worker("gpu", pass_dir, "warmup_gpu", memo, True, args.limit_topics))
        lock_waits.append(lw)
        results.append(w)
    order = []
    for r in range(args.rounds):
        k = r % len(arm_names)
        rot = arm_names[k:] + arm_names[:k]
        order.append(rot)

        def round_fn(rot=rot, r=r):
            return [run_worker(a, pass_dir, f"r{r}_{a}", memo, False, args.limit_topics, args.cpu_venv)
                    for a in rot]

        rs, lw = locked(round_fn)
        lock_waits.append(lw)
        results.extend(rs)

    measured = [d for d in results if not d["tag"].startswith("warmup")]
    ok = [d for d in measured if d.get("rc") == 0]
    ref = next((d for d in ok if d["arm"] == "gpu"), None)
    summary_passes = []
    for d in results:
        s = {"tag": d["tag"], "arm": d["arm"], "rc": d.get("rc"), "wall_s": d.get("wall_s")}
        if d.get("rc") == 0:
            s.update({k: d[k] for k in ("device", "load_index_s", "import_to_ready_s", "warm_queries_s",
                                         "pass_s", "peak_rss_mb", "peak_rss_anon_mb_sampled", "final_rss",
                                         "cuda_max_allocated_mb", "remote_abstract_memo")})
            s["stages"] = {k: summ([r[k] for r in d["rows"]]) for k in STAGES}
            if ref is not None and d is not ref and not d["tag"].startswith("warmup"):
                s["parity_vs_first_gpu"] = compare(ref["rows"], d["rows"])
        else:
            s["stderr_tail"] = d.get("stderr_tail")
        summary_passes.append(s)

    pooled = {}
    for arm in arm_names:
        arm_ok = [d for d in ok if d["arm"] == arm]
        rows = [r for d in arm_ok for r in d["rows"]]
        if not rows:
            pooled[arm] = None
            continue
        pooled[arm] = {"n_passes": len(arm_ok),
                       "stages": {k: summ([r[k] for r in rows]) for k in STAGES},
                       "peak_rss_mb_max": max(d["peak_rss_mb"] for d in arm_ok),
                       "peak_rss_anon_mb_sampled_max": max(d["peak_rss_anon_mb_sampled"] for d in arm_ok),
                       "import_to_ready_s": [d["import_to_ready_s"] for d in arm_ok],
                       "warm_queries_s": [d["warm_queries_s"] for d in arm_ok]}
    parity = {}
    for arm in arm_names:
        arm_ok = [d for d in ok if d["arm"] == arm]
        if not arm_ok or ref is None:
            continue
        parity[arm] = {"vs_first_gpu_pass": [compare(ref["rows"], d["rows"]) for d in arm_ok if d is not ref]}
        if len(arm_ok) >= 2:
            parity[arm]["within_arm_pass0_vs_pass1"] = compare(arm_ok[0]["rows"], arm_ok[1]["rows"])

    n = len(ref["rows"]) if ref else 0
    out = {
        "what": "Portable stack §(d) row 6: served search path (router LOCAL_RRF -> _cache_works -> "
                "_maybe_rerank: embed rerank + cross-encoder) end-to-end with CUDA absent, both encoders "
                "on CPU, vs the GPU serving defaults; int8 ONNX CE opt-in as a third arm.",
        "date": DATE,
        "script": "scripts/experiments/eval_cpu_only_serve_path.py",
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n,
        "arms": {a: ARMS[a] for a in arm_names},
        "cpu_venv": args.cpu_venv, "round_orders": order, "rounds": args.rounds,
        "lock": LOCK, "lock_wait_s_per_round": lock_waits,
        "cpu_arm_serves": all(d.get("rc") == 0 for d in measured if d["arm"] != "gpu")
                          and any(d["arm"] == "cpu" for d in ok),
        "pooled": pooled,
        "parity": parity,
        "passes": summary_passes,
        "note": "host: local WSL2 (31 GB, 16 cores), RTX 4070 Ti SUPER; shards staged to "
                "SFU_SEISMIC_STAGE_DIR; other agents active on the host between rounds (flock held per "
                "round only). CPU arms hide the GPU with CUDA_VISIBLE_DEVICES=\"\" inside the cu124 "
                "torch / onnxruntime-gpu venv; no CPU-only wheel set was installed.",
    }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"cpu_arm_serves": out["cpu_arm_serves"],
                      "pooled_total": {a: (p["stages"]["total_ms"] if p else None) for a, p in pooled.items()},
                      "parity": {a: v["vs_first_gpu_pass"][-1] if v["vs_first_gpu_pass"] else None
                                 for a, v in parity.items()}}, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", choices=list(ARMS))
    ap.add_argument("--memo", default="")
    ap.add_argument("--allow-remote-calls", action="store_true")
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--skip-warmup", action="store_true")
    ap.add_argument("--cpu-venv", nargs="?", const=CPU_VENV_PY, default=None)
    ap.add_argument("--pass-dir", default="/tmp/claude-1000/cpu_only_serve_path")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    if args.worker:
        return worker(args)
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
