#!/usr/bin/env python3
"""Q11 Stage-0: C1 expansion-table + C2 static-weight lookup query encoders
(doc 14 §3-4). Zero training; both candidates are derivatives of the SERVED
fused encoder (same space by construction).

C1 (expansion-table distill): precompute the served model's expansion vector
for every vocab token (single-token forward passes, one-time); a query vector
is the elementwise aggregate of its tokens' rows (both `max` — SPLADE's pool —
and `sum` are measured), cut to the served top-64 convention.
C2 (static-weight lookup, no expansion): query terms = the query's own tokens,
weight = each token's SELF-weight from its C1 row (a model-derived static
"learned-IDF" scalar; mechanism class = OpenSearch doc-only lookup, minus
their joint training). NOTE deviation from doc 14 §3: corpus-IDF weights are
deferred (no cheap df source per SPLADE-vocab term); the self-weight variant
brackets the same question — expansion vs none.

Gate (pre-registered, doc 14 §4): merged federated overlap@10 vs the served
fp32/fused qvecs >= 0.99 AND shards 1-2 each >= 0.99 at n=100 -> PASS
(candidate advances to the served ship-gate). 0.97-0.99 -> ESCALATE to C3
(learned scalar head). < 0.97 -> the lookup family is weak; C4 territory.
Backend: SequentialSeismicBackend (bit-identical to parallel per T1; ~1-shard
resident so this can run alongside the Q7-Q9 session). Rule Zero: read-only.
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

from d2_ort_fusion_matrix import (  # noqa: E402
    FUSED_DIR, FP32_DIR, N_QUERIES, TOP_K, encode_with, make_session)
from e6_forward_codec_proto import load_queries  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.opensearch_retriever import _get_splade_model  # noqa: E402
from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS  # noqa: E402
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    SequentialSeismicBackend, _load_manifest)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
RESULT = REPO / ("data/eval_results/q11_c1c2_stage0_"
                 f"{time.strftime('%Y%m%d_%H%M')}.json")
TABLE_CACHE = REPO / "data/eval_results/_q11_expansion_table_fused.npz"
TOP_E = 256          # expansion entries kept per vocab row (table size lever)
BATCH = 128


def build_table(sess, tokenizer, vocab_size):
    """Expansion row per vocab token: [CLS] tok [SEP] through the served
    model, SPLADE pool over positions, top-TOP_E entries kept."""
    cls_id = tokenizer.cls_token_id
    sep_id = tokenizer.sep_token_id
    idx_rows, val_rows = [], []
    t0 = time.time()
    for start in range(0, vocab_size, BATCH):
        ids = np.arange(start, min(start + BATCH, vocab_size))
        n = ids.size
        input_ids = np.stack([np.full(n, cls_id), ids, np.full(n, sep_id)],
                             axis=1).astype(np.int64)
        feeds = {"input_ids": input_ids,
                 "attention_mask": np.ones_like(input_ids),
                 "token_type_ids": np.zeros_like(input_ids)}
        logits = sess.run(["logits"], feeds)[0]
        vecs = np.log1p(np.maximum(logits, 0.0)).max(axis=1)  # (n, vocab)
        top = np.argpartition(-vecs, TOP_E - 1, axis=1)[:, :TOP_E]
        idx_rows.append(top.astype(np.int32))
        val_rows.append(np.take_along_axis(vecs, top, axis=1).astype(np.float32))
    idx = np.concatenate(idx_rows)
    val = np.concatenate(val_rows)
    return idx, val, round(time.time() - t0, 1)


def qvec_from_table(text, tokenizer, id_to_token, idx, val, vocab_size, mode):
    enc = tokenizer([text], max_length=512, truncation=True,
                    return_tensors="np")
    tok_ids = [int(t) for t in enc["input_ids"][0]
               if int(t) not in (tokenizer.cls_token_id, tokenizer.sep_token_id,
                                 tokenizer.pad_token_id or -1)]
    if not tok_ids:
        return {}, 0.0
    t0 = time.perf_counter()
    if mode == "c2_selfweight":
        sparse_ids, sparse_vals = [], []
        for t in tok_ids:
            hit = np.where(idx[t] == t)[0]
            if hit.size:
                sparse_ids.append(t)
                sparse_vals.append(float(val[t][hit[0]]))
        agg_idx = np.array(sparse_ids, dtype=np.int64)
        agg_val = np.array(sparse_vals, dtype=np.float32)
    else:
        dense = np.zeros(vocab_size, dtype=np.float32)
        for t in tok_ids:
            if mode == "c1_max":
                np.maximum.at(dense, idx[t], val[t])
            else:  # c1_sum
                np.add.at(dense, idx[t], val[t])
        agg_idx = np.nonzero(dense)[0]
        agg_val = dense[agg_idx]
    lookup_ms = (time.perf_counter() - t0) * 1000
    order = np.argsort(-agg_val)
    sparse = {}
    for j in order:
        token = id_to_token.get(int(agg_idx[j]), "")
        if not token or token.startswith("[") or agg_val[j] <= 0.0:
            continue
        sparse[token] = round(float(agg_val[j]), 4)
        if len(sparse) >= SPLADE_QUERY_TERMS:
            break
    return sparse, lookup_ms


def overlap(ra, rb, k):
    return len(set(ra[:k]) & set(rb[:k])) / k


def main():
    t_start = time.time()
    queries = load_queries(N_QUERIES,
                           REPO / "data/eval_results/diverse_queries.json")
    _sess_unused, tokenizer, id_to_token = _get_splade_model(str(FP32_DIR))
    sess_fused, _ = make_session(FUSED_DIR / "model.onnx", None, None)
    vocab_size = max(id_to_token) + 1

    if TABLE_CACHE.exists():
        z = np.load(TABLE_CACHE)
        idx, val, table_secs = z["idx"], z["val"], float(z["secs"])
        print(f"table loaded from cache ({TABLE_CACHE.name})")
    else:
        idx, val, table_secs = build_table(sess_fused, tokenizer, vocab_size)
        np.savez_compressed(TABLE_CACHE, idx=idx, val=val, secs=table_secs)
    print(f"expansion table: {idx.shape[0]} rows x {TOP_E} entries "
          f"({table_secs}s to build)")

    # reference (served) + candidate qvecs, with encode timings
    ref_qv, ref_ms = [], []
    for q in queries:
        t0 = time.perf_counter()
        ref_qv.append(encode_with(sess_fused, tokenizer, id_to_token,
                                  SPLADE_QUERY_TERMS, q))
        ref_ms.append((time.perf_counter() - t0) * 1000)
    arms = {}
    for mode in ("c1_max", "c1_sum", "c2_selfweight"):
        qvs, times = [], []
        for q in queries:
            qv, ms = qvec_from_table(q, tokenizer, id_to_token, idx, val,
                                     vocab_size, mode)
            qvs.append(qv)
            times.append(ms)
        arms[mode] = {"qv": qvs, "lookup_ms_p50": round(statistics.median(times), 3)}

    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be_all = SequentialSeismicBackend(paths, splade_model_path=str(FP32_DIR),
                                      load_mode="mmap")
    be_s1 = SequentialSeismicBackend(paths[1:2], splade_model_path=str(FP32_DIR),
                                     load_mode="mmap")
    be_s2 = SequentialSeismicBackend(paths[2:3], splade_model_path=str(FP32_DIR),
                                     load_mode="mmap")
    backends = {"merged": be_all, "shard1": be_s1, "shard2": be_s2}

    ref_top = {name: [[d for d, _s in be.search_encoded(qv, TOP_K)]
                      for qv in ref_qv] for name, be in backends.items()}

    results = {}
    for mode, arm in arms.items():
        row = {"lookup_ms_p50": arm["lookup_ms_p50"]}
        for name, be in backends.items():
            o10, o50 = [], []
            for i, qv in enumerate(arm["qv"]):
                got = [d for d, _s in be.search_encoded(qv, TOP_K)]
                o10.append(overlap(ref_top[name][i], got, 10))
                o50.append(overlap(ref_top[name][i], got, 50))
            row[name] = {"overlap@10_mean": round(statistics.mean(o10), 4),
                         "overlap@10_min": round(min(o10), 4),
                         "overlap@50_mean": round(statistics.mean(o50), 4)}
        m, s1, s2 = (row["merged"]["overlap@10_mean"],
                     row["shard1"]["overlap@10_mean"],
                     row["shard2"]["overlap@10_mean"])
        row["verdict"] = ("PASS" if min(m, s1, s2) >= 0.99 else
                          "ESCALATE_C3" if m >= 0.97 else "WEAK")
        results[mode] = row
        print(f"{mode}: merged@10={m} s1={s1} s2={s2} -> {row['verdict']}")

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/q11_c1c2_stage0.py",
                    "doc": "docs/seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md",
                    "bars": "PASS iff merged AND shard1 AND shard2 overlap@10 "
                            ">= 0.99 (n=100); 0.97-0.99 merged -> ESCALATE_C3; "
                            "<0.97 -> WEAK (pre-registered doc 14 §4)",
                    "reference": "served fused encoder qvecs (D2-promoted)",
                    "table": {"rows": int(idx.shape[0]), "top_e": TOP_E,
                              "build_seconds": table_secs,
                              "cache": str(TABLE_CACHE.name)},
                    "c2_deviation": "self-weight from the C1 row (model-derived "
                                    "static scalar), NOT corpus IDF — no cheap "
                                    "df source per SPLADE-vocab term; recorded "
                                    "in doc 14",
                    "encode_ms_p50_reference": round(statistics.median(ref_ms), 2),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "backend": "SequentialSeismicBackend (T1: bit-identical "
                               "to parallel), e5 manifest"},
           "arms": results}
    res["meta"]["wall_seconds"] = round(time.time() - t_start, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
