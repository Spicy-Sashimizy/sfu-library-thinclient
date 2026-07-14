#!/usr/bin/env python3
"""Q11 C4 PRE-GATE: untrained layer truncation of the served SPLADE encoder
(doc 14 §3 C4). Zero training — ONNX graph surgery only: rewire the MLM head
input from the layer-12 encoder output to layer-k's output and let ORT prune
the dead tail. Measures the overlap-vs-depth curve + encode speedup.

Pre-registered decision rule (one-directional by design):
  - k<=4 untrained overlap@10 >= 0.95 -> C4 distillation STRONG GO
    (distillation only has to close <=0.04).
  - low untrained overlap does NOT kill C4 (KALE: distilled 2-layer retains
    92.5% where raw truncation collapses) — it just means C4 needs the real
    distillation build to be decided, and this pre-gate records the gap.
  - k=12 arm is the harness CONTROL: must be ~1.0 vs the fp32 base (same
    weights), ~0.999 vs served fused (D2's measured fp32-vs-fused gap).
Reference/backends identical to q11_c1c2_stage0 (served fused qvecs,
SequentialSeismicBackend, merged + worst-case shards 1-2, n=100).
Rule Zero: read-only; truncated models go to the session scratchpad.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

import numpy as np  # noqa: E402
import onnx  # noqa: E402

from d2_ort_fusion_matrix import (  # noqa: E402
    FUSED_DIR, FP32_DIR, N_QUERIES, TOP_K, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.opensearch_retriever import _get_splade_model  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    SequentialSeismicBackend, _load_manifest)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
RESULT = REPO / ("data/eval_results/q11_c4_pregate_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")
SCRATCH = Path("/tmp/claude-1000/-workspaces-sfu-library-thinclient/"
               "ecab544f-777d-490d-8c0d-1584b70de5cb/scratchpad")
KS = (4, 8, 12)
HEAD_IN_NODE = "/cls/predictions/transform/dense/MatMul"


def truncate(base_onnx: Path, k: int, out_path: Path):
    """Rewire the MLM head to consume layer-k's encoder output (1-based k)."""
    m = onnx.load(str(base_onnx))
    if k == 12:
        onnx.save(m, str(out_path))
        return
    want = f"/bert/encoder/layer.{k - 1}/output/LayerNorm/LayerNormalization_output_0"
    tensors = {o for n in m.graph.node for o in n.output}
    if want not in tensors:
        cands = sorted(t for t in tensors if f"layer.{k - 1}/output" in t)
        raise RuntimeError(f"layer output tensor not found: {want}; near: {cands}")
    hit = False
    for n in m.graph.node:
        if n.name == HEAD_IN_NODE:
            n.input[0] = want
            hit = True
    if not hit:
        raise RuntimeError(f"head node not found: {HEAD_IN_NODE}")
    onnx.save(m, str(out_path))


def overlap(ra, rb, k):
    return len(set(ra[:k]) & set(rb[:k])) / k


def main():
    t_start = time.time()
    queries = load_queries(N_QUERIES,
                           REPO / "data/eval_results/diverse_queries.json")
    _s, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))
    sess_fused, _ = make_session(FUSED_DIR / "model.onnx", None, None)

    ref_qv, ref_ms = [], []
    for q in queries:
        t0 = time.perf_counter()
        ref_qv.append(encode_with(sess_fused, tokenizer, id_to_token,
                                  SPLADE_QUERY_TERMS, q))
        ref_ms.append((time.perf_counter() - t0) * 1000)

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    backends = {
        "merged": SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard1": SequentialSeismicBackend(paths[1:2], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard2": SequentialSeismicBackend(paths[2:3], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
    }
    ref_top = {name: [[d for d, _s in be.search_encoded(qv, TOP_K)]
                      for qv in ref_qv] for name, be in backends.items()}

    results = {}
    for k in KS:
        mp = SCRATCH / f"splade_trunc_L{k}.onnx"
        truncate(FP32_DIR / "model.onnx", k, mp)
        sess_k, _ = make_session(mp, None, None)
        qvs, enc_ms = [], []
        for q in queries:
            t0 = time.perf_counter()
            qvs.append(encode_with(sess_k, tokenizer, id_to_token,
                                   SPLADE_QUERY_TERMS, q))
            enc_ms.append((time.perf_counter() - t0) * 1000)
        row = {"encode_ms_p50": round(statistics.median(enc_ms), 2),
               "speedup_vs_ref": round(statistics.median(ref_ms)
                                       / statistics.median(enc_ms), 2)}
        for name, be in backends.items():
            o10, o50 = [], []
            for i, qv in enumerate(qvs):
                got = [d for d, _s in be.search_encoded(qv, TOP_K)]
                o10.append(overlap(ref_top[name][i], got, 10))
                o50.append(overlap(ref_top[name][i], got, 50))
            row[name] = {"overlap@10_mean": round(statistics.mean(o10), 4),
                         "overlap@10_min": round(min(o10), 4),
                         "overlap@50_mean": round(statistics.mean(o50), 4)}
        results[f"L{k}"] = row
        print(f"L{k}: merged@10={row['merged']['overlap@10_mean']} "
              f"s1={row['shard1']['overlap@10_mean']} "
              f"s2={row['shard2']['overlap@10_mean']} "
              f"encode {row['encode_ms_p50']}ms ({row['speedup_vs_ref']}x)")

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/q11_c4_pregate.py",
                    "doc": "docs/seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md",
                    "decision_rule": "k<=4 untrained >=0.95 -> C4 STRONG GO; "
                                     "low untrained does NOT kill C4 (KALE); "
                                     "L12 = harness control (~0.999 vs fused)",
                    "reference": "served fused encoder qvecs",
                    "encode_ms_p50_reference": round(statistics.median(ref_ms), 2),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "backend": "SequentialSeismicBackend, e5 manifest"},
           "arms": results}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
