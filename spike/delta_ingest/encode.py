"""SPLADE document encoding for delta records — same math/model as the base.

`ensure_sparse` fills `sparse_field` on records that lack one, reusing stored
vectors from the ledger when the encoder text is unchanged, and batching the
rest through `lib.thinclient.doc_encoder` (TensorRT → PyTorch fallback). The
text is `DocRecord.encoder_text()` = f"{title} {abstract}".strip(), byte-
identical to what produced the 150M base vectors (retired splade_indexer).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .records import DocRecord

log = logging.getLogger("delta_ingest.encode")

Encoder = Callable[[list[str]], list[dict[str, float]]]


def make_encoder(backend: str = "auto", batch_size: int = 64, device: str = "auto") -> Encoder:
    """backend: auto|trt|pytorch; device: auto|cuda|cpu. The laptop profile
    runs device=cpu (fp32 PyTorch, a few docs/s per core); the server profile
    runs TRT on the GPU (~3.1k docs/s measured on the RTX 4070)."""
    from lib.thinclient.doc_encoder import make_doc_encoder
    enc = make_doc_encoder(backend=backend, batch_size=batch_size, device=device)
    return enc.encode_batch


def ensure_sparse(records: list[DocRecord], encoder: Encoder | None,
                  reusable: dict[str, dict[str, float]] | None = None,
                  batch_size: int = 64) -> dict:
    reusable = reusable or {}
    todo: list[DocRecord] = []
    reused = 0
    for r in records:
        if r.sparse_field:
            continue
        if r.id in reusable:
            r.sparse_field = reusable[r.id]
            reused += 1
        else:
            todo.append(r)
    t0 = time.perf_counter()
    encoded = 0
    if todo:
        if encoder is None:
            log.warning("%d records need encoding but no encoder given — they will be "
                        "invisible to the SPLADE leg until re-run with --encode", len(todo))
        else:
            for i in range(0, len(todo), batch_size):
                batch = todo[i:i + batch_size]
                vecs = encoder([r.encoder_text() for r in batch])
                for r, v in zip(batch, vecs):
                    r.sparse_field = v or None
                encoded += len(batch)
    dt = time.perf_counter() - t0
    return {"reused": reused, "encoded": encoded, "missing": len([r for r in records if not r.sparse_field]),
            "encode_seconds": round(dt, 3),
            "docs_per_s": round(encoded / dt, 1) if encoded and dt > 0 else None}
