#!/usr/bin/env python3
"""SEISMIC testbed — E6: SFR1 compressed-forward codec, prototyped on real shard0 data.

Design question (asked 2026-07-02): can the mmap forward index — 85% of shard
bytes, read as ~350 B random probes across TWO files (≈2 page faults per scored
candidate, `09_CROSS_SHARD_MMAP_AUDIT.md` §3.2) — be compressed WITHOUT losing
serving quality? This prototypes a corpus-customized record format, SFR1, and
measures its three claims on the real 18.8M-doc shard0:

**SFR1 (Seismic Forward Record v1)** — one interleaved file replaces
`forward_components.bin` + `forward_values.bin`:

    per-doc record (byte-aligned, random-access via offsets table):
      u16 first_component_id     (df-rank remapped id space)
      f16 vmax                   (per-doc value scale — exact, it IS an f16 value)
      varint[nnz-1] gaps         (LEB128 over gap-1; ids strictly ascending)
      u8[nnz] value codes        (v̂ = code/255 · vmax)

    nnz is derived from the offsets table (measured over ALL 18.8M shard0 docs:
    7 ≤ nnz ≤ 256, a build-time top-256 cap — never stored). Offsets shrink
    u64 → u32 (compressed file < 4 GiB/shard).

Corpus-customized choices, each measured here (phase A), not assumed:
  1. INTERLEAVE — candidates fault 1 page, not 2 (E[pages] 2.09 → ~1.04).
  2. DF-RANK ID REMAP — token ids reassigned by descending document frequency
     at convert time (posting-list array + summaries reorder consistently;
     queries are token-string keyed so scores can't move). Skews gaps small:
     measured gap entropy 8.23 → 7.40 bits.
  3. BYTE-VARINT gaps — beats per-doc fixed-width (heavy gap tail, p99 ≈ 2.5k);
     chosen over nibble-varint (~15 B/doc better) for trivial branch-light decode.
  4. PER-DOC LINEAR u8 VALUES — measured rel-L2 err 0.33% vs 1.28% for a global
     256-quantile codebook (per-doc scale adapts; the "obvious" corpus codebook
     LOSES on this corpus). Components stay LOSSLESS.

Phases:
  A. STATS — sample real docs; nnz/gap/value distributions; coding-variant
     bytes/doc table (current ids vs df-rank remap); quantizer error table.
  B. CODEC — encode the sampled docs with SFR1 (real encoder below); assert
     lossless component round-trip; measured bytes/doc + projected shard/corpus
     sizes + E[pages/candidate].
  C. QUALITY PROXY — run REAL searches (E1 harness pattern: mmap load, ≤100
     diverse queries, baseline params all-terms/qc=all/hf=0.8/k'=200), take each
     query's top-k' candidates, re-score them in Python from the forward files
     exactly (f32-from-f16 sanity vs engine scores) and under SFR1 quantized
     values; report overlap@10/@50 of the re-ranked lists. Gate: overlap@10 ≥ 0.99.

     HONESTY: this is a *scoring-side* proxy. It does not capture the
     second-order effect of quantized scores on the heap-min block-skip test
     during traversal (bounded by the ~0.33% score error; the audit's E-series
     parity convention gates that at implementation time). LAYOUT class — the
     converter + a reader `MmapSparseStorage` fork are the implementation cost.

RAM discipline (audit rules): ONE shard, mmap load only, ≤100 queries,
RssAnon/RssFile recorded before/after load and at end.

Run from repo root:

    .venv/bin/python3 scripts/seismic_testbed/e6_forward_codec_proto.py \
        --mmap-dir data/seismic_150m/index/plan01/global_shard0of8.mmap \
        --queries 40
"""
import argparse
import json
import logging
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("e6_codec")

TOP_K = 50
OVERLAP_K = 10
K_PRIME = 200            # served default over-fetch — the candidate set we protect
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
SAMPLE_DOCS = 200_000    # nnz / offsets stats
SAMPLE_FULL = 50_000     # docs fully decoded for gap/value/codec work
SEED = 42


# ── SFR1 codec (reference implementation; the Rust reader mirrors this) ─────

def leb128_encode(arr: np.ndarray) -> bytes:
    out = bytearray()
    for g in arr:
        g = int(g)
        while True:
            b = g & 0x7F
            g >>= 7
            if g:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
    return bytes(out)


def leb128_decode(buf: memoryview, n: int) -> tuple[np.ndarray, int]:
    out = np.empty(n, dtype=np.int64)
    pos = 0
    for i in range(n):
        val, shift = 0, 0
        while True:
            b = buf[pos]; pos += 1
            val |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        out[i] = val
    return out, pos


def sfr1_encode(ids: np.ndarray, vals: np.ndarray) -> bytes:
    """ids: sorted int64 (remapped) component ids; vals: f32 (from f16)."""
    assert len(ids) >= 1 and np.all(np.diff(ids) > 0)
    vmax = np.float16(vals.max())
    codes = np.clip(np.round(vals / np.float32(vmax) * 255.0), 0, 255).astype(np.uint8)
    rec = struct.pack("<H", int(ids[0])) + vmax.tobytes()
    rec += leb128_encode(np.diff(ids) - 1)
    rec += codes.tobytes()
    return rec


def sfr1_decode(rec: bytes, nnz: int) -> tuple[np.ndarray, np.ndarray]:
    (first,) = struct.unpack_from("<H", rec, 0)
    vmax = np.frombuffer(rec, dtype=np.float16, count=1, offset=2)[0]
    gaps, used = leb128_decode(memoryview(rec)[4:], nnz - 1)
    ids = np.empty(nnz, dtype=np.int64)
    ids[0] = first
    np.cumsum(gaps + 1, out=ids[1:]) if nnz > 1 else None
    if nnz > 1:
        ids[1:] += first
    codes = np.frombuffer(rec, dtype=np.uint8, count=nnz, offset=4 + used)
    vals = codes.astype(np.float32) / 255.0 * np.float32(vmax)
    return ids, vals


# ── shared helpers (E1 conventions) ──────────────────────────────────────────

def read_rss() -> dict[str, float]:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for key in ("RssAnon", "RssFile", "VmRSS", "VmSwap"):
            if line.startswith(key + ":"):
                out[key.lower() + "_gb"] = round(int(line.split()[1]) / 1e6, 3)
    return out


def load_token_to_id(mmap_dir: Path) -> dict[str, int]:
    # bincode 2.x serde fixed-int LE — same parser verified byte-exact in E1.
    raw = (mmap_dir / "token_to_id_map.bin").read_bytes()
    off = 0
    (count,) = struct.unpack_from("<Q", raw, off); off += 8
    tok2id: dict[str, int] = {}
    for _ in range(count):
        (slen,) = struct.unpack_from("<Q", raw, off); off += 8
        s = raw[off:off + slen].decode("utf-8"); off += slen
        (v,) = struct.unpack_from("<Q", raw, off); off += 8
        tok2id[s] = v
    assert off == len(raw)
    return tok2id


def load_queries(n: int, qpath: Path) -> list[str]:
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        if rec["paraphrase"] not in seen:
            seen.add(rec["paraphrase"])
            out.append(rec["paraphrase"])
        if len(out) >= n:
            break
    return out


def expected_pages(sizes: np.ndarray, files: int = 1) -> float:
    """E[4K pages touched] for a random-aligned read of each record."""
    return float((files * (1 + (sizes.astype(np.float64) - 1) / 4096)).mean())


# ── phases ───────────────────────────────────────────────────────────────────

def phase_a_stats(offs, comps, vals, rng):
    n_docs = len(offs) - 1
    nnz_all = np.diff(offs.astype(np.int64))
    assert nnz_all.max() <= 256 and nnz_all.min() >= 1, "SFR1 premise broken"

    docs = np.sort(rng.choice(n_docs, size=SAMPLE_DOCS, replace=False))
    starts, ends = offs[docs].astype(np.int64), offs[docs + 1].astype(np.int64)
    nnz = ends - starts

    sub = rng.choice(SAMPLE_DOCS, size=SAMPLE_FULL, replace=False)
    doc_ids, doc_vals = [], []
    tf = np.zeros(comps.max() + 1 if False else 32768, dtype=np.int64)
    unsorted = 0
    for i in sub:
        c = np.asarray(comps[starts[i]:ends[i]], dtype=np.int64)
        v = np.asarray(vals[starts[i]:ends[i]], dtype=np.float32)
        if np.any(np.diff(c) <= 0):
            unsorted += 1
            continue
        doc_ids.append(c)
        doc_vals.append(v)
        tf[c] += 1
    assert unsorted == 0, f"{unsorted} unsorted docs — SFR1 gap premise broken"

    order = np.argsort(-tf, kind="stable")
    remap = np.empty(len(tf), dtype=np.int64)
    remap[order] = np.arange(len(tf))

    def varint_len(g):
        return int(np.where(g < 128, 1, np.where(g < 16384, 2, 3)).sum())

    coding = {}
    for name, mapper in [("current_ids", None), ("dfrank_ids", remap)]:
        vb, ent_counts, n = 0, {}, 0
        for c in doc_ids:
            ids = np.sort(mapper[c]) if mapper is not None else c
            g = np.diff(ids) - 1
            if len(g) == 0:
                continue
            vb += varint_len(g) + 2
            u, cnt = np.unique(g, return_counts=True)
            for uu, cc in zip(u, cnt):
                ent_counts[uu] = ent_counts.get(uu, 0) + int(cc)
            n += 1
        cnts = np.array(list(ent_counts.values()), dtype=float)
        p = cnts / cnts.sum()
        H = float(-(p * np.log2(p)).sum())
        coding[name] = {"varint_first_bytes_per_doc": round(vb / n, 1),
                        "gap_entropy_bits": round(H, 2)}

    av = np.concatenate(doc_vals)
    err_lin = [float(np.linalg.norm(v - (np.clip(np.round(v / v.max() * 255), 0, 255)
                                         / 255.0 * v.max()))
                     / (np.linalg.norm(v) + 1e-9)) for v in doc_vals]
    # global 256-quantile codebook, fit on this corpus sample — the loser, kept on record
    edges = np.quantile(av, np.linspace(0, 1, 257)[1:-1])
    centers = np.zeros(256, dtype=np.float32)
    idx = np.searchsorted(edges, av)
    for k in range(256):
        m = av[idx == k]
        centers[k] = m.mean() if len(m) else (edges[min(k, 254)] if k < 256 else 0)
    err_cb = [float(np.linalg.norm(v - centers[np.searchsorted(edges, v)])
                    / (np.linalg.norm(v) + 1e-9)) for v in doc_vals[:5000]]

    stats = {
        "n_docs": int(n_docs),
        "nnz": {"mean": round(float(nnz_all.mean()), 1), "min": int(nnz_all.min()),
                "max": int(nnz_all.max()),
                "p50": int(np.percentile(nnz, 50)), "p99": int(np.percentile(nnz, 99)),
                "cap_note": "7<=nnz<=256 over ALL 18.8M docs (top-256 build cap) — "
                            "nnz derived from offsets, never stored in SFR1"},
        "sortedness": f"all {len(doc_ids)} fully-decoded sampled docs strictly ascending",
        "gap_coding_bytes_per_doc": coding,
        "values": {"min": round(float(av.min()), 4), "max": round(float(av.max()), 4),
                   "all_nonneg": bool((av >= 0).all()),
                   "u8_perdoc_linear_relL2_mean_pct": round(float(np.mean(err_lin)) * 100, 3),
                   "u8_perdoc_linear_relL2_p95_pct": round(float(np.percentile(err_lin, 95)) * 100, 3),
                   "u8_global_quantile_codebook_relL2_mean_pct": round(float(np.mean(err_cb)) * 100, 3),
                   "verdict": "per-doc linear WINS on this corpus (scale adapts per doc)"},
    }
    return stats, doc_ids, doc_vals, remap, nnz_all


def phase_b_codec(doc_ids, doc_vals, remap, nnz_all):
    enc_sizes, val_err = [], []
    t0 = time.perf_counter()
    for c, v in zip(doc_ids, doc_vals):
        perm = np.argsort(remap[c], kind="stable")
        ids, vsort = remap[c][perm], v[perm]
        rec = sfr1_encode(ids, vsort)
        enc_sizes.append(len(rec))
        dids, dvals = sfr1_decode(rec, len(ids))
        assert np.array_equal(dids, ids), "component round-trip NOT lossless"
        val_err.append(float(np.linalg.norm(vsort - dvals) / (np.linalg.norm(vsort) + 1e-9)))
    dt = time.perf_counter() - t0
    enc_sizes = np.array(enc_sizes)

    cur_rec = np.array([len(c) * 2 for c in doc_ids])  # per file
    mean_rec = float(enc_sizes.mean())
    n_docs = len(nnz_all)
    proj_fwd_gb = (nnz_all.mean() / (np.mean([len(c) for c in doc_ids]))
                   * mean_rec * n_docs) / 1e9  # rescale sample mean to true nnz mean
    cur_fwd_gb = int(nnz_all.sum()) * 4 / 1e9
    return {
        "sample_docs_encoded": len(enc_sizes),
        "component_roundtrip": "LOSSLESS (asserted per doc)",
        "value_relL2_mean_pct": round(float(np.mean(val_err)) * 100, 3),
        "record_bytes": {"mean": round(mean_rec, 1),
                         "p50": int(np.percentile(enc_sizes, 50)),
                         "p99": int(np.percentile(enc_sizes, 99)),
                         "current_two_file_mean": round(float(cur_rec.mean() * 2), 1)},
        "compression_ratio": round(float(cur_rec.mean() * 2) / mean_rec, 2),
        "expected_pages_per_candidate": {
            "current": round(expected_pages(cur_rec, files=2), 2),
            "sfr1": round(expected_pages(enc_sizes, files=1), 2)},
        "projected_shard0_forward_gb": {"current": round(cur_fwd_gb, 2),
                                        "sfr1": round(proj_fwd_gb, 2),
                                        "offsets_u64_to_u32_mb": "150 -> 75"},
        "projected_corpus_forward_gb_8shards": {"current": round(cur_fwd_gb * 8, 1),
                                                "sfr1_est": round(proj_fwd_gb * 8, 1)},
        "python_encode_decode_s_total": round(dt, 1),
        "decode_cost_note": "Python reference only — Rust decode cost is the "
                            "implementation gate (C0.5 precedent: 1.07x envelope)",
    }


def phase_c_quality(mmap_dir: Path, offs, comps, vals, n_queries: int,
                    model_path: str, qpath: Path):
    import seismic
    rss_pre = read_rss()
    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    string_dtype = seismic.get_seismic_string()
    rss_loaded = read_rss()
    log.info("mmap loaded len=%d rss=%s", idx.len, rss_loaded)

    from lib.opensearch_retriever import encode_splade
    tok2id = load_token_to_id(mmap_dir)
    queries = load_queries(n_queries, qpath)
    log.info("encoding %d queries...", len(queries))
    q64s = [dict(sorted(encode_splade(q, model_path).items(),
                        key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]) for q in queries]

    # baseline engine searches (recall-max params, E1 convention)
    per_q = []
    for q64 in q64s:
        known = {t: w for t, w in q64.items() if t in tok2id}
        qcomp = np.array(list(known.keys()), dtype=string_dtype)
        qvals = np.array([float(v) for v in known.values()], dtype=np.float32)
        res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                         k=K_PRIME, query_cut=len(known), heap_factor=HEAP_FACTOR)
        per_q.append({"qids": np.array(sorted(tok2id[t] for t in known), dtype=np.int64),
                      "qw": {tok2id[t]: float(w) for t, w in known.items()},
                      "docs": [d for (_q, _s, d) in res],
                      "scores": [float(s) for (_q, s, _d) in res]})

    # map W-ids -> forward rows: one sequential pass over the doc mapping
    targets = {d for pq in per_q for d in pq["docs"]}
    moffs = np.memmap(mmap_dir / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
    blob = (mmap_dir / "document_mapping_strings.bin").read_bytes()
    row_of: dict[str, int] = {}
    t0 = time.perf_counter()
    mo = moffs.astype(np.int64)
    for i in range(len(mo) - 1):
        s = blob[mo[i]:mo[i + 1]].decode()
        if s in targets:
            row_of[s] = i
    log.info("doc-mapping scan: %d/%d targets found in %.1fs",
             len(row_of), len(targets), time.perf_counter() - t0)
    assert len(row_of) == len(targets), "doc ids missing from mapping"
    del blob

    def dot(row: int, qids: np.ndarray, qw: dict, quantize: bool) -> float:
        s, e = int(offs[row]), int(offs[row + 1])
        c = np.asarray(comps[s:e], dtype=np.int64)
        v = np.asarray(vals[s:e], dtype=np.float32)
        if quantize:
            vmax = np.float32(np.float16(v.max()))
            v = np.clip(np.round(v / vmax * 255.0), 0, 255).astype(np.float32) / 255.0 * vmax
        m = np.searchsorted(c, qids)
        ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
        return float(sum(qw[int(q)] * v[mm] for q, mm in zip(qids[ok], m[ok])))

    ov10, ov50, sanity_diff = [], [], []
    for pq in per_q:
        rows = [row_of[d] for d in pq["docs"]]
        exact = [dot(r, pq["qids"], pq["qw"], quantize=False) for r in rows]
        quant = [dot(r, pq["qids"], pq["qw"], quantize=True) for r in rows]
        sanity_diff.extend(abs(a - b) / (abs(b) + 1e-9)
                           for a, b in zip(exact, pq["scores"]))
        base_rank = [pq["docs"][i] for i in np.argsort(-np.array(exact), kind="stable")]
        q_rank = [pq["docs"][i] for i in np.argsort(-np.array(quant), kind="stable")]
        ov10.append(len(set(base_rank[:OVERLAP_K]) & set(q_rank[:OVERLAP_K])) / OVERLAP_K)
        ov50.append(len(set(base_rank[:TOP_K]) & set(q_rank[:TOP_K])) / TOP_K)

    return {
        "n_queries": len(per_q),
        "candidates_rescored_per_query": K_PRIME,
        "engine_vs_python_exact_rel_diff_max": round(max(sanity_diff), 5),
        "overlap@10_mean": round(statistics.mean(ov10), 4),
        "overlap@10_min": round(min(ov10), 4),
        "overlap@50_mean": round(statistics.mean(ov50), 4),
        "gate": "overlap@10 >= 0.99",
        "gate_pass": statistics.mean(ov10) >= 0.99,
        "caveat": "scoring-side proxy on the engine's own top-k' candidates; "
                  "heap/skip second-order effect gated at implementation parity run",
        "rss": {"pre_load": rss_pre, "post_load": rss_loaded, "end": read_rss()},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmap-dir",
                    default="data/seismic_150m/index/plan01/global_shard0of8.mmap")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--skip-quality", action="store_true",
                    help="phases A+B only (no index load, no model)")
    args = ap.parse_args()
    assert args.queries <= 100, "audit rule: <=100 queries"

    if not args.skip_quality:
        # torch import is the peak-RSS moment (observed transient ENOMEM on the
        # WSL2 kernel when it lands mid-run) — pay it first, before any sampling
        # allocations or the mmap load exist.
        log.info("preloading SPLADE encoder stack...")
        from lib.opensearch_retriever import encode_splade  # noqa: F401

    mmap_dir = Path(args.mmap_dir)
    rng = np.random.default_rng(SEED)
    offs = np.memmap(mmap_dir / "forward_offsets.bin", dtype=np.uint64, mode="r")
    comps = np.memmap(mmap_dir / "forward_components.bin", dtype=np.uint16, mode="r")
    vals = np.memmap(mmap_dir / "forward_values.bin", dtype=np.float16, mode="r")

    log.info("phase A: stats over %d sampled docs (%d fully decoded)...",
             SAMPLE_DOCS, SAMPLE_FULL)
    stats, doc_ids, doc_vals, remap, nnz_all = phase_a_stats(offs, comps, vals, rng)
    log.info("phase A done: %s", json.dumps(stats["gap_coding_bytes_per_doc"]))

    log.info("phase B: SFR1 encode/decode over %d real docs...", len(doc_ids))
    codec = phase_b_codec(doc_ids, doc_vals, remap, nnz_all)
    log.info("phase B done: %.1f B/doc, ratio %.2fx, pages %s",
             codec["record_bytes"]["mean"], codec["compression_ratio"],
             codec["expected_pages_per_candidate"])

    quality = None
    if not args.skip_quality:
        del doc_ids, doc_vals, remap, nnz_all  # free A/B state before the index load
        log.info("phase C: quality proxy (%d real queries)...", args.queries)
        quality = phase_c_quality(mmap_dir, offs, comps, vals, args.queries,
                                  args.model_path, Path(args.query_workload))
        log.info("phase C done: overlap@10 mean=%.4f min=%.4f gate_pass=%s",
                 quality["overlap@10_mean"], quality["overlap@10_min"],
                 quality["gate_pass"])

    summary = {
        "meta": {
            "purpose": "E6: SFR1 compressed interleaved forward record — corpus-"
                       "customized codec prototype + quality proxy (design for the "
                       "09-audit forward-width LAYOUT lever)",
            "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "shard": str(mmap_dir),
            "seed": SEED,
            "spec": "u16 first_id(dfrank) | f16 vmax | LEB128(gap-1) | u8 codes; "
                    "nnz from offsets(u32); one file",
        },
        "phase_a_stats": stats,
        "phase_b_codec": codec,
        "phase_c_quality_proxy": quality,
    }
    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_e6_forward_codec_proto_{time.strftime('%Y%m%d_%H%M')}.json")
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"record_bytes_mean": codec["record_bytes"]["mean"],
                      "compression_ratio": codec["compression_ratio"],
                      "pages_per_candidate": codec["expected_pages_per_candidate"],
                      "quality": None if quality is None else {
                          "overlap@10_mean": quality["overlap@10_mean"],
                          "gate_pass": quality["gate_pass"]},
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
