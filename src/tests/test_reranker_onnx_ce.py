"""Tests for the int8 ONNX cross-encoder serve-path wiring (SFU_CE_ONNX).

The ONNX backend is OPT-IN (SFU_CE_ONNX=1): at the serve shape (batch of 20)
torch v1 measured 11.8 ms vs int8 ONNX 52 ms, so torch stays the default —
see data/eval_results/ce_v1_inversion_check_20260819_*.json. These tests
assert WIRING invariants (backend selection, fallback, faithful export), not
model semantics: the fine-tuned v1's relevance behavior is a model question,
measured separately (scripts/archive/demo_dependability/check_ce_direction.py).
"""

import pytest

import lib.reranker as reranker
from lib.reranker import _ONNX_CE_DIR, _OnnxCrossEncoder, rerank_with_crossencoder

_ONNX_PRESENT = (_ONNX_CE_DIR / "model_quantized.onnx").exists()

PAIRS = [
    ("transformer models for protein structure prediction",
     "AlphaFold2 attention-based architecture for predicting 3D protein folds from sequence."),
    ("transformer models for protein structure prediction",
     "Longitudinal cohort study linking socioeconomic status to depression in teens."),
    ("carbon capture using metal organic frameworks",
     "Porous MOFs with high CO2 uptake and selectivity for post-combustion capture."),
    ("carbon capture using metal organic frameworks",
     "Cross-lingual pretraining and back-translation for under-resourced NMT."),
    ("quantum error correction surface codes",
     "Threshold theorems and decoding of topological surface codes under noise."),
    ("quantum error correction surface codes",
     "Genome-wide profiling of Cas9 cleavage at mismatched target sites."),
]


@pytest.fixture(autouse=True)
def _reset_ce_singleton(monkeypatch):
    """Each test gets a fresh lazy-load; restore afterwards so other test
    modules don't inherit a backend this module selected."""
    monkeypatch.setattr(reranker, "_cross_encoder", None)
    yield
    reranker._cross_encoder = None


@pytest.mark.skipif(not _ONNX_PRESENT, reason="int8 ONNX CE export not present")
class TestOnnxWrapper:
    def test_predict_shape_and_finiteness(self):
        import numpy as np
        ce = _OnnxCrossEncoder(_ONNX_CE_DIR)
        scores = ce.predict(PAIRS)
        assert scores.shape == (len(PAIRS),)
        assert np.all(np.isfinite(scores))

    def test_single_pair_squeezes_to_1d(self):
        ce = _OnnxCrossEncoder(_ONNX_CE_DIR)
        scores = ce.predict(PAIRS[:1])
        assert scores.shape == (1,)

    def test_ordering_parity_with_torch_ce(self):
        """The export must be faithful: full-order agreement with the torch CE
        on the same model (export bench: r=0.994 / top-half Jaccard 1.0)."""
        import numpy as np
        st = pytest.importorskip("sentence_transformers")
        onnx_scores = _OnnxCrossEncoder(_ONNX_CE_DIR).predict(PAIRS)
        torch_ce = st.CrossEncoder(reranker._CROSS_ENCODER_MODEL)
        torch_scores = torch_ce.predict(PAIRS, show_progress_bar=False)
        assert list(np.argsort(-onnx_scores)) == list(np.argsort(-torch_scores))


@pytest.mark.skipif(not _ONNX_PRESENT, reason="int8 ONNX CE export not present")
class TestBackendSelection:
    def test_default_selects_torch(self, monkeypatch):
        pytest.importorskip("sentence_transformers")
        monkeypatch.delenv("SFU_CE_ONNX", raising=False)
        ce = reranker._get_cross_encoder()
        assert ce is not None
        assert not isinstance(ce, _OnnxCrossEncoder)

    def test_env_one_selects_onnx(self, monkeypatch):
        monkeypatch.setenv("SFU_CE_ONNX", "1")
        assert isinstance(reranker._get_cross_encoder(), _OnnxCrossEncoder)

    def test_env_zero_selects_torch(self, monkeypatch):
        pytest.importorskip("sentence_transformers")
        monkeypatch.setenv("SFU_CE_ONNX", "0")
        ce = reranker._get_cross_encoder()
        assert ce is not None
        assert not isinstance(ce, _OnnxCrossEncoder)

    def test_missing_export_falls_back_to_torch(self, monkeypatch, tmp_path):
        pytest.importorskip("sentence_transformers")
        monkeypatch.setenv("SFU_CE_ONNX", "1")
        monkeypatch.setattr(reranker, "_ONNX_CE_DIR", tmp_path / "nope")
        ce = reranker._get_cross_encoder()
        assert ce is not None
        assert not isinstance(ce, _OnnxCrossEncoder)

    def test_model_path_env_overrides_torch_checkpoint(self, monkeypatch):
        """SFU_CE_MODEL_PATH is the one-env flip for the v1-vs-base decision."""
        st = pytest.importorskip("sentence_transformers")
        alt = reranker._ONNX_CE_DIR.parent / "sfu-cross-encoder-baseline"
        if not alt.exists():
            pytest.skip("baseline CE checkpoint not present")
        monkeypatch.delenv("SFU_CE_ONNX", raising=False)
        monkeypatch.setenv("SFU_CE_MODEL_PATH", str(alt))
        ce = reranker._get_cross_encoder()
        assert isinstance(ce, st.CrossEncoder)
        name_or_path = getattr(getattr(ce, "model", None), "name_or_path", "") or \
            getattr(ce, "model_name_or_path", "")
        assert "sfu-cross-encoder-baseline" in str(name_or_path)


@pytest.mark.skipif(not _ONNX_PRESENT, reason="int8 ONNX CE export not present")
def test_rerank_with_crossencoder_backend_equivalence(monkeypatch):
    """The real rerank entrypoint must return the SAME ordering under both
    backends (faithful export at the serve call shape)."""
    pytest.importorskip("sentence_transformers")

    def flat(title, abstract):
        return {"title": title, "abstract": abstract, "authorships": [],
                "publication_year": 2024, "type": "article"}

    docs = [flat(f"Doc {i}", d) for i, (_, d) in enumerate(PAIRS)]
    query = "quantum error correction surface codes"

    monkeypatch.setenv("SFU_CE_ONNX", "1")
    out_onnx = rerank_with_crossencoder(list(docs), query, limit=6)
    assert isinstance(reranker._cross_encoder, _OnnxCrossEncoder)

    reranker._cross_encoder = None
    monkeypatch.setenv("SFU_CE_ONNX", "0")
    out_torch = rerank_with_crossencoder(list(docs), query, limit=6)
    assert not isinstance(reranker._cross_encoder, _OnnxCrossEncoder)

    assert [d["title"] for d in out_onnx] == [d["title"] for d in out_torch]
