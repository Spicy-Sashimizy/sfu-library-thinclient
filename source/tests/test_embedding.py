"""Tests for the embedding module and embedding-based reranking."""

import pytest
from unittest.mock import patch, MagicMock

import numpy as np


class TestEmbeddingModule:
    """Unit tests for source/lib/embedding.py (mocked, no model download)."""

    def test_compute_similarity_empty_docs(self):
        from lib.embedding import compute_similarity
        result = compute_similarity("test query", [])
        assert result == []

    @staticmethod
    def _fake_batch(vectors: dict):
        """_embed_batch stand-in: known vectors, zeros for dummy pad rows."""
        calls = []

        def fwd(model, texts):
            calls.append(list(texts))
            rows = [vectors.get(t, np.zeros(3)) for t in texts]
            return np.asarray(rows, dtype=np.float32)
        return fwd, calls

    def test_compute_similarity_returns_scores(self):
        import lib.embedding as emb
        v = {"query": np.array([1.0, 0.0, 0.0]),
             "doc1": np.array([0.9, 0.1, 0.0]) / np.linalg.norm([0.9, 0.1, 0.0]),
             "doc2": np.array([0.0, 0.0, 1.0])}
        fwd, calls = self._fake_batch(v)
        with patch("lib.embedding._load_model", return_value=MagicMock()), \
                patch("lib.embedding._embed_batch", side_effect=fwd):
            scores = emb.compute_similarity("query", ["doc1", "doc2"])

        assert len(scores) == 2
        assert scores[0] > scores[1]
        assert all(len(c) == emb._EMBED_BATCH for c in calls)
        assert calls[0][:3] == ["query", "doc1", "doc2"]
        assert calls[0][3:] == [emb._PAD_TEXT] * (emb._EMBED_BATCH - 3)

    def test_encode_texts_chunks_into_fixed_batches(self):
        import lib.embedding as emb
        texts = [f"t{i}" for i in range(emb._EMBED_BATCH + 3)]
        v = {t: np.array([float(i), 1.0, 0.0]) for i, t in enumerate(texts)}
        fwd, calls = self._fake_batch(v)
        with patch("lib.embedding._load_model", return_value=MagicMock()), \
                patch("lib.embedding._embed_batch", side_effect=fwd):
            out = emb.encode_texts(texts)
        assert out.shape == (len(texts), 3)
        assert [len(c) for c in calls] == [emb._EMBED_BATCH, emb._EMBED_BATCH]
        assert out[-1][0] == float(len(texts) - 1)

    def test_encode_texts_failure_returns_none(self):
        with patch("lib.embedding._load_model", return_value=MagicMock()), \
                patch("lib.embedding._embed_batch", side_effect=RuntimeError("CUDA OOM")):
            from lib.embedding import encode_texts
            result = encode_texts(["test"])
        assert result is None


class TestRerankerWithEmbedding:
    """Tests for reranker.py's embedding integration."""

    def _make_doc(self, title="Test", creator="Author", date="2024",
                  doc_type="article", doi="10.1234/test",
                  availability="available", description=""):
        return {
            "title": title,
            "abstract": description,
            "authors": [creator] if creator else [],
            "date": date or "",
            "type": doc_type,
            "doi": doi or "",
            "is_oa": "available" in (availability or "").lower(),
        }

    def test_rerank_without_embedding(self):
        """Reranker works when embedding is disabled."""
        from lib.reranker import rerank_results
        docs = [self._make_doc(title=f"Doc {i}") for i in range(5)]
        result = rerank_results(docs, "test", limit=3, use_embedding=False)
        assert len(result) == 3

    def test_rerank_embedding_fallback(self):
        """Reranker falls back gracefully when embedding fails."""
        with patch("lib.reranker._compute_semantic_scores", return_value=None):
            from lib.reranker import rerank_results
            docs = [self._make_doc(title="Test Doc")]
            result = rerank_results(docs, "test", limit=1, use_embedding=True)
            assert len(result) == 1

    def test_rerank_with_embedding_scores(self):
        """Semantic scores influence ranking when available."""
        from lib.reranker import rerank_results

        doc_relevant = self._make_doc(
            title="History of Ancient Rome",
            date="2020",
            description="A comprehensive study of deep learning neural networks",
        )
        doc_title_match = self._make_doc(
            title="Deep Learning Survey",
            date="2020",
        )

        fake_scores = [0.95, 0.30]
        with patch("lib.reranker._compute_semantic_scores", return_value=fake_scores):
            result = rerank_results(
                [doc_relevant, doc_title_match],
                "deep learning",
                limit=2,
                use_embedding=True,
            )
        assert result[0]["title"] == "History of Ancient Rome"

    def test_rerank_semantic_scores_length_match(self):
        """Semantic scores list must match docs length."""
        from lib.reranker import rerank_results

        docs = [self._make_doc(title=f"Doc {i}") for i in range(3)]
        fake_scores = [0.5, 0.8, 0.3]
        with patch("lib.reranker._compute_semantic_scores", return_value=fake_scores):
            result = rerank_results(docs, "test", limit=3, use_embedding=True)
        assert len(result) == 3

    def test_extract_doc_text(self):
        """_extract_doc_text takes a normalized dict (output of _normalize_for_rerank)."""
        from lib.reranker import _extract_doc_text, _normalize_for_rerank
        raw = self._make_doc(title="Test Title", description="Test Description")
        norm = _normalize_for_rerank(raw)
        text = _extract_doc_text(norm)
        assert "Test Title" in text
        assert "Test Description" in text

    def test_extract_doc_text_no_description(self):
        from lib.reranker import _extract_doc_text, _normalize_for_rerank
        raw = self._make_doc(title="Only Title")
        norm = _normalize_for_rerank(raw)
        text = _extract_doc_text(norm)
        assert "Only Title" in text
