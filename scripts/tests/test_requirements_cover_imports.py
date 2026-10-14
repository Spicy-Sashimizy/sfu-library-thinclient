"""Pins root requirements.txt to the third-party imports of the code.

Every third-party import of product code (source/ outside source/tests) must have a
requirement line, and every requirement line must correspond to an import in
source/ or in the non-evidence scripts/ dirs, or sit in an allowlist with a
reason. Evidence dirs (scripts/archive, scripts/experiments,
scripts/seismic_testbed) bring their own needs and are not scanned.

Lifecycle: harness
Doc: docs/REPRODUCIBILITY.md
"""

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = ("scripts/archive", "scripts/experiments", "scripts/seismic_testbed")

IMPORT_TO_DIST = {
    "mcp": "mcp",
    "requests": "requests",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "pyzotero": "pyzotero",
    "sentence_transformers": "sentence-transformers",
    "torch": "torch",
    "transformers": "transformers",
    "onnxruntime": "onnxruntime",
    "optimum": "optimum",
    "numpy": "numpy",
    "pytest": "pytest",
    "tantivy": "tantivy",
    "usearch": "usearch",
    "zstandard": "zstandard",
    "orjson": "orjson",
    "fastapi": "fastapi",
    "cryptography": "cryptography",
}

OPTIONAL_IMPORTS = {
    "seismic": "local patched fork wheel (spike/seismic_upstream), never a PyPI requirement line",
    "cudf": "optional GPU path in scripts/snapshot_downloader.py, not a pinned requirement",
    "cupy": "optional GPU path in scripts/snapshot_downloader.py, not a pinned requirement",
    "rmm": "optional GPU path in scripts/snapshot_downloader.py, not a pinned requirement",
}

REQUIREMENT_ALLOWLIST = {
    "pytest-asyncio": "pytest plugin, never imported by name",
    "brotli": "eval-only, scripts/experiments",
    "py3langid": "eval-only, scripts/experiments",
}


def _local_modules():
    names = set()
    names.update(p.name for p in REPO.iterdir() if p.is_dir())
    for root in ("source", "source/lib", "scripts", "spike"):
        base = REPO / root
        if base.is_dir():
            names.update(p.stem for p in base.iterdir())
    for p in (REPO / "scripts").rglob("*"):
        if p.is_dir() or p.suffix == ".py":
            names.add(p.stem)
    return names


def _imports(roots, skip):
    found = {}
    local = _local_modules()
    for root in roots:
        for path in (REPO / root).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if any(rel.startswith(s) for s in skip):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                else:
                    continue
                for mod in mods:
                    top = mod.split(".")[0]
                    if top in sys.stdlib_module_names or top in local:
                        continue
                    found.setdefault(top, f"{rel}:{node.lineno}")
    return found


def _requirement_dists():
    dists = {}
    for line in (REPO / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0].lower()
        dists[name] = line
    return dists


def test_every_src_import_has_a_requirement():
    src = {m: w for m, w in _imports(["source"], skip=("source/tests",)).items() if m not in OPTIONAL_IMPORTS}
    reqs = _requirement_dists()
    unmapped = sorted(m for m in src if m not in IMPORT_TO_DIST)
    uncovered = sorted(
        f"{m} -> {IMPORT_TO_DIST[m]} (first import {where})"
        for m, where in src.items()
        if m in IMPORT_TO_DIST and IMPORT_TO_DIST[m].lower() not in reqs
    )
    assert not unmapped, f"source/ imports missing from IMPORT_TO_DIST: {unmapped}"
    assert not uncovered, f"source/ imports with no requirements.txt line: {uncovered}"


def test_non_evidence_scripts_imports_are_covered_or_declared_optional():
    scripts = _imports(["scripts"], skip=EVIDENCE)
    reqs = _requirement_dists()
    offenders = sorted(
        f"{m} (first import {where})"
        for m, where in scripts.items()
        if m not in OPTIONAL_IMPORTS
        and not (m in IMPORT_TO_DIST and IMPORT_TO_DIST[m].lower() in reqs)
    )
    assert not offenders, f"scripts/ imports with no requirement or optional declaration: {offenders}"


def test_every_requirement_line_maps_to_a_live_import():
    live = set(_imports(["source", "scripts"], skip=("source/tests",) + EVIDENCE))
    live_dists = {IMPORT_TO_DIST[m].lower() for m in live if m in IMPORT_TO_DIST}
    stale = sorted(
        f"{name} ({line})"
        for name, line in _requirement_dists().items()
        if name not in live_dists and name not in REQUIREMENT_ALLOWLIST
    )
    assert not stale, f"requirements.txt lines whose import exists nowhere outside evidence dirs: {stale}"


def test_no_pypi_pin_for_the_local_seismic_fork():
    bad = sorted(n for n in _requirement_dists() if n.startswith("pyseismic"))
    assert not bad, f"requirements.txt must not pin the PyPI seismic (drops the fork patch): {bad}"
