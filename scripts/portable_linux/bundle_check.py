#!/usr/bin/env python3
"""Self-check shipped inside the portable Linux bundle (``bin/bundle_check.py``).

Run with the bundle's own interpreter, ``bin/sfu-python bin/bundle_check.py``:

``imports`` (no index, no model, no lock needed)
    Proves the bundle is self-contained: ``lib.thinclient.retriever`` and the
    ``seismic`` extension both resolve from INSIDE the bundle, the extension
    exports ``MmapSeismicIndex``, ``torch.cuda.is_available()`` is False and
    onnxruntime offers CPU providers only. Reports any ``sys.path`` entry or
    loaded module that lives outside the bundle (isolation leak).

``smoke --index-root DIR --manifest JSON --splade-model DIR [--anchor DIR] [--splade-tokenizer DIR]``
    Fires ONE ``ThinClientRetriever.search_rrf`` against a real served index
    and reports hit count, wall-clock, which ``seismic`` file served, and any
    WARNING/ERROR log records (a silent fallback from the SPLADE leg to BM25F
    only shows up there). Shard manifests record repo-root-relative
    ``mmap_dir`` paths; ``--anchor`` rewrites them to absolute paths in a temp
    copy so the bundle can live anywhere. Loads the index: callers on a shared
    host hold the latency-measurement lock around this subcommand.

Both print one JSON object on stdout and exit non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]


def _inside(path: str | None) -> bool:
    """True when a path lies under the bundle root."""
    if not path:
        return True
    try:
        Path(path).resolve().relative_to(BUNDLE)
        return True
    except ValueError:
        return False


def _in_tmp(path: str) -> bool:
    """True for runtime-generated temp paths (torch writes a jit stub module
    into a fresh ``tempfile.mkdtemp()`` and appends it to ``sys.path``)."""
    try:
        Path(path).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False


def _leaks() -> dict:
    """sys.path entries and loaded modules outside the bundle; runtime temp
    stubs are reported separately and do not count as leaks, and modules with
    a relative placeholder ``__file__`` (``torch.ops`` -> ``_ops.py``) are not
    files at all and are skipped."""
    path_out = [p for p in sys.path if p and not _inside(p)]
    mod_out = sorted({
        (name, m.__file__) for name, m in list(sys.modules.items())
        if isinstance(getattr(m, "__file__", None), str)
        and os.path.isabs(m.__file__) and not _inside(m.__file__)
    })
    return {
        "sys_path_outside_bundle": [p for p in path_out if not _in_tmp(p)],
        "modules_outside_bundle": sorted({n.split(".")[0] for n, f in mod_out
                                          if not _in_tmp(f)}),
        "runtime_temp_stubs": sorted({f for _, f in mod_out if _in_tmp(f)}
                                     | {p for p in path_out if _in_tmp(p)}),
    }


def cmd_imports(_args: argparse.Namespace) -> int:
    """Import-surface check; no data touched."""
    out: dict = {"bundle": str(BUNDLE), "python": sys.version.split()[0],
                 "executable": sys.executable}
    import lib.thinclient.retriever as retr
    out["retriever_file"] = retr.__file__
    import seismic
    out["seismic_file"] = getattr(seismic.seismic, "__file__", None)
    out["seismic_has_MmapSeismicIndex"] = hasattr(seismic, "MmapSeismicIndex")
    import torch
    out["torch_version"] = torch.__version__
    out["torch_cuda_available"] = bool(torch.cuda.is_available())
    import onnxruntime as ort
    out["onnxruntime_version"] = ort.__version__
    out["ort_providers"] = ort.get_available_providers()
    import importlib.metadata as md
    out["dists"] = {d: md.version(d) for d in (
        "tantivy", "transformers", "tokenizers", "sentence-transformers",
        "numpy", "zstandard", "usearch", "onnxruntime", "torch", "mcp",
        "starlette", "uvicorn")}
    import sentence_transformers
    import tantivy
    import transformers
    import usearch.index
    import zstandard
    out["all_inside_bundle"] = all(_inside(f) for f in (
        out["retriever_file"], out["seismic_file"], torch.__file__, ort.__file__,
        tantivy.__file__, transformers.__file__, sentence_transformers.__file__,
        usearch.index.__file__, zstandard.__file__))
    out.update(_leaks())
    cpu_only = [p for p in out["ort_providers"]
                if p not in ("CPUExecutionProvider", "AzureExecutionProvider")]
    out["ort_non_cpu_providers"] = cpu_only
    ok = (out["seismic_has_MmapSeismicIndex"] and not out["torch_cuda_available"]
          and not cpu_only and out["all_inside_bundle"]
          and not out["modules_outside_bundle"]
          and not out["sys_path_outside_bundle"])
    out["status"] = "PASS" if ok else "FAIL"
    print(json.dumps(out, indent=1))
    return 0 if ok else 1


class _Collect(logging.Handler):
    """Keep WARNING+ records so a silent leg fallback is visible."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}"[:400])


def _anchored_manifest(manifest: str, anchor: str | None) -> str:
    """Return a manifest whose shard paths are absolute (temp copy if needed)."""
    if not anchor:
        return manifest
    data = json.loads(Path(manifest).read_text())
    for rec in data.get("shards", []):
        for key in ("mmap_dir", "index_path"):
            v = rec.get(key)
            if v and not os.path.isabs(v):
                rec[key] = str(Path(anchor) / v)
    fd, tmp = tempfile.mkstemp(prefix="sfu_bundle_manifest_", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    return tmp


def _composite_splade_dir(model_dir: str, tokenizer_dir: str | None) -> tuple[str, str | None]:
    """Return a SPLADE model dir that carries its own tokenizer.

    The served ``models/splade_onnx_fused`` holds only ``model.onnx`` +
    ``config.json``; in the repo the tokenizer is borrowed from embed-model
    dirs located relative to the CODE (``lib/opensearch_retriever.py``
    ``_TOKENIZER_FALLBACK_DIRS``), which do not exist next to the bundle's
    code. With ``--splade-tokenizer`` a temp dir of symlinks joins the ONNX
    model and the tokenizer files so the handout contract is one dir."""
    if not tokenizer_dir:
        return model_dir, None
    tmp = tempfile.mkdtemp(prefix="sfu_bundle_splade_")
    for src_dir, names in ((model_dir, ("model.onnx", "config.json")),
                           (tokenizer_dir, ("tokenizer.json", "tokenizer_config.json",
                                            "special_tokens_map.json", "vocab.txt"))):
        for name in names:
            src = Path(src_dir) / name
            if src.is_file():
                os.symlink(src, Path(tmp) / name)
    return tmp, tmp


def cmd_smoke(args: argparse.Namespace) -> int:
    """One real search_rrf through the bundle's interpreter."""
    collector = _Collect()
    logging.getLogger().addHandler(collector)
    splade_dir, splade_tmp = _composite_splade_dir(args.splade_model, args.splade_tokenizer)
    manifest = _anchored_manifest(args.manifest, args.anchor)
    os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = manifest
    os.environ.setdefault("SFU_SPLADE_BACKEND", "seismic")
    os.environ.setdefault("SFU_SEISMIC_LOAD_MODE", "mmap")
    os.environ.setdefault("SFU_DENSE_LEG", "0")
    from lib.thinclient.retriever import ThinClientRetriever
    t0 = time.perf_counter()
    r = ThinClientRetriever(index_root=args.index_root,
                            splade_model_path=splade_dir,
                            remote_abstracts=False)
    t1 = time.perf_counter()
    error = None
    hits: list = []
    try:
        hits = r.search_rrf(args.query, top_k=args.top_k)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    t2 = time.perf_counter()
    seismic_mod = sys.modules.get("seismic.seismic") or sys.modules.get("seismic")
    fallback = [m for m in collector.records if "falling back" in m or "failed" in m]
    out = {
        "bundle": str(BUNDLE),
        "query": args.query,
        "splade_model_dir": args.splade_model,
        "splade_tokenizer_dir": args.splade_tokenizer,
        "top_k": args.top_k,
        "n_hits": len(hits),
        "n_with_abstract": sum(1 for h in hits if h.get("abstract")),
        "top_titles": [(h.get("title") or "")[:90] for h in hits[:3]],
        "construct_ms": round((t1 - t0) * 1000, 1),
        "first_search_rrf_wall_ms": round((t2 - t1) * 1000, 1),
        "seismic_so_served": getattr(seismic_mod, "__file__", None),
        "seismic_backend_loaded": getattr(r, "_seismic", None) is not None,
        "error": error,
        "warnings": collector.records[:20],
        "leg_fallback_warnings": fallback,
        "torch_imported": "torch" in sys.modules,
        "cuda_available": (sys.modules["torch"].cuda.is_available()
                           if "torch" in sys.modules else None),
    }
    out.update(_leaks())
    ok = (error is None and out["n_hits"] > 0 and out["seismic_backend_loaded"]
          and _inside(out["seismic_so_served"]) and not fallback)
    out["status"] = "PASS" if ok else "FAIL"
    if manifest != args.manifest:
        os.unlink(manifest)
    if splade_tmp:
        import shutil
        shutil.rmtree(splade_tmp, ignore_errors=True)
    print(json.dumps(out, indent=1))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("imports").set_defaults(fn=cmd_imports)
    p = sub.add_parser("smoke")
    p.add_argument("--index-root", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--splade-model", required=True)
    p.add_argument("--anchor", default=None)
    p.add_argument("--splade-tokenizer", default=None)
    p.add_argument("--query", default="social capital and civic participation")
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(fn=cmd_smoke)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
