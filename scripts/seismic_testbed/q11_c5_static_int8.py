#!/usr/bin/env python3
"""Q11 C5: static-calibrated int8 of the served SPLADE encoder (doc 14 §3).

D1 killed DYNAMIC int8 (merged overlap@10 0.79 — encoder asymmetry vs the
fp32-encoded corpus). Static quantization with real-query calibration is the
one unmeasured cheap variant: activations get fixed scales from calibration
data instead of per-batch dynamic ranges. Honest prior: thin (same asymmetry
class); this run closes the question either way.

Calibration set: the 120 sfu_eval_queries (DISTINCT from the 100
diverse_queries eval set). Gate identical to q11_c1c2_stage0 / c4_pregate:
merged + shards 1-2 overlap@10 vs served fused qvecs, n=100,
SequentialSeismicBackend. Bars: >=0.99 all three -> PASS (ship-gate next);
else KILL (and the cheap tier of Q11 is exhausted). Rule Zero: read-only;
the quantized model goes to the session scratchpad.
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
from onnxruntime.quantization import (  # noqa: E402
    CalibrationDataReader, QuantFormat, QuantType, quantize_static)
from onnxruntime.quantization.shape_inference import quant_pre_process  # noqa: E402

from d2_ort_fusion_matrix import (  # noqa: E402
    FUSED_DIR, FP32_DIR, N_QUERIES, TOP_K, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.opensearch_retriever import _get_splade_model  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    SequentialSeismicBackend, _load_manifest)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
RESULT = REPO / ("data/eval_results/q11_c5_static_int8_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")
SCRATCH = Path("/tmp/claude-1000/-workspaces-sfu-library-thinclient/"
               "ecab544f-777d-490d-8c0d-1584b70de5cb/scratchpad")
CALIB_QUERIES = REPO / "data/sfu_eval_queries.json"


class QueryReader(CalibrationDataReader):
    def __init__(self, tokenizer, texts):
        self.feeds = []
        for t in texts:
            enc = tokenizer([t], max_length=512, truncation=True, padding=True,
                            return_tensors="np")
            ii = enc["input_ids"].astype(np.int64)
            self.feeds.append({
                "input_ids": ii,
                "attention_mask": enc["attention_mask"].astype(np.int64),
                "token_type_ids": enc.get("token_type_ids",
                                          np.zeros_like(ii)).astype(np.int64)})
        self.it = iter(self.feeds)

    def get_next(self):
        return next(self.it, None)


def overlap(ra, rb, k):
    return len(set(ra[:k]) & set(rb[:k])) / k


def main():
    t_start = time.time()
    queries = load_queries(N_QUERIES,
                           REPO / "data/eval_results/diverse_queries.json")
    calib = [q["query"] for q in json.loads(CALIB_QUERIES.read_text())]
    _s, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))
    sess_fused, _ = make_session(FUSED_DIR / "model.onnx", None, None)

    pre = SCRATCH / "splade_preproc.onnx"
    qmodel = SCRATCH / "splade_static_int8.onnx"
    t0 = time.time()
    # symbolic shape inference dies on this graph ("Incomplete symbolic
    # shape inference", 2026-07-10) — basic ONNX shape inference suffices
    quant_pre_process(str(FP32_DIR / "model.onnx"), str(pre),
                      skip_symbolic_shape=True)
    quantize_static(str(pre), str(qmodel),
                    QueryReader(tokenizer, calib),
                    quant_format=QuantFormat.QDQ,
                    activation_type=QuantType.QInt8,
                    weight_type=QuantType.QInt8,
                    per_channel=True)
    quant_secs = round(time.time() - t0, 1)
    print(f"static int8 quantized in {quant_secs}s (calib n={len(calib)})")

    sess_q, _ = make_session(qmodel, None, None)

    ref_qv, ref_ms, q_qv, q_ms = [], [], [], []
    for q in queries:
        t0 = time.perf_counter()
        ref_qv.append(encode_with(sess_fused, tokenizer, id_to_token,
                                  SPLADE_QUERY_TERMS, q))
        ref_ms.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        q_qv.append(encode_with(sess_q, tokenizer, id_to_token,
                                SPLADE_QUERY_TERMS, q))
        q_ms.append((time.perf_counter() - t0) * 1000)

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    backends = {
        "merged": SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard1": SequentialSeismicBackend(paths[1:2], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard2": SequentialSeismicBackend(paths[2:3], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
    }
    row = {"encode_ms_p50": round(statistics.median(q_ms), 2),
           "speedup_vs_ref": round(statistics.median(ref_ms)
                                   / statistics.median(q_ms), 2)}
    for name, be in backends.items():
        ref_top = [[d for d, _s in be.search_encoded(qv, TOP_K)] for qv in ref_qv]
        o10, o50 = [], []
        for i, qv in enumerate(q_qv):
            got = [d for d, _s in be.search_encoded(qv, TOP_K)]
            o10.append(overlap(ref_top[i], got, 10))
            o50.append(overlap(ref_top[i], got, 50))
        row[name] = {"overlap@10_mean": round(statistics.mean(o10), 4),
                     "overlap@10_min": round(min(o10), 4),
                     "overlap@50_mean": round(statistics.mean(o50), 4)}
    m, s1, s2 = (row["merged"]["overlap@10_mean"],
                 row["shard1"]["overlap@10_mean"],
                 row["shard2"]["overlap@10_mean"])
    row["verdict"] = "PASS" if min(m, s1, s2) >= 0.99 else "KILL"
    print(f"c5_static_int8: merged@10={m} s1={s1} s2={s2} "
          f"encode {row['encode_ms_p50']}ms ({row['speedup_vs_ref']}x) "
          f"-> {row['verdict']}")

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/q11_c5_static_int8.py",
                    "doc": "docs/seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md",
                    "bars": "PASS iff merged AND shard1 AND shard2 "
                            "overlap@10 >= 0.99 (n=100); else KILL — closes "
                            "the cheap tier of Q11",
                    "calibration": f"{len(calib)} sfu_eval_queries (distinct "
                                   "from the diverse_queries eval set)",
                    "quant": "QDQ, per-channel, int8 weights+activations",
                    "quant_seconds": quant_secs,
                    "reference": "served fused encoder qvecs",
                    "encode_ms_p50_reference": round(statistics.median(ref_ms), 2),
                    "timing_caveat": "encode timings contended (Q7-Q9 session "
                                     "benches running on this container)",
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "backend": "SequentialSeismicBackend, e5 manifest"},
           "arm": row}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
