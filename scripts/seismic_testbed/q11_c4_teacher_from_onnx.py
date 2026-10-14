#!/usr/bin/env python3
"""Q11-C4 step 1: reconstruct the served 12-layer SPLADE encoder as a torch
`BertForMaskedLM` teacher from the ONNX export's initializers (doc 11
§Q11-C4, pre-registered 2026-07-28).

Source = `models/splade_onnx_fp16/model.onnx` — misnamed dir: all 203
initializers are fp32 (verified 2026-07-28); this is the D2/pregate "fp32
base" whose truncation harness measured L12 control 0.999. The export
preserves HF parameter names, so weight transfer is a name-matched state-dict
load (2-D tensors transposed when the export stored the MatMul layout).

MANDATORY parity gate before any training (doc 11 §Q11-C4 method): encode
n=100 diverse queries with the ONNX CPU session vs the torch model, compare
full sparse vectors in log1p-ReLU-maxpool space (the serving space) + the
top-64 serve-shape term sets. Bars (pre-registered here, recorded in the
result JSON): max|Δ| over all vocab dims ≤ 1e-3 AND mean top-64 term-set
overlap ≥ 0.999. FAIL → do not train on this teacher.

Rule Zero: read-only on all inputs; writes only models/sfu-splade-teacher-torch/
and the result JSON.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

import numpy as np  # noqa: E402
import onnx  # noqa: E402
from onnx import numpy_helper  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
import torch  # noqa: E402
from transformers import AutoTokenizer, BertConfig, BertForMaskedLM  # noqa: E402

from d2_ort_fusion_matrix import (  # noqa: E402
    FP32_DIR, N_QUERIES, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402
from lib.opensearch_retriever import _resolve_tokenizer_dir  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402

OUT_DIR = REPO / "models/sfu-splade-teacher-torch"
RESULT = REPO / ("data/eval_results/q11_c4_teacher_parity_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")
MAX_ABS_BAR = 1e-3
TERM_OVERLAP_BAR = 0.999


def build_teacher():
    onnx_path = FP32_DIR / "model.onnx"
    m = onnx.load(str(onnx_path))
    onnx_tensors = {i.name: numpy_helper.to_array(i) for i in m.graph.initializer}

    # Linear weights are anonymous initializers (onnx::MatMul_*); recover their
    # param names from the exporting module path kept in the MatMul node name
    # (e.g. /bert/encoder/layer.0/attention/self/query/MatMul -> ...query.weight).
    matmul_params = set()
    for node in m.graph.node:
        if node.op_type != "MatMul" or not node.name.endswith("/MatMul"):
            continue
        w = node.input[1]
        if w not in onnx_tensors:
            continue
        pname = node.name[1:-len("/MatMul")].replace("/", ".") + ".weight"
        if pname not in onnx_tensors:
            # MatMul stores (in, out) = torch weight.T — ALWAYS transpose,
            # shape comparison cannot catch the square 768x768 attention mats
            onnx_tensors[pname] = onnx_tensors[w].T
            matmul_params.add(pname)

    cfg = BertConfig.from_json_file(str(FP32_DIR / "config.json"))
    cfg.dtype = None  # config says float16; the initializers are fp32
    model = BertForMaskedLM(cfg)
    model = model.float()
    sd = model.state_dict()

    loaded, transposed, missing = [], [], []
    new_sd = {}
    for name, ref in sd.items():
        if name in onnx_tensors:
            arr = onnx_tensors[name]
        elif name == "cls.predictions.decoder.weight" and \
                "bert.embeddings.word_embeddings.weight" in onnx_tensors:
            arr = onnx_tensors["bert.embeddings.word_embeddings.weight"]  # tied
        elif name == "cls.predictions.decoder.bias" and \
                "cls.predictions.bias" in onnx_tensors:
            arr = onnx_tensors["cls.predictions.bias"]  # tied
        elif name.endswith("position_ids"):
            new_sd[name] = ref
            continue
        else:
            missing.append(name)
            continue
        t = torch.from_numpy(np.ascontiguousarray(arr))
        if t.shape != ref.shape:
            if t.ndim == 2 and t.T.shape == ref.shape:
                t = t.T.contiguous()
                transposed.append(name)
            else:
                raise RuntimeError(f"shape mismatch {name}: onnx {tuple(t.shape)} "
                                   f"vs torch {tuple(ref.shape)}")
        new_sd[name] = t.to(ref.dtype)
        loaded.append(name)

    if missing:
        raise RuntimeError(f"unmapped torch params: {missing}")
    unused = sorted(set(onnx_tensors) - set(loaded))
    model.load_state_dict(new_sd)
    model.tie_weights()
    model.eval()
    return model, {"loaded": len(loaded), "transposed": transposed,
                   "onnx_inits_unused": unused,
                   "source_onnx": str(onnx_path.relative_to(REPO))}


@torch.no_grad()
def torch_qvec(model, tokenizer, text, device):
    enc = tokenizer([text], max_length=512, truncation=True, padding=True,
                    return_tensors="pt").to(device)
    logits = model(**enc).logits[0]  # (seq, vocab)
    return torch.log1p(torch.relu(logits)).max(dim=0).values.cpu().numpy()


def main():
    t_start = time.time()
    queries = load_queries(N_QUERIES,
                           REPO / "data/eval_results/diverse_queries.json")
    tok_dir = _resolve_tokenizer_dir(str(FP32_DIR))
    tokenizer = AutoTokenizer.from_pretrained(str(tok_dir))
    id_to_token = {v: k for k, v in tokenizer.get_vocab().items()}

    model, transfer_meta = build_teacher()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)

    sess, _ = make_session(FP32_DIR / "model.onnx", None, None)

    max_abs, term_overlaps = [], []
    for q in queries:
        enc = tokenizer([q], max_length=512, truncation=True, padding=True,
                        return_tensors="np")
        feeds = {"input_ids": enc["input_ids"].astype(np.int64),
                 "attention_mask": enc["attention_mask"].astype(np.int64),
                 "token_type_ids": enc.get(
                     "token_type_ids",
                     np.zeros_like(enc["input_ids"])).astype(np.int64)}
        ref_vec = np.log1p(np.maximum(sess.run(["logits"], feeds)[0][0], 0.0)).max(axis=0)
        got_vec = torch_qvec(model, tokenizer, q, device)
        max_abs.append(float(np.abs(ref_vec - got_vec).max()))

        ref_terms = set(encode_with(sess, tokenizer, id_to_token,
                                    SPLADE_QUERY_TERMS, q))
        nz = np.nonzero(got_vec)[0]
        order = nz[np.argsort(-got_vec[nz])]
        got_terms = []
        for idx in order:
            tok = id_to_token.get(int(idx), "")
            if not tok or tok.startswith("[") or got_vec[int(idx)] <= 0.0:
                continue
            got_terms.append(tok)
            if len(got_terms) == SPLADE_QUERY_TERMS:
                break
        denom = max(len(ref_terms), 1)
        term_overlaps.append(len(ref_terms & set(got_terms)) / denom)

    max_abs_all = max(max_abs)
    mean_overlap = float(np.mean(term_overlaps))
    verdict = "PASS" if (max_abs_all <= MAX_ABS_BAR
                         and mean_overlap >= TERM_OVERLAP_BAR) else "FAIL"

    if verdict == "PASS":
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        model.cpu().save_pretrained(str(OUT_DIR))
        tokenizer.save_pretrained(str(OUT_DIR))
        (OUT_DIR / ".provenance").write_text(
            f"{time.strftime('%Y-%m-%d')} reconstructed from "
            f"{transfer_meta['source_onnx']} by "
            "scripts/seismic_testbed/q11_c4_teacher_from_onnx.py; "
            f"parity {RESULT.name}\n")

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/q11_c4_teacher_from_onnx.py",
                    "doc": "docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md §Q11-C4",
                    "n_queries": len(queries), "device": device,
                    "bars": {"max_abs_logspace": MAX_ABS_BAR,
                             "mean_top64_term_overlap": TERM_OVERLAP_BAR},
                    "tokenizer_dir": str(tok_dir),
                    "wall_seconds": round(time.time() - t_start, 1)},
           "transfer": transfer_meta,
           "parity": {"max_abs_logspace": max_abs_all,
                      "max_abs_p50": float(np.median(max_abs)),
                      "mean_top64_term_overlap": mean_overlap,
                      "min_top64_term_overlap": float(min(term_overlaps))},
           "verdict": verdict,
           "teacher_dir": str(OUT_DIR.relative_to(REPO)) if verdict == "PASS" else None}
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["parity"], indent=2))
    print(f"verdict={verdict}  result -> {RESULT}")


if __name__ == "__main__":
    main()
