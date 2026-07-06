#!/usr/bin/env python3
"""SEISMIC testbed — C2.5 step E: convert the K=8 150M shards to the mmap layout.

The 150M build (Plan 01, G7) wrote each shard as a stock `*.index.seismic`
(bincode, Path A) — fine for the BUILD, but unservable on 32 GB via stock
`SeismicIndex.load()` (owned anon, ~137 GB @150M). C2.5 shipped the pyo3 mmap
reader (`seismic.MmapSeismicIndex`); this driver produces the converted mmap
*layout* each shard must be in to be loaded mmap'd (Path C: anon Δ 0.0 GB, 96%
file-resident — the C2.5 MMAP_SERVE_READY result).

Per shard, one serial pass of the `c1a_mmap_index` Rust bin (load owned →
`write_mmap_index` → `MmapSeismicIndex::from_mmap` → parity assert → floor +
latency). The bin runs the C1a/C2 gate end-to-end; this driver just queues K of
them with an RSS kill-watcher (mirrors `build_plan01_150m_shards.py`).

**Serially, never concurrent** — each conversion loads one whole shard into
owned RAM (~9.9 GB peak for an 18.8M-doc shard, same as the G7 build peak)
before writing the flat files + dropping it. Two concurrent conversions would
stack RSS and OOM the 32 GB host.

**Layout note (load-bearing, found in Piece D):** the converted dir MUST use
the C2 flat doc-mapping layout (`document_mapping_strings.bin` +
`document_mapping_offsets.bin`), NOT the stale C1a writer
(`document_mapping.bin`). The C2 reader loads `doc_mapping = None` from the old
layout → `search` falls back to numeric internal ids → overlap collapses to 0.
This driver invokes the `c1a_mmap_index` bin BUILT AGAINST THE CURRENT (C2)
writer, so the flat layout is what it produces. If you rebuild the bin from a
pre-C2 checkout, re-conversion is required.

Output: a per-shard `c25_mmap_global_shard{0..7}.json` +
`data/eval_results/seismic_c25_shards_150m_mmap.json` (the manifest: K,
per-shard conversion RSS/floor/parity, totals, a C2.5-serve verdict).

**This is a TURNKEY driver. The 8-shard 150M conversion run (run 2026-06-28)
took ~7 min wall-clock, NOT multi-hour: ~9-11 GB owned load + ~8.3 GB write
per shard × 8, serially, peak RSS 9.878 GB (≈half the 20 GB/shard budget). Run
it explicitly once you are on a box with the budget and the C2.5 persona gate
is green.**

Run from repo root (project venv; cargo env must be visible to the bin):

    sudo env "PATH=/usr/local/cargo/bin:$PATH" \\
        "CARGO_HOME=/usr/local/cargo" "RUSTUP_HOME=/usr/local/rustup" \\
        .venv/bin/python3 scripts/seismic_testbed/convert_shard_to_mmap.py \\
        --g7-manifest data/eval_results/seismic_plan01_shards_150m.json \\
        --abort-rss-gb 20
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
# The C1a bin lives in the (gitignored) spike fork target/ — built via
# `cargo build --release --bin c1a_mmap_index` from spike/seismic_upstream.
C1A_BIN = REPO / "spike" / "seismic_upstream" / "target" / "release" / "c1a_mmap_index"
ABORT_RSS_GB = 20.0  # same per-shard budget as the G7 build
N_QUERIES = 10  # parity smoke per shard (enough for a real latency #, not a full run)

log = logging.getLogger("c25_convert")


def shard_stem_from_index_path(index_path: str) -> str:
    """`/.../global_shard0of8.index.seismic` -> `/.../global_shard0of8`
    (the converted dir lands at `<stem>.mmap/`)."""
    p = str(index_path)
    return p[: -len(".index.seismic")] if p.endswith(".index.seismic") else p


def parse_c1a_stdout_json(stdout: str) -> dict:
    """The c1a bin prints ONE pretty-printed JSON object to stdout (everything
    else goes to stderr via eprintln!), so stdout is pure JSON. Parse from the
    first `{` through the final `}`. Returns {} if none."""
    start = stdout.find("{")
    if start < 0:
        return {}
    end = stdout.rfind("}")
    if end < start:
        return {}
    try:
        return json.loads(stdout[start:end + 1])
    except json.JSONDecodeError:
        return {}


def convert_one_shard(index_path: str, mmap_dir: str, abort_rss_gb: float,
                      n_queries: int) -> dict:
    """Run the c1a bin on one shard (RSS-watched, serial). Returns a manifest
    entry. Aborts the whole run if VmRSS exceeds the budget. `mmap_dir` is the
    converted output dir (may be a persistent path != sibling of the source)."""
    target = mmap_dir
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(C1A_BIN), "--index-book", str(index_path),
           "--mmap-dir", target, "--n-queries", str(n_queries)]
    log.info("converting %s -> %s", index_path, target)
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = p.pid
    peak_gb = 0.0
    status_path = Path(f"/proc/{pid}/status")
    aborted = False
    while True:
        rc = p.poll()
        if status_path.exists():
            try:
                for line in open(status_path):
                    if line.startswith("VmRSS:"):
                        peak_gb = max(peak_gb, int(line.split()[1]) / 1024 / 1024)
                        break
            except (ValueError, OSError, StopIteration):
                pass
        if peak_gb > abort_rss_gb:
            log.error("ABORT: conversion pid=%d hit %.2f GB > %.0f GB budget — killing",
                      pid, peak_gb, abort_rss_gb)
            p.kill()
            p.wait()
            aborted = True
            break
        if rc is not None:
            break
        time.sleep(2)
    dt = time.perf_counter() - t0
    stdout = p.stdout.read() if p.stdout else ""
    rc = p.returncode
    entry = {
        "index_path": index_path, "mmap_dir": target,
        "convert_seconds": round(dt, 1), "peak_rss_gb_observed": round(peak_gb, 3),
        "rc": rc, "aborted_rss_budget": aborted,
    }
    if aborted:
        entry["status"] = "ABORTED_RSS_BUDGET"
        return entry
    if rc != 0:
        entry["status"] = "FAILED"
        log.error("convert FAILED rc=%d (%.0fs). stderr tail:\n%s",
                  rc, dt, (p.stderr.read() if p.stderr else "")[-2000:])
        return entry
    parsed = parse_c1a_stdout_json(stdout)
    entry.update({
        "parity_ok": parsed.get("parity_ok"),
        "parity_failures": parsed.get("parity_failures", [])[:5],
        "floor_anon_delta_gb": parsed.get("floor_anon_delta_gb")
                              or parsed.get("rss_kb", {}).get("floor_anon_delta_vs_baseline_gb"),
        "floor_file_resident_gb": parsed.get("floor_file_resident_gb")
                                  or parsed.get("rss_kb", {}).get("floor_file_resident_gb"),
        "latency_ok": parsed.get("latency_ok"),
        "mmap_p50_ms": (parsed.get("latency_ms", {}) or {}).get("mmap", {}).get("warm_p50"),
        "path_a_p50_ms": (parsed.get("latency_ms", {}) or {}).get("path_a", {}).get("warm_p50"),
        "n_docs": parsed.get("config", {}).get("n_docs"),
        "on_disk_gb": parsed.get("config", {}).get("mmap_disk_gb"),
    })
    entry["status"] = "OK" if parsed.get("parity_ok") else "PARITY_FAIL"
    # disk size of the produced mmap dir (sanity vs the bin's on_disk report)
    try:
        dsize = sum(os.path.getsize(os.path.join(target, f)) for f in os.listdir(target))
        entry["mmap_dir_size_gb"] = round(dsize / 1e9, 3)
    except OSError:
        pass
    log.info("  done in %.0fs (VmRSS peak %.2f GB) parity=%s anon_delta=%s status=%s",
             dt, peak_gb, entry.get("parity_ok"), entry.get("floor_anon_delta_gb"), entry["status"])
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--g7-manifest", default="data/eval_results/seismic_plan01_shards_150m.json",
                    help="the Plan 01 G7 build manifest (source of shard index_paths)")
    ap.add_argument("--results-dir", default="data/eval_results")
    ap.add_argument("--abort-rss-gb", type=float, default=ABORT_RSS_GB,
                    help="kill a conversion if VmRSS exceeds this (per-shard budget)")
    ap.add_argument("--n-queries", type=int, default=N_QUERIES,
                    help="parity queries per shard (10 = a real latency #, not a full run)")
    ap.add_argument("--start-shard", type=int, default=0, help="resume from this shard index")
    ap.add_argument("--stop-after-shard", type=int, default=None,
                    help="convert only shards 0..N-1 (checkpoint)")
    ap.add_argument("--out-manifest", default=None,
                    help="output manifest path (default <results-dir>/seismic_c25_shards_150m_mmap.json)")
    ap.add_argument("--mmap-out-dir", default=None,
                    help="PERSISTENT directory to write converted .mmap/ dirs into "
                         "(overrides the default 'sibling .mmap next to the source'). "
                         "G7 sources can live on volatile /tmp scratch; this keeps the "
                         "served mmap shards on a non-volatile path that survives reboot. "
                         "The per-shard dir is <mmap-out-dir>/<global_shardKofN>.mmap.")
    ap.add_argument("--list-only", action="store_true",
                    help="print the shard -> mmap-dir plan and exit (no conversion)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if not C1A_BIN.exists():
        log.error("c1a_mmap_index bin not found at %s — build it first:\n"
                  "  cd spike/seismic_upstream && cargo build --release --bin c1a_mmap_index",
                  C1A_BIN)
        return 2

    g7 = json.load(open(args.g7_manifest))
    shards = g7.get("shards", [])
    plan = []
    for s in shards:
        ip = s.get("index_path")
        if not ip or not Path(ip).exists():
            log.warning("skip shard %s: index_path missing/absent (%s)", s.get("shard"), ip)
            continue
        stem = shard_stem_from_index_path(ip)
        # Default: converted mmap dir = sibling <stem>.mmap next to the source.
        # With --mmap-out-dir: write to a PERSISTENT dir (survives /tmp wipes) so
        # the served shards are not on volatile scratch. The source G7 .index.seismic
        # may stay on /tmp (regenerable from spool_backup); only the served mmap dir
        # needs to persist. Per-shard dir name keeps the source stem for traceability.
        if args.mmap_out_dir:
            mmap_dir = str(Path(args.mmap_out_dir) / f"{Path(stem).name}.mmap")
        else:
            mmap_dir = f"{stem}.mmap"
        plan.append({"shard": s["shard"], "index_path": ip,
                     "mmap_dir": mmap_dir,
                     "docs": s.get("docs"), "nnz": s.get("nnz")})
    if not plan:
        log.error("no convertible shards resolved from %s", args.g7_manifest)
        return 2
    log.info("C2.5 shard->mmap conversion plan: %d shards (abort RSS %.0f GB, n_queries=%d)",
             len(plan), args.abort_rss_gb, args.n_queries)
    if args.list_only:
        for p in plan:
            print(f"  shard {p['shard']}: {p['index_path']} -> {p['mmap_dir']}")
        return 0

    kmax = args.stop_after_shard if args.stop_after_shard is not None else len(plan)
    entries = []
    abort = False
    for p in plan:
        if p["shard"] < args.start_shard:
            continue
        if p["shard"] >= kmax:
            break
        e = convert_one_shard(p["index_path"], p["mmap_dir"], args.abort_rss_gb, args.n_queries)
        e["shard"] = p["shard"]
        e["source_docs"] = p.get("docs")
        e["source_nnz"] = p.get("nnz")
        entries.append(e)
        if e.get("status") in ("ABORTED_RSS_BUDGET", "FAILED", "PARITY_FAIL"):
            log.error("shard %d %s — STOPPING the conversion run.", p["shard"], e["status"])
            abort = True
            break

    ok = [e for e in entries if e.get("status") == "OK"]
    peaks = [e.get("peak_rss_gb_observed") for e in ok if e.get("peak_rss_gb_observed") is not None]
    anon = [e.get("floor_anon_delta_gb") for e in ok if e.get("floor_anon_delta_gb") is not None]
    disk = [e.get("mmap_dir_size_gb") for e in ok if e.get("mmap_dir_size_gb") is not None]
    totals = {
        "shards_ok": len(ok), "shards_attempted": len(entries),
        "peak_rss_gb_max": round(max(peaks), 3) if peaks else None,
        "mmap_dir_gb_total": round(sum(disk), 3) if disk else None,
        "floor_anon_delta_gb_max": round(max(anon), 3) if anon else None,
        "all_parity_ok": all(e.get("parity_ok") for e in ok) if ok else False,
    }
    c25_ready = (totals["shards_ok"] == len(plan)
                 and totals["all_parity_ok"]
                 and (totals["floor_anon_delta_gb_max"] is None
                      or totals["floor_anon_delta_gb_max"] < 0.1))
    out_manifest = {
        "plan": "C2.5 step E — 150M shard -> mmap layout conversion (turnkey driver)",
        "built_utc": "2026-06-28",
        "source_g7_manifest": args.g7_manifest,
        "n_shards": len(plan), "abort_rss_gb": args.abort_rss_gb,
        "n_queries_per_shard": args.n_queries,
        "layout_note": "C2 flat doc-mapping (strings+offsets); the c1a bin must be "
                       "built against the current (C2) writer — stale C1a writer "
                       "produces document_mapping.bin, which the C2 reader loads as "
                       "doc_mapping=None -> search falls back to numeric ids.",
        "shards": entries, "totals": totals,
        "c25_serve_verdict": ("C2.5 150M_MMAP_READY" if c25_ready and not abort
                              else "C2.5 150M_MMAP_INCOMPLETE"),
    }
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    mpath = Path(args.out_manifest) if args.out_manifest else (
        results_dir / "seismic_c25_shards_150m_mmap.json")
    json.dump(out_manifest, open(mpath, "w"), indent=2)
    log.info("=== wrote manifest %s ===", mpath)
    print(json.dumps({"manifest": str(mpath), "shards_ok": totals["shards_ok"],
                      "shards_attempted": totals["shards_attempted"],
                      "peak_rss_gb_max": totals["peak_rss_gb_max"],
                      "c25_serve_verdict": out_manifest["c25_serve_verdict"]}))
    return 0 if c25_ready else 1


if __name__ == "__main__":
    sys.exit(main())
