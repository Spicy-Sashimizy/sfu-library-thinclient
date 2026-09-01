#!/usr/bin/env python3
"""Phase 3 (v1) — ship the FULL seismic set into the bundle, bit-exact.

Chosen 2026-08-04 (owner): the design doc §5 pragmatic v1 — copy the 8
whole-corpus `*.e5.v2.mmap` shards verbatim and let social-only filtering happen
at hydration (candidates outside social_sciences self-drop because the bundle's
trimmed meta.sqlite only holds social rows). No new Rust, bit-exact, verifiable
here on Linux. The v2 subset-rebuild (~7 GiB) is a tracked size optimization on
top — see the design doc §5 and the README.

Produces:

    $BUNDLE/seismic/
      global_shard{0..7}of8.dotvbyte.e5.v2.mmap/   (copied verbatim)
      shards.e5.v2.json                            (bundle-local manifest,
                                                     ABSOLUTE mmap_dir paths)

The retriever consumes the manifest via SFU_SEISMIC_SHARD_MANIFEST; each shard's
`mmap_dir` is used as-is when absolute (sharded_seismic_backend.py:337), so the
bundle serves off its own copies with no repo-root anchoring.

    # full copy + manifest (idempotent; resumes; ~42 GiB, copy-bound):
    .venv/bin/python3 scripts/portable_socsci/03_seismic_full.py

    # regenerate ONLY the manifest for a different shard location (e.g. the
    # Windows launcher pointing at the mounted drive) — no copy:
    .venv/bin/python3 scripts/portable_socsci/03_seismic_full.py \
        --manifest-only --seismic-root 'E:/seismic'

Env: BUNDLE (default /var/tmp/portable_socsci_bundle), SRC_MANIFEST (default
data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json — the promoted e5.v2
served set). Read-only on data/seismic_150m (IRREPLACEABLE).
"""
import argparse
import json
import os
import subprocess
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUNDLE = os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle")
SRC_MANIFEST = os.environ.get(
    "SRC_MANIFEST",
    os.path.join(REPO_ROOT, "data", "eval_results",
                 "seismic_c25_shards_150m_mmap_e5_v2.json"))

BSEISMIC = os.path.join(BUNDLE, "seismic")
MANIFEST_OUT = os.path.join(BSEISMIC, "shards.e5.v2.json")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _abs(path):
    """Resolve a manifest mmap_dir (repo-root-relative or absolute) to abs."""
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def load_records():
    with open(SRC_MANIFEST) as fh:
        man = json.load(fh)
    records = man.get("shards", [])
    if not records:
        raise SystemExit(f"no shards in {SRC_MANIFEST}")
    return man, records


def copy_shard(src_dir, dst_dir):
    """cp -a one shard dir, idempotent on the load-bearing forward_data.bin size.

    reflink=auto is a no-op fast-path on overlayfs (falls back to a full copy),
    harmless elsewhere. We copy the whole shard verbatim (incl. the tiny
    hotset_*.json prefault sidecars) so the set stays bit-exact with the served
    index; the F6 prefault simply won't apply on Windows (design §7)."""
    fwd = "forward_data.bin"
    src_fwd = os.path.join(src_dir, fwd)
    dst_fwd = os.path.join(dst_dir, fwd)
    if (os.path.isdir(dst_dir) and os.path.exists(dst_fwd)
            and os.path.getsize(dst_fwd) == os.path.getsize(src_fwd)):
        log(f"  {os.path.basename(dst_dir)} already present "
            f"({_du(dst_dir) / 2**30:.2f} GiB) — skip")
        return
    log(f"  copying {os.path.basename(src_dir)} "
        f"({_du(src_dir) / 2**30:.2f} GiB)...")
    os.makedirs(BSEISMIC, exist_ok=True)
    os.makedirs(dst_dir, exist_ok=True)
    subprocess.run(
        ["cp", "-a", "--reflink=auto", f"{src_dir}/.", dst_dir],
        check=True)


def write_manifest(src_man, records, seismic_root):
    """Emit the bundle-local manifest. Each record keeps its informational build
    stats but gets `mmap_dir`/`index_path` repointed at `seismic_root` (absolute).
    `seismic_root` is the dir that CONTAINS the shard dirs on the serving host."""
    out_records = []
    for rec in records:
        base = os.path.basename(rec["mmap_dir"].rstrip("/"))
        mmap_dir = os.path.join(seismic_root, base)
        new = dict(rec)
        new["mmap_dir"] = mmap_dir
        new["index_path"] = mmap_dir
        new["source_mmap_dir"] = rec["mmap_dir"]
        out_records.append(new)
    manifest = {
        "plan": "PORTABLE_SOCSCI v1 — full seismic (bit-exact) shipped in bundle",
        "derived_from": os.path.relpath(SRC_MANIFEST, REPO_ROOT),
        "assembled_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seismic_root": seismic_root,
        "n_shards": len(out_records),
        "forward_format_version": src_man.get("forward_format_version", 2),
        "note": ("full-corpus shards; social-only filtering is at hydration via "
                 "the bundle's trimmed meta.sqlite (non-social candidates "
                 "self-drop). Regenerate with --manifest-only --seismic-root to "
                 "repoint at the drive's mount location on the target host."),
        "shards": out_records,
    }
    os.makedirs(BSEISMIC, exist_ok=True)
    with open(MANIFEST_OUT, "w") as fh:
        json.dump(manifest, fh, indent=2)
    log(f"wrote manifest {MANIFEST_OUT} "
        f"({len(out_records)} shards, seismic_root={seismic_root})")
    return manifest


def _du(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest-only", action="store_true",
                    help="skip the copy; only (re)write the shard manifest")
    ap.add_argument("--seismic-root", default=None,
                    help="dir that contains the shard dirs on the serving host "
                         "(default: the bundle's own $BUNDLE/seismic, absolute)")
    args = ap.parse_args()

    t0 = time.time()
    src_man, records = load_records()
    seismic_root = args.seismic_root or os.path.abspath(BSEISMIC)

    if not args.manifest_only:
        log(f"phase 3 (v1 full seismic): {len(records)} shards -> {BSEISMIC}")
        for rec in records:
            src_dir = _abs(rec["mmap_dir"])
            if not os.path.isdir(src_dir):
                raise SystemExit(f"source shard missing: {src_dir}")
            dst_dir = os.path.join(BSEISMIC, os.path.basename(src_dir.rstrip("/")))
            copy_shard(src_dir, dst_dir)

    manifest = write_manifest(src_man, records, seismic_root)

    report = {
        "bundle": BUNDLE,
        "seismic_root": seismic_root,
        "manifest": MANIFEST_OUT,
        "n_shards": len(records),
        "manifest_only": args.manifest_only,
    }
    if not args.manifest_only:
        report["seismic_gib"] = round(_du(BSEISMIC) / 2**30, 2)
        report["per_shard_gib"] = {
            os.path.basename(s["mmap_dir"]): round(
                _du(s["mmap_dir"]) / 2**30, 2) for s in manifest["shards"]}
    report["total_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(report, indent=2), flush=True)
    with open(os.path.join(BUNDLE, "_seismic_full_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
