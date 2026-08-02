#!/usr/bin/env python3
"""BM25-through-SEISMIC spike — step 2: build both sides of the comparison.

Builds, over the SAME docs:

1. **tantivy** — a mini index with `lib/thinclient/builder.py`'s exact schema
   (`title`/`abstract` indexed-only with `index_option="freq"`, `id` stored raw).
   Queried the way `retriever._bm25f_leg` queries it (boolean OR, title boosted
   3.0), this is the production lexical leg, reproduced on the spike corpus.
2. **SEISMIC** — the BM25F decomposition from `bm25_lib.py`, one index per
   variant, built with the SAME parameters the 150M production shards use
   (`n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
   summary_energy=0.4, max_fraction=1.5, doc_cut=15`) so the spike measures
   SEISMIC as actually deployed, not a spike-tuned configuration.

The BM25 vocabulary is open (real words, numbers, OCR noise) rather than
SPLADE's fixed 30522-entry BERT vocabulary, so `dim` will exceed the 65K limit
of the standard index and the build falls back to `SeismicIndexLV`, exactly as
`build_persona_seismic.py` does.

Writes ONLY under this spike's `work/` dir. Nothing in `data/` is opened for
writing; the serving index, its routing, and the MCP request path are untouched.

    .venv/bin/python3 spike/bm25_seismic/02_build_indexes.py --variant both
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import resource
import shutil
import time
from pathlib import Path

import bm25_lib as BL

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("bm25seismic.build")

SEISMIC_PARAMS = dict(n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
                      summary_energy=0.4, max_fraction=1.5, doc_cut=15)


def iter_corpus(path: Path):
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


def build_stats(corpus: Path) -> BL.BM25FStats:
    stats = BL.BM25FStats()
    t0 = time.perf_counter()
    for n, rec in enumerate(iter_corpus(corpus), 1):
        stats.add(BL.tokenize(rec["title"]), BL.tokenize(rec["abstract"]))
        if n % 100_000 == 0:
            log.info("  stats pass: %d docs", n)
    log.info("stats: %s in %.1fs", stats.to_json(), time.perf_counter() - t0)
    return stats


def write_seismic_jsonl(corpus: Path, stats: BL.BM25FStats, variant: str,
                        out: Path, min_impact: float) -> dict:
    """SEISMIC's native format: {"id": <str>, "vector": {component: weight}}."""
    n = nnz = dropped = 0
    t0 = time.perf_counter()
    with open(out, "w") as fout:
        for rec in iter_corpus(corpus):
            vec = BL.doc_vector(BL.tokenize(rec["title"]),
                                BL.tokenize(rec["abstract"]), stats, variant)
            if min_impact > 0:
                before = len(vec)
                vec = {k: v for k, v in vec.items() if v >= min_impact}
                dropped += before - len(vec)
            if not vec:
                continue
            fout.write(json.dumps({"id": rec["id"], "vector": vec}) + "\n")
            n += 1
            nnz += len(vec)
    return {"jsonl": str(out), "docs": n, "nnz": nnz,
            "avg_nnz_per_doc": round(nnz / n, 2) if n else 0,
            "components_dropped_below_min_impact": dropped,
            "on_disk_mb": round(out.stat().st_size / 1e6, 2),
            "seconds": round(time.perf_counter() - t0, 1)}


def build_seismic(jsonl: Path, index_path: Path, n_components: int) -> dict:
    """`build_persona_seismic.py` picks the LV class by checking `idx.dim` after
    a standard build. That does NOT work for BM25: with an open vocabulary the
    standard builder **panics** in Rust (`inverted_index_wrapper.rs:499`, "The
    number of different tokens exceeds 2^16") before any `dim` is readable —
    measured 2026-08-01 at 710,047 components. So the class is chosen up front
    from the counted vocabulary instead."""
    import seismic
    cls = (seismic.SeismicIndexLV if n_components > 65_000
           else seismic.SeismicIndex)
    log.info("vocabulary %d components -> %s (SPLADE's fixed BERT vocab is "
             "30522, which fits the standard u16 token id; BM25's does not)",
             n_components, cls.__name__)
    t0 = time.perf_counter()
    idx = cls.build(str(jsonl), **SEISMIC_PARAMS)
    build_s = time.perf_counter() - t0
    idx.save(str(index_path))
    disk = dir_size(index_path.parent)
    saved = index_path.with_suffix(index_path.suffix + ".index.seismic")
    if not saved.exists():
        cand = list(index_path.parent.glob(index_path.name + "*"))
        saved = cand[0] if cand else index_path
    return {"index_path": str(saved),
            "variant_class": "LV" if cls is seismic.SeismicIndexLV else "standard",
            "len": idx.len, "dim": idx.dim, "nnz": idx.nnz,
            "postings_per_doc": round(idx.nnz / idx.len, 2) if idx.len else 0,
            "build_seconds": round(build_s, 1),
            "index_on_disk_mb": round(dir_size(saved) / 1e6, 2),
            "index_dir_on_disk_mb": round(disk / 1e6, 2),
            "peak_rss_gb_process": round(peak_rss_gb(), 3),
            "params": SEISMIC_PARAMS}


def build_tantivy(corpus: Path, out_dir: Path) -> dict:
    import tantivy
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    # Schema copied verbatim from lib/thinclient/builder.py so the baseline is
    # the production lexical leg, not a lookalike.
    schema = (tantivy.SchemaBuilder()
              .add_text_field("id", stored=True, tokenizer_name="raw")
              .add_text_field("title", stored=False, index_option="freq")
              .add_text_field("abstract", stored=False, index_option="freq")
              .add_integer_field("year", stored=False, indexed=True, fast=True)
              .add_text_field("doctype", stored=False, tokenizer_name="raw")
              .add_boolean_field("is_oa", stored=False, indexed=True)
              .build())
    index = tantivy.Index(schema, path=str(out_dir))
    writer = index.writer(heap_size=512 * 1024 * 1024)
    t0 = time.perf_counter()
    n = 0
    for rec in iter_corpus(corpus):
        writer.add_document(tantivy.Document(
            id=rec["id"], title=rec["title"], abstract=rec["abstract"],
            year=0, doctype="article", is_oa=False))
        n += 1
    writer.commit()
    index.reload()
    return {"index_dir": str(out_dir), "docs": n,
            "build_seconds": round(time.perf_counter() - t0, 1),
            "on_disk_mb": round(dir_size(out_dir) / 1e6, 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--corpus", type=Path, default=here / "work" / "corpus.jsonl")
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--variant", choices=["idf_in_doc", "idf_in_query", "both"],
                    default="both")
    ap.add_argument("--min-impact", type=float, default=0.0,
                    help="drop doc components below this BM25 impact (0 = keep all)")
    ap.add_argument("--skip-tantivy", action="store_true")
    ap.add_argument("--reuse-vectors", action="store_true",
                    help="reuse an already-written vectors_<variant>.jsonl")
    ap.add_argument("--n-postings", type=int, default=None,
                    help="override n_postings. At the production 3500 the global "
                         "budget (n_postings*dim) is 95x the corpus's actual "
                         "postings, so NOTHING is pruned and SEISMIC degenerates "
                         "to an exhaustive index. Lower this to make the pruning "
                         "actually bind — e.g. 9 targets tantivy's on-disk size.")
    ap.add_argument("--tag", default="",
                    help="suffix for the index dir, to keep sweeps side by side")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    args.work.mkdir(parents=True, exist_ok=True)

    if args.n_postings is not None:
        SEISMIC_PARAMS["n_postings"] = args.n_postings
        log.info("n_postings overridden to %d (production default is 3500)",
                 args.n_postings)

    report = {"corpus": str(args.corpus),
              "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "min_impact": args.min_impact,
              "n_postings": SEISMIC_PARAMS["n_postings"]}

    stats = build_stats(args.corpus)
    with open(args.work / "stats.pkl", "wb") as fh:
        pickle.dump(stats, fh, protocol=pickle.HIGHEST_PROTOCOL)
    report["stats"] = stats.to_json()
    log.info("stats saved (%s)", args.work / "stats.pkl")

    if not args.skip_tantivy:
        log.info("building tantivy baseline (production builder.py schema)…")
        report["tantivy"] = build_tantivy(args.corpus, args.work / "tantivy")
        log.info("tantivy: %s", report["tantivy"])

    variants = ([BL.VARIANT_A, BL.VARIANT_B] if args.variant == "both"
                else [args.variant])
    report["seismic"] = {}
    for v in variants:
        log.info("=== variant %s ===", v)
        jl = args.work / f"vectors_{v}.jsonl"
        if args.reuse_vectors and jl.exists():
            log.info("reusing existing %s", jl)
            vr = {"jsonl": str(jl), "reused": True,
                  "on_disk_mb": round(jl.stat().st_size / 1e6, 2)}
        else:
            vr = write_seismic_jsonl(args.corpus, stats, v, jl, args.min_impact)
        log.info("vectors: %s", vr)
        # Variant B splits every term into title/abstract namespaces, so its
        # component count is the sum of the per-field vocabularies.
        n_comp = (stats.to_json()["vocab_union"] if v == BL.VARIANT_A
                  else len(stats.df_title) + len(stats.df_abs))
        idx_dir = args.work / f"seismic_{v}{args.tag}"
        idx_dir.mkdir(exist_ok=True)
        br = build_seismic(jl, idx_dir / "bm25", n_comp)
        log.info("index: %s", br)
        report["seismic"][v] = {"vectors": vr, "index": br}

    out = args.work / f"build_report{args.tag}.json"
    out.write_text(json.dumps(report, indent=2))
    log.info("wrote %s", out)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
