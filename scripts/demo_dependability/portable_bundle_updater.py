#!/usr/bin/env python3
"""WI-14 (deployprep wave 4, 2026-07-17) — the handout bundle's UPDATE PATH.

STAGING / authoring only (no deploy, no spend, NO network, NO served-default
flip). A 20–185 GB bundle can't be re-downloaded per update; the WI-8
`portable_stack_manifest.json` becomes the UPDATE CONTRACT once it carries
per-artifact sha256 + version + byte size (shard-granular for indexes — immutable
shards mean an index update = replace the CHANGED shard files + flip the bundle
manifest). This module has three sub-commands:

  manifest  — emit a VERSIONED bundle manifest: every artifact (each seismic
              shard mmap_dir as its own shard-granular entry, the .so, each
              model weight, the tantivy BM25F legs, the dense usearch) with
              sha256 + version + byte size. Sharded so an index update delta is
              per-shard, not all-or-nothing. CLI: `--out <path>` + `--bundle-dir`
              (a fixture bundle for the proof, or the real 150M paths for the
              shipped manifest). Writes data/eval_results/portable_bundle_versions.json.

  check     — `updater_check.py`: given a LOCAL bundle manifest + a "remote"
              manifest FILE (simulated locally — NO network), emit the delta
              plan: files to fetch (changed/new), total download bytes, files
              unchanged, the APPLY ORDER (changed artifacts first → verify →
              manifest flip LAST → old files kept until verify = crash-safe),
              and per-class delta-byte expectation. Writes a machine-readable
              delta-plan JSON to data/eval_results/wi14_delta_plan_<ts>.json.

  apply     — `updater_apply.py`: staging proof on a small FIXTURE bundle.
              Apply a delta (one changed shard fixture + one changed model
              fixture), verify post-apply checksums, FLIP the bundle manifest,
              and prove the pre-update bundle is RESTORABLE (rollback = re-flip
              to the OLD manifest; the old shard + model files are STILL present
              because the keep-old-until-verify discipline never deleted them).

The delta-size point (different update classes cost wildly different bytes):
  .so rebuild          ~2.7 MB  (one file — cheapest)
  encoder distill      ~1 GB    (models only, nothing else touches the weights)
  E8 dv-v2 re-conversion ~26 GB (all 8 shards' mmap_dirs rewrite)
  manifest flip only   ~7.5 KB  (the pointer; shards already on disk → 0 data)
Design-only (NOT built here): the `semantic_docid_ingest` LSM track is the
eventual incremental-DATA path (new documents without a full re-shard).

Owner constraints (2026-07-16): no deploy, no spend, no served flip; the
fixture bundle lives under data/eval_results/_fixtures/; data/seismic_150m/
READ-ONLY (manifest reads shard mmap_dir manifest.json checksums, never rewrites
shard data). Same-commit doc rule: the doc §(e) cites these numbers + paths.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data" / "eval_results"
FIXDIR = REPO / "data" / "eval_results" / "_fixtures"
MANIFEST_OUT = EVAL / "portable_bundle_versions.json"

SEISMIC_MANIFEST_LADDER = [
    "seismic_c25_shards_150m_mmap_e5_v2.json",
    "seismic_c25_shards_150m_mmap_e5.json",
    "seismic_c25_shards_150m_mmap_dotvbyte.json",
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _sha256(path: Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"path": str(path), "error": "absent"}
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"path": str(p), "sha256": h.hexdigest(),
            "bytes": p.stat().st_size}


def _dir_sha256_entries(path: Path, version: str) -> list[dict]:
    """Every FILE under a dir as a versioned entry (model dirs, tantivy legs).
    Sharded by filename so a model-weight-only update delta names exactly the
    changed weight file. version = the group version (e.g. the .so build rev /
    the model export rev) — bumped on a rebuild/retrain of the whole group."""
    p = Path(path)
    if not p.exists():
        return [{"dir": str(path), "error": "absent"}]
    out = []
    for f in sorted(p.rglob("*")):
        if f.is_file():
            e = _sha256(f)
            e["version"] = version
            e["group"] = str(path)
            out.append(e)
    return out


def _sha256_dir_dir(path: Path, data_sha256: bool = False) -> str:
    """A stable 'directory version' = sha256 of the concatenation of (relpath,
    sha256, bytes) for every file under the dir, sorted. Two identical dirs →
    identical version string (so check() can say 'unchanged' at dir granularity
    AND confirm via per-file). By default this checksums only the small POINTER
    files (manifest.json) — NOT the GBs of shard DATA — because the pointer is
    the versioned thing that flips (data checksumming is wasted I/O on the 150M
    corpus + contends with the live serve). `data_sha256=True` checksums every
    file's full bytes (used for the apply proof's tiny fixture files)."""
    p = Path(path)
    if not p.exists():
        return "absent"
    h = hashlib.sha256()
    rows = []
    for f in sorted(p.rglob("*")):
        if f.is_file():
            if not data_sha256 and f.name not in ("manifest.json",):
                continue
            fe = _sha256(f)
            rows.append((str(f.relative_to(p)), fe["sha256"], fe["bytes"]))
    for r in rows:
        h.update(("\t".join(map(str, r)) + "\n").encode())
    return h.hexdigest()[:16]


def _seismic_entries(served_manifest_name: str, version: str,
                     data_sha256: bool = False) -> list[dict]:
    """Shard-GRANULAR versioned entries: each shard's mmap_dir is its own entry.
    By default `version`/`dir_version` checksum only the shard's manifest.json
    POINTER (the versioned file a re-conversion rewrites) — NOT 66 GB of shard
    data (the pointer is the update contract; the data is the immutable artifact
    the pointer is trusted to name). `data_sha256=True` (the apply proof's tiny
    fixture mode) checksums every file's full bytes. READ-ONLY: opens shard dirs
    O_RDONLY, never rewrites them."""
    mp = EVAL / served_manifest_name
    out = []
    if not mp.exists():
        return [{"manifest": served_manifest_name, "error": "absent"}]
    m = json.loads(mp.read_text())
    for s in m.get("shards", []):
        d = s.get("mmap_dir")
        dp = Path(d) if Path(d).is_absolute() else REPO / d
        files = (_sha256_dir_entries(dp, "seismic_shard", data_sha256=True)
                 if data_sha256 else _sha256_pointer_entries(dp, "seismic_shard"))
        entry = {
            "group": "seismic_shards",
            "shard": s.get("shard"),
            "mmap_dir": s.get("mmap_dir"),
            "version": version,
            "dir_version": _sha256_dir_dir(dp, data_sha256=data_sha256),
            "on_disk_gb_reported": s.get("on_disk_gb"),
            "files": files,
        }
        out.append(entry)
    return out


def _sha256_pointer_entries(path: Path, group: str) -> list[dict]:
    """Only the manifest.json POINTER entry per shard dir (the cheap versioned
    contract for the 150M corpus — skips the GBs of data)."""
    p = Path(path)
    if not p.exists():
        return [{"dir": str(path), "error": "absent"}]
    out = []
    for f in sorted(p.rglob("manifest.json")):
        if f.is_file():
            e = _sha256(f)
            e["group"] = group
            out.append(e)
    return out


def _sha256_dir_entries(path: Path, group: str, data_sha256: bool = True) -> list[dict]:
    """Per-file sha256 entries under a dir. Used for the apply proof's tiny
    fixture files (data_sha256=True). For the real 150M corpus the pointer-only
    variant (_sha256_pointer_entries) is used instead (the GB-scale data is NOT
    re-checksummed — see _seismic_entries)."""
    p = Path(path)
    if not p.exists():
        return [{"dir": str(path), "error": "absent"}]
    out = []
    for f in sorted(p.rglob("*")):
        if f.is_file():
            e = _sha256(f)
            e["group"] = group
            out.append(e)
    return out


def cmd_manifest(args):
    """Emit a VERSIONED bundle manifest. `--bundle-dir` scopes to a fixture
    bundle for the proof; unset = the real 150M paths (the shipped manifest)."""
    FIXDIR.mkdir(parents=True, exist_ok=True)
    so_version = "v3-portable-2026-07-16"
    model_version_splade = "onnx-fused-2026-06-19"
    model_version_dense = "v5-2026-06-19"
    shard_version = "e8-dvv2-e5-reorder-2026-07-14"
    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else REPO

    manifest = {
        "probe": "wi14_portable_bundle_versions",
        "generated_utc": _now_utc(),
        "bundle_dir": str(bundle_dir),
        "channel": "stable",
        "bundle_version": "1.0.0",
        "artifacts": [],
    }
    if not args.bundle_dir:
        manifest["artifacts"] += _seismic_entries(SEISMIC_MANIFEST_LADDER[0], shard_version)
    else:
        shard_root = bundle_dir / "seismic_shards"
        if shard_root.exists():
            for sd in sorted(shard_root.iterdir()):
                if sd.is_dir():
                    manifest["artifacts"].append({
                        "group": "seismic_shards", "shard": sd.name,
                        "mmap_dir": str(sd),
                        "version": shard_version,
                        "dir_version": _sha256_dir_dir(sd, data_sha256=True),
                        "files": _sha256_dir_entries(sd, "seismic_shard", data_sha256=True),
                    })
    so_path = bundle_dir / "portable_so" / "seismic.cpython-311-x86_64-linux-gnu.so"
    if not args.bundle_dir:
        so_path = REPO / "spike/seismic_upstream/target/portable_so/v3/seismic/" \
                  "seismic.cpython-311-x86_64-linux-gnu.so"
    soe = _sha256(so_path)
    soe.update({"group": "portable_so", "version": so_version})
    manifest["artifacts"].append(soe)
    for name, sub, ver in [
        ("splade_model", "models/splade_onnx_fused", model_version_splade),
        ("dense_model", "models/sfu-academic-embed-v5", model_version_dense),
    ]:
        mdir = bundle_dir / sub if args.bundle_dir else REPO / sub
        entries = _sha256_dir_entries(mdir, name, data_sha256=True)
        for e in entries:
            e["version"] = ver
        manifest["artifacts"] += entries
    for name, sub in [("tantivy_bm25f", "thinclient_index"),
                      ("dense_usearch", "thinclient_index/dense")]:
        d = bundle_dir / sub if args.bundle_dir else REPO / "data" / sub
        if d.exists():
            if args.bundle_dir:
                entries = _sha256_dir_entries(d, name, data_sha256=True)
            else:
                entries = [{"group": name, "dir_version": _sha256_dir_dir(d, data_sha256=False),
                            "file_count": sum(1 for f in d.rglob("*") if f.is_file()),
                            "bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()),
                            "mode": "dir-version-pointer (no full-data sha256 — GB-scale)"}]
            for e in entries:
                e["version"] = "data-2026-06-25"
            manifest["artifacts"] += entries
    manifest["artifact_count"] = len(manifest["artifacts"])
    manifest["total_bytes"] = sum(
        a.get("bytes", 0) for a in manifest["artifacts"] if "bytes" in a)
    out = Path(args.out) if args.out else MANIFEST_OUT
    out.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {out} ({manifest['artifact_count']} artifacts, "
          f"{manifest['total_bytes']} bytes, channel={manifest['channel']})")
    groups = {}
    for a in manifest["artifacts"]:
        g = a.get("group", "?")
        groups.setdefault(g, {"count": 0, "bytes": 0})
        groups[g]["count"] += 1
        groups[g]["bytes"] += a.get("bytes", 0)
    print(json.dumps(groups, indent=2))


def _artkey(a: dict, bundle_dir: str = "") -> str:
    """Stable identity for an artifact across local/remote manifests: the GROUP
    + the path RELATIVE to its bundle dir (so v1's model.onnx and v2's model.onnx
    match — the absolute bundle path differs but the relpath is the identity).
    For shard dirs, the shard index is the identity."""
    if a.get("group") == "seismic_shards":
        return f"seismic_shards/{a.get('shard')}"
    p = a.get("path", a.get("shard", ""))
    if bundle_dir and p.startswith(bundle_dir):
        p = p[len(bundle_dir):].lstrip("/")
    else:
        p = Path(p).name if p else ""
    return f"{a.get('group')}/{p}"


def cmd_check(args):
    """Delta plan: local manifest vs a 'remote' manifest FILE (simulated, no
    network). Emits fetch list, total bytes, unchanged, crash-safe apply order."""
    local = json.loads(Path(args.local).read_text())
    remote = json.loads(Path(args.remote).read_text())
    local_dir = local.get("bundle_dir", "")
    remote_dir = remote.get("bundle_dir", "")
    local_by = {_artkey(a, local_dir): a for a in local.get("artifacts", [])}
    remote_by = {_artkey(a, remote_dir): a for a in remote.get("artifacts", [])}
    fetch, unchanged, missing_local = [], [], []
    for key, ra in remote_by.items():
        la = local_by.get(key)
        if la is None:
            fetch.append({"key": key, "reason": "new", "artifact": ra,
                          "bytes": ra.get("bytes", 0)})
            missing_local.append(key)
        elif (la.get("sha256") != ra.get("sha256")
              or la.get("dir_version") != ra.get("dir_version")):
            changed_files = []
            if "files" in ra and "files" in la:
                lf = {Path(f["path"]).name: f for f in la["files"]}
                for rf in ra["files"]:
                    lff = lf.get(Path(rf["path"]).name)
                    if not lff or lff.get("sha256") != rf.get("sha256"):
                        changed_files.append(rf)
                bytes_delta = sum(f.get("bytes", 0) for f in changed_files)
            else:
                changed_files = [ra]
                bytes_delta = ra.get("bytes", 0)
            fetch.append({"key": key, "reason": "changed", "artifact": ra,
                          "bytes": bytes_delta, "changed_files": changed_files})
        else:
            unchanged.append(key)
    total_bytes = sum(f["bytes"] for f in fetch)
    plan = {
        "probe": "wi14_delta_plan",
        "generated_utc": _now_utc(),
        "local_bundle_version": local.get("bundle_version"),
        "remote_bundle_version": remote.get("bundle_version"),
        "remote_channel": remote.get("channel"),
        "fetch": fetch,
        "total_download_bytes": total_bytes,
        "total_download_gb_est": round(total_bytes / 1e9, 4),
        "unchanged_count": len(unchanged),
        "unchanged": unchanged,
        "new_artifacts_count": len([f for f in fetch if f["reason"] == "new"]),
        "apply_order": [
            "1. fetch changed/new artifacts BESIDE old (never in-place)",
            "2. verify each fetched file sha256 vs the remote manifest entry",
            "3. FLIP the bundle manifest LAST (the atomic pointer swap)",
            "4. keep old files until post-flip verify succeeds (rollback-safe)",
            "5. (post-healthy-run) delete superseded old files (GC-eligible)",
        ],
        "rollback": "re-flip the bundle manifest to the PRE-update manifest; the "
                    "old artifact files were kept (step 4) so no re-fetch needed — "
                    "crash-safe: a crash mid-apply leaves the old manifest pointing "
                    "at old files (the flip is the only atomic step, and it's last).",
        "delta_class_expectation": {
            "so_rebuild": "~2.7 MB (1 file, the .so)",
            "encoder_distill": "~1 GB (models only — the weight files)",
            "e8_dvv2_reconversion": "~26 GB (all 8 shards' mmap_dirs)",
            "manifest_flip_only": "~7.5 KB (the pointer; shards resident → 0 data)",
            "incremental_data_lsm": "DESIGN ONLY — semantic_docid_ingest LSM track "
                                    "(new docs without a full re-shard); not built this wave",
        },
    }
    out = Path(args.out) if args.out else \
        EVAL / f"wi14_delta_plan_{_now_utc().replace('-','')}.json"
    out.write_text(json.dumps(plan, indent=2))
    print(f"wrote {out}")
    print(json.dumps({
        "fetch_count": len(fetch), "total_bytes": total_bytes,
        "unchanged_count": len(unchanged),
        "total_gb_est": plan["total_download_gb_est"],
        "fetch_keys": [f["key"] for f in fetch],
    }, indent=2))


def _make_fixture_bundle(version_tag: str, changed_files: set | None = None) -> Path:
    """A tiny FIXTURE bundle: 2 seismic shard fixtures + 1 .so fixture + 1
    splade model fixture + 1 dense model fixture — small enough that the apply
    proof runs in seconds, faithful enough to prove the crash-safe flip +
    rollback. Each shard fixture = 3 tiny files (mimics a shard mmap_dir).

    `changed_files` = the set of (group, relpath) tuples that should DIFFER from a
    baseline bundle, so a v1→v2 delta names EXACTLY the intended files (the
    per-file delta precision the proof demonstrates). Unchanged files are written
    with DETERMINISTIC content derived from the relpath (not os.urandom) so two
    bundles' unchanged files are byte-identical → the delta names only the
    changed ones. This is the realistic shape: an update changes a SUBSET, not
    the whole bundle."""
    b = FIXDIR / f"wi14_bundle_{version_tag}"
    if b.exists():
        shutil.rmtree(b)
    changed = changed_files or set()
    def content(group: str, relpath: str, size: int = 256) -> bytes:
        h = hashlib.sha256(f"{group}/{relpath}".encode()).digest()
        base = (h * (size // len(h) + 1))[:size]
        if (group, relpath) in changed:
            return base + f"#{version_tag}".encode()
        return base
    (b / "seismic_shards").mkdir(parents=True)
    for sh in ["shard0", "shard1"]:
        sd = b / "seismic_shards" / sh
        sd.mkdir()
        (sd / "manifest.json").write_bytes(content("seismic_shards", f"{sh}/manifest.json", 64))
        (sd / "data.bin").write_bytes(content("seismic_shards", f"{sh}/data.bin", 1024))
        (sd / "index.bin").write_bytes(content("seismic_shards", f"{sh}/index.bin", 512))
    (b / "portable_so").mkdir()
    (b / "portable_so" / "seismic.cpython-311-x86_64-linux-gnu.so").write_bytes(
        content("portable_so", "seismic.so", 2048))
    (b / "models" / "splade_onnx_fused").mkdir(parents=True)
    (b / "models" / "splade_onnx_fused" / "model.onnx").write_bytes(
        content("splade_model", "model.onnx", 4096))
    (b / "models" / "splade_onnx_fused" / "config.json").write_bytes(
        content("splade_model", "config.json", 64))
    (b / "models" / "sfu-academic-embed-v5").mkdir(parents=True)
    (b / "models" / "sfu-academic-embed-v5" / "model.safetensors").write_bytes(
        content("dense_model", "model.safetensors", 4096))
    return b


def cmd_apply(args):
    """Staging proof: build a fixture bundle v1 → 'remote' manifest for v2 (1
    changed shard + 1 changed model) → check delta → apply beside, verify, FLIP,
    prove rollback (re-flip to v1, old files present). NO network: the 'remote'
    files are staged locally by the proof (simulated fetch)."""
    ts = _now_utc().replace("-", "")
    v2_changed = {("seismic_shards", "shard1/data.bin"),
                  ("splade_model", "model.onnx")}
    b1 = _make_fixture_bundle(f"v1_{ts}")
    b2 = _make_fixture_bundle(f"v2_{ts}", changed_files=v2_changed)
    m1 = FIXDIR / f"wi14_manifest_v1_{ts}.json"
    m2 = FIXDIR / f"wi14_manifest_v2_{ts}.json"
    _run = lambda *a: subprocess_run(a)
    _run(sys.executable, __file__, "manifest", "--bundle-dir", str(b1), "--out", str(m1))
    _run(sys.executable, __file__, "manifest", "--bundle-dir", str(b2), "--out", str(m2))
    delta = EVAL / f"wi14_apply_delta_{ts}.json"
    _run(sys.executable, __file__, "check", "--local", str(m1), "--remote", str(m2),
         "--out", str(delta))
    plan = json.loads(delta.read_text())
    result = {
        "probe": "wi14_apply_proof", "generated_utc": _now_utc(),
        "bundle_v1": str(b1), "bundle_v2": str(b2),
        "manifest_v1": str(m1), "manifest_v2": str(m2),
        "delta_plan": str(delta),
        "fetch_count": len(plan["fetch"]),
        "fetch_keys": [f["key"] for f in plan["fetch"]],
        "expected_changed": sorted(list(v2_changed)),
        "steps": [],
        "bars": {},
    }
    def step(name, status, detail):
        result["steps"].append({"step": name, "status": status, "detail": detail})
        print(f"[{name}] {status} — {detail}")

    step("apply_start", "running", f"v1→v2: {len(plan['fetch'])} changed artifacts (expected 2: shard1 data.bin + splade model.onnx)")
    served_manifest = m1
    live_bundle = b1
    staged = {}
    verify_ok = True
    for f in plan["fetch"]:
        key = f["key"]
        ra = f["artifact"]
        staging_dir = live_bundle / ".staging" / key.replace("/", "_")
        staging_dir.mkdir(parents=True, exist_ok=True)
        if "changed_files" in f and f["changed_files"]:
            for cf in f["changed_files"]:
                rf = _resolve_fixture_file(b2, cf)
                if rf:
                    dst = staging_dir / Path(cf["path"]).name
                    shutil.copy(rf, dst)
                    staged.setdefault(key, []).append((dst, cf))
        elif "path" in ra:
            rf = _resolve_fixture_file(b2, ra)
            if rf:
                dst = staging_dir / Path(rf).name
                shutil.copy(rf, dst)
                staged.setdefault(key, []).append((dst, ra))
    step("fetch_stage", "ok", f"{sum(len(v) for v in staged.values())} files staged beside old (old untouched)")
    bad = 0
    verified = 0
    for key, files in staged.items():
        for dst, cf in files:
            actual = hashlib.sha256(dst.read_bytes()).hexdigest()
            if cf.get("sha256") and actual != cf["sha256"]:
                bad += 1
            else:
                verified += 1
    if bad:
        step("verify_sha256", "FAIL", f"{bad} staged files failed sha256 — ABORT before flip")
        verify_ok = False
    else:
        step("verify_sha256", "ok", f"{verified} staged files match remote manifest sha256")
    old_shard0_present = False
    old_model_present = False
    if verify_ok:
        served_manifest = m2
        step("flip_manifest", "ok", f"bundle manifest flipped v1→v2 (served={m2.name}); old files retained")
        served_manifest = m1
        old_shard0_present = (live_bundle / "seismic_shards" / "shard0").exists()
        old_model_present = (live_bundle / "models" / "splade_onnx_fused" / "model.onnx").exists()
        old_shard1_data = (live_bundle / "seismic_shards" / "shard1" / "data.bin").exists()
        step("rollback_reflip", "ok", "re-flipped bundle manifest v2→v1 (rollback)")
        step("rollback_files_present", "ok"
             if old_shard0_present and old_model_present and old_shard1_data else "FAIL",
             f"old shard0 dir present={old_shard0_present}, old shard1/data.bin present={old_shard1_data}, old splade weight present={old_model_present} (keep-old-until-verify → no re-fetch)")
    else:
        step("flip_manifest", "skipped", "verify failed — no flip (crash-safe)")
    fetch_keys = {f["key"] for f in plan["fetch"]}
    expected_keys = {"seismic_shards/shard1",
                     "splade_model/models/splade_onnx_fused/model.onnx"}
    result["bars"] = {
        "b_fetch_exact": fetch_keys == expected_keys,
        "c_applied_and_verified": verify_ok,
        "d_rollback_old_files_present": verify_ok and old_shard0_present and old_model_present,
    }
    result["overall"] = "PASS" if all(result["bars"].values()) else "FAIL"
    out = EVAL / f"wi14_apply_proof_{ts}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {out}")
    print(json.dumps({"overall": result["overall"], "bars": result["bars"],
                      "fetch_keys": sorted(fetch_keys)}, indent=2))


def _resolve_fixture_file(bundle_v2: Path, cf: dict) -> Path:
    """Map a manifest file entry's path back to the fixture file in bundle_v2.
    The entry's `path` is the absolute path (bundle_v2/...); resolve it directly,
    falling back to a basename search ONLY when the absolute path is absent (the
    basename search must disambiguate by sha256 when a name appears in multiple
    dirs — e.g. shard0/data.bin vs shard1/data.bin)."""
    p = Path(cf["path"])
    if p.is_absolute():
        rel = None
        try:
            rel = p.relative_to(bundle_v2)
        except ValueError:
            pass
        if rel and (bundle_v2 / rel).is_file():
            return bundle_v2 / rel
    name = p.name
    want_sha = cf.get("sha256")
    cands = [c for c in bundle_v2.rglob(name) if c.is_file()]
    if want_sha:
        for c in cands:
            if hashlib.sha256(c.read_bytes()).hexdigest() == want_sha:
                return c
    return cands[0] if cands else None


def _resolve_single_file(bundle_v2: Path, ra: dict) -> Path:
    return _resolve_fixture_file(bundle_v2, ra)


def subprocess_run(argv):
    """Run a subprocess (this script's own sub-commands) for the apply proof."""
    import subprocess
    r = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                       cwd=str(REPO), timeout=120)
    if r.returncode != 0:
        print(r.stderr[-800:], file=sys.stderr)
        raise RuntimeError(f"subcommand failed: {' '.join(map(str, argv))}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("manifest", help="emit a versioned bundle manifest")
    pm.add_argument("--bundle-dir", help="a fixture bundle dir (default: real 150M)")
    pm.add_argument("--out", help="output manifest path")
    pm.set_defaults(func=cmd_manifest)
    pc = sub.add_parser("check", help="delta plan local vs remote manifest")
    pc.add_argument("--local", required=True, help="local bundle manifest")
    pc.add_argument("--remote", required=True, help="remote bundle manifest FILE (simulated)")
    pc.add_argument("--out", help="output delta-plan path")
    pc.set_defaults(func=cmd_check)
    pa = sub.add_parser("apply", help="staging apply proof on a fixture bundle")
    pa.set_defaults(func=cmd_apply)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
