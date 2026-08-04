#!/usr/bin/env python3
"""Phase 2 — assemble the OS-neutral data layer of the bundle.

Idempotent. Produces:

    $BUNDLE/
      thinclient_index/
        meta.sqlite                 (from phase 1; relocated if at bundle root)
        manifest.json               (trimmed: the two kept sections, both hot)
        sections/
          social_sciences__recent/  (copied: tantivy + abstracts.sqlite)
          social_sciences__archive/ (unpacked from packed/*.tar.zst)
      models/splade_onnx_fused/      (copied; the query encoder)

The dense leg is intentionally omitted (design decision D1). The seismic subset
shards land under $BUNDLE/seismic/ in phase 3.

    .venv/bin/python3 scripts/portable_socsci/02_assemble_data.py
"""
import os, io, json, time, shutil, sqlite3
import zstandard as zstd
import tarfile

BUNDLE = os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle")
SRC_INDEX = os.environ.get("SRC_INDEX", "data/thinclient_index")
SRC_MODELS = os.environ.get("SRC_MODELS", "models")

BINDEX = os.path.join(BUNDLE, "thinclient_index")
BSECTIONS = os.path.join(BINDEX, "sections")
RECENT = "social_sciences__recent"
ARCHIVE = "social_sciences__archive"
ENCODER = "splade_onnx_fused"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def relocate_meta():
    """Phase-1 may have written meta.sqlite at the bundle root; move it in."""
    stray = os.path.join(BUNDLE, "meta.sqlite")
    dst = os.path.join(BINDEX, "meta.sqlite")
    os.makedirs(BINDEX, exist_ok=True)
    if os.path.exists(dst):
        log(f"meta.sqlite already in place ({os.path.getsize(dst)/2**30:.2f} GiB)")
    elif os.path.exists(stray):
        log("relocating meta.sqlite -> thinclient_index/")
        shutil.move(stray, dst)
    else:
        raise SystemExit("meta.sqlite not found — run 01_filter_meta.py first")


def copy_recent():
    src = os.path.join(SRC_INDEX, "sections", RECENT)
    dst = os.path.join(BSECTIONS, RECENT)
    if os.path.isdir(dst) and os.path.isfile(os.path.join(dst, "abstracts.sqlite")):
        log(f"{RECENT} already assembled ({_du(dst)/2**30:.1f} GiB)")
        return
    os.makedirs(BSECTIONS, exist_ok=True)
    log(f"copying {RECENT} (tantivy + abstracts.sqlite, ~19 GiB from 9p)...")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    log(f"  done ({_du(dst)/2**30:.1f} GiB)")


def unpack_archive():
    dst = os.path.join(BSECTIONS, ARCHIVE)
    if os.path.isdir(dst) and os.path.isfile(os.path.join(dst, "abstracts.sqlite")):
        log(f"{ARCHIVE} already unpacked ({_du(dst)/2**30:.1f} GiB)")
        return
    archive = os.path.join(SRC_INDEX, "packed", f"{ARCHIVE}.tar.zst")
    if not os.path.isfile(archive):
        raise SystemExit(f"no packed archive at {archive}")
    os.makedirs(BSECTIONS, exist_ok=True)
    log(f"unpacking {ARCHIVE} from {os.path.basename(archive)}...")
    dctx = zstd.ZstdDecompressor()
    with open(archive, "rb") as f, dctx.stream_reader(f) as zr:
        with tarfile.open(fileobj=io.BufferedReader(zr, buffer_size=8 << 20),
                          mode="r|") as tar:
            try:
                tar.extractall(BSECTIONS, filter="data")
            except TypeError:  # py < 3.11.4
                tar.extractall(BSECTIONS)
    log(f"  done ({_du(dst)/2**30:.1f} GiB)")


def copy_encoder():
    src = os.path.join(SRC_MODELS, ENCODER)
    dst = os.path.join(BUNDLE, "models", ENCODER)
    if os.path.isdir(dst):
        log(f"{ENCODER} already present ({_du(dst)/2**30:.2f} GiB)")
        return
    os.makedirs(os.path.join(BUNDLE, "models"), exist_ok=True)
    log(f"copying SPLADE encoder {ENCODER}...")
    shutil.copytree(src, dst)
    log(f"  done ({_du(dst)/2**30:.2f} GiB)")


def write_manifest():
    """Trimmed manifest: the two kept sections, both live + hot, dense stripped."""
    src = json.load(open(os.path.join(SRC_INDEX, "manifest.json")))
    kept = {}
    for name in (RECENT, ARCHIVE):
        e = dict(src.get("sections", {}).get(name, {}))
        e["state"] = "live"
        e["hot"] = True          # both eras ship offline in this bundle
        e.pop("archive", None)   # packed copy is not shipped
        kept[name] = e
    n_docs = sum(kept[n].get("docs", 0) for n in kept)
    manifest = {
        "sections": kept,
        "built": src.get("built"),
        "source": src.get("source"),
        "docs_exported": n_docs,
        "persona": "political_science",
        "hot_sections": [RECENT, ARCHIVE],
        "splade_quant_scale": src.get("splade_quant_scale", 70),
        "engines": {
            "lexical": "tantivy 0.26 (BM25F title^3/abstract, freq-only)",
            "sparse": "SEISMIC dotvbyte e5.v2 mmap, subset to social_sciences",
            "dense": "STRIPPED (portable social-sci bundle, D1)",
        },
        "bundle": {
            "kind": "portable_socsci_windows",
            "derived_from": "data/thinclient_index (150M)",
            "kept_sections": [RECENT, ARCHIVE],
            "assembled": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }
    with open(os.path.join(BINDEX, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"wrote trimmed manifest.json ({n_docs} docs, 2 sections, dense stripped)")
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
    t0 = time.time()
    relocate_meta()
    copy_recent()
    unpack_archive()
    copy_encoder()
    manifest = write_manifest()
    report = {
        "bundle": BUNDLE,
        "meta_gib": round(os.path.getsize(os.path.join(BINDEX, "meta.sqlite")) / 2**30, 2),
        "sections": {n: round(_du(os.path.join(BSECTIONS, n)) / 2**30, 2)
                     for n in (RECENT, ARCHIVE)},
        "encoder_gib": round(_du(os.path.join(BUNDLE, "models", ENCODER)) / 2**30, 2),
        "docs": manifest["docs_exported"],
        "total_seconds": round(time.time() - t0, 1),
    }
    report["data_layer_gib_no_seismic"] = round(
        report["meta_gib"] + sum(report["sections"].values()) + report["encoder_gib"], 2)
    print(json.dumps(report, indent=2), flush=True)
    with open(os.path.join(BUNDLE, "_assemble_report.json"), "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
