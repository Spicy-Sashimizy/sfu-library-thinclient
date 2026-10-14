#!/usr/bin/env python3
"""Q11-C4 step 4: the pre-registered Stage-0 gate on the distilled student
(doc 11 §Q11-C4; bars inherited doc 14 §4 unchanged).

Exports the student checkpoint to ONNX (the serving shape), then measures
merged 8-shard AND worst-case shards 1-2 overlap@10 vs the served fused
encoder on n=100 diverse queries (overlap@50 recorded as tail check),
SequentialSeismicBackend on the e5 manifest — same harness lineage as
`q11_c4_pregate.py` (L12 control 0.999). Also records the clean encode
speedup (interleaved timing not needed: encode is same-process, same
methodology as the pregate run).

Decision (pre-registered): merged AND shards 1-2 overlap@10 >= 0.99 -> PASS;
[0.97, 0.99) -> one escalation round; else KILL. Recorded, not renegotiated.

Rule Zero: shards read-only; writes only the ONNX export + result JSON.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

import numpy as np  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
import torch  # noqa: E402
from transformers import AutoTokenizer, BertForMaskedLM  # noqa: E402

from d2_ort_fusion_matrix import (  # noqa: E402
    FP32_DIR, FUSED_DIR, N_QUERIES, TOP_K, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    SequentialSeismicBackend, _load_manifest)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
BAR = 0.99
ESCALATION_BAND = 0.97


def export_onnx(model_dir: Path) -> Path:
    out = model_dir / "model.onnx"
    model = BertForMaskedLM.from_pretrained(str(model_dir)).float().eval()
    ids = torch.ones(1, 8, dtype=torch.int64)
    dyn = {0: "batch", 1: "seq"}
    torch.onnx.export(
        model, (ids, torch.ones_like(ids), torch.zeros_like(ids)),
        str(out),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={"input_ids": dyn, "attention_mask": dyn,
                      "token_type_ids": dyn, "logits": dyn},
        opset_version=17)
    return out


def overlap(ra, rb, k):
    return len(set(ra[:k]) & set(rb[:k])) / k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(REPO / "models/sfu-splade-student-l4/best"))
    ap.add_argument("--n", type=int, default=N_QUERIES)
    args = ap.parse_args()

    t_start = time.time()
    model_dir = Path(args.model)
    queries = load_queries(args.n,
                           REPO / "data/eval_results/diverse_queries.json")
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    id_to_token = {v: k for k, v in tokenizer.get_vocab().items()}

    onnx_path = export_onnx(model_dir)
    sess_student, _ = make_session(onnx_path, None, None)
    sess_fused, _ = make_session(FUSED_DIR / "model.onnx", None, None)

    ref_qv, ref_ms = [], []
    stu_qv, stu_ms = [], []
    for q in queries:
        t0 = time.perf_counter()
        ref_qv.append(encode_with(sess_fused, tokenizer, id_to_token,
                                  SPLADE_QUERY_TERMS, q))
        ref_ms.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        stu_qv.append(encode_with(sess_student, tokenizer, id_to_token,
                                  SPLADE_QUERY_TERMS, q))
        stu_ms.append((time.perf_counter() - t0) * 1000)

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    backends = {
        "merged": SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard1": SequentialSeismicBackend(paths[1:2], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
        "shard2": SequentialSeismicBackend(paths[2:3], splade_model_path=str(FP32_DIR),
                                           load_mode="mmap"),
    }
    arms = {}
    for name, be in backends.items():
        o10, o50 = [], []
        for rq, sq in zip(ref_qv, stu_qv):
            ref_top = [d for d, _s in be.search_encoded(rq, TOP_K)]
            got_top = [d for d, _s in be.search_encoded(sq, TOP_K)]
            o10.append(overlap(ref_top, got_top, 10))
            o50.append(overlap(ref_top, got_top, 50))
        arms[name] = {"overlap@10_mean": round(statistics.mean(o10), 4),
                      "overlap@10_min": round(min(o10), 4),
                      "overlap@50_mean": round(statistics.mean(o50), 4),
                      "raw_overlap@10": o10}
        print(f"{name}: @10 {arms[name]['overlap@10_mean']} "
              f"(min {arms[name]['overlap@10_min']}) "
              f"@50 {arms[name]['overlap@50_mean']}", flush=True)

    worst = min(arms[a]["overlap@10_mean"] for a in ("merged", "shard1", "shard2"))
    verdict = ("PASS" if worst >= BAR else
               "ESCALATE" if worst >= ESCALATION_BAND else "KILL")
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/q11_c4_gate_student.py",
                    "doc": "docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q11-C4",
                    "model": str(model_dir), "n_queries": len(queries),
                    "top_k": TOP_K,
                    "bars": {"pass": BAR, "escalation_band": ESCALATION_BAND},
                    "reference": "served fused encoder qvecs",
                    "backend": "SequentialSeismicBackend, e5 manifest",
                    "wall_seconds": round(time.time() - t_start, 1)},
           "encode_ms_p50": {"fused_ref": round(statistics.median(ref_ms), 2),
                             "student": round(statistics.median(stu_ms), 2),
                             "speedup": round(statistics.median(ref_ms)
                                              / statistics.median(stu_ms), 2)},
           "arms": arms, "worst_arm_overlap@10": worst, "verdict": verdict}
    result = REPO / ("data/eval_results/q11_c4_distill_gate_"
                     f"{time.strftime('%Y%m%d_%H%M')}.json")
    result.write_text(json.dumps(res, indent=2))
    print(f"verdict={verdict} worst-arm @10 {worst} "
          f"encode speedup {res['encode_ms_p50']['speedup']}x -> {result}")


if __name__ == "__main__":
    main()
