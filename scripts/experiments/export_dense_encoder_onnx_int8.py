#!/usr/bin/env python3
"""Export the v5 dense query encoder to ONNX + dynamic int8, and benchmark it
against the torch-CPU baseline.

Why: the dense warm cache CPU-encodes every surfaced doc on the serving host
(~87 docs/s at batch 32, docs/DENSE_WARMCACHE_RESEARCH.md), and the same v5
bi-encoder encodes every dense query. int8 ONNX was the last unmeasured item of
that doc's "Deferred to v2" list. Structure mirrors export_ce_onnx_int8.py (the
cross-encoder equivalent) exactly.

The model is models/sfu-academic-embed-v5 (BertModel, 12L/384h) served through
sentence-transformers with CLS pooling + L2 normalize (1_Pooling/config.json:
pooling_mode=cls; 2_Normalize). The ONNX path reproduces that pooling by hand,
so parity is measured against the real serving transform, not raw logits.

Measures (records to data/eval_results/):
  * batch=1 and batch=32 CPU encode latency + throughput, torch fp32 vs ONNX
    int8, with intra-op threads pinned explicitly on both sides
  * embedding parity: mean/min cosine similarity of the L2-normalized vectors
    (this is the quantity the dense leg actually ranks with) plus top-k
    neighbour agreement on the benchmark texts

Serving: models/sfu-academic-embed-v5-onnx-int8 is consumed by the
`SFU_DENSE_ENCODER_ONNX=1` gate in source/lib/thinclient/dense_cache.py
(default OFF; docs/ENV_GATES.md).

Usage:
  .venv/bin/python3 scripts/experiments/export_dense_encoder_onnx_int8.py \
      [--model DIR] [--out DIR] [--texts N] [--threads N] [--skip-export]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = str(REPO / "models/sfu-academic-embed-v5")
OUT_DIR = str(REPO / "models/sfu-academic-embed-v5-onnx-int8")
RESULTS_DIR = str(REPO / "data/eval_results")
MAX_LEN = 256


def _texts(n: int) -> list[str]:
    """Realistic warm-cache encode inputs: academic title + abstract head."""
    base = [
        "Transformer models for protein structure prediction. AlphaFold2 uses "
        "attention over multiple sequence alignments to predict 3D folds.",
        "Carbon capture using metal organic frameworks. Porous MOFs show high "
        "CO2 uptake and selectivity for post-combustion capture.",
        "Reinforcement learning for robotic manipulation. Sim-to-real transfer "
        "of dexterous grasping policies with domain randomization.",
        "Social determinants of mental health in adolescents. A longitudinal "
        "cohort study linking socioeconomic status to depression in teens.",
        "Quantum error correction with surface codes. Threshold theorems and "
        "decoding of topological codes under circuit-level noise.",
        "CRISPR off-target effects in gene therapy. Genome-wide profiling of "
        "Cas9 cleavage at mismatched target sites in primary cells.",
        "Federated learning privacy guarantees. Differential privacy bounds "
        "for gradient aggregation across distributed clients.",
        "Machine translation for low resource languages. Cross-lingual "
        "pretraining and back-translation for under-resourced NMT.",
    ]
    return [f"{base[i % len(base)]} (record {i})" for i in range(n)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_DIR)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--texts", type=int, default=64)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args()

    import numpy as np
    import onnxruntime as ort
    import torch
    from transformers import AutoModel, AutoTokenizer

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    torch.set_num_threads(args.threads)
    tok = AutoTokenizer.from_pretrained(args.model)
    texts = _texts(args.texts)

    if not args.skip_export:
        from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig

        # --- 1. export fp32 ONNX ---
        print(f">> exporting {args.model} -> ONNX (fp32) ...")
        ort_fp32 = ORTModelForFeatureExtraction.from_pretrained(
            args.model, export=True)
        ort_fp32.save_pretrained(args.out)
        tok.save_pretrained(args.out)

        # --- 2. dynamic int8 (AVX2; this host has no avx512_vnni) ---
        print(">> quantizing -> dynamic int8 (avx2) ...")
        quantizer = ORTQuantizer.from_pretrained(args.out)
        qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=True)
        quantizer.quantize(save_dir=args.out, quantization_config=qconfig)

    # --- 3. sessions with explicit intra-op threads (both engines) ---
    def _session(fname: str):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = args.threads
        opts.inter_op_num_threads = 1
        return ort.InferenceSession(os.path.join(args.out, fname), opts,
                                    providers=["CPUExecutionProvider"])

    sess_int8 = _session("model_quantized.onnx")
    in_names = {i.name for i in sess_int8.get_inputs()}
    torch_model = AutoModel.from_pretrained(args.model).eval()

    def _tok(batch):
        return tok(list(batch), padding=True, truncation=True,
                   max_length=MAX_LEN, return_tensors="np")

    def _norm(v):
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)

    def torch_embed(batch):
        enc = _tok(batch)
        with torch.no_grad():
            out = torch_model(**{k: torch.from_numpy(v.astype("int64"))
                                 for k, v in enc.items()}).last_hidden_state
        return _norm(out[:, 0, :].cpu().numpy().astype(np.float32))

    def onnx_embed(batch):
        enc = _tok(batch)
        feed = {k: v.astype(np.int64) for k, v in enc.items()
                if k in in_names}
        out = np.asarray(sess_int8.run(None, feed)[0], dtype=np.float32)
        cls = out[:, 0, :] if out.ndim == 3 else out
        return _norm(cls)

    # --- 4. parity against the sentence-transformers reference ---
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer(args.model, device="cpu")
    st_vecs = np.asarray(st.encode(texts, batch_size=32,
                                   normalize_embeddings=True,
                                   show_progress_bar=False), dtype=np.float32)
    t_vecs = torch_embed(texts)
    o_vecs = onnx_embed(texts)
    cos_to = (t_vecs * o_vecs).sum(1)
    cos_st_t = (st_vecs * t_vecs).sum(1)
    cos_st_o = (st_vecs * o_vecs).sum(1)
    sim_t = t_vecs @ t_vecs.T
    sim_o = o_vecs @ o_vecs.T
    k = min(5, len(texts) - 1)
    agree = [len(set(np.argsort(-sim_t[i])[1:k + 1])
                 & set(np.argsort(-sim_o[i])[1:k + 1])) / k
             for i in range(len(texts))]
    # _texts() repeats 8 base topics, so most neighbours are near-duplicate
    # ties and the all-texts number above is pessimistic by construction.
    # Repeat it over one text per topic, where the ranking is real.
    seen, uniq = set(), []
    for i, t in enumerate(texts):
        head = t.split(".")[0]
        if head not in seen:
            seen.add(head)
            uniq.append(i)
    ku = max(1, min(3, len(uniq) - 1))
    su_t, su_o = sim_t[np.ix_(uniq, uniq)], sim_o[np.ix_(uniq, uniq)]
    agree_u = [len(set(np.argsort(-su_t[i])[1:ku + 1])
                   & set(np.argsort(-su_o[i])[1:ku + 1])) / ku
               for i in range(len(uniq))]

    # --- 5. latency at the two serving shapes ---
    def bench(fn, bsize: int) -> dict:
        batches = [texts[i:i + bsize] for i in range(0, len(texts), bsize)]
        batches = [b for b in batches if len(b) == bsize] or [texts[:bsize]]
        for _ in range(args.warmup):
            fn(batches[0])
        lat = []
        for _ in range(args.iters):
            for b in batches:
                t0 = time.perf_counter()
                fn(b)
                lat.append((time.perf_counter() - t0) * 1000.0)
        lat.sort()
        mean = statistics.mean(lat)
        return {"batch": bsize, "n": len(lat),
                "p50_ms": round(statistics.median(lat), 3),
                "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 3),
                "mean_ms": round(mean, 3),
                "docs_per_s": round(bsize * 1000.0 / mean, 1)}

    latency = {}
    for bsize in (1, 32):
        print(f">> benchmarking torch fp32 batch={bsize} ...")
        bt = bench(torch_embed, bsize)
        print(f">> benchmarking onnx int8 batch={bsize} ...")
        bo = bench(onnx_embed, bsize)
        latency[f"batch_{bsize}"] = {
            "torch_fp32": bt, "onnx_int8": bo,
            "speedup_mean": round(bt["mean_ms"] / bo["mean_ms"], 2),
            "speedup_p50": round(bt["p50_ms"] / bo["p50_ms"], 2)}

    def fsize(path, name):
        p = os.path.join(path, name)
        return round(os.path.getsize(p) / 1e6, 1) if os.path.exists(p) else None

    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": "v5 dense encoder (CLS pool + L2 norm): torch fp32 CPU vs "
                "dynamic-int8 ONNX — encode latency + embedding parity",
        "model": args.model,
        "out": args.out,
        "host": {"cpu_count": os.cpu_count(), "intra_op_threads": args.threads,
                 "torch_threads": torch.get_num_threads(), "isa": "avx2",
                 "quant": "dynamic int8 per-channel",
                 "loadavg_1_5_15": [round(v, 2) for v in os.getloadavg()]},
        "n_texts": len(texts),
        "max_len": MAX_LEN,
        "size_mb": {
            "torch_safetensors": fsize(args.model, "model.safetensors"),
            "onnx_fp32": fsize(args.out, "model.onnx"),
            "onnx_int8": fsize(args.out, "model_quantized.onnx")},
        "embedding_parity": {
            "cosine_torch_vs_int8": {
                "mean": round(float(cos_to.mean()), 6),
                "min": round(float(cos_to.min()), 6)},
            "cosine_st_vs_torch": {
                "mean": round(float(cos_st_t.mean()), 6),
                "min": round(float(cos_st_t.min()), 6)},
            "cosine_st_vs_int8": {
                "mean": round(float(cos_st_o.mean()), 6),
                "min": round(float(cos_st_o.min()), 6)},
            f"neighbour_top{k}_agreement_all_texts": round(float(np.mean(agree)), 4),
            f"neighbour_top{ku}_agreement_distinct_topics": round(
                float(np.mean(agree_u)), 4),
            "distinct_topics": len(uniq)},
        "latency": latency,
        "note": "Latency + embedding parity only. Retrieval-quality parity "
                "(nDCG) is NOT measured here; the dense leg is default OFF "
                "(SFU_DENSE_LEG, ablation DROP 2026-08-18).",
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = os.path.join(RESULTS_DIR, f"dense_encoder_onnx_int8_bench_{stamp}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\n>> results -> {path}")


if __name__ == "__main__":
    main()
