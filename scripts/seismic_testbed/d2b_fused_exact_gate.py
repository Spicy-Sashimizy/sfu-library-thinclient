#!/usr/bin/env python3
"""D2b: served gate for the exact-GELU `fused` arm (doc 08 §D).

D2's matrix gated arms fastest-first and stopped at `fused_gelu` (1.14x),
which passed with ZERO margin (overlap@10 mean 0.990, bar 0.99). The exact-
GELU `fused` arm (1.11x, 37/100 qvec-exact vs gelu's 0/100) was never gated.
This runs the identical gate for it: federated merged overlap@10/@50 vs
baseline fp32 qvecs + the sequential-method identity leg, n=100, served
defaults. Decision rule: prefer `fused` for the serving flip if it clears
the bar with real margin (>= 0.995) — a ~0.5 ms extra win from gelu-approx
does not justify grazing the quality floor. Rule Zero: read-only.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from d2_ort_fusion_matrix import (  # noqa: E402
    FP32_DIR, FUSED_DIR, MANIFEST, N_QUERIES, TOP_K, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.opensearch_retriever import _get_splade_model  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    ParallelSeismicBackend, SequentialSeismicBackend, _load_manifest)

RESULT = REPO / ("data/eval_results/d2b_fused_exact_gate_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")


def main():
    t_start = time.time()
    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    sess_base, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))
    sess_fused, _init = make_session(FUSED_DIR / "model.onnx", None, None)

    def enc(sess, q):
        return encode_with(sess, tokenizer, id_to_token, SPLADE_QUERY_TERMS, q)

    qv_base = [enc(sess_base, q) for q in queries]
    qv_fused = [enc(sess_fused, q) for q in queries]

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be = ParallelSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                load_mode="mmap")
    seq = SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                   load_mode="mmap")

    ov10, ov50, mism = [], [], 0
    for i in range(N_QUERIES):
        rb_par = be.search_encoded(qv_fused[i], TOP_K)
        if rb_par != seq.search_encoded(qv_fused[i], TOP_K):
            mism += 1
        rb = [d for d, _s in rb_par]
        ra = [d for d, _s in be.search_encoded(qv_base[i], TOP_K)]
        ov10.append(len(set(ra[:10]) & set(rb[:10])) / 10)
        ov50.append(len(set(ra[:50]) & set(rb[:50])) / 50)

    gate = {"overlap@10_mean": round(statistics.mean(ov10), 4),
            "overlap@10_min": round(min(ov10), 4),
            "overlap@50_mean": round(statistics.mean(ov50), 4),
            "n_queries": N_QUERIES}
    seq_leg = {"mismatches": mism,
               "verdict": "IDENTICAL" if mism == 0 else "MISMATCH"}
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/d2b_fused_exact_gate.py",
                    "arm": "fused (offline bert fusion, exact GELU), "
                           "models/splade_onnx_fused",
                    "companion": "d2_ort_fusion_matrix_20260709_0103.json "
                                 "(latency: fused 1.11x, fused_gelu 1.14x)",
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "decision_rule": "prefer fused over fused_gelu for the flip "
                                     "if overlap@10 >= 0.995"},
           "gate": gate, "sequential_identity": seq_leg}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(gate))
    print(json.dumps(seq_leg))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
