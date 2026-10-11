#!/usr/bin/env python3
# CLOSED SUPERSEDED 2026-07-06 — BMP shard-wave parity recorder; the BMP 150M artifacts were deleted 2026-06-25 and SEISMIC promoted 2026-07-06 (docs/SEISMIC_ARCHIVE_SPLIT.md, docs/archive/bmp_decommission_plan/). Moved from scripts/ root 2026-10-11; its recorded numbers stay cited in docs/BENCHMARK_METHODOLOGY.md
"""Section/shard-wave thin-client parity recorder — produces a record-tc record
on a host too small to hold the ~211 GB SPLADE set in one process.

WHY THIS EXISTS
───────────────
`bmp.Searcher` (0.2.6, no mmap mode) loads each *.bmp shard into ANONYMOUS RAM at
a measured ~3.07x its on-disk size (see docs/THIN_CLIENT_SWAP.md). The full 150M
SPLADE leg is ~211 GB resident, so `eval_thinclient_parity.py record-tc` OOM-kills
on a 24 GB host before serving a query. Section-level waves don't help — a single
`__recent` section is up to 74 GB resident.

KEY INSIGHT (makes this EXACT, not approximate)
───────────────────────────────────────────────
The thin-client legs already merge across sections/shards by plain SCORE
CONCATENATION (retriever._splade_leg / _bm25f_leg). So partitioning the work and
joining offline reproduces the full-corpus ranking byte-for-byte:

  • BM25F runs on tantivy (mmap, ~0 resident) → one light pass over ALL sections,
    via the retriever with SFU_SKIP_BMP=1. Output is IDENTICAL to record-tc's
    bm25f field (same code path).
  • SPLADE/BMP scores are corpus-independent dot products. Each shard returns its
    top-K by score; concatenating per-shard top-K across a partition and taking
    the global top-K recovers the exact full-leg top-K (a shard's global-top-K
    contributions are always within its own top-K). So we record SPLADE shard by
    shard, each wave in a FRESH PROCESS (the only way to free BMP RAM), and merge.

The emitted JSON is schema-identical to `eval_thinclient_parity.py record-tc`, so
`eval_thinclient_parity.py compare --tc-record <this> --os-record <...>` consumes
it unchanged.

USAGE
─────
  # end-to-end (plan → prep queries → bm25f pass → splade waves → merge):
  .venv/bin/python3 scripts/archive/bmp_era/eval_parity_section_waves.py run \
      --index-root data/thinclient_index --queries 40 \
      --resident-budget-gb 8 --output data/eval_results/parity_record_tc_waves.json

  # then join against an OpenSearch record (record it separately, OOM-safe):
  .venv/bin/python3 scripts/eval_thinclient_parity.py compare \
      --tc-record data/eval_results/parity_record_tc_waves.json \
      --os-record data/eval_results/parity_record_os_<ts>.json \
      --output    data/eval_results/thinclient_parity_waves.json

Resumable: completed wave/bm25f files are reused on re-run (delete --work-dir to
force a clean run).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.thinclient.retriever import (  # noqa: E402
    BMP_ALPHA, BMP_BETA, BMP_RESIDENT_RATIO, QUANT_SCALE, SPLADE_QUERY_TERMS,
    _mem_available_gb,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("parity_waves")

TOP_K = 50


def load_queries(n: int) -> list[dict]:
    """Same selection as eval_thinclient_parity.load_queries (dedup by paraphrase)."""
    records = json.loads(
        (REPO_ROOT / "data/eval_results/diverse_queries.json").read_text())
    out, seen = [], set()
    for rec in records:
        if rec["paraphrase"] not in seen:
            seen.add(rec["paraphrase"])
            out.append(rec)
        if len(out) >= n:
            break
    return out


def discover_shards(index_root: Path) -> list[tuple[str, int]]:
    """All (relative_path, size_bytes) BMP shards under sections/, biggest first."""
    sec = index_root / "sections"
    shards = [(str(p.relative_to(index_root)), p.stat().st_size)
              for p in sec.glob("*/splade_*.bmp")]
    shards.sort(key=lambda t: -t[1])
    return shards


def plan_waves(shards: list[tuple[str, int]],
               budget_gb: float) -> list[list[str]]:
    """First-fit-decreasing bin-pack shards into waves whose projected resident
    cost (disk * BMP_RESIDENT_RATIO) stays under budget_gb. A shard larger than
    the budget gets its own wave (it still fits — largest 150M shard ~1.7 GB)."""
    budget_bytes = budget_gb * 1073741824 / BMP_RESIDENT_RATIO
    waves: list[list[str]] = []
    loads: list[int] = []
    for path, size in shards:
        placed = False
        for i, used in enumerate(loads):
            if used + size <= budget_bytes:
                waves[i].append(path)
                loads[i] += size
                placed = True
                break
        if not placed:
            waves.append([path])
            loads.append(size)
    return waves


def cmd_prep_queries(args) -> None:
    from lib.opensearch_retriever import encode_splade
    model = str(REPO_ROOT / "models" / "splade_onnx")
    out = []
    for rec in load_queries(args.queries):
        q = rec["paraphrase"]
        t0 = time.perf_counter()
        sparse = encode_splade(q, model)
        encode_ms = (time.perf_counter() - t0) * 1000
        top_terms = dict(sorted(sparse.items(),
                                key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        qvec = {t: max(1, int(round(w * QUANT_SCALE))) for t, w in top_terms.items()}
        out.append({"query": q, "judge_key": rec.get("judge_key", q),
                    "qvec": qvec, "encode_ms": round(encode_ms, 2)})
    Path(args.output).write_text(json.dumps(out))
    logger.info("prepped %d query vectors -> %s", len(out), args.output)


def cmd_bm25f(args) -> None:
    os.environ["SFU_SKIP_BMP"] = "1"
    os.environ.setdefault("SFU_DENSE_WARMCACHE", "0")
    from lib.thinclient.retriever import ThinClientRetriever
    tc = ThinClientRetriever(index_root=args.index_root, remote_abstracts=False)
    assert tc.is_available(), f"index at {args.index_root} not available"
    logger.info("bm25f pass over sections: %s", tc.live_sections())
    rows = []
    for rec in load_queries(args.queries):
        q = rec["paraphrase"]
        t0 = time.perf_counter()
        bm = [d["openalex_id"] for d in tc.search(q, TOP_K, mode="bm25f")]
        rows.append({"query": q, "judge_key": rec.get("judge_key", q),
                     "bm25f": bm, "lat_bm25f_ms": round((time.perf_counter() - t0) * 1000, 2)})
    Path(args.output).write_text(json.dumps(rows))
    logger.info("bm25f recorded %d queries -> %s", len(rows), args.output)


def _load_vocab(bmp_path: Path) -> set | None:
    """Mirror retriever._load: read the *.vocab.zst sidecar (term whitelist)."""
    vp = bmp_path.with_suffix(".vocab.zst")
    if not vp.exists():
        return None
    try:
        import zstandard
        return set(zstandard.ZstdDecompressor()
                   .decompress(vp.read_bytes()).decode().split("\n"))
    except Exception as e:
        logger.warning("bad vocab sidecar %s (%s)", vp, e)
        return None


def cmd_wave_worker(args) -> None:
    import bmp
    index_root = Path(args.index_root)
    wave = json.loads(Path(args.wave_file).read_text())
    queries = json.loads(Path(args.qvec_file).read_text())
    floor = float(os.environ.get("SFU_LOAD_MEM_FLOOR_GB", "1.5"))

    acc: dict[str, list] = {qr["query"]: [] for qr in queries}
    lat: dict[str, float] = {qr["query"]: 0.0 for qr in queries}

    for rel in wave:
        p = index_root / rel
        avail = _mem_available_gb()
        proj = p.stat().st_size / 1073741824 * BMP_RESIDENT_RATIO
        if avail is not None and avail - proj < floor:
            raise RuntimeError(
                f"wave worker abort: MemAvailable {avail:.1f} GB, shard {rel} "
                f"needs ~{proj:.1f} GB; would breach {floor:.1f} GB floor")
        vocab = _load_vocab(p)
        searcher = bmp.Searcher(str(p))
        for qr in queries:
            qvec = qr["qvec"]
            q_here = qvec
            if vocab is not None:
                q_here = {t: w for t, w in qvec.items() if t in vocab}
                if not q_here:
                    continue
            t0 = time.perf_counter()
            try:
                ids, scores = searcher.search(q_here, k=TOP_K,
                                              alpha=BMP_ALPHA, beta=BMP_BETA)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning("BMP search failed in %s: %s", rel, exc)
                continue
            lat[qr["query"]] += (time.perf_counter() - t0) * 1000
            acc[qr["query"]].extend(zip(ids, map(float, scores)))
        del searcher

    out = {}
    for q, hits in acc.items():
        hits.sort(key=lambda t: -t[1])
        out[q] = {"hits": hits[:TOP_K], "lat_splade_ms": round(lat[q], 2)}
    Path(args.output).write_text(json.dumps(out))
    logger.info("wave (%d shards) recorded -> %s", len(wave), args.output)


def cmd_merge(args) -> None:
    bm_rows = {r["query"]: r for r in json.loads(Path(args.bm25f).read_text())}
    qmeta = {qr["query"]: qr for qr in json.loads(Path(args.qvec_file).read_text())}

    splade_acc: dict[str, list] = {q: [] for q in qmeta}
    splade_lat: dict[str, float] = {q: 0.0 for q in qmeta}
    for wf in sorted(Path(args.waves_dir).glob("wave_*.json")):
        wd = json.loads(wf.read_text())
        for q, rec in wd.items():
            splade_acc[q].extend(rec["hits"])
            splade_lat[q] += rec["lat_splade_ms"]

    rows = []
    for q, qr in qmeta.items():
        hits = splade_acc[q]
        best: dict[str, float] = {}
        for did, sc in hits:
            if sc > best.get(did, float("-inf")):
                best[did] = sc
        splade = sorted(best, key=lambda d: -best[d])[:TOP_K]
        bm = bm_rows.get(q, {})
        rows.append({
            "query": q, "judge_key": qr["judge_key"],
            "bm25f": bm.get("bm25f", []),
            "splade": splade,
            "lat_bm25f_ms": bm.get("lat_bm25f_ms", 0.0),
            "lat_splade_ms": round(qr["encode_ms"] + splade_lat[q], 2),
        })

    out = {"engine": "tc", "config": {
        "index_root": args.index_root, "top_k": TOP_K, "recorded": len(rows),
        "requested": len(rows), "method": "section-shard-waves",
        "note": ("bm25f exact (tantivy mmap, full pass); splade exact "
                 "(corpus-independent shard scores merged offline); "
                 "lat_splade_ms reconstructed encode+search, hydration excluded")},
        "queries": rows}
    Path(args.output).write_text(json.dumps(out, indent=2))
    logger.info("merged record-tc -> %s (%d queries)", args.output, len(rows))


def _run(mode: str, extra: list[str], env: dict | None = None) -> None:
    cmd = [sys.executable, str(Path(__file__).resolve()), mode, *extra]
    e = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, env=e)
    if r.returncode != 0:
        raise SystemExit(f"sub-step '{mode}' failed (exit {r.returncode})")


def cmd_run(args) -> None:
    index_root = Path(args.index_root)
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    qvec_file = work / "qvecs.json"
    bm25f_file = work / "bm25f.json"
    waves_dir = work / "waves"
    waves_dir.mkdir(exist_ok=True)

    shards = discover_shards(index_root)
    waves = plan_waves(shards, args.resident_budget_gb)
    total_gb = sum(s for _, s in shards) / 1073741824
    logger.info("planned %d shards (%.1f GB disk, ~%.0f GB resident) into %d "
                "waves at %.1f GB resident-budget", len(shards), total_gb,
                total_gb * BMP_RESIDENT_RATIO, len(waves), args.resident_budget_gb)
    avail = _mem_available_gb()
    logger.info("MemAvailable now: %.1f GB", avail if avail else -1)

    if qvec_file.exists():
        logger.info("[skip] qvecs exist: %s", qvec_file)
    else:
        _run("prep-queries", ["--queries", str(args.queries),
                              "--output", str(qvec_file)])

    if bm25f_file.exists():
        logger.info("[skip] bm25f exists: %s", bm25f_file)
    else:
        _run("bm25f", ["--index-root", str(index_root),
                       "--queries", str(args.queries),
                       "--output", str(bm25f_file)])

    for wi, wave in enumerate(waves):
        wf = waves_dir / f"wave_{wi:03d}.json"
        wave_spec = work / f"_wavespec_{wi:03d}.json"
        if wf.exists():
            logger.info("[skip] wave %d/%d exists", wi + 1, len(waves))
            continue
        wave_spec.write_text(json.dumps(wave))
        disk = sum(dict(shards)[p] for p in wave) / 1073741824
        logger.info("wave %d/%d: %d shards, %.2f GB disk (~%.1f GB resident)",
                    wi + 1, len(waves), len(wave), disk, disk * BMP_RESIDENT_RATIO)
        _run("wave-worker", ["--index-root", str(index_root),
                             "--wave-file", str(wave_spec),
                             "--qvec-file", str(qvec_file),
                             "--output", str(wf)])

    _run("merge", ["--index-root", str(index_root),
                   "--bm25f", str(bm25f_file),
                   "--qvec-file", str(qvec_file),
                   "--waves-dir", str(waves_dir),
                   "--output", str(args.output)])
    logger.info("DONE — record-tc written to %s", args.output)
    logger.info("next: eval_thinclient_parity.py compare --tc-record %s "
                "--os-record <os.json> --output <summary.json>", args.output)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="end-to-end orchestrator")
    r.add_argument("--index-root", default=str(REPO_ROOT / "data/thinclient_index"))
    r.add_argument("--queries", type=int, default=40)
    r.add_argument("--resident-budget-gb", type=float, default=8.0,
                   help="max projected BMP resident RAM per wave")
    r.add_argument("--work-dir", default=str(REPO_ROOT / "data/eval_results/_waves"))
    r.add_argument("--output", default=str(REPO_ROOT / "data/eval_results/parity_record_tc_waves.json"))
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("prep-queries")
    p.add_argument("--queries", type=int, default=40)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_prep_queries)

    b = sub.add_parser("bm25f")
    b.add_argument("--index-root", required=True)
    b.add_argument("--queries", type=int, default=40)
    b.add_argument("--output", required=True)
    b.set_defaults(func=cmd_bm25f)

    w = sub.add_parser("wave-worker")
    w.add_argument("--index-root", required=True)
    w.add_argument("--wave-file", required=True)
    w.add_argument("--qvec-file", required=True)
    w.add_argument("--output", required=True)
    w.set_defaults(func=cmd_wave_worker)

    m = sub.add_parser("merge")
    m.add_argument("--index-root", required=True)
    m.add_argument("--bm25f", required=True)
    m.add_argument("--qvec-file", required=True)
    m.add_argument("--waves-dir", required=True)
    m.add_argument("--output", required=True)
    m.set_defaults(func=cmd_merge)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
