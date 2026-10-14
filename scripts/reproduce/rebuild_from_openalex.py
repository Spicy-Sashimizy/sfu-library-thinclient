#!/usr/bin/env python3
"""Rebuild a servable Duck Library index from the public OpenAlex snapshot.

One command takes raw OpenAlex ``works`` part files (JSONL.gz, exactly as
published at ``s3://openalex/data/jsonl/works/``) to every artifact type the
served stack reads: per-section tantivy BM25F indexes, ``meta.sqlite`` (v2
layout), the abstract sidecars, a SPLADE-encoded SEISMIC shard in the served
``dotvbyte v2`` mmap format, and the shard manifest. It then writes a
``serve.env`` for the retriever and runs ``verify_rebuild.py`` against the
result.

It reuses the delta-ingest chain (``spike/delta_ingest``) with an EMPTY base
index, so the whole corpus lands in one published generation whose directory
is served directly as the index root. Nothing here touches the repo's
``data/`` tree; the work dir must be on local disk outside it.

Usage (from the repo root, with the venv):

    .venv/bin/python3 scripts/reproduce/rebuild_from_openalex.py \
        --work /var/tmp/duck_rebuild --download 1 --limit 50000

    .venv/bin/python3 scripts/reproduce/rebuild_from_openalex.py \
        --work /var/tmp/duck_rebuild --part /path/to/part_0005.gz

Outputs under ``--work``: ``parts/`` (downloads), ``base/`` (empty),
``delta/g0001/`` (the index root to serve), ``serve.env``,
``verify.json`` and ``rebuild_report.json`` (timings, counts, sizes, host).

Measured record and the full recipe (toolchain, models, limits):
``docs/REPRODUCIBILITY.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST_URL = "https://openalex.s3.amazonaws.com/data/jsonl/works/manifest.json"
S3_PREFIX = "s3://openalex/"
HTTPS_PREFIX = "https://openalex.s3.amazonaws.com/"
PART_SIZE_DEFAULT = (40_000, 120_000)
ONE_GENERATION = 1_000_000_000


def log(msg: str) -> None:
    print(f"[rebuild {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_manifest(dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MANIFEST_URL, timeout=120) as r:
        dest.write_bytes(r.read())
    return json.loads(dest.read_text())


def choose_parts(manifest: dict, n: int, lo: int, hi: int) -> list[dict]:
    files = [f for f in manifest["files"] if lo <= f["meta"]["record_count"] <= hi]
    files.sort(key=lambda f: f["url"], reverse=True)
    if len(files) < n:
        sys.exit(f"only {len(files)} parts have {lo}..{hi} records; lower --min-records or --max-records")
    return files[:n]


def download_part(entry: dict, parts_dir: Path) -> Path:
    url = entry["url"].replace(S3_PREFIX, HTTPS_PREFIX, 1)
    name = "__".join(entry["url"].split("/")[-2:])
    dest = parts_dir / name
    want = int(entry["meta"]["content_length"])
    if dest.exists() and dest.stat().st_size == want:
        log(f"have {name} ({want} B)")
        return dest
    parts_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log(f"download {url} ({want / 1e6:.1f} MB)")
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh, length=1 << 20)
    got = tmp.stat().st_size
    if got != want:
        sys.exit(f"{name}: downloaded {got} B, manifest says {want} B")
    tmp.rename(dest)
    log(f"downloaded {name} in {time.perf_counter() - t0:.1f}s")
    return dest


def run_cli(args: list[str], log_path: Path) -> tuple[int, float, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "source") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, "-m", "spike.delta_ingest.cli", *args]
    log("$ " + " ".join(cmd))
    t0 = time.perf_counter()
    with open(log_path, "ab") as fh:
        fh.write(("\n$ " + " ".join(cmd) + "\n").encode())
        fh.flush()
        p = subprocess.run(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        fh.write(p.stdout)
    out = p.stdout.decode(errors="replace")
    return p.returncode, time.perf_counter() - t0, out


def last_json(text: str) -> dict:
    start = text.rfind("\n{")
    if start < 0:
        return {}
    try:
        return json.loads(text[start + 1:])
    except json.JSONDecodeError:
        return {}


def du(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def host_facts() -> dict:
    facts = {"python": sys.version.split()[0], "platform": platform.platform(), "cpu_count": os.cpu_count()}
    try:
        facts["mem_total_gb"] = round(int(next(l for l in open("/proc/meminfo") if l.startswith("MemTotal")).split()[1]) / 2**20, 1)
    except Exception:
        pass
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=10)
        facts["gpu"] = q.stdout.strip().splitlines()[0] if q.returncode == 0 and q.stdout.strip() else None
    except Exception:
        facts["gpu"] = None
    try:
        facts["git_commit"] = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                                             capture_output=True, text=True).stdout.strip()
    except Exception:
        facts["git_commit"] = None
    return facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--work", required=True, help="local-disk work dir, outside the repo's data/ tree")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--part", action="append", help="local OpenAlex works part (.gz); repeatable")
    src.add_argument("--download", type=int, metavar="N", help="download N parts picked from the live manifest")
    ap.add_argument("--min-records", type=int, default=PART_SIZE_DEFAULT[0])
    ap.add_argument("--max-records", type=int, default=PART_SIZE_DEFAULT[1])
    ap.add_argument("--limit", type=int, default=None, help="stop each part after this many input works")
    ap.add_argument("--profile", default="desktop_gpu", choices=["desktop_gpu", "laptop", "server"])
    ap.add_argument("--encode-device", default=None, help="cuda | cpu (default: the profile's auto)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--queries", nargs="*", default=None, help="verification queries (default: three built in)")
    args = ap.parse_args(argv)

    work = Path(args.work).resolve()
    data_dir = (REPO / "data").resolve()
    if work == data_dir or data_dir in work.parents or REPO in work.parents and work.is_relative_to(data_dir):
        sys.exit("--work must not be under the repo's data/ tree")
    parts_dir, base, delta = work / "parts", work / "base", work / "delta"
    base.mkdir(parents=True, exist_ok=True)
    delta.mkdir(parents=True, exist_ok=True)
    log_path = work / "rebuild.log"
    report: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "work": str(work),
                    "args": vars(args), "host": host_facts(), "steps": []}
    t_all = time.perf_counter()

    if args.download:
        t0 = time.perf_counter()
        manifest = fetch_manifest(work / "openalex_manifest.json")
        picks = choose_parts(manifest, args.download, args.min_records, args.max_records)
        report["snapshot"] = {"manifest_date": manifest.get("date"), "total_records": manifest.get("record_count"),
                              "parts": [{"url": p["url"], **p["meta"]} for p in picks]}
        parts = [download_part(p, parts_dir) for p in picks]
        report["steps"].append({"step": "download", "seconds": round(time.perf_counter() - t0, 1),
                                "bytes": sum(p.stat().st_size for p in parts)})
    else:
        parts = [Path(p).resolve() for p in args.part]
        for p in parts:
            if not p.is_file():
                sys.exit(f"missing part file {p}")

    common = ["--index-root", str(base), "--delta-root", str(delta), "--profile", args.profile,
              "--flush-docs", str(ONE_GENERATION), "--buffer-max-docs", str(ONE_GENERATION)]
    if args.encode_device:
        common += ["--encode-device", args.encode_device]
    kept = 0
    for p in parts:
        cli = ["ingest", "--source", "jsonl", "--openalex-shape", "--path", str(p), *common]
        if args.limit:
            cli += ["--limit", str(args.limit)]
        rc, secs, out = run_cli(cli, log_path)
        summary = last_json(out)
        report["steps"].append({"step": "ingest", "part": p.name, "rc": rc, "seconds": round(secs, 1),
                                "totals": summary.get("totals", summary)})
        if rc != 0:
            log(f"ingest failed (rc={rc}); see {log_path}")
            (work / "rebuild_report.json").write_text(json.dumps(report, indent=1))
            return rc
        tot = summary.get("totals", summary)
        kept += int(tot.get("seen", 0) or 0)

    rc, secs, out = run_cli(["flush", "--force", *common], log_path)
    flush = last_json(out)
    report["steps"].append({"step": "flush", "rc": rc, "seconds": round(secs, 1),
                            "frozen_generation": flush.get("frozen_generation"), "frozen_docs": flush.get("frozen_docs")})
    if rc != 0 or "frozen_generation" not in flush:
        log(f"flush failed (rc={rc}); see {log_path}")
        (work / "rebuild_report.json").write_text(json.dumps(report, indent=1))
        return rc or 1

    gen_dir = delta / f"g{int(flush['frozen_generation']):04d}"
    gen = json.loads((gen_dir / "generation.json").read_text())
    manifests = sorted((delta / "shard_manifests").glob("shard_manifest-*.json"))
    manifest_path = manifests[-1]
    serve_env = {
        "SFU_THINCLIENT_INDEX_ROOT": str(gen_dir),
        "SFU_SEISMIC_SHARD_MANIFEST": str(manifest_path),
        "SFU_SPLADE_BACKEND": "seismic",
        "SFU_SEISMIC_LOAD_MODE": "mmap",
        "SFU_DENSE_LEG": "0",
    }
    (work / "serve.env").write_text("".join(f"{k}={v}\n" for k, v in serve_env.items()))
    report["result"] = {
        "index_root": str(gen_dir), "shard_manifest": str(manifest_path), "serve_env": str(work / "serve.env"),
        "records_after_abstract_filter": kept, "docs_indexed": gen.get("n_docs") or flush.get("frozen_docs"),
        "note": "input lines read per part = --limit (or the whole part); works without a usable abstract (< 50 chars, or paratext) are dropped by normalize_openalex_work before counting",
        "sections": {k: v["docs"] for k, v in gen["sections"].items()},
        "seismic": gen["seismic"],
        "bytes": {"generation_total": du(gen_dir), "seismic_mmap": du(gen_dir / gen["seismic"]["mmap_dir"]),
                  "meta_sqlite": (gen_dir / "meta.sqlite").stat().st_size,
                  "sections": du(gen_dir / "sections")},
    }

    if not args.no_verify:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import verify_rebuild
        t0 = time.perf_counter()
        v = verify_rebuild.verify(serve_env, args.queries)
        (work / "verify.json").write_text(json.dumps(v, indent=1))
        report["steps"].append({"step": "verify", "seconds": round(time.perf_counter() - t0, 1), "status": v["status"]})
        report["verify"] = {"status": v["status"], "queries": [(q["q"], q["n_hits"], q["legs_hit_counts"]) for q in v["queries"]]}

    report["total_seconds"] = round(time.perf_counter() - t_all, 1)
    (work / "rebuild_report.json").write_text(json.dumps(report, indent=1))
    log(f"index root: {gen_dir}")
    log(f"serve env:  {work / 'serve.env'}")
    log(f"report:     {work / 'rebuild_report.json'}  (total {report['total_seconds']}s)")
    return 0 if report.get("verify", {}).get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
