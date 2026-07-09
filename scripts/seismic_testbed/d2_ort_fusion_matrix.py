#!/usr/bin/env python3
"""D2: ORT graph-fusion + session-option matrix for the SPLADE query encoder
(doc 08 §D follow-up; the lossless arm D1's kill left open, 2026-07-09).

D1 killed dynamic int8 (encoder asymmetry: overlap@10 ≈ 0.79). The remaining
encoder levers that do NOT re-encode weights are graph/runtime options. This
script runs the full matrix against the production baseline (the
`_get_splade_model` singleton: default SessionOptions → ORT_ENABLE_ALL
runtime fusion, default intra-op threads, spinning on):

  fused        — offline transformer fusion (onnxruntime.transformers
                 optimizer, model_type=bert, 12 heads / 768 hidden: fused
                 Attention / EmbedLayerNorm / SkipLayerNorm; exact GELU) →
                 models/splade_onnx_fused/
  fused_gelu   — same + FastGelu approximation (numerics NOT exact — gated
                 like any lossy arm) → models/splade_onnx_fused_gelu/
  base_t{1,2,4,8} — production model, intra_op_num_threads pinned (batch-1
                 short-seq encodes often lose to thread fan-out; default is
                 all 16 logical cores)
  base_nospin  — production model, session.intra_op.allow_spinning=0
  fused_t{best} — combined arm, built after the sweep if both independent
                 levers win.

  (Not tested, with reason: graph_optimization_level below ORT_ENABLE_ALL —
  the baseline already runs ALL, lower can only remove fusions;
  optimized_model_filepath offline-save — amortizes session INIT, not
  per-query latency; fp16/bf16 CPU — no native fp16 on this avx2 host;
  batching / IOBinding — serving is batch-1 with tiny feeds.)

Method per arm: ONE arm session co-resident with the baseline at a time
(created, benched, destroyed — the D1 lesson: many co-resident ORT sessions
inflate every wall via spinning pools), interleaved per query with the
baseline, n=100 × 2 recorded passes, full encode wall (tokenize + run +
sparsify).

Quality: per arm, count queries whose top-64 qvec dict is EXACTLY equal to
the baseline's. 100/100 equal → lossless by construction (search unreachable
by the change; no further gate needed). Otherwise the arm gets the D1-style
served gate: federated merged overlap@10/@50 vs baseline qvecs (n=100,
parallel backend) AND the sequential-method identity leg (parallel ≡
sequential bit-identical on the arm's qvecs) — shards are loaded lazily only
if some candidate arm needs this.

Bars (pre-registered): flip the served encoder configuration to the fastest
arm with [qvec exact 100/100 OR (overlap@10 mean >= 0.99 AND sequential
identity 0 mismatches)] AND speedup_p50 > 1.05 (a <5% win doesn't justify a
serving change). No arm passes -> record, keep baseline, stop.
Rule Zero: read-only over shard dirs; writes only models/splade_onnx_fused*/.
"""
import argparse
import gc
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

FP32_DIR = REPO / "models/splade_onnx_fp16"
FUSED_DIR = REPO / "models/splade_onnx_fused"
FUSED_GELU_DIR = REPO / "models/splade_onnx_fused_gelu"
MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 100
WARM_PASSES = 2
TOP_K = 50
MIN_SPEEDUP = 1.05
RESULT = REPO / ("data/eval_results/d2_ort_fusion_matrix_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")


def build_fused(out_dir: Path, gelu_approx: bool, force: bool) -> dict:
    out = out_dir / "model.onnx"
    if out.exists() and not force:
        print(f"fused model already at {out}")
        return {"built": "skipped (exists)"}
    from onnxruntime.transformers import optimizer
    from onnxruntime.transformers.fusion_options import FusionOptions
    t0 = time.time()
    opts = FusionOptions("bert")
    opts.enable_gelu_approximation = gelu_approx
    m = optimizer.optimize_model(str(FP32_DIR / "model.onnx"), model_type="bert",
                                 num_heads=12, hidden_size=768,
                                 optimization_options=opts)
    out_dir.mkdir(parents=True, exist_ok=True)
    m.save_model_to_file(str(out))
    shutil.copy2(FP32_DIR / "config.json", out_dir / "config.json")
    (out_dir / ".export_complete").write_text(
        f"{time.strftime('%Y-%m-%d')} offline bert fusion of "
        f"models/splade_onnx_fp16/model.onnx (gelu_approx={gelu_approx}) via "
        f"scripts/seismic_testbed/d2_ort_fusion_matrix.py\n")
    return {"built": "built", "mb": round(out.stat().st_size / 1e6, 1),
            "fused_ops": {k: v for k, v in m.get_fused_operator_statistics().items() if v},
            "seconds": round(time.time() - t0, 1)}


def encode_with(session, tokenizer, id_to_token, n_terms, text):
    """Replica of `opensearch_retriever.encode_splade` + `encode_query`
    truncation (pinned against production in leg 1, same as D1)."""
    import numpy as np
    enc = tokenizer([text], max_length=512, truncation=True, padding=True,
                    return_tensors="np")
    input_ids = enc["input_ids"].astype(np.int64)
    feeds = {"input_ids": input_ids,
             "attention_mask": enc["attention_mask"].astype(np.int64),
             "token_type_ids": enc.get("token_type_ids",
                                       np.zeros_like(input_ids)).astype(np.int64)}
    logits = session.run(["logits"], feeds)[0][0]
    vec = np.log1p(np.maximum(logits, 0.0)).max(axis=0)
    nonzero = np.nonzero(vec)[0]
    if nonzero.size == 0:
        return {}
    order = nonzero[np.argsort(-vec[nonzero])]
    sparse = {}
    for idx in order:
        token = id_to_token.get(int(idx), "")
        weight = float(vec[int(idx)])
        if not token or token.startswith("["):
            continue
        if weight <= 0.0:
            continue
        sparse[token] = round(weight, 4)
    return dict(sorted(sparse.items(), key=lambda x: -x[1])[:n_terms])


def make_session(model_path: Path, threads: int | None, spin: str | None):
    import onnxruntime as ort
    so = ort.SessionOptions()
    if threads is not None:
        so.intra_op_num_threads = threads
    if spin is not None:
        so.add_session_config_entry("session.intra_op.allow_spinning", spin)
    t0 = time.time()
    sess = ort.InferenceSession(str(model_path), sess_options=so,
                                providers=["CPUExecutionProvider"])
    return sess, round(time.time() - t0, 2)


def p50(xs):
    return round(statistics.median(xs), 2)


def p95(xs):
    xs = sorted(xs)
    return round(xs[int(round(0.95 * (len(xs) - 1)))], 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    t_start = time.time()

    build_meta = {"fused": build_fused(FUSED_DIR, False, args.rebuild),
                  "fused_gelu": build_fused(FUSED_GELU_DIR, True, args.rebuild)}

    from e6_forward_codec_proto import load_queries
    import lib.opensearch_retriever  # noqa: F401  torch first (ENOMEM lesson)
    from lib.opensearch_retriever import _get_splade_model, encode_splade
    from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS

    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    sess_base, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))

    def enc(sess, q):
        return encode_with(sess, tokenizer, id_to_token, SPLADE_QUERY_TERMS, q)

    # PIN: replica(baseline) == production encode pipeline
    for q in queries[:5]:
        prod = dict(sorted(encode_splade(q, str(FP32_DIR)).items(),
                           key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        assert enc(sess_base, q) == prod, f"replica drift on {q!r}"
    print("pin: replica == production encode pipeline on 5 queries", flush=True)

    qv_base = [enc(sess_base, q) for q in queries]

    arms = [("fused", FUSED_DIR / "model.onnx", None, None),
            ("fused_gelu", FUSED_GELU_DIR / "model.onnx", None, None),
            ("base_t8", FP32_DIR / "model.onnx", 8, None),
            ("base_t4", FP32_DIR / "model.onnx", 4, None),
            ("base_t2", FP32_DIR / "model.onnx", 2, None),
            ("base_t1", FP32_DIR / "model.onnx", 1, None),
            ("base_nospin", FP32_DIR / "model.onnx", None, "0")]

    def bench_arm(name, model_path, threads, spin):
        sess, init_s = make_session(model_path, threads, spin)
        for q in queries[:20]:            # warm-up, unrecorded
            enc(sess, q), enc(sess_base, q)
        lb, la = [], []
        qv_arm = None
        for p in range(WARM_PASSES):
            cur = []
            for q in queries:
                t0 = time.perf_counter()
                b = enc(sess_base, q)
                lb.append((time.perf_counter() - t0) * 1000.0)
                t0 = time.perf_counter()
                a = enc(sess, q)
                la.append((time.perf_counter() - t0) * 1000.0)
                cur.append(a)
            qv_arm = cur
        n_exact = sum(1 for a, b in zip(qv_arm, qv_base) if a == b)
        row = {"session_init_s": init_s,
               "base_ms_p50_paired": p50(lb),
               "arm_ms": {"p50": p50(la), "p95": p95(la)},
               "speedup_p50": round(p50(lb) / p50(la), 2),
               "qvec_exact": f"{n_exact}/{N_QUERIES}"}
        del sess
        gc.collect()
        return row, qv_arm, n_exact

    rows, qvecs, exact = {}, {}, {}
    for name, mp, th, sp in arms:
        rows[name], qvecs[name], exact[name] = bench_arm(name, mp, th, sp)
        print(f"{name}: {json.dumps(rows[name])}", flush=True)

    # combined arm: fused model at the best thread count, if both levers won
    best_thread_arm = max((a for a in rows if a.startswith("base_t")),
                          key=lambda a: rows[a]["speedup_p50"])
    if (rows["fused"]["speedup_p50"] > 1.0
            and rows[best_thread_arm]["speedup_p50"] > 1.0):
        th = int(best_thread_arm.split("_t")[1])
        name = f"fused_t{th}"
        rows[name], qvecs[name], exact[name] = bench_arm(
            name, FUSED_DIR / "model.onnx", th, None)
        print(f"{name}: {json.dumps(rows[name])}", flush=True)

    # candidates by speed, quality-gated lazily
    order = sorted(rows, key=lambda a: -rows[a]["speedup_p50"])
    gates, seq_leg, winner = {}, {}, None
    be = seq = None
    for name in order:
        if rows[name]["speedup_p50"] < MIN_SPEEDUP:
            break
        if exact[name] == N_QUERIES:
            winner = name          # lossless by construction
            break
        # lossy-numerics arm → served overlap gate + sequential identity
        if be is None:
            from lib.thinclient.sharded_seismic_backend import (
                ParallelSeismicBackend, SequentialSeismicBackend, _load_manifest)
            paths = _load_manifest(str(MANIFEST), load_mode="mmap")
            be = ParallelSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                        load_mode="mmap")
            seq = SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                           load_mode="mmap")
        ov10, ov50, mism = [], [], 0
        for i, v in enumerate(qvecs[name]):
            rb_par = be.search_encoded(v, TOP_K)
            if rb_par != seq.search_encoded(v, TOP_K):
                mism += 1
            rb = [d for d, _s in rb_par]
            ra = [d for d, _s in be.search_encoded(qv_base[i], TOP_K)]
            ov10.append(len(set(ra[:10]) & set(rb[:10])) / 10)
            ov50.append(len(set(ra[:50]) & set(rb[:50])) / 50)
        gates[name] = {"overlap@10_mean": round(statistics.mean(ov10), 4),
                       "overlap@10_min": round(min(ov10), 4),
                       "overlap@50_mean": round(statistics.mean(ov50), 4),
                       "n_queries": N_QUERIES}
        seq_leg[name] = {"mismatches": mism,
                         "verdict": "IDENTICAL" if mism == 0 else "MISMATCH"}
        print(f"gate[{name}]: {json.dumps(gates[name])} "
              f"seq={json.dumps(seq_leg[name])}", flush=True)
        if gates[name]["overlap@10_mean"] >= 0.99 and mism == 0:
            winner = name
            break

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/d2_ort_fusion_matrix.py",
                    "baseline": "production _get_splade_model singleton "
                                "(ORT_ENABLE_ALL, default threads, spinning on), "
                                "models/splade_onnx_fp16",
                    "method": "one arm session co-resident with baseline at a "
                              "time, interleaved per query (D1 lesson)",
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "warm_passes_recorded": WARM_PASSES,
                    "environment": "devcontainer (16 cores, avx2, drvfs); warm-only",
                    "not_tested": "graph_opt_level < ALL (baseline already ALL); "
                                  "optimized_model_filepath (init-time only); "
                                  "fp16/bf16 CPU (no native fp16 on avx2); "
                                  "batching/IOBinding (serving is batch-1)",
                    "bars": f"[qvec exact 100/100 OR (overlap@10 >= 0.99 AND "
                            f"sequential identity 0 mismatches)] AND "
                            f"speedup_p50 > {MIN_SPEEDUP}"},
           "build": build_meta,
           "arms": rows,
           "gates": gates,
           "sequential_identity": seq_leg,
           "flip_verdict": f"FLIP:{winner}" if winner else "KEEP_BASELINE"}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(f"flip_verdict: {res['flip_verdict']}")
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
