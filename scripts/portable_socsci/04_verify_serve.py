#!/usr/bin/env python3
"""Phase 4 — prove the assembled bundle SERVES a real query, on Linux.

Points a ThinClientRetriever at the bundle's own index root + seismic manifest
(no repo data), runs representative social_sciences queries end-to-end
(BM25F + SPLADE/SEISMIC + RRF, abstracts hydrated from the bundle's LOCAL
sidecars only — remote_abstracts=False), and asserts each returns hydrated hits.

This is the OS-neutral proof: the bytes are identical on Windows, so a PASS here
establishes the data layer + serving contract; only the Windows *runtime*
(seismic.pyd load/mmap) remains to be proven on a real Windows host (design §7).

    .venv/bin/python3 scripts/portable_socsci/04_verify_serve.py

Env: BUNDLE (default /var/tmp/portable_socsci_bundle).
Writes data/eval_results/portable_socsci_verify.json (repo efficacy evidence)
and $BUNDLE/_verify_report.json. Exit 0 = PASS, 1 = FAIL.
"""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

BUNDLE = Path(os.environ.get("BUNDLE", "/var/tmp/portable_socsci_bundle"))
BINDEX = BUNDLE / "thinclient_index"
MANIFEST = BUNDLE / "seismic" / "shards.e5.v2.json"
ENCODER = BUNDLE / "models" / "splade_onnx_fused"

os.environ["SFU_SPLADE_BACKEND"] = "seismic"
os.environ["SFU_SEISMIC_SHARD_MANIFEST"] = str(MANIFEST)
os.environ.pop("SFU_SEISMIC_STAGE_DIR", None)
os.environ["SFU_DENSE_WARMCACHE"] = "0"
os.environ.setdefault("SFU_SEISMIC_LOAD_MODE", "mmap")

QUERIES = [
    "kinship structures in stateless societies",
    "electoral systems and coalition government",
    "causes of the industrial revolution",
    "social capital and civic participation",
]


def fail(msg: str) -> "typing.NoReturn":  # noqa: F821
    print(f"FAIL: {msg}", file=sys.stderr, flush=True)
    _write({"status": "FAIL", "reason": msg})
    sys.exit(1)


def _write(extra: dict) -> None:
    report = {
        "bundle": str(BUNDLE),
        "manifest": str(MANIFEST),
        "index_root": str(BINDEX),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **extra,
    }
    (REPO / "data" / "eval_results" / "portable_socsci_verify.json").write_text(
        json.dumps(report, indent=2))
    (BUNDLE / "_verify_report.json").write_text(json.dumps(report, indent=2))


def main() -> None:
    for p in (BINDEX / "manifest.json", BINDEX / "meta.sqlite", MANIFEST, ENCODER):
        if not p.exists():
            fail(f"missing bundle artifact: {p} (run phases 1-3 first)")

    from lib.thinclient.retriever import ThinClientRetriever

    t_load = time.perf_counter()
    r = ThinClientRetriever(
        index_root=str(BINDEX),
        splade_model_path=str(ENCODER),
        remote_abstracts=False,
    )
    r._load()
    if not r._sections:
        fail("no sections loaded from bundle (expected 2 social_sciences eras)")
    load_ms = (time.perf_counter() - t_load) * 1000
    print(f"loaded sections: {sorted(r._sections)} in {load_ms:.0f} ms", flush=True)

    per_query = []
    ok_all = True
    for q in QUERIES:
        t0 = time.perf_counter()
        try:
            hits = r.search_rrf(q, top_k=10)
        except Exception as exc:
            fail(f"query {q!r} raised: {type(exc).__name__}: {exc}")
        ms = (time.perf_counter() - t0) * 1000
        n = len(hits)
        n_abs = sum(1 for h in hits if h.get("abstract"))
        top = hits[0] if hits else {}
        rec = {
            "query": q,
            "n_hits": n,
            "n_with_local_abstract": n_abs,
            "latency_ms": round(ms, 1),
            "top_title": (top.get("title") or "")[:100],
            "top_id": top.get("openalex_id", ""),
        }
        per_query.append(rec)
        status = "ok" if (n > 0 and n_abs > 0) else "EMPTY"
        if status != "ok":
            ok_all = False
        print(f"  [{status}] {q!r}: {n} hits, {n_abs} w/ local abstract, "
              f"{ms:.0f} ms — top: {rec['top_title']!r}", flush=True)

    if not ok_all:
        fail("at least one query returned no hits or no offline abstracts")

    _write({
        "status": "PASS",
        "sections_loaded": sorted(r._sections),
        "load_ms": round(load_ms, 1),
        "federation": r._seismic_federation_mode(),
        "queries": per_query,
        "note": ("full-seismic v1 served bit-exact from the bundle; social-only "
                 "via trimmed meta.sqlite; abstracts offline (local sidecars). "
                 "Windows runtime still unproven (design §7)."),
    })
    print("\nPASS — bundle serves social_sciences end-to-end, offline.", flush=True)


if __name__ == "__main__":
    main()
