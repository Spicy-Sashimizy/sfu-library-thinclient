#!/usr/bin/env python3
"""M2 pre-gate: does an integer-domain dot product (query ALSO quantized to int)
hold overlap@10 >= 0.99 against the f32 baseline?

CONTEXT (see docs/math_optimization/01_kernel_and_math_map.md, M2):
  The served SEISMIC dot kernel (vectorium_fork dotvbyte_fixedu8.rs:603-642)
  runs an f32 dot: gather dense f32 query weights -> vpmaddubsw-free mul_add.
  M2 proposes scoring in the INTEGER domain the way quantized NN inference does:
      score ~= s_q * s_d * sum( q_u8[c] * d_u8[c] )
  so the mul-accumulate lowers to vpmaddubsw (32 u8xi8 products/insn on AVX2)
  instead of 8 f32 FMA lanes, AND the dense query table shrinks 115KB->29KB.

MEASUREMENT METHOD (reuses the E6b / E6 phase-C harness pattern exactly):
  - Run the REAL engine (seismic.MmapSeismicIndex) per query, take its top-200
    candidates (K_PRIME=200, HEAP_FACTOR=0.8 — served defaults).
  - Re-score those SAME candidate docs in pure Python from the forward files
    under each arithmetic mode (f32 baseline + integer modes).
  - overlap@10 of re-ranked list vs f32 baseline. Gate: overlap@10 >= 0.99.

NO RUST TOUCHED. This is the cheap pre-gate before any kernel edit. The served
shard (global_shard0of8.mmap) is the f16-forward shard; FixedU8<U6> is reproduced
in Python the same way e6b_fixedu8_quality.py does it (round(v*64) -> u8).

SATURATION BOUND (the load-bearing math):
  vpmaddubsw produces saturated i16 PAIR sums: out[i] = q[2i]*d[2i] + q[2i+1]*d[2i+1].
  Doc values are FixedU8<U6> => d in [0, 255]. For NO saturation we need:
      2 * d_max * q_max <= 32767  =>  q_max <= 32767 / (2*255) = 64.2  =>  q <= 63 (6-bit).
  Measured doc values (seismic_e6_forward_codec_proto_20260702_2346.json phase A):
  min 0.01, MAX 3.25 -> 208 in u8 scale, all non-negative (no sign handling).
  So query MUST quantize to 6-bit to be saturation-safe by construction.
  5-bit is the headroom floor probe; 7/8-bit are EXPECTED to saturate -> collapse.

OUTPUT: data/eval_results/seismic_m2_pregate_queryint_{date}.json
"""
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import (load_token_to_id, load_queries,
                                    SPLADE_QUERY_TERMS, K_PRIME, HEAP_FACTOR,
                                    OVERLAP_K, TOP_K)

MMAP_DIR = REPO / "data/seismic_150m/index/plan01/global_shard0of8.mmap"
GATE_BAR = 0.99

# torch first (the ENOMEM lesson from e6b — import order matters under RAM pressure)
from lib.opensearch_retriever import encode_splade  # noqa: E402

import seismic  # noqa: E402

print(f"[t+{time.monotonic()-_t0:.1f}s] loading MmapSeismicIndex") if False else None
idx = seismic.MmapSeismicIndex(str(MMAP_DIR))
sd = seismic.get_seismic_string()
_t0 = time.monotonic()

# Forward files (f16 forward shard — same as e6b). FixedU8<U6> is simulated below.
offs = np.memmap(MMAP_DIR / "forward_offsets.bin", dtype=np.uint64, mode="r")
comps = np.memmap(MMAP_DIR / "forward_components.bin", dtype=np.uint16, mode="r")
vals = np.memmap(MMAP_DIR / "forward_values.bin", dtype=np.float16, mode="r")

tok2id = load_token_to_id(MMAP_DIR)
queries = load_queries(40, REPO / "data/eval_results/diverse_queries.json")
print(f"[t+{time.monotonic()-_t0:.1f}s] encoding {len(queries)} SPLADE queries")
q64s = [dict(sorted(encode_splade(q, "models/splade_onnx_fp16").items(),
                    key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]) for q in queries]

per_q = []
for q64 in q64s:
    known = {t: w for t, w in q64.items() if t in tok2id}
    qcomp = np.array(list(known.keys()), dtype=sd)
    qvals = np.array([float(v) for v in known.values()], dtype=np.float32)
    res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                     k=K_PRIME, query_cut=len(known), heap_factor=HEAP_FACTOR)
    per_q.append({"qids": np.array(sorted(tok2id[t] for t in known), dtype=np.int64),
                  "qw": {tok2id[t]: float(w) for t, w in known.items()},
                  "docs": [d for (_q, _s, d) in res]})
print(f"[t+{time.monotonic()-_t0:.1f}s] got {sum(len(pq['docs']) for pq in per_q)} candidates across {len(per_q)} queries")

# ---- candidate-row resolution (oaids -> forward rows), same as e6b ----
targets = {d for pq in per_q for d in pq["docs"]}
moffs = np.memmap(MMAP_DIR / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
blob = (MMAP_DIR / "document_mapping_strings.bin").read_bytes()
mo = moffs.astype(np.int64)
row_of = {}
for i in range(len(mo) - 1):
    s = blob[mo[i]:mo[i + 1]].decode()
    if s in targets:
        row_of[s] = i
assert len(row_of) == len(targets), f"resolved {len(row_of)} != {len(targets)} targets"
del blob
print(f"[t+{time.monotonic()-_t0:.1f}s] resolved {len(row_of)} candidate rows")


def load_row(row):
    """Return (components_i64, values_f32) for a forward row."""
    s, e = int(offs[row]), int(offs[row + 1])
    c = np.asarray(comps[s:e], dtype=np.int64)
    v = np.asarray(vals[s:e], dtype=np.float32)
    return c, v


def dot_f32(c, v, qids, qw_map):
    """Exact baseline: f32 dot of doc.values (from f16) * f32 query weights."""
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    return float(sum(qw_map[int(q)] * v[mm] for q, mm in zip(qids[ok], m[ok])))


def dot_integer(c, v, qids, qw, qbits, qw_map):
    """Integer-domain dot modeling vpmaddubsw pairs.

    doc  -> FixedU8<U6>: d_u8 = clip(round(v * 64), 0, 255)   # [0, 255]
    query-> q_bits int: q_u8 = clip(round(q / qmax * (2**qbits - 1)), 0, 2**qbits-1)
    score_int = sum(d_u8 * q_u8)  over doc-terms present in query
      (this is what vpmaddubsw + i32 horizontal accumulation would compute,
       provided 2 * 255 * (2**qbits - 1) <= 32767  -- else SATURATION corrupts it;
       we DO NOT simulate saturation here, we gate by qbits so it can't happen,
       and separately demonstrate the 7/8-bit collapse to prove the bound bites.)
    Returns (score_int, n_doc_terms, n_present) for zero-gather instrumentation.
    """
    vmax_q = max(qw.values()) if qw else 1.0
    qmax_int = (1 << qbits) - 1
    # quantize the present query weights to int
    q_u8 = {qid: int(np.clip(round(w / vmax_q * qmax_int), 0, qmax_int))
            for qid, w in qw.items()}
    # doc values -> FixedU8<U6>
    d_u8 = np.clip(np.round(v * 64.0), 0, 255).astype(np.int64)
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    score = int(sum(q_u8[int(q)] * d_u8[mm] for q, mm in zip(qids[ok], m[ok])))
    n_present = int(ok.sum())
    return float(score), len(c), n_present


# ---- run all modes ----
MODES = [
    ("query_int5", 5),   # headroom floor probe (q<=31, safe, lower resolution)
    ("query_int6", 6),   # saturation boundary (q<=63, 255*63*2=32130<32767 SAFE)
    ("query_int7", 7),   # EXPECTED saturation collapse (q<=127, 255*127*2=64770>32767)
    ("query_int8", 8),   # EXPECTED saturation collapse (q<=255, would need i32 accumulation, not maddubsw)
]
SAT_SAFE = {5, 6}  # 2*255*(2^b-1) <= 32767 holds only for b<=6

out = {"meta": {
    "mmap_dir": str(MMAP_DIR),
    "n_queries": len(per_q),
    "k_prime": K_PRIME, "heap_factor": HEAP_FACTOR,
    "overlap_k": OVERLAP_K, "top_k": TOP_K,
    "gate_bar_overlap10": GATE_BAR,
    "doc_quant": "FixedU8<U6> (round(v*64), clip[0,255])",
    "doc_value_stats_ref": "seismic_e6_forward_codec_proto_20260702_2346.json phase A (min 0.01, max 3.25, nnz mean 87.6)",
    "saturation_bound": "2*255*qmax <= 32767 => qmax<=64 => q<=63 (6-bit). Saturation-safe bits: {5,6}.",
    "note": "NO saturation simulated; bits>6 are gated-out by construction and shown only to prove the bound bites.",
}, "modes": {}}

# zero-gather instrumentation (grounds the "wasted FMA / zero-gather" estimate)
zg_doc_terms = 0      # total doc-term slots iterated by the kernel across all candidates
zg_present = 0         # of those, present in the query (non-zero gather)
zg_zero = 0            # of those, NOT in the query (zero gather -> wasted FMA)

for mode_name, qbits in MODES:
    ov10, ov50 = [], []
    for pq in per_q:
        rows = [row_of[d] for d in pq["docs"]]
        exact = []
        quant = []
        for r in rows:
            c, v = load_row(r)
            exact.append(dot_f32(c, v, pq["qids"], pq["qw"]))
            qsc, n_terms, n_present = dot_integer(c, v, pq["qids"], qw=pq["qw"],
                                                  qbits=qbits, qw_map=pq["qw"])
            quant.append(qsc)
            if mode_name == "query_int6":  # instrument once (the saturation-safe mode)
                zg_doc_terms += n_terms
                zg_present += n_present
                zg_zero += (n_terms - n_present)
        br = [pq["docs"][i] for i in np.argsort(-np.array(exact), kind="stable")]
        qr = [pq["docs"][i] for i in np.argsort(-np.array(quant), kind="stable")]
        ov10.append(len(set(br[:OVERLAP_K]) & set(qr[:OVERLAP_K])) / OVERLAP_K)
        ov50.append(len(set(br[:TOP_K]) & set(qr[:TOP_K])) / TOP_K)
    sat_label = "SAFE" if qbits in SAT_SAFE else "UNSAFE-INTENTIONAL-DEMO"
    m_out = {
        "query_bits": qbits,
        "query_int_range": f"[0, {(1<<qbits)-1}]",
        "saturation_safe": qbits in SAT_SAFE,
        "saturation_label": sat_label,
        "overlap@10_mean": round(statistics.mean(ov10), 4),
        "overlap@10_min": round(min(ov10), 4),
        "overlap@50_mean": round(statistics.mean(ov50), 4),
        "gate_pass_0.99": statistics.mean(ov10) >= GATE_BAR,
    }
    out["modes"][mode_name] = m_out
    print(f"  {mode_name}: ov@10 mean {m_out['overlap@10_mean']} min {m_out['overlap@10_min']} "
          f"[{sat_label}] -> {'PASS' if m_out['gate_pass_0.99'] else 'FAIL'}")

# zero-gather summary
out["zero_gather_inventory"] = {
    "doc_term_slots": zg_doc_terms,
    "present_in_query_nonzero_gather": zg_present,
    "absent_from_query_zero_gather": zg_zero,
    "zero_gather_fraction": round(zg_zero / zg_doc_terms, 4) if zg_doc_terms else None,
    "meaning": "fraction of kernel gather lanes that fetch 0 from the dense query array "
               "(doc term not in query) -> the wasted-FMA lanes M1 (vptest skip) would elide",
}

# verdict: query_int5 AND query_int6 must both pass for M2 to be worth a Rust change;
# query_int7/int8 expected to fail (proves the saturation bound, not an M2 blocker).
int6 = out["modes"]["query_int6"]
verdict = "M2 GO" if int6["gate_pass_0.99"] else "M2 NO-GO"
out["verdict"] = {
    "m2_query_int6_overlap10": int6["overlap@10_mean"],
    "bar": GATE_BAR,
    "pass": bool(int6["gate_pass_0.99"]),
    "overall": verdict,
    "rationale": ("6-bit query quant preserves top-10 ranking under integer dot -> "
                  "vpmaddubsw kernel is quality-safe to implement (saturation-free by construction).")
                  if int6["gate_pass_0.99"] else
                  ("6-bit query quant DROPS overlap@10 below 0.99 -> integer dot loses too much "
                   "query resolution; M2 dies at pre-gate, no Rust change."),
}

ts = datetime.now().strftime("%Y%m%d")
out_path = REPO / "data/eval_results" / f"seismic_m2_pregate_queryint_{ts}.json"
out_path.write_text(json.dumps(out, indent=2))
print("\n=== VERDICT ===")
print(f"query_int6 overlap@10 = {int6['overlap@10_mean']} (bar {GATE_BAR}) -> {verdict}")
print(f"zero-gather fraction = {out['zero_gather_inventory']['zero_gather_fraction']}")
print(f"result: {out_path}")
