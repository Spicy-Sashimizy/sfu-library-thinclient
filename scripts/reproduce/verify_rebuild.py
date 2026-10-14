#!/usr/bin/env python3
"""Serve check for a rebuilt index: real fused searches through the retriever.

Loads ``ThinClientRetriever`` on the rebuilt generation directory with the
SEISMIC shard manifest the rebuild wrote, runs a few queries through
``search_rrf`` with provenance, and reports per query how many hits came
back, which legs (BM25F, SPLADE) surfaced them, and whether the hits carry
title, year and abstract. PASS = every query returns hits, both legs
contribute on at least one query, every hit has a title, and no leg fell
back or failed.

Usage:

    set -a; . /var/tmp/duck_rebuild/serve.env; set +a
    PYTHONPATH=src .venv/bin/python3 scripts/reproduce/verify_rebuild.py [--query ...]

or let ``rebuild_from_openalex.py`` call it. Writes JSON to stdout.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_QUERIES = [
    "social capital and civic participation",
    "CRISPR gene editing off-target effects",
    "graph neural networks for molecule property prediction",
]
REQUIRED_ENV = ("SFU_THINCLIENT_INDEX_ROOT", "SFU_SEISMIC_SHARD_MANIFEST")


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(self.format(record))


def verify(env: dict[str, str] | None = None, queries: list[str] | None = None, top_k: int = 10) -> dict:
    if env:
        os.environ.update(env)
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        return {"status": "FAIL", "error": f"missing env {missing}", "queries": []}
    os.environ.setdefault("SFU_SPLADE_BACKEND", "seismic")
    os.environ.setdefault("SFU_SEISMIC_LOAD_MODE", "mmap")
    os.environ.setdefault("SFU_DENSE_LEG", "0")
    if str(REPO / "source") not in sys.path:
        sys.path.insert(0, str(REPO / "source"))
    collector = _Collect()
    logging.getLogger().addHandler(collector)
    from lib.thinclient.retriever import ThinClientRetriever

    root = os.environ["SFU_THINCLIENT_INDEX_ROOT"]
    t0 = time.perf_counter()
    r = ThinClientRetriever(index_root=root, remote_abstracts=False)
    out: dict = {"index_root": root, "shard_manifest": os.environ["SFU_SEISMIC_SHARD_MANIFEST"],
                 "construct_ms": round((time.perf_counter() - t0) * 1000, 1), "queries": [], "error": None}
    legs_seen: set[str] = set()
    try:
        for q in (queries or DEFAULT_QUERIES):
            ta = time.perf_counter()
            hits = r.search_rrf(q, top_k=top_k, with_provenance=True)
            tb = time.perf_counter()
            legs: dict[str, int] = {}
            for h in hits:
                for leg in (h.get("rrf_legs") or {}):
                    legs[leg] = legs.get(leg, 0) + 1
            legs_seen.update(legs)
            out["queries"].append({
                "q": q, "n_hits": len(hits), "wall_ms": round((tb - ta) * 1000, 1), "legs_hit_counts": legs,
                "n_with_title": sum(1 for h in hits if h.get("title")),
                "n_with_year": sum(1 for h in hits if h.get("year") not in (None, "", "None")),
                "n_with_abstract": sum(1 for h in hits if h.get("abstract")),
                "top3": [(h.get("openalex_id"), (h.get("title") or "")[:90], h.get("year")) for h in hits[:3]],
            })
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["n_sections_loaded"] = len(getattr(r, "_sections", {}) or {})
    out["seismic_backend_loaded"] = getattr(r, "_seismic", None) is not None
    fallback = [m for m in collector.records if "falling back" in m or "failed" in m]
    out["leg_fallback_warnings"] = fallback
    out["warnings"] = collector.records[:20]
    ok = (out["error"] is None and out["queries"] and all(q["n_hits"] > 0 for q in out["queries"])
          and {"bm25f", "splade"} <= legs_seen and all(q["n_with_title"] == q["n_hits"] for q in out["queries"])
          and out["seismic_backend_loaded"] and not fallback)
    out["status"] = "PASS" if ok else "FAIL"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--query", action="append", help="repeatable; default: three built-in queries")
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args(argv)
    res = verify(None, args.query, args.top_k)
    print(json.dumps(res, indent=1))
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
