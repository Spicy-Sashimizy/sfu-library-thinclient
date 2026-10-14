#!/usr/bin/env python3
"""BM25-through-SEISMIC spike — step 5: the MIRROR question, measured.

The spike's main line asks "can SEISMIC read BM25 vectors?". This asks the
reverse: **can tantivy read SPLADE vectors?** If it could, the lexical and
learned-sparse legs could unify on tantivy instead — no SEISMIC, no second
engine, and tantivy's mmap profile for both.

## The structural situation (tantivy 0.26 / tantivy-py)

Serving a SPLADE vector means computing a sparse dot product
`SUM_t q_w(t) * d_w(t)`. For that, an engine needs a per-(term, doc) float the
scorer uses **linearly**. Lucene has one (`FeatureField` / `rank_features`) —
which is why SPLADE rode Lucene into Elasticsearch (`docs/archive/sparse_engine_project/WHY_NO_FOSS.md` §3).
tantivy's exposed schema has no equivalent: `add_text_field`,
`add_{integer,float,unsigned,date,bytes,json,ip_addr,facet,boolean}_field` —
the float/integer fields are per-DOC, not per-(term, doc). The only per-(term,
doc) magnitude in a tantivy posting list is the **term frequency**, and the only
scorer that reads it is BM25, whose constants (k1=1.2, b=0.75) are fixed in Rust
and not settable through the Python bindings.

So the only encoding available is the classic "fake words" trick: emit token `t`
`round(w * scale)` times so `tf == quantized impact`. That is what this script
measures. The query side is fine — `boolean_query` + `boost_query` gives exact
per-term query weights. The doc side is where it breaks, in three places:

    contribution = idf(t) * tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))
                   ~~~~~~   ~~~~~~~~~~~~~~~~~~~~~~~~   ~~~~~~~~~~~~~~
                   (a)      (b) saturation             (c) length norm

(a) `idf(t)` is a corpus factor the dot product does not contain — but it is
    known at query time, so it CAN be divided out of the query boost. This
    script measures with and without that correction.
(b) tf saturates: at k1=1.2 a tf of 1 already scores 0.478 of the ceiling, tf=10
    scores 0.893, tf=100 scores 0.988. Impact is doc-side, so no query-time
    boost can undo it.
(c) length normalisation divides by doc length — and under this encoding doc
    length IS the doc vector's total mass, so the docs with the most SPLADE
    weight are penalised hardest. Also doc-side, also uncorrectable.

Ground truth is the exact dot product over the same vectors (brute force). The
gap is what tantivy's scorer costs you.

Runs on a subset (`--docs`, default 20k) because the tf-repetition encoding
inflates the index: every doc's token stream becomes ~`sum(round(w*scale))`
tokens instead of ~150. That inflation is itself a reported result.

    .venv/bin/python3 spike/bm25_seismic/05_tantivy_reads_splade.py --docs 20000
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))
log = logging.getLogger("bm25seismic.tantivy_splade")

# Mirrors the repo's BMP u8 impact constant (QUANT_SCALE=70, see
# source/lib/thinclient/CLAUDE.md) so the quantisation is the one this project
# already validated for sparse impacts, not an arbitrary choice.
QUANT_SCALE = 70
SPLADE_QUERY_TERMS = 64        # retriever.py's serve constant


def dir_size_mb(p: Path) -> float:
    return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6, 2)


def encode_corpus(corpus: Path, n_docs: int, batch: int) -> tuple[list[str], list[dict]]:
    """Encode title+abstract with the production SPLADE doc encoder (GPU)."""
    from lib.thinclient.doc_encoder import make_doc_encoder
    ids, texts = [], []
    with open(corpus) as fh:
        for line in fh:
            r = json.loads(line)
            ids.append(r["id"])
            texts.append(f"{r['title']} {r['abstract']}")
            if len(ids) >= n_docs:
                break
    enc = make_doc_encoder(batch_size=batch)
    vecs: list[dict] = []
    t0 = time.perf_counter()
    for i in range(0, len(texts), batch):
        vecs += enc.encode_batch(texts[i:i + batch])
        if (i // batch) % 25 == 0:
            log.info("  encoded %d/%d (%.0f docs/s)", len(vecs), len(texts),
                     len(vecs) / max(time.perf_counter() - t0, 1e-9))
    log.info("SPLADE encode: %d docs in %.1fs", len(vecs), time.perf_counter() - t0)
    return ids, vecs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--docs", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--queries", type=Path,
                    default=ROOT / "data" / "sfu_eval_queries.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--scale", type=int, default=QUANT_SCALE)
    ap.add_argument("--result-file", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    import tantivy

    cache = args.work / f"splade_vectors_{args.docs}.jsonl"
    if cache.exists():
        log.info("reusing cached SPLADE vectors %s", cache)
        ids, vecs = [], []
        with open(cache) as fh:
            for line in fh:
                r = json.loads(line)
                ids.append(r["id"])
                vecs.append(r["vector"])
    else:
        ids, vecs = encode_corpus(args.work / "corpus.jsonl", args.docs, args.batch)
        with open(cache, "w") as fh:
            for i, v in zip(ids, vecs):
                fh.write(json.dumps({"id": i, "vector": v}) + "\n")

    nnz = sum(len(v) for v in vecs)
    log.info("%d docs, %d nnz, %.1f terms/doc", len(ids), nnz, nnz / len(ids))

    # ── token universe -> synthetic alphanumeric "fake words" ─────────────────
    # SPLADE tokens are BERT wordpieces ("##ing", "[unused0]"); feeding those to
    # tantivy's default tokenizer would re-split them. Mapping each to `t<id>`
    # sidesteps tokenisation entirely — this IS the Lucene fake-words trick.
    tok_id: dict[str, int] = {}
    for v in vecs:
        for t in v:
            if t not in tok_id:
                tok_id[t] = len(tok_id)
    log.info("token universe: %d distinct SPLADE terms", len(tok_id))

    # ── exact dot product (ground truth) ──────────────────────────────────────
    indptr, indices, data = [0], [], []
    df = np.zeros(len(tok_id), dtype=np.int64)
    for v in vecs:
        for t, w in v.items():
            c = tok_id[t]
            indices.append(c)
            data.append(float(w))
            df[c] += 1
        indptr.append(len(indices))
    csc = sp.csr_matrix((np.asarray(data, dtype=np.float32),
                         np.asarray(indices, dtype=np.int32),
                         np.asarray(indptr, dtype=np.int64)),
                        shape=(len(ids), len(tok_id))).tocsc()
    ids_arr = np.array(ids)

    def exact_search(qv: dict[str, float], k: int):
        scores = np.zeros(len(ids), dtype=np.float32)
        for t, w in qv.items():
            c = tok_id.get(t)
            if c is None:
                continue
            lo, hi = csc.indptr[c], csc.indptr[c + 1]
            scores[csc.indices[lo:hi]] += csc.data[lo:hi] * w
        kk = min(k, scores.size)
        top = np.argpartition(-scores, kk - 1)[:kk]
        top = top[np.argsort(-scores[top])]
        return [(str(ids_arr[i]), float(scores[i])) for i in top if scores[i] > 0]

    # ── tantivy index over the tf-repetition encoding ─────────────────────────
    tdir = args.work / f"tantivy_splade_{args.docs}"
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    schema = (tantivy.SchemaBuilder()
              .add_text_field("id", stored=True, tokenizer_name="raw")
              .add_text_field("sparse", stored=False, index_option="freq")
              .build())
    tindex = tantivy.Index(schema, path=str(tdir))
    writer = tindex.writer(heap_size=512 * 1024 * 1024)
    t0 = time.perf_counter()
    total_tokens = 0
    for oid, v in zip(ids, vecs):
        parts = []
        for t, w in v.items():
            tf = int(round(float(w) * args.scale))
            if tf > 0:
                parts.append(f"t{tok_id[t]} " * tf)
        stream = "".join(parts)
        total_tokens += stream.count(" ")
        writer.add_document(tantivy.Document(id=oid, sparse=stream))
    writer.commit()
    tindex.reload()
    build_s = time.perf_counter() - t0
    log.info("tantivy tf-repetition index: %d docs, %.1f tokens/doc, %.1f MB, %.1fs",
             len(ids), total_tokens / len(ids), dir_size_mb(tdir), build_s)

    def tantivy_search(qv: dict[str, float], k: int, idf_correct: bool):
        clauses = []
        for t, w in qv.items():
            c = tok_id.get(t)
            if c is None:
                continue
            boost = float(w)
            if idf_correct:
                # divide out tantivy's own idf so only the doc-side distortions
                # (tf saturation + length norm) remain
                d = int(df[c])
                idf = math.log(1.0 + (len(ids) - d + 0.5) / (d + 0.5))
                boost = boost / idf if idf > 0 else 0.0
            if boost <= 0:
                continue
            clauses.append((tantivy.Occur.Should, tantivy.Query.boost_query(
                tantivy.Query.term_query(schema, "sparse", f"t{c}"), boost)))
        if not clauses:
            return []
        q = tantivy.Query.boolean_query(clauses)
        s = tindex.searcher()
        return [(s.doc(addr)["id"][0], float(sc)) for sc, addr in s.search(q, k).hits]

    # ── queries: same encoder, same top-64 shaping as the serving retriever ───
    from lib.opensearch_retriever import encode_splade
    queries = [q["query"] if isinstance(q, dict) else q
               for q in json.loads(args.queries.read_text())]
    model = str(ROOT / "models" / "splade_onnx_fused")

    def overlap(a, b, k):
        return len(set(a[:k]) & set(b[:k])) / k

    rows = []
    for n, qt in enumerate(queries, 1):
        sparse = encode_splade(qt, model)
        qv = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        ex = [d for d, _ in exact_search(qv, args.top_k)]
        raw = [d for d, _ in tantivy_search(qv, args.top_k, idf_correct=False)]
        cor = [d for d, _ in tantivy_search(qv, args.top_k, idf_correct=True)]
        rows.append({"query": qt,
                     "overlap_raw_boost": overlap(raw, ex, args.top_k),
                     "overlap_idf_corrected": overlap(cor, ex, args.top_k),
                     "top1_raw": bool(raw[:1] == ex[:1]),
                     "top1_idf_corrected": bool(cor[:1] == ex[:1])})
        if n % 20 == 0:
            log.info("  %d/%d queries", n, len(queries))

    def mean(xs):
        return round(statistics.fmean(xs), 4) if xs else 0.0

    k = args.top_k
    summary = {
        "meta": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "question": "can tantivy serve SPLADE (sparse dot-product) vectors?",
            "docs": len(ids), "splade_terms_per_doc": round(nnz / len(ids), 1),
            "token_universe": len(tok_id),
            "quant_scale": args.scale, "n_queries": len(queries), "top_k": k,
            "encoding": "fake-words tf-repetition: token t emitted round(w*scale) "
                        "times so tf == quantised impact (the only per-(term,doc) "
                        "magnitude tantivy exposes; it has no Lucene FeatureField "
                        "equivalent and no settable BM25 k1/b)",
            "tantivy_index_mb": dir_size_mb(tdir),
            "tokens_per_doc_after_repetition": round(total_tokens / len(ids), 1),
            "index_build_seconds": round(build_s, 1),
        },
        "scores": {
            f"overlap@{k}_vs_exact_raw_boost":
                mean([r["overlap_raw_boost"] for r in rows]),
            f"overlap@{k}_vs_exact_idf_corrected":
                mean([r["overlap_idf_corrected"] for r in rows]),
            "top1_match_raw": mean([1.0 if r["top1_raw"] else 0.0 for r in rows]),
            "top1_match_idf_corrected":
                mean([1.0 if r["top1_idf_corrected"] else 0.0 for r in rows]),
        },
        "per_query": rows,
    }
    out = args.result_file or (ROOT / "data" / "eval_results" /
                               f"bm25_seismic_spike_tantivy_splade_"
                               f"{time.strftime('%Y%m%d_%H%M')}.json")
    out.write_text(json.dumps(summary, indent=2))
    log.info("=== can tantivy read SPLADE vectors? ===")
    for kk, vv in summary["scores"].items():
        log.info("  %-42s %s", kk, vv)
    log.info("  index %.1f MB for %d docs (%.1f tokens/doc after repetition)",
             summary["meta"]["tantivy_index_mb"], len(ids),
             summary["meta"]["tokens_per_doc_after_repetition"])
    log.info("result: %s", out)


if __name__ == "__main__":
    main()
