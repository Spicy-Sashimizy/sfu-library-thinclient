#!/usr/bin/env python3
"""OCI demo payload MANIFEST — the curated set of files that ships to the demo box.

Lifecycle: tool
Doc: docs/infrastructure/OCI_DEMO_DEPLOYMENT.md

Phase 1 of `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §9 ("seed"): before the
~120 GB one-time upload can be made resumable it has to be ENUMERABLE. This
script walks the *served* set (not the whole repo, not the 187 GB seismic dir
with its rollback ladder) and emits a manifest JSON:

    {generated_utc, repo_root, options, components: {...}, files: [
        {"path": "<repo-relative>", "bytes": N, "mtime_ns": N, "sha256": "..."},
        ...
    ], totals: {files, bytes, gb}}

`scripts/demo_broker/seed_oci_volume.sh` consumes it as an rsync
`--files-from` list, so the manifest is the single definition of "the payload".

READ-ONLY with respect to `data/`. `data/seismic_150m/` is IRREPLACEABLE: shard
files there are `stat`ed and (with --hash) opened O_RDONLY, never written.
The manifest is written to `scripts/data/demo_payload_manifest.json` (NOT
`data/eval_results/` — that directory is for eval results).

Usage
-----
    .venv/bin/python3 scripts/demo_broker/build_demo_payload_manifest.py
    ... --hash                     # full sha256 (slow: ~108 GB), resumable
    ... --out /path/manifest.json  # alternate output
    ... --files-from -             # print the rsync files-from list to stdout
    ... --include-dense            # add back the ablated dense leg (3 files)
    ... --sqlite-free-abstracts    # drop abstracts.sqlite where a .flat exists

Hashing is RESUMABLE across runs: an entry whose `bytes` + `mtime_ns` are
unchanged from the existing manifest keeps its recorded sha256 and is not
re-read. Interrupt a `--hash` run and re-run it: it picks up where it stopped
(the partial manifest is flushed every --flush-every hashed files).

EFFICACY: this is an inventory tool; the measured payload total it produced on
2026-08-19 is recorded in `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §2/§8.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "scripts" / "data" / "demo_payload_manifest.json"

SERVED_SHARD_MANIFEST = (
    REPO / "data" / "eval_results" / "seismic_c25_shards_150m_mmap_e5_v2.json"
)

EXCLUDE_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".ipynb_checkpoints", "node_modules", ".git",
}
EXCLUDE_SUFFIXES = (
    ".pyc", ".pyo", ".log", ".tmp", ".partial", ".swp",
    "-wal", "-shm", ".sqlite-journal",
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _served_shard_dirs() -> list[Path]:
    """The 8 `*.dotvbyte.e5.v2.mmap` dirs, read from the served shard manifest
    rather than glob-guessed, so a manifest flip moves the payload with it."""
    if not SERVED_SHARD_MANIFEST.exists():
        raise SystemExit(
            f"ERROR: served shard manifest missing: {SERVED_SHARD_MANIFEST}\n"
            "  (the payload's shard set is DEFINED by it — refusing to guess)")
    m = json.loads(SERVED_SHARD_MANIFEST.read_text())
    dirs = []
    for s in m.get("shards", []):
        d = s.get("mmap_dir")
        if not d:
            continue
        p = Path(d)
        dirs.append(p if p.is_absolute() else REPO / p)
    return dirs


def _v5_excluder(rel: Path) -> bool:
    """models/sfu-academic-embed-v5/checkpoints/ is 3.0 GB of TRAINING
    checkpoints; the serve path loads model.safetensors + the tokenizer only."""
    return "checkpoints" in rel.parts


def _code_excluder(rel: Path) -> bool:
    parts = rel.parts
    if parts[:2] == ("scripts", "data"):
        return True
    return False


def build_components(include_dense: bool, sqlite_free_abstracts: bool) -> list[dict]:
    """The include list. Every EXCLUSION below is deliberate and dated — see the
    per-entry comments; the exclusions are as load-bearing as the inclusions.

    NOT IN THE PAYLOAD, by decision:
      * `data/thinclient_index/dense/` (b1.usearch + rescore_int8.npy +
        ids.json, 0.357 GB) — the dense leg was ABLATED 2026-08-18, verdict
        DROP (Δ nDCG@10 −0.0077, CI excludes 0; static coverage 0.4% of 150M).
        `SFU_DENSE_LEG` is DEFAULT OFF in code since that date. Opt back in with
        --include-dense. See docs/DENSE_PARTITION_AND_ABLATION.md §7.
      * `data/thinclient_index/dense/delta.sqlite` (+ -wal/-shm) — the query-
        driven warm cache's RUNTIME STATE. Never shipped, not even with
        --include-dense (it re-creates itself, and shipping it would carry this
        container's query history to the demo box).
      * every non-served shard variant under data/seismic_150m/index/plan01/
        (`*.mmap`, `*.dotvbyte.mmap`, `*.dotvbyte.e5.mmap`, `e5_perms/`) — the
        rollback ladder lives on the build host; only the manifest's e5.v2 dv
        set ships. This is the 187 GB → 42 GB cut.
      * `data/thinclient_index/packed/` (44 GB of hot/cold tar.zst) — the
        packer's TRANSPORT archives of artifacts already in `sections/`;
        shipping both would double-count.
      * `data/thinclient_index/spool/` — build spool (empty at rest).
      * `.venv/` — rebuilt on the target from
        scripts/portable_linux/serving_requirements_linux.lock.txt (a Linux venv
        with torch is ~6 GB of files that pip reproduces).
      * `models/` other than the serve-path four (v1/v4 embedders, splade
        fp16/onnx/teacher/student, trt_engine_cache) — dead or training-only.
    """
    comps: list[dict] = [
        {
            "name": "seismic_served_shards",
            "note": "the 8 e5.v2 dotvbyte mmap shards named by the served "
                    "manifest — the SPLADE/SEISMIC leg",
            "paths": _served_shard_dirs(),
        },
        {
            "name": "seismic_shard_manifest",
            "note": "the served shard-set manifest itself (the pointer the "
                    "retriever's promotion default resolves to)",
            "paths": [SERVED_SHARD_MANIFEST],
        },
        {
            "name": "thinclient_meta",
            "note": "meta.sqlite (filter + hydrate) + the index manifests",
            "paths": [
                REPO / "data" / "thinclient_index" / "meta.sqlite",
                REPO / "data" / "thinclient_index" / "manifest.json",
                REPO / "data" / "thinclient_index" / "build_status.json",
            ],
        },
        {
            "name": "thinclient_sections",
            "note": "tantivy BM25F (10 sections) + the hot-section abstract "
                    "sidecar (social_sciences__recent: abstracts.sqlite and/or "
                    "the N5 flat block store abstracts.sqlite.flat/)",
            "paths": [REPO / "data" / "thinclient_index" / "sections"],
        },
        {
            "name": "models_serve_path",
            "note": "SPLADE ONNX query encoder + dense v5 query encoder (shared "
                    "with the embed-rerank stage, so it ships even with the "
                    "dense leg dropped) + the cross-encoder reranker",
            "paths": [
                REPO / "models" / "splade_onnx_fused",
                REPO / "models" / "sfu-academic-embed-v5",
                REPO / "models" / "sfu-cross-encoder-v1",
                REPO / "models" / "sfu-cross-encoder-v1-onnx-int8",
                REPO / "models" / "model_registry.json",
            ],
            "exclude": _v5_excluder,
        },
        {
            "name": "seismic_portable_so",
            "note": "WI-4's x86-64-v3 portable .so — runs on E4/E5 Flex with no "
                    "recompile (an A1/ARM box needs an aarch64 build first)",
            "paths": [
                REPO / "spike" / "seismic_upstream" / "target" / "portable_so"
                     / "v3" / "seismic",
                REPO / "spike" / "seismic_upstream" / "target" / "portable_so"
                     / "seismic_x86_64_v3.so",
            ],
        },
        {
            "name": "code",
            "note": "the serve path (source/), the GUI "
                    "(web/) and the operational scripts (scripts/)",
            "paths": [REPO / "source", REPO / "web", REPO / "scripts"],
            "exclude": _code_excluder,
        },
    ]
    if include_dense:
        comps.append({
            "name": "dense_leg_OPTIONAL",
            "note": "ABLATED 2026-08-18 (verdict DROP); included because "
                    "--include-dense was passed",
            "paths": [
                REPO / "data" / "thinclient_index" / "dense" / "b1.usearch",
                REPO / "data" / "thinclient_index" / "dense" / "rescore_int8.npy",
                REPO / "data" / "thinclient_index" / "dense" / "ids.json",
            ],
        })
    if sqlite_free_abstracts:
        base = next(c for c in comps if c["name"] == "thinclient_sections")
        prev = base.get("exclude")

        def _drop_abs_sqlite(rel: Path, _prev=prev) -> bool:
            if _prev is not None and _prev(rel):
                return True
            if rel.name == "abstracts.sqlite":
                sib = REPO / rel.parent / "abstracts.sqlite.flat"
                return sib.is_dir()
            return False

        base["exclude"] = _drop_abs_sqlite
        base["note"] += " [--sqlite-free-abstracts: abstracts.sqlite dropped " \
                        "where a verified .flat sidecar exists]"
    return comps


def _excluded_name(name: str) -> bool:
    return name.endswith(EXCLUDE_SUFFIXES)


def _iter_files(root: Path, exclude) -> list[Path]:
    """Absolute paths of every file under `root` (or `root` itself if a file),
    minus the global excludes and the component's own `exclude` predicate."""
    out: list[Path] = []
    if root.is_file():
        rel = root.relative_to(REPO)
        if not _excluded_name(root.name) and not (exclude and exclude(rel)):
            out.append(root)
        return out
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIR_NAMES)
        d = Path(dirpath)
        for fn in sorted(filenames):
            if _excluded_name(fn):
                continue
            fp = d / fn
            if fp.is_symlink() or not fp.is_file():
                continue
            rel = fp.relative_to(REPO)
            if exclude and exclude(rel):
                continue
            out.append(fp)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_prior(out_path: Path) -> dict[str, dict]:
    """Existing manifest indexed by path — the resume state for --hash."""
    if not out_path.exists():
        return {}
    try:
        prior = json.loads(out_path.read_text())
    except (ValueError, OSError):
        return {}
    return {e["path"]: e for e in prior.get("files", []) if "path" in e}


def build_manifest(out_path: Path, do_hash: bool = False,
                   include_dense: bool = False,
                   sqlite_free_abstracts: bool = False,
                   flush_every: int = 25,
                   progress=None) -> dict:
    comps = build_components(include_dense, sqlite_free_abstracts)
    prior = _load_prior(out_path) if do_hash else {}

    files: list[dict] = []
    comp_summary: list[dict] = []
    seen: set[str] = set()
    missing: list[str] = []
    hashed = reused = 0

    for comp in comps:
        c_files = c_bytes = 0
        for p in comp["paths"]:
            if not p.exists():
                missing.append(str(p.relative_to(REPO)) if str(p).startswith(str(REPO))
                               else str(p))
                continue
            for fp in _iter_files(p, comp.get("exclude")):
                rel = str(fp.relative_to(REPO))
                if rel in seen:
                    continue
                seen.add(rel)
                st = fp.stat()
                entry = {"path": rel, "bytes": st.st_size,
                         "mtime_ns": st.st_mtime_ns, "component": comp["name"]}
                if do_hash:
                    old = prior.get(rel)
                    if (old and old.get("sha256")
                            and old.get("bytes") == st.st_size
                            and old.get("mtime_ns") == st.st_mtime_ns):
                        entry["sha256"] = old["sha256"]
                        reused += 1
                    else:
                        entry["sha256"] = _sha256(fp)
                        hashed += 1
                        if progress:
                            progress(rel, st.st_size)
                        if flush_every and hashed % flush_every == 0:
                            _write(out_path, _record(files + [entry], comp_summary,
                                                     do_hash, include_dense,
                                                     sqlite_free_abstracts,
                                                     missing, partial=True))
                files.append(entry)
                c_files += 1
                c_bytes += st.st_size
        comp_summary.append({"name": comp["name"], "note": comp["note"],
                             "files": c_files, "bytes": c_bytes,
                             "gb": round(c_bytes / 1e9, 3)})

    rec = _record(files, comp_summary, do_hash, include_dense,
                  sqlite_free_abstracts, missing)
    rec["hash_stats"] = {"hashed_this_run": hashed, "reused_from_prior": reused}
    return rec


def _record(files, comp_summary, do_hash, include_dense, sqlite_free_abstracts,
            missing, partial: bool = False) -> dict:
    total = sum(f["bytes"] for f in files)
    return {
        "probe": "oci_demo_payload_manifest",
        "generated_utc": _now_utc(),
        "repo_root": str(REPO),
        "partial": partial,
        "options": {"hash": do_hash, "include_dense": include_dense,
                    "sqlite_free_abstracts": sqlite_free_abstracts},
        "served_shard_manifest": str(SERVED_SHARD_MANIFEST.relative_to(REPO)),
        "components": comp_summary,
        "missing_paths": missing,
        "totals": {"files": len(files), "bytes": total,
                   "gb": round(total / 1e9, 3), "gib": round(total / (1 << 30), 3)},
        "files": files,
    }


def _write(out_path: Path, rec: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".writing")
    tmp.write_text(json.dumps(rec, indent=1))
    os.replace(tmp, out_path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"manifest path (default {DEFAULT_OUT})")
    ap.add_argument("--hash", action="store_true",
                    help="compute sha256 (slow over ~108 GB; resumable)")
    ap.add_argument("--include-dense", action="store_true",
                    help="add the ablated dense leg's 3 files (never delta.sqlite)")
    ap.add_argument("--sqlite-free-abstracts", action="store_true",
                    help="drop abstracts.sqlite where a .flat sidecar exists "
                         "(doc 18 §18; verify the locator gate first)")
    ap.add_argument("--flush-every", type=int, default=25,
                    help="flush the partial manifest every N hashed files "
                         "(0 = never; makes --hash resumable)")
    ap.add_argument("--files-from", metavar="PATH",
                    help="also write the rsync --files-from list here ('-' = stdout)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out

    def _progress(rel, nbytes):
        if not args.quiet:
            print(f"  hashed {nbytes/1e9:8.3f} GB  {rel}", file=sys.stderr)

    rec = build_manifest(out, do_hash=args.hash,
                         include_dense=args.include_dense,
                         sqlite_free_abstracts=args.sqlite_free_abstracts,
                         flush_every=args.flush_every,
                         progress=_progress if args.hash else None)
    _write(out, rec)

    if args.files_from:
        lines = "".join(f["path"] + "\n" for f in rec["files"])
        if args.files_from == "-":
            sys.stdout.write(lines)
        else:
            fp = Path(args.files_from)
            if not fp.is_absolute():
                fp = REPO / fp
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(lines)

    if not args.quiet:
        print(f"wrote {out}")
        for c in rec["components"]:
            print(f"  {c['name']:26s} {c['files']:7d} files  {c['gb']:9.3f} GB")
        t = rec["totals"]
        print(f"  {'TOTAL':26s} {t['files']:7d} files  {t['gb']:9.3f} GB "
              f"({t['gib']:.3f} GiB)")
        if rec["missing_paths"]:
            print("  MISSING (not on this host): " + ", ".join(rec["missing_paths"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
