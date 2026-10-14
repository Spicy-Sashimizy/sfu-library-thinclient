"""Local embedding model for semantic reranking.

Loads a sentence-transformer model (off-the-shelf or fine-tuned) and provides
embedding + cosine similarity scoring (``encode_texts``, ``compute_similarity``)
for the reranker's embedding stage.
"""

import logging
import math
from pathlib import Path

import numpy as np

logger = logging.getLogger("sfu_library_mcp")

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_FIXED_SEQ_LEN = 256
_EMBED_BATCH = 11
_PAD_TEXT = ""

_model = None
_model_name = None


def _resolve_target(model_path: str | None) -> str:
    """Resolve the model target, surviving stale absolute paths.

    A configured absolute path that doesn't exist (e.g. an env var baked from
    another machine/container — the /workspaces/sfu-library-mcp-training case,
    2026-07-18) falls back to the repo-local copy of the same-named model under
    models/ when present, so a portable deploy (DO droplet) keeps serving the
    fine-tuned model instead of silently degrading the embed leg.
    """
    target = model_path or _DEFAULT_MODEL
    p = Path(target)
    if target.startswith("/") and not p.exists():
        local = Path(__file__).resolve().parents[2] / "models" / p.name
        if local.is_dir():
            logger.warning(
                "Embedding model path %s not found; using repo-local %s",
                target, local)
            return str(local)
    return target


def _load_model(model_path: str | None = None):
    """Load a sentence-transformer model, caching it as a module-level singleton."""
    global _model, _model_name

    target = _resolve_target(model_path)
    if _model is not None and _model_name == target:
        return _model

    try:
        from lib.hf_load_lock import HF_LOAD_LOCK
        logger.info("Loading embedding model: %s", target)
        with HF_LOAD_LOCK:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(target)
        _model_name = target
        logger.info("Embedding model loaded (%s)", target)
        return _model
    except Exception as e:
        logger.error("Failed to load embedding model '%s': %s", target, e)
        _model = None
        _model_name = None
        return None


def _seq_len(model) -> int:
    """The constant padded length: min(_FIXED_SEQ_LEN, the model's max_seq_length)."""
    configured = getattr(model, "max_seq_length", None) or _FIXED_SEQ_LEN
    return min(_FIXED_SEQ_LEN, int(configured))


def _embed_batch(model, texts: list[str]) -> np.ndarray:
    """Embed exactly one fixed-shape batch: (len(texts), _seq_len(model)) tokens.

    Tokenizes with ``padding="max_length"`` so the forward pass always sees the
    same tensor shape, then L2-normalizes each row. Returns float32 (N, D).
    """
    import torch
    if getattr(model, "training", False):
        model.eval()
    enc = model.tokenizer(
        list(texts), padding="max_length", truncation="longest_first",
        max_length=_seq_len(model), return_tensors="pt",
    )
    features = {k: v.to(model.device) for k, v in enc.items()}
    with torch.inference_mode():
        emb = model.forward(features)["sentence_embedding"]
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
    return emb.float().cpu().numpy()


def encode_texts(texts: list[str], model_path: str | None = None) -> np.ndarray | None:
    """Encode a list of texts into normalized embedding vectors, fixed-shape.

    Every forward pass is one (_EMBED_BATCH, _seq_len) batch: texts are cut into
    chunks of _EMBED_BATCH and a short chunk is filled with _PAD_TEXT rows whose
    outputs are discarded. A text's vector therefore does not depend on which
    other texts, or how many, were encoded with it (docs/CODE_INVARIANTS.md,
    "Fixed-shape scoring").

    Returns an (N, D) numpy array of unit-length embeddings, or None on failure.
    """
    model = _load_model(model_path)
    if model is None:
        return None

    try:
        rows = []
        for start in range(0, len(texts), _EMBED_BATCH):
            chunk = list(texts[start:start + _EMBED_BATCH])
            n = len(chunk)
            chunk.extend([_PAD_TEXT] * (_EMBED_BATCH - n))
            rows.append(_embed_batch(model, chunk)[:n])
        if not rows:
            return np.zeros((0, 0), dtype=np.float32)
        return np.concatenate(rows, axis=0)
    except Exception as e:
        logger.error("Embedding encode failed: %s", e)
        return None


def _cosine(doc_emb: np.ndarray, query_emb: np.ndarray) -> float:
    """Dot product of two unit vectors, exactly rounded (order-independent)."""
    return math.fsum((doc_emb.astype(np.float64) * query_emb.astype(np.float64)).tolist())


def compute_similarity(query: str, documents: list[str], model_path: str | None = None) -> list[float]:
    """Compute cosine similarity between a query and a list of documents.

    Returns a list of similarity scores (0.0-1.0), one per document.
    Returns empty list on failure. Each score is a pure function of
    (query, document, model): fixed-shape encoding plus an exactly rounded dot
    product, so it is bit-identical whatever else is in ``documents``.
    """
    if not documents:
        return []

    texts = [query] + documents
    embeddings = encode_texts(texts, model_path)
    if embeddings is None or len(embeddings) != len(texts):
        return []

    query_emb = embeddings[0]
    return [max(0.0, _cosine(d, query_emb)) for d in embeddings[1:]]
