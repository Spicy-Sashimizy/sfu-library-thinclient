#!/usr/bin/env python3
"""D1: dynamic-int8 SPLADE query encoder — quantize + gate (doc 08 §D).

G8g (2026-07-08) left encode (~19.5 ms of the 53.8 ms served warm p50) as the
largest single addressable component. Doc 08 §D's candidate is dynamic INT8
quantization of the query-side SPLADE ONNX encoder (house precedent:
`scripts/export_ce_onnx_int8.py`, the cross-encoder int8 export; this host is
AVX2-only — no VNNI — so expect the moderate end of the literature's 1.5–3×).

Discovered en route (recorded): `models/splade_onnx` and
`models/splade_onnx_fp16` are byte-identical (md5 2c54704e…) and BOTH carry
fp32 weights — the "_fp16" name is a misnomer. Serving encode is fp32 today.

§D caveat (load-bearing): the 150M doc vectors were encoded with this fp32
model; quantizing only the QUERY encoder introduces encoder asymmetry. The
gate is therefore on the SERVED merged top-k, not on encoder logits.

Two quantization arms (run 1 of 2026-07-09 measured arm `int8_all` FAIL:
overlap@10 0.791 despite 1.59x encode — full-model dynamic int8 wrecks the
SPLADE term weights):
  - `int8_all`    — every MatMul quantized → models/splade_onnx_int8/
  - `int8_nohead` — the MLM vocab-projection head kept fp32
                    (`/cls/predictions/transform/dense/MatMul` +
                    `/cls/predictions/decoder/MatMul` excluded; the head emits
                    the term weights directly, so it is the largest
                    quantization-error surface) → models/splade_onnx_int8_nohead/

Legs:
  0. Quantize both arms (idempotent; --requantize forces).
  1. PIN — the script's encode replica (fp32 session) must equal the
     production `encode_query` output exactly on 5 queries.
  2. Encode latency — same-process interleaved fp32 vs each arm, batch 1,
     n=100 × 3 recorded passes (tokenize + run + sparsify, the full encode
     wall serving pays). NOTE: co-resident ORT sessions' spinning thread
     pools can inflate ALL arms' absolute walls — the ratio is the deliverable.
  3. Quality gate per arm — federated `search_encoded` (dv shards, mmap,
     served defaults) fp32 qvec vs arm qvec; merged overlap@10/@50, n=100.
  4. SEQUENTIAL serving-method check (both serving classes must be covered):
     `SequentialSeismicBackend` (mechanism A+B, real `release_pages` eviction)
     must return merged top-50 BIT-IDENTICAL to `ParallelSeismicBackend` for
     the same qvec — checked on fp32 qvecs AND the winning arm's qvecs (or
     `int8_nohead` if no winner), time-budgeted (sequential refaults every
     shard each query on this container; n_done is recorded).

Bars (pre-registered, house standard): an arm flips the served encoder
default only if merged overlap@10 mean >= 0.99 at n=100 AND encode
speedup_p50 > 1.0 AND the sequential identity leg has 0 mismatches. No arm
passes -> record, keep fp32, stop.
Rule Zero: read-only over shard dirs; writes only models/splade_onnx_int8*/.
"""
import argparse
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
ARM_DIRS = {"int8_all": REPO / "models/splade_onnx_int8",
            "int8_nohead": REPO / "models/splade_onnx_int8_nohead"}
HEAD_NODES = ["/cls/predictions/transform/dense/MatMul",
              "/cls/predictions/decoder/MatMul"]
MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 100
WARM_PASSES = 3
TOP_K = 50
SEQ_BUDGET_S = 600.0   # wall budget for the sequential identity leg, per qvec set
RESULT = REPO / ("data/eval_results/d1_int8_query_encoder_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")


def quantize(arm: str, out_dir: Path, force: bool) -> dict:
    """fp32 model.onnx -> dynamic int8 per-channel (AVX2 config) model.onnx."""
    out = out_dir / "model.onnx"
    if out.exists() and not force:
        print(f"{arm}: already at {out} (use --requantize to rebuild)")
        return {"quantized": "skipped (exists)"}
    from optimum.onnxruntime import ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig
    t0 = time.time()
    quantizer = ORTQuantizer.from_pretrained(str(FP32_DIR), file_name="model.onnx")
    qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=True)
    if arm == "int8_nohead":
        qconfig.nodes_to_exclude = list(HEAD_NODES)
    quantizer.quantize(save_dir=str(out_dir), quantization_config=qconfig)
    (out_dir / "model_quantized.onnx").rename(out)
    if not (out_dir / "config.json").exists():
        shutil.copy2(FP32_DIR / "config.json", out_dir / "config.json")
    (out_dir / ".export_complete").write_text(
        f"{time.strftime('%Y-%m-%d')} dynamic int8 per-channel (avx2) of "
        f"models/splade_onnx_fp16/model.onnx, arm={arm} "
        f"(nodes_to_exclude={HEAD_NODES if arm == 'int8_nohead' else []}) via "
        f"scripts/seismic_testbed/d1_int8_query_encoder.py\n")
    return {"quantized": "built",
            "int8_mb": round(out.stat().st_size / 1e6, 1),
            "quantize_seconds": round(time.time() - t0, 1)}


def encode_with(session, tokenizer, id_to_token, n_terms, text):
    """Replica of `opensearch_retriever.encode_splade` + the backend's
    `encode_query` top-`SPLADE_QUERY_TERMS` truncation (pinned in leg 1)."""
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


def p50(xs):
    return round(statistics.median(xs), 2)


def p95(xs):
    xs = sorted(xs)
    return round(xs[int(round(0.95 * (len(xs) - 1)))], 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requantize", action="store_true")
    args = ap.parse_args()
    t_start = time.time()

    quant_meta = {arm: quantize(arm, d, args.requantize)
                  for arm, d in ARM_DIRS.items()}

    import onnxruntime as ort
    from e6_forward_codec_proto import load_queries
    import lib.opensearch_retriever  # noqa: F401  torch first (ENOMEM lesson)
    from lib.opensearch_retriever import _get_splade_model
    from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend, _load_manifest)

    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be = ParallelSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                load_mode="mmap")

    # fp32 arm = the PRODUCTION session/tokenizer singleton; int8 arms differ
    # only in the InferenceSession.
    sess_fp32, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))
    sessions = {"fp32": sess_fp32}
    for arm, d in ARM_DIRS.items():
        sessions[arm] = ort.InferenceSession(str(d / "model.onnx"),
                                             providers=["CPUExecutionProvider"])

    def enc(arm, q):
        return encode_with(sessions[arm], tokenizer, id_to_token,
                           SPLADE_QUERY_TERMS, q)

    # 1. PIN
    for q in queries[:5]:
        assert enc("fp32", q) == be.encode_query(q), f"replica drift on {q!r}"
    print("pin: replica == production encode_query on 5 queries", flush=True)

    # 2. encode latency (interleaved; warm-up pass unrecorded)
    all_arms = list(sessions)
    for q in queries:
        for a in all_arms:
            enc(a, q)
    lat = {a: [] for a in all_arms}
    for p in range(1, WARM_PASSES + 1):
        for q in queries:
            for a in all_arms:
                t0 = time.perf_counter()
                enc(a, q)
                lat[a].append((time.perf_counter() - t0) * 1000.0)
        print(f"latency pass {p} done", flush=True)
    latency = {a: {"p50": p50(lat[a]), "p95": p95(lat[a])} for a in all_arms}
    for a in ARM_DIRS:
        latency[a]["speedup_p50"] = round(latency["fp32"]["p50"] / latency[a]["p50"], 2)
    print(json.dumps(latency), flush=True)

    # 3. quality gate per arm (parallel backend), reusing fp32 qvecs + results
    qv = {a: [enc(a, q) for q in queries] for a in all_arms}
    res_fp32 = [[d for d, _s in be.search_encoded(v, TOP_K)] for v in qv["fp32"]]
    gates = {}
    for a in ARM_DIRS:
        ov10, ov50, jac, mae = [], [], [], []
        for i, v in enumerate(qv[a]):
            shared = set(qv["fp32"][i]) & set(v)
            jac.append(len(shared) / max(1, len(set(qv["fp32"][i]) | set(v))))
            if shared:
                mae.append(statistics.mean(
                    abs(qv["fp32"][i][t] - v[t]) for t in shared))
            rb = [d for d, _s in be.search_encoded(v, TOP_K)]
            ov10.append(len(set(res_fp32[i][:10]) & set(rb[:10])) / 10)
            ov50.append(len(set(res_fp32[i][:50]) & set(rb[:50])) / 50)
        gates[a] = {"overlap@10_mean": round(statistics.mean(ov10), 4),
                    "overlap@10_min": round(min(ov10), 4),
                    "overlap@50_mean": round(statistics.mean(ov50), 4),
                    "qvec_top64_jaccard_mean": round(statistics.mean(jac), 4),
                    "qvec_weight_mae_shared_terms": round(statistics.mean(mae), 5),
                    "n_queries": N_QUERIES}
        print(f"{a}: {json.dumps(gates[a])}", flush=True)

    passing = [a for a in ARM_DIRS
               if gates[a]["overlap@10_mean"] >= 0.99
               and latency[a]["speedup_p50"] > 1.0]
    candidate = (sorted(passing, key=lambda a: (-gates[a]["overlap@10_mean"],
                                                latency[a]["p50"]))[0]
                 if passing else "int8_nohead")

    # 4. sequential serving-method identity (mechanism A+B, release_pages)
    seq = SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                   load_mode="mmap")
    seq_leg = {}
    for label in ("fp32", candidate):
        mism, n_done, t0 = 0, 0, time.time()
        for i, v in enumerate(qv[label]):
            if time.time() - t0 > SEQ_BUDGET_S:
                break
            par_r = be.search_encoded(v, TOP_K)
            seq_r = seq.search_encoded(v, TOP_K)
            n_done += 1
            if par_r != seq_r:
                mism += 1
        seq_leg[label] = {"n_done": n_done, "mismatches": mism,
                          "wall_s": round(time.time() - t0, 1),
                          "verdict": "IDENTICAL" if mism == 0 else "MISMATCH"}
        print(f"sequential[{label}]: {json.dumps(seq_leg[label])}", flush=True)

    flip = (passing and candidate in passing
            and seq_leg.get(candidate, {}).get("mismatches", 1) == 0
            and seq_leg.get("fp32", {}).get("mismatches", 1) == 0)
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/d1_int8_query_encoder.py",
                    "quantization": "dynamic int8 per-channel, "
                                    "AutoQuantizationConfig.avx2 (host has no VNNI); "
                                    "int8_nohead excludes the MLM head "
                                    f"({HEAD_NODES})",
                    "source_model": "models/splade_onnx_fp16 (fp32 weights; "
                                    "byte-identical to models/splade_onnx, "
                                    "md5 2c54704e3cb76cb7122587be6b82cfc0)",
                    "backend": "ParallelSeismicBackend + SequentialSeismicBackend "
                               "(load_mode=mmap), dv manifest, served defaults "
                               "(k'=100, heap_factor=0.8)",
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "warm_passes_recorded": WARM_PASSES,
                    "seq_budget_s": SEQ_BUDGET_S,
                    "environment": "devcontainer (16 cores, avx2, drvfs); warm-only",
                    "bars": "overlap@10 mean >= 0.99 AND encode speedup_p50 > 1.0 "
                            "AND sequential identity 0 mismatches -> flip served "
                            "encoder default"},
           "quantize": quant_meta,
           "encode_latency": latency,
           "gates": gates,
           "sequential_identity": seq_leg,
           "candidate": candidate,
           "flip_verdict": f"FLIP:{candidate}" if flip else "KEEP_FP32"}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(f"flip_verdict: {res['flip_verdict']}")
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
