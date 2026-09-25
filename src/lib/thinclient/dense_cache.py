"""Query-driven dense warm cache — the index that builds itself from queries.

Two-tier delta over the static usearch seed (design + lineage in
docs/DENSE_WARMCACHE_RESEARCH.md): SQLite is the sole durability point; the
in-RAM delta is searched by brute-force Hamming (popcount LUT) + exact int8
rescore, which sidesteps HNSW insert-order recall degradation entirely at
delta scale and merges with seed scores exactly (corpus-independent dot
products). A single background worker dedups, CPU-encodes surfaced docs in
small batches, and appends. Everything is bounded: queue, doc cap, one thread.

v2 levers, both default-inert (docs/DENSE_WARMCACHE_RESEARCH.md "Deferred to
v2"): `SFU_DENSE_DELTA_USEARCH_MIN` swaps the RAM brute force for a mutable
usearch b1 index once the delta passes a configurable row count, and
`SFU_DENSE_ENCODER_ONNX` swaps the torch encoder for an int8 ONNX export.
Folding the delta back into the seed lives in `dense_delta_merge.py`.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger("sfu_library_mcp")

DELTA_KEY_BASE = 1 << 40
ENCODE_BATCH = 32
QUEUE_MAX_DOCS = 2_000
DEFAULT_MAX_DOCS = 500_000
ANN_OVERFETCH = 4
ANN_EXPANSION_ADD = 128
ANN_EXPANSION_SEARCH = 128
ONNX_DEFAULT_DIR = "models/sfu-academic-embed-v5-onnx-int8"
ONNX_MAX_LEN = 256
_POPCNT = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None],
                        axis=1).sum(1).astype(np.uint8)

_SCHEMA = (
    "PRAGMA journal_mode=WAL;"
    "CREATE TABLE IF NOT EXISTS delta ("
    "  id TEXT PRIMARY KEY, key INTEGER UNIQUE, vec BLOB,"
    "  title TEXT, doi TEXT, year INTEGER, type TEXT, is_oa INTEGER,"
    "  added_at REAL);"
)


def _ann_threshold() -> int:
    raw = os.environ.get("SFU_DENSE_DELTA_USEARCH_MIN", "")
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("SFU_DENSE_DELTA_USEARCH_MIN=%r is not an integer; "
                       "keeping brute-force delta search", raw)
        return 0


class OnnxDenseEncoder:
    """int8 ONNX query/doc encoder for the v5 bi-encoder (CLS pool + L2 norm).

    Mirrors `sentence_transformers` for this checkpoint exactly: BERT forward,
    take token 0 of `last_hidden_state`, L2-normalize. Export + measured parity
    and latency: `scripts/experiments/export_dense_encoder_onnx_int8.py`.
    """

    def __init__(self, onnx_dir: str, tokenizer_dir: str,
                 intra_threads: int = 0, max_length: int = ONNX_MAX_LEN):
        d = Path(onnx_dir)
        model_file = d / "model_quantized.onnx"
        if not model_file.exists():
            model_file = d / "model.onnx"
        if not model_file.exists():
            raise FileNotFoundError(
                f"no model_quantized.onnx / model.onnx in {d} — build it with "
                "scripts/experiments/export_dense_encoder_onnx_int8.py")
        import onnxruntime as ort
        from transformers import AutoTokenizer

        opts = ort.SessionOptions()
        if intra_threads > 0:
            opts.intra_op_num_threads = intra_threads
            opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_file), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        tok_dir = d if (d / "tokenizer.json").exists() else Path(tokenizer_dir)
        self.tok = AutoTokenizer.from_pretrained(str(tok_dir))
        self.max_length = max_length

    def __call__(self, texts: list[str]) -> np.ndarray:
        enc = self.tok(list(texts), padding=True, truncation=True,
                       max_length=self.max_length, return_tensors="np")
        feed = {k: v.astype(np.int64) for k, v in enc.items()
                if k in self.inputs}
        out = np.asarray(self.session.run(None, feed)[0], dtype=np.float32)
        cls = out[:, 0, :] if out.ndim == 3 else out
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        return cls / np.maximum(norms, 1e-12)


def make_onnx_encoder(model_path: str):
    """Build the gated int8 ONNX encoder, or None when the gate is off.

    `SFU_DENSE_ENCODER_ONNX` is a literal-`1` gate (default OFF). An enabled
    gate whose export is unusable logs an error and returns None — the caller
    falls back to torch, which is slower but semantically identical.
    """
    if os.environ.get("SFU_DENSE_ENCODER_ONNX", "0") != "1":
        return None
    repo_root = Path(__file__).resolve().parents[3]
    onnx_dir = os.environ.get("SFU_DENSE_ENCODER_ONNX_PATH") or str(
        repo_root / ONNX_DEFAULT_DIR)
    try:
        threads = int(os.environ.get("SFU_DENSE_ENCODER_ONNX_THREADS", "0"))
    except ValueError:
        threads = 0
    try:
        enc = OnnxDenseEncoder(onnx_dir, model_path, intra_threads=threads)
    except Exception as exc:
        logger.error("SFU_DENSE_ENCODER_ONNX=1 but %s is unusable (%s); "
                     "falling back to the torch encoder", onnx_dir, exc)
        return None
    logger.info("dense warm cache: int8 ONNX encoder from %s", onnx_dir)
    return enc


class DenseWarmCache:
    """Usage-driven dense delta alongside the static seed index."""

    def __init__(self, dense_dir: Path, seed_ids: list[str],
                 model_path: str, dim: int = 384,
                 max_docs: int = DEFAULT_MAX_DOCS, encoder=None):
        self.dir = Path(dense_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.model_path = model_path
        self.dim = dim
        self.max_docs = max_docs
        self._encoder = encoder
        self._db = sqlite3.connect(str(self.dir / "delta.sqlite"),
                                   check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db_lock = threading.Lock()

        self._lock = threading.Lock()
        self._n = 0
        cap = 4096
        self._codes = np.zeros((cap, dim // 8), dtype=np.uint8)
        self._int8 = np.zeros((cap, dim), dtype=np.int8)
        self._ids: list[str] = []
        self._known: set[str] = set(seed_ids)
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX_DOCS)
        self._worker: threading.Thread | None = None
        self._closed = False
        self._ann = None
        self._ann_n = 0
        self._ann_min = _ann_threshold()
        self._onnx_checked = False
        self.stats = {"enqueued": 0, "encoded": 0, "dropped": 0, "errors": 0}

        rows = self._db.execute(
            "SELECT id, vec FROM delta ORDER BY key").fetchall()
        for doc_id, blob in rows:
            vec = np.frombuffer(blob, dtype=np.int8)
            if vec.shape[0] != dim:
                continue
            self._append_row(doc_id, vec)
        if rows:
            logger.info("dense warm cache: restored %d docs from delta.sqlite",
                        self._n)
        with self._lock:
            self._ann_sync_locked()


    def enqueue(self, docs: list[dict]) -> None:
        """Fire-and-forget: queue surfaced docs for background encoding.
        Never blocks a query — drops on overflow."""
        if self._closed or self._n >= self.max_docs:
            return
        fresh = [d for d in docs
                 if d.get("openalex_id") and d.get("title")
                 and d["openalex_id"] not in self._known]
        if not fresh:
            return
        self._ensure_worker()
        for d in fresh:
            try:
                self._queue.put_nowait(
                    {k: d.get(k) for k in ("openalex_id", "title", "abstract",
                                           "doi", "year", "type", "is_oa")})
                self.stats["enqueued"] += 1
            except queue.Full:
                self.stats["dropped"] += 1
                return

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            with self._lock:
                if self._worker is None or not self._worker.is_alive():
                    self._worker = threading.Thread(
                        target=self._run, daemon=True, name="dense-warmcache")
                    self._worker.start()

    def _encode(self, texts: list[str]) -> np.ndarray:
        if self._encoder is None and not self._onnx_checked:
            self._onnx_checked = True
            self._encoder = make_onnx_encoder(self.model_path)
        if self._encoder is not None:
            return np.asarray(self._encoder(texts), dtype=np.float32)
        from lib.opensearch_retriever import _get_dense_model
        model = _get_dense_model(self.model_path)
        return np.asarray(
            model.encode(texts, batch_size=ENCODE_BATCH,
                         normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32)

    def _run(self) -> None:
        while not self._closed:
            batch: list[dict] = []
            try:
                batch.append(self._queue.get(timeout=5))
            except queue.Empty:
                continue
            while len(batch) < ENCODE_BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            batch = list({d["openalex_id"]: d for d in batch
                          if d["openalex_id"] not in self._known}.values())
            if not batch or self._n >= self.max_docs:
                continue
            try:
                texts = [f"{d['title']} {d.get('abstract') or ''}"[:2000]
                         for d in batch]
                X = self._encode(texts)
                int8 = np.clip(np.round(X * 127.0), -127, 127).astype(np.int8)
                now = time.time()
                with self._db_lock:
                    for i, d in enumerate(batch):
                        self._db.execute(
                            "INSERT OR IGNORE INTO delta VALUES (?,?,?,?,?,?,?,?,?)",
                            (d["openalex_id"], DELTA_KEY_BASE + self._n + i,
                             int8[i].tobytes(), d["title"], d.get("doi") or "",
                             d.get("year"), d.get("type") or "",
                             int(bool(d.get("is_oa"))), now))
                    self._db.commit()
                with self._lock:
                    for i, d in enumerate(batch):
                        self._append_row_locked(d["openalex_id"], int8[i])
                self.stats["encoded"] += len(batch)
            except Exception as exc:
                self.stats["errors"] += 1
                logger.warning("dense warm cache encode batch failed: %s", exc)
                if self.stats["errors"] >= 5 and self.stats["encoded"] == 0:
                    logger.error("dense warm cache disabled (encoder unusable)")
                    self._closed = True


    def _append_row(self, doc_id: str, int8_vec: np.ndarray) -> None:
        with self._lock:
            self._append_row_locked(doc_id, int8_vec)

    def _append_row_locked(self, doc_id: str, int8_vec: np.ndarray) -> None:
        if self._n >= self._codes.shape[0]:
            self._codes = np.vstack([self._codes, np.zeros_like(self._codes)])
            self._int8 = np.vstack([self._int8, np.zeros_like(self._int8)])
        self._codes[self._n] = np.packbits(int8_vec > 0)
        self._int8[self._n] = int8_vec
        self._ids.append(doc_id)
        self._known.add(doc_id)
        self._n += 1
        self._ann_sync_locked()

    def _ann_sync_locked(self) -> None:
        """Bring the mutable usearch delta index level with the RAM arrays.

        No-op below `SFU_DENSE_DELTA_USEARCH_MIN` rows (0/unset = never, the
        v1 brute-force behaviour byte-for-byte). Any usearch failure disables
        the lever for the process: brute force stays correct, just slower.
        """
        if self._ann_min <= 0 or self._n < self._ann_min:
            return
        try:
            if self._ann is None:
                from usearch.index import Index
                self._ann = Index(ndim=self.dim, dtype="b1",
                                  metric="hamming",
                                  expansion_add=ANN_EXPANSION_ADD,
                                  expansion_search=ANN_EXPANSION_SEARCH)
                self._ann_n = 0
            if self._ann_n < self._n:
                self._ann.add(
                    np.arange(self._ann_n, self._n, dtype=np.uint64),
                    self._codes[self._ann_n:self._n])
                self._ann_n = self._n
        except Exception as exc:
            logger.warning("dense delta usearch index disabled (%s); "
                           "falling back to brute force", exc)
            self._ann, self._ann_n, self._ann_min = None, 0, 0


    def search(self, qbits: np.ndarray, q: np.ndarray,
               fetch: int) -> list[tuple[str, float]]:
        """Hamming candidates over the delta + exact int8 rescore.

        Candidates come from the RAM brute force (v1 default) or, above
        `SFU_DENSE_DELTA_USEARCH_MIN`, from the mutable usearch b1 index with
        `ANN_OVERFETCH`× over-fetch. Either way the returned scores are exact
        int8 dot products, so they stay directly comparable with the seed leg's.
        """
        with self._lock:
            n = self._n
            if n == 0:
                return []
            codes = self._codes[:n]
            int8 = self._int8[:n]
            ids = list(self._ids)
            ann = self._ann if self._ann_n == n else None
        take = min(fetch, n)
        cand = None
        if ann is not None:
            try:
                hits = ann.search(qbits.ravel(),
                                  min(n, max(take, take * ANN_OVERFETCH)))
                keys = np.asarray(hits.keys, dtype=np.int64).ravel()
                if keys.size:
                    cand = keys[keys < n]
            except Exception as exc:
                logger.warning("dense delta usearch search failed (%s); "
                               "brute force for this query", exc)
        if cand is None or cand.size == 0:
            dists = _POPCNT[np.bitwise_xor(codes, qbits.ravel())].sum(axis=1)
            cand = np.argpartition(dists, take - 1)[:take]
        scores = (int8[cand].astype(np.float32) / 127.0) @ q
        order = np.argsort(-scores)[:take]
        return [(ids[int(cand[i])], float(scores[i])) for i in order]

    def metadata_rows(self, ids: list[str]) -> dict[str, tuple]:
        """meta.sqlite-shaped rows for warm docs missing from the main meta DB:
        (id, title, doi, year, type, is_oa, section)."""
        out: dict[str, tuple] = {}
        want = [i for i in ids if i in self._known]
        if not want:
            return out
        with self._db_lock:
            for start in range(0, len(want), 500):
                chunk = want[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for r in self._db.execute(
                        f"SELECT id, title, doi, year, type, is_oa FROM delta "
                        f"WHERE id IN ({marks})", chunk):
                    out[r[0]] = (r[0], r[1], r[2], r[3], r[4], r[5], "warmcache")
        return out

    def info(self) -> dict:
        return {"docs": self._n, "max_docs": self.max_docs,
                "queue": self._queue.qsize(),
                "delta_engine": "usearch" if self._ann is not None else "brute",
                "delta_ann_min": self._ann_min, **self.stats}

    def close(self) -> None:
        self._closed = True
