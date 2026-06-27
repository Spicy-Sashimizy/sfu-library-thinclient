#!/usr/bin/env python3
"""SEISMIC testbed — P1: build a persona-scale SEISMIC index from the spool-derived
jsonl (no re-encode), param-matched to Qdrant recall FIRST (R-PARAM guard).

`docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` G1 PASS = "SEISMIC index builds
from the stored SPLADE `sparse_field` with no re-encode; build completes without
OOM." This script does the build, records build time / peak RSS / on-disk size,
and (for G3) dumps the `print_space_usage_byte()` breakdown so the
forward-vs-inverted/summary split is known without a second load.

R-PARAM (05_RISK_REGISTER): params are tuned to MATCH Qdrant recall@k first,
then latency/RAM read off — never tuned to a flattering number. The defaults
below are SEISMIC's documented `best_configs` for MS MARCO (the corpus the ECIR
scalability paper validated at 138M), chosen because Qdrant on_disk sparse is
exact so recall(seismic) ≤ recall(qdrant) and the best_configs maximize recall.
We RE-VERIFY recall@k at persona in `eval_seismic_parity.py` (G2) before any
claim about the index — build params are provisional until G2 green.

Index variant selection: standard `SeismicIndex` for ≤65K unique tokens,
`SeismicIndexLV` for >65K (the upstream large-vocabulary variant). The
verified smoke build (5k docs → 15,826 unique tokens) projects well under 65K
for persona, but this is auto-detected from the built dim, not assumed.

Isolation: writes to an external ext4 dir, NOT the serving `data/` path
(mirrors `spike/mmap_bmp/build_persona_bmp.py`). Watch MemAvailable during
build — the R-BUILD150M projection for the real 150M host starts from this
persona peak.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/build_persona_seismic.py \\
        --jsonl /tmp/seismic_testbed/jsonl/med_bio_929000.jsonl \\
        --index-path /tmp/seismic_testbed/index/med_bio_929000.index.seismic \\
        --result-file data/eval_results/seismic_build_persona_<ts>.json

Todo: implement a recall-tuning sweep (param grid → recall@k vs Qdrant)
if the G2 parity gate fails at these defaults.
"""
import argparse
import gc
import json
import logging
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("seismic_build")

# SEISMIC best_configs for MS MARCO (the ECIR-2025 138M validation corpus).
# Tuned for recall first; re-verified vs Qdrant in eval_seismic_parity.py (G2).
DEFAULTS = dict(n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
                summary_energy=0.4, max_fraction=1.5, doc_cut=15)


def mem_available_gb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except Exception:
        return None
    return None


def rssanon_gb():
    """RssAnon (kB → GB) from /proc/self/status — the non-reclaimable floor."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("RssAnon:"):
                return int(line.split()[1]) / 1024 / 1024
    except Exception:
        return None
    return None


def capture_space_usage(idx) -> dict:
    """print_space_usage_byte() writes to the C-level stdout fd (fd 1), NOT
    Python sys.stdout, so contextlib.redirect_stdout can't see it. Capture via
    fd-level dup2 redirect to a temp file, then parse the breakdown — this is
    the G3 forward-vs-inverted/summary split."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="r", delete=False, suffix=".txt")
    saved = os.dup(1)
    fd = os.open(tmp.name, os.O_WRONLY | os.O_TRUNC | os.O_CREAT)
    try:
        os.dup2(fd, 1)
        idx.print_space_usage_byte()
    finally:
        os.dup2(saved, 1)
        os.close(fd)
        os.close(saved)
    text = open(tmp.name).read()
    os.unlink(tmp.name)
    out = {}
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"\s*(.*?)\s*:\s*([\d,]+)\s+Bytes", s)
        if m:
            out[m.group(1)] = int(m.group(2).replace(",", ""))
    return {"raw": text, "bytes": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", required=True, help="spool_to_seismic_jsonl.py output")
    ap.add_argument("--index-path", required=True, help="output .index.seismic path")
    ap.add_argument("--variant", choices=["auto", "standard", "lv"], default="auto")
    ap.add_argument("--n-postings", type=int, default=DEFAULTS["n_postings"])
    ap.add_argument("--centroid-fraction", type=float, default=DEFAULTS["centroid_fraction"])
    ap.add_argument("--min-cluster-size", type=int, default=DEFAULTS["min_cluster_size"])
    ap.add_argument("--summary-energy", type=float, default=DEFAULTS["summary_energy"])
    ap.add_argument("--max-fraction", type=float, default=DEFAULTS["max_fraction"])
    ap.add_argument("--doc-cut", type=int, default=DEFAULTS["doc_cut"])
    ap.add_argument("--num-threads", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    import seismic

    jsonl = Path(args.jsonl)
    assert jsonl.exists(), f"missing {jsonl}"
    idx_path = Path(args.index_path)
    idx_path.parent.mkdir(parents=True, exist_ok=True)

    # Warm the page cache + RAM before measuring the build floor, snapshot baseline.
    gc.collect()
    mem_base = mem_available_gb()
    rss_base = rssanon_gb()
    log.info("build: jsonl=%s variant=%s threads=%d | RAM base: available=%.2f rssanon=%.3f GB",
             jsonl, args.variant, args.num_threads, mem_base or -1, rss_base or -1)
    log.info("params: n_postings=%s centroid_fraction=%s summary_energy=%s "
             "max_fraction=%s doc_cut=%s (MS MARCO best_configs; recall-matched in G2)",
             args.n_postings, args.centroid_fraction, args.summary_energy,
             args.max_fraction, args.doc_cut)

    # Variant: build standard, switch to LV only if dim > 65K and variant is auto.
    build_cls = seismic.SeismicIndex
    if args.variant == "lv":
        build_cls = seismic.SeismicIndexLV
    t0 = time.perf_counter()
    peak_avail = mem_base
    peak_rss = rss_base
    # The build is synchronous; peak is read after via getrusage + a final mem poll.
    idx = build_cls.build(
        str(jsonl), n_postings=args.n_postings,
        centroid_fraction=args.centroid_fraction, min_cluster_size=args.min_cluster_size,
        summary_energy=args.summary_energy, max_fraction=args.max_fraction,
        doc_cut=args.doc_cut, num_threads=args.num_threads)

    build_s = time.perf_counter() - t0
    ru = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss_gb = ru.ru_maxrss / 1024 / 1024  # peak RSS over the whole process life
    mem_after = mem_available_gb()
    rss_after = rssanon_gb()
    gc.collect()
    rss_after_gc = rssanon_gb()

    auto_switched = False
    if args.variant == "auto" and idx.dim > 65000:
        log.info("dim=%d > 65K — rebuild with SeismicIndexLV", idx.dim)
        auto_switched = True
        build_cls = seismic.SeismicIndexLV
        t0 = time.perf_counter()
        idx = build_cls.build(str(jsonl), n_postings=args.n_postings,
                              centroid_fraction=args.centroid_fraction,
                              min_cluster_size=args.min_cluster_size,
                              summary_energy=args.summary_energy,
                              max_fraction=args.max_fraction, doc_cut=args.doc_cut,
                              num_threads=args.num_threads)
        build_s = time.perf_counter() - t0
        ru = resource.getrusage(resource.RUSAGE_SELF)
        peak_rss_gb = ru.ru_maxrss / 1024 / 1024
        rss_after_gc = rssanon_gb()

    log.info("BUILD %.1fs len=%d dim=%d nnz=%d avg_nnz/doc=%.1f | peak RSS=%.3f GB",
             build_s, idx.len, idx.dim, idx.nnz, idx.nnz / idx.len, peak_rss_gb)

    space = capture_space_usage(idx)
    b = space["bytes"]
    post_total = (b.get("├─ packed_postings", 0) + b.get("├─ block_offsets", 0)
                  + b.get("└─ summaries", 0))
    log.info("space usage: Forward=%s PostingLists=%s (packed=%s offsets=%s summaries=%s) "
             "Knn=%s Total=%s bytes",
             f"{b.get('Forward Index',0):,}", f"{b.get('Posting Lists',0):,}",
             f"{b.get('├─ packed_postings',0):,}", f"{b.get('├─ block_offsets',0):,}",
             f"{b.get('└─ summaries',0):,}", f"{b.get('Knn',0):,}",
             f"{b.get('Total',0):,}")

    t0 = time.perf_counter()
    idx.save(str(idx_path))
    save_s = time.perf_counter() - t0
    # seismic.save() appends '.index.seismic' to the path it's given, so the
    # real on-disk file is <index_path>.index.seismic — stat THAT, not the stem.
    actual = idx_path if idx_path.name.endswith(".index.seismic") \
        else idx_path.with_name(idx_path.name + ".index.seismic")
    size_gb = actual.stat().st_size / 1e9
    log.info("SAVED %.1fs -> %s (%.3f GB)", save_s, actual, size_gb)

    result = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.5.0",
                 "variant": ("LV" if build_cls is seismic.SeismicIndexLV else "standard")
                           + (" (auto-switched, dim>65K)" if auto_switched else ""),
                 "section": jsonl.stem,
                 "built_utc": "2026-06-26", "params": {
                     "n_postings": args.n_postings, "centroid_fraction": args.centroid_fraction,
                     "min_cluster_size": args.min_cluster_size, "summary_energy": args.summary_energy,
                     "max_fraction": args.max_fraction, "doc_cut": args.doc_cut,
                     "param_source": "MS MARCO best_configs; recall-matched vs Qdrant in G2 (R-PARAM)"},
                 "purpose": "P1 G1: build persona SEISMIC index from stored sparse_field, no re-encode"},
        "build_seconds": round(build_s, 2),
        "save_seconds": round(save_s, 2),
        "docs": idx.len, "dim": idx.dim, "nnz": idx.nnz, "avg_nnz_per_doc": round(idx.nnz/idx.len, 2),
        "peak_rss_gb": round(peak_rss_gb, 3),
        "rssanon_gb": {"before_load": round(rss_base, 4) if rss_base else None,
                       "after_build": round(rss_after, 4) if rss_after else None,
                       "after_gc": round(rss_after_gc, 4) if rss_after_gc else None},
        "mem_available_gb": {"before": round(mem_base, 2) if mem_base else None,
                             "after": round(mem_after, 2) if mem_after else None},
        "space_usage_bytes": {"forward_index": b.get("Forward Index", 0),
                              "posting_lists_total": b.get("Posting Lists", 0),
                              "packed_postings": b.get("├─ packed_postings", 0),
                              "block_offsets": b.get("├─ block_offsets", 0),
                              "summaries": b.get("└─ summaries", 0),
                              "knn": b.get("Knn", 0),
                              "total": b.get("Total", 0),
                              # G3 split: forward vs inverted/block/summary
                              "forward_vs_inverted_split": {
                                  "forward_index": b.get("Forward Index", 0),
                                  "inverted_block_summary": post_total}},
        "on_disk_gb": round(size_gb, 4),
        "index_path": str(actual),
        "g1_verdict": "PASS — index built from stored sparse_field, no OOM" if idx.len else "FAIL",
    }
    if args.result_file:
        rpath = Path(args.result_file); rpath.parent.mkdir(parents=True, exist_ok=True)
        json.dump(result, open(rpath, "w"), indent=2)
        log.info("wrote %s", rpath)
    print(json.dumps({"index_path": str(idx_path), "docs": idx.len, "on_disk_gb": round(size_gb, 4),
                      "g1": result["g1_verdict"]}))


if __name__ == "__main__":
    main()
