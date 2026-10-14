#!/usr/bin/env python3
"""Q4 — M2b pre-gate: 7-bit/i32 integer query dot, n=100, shards 1-2 (2026-07-10).

M2 (the int6/vpmaddubsw kernel) FAILED at n=100 (gate a 0.984 < 0.99,
math_optimization/07; env-gated OFF). Q4/M2b is the widened variant: quantize
the query to 7-bit AND widen the horizontal accumulation to i32 (no
vpmaddubsw i16 pair-sum saturation — i32 holds 255*127*n_terms for any real
nnz). The question: does 7-bit/i32 integer dot hold overlap@10 >= 0.99 vs the
f32 baseline on shards 1-2 (the worst-case shards per doc 12 §2.1)?

PRE-REGISTERED BARS (doc 12 §3 Q4):
  - overlap@10 >= 0.99 on BOTH shards at n=100 -> build the kernel variant
    behind the existing SFU_SEISMIC_M2_INT6 plumbing (protocol stages in
    math_optimization/05).
  - else -> record and STOP; the FAIL also kills Q5 (M6 VNNI/UDOT)'s quality
    leg (same arithmetic width).

METHOD (zero Rust, mirrors m2_pregate_query_integer_dot.py):
  - Run the REAL engine (seismic.MmapSeismicIndex) per query, take its top-100
    candidates (k'=100, the served default — NOT 200, the old M2 run used 200;
    the served default flipped to max(2*top_k,100) on 2026-07-08 G8f).
  - Re-score those SAME candidate docs in pure Python under each mode:
      f32 baseline (exact) + query_int6 (saturation-safe boundary) +
      query_int7_i32 (the M2b variant — 7-bit query, i32 accumulation, NO
      saturation by construction: 255*127 = 32385 < 2^31 for any real nnz).
  - overlap@10 of re-ranked list vs f32 baseline. Gate: >= 0.99.
  i32 accumulation is modeled by Python's arbitrary-precision int(sum(...)),
  which never saturates — the faithful model of an i32-accumulating kernel.

Shards 1-2 f16 twins (the parity reference). Q4 is quality-free to RUN
(observes/re-scores; no served path change); the kernel BUILD is gated on PASS.

Usage (repo root, project venv):

    .venv/bin/python3 scripts/seismic_testbed/q4_m2b_integer_dot_pregate.py \
        --queries 100 --k-prime 100 \
        --result-file data/eval_results/q4_m2b_pregate_20260710.json
"""
import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

log = logging.getLogger("q4_m2b")

from e6_forward_codec_proto import (load_token_to_id, load_queries,  # noqa: E402
                                    SPLADE_QUERY_TERMS)
# Q4 uses the SERVED k'=100 (not the old 200); define locally.
K_PRIME = 100
HEAP_FACTOR = 0.8
OVERLAP_K = 10
TOP_K = 50
GATE_BAR = 0.99

SHARDS = {
    "shard1": REPO / "data" / "seismic_150m" / "index" / "plan01" / "global_shard1of8.mmap",
    "shard2": REPO / "data" / "seismic_150m" / "index" / "plan01" / "global_shard2of8.mmap",
}


def dot_f32(c, v, qids, qw_map):
    """Exact baseline: f32 dot of doc.values (from f16) * f32 query weights."""
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    return float(sum(qw_map[int(q)] * v[mm] for q, mm in zip(qids[ok], m[ok])))


def dot_integer(c, v, qids, qw, qbits):
    """Integer-domain dot: d_u8 = clip(round(v*64),0,255) [FixedU8<U6>];
    q_u8 = clip(round(q/qmax*(2^qbits-1)),0,2^qbits-1); score = sum(d_u8*q_u8).

    i32 accumulation is modeled by Python's arbitrary-precision int(sum(...))
    — never saturates (255*127=32385, and 32385*max_nnz_terms << 2^31). This
    is the faithful model of an i32-accumulating kernel (the M2b variant),
    NOT the vpmaddubsw i16 pair-sum (which saturates >6-bit). Returns score."""
    vmax_q = max(qw.values()) if qw else 1.0
    qmax_int = (1 << qbits) - 1
    q_u8 = {qid: int(np.clip(round(w / vmax_q * qmax_int), 0, qmax_int))
            for qid, w in qw.items()}
    d_u8 = np.clip(np.round(v * 64.0), 0, 255).astype(np.int64)
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    return float(int(sum(q_u8[int(q)] * d_u8[mm] for q, mm in zip(qids[ok], m[ok]))))


def measure_shard(shard_name: str, mmap_dir: Path, queries, k_prime, model_path):
    from lib.opensearch_retriever import encode_splade
    import seismic
    sd = seismic.get_seismic_string()
    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    log.info("%s: len=%d dim=%d nnz=%d", shard_name, idx.len, idx.dim, idx.nnz)

    offs = np.memmap(mmap_dir / "forward_offsets.bin", dtype=np.uint64, mode="r")
    comps = np.memmap(mmap_dir / "forward_components.bin", dtype=np.uint16, mode="r")
    vals = np.memmap(mmap_dir / "forward_values.bin", dtype=np.float16, mode="r")
    tok2id = load_token_to_id(mmap_dir)

    q64s = [dict(sorted(encode_splade(q, model_path).items(),
                        key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]) for q in queries]
    per_q = []
    for q64 in q64s:
        known = {t: w for t, w in q64.items() if t in tok2id}
        qcomp = np.array(list(known.keys()), dtype=sd)
        qvals = np.array([float(v) for v in known.values()], dtype=np.float32)
        res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                         k=k_prime, query_cut=len(known), heap_factor=HEAP_FACTOR)
        per_q.append({"qids": np.array(sorted(tok2id[t] for t in known), dtype=np.int64),
                      "qw": {tok2id[t]: float(w) for t, w in known.items()},
                      "docs": [d for (_q, _s, d) in res]})

    # Resolve oaid -> forward row.
    targets = {d for pq in per_q for d in pq["docs"]}
    moffs = np.memmap(mmap_dir / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
    blob = (mmap_dir / "document_mapping_strings.bin").read_bytes()
    mo = moffs.astype(np.int64)
    row_of = {}
    for i in range(len(mo) - 1):
        s = blob[mo[i]:mo[i + 1]].decode()
        if s in targets:
            row_of[s] = i
    del blob
    log.info("%s: resolved %d/%d candidate rows", shard_name, len(row_of), len(targets))

    def load_row(row):
        s, e = int(offs[row]), int(offs[row + 1])
        return np.asarray(comps[s:e], dtype=np.int64), np.asarray(vals[s:e], dtype=np.float32)

    modes = [("query_int6", 6), ("query_int7_i32", 7)]  # int6 boundary + the M2b 7-bit/i32
    out = {"n_queries": len(per_q), "k_prime": k_prime, "modes": {}}
    for mode_name, qbits in modes:
        ov10, ov50 = [], []
        for pq in per_q:
            rows = [row_of[d] for d in pq["docs"]]
            exact, quant = [], []
            for r in rows:
                c, v = load_row(r)
                exact.append(dot_f32(c, v, pq["qids"], pq["qw"]))
                quant.append(dot_integer(c, v, pq["qids"], qw=pq["qw"], qbits=qbits))
            br = [pq["docs"][i] for i in np.argsort(-np.array(exact), kind="stable")]
            qr = [pq["docs"][i] for i in np.argsort(-np.array(quant), kind="stable")]
            ov10.append(len(set(br[:OVERLAP_K]) & set(qr[:OVERLAP_K])) / OVERLAP_K)
            ov50.append(len(set(br[:TOP_K]) & set(qr[:TOP_K])) / TOP_K)
        m_out = {
            "query_bits": qbits,
            "query_int_range": f"[0, {(1<<qbits)-1}]",
            "accumulation": "i32 (Python arbitrary-precision int(sum) = never saturates)",
            "overlap@10_mean": round(statistics.mean(ov10), 4),
            "overlap@10_min": round(min(ov10), 4),
            "overlap@50_mean": round(statistics.mean(ov50), 4),
            "gate_pass_0.99": statistics.mean(ov10) >= GATE_BAR,
        }
        out["modes"][mode_name] = m_out
        log.info("%s %s: ov@10 mean %s min %s -> %s", shard_name, mode_name,
                 m_out["overlap@10_mean"], m_out["overlap@10_min"],
                 "PASS" if m_out["gate_pass_0.99"] else "FAIL")
    del idx
    import gc; gc.collect()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--k-prime", type=int, default=100)
    ap.add_argument("--query-file", default="data/eval_results/diverse_queries.json")
    ap.add_argument("--splade-model", default="models/splade_onnx_fp16")
    ap.add_argument("--result-file", required=True)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    qpath = Path(args.query_file)
    if not qpath.is_absolute():
        qpath = REPO / qpath
    queries = load_queries(args.queries, qpath)
    log.info("loaded %d queries; k'=%d", len(queries), args.k_prime)

    results = {}
    for shard_name, d in SHARDS.items():
        if not d.is_dir():
            log.warning("%s: missing %s — skipping", shard_name, d)
            continue
        results[shard_name] = measure_shard(shard_name, d, queries, args.k_prime, args.splade_model)

    # Verdict: the M2b 7-bit/i32 mode must pass on BOTH shards.
    def m2b_pass(shard):
        return results.get(shard, {}).get("modes", {}).get("query_int7_i32", {}).get("gate_pass_0.99")
    both = all(m2b_pass(s) for s in SHARDS)
    bars = [m2b_pass(s) for s in SHARDS]
    verdict = {
        "bar_overlap10_ge_0.99_both_shards": GATE_BAR,
        "shard1_query_int7_i32_pass": m2b_pass("shard1"),
        "shard2_query_int7_i32_pass": m2b_pass("shard2"),
        "overall": "PASS_build_kernel_behind_SFU_SEISMIC_M2_INT6" if both
                   else "FAIL_record_and_stop_kills_Q5",
        "q5_killed_on_fail": (not both),
        "note": ("Pre-registered bars (doc 12 §3 Q4): 7-bit/i32 integer dot "
                 "overlap@10 >= 0.99 on BOTH shards at n=100 -> build the kernel "
                 "variant behind SFU_SEISMIC_M2_INT6; else STOP (the FAIL also "
                 "kills Q5/M6's quality leg — same arithmetic width). Served "
                 "k'=100 (G8f default; the old M2 run used 200). i32 accumulation "
                 "modeled by Python arbitrary-precision int(sum) = never saturates "
                 "(255*127=32385, *nnz << 2^31) — the faithful i32 model, NOT "
                 "vpmaddubsw i16 (saturates >6-bit)."),
    }
    out = {
        "meta": {
            "date_utc": __import__("datetime").datetime.utcnow().isoformat(),
            "benchmark": "q4 m2b 7-bit/i32 integer-dot pre-gate",
            "queries": len(queries), "k_prime": args.k_prime, "shards": list(SHARDS),
            "gate_bar_overlap10": GATE_BAR,
        },
        "results": results,
        "verdict": verdict,
    }
    result_file = REPO / args.result_file
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(out, f, indent=2)
    log.info("result written to %s", result_file)
    log.info("VERDICT: %s", json.dumps(verdict, indent=2))
    return 0 if both else 1


if __name__ == "__main__":
    sys.exit(main())
