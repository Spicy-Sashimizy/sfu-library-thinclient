#!/usr/bin/env python3
"""WI-13 (deployprep wave 4, 2026-07-17) — the demo host's VERSION CONTRACT.

STAGING / authoring only (no deploy, no spend, no served-default flip). Produces
`data/eval_results/deploy_versions.json`: the 4-tuple that is the demo's update
unit, each component captured with **sha256 + byte size + an absolute date** so
`update_demo.sh` can VERIFY a staged new version before it flips and re-verify
after — and so a rollback knows exactly which prior 4-tuple to restore.

The four components (the things a pending upgrade / research finding changes):
  1. code_rev      — the git commit the serve runs (SFU_* env is versioned too).
  2. seismic_so    — the seismic .so variant on the import path (portable v3
                     SHIPS per WI-4; the native .so is the dev-container build).
                     A .so rebuild (RUSTFLAGS target-cpu bump) is the cheapest
                     update class (~2.7 MB).
  3. index_manifest — the served shard-set manifest (`SFU_SEISMIC_SHARD_MANIFEST`
                     unset → the retriever's promotion default = e5_v2; the
                     ladder below it: e5_v1 → plain dv). A manifest FLIP is the
                     one-env rollback mechanism E5/E8 rollouts already use. The
                     manifest's shard `mmap_dir`s (immutable) are checksummed
                     as a group so a re-conversion (E8 dv-v2 = all shards
                     change ~26 GB) shows as a delta.
  4. models        — the SPLADE ONNX + dense v5 query encoders (encoder distill
                     = models only ~1 GB; the only files a *model* upgrade
                     touches on the serve path).

Method (F6-honesty): every sha256 is computed off the REAL file on this
container (no est.). The code_rev is `git rev-parse HEAD` (+ branch + dirty
flag). The manifest component records the manifest's OWN sha256 + each shard
mmap_dir's manifest.json sha256 (the per-shard file that a re-conversion
rewrites) — NOT a checksum of the 66 GB of shard data (that's the on-disk
artifact; the manifest.json is the versioned pointer that flips). The .so
variant is whichever is importable on the serve path (probed by attempting the
import, not assumed — so a rebuild is detected). A `generated_utc` stamps the
whole record so two deploy_versions.json can be diffed = the upgrade delta.

This is the MACHINE-READABLE half of the update contract; the human-readable
flow + PROOF is `update_demo.sh` (the staging flow) + `DEMO_DEPENDABILITY.md`
§WI-13 (the measured timelines). Output written to
`data/eval_results/deploy_versions.json` (overwritten each run; a snapshot is
copied alongside the WI-13 proof cells).

NO served-default flip: this reads state, it never changes what the serve loads.
`data/seismic_150m/` READ-ONLY: shard mmap_dirs are opened O_RDONLY for the
manifest.json checksum only (the versioned pointer), never the shard data.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data" / "eval_results"
OUT = EVAL / "deploy_versions.json"

SERVED_MANIFEST_LADDER = [
    "seismic_c25_shards_150m_mmap_e5_v2.json",
    "seismic_c25_shards_150m_mmap_e5.json",
    "seismic_c25_shards_150m_mmap_dotvbyte.json",
]
SO_VARIANTS = {
    "portable_v3": REPO / "spike" / "seismic_upstream" / "target" / \
                    "portable_so" / "v3" / "seismic" /
                    "seismic.cpython-311-x86_64-linux-gnu.so",
    "portable_v3_flat": REPO / "spike" / "seismic_upstream" / "target" /
                        "portable_so" / "seismic_x86_64_v3.so",
    "native_dev": REPO / "spike" / "seismic_upstream" / "target" /
                  "release" / "libseismic.so",
}
MODEL_DIRS = {
    "splade_onnx_fused": REPO / "models" / "splade_onnx_fused",
    "dense_v5": REPO / "models" / "sfu-academic-embed-v5",
}
MODEL_WEIGHT_FILES = {
    "splade_onnx_fused": "model.onnx",
    "dense_v5": "model.safetensors",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _sha256(path: Path) -> dict:
    """sha256 + byte size for one file. Returns {sha256, bytes, path} or an
    {error} if the file is absent (reported, never silently skipped)."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO / p
    if not p.exists():
        return {"path": str(path), "error": "absent"}
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    st = p.stat()
    return {"path": str(path.relative_to(REPO)) if str(path).startswith(str(REPO))
            else str(path),
            "sha256": h.hexdigest(), "bytes": st.st_size}


def _code_rev() -> dict:
    """Component 1: the git commit + branch + dirty flag + the SFU_* env the
    serve reads. `git rev-parse HEAD` is the rev; `git status --porcelain` empty
    = clean. A code update = a new commit (the updater's `git pull`)."""
    def _git(*args):
        try:
            r = subprocess.run(["git", "-C", str(REPO), *args],
                               capture_output=True, text=True, timeout=15)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None
    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = _git("status", "--porcelain")
    version_envs = {}
    for k in ("SFU_SPLADE_BACKEND", "SFU_SEISMIC_SHARD_MANIFEST",
              "SFU_SEISMIC_FEDERATION", "SFU_SEISMIC_LOAD_MODE",
              "SEP.VM.x12x86_64", "RUSTFLAGS"):
        if k in os.environ:
            version_envs[k] = os.environ[k]
    head_short = head[:12] if head else None
    return {
        "component": "code_rev",
        "head": head, "head_short": head_short, "branch": branch,
        "dirty": bool(dirty), "dirty_files": len(dirty.splitlines()) if dirty else 0,
        "version_envs_set": version_envs,
        "note": "the git commit the serve runs; a code update = git pull → new "
                 "HEAD. `SFU_SEISMIC_SHARD_MANIFEST` set = an explicit override "
                 "of the promotion-default (e5_v2) ladder; unset = default.",
    }


def _seismic_so() -> dict:
    """Component 2: the seismic .so on the import path. Probes each variant's
    existence + sha256; the SERVED one is whichever a real `import seismic`
    actually loads as its extension module (recorded as `served_variant` /
    `served_file`). A .so rebuild (native rebuild) is a sha256 change on the
    served file — the cheapest update class."""
    variants = {name: _sha256(p) for name, p in SO_VARIANTS.items()}
    served = None
    served_file = None
    venv_py = REPO / ".venv" / "bin" / "python3"
    try:
        probe = (
            "import seismic, os, pathlib;"
            "d=pathlib.Path(seismic.__file__).parent;"
            "sos=[p for p in d.glob('seismic.*.so')];"
            "print(sos[0] if sos else '')"
        )
        r = subprocess.run([str(venv_py), "-c", probe],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            served_path = Path(r.stdout.strip())
            served = "venv_installed (portable v3 installed into venv per WI-4)"
            for name, p in SO_VARIANTS.items():
                if Path(p).resolve() == served_path.resolve():
                    served = name
                    break
            served_file = _sha256(served_path)
    except Exception as e:
        served_file = {"error": f"probe-failed: {type(e).__name__}"}
    return {
        "component": "seismic_so",
        "variants": variants,
        "served_variant": served,
        "served_file": served_file,
        "note": "the seismic .so on the import path. The serve loads the EXTENSION "
                ".so under the `seismic` package (the venv site-packages copy = "
                "the portable v3 installed into the venv per WI-4). A .so rebuild "
                "(RUSTFLAGS target-cpu bump / portable re-compile) = a sha256 "
                "change on the served .so (~2.7 MB — the cheapest update class). "
                "The portable v3 + native dev .so paths are also checksummed as "
                "build-tier variants a rebuild would change.",
    }


def _index_manifest() -> dict:
    """Component 3: the served shard-set manifest + its ladder + per-shard
    manifest.json checksums. The manifest FLIP is the one-env rollback the E5
    /E8 rollouts use; the ladder (e5_v2 → e5_v1 → plain dv) is every prior
    served set reachable by flipping `SFU_SEISMIC_SHARD_MANIFEST`. Each shard's
    `mmap_dir/manifest.json` is checksummed (the versioned POINTER a re-
    conversion rewrites — NOT the 66 GB shard data). A re-conversion (E8 dv-v2
    = all 8 shards change ~26 GB) shows as 8 changed manifest.json sha256s."""
    ladder = []
    served_default = None
    for name in SERVED_MANIFEST_LADDER:
        mp = EVAL / name
        entry = _sha256(mp)
        shard_manifests = []
        if "sha256" in entry:
            try:
                m = json.loads(mp.read_text())
                served_default = served_default or name
                for s in m.get("shards", []):
                    d = s.get("mmap_dir")
                    if not d:
                        continue
                    dp = Path(d)
                    if not dp.is_absolute():
                        dp = REPO / dp
                    smp = dp / "manifest.json"
                    shard_manifests.append({
                        "shard": s.get("shard"),
                        "mmap_dir": s.get("mmap_dir"),
                        "manifest_json": _sha256(smp),
                        "on_disk_gb": s.get("on_disk_gb"),
                    })
            except Exception as e:
                entry["parse_error"] = str(e)
        entry["rank"] = len(ladder)
        entry["shard_manifests"] = shard_manifests
        ladder.append(entry)
    return {
        "component": "index_manifest",
        "ladder": ladder,
        "promotion_default": served_default,
        "served_env": os.environ.get("SFU_SEISMIC_SHARD_MANIFEST",
                                     f"<unset → default {served_default}>"),
        "note": "the served shard-set manifest + its ladder. The manifest FLIP "
                "(`SFU_SEISMIC_SHARD_MANIFEST=<older>`) is the one-env rollback "
                "E5/E8 rollouts use. Per-shard manifest.json checksums = the "
                "immutable-shard versioned pointers a re-conversion rewrites "
                "(NOT 66 GB of shard data). Ladder rank 0 = newest (the unset-"
                "env promotion default); an older manifest on the ladder is a "
                "reachable rollback target with old shards still on disk.",
    }


def _models() -> dict:
    """Component 4: the query-encoder models. The WEIGHT files (model.onnx /
    model.safetensors) are the versioned checksums — an encoder distill /
    retrain changes ONLY these on the serve path (~1 GB), nothing else."""
    out = {}
    for name, d in MODEL_DIRS.items():
        weight = MODEL_WEIGHT_FILES[name]
        out[name] = {
            "dir": str(d.relative_to(REPO)),
            "weight_file": _sha256(d / weight),
            "dir_size_bytes": sum(
                f.stat().st_size for f in d.rglob("*") if f.is_file()),
        }
    return {
        "component": "models",
        "models": out,
        "note": "the SPLADE ONNX + dense v5 query encoders. An encoder distill "
                "/ retrain = sha256 changes on the WEIGHT files ONLY (~1 GB, "
                "nothing else on the serve path touches these).",
    }


def main():
    EVAL.mkdir(parents=True, exist_ok=True)
    record = {
        "probe": "wi13_deploy_versions",
        "generated_utc": _now_utc(),
        "repo_root": str(REPO),
        "components": {
            "code_rev": _code_rev(),
            "seismic_so": _seismic_so(),
            "index_manifest": _index_manifest(),
            "models": _models(),
        },
        "update_class_delta_expectation": {
            "so_rebuild": {"changes": "1 .so variant", "bytes_est": 2_700_288,
                           "note": "the cheapest class — one file"},
            "encoder_distill": {"changes": "models only", "bytes_est": 1_073_741_824,
                                "note": "~1 GB models; nothing else"},
            "e8_dvv2_reconversion": {"changes": "all 8 shards",
                                    "bytes_est": 26_000_000_000,
                                    "note": "~26 GB — every shard's mmap_dir rewrites"},
            "manifest_flip_only": {"changes": "the manifest pointer",
                                   "bytes_est": 7_509,
                                   "note": "zero data movement — flip env; old shards already on disk"},
        },
    }
    OUT.write_text(json.dumps(record, indent=2))
    print(f"wrote {OUT.relative_to(REPO)}")
    print(json.dumps({
        "generated_utc": record["generated_utc"],
        "code_head": record["components"]["code_rev"]["head_short"],
        "code_dirty": record["components"]["code_rev"]["dirty"],
        "served_so_variant": record["components"]["seismic_so"]["served_variant"],
        "promotion_default_manifest": record["components"]["index_manifest"]["promotion_default"],
        "model_weights": {
            n: v["weight_file"]["sha256"][:12]
            for n, v in record["components"]["models"]["models"].items()
            if "sha256" in v["weight_file"]
        },
    }, indent=2))


if __name__ == "__main__":
    main()
