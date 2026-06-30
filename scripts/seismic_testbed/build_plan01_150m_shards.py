#!/usr/bin/env python3
"""SEISMIC testbed — Plan 01 step 2: the full 150M sharded build (G7).

Builds the whole 150M corpus as K=8 deterministic shards, ONE AT A TIME, on the
32 GB host. Each global shard = the concatenation of the 5 per-section shard-k
jsonl files produced by `shard_spool.py` (the hash `blake2b(seed+oaid)%K` is
section-independent and deterministic, so global shard k is exactly the union of
section shard-k across the 5 sections → every doc lands in exactly one global
shard, reproducibly).

**Why serially, never two concurrent.** Build-RAM is linear in nnz; two builds
stack their RSS and OOM the 32 GB host. The G7 budget is ~20 GB peak RSS/shard
(each ~18.8M-doc shard projects to ~9-11 GB; the 20M measured point was 9.54 GB).

**Why concat (not re-shard globally).** `SeismicIndex.build(input_path)` reads a
single file path; section-sharding first keeps `shard_spool.py` reusable (it
knows one section at a time) and gives balanced section-level manifests. The
global shard is a streaming `cat` of the 5 section shard-k files — no decode,
no re-hash, no re-encode. Lossless per shard (no quantization, no nnz pruning).

Flow per global shard k:
  0. assert the 5 section shard-k jsonl files exist (else: shard that gap).
  1. cat section0/shard{k} ... section4/shard{k} -> global_shard{k}.jsonl  (stream)
  2. build_persona_seismic.py --jsonl global_shard{k}.jsonl --result-file <json>
     (DEFAULTS = G2-locked: n_postings 3500, centroid_fraction 0.1,
      summary_energy 0.4, max_fraction 1.5, doc_cut 15)
  3. parse peak_rss_gb from the build's stdout json + the result-file; ABORT the
     whole run if it exceeds --abort-rss-gb (default 20 = the G7 budget).
  4. delete the global_shard{k}.jsonl concat (reclaim scratch) if --keep-concat
     is not set.
  5. record (docs, peak_rss_gb, on_disk_gb, index_path, nnz) for the manifest.

Writes `shards.json` (the source-of-truth manifest for the serving layer):
  K, hash seed, build params, per-shard {docs, nnz, peak_rss_gb, on_disk_gb,
  index_path, jsonl_path}, totals, and a G7 verdict against the 25-60 GB band.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/build_plan01_150m_shards.py \\
        --out-dir /tmp/seismic_testbed/jsonl/plan01 \\
        --index-dir /tmp/seismic_testbed/index/plan01 \\
        --manifest /tmp/seismic_testbed/jsonl/plan01/shards.json

Stages (--shard-only / --build-only) let you resume: shard first (one pass per
section), then build the 8 shards in order. A --stop-after-shard N halts after
global shard N-1 builds (used to report peak RSS after shard 0 before going on).
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PY = REPO / ".venv" / "bin" / "python3"
SHARD_SPLOOL = REPO / "scripts" / "seismic_testbed" / "shard_spool.py"
BUILD = REPO / "scripts" / "seismic_testbed" / "build_persona_seismic.py"

SECTIONS = ["cs_math", "med_bio", "other", "phys_eng", "social_sciences"]
SEED = "sfu-seismic-plan01"
K = 8
# G2-locked DEFAULTS (recap of build_persona_seismic.DEFAULTS). Recorded in the
# manifest so the serving layer knows exactly what each shard was built with.
DEFAULTS = dict(n_postings=3500, centroid_fraction=0.1, summary_energy=0.4,
                max_fraction=1.5, doc_cut=15)
ABORT_RSS_GB = 20.0  # the G7 budget

log = logging.getLogger("plan01_150m")


def shard_section(section, out_dir, n_shards, hash_seed, limit=None):
    """Run shard_spool.py for one section (subprocess). Returns manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(PY), str(SHARD_SPLOOL), "--section", section,
           "--out-dir", str(out_dir), "--n-shards", str(n_shards),
           "--hash-seed", hash_seed]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    log.info("shard_spool: %s -> %s", section, out_dir)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if p.returncode != 0:
        log.error("shard_spool FAILED %s (rc=%d, %.0fs):", section, p.returncode, dt)
        log.error("stderr:\n%s", p.stderr[-3000:])
        raise RuntimeError(f"shard_spool failed for {section}")
    # splitter prints a final json line to stdout
    out = p.stdout.strip().splitlines()[-1]
    summary = json.loads(out) if out.startswith("{") else {}
    mpath = out_dir / f"{section}_shards{n_shards}_manifest.json"
    manifest = json.load(open(mpath)) if mpath.exists() else summary
    per = manifest.get("shards", [])
    docs = [s.get("docs", 0) for s in per]
    ratio = (max(docs) / min(docs)) if docs and min(docs) > 0 else float("nan")
    log.info("  %s sharded: %d docs into %d shards in %.0fs (balance max/min=%.3f)",
             section, manifest.get("docs_total", sum(docs)), len(per), dt, ratio)
    return manifest


def cat_global_shard(shard_k, section_shard_jsonls, out_path):
    """Streaming cat of the 5 section shard-k files into one global-shard jsonl.
    No decode, no re-hash — pure byte concatenation (each input line is already a
    complete {"id","vector"} record). Returns (docs, bytes)."""
    t0 = time.perf_counter()
    n = 0
    nbytes = 0
    with open(out_path, "wb") as w:
        for sp in section_shard_jsonls:
            with open(sp, "rb") as r:
                for line in r:
                    w.write(line)
                    n += 1
                    nbytes += len(line)
    dt = time.perf_counter() - t0
    log.info("  cat global shard %d: %d docs / %.2f GB from %d files in %.0fs",
             shard_k, n, nbytes / 1e9, len(section_shard_jsonls), dt)
    return n, nbytes


def watch_and_build(jsonl_path, index_path, result_file, abort_rss_gb,
                    num_threads=8):
    """Run build_persona_seismic.py as a subprocess; poll /proc/<pid>/status
    VmRSS (actual resident, not ru_maxrss which can lag spikes) and kill it
    (terminating the whole run) if it exceeds the G7 budget. Returns
    (peak_rss_gb_observed, returncode, the build's stdout json)."""
    cmd = [str(PY), str(BUILD), "--jsonl", str(jsonl_path),
           "--index-path", str(index_path), "--result-file", str(result_file),
           "--num-threads", "min(8,nproc)".replace("min(8,nproc)", str(num_threads))]
    # forward the G2-locked DEFAULTS explicitly (they are the script defaults,
    # but restating pins them in the invocation = no silent drift).
    cmd += ["--n-postings", str(DEFAULTS["n_postings"]),
            "--centroid-fraction", str(DEFAULTS["centroid_fraction"]),
            "--summary-energy", str(DEFAULTS["summary_energy"]),
            "--max-fraction", str(DEFAULTS["max_fraction"]),
            "--doc-cut", str(DEFAULTS["doc_cut"])]
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = p.pid
    peak_gb = 0.0
    status_path = Path(f"/proc/{pid}/status")
    while True:
        rc = p.poll()
        # read VmRSS while running (kB)
        if status_path.exists():
            try:
                for line in open(status_path):
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        peak_gb = max(peak_gb, rss_kb / 1024 / 1024)
                        break
            except (ValueError, OSError, StopIteration):
                pass
        if peak_gb > abort_rss_gb:
            log.error("ABORT: shard build pid=%d hit %.2f GB > %.0f GB G7 budget — killing",
                      pid, peak_gb, abort_rss_gb)
            p.kill()
            p.wait()
            return peak_gb, -9, ""
        if rc is not None:
            break
        time.sleep(2)
    dt = time.perf_counter() - t0
    out = p.stdout.read()
    p.wait()
    if p.returncode != 0:
        log.error("build FAILED rc=%d (%.0fs). stderr tail:\n%s",
                  p.returncode, dt, p.stderr[-3000:])
    else:
        log.info("  build done rc=0 in %.0fs (VmRSS peak %.2f GB)", dt, peak_gb)
    return peak_gb, p.returncode, out


def build_one_shard(shard_k, out_dir, index_dir, results_dir, abort_rss_gb,
                    keep_concat, num_threads, sections=None, n_shards=K):
    """Build global shard k. Returns a manifest dict or None on abort/failure.

    `sections` defaults to the module SECTIONS; `n_shards` defaults to K. Both
    are passed in (not read from globals) so a smoke run with a subset works."""
    sections = sections or SECTIONS
    section_shards = []
    for sect in sections:
        sp = out_dir / sect / f"{sect}_shard{shard_k}of{n_shards}.jsonl"
        if not sp.exists():
            log.error("missing section shard %s — run --shard-only first", sp)
            return None
        section_shards.append(sp)
    concat = out_dir / f"_global_shard{shard_k}.jsonl"
    index_path = index_dir / f"global_shard{shard_k}of{K}"
    result_file = results_dir / f"build_global_shard{shard_k}.json"

    docs, nbytes = cat_global_shard(shard_k, section_shards, concat)

    rss_peak, rc, stdout = watch_and_build(
        concat, index_path, result_file, abort_rss_gb, num_threads)

    entry = {"shard": shard_k, "concat_jsonl": str(concat),
             "concat_docs": docs, "concat_gb": round(nbytes / 1e9, 3),
             "rss_peak_gb_observed": round(rss_peak, 3), "build_rc": rc}

    # Preferred source: the result-file JSON the builder writes (has ru_maxrss +
    # space usage + nnz). Fall back to its stdout json if the file is missing.
    bf = {}
    if result_file.exists():
        try:
            bf = json.load(open(result_file))
        except Exception:
            bf = {}
    if not bf:
        s = stdout.strip().splitlines()
        if s and s[-1].startswith("{"):
            bf = json.loads(s[-1])

    entry["docs"] = bf.get("docs", docs)
    entry["nnz"] = bf.get("nnz")
    entry["avg_nnz_per_doc"] = bf.get("avg_nnz_per_doc")
    entry["dim"] = bf.get("dim")
    entry["variant"] = bf.get("meta", {}).get("variant")
    entry["peak_rss_gb"] = bf.get("peak_rss_gb", round(rss_peak, 3))
    entry["on_disk_gb"] = bf.get("on_disk_gb")
    entry["index_path"] = bf.get("index_path", str(index_path) + ".index.seismic")
    entry["build_seconds"] = bf.get("build_seconds")
    entry["save_seconds"] = bf.get("save_seconds")
    entry["space_usage_bytes"] = bf.get("space_usage_bytes", {})
    entry["result_file"] = str(result_file)

    if rc != 0:
        entry["status"] = "ABORTED_RSS_BUDGET" if rc == -9 and rss_peak > abort_rss_gb else "FAILED"
        return entry
    entry["status"] = "OK"

    if not keep_concat:
        try:
            concat.unlink()
            log.info("  reclaimed concat %s", concat)
        except OSError:
            pass
    # also free section-shard-k scratch per built global shard to stay lean
    if not keep_concat:
        for sp in section_shards:
            try:
                sp.unlink()
            except OSError:
                pass
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="/tmp/seismic_testbed/jsonl/plan01",
                    help="section shards live here under <section>/")
    ap.add_argument("--index-dir", default="/tmp/seismic_testbed/index/plan01")
    ap.add_argument("--results-dir", default="data/eval_results")
    ap.add_argument("--manifest", default=None,
                    help="output shards.json path (default <out-dir>/shards.json)")
    ap.add_argument("--n-shards", type=int, default=K)
    ap.add_argument("--hash-seed", default=SEED)
    ap.add_argument("--sections", nargs="+", default=SECTIONS)
    ap.add_argument("--spool-root", default="data/thinclient_index/spool_backup")
    ap.add_argument("--shard-only", action="store_true", help="only shard, don't build")
    ap.add_argument("--build-only", action="store_false", dest="do_shard")
    ap.add_argument("--stop-after-shard", type=int, default=None,
                    help="build only global shards 0..N-1 then stop (for the "
                         "report-peak-RSS-after-shard-0 checkpoint)")
    ap.add_argument("--shard-0-only", action="store_true",
                    help="build ONLY global shard 0 (the checkpoint run)")
    ap.add_argument("--start-shard", type=int, default=0,
                    help="resume: build global shards from this index onward")
    ap.add_argument("--keep-concat", action="store_true",
                    help="keep concat + section shards on disk after build (debug)")
    ap.add_argument("--abort-rss-gb", type=float, default=ABORT_RSS_GB,
                    help="kill a shard build if VmRSS exceeds this (G7 budget)")
    ap.add_argument("--num-threads", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap docs per section (smoke; None=full 150M)")
    ap.add_argument("--write-manifest-only", action="store_true",
                    help="assemble shards.json from existing build result-files "
                         "without rebuilding (resume manifest after a crash)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    out_dir = Path(args.out_dir)
    index_dir = Path(args.index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "shards.json"

    # The spool_root is fixed in shard_spool.py default; shard_spool --spool-root
    # is not exposed (it has its own default) so sections resolve under that.
    # (Shard manifest records the section, not the root.)

    sharded_manifests = {}
    if args.do_shard and not args.write_manifest_only:
        log.info("=== STAGE 1: shard %d sections into K=%d (seed=%s, limit=%s) ===",
                 len(args.sections), args.n_shards, args.hash_seed, args.limit)
        for sect in args.sections:
            # shard_spool writes into out_dir/<section> via its --out-dir ...
            # actually --out-dir is the dir the shards land in; we want per-section
            # subdirs so the 5 sections don't collide. shard_spool namespaces its
            # filenames by section already ({section}_shard{i}of{K}.jsonl), so a
            # single out dir is fine — but a per-section subdir keeps the section
            # manifest next to its shards. Use a flat out_dir (filenames are unique).
            m = shard_section(sect, out_dir / sect, args.n_shards, args.hash_seed,
                              limit=args.limit)
            sharded_manifests[sect] = m
        # balance gate
        worst = 0.0
        for sect, m in sharded_manifests.items():
            docs = [s["docs"] for s in m["shards"]]
            ratio = max(docs) / max(min(docs), 1)
            worst = max(worst, ratio)
            log.info("  balance %s: max/min=%.4f per=%s", sect, ratio, docs)
        log.info("=== sharding done. worst balance ratio=%.4f (want ~1.0) ===", worst)

    if args.shard_only:
        log.info("--shard-only: stopping after sharding.")
        return

    # STAGE 2: build global shards serially.
    log.info("=== STAGE 2: build %d global shards serially (abort RSS %.0f GB) ===",
             args.n_shards, args.abort_rss_gb)
    entries = []
    # collect any pre-existing entries (resume)
    for k in range(args.start_shard, args.n_shards):
        rf = results_dir / f"build_global_shard{k}.json"
        if k < args.start_shard:
            continue
        if rf.exists() and not args.write_manifest_only:
            try:
                bf = json.load(open(rf))
                if bf.get("docs"):
                    log.info("  shard %d already built (%d docs) — skipping", k, bf["docs"])
                    entries.append(_entry_from_resultfile(k, rf, out_dir))
                    continue
            except Exception:
                pass

    if args.write_manifest_only:
        for k in range(args.n_shards):
            rf = results_dir / f"build_global_shard{k}.json"
            entries.append(_entry_from_resultfile(k, rf, out_dir))
    else:
        kmax = args.stop_after_shard if args.stop_after_shard is not None else args.n_shards
        if args.shard_0_only:
            kmax = 1
        abort = False
        for k in range(args.start_shard, kmax):
            log.info("--- global shard %d/%d ---", k, args.n_shards)
            e = build_one_shard(k, out_dir, index_dir, results_dir,
                                args.abort_rss_gb, args.keep_concat, args.num_threads,
                                sections=args.sections, n_shards=args.n_shards)
            entries.append(e)
            if e is None or e.get("status") in ("ABORTED_RSS_BUDGET", "FAILED"):
                log.error("shard %d %s — STOPPING the run (G7 budget guard or failure).",
                          k, (e.get("status") if e else "None"))
                abort = True
                break
        if abort:
            built_k = entries[-1]["shard"] if entries and entries[-1] else -1
            log.warning("run aborted after shard %d — manifest will record partial state.",
                        built_k)

    # STAGE 3: write shards.json
    manifest = {
        "plan": "01_SHARDED_BUILD_FEDERATED_QUERY — step 2 (full 150M build)",
        "built_utc": "2026-06-28",
        "n_shards": args.n_shards,
        "hash_seed": args.hash_seed,
        "hash_fn": "blake2b(seed+oaid, digest_size=8) int % K — sections concatenated (global shard k = UNION of section shard-k)",
        "sections": args.sections,
        "build_params": {**DEFAULTS, "variant": "auto (standard unless dim>65K)",
                         "param_source": "G2-locked MS MARCO best_configs; recall-matched vs Qdrant in G2 (R-PARAM)"},
        "abort_rss_gb": args.abort_rss_gb,
        "limit": args.limit,
        "shards": entries,
        "totals": _totals(entries),
    }
    manifest["g7_verdict"] = _g7_verdict(entries, args.abort_rss_gb)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(manifest, open(manifest_path, "w"), indent=2)
    log.info("=== wrote manifest %s ===", manifest_path)
    print(json.dumps({"manifest": str(manifest_path),
                      "n_shards": args.n_shards,
                      "built": len([e for e in entries if e and e.get("status") == "OK"]),
                      "totals": manifest["totals"],
                      "g7_verdict": manifest["g7_verdict"]}))


def _entry_from_resultfile(k, rf, out_dir):
    try:
        bf = json.load(open(rf))
    except Exception:
        return {"shard": k, "status": "MISSING_RESULT_FILE", "result_file": str(rf)}
    concat = out_dir / f"_global_shard{k}.jsonl"
    return {
        "shard": k, "status": "OK" if bf.get("docs") else "INCOMPLETE",
        "docs": bf.get("docs"), "nnz": bf.get("nnz"),
        "avg_nnz_per_doc": bf.get("avg_nnz_per_doc"), "dim": bf.get("dim"),
        "variant": bf.get("meta", {}).get("variant"),
        "peak_rss_gb": bf.get("peak_rss_gb"), "on_disk_gb": bf.get("on_disk_gb"),
        "index_path": bf.get("index_path"),
        "concat_docs": None, "concat_gb": None,
        "rss_peak_gb_observed": None, "build_rc": 0,
        "build_seconds": bf.get("build_seconds"), "save_seconds": bf.get("save_seconds"),
        "space_usage_bytes": bf.get("space_usage_bytes", {}),
        "result_file": str(rf), "concat_jsonl": str(concat),
    }


def _totals(entries):
    ok = [e for e in entries if e and e.get("status") == "OK"]
    n_ok = len(ok)
    docs = sum(e.get("docs") or 0 for e in ok)
    nnz = sum(e.get("nnz") or 0 for e in ok)
    peak = [e.get("peak_rss_gb") for e in ok if e.get("peak_rss_gb") is not None]
    disk = [e.get("on_disk_gb") for e in ok if e.get("on_disk_gb") is not None]
    # peak RSS across the WHOLE 150M build = SUM of per-shard peaks IF they were
    # served concurrently (they are NOT — builds are serial). The G7 question is
    # per-shard peak (does ONE shard fit the budget), so report BOTH:
    #   max_per_shard_peak (the budget gate) + naive_sum (an upper bound for a
    #   hypothetical concurrent build, NOT how this build ran).
    return {
        "shards_ok": n_ok, "shards_attempted": len(entries),
        "docs_total": docs, "nnz_total": nnz,
        "peak_rss_gb_max_per_shard": round(max(peak), 3) if peak else None,
        "peak_rss_gb_sum_naive": round(sum(peak), 3) if peak else None,
        "on_disk_gb_total": round(sum(disk), 3) if disk else None,
        "peak_rss_note": "builds ran SERIALLY (one shard at a time); max_per_shard is the G7 gate, "
                         "sum_naive is a hypothetical-concurrent upper bound only.",
    }


def _g7_verdict(entries, budget):
    ok = [e for e in entries if e and e.get("status") == "OK"]
    if not ok:
        return "NO_SHARDS_BUILT"
    peaks = [e.get("peak_rss_gb") for e in ok if e.get("peak_rss_gb") is not None]
    max_peak = max(peaks) if peaks else None
    n_ok = len(ok)
    verdict = {
        "shards_ok": n_ok,
        "max_peak_rss_gb": round(max_peak, 3) if max_peak else None,
        "budget_gb": budget,
        "under_budget": (max_peak is not None and max_peak <= budget),
        "g7_projection_band_gb": "25-60 (power-law c=0.51 -> 25 / linear -> 60, from 4-pt curve)",
        "actually_built_150m": (n_ok == K and sum(e.get("docs") or 0 for e in ok) >= 150_000_000),
    }
    verdict["pass"] = verdict["under_budget"] and verdict["actually_built_150m"]
    return verdict


if __name__ == "__main__":
    main()
