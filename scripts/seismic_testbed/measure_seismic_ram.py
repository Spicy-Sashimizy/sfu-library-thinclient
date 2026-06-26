#!/usr/bin/env python3
"""SEISMIC testbed — P2 G3: resident RAM floor, forward-vs-inverted/summary split.

`docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` G3 = "measure resident RAM/doc
for Path A, broken into forward-index vs inverted/block/summary side; if it
confirms ~RAM-resident (≳ Qdrant's 43 B/pt → >6.55 GB @150M proj.), Path A is
RAM-NO-GO." Mirrors the BMP probe (`spike/mmap_bmp/measure_p3a_inverted_floor.py`).

Two lenses (per `03_BENCHMARK_METHODOLOGY.md` "RAM measurement is load-bearing"):
  1. OS view — RssAnon (`/proc/self/status`) + Pss_Anon (`smaps_rollup`):
     non-reclaimable private-dirty, the floor that causes OOM.
  2. Engine view — `print_space_usage_byte()` breakdown: Forward Index vs
     Posting Lists (packed_postings + block_offsets + summaries). These are the
     STRUCTURAL bytes; if RssAnon ≈ Total, the index is resident (R-RAM, RAM-
     resident like BMP). If RssAnon ≪ Total, it's page-cache-resident (cure).
Captured via fd-level dup2 (print_space_usage_byte writes to fd 1, not Python
sys.stdout). Per-doc rate so persona → 150M extrapolation is honest.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/measure_seismic_ram.py \
        --index-path /tmp/seismic_testbed/index/med_bio_2m \
        --result-file data/eval_results/seismic_ram_floor_persona_2m.json
"""
import argparse
import gc
import json
import logging
import os
import re
import resource
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("seismic_ram")

QDRANT_REF_BYTES_PER_DOC = 43 * (1 << 30) / 150_000_000  # ~43B/doc → 6.55GB@150M
BMP_REF_GB = 211.0  # retired baseline


def rssanon_kb():
    for line in open("/proc/self/status"):
        if line.startswith("RssAnon:"):
            return int(line.split()[1])
    return None


def pssanon_kb():
    try:
        txt = open("/proc/self/smaps_rollup").read()
        for line in txt.splitlines():
            if line.startswith("Pss_Anon:"):
                return int(line.split()[1])
    except Exception:
        return None
    return None


def rssfile_kb():
    for line in open("/proc/self/status"):
        if line.startswith("RssFile:"):
            return int(line.split()[1])
    return None


def capture_space_usage(idx) -> dict:
    """print_space_usage_byte() writes to fd 1 (C-level), NOT Python stdout."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="r", delete=False, suffix=".txt")
    saved = os.dup(1)
    fd = os.open(tmp.name, os.O_WRONLY | os.O_TRUNC | os.O_CREAT)
    try:
        os.dup2(fd, 1)
        idx.print_space_usage_byte()
    finally:
        os.dup2(saved, 1)
        os.close(fd); os.close(saved)
    text = open(tmp.name).read()
    os.unlink(tmp.name)
    out = {}
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"\s*(.*?)\s*:\s*([\d,]+)\s+Bytes", s)
        if m:
            out[m.group(1)] = int(m.group(2).replace(",", ""))
    return {"raw": text, "bytes": out}


def gb(kb):
    return round(kb / 1024 / 1024, 4) if kb else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-path", required=True, help=".index.seismic stem")
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()
    import seismic

    fp = args.index_path if args.index_path.endswith(".index.seismic") \
        else f"{args.index_path}.index.seismic"
    assert os.path.exists(fp), f"missing {fp}"

    gc.collect()
    rss0, pss0, rf0 = rssanon_kb(), pssanon_kb(), rssfile_kb()
    log.info("baseline RSS: RssAnon=%s RssFile=%s Pss_Anon=%s GB",
             gb(rss0), gb(rf0), gb(pss0))

    t0 = time.perf_counter()
    idx = seismic.SeismicIndex.load(fp)
    load_s = time.perf_counter() - t0
    rss1, pss1, rf1 = rssanon_kb(), pssanon_kb(), rssfile_kb()
    log.info("after load (%.1fs) len=%d: RssAnon=%s RssFile=%s Pss_Anon=%s GB",
             load_s, idx.len, gb(rss1), gb(rf1), gb(pss1))

    gc.collect()
    rss2, pss2, rf2 = rssanon_kb(), pssanon_kb(), rssfile_kb()
    log.info("after gc: RssAnon=%s RssFile=%s Pss_Anon=%s GB",
             gb(rss2), gb(rf2), gb(pss2))

    space = capture_space_usage(idx)
    b = space["bytes"]
    forward = b.get("Forward Index", 0)
    post_total = b.get("Posting Lists", 0)
    inverted_block_summary = (b.get("├─ packed_postings", 0)
                              + b.get("├─ block_offsets", 0)
                              + b.get("└─ summaries", 0))
    total = b.get("Total", 0)

    # RAM floor: the resident anon DELTA from loading. If it's ≈ Total bytes,
    # the whole index lives in anon RAM (R-RAM confirmed — BMP-style). If it's
    # ≪ Total (mostly RssFile / cache), it's page-cache-resident (RAM cured).
    anon_delta_kb = (rss2 or rss0 or 0) - (rss0 or 0)
    anon_delta_gb = gb(anon_delta_kb)
    resid_frac = (anon_delta_kb * 1024 / total) if total else None
    per_doc_bytes = (anon_delta_kb * 1024 / idx.len) if idx.len else None
    proj_150m_gb = (per_doc_bytes * 150_413_098 / 1e9) if per_doc_bytes else None

    log.info("space: Forward=%s Postings=%s (packed=%s offsets=%s summaries=%s) "
             "Total=%s bytes", f"{forward:,}", f"{post_total:,}",
             f"{b.get('├─ packed_postings',0):,}", f"{b.get('├─ block_offsets',0):,}",
             f"{b.get('└─ summaries',0):,}", f"{total:,}")
    log.info("RAM floor: anon delta=%s GB (%.2f%% of Total) | per-doc=%s B | "
             "150M proj=%s GB (Qdrant ref 6.55; BMP ref 211)",
             anon_delta_gb, 100 * (resid_frac or 0),
             f"{per_doc_bytes:.1f}" if per_doc_bytes else "n/a",
             f"{proj_150m_gb:.1f}" if proj_150m_gb else "n/a")

    # G3 verdict
    ram_cured = resid_frac is not None and resid_frac < 0.25  # mostly cache, not anon
    if per_doc_bytes is not None:
        ram_no_go = per_doc_bytes >= QDRANT_REF_BYTES_PER_DOC
    else:
        ram_no_go = None
    if ram_cured:
        verdict = ("G3 PASS (Path-C-style) — resident anon %.2f%% of Total; "
                   "mostly page-cache. But note: SEISMIC FOSS loads into anon, "
                   "this is measuring that load" % (100 * (resid_frac or 0)))
    elif ram_no_go:
        verdict = ("G3 FAIL — RAM-resident (Path A): %.0f B/doc ≳ Qdrant 43 B/doc; "
                   "150M proj %.1f GB. Path A is RAM-NO-GO; routes to B-vs-C."
                   % (per_doc_bytes, proj_150m_gb))
    else:
        verdict = ("G3 PARTIAL — %.1f B/doc (Qdrant ref 43), 150M proj %.1f GB; "
                   "RssAnon delta %.2f%% of Total. Path A is resident but smaller "
                   "than Qdrant — NOT the ~211GB BMP floor; quantify more at scale"
                   % (per_doc_bytes, proj_150m_gb, 100 * (resid_frac or 0)))

    result = {
        "meta": {"engine": "seismic-pyseismic-lsr-0.5.0", "built_utc": "2026-06-26",
                 "index": fp, "docs": idx.len, "dim": idx.dim, "nnz": idx.nnz,
                 "purpose": "P2 G3: resident RAM/doc with forward-vs-inverted/summary split + 150M projection"},
        "rss_gb": {"baseline": gb(rss0), "after_load": gb(rss1), "after_gc": gb(rss2),
                   "anon_delta": anon_delta_gb,
                   "rssfile": {"baseline": gb(rf0), "after_load": gb(rf1), "after_gc": gb(rf2)},
                   "pss_anon": {"baseline": gb(pss0), "after_load": gb(pss1), "after_gc": gb(pss2)}},
        "space_usage_bytes": {"forward_index": forward, "posting_lists_total": post_total,
                              "packed_postings": b.get("├─ packed_postings", 0),
                              "block_offsets": b.get("├─ block_offsets", 0),
                              "summaries": b.get("└─ summaries", 0), "knn": b.get("Knn", 0),
                              "total": total,
                              "forward_vs_inverted_split": {
                                  "forward_index": forward,
                                  "inverted_block_summary": inverted_block_summary,
                                  "split_note": "which side dominates decides the cheap Path C scope "
                                               "(mmap-forward-only vs whole-index)"}},
        "ram_floor": {"anon_delta_gb": anon_delta_gb,
                      "resid_fraction_of_total": round(resid_frac, 4) if resid_frac else None,
                      "per_doc_bytes": round(per_doc_bytes, 2) if per_doc_bytes else None,
                      "proj_150m_gb": round(proj_150m_gb, 2) if proj_150m_gb else None,
                      "refs": {"qdrant_b_per_doc": round(QDRANT_REF_BYTES_PER_DOC, 2),
                               "qdrant_150m_gb": 6.55, "bmp_150m_gb": BMP_REF_GB}},
        "g3_verdict": verdict,
    }
    rpath = (Path(args.result_file) if args.result_file
             else Path(f"data/eval_results/seismic_ram_floor_{idx.len}_{int(time.time())}.json"))
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"g3_verdict": verdict, "per_doc_bytes": per_doc_bytes,
                      "proj_150m_gb": proj_150m_gb, "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
