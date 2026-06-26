#!/usr/bin/env python3
"""SEISMIC testbed — Path A backend shim: load a saved SEISMIC index and serve
the SPLADE leg from it (no JVM, in-process, like the tantivy/usearch legs).

This is the `SFU_SPLADE_BACKEND=seismic` adapter the docs name
(`04_BUILD_AND_GATHER.md`). It loads a saved `.index.seismic` ONCE per process
and serves `search(query, top_k) -> [(oaid, score)]` using the SAME query
encoder as the Qdrant/BMP paths (`lib.opensearch_retriever.encode_splade` +
models/splade_onnx_fp16), so SEISMIC vs Qdrant quality is attributable to
SEISMIC's approximation/pruning, not a different encoder.

Token-string queries: SEISMIC accepts the raw BERT subword tokens as the numpy
fixed-width-str array `seismic.get_seismic_string()` (U30), so this path is
INDEPENDENT of the Qdrant ingest's bert-vocab-id mapping — no id bookkeeping to
drift. The doc `id` stored at build time is the openalex_id (string), returned
verbatim — matches the Qdrant payload `oaid` field the parity harness joins on.

Serve-constant fidelity: top SPLADE_QUERY_TERMS terms, QUANT_SCALE not applied
to the query (SEISMIC takes raw float weights — the doc vectors were stored raw
float too, no QUANT, so the scorer is symmetric). matching the docs' identical-
compute guarantee where Qdrant also uses raw f32 queries.

Not wired into src/lib/thinclient/retriever.py yet — this is the standalone Path-A
shim for the persona parity eval (G2/G5) and the RAM/pruning probes (G3/G4).
Wiring into the live retriever is a Path-A-GO decision, not a P2 task.
"""
import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger("seismic_backend")

# Match the serving retriever's query-shape constants (src/lib/thinclient/retriever.py)
SPLADE_QUERY_TERMS = 64


class SeismicBackend:
    """In-process SEISMIC sparse-leg backend. Drop-in shape for a future
    `SFU_SPLADE_BACKEND=seismic` branch in ThinClientRetriever."""

    def __init__(self, index_path: str, splade_model_path: str = "models/splade_onnx_fp16"):
        import seismic
        self._seismic = seismic
        # seismic.save() appends '.index.seismic' to the path it's given, so the
        # on-disk file is <index_path>.index.seismic (see build_persona_seismic.py).
        fp = index_path
        if not fp.endswith(".index.seismic"):
            fp = f"{index_path}.index.seismic"
        if not os.path.exists(fp):
            # allow passing the full .index.seismic path directly
            fp = index_path if os.path.exists(index_path) else fp
        log.info("seismic: loading index %s", fp)
        self.index = seismic.SeismicIndex.load(fp)
        self.splade_model_path = splade_model_path
        self._string_dtype = seismic.get_seismic_string()
        log.info("seismic: loaded len=%d dim=%d nnz=%d (string dtype %s)",
                 self.index.len, self.index.dim, self.index.nnz, self._string_dtype)

    def encode_query(self, query: str) -> dict[str, float]:
        from lib.opensearch_retriever import encode_splade
        sparse = encode_splade(query, self.splade_model_path)
        if not sparse:
            return {}
        # Same top-N shaping as the serving retriever's _encode_splade_top.
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def search(self, query: str, top_k: int,
               query_cut: int | None = None,
               heap_factor: float = 0.8) -> list[tuple[str, float]]:
        """Return [(openalex_id, score)] for the top_k SPLADE matches.
        query_cut defaults to the number of query terms (use all) — SEISMIC's
        own MS MARCO best_configs use query_cut small, but recall-first means we
        evaluate the full top-64 query until G2 proves otherwise."""
        q = self.encode_query(query)
        if not q:
            return []
        tokens = list(q.keys())
        values = [float(v) for v in q.values()]
        qc = query_cut if query_cut is not None else len(tokens)
        qcomp = np.array(tokens, dtype=self._string_dtype)
        qvals = np.array(values, dtype=np.float32)
        res = self.index.search(
            query_id="q", query_components=qcomp, query_values=qvals,
            k=top_k, query_cut=qc, heap_factor=heap_factor)
        # search returns [(query_id, distance, doc_id), ...]
        return [(doc_id, float(dist)) for (_qid, dist, doc_id) in res]
