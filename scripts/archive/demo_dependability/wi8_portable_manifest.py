#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-8 (deployprep wave 2, 2026-07-17) — portable-stack dependency MANIFEST.

STAGING / authoring only (no deploy, no spend). Produces the authoritative
manifest of a Qdrant-free, docker-free portable bundle: what python packages
actually load on the staging serve path (with versions), the artifact inventory
each leg needs (with per-file sizes), a staging probe the serve runs with the
seismic backend + v3 portable .so + no Qdrant reachable, and the delta list of
what's still missing for a real installer.

This is the MACHINE-READABLE half; the human-readable write-up is
`docs/infrastructure/PORTABLE_STACK_MANIFEST.md`. Output:
`data/eval_results/portable_stack_manifest.json`.

Method (F6-honesty): (a) imports are audited by ACTUALLY LOADING the serve path
in a subprocess with venv sys.path + recording `sys.modules` after a real
`search_rrf` warmup query (what loads, not what's grepped — conditional imports
that don't fire on the seismic path are NOT manifest deps); (b) sizes are
measured off the real files on this container (the 150M figures as-is); (c) the
subset-tier projection is a FORMULA recorded as such (WI-5 measured the year-axis
cut is 9p-blocked for full-corpus — the projection is marked *est.*, not a
measured full-corpus number).
"""
import importlib
import json
import os
import sys
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / "data" / "eval_results"
VENV_PY = REPO / ".venv" / "bin" / "python3"

FIRST_PARTY_PREFIX = ("lib.", "scripts.")


def _probe_imports() -> dict:
    """Run the serve path in a subprocess that loads the staging serve, fires one
    warmup-ish query, then dumps sys.modules. Returns {loaded: [...], versions:
    {...}, note}. A package only counts if it actually imported on the seismic
    serve path (conditional Qdrant/transformers imports that didn't fire are
    excluded — the manifest is what a Qdrant-free bundle needs)."""
    probe = r'''
import os, sys, json, importlib.metadata as md
sys.path.insert(0, "source")
os.environ.setdefault("SFU_DEMO_STAGING_PORT", "0")  # not binding a port
# Configure the Qdrant-free seismic serve path the bundle targets:
os.environ["SFU_SPLADE_BACKEND"] = "seismic"          # NOT qdrant
os.environ["SFU_SEISMIC_FEDERATION"] = "parallel"
os.environ.setdefault("SFU_SKIP_BMP", "1")
# Load the retriever (tantivy+dense sections come up; seismic lazy on search).
from lib.thinclient.retriever import ThinClientRetriever
r = ThinClientRetriever(index_root="")
loaded = sorted(m for m in sys.modules if "." not in m and sys.modules[m] is not None)
# fire the seismic backend lazy-load (the .so + onnxruntime) by one real search
try:
    r.search_rrf("machine learning fairness", top_k=5, include_dense=False)
except Exception as e:
    sys.stderr.write("probe-search-warn: %s\n" % e)
loaded = sorted(m for m in sys.modules if "." not in m and sys.modules[m] is not None)
# Versions via importlib.metadata (the dist name, not __version__ attr — many
# packages don't expose __version__ at module level; e.g. onnxruntime's dist
# name is "onnxruntime"). Map loaded-module → dist version where resolvable.
versions = {}
for name in loaded:
    try:
        v = md.version(name)
        versions[name] = str(v)
    except md.PackageNotFoundError:
        pass  # stdlib / non-pip module — no dist version
out = {"loaded": loaded, "versions": versions,
       "py_version": "%d.%d.%d" % sys.version_info[:3]}
print("__PROBE_JSON__" + json.dumps(out))
'''
    env = dict(os.environ)
    env["SFU_SPLADE_BACKEND"] = "seismic"
    env["SFU_SEISMIC_FEDERATION"] = "parallel"
    env["SFU_SKIP_BMP"] = "1"
    try:
        r = subprocess.run(
            [str(VENV_PY), "-c", probe],
            cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"error": "probe timed out (cold seismic load >300s)", "loaded": [], "versions": {}}
    out = {"stdout_tail": r.stdout[-400:], "stderr_tail": r.stderr[-400:],
           "returncode": r.returncode}
    marker = r.stdout.find("__PROBE_JSON__")
    if marker >= 0:
        try:
            out.update(json.loads(r.stdout[marker + len("__PROBE_JSON__"):]))
        except Exception as e:
            out["parse_error"] = str(e)
    else:
        out["error"] = "no probe JSON marker (serve path failed to load?)"
        out["loaded"] = []
        out["versions"] = {}
    return out


def _artifact_inventory() -> dict:
    """Per-leg artifact inventory with measured file sizes. 150M figures = the
    real served index as-is. The subset-tier projection is a formula marked est."""
    def gb(p):
        p = Path(p)
        if not p.exists():
            return None
        if p.is_file():
            return round(p.stat().st_size / 1e9, 3)
        t = 0
        for root, _, files in os.walk(p):
            for f in files:
                fp = os.path.join(root, f)
                try: t += os.path.getsize(fp)
                except OSError: pass
        return round(t / 1e9, 3) if t else 0.0

    manifest = json.load(open(EVAL / "seismic_c25_shards_150m_mmap_e5_v2.json"))
    shards = manifest["shards"]
    seismic_mmap_total = sum(s.get("mmap_dir_size_gb", 0) or 0 for s in shards)
    on_disk_total = sum(s.get("on_disk_gb", 0) or 0 for s in shards)
    inv = {
        "seismic_shards": {
            "n": len(shards),
            "mmap_dir_total_gb": round(seismic_mmap_total, 3),
            "on_disk_total_gb": round(on_disk_total, 3),
            "per_shard_mmap_gb": [round(s.get("mmap_dir_size_gb", 0) or 0, 3) for s in shards],
            "note": "the SPLADE/SEISMIC leg — 8 dotvbyte e5_v2 mmap shards",
        },
        "tantivy_bm25f": {
            "path": "data/thinclient_index/",
            "size_gb": gb(REPO / "data" / "thinclient_index"),
            "note": "the BM25F leg (8 sections) + meta.sqlite + packed abstracts",
        },
        "dense_usearch": {
            "path": "data/thinclient_index/dense/",
            "size_gb": gb(REPO / "data" / "thinclient_index" / "dense"),
            "note": "the dense leg (usearch int8 rescore, partial-coverage subset)",
        },
        "splade_model": {
            "path": "models/splade_onnx_fused/",
            "size_gb": gb(REPO / "models" / "splade_onnx_fused"),
            "note": "the SPLADE query encoder (ORt fp32 fused, the serve default)",
        },
        "dense_model": {
            "path": "models/sfu-academic-embed-v5/",
            "size_gb": gb(REPO / "models" / "sfu-academic-embed-v5"),
            "note": "the dense query encoder (sentence-transformers export)",
        },
        "portable_so_v3": {
            "path": "spike/seismic_upstream/target/portable_so/v3/seismic/",
            "size_mb": round(Path(REPO / "spike/seismic_upstream/target/portable_so/v3/seismic/seismic.cpython-311-x86_64-linux-gnu.so").stat().st_size / 1e6, 2) if (REPO / "spike/seismic_upstream/target/portable_so/v3/seismic/seismic.cpython-311-x86_64-linux-gnu.so").exists() else None,
            "note": "WI-4's x86-64-v3 portable .so (parity 1.0, warm 0.96x) — ships NOT the native .so",
        },
        "subset_tier_projection_est": {
            "target_gb": "~10-15",
            "formula": "subset_docs/150413098 * seismic_on_disk_total_gb (linear in docs; the "
                       "year-axis cut measured 9p-blocked for full in WI-5, so this is *est.* — "
                       "the LOCALIZED_DEPLOYMENT_PLAN §3 figure '2022+ = 83M docs' came from the "
                       "live source index, not corroborated in-container)",
            "note": "*est. — design only, not a measured full-corpus cut (WI-5 doc 16)",
        },
    }
    inv["portable_bundle_total_150m_gb_est"] = round(
        (seismic_mmap_total + (inv["tantivy_bm25f"]["size_gb"] or 0)
         + (inv["dense_usearch"]["size_gb"] or 0) + (inv["splade_model"]["size_gb"] or 0)
         + (inv["dense_model"]["size_gb"] or 0)), 3)
    return inv


def _staging_probe() -> dict:
    """Prove the serve runs Qdrant-free: SFU_SPLADE_BACKEND=seismic + the v3 .so
    loadable by explicit path + no qdrant_client import. Env-selected, no
    served-default flip. Reports what actually happened (the F6 honest verdict)."""
    probe = r'''
import os, sys, json, importlib, importlib.util
sys.path.insert(0, "source")
# Qdrant-free path:
os.environ["SFU_SPLADE_BACKEND"] = "seismic"
os.environ["SFU_SEISMIC_FEDERATION"] = "parallel"
os.environ.setdefault("SFU_SKIP_BMP", "1")
out = {}
# 1) Is qdrant_client INSTALLED (importable)? use importlib.util.find_spec (does
#    NOT import it — importing it would pollute sys.modules and self-fulfill the
#    "on the path" check below; the earlier probe had this bug).
qs = importlib.util.find_spec("qdrant_client")
out["qdrant_client_installed"] = qs is not None
# the real check: does the SEISMIC serve path import it? Load retriever + drive a
# search WITHOUT ever importing qdrant_client ourselves, then inspect sys.modules.
from lib.thinclient.retriever import ThinClientRetriever
r = ThinClientRetriever(index_root="")
try:
    r.search_rrf("test query encoders", top_k=5, include_dense=False)
except Exception as e:
    out["probe_search_error"] = str(e)[:200]
out["qdrant_client_imported_on_seismic_path"] = "qdrant_client" in sys.modules
out["seismic_backend_served"] = (r._splade_backend == "seismic")
# 2) v3 .so loadable by explicit path?
v3 = "spike/seismic_upstream/target/portable_so/v3"
so = None
for root, _, files in os.walk(v3):
    for f in files:
        if f.endswith(".so") and "seismic" in f:
            so = os.path.join(root, f); break
    if so: break
out["v3_so_path"] = so
loaded_v3 = False
v3_exports = []
if so:
    try:
        # The pyo3 module's init is PyInit_seismic, so the spec NAME must be
        # "seismic" (a different name → "does not define module export function").
        spec = importlib.util.spec_from_file_location("seismic", so)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        v3_exports = [a for a in dir(m) if not a.startswith("_")]
        # the served class is MmapSeismicIndex (Path C mmap); SeismicIndex* are the variants
        loaded_v3 = hasattr(m, "MmapSeismicIndex")
    except Exception as e:
        out["v3_load_error"] = str(e)[:200]
out["v3_so_loadable"] = loaded_v3
out["v3_exports"] = v3_exports
print("__PROBE_JSON__" + json.dumps(out))
'''
    env = dict(os.environ)
    env["SFU_SPLADE_BACKEND"] = "seismic"
    env["SFU_SEISMIC_FEDERATION"] = "parallel"
    env["SFU_SKIP_BMP"] = "1"
    try:
        r = subprocess.run([str(VENV_PY), "-c", probe], cwd=str(REPO),
                           env=env, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"error": "staging probe timed out"}
    out = {"returncode": r.returncode, "stderr_tail": r.stderr[-300:]}
    marker = r.stdout.find("__PROBE_JSON__")
    if marker >= 0:
        out.update(json.loads(r.stdout[marker + len("__PROBE_JSON__"):]))
    else:
        out["error"] = "no probe JSON (serve path failed)"
    return out


def main():
    print("WI-8 portable-stack manifest — auditing imports + artifacts...")
    imports = _probe_imports()
    print("  imports: %d loaded, %d versioned" % (
        len(imports.get("loaded", [])), len(imports.get("versions", {}))))
    artifacts = _artifact_inventory()
    print("  artifacts inventoried; portable bundle total (150M, as-is): %s GB" %
          artifacts.get("portable_bundle_total_150m_gb_est"))
    probe = _staging_probe()
    print("  staging probe rc=%s qdrant_in_path=%s v3_loadable=%s" % (
        probe.get("returncode"), probe.get("qdrant_client_imported_on_seismic_path"),
        probe.get("v3_so_loadable")))
    manifest = {
        "probe": "wi8_portable_stack_manifest",
        "date_utc": "2026-07-17",
        "imports_audit": imports,
        "artifact_inventory": artifacts,
        "qdrant_free_staging_probe": probe,
        "delta_for_real_installer": [
            {"item": "Windows/mmap portability", "status": "OPEN",
             "owner": "PORTABLE_STACK_MANIFEST.md §delta",
             "note": "the seismic .so is Linux x86-64-v3; a Windows handout needs a "
                     "native build or a WSL2 boundle. The mmap load path is POSIX."},
            {"item": "spool re-export for a subset bundle", "status": "OPEN",
             "owner": "16_SUBSET_CORPUS_PILOT.md (WI-5)",
             "note": "the subset-tier bundle needs the pre-encoded sparse spool "
                     "re-exported with cited_by_count (WI-5's blocker); a full-150M "
                     "bundle ships the as-is shards and skips this."},
            {"item": "licensing check", "status": "OPEN",
             "owner": "PORTABLE_STACK_MANIFEST.md §delta",
             "note": "the models (SPLADE ONNX, dense v5) + the corpus license "
                     "must be cleared for redistribution before any real handout."},
            {"item": "python runtime bundling", "status": "OPEN",
             "owner": "PORTABLE_STACK_MANIFEST.md §delta",
             "note": "the manifest lists packages; an installer still needs a "
                     "frozen python (+ the v3 .so placed on the import path)."},
        ],
        "caveat": "150M figures measured as-is on this container; subset-tier is "
                  "*est.* (WI-5 measured the full-corp year cut 9p-blocked). No "
                  "served-default flip — the bundle path is env-selected, the "
                  "served default is unchanged. No docker, no Qdrant on the path.",
    }
    out = EVAL / "portable_stack_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, default=str))
    print("\nmanifest -> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
