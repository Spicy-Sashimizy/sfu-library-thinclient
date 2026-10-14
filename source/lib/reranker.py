"""Two-stage re-ranking for search results.

Scores documents on multiple signals and re-orders them to surface
the most useful results. Designed to run after the initial API ranking.
Handles raw OpenAlex works (``authorships``) and flat normalized docs via
_normalize_for_rerank.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path

from lib import speculative_rerank

logger = logging.getLogger("sfu_library_mcp")

_CURRENT_YEAR = datetime.now().year

_WEIGHTS_NO_EMBEDDING = {
    "title_relevance": 0.35,
    "recency": 0.20,
    "fulltext_available": 0.20,
    "type_match": 0.15,
    "completeness": 0.10,
}

_WEIGHTS_WITH_EMBEDDING = {
    "semantic_similarity": 0.35,
    "title_relevance": 0.15,
    "recency": 0.15,
    "fulltext_available": 0.15,
    "type_match": 0.10,
    "completeness": 0.10,
}


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase word tokens."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _normalize_for_rerank(doc: dict) -> dict:
    """Return a shape-stable view of a doc for scoring.

    Detects a raw OpenAlex work (``authorships``) vs a flat normalized doc
    (``normalize_work`` / thin-client / Europe PMC / S2 shape) and extracts:
      title, abstract, year (int|None), type, doi, authors (list), has_fulltext (bool)
    """
    if "authorships" in doc:
        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        year = doc.get("publication_year")
        doc_type = (doc.get("type") or "").lower()
        doi = doc.get("doi") or ""
        authors = [
            a["author"]["display_name"]
            for a in doc.get("authorships", [])
            if (a.get("author") or {}).get("display_name")
        ]
        oa = doc.get("open_access") or {}
        primary_loc = doc.get("primary_location") or {}
        has_fulltext = (
            bool(oa.get("is_oa"))
            or bool(primary_loc.get("pdf_url"))
            or bool(primary_loc.get("landing_page_url"))
        )
    else:
        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        date_str = doc.get("date") or ""
        year: int | None = None
        if date_str:
            try:
                year = int(str(date_str)[:4])
            except (ValueError, IndexError):
                pass
        doc_type = (doc.get("type") or "").lower()
        doi = doc.get("doi") or ""
        authors = doc.get("authors") or []
        has_fulltext = bool(doc.get("is_oa")) or bool(doc.get("oa_url"))

    return {
        "title": title,
        "abstract": abstract,
        "year": year,
        "type": doc_type,
        "doi": doi,
        "authors": authors,
        "has_fulltext": has_fulltext,
    }


def _score_title_relevance(norm: dict, query_tokens: set[str]) -> float:
    """Score 0-1 based on query term overlap with title."""
    title_tokens = _tokenize(norm["title"])
    if not query_tokens or not title_tokens:
        return 0.0
    overlap = query_tokens & title_tokens
    return len(overlap) / len(query_tokens)


def _score_recency(norm: dict) -> float:
    """Score 0-1 based on publication year. Current year = 1.0, decays 0.05/yr."""
    year = norm["year"]
    if year is None:
        return 0.0
    age = _CURRENT_YEAR - year
    return max(0.0, 1.0 - age * 0.05)


def _score_fulltext(norm: dict) -> float:
    """Score 1.0 if full text available, 0.0 otherwise."""
    return 1.0 if norm["has_fulltext"] else 0.0


def _score_type_match(norm: dict) -> float:
    """Score based on resource type. Peer-reviewed articles score highest."""
    doc_type = norm["type"]
    if doc_type in ("article", "journal_article", "review"):
        return 1.0
    elif doc_type in ("book", "book_chapter"):
        return 0.7
    elif doc_type in ("conference_proceeding", "dissertation"):
        return 0.6
    return 0.5


def _score_completeness(norm: dict) -> float:
    """Score 0-1 based on metadata completeness (DOI, authors, date)."""
    score = 0.0
    if norm["doi"]:
        score += 0.34
    if norm["authors"]:
        score += 0.33
    if norm["year"] is not None:
        score += 0.33
    return min(score, 1.0)


def _extract_doc_text(norm: dict) -> str:
    """Extract title + abstract text from a normalized doc for embedding."""
    return f"{norm['title']} {norm['abstract']}".strip()


def _compute_semantic_scores(query: str, docs: list[dict], model_path: str | None = None) -> list[float] | None:
    """Compute semantic similarity scores using local embedding model.

    Returns None if embedding model is unavailable (graceful fallback).
    """
    try:
        from lib.embedding import compute_similarity
    except ImportError:
        logger.debug("Embedding module not available, skipping semantic scoring")
        return None

    norms = [_normalize_for_rerank(doc) for doc in docs]
    doc_texts = [_extract_doc_text(n) for n in norms]
    if not any(doc_texts):
        return None

    spec = speculative_rerank.current()
    if spec is None:
        scores = compute_similarity(query, doc_texts, model_path)
    else:
        scores = spec.similarity(compute_similarity, query, doc_texts, model_path)
    if not scores:
        return None

    return scores


_EMBEDDING_RRF_K = 60


def _compute_rrf_scores(semantic_scores: list[float], n_docs: int) -> list[float]:
    """Fuse original retriever doc order with embedding rank via Reciprocal Rank Fusion.

    The retriever returns docs in relevance order, so the input position
    is itself a lexical-relevance signal. RRF combines two ranked lists:

        rrf(d) = 1 / (k + rank_lexical(d))  +  1 / (k + rank_embedding(d))

    Returns scores normalised to [0, 1] so they slot into the existing weighted
    sum in place of raw cosine similarity. Documents that rank well on either
    signal — or both — surface; neither ranker can fully suppress a doc the
    other rates highly. This is the property that rescues queries where one
    signal is blind (e.g. niche topics where embeddings fail but lexical hits).
    """
    embed_order = sorted(range(n_docs), key=lambda i: semantic_scores[i], reverse=True)
    embed_rank = [0] * n_docs
    for rank, idx in enumerate(embed_order):
        embed_rank[idx] = rank

    scores = [
        1.0 / (_EMBEDDING_RRF_K + i) + 1.0 / (_EMBEDDING_RRF_K + embed_rank[i])
        for i in range(n_docs)
    ]
    max_possible = 2.0 / _EMBEDDING_RRF_K
    return [s / max_possible for s in scores]


_FINETUNED_CE = Path(__file__).resolve().parents[2] / "models" / "sfu-cross-encoder-v1"
_CROSS_ENCODER_MODEL = (
    str(_FINETUNED_CE) if _FINETUNED_CE.exists()
    else "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
_ONNX_CE_DIR = Path(__file__).resolve().parents[2] / "models" / "sfu-cross-encoder-v1-onnx-int8"
_cross_encoder = None

_CE_CANDIDATE_POOL = 20

_CE_SEQ_LEN = 256
_CE_BATCH = 10
_CE_PAD_PAIR = ("", "")


class _OnnxCrossEncoder:
    """Serve-path wrapper for the dynamic-int8 ONNX cross-encoder export.

    predict() mirrors sentence_transformers.CrossEncoder.predict (list of
    (query, text) pairs -> 1-D logit array) so rerank_with_crossencoder is
    backend-agnostic. Tokenization params (truncation, max_length=256) match
    the export bench (export_ce_onnx_int8.py) that measured logit parity;
    padding is ``max_length`` so every call of a given batch size has one
    tensor shape (fixed-shape scoring, see _ce_score_pairs).
    """

    def __init__(self, model_dir: Path):
        import onnxruntime as ort
        from transformers import AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = os.cpu_count() or 1
        self._session = ort.InferenceSession(
            str(model_dir / "model_quantized.onnx"),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

    def predict(self, pairs, show_progress_bar=False):
        import numpy as np
        queries = [p[0] for p in pairs]
        texts = [p[1] for p in pairs]
        enc = self._tokenizer(
            queries, texts, padding="max_length", truncation=True,
            max_length=_CE_SEQ_LEN, return_tensors="np",
        )
        feed = {k: v.astype(np.int64) for k, v in enc.items() if k in self._input_names}
        logits = self._session.run(None, feed)[0]
        return np.asarray(logits).squeeze(-1)


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        use_onnx = (
            os.environ.get("SFU_CE_ONNX", "0") == "1"
            and (_ONNX_CE_DIR / "model_quantized.onnx").exists()
        )
        if use_onnx:
            try:
                from lib.hf_load_lock import HF_LOAD_LOCK
                with HF_LOAD_LOCK:
                    _cross_encoder = _OnnxCrossEncoder(_ONNX_CE_DIR)
                logger.info("CrossEncoder loaded (int8 ONNX): %s", _ONNX_CE_DIR)
                return _cross_encoder
            except Exception as e:
                logger.warning(
                    "int8 ONNX CrossEncoder unavailable (%s), falling back to torch CE", e)
        model_id = os.environ.get("SFU_CE_MODEL_PATH") or _CROSS_ENCODER_MODEL
        try:
            from lib.hf_load_lock import HF_LOAD_LOCK
            with HF_LOAD_LOCK:
                from sentence_transformers import CrossEncoder
                _cross_encoder = CrossEncoder(model_id)
            logger.info("CrossEncoder loaded: %s", model_id)
        except Exception as e:
            logger.warning("CrossEncoder unavailable (%s), skipping second-pass rerank", e)
            _cross_encoder = False
    return _cross_encoder if _cross_encoder is not False else None


def _is_st_cross_encoder(ce) -> bool:
    return type(ce).__module__.startswith("sentence_transformers") and hasattr(ce, "tokenizer")


def _ce_seq_len(ce) -> int:
    configured = getattr(ce, "max_seq_length", None) or _CE_SEQ_LEN
    return min(_CE_SEQ_LEN, int(configured))


def _ce_logits(model, enc: dict):
    """Encoder batched; on CPU the pooler + classifier head one row at a time.

    The head's GEMMs have M = batch rows; on CPU a small-M GEMM gives a row
    different bits depending on its position in the batch (measured
    2026-09-25 at batch 10: rows 8-9 differ from row 0 by 9.5e-7). Running
    the head on a (1, hidden) slice per row makes every row take the same
    path. On CUDA the batched head measured bit-identical at the fixed shape
    and the per-row loop cost ~10 ms per call, so CUDA runs the plain
    forward. Architectures without a BERT-style ``pooler`` + ``classifier``
    head run the plain forward (both serving CEs are BERT).
    """
    import torch
    base = getattr(model, getattr(model, "base_model_prefix", ""), None)
    pooler = getattr(base, "pooler", None) if base is not None else None
    classifier = getattr(model, "classifier", None)
    if pooler is None or classifier is None or model.device.type != "cpu":
        return model(**enc).logits
    hidden = base(**enc).last_hidden_state
    dropout = getattr(model, "dropout", None) or (lambda x: x)
    rows = [classifier(dropout(pooler(hidden[i:i + 1, :1].contiguous())))
            for i in range(hidden.shape[0])]
    return torch.cat(rows, dim=0)


def _ce_forward(ce, pairs: list[tuple]) -> list[float]:
    """Score exactly one fixed-shape batch of pairs.

    sentence-transformers CrossEncoder: tokenize with ``padding="max_length"``
    to _ce_seq_len and run the HF model directly (``predict`` would pad to the
    batch's longest pair). Any other backend (int8 ONNX wrapper, test fakes)
    is called through ``predict``; the ONNX wrapper pads to max_length itself.
    """
    if not _is_st_cross_encoder(ce):
        return [float(x) for x in ce.predict(pairs, show_progress_bar=False).tolist()]
    import torch
    model = ce.model
    if model.training:
        model.eval()
    enc = ce.tokenizer(
        [p[0] for p in pairs], [p[1] for p in pairs],
        padding="max_length", truncation="longest_first",
        max_length=_ce_seq_len(ce), return_tensors="pt",
    )
    enc = {k: v.to(model.device) for k, v in enc.items()}
    with torch.inference_mode():
        logits = _ce_logits(model, enc)
        act = getattr(ce, "activation_fn", None) or getattr(ce, "default_activation_function", None)
        if act is not None:
            logits = act(logits)
        if logits.ndim > 1 and logits.shape[-1] == 1:
            logits = logits.squeeze(-1)
    return [float(x) for x in logits.float().cpu().tolist()]


def _ce_score_pairs(ce, pairs: list[tuple]) -> list[float]:
    """Fixed-shape CE scoring: the only way the serve path calls the CE.

    Pairs are cut into chunks of _CE_BATCH; a short chunk is filled with
    _CE_PAD_PAIR rows whose scores are discarded, so every forward pass is one
    (_CE_BATCH, _ce_seq_len) tensor and a pair's score does not depend on the
    other pairs or on how many there are (docs/CODE_INVARIANTS.md,
    "Fixed-shape scoring").
    """
    scores: list[float] = []
    for start in range(0, len(pairs), _CE_BATCH):
        chunk = list(pairs[start:start + _CE_BATCH])
        n = len(chunk)
        chunk.extend([_CE_PAD_PAIR] * (_CE_BATCH - n))
        out = _ce_forward(ce, chunk)
        if len(out) != _CE_BATCH:
            raise ValueError(f"cross-encoder returned {len(out)} scores for {_CE_BATCH} pairs")
        scores.extend(out[:n])
    return scores


def rerank_with_crossencoder(docs: list[dict], query: str, limit: int) -> list[dict]:
    """Second-pass reranker: score top candidates with a cross-encoder.

    Runs only on the top _CE_CANDIDATE_POOL inputs to bound latency (~50-100ms on
    CPU). For this to be effective the caller must pass a pool wider than `limit`
    (see _maybe_rerank, item #4) — otherwise the CE only ever re-scores `limit`
    docs and can't pull a better doc up from rank 11-20.
    Falls back silently to `docs[:limit]` if the model is unavailable or errors.
    """
    ce = _get_cross_encoder()
    if ce is None:
        return docs[:limit]

    candidates = docs[:_CE_CANDIDATE_POOL]
    norms = [_normalize_for_rerank(d) for d in candidates]
    texts = [f"{n['title']} {n['abstract']}".strip() or n["title"] for n in norms]
    pairs = [(query, t) for t in texts]

    try:
        spec = speculative_rerank.current()
        if spec is None:
            scores = _ce_score_pairs(ce, pairs)
        else:
            scores = spec.ce_scores(ce, pairs, lambda sub: _ce_score_pairs(ce, sub))
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        result = [d for _, d in ranked[:limit]]
        logger.info("crossencoder: scored %d candidates -> %d results", len(candidates), len(result))
        return result
    except Exception as e:
        logger.warning("CrossEncoder scoring failed (%s), using pre-CE order", e)
        return docs[:limit]


def rerank_results(
    docs: list[dict],
    query: str,
    limit: int,
    use_embedding: bool = True,
    use_rrf: bool = False,
    embedding_model_path: str | None = None,
) -> list[dict]:
    """Re-rank search results using weighted multi-signal scoring.

    Args:
        docs: List of document dicts (flat normalized shape), in the
            retriever's relevance-derived order (used as the lexical signal
            for RRF).
        query: The original search query for title relevance scoring.
        limit: Maximum number of results to return.
        use_embedding: Whether to use local embedding model for semantic scoring.
        use_rrf: Whether to fuse original doc order with embedding rank via
            Reciprocal Rank Fusion. Replaces raw cosine in the semantic weight
            slot. No-op when use_embedding is False or no embedding scores
            could be computed.
        embedding_model_path: Custom path to embedding model (None = default).

    Returns:
        Re-ranked list of docs, sorted by composite score descending.
    """
    if not docs:
        return []

    query_tokens = _tokenize(query)

    semantic_scores = None
    if use_embedding:
        semantic_scores = _compute_semantic_scores(query, docs, embedding_model_path)
        if semantic_scores:
            logger.debug("Semantic reranking active (%d docs scored)", len(semantic_scores))

    semantic_signal = semantic_scores
    if use_rrf and semantic_scores:
        semantic_signal = _compute_rrf_scores(semantic_scores, len(docs))
        logger.debug("RRF fusion active (k=%d)", _EMBEDDING_RRF_K)

    weights = _WEIGHTS_WITH_EMBEDDING if semantic_signal else _WEIGHTS_NO_EMBEDDING

    scored: list[tuple[float, int, dict]] = []
    for idx, doc in enumerate(docs):
        norm = _normalize_for_rerank(doc)
        title_score = _score_title_relevance(norm, query_tokens)
        recency_score = _score_recency(norm)
        fulltext_score = _score_fulltext(norm)
        type_score = _score_type_match(norm)
        completeness_score = _score_completeness(norm)

        composite = (
            weights["title_relevance"] * title_score
            + weights["recency"] * recency_score
            + weights["fulltext_available"] * fulltext_score
            + weights["type_match"] * type_score
            + weights["completeness"] * completeness_score
        )

        if semantic_signal:
            composite += weights["semantic_similarity"] * semantic_signal[idx]

        scored.append((composite, -idx, doc))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    result = [doc for _, _, doc in scored[:limit]]
    logger.info("rerank: rrf=%s embed=%s docs=%d -> %d", use_rrf, bool(semantic_scores), len(docs), limit)
    return result
